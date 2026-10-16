# OSS and Energy Agent: What Has Been Built

What this repository delivers today for the two components LLD US202610010001
v10.4 assigns to us, **OSS** and the **Energy Agent**, how it works, and what is
still missing. The Orchestration Center and Registry Center are upstream code
that we run unchanged (LLD §0.0); MAE and the electricity price API are
external systems we stand in for with mocks.

For the endpoints and payloads, see the [API reference](api-reference.md). For
running the stack, see [Development environment](dev-environment.md).

> **Snapshot.** This describes `main` as of 2026-10-16 (after PR #4, LLD v10.4).
> Work in progress elsewhere will change some of it: richer mock behaviour and
> responses, security and audit, and LLM intent handling (including the
> workflow-selection step's sensitivity to the intent's wording). Sections that
> those changes touch are marked *(in flux)*.

---

## 1. Status at a glance

| Component | LLD sections | State on `main` | Where |
|---|---|---|---|
| **Energy Agent** | §11.4, §11.5, §11.11 | **Working mock.** Runs UC1 end to end as the Orchestration Center's host agent: tariff, policy guard, Negotiation-T with MAE, Task-T dispatch, intent report, hash-chained audit log | `mocks/energy_agent/` |
| **OSS** | §11.1, §11.2, §11.3, §11.8, §13.1 | **Not built.** Designed in the LLD and broken down in the backlog. The audit module it will use exists and is shared with the Energy Agent | `mocks/common/audit.py` |
| UC1 workflow (PSOP) | §11.6 | Done for the mock: four-step PSOP saved into the Orchestration Center on Energy Agent startup | `mocks/energy_agent/workflow.py` |
| Mock MAE | §11.7 | Done: Negotiation-T feasibility and Task-T `ran-energy-saving/v1`, six artifacts, four failure scenarios | `mocks/mae/` |
| Mock price API | §11.4 | Done: UC1 power-band tariff and UC2 time-of-use prices, error and slow modes | `mocks/price_api/` |
| Mock LLM | — | Done: answers the Orchestration Center's workflow-selection prompt | `mocks/llm/` |
| Dev stack, VS Code, CI | — | Done: `scripts/dev.py`, `.vscode/`, `.github/workflows/ci.yml` | |

Until OSS exists, the Orchestration Center's own web console (the
**Execution Center** page) and `scripts/demo_orchestration.py` take OSS's place as
the caller that submits an intent.

---

## 2. How the pieces fit today

```
  Browser (OpenAN console :3003)          scripts/demo_orchestration.py
        │  Execution Center: intent + host agent         │
        └──────────────────────┬─────────────────────────┘
                               │ GET /rest/v1/orchestrate/dispatch  (SSE)
                               ▼
                 ┌───────────────────────────┐   chat/completions   ┌──────────┐
                 │ Orchestration Center :5001│─────────────────────▶│ Mock LLM │
                 │ (upstream, unchanged)     │  pick the workflow   │  :8093   │
                 └─────────────┬─────────────┘                      └──────────┘
                               │ A2A-T (intent text) to the chosen host agent
                               ▼
                 ┌───────────────────────────┐
                 │ Mock Energy Agent :8092   │  upstream host_agent runtime
                 │ + EnergySavingControlPoint│  + our ControlPoint
                 └──┬──────────┬──────────┬──┘
   GET tariff       │          │          │ Task-T ran-energy-saving/v1
                    ▼          │          ▼ (sent by the workflow engine)
          ┌────────────────┐   │   ┌────────────────┐
          │ Mock price API │   └──▶│   Mock MAE     │  Negotiation-T feasibility
          │     :8090      │       │     :8091      │  (sent by our ControlPoint)
          └────────────────┘       └────────────────┘

   Mock MAE and Mock Energy Agent register their AgentCards in the
   Registry Center :5000 (upstream, unchanged); the Orchestration Center
   and the Energy Agent look agents up there.
```

`scripts/demo_uc1.py` runs the same UC1 steps without the Orchestration Center,
playing the Energy Agent's part directly against the mocks.

---

## 3. Energy Agent

### 3.1 Shape

