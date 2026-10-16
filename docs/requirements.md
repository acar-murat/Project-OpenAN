# OpenAN Energy-Saving Function — Requirements

**Sources:** the original use-case deck ([use-cases.md](use-cases.md),
[`source/Open_AN_UC.pptx`](source/Open_AN_UC.pptx)) and LLD US202610010001
**v10.4** (2026-10-16, [`source/US202610010001-energy-saving-LLD-v10.4.md`](source/US202610010001-energy-saving-LLD-v10.4.md)), derived from the *OpenAN Energy-Saving Function Software
Design Specification v1.0.0*. Where the two differ, the requirement says so.
**Baseline:** the upstream repositories under `upstream/` (see the root README).

Each requirement has an ID (`R-<area>-<n>`), traces to a function point (FP)
and an LLD section, and carries a status:

- ✅ **Ready**: can be implemented now.
- 🟡 **P1**: can be built, but an open item must close before GA.
- 🔴 **P0**: blocked; the open item must close before implementation.

Open items (O-n) are listed in §8. Development tasks that implement these
requirements are in [development-backlog.md](development-backlog.md).
Requirements marked 🆕 are new in v10.4; §9 lists what changed from v10.2.

> **Design constraint (LLD v10.4 §0.0, assumption 12):** `orchestration-center`
> and `registry-center` code is **not modified**. Everything they do not do is
> done in OSS, the Energy Agent, the workflow definition, or their configuration.

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
which the platform does not provide; any change to Orchestration Center or
Registry Center code.

### Components

| Component | Source | Status |
|---|---|---|
| Front-end | New | To build |
| OSS (Business, Security, Audit, SSE watcher) | New | To build |
| Energy Agent | New, on `a2a-t-sdk-python` | To build (a mock stands in: `mocks/energy_agent`) |
| Registry Center | `upstream/registry-center` | Deploy and configure only |
| Orchestration Center | `upstream/orchestration-center` | Deploy and configure only; add workflow and node configuration |
| Workflow-engine SDK | `upstream/workflow-engine-sdk-python` | Use |
| MAE | External (Huawei iMaster MAE) | Integrate (a mock stands in: `mocks/mae`) |
| Electricity price API | External | Integrate (a mock stands in: `mocks/price_api`) |

---

## 2. Functional requirements

### FP-001 Intent reception, recognition and validation (High) — LLD §11.1, §12

| ID | Requirement | Status |
|---|---|---|
| R-INT-1 | OSS exposes `POST /api/v1/energy-saving/intents` accepting `raw_text` and optional `region`, `saving_target`, `experience_target`, `session_id`. | ✅ |
| R-INT-2 | OSS authenticates the caller and checks permission `energy_saving:submit` **before** any LLM call; it returns `401` when identity is not established and `403` on a missing permission. Both are audited (R-AUD-5). | ✅ |
| R-INT-3 | OSS writes audit event `intent_received` once authentication and the permission check pass. | ✅ |
| R-INT-4 | OSS classifies the text with the configured LLM, producing `{is_energy_saving_intent, confidence}`. | 🟡 O-2 |
| R-INT-5 | A non-energy-saving intent returns `200 {"handled": false}`, starts no workflow, and is audited as `intent_not_energy_saving` (informational, not a failure). | ✅ |
| R-INT-6 | OSS validates the required field `region` (→ Task-T `task_object`) and derives `operation_type` (`Create` / `Modify`) and `task_description`. | ✅ |
| R-INT-7 | Missing required parameters return status `awaiting_supplement` with the list of missing fields. | ✅ |
| R-INT-8 | `POST /api/v1/energy-saving/intents/{id}/supplement` merges new fields into the pending intent by `session_id`, writes audit event `parameter_supplement`, and re-runs validation. | ✅ |
| R-INT-10 | The intent carries a **time-period schedule**: a list of `{start_hour, end_hour, saving_mode, experience_target}` entries (UC1 input 1). Periods may wrap midnight (e.g. 23–5). | ✅ (deck D-2) |
| R-INT-11 | `saving_mode` is one of `maximized_energy_saving`, `proactive_energy_saving`, `experience_first`; `experience_target` is one of `none`, `rate_floor` (with a value in Mbps, e.g. 10), `no_degradation`. | ✅ (deck D-3) |
| R-INT-12 | Validation rejects schedules whose periods overlap or leave hours uncovered; together they must cover 0–23 exactly once. | ✅ |
| R-INT-13 | The intent carries the planning month the optimization applies to. | 🟡 O-29 |
| R-INT-9 | Each intent gets a `trace_id`, which is passed to the Orchestration Center and written into every audit event. | ✅ |
| R-INT-14 🆕 | The processing order is fixed: authenticate → RBAC → audit `intent_received` → classify → validate parameters → region scope (R-SEC-3) → audit `workflow_started` → submit. | ✅ (§11.2) |

