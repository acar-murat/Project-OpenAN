"""Run the Henan demo page: ``python -m henan_demo``. See ``henan_demo/app.py``."""

import os

import uvicorn

from henan_demo.app import app


def main() -> None:
    uvicorn.run(app, host=os.environ.get("HENAN_DEMO_HOST", "127.0.0.1"),
                port=int(os.environ.get("HENAN_DEMO_PORT", "8094")))


if __name__ == "__main__":
    main()
