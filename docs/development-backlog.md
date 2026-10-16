# OpenAN Energy-Saving Function — Development Backlog

The change and development list for implementing
[requirements.md](requirements.md), which traces to the original use cases
([use-cases.md](use-cases.md)) and LLD US202610010001 v10.4. The first
release delivers UC1 (power-band energy saving).

**How to read it**

- Work items have an ID (`<area>-<n>`), the requirements they cover, what they
  depend on, and a definition of done.
- **Status:** ✅ Ready (start now) · 🟡 Ready, finish before GA · 🔴 Blocked on an open item · ☑️ Done.
- Blocked items are designed so that a stub lets development continue; only
  the item that swaps the stub for the real integration is blocked.
- **No changes to `upstream/orchestration-center` or `upstream/registry-center`**
  (LLD v10.4 §0.0). Anything they lack is built in OSS, the Energy Agent or the
  workflow definition, or set by their configuration. §8 lists the gaps as
  feature requests to raise upstream, not as patches to apply here.
- Items marked 🆕 are new or reworked for LLD v10.4.

---

## 1. Milestones

| Milestone | Goal | Items | Gate |
|---|---|---|---|
| **M0 Foundation** | Repo layout, CI, dev stack running locally | PLT-1 … PLT-5 | Registry + Orchestration start with `docker compose up` |
| **M1 OSS core** | Intents accepted, validated, audited, permission-checked | OSS-1 … OSS-9, OSS-14, OSS-16 … OSS-19 | OSS API tests pass with the LLM stubbed |
| **M2 Energy Agent (stubbed)** | Agent registered and discoverable; price skill, policy guard and negotiation work against stubs | EA-1 … EA-7, EA-10, EA-12, EA-13 | Agent appears in a semantic query; negotiation runs against Mock MAE |
| **M3 Sandbox end-to-end** | Full workflow runs in the sandbox with stub agents; OSS consumes SSE | ORC-1 … ORC-7, OSS-10 … OSS-12 | Intent → `COMPLETED` / `REJECTED` / `FAILED` end to end with stubs |
| **M4 Front-end** | Submit, supplement, status and report screens | FE-1 … FE-4, FE-6 | Manual demo against M3 |
| **M5 Live integration** | Real price API and MAE | EA-8, EA-9, EA-11, EA-14, ORC-8, ORC-9, FE-5, FE-7 | **Needs O-1, O-3, O-11, O-12, O-25, O-27, O-28** |
| **M6 GA hardening** | P1 items closed, security review, deployment | GA-1 … GA-12 | All 🟡 items closed |

---

## 2. Platform and repository (M0)