### FP-002 Energy-saving intent negotiation (Medium) — LLD §11.5, §5.2

| ID | Requirement | Status |
|---|---|---|
| R-NEG-1 | The Energy Agent opens a Negotiation-T `feasibility-negotiation/propose` with `category=goal_achievement`, `message_class=initiate_feasibility_assessment` and `under_evaluation_description` {region, saving_target, experience_target, electricity_price_table}. | 🔴 O-3 |
| R-NEG-2 | The Energy Agent handles both MAE replies with `accept-reject` Accept: *feasible-request-confirmation* → `AGREED`; *infeasible-with-proposal* → `CLOSED_INFEASIBLE`, with the counter-proposal returned to the user. Any other reply is closed with `common/abort`. | 🔴 O-3 (done against the mock MAE) |
| R-NEG-3 | Negotiation is bounded by `ENERGY_AGENT_NEGOTIATION_MAX_ROUNDS` (default 3) and a per-round timeout (`ENERGY_AGENT_NEGOTIATION_ROUND_TIMEOUT_MS`); on exhaustion the agent sends `common/abort`. | ✅ |
| R-NEG-4 | The agent is stateless per message; round state lives in the negotiation context. | ✅ |
| R-NEG-5 | The agent never relaxes user targets on its own unless `ENERGY_AGENT_ALLOW_TARGET_RELAXATION=true` (default `false`). | 🟡 O-14 |
| R-NEG-6 | Every round is recorded as a `NegotiationRound` (LLD §12) and in the Energy Agent's audit log (R-EAS-3). | ✅ |

### FP-003 External electricity price acquisition (High) — LLD §11.4

| ID | Requirement | Status |
|---|---|---|
| R-PRC-1 | The Energy Agent exposes skill `electricity_price_lookup` (input: `region`, optional `date_range`; output: `price_table[]` of `{start_time, end_time, relative_price}`). | ✅ (shape) |
| R-PRC-2 | Price retrieval goes through an adapter interface, with a stub implementation for development and tests. | ✅ |
| R-PRC-3 | The production adapter calls the external price API with configured URL, key and timeout (`ENERGY_AGENT_PRICE_API_TIMEOUT_MS`, default 5000), over TLS, with the key from a secret store. | 🔴 O-1 |
| R-PRC-5 | The price model supports a **power-band tariff**: a list of `{band_no, min_kw, max_kw, charge, currency, billing_period}` (UC1 input 2; e.g. band 1 = 0.00–0.99 kW → 8,247.66 GHS). The LLD's time-of-use `price_table` stays as a second price type, used by UC2. | 🔴 O-1, O-27 (deck D-1) |
| R-PRC-6 | Electricity prices and the intent schedule are combined into one A2A-T intent ("integration of electricity price synergy and energy-saving intentions"); the two tables keep their own periods and are not forced to align. | ✅ (deck D-1) |
| R-PRC-4 | A price API failure ends the workflow `FAILED` with reason `price_api_unavailable`; the skill never returns an empty table. | ✅ |

### FP-004 External LLM adaptation (High) — LLD §11.1, §15

| ID | Requirement | Status |
|---|---|---|
| R-LLM-1 | The OSS classifier LLM is configured by provider, model, base URL and key (`OSS_INTENT_LLM_*`), with no provider hard-coded. | ✅ |
| R-LLM-2 | The A2A-T LLM used by the Energy Agent is configured separately (`A2AT_LLM_*`). | ✅ |
| R-LLM-3 | The production classifier model is evaluated for semantic-validation sensitivity before GA. | 🟡 O-2 |

### FP-005 Invoke the Orchestration Center (High) — LLD §11.1, §11.6, §13.2

