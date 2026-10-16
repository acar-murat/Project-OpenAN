"""Run the mock Energy Agent: ``python -m mocks.energy_agent``. See ``mocks/energy_agent/server.py``."""

import asyncio
import logging
import os
import ssl
import threading

import uvicorn
from a2a.types import AgentCard
from google.protobuf.json_format import ParseDict
from host_agent.service import create_agent_app

from mocks.common import audit
from mocks.common.registry import register_with_retry
from mocks.energy_agent.caller_auth import AllowedCallers, CallerAuthMiddleware
from mocks.energy_agent.server import agent_card_payload, build_executor, save_workflow_with_retry


def announce(payload: dict, timeout: float) -> None:
    """Save the UC1 workflow first, then register: once the card is listed, the workflow exists too."""
    orch_url = os.environ.get("ORCH_CENTER_URL")
    if orch_url:
        save_workflow_with_retry(orch_url, timeout)
    registry_url = os.environ.get("REGISTRY_CENTER_URL")
    if registry_url:
        register_with_retry(registry_url, payload, timeout)


def tls_options() -> dict:
    """uvicorn TLS settings; with a client CA, a TLS client without a certificate from it is refused (mTLS)."""
    cert, key = os.environ.get("MOCK_ENERGY_AGENT_TLS_CERT"), os.environ.get("MOCK_ENERGY_AGENT_TLS_KEY")
    if not (cert and key):
        return {}
    options = {"ssl_certfile": cert, "ssl_keyfile": key}
    if client_ca := os.environ.get("MOCK_ENERGY_AGENT_TLS_CLIENT_CA"):
        options |= {"ssl_ca_certs": client_ca, "ssl_cert_reqs": ssl.CERT_REQUIRED}
    return options


async def serve(card: AgentCard, executor, host: str, port: int) -> None:
    """``host_agent.service.start_agent_server`` with caller authentication in front of the A2A routes.

    Same app and executor lifecycle; built here because the upstream helper has no hook for
    request middleware, and upstream code is not changed (LLD v10.4 §0.0).
    """
    log_path = os.environ.get("ENERGY_AGENT_AUDIT_LOG_PATH")
    app = CallerAuthMiddleware(create_agent_app(card, executor), AllowedCallers.from_env(),
                               audit.AuditLog.shared(log_path) if log_path else None)
    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, timeout_graceful_shutdown=2, **tls_options()))
    await executor.start()
    try:
        await server.serve()
    finally:
        await executor.aclose()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    host = os.environ.get("MOCK_ENERGY_AGENT_HOST", "127.0.0.1")
    port = int(os.environ.get("MOCK_ENERGY_AGENT_PORT", "8092"))
    public_url = os.environ.get("MOCK_ENERGY_AGENT_PUBLIC_URL", f"http://{host}:{port}")
    payload = agent_card_payload(public_url)
    timeout = float(os.environ.get("MOCK_ENERGY_AGENT_REGISTER_TIMEOUT_SECONDS", "60"))
    threading.Thread(target=announce, args=(payload, timeout), daemon=True).start()
    asyncio.run(serve(ParseDict(payload, AgentCard()), build_executor(), host, port))


if __name__ == "__main__":
    main()
