"""Exercise the mock MAE over its real A2A HTTP+JSON routes."""

import json

import pytest
from starlette.testclient import TestClient

from mocks.common import uc1_data
from mocks.common.a2at import (
    ENERGY_SAVING_TEMPLATE_URI,
    NEGOTIATION_T_EXTENSION_URI,
    TASK_T_EXTENSION_URI,
)
from mocks.mae.server import agent_card_payload, build_app

HEADERS = {"A2A-Version": "1.0"}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("MOCK_MAE_STEP_DELAY_SECONDS", "0")
    monkeypatch.setenv("MOCK_MAE_SCENARIO", "auto")
    monkeypatch.setenv("MOCK_MAE_MAX_RATE_FLOOR_MBPS", "20")
    return TestClient(build_app("http://testserver"))


def message(metadata, text="request"):
    return {"message": {"messageId": "m-1", "role": "ROLE_USER", "parts": [{"text": text}], "metadata": metadata}}


def negotiate(client, content, **extra):
    response = client.post("/message:send", headers=HEADERS,
                           json=message({NEGOTIATION_T_EXTENSION_URI: json.dumps(content), **extra}))
    assert response.status_code == 200, response.text
    return json.loads(response.json()["message"]["metadata"][NEGOTIATION_T_EXTENSION_URI])


def stream_task(client, slots, **extra):
    metadata = {TASK_T_EXTENSION_URI: json.dumps(slots), "templateUri": ENERGY_SAVING_TEMPLATE_URI, **extra}
    with client.stream("POST", "/message:stream", headers=HEADERS, json=message(metadata)) as response:
        assert response.status_code == 200
        return [json.loads(line[5:]) for line in response.iter_lines() if line.startswith("data:")]


def final_state(events):
    states = [e["statusUpdate"]["status"]["state"] for e in events if "statusUpdate" in e]
    return states[-1] if states else events[-1]["task"]["status"]["state"]


def artifact_types(events):
    return [json.loads(e["artifactUpdate"]["artifact"]["metadata"][TASK_T_EXTENSION_URI])["type"]
            for e in events if "artifactUpdate" in e]


def test_agent_card_is_served(client):
    card = client.get("/.well-known/agent-card.json").json()
    assert card["name"] == "Mock MAE"
    uris = {ext["uri"] for ext in card["capabilities"]["extensions"]}
    assert {TASK_T_EXTENSION_URI, NEGOTIATION_T_EXTENSION_URI} <= uris
    assert agent_card_payload("http://x")["supportedInterfaces"][0]["url"] == "http://x"


def test_feasible_negotiation_then_accept(client):
    reply = negotiate(client, {"message_class": "initiate_feasibility_assessment", "negotiation_id": "n-1",
                               "under_evaluation_description": {"region": "Accra Central"}})
    assert reply["message_class"] == "feasible_request_confirmation"
    assert reply["negotiation_id"] == "n-1"
    closed = negotiate(client, {"message_class": "accept", "negotiation_id": "n-1"})
    assert closed == {"category": "goal_achievement", "message_class": "negotiation_closed",
                      "negotiation_id": "n-1", "round": 1, "outcome": "agreed"}


def test_infeasible_negotiation_returns_counter_proposal(client):
    schedule = uc1_data.intent_schedule()
    schedule[1]["experience_target"]["mbps"] = 40
    reply = negotiate(client, {"message_class": "initiate_feasibility_assessment",
                               "under_evaluation_description": {"region": "Accra", "schedule": schedule}})
    assert reply["message_class"] == "infeasible_with_proposal"
    assert reply["proposal"]["schedule"][1]["experience_target"]["mbps"] == 20


def test_scenario_override_forces_infeasible(client):
    reply = negotiate(client, {"message_class": "initiate_feasibility_assessment",
                               "under_evaluation_description": {"region": "Accra"}}, mockScenario="infeasible")
    assert reply["message_class"] == "infeasible_with_proposal"


@pytest.mark.parametrize("message_class, outcome", [("reject", "aborted"), ("abort", "aborted")])
def test_reject_and_abort_close_the_negotiation(client, message_class, outcome):
    assert negotiate(client, {"message_class": message_class})["outcome"] == outcome


def test_task_streams_artifacts_and_completes(client):
    events = stream_task(client, {"task_object": "Accra Central", "operation_type": "Create"})
    assert events[0]["task"]["status"]["state"] == "TASK_STATE_SUBMITTED"
    assert artifact_types(events) == ["TaskPlan", "BandPrediction", "SiteClassification", "TrafficMigrationPlan",
                                      "EnergySavingActivated", "IntentReport"]
    assert final_state(events) == "TASK_STATE_COMPLETED"


def test_task_without_region_is_rejected(client):
    events = stream_task(client, {"operation_type": "Create"})
    assert final_state(events) == "TASK_STATE_REJECTED"
    assert artifact_types(events) == []


def test_exec_failure_scenario_fails_mid_task(client):
    events = stream_task(client, {"task_object": "Accra"}, mockScenario="exec_failure")
    assert final_state(events) == "TASK_STATE_FAILED"
    assert artifact_types(events) == ["TaskPlan", "BandPrediction"]


def test_wrong_template_is_rejected(client):
    metadata = {TASK_T_EXTENSION_URI: json.dumps({"task_object": "A"}), "templateUri": "Task-T/other/v1"}
    with client.stream("POST", "/message:stream", headers=HEADERS, json=message(metadata)) as response:
        events = [json.loads(line[5:]) for line in response.iter_lines() if line.startswith("data:")]
    assert final_state(events) == "TASK_STATE_REJECTED"


def test_plain_message_without_parameters_fails_with_usage_hint(client):
    response = client.post("/message:send", headers=HEADERS, json=message({}))
    status = response.json()["task"]["status"]
    assert status["state"] == "TASK_STATE_FAILED"
    assert "未解析出任务参数" in status["message"]["parts"][0]["text"]


def test_accepting_an_infeasible_verdict_closes_infeasible(client):
    closed = negotiate(client, {"message_class": "accept", "accepted": "infeasible_with_proposal",
                                "negotiation_id": "n-2", "round": 1})
    assert closed["outcome"] == "closed_infeasible"