The real Energy Agent is meant to be an A2A-T server built on `a2a-t-sdk` (LLD
§11.4). The mock takes a shortcut that lets the Orchestration Center's web UI
show every step: it runs the upstream **`host_agent` runtime** from
`upstream/orchestration-center` (imported, not modified) and supplies our
business logic as a workflow-engine **ControlPoint**.

| File | Responsibility |
|---|---|
| `mocks/energy_agent/__main__.py` | Starts the A2A server; on startup saves the UC1 workflow in the Orchestration Center, then registers the AgentCard in the Registry Center (in that order, so the workflow exists once the card is listed) |
| `mocks/energy_agent/server.py` | AgentCard ("Mock Energy Agent", organisation "OpenAN Mock"), host-agent executor wiring, workflow save with login and retry |
| `mocks/energy_agent/workflow.py` | The UC1 PSOP, and extraction of region and test scenario from the intent text |
| `mocks/energy_agent/control_point.py` | `EnergySavingControlPoint`: the step handlers, negotiation, Task-T content, report, audit calls |
| `mocks/energy_agent/policy.py` | `PolicyGuard`, the LLD §11.11 policy check |
| `mocks/common/uc1_messages.py` | Negotiation-T and Task-T bodies, shared with `scripts/demo_uc1.py` |
| `mocks/common/audit.py` | Hash-chained audit log and verifier |
| `mocks/common/registry.py` | Registry Center registration and card lookup |

It runs in the Orchestration Center's virtualenv with
`upstream/orchestration-center` on `PYTHONPATH`; `scripts/dev.py` sets both.

### 3.2 The UC1 workflow

The PSOP `psop_uc1_power_band_energy_saving` ("UC1 power-band energy saving")
has four steps. Three are `SelfLoop` steps the Energy Agent runs itself; one is
a normal agent task the workflow engine sends to MAE.

| # | Step | Runs in | ControlPoint hook | What it does |
|---|---|---|---|---|
| 1 | `power_band_tariff` | Energy Agent | `on_self_task` | `GET /v1/tariffs/power-band?region=…` on the price API; returns the band table as Markdown |
| 2 | `feasibility_negotiation` | Energy Agent | `on_self_task` | Policy guard, then one Negotiation-T feasibility exchange with MAE (see 3.4) |
| 3 | `ran_energy_saving` | Mock MAE | `on_task` | Builds the Task-T `ran-energy-saving/v1` message; the workflow engine sends it and collects the six artifacts |
| 4 | `intent_report` | Energy Agent | `on_self_task` | Reads MAE's artifacts from the upstream results and writes the intent report |

LLD §11.6 describes `PriceNode → NegotiationNode → gateway → DispatchNode →
MonitorNode`. The mock covers the same ground with a linear PSOP: a failed
feasibility step ends the workflow, which stands in for the gateway, and the
report step stands in for the Monitor node.

One ControlPoint instance serves one workflow execution, so it remembers the
region, scenario and tariff between steps. The execution id is used as the
`trace_id` in the audit log.

### 3.3 Reading the intent *(in flux)*

