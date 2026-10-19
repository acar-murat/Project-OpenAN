"""The Henan demo page's API."""

import pytest
from fastapi.testclient import TestClient

from henan_demo.app import SKILL_ROOT, app
from mocks.common.a2at import TASK_T_EXTENSION_URI

SAMPLE = (SKILL_ROOT / "assets" / "sample-tariff.csv").read_text(encoding="utf-8")


@pytest.fixture
def client():
    return TestClient(app)


def body(**extra):
    return {"tariff_csv": SAMPLE, "sites": ["HN-ZZ-BTS-0001", "HN-ZZ-BTS-0002"], **extra}


def test_page_and_sample(client):
    assert "功能一" in client.get("/").text
    assert client.get("/api/sample-tariff").text == SAMPLE
    config = client.get("/api/config").json()
    assert config["template"]["placeholder"] is True
    assert config["battery"]["soc_min_pct"] == 40


def test_strategy_has_rules_fleet_preview_and_display_only_intent(client):
    result = client.post("/api/strategy", json=body()).json()
    assert result["rules"] and result["summary"]["daily_saving"] > 0
    assert result["fleet"]["monthly_saving"] == pytest.approx(2 * result["summary"]["monthly_saving"], abs=0.02)
    preview = result["deployment_preview"]
    assert preview["placeholder"] and preview["row_count"] == 2 * sum(r["action"] != "hold" for r in result["rules"])
    assert result["intent"]["sent"] is False
    assert result["intent"]["metadata"][TASK_T_EXTENSION_URI]["task_context"]["power_vendor"] == "Huawei"


def test_battery_overrides(client):
    small = client.post("/api/strategy", json=body(battery={"capacity_kwh": 5})).json()
    large = client.post("/api/strategy", json=body()).json()
    assert small["summary"]["daily_saving"] < large["summary"]["daily_saving"]


def test_export_downloads_the_csv(client):
    response = client.post("/api/export", json=body(effective_date="2026-10-20"))
    assert response.status_code == 200
    assert 'filename="battery-strategy-2026-10-20-PLACEHOLDER-template.csv"' in response.headers["content-disposition"]
    text = response.content.decode("utf-8-sig")
    assert text.startswith("NE Name,Power Vendor,Rule ID")
    assert "HN-ZZ-BTS-0002" in text


@pytest.mark.parametrize("payload, message", [
    (body(tariff_csv="start_time,end_time,tier,price\n00:00,10:00,flat,1\n"), "gap"),
    (body(sites=[" "]), "at least one site"),
    (body(sites=["bad;name"]), "site names"),
    (body(battery={"voltage": 48}), "unknown battery fields"),
    (body(battery={"soc_min_pct": 99}), "SoC"),
])
def test_bad_requests_are_explained(client, payload, message):
    response = client.post("/api/strategy", json=payload)
    assert response.status_code == 422
    assert message in response.json()["detail"]
