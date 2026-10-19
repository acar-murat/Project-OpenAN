"""Wire details HQ's A2A-T client plugin (``a2a-client-connector``) expects, on top of the a2a SDK.

The plugin's reference server (``mock-a2a-server.mjs``, modelled on a2a-t-sdk-java) differs from
the Python a2a SDK's HTTP+JSON routes in ways the mocks bridge here:

* the AgentCard is fetched with ``GET /`` (the SDK serves ``/.well-known/agent-card.json``);
* SSE frames carry ``id:N`` lines.

Its frames also put ``"final": true`` on the terminal ``statusUpdate``. We do not: A2A 1.0 has no
such field, the a2a SDK client the Energy Agent uses rejects the frame if it is there, and the
plugin stops on the terminal state anyway (``isTerminalClass`` in its index.js). See
docs/henan-demo.md for the full checklist.
"""

from __future__ import annotations

import re
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

VERSION_HEADER = "A2A-Version"
_EVENT_SEPARATOR = re.compile(rb"\r?\n\r?\n")


def version_error(request: Request) -> JSONResponse | None:
    """400 in the plugin's error shape when a non-card call lacks ``A2A-Version``."""
    if request.headers.get(VERSION_HEADER) is None:
        return JSONResponse({"error": {"code": 400, "status": "INVALID_ARGUMENT",
                                       "message": f"missing {VERSION_HEADER} header"}}, status_code=400)
    return None


def _rewrite_event(raw: bytes, seq: int) -> bytes:
    lines = raw.decode("utf-8").splitlines()
    data_lines = [line[5:].lstrip() for line in lines if line.startswith("data:")]
    other = [line for line in lines if not line.startswith(("data:", "id:"))]
    out = [f"id:{seq}", *other, *(f"data:{line}" for line in data_lines)]
    return ("\n".join(out) + "\n\n").encode("utf-8")


class PluginWireMiddleware:
    """ASGI middleware: numbers the SSE frames of ``/message:stream`` (``id:N``)."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http" or not scope["path"].endswith("/message:stream"):
            await self.app(scope, receive, send)
            return
        buffer = b""
        seq = 0

        async def wrapped(message: dict) -> None:
            nonlocal buffer, seq
            if message["type"] != "http.response.body":
                await send(message)
                return
            buffer += message.get("body", b"")
            chunks = _EVENT_SEPARATOR.split(buffer)
            buffer = chunks.pop()
            out = b""
            for chunk in chunks:
                if chunk.strip():
                    seq += 1
                    out += _rewrite_event(chunk, seq)
            more = message.get("more_body", False)
            if not more and buffer.strip():
                seq += 1
                out += _rewrite_event(buffer, seq)
                buffer = b""
            if out or not more:
                await send({"type": "http.response.body", "body": out, "more_body": more})

        await self.app(scope, receive, wrapped)