| ID | Requirement | Status |
|---|---|---|
| R-ORC-1 | OSS authenticates to the Orchestration Center with a **service credential**, not a user login: ORCH `external.auth.mode` is set to `mtls` (preferred) or `bearer` (`ORCH_API_TOKEN`, at least 32 bytes), and OSS holds the matching secret (`OSS_ORCH_AUTH_MODE`, `OSS_ORCH_BEARER_TOKEN_REF`, `OSS_ORCH_CLIENT_CERT_REF`). Configuration only (F-12). | ✅ (O-21 resolved) |
| R-ORC-2 | OSS submits complete intents with `POST /api/v1/orchestrate/execute` and consumes the SSE response directly. | ✅ (O-20 resolved) |
| R-ORC-3 | OSS writes audit event `workflow_started` **before** submitting; if that write fails, nothing is submitted (fail closed). It then returns `202 Accepted` with `intent_id`. | ✅ |
| R-ORC-4 | An OSS SSE watcher holds the stream open until a terminal event (`OSS_ORCH_STREAM_IDLE_TIMEOUT_MS`, `OSS_ORCH_EXECUTION_TIMEOUT_MS`). It is the only observer of a running workflow: status during a run comes from OSS's own store, fed by the stream. A timeout ends the intent `FAILED`; synchronous callers get `504`. | ✅ |
| R-ORC-5 | After the stream ends, OSS resolves the ORCH `execution_id` through `GET /api/v1/executions` by `psop_id` and start time, then audits `execution_linked`. There is no polling of a running execution: the record exists only once the stream ends (F-7). | 🟡 O-23 |
| R-ORC-6 🆕 | A dropped or ended-without-terminal stream ends the intent `FAILED` with `orchestration_stream_lost` and is audited as `workflow_stream_lost`; ORCH records such a run as `STOPPED` and it cannot be resumed (F-13). | ✅ (O-26 open) |
| R-ORC-7 🆕 | ORCH's busy `503` maps to a retryable `orchestration_busy` error with `Retry-After`. | ✅ |

### FP-006 Orchestrate the energy-saving workflow (High) — LLD §11.6, §7, §5.1

| ID | Requirement | Status |
|---|---|---|
| R-WF-1 | A PSOP workflow implements `intent → PriceNode → NegotiationNode → gateway → DispatchNode → MonitorNode → terminal`, built by importing the IG1526A solution package where possible. | ✅ (shape) |
| R-WF-2 | Nodes bind to concrete agents discovered from the Registry Center by semantic query; a missing card fails with `agent_not_discoverable`, never a hard-coded fallback address. | ✅ |
| R-WF-3 | Price and dispatch use the `on_task` hook; the feasible/infeasible branch uses `on_route`; mid-flight negotiation uses `on_negotiation`. | 🔴 O-3 |
| R-WF-4 | DispatchNode sends Task-T `network-layer/ran-energy-saving/v1` to MAE, after an Authorization-T exchange if one is required. Any such exchange lives in the workflow definition, not in ORCH code. | 🔴 O-12 |
| R-WF-5 | MonitorNode parses MAE's artifact stream (`TaskPlan`, `CellSelection`, `EnergySavingActivated`, `IntentReport`), with a stub parser until the schema is confirmed. | 🔴 O-11 |
| R-WF-6 | The workflow follows the state machine in LLD §5.1. Terminal SSE events are `complete`, `error` and `cancelled` (F-6). | ✅ (O-19 resolved) |
| R-WF-7 | The workflow runs end-to-end in the sandbox with stub agents before live execution is enabled, covering normal, infeasible with counter-proposal, price API error and delayed response. | ✅ |

### FP-007 Energy-saving report display (Medium) — LLD §11.8

| ID | Requirement | Status |
|---|---|---|
| R-RPT-1 | `GET /api/v1/energy-saving/intents/{id}/status` returns `intent_id`, `workflow_state`, `artifacts`, `counter_proposal`, `final_report`, `failure_reason`, built from OSS's own store and filtered by ownership (R-SEC-4); raw ORCH data is never relayed. | ✅ (shape) |
| R-RPT-2 | The front-end shows the intent state, any counter-proposal, and the final report. | ✅ |
| R-RPT-4 | The final report shows, as MAE supplies them: predicted charging band per site, site classification (downgrade / upgrade / grade-stable), traffic-migration actions, and predicted electricity cost before and after. | 🔴 O-11 (deck D-6) |
| R-RPT-3 | The front-end renders an artifact timeline, with placeholder rendering until the schema is known. | 🔴 O-11 |

### FP-008 Permission control (Medium) — LLD §11.2, §17

OSS is the only component that knows the end user: ORCH sees OSS as one
machine identity and has no per-user ownership or roles (F-12, F-14).

