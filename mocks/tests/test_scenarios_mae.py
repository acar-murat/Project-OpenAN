"""Documented test cases for the mock MAE over its real A2A HTTP+JSON routes.

Each test records its case (``case`` fixture, see conftest.py) so ``scripts/test_report.py``
can list input, expected and actual result in ``docs/test-cases.md``.
"""

import json
import time

import pytest
from starlette.testclient import TestClient

from mocks.common import uc1_data
from mocks.common.a2at import ENERGY_SAVING_TEMPLATE_URI, NEGOTIATION_T_EXTENSION_URI, TASK_T_EXTENSION_URI
from mocks.mae.server import build_app

HEADERS = {"A2A-Version": "1.0"}
SUITE = "Mock MAE (A2A HTTP+JSON)"
REGION = "Accra Central"


@pytest.fixture
def client(monkeypatch):
    for name, value in {"MOCK_MAE_STEP_DELAY_SECONDS": "0", "MOCK_MAE_SCENARIO": "auto",
                        "MOCK_MAE_MAX_RATE_FLOOR_MBPS": "20", "MOCK_MAE_SLOW_SECONDS": "0.3",
                        "MOCK_MAE_EXEC_TIMEOUT_SECONDS": "0.1", "MOCK_MAE_SLOW_STEP_SECONDS": "0.05"}.items():
        monkeypatch.setenv(name, value)
    return TestClient(build_app("http://testserver"))


def _message(metadata):
    return {"message": {"messageId": "m-1", "role": "ROLE_USER", "parts": [{"text": "request"}],
                        "metadata": metadata}}


def negotiate(client, content, scenario=None):
    metadata = {NEGOTIATION_T_EXTENSION_URI: json.dumps(content)}
    if scenario:
        metadata["mockScenario"] = scenario
    response = client.post("/message:send", headers=HEADERS, json=_message(metadata))
    assert response.status_code == 200, response.text
    return json.loads(response.json()["message"]["metadata"][NEGOTIATION_T_EXTENSION_URI])


def opening(schedule=None, round_no=1, region=REGION):
    description = {"region": region, "schedule": schedule or uc1_data.intent_schedule()}
    return {"category": "goal_achievement", "message_class": "initiate_feasibility_assessment",
            "negotiation_id": "neg-1", "round": round_no, "under_evaluation_description": description}


def run_task(client, slots, scenario=None, template=ENERGY_SAVING_TEMPLATE_URI):
    metadata = {TASK_T_EXTENSION_URI: json.dumps(slots), "templateUri": template}
    if scenario:
        metadata["mockScenario"] = scenario
    with client.stream("POST", "/message:stream", headers=HEADERS, json=_message(metadata)) as response:
        assert response.status_code == 200
        events = [json.loads(line[5:]) for line in response.iter_lines() if line.startswith("data:")]
    statuses = [e["statusUpdate"]["status"] for e in events if "statusUpdate" in e]
    artifacts = [json.loads(e["artifactUpdate"]["artifact"]["metadata"][TASK_T_EXTENSION_URI])
                 for e in events if "artifactUpdate" in e]
    final = statuses[-1] if statuses else events[-1]["task"]["status"]
    return {"state": final["state"].removeprefix("TASK_STATE_"), "text": final["message"]["parts"][0]["text"],
            "artifacts": artifacts, "types": [a["type"] for a in artifacts]}


def slots(region=REGION, schedule=None):
    return {"task_object": region, "operation_type": "Create", "task_description": f"Energy saving for {region}",
            "task_target": {"schedule": schedule or uc1_data.intent_schedule()},
            "task_context": {"power_band_tariff": uc1_data.power_band_tariff()}}


FULL_STREAM = ["TaskPlan", "BandPrediction", "SiteClassification", "TrafficMigrationPlan", "CellSelection",
               "EnergySavingActivated", "IntentReport"]


# Negotiation-T -----------------------------------------------------------------------------------