| ID | Item | Covers | Depends on | Status | Done when |
|---|---|---|---|---|---|
| PLT-1 | Create the repo layout: `services/oss`, `services/energy-agent`, `workflows/energy-saving`, `frontend`, `deploy`, `tests/e2e`. | — | — | ✅ | Folders exist, each with a README and an empty test suite |
| PLT-2 | Add `deploy/docker-compose.dev.yml` that starts Registry (5000) and Orchestration (5001) from `upstream/`, plus OSS and the Energy Agent. Ports come from env vars, defaulting to F-8. | R-NFR-3, R-NFR-5 | PLT-1 | ✅ | `docker compose up` brings all services up healthy |
| PLT-3 | Add `.env.example` with every variable in LLD §15 (including the v10.4 `OSS_ORCH_*`, `OSS_AUDIT_*`, `OSS_RATE_LIMIT_*` and `ENERGY_AGENT_POLICY_*` / `ALLOWED_CALLERS` / `AUDIT_LOG_PATH` groups), each blocked value marked with its O-item. Secrets are references, never values. | R-NFR-5, R-SEC-7 | PLT-1 | ✅ | File committed; services fail fast on a missing required variable |
| PLT-4 | Add CI (GitHub Actions). **Done for the current code:** `.github/workflows/ci.yml` runs ruff + pytest on `mocks/` and a full dev-stack run (`scripts/dev.py ci`). Extend to `services/*` as they appear. | — | PLT-1 | ☑️ | CI green on `main` |
| PLT-5 | Pin `a2a-t-sdk` 1.1.0 and `workflow-exec-engine` from the vendored subtrees (path dependencies). | O-15 | PLT-1 | 🟡 | Services install the SDKs from `upstream/` |
| PLT-8 | Local dev runner and VS Code setup: `scripts/dev.py` (setup / up / down / status / logs / test / demo / ci, cross-platform) and `.vscode/` launch, task and settings files. Registry runs in its documented local HTTP profile; Orchestration gets a generated admin password. | R-NFR-3 | — | ☑️ | `OpenAN: all services` launches the stack in VS Code; `dev.py ci` passes |
| PLT-9 | Mock electricity price API (`mocks/price_api`): UC1 power-band tariff and UC2 time-of-use prices, optional API key, error and slow modes. | R-PRC-1, R-PRC-4, R-PRC-5 | — | ☑️ | Tests pass; used by the demo |
| PLT-6 | Bootstrap secrets and TLS for the dev stack (self-signed, RSA ≥ 3072), using the upstream `generate_selfsign_cert.py`. | R-NFR-1, R-NFR-2 | PLT-2 | ✅ | Services talk over TLS in dev |
| PLT-7 | Final port allocation and topology; fill in AgentCard `agent_id` and URLs. | R-REG-5 | **O-4** | 🔴 | Topology doc approved; config updated |
| PLT-10 🆕 | ORCH service credential by configuration: set `external.auth.mode` to `bearer` (`ORCH_API_TOKEN`, ≥ 32 bytes) in the dev stack and `mtls` in production; give OSS the matching secret. | R-ORC-1, R-NFR-2 | PLT-2 | ✅ | Dev Orchestration rejects calls without the token; OSS calls succeed with it |
| PLT-11 🆕 | Network policy in `deploy/`: ORCH reachable only from OSS and ops hosts, Energy Agent only from ORCH, MAE Negotiation-T only from the Energy Agent and Task-T only from ORCH, Registry only from ORCH, Energy Agent and MAE. | R-SEC-8 | PLT-2, PLT-7 | 🔴 O-4 | Policy applied; a probe from another host is refused |
| PLT-12 🆕 | Registry production configuration checklist: HTTPS + `verify_client`, `owner.isolation.enabled=true`, `startup.strict.identity=true`, signed AgentCards with a `jku` allowlist, CRL. | R-NFR-8, R-REG-6 | PLT-6 | 🟡 O-22 | Checklist in `deploy/`; a production-profile Registry starts with it |

---

## 3. OSS (M1, M3)

