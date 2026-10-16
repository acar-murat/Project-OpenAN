"""The mock Energy Agent's ControlPoint against the real mock MAE app (in process).

Needs the workflow-engine SDK, so it runs in the Orchestration Center's virtualenv
(``scripts/dev.py test``) and is skipped in the plain mocks environment.
"""

import json
from types import SimpleNamespace

import httpx
import pytest

pytest.importorskip("workflow_engine")

from mocks.common import audit, uc1_data  # noqa: E402
from mocks.energy_agent import control_point, workflow  # noqa: E402
from mocks.energy_agent.policy import PolicyGuard  # noqa: E402
from mocks.mae.server import build_app  # noqa: E402


@pytest.fixture
def agent(monkeypatch, tmp_path):
    monkeypatch.setenv("MOCK_MAE_STEP_DELAY_SECONDS", "0")
    monkeypatch.setenv("MOCK_MAE_SCENARIO", "auto")
    app = build_app("http://mae.test")
    real_client = httpx.AsyncClient

    def mae_client(**kwargs):
        kwargs.pop("trust_env", None)
        return real_client(transport=httpx.ASGITransport(app=app), base_url="http://mae.test", **kwargs)

    monkeypatch.setattr(control_point.httpx, "AsyncClient", mae_client)
    monkeypatch.setattr(control_point.registry, "find_card", lambda *_args: None)

    def make(policy=None):
        point = control_point.EnergySavingControlPoint(
            price_url="http://price.test", registry_url="http://registry.test", mae_url="http://mae.test",
            policy=policy, audit_log=audit.AuditLog(tmp_path / "ea-audit.jsonl"))
        point._tariff = uc1_data.power_band_tariff()
        return point

    return make, tmp_path / "ea-audit.jsonl"


def feasibility_request(intent):
    return SimpleNamespace(execution_id="exec-1", skill=workflow.SKILL_FEASIBILITY, step_name="feasibility_negotiation",
                           workflow_input=SimpleNamespace(runtime_intent=intent, upstream_results=()))


def audit_records(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


async def test_feasible_negotiation_is_agreed_and_audited(agent):
    make, log = agent
    result = await make().on_self_task(feasibility_request("Run power-band energy saving for Accra Central"))
    assert result.success, result.error
    records = audit_records(log)
    assert [r["event"] for r in records] == ["policy_decision", "negotiation_round", "negotiation_round"]
    assert {r["trace_id"] for r in records} == {"exec-1"}
    assert records[-1]["detail"]["outcome"] == "agreed"
    assert len(records[-1]["detail"]["mae_card_digest"]) == 64
    assert records[1]["detail"]["price_table_digest"] == audit.digest(uc1_data.power_band_tariff())
    assert audit.verify(log) == []


async def test_infeasible_verdict_is_accepted_and_closed_infeasible(agent):
    make, log = agent
    result = await make().on_self_task(feasibility_request("Energy saving for Accra Central scenario=infeasible"))
    assert not result.success
    assert result.error_code == "energy_agent.infeasible"
    assert "not feasible" in result.error and "Counter-proposal" in result.error
    last = audit_records(log)[-1]["detail"]
    assert last["sent"]["message_class"] == "accept" and last["outcome"] == "closed_infeasible"


async def test_policy_violation_never_reaches_mae(agent):
    make, log = agent
    guard = PolicyGuard(region_allowlist=frozenset({"tamale"}))
    result = await make(guard).on_self_task(feasibility_request("Run power-band energy saving for Accra Central"))
    assert not result.success
    assert result.error_code == "energy_agent.policy_violation"
    [record] = audit_records(log)
    assert record["event"] == "policy_decision" and record["outcome"] == "denied"
    assert record["reason"] == "policy_violation"
