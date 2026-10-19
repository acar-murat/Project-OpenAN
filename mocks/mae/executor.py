"""A2A executor for the mock MAE.

Routes each inbound message by the A2A-T extension it carries in ``message.metadata``:

* **Negotiation-T** (feasibility negotiation, LLD v10.4 §11.5): replies with one agent
  ``Message`` whose ``metadata[Negotiation-T/v1]`` holds the reply as JSON.
* **Task-T** (``ran-energy-saving/v1`` dispatch, LLD v10.4 §11.7): streams a task through
  SUBMITTED → WORKING → artifacts → COMPLETED. Each artifact's body is JSON in
  ``artifact.metadata[Task-T/v1]`` (see ``planning.build_artifacts``).

Without either extension the message is read the way the RAN adapter reads it (HQ's A2A-T
client plugin, docs/henan-demo.md): parameters come from ``metadata.taskParameters``, a DataPart,
or the text as a JSON block or ``key: value`` lines. ``issueId`` / ``objectId`` / ``problemType``
make an optimisation work order (``mocks.mae.optimization``); a ``region`` makes an energy-saving
task; the ``energy-saving`` skill without a region asks for one (INPUT_REQUIRED); anything else
fails with ``未解析出任务参数``.

Content is read as JSON where possible. Unlike the real MAE, the mock does not
run the A2A-T SDK's LLM-based prompt validation, so it is deterministic and
needs no LLM.

``MOCK_MAE_SCENARIO`` forces an outcome: ``auto`` (default: decide from the
content), ``feasible``, ``infeasible``, ``reject_task`` or ``exec_failure``.
A message can override it with ``metadata["mockScenario"]``.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from typing import Any

from a2a.server.agent_execution.agent_executor import AgentExecutor
from a2a.server.agent_execution.context import RequestContext
from a2a.server.events.event_queue import EventQueue
from a2a.types import (
    Artifact,
    Message,
    Role,
    Task,
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
)
from google.protobuf.json_format import MessageToDict

from mocks.common.a2at import (
    ABORT_TEMPLATE_URI,
    ENERGY_SAVING_TEMPLATE_URI,
    FEASIBILITY_ACCEPT_REJECT_TEMPLATE_URI,
    FEASIBILITY_PROPOSE_TEMPLATE_URI,
    NEGOTIATION_T_EXTENSION_URI,
    TASK_T_EXTENSION_URI,
    TEMPLATE_URI_METADATA_KEY,
)
from mocks.mae import optimization, planning

SCENARIOS = ("auto", "feasible", "infeasible", "reject_task", "exec_failure")
SCENARIO_METADATA_KEY = "mockScenario"


def _scenario(metadata: dict[str, Any]) -> str:
    scenario = str(metadata.get(SCENARIO_METADATA_KEY) or os.environ.get("MOCK_MAE_SCENARIO", "auto")).lower()
    return scenario if scenario in SCENARIOS else "auto"


def _step_delay() -> float:
    return float(os.environ.get("MOCK_MAE_STEP_DELAY_SECONDS", "0.5"))


def _agent_message(context_id: str, task_id: str | None, text: str) -> Message:
    message = Message(message_id=str(uuid.uuid4()), context_id=context_id, role=Role.ROLE_AGENT)
    if task_id:
        message.task_id = task_id
    message.parts.add(text=text)
    return message


ENERGY_SAVING_SKILL = "energy-saving"
OPTIMIZATION_SKILL = "ran-complaint-optimization"


def _plain_parameters(message: Message | None, metadata: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """Parameters of a message without a Task-T payload, by the adapter's priority:
    ``metadata.taskParameters``, then a DataPart, then the text."""
    if message is None:
        return {}, ""
    parts = MessageToDict(message).get("parts", [])
    text = "\n".join(part["text"] for part in parts if isinstance(part.get("text"), str))
    if isinstance(metadata.get("taskParameters"), dict):
        return metadata["taskParameters"], text
    for part in parts:
        if isinstance(part.get("data"), dict):
            return part["data"], text
    return optimization.parse_parameters(text), text


class MockMaeExecutor(AgentExecutor):
    def __init__(self, work_orders: optimization.WorkOrderStore | None = None) -> None:
        self.work_orders = work_orders or optimization.WorkOrderStore()

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        message = context.message
        metadata = MessageToDict(message.metadata) if message is not None and message.metadata else {}
        if NEGOTIATION_T_EXTENSION_URI in metadata:
            await self._negotiate(context, event_queue, metadata)
        elif TASK_T_EXTENSION_URI in metadata:
            await self._run_task(context, event_queue, metadata, metadata[TASK_T_EXTENSION_URI])
        else:
            await self._plain(context, event_queue, metadata)

    async def _plain(self, context: RequestContext, event_queue: EventQueue, metadata: dict[str, Any]) -> None:
        params, text = _plain_parameters(context.message, metadata)
        skill = str(metadata.get("skill") or "")
        if skill == OPTIMIZATION_SKILL or optimization.looks_like_work_order(params):
            await self._work_order(context, event_queue, params)
            return
        content: Any = params if params.get("region") or params.get("task_object") else text
        try:
            planning.parse_intent(content)
        except planning.IntentError:
            if skill == ENERGY_SAVING_SKILL:
                await self._submitted(context, event_queue, "Energy-saving request received.")
                await self._status(context, event_queue, TaskState.TASK_STATE_INPUT_REQUIRED,
                                   "请补充：目标区域 region（例如 region: Zhengzhou）。"
                                   "Please supply the target region, e.g. 'region: Zhengzhou'.")
                return
            await self._submitted(context, event_queue, "Request received.")
            await self._status(context, event_queue, TaskState.TASK_STATE_FAILED,
                               f"{optimization.UNPARSED}：请以 JSON 块或「键: 值」行给出参数。"
                               f"Work order: issueId, objectId (cell CGI), problemType, rat (default NR). "
                               f"Energy saving: region. Or send a Task-T / Negotiation-T message "
                               f"(metadata key {TASK_T_EXTENSION_URI} or {NEGOTIATION_T_EXTENSION_URI}).")
            return
        await self._run_task(context, event_queue, metadata, content)

    async def _work_order(self, context: RequestContext, event_queue: EventQueue, params: dict[str, Any]) -> None:
        await self._submitted(context, event_queue, "工单请求已受理 Work-order request accepted.")
        try:
            result = self.work_orders.submit(optimization.validate(params))
        except optimization.WorkOrderError as exc:
            await self._status(context, event_queue, TaskState.TASK_STATE_FAILED, f"工单创建失败：{exc}")
            return
        body = result["serviceManagement"]["RanOptimizationResult"]
        await self._status(context, event_queue, TaskState.TASK_STATE_WORKING,
                           f"工单 {body['issueId']} {body['workOrderStatus']}，诊断中 diagnosing")
        await asyncio.sleep(_step_delay())
        artifact = Artifact(artifact_id=str(uuid.uuid4()), name="RanOptimizationResult")
        artifact.parts.add(text=json.dumps(result, ensure_ascii=False))
        await event_queue.enqueue_event(TaskArtifactUpdateEvent(
            task_id=context.task_id or "", context_id=context.context_id or "", artifact=artifact, last_chunk=True,
        ))
        await self._status(context, event_queue, TaskState.TASK_STATE_COMPLETED,
                           f"工单 {body['issueId']}：{body['rootCause']}")

    @staticmethod
    async def _submitted(context: RequestContext, event_queue: EventQueue, text: str) -> None:
        await event_queue.enqueue_event(Task(
            id=context.task_id or "",
            context_id=context.context_id or "",
            status=TaskStatus(
                state=TaskState.TASK_STATE_SUBMITTED,
                message=_agent_message(context.context_id or "", context.task_id, text),
            ),
        ))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        await self._status(context, event_queue, TaskState.TASK_STATE_CANCELED, "Task cancelled.")

    # Negotiation-T ---------------------------------------------------------

    async def _negotiate(self, context: RequestContext, event_queue: EventQueue, metadata: dict[str, Any]) -> None:
        raw = metadata[NEGOTIATION_T_EXTENSION_URI]
        content = planning.parse_json(raw) or {}
        message_class = str(content.get("message_class") or _guess_message_class(raw))
        negotiation_id = str(content.get("negotiation_id") or uuid.uuid4())
        round_no = int(content.get("round") or 1)

        if message_class == "initiate_feasibility_assessment":
            reply = self._assess(content if content else raw, _scenario(metadata), negotiation_id, round_no)
            template = FEASIBILITY_PROPOSE_TEMPLATE_URI
        elif message_class in ("accept", "reject"):
            # Accepting an infeasible verdict closes the negotiation without agreement (LLD §5.2).
            if message_class == "reject":
                outcome = "aborted"
            elif content.get("accepted") == "infeasible_with_proposal":
                outcome = "closed_infeasible"
            else:
                outcome = "agreed"
            reply = {
                "category": "goal_achievement",
                "message_class": "negotiation_closed",
                "negotiation_id": negotiation_id,
                "round": round_no,
                "outcome": outcome,
            }
            template = FEASIBILITY_ACCEPT_REJECT_TEMPLATE_URI
        elif message_class == "abort":
            reply = {"message_class": "negotiation_closed", "negotiation_id": negotiation_id,
                     "round": round_no, "outcome": "aborted"}
            template = ABORT_TEMPLATE_URI
        else:
            reply = {"message_class": "error", "negotiation_id": negotiation_id,
                     "error": f"unsupported message_class {message_class!r}"}
            template = FEASIBILITY_PROPOSE_TEMPLATE_URI

        message = _agent_message(context.context_id or "", None, _negotiation_summary(reply))
        message.metadata[NEGOTIATION_T_EXTENSION_URI] = json.dumps(reply, ensure_ascii=False)
        message.metadata[TEMPLATE_URI_METADATA_KEY] = template
        await event_queue.enqueue_event(message)

    @staticmethod
    def _assess(content: Any, scenario: str, negotiation_id: str, round_no: int) -> dict[str, Any]:
        base = {"category": "goal_achievement", "negotiation_id": negotiation_id, "round": round_no}
        try:
            intent = planning.parse_intent(content)
        except planning.IntentError as exc:
            return {**base, "message_class": "infeasible_with_proposal", "reasons": [str(exc)], "proposal": None}
        assessment = planning.assess_feasibility(intent)
        if scenario == "feasible":
            assessment = {"feasible": True, "reasons": [], "proposal": None}
        elif scenario == "infeasible" and assessment["feasible"]:
            assessment = {
                "feasible": False,
                "reasons": ["mock scenario 'infeasible' forced by configuration"],
                "proposal": {"schedule": intent.schedule},
            }
        if assessment["feasible"]:
            return {**base, "message_class": "feasible_request_confirmation", "region": intent.region,
                    "assessment": "The cluster can meet the energy-saving and experience targets."}
        return {**base, "message_class": "infeasible_with_proposal", "region": intent.region,
                "reasons": assessment["reasons"], "proposal": assessment["proposal"]}

    # Task-T ----------------------------------------------------------------

    async def _run_task(self, context: RequestContext, event_queue: EventQueue, metadata: dict[str, Any],
                        content: Any) -> None:
        scenario = _scenario(metadata)
        await self._submitted(context, event_queue, "Energy-saving task accepted.")

        template = str(metadata.get(TEMPLATE_URI_METADATA_KEY) or ENERGY_SAVING_TEMPLATE_URI)
        if template != ENERGY_SAVING_TEMPLATE_URI:
            await self._status(context, event_queue, TaskState.TASK_STATE_REJECTED,
                               f"Unsupported template {template}; expected {ENERGY_SAVING_TEMPLATE_URI}.")
            return
        try:
            intent = planning.parse_intent(content)
        except planning.IntentError as exc:
            await self._status(context, event_queue, TaskState.TASK_STATE_REJECTED, f"Intent rejected: {exc}")
            return
        if scenario == "reject_task":
            await self._status(context, event_queue, TaskState.TASK_STATE_REJECTED,
                               "Intent rejected: mock scenario 'reject_task'.")
            return

        artifacts = planning.build_artifacts(intent)
        for index, body in enumerate(artifacts):
            await self._status(context, event_queue, TaskState.TASK_STATE_WORKING,
                               f"Region {intent.region}: {body['type']} ({index + 1}/{len(artifacts)})")
            await asyncio.sleep(_step_delay())
            if scenario == "exec_failure" and index == 2:
                await self._status(context, event_queue, TaskState.TASK_STATE_FAILED,
                                   "Cluster optimization failed: mock scenario 'exec_failure'.")
                return
            await self._artifact(context, event_queue, body)
        await self._status(context, event_queue, TaskState.TASK_STATE_COMPLETED,
                           f"Energy-saving task completed for {intent.region}.")

    @staticmethod
    async def _status(context: RequestContext, event_queue: EventQueue, state: TaskState, text: str) -> None:
        await event_queue.enqueue_event(TaskStatusUpdateEvent(
            task_id=context.task_id or "",
            context_id=context.context_id or "",
            status=TaskStatus(state=state, message=_agent_message(context.context_id or "", context.task_id, text)),
        ))

    @staticmethod
    async def _artifact(context: RequestContext, event_queue: EventQueue, body: dict[str, Any]) -> None:
        artifact = Artifact(artifact_id=str(uuid.uuid4()), name=body["type"])
        artifact.parts.add(text=planning.describe(body))
        artifact.metadata[TASK_T_EXTENSION_URI] = json.dumps(body, ensure_ascii=False)
        await event_queue.enqueue_event(TaskArtifactUpdateEvent(
            task_id=context.task_id or "",
            context_id=context.context_id or "",
            artifact=artifact,
            last_chunk=True,
        ))


def _guess_message_class(raw: Any) -> str:
    text = str(raw).lower()
    for name in ("initiate_feasibility_assessment", "abort", "reject", "accept"):
        if name in text:
            return name
    return "initiate_feasibility_assessment"


def _negotiation_summary(reply: dict[str, Any]) -> str:
    message_class = reply.get("message_class")
    if message_class == "feasible_request_confirmation":
        return "Feasible: please confirm to proceed."
    if message_class == "infeasible_with_proposal":
        return "Infeasible: " + "; ".join(reply.get("reasons") or []) + " A counter-proposal is attached."
    if message_class == "negotiation_closed":
        return f"Negotiation closed: {reply.get('outcome')}."
    return f"Negotiation error: {reply.get('error')}"
