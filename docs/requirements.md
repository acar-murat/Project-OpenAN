# OpenAN Energy-Saving Function — Requirements

**Sources:** the original use-case deck ([use-cases.md](use-cases.md),
[`source/Open_AN_UC.pptx`](source/Open_AN_UC.pptx)) and LLD US202610010001
v10.2 (2026-10-12), derived from the *OpenAN Energy-Saving Function Software
Design Specification v1.0.0*. Where the two differ, the requirement says so.
**Baseline:** the upstream repositories under `upstream/` (see the root README).

Each requirement has an ID (`R-<area>-<n>`), traces to a function point (FP)
and an LLD section, and carries a status:

- ✅ **Ready**: can be implemented now.
- 🟡 **P1**: can be built, but an open item must close before GA.
- 🔴 **P0**: blocked; the open item must close before implementation.

Open items (O-n) are listed in §8. Development tasks that implement these
requirements are in [development-backlog.md](development-backlog.md).

---

## 1. Scope

**In scope:** use case UC1, electricity price collaboration for energy saving
(MTN power-band energy saving). A user states an energy-saving intent in natural language; OSS
validates it and hands it to the Orchestration Center; an Energy Agent fetches
electricity prices and negotiates feasibility with MAE; MAE executes the
energy-saving task on the RAN; the user sees progress and a final report.

**Out of scope:** UC2 (lithium battery charge/discharge planning on
time-of-use prices); MAE internals (AGLink,
WattSpirit, GreenPulse); role-based orchestration and layer-order enforcement,
which the platform does not provide.

### Components

| Component | Source | Status |
|---|---|---|
| Front-end | New | To build |
| OSS (Business, Security, Audit, SSE consumer) | New | To build |
| Energy Agent | New, on `a2a-t-sdk-python` | To build |
| Registry Center | `upstream/registry-center` | Deploy and configure |
| Orchestration Center | `upstream/orchestration-center` | Deploy, add workflow and nodes |
| Workflow-engine SDK | `upstream/workflow-engine-sdk-python` | Use |
| MAE | External (Huawei iMaster MAE) | Integrate |
| Electricity price API | External | Integrate |

---

## 2. Functional requirements

### FP-001 Intent reception, recognition and validation (High) — LLD §7.1, §11.1

| ID | Requirement | Status |
|---|---|---|
| R-INT-1 | OSS exposes `POST /api/v1/energy-saving/intents` accepting `raw_text` and optional `region`, `saving_target`, `experience_target`, `session_id`. | ✅ |
| R-INT-2 | OSS checks permission `energy_saving:submit` **before** any LLM call and returns `403` on failure. | ✅ |
| R-INT-3 | OSS writes audit event `intent_received` once the permission check passes. | ✅ |
| R-INT-4 | OSS classifies the text with the configured LLM, producing `{is_energy_saving_intent, confidence}`. | 🟡 O-2 |
| R-INT-5 | A non-energy-saving intent returns `200 {"handled": false}` and starts no workflow. | ✅ |
| R-INT-6 | OSS validates the required field `region` (→ Task-T `task_object`) and derives `operation_type` (`Create` / `Modify`) and `task_description`. | ✅ |
| R-INT-7 | Missing required parameters return status `awaiting_supplement` with the list of missing fields. | ✅ |
| R-INT-8 | `POST /api/v1/energy-saving/intents/{id}/supplement` merges new fields into the pending intent by `session_id` and writes audit event `parameter_supplement`. | ✅ |
| R-INT-10 | The intent carries a **time-period schedule**: a list of `{start_hour, end_hour, saving_mode, experience_target}` entries (UC1 input 1). Periods may wrap midnight (e.g. 23–5). | ✅ (deck D-2) |
| R-INT-11 | `saving_mode` is one of `maximized_energy_saving`, `proactive_energy_saving`, `experience_first`; `experience_target` is one of `none`, `rate_floor` (with a value in Mbps, e.g. 10), `no_degradation`. | ✅ (deck D-3) |
| R-INT-12 | Validation rejects schedules whose periods overlap or leave hours uncovered; together they must cover 0–23 exactly once. | ✅ |
| R-INT-13 | The intent carries the planning month the optimization applies to. | 🟡 O-23 |
| R-INT-9 | Each intent gets a `trace_id`, which is passed to the Orchestration Center and written into every audit event. | ✅ |

