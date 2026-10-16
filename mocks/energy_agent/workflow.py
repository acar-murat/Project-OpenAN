"""The UC1 workflow (PSOP) the Orchestration Center runs through the mock Energy Agent.

Four steps, in order:

1. ``power_band_tariff``: the Energy Agent fetches the tariff from the price API.
2. ``feasibility_negotiation``: the Energy Agent negotiates feasibility with MAE (Negotiation-T).
3. ``ran_energy_saving``: the workflow engine dispatches Task-T ``ran-energy-saving/v1`` to MAE
   and collects its six artifacts.
4. ``intent_report``: the Energy Agent turns MAE's artifacts into a readable report.

Steps 1, 2 and 4 are ``SelfLoop`` steps (run inside the host agent); step 3 is a
normal agent task, so it shows up in the Execution Center as a call to Mock MAE.
``layer`` is each step's depth in the graph (the workflow engine requires 0 for the root).
"""

from __future__ import annotations

import re
from typing import Any

AGENT_NAME = "Mock Energy Agent"
AGENT_ORGANIZATION = "OpenAN Mock"
#: ``mocks.mae.server.AGENT_NAME``; kept as a literal so ``scripts/dev.py`` can import this module
#: without the a2a SDK (a test checks they match).
MAE_NAME = "Mock MAE"
DEFAULT_REGION = "Accra Central"
WORKFLOW_ID = "psop_uc1_power_band_energy_saving"
WORKFLOW_NAME = "UC1 power-band energy saving"
EXAMPLE_INTENT = "Run power-band energy saving for Accra Central"

SKILL_TARIFF = "power-band-tariff"
SKILL_FEASIBILITY = "feasibility-negotiation"
SKILL_ENERGY_SAVING = "energy-saving"
SKILL_REPORT = "intent-report"

SCENARIO = re.compile(r"\bscenario\s*[:=]\s*([a-z_]+)", re.I)
#: Regions the mocks know (mock MAE plans any region; these are the ones the tests use).
KNOWN_REGIONS = ("Accra Central", "Kumasi", "Tamale", "Takoradi", "Cape Coast")
#: "region: Kumasi", a known region in any case and wording, or "for/in/at Accra Central [Region]"
#: (capitalised words after the preposition).
REGION_FIELD = re.compile(r"\bregion\s*[:=]\s*\"?([^\"\n;,]+)", re.I)
KNOWN_REGION = re.compile("|".join(re.escape(region) for region in KNOWN_REGIONS), re.I)
REGION_AFTER = re.compile(r"\b(?:for|in|at)\s+((?:[A-Z][\w'-]*)(?:\s+[A-Z][\w'-]*)*)")


def _step(name: str, agent: str, skill: str, description: str, *, step_type: str, layer: int,
          next_step: str, context_from: list[str] | None = None) -> dict[str, Any]:
    return {
        "name": name,
        "type": step_type,
        "subtasks": [{"task_id": f"task-{name}", "description": description, "agent": agent, "skill": skill,
                      "status": "pending"}],
        "next": [{"step": next_step, "condition": ""}],
        "layer": layer,
        "context_from": context_from,
    }


def psop() -> dict[str, Any]:
    """The PSOP document ``scripts/dev.py`` saves in the Orchestration Center."""
    return {
        "id": WORKFLOW_ID,
        "name": WORKFLOW_NAME,
        "description": (
            "UC1 (MTN power-band energy saving): fetch the power-band tariff, negotiate feasibility "
            "with MAE, dispatch the RAN energy-saving task to MAE and report the predicted saving."
        ),
        "steps": [
            _step("power_band_tariff", AGENT_NAME, SKILL_TARIFF,
                  "Fetch the power-band tariff for the region from the price API",
                  step_type="SelfLoop", layer=0, next_step="feasibility_negotiation"),
            _step("feasibility_negotiation", AGENT_NAME, SKILL_FEASIBILITY,
                  "Negotiate feasibility of the energy-saving intent with MAE (Negotiation-T)",
                  step_type="SelfLoop", layer=1, next_step="ran_energy_saving",
                  context_from=["power_band_tariff"]),
            _step("ran_energy_saving", MAE_NAME, SKILL_ENERGY_SAVING,
                  "Plan and activate power-band energy saving (Task-T ran-energy-saving/v1)",
                  step_type="AllSuccess", layer=2, next_step="intent_report",
                  context_from=["feasibility_negotiation"]),
            _step("intent_report", AGENT_NAME, SKILL_REPORT,
                  "Report the predicted monthly cost and saving from MAE's artifacts",
                  step_type="SelfLoop", layer=3, next_step="end", context_from=["ran_energy_saving"]),
        ],
        # Phrased with the words users actually use (bill, electricity cost, power consumption, tariff)
        # so workflow selection does not depend on the user saying "power-band energy saving".
        "user_intent": "Power-band energy saving for a region: cut the sites' electricity bill and power "
                       "consumption by lowering their monthly power-band (tariff) charges while keeping the "
                       "experience targets (UC1)",
        "tags": ["energy saving", "power band", "electricity cost", "power consumption", "tariff", "UC1", "RAN",
                 "MAE"],
        "source": "template",
    }


def find_region(intent: str) -> str | None:
    """The region an intent names ("... for Accra Central", "in kumasi"), or None."""
    text = SCENARIO.sub("", intent)
    if match := REGION_FIELD.search(text):
        region = match.group(1).strip()
    elif match := KNOWN_REGION.search(text):
        return next(r for r in KNOWN_REGIONS if r.lower() == match.group(0).lower())
    elif match := REGION_AFTER.search(text):
        region = match.group(1).strip()
    else:
        return None
    return re.sub(r"\s+region$", "", region, flags=re.I) or None


def region_of(intent: str) -> str:
    """The region an intent names, or the UC1 default."""
    return find_region(intent) or DEFAULT_REGION


def scenario_of(intent: str) -> str | None:
    """Optional mock MAE scenario written into the intent, e.g. ``scenario=infeasible``."""
    match = SCENARIO.search(intent)
    return match.group(1).lower() if match else None