| ID | Requirement | Status |
|---|---|---|
| R-SEC-1 | RBAC permissions: `energy_saving:submit` (submit, supplement), `energy_saving:query` (status), `energy_saving:admin` (audit logs, workflows). | ✅ |
| R-SEC-2 | Permission checks happen once, at the OSS boundary. | ✅ |
| R-SEC-3 🆕 | **Region scope:** a user may target only regions in their allowed set (`user → regions`). Checked after parameter extraction and before submit; failure returns `403` and is audited as `permission_denied`. | ✅ |
| R-SEC-4 🆕 | **Object ownership:** status and report queries return an intent only to its owner or an `admin`. OSS keeps its own `intent_id → user_id` table (`ExecutionLink`, LLD §12). | ✅ |
| R-SEC-5 🆕 | **Input handling:** `raw_text` has a length cap (`OSS_RAW_TEXT_MAX_CHARS`) and is treated as data. Classifier output is schema-validated to its two fields. Only structured, validated fields are forwarded; `raw_text` never goes to ORCH, the Energy Agent or MAE. | ✅ |
| R-SEC-6 🆕 | **Rate limiting:** per-user limits on submit and supplement (`OSS_RATE_LIMIT_SUBMIT_PER_MIN`). | ✅ |
| R-SEC-7 🆕 | **Secrets:** price API key, LLM keys and the ORCH credential come from the environment or a secret manager, are redacted from logs and audit, and each has a rotation owner. | ✅ |
| R-SEC-8 🆕 | **Network isolation:** ORCH accepts connections only from OSS and operations hosts; the Energy Agent accepts A2A-T only from ORCH; MAE accepts Negotiation-T only from the Energy Agent and Task-T only from ORCH; the Registry is reachable only by ORCH, the Energy Agent and MAE. This is the main control, since ORCH has no per-user access control. | ✅ (deployment, LLD §8) |

### FP-009 Operation audit (Low) — LLD §11.3, §9, §17

OSS owns the audit trail: the Orchestration Center audits PSOP and AgentCard
changes but **not workflow executions** (F-15), and neither center has end-user
identity, so OSS's records are the authoritative record of an energy-saving action.

| ID | Requirement | Status |
|---|---|---|
| R-AUD-1 | Audit events: `auth_failure`, `permission_denied`, `intent_received`, `intent_not_energy_saving`, `parameter_supplement`, `workflow_started`, `negotiation_summary`, `workflow_completed`, `workflow_failed`, `workflow_rejected`, `workflow_stream_lost`, `execution_linked`, `audit_read`. | ✅ |
| R-AUD-2 | Terminal events (`workflow_completed` / `workflow_failed` / `workflow_rejected` / `workflow_stream_lost`) are written **once** per `intent_id`, driven by the SSE watcher, not by status polling. | ✅ |
| R-AUD-3 | Within one stream, events are trusted in arrival order (FIFO, F-5); the watcher is idempotent on `(execution_id, type, timestamp)`. | ✅ (O-19 resolved) |
| R-AUD-4 | Audit logs are readable only with `energy_saving:admin`, and every read or export is itself audited as `audit_read`. | ✅ |
| R-AUD-5 🆕 | Denials are audited: `auth_failure` (no user id; source IP recorded) and `permission_denied` (the permission or region refused). | ✅ |
| R-AUD-6 🆕 | Every record follows the LLD §11.3 schema: `audit_id`, `ts` (RFC 3339 UTC), `event`, `intent_id`, `trace_id`, `actor {user_id, source_ip, roles}`, `resource {region, psop_id, execution_id}`, `outcome` (`success` / `failure` / `denied`), `reason`, `detail_digest`, `prev_hash`, `hash`. Reference implementation: `mocks/common/audit.py`. | ✅ |
| R-AUD-7 🆕 | **Integrity:** append-only store whose OSS database role has `INSERT` and `SELECT` only; records are hash-chained (`prev_hash`, `hash`), and a periodic verifier job reports breaks. | ✅ |
| R-AUD-8 🆕 | **Write-failure policy:** `workflow_started` fails closed (no submit); terminal and negotiation events are spooled to local durable storage (`OSS_AUDIT_SPOOL_DIR`) and retried; a stuck spool raises an alert. | ✅ |
| R-AUD-9 🆕 | Payloads are redacted before hashing and storage. Raw user text is not stored unless compliance decides otherwise (`OSS_AUDIT_STORE_RAW_TEXT=false`). Retention and archive target are configuration (`OSS_AUDIT_RETENTION_DAYS`). Clocks are NTP-synchronized. | 🟡 O-5, O-24 |
| R-AUD-10 🆕 | **One parser for every log:** OSS and Energy Agent records map onto the six elements of the upstream audit format (Registry Security Guide; ORCH `common/log/audit_logger.py`): time → `ts`, client IP → `actor.source_ip`, user name → `actor.user_id`, operation name → `event`, operation target → `resource`, result → `outcome`. An exporter emits that shape for SIEM ingestion. | ✅ (security research, gap 1) |

