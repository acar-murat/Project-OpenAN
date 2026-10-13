"""Energy-saving ControlPoint: the business decisions the host agent runtime delegates.

``on_self_task`` runs the Energy Agent's own steps (tariff, feasibility, report);
``on_task`` builds the Task-T content the workflow engine sends to MAE. One
instance serves one workflow execution, so it keeps the region and tariff it
fetched for the later steps.
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

from mocks.common import registry
from mocks.common.a2at import (
    ENERGY_SAVING_TEMPLATE_URI,
    FEASIBILITY_ACCEPT_REJECT_TEMPLATE_URI,
    FEASIBILITY_PROPOSE_TEMPLATE_URI,
    NEGOTIATION_T_EXTENSION_URI,
    TASK_T_EXTENSION_URI,
    TEMPLATE_URI_METADATA_KEY,
)
from mocks.common.uc1_messages import energy_saving_slots, feasibility_accept, feasibility_opening
from mocks.energy_agent import workflow
from mocks.mae.server import AGENT_ORGANIZATION as MAE_ORGANIZATION

SCENARIO_METADATA_KEY = "mockScenario"


class EnergySavingControlPoint(ControlPoint):
    def __init__(self, *, price_url: str, registry_url: str, mae_url: str) -> None:
        self._price_url = price_url.rstrip("/")
        self._registry_url = registry_url
        self._mae_url = mae_url.rstrip("/")
        self._region: str | None = None
        self._scenario: str | None = None
        self._tariff: dict[str, Any] | None = None

    @classmethod
    def from_env(cls) -> EnergySavingControlPoint:
        return cls(
            price_url=os.environ.get("ENERGY_AGENT_PRICE_API_BASE_URL", "http://127.0.0.1:8090"),
            registry_url=os.environ.get("REGISTRY_CENTER_URL", "http://127.0.0.1:5000"),
            mae_url=os.environ.get("MOCK_MAE_URL", "http://127.0.0.1:8091"),
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
            async with httpx.AsyncClient(timeout=30, trust_env=False) as http:
                headers = {}
                if os.environ.get("ENERGY_AGENT_PRICE_API_KEY"):
                    headers["X-API-Key"] = os.environ["ENERGY_AGENT_PRICE_API_KEY"]
                response = await http.get(f"{self._price_url}/v1/tariffs/power-band",
                                          params={"region": self._region}, headers=headers)
                response.raise_for_status()
                self._tariff = response.json()
        return self._tariff

    async def _fetch_tariff(self, _request) -> TaskResult:
        tariff = await self._tariff_or_fetch()
        rows = [f"| {b['band_no']} | {b['min_kw']:.2f} to {b['max_kw']:.2f} | {b['charge']:,.2f} |"
                for b in tariff["bands"]]
        return TaskResult.succeeded((
            f"**Power-band tariff for {self._region}** ({tariff['currency']}, {tariff['billing_period']})\n\n"
            f"| Band | Power draw (kW) | Charge per site |\n|---|---|---|\n" + "\n".join(rows),
        ))

    async def _negotiate_feasibility(self, _request) -> TaskResult:
        tariff = await self._tariff_or_fetch()
        async with httpx.AsyncClient(timeout=30, trust_env=False) as http:
            card = await self._mae_card(http)
            factory = ClientFactory(ClientConfig(httpx_client=http,
                                                 supported_protocol_bindings=[TransportProtocol.HTTP_JSON]))
            client = factory.create(ParseDict(card, AgentCard(), ignore_unknown_fields=True))
            reply = await self._negotiation_round(
                client, feasibility_opening(self._region, tariff), FEASIBILITY_PROPOSE_TEMPLATE_URI)
            if reply.get("message_class") != "feasible_request_confirmation":
                reasons = "; ".join(reply.get("reasons") or []) or reply.get("error") or "no reason given"
                proposal = json.dumps(reply.get("proposal"), ensure_ascii=False)
                return TaskResult.failed(
                    "energy_agent.infeasible",
                    f"MAE: {self._region} is not feasible as requested ({reasons}). Counter-proposal: {proposal}",
                )
            closed = await self._negotiation_round(
                client, feasibility_accept(reply), FEASIBILITY_ACCEPT_REJECT_TEMPLATE_URI)
        return TaskResult.succeeded((
            f"MAE: {reply.get('assessment', 'feasible')} Energy Agent accepted; "
            f"negotiation {closed.get('outcome', 'closed')} (id {reply['negotiation_id']}).",
        ))

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
        return TaskResult.succeeded(("\n".join(lines),))

    # MAE access -----------------------------------------------------------------

    async def _mae_card(self, http: httpx.AsyncClient) -> dict[str, Any]:
        card = await asyncio.to_thread(registry.find_card, self._registry_url, MAE_ORGANIZATION, workflow.MAE_NAME)
        if card:
            return card
        response = await http.get(f"{self._mae_url}/.well-known/agent-card.json")
        response.raise_for_status()
        return response.json()

    async def _negotiation_round(self, client: Any, content: dict[str, Any], template: str) -> dict[str, Any]:
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
        return json.loads(events[-1]["message"]["metadata"][NEGOTIATION_T_EXTENSION_URI])
