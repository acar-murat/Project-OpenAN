# OpenAN Energy-Saving Function — Development Backlog

The change and development list for implementing
[requirements.md](requirements.md) (LLD US202610010001 v10.2).

**How to read it**

- Work items have an ID (`<area>-<n>`), the requirements they cover, what they
  depend on, and a definition of done.
- **Status:** ✅ Ready (start now) · 🟡 Ready, finish before GA · 🔴 Blocked on an open item.
- Blocked items are designed so that a stub lets development continue; only
  the item that swaps the stub for the real integration is blocked.
- Changes to `upstream/` are kept small and listed in §8, so they can be
  offered back upstream or re-applied after a `git subtree pull`.

---

## 1. Milestones

| Milestone | Goal | Items | Gate |
|---|---|---|---|
| **M0 Foundation** | Repo layout, CI, dev stack running locally | PLT-1 … PLT-5 | Registry + Orchestration start with `docker compose up` |
| **M1 OSS core** | Intents accepted, validated, audited, permission-checked | OSS-1 … OSS-9 | OSS API tests pass with the LLM stubbed |
| **M2 Energy Agent (stubbed)** | Agent registered and discoverable; price skill and negotiation work against stubs | EA-1 … EA-7 | Agent appears in a semantic query; negotiation runs against Mock MAE |
| **M3 Sandbox end-to-end** | Full workflow runs in the sandbox with stub agents; OSS consumes SSE | ORC-1 … ORC-7, OSS-10 … OSS-12 | Intent → `COMPLETED` / `REJECTED` / `FAILED` end to end with stubs |
| **M4 Front-end** | Submit, supplement, status and report screens | FE-1 … FE-4 | Manual demo against M3 |
| **M5 Live integration** | Real price API and MAE | EA-8, EA-9, ORC-8, ORC-9, FE-5 | **Needs O-1, O-3, O-11, O-12** |
| **M6 GA hardening** | P1 items closed, security review, deployment | GA-1 … GA-8 | All 🟡 items closed |

---

## 2. Platform and repository (M0)

| ID | Item | Covers | Depends on | Status | Done when |
|---|---|---|---|---|---|
| PLT-1 | Create the repo layout: `services/oss`, `services/energy-agent`, `workflows/energy-saving`, `frontend`, `deploy`, `tests/e2e`. | — | — | ✅ | Folders exist, each with a README and an empty test suite |
| PLT-2 | Add `deploy/docker-compose.dev.yml` that starts Registry (5000) and Orchestration (5001) from `upstream/`, plus OSS and the Energy Agent. Ports come from env vars, defaulting to F-8. | R-NFR-3, R-NFR-5 | PLT-1 | ✅ | `docker compose up` brings all services up healthy |
| PLT-3 | Add `.env.example` with every variable in LLD §14, each blocked value marked with its O-item. | R-NFR-5 | PLT-1 | ✅ | File committed; services fail fast on a missing required variable |
| PLT-4 | Add CI (GitHub Actions): lint, type check and unit tests for `services/*`; the upstream test suites run on change under `upstream/`. | — | PLT-1 | ✅ | CI green on `main` |
| PLT-5 | Pin `a2a-t-sdk` 1.1.0 and `workflow-exec-engine` from the vendored subtrees (path dependencies). | O-15 | PLT-1 | 🟡 | Services install the SDKs from `upstream/` |
| PLT-6 | Bootstrap secrets and TLS for the dev stack (self-signed, RSA ≥ 3072), using the upstream `generate_selfsign_cert.py`. | R-NFR-1, R-NFR-2 | PLT-2 | ✅ | Services talk over TLS in dev |
| PLT-7 | Final port allocation and topology; fill in AgentCard `agent_id` and URLs. | R-REG-5 | **O-4** | 🔴 | Topology doc approved; config updated |

---

## 3. OSS (M1, M3)

