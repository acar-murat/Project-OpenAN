"""Run the mock MAE: ``python -m mocks.mae``. See ``mocks/mae/server.py`` for settings."""

import logging
import os
import threading
import time

import uvicorn

from mocks.mae.server import build_app, register


def register_with_retry(registry_url: str, public_url: str, timeout: float) -> None:
    """Keep trying until the Registry Center accepts the card (it may start after this process)."""
    deadline = time.monotonic() + timeout
    while not register(registry_url, public_url) and time.monotonic() < deadline:
        time.sleep(2)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    host = os.environ.get("MOCK_MAE_HOST", "127.0.0.1")
    port = int(os.environ.get("MOCK_MAE_PORT", "8091"))
    public_url = os.environ.get("MOCK_MAE_PUBLIC_URL", f"http://{host}:{port}")
    registry_url = os.environ.get("REGISTRY_CENTER_URL")
    if registry_url:
        timeout = float(os.environ.get("MOCK_MAE_REGISTER_TIMEOUT_SECONDS", "60"))
        threading.Thread(target=register_with_retry, args=(registry_url, public_url, timeout), daemon=True).start()
    uvicorn.run(build_app(public_url), host=host, port=port)


if __name__ == "__main__":
    main()
