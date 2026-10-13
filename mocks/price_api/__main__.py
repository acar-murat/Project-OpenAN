"""Run the mock price API: ``python -m mocks.price_api`` (host/port from MOCK_PRICE_HOST/PORT)."""

import os

import uvicorn


def main() -> None:
    uvicorn.run(
        "mocks.price_api.app:app",
        host=os.environ.get("MOCK_PRICE_HOST", "127.0.0.1"),
        port=int(os.environ.get("MOCK_PRICE_PORT", "8090")),
    )


if __name__ == "__main__":
    main()
