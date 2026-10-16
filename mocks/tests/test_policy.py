import pytest

from mocks.common import uc1_data
from mocks.energy_agent.policy import PolicyGuard


def test_no_configuration_allows_everything():
    assert PolicyGuard.from_env({}).check("Anywhere", uc1_data.intent_schedule()).allowed


@pytest.mark.parametrize(("region", "allowed"), [("Accra Central", True), ("accra central ", True), ("Kumasi", False)])
def test_region_allowlist(region, allowed):
    guard = PolicyGuard.from_env({"ENERGY_AGENT_POLICY_REGION_ALLOWLIST": "Accra Central, Tamale"})
    decision = guard.check(region, uc1_data.intent_schedule())
    assert decision.allowed is allowed
    assert bool(decision.reasons) is not allowed


def test_experience_floor_counts_none_as_zero_and_passes_no_degradation():
    guard = PolicyGuard.from_env({"ENERGY_AGENT_POLICY_MIN_EXPERIENCE_FLOOR": "5"})
    decision = guard.check("Accra Central", uc1_data.intent_schedule())
    # Only the overnight "none" period (23-5) is below the floor; the 10 Mbps periods pass.
    assert not decision.allowed
    assert len(decision.reasons) == 1 and "23-5" in decision.reasons[0]

    raised = PolicyGuard.from_env({"ENERGY_AGENT_POLICY_MIN_EXPERIENCE_FLOOR": "12"})
    assert len(raised.check("Accra Central", uc1_data.intent_schedule()).reasons) == 3


def test_saving_target_limit_applies_only_when_a_number_is_given():
    guard = PolicyGuard.from_env({"ENERGY_AGENT_POLICY_MAX_SAVING_TARGET": "30"})
    assert guard.check("Accra", []).allowed
    assert guard.check("Accra", [], saving_target=25).allowed
    assert not guard.check("Accra", [], saving_target=40).allowed


def test_saving_windows_refuse_saving_outside_them():
    # UC1 saves 23-5, 6-9 and 16-17; 10-15 and 18-22 are experience_first and never restricted.
    covering = PolicyGuard.from_env({"ENERGY_AGENT_POLICY_SAVING_WINDOWS": "23-9, 16-17"})
    assert covering.check("Accra", uc1_data.intent_schedule()).allowed
    night_only = PolicyGuard.from_env({"ENERGY_AGENT_POLICY_SAVING_WINDOWS": "22-6"})
    decision = night_only.check("Accra", uc1_data.intent_schedule())
    assert not decision.allowed
    assert [reason.split(" asks")[0] for reason in decision.reasons] == ["period 6-9", "period 16-17"]
    # A period must sit wholly inside one window, not across two.
    split = PolicyGuard.from_env({"ENERGY_AGENT_POLICY_SAVING_WINDOWS": "23-2,3-9,16-17"})
    assert not split.check("Accra", uc1_data.intent_schedule()).allowed
