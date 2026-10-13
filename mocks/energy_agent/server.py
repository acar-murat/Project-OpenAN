"""AgentCard and host-agent composition for the mock Energy Agent.

Environment:

* ``MOCK_ENERGY_AGENT_HOST`` / ``MOCK_ENERGY_AGENT_PORT``: bind address (default 127.0.0.1:8092).
* ``MOCK_ENERGY_AGENT_PUBLIC_URL``: URL put in the AgentCard (default ``http://<host>:<port>``).
* ``ORCH_CENTER_URL`` / ``REGISTRY_CENTER_URL``: where the host runtime loads workflows and AgentCards.
* ``ORCH_AUTH_USERNAME`` / ``ORCH_AUTH_PASSWORD``: login used to save the UC1 workflow in the
  Orchestration Center on startup (``scripts/dev.py setup`` puts both in ``.dev/dev.env``).
* ``ENERGY_AGENT_PRICE_API_BASE_URL``, ``MOCK_MAE_URL``: used by the ControlPoint.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import httpx
from host_agent import HostAgentConfig, HostAgentExecutor

from mocks.energy_agent import workflow
from mocks.energy_agent.control_point import EnergySavingControlPoint

log = logging.getLogger("mock-energy-agent")


def agent_card_payload(public_url: str) -> dict[str, Any]:
    return {
        "name": workflow.AGENT_NAME,
        "description": (
            "Development stand-in for the Energy Agent. Hosts the UC1 power-band energy-saving workflow: "
            "fetches the tariff, negotiates feasibility with MAE, dispatches the RAN energy-saving task "
            "and reports the predicted saving. Pick it as the host agent in the Execution Center."
        ),
        "version": "1.0.0",
        "provider": {"organization": workflow.AGENT_ORGANIZATION,
                     "url": "https://github.com/acar-murat/Project-OpenAN"},
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain", "application/json"],
        "capabilities": {"streaming": True, "pushNotifications": False},
        "skills": [
            {
                "id": "uc1-energy-saving-workflow",
                "name": "UC1 power-band energy saving",
                "description": "Runs the UC1 workflow for a region and streams every step.",
                "tags": ["energy saving", "host agent", "workflow"],
                "examples": [workflow.EXAMPLE_INTENT],
            },
            {"id": workflow.SKILL_TARIFF, "name": "Power-band tariff",
             "description": "Fetches the region's power-band tariff from the price API.", "tags": ["price"]},
            {"id": workflow.SKILL_FEASIBILITY, "name": "Feasibility negotiation with MAE",
             "description": "Runs the Negotiation-T feasibility round with MAE.", "tags": ["negotiation"]},
            {"id": workflow.SKILL_REPORT, "name": "Intent report",
             "description": "Summarises MAE's artifacts as the intent report.", "tags": ["report"]},
        ],
        "supportedInterfaces": [
            {"url": public_url, "protocolBinding": "HTTP+JSON", "protocolVersion": "1.0.0"}
        ],
    }


def build_executor() -> HostAgentExecutor:
    return HostAgentExecutor(
        config=HostAgentConfig(
            orchestration_url=os.environ.get("ORCH_CENTER_URL", "http://127.0.0.1:5001"),
            registry_url=os.environ.get("REGISTRY_CENTER_URL", "http://127.0.0.1:5000"),
        ),
        control_point_factory=lambda _context: EnergySavingControlPoint.from_env(),
    )


def save_workflow(orch_url: str) -> bool:
    """Save the UC1 workflow in the Orchestration Center; the same id each time, so restarts overwrite it."""
    login = {"username": os.environ.get("ORCH_AUTH_USERNAME", "admin"),
             "password": os.environ.get("ORCH_AUTH_PASSWORD", "")}
    psop = workflow.psop()
    try:
        with httpx.Client(base_url=orch_url, timeout=10, trust_env=False) as http:
            http.post("/rest/v1/orchestrate/auth/login", json=login).raise_for_status()
            http.post("/rest/v1/orchestrate/workflows", json={"psop": psop}).raise_for_status()
    except httpx.HTTPError as exc:
        log.warning("saving the workflow in the Orchestration Center failed: %s", exc)
        return False
    log.info("saved workflow '%s' in %s", psop["name"], orch_url)
    return True


def save_workflow_with_retry(orch_url: str, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while not save_workflow(orch_url) and time.monotonic() < deadline:
        time.sleep(2)
