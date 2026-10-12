# Project-OpenAN

A fork of [Project OpenAN](https://github.com/project-openan), assembled as the
baseline for the **OpenAN Energy-Saving Function** (LLD US202610010001 v10.2).

## Documentation

- [Use cases](docs/use-cases.md): the original requirement deck ([pptx](docs/source/Open_AN_UC.pptx)) transcribed, with where the LLD differs from it.
- [Requirements](docs/requirements.md): functional and non-functional requirements traced to the LLD, open items, and findings from the upstream code.
- [Development backlog](docs/development-backlog.md): milestones, work items, blockers, and proposed upstream changes.

## Upstream repositories

Each repository the LLD's verified baseline (§2) relies on is imported under
`upstream/` as a `git subtree`, with its full commit history. All are Apache-2.0.

| Directory | Upstream | Imported commit | LLD role |
|---|---|---|---|
| `upstream/a2a-t-sdk-python` | [project-openan/a2a-t-sdk-python](https://github.com/project-openan/a2a-t-sdk-python) | `d8a80fa` | Task-T `ran-energy-saving/v1`, Negotiation-T, Authorization-T, OpenTelemetry (§2, §7.5) |
| `upstream/registry-center` | [project-openan/registry-center](https://github.com/project-openan/registry-center) | `49d9c24` | AgentCards, semantic query, approval, heartbeat, layer metadata (§8, §12.3) |
| `upstream/orchestration-center` | [project-openan/orchestration-center](https://github.com/project-openan/orchestration-center) | `77ee99e` | PSOP engine, sandbox, SSE, Handler Registry (§7.6, §12.2, §12.5) |
| `upstream/workflow-engine-sdk-python` | [project-openan/workflow-engine-sdk-python](https://github.com/project-openan/workflow-engine-sdk-python) | `6033426` | Workflow-engine SDK (Python 0.1.0), ControlPoint callbacks (§7.6) |
| `upstream/workflow-engine-sdk-java` | [project-openan/workflow-engine-sdk-java](https://github.com/project-openan/workflow-engine-sdk-java) | `61fae8c` | Workflow-engine SDK (Java 0.1.1) (§2) |

Not imported: MAE and the electricity price API are external systems
(blocked on O-1, O-3, O-11, O-12). The OSS, Energy Agent and Front-end do
not exist upstream and are new work for this repository.

## Syncing with upstream

```sh
git subtree pull --prefix=upstream/<name> https://github.com/project-openan/<name> main
```

For example:

```sh
git subtree pull --prefix=upstream/orchestration-center \
  https://github.com/project-openan/orchestration-center main
```
