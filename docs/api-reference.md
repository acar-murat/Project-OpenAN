# API Reference

Every interface our code serves or calls in the energy-saving stack: the
mocks we run (price API, MAE, Energy Agent, LLM), the upstream Orchestration
Center and Registry Center endpoints we use, the audit log format, and the
planned OSS API from LLD v10.4.

For what each component does and why, see
[OSS and Energy Agent](oss-and-energy-agent.md). For running the stack, see
[Development environment](dev-environment.md).

> **Snapshot.** Documents `main` as of 2026-10-16. Mock behaviour, security and
> audit, and LLM intent handling are being extended in parallel, so new
> settings, scenarios and responses will appear. Examples below were captured
> from the code on that date; ids, timestamps and hashes differ on every run.

---

## 1. Services and conventions

| Service | Base URL (dev) | Protocol | Source | Status |
|---|---|---|---|---|
| Mock price API | `http://127.0.0.1:8090` | REST, JSON | `mocks/price_api` | Implemented (mock) |
| Mock MAE | `http://127.0.0.1:8091` | A2A HTTP+JSON with A2A-T extensions | `mocks/mae` | Implemented (mock) |
| Mock Energy Agent | `http://127.0.0.1:8092` | A2A HTTP+JSON (upstream `host_agent` runtime) | `mocks/energy_agent` | Implemented (mock) |
| Mock LLM | `http://127.0.0.1:8093` | OpenAI-compatible chat completions | `mocks/llm` | Implemented (mock) |
| Registry Center | `http://127.0.0.1:5000` | REST | `upstream/registry-center` | Upstream, unchanged |
| Orchestration Center | `http://127.0.0.1:5001` | REST and SSE | `upstream/orchestration-center` | Upstream, unchanged |
| OSS | — | REST | — | **Planned** (LLD §13.1), not built |

Conventions:

- All dev services bind to `127.0.0.1` over plain HTTP. TLS, mTLS and service
  credentials are production concerns (LLD §11.2, §17) and are not set up in the
  dev stack.
- The price API, mock MAE and mock LLM have `GET /health` returning
  `200 {"status": "ok"}`. The mock Energy Agent has no `/health`; `dev.py`
  treats its `/.well-known/agent-card.json` as the health check.
- The price API and the mock LLM are FastAPI apps: interactive OpenAPI docs are
  at `/docs` and the schema at `/openapi.json`. Their errors use FastAPI's
  `{"detail": …}` body.
- A2A-T content travels as a **JSON string** inside `message.metadata` (or
  `artifact.metadata`) under the extension URI:

| Name | Value |
|---|---|
| Task-T extension | `https://projects.tmforum.org/a2aproject/telecommunication/extensions/Task-T/v1` |
| Negotiation-T extension | `https://projects.tmforum.org/a2aproject/telecommunication/extensions/Negotiation-T/v1` |
| Template key in metadata | `templateUri` |
| Energy-saving task template | `Task-T/network-layer/ran-energy-saving/v1` |
| Feasibility propose | `Negotiation-T/feasibility-negotiation/propose` |
| Feasibility accept / reject | `Negotiation-T/feasibility-negotiation/accept-reject` |
| Abort | `Negotiation-T/common/abort` |
| Mock scenario override | `mockScenario` (mocks only) |

These match the a2a-t SDK and its `ran-energy-saving` sample
(`mocks/common/a2at.py`).

---

## 2. Mock price API

Stands in for the external electricity price provider (open item O-1).

### `GET /v1/tariffs/power-band`

UC1 power-band tariff for a region: five bands, monthly charge per site, GHS.

| Parameter | In | Required | Notes |
|---|---|---|---|
| `region` | query | yes | Any non-empty name; `unknown` and `nowhere` return 404 |
| `X-API-Key` | header | when `MOCK_PRICE_API_KEY` is set | Must equal it |
| `X-Mock-Mode` | header | no | `normal`, `error` or `slow`; overrides `MOCK_PRICE_MODE` for this request |

```http
GET /v1/tariffs/power-band?region=Accra%20Central
```