### FP-002 Energy-saving intent negotiation (Medium) — LLD §7.5, §6.2

| ID | Requirement | Status |
|---|---|---|
| R-NEG-1 | The Energy Agent opens a Negotiation-T `feasibility-negotiation/propose` with `category=goal_achievement`, `message_class=initiate_feasibility_assessment` and `under_evaluation_description` {region, saving_target, experience_target, electricity_price_table}. | 🔴 O-3 |
| R-NEG-2 | The Energy Agent handles both MAE replies: *feasible-request-confirmation* (→ `accept-reject` Accept → `AGREED`) and *infeasible-with-proposal* (→ `CLOSED_INFEASIBLE`, counter-proposal returned to the user). | 🔴 O-3 |
| R-NEG-3 | Negotiation is bounded by `ENERGY_AGENT_NEGOTIATION_MAX_ROUNDS` (default 3) and a per-round timeout; on exhaustion the agent sends `common/abort`. | ✅ |
| R-NEG-4 | The agent is stateless per message; round state lives in the negotiation context. | ✅ |
| R-NEG-5 | The agent never relaxes user targets on its own unless `ENERGY_AGENT_ALLOW_TARGET_RELAXATION=true` (default `false`). | 🟡 O-14 |
| R-NEG-6 | Every round is recorded as a `NegotiationRound` (LLD §11). | ✅ |

### FP-003 External electricity price acquisition (High) — LLD §7.4

| ID | Requirement | Status |
|---|---|---|
| R-PRC-1 | The Energy Agent exposes skill `electricity_price_lookup` (input: `region`, optional `date_range`; output: `price_table[]` of `{start_time, end_time, relative_price}`). | ✅ (shape) |
| R-PRC-2 | Price retrieval goes through an adapter interface, with a stub implementation for development and tests. | ✅ |
| R-PRC-3 | The production adapter calls the external price API with configured URL, key and timeout (`ENERGY_AGENT_PRICE_API_TIMEOUT_MS`, default 5000). | 🔴 O-1 |
| R-PRC-5 | The price model supports a **power-band tariff**: a list of `{band_no, min_kw, max_kw, charge, currency, billing_period}` (UC1 input 2; e.g. band 1 = 0.00–0.99 kW → 8,247.66 GHS). The LLD's time-of-use `price_table` stays as a second price type, used by UC2. | 🔴 O-1, O-21 (deck D-1) |
| R-PRC-6 | Electricity prices and the intent schedule are combined into one A2A-T intent ("integration of electricity price synergy and energy-saving intentions"); the two tables keep their own periods and are not forced to align. | ✅ (deck D-1) |
| R-PRC-4 | A price API failure ends the workflow `FAILED` with reason `price_api_unavailable`. | ✅ |

### FP-004 External LLM adaptation (High) — LLD §7.1, §14

| ID | Requirement | Status |
|---|---|---|
| R-LLM-1 | The OSS classifier LLM is configured by provider, model, base URL and key (`OSS_INTENT_LLM_*`), with no provider hard-coded. | ✅ |
| R-LLM-2 | The A2A-T LLM used by the Energy Agent is configured separately (`A2AT_LLM_*`). | ✅ |
| R-LLM-3 | The production classifier model is evaluated for semantic-validation sensitivity before GA. | 🟡 O-2 |

### FP-005 Invoke the Orchestration Center (High) — LLD §7.1, §12.2

| ID | Requirement | Status |
|---|---|---|
| R-ORC-1 | OSS authenticates to the Orchestration Center (`/rest/v1/orchestrate/auth/login`, session cookie or Bearer). | ✅ |
| R-ORC-2 | OSS submits complete intents through a **config-driven** path (`OSS_ORCH_SUBMIT_PATH`), so the endpoint can change without a code change. | 🔴 O-20 |
| R-ORC-3 | On submit, OSS writes audit event `workflow_started` and returns `202 Accepted` with `intent_id`. | ✅ |
| R-ORC-4 | A background worker pool (`OSS_SSE_WORKER_POOL_SIZE`) consumes the SSE stream with a timeout (`OSS_SSE_TIMEOUT_MS`); a timeout ends the intent `FAILED`, and synchronous callers get `504`. | ✅ |
| R-ORC-5 | If the SSE stream drops, OSS reconciles the final state through `GET /api/v1/executions/{id}`. | ✅ |