| ID | Item | Covers | Depends on | Status | Done when |
|---|---|---|---|---|---|
| OSS-1 | Service scaffold (Python/FastAPI suggested, to match upstream): config loading, health endpoint, structured logs with `trace_id`. | R-NFR-4, R-NFR-5 | PLT-1 | ✅ | Service starts; `/health` returns 200 |
| OSS-2 | Data model and store for `EnergySavingIntentRequest` and its status values (LLD §12). | R-INT-1, R-RPT-1 | OSS-1 | ✅ | CRUD unit tests pass |
| OSS-3 | Authentication and RBAC: `AuthManager` (deployment SSO/OIDC or session) returning `401`, then the three permissions, checked once at the boundary, before any LLM call. Both denials are audited (`auth_failure`, `permission_denied`). **Done:** `oss/security.py` (`AuthManager`, roles) and `oss/app.py`; the token table is the dev stand-in for SSO/OIDC. | R-SEC-1, R-SEC-2, R-INT-2, R-AUD-5 | OSS-1, OSS-4 | ☑️ (reference) | Tests: 401 and 403 are audited, and the LLM is never called |
| OSS-4 | Audit module per LLD v10.4 §11.3: the thirteen event types, the record schema, hash chain, insert-only database role, spool and retry for non-blocking events, fail-closed `workflow_started`, admin-only read API that audits `audit_read`, and a verifier job. Start from `mocks/common/audit.py`. **Done:** `oss/audit.py` (`AuditService`): event set, fail-closed `workflow_started` and `audit_read`, spool with replay and stuck alert, terminal-once, watcher idempotency. The insert-only database role waits on the real store; retention waits on O-24. | R-AUD-1 … R-AUD-9 | OSS-1 | ☑️ (reference) | Tests: duplicate terminal events are ignored; non-admin read is 403; an edited record is reported; a failed `workflow_started` write blocks submit |
| OSS-20 🆕 | Audit export in the upstream six-element shape (time, client IP, user name, operation name, operation target, result) so Registry, Orchestration and OSS logs share one parser. **Done:** `oss.audit.to_upstream`, also served by `GET /audit-logs?format=upstream`. | R-AUD-10 | OSS-4 | ☑️ | Golden test of the export against an upstream audit line |
| OSS-5 | LLM classifier adapter behind an interface (`OSS_INTENT_LLM_*`), plus a deterministic stub for tests. | R-INT-4, R-LLM-1 | OSS-1 | ✅ | Classifier is swappable by config; stub used in CI |
| OSS-6 | `POST /intents`: permission → audit `intent_received` → classify → `handled:false` or validate. | R-INT-1, R-INT-3, R-INT-5 | OSS-2 … OSS-5 | ✅ | API tests for each branch |
| OSS-7 | Parameter validation: required `region`; derive `operation_type` and `task_description`; map to Task-T slots (LLD §12). | R-INT-6, R-INT-7 | OSS-6 | ✅ | Table-driven tests for complete / incomplete inputs |
| OSS-8 | `POST /intents/{id}/supplement`: merge by `session_id`, audit `parameter_supplement`, re-validate. | R-INT-8 | OSS-7 | ✅ | Tests: supplement completes the intent |
| OSS-14 | Intent schedule model: `{start_hour, end_hour, saving_mode, experience_target}` entries with enumerations, midnight wrap, and full 24-hour coverage check; seeded with the UC1 example schedule as a test fixture. | R-INT-10 … R-INT-12 | OSS-2 | ✅ | Table-driven tests: UC1 schedule passes; overlaps and gaps are rejected |
| OSS-15 | Classifier and slot extraction produce the schedule from free text (e.g. "maximize saving overnight, keep 10 Mbps in the morning"); the supplement flow asks for missing periods. | R-INT-4, R-INT-10 | OSS-5, OSS-14 | 🟡 O-2 | Extraction tests on example phrasings |
| OSS-9 | `GET /intents/{id}/status` with the LLD §11.8 response shape, built from OSS's own store and returned only to the intent's owner or an admin. **Done:** ownership check in `oss/app.py`; another user's intent reads as `404`. The response is built from the in-memory store until OSS-2. | R-RPT-1, R-SEC-4 | OSS-2 | ☑️ (reference) | API tests against fixtures, including another user's intent (403 or 404) |
| OSS-10 | Orchestration client: service credential (`OSS_ORCH_AUTH_MODE` = `bearer` or `mtls`, secret by reference), `POST /api/v1/orchestrate/execute`, audit `workflow_started` first (fail closed), return `202`; map ORCH `503` to `orchestration_busy` with `Retry-After`. | R-ORC-1 … R-ORC-3, R-ORC-7 | OSS-6, PLT-10 | ✅ 🆕 | Works against the dev Orchestration Center in `bearer` mode |
| OSS-11 | SSE watcher pool: hold each stream open to a terminal event; parse `data:` JSON events (F-5), map them to workflow states (LLD §5.1), treat `complete` / `error` / `cancelled` as terminal (F-6), apply the idle and execution timeouts, be idempotent on `(execution_id, type, timestamp)`, write `negotiation_summary` and terminal audit events once; a drop or missing terminal event ends `orchestration_stream_lost` and audits `workflow_stream_lost`. | R-ORC-4, R-ORC-6, R-WF-6, R-AUD-2, R-AUD-3 | OSS-4, OSS-10 | ✅ 🆕 | Tests with recorded streams, including disconnects and a missing terminal event |
| OSS-12 | Execution link: after the stream ends, match `GET /api/v1/executions` by `psop_id` and start time, store the `ExecutionLink`, audit `execution_linked`. No polling during a run (F-7). | R-ORC-5 | OSS-11 | 🟡 O-23 🆕 | Test: overlapping runs link to the right records |
| OSS-16 🆕 | Region scope: `user → regions` mapping, checked after extraction and before submit; `403` and `permission_denied` on failure. **Done:** `Principal.may_target`, checked in `oss/app.py` after validation and before `workflow_started`. | R-SEC-3, R-INT-14 | OSS-3, OSS-7 | ☑️ | Tests: an out-of-scope region is refused and audited, and nothing is submitted |
| OSS-17 🆕 | Input handling: `raw_text` length cap, schema validation of the classifier output, and only validated structured fields forwarded (never `raw_text`). **Done:** `check_raw_text`, `validate_classifier_output`, `FORWARDED_FIELDS` in `oss/`. | R-SEC-5 | OSS-5, OSS-6 | ☑️ | Tests: oversize text is refused; extra classifier fields are rejected; the submit body has no `raw_text` |
| OSS-18 🆕 | Per-user rate limits on submit and supplement. **Done:** `oss.security.RateLimiter`; `429` with `Retry-After`. | R-SEC-6 | OSS-6 | ☑️ | Test: the limit returns `429` |
| OSS-19 🆕 | Secrets: all keys and the ORCH credential from env or a secret manager, redacted from logs and audit; rotation owner recorded per secret. **Done:** `resolve_secret` (`env:` / `file:` references only) and `SecretRedactingFilter`. Rotation owners still to record per secret in the deployment notes. | R-SEC-7 | OSS-1 | ☑️ | Test: no configured secret appears in captured logs or audit |
| OSS-13 | Idempotent submission: an idempotency key on `POST /intents` so retries return the same intent and start no second workflow. | R-NFR-6 | OSS-10 | 🟡 O-8 | Test: duplicate submits create one workflow |