def test_n01_feasible(client, case):
    case.define("MAE-N01", "Feasible intent is confirmed with an expected outcome", suite=SUITE, lld="§5.2, §11.5",
                input={"scenario": "auto", "region": REGION, "schedule": "UC1 default (rate floors 10 Mbps)"},
                expected={"message_class": "feasible_request_confirmation", "feasibility": "full",
                          "saving_quoted": True, "accept_outcome": "agreed"})
    reply = negotiate(client, opening())
    closed = negotiate(client, {"message_class": "accept", "accepted": reply["message_class"],
                                "negotiation_id": "neg-1", "round": 1})
    case.check({"message_class": reply["message_class"], "feasibility": reply["feasibility"],
                "saving_quoted": reply["expected_outcome"]["predicted_monthly_saving"] > 0,
                "expected_outcome": reply["expected_outcome"], "accept_outcome": closed["outcome"]})


def test_n02_rate_floor_too_high_is_partially_feasible(client, case):
    schedule = uc1_data.intent_schedule()
    schedule[1]["experience_target"]["mbps"] = 40
    case.define("MAE-N02", "Rate floor above the cluster limit gives a partial verdict and a capped proposal",
                suite=SUITE, lld="§4 F5, §11.5",
                input={"scenario": "auto", "schedule": "hours 6-9 rate floor 40 Mbps (limit 20)"},
                expected={"message_class": "infeasible_with_proposal", "feasibility": "partial",
                          "infeasible_periods": ["6-9"], "proposed_mbps_6_9": 20,
                          "counter_proposal": {"adjusted_experience_target": "rate floor 20 Mbps in hours 6-9"}})
    reply = negotiate(client, opening(schedule))
    case.check({"message_class": reply["message_class"], "feasibility": reply["feasibility"],
                "infeasible_periods": [p["period"] for p in reply["periods"] if not p["feasible"]],
                "proposed_mbps_6_9": reply["proposal"]["schedule"][1]["experience_target"]["mbps"],
                "counter_proposal": reply["counter_proposal"], "basis": reply["basis"]})


def test_n03_forced_infeasible_closes_infeasible(client, case):
    case.define("MAE-N03", "Forced infeasible verdict; accepting it closes the negotiation infeasible",
                suite=SUITE, lld="§5.2 CLOSED_INFEASIBLE", input={"scenario": "infeasible"},
                expected={"message_class": "infeasible_with_proposal", "feasibility": "none",
                          "accept_outcome": "closed_infeasible"})
    reply = negotiate(client, opening(), "infeasible")
    closed = negotiate(client, {"message_class": "accept", "accepted": reply["message_class"],
                                "negotiation_id": "neg-1", "round": 1}, "infeasible")
    case.check({"message_class": reply["message_class"], "feasibility": reply["feasibility"],
                "basis": reply["basis"], "accept_outcome": closed["outcome"]})


def test_n04_partially_feasible(client, case):
    case.define("MAE-N04", "Partially feasible: one saving period cannot save energy; proposal drops it",
                suite=SUITE, lld="§11.5 adjusted_saving_target", input={"scenario": "partially_feasible"},
                expected={"message_class": "infeasible_with_proposal", "feasibility": "partial",
                          "infeasible_periods": ["6-9"], "proposed_mode_6_9": "experience_first",
                          "counter_proposal": {"adjusted_saving_target": "no energy saving in hours 6-9"}})
    reply = negotiate(client, opening(), "partially_feasible")
    case.check({"message_class": reply["message_class"], "feasibility": reply["feasibility"],
                "infeasible_periods": [p["period"] for p in reply["periods"] if not p["feasible"]],
                "proposed_mode_6_9": reply["proposal"]["schedule"][1]["saving_mode"],
                "counter_proposal": reply["counter_proposal"]})


def test_n05_multi_round(client, case):
    case.define("MAE-N05", "Multi-round: infeasible in round 1 with relaxed floors, feasible when re-initiated",
                suite=SUITE, lld="§5.2 INFEASIBLE_PROPOSAL -> INITIATED",
                input={"scenario": "multi_round", "round_2": "re-initiated with MAE's proposal"},
                expected={"round_1": "infeasible_with_proposal", "proposed_mbps": [8.0, 8.0],
                          "round_2": "feasible_request_confirmation", "round_2_echo": 2})
    first = negotiate(client, opening(), "multi_round")
    proposal = first["proposal"]["schedule"]
    second = negotiate(client, opening(proposal, round_no=2), "multi_round")
    case.check({"round_1": first["message_class"],
                "proposed_mbps": [p["experience_target"]["mbps"] for p in proposal
                                  if p["experience_target"]["type"] == "rate_floor"],
                "round_2": second["message_class"], "round_2_echo": second["round"]})


