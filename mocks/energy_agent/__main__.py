"""Run the mock Energy Agent: ``python -m mocks.energy_agent``. See ``mocks/energy_agent/server.py``."""

import asyncio
import logging
import os
import threading

from a2a.types import AgentCard
from google.protobuf.json_format import ParseDict
from host_agent.service import start_agent_server

from mocks.common.registry import register_with_retry
from mocks.energy_agent.server import agent_card_payload, build_executor, save_workflow_with_retry


def announce(payload: dict, timeout: float) -> None:
    """Save the UC1 workflow first, then register: once the card is listed, the workflow exists too."""
    orch_url = os.environ.get("ORCH_CENTER_URL")
    if orch_url:
        save_workflow_with_retry(orch_url, timeout)
    registry_url = os.environ.get("REGISTRY_CENTER_URL")
    if registry_url:
        register_with_retry(registry_url, payload, timeout)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    host = os.environ.get("MOCK_ENERGY_AGENT_HOST", "127.0.0.1")
    port = int(os.environ.get("MOCK_ENERGY_AGENT_PORT", "8092"))
    public_url = os.environ.get("MOCK_ENERGY_AGENT_PUBLIC_URL", f"http://{host}:{port}")
    payload = agent_card_payload(public_url)
    timeout = float(os.environ.get("MOCK_ENERGY_AGENT_REGISTER_TIMEOUT_SECONDS", "60"))
    threading.Thread(target=announce, args=(payload, timeout), daemon=True).start()
    asyncio.run(start_agent_server(ParseDict(payload, AgentCard()), build_executor(), port=port, host=host))


if __name__ == "__main__":
    main()
