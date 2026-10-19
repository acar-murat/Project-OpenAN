# Henan Mobile phase-1 demo

What HQ and Henan Mobile asked for on 2026-10-19, and what this repository provides for it.
Phase 1 is a showcase: nothing is delivered to the live network and no external tariff or power
system is connected.

| Asked for | Where it is |
|---|---|
| One simplified page: import a tiered tariff, show the generated battery charge/discharge strategy, export it as a CSV for Deployment | `henan_demo/` (port 8094) |
| Energy-saving status on the same page: strategy, activation, results | `henan_demo/`, Function 2 |
| Tariff -> battery rules as a Skill registered in OpenTalon (NextAgent) | `skills/tariff-to-battery-rules/` |
| Reuse the energy-saving A2A-T intent and CME power-strategy delivery, display only | Shown on the page, never called |
| Our mocks in line with HQ's A2A-T client plugin (`a2a-client-connector` 1.1.1) | `mocks/mae/`, checked by `scripts/a2a_plugin_check.mjs` |

## Running it

```sh
python scripts/dev.py up henan-demo mae   # or the VS Code compound "Henan demo: page + mock MAE"
```

Open <http://127.0.0.1:8094>. **Load sample** fills in an illustrative tariff, **Generate strategy**
shows the strategy and the CSV preview, **Export CSV** downloads it, and **Simulate activation**
walks the activation track (Deployment import, CME delivery, sites active) as a simulation.

### Function 1: strategy generation

1. Import the tariff: a CSV file or pasted text, `start_time,end_time,tier,price`
   (format: `skills/tariff-to-battery-rules/references/tariff-format.md`). Sites are NE names.
   Battery figures can be changed under *Battery profile*.
2. The strategy: a 24-hour chart (price by tier, charge/discharge windows, battery SoC) and one
   rule per tariff period with action, power, energy and SoC.
3. Export: one CSV row per site and charge/discharge rule, laid out by
   `skills/tariff-to-battery-rules/assets/deployment-template.json`. The user imports it by hand
   in the Deployment UI; CME then delivers it to the Huawei power systems.

### Function 2: activation and status

The meeting left this "to be refined", so the page shows a first cut:

- **Strategy**: charge and discharge windows, SoC limits, and the energy-saving A2A-T intent the
  strategy maps to (Task-T `ran-energy-saving/v1`, the reused intent interface), marked as not sent.
- **Activation**: strategy generated, CSV exported, imported in Deployment, CME delivery, active on
  sites. The first two are real; the rest is simulated.
- **Results**: expected saving per site and for all sites, cost reduction and kWh moved off peak.
  Measured effect is out of scope for phase 1.

## The Skill

`skills/tariff-to-battery-rules/` follows the NextAgent Skill contract (HQ's
`04-skill-tool-development.md`):

- `SKILL.md` with `name` equal to the folder name, `context: inline`, `metadata.version`; no
  `model`, since the customer's own LLM key and model profiles are not known yet.
- `scripts/tariff_to_rules.py`: standard library only. It fails fast without
  `NEXTAGENT_WORKSPACE_DIR`, `NEXTAGENT_TEMP_DIR` and `NEXTAGENT_SKILL_ROOT`, reads its assets from
  the Skill root, writes the CSV and strategy JSON to the workspace (timestamped, so runs in one
  session do not overwrite each other) and scratch data to the temp dir.
- `references/` and `assets/` hold the tariff format, the placeholder Deployment template, the
  placeholder battery profile and the sample tariff.

To register it, copy the folder to `configRoot/skills/` (system level, needs a restart) or
`configRoot/agents/<agentId>/skills/` (agent-owned, picked up on the next request) and add the
binding in `agent-binding.example.yaml` to the agent's `agent.yaml`. The page imports the same
script, so the page and the Skill always give the same strategy.

### How the strategy is built

