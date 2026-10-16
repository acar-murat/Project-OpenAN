"""Documented test cases for the mock Energy Agent's workflow steps.

The ControlPoint talks to the real mock price API and mock MAE apps in process
(``httpx.ASGITransport``), so every case runs the same code as the dev stack without
opening ports. Needs the workflow-engine SDK, so it runs in the Orchestration Center's
virtualenv (``scripts/dev.py test``) and is skipped in the plain mocks environment.
"""

import json
from types import SimpleNamespace

import httpx
import pytest

pytest.importorskip("workflow_engine")

from mocks.common import audit  # noqa: E402
from mocks.energy_agent import control_point, workflow  # noqa: E402
from mocks.energy_agent.policy import PolicyGuard  # noqa: E402
from mocks.mae.server import build_app as build_mae_app  # noqa: E402
from mocks.price_api.app import app as price_app  # noqa: E402

SUITE = "Mock Energy Agent (workflow steps against mock MAE and price API)"
INTENT = "Run power-band energy saving for Accra Central"


class Router(httpx.AsyncBaseTransport):
    """Sends each request to the in-process app for its host."""

    def __init__(self, apps):
        self._transports = {host: httpx.ASGITransport(app=app) for host, app in apps.items()}

    async def handle_async_request(self, request):
        return await self._transports[request.url.host].handle_async_request(request)


@pytest.fixture
def stack(monkeypatch, tmp_path):
    for name, value in {"MOCK_MAE_STEP_DELAY_SECONDS": "0", "MOCK_MAE_SCENARIO": "auto",
                        "MOCK_MAE_MAX_RATE_FLOOR_MBPS": "20", "MOCK_MAE_SLOW_SECONDS": "1",
                        "MOCK_PRICE_MODE": "normal", "MOCK_PRICE_SLOW_SECONDS": "1"}.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("MOCK_PRICE_API_KEY", raising=False)
    monkeypatch.delenv("ENERGY_AGENT_PRICE_API_KEY", raising=False)
    mae_app = build_mae_app("http://mae.test")
    router = Router({"mae.test": mae_app, "price.test": price_app})
    real_client = httpx.AsyncClient

    def routed_client(**kwargs):
        kwargs.pop("trust_env", None)
        return real_client(transport=router, **kwargs)

    monkeypatch.setattr(control_point.httpx, "AsyncClient", routed_client)
    monkeypatch.setattr(control_point.registry, "find_card", lambda *_args: None)
    log = tmp_path / "ea-audit.jsonl"

    def make(**options):
        return control_point.EnergySavingControlPoint(
            price_url="http://price.test", registry_url="http://registry.test", mae_url="http://mae.test",
            audit_log=audit.AuditLog(log), **options)

    return SimpleNamespace(make=make, log=log, mae=real_client(transport=router, base_url="http://mae.test"))


class RateFloorGuard(PolicyGuard):
    """Applies the experience floor to rate-floor periods only; the UC1 schedule's "none" target in
    hours 23-5 would otherwise fail every floor above 0 in round 1."""

    def check(self, region, schedule, saving_target=None):
        floors = [p for p in schedule if p["experience_target"].get("type") == "rate_floor"]
        return super().check(region, floors, saving_target)


def step(skill, name, intent, upstream=()):
    return SimpleNamespace(execution_id="exec-1", skill=skill, step_name=name,
                           workflow_input=SimpleNamespace(runtime_intent=intent, upstream_results=upstream))


def records(path):
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def rounds_sent(path):
    return [(r["detail"]["round"], r["detail"]["sent"]["message_class"]) for r in records(path)
            if r["event"] == "negotiation_round" and r["detail"].get("sent")]


def summary(result):
    return {"success": result.success, "error_code": result.error_code,
            "text": (result.outputs[0] if result.success else result.error)}


async def negotiate(stack, intent, **options):
    point = stack.make(**options)
    tariff = await point.on_self_task(step(workflow.SKILL_TARIFF, "power_band_tariff", intent))
    if not tariff.success:
        return tariff
    return await point.on_self_task(step(workflow.SKILL_FEASIBILITY, "feasibility_negotiation", intent))


