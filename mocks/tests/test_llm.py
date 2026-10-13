import json

import pytest
from fastapi.testclient import TestClient

from mocks.llm.app import UNSUPPORTED_REPLY, app, select_workflows

WORKFLOWS = [
    {"name": "SPN跨城专线故障诊断与抢通", "description": "SPN cross-city fault diagnosis", "tags": ["SPN"],
     "user_intent": "", "tasks": "", "id": "psop_spn"},
    {"name": "UC1 power-band energy saving", "description": "Fetch the power-band tariff and run energy saving",
     "tags": ["energy saving", "UC1"], "user_intent": "Power-band energy saving for a region", "tasks": "",
     "id": "psop_uc1"},
]


def retrieval_prompt(intent: str, top_n: int = 3) -> str:
    """Same layout as upstream orchestrate.core.prompts.get_retrieve_psop_prompt."""
    return (f"As a senior IT operations expert, select the top {top_n} most suitable existing PSOP workflow(s)\n"
            f"for the given user intent, ordered by relevance.\n\n## User Intent\n{intent}\n\n"
            f"## Available PSOP Workflows\n{json.dumps(WORKFLOWS, ensure_ascii=False, indent=2)}\n\n"
            f"## Selection Criteria\n1. **Intent Match**: ...\n\n## Output Format\nOutput a JSON array.")


def test_selects_the_matching_workflow():
    assert select_workflows(retrieval_prompt("Run power-band energy saving for Accra Central")) == [
        "UC1 power-band energy saving"]


def test_no_overlap_selects_nothing():
    assert select_workflows(retrieval_prompt("reboot the printer")) == []


def test_other_prompts_are_not_retrieval():
    assert select_workflows("Summarise this text") is None


@pytest.fixture
def client():
    return TestClient(app)


def test_chat_completions_shape(client):
    response = client.post("/v1/chat/completions", json={
        "model": "mock", "messages": [{"role": "user", "content": retrieval_prompt("energy saving for Kumasi")}]})
    assert response.status_code == 200
    content = response.json()["choices"][0]["message"]["content"]
    assert json.loads(content.strip("`").removeprefix("json")) == ["UC1 power-band energy saving"]


def test_chat_completions_other_prompt(client):
    response = client.post("/v1/chat/completions", json={"messages": [{"role": "user", "content": "hello"}]})
    assert response.json()["choices"][0]["message"]["content"] == UNSUPPORTED_REPLY
