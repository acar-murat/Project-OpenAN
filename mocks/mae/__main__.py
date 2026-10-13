"""Run the mock MAE: ``python -m mocks.mae``. See ``mocks/mae/server.py`` for settings."""

import logging
import os
import threading

import uvicorn

from mocks.common.registry import register_with_retry
from mocks.mae.server import agent_card_payload, build_app


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    host = os.environ.get("MOCK_MAE_HOST", "127.0.0.1")
    port = int(os.environ.get("MOCK_MAE_PORT", "8091"))
    public_url = os.environ.get("MOCK_MAE_PUBLIC_URL", f"http://{host}:{port}")
    registry_url = os.environ.get("REGISTRY_CENTER_URL")
    if registry_url:
        timeout = float(os.environ.get("MOCK_MAE_REGISTER_TIMEOUT_SECONDS", "60"))
        card = agent_card_payload(public_url)
        threading.Thread(target=register_with_retry, args=(registry_url, card, timeout), daemon=True).start()
    uvicorn.run(build_app(public_url), host=host, port=port)


if __name__ == "__main__":
    main()
