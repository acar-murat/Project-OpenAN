# Next phase: DFX, LLM choice, robustness and security

Status of the basic UC1 energy-saving feature against LLD v10.4, and a plan for
the next phase. It counts `main` plus the four open PRs as of 2026-10-19:

- #5 docs for OSS, Energy Agent and the APIs
- #6 OSS security and audit controls, Energy Agent caller authentication
- #7 richer mock MAE and Energy Agent outcomes, 41 documented test cases
- #8 LLM use cases and the intent wording evaluation

Nothing here changes `upstream/orchestration-center` or `upstream/registry-center`
(LLD §0.0). Item IDs are new (`BF-`, `DFX-`, `LLM-`, `ROB-`, `SEC-`) and point
to the backlog items they extend.

---

## 1. Is the basic feature complete?

**Mostly, but not end to end through OSS.** UC1 runs from intent to report
through the real Orchestration Center and Registry Center with mock MAE, price
API and LLM. OSS, the front door of the LLD, is built as a library with stubs
but is not yet wired to the Orchestration Center.

| LLD area | State (main + open PRs) | Gap that blocks "basic feature done" |
|---|---|---|
| Energy Agent workflow (§11.4–§11.6) | Done vs. mocks: tariff, policy guard, bounded negotiation, dispatch, report (#7) | Region falls back to Accra Central when none is found (#8 finding) |
| Mock MAE (§11.7) | Done: full, partial, none feasibility; multi-round; task failure modes; per-cell results and KPIs (#7) | none |
| OSS intent API (§11.1, §11.8) | Submit, supplement, status, audit read with the fixed control order (#6) | Classifier and extractor are stubs; the #8 prompts are not plugged in (OSS-5, OSS-15) |
| OSS → ORCH (§11.1 steps 7–9) | Stub submitter (#6) | **No ORCH client, no SSE watcher, no execution link** (OSS-10, OSS-11, OSS-12) |
| OSS store (§12) | In memory (#6) | No persistent store, no insert-only audit role (OSS-2, GA-10) |
| Idempotent submit | Not started | OSS-13 (O-8) |
| Front-end | The upstream Execution Center drives UC1 (#3) | Our own screens not started (FE-1 … FE-4, FE-6) |
| Real price API, real MAE, artifact parser | Mocks only | Blocked on O-1, O-3, O-11, O-12, O-25, O-27, O-28 (M5) |

### Phase 0: close the basic feature (recommended first)

| ID | Work | Extends |
|---|---|---|
| BF-1 | Merge #5–#8 (resolve the overlaps in `control_point.py`, `dev.py`, `ci.yml` and the backlog) | — |
| BF-2 | OSS ORCH client (bearer in dev) and SSE watcher to a terminal event, with the idle and execution timeouts and `orchestration_stream_lost` | OSS-10, OSS-11 |
| BF-3 | Plug the #8 classify and extract prompts into OSS behind the existing interface; the mock LLM in CI | OSS-5, OSS-15 |
| BF-4 | Remove the Energy Agent's region default: no region means `awaiting_supplement` in OSS | R-INT-7 |
| BF-5 | CI end-to-end: OSS `POST /intents` → ORCH → Energy Agent → mock MAE → OSS status `COMPLETED`, plus `REJECTED` and one `FAILED` path | M3 gate |

After Phase 0, "basic feature done" means the M3 gate passes through OSS, not
only through the Execution Center.

---

## 2. DFX

### 2.1 Reliability

| Done | Gap | ID |
|---|---|---|
| Fail-closed `workflow_started` and `audit_read`; spool and replay for other audit events; terminal-once (#6) | Audit hash chain uses an in-process lock only: two OSS or Energy Agent replicas writing one file fork the chain | DFX-1: one writer per chain (DB sequence or per-replica chain with a merge verifier) |
| Registration and PSOP save retry at startup | No readiness distinct from liveness; services report healthy before Registry registration succeeds | DFX-2: `/ready` that includes registration and audit store |
| — | OSS restart loses in-flight SSE watchers | DFX-3: on start, re-link non-terminal intents via `GET /api/v1/executions` (same logic as OSS-12) and mark the rest `orchestration_stream_lost` |
| — | Does a dropped SSE stream cancel the run? (O-26) | DFX-4: test against the dev ORCH and record the answer |

### 2.2 Performance

| Done | Gap | ID |
|---|---|---|
| — | No load numbers at all | DFX-5: load test (k6 or Locust) for OSS submit and status and for N concurrent UC1 runs through ORCH; record p50/p95 and the point where ORCH returns `503` |
| — | LLM latency is the largest unknown on submit | DFX-6: time each LLM call (classify, extract, select, A2A-T) per model in the #8 harness |
| — | SSE watcher pool size and memory per stream unknown | DFX-7: watcher pool limit with `orchestration_busy` beyond it |

### 2.3 Observability

| Done | Gap | ID |
|---|---|---|
| `trace_id` in Energy Agent audit; structured logs | No metrics; no trace across OSS → ORCH → EA → MAE (ORCH drops the trace, UP-4) | DFX-8: OpenTelemetry in OSS and the Energy Agent (the A2A-T SDK already has it); carry `trace_id` in Task-T / Negotiation-T metadata so the join works without ORCH changes |
| — | — | DFX-9: metrics: intents by outcome, negotiation rounds, price API errors, LLM latency and refusal rate, audit spool depth, watcher count |
| — | — | DFX-10: a dev Grafana/Jaeger profile in `dev.py up --obs` |

### 2.4 Operability

| Done | Gap | ID |
|---|---|---|
| `dev.py` runner, VS Code setup, CI | No container images or deployment manifests (PLT-1, PLT-2) | DFX-11: Dockerfiles for OSS, Energy Agent, mocks; `deploy/docker-compose.dev.yml` |
| Config by env vars | No startup validation of the full config | DFX-12: fail fast with a list of every missing or invalid variable (PLT-3) |
| Audit verifier CLI | Not scheduled, no alert | GA-10 |
| — | No runbook | DFX-13: runbook for the alerts in DFX-9 (stuck spool, broken chain, price API down, ORCH busy) |

### 2.5 Testability

| Done | Gap | ID |
|---|---|---|
| 105+ unit tests, 41 documented scenario cases with a generated report (#7), dev-stack CI | No contract tests for the MAE artifact schema or the price API | DFX-14: schema contract tests (JSON Schema for the six artifacts and the tariff), reused when real samples arrive (O-11, O-1) |
| Mock scenarios by `scenario=` | Fault injection only at the mock level | DFX-15: toxiproxy-style faults between services (latency, drop, reset) in CI |
| — | — | DFX-16: coverage report in CI with a floor for `oss/` and `mocks/energy_agent/` |

---

## 3. Different LLMs

Four places use an LLM; three are ours to configure.

| Use case | Who | Config | Model choice is ours? |
|---|---|---|---|
| Classify, extract | OSS | `OSS_INTENT_LLM_*` | Yes |
| Workflow selection | Orchestration Center | `models.yaml` (`LLM_CONFIG_FILE`) | Yes, by config only |
| A2A-T slot extraction and validation | Energy Agent and MAE (SDK) | `A2AT_LLM_*` | Ours for the Energy Agent; MAE's is theirs |

**Done (#8):** the prompts, strict parsers, 24 phrasings and `scripts/llm_eval.py`
against any OpenAI-compatible endpoint. **Gap:** no real model has been run;
there is no LLM key in the cloud environment.

| ID | Work |
|---|---|
| LLM-1 | Model matrix: run `llm_eval.py --repeat 3` on 4–6 candidates through one OpenAI-compatible gateway, covering a hosted frontier model, a small hosted model, and self-hostable open-weight models (for example Qwen and Llama on vLLM or Ollama). Record accuracy per use case, latency and cost in `docs/llm-model-matrix.md`. Needs keys or a gateway from murat. |
| LLM-2 | Extend the eval to use case 4 (A2A-T) with the corpus in `upstream/a2a-t-sdk-python/a2a-t-corpus`; closes O-2 together with GA-1 |
| LLM-3 | Per-use-case model config: a small model can classify while a stronger one extracts; one `models.yaml`-style file for OSS so the three consumers are configured the same way |
| LLM-4 | Use JSON mode or structured output where the provider supports it; keep the strict parser as the final check |
| LLM-5 | Fallback model on timeout or invalid output (one retry with a stricter re-prompt, then fallback, then `502 classifier_invalid`); every fallback counted (DFX-9) |
| LLM-6 | A CI job that runs the eval against a real model when the secret is present (nightly, not per PR) so prompt or model drift shows up |

---

## 4. Robustness

| Area | Done | Gap | ID |
|---|---|---|---|
| Timeouts | Price API timeout, negotiation round timeout and round limit, abort on exhaustion (#7) | No total timeout on reading the MAE Task-T stream in the Energy Agent (only the HTTP client read timeout); OSS idle and execution timeouts not built (BF-2) | ROB-1: Task-T stream idle and total timeouts, ending `mae_execution_timeout` |
| Retries | Startup registration retry | No retry on transient price API errors (5xx, reset); no retry policy anywhere on the request path | ROB-2: bounded retry with jitter for idempotent GETs (price API, ORCH execution lookup) only; never for negotiation or dispatch |
| Circuit breaking | — | A down price API costs a full timeout per intent | ROB-3: breaker on the price API and the LLM, open state fails fast with the same error codes |
| Bad price response | Status, timeout and transport errors map to `price_api_unavailable` | A 200 with a malformed body (missing `bands`, negative or overlapping bands, wrong currency) raises a bare `KeyError` in the tariff step (`control_point.py` reads `tariff["bands"]` unchecked) | ROB-4: validate the tariff against a schema on receipt; malformed is `price_api_invalid_response` |
| Bad MAE response | Unknown verdicts are aborted; `TaskError` artifact (#7) | Artifact payloads are passed through without validation | ROB-5: validate each artifact against the DFX-14 schema; unknown artifact types are logged and kept, malformed ones fail the report step clearly |
| Malformed LLM output | Strict parsers refuse extra keys and wrong types (#6, #8) | No retry or fallback (LLM-5); prompt-injection cases only scored, not enforced | ROB-6: injection phrasings in #8 must classify as not-UC1 for the chosen model before GA |
| Concurrency | One ControlPoint per execution; audit append under a lock | Multi-replica audit (DFX-1); duplicate submits (OSS-13); two intents for the same region at once | ROB-7: idempotency key (OSS-13) and a per-region in-flight guard in OSS so two plans for the same sites do not run together |
| Cancellation | — | No user cancel; behaviour on a dropped stream unknown (O-26) | ROB-8: `POST /intents/{id}/cancel` through ORCH's cancel, audited |

---

## 5. Security

| Done | Gap | ID |
|---|---|---|
| OSS bearer auth stand-in, RBAC, region scope, ownership, rate limits, input cap, classifier-output validation, secret references, log redaction (#6) | SSO/OIDC instead of the bearer stand-in | SEC-1: OIDC `AuthManager` (OSS-3) |
| Energy Agent caller authentication by bearer, IP range or mTLS (#6) | Which one production uses (O-25); EA ↔ MAE mutual authentication (O-7) | GA-11, GA-3 |
| Six-element audit export, hash chain, verifier | Retention (O-24); insert-only DB role | GA-9, GA-10 |
| Dev stack: ORCH bearer token, Registry local HTTP | No TLS in dev; Registry production posture only a checklist | SEC-2: TLS in the dev stack (PLT-6) so prod settings are exercised in CI; PLT-12 |
| — | No dependency or secret scanning in CI | SEC-3: `pip-audit`, a secret scanner and `bandit` in CI |
| — | Prompt injection through `raw_text` reaching ORCH workflow selection | SEC-4: OSS forwards only validated structured fields (already designed, R-SEC-5); add a test that injected text never reaches the ORCH request |
| — | No threat model document | SEC-5: STRIDE pass over the LLD §17 control matrix, feeding GA-8 |

---

## 6. Suggested order

1. **Phase 0** (BF-1 … BF-5): finish the basic feature through OSS.
2. **Robustness core**: ROB-1, ROB-4, ROB-5, ROB-2, ROB-7. These are small and
   each closes a crash or a hang we can trigger today with the mocks.
3. **LLM-1 … LLM-3**, as soon as keys or a gateway are available; this informs
   GA-1 and the cost of running the feature.
4. **Observability**: DFX-8, DFX-9, then DFX-5 load tests with metrics in place.
5. **Security**: SEC-3 (cheap), SEC-2, SEC-5, then SEC-1.
6. **Operability**: DFX-11 … DFX-13, before any shared environment.

### Decisions for murat

- Which parts to start first after Phase 0 (default above).
- Which LLM providers to put in the matrix, and how to give the cloud
  environment access to them (a key per provider or one gateway).
- Whether our own front-end (FE-1 …) is in scope, or the upstream Execution
  Center stays the UI for now.