def test_n06_multiple_solutions(client, case):
    case.define("MAE-N06", "Feasible with three solutions; accept names the chosen one", suite=SUITE,
                lld="§11.5 selected_solution", input={"scenario": "multiple_solutions", "accept": "SOL-2"},
                expected={"message_class": "feasible_request_confirmation",
                          "solutions": ["SOL-1", "SOL-2", "SOL-3"], "risks": ["low", "medium", "high"],
                          "accept_outcome": "agreed", "selected_solution": "SOL-2"})
    reply = negotiate(client, opening(), "multiple_solutions")
    closed = negotiate(client, {"message_class": "accept", "accepted": reply["message_class"],
                                "selected_solution": "SOL-2", "negotiation_id": "neg-1", "round": 1})
    case.check({"message_class": reply["message_class"], "solutions": [s["solution_id"] for s in reply["solutions"]],
                "risks": [s["experience_risk"] for s in reply["solutions"]], "accept_outcome": closed["outcome"],
                "selected_solution": closed.get("selected_solution")})


def test_n07_negotiation_error(client, case):
    case.define("MAE-N07", "MAE answers the assessment with an error", suite=SUITE, lld="§4 F6",
                input={"scenario": "negotiation_error"}, expected={"message_class": "error", "has_error": True})
    reply = negotiate(client, opening(), "negotiation_error")
    case.check({"message_class": reply["message_class"], "has_error": bool(reply.get("error")),
                "error": reply.get("error")})


def test_n08_slow_negotiation(client, case):
    case.define("MAE-N08", "Slow assessment: the verdict arrives after MOCK_MAE_SLOW_SECONDS", suite=SUITE,
                lld="§11.5 per-round timeout", input={"scenario": "slow_negotiation", "MOCK_MAE_SLOW_SECONDS": 0.3},
                expected={"message_class": "feasible_request_confirmation", "waited_at_least_slow_seconds": True})
    start = time.monotonic()
    reply = negotiate(client, opening(), "slow_negotiation")
    elapsed = round(time.monotonic() - start, 2)
    case.check({"message_class": reply["message_class"], "waited_at_least_slow_seconds": elapsed >= 0.3,
                "elapsed_seconds": elapsed})


@pytest.mark.parametrize(("case_id", "message_class"), [("MAE-N09", "reject"), ("MAE-N10", "abort")])
def test_n09_n10_reject_and_abort(client, case, case_id, message_class):
    case.define(case_id, f"Energy Agent sends {message_class}; negotiation closes aborted", suite=SUITE,
                lld="§5.2 ABORTED", input={"message_class": message_class},
                expected={"message_class": "negotiation_closed", "outcome": "aborted"})
    reply = negotiate(client, {"message_class": message_class, "negotiation_id": "neg-1", "round": 1})
    case.check({"message_class": reply["message_class"], "outcome": reply["outcome"]})


def test_n11_missing_region(client, case):
    case.define("MAE-N11", "Assessment without a region is infeasible with the reason", suite=SUITE, lld="§12",
                input={"under_evaluation_description": {}},
                expected={"message_class": "infeasible_with_proposal", "feasibility": "none",
                          "basis": "intent has no region (Task-T slot task_object)"})
    reply = negotiate(client, {"message_class": "initiate_feasibility_assessment",
                               "under_evaluation_description": {"schedule": uc1_data.intent_schedule()}})
    case.check({"message_class": reply["message_class"], "feasibility": reply["feasibility"],
                "basis": reply["basis"]})


def test_n12_unsupported_message_class(client, case):
    case.define("MAE-N12", "Unsupported message class gets an error", suite=SUITE, lld="§11.5",
                input={"message_class": "counter_offer"},
                expected={"message_class": "error", "error": "unsupported message_class 'counter_offer'"})
    reply = negotiate(client, {"message_class": "counter_offer"})
    case.check({"message_class": reply["message_class"], "error": reply.get("error")})


# Task-T -----------------------------------------------------------------------------------------

