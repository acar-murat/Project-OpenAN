import json

import pytest

from mocks.common import uc1_data
from mocks.mae import planning


def test_parse_intent_from_task_t_slots():
    intent = planning.parse_intent(json.dumps({
        "task_object": "Accra Central",
        "operation_type": "Modify",
        "task_target": {"schedule": uc1_data.intent_schedule()},
        "task_context": {"power_band_tariff": uc1_data.power_band_tariff()},
    }))
    assert intent.region == "Accra Central"
    assert intent.operation_type == "Modify"
    assert len(intent.schedule) == 5


def test_parse_intent_from_negotiation_content():
    intent = planning.parse_intent({"under_evaluation_description": {"region": "Kumasi"}})
    assert intent.region == "Kumasi"
    assert intent.schedule == uc1_data.intent_schedule()


@pytest.mark.parametrize("text", [
    "Create a RAN energy-saving task for Accra Central Region to maximize energy savings.",
    "region: Accra Central; target: maximize",
])
def test_parse_intent_from_free_text(text):
    assert planning.parse_intent(text).region == "Accra Central"


def test_parse_intent_without_region_fails():
    with pytest.raises(planning.IntentError):
        planning.parse_intent({"task_target": {}})
    with pytest.raises(planning.IntentError):
        planning.parse_intent("maximize energy saving please")


def test_uc1_schedule_is_feasible():
    assert planning.assess_feasibility(planning.Intent(region="A"))["feasible"] is True


def test_high_rate_floor_is_infeasible_with_capped_proposal(monkeypatch):
    monkeypatch.setenv("MOCK_MAE_MAX_RATE_FLOOR_MBPS", "20")
    schedule = uc1_data.intent_schedule()
    schedule[1]["experience_target"]["mbps"] = 50
    result = planning.assess_feasibility(planning.Intent(region="A", schedule=schedule))
    assert result["feasible"] is False
    assert "50" in result["reasons"][0]
    assert result["proposal"]["schedule"][1]["experience_target"]["mbps"] == 20
    assert schedule[1]["experience_target"]["mbps"] == 50  # the request itself is not modified


def test_plan_is_deterministic_and_saves_money():
    first = planning.build_artifacts(planning.Intent(region="Accra Central"))
    second = planning.build_artifacts(planning.Intent(region="Accra Central"))
    assert first == second
    assert [a["type"] for a in first] == [
        "TaskPlan", "BandPrediction", "SiteClassification", "TrafficMigrationPlan", "EnergySavingActivated",
        "IntentReport",
    ]
    report = first[-1]
    assert report["predicted_cost_after"] <= report["predicted_cost_before"]
    assert report["predicted_saving"] == pytest.approx(report["predicted_cost_before"] - report["predicted_cost_after"])


@pytest.mark.parametrize("region", ["Accra Central", "Kumasi", "Tamale", "Takoradi", "Cape Coast"])
def test_migration_conserves_load_and_respects_headroom(region):
    intent = planning.Intent(region=region, site_count=20)
    sites = planning.predict_sites(intent)
    migration = planning.plan_migration(intent, sites)
    shed = sum(a["load_kw"] for a in migration["actions"] if a["direction"] == "out")
    taken = sum(a["load_kw"] for a in migration["actions"] if a["direction"] == "in")
    assert taken + migration["unplaced_kw"] == pytest.approx(shed, abs=0.02)
    bands = {b["band_no"]: b for b in intent.tariff["bands"]}
    for site in sites:
        if site["classification"] == "grade_stable":
            limit = bands[site["predicted_band"]]["max_kw"] - planning.ABSORB_HEADROOM_KW
            assert migration["after_kw"][site["site_id"]] <= max(limit, site["predicted_kw"]) + 1e-9


def test_downgrade_sites_drop_a_band():
    intent = planning.Intent(region="Accra Central")
    sites = planning.predict_sites(intent)
    migration = planning.plan_migration(intent, sites)
    for site in sites:
        if site["classification"] == "downgrade":
            after = uc1_data.band_for_kw(migration["after_kw"][site["site_id"]])
            assert after["band_no"] == site["predicted_band"] - 1


def test_experience_first_periods_are_excluded_from_activation():
    report = planning.build_artifacts(planning.Intent(region="A"))
    activated = next(a for a in report if a["type"] == "EnergySavingActivated")
    assert {(p["start_hour"], p["end_hour"]) for p in activated["active_periods"]} == {(23, 5), (6, 9), (16, 17)}