async def run_task_and_report(stack, point, intent):
    """The workflow engine's part (send on_task's content to MAE) and the report step."""
    request = SimpleNamespace(agent_name=workflow.MAE_NAME, skill=workflow.SKILL_ENERGY_SAVING,
                              workflow_input=SimpleNamespace(runtime_intent=intent, upstream_results=()))
    content = await point.on_task(request)
    body = {"message": {"messageId": "m-1", "role": "ROLE_USER", "parts": [{"text": content.parts[0].text}],
                        "metadata": dict(content.metadata)}}
    artifacts = []
    async with stack.mae.stream("POST", "/message:stream", headers={"A2A-Version": "1.0"}, json=body) as response:
        async for line in response.aiter_lines():
            if line.startswith("data:") and "artifactUpdate" in (event := json.loads(line[5:])):
                artifacts.append(SimpleNamespace(metadata=event["artifactUpdate"]["artifact"]["metadata"]))
    upstream = (SimpleNamespace(task_results=(SimpleNamespace(
        received_messages=(SimpleNamespace(artifacts=tuple(artifacts)),)),)),)
    return await point.on_self_task(step(workflow.SKILL_REPORT, "intent_report", intent, upstream))


async def test_ea01_full_workflow(stack, case):
    case.define("EA-01", "UC1 end to end: tariff, agreed negotiation, Task-T, intent report", suite=SUITE,
                lld="§3 happy path", input={"intent": INTENT},
                expected={"tariff": True, "negotiation": True, "rounds": [(1, "initiate_feasibility_assessment"),
                                                                          (1, "accept")],
                          "report": True, "report_has_kpis": True, "audit_chain_valid": True})
    point = stack.make()
    tariff = await point.on_self_task(step(workflow.SKILL_TARIFF, "power_band_tariff", INTENT))
    negotiation = await point.on_self_task(step(workflow.SKILL_FEASIBILITY, "feasibility_negotiation", INTENT))
    report = await run_task_and_report(stack, point, INTENT)
    text = report.outputs[0] if report.success else report.error
    case.check({"tariff": tariff.success, "negotiation": negotiation.success, "rounds": rounds_sent(stack.log),
                "report": report.success, "report_has_kpis": "Avg user rate" in text and "Predicted energy" in text,
                "audit_chain_valid": audit.verify(stack.log) == [], "negotiation_text": summary(negotiation)["text"]})


async def test_ea02_price_api_error(stack, case):
    case.define("EA-02", "Price API answers 503", suite=SUITE, lld="§4 F4 price_api_unavailable",
                input={"intent": INTENT + " scenario=price_api_error"},
                expected={"success": False, "error_code": "energy_agent.price_api_unavailable"})
    point = stack.make()
    result = await point.on_self_task(step(workflow.SKILL_TARIFF, "power_band_tariff",
                                           INTENT + " scenario=price_api_error"))
    case.check(summary(result))


async def test_ea03_price_api_timeout(stack, case):
    case.define("EA-03", "Price API slower than the Energy Agent's timeout", suite=SUITE,
                lld="§4 F4 price_api_unavailable",
                input={"intent": INTENT + " scenario=price_api_slow", "price_timeout_s": 0.2, "price_delay_s": 1},
                expected={"success": False, "error_code": "energy_agent.price_api_unavailable",
                          "mentions_timeout": True})
    point = stack.make(price_timeout=0.2)
    result = summary(await point.on_self_task(step(workflow.SKILL_TARIFF, "power_band_tariff",
                                                   INTENT + " scenario=price_api_slow")))
    case.check({**result, "mentions_timeout": "did not answer within 0.2 s" in result["text"]})


async def test_ea04_unknown_region(stack, case):
    case.define("EA-04", "Price API has no tariff for the region", suite=SUITE, lld="§4 F4",
                input={"intent": "Run power-band energy saving for Nowhere"},
                expected={"success": False, "error_code": "energy_agent.price_api_unavailable", "mentions_404": True})
    point = stack.make()
    result = summary(await point.on_self_task(step(workflow.SKILL_TARIFF, "power_band_tariff",
                                                   "Run power-band energy saving for Nowhere")))
    case.check({**result, "mentions_404": "404" in result["text"]})


