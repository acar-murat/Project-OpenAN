# Local Development Environment

Runs the parts of the energy-saving stack that exist today on one machine:
the upstream **Registry Center** and **Orchestration Center**, plus two mocks
that stand in for the external systems still blocked on open items:

| Service | Port | Source | Stands in for |
|---|---|---|---|
| Registry Center | 5000 | `upstream/registry-center` | — (real) |
| Orchestration Center | 5001 | `upstream/orchestration-center` | — (real) |
| Mock price API | 8090 | `mocks/price_api` | External price API (O-1) |
| Mock MAE | 8091 | `mocks/mae` | MAE (O-3, O-11, O-12) |
| Orchestration UI (optional) | 3003 | `upstream/orchestration-center/workflow-designer` | — (real) |

OSS and the Energy Agent are not built yet. Until they are,
`scripts/demo_uc1.py` plays the Energy Agent's part, so the whole UC1 flow can
be run and tested.

## Requirements

- Python 3.12+ (3.13 works).
- [`uv`](https://docs.astral.sh/uv/) is recommended (much faster installs); without it `pip` is used.
- Node.js 20+ only for the optional Orchestration UI.

## VS Code

1. Open the repository folder and install the recommended extensions (Python, Python Debugger, Ruff).
2. **Run and Debug → "OpenAN: all services" → Start.** The first run executes the
   `dev: setup` task, which creates `.dev/` (three virtualenvs and `dev.env`); later runs skip it.
   Each service gets its own terminal and debugger, so breakpoints work in upstream code too.
3. With the services running, start **"Demo: UC1 end to end"** (or **"Demo: UC1 infeasible"**).
4. Stop the compound to stop every service.

`OpenAN: mocks only` starts just the two mocks. **Terminal → Run Task…** has the
same operations as `dev.py` (`dev: up (background)`, `dev: status`, `dev: test`, `dev: ci`, …).
`Tests: mocks` runs the test suite under the debugger; the Testing panel also finds the tests.

## Command line

```sh
python scripts/dev.py setup     # once; idempotent
python scripts/dev.py up        # registry, orchestration, price-api, mae in the background
python scripts/dev.py demo      # UC1 end to end
python scripts/dev.py demo --scenario infeasible
python scripts/dev.py status
python scripts/dev.py logs mae
python scripts/dev.py down
python scripts/dev.py test      # ruff + pytest
python scripts/dev.py ci        # exactly what the CI dev-stack job runs
```

Use `python3` on Linux and macOS if `python` is not Python 3.
`python scripts/dev.py up registry orchestration price-api mae designer` also starts the UI.

## Configuration and credentials

`dev.py setup` writes `.dev/dev.env` (git-ignored). It is read by `dev.py`, the VS Code
launch configurations and the demo. Edit values there; `setup` keeps your edits.

- **Orchestration login:** user `admin`, password `ORCH_AUTH_PASSWORD` from `dev.env`. Setup
  generates a random password per machine and stores its hash in `ORCH_ACCESS_PASSWORD`; the
  Orchestration Center refuses to start without one (fail-closed startup).
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

## CI

`.github/workflows/ci.yml` runs on every pull request and push to `main`:

- **Lint and unit tests:** ruff and pytest for `mocks/` and `scripts/`.
- **Dev stack end to end:** `python scripts/dev.py ci`, which installs all three
  environments, starts the four services, runs the feasible and infeasible demos
  (requiring discovery through the Registry and visibility in the Orchestration
  Center), then stops everything. Service logs are uploaded if it fails.
