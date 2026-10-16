"""Energy-saving ControlPoint: the business decisions the host agent runtime delegates.

``on_self_task`` runs the Energy Agent's own steps (tariff, feasibility, report);
``on_task`` builds the Task-T content the workflow engine sends to MAE. One
instance serves one workflow execution, so it keeps the region and tariff it
fetched for the later steps.

Security and audit (LLD v10.4 §11.11): the policy guard (``policy.py``) runs
before any Negotiation-T message goes to MAE, and every policy decision and
negotiation round is written to the agent's own hash-chained audit log when
``ENERGY_AGENT_AUDIT_LOG_PATH`` is set. The workflow execution id is the
``trace_id`` there. Caller authentication is not done yet (open item O-25), so
records name the caller as unverified.

Negotiation (LLD v10.4 §5.2, §11.5) is bounded by ``ENERGY_AGENT_NEGOTIATION_MAX_ROUNDS``
(default 3) and ``ENERGY_AGENT_NEGOTIATION_ROUND_TIMEOUT_SECONDS`` (default 30); on
exhaustion or timeout the agent sends ``abort``. Re-initiating with MAE's relaxed target
needs ``ENERGY_AGENT_ALLOW_TARGET_RELAXATION=true`` (design decision D-1, off by default);
otherwise an infeasible verdict is accepted and closes as ``closed_infeasible``.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from typing import Any

import httpx
from a2a.client.client import ClientCallContext, ClientConfig
from a2a.client.client_factory import ClientFactory
from a2a.types import AgentCard, Part, Role, SendMessageRequest
from a2a.utils.constants import TransportProtocol
from google.protobuf.json_format import MessageToDict, ParseDict
from loguru import logger
from workflow_engine import ControlPoint, MessageContent, TaskResult

from mocks.common import audit, registry, uc1_data
from mocks.common.a2at import (
    ABORT_TEMPLATE_URI,
    ENERGY_SAVING_TEMPLATE_URI,
    FEASIBILITY_ACCEPT_REJECT_TEMPLATE_URI,
    FEASIBILITY_PROPOSE_TEMPLATE_URI,
    NEGOTIATION_T_EXTENSION_URI,
    TASK_T_EXTENSION_URI,
    TEMPLATE_URI_METADATA_KEY,
)
from mocks.common.uc1_messages import (
    energy_saving_slots,
    feasibility_abort,
    feasibility_accept,
    feasibility_opening,
)
from mocks.energy_agent import workflow
from mocks.energy_agent.policy import POLICY_VIOLATION, PolicyGuard
from mocks.mae.server import AGENT_ORGANIZATION as MAE_ORGANIZATION

SCENARIO_METADATA_KEY = "mockScenario"
#: Intent scenarios that drive the mock price API (``X-Mock-Mode``) instead of the mock MAE.
PRICE_API_SCENARIOS = {"price_api_error": "error", "price_api_slow": "slow"}
#: Highest experience risk the agent accepts when MAE offers several solutions.
SOLUTION_RISK_ORDER = ("low", "medium", "high")
UNVERIFIED_CALLER = {"user_id": None, "source_ip": None, "roles": [], "caller": "unverified (O-25)"}


class PriceApiUnavailable(RuntimeError):
    """The price API timed out or answered with an error (LLD v10.4 §4, F4)."""


def _env_bool(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


async def _within(seconds: float, coro: Any) -> Any:
    """Await ``coro`` for at most ``seconds``, then raise ``TimeoutError``.

    Runs it as its own task rather than ``asyncio.wait_for`` because the A2A client can swallow
    the cancellation, which would turn a timeout into a half-finished call.
    """
    task = asyncio.ensure_future(coro)
    done, _ = await asyncio.wait({task}, timeout=seconds)
    if not done:
        task.cancel()
        task.add_done_callback(lambda t: t.cancelled() or t.exception())
        raise TimeoutError(f"no answer within {seconds:g} s")
    return task.result()


def choose_solution(solutions: list[dict[str, Any]] | None, max_risk: str = "medium") -> str | None:
    """The offered solution with the highest predicted saving whose experience risk is at most ``max_risk``."""
    if not solutions:
        return None
    allowed = SOLUTION_RISK_ORDER[: SOLUTION_RISK_ORDER.index(max_risk) + 1]
    candidates = [s for s in solutions if s.get("experience_risk", "low") in allowed] or solutions[:1]
    return max(candidates, key=lambda s: s.get("predicted_energy_saving_percent", 0))["solution_id"]


class EnergySavingControlPoint(ControlPoint):
    def __init__(self, *, price_url: str, registry_url: str, mae_url: str,
                 policy: PolicyGuard | None = None, audit_log: audit.AuditLog | None = None,
                 max_rounds: int = 3, round_timeout: float = 30.0, allow_relaxation: bool = False,
                 price_timeout: float = 30.0, max_solution_risk: str = "medium") -> None:
        self._price_url = price_url.rstrip("/")
        self._registry_url = registry_url
        self._mae_url = mae_url.rstrip("/")
        self._policy = policy or PolicyGuard()
        self._audit_log = audit_log
        self._mae_card_digest: str | None = None
        self._region: str | None = None
        self._scenario: str | None = None
        self._tariff: dict[str, Any] | None = None
        self._max_rounds = max(1, max_rounds)
        self._round_timeout = round_timeout
        self._allow_relaxation = allow_relaxation
        self._price_timeout = price_timeout
        self._max_solution_risk = max_solution_risk

    @classmethod
    def from_env(cls) -> EnergySavingControlPoint:
        return cls(
            price_url=os.environ.get("ENERGY_AGENT_PRICE_API_BASE_URL", "http://127.0.0.1:8090"),
            registry_url=os.environ.get("REGISTRY_CENTER_URL", "http://127.0.0.1:5000"),
            mae_url=os.environ.get("MOCK_MAE_URL", "http://127.0.0.1:8091"),
            policy=PolicyGuard.from_env(),
            audit_log=audit.AuditLog.shared(path) if (path := os.environ.get("ENERGY_AGENT_AUDIT_LOG_PATH")) else None,
            max_rounds=int(os.environ.get("ENERGY_AGENT_NEGOTIATION_MAX_ROUNDS", "3")),
            round_timeout=float(os.environ.get("ENERGY_AGENT_NEGOTIATION_ROUND_TIMEOUT_SECONDS", "30")),
            allow_relaxation=_env_bool("ENERGY_AGENT_ALLOW_TARGET_RELAXATION"),
            price_timeout=float(os.environ.get("ENERGY_AGENT_PRICE_API_TIMEOUT_SECONDS", "30")),
            max_solution_risk=os.environ.get("ENERGY_AGENT_MAX_SOLUTION_RISK", "medium"),
        )

    # Workflow engine callbacks ------------------------------------------------

    async def on_self_task(self, request) -> TaskResult:
        self._remember_intent(request.workflow_input.runtime_intent)
        handlers = {
            workflow.SKILL_TARIFF: self._fetch_tariff,
            workflow.SKILL_FEASIBILITY: self._negotiate_feasibility,
            workflow.SKILL_REPORT: self._report,
        }
        handler = handlers.get(request.skill)
        if handler is None:
            return TaskResult.failed("energy_agent.unknown_skill", f"No handler for skill {request.skill!r}")
        try:
            return await handler(request)
        except PriceApiUnavailable as exc:
            return TaskResult.failed("energy_agent.price_api_unavailable", str(exc))
        except Exception as exc:  # surfaced as a failed step in the Execution Center
            logger.exception(f"[EnergyAgent] {request.step_name} failed")
            return TaskResult.failed(f"energy_agent.{request.skill}", f"{type(exc).__name__}: {exc}")

    async def on_task(self, request) -> MessageContent:
        if request.agent_name != workflow.MAE_NAME or request.skill != workflow.SKILL_ENERGY_SAVING:
            raise ValueError(f"Mock Energy Agent cannot build a task for {request.agent_name}/{request.skill}")
        self._remember_intent(request.workflow_input.runtime_intent)
        tariff = await self._tariff_or_fetch()
        slots = energy_saving_slots(self._region, tariff)
        metadata = {TASK_T_EXTENSION_URI: json.dumps(slots, ensure_ascii=False),
                    TEMPLATE_URI_METADATA_KEY: ENERGY_SAVING_TEMPLATE_URI}
        if self._scenario:
            metadata[SCENARIO_METADATA_KEY] = self._scenario
        return MessageContent(
            parts=(Part(text=slots["task_description"]),),
            metadata=metadata,
            extensions=frozenset({TASK_T_EXTENSION_URI}),
        )

    # Steps --------------------------------------------------------------------

    def _remember_intent(self, intent: str) -> None:
        if self._region is None:
            self._region = workflow.region_of(intent or "")
            self._scenario = workflow.scenario_of(intent or "")

    async def _tariff_or_fetch(self) -> dict[str, Any]:
        if self._tariff is None:
            headers = {}
            if os.environ.get("ENERGY_AGENT_PRICE_API_KEY"):
                headers["X-API-Key"] = os.environ["ENERGY_AGENT_PRICE_API_KEY"]
            if self._scenario in PRICE_API_SCENARIOS:
                headers["X-Mock-Mode"] = PRICE_API_SCENARIOS[self._scenario]
            try:
                async with httpx.AsyncClient(timeout=self._price_timeout, trust_env=False) as http:
                    response = await _within(self._price_timeout, http.get(
                        f"{self._price_url}/v1/tariffs/power-band", params={"region": self._region},
                        headers=headers))
                    response.raise_for_status()
                    self._tariff = response.json()
            except (httpx.TimeoutException, TimeoutError) as exc:
                raise PriceApiUnavailable(
                    f"price API did not answer within {self._price_timeout:g} s ({type(exc).__name__})") from exc
            except httpx.HTTPStatusError as exc:
                raise PriceApiUnavailable(
                    f"price API answered {exc.response.status_code}: {exc.response.text[:200]}") from exc
            except httpx.TransportError as exc:
                raise PriceApiUnavailable(f"price API unreachable: {type(exc).__name__}: {exc}") from exc
        return self._tariff

    async def _fetch_tariff(self, _request) -> TaskResult:
        tariff = await self._tariff_or_fetch()
        rows = [f"| {b['band_no']} | {b['min_kw']:.2f} to {b['max_kw']:.2f} | {b['charge']:,.2f} |"
                for b in tariff["bands"]]
        return TaskResult.succeeded((
            f"**Power-band tariff for {self._region}** ({tariff['currency']}, {tariff['billing_period']})\n\n"
            f"| Band | Power draw (kW) | Charge per site |\n|---|---|---|\n" + "\n".join(rows),
        ))

    def _check_policy(self, trace_id: str, tariff: dict[str, Any], schedule: list[dict[str, Any]],
                      round_no: int) -> Any:
        decision = self._policy.check(self._region, schedule)
        self._audit("policy_decision", trace_id, "success" if decision.allowed else "denied",
                    reason=None if decision.allowed else POLICY_VIOLATION,
                    detail={**decision.as_dict(), "round": round_no, "price_table_digest": audit.digest(tariff)})
        return decision

    async def _negotiate_feasibility(self, request) -> TaskResult:
        trace_id = request.execution_id
        tariff = await self._tariff_or_fetch()
        decision = self._check_policy(trace_id, tariff, uc1_data.intent_schedule(), 1)
        if not decision.allowed:
            return TaskResult.failed(f"energy_agent.{POLICY_VIOLATION}",
                                     f"Policy guard refused {self._region}: {'; '.join(decision.reasons)}")
        async with httpx.AsyncClient(timeout=max(30.0, self._round_timeout + 5), trust_env=False) as http:
            card = await self._mae_card(http)
            self._mae_card_digest = audit.digest(card)
            factory = ClientFactory(ClientConfig(httpx_client=http,
                                                 supported_protocol_bindings=[TransportProtocol.HTTP_JSON]))
            client = factory.create(ParseDict(card, AgentCard(), ignore_unknown_fields=True))
            return await self._negotiation_loop(client, tariff, trace_id)

    async def _negotiation_loop(self, client: Any, tariff: dict[str, Any], trace_id: str) -> TaskResult:
        """Rounds of propose -> verdict until agreed, closed infeasible or aborted (LLD v10.4 §5.2)."""
        opening = feasibility_opening(self._region, tariff)
        history: list[str] = []
        while True:
            round_no = opening["round"]
            try:
                reply = await _within(self._round_timeout, self._negotiation_round(
                    client, opening, FEASIBILITY_PROPOSE_TEMPLATE_URI, trace_id))
            except TimeoutError:
                self._audit("negotiation_round", trace_id, "failure", reason="round_timeout", detail={
                    "negotiation_id": opening["negotiation_id"], "round": round_no,
                    "sent": {"template": FEASIBILITY_PROPOSE_TEMPLATE_URI, "message_class": opening["message_class"]},
                    "received": None, "outcome": "aborted", "timeout_seconds": self._round_timeout,
                    "mae_card_digest": self._mae_card_digest,
                })
                await self._abort(client, opening, {}, trace_id)
                return TaskResult.failed(
                    "energy_agent.negotiation_aborted",
                    f"Negotiation with MAE aborted: no answer to round {round_no} within {self._round_timeout:g} s")
            received = reply.get("message_class")
            history.append(f"round {round_no}: {received}")

            if received == "feasible_request_confirmation":
                chosen = choose_solution(reply.get("solutions"), self._max_solution_risk)
                closed = await self._negotiation_round(client, feasibility_accept(reply, chosen),
                                                       FEASIBILITY_ACCEPT_REJECT_TEMPLATE_URI, trace_id)
                outcome = closed.get("outcome", "closed")
                if outcome != "agreed":
                    return TaskResult.failed("energy_agent.negotiation_aborted",
                                             f"Negotiation with MAE {outcome} after confirmation")
                return TaskResult.succeeded((self._agreed_text(reply, chosen, history),))

            if received == "infeasible_with_proposal":
                proposed = (reply.get("proposal") or {}).get("schedule")
                if self._allow_relaxation and proposed:
                    if round_no >= self._max_rounds:
                        await self._abort(client, opening, reply, trace_id)
                        return TaskResult.failed(
                            "energy_agent.negotiation_aborted",
                            f"Negotiation with MAE aborted: still infeasible after {round_no} rounds "
                            f"(limit {self._max_rounds}). Last basis: {_basis(reply)}")
                    # The relaxed target must pass the same policy guard as the original (LLD §11.10).
                    decision = self._check_policy(trace_id, tariff, proposed, round_no + 1)
                    if not decision.allowed:
                        await self._abort(client, opening, reply, trace_id)
                        return TaskResult.failed(
                            f"energy_agent.{POLICY_VIOLATION}",
                            f"MAE's counter-proposal breaks policy: {'; '.join(decision.reasons)}")
                    opening = feasibility_opening(self._region, tariff, schedule=proposed,
                                                  negotiation_id=reply.get("negotiation_id") or
                                                  opening["negotiation_id"], round_no=round_no + 1)
                    continue
                # D-1 default: accept the infeasible verdict and hand the counter-proposal to the user.
                await self._negotiation_round(client, feasibility_accept(reply),
                                              FEASIBILITY_ACCEPT_REJECT_TEMPLATE_URI, trace_id)
                verdict = "partially feasible" if reply.get("feasibility") == "partial" else "infeasible"
                counter = reply.get("counter_proposal") or reply.get("proposal")
                return TaskResult.failed(
                    "energy_agent.infeasible",
                    f"MAE: {self._region} is not feasible as requested ({verdict}: {_basis(reply)}). "
                    f"Counter-proposal: {json.dumps(counter, ensure_ascii=False)}")

            closed = await self._abort(client, opening, reply, trace_id)
            return TaskResult.failed("energy_agent.negotiation_aborted",
                                     f"Negotiation with MAE {closed.get('outcome', 'aborted')}: "
                                     f"{reply.get('error') or received}")

    async def _abort(self, client: Any, opening: dict[str, Any], reply: dict[str, Any],
                     trace_id: str) -> dict[str, Any]:
        try:
            return await _within(self._round_timeout, self._negotiation_round(
                client, feasibility_abort(opening, reply), ABORT_TEMPLATE_URI, trace_id))
        except TimeoutError:
            return {"outcome": "aborted"}

    def _agreed_text(self, reply: dict[str, Any], chosen: str | None, history: list[str]) -> str:
        text = (f"MAE: {reply.get('assessment', 'feasible')} Energy Agent accepted; "
                f"negotiation agreed (id {reply['negotiation_id']}, {len(history)} round"
                f"{'s' if len(history) > 1 else ''}).")
        if chosen:
            name = next((s["name"] for s in reply.get("solutions", []) if s["solution_id"] == chosen), chosen)
            text += f" Selected solution {chosen}: {name}."
        outcome = reply.get("expected_outcome")
        if outcome:
            text += (f" Expected saving {outcome['predicted_monthly_saving']:,.2f} {outcome['currency']} per month "
                     f"({outcome['predicted_energy_saving_percent']:g}% energy).")
        return text

    async def _report(self, request) -> TaskResult:
        artifacts = {}
        for upstream in request.workflow_input.upstream_results:
            for result in upstream.task_results:
                for received in result.received_messages:
                    for artifact in received.artifacts:
                        body = artifact.metadata.get(TASK_T_EXTENSION_URI)
                        if body:
                            parsed = json.loads(body) if isinstance(body, str) else dict(body)
                            artifacts[parsed["type"]] = parsed
        report = artifacts.get("IntentReport")
        if report is None:
            error = artifacts.get("TaskError")
            if error:
                return TaskResult.failed(f"mae.{error['code']}", f"MAE failed at {error['failed_step']}: "
                                                                 f"{error['reason']}")
            return TaskResult.failed("energy_agent.no_report", "MAE returned no IntentReport artifact")
        counts = artifacts.get("SiteClassification", {}).get("counts", {})
        activated = artifacts.get("EnergySavingActivated", {}).get("activated_sites", [])
        currency = report["currency"]
        lines = [
            f"**Energy-saving intent report for {report['region']}**",
            "",
            "| | |",
            "|---|---|",
            f"| Predicted {report['billing_period']} cost before | {report['predicted_cost_before']:,.2f} {currency} |",
            f"| Predicted {report['billing_period']} cost after | {report['predicted_cost_after']:,.2f} {currency} |",
            f"| Predicted saving | **{report['predicted_saving']:,.2f} {currency}** |",
            f"| Intent achieved | {'yes' if report['intent_achieved'] else 'no'} |",
            f"| Sites changing band | {report['sites_changing_band']} |",
        ]
        if counts:
            lines.append(f"| Site classification | {counts.get('downgrade', 0)} downgrade, "
                         f"{counts.get('upgrade', 0)} upgrade, {counts.get('grade_stable', 0)} grade-stable |")
        if activated:
            lines.append(f"| Energy saving activated on | {', '.join(activated)} |")
        energy = report.get("energy")
        if energy:
            lines.append(f"| Predicted energy saving | {energy['predicted_saving']:,.1f} {energy['unit']} "
                         f"({energy['saving_percent']:g}%) |")
        cells = report.get("cells")
        if cells:
            failed_text = f", {cells['failed']} failed" if cells["failed"] else ""
            lines.append(f"| Cells | {cells['activated']} of {cells['selected']} activated{failed_text} "
                         f"(achievement {report.get('achievement', 'full')}) |")
        failed = artifacts.get("EnergySavingActivated", {}).get("failed_cells", [])
        kpis = report.get("experience_kpis") or []
        if kpis:
            lines += ["", "| Period | Saving mode | Target | Avg user rate (Mbps) | PRB load | Target met |",
                      "|---|---|---|---|---|---|"]
            for kpi in kpis:
                lines.append(
                    f"| {kpi['period']} | {kpi['saving_mode']} | {_target_text(kpi['experience_target'])} | "
                    f"{kpi['baseline_avg_user_rate_mbps']:g} -> {kpi['predicted_avg_user_rate_mbps']:g} | "
                    f"{kpi['prb_utilization_before_percent']:g}% -> {kpi['prb_utilization_after_percent']:g}% | "
                    f"{'yes' if kpi['target_met'] else 'no'} |")
        if failed:
            lines += ["", "Cells not activated: " + ", ".join(f"{c['cell_id']} ({c['reason']})" for c in failed)]
        return TaskResult.succeeded(("\n".join(lines),))

    # MAE access -----------------------------------------------------------------

    async def _mae_card(self, http: httpx.AsyncClient) -> dict[str, Any]:
        card = await asyncio.to_thread(registry.find_card, self._registry_url, MAE_ORGANIZATION, workflow.MAE_NAME)
        if card:
            return card
        response = await http.get(f"{self._mae_url}/.well-known/agent-card.json")
        response.raise_for_status()
        return response.json()

    async def _negotiation_round(self, client: Any, content: dict[str, Any], template: str,
                                 trace_id: str) -> dict[str, Any]:
        request = SendMessageRequest()
        request.message.message_id = str(uuid.uuid4())
        request.message.role = Role.ROLE_USER
        request.message.parts.add().text = content["message_class"]
        request.message.metadata[NEGOTIATION_T_EXTENSION_URI] = json.dumps(content)
        request.message.metadata[TEMPLATE_URI_METADATA_KEY] = template
        if self._scenario:
            request.message.metadata[SCENARIO_METADATA_KEY] = self._scenario
        context = ClientCallContext(service_parameters={"A2A-Extensions": NEGOTIATION_T_EXTENSION_URI})
        events = [MessageToDict(event) async for event in client.send_message(request, context=context)]
        if not events or "message" not in events[-1]:
            raise RuntimeError(f"MAE sent no Negotiation-T reply to {content['message_class']}")
        metadata = events[-1]["message"]["metadata"]
        reply = json.loads(metadata[NEGOTIATION_T_EXTENSION_URI])
        self._audit("negotiation_round", trace_id, "failure" if reply.get("message_class") == "error" else "success",
                    reason=reply.get("error"), detail={
                        "negotiation_id": content.get("negotiation_id"),
                        "round": content.get("round"),
                        "sent": {"template": template, "message_class": content["message_class"]},
                        "received": {"template": metadata.get(TEMPLATE_URI_METADATA_KEY),
                                     "message_class": reply.get("message_class")},
                        "outcome": reply.get("outcome", "continuing"),
                        "price_table_digest": audit.digest(self._tariff) if self._tariff else None,
                        "counter_proposal_digest": audit.digest(reply["proposal"]) if reply.get("proposal") else None,
                        # Pins which MAE AgentCard was negotiated with (agent identity at dispatch).
                        "mae_card_digest": self._mae_card_digest,
                    })
        return reply

    def _audit(self, event: str, trace_id: str, outcome: str, *, reason: str | None = None,
               detail: dict[str, Any]) -> None:
        if self._audit_log is not None:
            self._audit_log.append(event, outcome=outcome, trace_id=trace_id, actor=UNVERIFIED_CALLER,
                                   resource={"region": self._region}, reason=reason, detail=detail)


def _basis(reply: dict[str, Any]) -> str:
    return reply.get("basis") or "; ".join(reply.get("reasons") or []) or "no reason given"


def _target_text(target: dict[str, Any]) -> str:
    if target.get("type") == "rate_floor":
        return f">= {target.get('mbps')} Mbps"
    return {"no_degradation": "no degradation", "none": "none"}.get(target.get("type"), str(target.get("type")))