The intent arrives as free text. `workflow.region_of` takes the region from
`region: <name>` or from the capitalised words after "for" ("… for Accra
Central"), and falls back to `Accra Central`. `scenario=<name>` in the text is
passed to the mock MAE as `mockScenario`, to force an outcome.

This is regular-expression extraction, not the LLD's LLM classifier and slot
extraction, which belongs to OSS (§11.1). The schedule is not extracted at
all: every run uses the UC1 example schedule from the use-case deck
(`mocks/common/uc1_data.py`).

Before the Energy Agent sees the intent, the Orchestration Center asks a chat
model which workflow fits. The mock LLM answers by word overlap between the
intent and each workflow's name, description, intent and tags, so wording
matters: an intent that shares no meaningful word with the workflow is not
matched.

### 3.4 Feasibility negotiation (LLD §11.5)

1. The policy guard checks the region and schedule (3.6). A refusal ends the
   step with `energy_agent.policy_violation`; nothing is sent to MAE.
2. The MAE AgentCard is looked up in the Registry Center
   (`GET /rest/v1/registry-center/agent-cards/OpenAN Mock/Mock MAE`), falling
   back to MAE's `/.well-known/agent-card.json`. Its digest is kept for the
   audit log.
3. **Round 1, propose:** `initiate_feasibility_assessment` with the region, the
   schedule and the tariff (template `Negotiation-T/feasibility-negotiation/propose`).
4. **Close:** whatever MAE answers, the Energy Agent accepts the verdict with
   `accept` (template `…/accept-reject`): feasible closes `agreed`, infeasible
   closes `closed_infeasible`. Any other reply is answered with `abort`
   (`Negotiation-T/common/abort`).
5. Outcome of the step:

| MAE said | Step result | Error code |
|---|---|---|
| `feasible_request_confirmation`, closed `agreed` | Succeeded | — |
| `infeasible_with_proposal` | Failed, message carries MAE's reasons and the counter-proposal | `energy_agent.infeasible` |
| anything else | Failed | `energy_agent.negotiation_aborted` |

The agent never relaxes the target and re-proposes on the user's behalf
(decision D-1, default off). The counter-proposal goes back to the caller.

Not implemented yet from §11.5: messages are built as JSON rather than from
the SDK's Negotiation-T templates; there is no round limit or per-round
timeout (`ENERGY_AGENT_NEGOTIATION_MAX_ROUNDS`, `…_ROUND_TIMEOUT_MS`) because
only one round is ever sent; and `ENERGY_AGENT_ALLOW_TARGET_RELAXATION` does
not exist.

### 3.5 Task-T dispatch and the report

`on_task` returns a message with text `Power-band energy saving for <region>`,
the Task-T extension, `templateUri = Task-T/network-layer/ran-energy-saving/v1`
and these slots:

| Slot | Content |
|---|---|
| `task_object` | region |
| `operation_type` | `Create` |
| `task_description` | `Power-band energy saving for <region>` |
| `task_target.schedule` | the UC1 schedule |
| `task_context.power_band_tariff` | currency, billing period and bands from the price API |

Putting the schedule in `task_target` and the tariff in `task_context` is
provisional, pending open item O-28.

The report step collects every artifact whose Task-T metadata carries a JSON
body and builds a Markdown table from `IntentReport` (predicted monthly cost
before and after, saving, intent achieved, sites changing band), plus the
`SiteClassification` counts and the `EnergySavingActivated` sites. Without an
`IntentReport` it fails with `energy_agent.no_report`.

### 3.6 Security and audit (LLD §11.11) *(in flux)*

| LLD control | Done | Notes |
|---|---|---|
| Policy guard before `agreed` | **Yes** (mock) | Region allowlist, minimum experience floor, maximum saving target, from `ENERGY_AGENT_POLICY_*`. Empty means no limit. Time windows are not done |
| No silent relaxation | **Yes** | D-1 default |
| Local audit log | **Yes** (mock) | One record per policy decision and per negotiation round, hash-chained, at `ENERGY_AGENT_AUDIT_LOG_PATH` |
| Secrets kept out of logs and audit | **Partly** | Audit payloads are redacted by key name (`api_key`, `token`, `secret`, `password`, `authorization`, `credential`, `cookie`) before hashing |
| Caller authentication | No | Blocked on O-25; records name the caller `unverified (O-25)` |
| Outbound trust to MAE | No | Plain HTTP in the dev stack; mutual authentication is O-7 |
| Tracing (OpenTelemetry) | No | The mock does not use `a2a-t-sdk`, so it does not inherit its tracing |

Policy rules in detail:

- **Region allowlist:** case-insensitive match against
  `ENERGY_AGENT_POLICY_REGION_ALLOWLIST` (comma-separated).
- **Experience floor:** every schedule period must ask for at least
  `ENERGY_AGENT_POLICY_MIN_EXPERIENCE_FLOOR` Mbps. `no_degradation` always
  passes; `none` counts as 0 Mbps. Note that the UC1 schedule's overnight period
  is `none`, so any floor above 0 refuses the UC1 example.
- **Saving target:** a numeric `saving_target` above
  `ENERGY_AGENT_POLICY_MAX_SAVING_TARGET` is refused. UC1 intents carry saving
  modes rather than a number, so this rule only applies when a number is given.

Audit records follow the LLD §11.3 schema (`audit_id`, `ts`, `event`,
`intent_id`, `trace_id`, `actor`, `resource`, `outcome`, `reason`, `detail`,
`detail_digest`, `prev_hash`, `hash`). Negotiation records also carry the
negotiation id, round, templates and message classes sent and received,
outcome, and digests of the price table, any counter-proposal and the MAE
AgentCard. `python -m mocks.common.audit <path>` verifies the chain and
reports edited, removed or reordered lines; CI runs it after the demos.

### 3.7 Registration

Both mock agents register with `POST /rest/v1/registry-center/agent-cards`,
retrying for up to 60 seconds and treating `409` as already registered. An
optional `REGISTRY_ACCESS_TOKEN` is sent as a bearer token. Heartbeats, the
registry `layer` (O-13) and the approval flow are not implemented; the dev
Registry runs in its local HTTP demo profile, where none of them is required.

### 3.8 Configuration

| Variable | Default | Purpose |
|---|---|---|
| `MOCK_ENERGY_AGENT_HOST` / `_PORT` | `127.0.0.1` / `8092` | Bind address |
| `MOCK_ENERGY_AGENT_PUBLIC_URL` | `http://<host>:<port>` | URL in the AgentCard |
| `MOCK_ENERGY_AGENT_REGISTER_TIMEOUT_SECONDS` | `60` | Retry window for workflow save and registration |
| `ORCH_CENTER_URL` | `http://127.0.0.1:5001` | Where the workflow is saved and loaded |
| `ORCH_AUTH_USERNAME` / `ORCH_AUTH_PASSWORD` | `admin` / — | Login used to save the workflow |
| `REGISTRY_CENTER_URL` | `http://127.0.0.1:5000` | Registration and MAE lookup |
| `REGISTRY_ACCESS_TOKEN` | — | Optional bearer token for registration |
| `ENERGY_AGENT_PRICE_API_BASE_URL` | `http://127.0.0.1:8090` | Price API |
| `ENERGY_AGENT_PRICE_API_KEY` | — | Sent as `X-API-Key` when set |
| `MOCK_MAE_URL` | `http://127.0.0.1:8091` | MAE fallback when the registry has no card |
| `ENERGY_AGENT_POLICY_REGION_ALLOWLIST` | — | Policy guard |
| `ENERGY_AGENT_POLICY_MIN_EXPERIENCE_FLOOR` | — | Policy guard (Mbps) |
| `ENERGY_AGENT_POLICY_MAX_SAVING_TARGET` | — | Policy guard |
| `ENERGY_AGENT_AUDIT_LOG_PATH` | — (`dev.py` sets `.dev/logs/energy-agent-audit.jsonl`) | Audit log; no log when unset |

### 3.9 Gaps against the LLD

| LLD asks for | Mock today | Tracked as |
|---|---|---|
| A2A-T server on `a2a-t-sdk`, with OpenTelemetry | Upstream `host_agent` runtime, no tracing | EA-1 |
| Skill `electricity_price_lookup` returning a time-of-use `price_table` | Power-band tariff for UC1; the time-of-use shape exists only in the price API mock | EA-4, EA-10 |
| `PriceAPIUnavailableError` → `price_api_unavailable` | An HTTP error fails the step as `energy_agent.power-band-tariff` | EA-4 |
| `saving_target` and `experience_target` fields | A per-period schedule (UC1 deck); see requirements R-INT-10 | OSS-14, EA-11 |
| Messages from the SDK's Negotiation-T templates, round limit and timeout | Hand-built JSON, single round | EA-5 |
| Caller authentication, mutual authentication to MAE | None | EA-14 (O-25), O-7 |
| Heartbeat, `layer`, approval | Registration only | EA-3 (O-13, O-22) |
| Real MAE artifacts | This repo's proposed schema (`schema_version: mock-1`) | ORC-8 (O-11) |

---

## 4. OSS

OSS is the front door of the LLD design: it authenticates the user, classifies
and completes the intent, checks permissions and region scope, writes the
audit trail, submits to the Orchestration Center with a service credential,
holds the SSE stream, and answers status queries (LLD §11.1–§11.3, §11.8).

**None of the OSS service exists on `main` yet.** What does exist:

| Piece | State |
|---|---|
| Design | LLD v10.4 §11.1–§11.3, §11.8, §12, §13.1–§13.2, §14, §15; requirements in [requirements.md](requirements.md) |
| Work breakdown | Backlog items OSS-1 … OSS-20, all ready to start except OSS-12 (O-23), OSS-13 (O-8) and OSS-15 (O-2); see [development-backlog.md](development-backlog.md) §3 |
| Audit module | `mocks/common/audit.py` implements the §11.3 record schema, hash chain, redaction and verifier. OSS-4 starts from it and moves the store to a database with an insert-only role |
| Reference data | `mocks/common/uc1_data.py` holds the UC1 schedule, which is the test fixture OSS-14 asks for |
| Stand-in caller | The Orchestration Center's Execution Center page and `scripts/demo_orchestration.py` submit intents in OSS's place, with the admin login instead of a service credential |
| Planned API | Documented in the [API reference](api-reference.md#7-oss-planned) from LLD §11.1, §11.8 and §13.1, marked as not implemented |

Points the OSS work will need to handle, learned from building the mocks and
reading the upstream code (details in [requirements.md](requirements.md)):

- The Orchestration Center sees one machine identity; all per-user checks are
  OSS's job, and the Orchestration Center must be reachable only from OSS.
- The execution record exists only after the SSE stream ends and its id is not
  in the stream, so OSS must hold the stream open and resolve the id afterwards
  (O-23, feature request UP-1).
- A dropped stream makes the Orchestration Center record the run as `STOPPED`;
  OSS must audit `workflow_stream_lost`.
- The Orchestration Center sends `complete`, `error` or `cancelled` as terminal
  events and no `close` event.
- The workflow-selection step uses a chat model, so the wording of the intent
  OSS forwards affects which workflow runs. OSS forwards only validated
  structured fields, never `raw_text`.

---

## 5. Tests and CI

| Test file | Covers |
|---|---|
| `test_energy_workflow.py` | PSOP shape; the MAE step targets the mock MAE skill; region and scenario extraction from intent text; the PSOP passes the workflow engine's validator |
| `test_energy_control_point.py` | ControlPoint against stubbed price API and MAE: feasible is agreed and audited, infeasible closes `closed_infeasible`, a policy violation never reaches MAE |
| `test_policy.py` | Each policy rule refuses; empty configuration allows |
| `test_audit.py` | Record schema and chain; a reopened log continues the chain; edits and gaps are detected; secrets are redacted before hashing |
| `test_mae_server.py` | Mock MAE over its real HTTP routes: AgentCard, negotiation verdicts, accept / reject / abort, Task-T stream, scenarios, wrong template |
| `test_planning.py` | Intent parsing, feasibility, deterministic planning, migration, artifacts |
| `test_price_api.py` | Tariff and time-of-use responses, API key, error mode and header override, unknown mode, unknown and missing region |
| `test_llm.py` | Workflow selection by word overlap; non-selection prompts |

The workflow-engine tests (`test_energy_control_point.py` and the validator
check) need the Orchestration Center's packages, so the plain mocks environment
skips them and `scripts/dev.py test` runs them in the Orchestration Center's
virtualenv. CI (`.github/workflows/ci.yml`) runs ruff and pytest, then
`scripts/dev.py ci`, which includes `dev.py test`;
it starts the six services, runs the feasible and infeasible UC1 demos
directly and through the Orchestration Center, and verifies the Energy Agent's
audit chain.

---

## 6. Open items that block the real components

| Item | Blocks |
|---|---|
| O-1 price API provider | Real price adapter (EA-8) |
| O-3, O-7 MAE identity and trust model | Pointing the Energy Agent at the real MAE (EA-9) |
| O-11 MAE artifact schema | Real artifact parsing and report (ORC-8, FE-5, FE-7) |
| O-12 Authorization-T before dispatch | ORC-9 |
| O-25 Energy Agent caller authentication | EA-14 |
| O-27 tariff semantics, O-28 schedule and tariff in Task-T | Final intent and Task-T mapping (EA-11) |

The full register is in LLD §18 and [requirements.md](requirements.md).