```json
{
  "region": "Accra Central",
  "source": "mock",
  "currency": "GHS",
  "billing_period": "monthly",
  "bands": [
    {"band_no": 1, "min_kw": 0.0, "max_kw": 0.99, "charge": 8247.66},
    {"band_no": 2, "min_kw": 1.0, "max_kw": 1.99, "charge": 10628.25},
    {"band_no": 3, "min_kw": 2.0, "max_kw": 2.99, "charge": 11956.25},
    {"band_no": 4, "min_kw": 3.0, "max_kw": 3.99, "charge": 15409.75},
    {"band_no": 5, "min_kw": 4.0, "max_kw": 4.99, "charge": 17784.09}
  ]
}
```

Whether `charge` is a monthly charge per site is still to be confirmed (O-27).

### `GET /v1/prices/time-of-use`

UC2 time-of-use relative prices in the LLD's `price_table` shape (LLD §11.4).

| Parameter | In | Required | Notes |
|---|---|---|---|
| `region` | query | yes | As above |
| `date` | query | no | `YYYY-MM-DD`; defaults to today |
| `X-API-Key`, `X-Mock-Mode` | header | as above | |

```json
{
  "region": "Accra Central",
  "date": "2026-10-16",
  "timezone": "Africa/Accra",
  "source": "mock",
  "price_table": [
    {"start_time": "00:00", "end_time": "05:59", "relative_price": 1.0},
    {"start_time": "06:00", "end_time": "09:59", "relative_price": 1.176},
    {"start_time": "10:00", "end_time": "15:59", "relative_price": 0.824},
    {"start_time": "16:00", "end_time": "17:59", "relative_price": 1.176},
    {"start_time": "18:00", "end_time": "21:59", "relative_price": 1.765},
    {"start_time": "22:00", "end_time": "23:59", "relative_price": 1.176}
  ]
}
```

### Errors

| Status | When | Body |
|---|---|---|
| 400 | Unknown mock mode | `{"detail": "unknown mock mode 'bogus'; use one of ('normal', 'error', 'slow')"}` |
| 401 | `MOCK_PRICE_API_KEY` set and `X-API-Key` missing or wrong | `{"detail": "invalid or missing X-API-Key"}` |
| 404 | Region `unknown` or `nowhere` | `{"detail": "no prices for region 'unknown'"}` |
| 422 | `region` missing or blank | FastAPI validation error, or `{"detail": "region must not be empty"}` |
| 503 | Mode `error` | `{"detail": "price provider unavailable (mock error mode)"}` |

Mode `slow` waits `MOCK_PRICE_SLOW_SECONDS` (default 10) and then answers
normally, to exercise client timeouts.

### Settings

| Variable | Default | Effect |
|---|---|---|
| `MOCK_PRICE_HOST` / `MOCK_PRICE_PORT` | `127.0.0.1` / `8090` | Bind address |
| `MOCK_PRICE_API_KEY` | — | Require `X-API-Key` |
| `MOCK_PRICE_MODE` | `normal` | `normal`, `error`, `slow` |
| `MOCK_PRICE_SLOW_SECONDS` | `10` | Delay in `slow` mode |

---

## 3. Mock MAE

An A2A server (HTTP+JSON binding, `a2a-sdk` 1.x) that stands in for MAE (open
items O-3, O-11, O-12). It handles **Negotiation-T** feasibility and **Task-T**
`ran-energy-saving/v1`, and registers its AgentCard in the Registry Center.
It is deterministic and needs no LLM: the same region always gives the same plan.

### 3.1 Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/.well-known/agent-card.json` | AgentCard |
| POST | `/message:send` | Send a message, get one response (used for Negotiation-T) |
| POST | `/message:stream` | Send a message, get an SSE stream of task events (used for Task-T) |
| GET | `/tasks/{id}` | Task state (standard A2A, in-memory store) |
| POST | `/tasks/{id}:cancel` | Cancel; the task ends `TASK_STATE_CANCELED` |
| GET | `/health` | Liveness |

Standard A2A routes for task subscription, task listing and push-notification
configs are also mounted by the SDK; the mock adds nothing to them. Requests
send the header `A2A-Version: 1.0`.

How the mock routes a message, by `message.metadata`:

| Metadata carries | Handled as |
|---|---|
| Negotiation-T extension key | Feasibility negotiation (3.3) |
| Task-T extension key | Energy-saving task (3.4) |
| neither | One agent message: "Mock MAE expects a Task-T or Negotiation-T message (metadata key … or …)." |