Per site, one battery, one day repeated daily: charge in valley periods up to the SoC ceiling;
discharge in peak and sharp-peak periods to carry the site load, down to the SoC floor (the
outage reserve); recharge in a flat period only when it pays for a later, dearer discharge; when
stored energy runs short, the dearest periods get it first. The day is simulated twice so the
start-of-day SoC is the steady state.

With the sample tariff and the placeholder battery (14.4 kWh, 2 kW site load, SoC 40-95%) a site
saves about 7.60 CNY a day (23.8%), moving 15.8 kWh a day off peak.

### Placeholders to replace

| File | Placeholder for | Replace when |
|---|---|---|
| `assets/deployment-template.json` | Deployment import columns and action codes | HQ sends the real template; set `placeholder` to `false` |
| `assets/battery-profile.json` | Battery capacity, charge power, site load, SoC limits, efficiency | Site survey for the demo sites |
| `assets/sample-tariff.csv` | The Henan tariff (figures are illustrative) | Customer supplies the tariff to import |

## A2A-T plugin contract

HQ's `a2a-client-connector` plugin calls a remote A2A-T agent (the MAE RAN Agent side). The mock
MAE now serves everything on the plugin's checklist. `node scripts/a2a_plugin_check.mjs --plugin
<plugin index.js> --url http://127.0.0.1:8091/` loads the plugin bundle and calls its five tools
against a running mock MAE (21 checks, all passing on 2026-10-19); `mocks/tests/test_plugin_contract.py`
pins the same wire behaviour in CI without the plugin. The plugin bundle is HQ's and is not committed.

| Plugin expects | Mock MAE |
|---|---|
| `GET /` returns the AgentCard (`name`, `supportedInterfaces[0].url`, `capabilities.streaming`, `skills[]`) | Yes, also still at `/.well-known/agent-card.json` |
| `A2A-Version: 1.0` required except on `GET /`, 400 with an error body otherwise | Yes |
| `POST /message:send` returns a Task (bare or `{task}`) with `artifacts[].parts[].text` | Yes (`{task}`) |
| `POST /message:stream` SSE `id:N\ndata:{json}`: task, statusUpdate, artifactUpdate, terminal statusUpdate | Yes. The plugin's own mock also sets `"final": true`; A2A 1.0 has no such field and the a2a SDK client our Energy Agent uses rejects it, so the mock leaves it out. The plugin stops on the terminal state without it |
| `GET /tasks/{id}`, `POST /tasks/{id}:cancel` | Yes (a2a SDK) |
| INPUT_REQUIRED with a message saying what is missing | `energy-saving` skill without a region: `请补充：目标区域 region` |
| Missing-parameter rejections with `缺少必选参数`, `未解析出任务参数`, `取值无效`, `必须是小区 CGI` | Yes, as FAILED tasks; the plugin then returns `needsUserInput: true` |
| Parameters from `metadata.taskParameters`, a DataPart, a JSON block or `key: value` lines | Yes, in that priority |
| Work order `{issueId, objectId, problemType, rat}`: `serviceManagement.RanOptimizationResult`; known `issueId` returns `Exist` | Yes, `ran-complaint-optimization` skill (`mocks/mae/optimization.py`) |
| Strict validation of `objectId` (CGI), `problemType` (standard code), `rat` (default NR) | Yes |
| `GET /ops/omc/status` and `/ops/omc/advice?issueId=` with `{statuses}` / `{advices}`, empty when no result | Yes |
| Work-order ledger for `a2a_find_work_order` | `mocks/mae/work_orders.json`, same shape as the plugin's `config/work-orders.json` |
| No authentication (P1) | None on these routes |

Not changed: the mock Energy Agent runs on the upstream `host_agent` server, whose routes we do
not modify, so it does not serve the card at `/`. The plugin targets the MAE side.

## Open questions for HQ

1. The Deployment import template (columns, action codes, encoding) and the tariff format the
   customer will import.
2. Whether the activation and results view should show mock data, as now, or read from the reused
   intent interface and CME.
3. Battery and site figures for the demo sites.
4. Who provides the OpenTalon instance for the energy scenario, and the customer LLM key (meeting
   open items 1 and 2).
