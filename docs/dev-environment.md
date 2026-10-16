# Local Development Environment

Runs the parts of the energy-saving stack that exist today on one machine:
the upstream **Registry Center** and **Orchestration Center** with their web UIs,
plus mocks that stand in for the systems that are external or not built yet:

| Service | Port | Source | Stands in for |
|---|---|---|---|
| Registry Center | 5000 | `upstream/registry-center` | — (real) |
| Orchestration Center | 5001 | `upstream/orchestration-center` | — (real) |
| Mock price API | 8090 | `mocks/price_api` | External price API (O-1) |
| Mock MAE | 8091 | `mocks/mae` | MAE (O-3, O-11, O-12) |
| Mock Energy Agent | 8092 | `mocks/energy_agent` | Energy Agent (LLD v10.4 §11.4, §11.5, §11.11), as the Orchestration Center's host agent |
| Mock LLM | 8093 | `mocks/llm` | The chat model the Orchestration Center uses to pick a workflow |
| OpenAN console (UI) | 3003 | `upstream/orchestration-center/workflow-designer` | — (real) |
| Registry Center UI | 3004 | `upstream/registry-center/registry-center-web` | — (real) |

OSS is not built yet. The UC1 flow runs two ways: `scripts/demo_uc1.py` plays the
Energy Agent's part directly against the mocks, and the mock Energy Agent runs the
same steps as an Orchestration Center workflow, so they show up in the web UI.

## Requirements