---

## 4. Energy Agent (M2, M5)

| ID | Item | Covers | Depends on | Status | Done when |
|---|---|---|---|---|---|
| EA-1 | Agent scaffold on `a2a-t-sdk` (A2A-T server, `A2AT_LLM_*` config, OpenTelemetry on). | R-LLM-2, R-NFR-4 | PLT-5 | ✅ | Agent starts and serves its AgentCard |
| EA-2 | AgentCard per LLD v10.2 §9 (two skills, mTLS scheme), with placeholder `agent_id` and URL. | R-REG-1 | EA-1 | ✅ | Card validates against the SDK schema |
| EA-3 | Capability registrar: register, publish (when approval is on), heartbeat; `layer` from `ENERGY_AGENT_REGISTRY_LAYER`; registry authentication from configuration. | R-REG-2 … R-REG-4, R-REG-6 | EA-2, PLT-2 | 🟡 O-13, O-22 | Agent found by `agent-cards/semantic-query` on the dev Registry |
| EA-4 | Price skill with a `PriceAdapter` interface and a **stub adapter** (fixed or fixture price tables). | R-PRC-1, R-PRC-2, R-PRC-4 | EA-1 | ✅ | Skill returns a valid `price_table`; failure maps to `price_api_unavailable` |
| EA-10 | Power-band tariff model and adapter (`{band_no, min_kw, max_kw, charge, currency, billing_period}`), with the UC1 tariff as the stub data; the LLD time-of-use `price_table` is kept as a second type for UC2. | R-PRC-5 | EA-4 | ✅ (stub) | Skill returns the UC1 band table from the stub |
| EA-11 | Build the combined A2A-T intent from the schedule and tariff; map them onto Task-T slots per the answer to O-28 (provisionally: schedule in `task_target`, tariff in `task_context`). | R-PRC-6 | EA-10, OSS-14 | 🔴 O-28 | Golden test of the generated Task-T message |
| EA-5 | Negotiation engine: build the opening `propose`, handle both MAE replies with `accept-reject` Accept (feasible → `AGREED`, infeasible → `CLOSED_INFEASIBLE`), `abort` for anything else; round limit and per-round timeout; record `NegotiationRound`. **Mock done:** the mock Energy Agent and mock MAE close infeasible verdicts as `closed_infeasible`. | R-NEG-1 … R-NEG-4, R-NEG-6 | EA-1, EA-4 | ✅ (vs. mock) | Golden tests based on `a2a-t-sdk-python/tests/resources/negotiation-cases` pass |
| EA-6 | Target-relaxation switch (`ENERGY_AGENT_ALLOW_TARGET_RELAXATION`, default off); counter-proposals go back to the user. | R-NEG-5 | EA-5 | 🟡 O-14 | Tests for both settings |
| EA-7 | Mock MAE (`mocks/mae`): A2A HTTP+JSON server on `a2a-sdk`, Task-T `ran-energy-saving/v1` and Negotiation-T feasibility, deterministic UC1 planning, registers in the Registry Center. Scenarios: feasible, infeasible-with-proposal, task rejected, execution failure. | — | EA-5 | ☑️ | 34 tests pass; `scripts/demo_uc1.py` runs feasible and infeasible paths end to end |
| EA-8 | Production price adapter against the real API (auth, timezone, rate limits). | R-PRC-3 | **O-1** | 🔴 | Contract tests against the provider sandbox |
| EA-9 | Point negotiation at the real MAE (`MAE_AGENT_ID`, `MAE_AGENT_ENDPOINT`), with the agreed trust model. | R-NEG-1, R-NEG-2, R-NFR-7, R-EAS-6 | **O-3**, O-7 | 🔴 | Feasibility round succeeds against MAE |
| EA-12 🆕 | Policy guard before `agreed`: region allowlist, experience floor, saving-target limit (`ENERGY_AGENT_POLICY_*`), optional time windows; violation fails `policy_violation` without contacting MAE. Time windows done too (`ENERGY_AGENT_POLICY_SAVING_WINDOWS`). | R-EAS-2 | EA-5 | ☑️ (mock) | Tests: each rule refuses; a refused request sends nothing to MAE |
| EA-13 🆕 | Local audit log: hash-chained record per policy decision and negotiation round (trace id, round, templates, outcome, price-table and MAE-card digests, caller) at `ENERGY_AGENT_AUDIT_LOG_PATH`. **Mock done:** `dev.py ci` verifies the chain after the demos. | R-EAS-3, R-EAS-7, R-NEG-6 | EA-5 | ☑️ (mock) | Tests: records chain and verify; an edit is detected |
| EA-14 🆕 | Caller authentication: accept A2A-T only from the ORCH identity (`ENERGY_AGENT_ALLOWED_CALLERS`, mTLS peer or bearer), and record the verified caller in the audit log. **Mock done:** `mocks/energy_agent/caller_auth.py` (bearer from a secret reference, source-IP range, optional mTLS at the TLS layer); refusals audited as `caller_rejected`, the verified caller named in every record. The dev stack allows only `127.0.0.1`. O-25 still decides which mechanism production uses. | R-EAS-1 | EA-1 | ☑️ (mock), 🟡 O-25 | Test: a request without the ORCH identity is refused |

