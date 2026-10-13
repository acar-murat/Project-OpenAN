"""Mock external electricity price API (stands in for the provider behind open item O-1).

Serves the two price shapes the requirements need:

* ``GET /v1/tariffs/power-band``: the UC1 power-band tariff (R-PRC-5).
* ``GET /v1/prices/time-of-use``: the LLD's time-of-use ``price_table`` (R-PRC-1), with UC2 data.

Behaviour is driven by environment variables so the Energy Agent's error paths
can be exercised:

* ``MOCK_PRICE_API_KEY``: when set, requests must send ``X-API-Key`` with this value.
* ``MOCK_PRICE_MODE``: ``normal`` (default), ``error`` (503), or ``slow`` (sleeps
  ``MOCK_PRICE_SLOW_SECONDS``, default 10, before answering). A request can
  override it with the ``X-Mock-Mode`` header.
"""

from __future__ import annotations

import asyncio
import os
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query

from mocks.common import uc1_data

#: Region names that answer 404, to exercise "unknown region" handling.
UNKNOWN_REGIONS = {"unknown", "nowhere"}
DEFAULT_TIMEZONE = "Africa/Accra"
MODES = ("normal", "error", "slow")


def _check_api_key(x_api_key: Annotated[str | None, Header()] = None) -> None:
    expected = os.environ.get("MOCK_PRICE_API_KEY", "")
    if expected and x_api_key != expected:
        raise HTTPException(status_code=401, detail="invalid or missing X-API-Key")


async def _apply_mode(x_mock_mode: Annotated[str | None, Header()] = None) -> None:
    mode = (x_mock_mode or os.environ.get("MOCK_PRICE_MODE", "normal")).lower()
    if mode not in MODES:
        raise HTTPException(status_code=400, detail=f"unknown mock mode {mode!r}; use one of {MODES}")
    if mode == "error":
        raise HTTPException(status_code=503, detail="price provider unavailable (mock error mode)")
    if mode == "slow":
        await asyncio.sleep(float(os.environ.get("MOCK_PRICE_SLOW_SECONDS", "10")))


def _check_region(region: str) -> str:
    region = region.strip()
    if not region:
        raise HTTPException(status_code=422, detail="region must not be empty")
    if region.lower() in UNKNOWN_REGIONS:
        raise HTTPException(status_code=404, detail=f"no prices for region {region!r}")
    return region


app = FastAPI(
    title="Mock Electricity Price API",
    version="1.0.0",
    description="Development stand-in for the external price API (open item O-1).",
)
v1 = APIRouter(prefix="/v1", dependencies=[Depends(_check_api_key), Depends(_apply_mode)])


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@v1.get("/tariffs/power-band")
def power_band_tariff(region: Annotated[str, Query()]) -> dict:
    """UC1 power-band tariff for a region."""
    region = _check_region(region)
    tariff = uc1_data.power_band_tariff()
    return {"region": region, "source": "mock", **tariff}


@v1.get("/prices/time-of-use")
def time_of_use_prices(
    region: Annotated[str, Query()], date_: Annotated[date | None, Query(alias="date")] = None
) -> dict:
    """Time-of-use relative prices for a region and day (UC2 data, LLD price_table shape)."""
    region = _check_region(region)
    return {
        "region": region,
        "date": (date_ or date.today()).isoformat(),
        "timezone": DEFAULT_TIMEZONE,
        "source": "mock",
        "price_table": uc1_data.time_of_use_prices(),
    }


app.include_router(v1)