| ID | Item | Covers | Depends on | Status | Done when |
|---|---|---|---|---|---|
| OSS-1 | Service scaffold (Python/FastAPI suggested, to match upstream): config loading, health endpoint, structured logs with `trace_id`. | R-NFR-4, R-NFR-5 | PLT-1 | ✅ | Service starts; `/health` returns 200 |
| OSS-2 | Data model and store for `EnergySavingIntentRequest` and its status values (LLD §11). | R-INT-1, R-RPT-1 | OSS-1 | ✅ | CRUD unit tests pass |
| OSS-3 | RBAC: the three permissions, checked once at the boundary, before any LLM call. | R-SEC-1, R-SEC-2, R-INT-2 | OSS-1 | ✅ | Tests: 403 without permission, and the LLM is never called |
| OSS-4 | Audit module: event store, the five event types, local monotonic sequence, write-once terminal events, admin-only read API. | R-AUD-1, R-AUD-2, R-AUD-4 | OSS-1 | ✅ | Tests: duplicate terminal events are ignored; non-admin read is 403 |
| OSS-5 | LLM classifier adapter behind an interface (`OSS_INTENT_LLM_*`), plus a deterministic stub for tests. | R-INT-4, R-LLM-1 | OSS-1 | ✅ | Classifier is swappable by config; stub used in CI |
| OSS-6 | `POST /intents`: permission → audit `intent_received` → classify → `handled:false` or validate. | R-INT-1, R-INT-3, R-INT-5 | OSS-2 … OSS-5 | ✅ | API tests for each branch |
| OSS-7 | Parameter validation: required `region`; derive `operation_type` and `task_description`; map to Task-T slots (LLD §11). | R-INT-6, R-INT-7 | OSS-6 | ✅ | Table-driven tests for complete / incomplete inputs |
| OSS-8 | `POST /intents/{id}/supplement`: merge by `session_id`, audit `parameter_supplement`, re-validate. | R-INT-8 | OSS-7 | ✅ | Tests: supplement completes the intent |
| OSS-9 | `GET /intents/{id}/status` with the LLD §7.8 response shape. | R-RPT-1 | OSS-2 | ✅ | API test against fixtures |
| OSS-10 | Orchestration client: login, token refresh, **config-driven submit path** (`OSS_ORCH_SUBMIT_PATH`), audit `workflow_started`, return `202`. | R-ORC-1 … R-ORC-3 | OSS-6, ORC-1 | 🔴 O-20 (path) | Works against the dev Orchestration Center; path is changeable by config only |
| OSS-11 | SSE worker pool: parse `data:` JSON events (F-5), map them to workflow states (LLD §6.3), treat `complete` / `error` / `cancelled` as terminal (F-6), apply the timeout, write terminal audit events once. | R-ORC-4, R-WF-6, R-AUD-2 | OSS-4, OSS-10 | 🔴 O-19 (confirm) | Tests with recorded streams, including disconnects and a missing terminal event |
| OSS-12 | Reconciliation: after a disconnect or timeout, poll `GET /api/v1/executions/{id}` and settle the final state (F-7); buffer out-of-order events. | R-ORC-5, R-AUD-3 | OSS-11 | 🔴 O-19 (confirm) | Test: a dropped stream still ends in the correct terminal state |
| OSS-13 | Idempotent submission: an idempotency key on `POST /intents` so retries return the same intent and start no second workflow. | R-NFR-6 | OSS-10 | 🟡 O-8 | Test: duplicate submits create one workflow |

---

## 4. Energy Agent (M2, M5)

| ID | Item | Covers | Depends on | Status | Done when |
|---|---|---|---|---|---|
| EA-1 | Agent scaffold on `a2a-t-sdk` (A2A-T server, `A2AT_LLM_*` config, OpenTelemetry on). | R-LLM-2, R-NFR-4 | PLT-5 | ✅ | Agent starts and serves its AgentCard |
| EA-2 | AgentCard per LLD §9 (two skills, mTLS scheme), with placeholder `agent_id` and URL. | R-REG-1 | EA-1 | ✅ | Card validates against the SDK schema |
| EA-3 | Capability registrar: register, publish (when approval is on), heartbeat; `layer` from `ENERGY_AGENT_REGISTRY_LAYER`. | R-REG-2 … R-REG-4 | EA-2, PLT-2 | 🟡 O-13 | Agent found by `agent-cards/semantic-query` on the dev Registry |
| EA-4 | Price skill with a `PriceAdapter` interface and a **stub adapter** (fixed or fixture price tables). | R-PRC-1, R-PRC-2, R-PRC-4 | EA-1 | ✅ | Skill returns a valid `price_table`; failure maps to `price_api_unavailable` |
| EA-5 | Negotiation engine: build the opening `propose`, handle both MAE replies, `accept-reject`, `abort`; round limit and per-round timeout; record `NegotiationRound`. | R-NEG-1 … R-NEG-4, R-NEG-6 | EA-1, EA-4 | ✅ (vs. mock) | Golden tests based on `a2a-t-sdk-python/tests/resources/negotiation-cases` pass |
| EA-6 | Target-relaxation switch (`ENERGY_AGENT_ALLOW_TARGET_RELAXATION`, default off); counter-proposals go back to the user. | R-NEG-5 | EA-5 | 🟡 O-14 | Tests for both settings |
| EA-7 | Mock MAE for development, based on the SDK sample server in `upstream/a2a-t-sdk-python/a2a-t-sample/ran-energy-saving`; returns feasible, infeasible-with-proposal, and error cases. | — | EA-5 | ✅ | Mock drives EA-5 tests and the sandbox |
| EA-8 | Production price adapter against the real API (auth, timezone, rate limits). | R-PRC-3 | **O-1** | 🔴 | Contract tests against the provider sandbox |
| EA-9 | Point negotiation at the real MAE (`MAE_AGENT_ID`, `MAE_AGENT_ENDPOINT`), with the agreed trust model. | R-NEG-1, R-NEG-2, R-NFR-7 | **O-3**, O-7 | 🔴 | Feasibility round succeeds against MAE |

---

## 5. Orchestration workflow (M3, M5)