### 3.2 AgentCard

Name `Mock MAE`, organisation `OpenAN Mock`, version `1.0.0`, streaming on,
both A2A-T extensions declared (not required), two skills:

| Skill id | Name |
|---|---|
| `energy-saving` | RAN energy saving |
| `feasibility-negotiation` | Energy-saving feasibility negotiation |

Interface: `{"url": "<MOCK_MAE_PUBLIC_URL>", "protocolBinding": "HTTP+JSON", "protocolVersion": "1.0.0"}`.
The real MAE card's names and values are open item O-3.

### 3.3 Negotiation-T feasibility

**Request** (`POST /message:send`). The Negotiation-T value is a JSON string;
it is shown decoded here.

```json
{
  "message": {
    "messageId": "5f0c…",
    "role": "ROLE_USER",
    "parts": [{"text": "initiate_feasibility_assessment"}],
    "metadata": {
      "https://projects.tmforum.org/a2aproject/telecommunication/extensions/Negotiation-T/v1": {
        "category": "goal_achievement",
        "message_class": "initiate_feasibility_assessment",
        "negotiation_id": "9b1c0d1e-0000-4000-8000-000000000001",
        "round": 1,
        "under_evaluation_description": {
          "region": "Accra Central",
          "schedule": [
            {"start_hour": 23, "end_hour": 5, "saving_mode": "maximized_energy_saving", "experience_target": {"type": "none"}},
            {"start_hour": 6, "end_hour": 9, "saving_mode": "proactive_energy_saving", "experience_target": {"type": "rate_floor", "mbps": 10}},
            {"start_hour": 10, "end_hour": 15, "saving_mode": "experience_first", "experience_target": {"type": "no_degradation"}},
            {"start_hour": 16, "end_hour": 17, "saving_mode": "proactive_energy_saving", "experience_target": {"type": "rate_floor", "mbps": 10}},
            {"start_hour": 18, "end_hour": 22, "saving_mode": "experience_first", "experience_target": {"type": "no_degradation"}}
          ],
          "power_band_tariff": {"currency": "GHS", "billing_period": "monthly", "bands": ["…as from the price API…"]}
        }
      },
      "templateUri": "Negotiation-T/feasibility-negotiation/propose"
    }
  }
}
```

`schedule` and `power_band_tariff` are optional for the mock (it falls back to
the UC1 values); `region` is required. Free text containing
`region: <name>` or `for <name> region` is also accepted.

**Response:** one agent message. Its text part is a one-line summary; the
Negotiation-T metadata holds the reply.

```json
{
  "message": {
    "messageId": "b52f6204-…",
    "contextId": "ba38a503-…",
    "role": "ROLE_AGENT",
    "parts": [{"text": "Feasible: please confirm to proceed."}],
    "metadata": {
      "https://projects.tmforum.org/a2aproject/telecommunication/extensions/Negotiation-T/v1": {
        "category": "goal_achievement",
        "negotiation_id": "9b1c0d1e-0000-4000-8000-000000000001",
        "round": 1,
        "message_class": "feasible_request_confirmation",
        "region": "Accra Central",
        "assessment": "The cluster can meet the energy-saving and experience targets."
      },
      "templateUri": "Negotiation-T/feasibility-negotiation/propose"
    }
  }
}
```

An infeasible verdict (here, a period asked for 30 Mbps with the default
20 Mbps limit) carries reasons and a counter-proposal that caps the rate floors:

```json
{
  "category": "goal_achievement",
  "negotiation_id": "9b1c0d1e-0000-4000-8000-000000000001",
  "round": 1,
  "message_class": "infeasible_with_proposal",
  "region": "Accra Central",
  "reasons": ["rate floor 30 Mbps in hours 6-9 exceeds the 20 Mbps the cluster can guarantee while saving energy"],
  "proposal": {"schedule": [
    {"start_hour": 23, "end_hour": 5, "saving_mode": "maximized_energy_saving", "experience_target": {"type": "none"}},
    {"start_hour": 6, "end_hour": 9, "saving_mode": "proactive_energy_saving", "experience_target": {"type": "rate_floor", "mbps": 20.0}},
    "…remaining periods unchanged…"
  ]}
}
```

**Closing the negotiation.** Send another message on the same
`negotiation_id`:

| `message_class` sent | Template | Reply `message_class` | Reply `outcome` |
|---|---|---|---|
| `accept` with `"accepted": "feasible_request_confirmation"` | `…/accept-reject` | `negotiation_closed` | `agreed` |
| `accept` with `"accepted": "infeasible_with_proposal"` | `…/accept-reject` | `negotiation_closed` | `closed_infeasible` |
| `reject` | `…/accept-reject` | `negotiation_closed` | `aborted` |
| `abort` | `common/abort` | `negotiation_closed` | `aborted` |
| anything else | `…/propose` | `error`, with `"error": "unsupported message_class '…'"` | — |

```json
{"category": "goal_achievement", "message_class": "accept",
 "accepted": "feasible_request_confirmation",
 "negotiation_id": "9b1c0d1e-0000-4000-8000-000000000001", "round": 1}
```

```json
{"category": "goal_achievement", "message_class": "negotiation_closed",
 "negotiation_id": "9b1c0d1e-0000-4000-8000-000000000001", "round": 1, "outcome": "agreed"}
```

The mock keeps no negotiation state: every message is judged on its own
content, which matches the SDK's stateless negotiation model (LLD §11.5).

The mock's reply field names (`reasons`, `proposal`) differ from the LLD's
logical content (`basis`, `counter_proposal`); the real MAE's names are open
item O-11.

### 3.4 Task-T `ran-energy-saving/v1`

**Request** (`POST /message:stream`), Task-T value decoded:

```json
{
  "message": {
    "messageId": "…",
    "role": "ROLE_USER",
    "parts": [{"text": "Power-band energy saving for Accra Central"}],
    "metadata": {
      "https://projects.tmforum.org/a2aproject/telecommunication/extensions/Task-T/v1": {
        "task_object": "Accra Central",
        "operation_type": "Create",
        "task_description": "Power-band energy saving for Accra Central",
        "task_target": {"schedule": ["…UC1 schedule…"]},
        "task_context": {"power_band_tariff": {"currency": "GHS", "billing_period": "monthly", "bands": ["…"]}}
      },
      "templateUri": "Task-T/network-layer/ran-energy-saving/v1"
    }
  }
}
```

| Slot | Required | Notes |
|---|---|---|
| `task_object` | yes | Region |
| `operation_type` | no | Default `Create` |
| `task_description` | no | Free text |
| `task_target.schedule` | no | Default: UC1 schedule |
| `task_context.power_band_tariff` | no | Default: UC1 tariff |
| `planning_month`, `site_count` | no | Mock extras; `site_count` defaults to 12 |

Where the schedule and tariff belong in Task-T is open item O-28.

**Response:** an SSE stream (`data: {…}` lines). The sequence for a
successful task:

1. `task` with `TASK_STATE_SUBMITTED` ("Energy-saving task accepted.")
2. For each of six artifacts: a `statusUpdate` with `TASK_STATE_WORKING`
   ("Region Accra Central: TaskPlan (1/6)"), then an `artifactUpdate`
3. `statusUpdate` with `TASK_STATE_COMPLETED`

An artifact event, with its Task-T value decoded:

```json
{
  "artifactUpdate": {
    "taskId": "3bdfc9c4-…",
    "contextId": "64b7c121-…",
    "artifact": {
      "artifactId": "479df000-…",
      "name": "IntentReport",
      "parts": [{"text": "IntentReport: predicted monthly cost 169,703.11 -> 162,573.84 GHS, saving 7,129.27 GHS; 3 sites change band"}],
      "metadata": {
        "https://projects.tmforum.org/a2aproject/telecommunication/extensions/Task-T/v1": {
          "type": "IntentReport",
          "schema_version": "mock-1",
          "region": "Accra Central",
          "intent_achieved": true,
          "currency": "GHS",
          "billing_period": "monthly",
          "predicted_cost_before": 169703.11,
          "predicted_cost_after": 162573.84,
          "predicted_saving": 7129.27,
          "sites_changing_band": 3,
          "schedule": ["…as requested…"]
        }
      }
    },
    "lastChunk": true
  }
}
```

### 3.5 Artifact schema (proposed for O-11)

Every artifact body has `type`, `schema_version` (`mock-1`) and `region`, plus:

