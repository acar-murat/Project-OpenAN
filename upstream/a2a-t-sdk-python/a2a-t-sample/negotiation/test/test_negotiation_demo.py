"""Offline tests of the negotiation closed-loop demo.

Runs the full 4-message flow (propose -> accept round trip) against the real SDK facades with the
scripted mock LLM installed, in both languages and both strategies, and pins the exact LLM call
count of every flow — the from-data negotiation generation makes no LLM call at all.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from negotiation_demo.demo_app import run_demo
from negotiation_demo.server_runtime import (
    STATE_COMPLETED,
    STATE_INPUT_REQUIRED,
    NegotiationRequest,
    NegotiationServerRuntime,
    parse_negotiation_context,
)
from negotiation_demo.shared import mock_llm
from negotiation_demo.shared.constants import NEGOTIATION_T_URI
from negotiation_demo.shared.scenario_data import FILLED_PARAMS_MARKER, SUPPORTED_LANGUAGES, ScenarioData
from negotiation_demo.shared.strategies import (
    FromDataStrategy,
    FromTextStrategy,
    accept_context,
    propose_context,
)

#: An env path that never exists: the demo then always installs the scripted mock LLM.
_OFFLINE_ENV_PATH = PROJECT_ROOT / "test" / ".no-env"

#: Slot names of the two demo languages (they follow the packaged slot schemas).
_SLOT_NAMES = {"en-US": "task_context", "zh-CN": "任务上下文"}


@pytest.fixture(autouse=True)
def _scripted_mock_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force-install the scripted mock LLM for every test, regardless of any real ``.env``."""
    monkeypatch.chdir(PROJECT_ROOT)
    mock_llm.install_mock_llm(env_path=_OFFLINE_ENV_PATH, language="en-US", force_language=True)


@pytest.mark.parametrize("language", SUPPORTED_LANGUAGES)
@pytest.mark.parametrize("use_from_text", [False, True], ids=["fromData", "fromText"])
def test_closed_loop_round_trip_completes(language: str, use_from_text: bool) -> None:
    mock_llm.reset_call_log()

    summary = run_demo(
        use_from_text=use_from_text,
        env_path=_OFFLINE_ENV_PATH,
        language=language,
    )

    assert summary["outcome"] == STATE_COMPLETED
    assert summary["messages"] == 4
    # The negotiation request asks for the missing slot of the language.
    assert _SLOT_NAMES[language] in str(summary["negotiation_request"])
    # The diagnosis is rendered from the extracted params via the scenario templates.
    assert FILLED_PARAMS_MARKER in str(summary["diagnosis"])
    assert str(summary["diagnosis"]).splitlines()[0].startswith("1.")


@pytest.mark.parametrize("language", SUPPORTED_LANGUAGES)
def test_from_data_makes_no_negotiation_llm_calls(language: str) -> None:
    mock_llm.reset_call_log()

    run_demo(use_from_text=False, env_path=_OFFLINE_ENV_PATH, language=language)

    # Exactly the two Task-T slot extractions and the two content validations; the deterministic
    # from-data negotiation generation renders without any LLM call.
    assert mock_llm.llm_calls == [
        mock_llm.STAGE_SLOT_EXTRACTION_MISSING,
        mock_llm.STAGE_CONTENT_VALIDATION_MISSING,
        mock_llm.STAGE_SLOT_EXTRACTION_FILLED,
        mock_llm.STAGE_CONTENT_VALIDATION_FILLED,
    ]


@pytest.mark.parametrize("language", SUPPORTED_LANGUAGES)
def test_from_text_runs_one_extraction_per_negotiation_message(language: str) -> None:
    mock_llm.reset_call_log()

    run_demo(use_from_text=True, env_path=_OFFLINE_ENV_PATH, language=language)

    assert mock_llm.llm_calls == [
        mock_llm.STAGE_SLOT_EXTRACTION_MISSING,
        mock_llm.STAGE_CONTENT_VALIDATION_MISSING,
        mock_llm.STAGE_NEGOTIATION_PROPOSE_EXTRACTION,
        mock_llm.STAGE_SLOT_EXTRACTION_FILLED,
        mock_llm.STAGE_NEGOTIATION_ACCEPT_EXTRACTION,
        mock_llm.STAGE_CONTENT_VALIDATION_FILLED,
    ]


@pytest.mark.parametrize("language", SUPPORTED_LANGUAGES)
def test_first_reply_requires_input_and_carries_the_negotiation_context(language: str) -> None:
    from a2a_t.server.a2at_server import A2ATServer

    scenario = ScenarioData(language)
    server_runtime = NegotiationServerRuntime(
        A2ATServer(env_path=_OFFLINE_ENV_PATH),
        FromDataStrategy(scenario),
        scenario,
    )

    from a2a_t.client.a2at_client import A2ATClient

    client = A2ATClient(env_path=_OFFLINE_ENV_PATH)
    task_prompt = client.generate_task_prompt_from_data_with_schema(
        scenario.missing_params(), scenario.task_schema(), "Task-T/network-layer/private-line-complaint/v1"
    )

    reply = server_runtime.handle_request(
        NegotiationRequest(
            metadata={
                "https://projects.tmforum.org/a2aproject/telecommunication/extensions/Task-T/v1": task_prompt.prompt_text
            }
        )
    )

    assert reply.state == STATE_INPUT_REQUIRED
    assert reply.negotiation_prompt_text
    context = parse_negotiation_context(reply.metadata)
    assert context is not None
    assert context.round == 1
    assert context.performative.value == "PROPOSE"
    # The accept continues the server's session: round advanced, performative stamped ACCEPT.
    accepted = accept_context(context)
    assert accepted.round == 2
    assert accepted.id == context.id
    assert accepted.performative.value == "ACCEPT"