async def test_ea05_infeasible_default_d1(stack, case):
    case.define("EA-05", "Infeasible verdict is accepted (D-1 default) and closes infeasible", suite=SUITE,
                lld="§4 F5, §11.5 D-1", input={"intent": INTENT + " scenario=infeasible"},
                expected={"success": False, "error_code": "energy_agent.infeasible",
                          "rounds": [(1, "initiate_feasibility_assessment"), (1, "accept")],
                          "last_outcome": "closed_infeasible", "has_counter_proposal": True})
    result = summary(await negotiate(stack, INTENT + " scenario=infeasible"))
    case.check({**result, "rounds": rounds_sent(stack.log), "last_outcome": records(stack.log)[-1]["detail"]["outcome"],
                "has_counter_proposal": "Counter-proposal" in result["text"]})


async def test_ea06_partially_feasible(stack, case):
    case.define("EA-06", "Partially feasible verdict goes back to the user with the adjusted saving target",
                suite=SUITE, lld="§11.5, §11.8 counter_proposal",
                input={"intent": INTENT + " scenario=partially_feasible"},
                expected={"success": False, "error_code": "energy_agent.infeasible", "says_partial": True,
                          "carries_adjusted_saving_target": True})
    result = summary(await negotiate(stack, INTENT + " scenario=partially_feasible"))
    case.check({**result, "says_partial": "partially feasible" in result["text"],
                "carries_adjusted_saving_target": "adjusted_saving_target" in result["text"]})


async def test_ea07_multi_round_without_relaxation(stack, case):
    case.define("EA-07", "Multi-round offer is not taken without consent (relaxation off)", suite=SUITE,
                lld="§11.5 D-1", input={"intent": INTENT + " scenario=multi_round", "allow_relaxation": False},
                expected={"success": False, "error_code": "energy_agent.infeasible",
                          "rounds": [(1, "initiate_feasibility_assessment"), (1, "accept")]})
    result = summary(await negotiate(stack, INTENT + " scenario=multi_round"))
    case.check({**result, "rounds": rounds_sent(stack.log)})


async def test_ea08_multi_round_with_relaxation(stack, case):
    case.define("EA-08", "With relaxation on, the agent re-initiates and agrees in round 2", suite=SUITE,
                lld="§5.2 INFEASIBLE_PROPOSAL -> INITIATED",
                input={"intent": INTENT + " scenario=multi_round", "allow_relaxation": True},
                expected={"success": True, "rounds": [(1, "initiate_feasibility_assessment"),
                                                      (2, "initiate_feasibility_assessment"), (2, "accept")],
                          "policy_checked_rounds": [1, 2], "says_2_rounds": True})
    result = summary(await negotiate(stack, INTENT + " scenario=multi_round", allow_relaxation=True))
    policy_rounds = [r["detail"]["round"] for r in records(stack.log) if r["event"] == "policy_decision"]
    case.check({**result, "rounds": rounds_sent(stack.log), "policy_checked_rounds": policy_rounds,
                "says_2_rounds": "2 rounds" in result["text"]})


async def test_ea09_round_limit(stack, case):
    case.define("EA-09", "Still infeasible at the round limit: the agent aborts", suite=SUITE,
                lld="§4 F6, §11.5 max rounds",
                input={"intent": INTENT + " scenario=infeasible", "allow_relaxation": True, "max_rounds": 3},
                expected={"success": False, "error_code": "energy_agent.negotiation_aborted",
                          "rounds": [(1, "initiate_feasibility_assessment"), (2, "initiate_feasibility_assessment"),
                                     (3, "initiate_feasibility_assessment"), (3, "abort")]})
    result = summary(await negotiate(stack, INTENT + " scenario=infeasible", allow_relaxation=True, max_rounds=3))
    case.check({**result, "rounds": rounds_sent(stack.log)})