| `type` | Fields |
|---|---|
| `TaskPlan` | `operation_type`, `planning_month` (null = next), `site_count`, `steps` (`band_prediction`, `site_classification`, `cluster_optimization`, `activation`) |
| `BandPrediction` | `sites[]`: `site_id`, `predicted_kw`, `predicted_band`, `predicted_charge` |
| `SiteClassification` | `counts` {`downgrade`, `upgrade`, `grade_stable`}; `sites[]`: `site_id`, `classification` |
| `TrafficMigrationPlan` | `actions[]`: `site_id`, `direction` (`out` / `in`), `action` (`reduce_tx_power`, `increase_tilt`, `handover_out`, `handover_in`), `load_kw`; `unplaced_kw`; `active_periods[]` {`start_hour`, `end_hour`} |
| `EnergySavingActivated` | `activated_sites[]`; `active_periods[]` (periods whose mode is not `experience_first`) |
| `IntentReport` | `intent_achieved`, `currency`, `billing_period`, `predicted_cost_before`, `predicted_cost_after`, `predicted_saving`, `sites_changing_band`, `schedule` |

LLD §11.7 lists `TaskPlan → CellSelection → EnergySavingActivated →
IntentReport`; the mock's set follows UC1 from the use-case deck instead. Site
data is derived from a hash of the region name and is illustrative only.

### 3.6 Failures and scenarios

| Condition | Result |
|---|---|
| Negotiation content has no region | `infeasible_with_proposal` with the reason and `"proposal": null` |
| Task-T `templateUri` is not `ran-energy-saving/v1` | Stream ends `TASK_STATE_REJECTED`: "Unsupported template …" |
| Task-T content has no region | `TASK_STATE_REJECTED`: "Intent rejected: intent has no region (Task-T slot task_object)" |
| Scenario `reject_task` | `TASK_STATE_REJECTED`: "Intent rejected: mock scenario 'reject_task'." |
| Scenario `exec_failure` | Two artifacts, then `TASK_STATE_FAILED`: "Cluster optimization failed: mock scenario 'exec_failure'." |
| Scenario `infeasible` | Negotiation answers `infeasible_with_proposal` with the request's own schedule as the proposal |
| Scenario `feasible` | Negotiation answers feasible regardless of rate floors |

The scenario comes from `metadata["mockScenario"]` on the message, else
`MOCK_MAE_SCENARIO`. Unknown values count as `auto` (decide from the content).

### 3.7 Settings

| Variable | Default | Effect |
|---|---|---|
| `MOCK_MAE_HOST` / `MOCK_MAE_PORT` | `127.0.0.1` / `8091` | Bind address |
| `MOCK_MAE_PUBLIC_URL` | `http://<host>:<port>` | URL in the AgentCard |
| `MOCK_MAE_SCENARIO` | `auto` | `auto`, `feasible`, `infeasible`, `reject_task`, `exec_failure` |
| `MOCK_MAE_MAX_RATE_FLOOR_MBPS` | `20` | Highest rate floor judged feasible |
| `MOCK_MAE_STEP_DELAY_SECONDS` | `0.5` | Pause between task steps |
| `REGISTRY_CENTER_URL` | — | Register the card here on startup |
| `MOCK_MAE_REGISTER_TIMEOUT_SECONDS` | `60` | Registration retry window |
| `REGISTRY_ACCESS_TOKEN` | — | Bearer token for registration |

---

## 4. Mock Energy Agent

The Orchestration Center's host agent for UC1. It is not called directly: the
Orchestration Center dispatches an intent to it (section 6.2), and it runs the
UC1 workflow and streams the workflow's events back. The A2A server, its
routes and the event stream come from the upstream `host_agent` runtime; what
is ours is the AgentCard, the workflow and the ControlPoint.

### 4.1 AgentCard

Name `Mock Energy Agent`, organisation `OpenAN Mock`, version `1.0.0`,
streaming on, interface HTTP+JSON at `MOCK_ENERGY_AGENT_PUBLIC_URL`.

| Skill id | Name | Used by |
|---|---|---|
| `uc1-energy-saving-workflow` | UC1 power-band energy saving | Host-agent entry; example intent `Run power-band energy saving for Accra Central` |
| `power-band-tariff` | Power-band tariff | Workflow step 1 |
| `feasibility-negotiation` | Feasibility negotiation with MAE | Workflow step 2 |
| `intent-report` | Intent report | Workflow step 4 |