def test_t01_full_task(client, case):
    case.define("MAE-T01", "Create task streams seven artifacts with per-cell and KPI results", suite=SUITE,
                lld="§3, §11.7", input={"scenario": "auto", "slots": "UC1 Create for Accra Central"},
                expected={"state": "COMPLETED", "artifacts": FULL_STREAM, "achievement": "full",
                          "intent_achieved": True, "cells_selected": 18, "cells_failed": 0,
                          "coverage_cells_selected": 0, "saves_money": True, "saves_energy": True,
                          "kpi_periods": 5, "all_targets_met": True})
    result = run_task(client, slots())
    report = result["artifacts"][-1]
    cells = next(a for a in result["artifacts"] if a["type"] == "CellSelection")["cells"]
    case.check({"state": result["state"], "artifacts": result["types"], "achievement": report["achievement"],
                "intent_achieved": report["intent_achieved"], "cells_selected": report["cells"]["selected"],
                "cells_failed": report["cells"]["failed"],
                "coverage_cells_selected": sum(1 for c in cells if c["layer"] == "coverage"),
                "saves_money": report["predicted_saving"] > 0, "saves_energy": report["energy"]["predicted_saving"] > 0,
                "kpi_periods": len(report["experience_kpis"]),
                "all_targets_met": all(k["target_met"] for k in report["experience_kpis"]),
                "cost": f"{report['predicted_cost_before']:,.2f} -> {report['predicted_cost_after']:,.2f} GHS",
                "energy_saving_percent": report["energy"]["saving_percent"]})


def test_t02_cell_features_follow_saving_mode(client, case):
    case.define("MAE-T02", "Per-cell features follow each period's saving mode", suite=SUITE, lld="§11.7 CellSelection",
                input={"scenario": "auto"},
                expected={"periods_per_cell": [["23-5", "6-9", "16-17"]],
                          "features_23_5": ["carrier_shutdown", "channel_shutdown"],
                          "features_6_9": ["symbol_shutdown", "tx_power_reduction"], "every_cell_saves": True})
    cells = next(a for a in run_task(client, slots())["artifacts"] if a["type"] == "CellSelection")["cells"]
    periods = sorted({tuple(p["period"] for p in c["periods"]) for c in cells})
    by_period = {p["period"]: p["features"] for p in cells[0]["periods"]}
    case.check({"periods_per_cell": [list(p) for p in periods], "features_23_5": by_period["23-5"],
                "features_6_9": by_period["6-9"],
                "every_cell_saves": all(c["predicted_saving_kwh"] > 0 for c in cells)})


def test_t03_kpi_target_missed(client, case):
    schedule = uc1_data.intent_schedule()
    schedule[0]["experience_target"] = {"type": "rate_floor", "mbps": 40}
    case.define("MAE-T03", "A KPI target the plan cannot hold is reported as missed", suite=SUITE,
                lld="§11.8 final_report", input={"schedule": "hours 23-5 maximized saving with a 40 Mbps floor"},
                expected={"state": "COMPLETED", "target_met_23_5": False, "intent_achieved": False})
    result = run_task(client, slots(schedule=schedule))
    report = result["artifacts"][-1]
    kpi = report["experience_kpis"][0]
    case.check({"state": result["state"], "target_met_23_5": kpi["target_met"],
                "intent_achieved": report["intent_achieved"],
                "predicted_rate_mbps": kpi["predicted_avg_user_rate_mbps"]})


def test_t04_partial_execution(client, case):
    case.define("MAE-T04", "Some cells fail to activate: completed with partial achievement", suite=SUITE,
                lld="§11.7, §11.8", input={"scenario": "partial_execution"},
                expected={"state": "COMPLETED", "achievement": "partial", "intent_achieved": False,
                          "cells_failed": 4, "failed_cells_listed": 4})
    result = run_task(client, slots(), "partial_execution")
    report = result["artifacts"][-1]
    activated = next(a for a in result["artifacts"] if a["type"] == "EnergySavingActivated")
    case.check({"state": result["state"], "achievement": report["achievement"],
                "intent_achieved": report["intent_achieved"], "cells_failed": report["cells"]["failed"],
                "failed_cells_listed": len(activated["failed_cells"]), "status_text": result["text"]})


