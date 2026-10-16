"""Mock OpenAI-compatible chat model for the energy-saving function.

It answers the three LLM use cases in ``mocks.llm.prompts`` deterministically, so the dev stack
and CI run without a model key:

* ``select`` (the Orchestration Center's workflow pick): reads the "User Intent" and the
  "Available PSOP Workflows" JSON out of the prompt and returns the workflow whose text shares the
  most concepts with the intent. Words are folded into concepts first ("bill", "tariff" and
  "cost" are one concept; so are "cut", "reduce" and "save"), so the pick does not hinge on the
  user saying "power-band energy saving". A workflow is skipped when the intent names a
  specialised concept it lacks (battery, cell sleep, fault, past runs), and needs two shared
  concepts, one of them more specific than "save" or "report", to count.
* ``classify`` (OSS): energy wording plus saving wording, and not a question, is an
  energy-saving intent.
* ``extract`` (OSS): region, saving mode and experience target from fixed patterns.

Any other prompt gets a fixed reply saying a real model is needed. ``mocks/llm/cases.py`` lists
the wordings it handles and the ones only a real model does (``scripts/llm_eval.py`` runs both).

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

from mocks.energy_agent.workflow import find_region
from mocks.llm.prompts import CLASSIFY_MARKER, EXTRACT_MARKER

UNSUPPORTED_REPLY = (
    "The local mock LLM only selects workflows and screens energy-saving intents. "
    "Configure a real model in models.yaml for anything else."
)
WORD = re.compile(r"[a-z0-9çğıöşü]+")
STOP_WORDS = {"a", "an", "and", "the", "for", "of", "to", "in", "on", "at", "with", "by", "run", "please", "our",
              "my", "this", "it", "is", "be", "from", "region", "workflow", "intent"}
#: Word -> concept. Words not listed are their own concept.
CONCEPTS = {
    **dict.fromkeys(["energy", "power", "electricity", "electric", "kw", "kwh", "consumption", "watt", "enerji",
                     "elektrik", "güç"], "energy"),
    **dict.fromkeys(["save", "saves", "saving", "savings", "saved", "reduce", "reduction", "cut", "lower",
                     "lowering", "decrease", "minimise", "minimize", "optimise", "optimize", "optimization",
                     "optimisation", "cheap", "cheaper", "efficiency", "efficient", "maximise", "maximize", "tasarruf",
                     "tasarrufu", "azalt", "düşür"],
                    "saving"),
    **dict.fromkeys(["cost", "costs", "bill", "bills", "tariff", "tariffs", "charge", "charges", "price", "prices",
                     "pricing", "expense", "cedi", "cedis", "ghs", "money", "spend", "fatura", "maliyet"], "cost"),
    **dict.fromkeys(["band", "bands", "tier", "tiers"], "band"),
    **dict.fromkeys(["battery", "batteries", "lithium", "discharge", "discharging"], "battery"),
    **dict.fromkeys(["sleep", "shutdown", "shut", "switch", "off", "carriers", "carrier"], "sleep"),
    **dict.fromkeys(["fault", "faults", "failure", "outage", "outages", "diagnose", "diagnosis", "broken"], "fault"),
    **dict.fromkeys(["past", "last", "previous", "history", "achieved", "actually"], "history"),
    **dict.fromkeys(["site", "sites", "cell", "cells"], "site"),
}
#: Concepts that name a different kind of workflow: an intent that names one only matches workflows that
#: have it, and a workflow that has one loses a point for every intent that does not name it.
SPECIALISED = {"battery", "sleep", "fault", "history"}
#: Concepts too general to pick a workflow on their own ("Save the report as PDF" is not energy saving).
GENERIC = {"saving", "report"}
QUESTION = re.compile(r"^\s*(how|what|which|did|does|was|were|show|list|when|why)\b|\?\s*$", re.I)

app = FastAPI(title="Mock LLM", version="1.0.0")


class ChatRequest(BaseModel):
    model: str = "mock"
    messages: list[dict[str, Any]] = []


def _words(text: str) -> set[str]:
    return {CONCEPTS.get(word, word) for word in WORD.findall(text.lower()) if word not in STOP_WORDS}


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
        offered = _words(text)
        if (wanted & SPECIALISED) - offered:
            continue
        shared = wanted & offered
        score = len(shared) - len((offered & SPECIALISED) - wanted)
        if score >= 2 and shared - GENERIC:
            scored.append((-score, index, workflow["name"]))
    return [name for _, _, name in sorted(scored)[:top_n]]


def classify(text: str) -> dict[str, Any]:
    """``{is_energy_saving_intent, confidence}`` for the OSS classifier prompt."""
    concepts = _words(text)
    energy = bool(concepts & {"energy", "cost", "band"})
    saving = "saving" in concepts
    if energy and saving and not QUESTION.search(text):
        return {"is_energy_saving_intent": True, "confidence": 0.9}
    return {"is_energy_saving_intent": False, "confidence": 0.6 if energy or saving else 0.95}


def extract(text: str) -> dict[str, Any]:
    """Region, saving mode and experience target for the OSS extraction prompt (null when not stated)."""
    lower = text.lower()
    if re.search(r"\bmaximi[sz]e|\bmaximum\b|\bmaximized\b", lower):
        mode = "maximized_energy_saving"
    elif "experience first" in lower or "experience-first" in lower:
        mode = "experience_first"
    elif re.search(r"\bproactive\b|\bat least\b|\bfloor\b", lower):
        mode = "proactive_energy_saving"
    else:
        mode = None
    if match := re.search(r"(\d+(?:\.\d+)?)\s*mbps", lower):
        number = float(match.group(1))
        target = {"type": "rate_floor", "mbps": int(number) if number.is_integer() else number}
    elif re.search(r"no (?:\w+ )?degradation|without degrad", lower):
        target = {"type": "no_degradation"}
    elif re.search(r"no (?:rate |experience )?(?:guarantee|target)", lower):
        target = {"type": "none"}
    else:
        target = None
    return {"region": find_region(text), "saving_mode": mode, "experience_target": target}


def _fenced(value: Any) -> str:
    return "```json\n" + json.dumps(value, ensure_ascii=False) + "\n```"


def answer(prompt: str) -> str:
    if CLASSIFY_MARKER in prompt:
        return _fenced(classify(_section(prompt, "User Text")))
    if EXTRACT_MARKER in prompt:
        return _fenced(extract(_section(prompt, "User Text")))
    names = select_workflows(prompt)
    if names is None:
        return UNSUPPORTED_REPLY
    return _fenced(names)


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