---

## 5. Orchestration workflow (M3, M5)

| ID | Item | Covers | Depends on | Status | Done when |
|---|---|---|---|---|---|
| ORC-1 | **Decide the submission flow** using findings F-1 … F-3. **Decided in LLD v10.4 (O-20):** `POST /api/v1/orchestrate/execute`, held open by the OSS watcher. | R-ORC-2 | — | ☑️ | Decision recorded in requirements §7; O-20 closed |
| ORC-2 | Confirm the SSE guarantees in F-5 and F-6. **LLD v10.4 closes O-19** (FIFO per stream, no resume); still to correct in the LLD: the server sends no `close` event and `cancelled` is terminal (F-6). Also ask whether a dropped stream cancels the run (O-26). | R-WF-6, R-AUD-3, R-ORC-6 | — | 🟡 O-26 | LLD corrected; O-26 answered |
| ORC-3 | Author the energy-saving PSOP: `PriceNode → NegotiationNode → gateway → DispatchNode → MonitorNode → terminal`, bound to concrete agent names. | R-WF-1, R-WF-2 | EA-3 | ✅ | PSOP saved and retrievable via `/orchestrate/psop/{id}` |
| ORC-4 | ControlPoint hooks: `on_task` for price and dispatch; `on_route` for the feasible / infeasible gateway; `on_negotiation` for mid-flight negotiation (against EA-7's outcome shape). | R-WF-3 | ORC-3, EA-5 | ✅ (vs. mock) | Unit tests per hook |
| ORC-5 | Sandbox run with `StubAgentRuntime` covering `COMPLETED`, `REJECTED`, and each `FAILED` path in LLD §5.1, including `policy_violation`. | R-WF-7 | ORC-3, ORC-4 | ✅ | Sandbox tests for every terminal state |
| ORC-6 | MonitorNode with a **stub artifact parser** (pass-through JSON). | R-WF-5 | ORC-3 | ✅ | Artifacts reach the OSS status response |
| ORC-7 | DispatchNode sending Task-T `ran-energy-saving/v1` to the Mock MAE, with an optional Authorization-T hook (off by default). | R-WF-4 | ORC-3, EA-7 | ✅ (vs. mock) | Dispatch reaches the mock with correct slots |
| ORC-8 | Real artifact parser (`TaskPlan`, `CellSelection`, `EnergySavingActivated`, `IntentReport`). | R-WF-5 | **O-11** | 🔴 | Parser tests against MAE-provided samples |
| ORC-9 | Authorization-T policy check before dispatch, if required, built into the workflow definition (no ORCH code change). | R-WF-4 | **O-12** | 🔴 | Dispatch is refused without authorization |

---

## 6. Front-end (M4, M5)

| ID | Item | Covers | Depends on | Status | Done when |
|---|---|---|---|---|---|
| FE-1 | App scaffold and OSS API client (auth, error handling for 403 / 504). | — | OSS-6 | ✅ | App builds and talks to OSS in dev |
| FE-2 | Intent entry screen, including the `handled:false` message. | R-INT-1, R-INT-5 | FE-1 | ✅ | Manual and component tests |
| FE-3 | Supplement form, driven by the missing-field list. | R-INT-7, R-INT-8 | FE-2 | ✅ | Completes an intent end to end |
| FE-4 | Status and report view: state, counter-proposal, final report, failure reason; artifact timeline with placeholder rendering. | R-RPT-1 … R-RPT-3 | FE-1, OSS-9 | ✅ (placeholder) | Renders every terminal state from M3 |
| FE-5 | Real artifact timeline rendering. | R-RPT-3 | **O-11**, ORC-8 | 🔴 | Renders MAE sample artifacts |
| FE-6 | Schedule editor: a 24-hour period table (mode and experience target per period), prefilled from the extracted intent. | R-INT-10, R-INT-11 | FE-2, OSS-14 | ✅ | Edits round-trip through OSS validation |
| FE-7 | UC1 report: per-site predicted band, site classification, migration actions, predicted cost before and after. | R-RPT-4 | FE-4, ORC-8 | 🔴 O-11 | Renders from MAE sample artifacts |

---

## 7. GA hardening (M6)

| ID | Item | Closes |
|---|---|---|
| GA-1 | Evaluate the production classifier model; record accuracy and threshold. | O-2 |
| GA-2 | Audit granularity sign-off with compliance. | O-5 |
| GA-3 | EA ↔ MAE trust model (mTLS, key rotation) implemented and reviewed. | O-7 |
| GA-4 | Idempotent submission (OSS-13) verified under retry load. | O-8 |
| GA-5 | Registry `layer` value agreed and configured. | O-13 |
| GA-6 | Decision D-1 on target relaxation recorded; EA-6 default confirmed. | O-14 |
| GA-7 | SDK version pin and template hosting agreed; PLT-5 updated. | O-15 |
| GA-8 | Security review against the LLD v10.4 §17 control matrix: TLS settings, fail-closed startup, secrets handling, RBAC, region scope and ownership tests, network policy. | R-NFR-1, R-NFR-2, R-SEC-3 … R-SEC-8 |
| GA-9 🆕 | Audit retention and archive target configured. | O-24 |
| GA-10 🆕 | Audit store created with an insert-only role; hash-chain verifier job scheduled and alerting. | R-AUD-7, R-NFR-9 |
| GA-11 🆕 | Energy Agent caller authentication in place (EA-14) and EA ↔ MAE mutual authentication reviewed. | O-25, O-7 |
| GA-12 🆕 | Execution-id resolution (OSS-12) verified with overlapping runs. | O-23 |

---

## 8. Feature requests for upstream (not applied here)

LLD v10.4 keeps Orchestration Center and Registry Center code unchanged, so
these are **not** patched in `upstream/`. They are the residual risks of LLD
§17, to raise with the upstream projects as feature requests; until then the
OSS-side controls listed in the "Why" column cover them.

| ID | Repo | Change | Why | Priority |
|---|---|---|---|---|
| UP-1 | orchestration-center | Return the `execution_id` in the first SSE event (or a response header) of `POST /orchestrate/execute`. | Removes the `psop_id` + start-time match in OSS-12 (O-23). | High |
| UP-2 | orchestration-center | Add SSE `id:` sequence numbers and `Last-Event-ID` resume. | A dropped stream could resume instead of ending `orchestration_stream_lost` (OSS-11). | Medium |
| UP-6 🆕 | orchestration-center | Per-user ownership or roles on executions (`/api/v1/executions`). | Today mitigated by network isolation and OSS-only access (R-SEC-8). | Medium |
| UP-3 | orchestration-center | Make `GET /orchestrate/execute/{psop_id}` run the stored PSOP itself, not just its name as an intent (F-3), or document the behaviour. | Predictable execution of a pinned workflow. | Medium |
| UP-5 | workflow-engine-sdk-python | `orchestration-center` pins `workflow-exec-engine>=0.0.9,<0.1` from PyPI, while the vendored SDK is 0.1.0; align the pin so PLT-5 can use the vendored copy. | Single SDK version across the stack. | Medium |
| UP-4 | orchestration-center, registry-center | Accept and propagate a caller `trace_id` (OpenTelemetry). | End-to-end tracing (R-NFR-4); today joined through OSS and Energy Agent audit. | Low |

---

## 9. Suggested order of work

1. **Week 1:** PLT-1 … PLT-4, OSS-1 … OSS-5, EA-1, EA-2. In parallel, raise
   ORC-1 and ORC-2 with the Orchestration Center maintainers (with findings
   F-1 … F-15); chase O-1, O-3, O-11, O-12 and O-25 per LLD §18; and take O-27
   (tariff semantics) to MTN and O-28 (schedule and tariff in Task-T) to the
   MAE team, since both change the intent model.
2. **Week 2:** OSS-6 … OSS-9, OSS-14, OSS-16 … OSS-20, EA-3 … EA-5, EA-7, EA-10, ORC-3, PLT-10.
3. **Week 3:** ORC-4 … ORC-7, OSS-10 … OSS-12, FE-1 … FE-3, FE-6.
4. **Week 4:** FE-4, a full sandbox end-to-end run (M3), then the M5 items as
   each P0 open item closes.
