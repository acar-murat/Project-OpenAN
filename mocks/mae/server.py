"""HTTP server, AgentCard and Registry Center registration for the mock MAE.

Run with ``python -m mocks.mae``. Environment:

* ``MOCK_MAE_HOST`` / ``MOCK_MAE_PORT``: bind address (default 127.0.0.1:8091).
* ``MOCK_MAE_PUBLIC_URL``: URL put in the AgentCard (default ``http://<host>:<port>``).
* ``REGISTRY_CENTER_URL``: when set, the card is registered there on startup
  (``POST /rest/v1/registry-center/agent-cards``); failures are logged, not fatal.
* ``REGISTRY_ACCESS_TOKEN``: optional bearer token for the registration call.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_rest_routes
from a2a.server.tasks.inmemory_task_store import InMemoryTaskStore
from a2a.types import AgentCard
from google.protobuf.json_format import ParseDict
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from mocks.common.a2at import NEGOTIATION_T_EXTENSION_URI, TASK_T_EXTENSION_URI
from mocks.mae.executor import MockMaeExecutor

log = logging.getLogger("mock-mae")

AGENT_NAME = "Mock MAE"
AGENT_ORGANIZATION = "OpenAN Mock"


def agent_card_payload(public_url: str) -> dict[str, Any]:
    """AgentCard for the mock. Real values are open item O-3."""
    return {
        "name": AGENT_NAME,
        "description": (
            "Development stand-in for MAE: RAN energy saving (Task-T ran-energy-saving/v1) and "
            "feasibility negotiation (Negotiation-T) for UC1 power-band energy saving."
        ),
        "version": "1.0.0",
        "provider": {"organization": AGENT_ORGANIZATION, "url": "https://github.com/acar-murat/Project-OpenAN"},
        "defaultInputModes": ["application/json", "text/plain"],
        "defaultOutputModes": ["application/json", "text/plain"],
        "capabilities": {
            "streaming": True,
            "pushNotifications": False,
            "extensions": [
                {"uri": TASK_T_EXTENSION_URI, "description": "Structured Task-T requests.", "required": False},
                {"uri": NEGOTIATION_T_EXTENSION_URI, "description": "Structured Negotiation-T requests.",
                 "required": False},
            ],
        },
        "skills": [
            {
                "id": "energy-saving",
                "name": "RAN energy saving",
                "description": "Plans and activates power-band energy saving for a region's cluster and "
                               "streams the plan and intent report as artifacts.",
                "tags": ["energy saving", "execution"],
                "examples": ["Create a RAN energy-saving task for Accra Central Region to maximize energy savings."],
            },
            {
                "id": "feasibility-negotiation",
                "name": "Energy-saving feasibility negotiation",
                "description": "Assesses whether an energy-saving intent is feasible and proposes changes if not.",
                "tags": ["energy saving", "negotiation"],
            },
        ],
        "supportedInterfaces": [
            {"url": public_url, "protocolBinding": "HTTP+JSON", "protocolVersion": "1.0.0"}
        ],
    }


def build_app(public_url: str) -> Starlette:
    card = ParseDict(agent_card_payload(public_url), AgentCard())
    handler = DefaultRequestHandler(agent_executor=MockMaeExecutor(), task_store=InMemoryTaskStore(), agent_card=card)

    async def health(_request: Any) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    return Starlette(routes=[
        Route("/health", health),
        *create_agent_card_routes(card),
        *create_rest_routes(handler),
    ])


def register(registry_url: str, public_url: str) -> bool:
    headers = {}
    token = os.environ.get("REGISTRY_ACCESS_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    url = registry_url.rstrip("/") + "/rest/v1/registry-center/agent-cards"
    try:
        response = httpx.post(url, json={"agentCards": [agent_card_payload(public_url)]},
                              headers=headers, timeout=10, trust_env=False)
    except httpx.HTTPError as exc:
        log.warning("registry registration failed: %s", exc)
        return False
    if response.status_code in (200, 201):
        log.info("registered %s with %s", AGENT_NAME, registry_url)
        return True
    if response.status_code == 409:
        log.info("%s already registered with %s", AGENT_NAME, registry_url)
        return True
    log.warning("registry registration failed: HTTP %s %s", response.status_code, response.text[:300])
    return False
