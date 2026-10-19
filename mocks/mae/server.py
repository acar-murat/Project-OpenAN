"""HTTP server, AgentCard and Registry Center registration for the mock MAE.

Run with ``python -m mocks.mae``. Environment:

* ``MOCK_MAE_HOST`` / ``MOCK_MAE_PORT``: bind address (default 127.0.0.1:8091).
* ``MOCK_MAE_PUBLIC_URL``: URL put in the AgentCard (default ``http://<host>:<port>``).
* ``REGISTRY_CENTER_URL``: when set, the card is registered there on startup
  (``POST /rest/v1/registry-center/agent-cards``); failures are logged, not fatal.
* ``REGISTRY_ACCESS_TOKEN``: optional bearer token for the registration call.

Besides the SDK's routes it serves what HQ's A2A-T client plugin expects (docs/henan-demo.md):
the AgentCard at ``/``, ``/ops/omc/status`` and ``/ops/omc/advice``, numbered SSE frames with a
final flag, and the ``ran-complaint-optimization`` skill (``mocks.mae.optimization``).
"""

from __future__ import annotations

from typing import Any

from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_rest_routes
from a2a.server.tasks.inmemory_task_store import InMemoryTaskStore
from a2a.types import AgentCard
from google.protobuf.json_format import ParseDict
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from mocks.common.a2at import NEGOTIATION_T_EXTENSION_URI, TASK_T_EXTENSION_URI
from mocks.common.plugin_wire import PluginWireMiddleware, version_error
from mocks.mae.executor import ENERGY_SAVING_SKILL, OPTIMIZATION_SKILL, MockMaeExecutor
from mocks.mae.optimization import MISSING, WorkOrderStore

AGENT_NAME = "Mock MAE"
AGENT_ORGANIZATION = "OpenAN Mock"


def agent_card_payload(public_url: str) -> dict[str, Any]:
    """AgentCard for the mock. Real values are open item O-3."""
    return {
        "name": AGENT_NAME,
        "description": (
            "Development stand-in for the MAE RAN Agent: RAN energy saving (Task-T ran-energy-saving/v1), "
            "feasibility negotiation (Negotiation-T) and complaint work-order optimisation."
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
                "id": ENERGY_SAVING_SKILL,
                "name": "RAN energy saving",
                "description": "Plans and activates power-band energy saving for a region's cluster and "
                               "streams the plan and intent report as artifacts. Needs region (Task-T "
                               "task_object, or 'region: <name>' in the text).",
                "tags": ["energy saving", "execution"],
                "examples": ["Create a RAN energy-saving task for Accra Central Region to maximize energy savings.",
                             "region: Zhengzhou"],
            },
            {
                "id": OPTIMIZATION_SKILL,
                "name": "RAN complaint optimisation",
                "description": "Creates or re-attaches to a complaint work order and returns "
                               "serviceManagement.RanOptimizationResult (root cause and parameter advice). "
                               "Required: objectId (cell CGI), problemType (OMC standard code); optional "
                               "issueId, rat (default NR). Send them as a JSON block or 'key: value' lines.",
                "tags": ["optimisation", "work order", "complaint"],
                "examples": ['{"issueId": "HN-ZZ-JS-20261015-00031752", "objectId": "460-00-617089-1103", '
                             '"problemType": "UP_LOW_THROUGHPUT"}'],
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
    payload = agent_card_payload(public_url)
    card = ParseDict(payload, AgentCard())
    work_orders = WorkOrderStore()
    handler = DefaultRequestHandler(agent_executor=MockMaeExecutor(work_orders), task_store=InMemoryTaskStore(),
                                    agent_card=card)

    async def health(_request: Any) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    async def root_card(_request: Any) -> JSONResponse:
        return JSONResponse(payload)

    def ops(key: str, lookup: Any) -> Any:
        async def endpoint(request: Request) -> JSONResponse:
            if error := version_error(request):
                return error
            issue_id = request.query_params.get("issueId", "").strip()
            if not issue_id:
                return JSONResponse({"error": {"code": 400, "status": "INVALID_ARGUMENT",
                                               "message": f"{MISSING}：issueId"}}, status_code=400)
            return JSONResponse({key: lookup(issue_id)})
        return endpoint

    async def ledger(_request: Any) -> JSONResponse:
        return JSONResponse(work_orders.ledger())

    return Starlette(routes=[
        Route("/", root_card),
        Route("/health", health),
        Route("/ops/omc/status", ops("statuses", work_orders.statuses)),
        Route("/ops/omc/advice", ops("advices", work_orders.advices)),
        Route("/mock/work-orders", ledger),
        *create_agent_card_routes(card),
        *create_rest_routes(handler),
    ], middleware=[Middleware(PluginWireMiddleware)])