### Energy Agent security and audit (FP-002, FP-008, FP-009) 🆕 — LLD §11.11, §11.10

| ID | Requirement | Status |
|---|---|---|
| R-EAS-1 | **Caller authentication:** the Energy Agent accepts A2A-T requests only from the ORCH service identity (mTLS peer certificate or configured bearer, `ENERGY_AGENT_ALLOWED_CALLERS`) and rejects everything else. | 🟡 O-25 (done in the mock: `mocks/energy_agent/caller_auth.py`) |
| R-EAS-2 | **Policy guard:** before it can report `agreed`, the agent checks the request against operator policy: region in `ENERGY_AGENT_POLICY_REGION_ALLOWLIST`, `experience_target` not below `ENERGY_AGENT_POLICY_MIN_EXPERIENCE_FLOOR`, `saving_target` not above `ENERGY_AGENT_POLICY_MAX_SAVING_TARGET`, and optional allowed time windows (`ENERGY_AGENT_POLICY_SAVING_WINDOWS`). A violation fails with `policy_violation`, separately from MAE's feasibility result. | ✅ (done in the mock: `mocks/energy_agent/policy.py`) |
| R-EAS-3 | **Local audit log:** an append-only, hash-chained record (same schema as R-AUD-6, at `ENERGY_AGENT_AUDIT_LOG_PATH`) per policy decision and negotiation round: `trace_id`, round, template sent and received, outcome, price-table digest, policy decision, caller identity. Joined to OSS's log by `trace_id`. | ✅ (done in the mock) |
| R-EAS-4 | **No silent relaxation:** a counter-proposal goes back to the user, not into the network (D-1, R-NEG-5). | ✅ |
| R-EAS-5 | **Prompt-injection stance:** only structured fields go into negotiation messages; free text from users or the price API is never interpreted as instructions. | ✅ |
| R-EAS-6 | **Outbound trust:** mutual authentication to MAE (R-NFR-7); price API key from secrets, TLS, bounded timeout. No secret appears in logs or audit. | 🟡 O-7 |
| R-EAS-7 | **Agent identity:** the audit log records a digest of the MAE AgentCard the agent negotiated with, so a record shows which card was used. | ✅ (done in the mock; security research, gap 6) |

---

## 3. Registry and discovery — LLD §7, §11.4

| ID | Requirement | Status |
|---|---|---|
| R-REG-1 | The Energy Agent registers an AgentCard with skills `electricity_price_lookup` and `energy_saving_negotiation` (card per LLD v10.2 §9; v10.4 no longer reproduces it). | ✅ |
| R-REG-2 | The Energy Agent sends heartbeats on the registry's configured interval. | ✅ |
| R-REG-3 | The registration `layer` value comes from `ENERGY_AGENT_REGISTRY_LAYER`. | 🟡 O-13 |
| R-REG-4 | When `agent_approval_enabled=true`, cards are published before use; an agent is discoverable only when published and not hidden by the heartbeat check. Startup is not complete until the card is published. | ✅ |
| R-REG-5 | The final `agent_id` (ULID) and endpoint URL come from the deployment topology. | 🔴 O-4 |
| R-REG-6 🆕 | Registration and heartbeat use whatever authentication the deployed registry requires, supplied by configuration. | 🟡 O-22 |

---

## 4. Non-functional requirements

| ID | Requirement | Source |
|---|---|---|
| R-NFR-1 | TLS 1.3 / 1.2 only on every hop; PEM certificates; RSA ≥ 3072 or ECDSA ≥ 256. | §11.2, §16 |
| R-NFR-2 | Startup security checks fail closed; admin accounts come from bootstrap secrets. ORCH `external.auth.mode` and its credential are set before first start. | §16 |
| R-NFR-3 | Startup order: OSS → Registry → Orchestration → Energy Agent → MAE → publish cards → verify discovery → sandbox dry run → enable live. | §16 |
| R-NFR-4 | `trace_id` propagates end to end; OpenTelemetry where supported (the Python SDK only; Orchestration and Registry have none, so OSS and Energy Agent audit tie the segments together). | §11.9 |
| R-NFR-5 | All endpoints, credentials and limits are configured through the environment variables in LLD §15. | §15 |
| R-NFR-6 | Retried intent submission must not start a duplicate workflow. | 🟡 O-8 |
| R-NFR-7 | EA ↔ MAE traffic is mutually authenticated, using the Registry certificate profile (TLS 1.2/1.3, RSA ≥ 3072 / ECDSA ≥ 256, mTLS). | 🟡 O-7 |
| R-NFR-8 🆕 | **Registry production posture**, by configuration only: HTTPS with `verify_client`, `owner.isolation.enabled=true`, `startup.strict.identity=true`, signed AgentCards with a `jku` allowlist, CRL configured. The dev profile turns all of these off (F-10). | 🟡 O-22 (security research, gap 3) |
| R-NFR-9 🆕 | Deployment creates the append-only audit store with an insert-only role and verifies the hash-chain job runs before go-live. | §16 |