| ID | Item | Covers | Depends on | Status | Done when |
|---|---|---|---|---|---|
| ORC-1 | **Decide the submission flow** using findings F-1 … F-3 (recommendation: `POST /orchestrate/execute`, consumed by the OSS worker); confirm with maintainers and set `OSS_ORCH_SUBMIT_PATH`. | R-ORC-2 | — | 🔴 O-20 | Decision recorded in requirements §7; O-20 closed |
| ORC-2 | Confirm the SSE guarantees in F-5 and F-6 with maintainers (FIFO per stream, no resume, `cancelled` terminal, no `close` event). | R-WF-6, R-AUD-3 | — | 🔴 O-19 | O-19 closed, or upstream change UP-2 agreed |
| ORC-3 | Author the energy-saving PSOP: `PriceNode → NegotiationNode → gateway → DispatchNode → MonitorNode → terminal`, bound to concrete agent names. | R-WF-1, R-WF-2 | EA-3 | ✅ | PSOP saved and retrievable via `/orchestrate/psop/{id}` |
| ORC-4 | ControlPoint hooks: `on_task` for price and dispatch; `on_route` for the feasible / infeasible gateway; `on_negotiation` for mid-flight negotiation (against EA-7's outcome shape). | R-WF-3 | ORC-3, EA-5 | ✅ (vs. mock) | Unit tests per hook |
| ORC-5 | Sandbox run with `StubAgentRuntime` covering `COMPLETED`, `REJECTED`, and each `FAILED` path in LLD §6.1. | R-WF-7 | ORC-3, ORC-4 | ✅ | Sandbox tests for every terminal state |
| ORC-6 | MonitorNode with a **stub artifact parser** (pass-through JSON). | R-WF-5 | ORC-3 | ✅ | Artifacts reach the OSS status response |
| ORC-7 | DispatchNode sending Task-T `ran-energy-saving/v1` to the Mock MAE, with an optional Authorization-T hook (off by default). | R-WF-4 | ORC-3, EA-7 | ✅ (vs. mock) | Dispatch reaches the mock with correct slots |
| ORC-8 | Real artifact parser (`TaskPlan`, `CellSelection`, `EnergySavingActivated`, `IntentReport`). | R-WF-5 | **O-11** | 🔴 | Parser tests against MAE-provided samples |
| ORC-9 | Authorization-T policy check before dispatch, if required. | R-WF-4 | **O-12** | 🔴 | Dispatch is refused without authorization |

---

## 6. Front-end (M4, M5)

| ID | Item | Covers | Depends on | Status | Done when |
|---|---|---|---|---|---|
| FE-1 | App scaffold and OSS API client (auth, error handling for 403 / 504). | — | OSS-6 | ✅ | App builds and talks to OSS in dev |
| FE-2 | Intent entry screen, including the `handled:false` message. | R-INT-1, R-INT-5 | FE-1 | ✅ | Manual and component tests |
| FE-3 | Supplement form, driven by the missing-field list. | R-INT-7, R-INT-8 | FE-2 | ✅ | Completes an intent end to end |
| FE-4 | Status and report view: state, counter-proposal, final report, failure reason; artifact timeline with placeholder rendering. | R-RPT-1 … R-RPT-3 | FE-1, OSS-9 | ✅ (placeholder) | Renders every terminal state from M3 |
| FE-5 | Real artifact timeline rendering. | R-RPT-3 | **O-11**, ORC-8 | 🔴 | Renders MAE sample artifacts |

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
| GA-8 | Security review: TLS settings, fail-closed startup, secrets handling, RBAC tests. | R-NFR-1, R-NFR-2 |

---

## 8. Proposed upstream changes

Changes to code under `upstream/`. Each should be small, kept in its own
commit, and offered upstream where it is generally useful.

| ID | Repo | Change | Why | Priority |
|---|---|---|---|---|
| UP-1 | orchestration-center | Return the `execution_id` in the first SSE event (or a response header) of `POST /orchestrate/execute`. | Lets OSS reconcile through `/executions/{id}` after a disconnect (OSS-12). | High |
| UP-2 | orchestration-center | Add SSE `id:` sequence numbers and `Last-Event-ID` resume. | Closes most of O-19; removes the need for client-side buffering. | Medium |
| UP-3 | orchestration-center | Make `GET /orchestrate/execute/{psop_id}` run the stored PSOP itself, not just its name as an intent (F-3), or document the behaviour. | Predictable execution of a pinned workflow. | Medium |
| UP-4 | orchestration-center | Accept and propagate a caller `trace_id`. | End-to-end tracing (R-NFR-4). | Low |

---

## 9. Suggested order of work

1. **Week 1:** PLT-1 … PLT-4, OSS-1 … OSS-5, EA-1, EA-2. In parallel, raise
   ORC-1 and ORC-2 with the Orchestration Center maintainers (with findings
   F-1 … F-7), and chase O-1, O-3, O-11 and O-12 per LLD §18.
2. **Week 2:** OSS-6 … OSS-9, EA-3 … EA-5, EA-7, ORC-3.
3. **Week 3:** ORC-4 … ORC-7, OSS-10 … OSS-12 (on the provisional path), FE-1 … FE-3.
4. **Week 4:** FE-4, a full sandbox end-to-end run (M3), then the M5 items as
   each P0 open item closes.