### FP-006 Orchestrate the energy-saving workflow (High) — LLD §7.6, §6.1

| ID | Requirement | Status |
|---|---|---|
| R-WF-1 | A PSOP workflow implements `intent → PriceNode → NegotiationNode → gateway → DispatchNode → MonitorNode → terminal`. | ✅ (shape) |
| R-WF-2 | Nodes bind to concrete agents discovered from the Registry Center by semantic query. | ✅ |
| R-WF-3 | Price and dispatch use the `on_task` hook; the feasible/infeasible branch uses `on_route`; mid-flight negotiation uses `on_negotiation`. | 🔴 O-3 |
| R-WF-4 | DispatchNode sends Task-T `network-layer/ran-energy-saving/v1` to MAE, after an Authorization-T check if one is required. | 🔴 O-12 |
| R-WF-5 | MonitorNode parses MAE's artifact stream (`TaskPlan`, `CellSelection`, `EnergySavingActivated`, `IntentReport`), with a stub parser until the schema is confirmed. | 🔴 O-11 |
| R-WF-6 | The workflow follows the state machine in LLD §6.1 and emits the SSE events in §6.3. | 🔴 O-19 |
| R-WF-7 | The workflow runs end-to-end in the sandbox with stub agents before live execution is enabled. | ✅ |

### FP-007 Energy-saving report display (Medium) — LLD §7.8

| ID | Requirement | Status |
|---|---|---|
| R-RPT-1 | `GET /api/v1/energy-saving/intents/{id}/status` returns `intent_id`, `workflow_state`, `artifacts`, `counter_proposal`, `final_report`, `failure_reason`. | ✅ (shape) |
| R-RPT-2 | The front-end shows the intent state, any counter-proposal, and the final report. | ✅ |
| R-RPT-4 | The final report shows, as MAE supplies them: predicted charging band per site, site classification (downgrade / upgrade / grade-stable), traffic-migration actions, and predicted electricity cost before and after. | 🔴 O-11 (deck D-6) |
| R-RPT-3 | The front-end renders an artifact timeline, with placeholder rendering until the schema is known. | 🔴 O-11 |

### FP-008 Permission control (Medium) — LLD §7.2

| ID | Requirement | Status |
|---|---|---|
| R-SEC-1 | RBAC permissions: `energy_saving:submit` (submit, supplement), `energy_saving:query` (status), `energy_saving:admin` (audit logs, workflows). | ✅ |
| R-SEC-2 | Permission checks happen once, at the OSS boundary. | ✅ |

### FP-009 Operation audit (Low) — LLD §7.3, §10

| ID | Requirement | Status |
|---|---|---|
| R-AUD-1 | Audit events: `intent_received`, `parameter_supplement`, `workflow_started`, `workflow_completed`, `workflow_failed`, each with `intent_id`, `user_id`, `trace_id` and a timestamp. | ✅ |
| R-AUD-2 | Terminal events (`workflow_completed` / `workflow_failed`) are written **once**, on first observation. | ✅ |
| R-AUD-3 | Audit events are ordered by a local monotonic sequence; out-of-order SSE events are buffered and reconciled before being written. | 🔴 O-19 |
| R-AUD-4 | Audit logs are readable only with `energy_saving:admin`. | ✅ |

---

## 3. Registry and discovery — LLD §8, §9

| ID | Requirement | Status |
|---|---|---|
| R-REG-1 | The Energy Agent registers the AgentCard in LLD §9 with skills `electricity_price_lookup` and `energy_saving_negotiation`. | ✅ |
| R-REG-2 | The Energy Agent sends heartbeats on a configured interval. | ✅ |
| R-REG-3 | The registration `layer` value comes from `ENERGY_AGENT_REGISTRY_LAYER`. | 🟡 O-13 |
| R-REG-4 | When `agent_approval_enabled=true`, cards are published before use; an agent is discoverable only when published and not hidden by the heartbeat check. | ✅ |
| R-REG-5 | The final `agent_id` (ULID) and endpoint URL come from the deployment topology. | 🔴 O-4 |