def test_t05_reject_task(client, case):
    case.define("MAE-T05", "Task rejected before any artifact", suite=SUITE, lld="§5.1 DISPATCHING -> FAILED",
                input={"scenario": "reject_task"}, expected={"state": "REJECTED", "artifacts": []})
    result = run_task(client, slots(), "reject_task")
    case.check({"state": result["state"], "artifacts": result["types"], "status_text": result["text"]})


def test_t06_semantic_rejected(client, case):
    case.define("MAE-T06", "Semantic validation rejects the task", suite=SUITE, lld="§4 F7",
                input={"scenario": "semantic_rejected"},
                expected={"state": "REJECTED", "artifacts": [], "code": "negotiation.semantic_rejected"})
    result = run_task(client, slots(), "semantic_rejected")
    case.check({"state": result["state"], "artifacts": result["types"], "code": result["text"].split(":")[0],
                "status_text": result["text"]})


def test_t07_exec_failure(client, case):
    case.define("MAE-T07", "Execution fails mid-task with an error artifact", suite=SUITE, lld="§4 F8",
                input={"scenario": "exec_failure"},
                expected={"state": "FAILED", "artifacts": ["TaskPlan", "BandPrediction", "TaskError"],
                          "error_code": "cluster_optimization_failed"})
    result = run_task(client, slots(), "exec_failure")
    case.check({"state": result["state"], "artifacts": result["types"],
                "error_code": result["artifacts"][-1]["code"], "status_text": result["text"]})


def test_t08_exec_timeout(client, case):
    case.define("MAE-T08", "Activation times out: error artifact then FAILED", suite=SUITE,
                lld="§5.1 EXECUTING -> FAILED (timeout)",
                input={"scenario": "exec_timeout", "MOCK_MAE_EXEC_TIMEOUT_SECONDS": 0.1},
                expected={"state": "FAILED", "artifacts": FULL_STREAM[:4] + ["TaskError"],
                          "error_code": "execution_timeout"})
    result = run_task(client, slots(), "exec_timeout")
    case.check({"state": result["state"], "artifacts": result["types"],
                "error_code": result["artifacts"][-1]["code"], "status_text": result["text"]})


def test_t09_delayed(client, case):
    case.define("MAE-T09", "Delayed response still completes", suite=SUITE, lld="§11.6 sandbox: delayed response",
                input={"scenario": "delayed", "MOCK_MAE_SLOW_STEP_SECONDS": 0.05},
                expected={"state": "COMPLETED", "artifacts": FULL_STREAM, "took_at_least_7_steps": True})
    start = time.monotonic()
    result = run_task(client, slots(), "delayed")
    elapsed = round(time.monotonic() - start, 2)
    case.check({"state": result["state"], "artifacts": result["types"],
                "took_at_least_7_steps": elapsed >= 7 * 0.05, "elapsed_seconds": elapsed})


def test_t10_missing_region(client, case):
    case.define("MAE-T10", "Task without task_object is rejected", suite=SUITE, lld="§12 slot mapping",
                input={"slots": {"operation_type": "Create"}}, expected={"state": "REJECTED", "artifacts": []})
    result = run_task(client, {"operation_type": "Create"})
    case.check({"state": result["state"], "artifacts": result["types"], "status_text": result["text"]})


def test_t11_wrong_template(client, case):
    case.define("MAE-T11", "Task on another template is rejected", suite=SUITE, lld="§13.4",
                input={"templateUri": "Task-T/other/v1"}, expected={"state": "REJECTED", "artifacts": []})
    result = run_task(client, slots(), template="Task-T/other/v1")
    case.check({"state": result["state"], "artifacts": result["types"], "status_text": result["text"]})


def test_t12_deterministic(client, case):
    case.define("MAE-T12", "Same intent gives the same report; another region gives another plan", suite=SUITE,
                lld="dev-environment: deterministic mock", input={"regions": [REGION, REGION, "Kumasi"]},
                expected={"same_region_identical": True, "other_region_differs": True})
    first, second, other = (run_task(client, slots(region))["artifacts"][-1] for region in (REGION, REGION, "Kumasi"))
    case.check({"same_region_identical": first == second,
                "other_region_differs": first["site_results"] != other["site_results"]})
