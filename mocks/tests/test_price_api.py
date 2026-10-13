import pytest
from fastapi.testclient import TestClient

from mocks.common import uc1_data
from mocks.price_api.app import app


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("MOCK_PRICE_API_KEY", raising=False)
    monkeypatch.setenv("MOCK_PRICE_MODE", "normal")
    return TestClient(app)


def test_power_band_tariff_serves_uc1_bands(client):
    response = client.get("/v1/tariffs/power-band", params={"region": "Accra Central"})
    assert response.status_code == 200
    body = response.json()
    assert body["region"] == "Accra Central"
    assert body["currency"] == "GHS"
    assert body["billing_period"] == "monthly"
    assert [b["charge"] for b in body["bands"]] == [8247.66, 10628.25, 11956.25, 15409.75, 17784.09]


def test_time_of_use_prices_cover_the_whole_day(client):
    body = client.get("/v1/prices/time-of-use", params={"region": "Accra", "date": "2026-10-13"}).json()
    assert body["date"] == "2026-10-13"
    table = body["price_table"]
    assert table[0]["start_time"] == "00:00" and table[-1]["end_time"] == "23:59"
    assert [row["relative_price"] for row in table] == [1.0, 1.176, 0.824, 1.176, 1.765, 1.176]


def test_unknown_region_is_404(client):
    assert client.get("/v1/tariffs/power-band", params={"region": "unknown"}).status_code == 404


def test_missing_region_is_422(client):
    assert client.get("/v1/tariffs/power-band").status_code == 422


def test_api_key_is_enforced_when_configured(client, monkeypatch):
    monkeypatch.setenv("MOCK_PRICE_API_KEY", "secret")
    assert client.get("/v1/tariffs/power-band", params={"region": "A"}).status_code == 401
    ok = client.get("/v1/tariffs/power-band", params={"region": "A"}, headers={"X-API-Key": "secret"})
    assert ok.status_code == 200
    assert client.get("/health").status_code == 200


def test_error_mode_returns_503_and_header_overrides_env(client, monkeypatch):
    monkeypatch.setenv("MOCK_PRICE_MODE", "error")
    assert client.get("/v1/tariffs/power-band", params={"region": "A"}).status_code == 503
    normal = client.get("/v1/tariffs/power-band", params={"region": "A"}, headers={"X-Mock-Mode": "normal"})
    assert normal.status_code == 200
    assert client.get("/health").status_code == 200


def test_unknown_mode_is_400(client):
    response = client.get("/v1/tariffs/power-band", params={"region": "A"}, headers={"X-Mock-Mode": "chaos"})
    assert response.status_code == 400


def test_band_for_kw_edges():
    assert uc1_data.band_for_kw(0.0)["band_no"] == 1
    assert uc1_data.band_for_kw(0.995)["band_no"] == 1
    assert uc1_data.band_for_kw(1.0)["band_no"] == 2
    assert uc1_data.band_for_kw(4.99)["band_no"] == 5
    assert uc1_data.band_for_kw(5.5) is None