---

## 5. Error handling — LLD §14

| Condition | Raised by | Result |
|---|---|---|
| Non-energy-saving intent | OSS classifier | `200 {handled:false}` |
| Incomplete parameters | OSS | `awaiting_supplement` |
| Authentication failed 🆕 | OSS Security | `401`, `auth_failure` audited |
| Permission denied / region not permitted | OSS Security | `403` (before any LLM call for RBAC), `permission_denied` audited |
| Agent not discoverable | Orchestration | `FAILED` (`agent_not_discoverable`) |
| Registry unreachable | Orchestration | `FAILED` (`registry_unavailable`) |
| Price API failure | EA price skill | `FAILED` (`price_api_unavailable`) |
| Policy violation 🆕 | EA policy guard | `FAILED` (`policy_violation`) |
| Negotiation infeasible | MAE via EA | `REJECTED` + MAE's basis and counter-proposal |
| Negotiation aborted / round limit | EA | `FAILED` (`negotiation_aborted`) |
| Semantic rejection | A2A-T server | `FAILED` (`semantic_validation_failed`) |
| MAE execution failure or timeout | MAE | `FAILED` (MAE's reason) |
| ORCH busy 🆕 | Orchestration (`503`) | retry: `orchestration_busy`, `Retry-After` |
| SSE stream lost 🆕 | OSS watcher | `FAILED` (`orchestration_stream_lost`); ORCH records `STOPPED` |
| Orchestration timeout | OSS | `504` |

---

## 6. Interfaces

| Interface | Path / template | Status |
|---|---|---|
| FE → OSS | `POST /api/v1/energy-saving/intents`, `POST …/{id}/supplement`, `GET …/{id}/status` | ✅ |
| OSS → Orchestration | `POST /api/v1/orchestrate/execute` (SSE, service credential); after the stream: `GET /api/v1/executions`, `GET /api/v1/executions/{id}` | ✅ (O-23 for id resolution) |
| Orchestration → Registry | `GET /rest/v1/registry-center/agent-cards`, `POST …/agent-cards/semantic-query`, `POST …/agent-cards-with-layer/semantic-query` | ✅ |
| Orchestration → EA | A2A-T task, price skill (caller-authenticated, R-EAS-1) | 🔴 O-1, O-25 |
| EA ↔ MAE | `Negotiation-T/feasibility-negotiation/{propose, accept-reject}`, `common/abort` | 🔴 O-3 |
| Orchestration → MAE | `Task-T/network-layer/ran-energy-saving/v1` | 🔴 O-12 |
| MAE → Orchestration | Task-T artifact stream | 🔴 O-11 |

---

## 7. Baseline findings from the upstream code

These were checked against the imported code. Most now agree with LLD v10.4;
where they still differ from, or narrow, what the LLD says, the row says so.

| # | Finding | Evidence | Affects |
|---|---|---|---|
| F-1 | `POST /api/v1/orchestrate/intent` only **generates and saves** a PSOP from the intent (LLM planning) and returns `201` with the PSOP. It does not execute anything or return an execution ID. | `orchestration-center/orchestrate/server/external_api.py` (`orchestrate_intent`) | O-20 (resolved) |
| F-2 | `POST /api/v1/orchestrate/execute` searches for a matching PSOP (or generates one) and executes it, returning the **SSE stream directly in the response**. There is no separate "submit, then subscribe" step. LLD v10.4 adopts this as the submit path. | `external_api.py` (`execute_workflow`) | R-ORC-2 |
| F-3 | `GET /api/v1/orchestrate/execute/{psop_id}` starts an execution (a side-effecting GET), and passes only the PSOP **name** (or `user_intent`) as an intent string, not the PSOP itself. The host agent then re-resolves which PSOP to run. | `external_api.py` (`execute_psop_by_id`), `server/sse_executor.py` | R-WF-1 |
| F-4 | The Orchestration Center does not run the workflow itself: it dispatches the intent over A2A-T to a **host agent** (`orchestration-center/host_agent`), which runs the PSOP through the workflow-engine SDK and relays SDK events. | `sse_executor.py` docstring, `host_agent/runtime.py` | Architecture |
| F-5 | **Within one stream, events are FIFO** (one producer, one `asyncio.Queue`, one consumer). There are **no SSE `id:` fields or named `event:` lines**: each event is a `data:` JSON object with a `type`. There is **no resume** (`Last-Event-ID`) after a disconnect. Heartbeats are `: heartbeat` comments every 15 s. Agrees with LLD v10.4 O-19. | `sse_executor.py` | R-AUD-3 |
| F-6 | Terminal event types are `complete`, `error` and **`cancelled`**. The server emits **no `close` event**; the stream just ends. LLD v10.4 still lists `close` (§3, O-19) and omits `cancelled`; the code is authoritative here, and the LLD should be corrected. | `sse_executor.py` | R-WF-6, R-AUD-2 |
| F-7 | The execution record is created only **when the stream ends**, and its `execution_id` is **not in the stream** (events carry the workflow/PSOP id). `GET /api/v1/executions` returns all records sorted by start time with no filter, so OSS matches `psop_id` and start time on its side. Agrees with LLD v10.4 (C9, C12). | `sse_executor.py` (`finally` block), `external_api.py` (`list_executions`) | R-ORC-5, O-23 |
| F-8 | Default ports: Orchestration Center `5001`, Registry Center `5000`. | `common/util/conf_obj.py` in each repo | O-4 |
| F-9 | `a2a-t-sdk-python` is at **1.1.0** and ships the `Task-T/network-layer/ran-energy-saving`, `Negotiation-T/feasibility-negotiation` and `Authorization-T/authorization-policy-management` templates. | `pyproject.toml`, `src/a2a_t/prompt_resources/` | O-15 |
| F-10 | Both services run locally without containers: Registry in its documented local HTTP profile (TLS, signing and owner isolation off), Orchestration over HTTP with a configured admin credential (it refuses to start without one, even on loopback). Orchestration lists Registry agents at `GET /rest/v1/orchestrate/agent-cards`. | `scripts/dev.py`, [dev-environment.md](dev-environment.md) | O-4, R-NFR-8 |
| F-11 | `orchestration-center` installs `workflow-exec-engine` 0.0.9 and `a2a-sdk` 1.2.x from PyPI; the vendored workflow-engine SDK is 0.1.0, outside its `<0.1` pin. | `orchestration-center/requirements.txt` | O-15, PLT-5 |
| F-12 🆕 | ORCH external API auth is chosen by `external.auth.mode`: `user` (default), `mtls`, `bearer` (token from `ORCH_API_TOKEN` or `external.auth.token_env`, at least 32 bytes) or `custom`. Each yields one machine identity, not the end user. | `orchestrate/server/external_auth.py` | R-ORC-1, O-21 (resolved) |
| F-13 🆕 | If the client disconnects before the stream completes, the record is saved as `STOPPED` ("SSE stream closed before execution completed") and the server cancels its own drain task. Whether the host agent's run also stops is not confirmed. | `sse_executor.py` (`finally` block) | R-ORC-6, O-26 |
| F-14 🆕 | `GET /api/v1/executions` and `/{id}` apply only a rate limiter on top of external auth: no per-user filter or ownership. | `external_api.py` (`list_executions`, `get_execution`) | R-SEC-4, R-SEC-8 |
| F-15 🆕 | ORCH's own audit log covers server start, PSOP save/delete and AgentCard update/delete only; **workflow executions are not audited**. | `audit_logger.audit` is called only in `orchestrate/start.py` and `orchestrate/server/frontend_support_server.py`; none in `external_api.py` or `sse_executor.py` | FP-009 |

---

## 8. Open items

Numbering follows LLD v10.4 §18. The deck items this repo raised as O-21 to
O-23 under v10.2 are renumbered **O-27 to O-29**, because v10.4 reuses O-21 to
O-23 for other items.

| ID | Priority | Item | Owner |
|---|---|---|---|
| O-1 | 🔴 P0 | External price API contract (URL, auth, schema, rate limits, SLA, timezone) | External provider |
| O-3 | 🔴 P0 | MAE AgentCard: `agent_id`, endpoint, version, capability names | MAE team |
| O-4 | 🔴 P0 | Ports and deployment topology (defaults in F-8) | Platform |
| O-11 | 🔴 P0 | MAE artifact schema | MAE team |
| O-12 | 🔴 P0 | Whether MAE dispatch requires Authorization-T (the Energy Agent policy guard is in place regardless) | Security + Product |
| O-25 🆕 | 🔴 P0 | Which caller-authentication mechanisms the A2A-T SDK server supports for the Energy Agent | Energy Agent team |
| O-27 | 🔴 P0 | Power-band tariff semantics: is the GHS amount a monthly charge per site? Is the band chosen by peak or average kW? How are bands above 4.99 kW handled? Where does the tariff come from (price API or configuration)? (was O-21) | MTN / product |
| O-28 | 🔴 P0 | How a time-period schedule and a band tariff map onto Task-T `ran-energy-saving/v1` slots (`task_target`, `task_context`), and whether MAE accepts both in one intent (was O-22) | MAE team |
| O-2 | 🟡 P1 | Classifier model sensitivity (confirmed by test) | Product |
| O-5 | 🟡 P1 | Audit granularity sign-off; whether raw user text is stored | Compliance |
| O-7 | 🟡 P1 | EA ↔ MAE mutual-authentication mechanism | Security |
| O-8 | 🟡 P1 | Idempotent intent submission | OSS team |
| O-13 | 🟡 P1 | Registry `layer` string | Platform |
| O-14 | 🟡 P1 | Decision D-1: autonomous target relaxation (default: return to the user) | Product |
| O-15 | 🟡 P1 | Template hosting / SDK version pin (current: 1.1.0, F-9) | Release management |
| O-22 🆕 | 🟡 P1 | Registry authentication for registration and heartbeat (unverified; read the deployed registry's config) | Platform |
| O-23 🆕 | 🟡 P1 | Resolving `execution_id` after a run by `psop_id` + start time: confirm it is reliable when runs overlap | Orchestration Center team |
| O-24 🆕 | 🟡 P1 | Audit retention period and archive target | Compliance |
| O-26 🆕 | 🟡 P1 | Whether a dropped SSE connection cancels the running workflow or only marks the record `STOPPED` (F-13; design assumes it may cancel) | Orchestration Center team |
| O-29 | 🟡 P1 | Planning horizon (month) and how a `region` resolves to the cluster MAE optimizes (was O-23) | MAE team / product |

**Resolved in v10.4:** O-19 (SSE ordering: FIFO per stream, no resume; F-5,
with the `close`/`cancelled` correction in F-6), O-20 (submit endpoint:
`POST /api/v1/orchestrate/execute`), O-21 (ORCH auth: `mtls` or `bearer`
service credential, F-12).

---

## 9. Changes from LLD v10.2

| Area | v10.2 | v10.4 | Requirements |
|---|---|---|---|
| Upstream code | Small upstream changes proposed (backlog §8) | Orchestration and Registry code is **not modified**; proposals become feature requests | §1, backlog §8 |
| Submit path | Config-driven, endpoint open (O-20) | `POST /api/v1/orchestrate/execute`, SSE held open | R-ORC-2, R-ORC-4 |
| OSS → ORCH auth | User login, cookie or Bearer | Service credential, `mtls` or `bearer` | R-ORC-1 |
| Run status | Poll `GET /executions/{id}`; reconcile after a drop | Record exists only after the stream ends; OSS watcher is the observer; `workflow_stream_lost` on a drop | R-ORC-4 … R-ORC-6 |
| OSS security | RBAC only | Authentication, region scope, ownership, input handling, rate limits, secrets, network isolation | R-SEC-3 … R-SEC-8 |
| Audit | Five events, monotonic sequence | Thirteen events, fixed schema, hash chain, insert-only store, spool, denials audited | R-AUD-1 … R-AUD-10 |
| Energy Agent | Price and negotiation | Adds caller authentication, policy guard, local hash-chained audit | R-EAS-1 … R-EAS-7 |
| Infeasible verdict | Ends the negotiation | Energy Agent sends Accept → `CLOSED_INFEASIBLE` | R-NEG-2 |
| Errors | — | `auth_failure`, `permission_denied`, `policy_violation`, `orchestration_busy`, `orchestration_stream_lost`, `registry_unavailable` | §5 |
| LLD section numbers | Component design in §7 | Component design in §11; most later sections shift by one | throughout |
