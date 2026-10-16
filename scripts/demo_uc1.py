"""End-to-end UC1 smoke run against the local dev stack.

Plays the Energy Agent's part (LLD v10.4 §11.4, §11.5) against the mocks:

1. fetch the power-band tariff from the mock price API,
2. discover the mock MAE in the Registry Center (falls back to MOCK_MAE_URL),
3. check the Orchestration Center is up, accepts the dev login and sees the MAE,
4. run a Negotiation-T feasibility round and accept MAE's verdict (feasible or infeasible),
5. dispatch a Task-T ``ran-energy-saving/v1`` task and stream its artifacts.

Exits non-zero if any step fails, so CI can use it as a smoke test.

    python scripts/demo_uc1.py [--region "Accra Central"] [--scenario auto|feasible|infeasible|...]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any

import httpx
from a2a.client.client import ClientCallContext, ClientConfig
from a2a.client.client_factory import ClientFactory
from a2a.types import AgentCard, Role, SendMessageRequest
from a2a.utils.constants import TransportProtocol
from google.protobuf.json_format import MessageToDict, ParseDict

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mocks.common.a2at import (  # noqa: E402
    ENERGY_SAVING_TEMPLATE_URI,
    FEASIBILITY_ACCEPT_REJECT_TEMPLATE_URI,
    FEASIBILITY_PROPOSE_TEMPLATE_URI,
    NEGOTIATION_T_EXTENSION_URI,
    TASK_T_EXTENSION_URI,
    TEMPLATE_URI_METADATA_KEY,
)
from mocks.common.uc1_messages import (  # noqa: E402
    energy_saving_slots,
    feasibility_accept,
    feasibility_opening,
)
from mocks.mae.server import AGENT_NAME, AGENT_ORGANIZATION  # noqa: E402

PRICE_URL = os.environ.get("ENERGY_AGENT_PRICE_API_BASE_URL", "http://127.0.0.1:8090")
REGISTRY_URL = os.environ.get("REGISTRY_CENTER_URL", "http://127.0.0.1:5000")
MAE_URL = os.environ.get("MOCK_MAE_URL", "http://127.0.0.1:8091")
ORCH_URL = os.environ.get("ORCH_CENTER_URL", "http://127.0.0.1:5001")


def step(text: str) -> None:
    print(f"\n== {text}", flush=True)


def fetch_tariff(http: httpx.Client, region: str) -> dict[str, Any]:
    headers = {}
    if os.environ.get("ENERGY_AGENT_PRICE_API_KEY"):
        headers["X-API-Key"] = os.environ["ENERGY_AGENT_PRICE_API_KEY"]
    response = http.get(f"{PRICE_URL}/v1/tariffs/power-band", params={"region": region}, headers=headers)
    response.raise_for_status()
    tariff = response.json()
    for band in tariff["bands"]:
        print(f"   band {band['band_no']}: {band['min_kw']:.2f}-{band['max_kw']:.2f} kW -> "
              f"{band['charge']:,.2f} {tariff['currency']}")
    return tariff


def discover_mae(http: httpx.Client) -> dict[str, Any]:
    url = f"{REGISTRY_URL}/rest/v1/registry-center/agent-cards/{AGENT_ORGANIZATION}/{AGENT_NAME}"
    try:
        response = http.get(url)
        cards = response.json().get("agentCards", []) if response.status_code == 200 else []
    except httpx.HTTPError as exc:
        print(f"   registry unreachable ({exc}); falling back to {MAE_URL}")
        cards = []
    if cards:
        print(f"   found in Registry Center: {cards[0]['supportedInterfaces'][0]['url']}")
        return cards[0]
    if os.environ.get("DEMO_REQUIRE_REGISTRY") == "1":
        raise SystemExit("mock MAE is not registered in the Registry Center")
    print(f"   not in registry; reading the card from {MAE_URL}")
    return http.get(f"{MAE_URL}/.well-known/agent-card.json").json()


def negotiation_message(content: dict[str, Any], template: str, scenario: str | None) -> SendMessageRequest:
    request = SendMessageRequest()
    request.message.message_id = str(uuid.uuid4())
    request.message.role = Role.ROLE_USER
    request.message.parts.add().text = content["message_class"]
    request.message.metadata[NEGOTIATION_T_EXTENSION_URI] = json.dumps(content)
    request.message.metadata[TEMPLATE_URI_METADATA_KEY] = template
    if scenario:
        request.message.metadata["mockScenario"] = scenario
    return request


async def send(client: Any, request: SendMessageRequest, extension: str) -> list[dict[str, Any]]:
    context = ClientCallContext(service_parameters={"A2A-Extensions": extension})
    return [MessageToDict(event) async for event in client.send_message(request, context=context)]


async def negotiate(client: Any, region: str, tariff: dict[str, Any], scenario: str | None) -> dict[str, Any]:
    opening = feasibility_opening(region, tariff)
    events = await send(client, negotiation_message(opening, FEASIBILITY_PROPOSE_TEMPLATE_URI, scenario),
                        NEGOTIATION_T_EXTENSION_URI)
    reply = json.loads(events[-1]["message"]["metadata"][NEGOTIATION_T_EXTENSION_URI])
    print(f"   MAE: {reply['message_class']}")
    for reason in reply.get("reasons", []):
        print(f"   reason: {reason}")
    if reply["message_class"] not in ("feasible_request_confirmation", "infeasible_with_proposal"):
        return reply
    # Accept either verdict; an accepted infeasible verdict closes as closed_infeasible (LLD v10.4 §5.2).
    accept = feasibility_accept(reply)
    events = await send(client, negotiation_message(accept, FEASIBILITY_ACCEPT_REJECT_TEMPLATE_URI, scenario),
                        NEGOTIATION_T_EXTENSION_URI)
    closed = json.loads(events[-1]["message"]["metadata"][NEGOTIATION_T_EXTENSION_URI])
    print(f"   negotiation closed: {closed['outcome']}")
    return closed


async def dispatch(client: Any, region: str, tariff: dict[str, Any], scenario: str | None) -> str:
    slots = energy_saving_slots(region, tariff)
    request = SendMessageRequest()
    request.message.message_id = str(uuid.uuid4())
    request.message.role = Role.ROLE_USER
    request.message.parts.add().text = slots["task_description"]
    request.message.metadata[TASK_T_EXTENSION_URI] = json.dumps(slots)
    request.message.metadata[TEMPLATE_URI_METADATA_KEY] = ENERGY_SAVING_TEMPLATE_URI
    if scenario:
        request.message.metadata["mockScenario"] = scenario
    final_state = "unknown"
    for event in await send(client, request, TASK_T_EXTENSION_URI):
        if "statusUpdate" in event:
            status = event["statusUpdate"]["status"]
            final_state = status["state"]
            print(f"   [{final_state}] {status['message']['parts'][0]['text']}")
        elif "artifactUpdate" in event:
            body = json.loads(event["artifactUpdate"]["artifact"]["metadata"][TASK_T_EXTENSION_URI])
            print(f"   artifact {body['type']}")
            if body["type"] == "IntentReport":
                print(f"      predicted cost {body['predicted_cost_before']:,.2f} -> "
                      f"{body['predicted_cost_after']:,.2f} {body['currency']} "
                      f"(saving {body['predicted_saving']:,.2f}, {body['sites_changing_band']} sites change band)")
        elif "task" in event:
            final_state = event["task"]["status"]["state"]
            print(f"   [{final_state}] task {event['task']['id']}")
    return final_state


def check_orchestration(http: httpx.Client) -> None:
    response = http.get(f"{ORCH_URL}/health")
    response.raise_for_status()
    password = os.environ.get("ORCH_AUTH_PASSWORD")
    if not password:
        print("   up (ORCH_AUTH_PASSWORD not set, login skipped)")
        return
    login = http.post(f"{ORCH_URL}/rest/v1/orchestrate/auth/login",
                      json={"username": os.environ.get("ORCH_AUTH_USERNAME", "admin"), "password": password})
    login.raise_for_status()
    print(f"   up; logged in as {login.json()['data']['username']}")
    # The login set a session cookie on this client; ask what the Orchestration Center discovers.
    cards = http.get(f"{ORCH_URL}/rest/v1/orchestrate/agent-cards")
    cards.raise_for_status()
    names = [card.get("name") for card in cards.json().get("data", [])]
    print(f"   agents visible to orchestration (via Registry Center): {names}")
    if os.environ.get("DEMO_REQUIRE_REGISTRY") == "1" and AGENT_NAME not in names:
        raise SystemExit(f"{AGENT_NAME} is not visible to the Orchestration Center")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--region", default="Accra Central")
    parser.add_argument("--scenario", default=None, help="mock MAE scenario override")
    parser.add_argument("--skip-orchestration", action="store_true")
    args = parser.parse_args()

    async with httpx.AsyncClient(timeout=30, trust_env=False) as async_http:
        with httpx.Client(timeout=30, trust_env=False) as http:
            step("1. Power-band tariff (mock price API)")
            tariff = fetch_tariff(http, args.region)
            step("2. Discover MAE (Registry Center)")
            card = discover_mae(http)
            if not args.skip_orchestration:
                step("3. Orchestration Center")
                check_orchestration(http)

        factory = ClientFactory(ClientConfig(httpx_client=async_http,
                                             supported_protocol_bindings=[TransportProtocol.HTTP_JSON]))
        client = factory.create(ParseDict(card, AgentCard(), ignore_unknown_fields=True))

        step("4. Feasibility negotiation (Negotiation-T)")
        outcome = await negotiate(client, args.region, tariff, args.scenario)
        if outcome.get("outcome") != "agreed":
            print("\nResult: REJECTED (counter-proposal returned to the user)")
            return 0 if args.scenario == "infeasible" else 1

        step("5. Dispatch energy-saving task (Task-T ran-energy-saving/v1)")
        state = await dispatch(client, args.region, tariff, args.scenario)
        print(f"\nResult: {state}")
        return 0 if state == "TASK_STATE_COMPLETED" else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
