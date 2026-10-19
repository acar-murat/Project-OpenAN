"""Henan Mobile phase-1 demo: one page from tiered tariff to battery charge/discharge strategy.

Run with ``python -m henan_demo`` (default http://127.0.0.1:8094). Environment:

* ``HENAN_DEMO_HOST`` / ``HENAN_DEMO_PORT``: bind address.

The page covers the two functions from the 2026-10-19 meeting notes (docs/henan-demo.md):

1. Strategy generation: import a tariff CSV, show the strategy, export the Deployment CSV.
2. Activation and status: the energy-saving strategy, how far activation has got, and the saving.

The strategy comes from the ``tariff-to-battery-rules`` Skill's own script, so the page and the
Skill registered in OpenTalon give the same answer. Nothing here calls an external system: the
A2A-T intent and the CME delivery are shown, never sent, and activation is simulated.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from datetime import date
from pathlib import Path
from types import ModuleType
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse, Response
from pydantic import BaseModel, Field

from mocks.common.a2at import ENERGY_SAVING_TEMPLATE_URI, TASK_T_EXTENSION_URI, TEMPLATE_URI_METADATA_KEY

ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / "skills" / "tariff-to-battery-rules"
STATIC = Path(__file__).resolve().parent / "static"
MAX_SITES = 500
SITE_NAME = re.compile(r"^[\w.\-]{1,64}$")


def _load_skill_script() -> ModuleType:
    name = "tariff_to_rules"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, SKILL_ROOT / "scripts" / "tariff_to_rules.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


rules = _load_skill_script()


class StrategyRequest(BaseModel):
    tariff_csv: str = Field(max_length=20_000)
    sites: list[str] = Field(default_factory=list)
    region: str = Field(default="河南 郑州 Zhengzhou, Henan", max_length=80)
    battery: dict[str, float] = Field(default_factory=dict)
    effective_date: date | None = None


def _sites(request: StrategyRequest) -> list[str]:
    sites = [s.strip() for s in request.sites if s.strip()]
    if not sites:
        raise HTTPException(422, "add at least one site (NE name)")
    if len(sites) > MAX_SITES:
        raise HTTPException(422, f"at most {MAX_SITES} sites")
    bad = [s for s in sites if not SITE_NAME.match(s)]
    if bad:
        raise HTTPException(422, f"site names may use letters, digits, '.', '_' and '-' only: {', '.join(bad[:3])}")
    return sites


def _strategy(request: StrategyRequest) -> dict[str, Any]:
    allowed = set(rules.Battery.__dataclass_fields__)
    unknown = set(request.battery) - allowed
    if unknown:
        raise HTTPException(422, f"unknown battery fields: {', '.join(sorted(unknown))}")
    try:
        return rules.strategy_from_csv(request.tariff_csv, request.battery)
    except (rules.TariffError, TypeError) as exc:
        raise HTTPException(422, str(exc)) from exc


def intent_preview(region: str, strategy: dict[str, Any], sites: list[str]) -> dict[str, Any]:
    """The energy-saving A2A-T intent the strategy maps to (reused Task-T template). Shown, never sent."""
    slots = {
        "task_object": region,
        "operation_type": "Create",
        "task_description": "Battery peak shaving by tiered tariff (Henan phase-1 demo)",
        "task_target": {
            "objective": "minimise_energy_cost",
            "sites": len(sites),
            "charge_windows": strategy["summary"]["charge_windows"],
            "discharge_windows": strategy["summary"]["discharge_windows"],
            "soc_limits_pct": [strategy["battery"]["soc_min_pct"], strategy["battery"]["soc_max_pct"]],
        },
        "task_context": {"time_of_use_tariff": strategy["tariff"], "power_vendor": "Huawei"},
    }
    return {
        "sent": False,
        "note": "Display only in phase 1: reuses the existing energy-saving A2A-T intent interface, not called.",
        "metadata": {TASK_T_EXTENSION_URI: slots, TEMPLATE_URI_METADATA_KEY: ENERGY_SAVING_TEMPLATE_URI},
    }


app = FastAPI(title="Henan Mobile energy-saving demo", version="0.1.0",
              description="Tiered tariff -> battery charge/discharge strategy -> Deployment CSV (demo only).")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
def page() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/sample-tariff", response_class=PlainTextResponse)
def sample_tariff() -> str:
    return (SKILL_ROOT / "assets" / "sample-tariff.csv").read_text(encoding="utf-8")


@app.get("/api/config")
def config() -> dict[str, Any]:
    template = rules.load_json_asset("deployment-template.json")
    profile = rules.load_json_asset("battery-profile.json")
    return {
        "battery": {k: v for k, v in profile.items() if not k.startswith("_")},
        "template": {"id": template["template_id"], "placeholder": bool(template.get("placeholder")),
                     "headers": [c["header"] for c in template["columns"]]},
    }


@app.post("/api/strategy")
def strategy(request: StrategyRequest) -> dict[str, Any]:
    sites = _sites(request)
    result = _strategy(request)
    template = rules.load_json_asset("deployment-template.json")
    effective = (request.effective_date or date.today()).isoformat()
    header, rows = rules.deployment_rows(result, sites, template, effective)
    summary = result["summary"]
    return {
        **result,
        "sites": sites,
        "fleet": {
            "daily_saving": round(summary["daily_saving"] * len(sites), 2),
            "monthly_saving": round(summary["monthly_saving"] * len(sites), 2),
            "peak_kwh_shifted_daily": round(summary["peak_kwh_shifted"] * len(sites), 2),
        },
        "deployment_preview": {"template_id": template["template_id"],
                               "placeholder": bool(template.get("placeholder")),
                               "header": header, "rows": rows[:12], "row_count": len(rows)},
        "intent": intent_preview(request.region, result, sites),
    }


@app.post("/api/export")
def export(request: StrategyRequest) -> Response:
    sites = _sites(request)
    result = _strategy(request)
    template = rules.load_json_asset("deployment-template.json")
    effective = (request.effective_date or date.today()).isoformat()
    body = rules.deployment_csv(result, sites, template, effective)
    encoding = template.get("encoding", "utf-8")
    suffix = "PLACEHOLDER-template" if template.get("placeholder") else "deployment"
    filename = f"battery-strategy-{effective}-{suffix}.csv"
    return Response(body.encode(encoding), media_type=f"text/csv; charset={encoding.replace('-sig', '')}",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"',
                             "X-Template-Id": template["template_id"]})