---

## 4. Non-functional requirements

| ID | Requirement | Source |
|---|---|---|
| R-NFR-1 | TLS 1.3 / 1.2 only; PEM certificates; RSA ≥ 3072 or ECDSA ≥ 256. | §15 |
| R-NFR-2 | Startup security checks fail closed; admin accounts come from bootstrap secrets. | §15 |
| R-NFR-3 | Startup order: OSS → Registry → Orchestration → Energy Agent → MAE → publish cards → verify discovery → sandbox dry run → enable live. | §15 |
| R-NFR-4 | `trace_id` propagates end to end; OpenTelemetry where supported (the Python SDK only; Orchestration and Registry have none). | §7.9 |
| R-NFR-5 | All endpoints, credentials and limits are configured through the environment variables in LLD §14. | §14 |
| R-NFR-6 | Retried intent submission must not start a duplicate workflow. | 🟡 O-8 |
| R-NFR-7 | EA ↔ MAE traffic uses an agreed trust model (mTLS per the AgentCard). | 🟡 O-7 |

---

## 5. Error handling — LLD §13

| Condition | Raised by | Result |
|---|---|---|
| Non-energy-saving intent | OSS classifier | `200 {handled:false}` |
| Incomplete parameters | OSS | `awaiting_supplement` |
| Permission denied | OSS Security | `403` |
| Agent not discoverable / registry unreachable | Orchestration | `FAILED` |
| Price API failure | EA price skill | `FAILED` (`price_api_unavailable`) |
| Negotiation infeasible | MAE via EA | `REJECTED` + counter-proposal |
| Negotiation aborted / round limit | EA | `FAILED` |
| Semantic rejection | A2A-T server | `FAILED` |
| MAE execution failure or timeout | MAE | `FAILED` |
| Orchestration timeout | OSS | `504` |

---

## 6. Interfaces

| Interface | Path / template | Status |
|---|---|---|
| FE → OSS | `POST /api/v1/energy-saving/intents`, `POST …/{id}/supplement`, `GET …/{id}/status` | ✅ |
| OSS → Orchestration | See §7 below and backlog item ORC-1 | 🔴 O-20 |
| Orchestration → Registry | `GET /rest/v1/registry-center/agent-cards`, `POST …/agent-cards/semantic-query`, `POST …/agent-cards-with-layer/semantic-query` | ✅ |
| Orchestration → EA | A2A-T task, price skill | 🔴 O-1 |
| EA ↔ MAE | `Negotiation-T/feasibility-negotiation/{propose, accept-reject}`, `common/abort` | 🔴 O-3 |
| Orchestration → MAE | `Task-T/network-layer/ran-energy-saving/v1` | 🔴 O-12 |
| MAE → Orchestration | Task-T artifact stream | 🔴 O-11 |

---

## 7. Baseline findings from the upstream code

These were checked against the imported code and **differ from, or narrow,
what the LLD assumes**. They should be confirmed with the Orchestration Center
maintainers but can already guide the design.

