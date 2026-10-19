"""The mock MAE against HQ's A2A-T client plugin contract (docs/henan-demo.md).

scripts/a2a_plugin_check.mjs runs the plugin itself against a live mock; these tests pin the
same wire behaviour without Node or the plugin bundle.
"""

import json

import pytest
from starlette.testclient import TestClient

from mocks.mae import optimization
from mocks.mae.server import build_app

HEADERS = {"A2A-Version": "1.0"}
PENDING = "HN-ZZ-JS-20261015-00031752"
DIAGNOSED = "HA-XNLC-PY-20260908-09674481"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("MOCK_MAE_STEP_DELAY_SECONDS", "0")
    return TestClient(build_app("http://testserver"))


def send(client, text, metadata=None, parts=None):
    body = {"message": {"messageId": "m-1", "contextId": "c-1", "role": "ROLE_USER",
                        "parts": parts or [{"text": text}], **({"metadata": metadata} if metadata else {})}}
    return client.post("/message:send", headers=HEADERS, json=body).json()["task"]


def stream(client, text, metadata=None):
    body = {"message": {"messageId": "m-1", "role": "ROLE_USER", "parts": [{"text": text}],
                        **({"metadata": metadata} if metadata else {})}}
    with client.stream("POST", "/message:stream", headers=HEADERS, json=body) as response:
        assert response.status_code == 200
        raw = response.read().decode()
    return [frame for frame in raw.split("\n\n") if frame.strip()]


def status_text(task):
    return task["status"]["message"]["parts"][0]["text"]


def result_of(task):
    for artifact in task.get("artifacts", []):
        return json.loads(artifact["parts"][0]["text"])["serviceManagement"]["RanOptimizationResult"]
    return None


def test_agent_card_at_root_without_version_header(client):
    card = client.get("/").json()
    assert card["supportedInterfaces"][0]["url"] == "http://testserver"
    assert card["capabilities"]["streaming"] is True
    assert {s["id"] for s in card["skills"]} >= {"energy-saving", "ran-complaint-optimization"}
    assert all({"id", "name", "description", "tags"} <= set(s) for s in card["skills"])


@pytest.mark.parametrize("method, path", [("post", "/message:send"), ("get", f"/ops/omc/status?issueId={PENDING}"),
                                          ("get", f"/ops/omc/advice?issueId={PENDING}")])
def test_calls_without_version_header_are_rejected(client, method, path):
    response = getattr(client, method)(path, **({"json": {}} if method == "post" else {}))
    assert response.status_code == 400
    assert response.json()["error"]["message"]


def test_stream_frames_are_numbered_and_end_in_a_terminal_state(client):
    frames = stream(client, "region: Zhengzhou", {"skill": "energy-saving"})
    assert all(frame.startswith(f"id:{i}\ndata:") for i, frame in enumerate(frames, start=1))
    events = [json.loads(frame.split("data:", 1)[1]) for frame in frames]
    assert "task" in events[0]
    assert any("artifactUpdate" in e for e in events)
    assert events[-1]["statusUpdate"]["status"]["state"] == "TASK_STATE_COMPLETED"
    # No "final" flag: A2A 1.0 dropped it and the a2a SDK client rejects it (see plugin_wire.py).
    assert "final" not in events[-1]["statusUpdate"]


def test_energy_saving_without_region_needs_input(client):
    frames = stream(client, "please save energy", {"skill": "energy-saving"})
    last = json.loads(frames[-1].split("data:", 1)[1])["statusUpdate"]
    assert last["status"]["state"] == "TASK_STATE_INPUT_REQUIRED"
    assert "请补充" in last["status"]["message"]["parts"][0]["text"]


def test_prose_is_not_parsed(client):
    task = send(client, "the cell near the station is slow")
    assert task["status"]["state"] == "TASK_STATE_FAILED"
    assert optimization.UNPARSED in status_text(task)


@pytest.mark.parametrize("text, marker", [
    ('{"problemType": "UP_LOW_THROUGHPUT"}', "缺少必选参数"),
    ("objectId: cell-17\nproblemType: UP_LOW_THROUGHPUT", "必须是小区 CGI"),
    ('{"objectId": "460-00-617089-1103", "problemType": "SLOW"}', "取值无效"),
    ('{"objectId": "460-00-617089-1103", "problemType": "UP_LOW_THROUGHPUT", "rat": "GSM"}', "取值无效"),
])
def test_invalid_work_orders_fail_with_the_plugin_markers(client, text, marker):
    task = send(client, text)
    assert task["status"]["state"] == "TASK_STATE_FAILED"
    assert marker in status_text(task)


def test_parameters_from_task_parameters_and_data_part(client):
    params = {"objectId": "460-00-617089-2201", "problemType": "WEAK_COVERAGE"}
    via_metadata = send(client, "see parameters", {"taskParameters": params})
    via_data = send(client, "", parts=[{"data": params}, {"text": "see data"}])
    assert result_of(via_metadata)["workOrderStatus"] in ("Created", "Exist")
    assert result_of(via_data)["issueId"] == result_of(via_metadata)["issueId"]


def test_ops_results_before_and_after_diagnosis(client):
    assert client.get(f"/ops/omc/status?issueId={DIAGNOSED}", headers=HEADERS).json()["statuses"]
    assert client.get(f"/ops/omc/advice?issueId={DIAGNOSED}", headers=HEADERS).json()["advices"]
    assert client.get(f"/ops/omc/status?issueId={PENDING}", headers=HEADERS).json() == {"statuses": []}
    assert client.get(f"/ops/omc/advice?issueId={PENDING}", headers=HEADERS).json() == {"advices": []}

    task = send(client, json.dumps({"issueId": PENDING, "objectId": "460-00-617089-1103",
                                    "problemType": "UP_LOW_THROUGHPUT"}))
    assert task["status"]["state"] == "TASK_STATE_COMPLETED"
    result = result_of(task)
    assert result["workOrderStatus"] == "Exist"
    assert result["rat"] == "NR"
    assert result["optimizationAdvice"]
    assert client.get(f"/ops/omc/advice?issueId={PENDING}", headers=HEADERS).json()["advices"]


def test_ops_needs_an_issue_id(client):
    response = client.get("/ops/omc/status", headers=HEADERS)
    assert response.status_code == 400
    assert "缺少必选参数" in response.json()["error"]["message"]


def test_known_issue_with_another_cell_is_rejected(client):
    task = send(client, json.dumps({"issueId": PENDING, "objectId": "460-00-1-1", "problemType": "CALL_DROP"}))
    assert task["status"]["state"] == "TASK_STATE_FAILED"
    assert "取值无效" in status_text(task)


def test_ledger_has_the_plugin_shape(client):
    ledger = client.get("/mock/work-orders").json()
    keys = {"issueId", "cgi", "cellName", "problemType", "problemDesc", "district", "submitTime"}
    assert ledger and all(set(entry) == keys for entry in ledger)


@pytest.mark.parametrize("text, expected", [
    ("issueId: A-1\nobjectId：460-00-1-2\nproblemType = CALL_DROP", {"issueId": "A-1", "objectId": "460-00-1-2",
                                                                     "problemType": "CALL_DROP"}),
    ('```json\n{"objectId": "460-00-1-2"}\n```', {"objectId": "460-00-1-2"}),
    ("no parameters here", {}),
])
def test_parse_parameters(text, expected):
    assert optimization.parse_parameters(text) == expected
