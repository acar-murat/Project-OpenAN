"""Deterministic stand-in for MAE's UC1 planning (docs/use-cases.md, UC1 "What the solution does").

Given an intent (region, schedule, tariff), it:

1. predicts each site's monthly power draw and charging band,
2. classifies sites as downgrade / upgrade / grade-stable,
3. moves load off downgrade and upgrade sites onto grade-stable sites,
4. selects cells and energy-saving features per saving period,
5. predicts the monthly electricity cost, energy use and experience KPIs before and after.

Site data is derived from a hash of the region name, so the same intent always
gives the same plan. The numbers are illustrative, not a network model; they
exist to give the Monitor node and the report realistic artifacts to handle.
The artifact payloads are this repo's proposal for the MAE artifact schema
(open item O-11).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from typing import Any

from mocks.common import uc1_data

SCHEMA_VERSION = "mock-1"

#: A site within this many kW above its band's lower edge can drop a band.
DOWNGRADE_MARGIN_KW = 0.25
#: A site within this many kW below its band's upper edge risks moving up a band.
UPGRADE_MARGIN_KW = 0.15
#: Headroom kept below a band's upper edge when a site takes on load.
ABSORB_HEADROOM_KW = 0.2
MIGRATION_ACTIONS = ("reduce_tx_power", "increase_tilt", "handover_out")
HOURS_PER_MONTH_DAY = 24
DAYS_PER_MONTH = 30
#: Cells per site: (suffix, technology, frequency band, layer). The coverage layer never sleeps.
CELL_LAYERS = (("C1", "LTE", "L1800", "coverage"), ("C2", "LTE", "L2600", "capacity"),
               ("C3", "NR", "N3500", "capacity"))
#: Features MAE applies to capacity cells in each saving mode.
MODE_FEATURES = {
    "maximized_energy_saving": ("carrier_shutdown", "channel_shutdown"),
    "proactive_energy_saving": ("symbol_shutdown", "tx_power_reduction"),
}
#: Share of a cell's draw each feature saves while active (illustrative).
FEATURE_SAVING_SHARE = {"carrier_shutdown": 0.30, "channel_shutdown": 0.12, "symbol_shutdown": 0.08,
                        "tx_power_reduction": 0.05}
#: Average user rate kept in each saving mode, as a share of the no-saving rate.
MODE_RATE_SHARE = {"maximized_energy_saving": 0.55, "proactive_energy_saving": 0.75, "experience_first": 1.0}
#: In the ``partial_execution`` scenario, every Nth selected cell fails to activate.
PARTIAL_FAILURE_EVERY = 4


@dataclass
class Intent:
    region: str
    schedule: list[dict[str, Any]] = field(default_factory=uc1_data.intent_schedule)
    tariff: dict[str, Any] = field(default_factory=uc1_data.power_band_tariff)
    planning_month: str | None = None
    operation_type: str = "Create"
    site_count: int = 12


class IntentError(ValueError):
    """The intent cannot be planned (for example, it has no region)."""


def parse_json(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str):
        return None
    text = value.strip()
    try:
        return json.loads(text)
    except ValueError:
        pass
    # A rendered A2A-T prompt may embed the structured content as a JSON object.
    start, end = text.find("{"), text.rfind("}")
    if 0 <= start < end:
        try:
            return json.loads(text[start : end + 1])
        except ValueError:
            return None
    return None


_REGION_PATTERNS = (
    re.compile(r"\bregion\s*[:=]\s*\"?([^\"\n;,]+)", re.IGNORECASE),
    re.compile(r"\bfor\s+(.+?)\s+region\b", re.IGNORECASE),
)


def parse_intent(content: Any) -> Intent:
    """Build an Intent from Task-T or Negotiation-T content.

    Accepts structured JSON (Task-T slots ``task_object`` / ``task_target`` /
    ``task_context``, or a negotiation ``under_evaluation_description``) and
    falls back to finding a region in free text.
    """
    data = parse_json(content)
    if isinstance(data, dict):
        body = data.get("under_evaluation_description") or data
        region = body.get("region") or body.get("task_object")
        target = body.get("task_target")
        context = body.get("task_context")
        schedule = body.get("schedule") or (target.get("schedule") if isinstance(target, dict) else None)
        tariff = body.get("power_band_tariff") or (
            context.get("power_band_tariff") if isinstance(context, dict) else None
        )
        if not region:
            raise IntentError("intent has no region (Task-T slot task_object)")
        return Intent(
            region=str(region),
            schedule=schedule or uc1_data.intent_schedule(),
            tariff=tariff or uc1_data.power_band_tariff(),
            planning_month=body.get("planning_month"),
            operation_type=str(body.get("operation_type") or "Create"),
            site_count=int(body.get("site_count") or 12),
        )
    if isinstance(content, str):
        for pattern in _REGION_PATTERNS:
            match = pattern.search(content)
            if match:
                return Intent(region=match.group(1).strip())
    raise IntentError("could not find a region in the intent")


def max_rate_floor_mbps() -> float:
    return float(os.environ.get("MOCK_MAE_MAX_RATE_FLOOR_MBPS", "20"))


def _period_key(period: dict[str, Any]) -> str:
    return f"{period.get('start_hour')}-{period.get('end_hour')}"


def assess_feasibility(intent: Intent) -> dict[str, Any]:
    """Feasible unless a period asks for a guaranteed rate above what the mock can hold.

    An infeasible result carries a counter-proposal that caps those rate floors.
    ``periods`` gives the verdict per schedule period; ``feasibility`` is ``full``,
    ``partial`` (some saving periods can be met) or ``none``.
    """
    limit = max_rate_floor_mbps()
    periods = []
    too_high = []
    for period in intent.schedule:
        target = period.get("experience_target", {})
        ok = not (target.get("type") == "rate_floor" and float(target.get("mbps", 0)) > limit)
        periods.append({"period": _period_key(period), "saving_mode": period.get("saving_mode"), "feasible": ok,
                        "reason": None if ok else f"rate floor {target.get('mbps')} Mbps exceeds {limit:g} Mbps"})
        if not ok:
            too_high.append(period)
    if not too_high:
        return {"feasible": True, "feasibility": "full", "reasons": [], "proposal": None, "periods": periods}
    proposal = json.loads(json.dumps(intent.schedule))
    for period in proposal:
        target = period.get("experience_target", {})
        if target.get("type") == "rate_floor" and float(target.get("mbps", 0)) > limit:
            target["mbps"] = limit
    reasons = [
        f"rate floor {p['experience_target']['mbps']} Mbps in hours {p['start_hour']}-{p['end_hour']} "
        f"exceeds the {limit:g} Mbps the cluster can guarantee while saving energy"
        for p in too_high
    ]
    return {"feasible": False, "feasibility": _feasibility_level(periods), "reasons": reasons,
            "proposal": {"schedule": proposal}, "periods": periods,
            "counter_proposal": {"adjusted_experience_target": "; ".join(
                f"rate floor {limit:g} Mbps in hours {_period_key(p)}" for p in too_high)}}


def _feasibility_level(periods: list[dict[str, Any]]) -> str:
    saving = [p for p in periods if p["saving_mode"] != "experience_first"] or periods
    if all(p["feasible"] for p in saving):
        return "full"
    return "partial" if any(p["feasible"] for p in saving) else "none"


def assess_partially_feasible(intent: Intent) -> dict[str, Any]:
    """Forced partial verdict: the first proactive-saving period cannot save energy at its target.

    The counter-proposal keeps the experience target and drops saving in that period
    (an adjusted saving target, LLD v10.4 §11.5).
    """
    assessment = assess_feasibility(intent)
    proposal = json.loads(json.dumps(intent.schedule))
    busy = next((p for p in proposal if p.get("saving_mode") == "proactive_energy_saving"), None)
    if busy is None:
        return assessment
    key = _period_key(busy)
    reason = (f"forecast busy-hour load in hours {key} leaves no headroom to put capacity cells to sleep "
              f"while holding the {busy['experience_target'].get('mbps', 0)} Mbps rate floor")
    busy["saving_mode"] = "experience_first"
    busy["experience_target"] = {"type": "no_degradation"}
    periods = [{**p, "feasible": False, "reason": reason} if p["period"] == key else p
               for p in assessment["periods"]]
    return {"feasible": False, "feasibility": _feasibility_level(periods), "reasons": [reason],
            "proposal": {"schedule": proposal}, "periods": periods,
            "counter_proposal": {"adjusted_saving_target": f"no energy saving in hours {key}"}}


def relaxed_proposal(intent: Intent, share: float = 0.8) -> dict[str, Any]:
    """Forced first-round verdict for ``multi_round``: lower every rate floor to ``share`` of itself."""
    proposal = json.loads(json.dumps(intent.schedule))
    reasons, adjusted = [], []
    for period in proposal:
        target = period.get("experience_target", {})
        if target.get("type") == "rate_floor":
            asked = float(target.get("mbps", 0))
            target["mbps"] = round(asked * share, 1)
            reasons.append(f"rate floor {asked:g} Mbps in hours {_period_key(period)} cannot be held with "
                           f"carrier shutdown; {target['mbps']:g} Mbps can")
            adjusted.append(f"rate floor {target['mbps']:g} Mbps in hours {_period_key(period)}")
    periods = [{"period": _period_key(p), "saving_mode": p.get("saving_mode"),
                "feasible": p.get("experience_target", {}).get("type") != "rate_floor", "reason": None}
               for p in intent.schedule]
    return {"feasible": False, "feasibility": _feasibility_level(periods), "reasons": reasons,
            "proposal": {"schedule": proposal}, "periods": periods,
            "counter_proposal": {"adjusted_experience_target": "; ".join(adjusted)}}


def expected_outcome(intent: Intent) -> dict[str, Any]:
    """Headline numbers MAE quotes with a feasible verdict (from the same plan the task produces)."""
    report = build_artifacts(intent)[-1]
    return {
        "currency": report["currency"],
        "predicted_monthly_saving": report["predicted_saving"],
        "predicted_cost_saving_percent": _percent(report["predicted_saving"], report["predicted_cost_before"]),
        "predicted_energy_saving_percent": report["energy"]["saving_percent"],
    }


def solutions(intent: Intent) -> list[dict[str, Any]]:
    """Alternative solutions for the ``multiple_solutions`` scenario, with their predicted saving and risk."""
    base = expected_outcome(intent)["predicted_energy_saving_percent"]
    return [
        {"solution_id": "SOL-1", "name": "Symbol and channel shutdown only",
         "predicted_energy_saving_percent": round(base * 0.6, 1), "experience_risk": "low"},
        {"solution_id": "SOL-2", "name": "Carrier shutdown with traffic migration",
         "predicted_energy_saving_percent": base, "experience_risk": "medium"},
        {"solution_id": "SOL-3", "name": "Site deep sleep in off-peak hours",
         "predicted_energy_saving_percent": round(base * 1.4, 1), "experience_risk": "high"},
    ]


def _percent(part: float, whole: float) -> float:
    return round(100 * part / whole, 1) if whole else 0.0


def _site_kw(region: str, index: int) -> float:
    digest = hashlib.sha256(f"{region}#{index}".encode()).digest()
    # Spread draws over 0.6 - 4.9 kW so every band is represented.
    return round(0.6 + (int.from_bytes(digest[:4], "big") % 4300) / 1000, 2)


def _band(kw: float, tariff: dict[str, Any]) -> dict[str, Any]:
    band = uc1_data.band_for_kw(kw, tariff)
    if band is None:
        band = tariff["bands"][-1]
    return band


def predict_sites(intent: Intent) -> list[dict[str, Any]]:
    """Monthly power prediction, charging band and classification for each site."""
    sites = []
    for index in range(1, intent.site_count + 1):
        kw = _site_kw(intent.region, index)
        band = _band(kw, intent.tariff)
        if band["band_no"] > 1 and kw - band["min_kw"] < DOWNGRADE_MARGIN_KW:
            classification = "downgrade"
        elif band["max_kw"] - kw < UPGRADE_MARGIN_KW and band["band_no"] < len(intent.tariff["bands"]):
            classification = "upgrade"
        else:
            classification = "grade_stable"
        sites.append({
            "site_id": f"{_slug(intent.region)}-S{index:03d}",
            "predicted_kw": kw,
            "predicted_band": band["band_no"],
            "predicted_charge": band["charge"],
            "classification": classification,
        })
    return sites


def plan_migration(intent: Intent, sites: list[dict[str, Any]]) -> dict[str, Any]:
    """Move load off downgrade/upgrade sites onto grade-stable sites with headroom."""
    bands = {band["band_no"]: band for band in intent.tariff["bands"]}
    after = {site["site_id"]: site["predicted_kw"] for site in sites}
    actions: list[dict[str, Any]] = []
    to_place = 0.0

    for index, site in enumerate(sites):
        band = bands[site["predicted_band"]]
        if site["classification"] == "downgrade":
            shed = round(site["predicted_kw"] - band["min_kw"] + 0.05, 2)
        elif site["classification"] == "upgrade":
            shed = round(site["predicted_kw"] - (band["max_kw"] - ABSORB_HEADROOM_KW), 2)
        else:
            continue
        after[site["site_id"]] = round(site["predicted_kw"] - shed, 2)
        to_place += shed
        actions.append({
            "site_id": site["site_id"],
            "direction": "out",
            "action": MIGRATION_ACTIONS[index % len(MIGRATION_ACTIONS)],
            "load_kw": shed,
        })

    for site in sites:
        if site["classification"] != "grade_stable" or to_place <= 0:
            continue
        band = bands[site["predicted_band"]]
        headroom = round(band["max_kw"] - ABSORB_HEADROOM_KW - site["predicted_kw"], 2)
        take = round(min(headroom, to_place), 2)
        if take <= 0:
            continue
        after[site["site_id"]] = round(site["predicted_kw"] + take, 2)
        to_place = round(to_place - take, 2)
        actions.append({"site_id": site["site_id"], "direction": "in", "action": "handover_in", "load_kw": take})

    return {"after_kw": after, "actions": actions, "unplaced_kw": max(to_place, 0.0)}


def _hours(period: dict[str, Any]) -> int:
    """Hours in an inclusive schedule period; periods may wrap past midnight."""
    return (int(period["end_hour"]) - int(period["start_hour"])) % 24 + 1


def _unit(seed: str) -> float:
    """A deterministic number in [0, 1) for ``seed``."""
    return int.from_bytes(hashlib.sha256(seed.encode()).digest()[:4], "big") / 2**32


def select_cells(intent: Intent, sites: list[dict[str, Any]], migration: dict[str, Any],
                 partial_execution: bool = False) -> list[dict[str, Any]]:
    """Capacity cells put to sleep per saving period, with each cell's predicted monthly saving.

    Cells on sites that absorb migrated load stay on. With ``partial_execution`` every
    ``PARTIAL_FAILURE_EVERY``-th cell fails to activate.
    """
    absorbing = {a["site_id"] for a in migration["actions"] if a["direction"] == "in"}
    cells = []
    for site in sites:
        if site["site_id"] in absorbing:
            continue
        cell_kw = migration["after_kw"][site["site_id"]] / len(CELL_LAYERS)
        for suffix, technology, band, layer in CELL_LAYERS:
            if layer != "capacity":
                continue
            periods, saving_kwh = [], 0.0
            for period in intent.schedule:
                features = MODE_FEATURES.get(period.get("saving_mode"))
                if not features:
                    continue
                periods.append({"period": _period_key(period), "features": list(features)})
                share = sum(FEATURE_SAVING_SHARE[f] for f in features)
                saving_kwh += cell_kw * share * _hours(period) * DAYS_PER_MONTH
            if not periods:
                continue
            cells.append({"cell_id": f"{site['site_id']}-{suffix}", "site_id": site["site_id"],
                          "technology": technology, "frequency_band": band, "layer": layer,
                          "periods": periods, "predicted_saving_kwh": round(saving_kwh, 1),
                          "status": "activated", "failure_reason": None})
    if partial_execution:
        for index, cell in enumerate(cells):
            if index % PARTIAL_FAILURE_EVERY == PARTIAL_FAILURE_EVERY - 1:
                cell["status"] = "failed"
                cell["failure_reason"] = "cell locked for maintenance; feature activation refused (mock)"
    return cells


def experience_kpis(intent: Intent) -> list[dict[str, Any]]:
    """Predicted average user rate and PRB load per schedule period, checked against its target."""
    kpis = []
    for period in intent.schedule:
        key = _period_key(period)
        baseline = round(30 + 15 * _unit(f"{intent.region}#rate#{key}"), 1)
        mode = period.get("saving_mode", "experience_first")
        rate = round(baseline * MODE_RATE_SHARE.get(mode, 1.0), 1)
        target = period.get("experience_target") or {"type": "none"}
        if target.get("type") == "rate_floor":
            met = rate >= float(target.get("mbps", 0))
        elif target.get("type") == "no_degradation":
            met = rate >= baseline
        else:
            met = True
        prb_before = round(25 + 40 * _unit(f"{intent.region}#prb#{key}"), 1)
        prb_after = round(min(95.0, prb_before / MODE_RATE_SHARE.get(mode, 1.0)), 1)
        kpis.append({"period": key, "saving_mode": mode, "experience_target": target,
                     "baseline_avg_user_rate_mbps": baseline, "predicted_avg_user_rate_mbps": rate,
                     "prb_utilization_before_percent": prb_before, "prb_utilization_after_percent": prb_after,
                     "target_met": met})
    return kpis


def build_artifacts(intent: Intent, partial_execution: bool = False) -> list[dict[str, Any]]:
    """The artifacts the mock MAE streams for one UC1 task, in order."""
    sites = predict_sites(intent)
    migration = plan_migration(intent, sites)
    cells = select_cells(intent, sites, migration, partial_execution)
    activated_cells = [c for c in cells if c["status"] == "activated"]
    failed_cells = [c for c in cells if c["status"] == "failed"]
    energy_before = round(sum(s["predicted_kw"] for s in sites) * HOURS_PER_MONTH_DAY * DAYS_PER_MONTH, 1)
    energy_saving = round(sum(c["predicted_saving_kwh"] for c in activated_cells), 1)
    kpis = experience_kpis(intent)
    cost_before = round(sum(site["predicted_charge"] for site in sites), 2)
    after_sites = []
    for site in sites:
        kw = migration["after_kw"][site["site_id"]]
        band = _band(kw, intent.tariff)
        after_sites.append({"site_id": site["site_id"], "kw": kw, "band": band["band_no"], "charge": band["charge"]})
    cost_after = round(sum(site["charge"] for site in after_sites), 2)
    saving_periods = [p for p in intent.schedule if p.get("saving_mode") != "experience_first"]
    counts = {c: sum(1 for s in sites if s["classification"] == c) for c in ("downgrade", "upgrade", "grade_stable")}
    currency = intent.tariff.get("currency", "GHS")

    def artifact(kind: str, body: dict[str, Any]) -> dict[str, Any]:
        return {"type": kind, "schema_version": SCHEMA_VERSION, "region": intent.region, **body}

    return [
        artifact("TaskPlan", {
            "operation_type": intent.operation_type,
            "planning_month": intent.planning_month,
            "site_count": len(sites),
            "steps": ["band_prediction", "site_classification", "cluster_optimization", "cell_selection",
                      "activation"],
        }),
        artifact("BandPrediction", {"sites": [
            {k: s[k] for k in ("site_id", "predicted_kw", "predicted_band", "predicted_charge")} for s in sites
        ]}),
        artifact("SiteClassification", {
            "counts": counts,
            "sites": [{"site_id": s["site_id"], "classification": s["classification"]} for s in sites],
        }),
        artifact("TrafficMigrationPlan", {
            "actions": migration["actions"],
            "unplaced_kw": migration["unplaced_kw"],
            "active_periods": [{"start_hour": p["start_hour"], "end_hour": p["end_hour"]} for p in saving_periods],
        }),
        artifact("CellSelection", {
            "cell_count": len(cells),
            "cells": [{k: c[k] for k in ("cell_id", "site_id", "technology", "frequency_band", "layer", "periods",
                                         "predicted_saving_kwh")} for c in cells],
        }),
        artifact("EnergySavingActivated", {
            "activated_sites": sorted({a["site_id"] for a in migration["actions"]}),
            "active_periods": [{"start_hour": p["start_hour"], "end_hour": p["end_hour"]} for p in saving_periods],
            "activated_cells": [c["cell_id"] for c in activated_cells],
            "failed_cells": [{"cell_id": c["cell_id"], "reason": c["failure_reason"]} for c in failed_cells],
        }),
        artifact("IntentReport", {
            "intent_achieved": cost_after <= cost_before and not failed_cells and all(k["target_met"] for k in kpis),
            "achievement": "partial" if failed_cells else "full",
            "currency": currency,
            "billing_period": intent.tariff.get("billing_period", "monthly"),
            "predicted_cost_before": cost_before,
            "predicted_cost_after": cost_after,
            "predicted_saving": round(cost_before - cost_after, 2),
            "sites_changing_band": sum(
                1 for s, a in zip(sites, after_sites, strict=True) if s["predicted_band"] != a["band"]
            ),
            "energy": {
                "unit": "kWh",
                "predicted_before": energy_before,
                "predicted_after": round(energy_before - energy_saving, 1),
                "predicted_saving": energy_saving,
                "saving_percent": _percent(energy_saving, energy_before),
            },
            "cells": {"selected": len(cells), "activated": len(activated_cells), "failed": len(failed_cells)},
            "experience_kpis": kpis,
            "site_results": [
                {"site_id": s["site_id"], "band_before": s["predicted_band"], "band_after": a["band"],
                 "charge_before": s["predicted_charge"], "charge_after": a["charge"]}
                for s, a in zip(sites, after_sites, strict=True)
            ],
            "schedule": intent.schedule,
        }),
    ]


def task_error(intent: Intent, code: str, reason: str, failed_step: str) -> dict[str, Any]:
    """The error artifact MAE streams before a failed task (LLD v10.4 §4, F8)."""
    return {"type": "TaskError", "schema_version": SCHEMA_VERSION, "region": intent.region,
            "code": code, "reason": reason, "failed_step": failed_step}


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").upper()[:12] or "REGION"


def describe(body: dict[str, Any]) -> str:
    """One readable line for an artifact, used as its text part (the JSON body stays in metadata)."""
    kind = body["type"]
    if kind == "TaskPlan":
        month = body["planning_month"] or "next"
        detail = f"{body['site_count']} sites, planning month {month}, steps {', '.join(body['steps'])}"
    elif kind == "BandPrediction":
        detail = f"predicted band and monthly charge for {len(body['sites'])} sites"
    elif kind == "SiteClassification":
        counts = body["counts"]
        detail = (f"{counts['downgrade']} downgrade, {counts['upgrade']} upgrade, "
                  f"{counts['grade_stable']} grade-stable sites")
    elif kind == "TrafficMigrationPlan":
        moved = sum(a["load_kw"] for a in body["actions"] if a["direction"] == "out")
        detail = f"{len(body['actions'])} migration actions moving {moved:.2f} kW"
    elif kind == "CellSelection":
        detail = f"{body['cell_count']} capacity cells selected for energy-saving features"
    elif kind == "EnergySavingActivated":
        detail = (f"energy saving active on {len(body['activated_sites'])} sites and "
                  f"{len(body['activated_cells'])} cells in {len(body['active_periods'])} periods")
        if body["failed_cells"]:
            detail += f"; {len(body['failed_cells'])} cells failed to activate"
    elif kind == "IntentReport":
        currency = body["currency"]
        detail = (f"predicted {body['billing_period']} cost {body['predicted_cost_before']:,.2f} -> "
                  f"{body['predicted_cost_after']:,.2f} {currency}, saving {body['predicted_saving']:,.2f} "
                  f"{currency}; {body['sites_changing_band']} sites change band; energy saving "
                  f"{body['energy']['saving_percent']:g}%; achievement {body['achievement']}")
    elif kind == "TaskError":
        detail = f"{body['code']} at {body['failed_step']}: {body['reason']}"
    else:
        return kind
    return f"{kind}: {detail}"