| # | Finding | Evidence | Affects |
|---|---|---|---|
| F-1 | `POST /api/v1/orchestrate/intent` only **generates and saves** a PSOP from the intent (LLM planning) and returns `201` with the PSOP. It does not execute anything or return an execution ID. | `orchestration-center/orchestrate/server/external_api.py` (`orchestrate_intent`) | O-20, R-ORC-2 |
| F-2 | `POST /api/v1/orchestrate/execute` searches for a matching PSOP (or generates one) and executes it, returning the **SSE stream directly in the response**. There is no separate "submit, then subscribe" step. | `external_api.py` (`execute_workflow`) | O-20, R-ORC-3/4 |
| F-3 | `GET /api/v1/orchestrate/execute/{psop_id}` starts an execution (a side-effecting GET), and passes only the PSOP **name** (or `user_intent`) as an intent string, not the PSOP itself. The host agent then re-resolves which PSOP to run. | `external_api.py` (`execute_psop_by_id`), `server/sse_executor.py` | O-20, R-WF-1 |
| F-4 | The Orchestration Center does not run the workflow itself: it dispatches the intent over A2A-T to a **host agent** (`orchestration-center/host_agent`), which runs the PSOP through the workflow-engine SDK and relays SDK events. | `sse_executor.py` docstring, `host_agent/runtime.py` | §5.2 architecture |
| F-5 | **Within one stream, events are FIFO** (one producer, one `asyncio.Queue`, one consumer). There are **no SSE `id:` fields or named `event:` lines**: each event is a `data:` JSON object with a `type`. There is **no resume** (`Last-Event-ID`) after a disconnect. Heartbeats are `: heartbeat` comments every 15 s. | `sse_executor.py` | O-19, R-AUD-3 |
| F-6 | Terminal event types are `complete`, `error` and **`cancelled`** (the last is not in the LLD). The server emits no `close` event; the stream just ends. A stream that ends without a terminal event is recorded as `FAILED`. | `sse_executor.py` | §6.4, R-AUD-2 |
| F-7 | The execution record (`GET /api/v1/executions/{id}`) is written when the stream ends, and is the source for reconciliation after a disconnect. | `sse_executor.py`, `external_api.py` | R-ORC-5 |
| F-8 | Default ports: Orchestration Center `5001`, Registry Center `5000`. | `common/util/conf_obj.py` in each repo | O-4 |
| F-9 | `a2a-t-sdk-python` is at **1.1.0** and ships the `Task-T/network-layer/ran-energy-saving`, `Negotiation-T/feasibility-negotiation` and `Authorization-T/authorization-policy-management` templates. | `pyproject.toml`, `src/a2a_t/prompt_resources/` | O-15 |

**Implication for O-20:** neither endpoint fits the LLD's "submit → get
execution ID → subscribe" flow as written. The two workable options are:

1. `POST /orchestrate/execute` and consume its SSE response in the OSS worker
   (one call; the worker holds the connection for the whole run), or
2. `POST /orchestrate/intent` to pin a PSOP, then `GET /orchestrate/execute/{psop_id}`
   to run it (two calls; subject to F-3).

Option 1 is the simpler fit; the decision is tracked as backlog item ORC-1.

---

## 8. Open items

| ID | Priority | Item | Owner |
|---|---|---|---|
| O-1 | 🔴 P0 | External price API contract (URL, auth, schema, rate limits, SLA, timezone) | External provider |
| O-3 | 🔴 P0 | MAE AgentCard: `agent_id`, endpoint, version, capability names | MAE team |
| O-4 | 🔴 P0 | Ports and deployment topology (defaults in F-8) | Platform |
| O-11 | 🔴 P0 | MAE artifact schema | MAE team |
| O-12 | 🔴 P0 | Whether MAE dispatch requires Authorization-T | Security + Product |
| O-19 | 🔴 P0 | SSE ordering and delivery guarantee (partly answered by F-5, F-6) | Orchestration Center team |
| O-20 | 🔴 P0 | Submission endpoint (narrowed by F-1 to F-3) | Orchestration Center team |
| O-2 | 🟡 P1 | Classifier model sensitivity | Product |
| O-5 | 🟡 P1 | Audit granularity sign-off | Compliance |
| O-7 | 🟡 P1 | EA ↔ MAE trust model | Security |
| O-8 | 🟡 P1 | Idempotent intent submission | OSS team |
| O-13 | 🟡 P1 | Registry `layer` string | Platform |
| O-14 | 🟡 P1 | Decision D-1: autonomous target relaxation | Product |
| O-15 | 🟡 P1 | Template hosting / SDK version pin (current: 1.1.0, F-9) | Release management |
| O-21 | 🔴 P0 | Power-band tariff semantics: is the GHS amount a monthly charge per site? Is the band chosen by peak or average kW? How are bands above 4.99 kW handled? Where does the tariff come from (price API or configuration)? | MTN / product |
| O-22 | 🔴 P0 | How a time-period schedule and a band tariff map onto Task-T `ran-energy-saving/v1` slots (`task_target`, `task_context`), and whether MAE accepts both in one intent | MAE team |
| O-23 | 🟡 P1 | Planning horizon (month) and how a `region` resolves to the cluster MAE optimizes | MAE team / product |
