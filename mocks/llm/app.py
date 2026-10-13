"""Mock OpenAI-compatible chat model for the Orchestration Center.

The Orchestration Center asks a chat model to pick a workflow (PSOP) for every
intent it dispatches, so without a model the Execution Center cannot run
anything. This mock answers that one prompt deterministically: it reads the
"User Intent" and the "Available PSOP Workflows" JSON out of the prompt and
returns the names of the workflows that share the most words with the intent.
Any other prompt gets a fixed reply saying a real model is needed.

``POST /v1/chat/completions`` takes and returns the OpenAI chat shape, which is
what the upstream ``openai_compatible`` provider sends. ``scripts/dev.py setup``
writes a ``models.yaml`` that points the Orchestration Center at this server.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

UNSUPPORTED_REPLY = (
    "The local mock LLM only selects workflows for the Execution Center. "
    "Configure a real model in models.yaml for anything else."
)
WORD = re.compile(r"[a-z0-9]+")
STOP_WORDS = {"a", "an", "and", "the", "for", "of", "to", "in", "on", "with", "by", "run", "please"}

app = FastAPI(title="Mock LLM", version="1.0.0")


class ChatRequest(BaseModel):
    model: str = "mock"
    messages: list[dict[str, Any]] = []


def _words(text: str) -> set[str]:
    return {word for word in WORD.findall(text.lower()) if word not in STOP_WORDS}


def _section(prompt: str, title: str) -> str:
    match = re.search(rf"## {re.escape(title)}\n(.*?)(?=\n## |\Z)", prompt, re.S)
    return match.group(1).strip() if match else ""


def select_workflows(prompt: str) -> list[str] | None:
    """Return workflow names for a PSOP-retrieval prompt, or ``None`` for any other prompt."""
    intent = _section(prompt, "User Intent")
    listing = _section(prompt, "Available PSOP Workflows")
    if not intent or not listing:
        return None
    try:
        workflows = json.loads(listing)
    except json.JSONDecodeError:
        return None
    top_n = int(m.group(1)) if (m := re.search(r"select the top (\d+)", prompt)) else 1
    wanted = _words(intent)
    scored = []
    for index, workflow in enumerate(workflows):
        text = " ".join(str(workflow.get(key, "")) for key in ("name", "description", "user_intent", "tasks"))
        text += " " + " ".join(map(str, workflow.get("tags") or []))
        score = len(wanted & _words(text))
        if score:
            scored.append((-score, index, workflow["name"]))
    return [name for _, _, name in sorted(scored)[:top_n]]


def answer(prompt: str) -> str:
    names = select_workflows(prompt)
    if names is None:
        return UNSUPPORTED_REPLY
    return "```json\n" + json.dumps(names, ensure_ascii=False) + "\n```"


@app.post("/v1/chat/completions")
def chat_completions(request: ChatRequest) -> dict[str, Any]:
    prompt = "\n".join(str(m.get("content", "")) for m in request.messages if m.get("role") != "system")
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": request.model,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": answer(prompt)},
            "finish_reason": "stop",
        }],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
