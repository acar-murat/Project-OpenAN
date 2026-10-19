#!/usr/bin/env python3
"""Tiered (peak/flat/valley) electricity tariff -> base-station battery charge/discharge rules.

Used two ways:

* As the script of the ``tariff-to-battery-rules`` NextAgent/OpenTalon Skill (see ../SKILL.md).
  Run it with ``python "$NEXTAGENT_SKILL_ROOT/scripts/tariff_to_rules.py" --tariff <file>``.
  It reads its own assets from ``NEXTAGENT_SKILL_ROOT`` (read-only), writes scratch data to
  ``NEXTAGENT_TEMP_DIR`` and the final CSV and JSON to ``NEXTAGENT_WORKSPACE_DIR``, and prints a
  JSON summary on stdout for the model to present.
* As a library, imported by the Henan demo page (``henan_demo/``), so the page and the Skill
  produce the same strategy.

Standard library only: the OpenTalon sandbox is not guaranteed to have extra packages.

Strategy, one battery per site, one day, repeated daily:

1. Charge in valley periods, up to the SoC ceiling, at the battery's charge power.
2. Discharge in peak and sharp-peak periods to carry the site load instead of the grid, down to
   the SoC floor (the floor is the outage reserve a base station must keep).
3. A flat period between two discharge periods may top the battery up, but only when that pays:
   flat price / efficiency must be below the price of the discharge it feeds.
4. When the stored energy cannot cover every discharge period before the next charge, it goes to
   the most expensive periods first.

Battery and site figures come from ``assets/battery-profile.json`` and the CSV layout from
``assets/deployment-template.json``. Both are placeholders until HQ supplies real values.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

SKILL_ROOT = Path(__file__).resolve().parents[1]
ASSETS = SKILL_ROOT / "assets"
REQUIRED_ENV = ("NEXTAGENT_WORKSPACE_DIR", "NEXTAGENT_TEMP_DIR", "NEXTAGENT_SKILL_ROOT")

#: Tier names accepted in the tariff file (English or Chinese) -> canonical tier.
TIER_ALIASES = {
    "sharp": "sharp", "critical": "sharp", "尖峰": "sharp", "尖": "sharp",
    "peak": "peak", "高峰": "peak", "峰": "peak",
    "flat": "flat", "shoulder": "flat", "平段": "flat", "平": "flat",
    "valley": "valley", "off-peak": "valley", "offpeak": "valley", "低谷": "valley", "谷": "valley",
    "deep-valley": "valley", "深谷": "valley",
}
TIER_LABELS = {"sharp": "尖峰 Sharp peak", "peak": "高峰 Peak", "flat": "平段 Flat", "valley": "低谷 Valley"}
DISCHARGE_TIERS = ("sharp", "peak")
DAY_MINUTES = 24 * 60


class TariffError(ValueError):
    """The tariff file cannot be turned into a strategy."""


@dataclass
class Period:
    start: int  # minutes after midnight
    end: int  # exclusive, up to 1440
    tier: str
    price: float

    @property
    def hours(self) -> float:
        return (self.end - self.start) / 60


@dataclass
class Battery:
    capacity_kwh: float
    charge_power_kw: float
    discharge_power_kw: float
    site_load_kw: float
    soc_min_pct: float
    soc_max_pct: float
    efficiency: float
    days_per_month: int = 30

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Battery:
        fields = cls.__dataclass_fields__
        battery = cls(**{k: data[k] for k in fields if k in data})
        if not 0 <= battery.soc_min_pct < battery.soc_max_pct <= 100:
            raise TariffError("SoC limits must satisfy 0 <= soc_min_pct < soc_max_pct <= 100")
        if not 0 < battery.efficiency <= 1:
            raise TariffError("efficiency must be in (0, 1]")
        for name in ("capacity_kwh", "charge_power_kw", "discharge_power_kw", "site_load_kw"):
            if getattr(battery, name) <= 0:
                raise TariffError(f"{name} must be positive")
        return battery


def _minutes(text: str) -> int:
    text = text.strip()
    try:
        hours, minutes = text.split(":")[:2]
        value = int(hours) * 60 + int(minutes)
    except ValueError as exc:
        raise TariffError(f"time {text!r} is not HH:MM") from exc
    if not 0 <= value <= DAY_MINUTES:
        raise TariffError(f"time {text!r} is outside 00:00-24:00")
    return value


def _clock(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def parse_tariff_csv(text: str) -> list[Period]:
    """Parse ``start_time,end_time,tier,price`` rows (see references/tariff-format.md).

    The periods must cover the whole day without overlapping. A period that ends at or before
    its start (``23:00,07:00``) wraps past midnight and is split in two.
    """
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    needed = {"start_time", "end_time", "tier", "price"}
    header = {name.strip() for name in (reader.fieldnames or [])}
    if not needed <= header:
        raise TariffError(f"tariff header must contain {', '.join(sorted(needed))}; got {', '.join(sorted(header))}")
    periods: list[Period] = []
    for line_no, raw in enumerate(reader, start=2):
        row = {k.strip(): (v or "").strip() for k, v in raw.items() if k}
        if not any(row.values()):
            continue
        tier = TIER_ALIASES.get(row["tier"].lower())
        if tier is None:
            raise TariffError(f"line {line_no}: unknown tier {row['tier']!r}; use sharp, peak, flat or valley")
        try:
            price = float(row["price"])
        except ValueError as exc:
            raise TariffError(f"line {line_no}: price {row['price']!r} is not a number") from exc
        if price < 0:
            raise TariffError(f"line {line_no}: price must not be negative")
        start, end = _minutes(row["start_time"]), _minutes(row["end_time"])
        if end <= start:
            periods.append(Period(start, DAY_MINUTES, tier, price))
            if end > 0:
                periods.append(Period(0, end, tier, price))
        else:
            periods.append(Period(start, end, tier, price))
    if not periods:
        raise TariffError("tariff has no periods")
    periods.sort(key=lambda p: p.start)
    cursor = 0
    for period in periods:
        if period.start != cursor:
            kind = "overlap" if period.start < cursor else "gap"
            raise TariffError(f"tariff has a {kind} at {_clock(min(cursor, period.start))}; periods must cover 24 h")
        cursor = period.end
    if cursor != DAY_MINUTES:
        raise TariffError(f"tariff has a gap at {_clock(cursor)}; periods must cover 24 h")
    return _merge(periods)


def _merge(periods: list[Period]) -> list[Period]:
    merged: list[Period] = []
    for period in periods:
        last = merged[-1] if merged else None
        if last and last.tier == period.tier and last.price == period.price and last.end == period.start:
            last.end = period.end
        else:
            merged.append(Period(period.start, period.end, period.tier, period.price))
    return merged


def _plan_actions(periods: list[Period], battery: Battery) -> list[str]:
    """Pick charge / discharge / hold for each period (before energy limits are applied)."""
    valley_price = min((p.price for p in periods if p.tier == "valley"), default=min(p.price for p in periods))
    actions = []
    for period in periods:
        if period.tier == "valley":
            actions.append("charge")
        elif period.tier in DISCHARGE_TIERS and period.price > valley_price / battery.efficiency:
            actions.append("discharge")
        else:
            actions.append("hold")
    # A flat period may recharge for a later, dearer discharge, once a discharge has drawn the
    # battery down since the last charge.
    count = len(periods)
    for index, period in enumerate(periods):
        if actions[index] != "hold" or period.tier != "flat":
            continue
        previous = next((actions[(index - k) % count] for k in range(1, count)
                         if actions[(index - k) % count] != "hold"), None)
        later = _next_discharge_prices(periods, actions, index)
        if previous == "discharge" and later and max(later) > period.price / battery.efficiency:
            actions[index] = "charge"
    return actions


def _next_discharge_prices(periods: list[Period], actions: list[str], index: int) -> list[float]:
    prices = []
    count = len(periods)
    for k in range(1, count):
        other = (index + k) % count
        if actions[other] == "charge":
            break
        if actions[other] == "discharge":
            prices.append(periods[other].price)
    return prices


def build_strategy(periods: list[Period], battery: Battery) -> dict[str, Any]:
    """Simulate one day (twice, so the start-of-day SoC is the steady state) and return the rules."""
    actions = _plan_actions(periods, battery)
    count = len(periods)
    # Rotate so the day starts with the longest charge period: SoC is then well defined.
    charge_indexes = [i for i, a in enumerate(actions) if a == "charge"] or [0]
    first = max(charge_indexes, key=lambda i: periods[i].hours)
    order = [(first + k) % count for k in range(count)]

    floor = battery.capacity_kwh * battery.soc_min_pct / 100
    ceiling = battery.capacity_kwh * battery.soc_max_pct / 100
    energy = floor
    results: dict[int, dict[str, Any]] = {}
    for _ in range(2):
        position = 0
        while position < count:
            index = order[position]
            period = periods[index]
            if actions[index] == "charge":
                stored = min(battery.charge_power_kw * period.hours, ceiling - energy)
                results[index] = _row(period, "charge", energy, energy + stored, stored, battery)
                energy += stored
                position += 1
                continue
            # A run of discharge/hold periods until the next charge: share the stored energy out
            # by price, dearest first.
            run = []
            while position < count and actions[order[position]] != "charge":
                run.append(order[position])
                position += 1
            budget = energy - floor
            planned: dict[int, float] = {}
            for i in sorted((i for i in run if actions[i] == "discharge"), key=lambda i: -periods[i].price):
                want = min(battery.discharge_power_kw, battery.site_load_kw) * periods[i].hours
                planned[i] = min(want, budget)
                budget -= planned[i]
            for i in run:
                used = planned.get(i, 0.0)
                action = "discharge" if used > 1e-9 else "hold"
                results[i] = _row(periods[i], action, energy, energy - used, used, battery)
                energy -= used
    rules = [results[i] for i in range(count)]
    for number, rule in enumerate(rules, start=1):
        rule["rule_id"] = f"R{number:02d}"
    return {"rules": rules, "summary": _summary(periods, rules, battery), "battery": asdict(battery)}


def _row(period: Period, action: str, before: float, after: float, energy: float, battery: Battery) -> dict[str, Any]:
    power = energy / period.hours if period.hours else 0.0
    return {
        "start": _clock(period.start),
        "end": _clock(period.end),
        "tier": period.tier,
        "tier_label": TIER_LABELS[period.tier],
        "price": period.price,
        "action": action,
        "power_kw": round(power, 2),
        "energy_kwh": round(energy, 2),
        "soc_start_pct": round(before / battery.capacity_kwh * 100, 1),
        "soc_end_pct": round(after / battery.capacity_kwh * 100, 1),
    }


def _summary(periods: list[Period], rules: list[dict[str, Any]], battery: Battery) -> dict[str, Any]:
    cost_before = sum(battery.site_load_kw * p.hours * p.price for p in periods)
    cost_after = 0.0
    for period, rule in zip(periods, rules, strict=True):
        grid = battery.site_load_kw * period.hours
        if rule["action"] == "charge":
            grid += rule["energy_kwh"] / battery.efficiency
        elif rule["action"] == "discharge":
            grid -= rule["energy_kwh"]
        cost_after += grid * period.price
    discharged = sum(r["energy_kwh"] for r in rules if r["action"] == "discharge")
    charged = sum(r["energy_kwh"] for r in rules if r["action"] == "charge")
    saving = cost_before - cost_after
    return {
        "currency": "CNY",
        "daily_cost_before": round(cost_before, 2),
        "daily_cost_after": round(cost_after, 2),
        "daily_saving": round(saving, 2),
        "monthly_saving": round(saving * battery.days_per_month, 2),
        "saving_pct": round(saving / cost_before * 100, 1) if cost_before else 0.0,
        "peak_kwh_shifted": round(discharged, 2),
        "charged_kwh": round(charged, 2),
        "charge_windows": [f"{r['start']}-{r['end']}" for r in rules if r["action"] == "charge"],
        "discharge_windows": [f"{r['start']}-{r['end']}" for r in rules if r["action"] == "discharge"],
    }


def load_json_asset(name: str, root: Path | None = None) -> dict[str, Any]:
    return json.loads(((root or SKILL_ROOT) / "assets" / name).read_text(encoding="utf-8"))


def deployment_rows(strategy: dict[str, Any], sites: list[str], template: dict[str, Any],
                    effective_date: str | None = None) -> tuple[list[str], list[list[str]]]:
    """Header and rows of the Deployment CSV: one row per site and rule, laid out by the template."""
    codes = template.get("action_codes", {})
    battery = strategy["battery"]
    include_hold = bool(template.get("include_hold_rows", False))
    effective = effective_date or date.today().isoformat()
    header = [column["header"] for column in template["columns"]]
    rows = []
    for site in sites:
        for rule in strategy["rules"]:
            if rule["action"] == "hold" and not include_hold:
                continue
            values = {
                **rule,
                "site_id": site,
                "action_code": codes.get(rule["action"], rule["action"].upper()),
                "soc_min_pct": battery["soc_min_pct"],
                "soc_max_pct": battery["soc_max_pct"],
                "effective_date": effective,
            }
            row = []
            for column in template["columns"]:
                value = column["value"] if "value" in column else values.get(column["field"], "")
                row.append(_cell(value))
            rows.append(row)
    return header, rows


def _cell(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def deployment_csv(strategy: dict[str, Any], sites: list[str], template: dict[str, Any],
                   effective_date: str | None = None) -> str:
    header, rows = deployment_rows(strategy, sites, template, effective_date)
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(header)
    writer.writerows(rows)
    return out.getvalue()


def strategy_from_csv(tariff_text: str, battery_overrides: dict[str, Any] | None = None,
                      root: Path | None = None) -> dict[str, Any]:
    profile = load_json_asset("battery-profile.json", root)
    battery = Battery.from_dict({**profile, **(battery_overrides or {})})
    periods = parse_tariff_csv(tariff_text)
    strategy = build_strategy(periods, battery)
    strategy["tariff"] = [
        {"start": _clock(p.start), "end": _clock(p.end), "tier": p.tier, "price": p.price} for p in periods
    ]
    return strategy


def _site_list(args: argparse.Namespace) -> list[str]:
    if args.sites:
        return [s.strip() for s in args.sites.split(",") if s.strip()]
    return [f"{args.site_prefix}{n:04d}" for n in range(1, args.site_count + 1)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tariff", help="tariff CSV (default: the Skill's assets/sample-tariff.csv)")
    parser.add_argument("--sites", help="comma-separated site / NE names for the Deployment CSV")
    parser.add_argument("--site-count", type=int, default=5, help="number of demo sites when --sites is not given")
    parser.add_argument("--site-prefix", default="HN-ZZ-BTS-")
    parser.add_argument("--effective-date", help="YYYY-MM-DD written into the CSV (default: today)")
    parser.add_argument("--task-name", default="battery-strategy", help="prefix of the output files")
    args = parser.parse_args(argv)

    missing = [name for name in REQUIRED_ENV if not os.environ.get(name)]
    if missing:
        raise RuntimeError(f"Missing NextAgent sandbox env: {', '.join(missing)}")
    skill_root = Path(os.environ["NEXTAGENT_SKILL_ROOT"])
    workspace = Path(os.environ["NEXTAGENT_WORKSPACE_DIR"])
    temp = Path(os.environ["NEXTAGENT_TEMP_DIR"])

    tariff_path = Path(args.tariff) if args.tariff else skill_root / "assets" / "sample-tariff.csv"
    try:
        strategy = strategy_from_csv(tariff_path.read_text(encoding="utf-8"), root=skill_root)
    except (OSError, TariffError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    template = load_json_asset("deployment-template.json", skill_root)
    sites = _site_list(args)

    # The workspace is shared by runs of one session: a timestamp keeps runs from overwriting each other.
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    temp.mkdir(parents=True, exist_ok=True)
    (temp / f"{args.task_name}-{stamp}-tariff.json").write_text(json.dumps(strategy["tariff"]), encoding="utf-8")
    workspace.mkdir(parents=True, exist_ok=True)
    csv_path = workspace / f"{args.task_name}-{stamp}.csv"
    json_path = workspace / f"{args.task_name}-{stamp}.json"
    encoding = template.get("encoding", "utf-8")
    csv_path.write_text(deployment_csv(strategy, sites, template, args.effective_date), encoding=encoding,
                        newline="")
    json_path.write_text(json.dumps(strategy, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({
        "ok": True,
        "csv": str(csv_path),
        "strategy_json": str(json_path),
        "template_id": template.get("template_id"),
        "template_is_placeholder": bool(template.get("placeholder")),
        "sites": len(sites),
        "rules": [{k: r[k] for k in ("start", "end", "tier", "action", "power_kw", "soc_end_pct")}
                  for r in strategy["rules"]],
        "summary": strategy["summary"],
        "demo_only": "Not delivered to the live network; import the CSV in the Deployment UI by hand.",
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
