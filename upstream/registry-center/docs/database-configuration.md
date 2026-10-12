# Database configuration / 数据库连接配置

两个中心统一使用 `etc/conf/db/<profile>.json`，按厂商/连接职责拆文件。
只复制启用连接的 `<profile>.json.template`；模板不作为运行时配置。
实际 JSON、.env 排除于 Git、Docker、Cloud Build。

| Service / 职责 | Selector / 开关 | Profile / 文件 |
|---|---|---|
| 编排主存储 | server.conf: persistence_mode=file/postgresql/mysql | postgresql.json / mysql.json |
| 注册主存储 | persistence.conf: persistence.mode=file/postgresql/mysql/gauss/sqlite | postgresql.json / mysql.json / gaussdb.json / sqlite.json |
| 注册审计 | persistence.conf: audit.mysql.enabled | audit_mysql.json |
| 注册图 | server.conf: knowledge_graph.enabled | neo4j.json |
| 注册向量 | server.conf: use_vectordb | milvus.json |

Each role owns separate credentials; audit MySQL is not the primary MySQL.
Only active profiles are read/validated. File mode needs no SQL config. Invalid
audit configuration degrades to local audit only; it never blocks business requests.
Audit batch_size/flush_interval remain policies in persistence.conf.
Moving files does not change the vector switch's existing replacement-storage
semantics; it does not implement the future authoritative-store + rebuildable-index
architecture. Do not enable that vector-only mode in production.

## Sources / 配置来源

**Process environment > repository-root .env > selected JSON > provider defaults.**

`DATABASE_CONFIG_DIR` overrides the directory (absolute or project-root relative).
Read-only connection mounts work. Relative SQLite/Milvus-Lite/CA paths resolve
from project root, not working directory. Restart after a change: a SQL backend
instance owns a fixed connection and dialect.

Fields are `host`, `port`, `database`, `user`, `connect_timeout` and (where
supported) `pool_min/pool_max`; consult the provider template for allowed fields.
Unknown fields, duplicate JSON keys, invalid bounds, literal secrets, and credentials
embedded in URIs are rejected.

密码只填 `password_env` 引用，不填明文或密文；Milvus 的可选 token 填 `token_env`。
例如 JSON:
```json
{"host":"127.0.0.1","port":3306,"database":"registry_center","user":"registry_user","password_env":"REGISTRY_DB_SECRET"}
```
Then set REGISTRY_DB_SECRET in environment/.env. Custom references are exclusive:
generic DB_PASSWORD cannot replace an audit connection's secret. Missing required
variables fail validation; explicitly empty ones allow deliberate passwordless local
databases. .env is read literally, without variable interpolation.

Default password aliases: POSTGRES_PASSWORD, MYSQL_PASSWORD, GAUSS_PASSWORD,
AUDIT_MYSQL_PASSWORD, NEO4J_PASSWORD. Milvus optionally uses MILVUS_TOKEN.
Non-secret aliases: POSTGRES_HOST/PORT/DATABASE/USER (same suffixes for MYSQL,
GAUSS, AUDIT_MYSQL); NEO4J_URI/USERNAME, MILVUS_URI, SQLITE_PATH.
Only primary SQL accepts DB_HOST/PORT/NAME/USERNAME/PASSWORD/CONNECT_TIMEOUT,
and DB_POOL_MIN/MAX where supported. Within one source layer vendor aliases win;
process generic aliases still beat vendor aliases in .env.
Registry REGISTRY_<legacy-provider-key> aliases remain supported and win within a
layer, e.g. REGISTRY_MYSQL_NAME and REGISTRY_MYSQL_USERNAME. These are environment
aliases, not accepted connection keys in persistence.conf.

## Profiles / 配置档案

Copy the template of every backend you select from `etc/conf/db/<brand>.json.template`
to `etc/conf/db/<brand>.json`. A selected backend with no profile file runs on the
built-in defaults, which point at a local server, so create the file for anything
other than a local default. Keep `.env` readable only by the service account (0600
POSIX, private Windows ACLs) and reference secrets by name with `password_env`; a
literal password or token in a profile is rejected at load.

## Containers / 容器

Python consumes DB variables directly; entrypoints never persist credentials.
Mount prepared profiles read-only:
`-v /private/db:/opt/registry-center/etc/conf/db:ro`
(or /opt/orchestration-center/etc/conf/db:ro), then inject secrets at runtime.
Environment-only primary SQL also works without a JSON. Custom password_env
still requires its named variable. No actual connection profiles are baked into images.

## Extension / 扩展

Add a provider profile (fields/defaults/aliases/secret references), credential-free
template, storage provider/registration and adapter tests. Shared source resolution
stays driver-independent; business code never reads vendor configuration files.