@pytest.mark.parametrize(("case_id", "max_risk", "chosen"), [("EA-10", "medium", "SOL-2"), ("EA-11", "low", "SOL-1")])
async def test_ea10_ea11_solution_choice(stack, case, case_id, max_risk, chosen):
    case.define(case_id, f"Several solutions: picks the best saving with risk at most {max_risk}", suite=SUITE,
                lld="§11.5 selected_solution",
                input={"intent": INTENT + " scenario=multiple_solutions", "max_solution_risk": max_risk},
                expected={"success": True, "selected_solution": chosen})
    result = summary(await negotiate(stack, INTENT + " scenario=multiple_solutions", max_solution_risk=max_risk))
    picked = next((s for s in ("SOL-1", "SOL-2", "SOL-3") if f"Selected solution {s}" in result["text"]), None)
    case.check({**result, "selected_solution": picked})


async def test_ea12_negotiation_error(stack, case):
    case.define("EA-12", "MAE answers with an error: the agent aborts", suite=SUITE, lld="§4 F6",
                input={"intent": INTENT + " scenario=negotiation_error"},
                expected={"success": False, "error_code": "energy_agent.negotiation_aborted",
                          "rounds": [(1, "initiate_feasibility_assessment"), (1, "abort")]})
    result = summary(await negotiate(stack, INTENT + " scenario=negotiation_error"))
    case.check({**result, "rounds": rounds_sent(stack.log)})


async def test_ea13_round_timeout(stack, case):
    case.define("EA-13", "MAE slower than the per-round timeout: the agent aborts", suite=SUITE,
                lld="§11.5 per-round timeout",
                input={"intent": INTENT + " scenario=slow_negotiation", "round_timeout_s": 0.2, "mae_delay_s": 1},
                expected={"success": False, "error_code": "energy_agent.negotiation_aborted",
                          "timeout_audited": True, "abort_sent": True})
    result = summary(await negotiate(stack, INTENT + " scenario=slow_negotiation", round_timeout=0.2))
    log = records(stack.log)
    case.check({**result, "timeout_audited": any(r.get("reason") == "round_timeout" for r in log),
                "abort_sent": (1, "abort") in rounds_sent(stack.log)})


async def test_ea14_policy_violation(stack, case):
    case.define("EA-14", "Region outside the allowlist never reaches MAE", suite=SUITE, lld="§11.10, §11.11",
                input={"intent": INTENT, "region_allowlist": ["Tamale"]},
                expected={"success": False, "error_code": "energy_agent.policy_violation", "rounds": []})
    result = summary(await negotiate(stack, INTENT, policy=PolicyGuard(region_allowlist=frozenset({"tamale"}))))
    case.check({**result, "rounds": rounds_sent(stack.log)})


async def test_ea15_relaxed_target_breaks_policy(stack, case):
    case.define("EA-15", "A relaxed counter-proposal below the policy floor is refused and the negotiation aborted",
                suite=SUITE, lld="§11.10 target bounds",
                input={"intent": INTENT + " scenario=multi_round", "allow_relaxation": True,
                       "policy_min_floor_mbps": 9, "offered_floor_mbps": 8},
                expected={"success": False, "error_code": "energy_agent.policy_violation",
                          "rounds": [(1, "initiate_feasibility_assessment"), (1, "abort")]})
    result = summary(await negotiate(stack, INTENT + " scenario=multi_round", allow_relaxation=True,
                                     policy=RateFloorGuard(min_experience_floor_mbps=9)))
    case.check({**result, "rounds": rounds_sent(stack.log)})


async def test_ea16_report_partial_execution(stack, case):
    case.define("EA-16", "Report shows partial achievement and the cells that failed", suite=SUITE,
                lld="§11.8 final_report", input={"intent": INTENT + " scenario=partial_execution"},
                expected={"success": True, "says_partial": True, "lists_failed_cells": True})
    point = stack.make()
    result = summary(await run_task_and_report(stack, point, INTENT + " scenario=partial_execution"))
    case.check({**result, "says_partial": "achievement partial" in result["text"],
                "lists_failed_cells": "Cells not activated" in result["text"]})


async def test_ea17_report_after_mae_failure(stack, case):
    case.define("EA-17", "MAE's error artifact becomes the report step's failure reason", suite=SUITE,
                lld="§4 F8 (MAE reason)", input={"intent": INTENT + " scenario=exec_failure"},
                expected={"success": False, "error_code": "mae.cluster_optimization_failed"})
    point = stack.make()
    case.check(summary(await run_task_and_report(stack, point, INTENT + " scenario=exec_failure")))