- Python 3.12+ (3.13 works).
- [`uv`](https://docs.astral.sh/uv/) is recommended (much faster installs); without it `pip` is used.
- Node.js 20+ only for the web UIs.

## VS Code

1. Open the repository folder and install the recommended extensions (Python, Python Debugger, Ruff).
2. **Run and Debug → "OpenAN: all services + UIs" → Start.** The first run executes the
   `dev: setup + UIs` task, which creates `.dev/` (three virtualenvs, `dev.env`, `models.yaml`) and
   runs `npm install` for both UIs; later runs skip what is already there.
   Each service gets its own terminal and debugger, so breakpoints work in upstream code too.
3. Open <http://127.0.0.1:3003> and follow [Watching UC1 in the web UI](#watching-uc1-in-the-web-ui),
   or start **"Demo: UC1 via Orchestration Center"** / **"Demo: UC1 end to end"**.
4. Stop the compound to stop every service.

Other compounds: `OpenAN: all services` (no UIs), `OpenAN: UIs only` (when the services already
run, e.g. from `dev.py up`) and `OpenAN: mocks only`. **Terminal → Run Task…** has the same
operations as `dev.py` (`dev: up + UIs (background)`, `dev: ui setup`, `dev: status`, `dev: test`,
`dev: ci`, …). `Tests: mocks` runs the test suite under the debugger; the Testing panel also finds the tests.

## Watching UC1 in the web UI

1. Open the **OpenAN console** at <http://127.0.0.1:3003> and log in as `admin` with
   `ORCH_AUTH_PASSWORD` from `.dev/dev.env`. The **Registry Center** tab lists Mock MAE and
   Mock Energy Agent; **Orchestration Center → Manage Workflows** lists the "UC1 power-band energy saving" workflow.
2. Go to **Execution Center**, type `Run power-band energy saving for Accra Central`, pick
   **Mock Energy Agent** under *Select Host Agent* and press **Dispatch**.
3. The graph lights up step by step. The *Interaction* panel lists each step: open a step, then
   *Self-Loop (Local Processing)*, to read the tariff, the negotiation outcome and the intent report
   (predicted monthly cost before and after, saving, sites changing band). The `ran_energy_saving`
   step shows the Task-T request to Mock MAE and its response.
4. Add `scenario=infeasible` to the intent to see MAE turn it down at the feasibility step.

The standalone **Registry Center UI** at <http://127.0.0.1:3004> shows the AgentCards and their heartbeats.

How it works: the Orchestration Center asks the mock LLM to pick a workflow for the intent
(it always needs a model for this step), then dispatches the intent with that workflow to the
host agent you picked. The mock Energy Agent runs the upstream `host_agent` runtime with an
energy-saving ControlPoint (`mocks/energy_agent/control_point.py`): it fetches the tariff,
negotiates feasibility with MAE (Negotiation-T), lets the workflow engine send the Task-T task to
MAE, and writes the report from MAE's artifacts. It saves the workflow in the Orchestration Center
when it starts, so a fresh `upstream/orchestration-center/data/` gets it back. Two upstream UI
gaps remain: the *Execution Summary* panel is a placeholder, and a response with several Task-T
artifacts shows only the first one's JSON (the report step covers all six).

## Command line

```sh
python scripts/dev.py setup     # once; idempotent (setup --ui also installs the UIs' npm packages)
python scripts/dev.py up        # registry, llm, orchestration, price-api, mae, energy-agent in the background
python scripts/dev.py up --ui   # the same plus the OpenAN console (3003) and Registry UI (3004)
python scripts/dev.py demo      # UC1 end to end, straight against the mocks
python scripts/dev.py demo --scenario infeasible
python scripts/dev.py demo-orch # UC1 through the Orchestration Center and mock Energy Agent
python scripts/dev.py demo-orch --scenario infeasible
python scripts/dev.py status
python scripts/dev.py logs energy-agent
python scripts/dev.py down
python scripts/dev.py test      # ruff + pytest
python scripts/dev.py ci        # exactly what the CI dev-stack job runs
```

Use `python3` on Linux and macOS if `python` is not Python 3. Services can also be named one by
one, e.g. `python scripts/dev.py up designer` starts just the OpenAN console.

### npm packages for the UIs

Both UIs' `package-lock.json` files resolve packages from `registry.npmmirror.com`, which is
blocked on many networks. `dev.py ui-setup` (run by `up` and `setup --ui` when `node_modules` is
missing) installs with `--replace-registry-host=registry.npmmirror.com`, so npm fetches the same
versions from `OPENAN_NPM_REGISTRY` (default `https://registry.npmjs.org/`) without editing the
lockfiles. Set `OPENAN_NPM_REGISTRY=https://registry.npmmirror.com/` to keep using the mirror, and
use `dev.py ui-setup --force` to reinstall. By hand:

```sh
cd upstream/orchestration-center/workflow-designer
npm install --force --registry=https://registry.npmjs.org/ --replace-registry-host=registry.npmmirror.com
```

## Configuration and credentials

`dev.py setup` writes `.dev/dev.env` (git-ignored). It is read by `dev.py`, the VS Code
launch configurations and the demo. Edit values there; `setup` keeps your edits.

- **Orchestration login:** user `admin`, password `ORCH_AUTH_PASSWORD` from `dev.env`. Setup
  generates a random password per machine and stores its hash in `ORCH_ACCESS_PASSWORD`; the
  Orchestration Center refuses to start without one (fail-closed startup). The mock Energy Agent
  uses the same login to save its workflow.
- **Model:** `dev.py setup` writes `.dev/models.yaml`, pointing the Orchestration Center (only)
  at the mock LLM through `LLM_CONFIG_FILE`. Replace it with a real model to use the AI features
  (generating workflows from an intent or a solution package); the mock only selects workflows.
- **Registry Center** runs in its documented local HTTP demo profile: no TLS, card signing or
  owner isolation. It binds to 127.0.0.1 only; never expose it.
- Registry and Orchestration keep their runtime data under their own `upstream/*/data/`
  directories (ignored by git). Delete `upstream/registry-center/data/` to start with an empty registry.

## The mocks

### Mock price API

| Endpoint | Returns |
|---|---|
| `GET /v1/tariffs/power-band?region=…` | UC1 power-band tariff (5 bands, GHS, monthly) |
| `GET /v1/prices/time-of-use?region=…&date=…` | UC2 time-of-use `price_table` (LLD shape) |
| `GET /health` | liveness |

| Setting | Effect |
|---|---|
| `MOCK_PRICE_API_KEY` | When set, `X-API-Key` must match |
| `MOCK_PRICE_MODE` | `normal`, `error` (503) or `slow` (`MOCK_PRICE_SLOW_SECONDS`, default 10) |
| `X-Mock-Mode` header | Overrides the mode for one request |
| region `unknown` | 404 |

OpenAPI docs: <http://127.0.0.1:8090/docs>.

### Mock MAE

An A2A HTTP+JSON server built on `a2a-sdk`, using the same A2A-T extension URIs
and metadata layout as the SDK's `ran-energy-saving` sample. It registers its
AgentCard ("Mock MAE", organisation "OpenAN Mock") in the Registry Center, so the
Orchestration Center discovers it like a real agent.

- **Negotiation-T** (`metadata[…/Negotiation-T/v1]`, JSON): `initiate_feasibility_assessment`
  returns `feasible_request_confirmation`, or `infeasible_with_proposal` with a counter-proposal
  when a period asks for a guaranteed rate above `MOCK_MAE_MAX_RATE_FLOOR_MBPS` (default 20).
  `accept`, `reject` and `abort` close the negotiation.
- **Task-T** `ran-energy-saving/v1` (`metadata[…/Task-T/v1]`, JSON slots `task_object`,
  `task_target.schedule`, `task_context.power_band_tariff`): streams SUBMITTED, a WORKING update
  per step, six artifacts, then COMPLETED.

The artifacts follow UC1 (deck slide 2) and are this repo's **proposed MAE artifact schema**
for open item O-11; see `mocks/mae/planning.py`:

| Artifact | Content |
|---|---|
| `TaskPlan` | operation type, planning month, site count, steps |
| `BandPrediction` | per site: predicted kW, band, charge |
| `SiteClassification` | per site: downgrade / upgrade / grade_stable, plus counts |
| `TrafficMigrationPlan` | load moved out of / into sites and how (power, tilt, handover), active periods |
| `EnergySavingActivated` | activated sites and the periods saving applies in (not "experience first") |
| `IntentReport` | predicted monthly cost before / after, saving, sites changing band, schedule |

| Setting | Effect |
|---|---|
| `MOCK_MAE_SCENARIO` | `auto` (default), `feasible`, `infeasible`, `reject_task`, `exec_failure` |
| `metadata["mockScenario"]` | Overrides the scenario for one message |
| `MOCK_MAE_STEP_DELAY_SECONDS` | Pause between task steps (default 0.5) |
| `REGISTRY_CENTER_URL` | Registry to register with (retries for `MOCK_MAE_REGISTER_TIMEOUT_SECONDS`, default 60) |

The mock does not run the A2A-T SDK's LLM-based prompt validation, so it needs no
LLM key and is deterministic: the same region always gives the same plan.

### Mock Energy Agent

The Orchestration Center's host agent for UC1 (see [Watching UC1 in the web UI](#watching-uc1-in-the-web-ui)).
It runs in the Orchestration Center's virtualenv with `upstream/orchestration-center` on
`PYTHONPATH`, registers its AgentCard ("Mock Energy Agent", organisation "OpenAN Mock") and, on
startup, saves the workflow from `mocks/energy_agent/workflow.py`:

| Step | Runs in | Does |
|---|---|---|
| `power_band_tariff` | Energy Agent (self-loop) | `GET /v1/tariffs/power-band` on the mock price API |
| `feasibility_negotiation` | Energy Agent (self-loop) | Policy guard, then a Negotiation-T round with MAE; accepts MAE's verdict and fails the workflow with the counter-proposal if infeasible (`closed_infeasible`), or with `policy_violation` without contacting MAE |
| `ran_energy_saving` | Mock MAE | Task-T `ran-energy-saving/v1`, sent by the workflow engine; six artifacts |
| `intent_report` | Energy Agent (self-loop) | Markdown report built from MAE's artifacts |

The region comes from the intent ("... for Kumasi", default Accra Central); `scenario=<name>` in
the intent is passed to the mock MAE as `mockScenario`.

Security and audit (LLD v10.4 §11.11):

| Variable | Meaning |
|---|---|
| `ENERGY_AGENT_POLICY_REGION_ALLOWLIST` | Comma-separated regions the agent may act on (empty: any) |
| `ENERGY_AGENT_POLICY_MIN_EXPERIENCE_FLOOR` | Lowest rate floor in Mbps a schedule period may ask for; `none` counts as 0 (empty: no floor) |
| `ENERGY_AGENT_POLICY_MAX_SAVING_TARGET` | Highest numeric saving target (empty: no limit) |
| `ENERGY_AGENT_AUDIT_LOG_PATH` | Hash-chained JSON-lines audit log; `dev.py` sets `.dev/logs/energy-agent-audit.jsonl` |

Check the audit chain with `python -m mocks.common.audit .dev/logs/energy-agent-audit.jsonl`.
Caller authentication is not implemented yet (O-25), so records name the caller as unverified.

### Mock LLM

An OpenAI-compatible `POST /v1/chat/completions`. For the Orchestration Center's
workflow-selection prompt it returns the workflows whose name, description, intent or tags share
the most words with the intent; any other prompt gets a fixed "configure a real model" reply.

## CI

`.github/workflows/ci.yml` runs on every pull request and push to `main`:

- **Lint and unit tests:** ruff and pytest for `mocks/` and `scripts/`.
- **Dev stack end to end:** `python scripts/dev.py ci`, which installs all three
  environments, starts the six services, runs the feasible and infeasible demos
  (requiring discovery through the Registry and visibility in the Orchestration
  Center), runs both again through the Orchestration Center and mock Energy Agent
  (`demo-orch`, the path the Execution Center uses), verifies the Energy Agent's
  audit chain, then stops everything.
  Service logs are uploaded if it fails. The web UIs are not started in CI.
