"""Run UC1 through the Orchestration Center, the way the Execution Center UI does.

Logs in, dispatches an intent to the mock Energy Agent (``GET /rest/v1/orchestrate/dispatch``)
and prints the streamed workflow events. The Orchestration Center picks the
"UC1 power-band energy saving" workflow (via the mock LLM) and the Energy Agent
runs it against the mock price API and mock MAE.

Exits non-zero unless the workflow completes, or with ``--scenario infeasible``
unless it stops at the feasibility step, so CI can use it as a smoke test.

    python scripts/demo_orchestration.py [--region "Accra Central"] [--scenario infeasible]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mocks.energy_agent.workflow import AGENT_NAME, WORKFLOW_NAME  # noqa: E402

ORCH_URL = os.environ.get("ORCH_CENTER_URL", "http://127.0.0.1:5001")


def describe(event: dict) -> str | None:
    kind, data = event.get("type"), event.get("data") or {}
    if kind == "start":
        return f"start ({data.get('phase')}): {data.get('workflow')}"
    if kind in ("step_start", "step_complete"):
        return f"{kind} {data.get('step')}"
    if kind == "agent_request":
        return f"-> {data.get('agent')}"
    if kind == "task_response":
        outputs = data.get("outputs") or []
        text = "\n".join(str(output) for output in outputs) or data.get("error", "")
        text = text.replace("\n", "\n      ")
        return f"<- {data.get('agent')} [{data.get('status')}] {data.get('step')}:\n      {text}"
    if kind in ("complete", "error", "cancelled"):
        return f"{kind}: {data.get('error', '')}".rstrip(": ")
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--region", default="Accra Central")
    parser.add_argument("--scenario", default=None, help="mock MAE scenario, e.g. infeasible")
    args = parser.parse_args()

    intent = f"Run power-band energy saving for {args.region}"
    if args.scenario:
        intent += f" scenario={args.scenario}"

    with httpx.Client(base_url=ORCH_URL, timeout=httpx.Timeout(30, read=180), trust_env=False) as http:
        login = http.post("/rest/v1/orchestrate/auth/login", json={
            "username": os.environ.get("ORCH_AUTH_USERNAME", "admin"),
            "password": os.environ.get("ORCH_AUTH_PASSWORD", ""),
        })
        login.raise_for_status()
        print(f"== Dispatching to {AGENT_NAME}: {intent!r}", flush=True)
        events = []
        params = {"intent": intent, "agent_name": AGENT_NAME, "lang": "en"}
        with http.stream("GET", "/rest/v1/orchestrate/dispatch", params=params) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line.startswith("data:"):
                    continue
                event = json.loads(line[5:])
                events.append(event)
                text = describe(event)
                if text:
                    print(f"   {text}", flush=True)

    kinds = [event.get("type") for event in events]
    workflows = {(event.get("data") or {}).get("workflow") for event in events if event.get("type") == "start"}
    if WORKFLOW_NAME not in workflows:
        print(f"\nResult: FAILED (the Orchestration Center did not pick '{WORKFLOW_NAME}')")
        return 1
    if args.scenario == "infeasible":
        failed = any("not feasible" in json.dumps(event) for event in events if event.get("type") == "task_response")
        print(f"\nResult: {'REJECTED as expected' if failed else 'UNEXPECTED'}")
        return 0 if failed and "complete" not in kinds else 1
    print(f"\nResult: {'COMPLETED' if 'complete' in kinds else 'FAILED'}")
    return 0 if "complete" in kinds and "error" not in kinds else 1


if __name__ == "__main__":
    sys.exit(main())