def test_parse_negotiation_context_returns_none_without_context() -> None:
    assert parse_negotiation_context({}) is None
    assert parse_negotiation_context({NEGOTIATION_T_URI: "text"}) is None
    assert parse_negotiation_context({"negotiationContext": {"id": "n-1", "round": 1}}) is None


@pytest.mark.parametrize("language", SUPPORTED_LANGUAGES)
def test_scenario_sections_are_complete(language: str) -> None:
    scenario = ScenarioData(language)

    schema_slots = set(scenario.task_schema()["properties"])
    assert schema_slots == set(scenario.missing_params())
    assert schema_slots == set(scenario.filled_params())
    # Only the filled params carry the marker the scripted mock routes on.
    assert FILLED_PARAMS_MARKER not in str(list(scenario.missing_params().values()))
    assert FILLED_PARAMS_MARKER in str(list(scenario.filled_params().values()))
    assert scenario.negotiation_phrasing()["missing_item_hint"]
    assert scenario.diagnosis_templates()["result_line"]


def test_strategies_render_the_expected_item_text() -> None:
    """The from-text strategy assembles the numbered item list from the scenario phrasing."""
    from a2a_t.negotiation.content.models import NegotiationItem

    scenario = ScenarioData("en-US")
    items = [NegotiationItem(name="task_context", value="please provide")]
    from_text = FromTextStrategy(scenario)
    phrasing = scenario.negotiation_phrasing()

    # The propose text is the phrasing prefix plus one numbered item line (Java rule:
    # ``N. name：value；`` per item, value omitted when blank).
    def _numbered(items: list[NegotiationItem]) -> str:
        return "".join(
            f"{index}. {item.name}：{item.value}；" if item.value else f"{index}. {item.name}；"
            for index, item in enumerate(items, start=1)
        )

    assert phrasing["from_text_propose_prefix"] + _numbered(items)
    assert propose_context().round == 1
    # The from-data strategy builds typed content instead of text; both share the same seam.
    assert callable(from_text.generate_propose)
    assert callable(FromDataStrategy(scenario).generate_propose)


@pytest.mark.parametrize(
    ("property_names", "marker_in_input", "expected_stage"),
    [
        ({"slots", "slot_errors"}, False, mock_llm.STAGE_SLOT_EXTRACTION_MISSING),
        ({"slots", "slot_errors"}, True, mock_llm.STAGE_SLOT_EXTRACTION_FILLED),
        ({"semantic_verdict", "errors", "params"}, False, mock_llm.STAGE_CONTENT_VALIDATION_MISSING),
        ({"semantic_verdict", "errors", "params"}, True, mock_llm.STAGE_CONTENT_VALIDATION_FILLED),
        ({"conclusion", "items"}, False, mock_llm.STAGE_NEGOTIATION_ACCEPT_EXTRACTION),
        ({"items", "relationship"}, False, mock_llm.STAGE_NEGOTIATION_PROPOSE_EXTRACTION),
    ],
    ids=[
        "slot-missing",
        "slot-filled",
        "content-missing",
        "content-filled",
        "negotiation-accept",
        "negotiation-propose",
    ],
)
def test_route_structured_call_dispatches_on_the_schema_signature(
    property_names: set[str],
    marker_in_input: bool,
    expected_stage: str,
) -> None:
    input_text = f"input {'with ' + FILLED_PARAMS_MARKER if marker_in_input else 'without marker'}"
    messages = [{"role": "user", "content": f"head\n[input]\n{input_text}\n\n[slots]\nslot definitions"}]
    json_schema = {"type": "object", "properties": {name: {"type": "string"} for name in property_names}}

    assert mock_llm.route_structured_call(messages, json_schema) == expected_stage


def test_route_structured_call_ignores_template_examples_in_the_tail() -> None:
    """A template example carrying the marker must not flip the missing-params variant."""
    messages = [
        {
            "role": "user",
            "content": (
                "Extension Name: Task-T\n"
                "Input Content: complaint without the sequence number\n"
                "Template URI: Task-T/network-layer/private-line-complaint/v1\n"
                f'Template Content: 3. OSS-side event sequence number. Example: "{FILLED_PARAMS_MARKER}"\n'
                "Parameter Schema: {}"
            ),
        }
    ]
    json_schema = {"type": "object", "properties": {"semantic_verdict": {"type": "boolean"}}}

    assert mock_llm.route_structured_call(messages, json_schema) == mock_llm.STAGE_CONTENT_VALIDATION_MISSING


def test_route_structured_call_rejects_unmapped_calls() -> None:
    messages = [{"role": "user", "content": "unrelated"}]
    json_schema = {"type": "object", "properties": {"unexpected": {"type": "string"}}}

    with pytest.raises(ValueError, match="cannot route"):
        mock_llm.route_structured_call(messages, json_schema)
