# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Registry connection profiles and adaptation to the existing provider API.

Primary storage, audit replication, graph and vector search own separate profiles.
Adding a provider does not change the environment/secret-resolution algorithm.
"""
from common.util.database_config import DatabaseProfile, load_profile
from common.util.app_config import get_root_path

PROFILES = {}
PRIMARY_PROFILES = {"postgresql": "postgresql", "mysql": "mysql",
                    "gauss": "gaussdb", "sqlite": "sqlite"}
PREFIXES = {"postgresql": "postgresql", "mysql": "mysql", "gaussdb": "gauss",
            "sqlite": "sqlite", "audit_mysql": "audit.mysql", "neo4j": "neo4j"}
FIELDS = {"database": "name", "user": "username", "pool_min": "pool.min", "pool_max": "pool.max"}


def _sql_profile(name, port, *, primary=True):
    vendor = {"postgresql": "POSTGRES", "gaussdb": "GAUSS", "mysql": "MYSQL",
              "audit_mysql": "AUDIT_MYSQL"}[name]
    prefix = PREFIXES[name].upper().replace(".", "_")
    defaults = dict(host="127.0.0.1", port=port, database="registry_center",
                    user="a2a_user", connect_timeout=10)
    if name == "postgresql":
        defaults["user"] = "opena2a_t"
    elif name == "gaussdb":
        defaults["database"] = "a2a_registry"
    elif name == "audit_mysql":
        defaults.update(database="registry_audit", user="audit_writer")
    if primary:
        defaults.update(pool_min=5, pool_max=20)
    fields = {"host": "HOST", "port": "PORT", "database": "DATABASE", "user": "USER",
              "connect_timeout": "CONNECT_TIMEOUT"}
    if primary:
        fields.update(pool_min="POOL_MIN", pool_max="POOL_MAX")
    env = {}
    for field, suffix in fields.items():
        alias = "DATABASE" if name == "gaussdb" and field == "database" else FIELDS.get(field, field).upper().replace(".", "_")
        aliases = [f"REGISTRY_{prefix}_{alias}", f"{vendor}_{suffix}"]
        if name == "audit_mysql" and field == "user":
            aliases.append("AUDIT_MYSQL_USERNAME")
        if name == "postgresql" and field == "connect_timeout":
            aliases.append("PG_CONNECT_TIMEOUT")
        if primary:
            aliases.append("DB_" + {"database": "NAME", "user": "USERNAME"}.get(field, suffix))
        env[field] = tuple(aliases)
    secrets = [f"REGISTRY_{prefix}_PASSWORD", f"{vendor}_PASSWORD"]
    if primary:
        secrets.append("DB_PASSWORD")
    bounds = dict(port=(1, 65535), connect_timeout=(1, 86400))
    if primary:
        bounds.update(pool_min=(1, 10000), pool_max=(1, 10000))
    return DatabaseProfile(defaults, env, {"password": tuple(secrets)},
                           ("user", "password"), bounds)


for _name, _port in (("postgresql", 5432), ("mysql", 3306), ("gaussdb", 5432), ("audit_mysql", 3306)):
    PROFILES[_name] = _sql_profile(_name, _port, primary=_name != "audit_mysql")
PROFILES["sqlite"] = DatabaseProfile(
    {"path": "data/agents.db"}, {"path": ("REGISTRY_SQLITE_PATH", "SQLITE_PATH")},
    required=("path",))
PROFILES["neo4j"] = DatabaseProfile(
    {"uri": "bolt://127.0.0.1:7687", "user": "neo4j"},
    {"uri": ("REGISTRY_NEO4J_URI", "NEO4J_URI"),
     "user": ("REGISTRY_NEO4J_USERNAME", "NEO4J_USERNAME")},
    {"password": ("REGISTRY_NEO4J_PASSWORD", "NEO4J_PASSWORD")},
    ("uri", "user", "password"))
PROFILES["milvus"] = DatabaseProfile(
    {"uri": "milvus_demo.db", "description": "Milvus DB Service", "version": "milvus-lite"},
    {"uri": ("MILVUS_URI",), "description": ("MILVUS_DESCRIPTION",), "version": ("MILVUS_VERSION",)},
    {"token": ("MILVUS_TOKEN",)}, ("uri",))


def load_connection_config(name, root=None):
    root = root or get_root_path()
    config = load_profile(name, PROFILES[name], root)
    if name == "sqlite":
        from pathlib import Path
        # :memory: is a SQLite connection target, not a relative filename.
        if config["path"] != ":memory:" and not Path(config["path"]).is_absolute():
            config["path"] = str(Path(root) / config["path"])
    if name == "milvus":
        from pathlib import Path
        if "://" not in config["uri"] and not Path(config["uri"]).is_absolute():
            config["uri"] = str(Path(root) / config["uri"])
    return config


def provider_config(name, root=None):
    config = load_connection_config(name, root)
    prefix = PREFIXES[name]
    fields = {**FIELDS, "database": "database" if name == "gaussdb" else "name"}
    return {prefix + "." + fields.get(key, key): value for key, value in config.items()}
