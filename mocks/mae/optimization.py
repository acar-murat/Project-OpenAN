"""Optimisation module of the mock MAE RAN Agent: complaint work orders, as the A2A-T client plugin uses them.

The HQ ``a2a-client-connector`` plugin (docs/henan-demo.md, "A2A-T plugin contract") talks to
the RAN adapter in three ways, all served by the mock MAE:

* ``a2a_send_task`` with ``{"issueId", "objectId", "problemType", "rat"}`` as a JSON block,
  ``key: value`` lines, a DataPart or ``metadata.taskParameters``: creates (or, for a known
  ``issueId``, re-attaches to) a work order and returns ``serviceManagement.RanOptimizationResult``.
* ``a2a_query_result``: ``GET /ops/omc/status`` and ``GET /ops/omc/advice`` by ``issueId``.
  Empty lists mean "no result yet" (the plugin then creates a task).
* ``a2a_find_work_order`` reads a local ledger; ``work_orders.json`` here has the same shape and
  can be copied to the plugin's ``config/work-orders.json``.

Parameters are validated strictly, with the Chinese phrases the plugin looks for to ask the user
for missing input (``缺少必选参数``, ``取值无效``, ``必须是小区 CGI``, ``未解析出任务参数``). Results are
deterministic and illustrative; nothing reaches a real OMC.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

LEDGER_FILE = Path(__file__).with_name("work_orders.json")

#: Cell CGI: MCC-MNC-(gNB|eNB) id-cell id, e.g. 460-00-5267578-0.
CGI_PATTERN = re.compile(r"^\d{3}-\d{2,3}-\d{1,10}-\d{1,5}$")
RATS = ("NR", "LTE")

#: OMC standard problem codes the mock knows, with the root cause and advice it reports.
PROBLEM_TYPES: dict[str, dict[str, Any]] = {
    "UP_LOW_THROUGHPUT": {
        "rootCause": "上行干扰抬升，PUSCH SINR 偏低 (uplink interference raises the noise floor)",
        "advice": [("PuschTargetSinr", "10", "13", "提升上行目标 SINR"),
                   ("UlSchedulerMode", "PF", "MAX_CI", "高干扰时段改用 MAX_CI 调度")],
    },
    "DL_LOW_THROUGHPUT": {
        "rootCause": "下行 MCS 受限，RSRP 弱覆盖 (weak coverage limits downlink MCS)",
        "advice": [("ElectricalTilt", "6", "4", "减小下倾角扩大覆盖"),
                   ("ReferenceSignalPwr", "15.2", "18.2", "提升参考信号功率")],
    },
    "NR_VINR_UL_PACKET_LOSS": {
        "rootCause": "VoNR 上行 RLC 重传超限 (uplink RLC retransmissions exceed the limit)",
        "advice": [("UlRlcMaxRetxThreshold", "8", "16", "放宽上行 RLC 最大重传次数"),
                   ("VoiceUlBundling", "OFF", "ON", "开启语音上行 TTI bundling")],
    },
    "WEAK_COVERAGE": {
        "rootCause": "小区边缘 RSRP 低于 -110 dBm (cell-edge RSRP below -110 dBm)",
        "advice": [("ElectricalTilt", "8", "5", "减小下倾角"), ("MaxTxPower", "43", "46", "提升发射功率")],
    },
    "HIGH_INTERFERENCE": {
        "rootCause": "邻区同频干扰 (co-channel interference from neighbour cells)",
        "advice": [("PciMod3Conflict", "YES", "NO", "调整 PCI 消除模三冲突"),
                   ("IcicSwitch", "OFF", "ON", "开启小区间干扰协调")],
    },
    "CALL_DROP": {
        "rootCause": "切换门限设置不当导致掉话 (handover thresholds cause late handovers)",
        "advice": [("A3Offset", "3", "2", "降低 A3 偏置，提前切换"), ("TimeToTrigger", "320", "256", "缩短触发时间")],
    },
}

MISSING = "缺少必选参数"
INVALID = "取值无效"
UNPARSED = "未解析出任务参数"
CGI_HINT = "必须是小区 CGI（MCC-MNC-基站ID-小区ID，例如 460-00-5267578-0）"

_KEY_VALUE = re.compile(r"^\s*[\"']?([A-Za-z][\w-]*)[\"']?\s*[:：=]\s*[\"']?(.*?)[\"']?\s*,?\s*$")


class WorkOrderError(ValueError):
    """The request cannot become a work order; the message carries the plugin's marker phrases."""


def parse_parameters(text: str) -> dict[str, Any]:
    """Read parameters from a JSON object (optionally fenced) or ``key: value`` lines."""
    stripped = text.strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", stripped, re.DOTALL)
    candidate = fenced.group(1) if fenced else stripped
    start, end = candidate.find("{"), candidate.rfind("}")
    if 0 <= start < end:
        try:
            value = json.loads(candidate[start : end + 1])
            if isinstance(value, dict):
                return value
        except ValueError:
            pass
    params = {}
    for line in candidate.splitlines():
        match = _KEY_VALUE.match(line)
        if match and match.group(2):
            params[match.group(1)] = match.group(2)
    return params


