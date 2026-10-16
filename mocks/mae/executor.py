"""A2A executor for the mock MAE.

Routes each inbound message by the A2A-T extension it carries in ``message.metadata``:

* **Negotiation-T** (feasibility negotiation, LLD v10.4 §11.5): replies with one agent
  ``Message`` whose ``metadata[Negotiation-T/v1]`` holds the reply as JSON.
* **Task-T** (``ran-energy-saving/v1`` dispatch, LLD v10.4 §11.7): streams a task through
  SUBMITTED → WORKING → artifacts → COMPLETED. Each artifact's body is JSON in
  ``artifact.metadata[Task-T/v1]`` (see ``planning.build_artifacts``).

Content is read as JSON where possible. Unlike the real MAE, the mock does not
run the A2A-T SDK's LLM-based prompt validation, so it is deterministic and
needs no LLM.

``MOCK_MAE_SCENARIO`` forces an outcome (default ``auto``: decide from the content).
A message can override it with ``metadata["mockScenario"]``. See ``SCENARIOS`` for
the list; each one maps to an outcome in LLD v10.4 §4 (failure paths) and §5.2
(negotiation rounds).

* ``MOCK_MAE_SLOW_SECONDS`` (default 60): how long ``slow_negotiation`` waits before
  answering, so the Energy Agent's per-round timeout fires.
* ``MOCK_MAE_EXEC_TIMEOUT_SECONDS`` (default 5): how long ``exec_timeout`` runs before
  giving up.
* ``MOCK_MAE_SLOW_STEP_SECONDS`` (default 3): step delay for ``delayed``.
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
from mocks.mae import planning

#: Scenario -> what the mock does. Negotiation scenarios change the feasibility verdict;
#: task scenarios change the Task-T stream.
SCENARIOS = {
    "auto": "decide from the content (rate floors above MOCK_MAE_MAX_RATE_FLOOR_MBPS are infeasible)",
    "feasible": "negotiation: feasible, request confirmation",
    "infeasible": "negotiation: infeasible in every round; the counter-proposal repeats the request",
    "partially_feasible": "negotiation: some saving periods feasible; the proposal drops saving in the others",
    "multi_round": "negotiation: infeasible in round 1 with relaxed rate floors, feasible from round 2",
    "multiple_solutions": "negotiation: feasible with three alternative solutions to choose from",
    "negotiation_error": "negotiation: MAE answers with an error message",
    "slow_negotiation": "negotiation: MAE answers after MOCK_MAE_SLOW_SECONDS",
    "reject_task": "task: REJECTED before any artifact",
    "semantic_rejected": "task: REJECTED with negotiation.semantic_rejected (LLD F7)",
    "exec_failure": "task: TaskError artifact then FAILED after two artifacts (LLD F8)",
    "exec_timeout": "task: TaskError execution_timeout then FAILED after MOCK_MAE_EXEC_TIMEOUT_SECONDS",
    "partial_execution": "task: COMPLETED, but some cells fail to activate (achievement partial)",
    "delayed": "task: COMPLETED, each step waits MOCK_MAE_SLOW_STEP_SECONDS",
}
SCENARIO_METADATA_KEY = "mockScenario"


def _scenario(metadata: dict[str, Any]) -> str:
    scenario = str(metadata.get(SCENARIO_METADATA_KEY) or os.environ.get("MOCK_MAE_SCENARIO", "auto")).lower()
    return scenario if scenario in SCENARIOS else "auto"


def _seconds(name: str, default: str) -> float:
    return float(os.environ.get(name, default))


def _step_delay(scenario: str = "auto") -> float:
    if scenario == "delayed":
        return _seconds("MOCK_MAE_SLOW_STEP_SECONDS", "3")
    return _seconds("MOCK_MAE_STEP_DELAY_SECONDS", "0.5")


def _agent_message(context_id: str, task_id: str | None, text: str) -> Message:
    message = Message(message_id=str(uuid.uuid4()), context_id=context_id, role=Role.ROLE_AGENT)
    if task_id:
        message.task_id = task_id
    message.parts.add(text=text)
    return message


class MockMaeExecutor(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        message = context.message
        metadata = MessageToDict(message.metadata) if message is not None and message.metadata else {}
        if NEGOTIATION_T_EXTENSION_URI in metadata:
            await self._negotiate(context, event_queue, metadata)
        elif TASK_T_EXTENSION_URI in metadata:
            await self._run_task(context, event_queue, metadata)
        else:
            reply = _agent_message(
                context.context_id or "", None,
                "Mock MAE expects a Task-T or Negotiation-T message "
                f"(metadata key {TASK_T_EXTENSION_URI} or {NEGOTIATION_T_EXTENSION_URI}).",
            )
            await event_queue.enqueue_event(reply)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        await self._status(context, event_queue, TaskState.TASK_STATE_CANCELED, "Task cancelled.")

    # Negotiation-T ---------------------------------------------------------

    async def _negotiate(self, context: RequestContext, event_queue: EventQueue, metadata: dict[str, Any]) -> None:
        raw = metadata[NEGOTIATION_T_EXTENSION_URI]
        content = planning.parse_json(raw) or {}
        message_class = str(content.get("message_class") or _guess_message_class(raw))
        negotiation_id = str(content.get("negotiation_id") or uuid.uuid4())
        round_no = int(content.get("round") or 1)

        scenario = _scenario(metadata)
        if message_class == "initiate_feasibility_assessment":
            if scenario == "slow_negotiation":
                await asyncio.sleep(_seconds("MOCK_MAE_SLOW_SECONDS", "60"))
            reply = self._assess(content if content else raw, scenario, negotiation_id, round_no)
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
            if outcome == "agreed" and content.get("selected_solution"):
                reply["selected_solution"] = content["selected_solution"]
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
            return {**base, "message_class": "infeasible_with_proposal", "feasibility": "none",
                    "reasons": [str(exc)], "basis": str(exc), "proposal": None, "counter_proposal": None}
        if scenario == "negotiation_error":
            return {**base, "message_class": "error", "region": intent.region,
                    "error": "assessment engine unavailable: traffic forecast for the cluster is missing (mock)"}
        assessment = planning.assess_feasibility(intent)
        if scenario in ("feasible", "multiple_solutions") or (scenario == "multi_round" and round_no >= 2):
            assessment = {**assessment, "feasible": True, "feasibility": "full", "reasons": [], "proposal": None,
                          "periods": [{**p, "feasible": True, "reason": None} for p in assessment["periods"]]}
        elif scenario == "multi_round":
            assessment = planning.relaxed_proposal(intent)
        elif scenario == "partially_feasible":
            assessment = planning.assess_partially_feasible(intent)
        elif scenario == "infeasible" and assessment["feasible"]:
            assessment = {
                **assessment,
                "feasible": False,
                "feasibility": "none",
                "reasons": ["mock scenario 'infeasible' forced by configuration"],
                "proposal": {"schedule": intent.schedule},
                "counter_proposal": {"adjusted_experience_target": "none: the request cannot be met as stated"},
            }
        if assessment["feasible"]:
            reply = {**base, "message_class": "feasible_request_confirmation", "region": intent.region,
                     "feasibility": "full", "periods": assessment["periods"],
                     "assessment": "The cluster can meet the energy-saving and experience targets.",
                     "expected_outcome": planning.expected_outcome(intent)}
            if scenario == "multiple_solutions":
                reply["solutions"] = planning.solutions(intent)
                reply["assessment"] = "Feasible with any of three solutions; select one to confirm."
            return reply
        return {**base, "message_class": "infeasible_with_proposal", "region": intent.region,
                "feasibility": assessment["feasibility"], "periods": assessment["periods"],
                "reasons": assessment["reasons"], "basis": "; ".join(assessment["reasons"]),
                "proposal": assessment["proposal"], "counter_proposal": assessment.get("counter_proposal")}

    # Task-T ----------------------------------------------------------------

    async def _run_task(self, context: RequestContext, event_queue: EventQueue, metadata: dict[str, Any]) -> None:
        scenario = _scenario(metadata)
        task = Task(
            id=context.task_id or "",
            context_id=context.context_id or "",
            status=TaskStatus(
                state=TaskState.TASK_STATE_SUBMITTED,
                message=_agent_message(context.context_id or "", context.task_id, "Energy-saving task accepted."),
            ),
        )
        await event_queue.enqueue_event(task)

        template = str(metadata.get(TEMPLATE_URI_METADATA_KEY) or ENERGY_SAVING_TEMPLATE_URI)
        if template != ENERGY_SAVING_TEMPLATE_URI:
            await self._status(context, event_queue, TaskState.TASK_STATE_REJECTED,
                               f"Unsupported template {template}; expected {ENERGY_SAVING_TEMPLATE_URI}.")
            return
        try:
            intent = planning.parse_intent(metadata[TASK_T_EXTENSION_URI])
        except planning.IntentError as exc:
            await self._status(context, event_queue, TaskState.TASK_STATE_REJECTED, f"Intent rejected: {exc}")
            return
        if scenario == "reject_task":
            await self._status(context, event_queue, TaskState.TASK_STATE_REJECTED,
                               "Intent rejected: mock scenario 'reject_task'.")
            return
        if scenario == "semantic_rejected":
            await self._status(context, event_queue, TaskState.TASK_STATE_REJECTED,
                               "negotiation.semantic_rejected: task_target does not match the agreed feasibility "
                               "assessment (mock scenario 'semantic_rejected').")
            return

        artifacts = planning.build_artifacts(intent, partial_execution=scenario == "partial_execution")
        for index, body in enumerate(artifacts):
            await self._status(context, event_queue, TaskState.TASK_STATE_WORKING,
                               f"Region {intent.region}: {body['type']} ({index + 1}/{len(artifacts)})")
            await asyncio.sleep(_step_delay(scenario))
            if scenario == "exec_failure" and index == 2:
                await self._fail(context, event_queue, planning.task_error(
                    intent, "cluster_optimization_failed",
                    "cluster optimization did not converge (mock scenario 'exec_failure')", "cluster_optimization"))
                return
            if scenario == "exec_timeout" and index == 4:
                limit = _seconds("MOCK_MAE_EXEC_TIMEOUT_SECONDS", "5")
                await asyncio.sleep(limit)
                await self._fail(context, event_queue, planning.task_error(
                    intent, "execution_timeout", f"cell activation did not finish within {limit:g} s", "activation"))
                return
            await self._artifact(context, event_queue, body)
        report = artifacts[-1]
        text = f"Energy-saving task completed for {intent.region}."
        if report["cells"]["failed"]:
            text = (f"Energy-saving task completed for {intent.region} with {report['cells']['failed']} of "
                    f"{report['cells']['selected']} cells not activated (achievement partial).")
        await self._status(context, event_queue, TaskState.TASK_STATE_COMPLETED, text)

    async def _fail(self, context: RequestContext, event_queue: EventQueue, error: dict[str, Any]) -> None:
        await self._artifact(context, event_queue, error)
        await self._status(context, event_queue, TaskState.TASK_STATE_FAILED,
                           f"{error['code']}: {error['reason']}")

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
        if reply.get("solutions"):
            return f"Feasible with {len(reply['solutions'])} solutions: select one to confirm."
        return "Feasible: please confirm to proceed."
    if message_class == "infeasible_with_proposal":
        verdict = "Partially feasible" if reply.get("feasibility") == "partial" else "Infeasible"
        return f"{verdict}: " + "; ".join(reply.get("reasons") or []) + ". A counter-proposal is attached."
    if message_class == "negotiation_closed":
        chosen = f" (solution {reply['selected_solution']})" if reply.get("selected_solution") else ""
        return f"Negotiation closed: {reply.get('outcome')}{chosen}."
    return f"Negotiation error: {reply.get('error')}"
