"""Reference data from the original use-case deck (docs/use-cases.md).

UC1 (MTN power-band energy saving) supplies the power-band tariff and the
intent schedule; UC2 supplies the time-of-use relative prices. The mocks serve
these values so development and tests run against the deck's own numbers.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

#: UC1 input 2: billing band by power draw. Charges are in GHS and read as a
#: monthly charge per site (to be confirmed, open item O-21).
POWER_BAND_TARIFF: dict[str, Any] = {
    "currency": "GHS",
    "billing_period": "monthly",
    "bands": [
        {"band_no": 1, "min_kw": 0.00, "max_kw": 0.99, "charge": 8247.66},
        {"band_no": 2, "min_kw": 1.00, "max_kw": 1.99, "charge": 10628.25},
        {"band_no": 3, "min_kw": 2.00, "max_kw": 2.99, "charge": 11956.25},
        {"band_no": 4, "min_kw": 3.00, "max_kw": 3.99, "charge": 15409.75},
        {"band_no": 5, "min_kw": 4.00, "max_kw": 4.99, "charge": 17784.09},
    ],
}

#: UC2 time-of-use relative prices, in the LLD's price_table shape.
TIME_OF_USE_PRICES: list[dict[str, Any]] = [
    {"start_time": "00:00", "end_time": "05:59", "relative_price": 1.0},
    {"start_time": "06:00", "end_time": "09:59", "relative_price": 1.176},
    {"start_time": "10:00", "end_time": "15:59", "relative_price": 0.824},
    {"start_time": "16:00", "end_time": "17:59", "relative_price": 1.176},
    {"start_time": "18:00", "end_time": "21:59", "relative_price": 1.765},
    {"start_time": "22:00", "end_time": "23:59", "relative_price": 1.176},
]

#: UC1 input 1: energy-saving mode and experience target by time of day.
#: Hours are inclusive; the first period wraps past midnight.
INTENT_SCHEDULE: list[dict[str, Any]] = [
    {"start_hour": 23, "end_hour": 5, "saving_mode": "maximized_energy_saving",
     "experience_target": {"type": "none"}},
    {"start_hour": 6, "end_hour": 9, "saving_mode": "proactive_energy_saving",
     "experience_target": {"type": "rate_floor", "mbps": 10}},
    {"start_hour": 10, "end_hour": 15, "saving_mode": "experience_first",
     "experience_target": {"type": "no_degradation"}},
    {"start_hour": 16, "end_hour": 17, "saving_mode": "proactive_energy_saving",
     "experience_target": {"type": "rate_floor", "mbps": 10}},
    {"start_hour": 18, "end_hour": 22, "saving_mode": "experience_first",
     "experience_target": {"type": "no_degradation"}},
]


def power_band_tariff() -> dict[str, Any]:
    return deepcopy(POWER_BAND_TARIFF)


def time_of_use_prices() -> list[dict[str, Any]]:
    return deepcopy(TIME_OF_USE_PRICES)


def intent_schedule() -> list[dict[str, Any]]:
    return deepcopy(INTENT_SCHEDULE)


def band_for_kw(kw: float, tariff: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Return the tariff band a power draw falls into, or None above the top band."""
    for band in (tariff or POWER_BAND_TARIFF)["bands"]:
        if band["min_kw"] <= kw < band["max_kw"] + 0.01:
            return band
    return None