def looks_like_work_order(params: dict[str, Any]) -> bool:
    return any(key in params for key in ("issueId", "objectId", "problemType"))


def validate(params: dict[str, Any]) -> dict[str, str]:
    """Return ``{issueId?, objectId, problemType, rat}`` or raise WorkOrderError listing every problem."""
    errors = []
    object_id = str(params.get("objectId") or "").strip()
    problem = str(params.get("problemType") or "").strip()
    rat = str(params.get("rat") or "NR").strip().upper()
    if not object_id:
        errors.append(f"{MISSING}：objectId（小区 CGI，例如 460-00-5267578-0）")
    elif not CGI_PATTERN.match(object_id):
        errors.append(f"objectId {INVALID}：{object_id!r} {CGI_HINT}")
    if not problem:
        errors.append(f"{MISSING}：problemType（OMC 标准问题代码，例如 UP_LOW_THROUGHPUT）")
    elif problem not in PROBLEM_TYPES:
        errors.append(f"problemType {INVALID}：{problem!r}，可选 {', '.join(PROBLEM_TYPES)}")
    if rat not in RATS:
        errors.append(f"rat {INVALID}：{rat!r}，可选 {', '.join(RATS)}（默认 NR）")
    if errors:
        raise WorkOrderError("；".join(errors))
    result = {"objectId": object_id, "problemType": problem, "rat": rat}
    if params.get("issueId"):
        result["issueId"] = str(params["issueId"]).strip()
    return result


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")


class WorkOrderStore:
    """Ledger plus the OMC-side statuses and advice, in memory, seeded from ``work_orders.json``."""

    def __init__(self, ledger_file: Path = LEDGER_FILE) -> None:
        self._lock = threading.Lock()
        seed = json.loads(ledger_file.read_text(encoding="utf-8"))
        self._orders = {entry["issueId"]: entry for entry in seed}
        self._statuses: dict[str, list[dict[str, Any]]] = {}
        self._advices: dict[str, list[dict[str, Any]]] = {}
        for entry in seed:
            if entry.get("diagnosed"):
                self._record(entry["issueId"], entry["cgi"], entry["problemType"], entry.get("submitTime") or _now())

    def ledger(self) -> list[dict[str, Any]]:
        with self._lock:
            return [{k: v for k, v in o.items() if k != "diagnosed"} for o in self._orders.values()]

    def statuses(self, issue_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return deepcopy(self._statuses.get(issue_id, []))

    def advices(self, issue_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return deepcopy(self._advices.get(issue_id, []))

    def submit(self, request: dict[str, str]) -> dict[str, Any]:
        """Create or re-attach to a work order, diagnose it and return the RanOptimizationResult."""
        with self._lock:
            issue_id = request.get("issueId")
            existing = issue_id is not None and issue_id in self._orders
            if existing and self._orders[issue_id]["cgi"] != request["objectId"]:
                raise WorkOrderError(
                    f"objectId {INVALID}：工单 {issue_id} 的小区是 {self._orders[issue_id]['cgi']}，"
                    f"与请求的 {request['objectId']} 不一致"
                )
            if not issue_id:
                digest = hashlib.sha256(f"{request['objectId']}#{request['problemType']}".encode()).hexdigest()
                issue_id = f"HN-OPT-{datetime.now(UTC):%Y%m%d}-{int(digest[:8], 16) % 10**8:08d}"
                existing = issue_id in self._orders
            if not existing:
                self._orders[issue_id] = {
                    "issueId": issue_id, "cgi": request["objectId"], "cellName": "",
                    "problemType": request["problemType"], "problemDesc": "", "district": "", "submitTime": _now(),
                }
            self._record(issue_id, request["objectId"], request["problemType"], _now())
            advice = PROBLEM_TYPES[request["problemType"]]
            return {"serviceManagement": {"RanOptimizationResult": {
                "issueId": issue_id,
                "objectId": request["objectId"],
                "rat": request["rat"],
                "problemType": request["problemType"],
                "workOrderStatus": "Exist" if existing else "Created",
                "optimizationStatus": "AdviceReady",
                "rootCause": advice["rootCause"],
                "optimizationAdvice": [
                    {"parameter": p, "currentValue": c, "suggestedValue": s, "reason": r}
                    for p, c, s, r in advice["advice"]
                ],
                "note": "Mock MAE: illustrative diagnosis, no parameters were changed on the network.",
            }}}

    def _record(self, issue_id: str, cgi: str, problem: str, when: str) -> None:
        advice = PROBLEM_TYPES[problem]
        self._statuses[issue_id] = [
            {"issueId": issue_id, "objectId": cgi, "status": "Diagnosed", "updateTime": when,
             "detail": f"根因 Root cause: {advice['rootCause']}"},
        ]
        self._advices[issue_id] = [
            {"issueId": issue_id, "objectId": cgi, "parameter": p, "currentValue": c, "suggestedValue": s,
             "advice": r, "updateTime": when}
            for p, c, s, r in advice["advice"]
        ]
