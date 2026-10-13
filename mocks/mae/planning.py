"""Deterministic stand-in for MAE's UC1 planning (docs/use-cases.md, UC1 "What the solution does").

Given an intent (region, schedule, tariff), it:

1. predicts each site's monthly power draw and charging band,
2. classifies sites as downgrade / upgrade / grade-stable,
3. moves load off downgrade and upgrade sites onto grade-stable sites,
4. predicts the monthly electricity cost before and after.

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


def assess_feasibility(intent: Intent) -> dict[str, Any]:
    """Feasible unless a period asks for a guaranteed rate above what the mock can hold.

    An infeasible result carries a counter-proposal that caps those rate floors.
    """
    limit = max_rate_floor_mbps()
    too_high = [
        period for period in intent.schedule
        if period.get("experience_target", {}).get("type") == "rate_floor"
        and float(period["experience_target"].get("mbps", 0)) > limit
    ]
    if not too_high:
        return {"feasible": True, "reasons": [], "proposal": None}
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
    return {"feasible": False, "reasons": reasons, "proposal": {"schedule": proposal}}


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


def build_artifacts(intent: Intent) -> list[dict[str, Any]]:
    """The artifacts the mock MAE streams for one UC1 task, in order."""
    sites = predict_sites(intent)
    migration = plan_migration(intent, sites)
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
            "steps": ["band_prediction", "site_classification", "cluster_optimization", "activation"],
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
        artifact("EnergySavingActivated", {
            "activated_sites": sorted({a["site_id"] for a in migration["actions"]}),
            "active_periods": [{"start_hour": p["start_hour"], "end_hour": p["end_hour"]} for p in saving_periods],
        }),
        artifact("IntentReport", {
            "intent_achieved": cost_after <= cost_before,
            "currency": currency,
            "billing_period": intent.tariff.get("billing_period", "monthly"),
            "predicted_cost_before": cost_before,
            "predicted_cost_after": cost_after,
            "predicted_saving": round(cost_before - cost_after, 2),
            "sites_changing_band": sum(
                1 for s, a in zip(sites, after_sites, strict=True) if s["predicted_band"] != a["band"]
            ),
            "schedule": intent.schedule,
        }),
    ]


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
    elif kind == "EnergySavingActivated":
        detail = (f"energy saving active on {len(body['activated_sites'])} sites in "
                  f"{len(body['active_periods'])} periods")
    elif kind == "IntentReport":
        currency = body["currency"]
        detail = (f"predicted {body['billing_period']} cost {body['predicted_cost_before']:,.2f} -> "
                  f"{body['predicted_cost_after']:,.2f} {currency}, saving {body['predicted_saving']:,.2f} "
                  f"{currency}; {body['sites_changing_band']} sites change band")
    else:
        return kind
    return f"{kind}: {detail}"
