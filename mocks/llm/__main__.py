"""Run the mock LLM: ``python -m mocks.llm`` (host/port from MOCK_LLM_HOST/PORT)."""

import os

import uvicorn


def main() -> None:
    uvicorn.run(
        "mocks.llm.app:app",
        host=os.environ.get("MOCK_LLM_HOST", "127.0.0.1"),
        port=int(os.environ.get("MOCK_LLM_PORT", "8093")),
    )


if __name__ == "__main__":
    main()
