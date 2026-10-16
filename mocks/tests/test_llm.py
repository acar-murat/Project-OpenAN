import json
import os
from unittest.mock import ANY

import pytest
from fastapi.testclient import TestClient

from mocks.energy_agent import workflow
from mocks.llm.app import UNSUPPORTED_REPLY, answer, app, select_workflows
from mocks.llm.cases import CASES, catalogues
from mocks.llm.prompts import (
    classify_prompt,
    extract_prompt,
    parse_classification,
    parse_extraction,
    select_prompt,
)
from scripts.llm_eval import USE_CASES, check_classify, check_extract, check_select

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


# The three LLM use cases against the phrasing set (mocks/llm/cases.py). scripts/llm_eval.py runs the same
# set against a real model; test_real_model_phrasings below does that when one is configured.

MOCK_CASES = [c for c in CASES if c.mock]


@pytest.mark.parametrize("case", MOCK_CASES, ids=lambda c: c.id)
def test_mock_classifies_each_phrasing(case):
    assert check_classify(case, answer(classify_prompt(case.text))) == (True, ANY)


@pytest.mark.parametrize("case", [c for c in MOCK_CASES if c.energy], ids=lambda c: c.id)
def test_mock_extracts_each_phrasing(case):
    assert check_extract(case, answer(extract_prompt(case.text))) == (True, ANY)


@pytest.mark.parametrize("catalogue", ["dev", "extended"])
@pytest.mark.parametrize("case", MOCK_CASES, ids=lambda c: c.id)
def test_mock_selects_each_phrasing(case, catalogue):
    prompt = select_prompt(case.text, list(catalogues()[catalogue].values()))
    assert check_select(case, catalogue, answer(prompt)) == (True, ANY)


def test_select_prompt_is_the_upstream_prompt():
    prompt = select_prompt("energy saving for Kumasi", [workflow.psop()])
    assert "## User Intent\nenergy saving for Kumasi" in prompt and "Language Consistency" in prompt
    assert json.loads(prompt.split("## Available PSOP Workflows\n")[1].split("\n\n## ")[0])[0]["tasks"].startswith(
        "[power_band_tariff] Fetch the power-band tariff")


@pytest.mark.parametrize("bad", [
    '{"is_energy_saving_intent": true}',
    '{"is_energy_saving_intent": "yes", "confidence": 0.9}',
    '{"is_energy_saving_intent": true, "confidence": 1.5}',
    '{"is_energy_saving_intent": true, "confidence": 0.9, "reason": "free text"}',
    "Yes, it is.",
])
def test_classifier_answer_is_held_to_two_fields(bad):
    with pytest.raises(ValueError):
        parse_classification(bad)


def test_extraction_lists_missing_fields_and_rejects_unknown_modes():
    value = parse_extraction(
        'Sure:\n```json\n{"region": "Kumasi", "saving_mode": null, "experience_target": null}\n```')
    assert value["missing_fields"] == ["saving_mode", "experience_target"]
    with pytest.raises(ValueError):
        parse_extraction('{"region": "Kumasi", "saving_mode": "turbo", "experience_target": null}')
    with pytest.raises(ValueError):
        parse_extraction('{"region": "Kumasi", "saving_mode": null, "experience_target": {"type": "rate_floor"}}')


@pytest.mark.skipif(not (os.environ.get("OPENAN_EVAL_LLM_URL") and os.environ.get("OPENAN_EVAL_LLM_MODEL")),
                    reason="no real model configured (OPENAN_EVAL_LLM_URL, OPENAN_EVAL_LLM_MODEL)")
def test_real_model_phrasings():
    from scripts.llm_eval import openai_chat, run

    ask = openai_chat(os.environ["OPENAN_EVAL_LLM_URL"], os.environ["OPENAN_EVAL_LLM_MODEL"],
                      os.environ.get("OPENAN_EVAL_LLM_API_KEY", ""), timeout=60)
    failures = [f"{r.use_case} {r.catalogue} {r.case.id}: {r.got}" for r in run(ask, "openai", 1, set(USE_CASES))
                if not r.ok]
    assert not failures, "\n".join(failures)
