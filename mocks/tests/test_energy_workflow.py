import pytest

from mocks.energy_agent import workflow
from mocks.mae.server import AGENT_NAME, agent_card_payload


def test_workflow_is_a_four_step_chain_ending_at_end():
    psop = workflow.psop()
    steps = psop["steps"]
    assert [s["name"] for s in steps] == [
        "power_band_tariff", "feasibility_negotiation", "ran_energy_saving", "intent_report"]
    for index, step in enumerate(steps):
        assert step["layer"] == index
        expected_next = steps[index + 1]["name"] if index + 1 < len(steps) else "end"
        assert step["next"] == [{"step": expected_next, "condition": ""}]
    assert psop["id"] == workflow.WORKFLOW_ID and psop["name"] == workflow.WORKFLOW_NAME


def test_mae_step_targets_the_mock_mae_skill():
    mae_step = workflow.psop()["steps"][2]["subtasks"][0]
    assert workflow.MAE_NAME == AGENT_NAME == mae_step["agent"]
    assert mae_step["skill"] in {skill["id"] for skill in agent_card_payload("http://x")["skills"]}


@pytest.mark.parametrize(("intent", "region", "scenario"), [
    ("Run power-band energy saving for Accra Central", "Accra Central", None),
    ("Energy saving for Kumasi scenario=infeasible", "Kumasi", "infeasible"),
    ("Power-band energy saving for Accra Central Region.", "Accra Central", None),
    ("region: Tamale", "Tamale", None),
    ("save some energy", workflow.DEFAULT_REGION, None),
    ("Cut the electricity bill of the sites in Kumasi", "Kumasi", None),
    ("Lower our tariff band charges at Takoradi", "Takoradi", None),
    ("save energy in accra central", "Accra Central", None),
    ("We pay too much for power at the Cape Coast sites", "Cape Coast", None),
    ("Run power-band energy saving for Sunyani", "Sunyani", None),
])
def test_region_and_scenario_from_intent(intent, region, scenario):
    assert workflow.region_of(intent) == region
    assert workflow.scenario_of(intent) == scenario


def test_workflow_passes_the_engine_validator():
    validator = pytest.importorskip("workflow_engine.core.workflow_validator")
    from workflow_engine import Workflow

    assert validator.find_workflow_errors(Workflow.from_dict(workflow.psop())) == []