### 4.2 Input

A free-text intent. The agent reads:

| From the text | Example | Default |
|---|---|---|
| Region: `region: <name>`, or capitalised words after "for" | `… for Kumasi` | `Accra Central` |
| Test scenario for the mock MAE: `scenario=<name>` | `scenario=infeasible` | none |

The schedule is always the UC1 example schedule; there is no extraction yet
*(LLM intent handling is being worked on separately)*.

### 4.3 Workflow and step outputs

PSOP id `psop_uc1_power_band_energy_saving`, saved on startup with
`POST /rest/v1/orchestrate/workflows`.

| Step | Type | Agent / skill | Success output |
|---|---|---|---|
| `power_band_tariff` | SelfLoop | Mock Energy Agent / `power-band-tariff` | Markdown table of the bands |
| `feasibility_negotiation` | SelfLoop | Mock Energy Agent / `feasibility-negotiation` | "MAE: … Energy Agent accepted; negotiation agreed (id …)." |
| `ran_energy_saving` | AllSuccess | Mock MAE / `energy-saving` | MAE's six artifacts (section 3.4) |
| `intent_report` | SelfLoop | Mock Energy Agent / `intent-report` | Markdown report: cost before and after, saving, intent achieved, sites changing band, classification counts, activated sites |

### 4.4 Step failure codes

A failed step ends the workflow with an `error` event in the stream.

| Code | When |
|---|---|
| `energy_agent.policy_violation` | The policy guard refused the region or schedule; MAE was not contacted |
| `energy_agent.infeasible` | MAE answered `infeasible_with_proposal`; the message carries MAE's reasons and the counter-proposal JSON |
| `energy_agent.negotiation_aborted` | MAE answered with anything other than a verdict |
| `energy_agent.no_report` | MAE returned no `IntentReport` artifact |
| `energy_agent.<skill>` | Any other exception in a step, e.g. the price API returning 503 (`energy_agent.power-band-tariff`); the message is `<ExceptionType>: <text>` |
| `energy_agent.unknown_skill` | The workflow named a skill the agent does not have |

