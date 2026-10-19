# Project-OpenAN

A fork of [Project OpenAN](https://github.com/project-openan), assembled as the
baseline for the **OpenAN Energy-Saving Function** (LLD US202610010001 v10.4).

## Quick start

Requires Python 3.12+ (and ideally [`uv`](https://docs.astral.sh/uv/)); the web UIs also need
Node.js 20+. In VS Code, run **"OpenAN: all services + UIs"** from Run and Debug. From a terminal:

```sh
python scripts/dev.py up --ui    # services plus the web UIs (OpenAN console :3003, Registry UI :3004)
python scripts/dev.py demo       # UC1 straight against the mocks: tariff -> negotiation -> task -> report
python scripts/dev.py demo-orch  # UC1 through the Orchestration Center, as the Execution Center runs it
python scripts/dev.py down
```

The Henan Mobile demo page (tiered tariff to battery charge/discharge strategy and Deployment CSV)
runs at <http://127.0.0.1:8094>; see [docs/henan-demo.md](docs/henan-demo.md).

To watch UC1 in the browser, open <http://127.0.0.1:3003>, log in as `admin` with
`ORCH_AUTH_PASSWORD` from `.dev/dev.env`, go to **Execution Center**, pick **Mock Energy Agent**
as host agent, type `Run power-band energy saving for Accra Central` and press **Dispatch**.

See [docs/dev-environment.md](docs/dev-environment.md) for details, the mocks, and CI.

## Documentation

- [Use cases](docs/use-cases.md): the original requirement deck ([pptx](docs/source/Open_AN_UC.pptx)) transcribed, with where the LLD differs from it.
- [Requirements](docs/requirements.md): functional and non-functional requirements traced to the LLD, open items, and findings from the upstream code.
- [Development backlog](docs/development-backlog.md): milestones, work items, blockers, and feature requests for upstream.
- [Henan Mobile phase-1 demo](docs/henan-demo.md): the tariff-to-battery-strategy page, the OpenTalon Skill, and the mocks checked against HQ's A2A-T client plugin.
- [Development environment](docs/dev-environment.md): running the stack locally and in VS Code, the mock price API and mock MAE, and CI.

## Upstream repositories

Each repository the LLD's verified baseline (§0.2) relies on is imported under
`upstream/` as a `git subtree`, with its full commit history. All are Apache-2.0.

| Directory | Upstream | Imported commit | LLD role |
|---|---|---|---|
| `upstream/a2a-t-sdk-python` | [project-openan/a2a-t-sdk-python](https://github.com/project-openan/a2a-t-sdk-python) | `d8a80fa` | Task-T `ran-energy-saving/v1`, Negotiation-T, Authorization-T, OpenTelemetry (§0.2, §11.5) |
| `upstream/registry-center` | [project-openan/registry-center](https://github.com/project-openan/registry-center) | `49d9c24` | AgentCards, semantic query, approval, heartbeat, layer metadata (§7, §13.3) |
| `upstream/orchestration-center` | [project-openan/orchestration-center](https://github.com/project-openan/orchestration-center) | `77ee99e` | PSOP engine, sandbox, SSE, external API auth modes (§11.6, §13.2) |
| `upstream/workflow-engine-sdk-python` | [project-openan/workflow-engine-sdk-python](https://github.com/project-openan/workflow-engine-sdk-python) | `6033426` | Workflow-engine SDK (Python 0.1.0), ControlPoint callbacks (§11.6) |
| `upstream/workflow-engine-sdk-java` | [project-openan/workflow-engine-sdk-java](https://github.com/project-openan/workflow-engine-sdk-java) | `3debe46` | Workflow-engine SDK (Java 0.1.1) (§0.2) |

Not imported: MAE and the electricity price API are external systems
(blocked on O-1, O-3, O-11, O-12). The OSS, Energy Agent and Front-end do
not exist upstream and are new work for this repository.

`upstream/orchestration-center` and `upstream/registry-center` are used as
they are: LLD v10.4 does not change their code, so security and audit live in
OSS, the Energy Agent and configuration (see
[requirements](docs/requirements.md) §1 and the backlog's §8).

## Syncing with upstream

```sh
git subtree pull --prefix=upstream/<name> https://github.com/project-openan/<name> main
```

For example:

```sh
git subtree pull --prefix=upstream/orchestration-center \
  https://github.com/project-openan/orchestration-center main
```