The LLD's reason codes (`price_api_unavailable`, `negotiation_aborted`,
`policy_violation`, LLD §14) are not yet mapped one to one; see
[OSS and Energy Agent](oss-and-energy-agent.md#39-gaps-against-the-lld).

### 4.5 Messages it sends

- To the price API: `GET /v1/tariffs/power-band?region=…`, with `X-API-Key` when
  `ENERGY_AGENT_PRICE_API_KEY` is set.
- To MAE (Negotiation-T, `POST /message:send` with header
  `A2A-Extensions: <Negotiation-T URI>`): the opening, then `accept` or
  `abort`, as in section 3.3.
- To MAE (Task-T, sent by the workflow engine from `on_task`): the slots in
  section 3.4.
- To the Registry Center: card registration, and lookup of the MAE card
  (section 6.3).

Settings are listed in [OSS and Energy Agent §3.8](oss-and-energy-agent.md#38-configuration).

---

## 5. Mock LLM

OpenAI-compatible model that the Orchestration Center calls to choose a
workflow for an intent. `scripts/dev.py setup` writes `.dev/models.yaml`
pointing the Orchestration Center at it through `LLM_CONFIG_FILE`.

### `POST /v1/chat/completions`

Request: the OpenAI chat shape (`model`, `messages`). System messages are
ignored; the other messages' `content` is joined into one prompt.

If the prompt has a `## User Intent` section and a `## Available PSOP
Workflows` section holding a JSON list, the mock returns the names of the
workflows that share the most words with the intent (in name, description,
`user_intent`, `tasks` and `tags`, ignoring common stop words), up to the N in
"select the top N" (default 1):

```json
{
  "id": "chatcmpl-9a137c46f9d3",
  "object": "chat.completion",
  "created": 1792139944,
  "model": "mock",
  "choices": [{
    "index": 0,
    "message": {"role": "assistant", "content": "```json\n[\"UC1 power-band energy saving\"]\n```"},
    "finish_reason": "stop"
  }],
  "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
}
```

No overlapping word gives an empty list (`[]`). Any other prompt gets the
content "The local mock LLM only selects workflows for the Execution Center.
Configure a real model in models.yaml for anything else."

Because selection is by word overlap, the intent's wording decides whether
the UC1 workflow is picked *(in flux: intent wording with real models is
being tested separately)*.

| Variable | Default |
|---|---|
| `MOCK_LLM_HOST` / `MOCK_LLM_PORT` | `127.0.0.1` / `8093` |

---

## 6. Upstream endpoints we use

The Orchestration Center and Registry Center are used unchanged. Only the
calls our code or dev tooling makes are listed; the full upstream references
are under `upstream/*/docs/`.

### 6.1 Orchestration Center: login and workflows

| Method | Path | Body | Used by |
|---|---|---|---|
| POST | `/rest/v1/orchestrate/auth/login` | `{"username": "admin", "password": "<ORCH_AUTH_PASSWORD>"}` | Energy Agent, `demo_orchestration.py`, `demo_uc1.py`; sets the session cookie the calls below need |
| POST | `/rest/v1/orchestrate/workflows` | `{"psop": {…}}` | Energy Agent on startup; `201 {"data": {"workflow_id": "…"}}` |
| GET | `/rest/v1/orchestrate/agent-cards` | — | `demo_uc1.py`, to check the Orchestration Center sees Mock MAE through the Registry Center |

### 6.2 Orchestration Center: dispatch (what the Execution Center calls)

`GET /rest/v1/orchestrate/dispatch?intent=<text>&agent_name=<host agent>&lang=en`

Requires the login session. Returns `text/event-stream`. The Orchestration
Center asks the LLM to pick a workflow, sends the intent to the named host
agent, and forwards the agent's workflow events. Each line is
`data: {"type": …, "data": {…}, "timestamp": …}`:

| `type` | Key `data` fields |
|---|---|
| `start` | `phase`, `workflow` (should be "UC1 power-band energy saving") |
| `step_start`, `step_complete` | `step` |
| `agent_request` | `agent` |
| `task_response` | `agent`, `step`, `status`, `outputs[]` (step output), `error` |
| `complete` | — terminal, success |
| `error` | `error` — terminal, failure |
| `cancelled` | — terminal |

Other types (`route_decision`, `negotiation_*`, `notification`, …) come from
the upstream runtime. `503 {"detail": "Server is busy"}` means the dispatch
concurrency limit was hit.

`scripts/demo_orchestration.py` is a working client of this endpoint.

### 6.3 Registry Center

| Method | Path | Body / result | Used by |
|---|---|---|---|
| POST | `/rest/v1/registry-center/agent-cards` | `{"agentCards": [<card>]}`; `200`/`201` registered, `409` already registered | Both mock agents on startup |
| GET | `/rest/v1/registry-center/agent-cards/{organization}/{name}` | `{"agentCards": [<card>]}` | Energy Agent and `demo_uc1.py`, to find Mock MAE |

### 6.4 OSS-facing endpoints (for when OSS is built)

LLD §13.2 has OSS submit with `POST /api/v1/orchestrate/execute` (body
`{"task": "<text>"}`, SSE response, service credential in `mtls` or `bearer`
mode), then resolve the run with `GET /api/v1/executions` and
`GET /api/v1/executions/{id}` after the stream ends. These exist upstream but
nothing in this repository calls them yet.

---

## 7. OSS (planned)

**Not implemented.** From LLD v10.4 §11.1, §11.8, §12, §13.1 and §14; the
work items are OSS-1 … OSS-20 in the [backlog](development-backlog.md).

| Method | Path | Permission | Purpose |
|---|---|---|---|
| POST | `/api/v1/energy-saving/intents` | `energy_saving:submit` | Submit an intent |
| POST | `/api/v1/energy-saving/intents/{intent_id}/supplement` | `energy_saving:submit` | Add missing parameters |
| GET | `/api/v1/energy-saving/intents/{intent_id}/status` | `energy_saving:query` (owner) or `energy_saving:admin` | Status and report |

### `POST /api/v1/energy-saving/intents`

```json
{"raw_text": "Maximise saving overnight in Accra Central, keep 10 Mbps in the morning",
 "user_id": "u-123", "session_id": "optional"}
```

Processing order (fixed): authenticate → RBAC → audit `intent_received` → LLM
classify → validate parameters → region scope → audit `workflow_started` →
submit to the Orchestration Center.

| Result | Body |
|---|---|
| Submitted | `{"handled": true, "intent_id": "uuid", "status": "submitted_to_orchestration", "workflow_execution_id": "string"}` |
| Missing parameters | `{"handled": true, "intent_id": "uuid", "status": "awaiting_supplement", "missing_fields": ["region", "experience_target"]}` |
| Not an energy-saving intent | `200 {"handled": false}` |

The classifier returns only `{"is_energy_saving_intent": bool, "confidence": float}`.
`raw_text` is length-capped (`OSS_RAW_TEXT_MAX_CHARS`) and never forwarded
beyond OSS. UC1 replaces the single saving and experience targets with a
per-period schedule (requirements R-INT-10 … R-INT-12, backlog OSS-14).

### `POST /api/v1/energy-saving/intents/{intent_id}/supplement`

Merges the supplied fields by `session_id`, audits `parameter_supplement`, and
re-runs validation. Responses as for submit.

### `GET /api/v1/energy-saving/intents/{intent_id}/status`

```json
{
  "intent_id": "uuid",
  "workflow_state": "REJECTED",
  "artifacts": [{"type": "TaskPlan", "summary": "..."}],
  "counter_proposal": {"adjusted_experience_target": "string"},
  "final_report": null,
  "failure_reason": null
}
```

Built from OSS's own store (fed by the SSE stream), returned only to the
intent's owner or an admin. `counter_proposal` is set only for `REJECTED`;
`final_report` comes from the `IntentReport` artifact on `COMPLETED`.

### Errors

| Status / result | Code | When |
|---|---|---|
| `401` | `auth_failure` | Identity not established (audited) |
| `403` | `permission_denied` | Missing permission or region out of scope (audited) |
| `429` | — | Per-user rate limit on submit or supplement |
| `503` + `Retry-After` | `orchestration_busy` | Orchestration Center answered 503 |
| `504` | — | Orchestration timeout; the front-end retries |
| `FAILED` | `agent_not_discoverable`, `registry_unavailable`, `price_api_unavailable`, `negotiation_aborted`, `semantic_validation_failed`, `policy_violation`, `orchestration_stream_lost`, or MAE's reason | Workflow failure |
| `REJECTED` | MAE's basis plus `counter_proposal` | Negotiation ended infeasible |

---

## 8. Audit log format

Shared by the Energy Agent today and OSS later (LLD §11.3, §11.11;
`mocks/common/audit.py`). One JSON object per line:

```json
{
  "audit_id": "78bc6899-10da-47c9-a563-8e762c7790c8",
  "ts": "2026-10-16T08:39:23.076578Z",
  "event": "policy_decision",
  "intent_id": null,
  "trace_id": "exec-123",
  "actor": {"user_id": null, "source_ip": null, "roles": [], "caller": "unverified (O-25)"},
  "resource": {"region": "Kumasi", "psop_id": null, "execution_id": null},
  "outcome": "denied",
  "reason": "policy_violation",
  "detail": {
    "allowed": false,
    "reasons": ["region 'Kumasi' is not in the allowlist"],
    "price_table_digest": "a5d4b59fb28bfde7157e0910f465be3fe6cccf60854a353e274f5cd99c3c4e19"
  },
  "detail_digest": "sha256 of canonical detail",
  "prev_hash": "hash of the previous record (64 zeros for the first)",
  "hash": "sha256 of this record without hash"
}
```

| Field | Meaning |
|---|---|
| `event` | Energy Agent: `policy_decision`, `negotiation_round`. OSS will add the §11.3 events |
| `outcome` | `success`, `failure` or `denied` |
| `detail` | Redacted before hashing: values of keys matching `api_key`, `token`, `secret`, `password`, `authorization`, `credential` or `cookie` become `[REDACTED]` |
| `hash` | SHA-256 of the record's canonical JSON (sorted keys, compact) without `hash` |

`negotiation_round` details: `negotiation_id`, `round`, `sent` and `received`
(`template`, `message_class`), `outcome`, `price_table_digest`,
`counter_proposal_digest`, `mae_card_digest`.

Verify a log:

```sh
python -m mocks.common.audit .dev/logs/energy-agent-audit.jsonl
# "audit chain intact", exit 0; or one line per break and exit 1
```
