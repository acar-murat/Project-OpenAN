# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Selected profile consumption, independent auxiliary roles and provider inputs."""
import json
import os

import pytest

from common.util import app_config, connection_profiles
from common.util.database_config import DatabaseConfigError


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "environ", {})
    monkeypatch.setattr(app_config, "get_root_path", lambda: str(tmp_path))
    monkeypatch.setattr(connection_profiles, "get_root_path", lambda: str(tmp_path))
    directory = tmp_path / "etc/conf"
    directory.mkdir(parents=True)
    (directory / "server.conf").write_text("knowledge_graph.enabled=false\n")
    (directory / "server.properties").write_text("")
    (directory / "persistence.conf").write_text("persistence.mode=file\n")
    return tmp_path


def put(root, name, config):
    directory = root / "etc/conf/db"
    directory.mkdir(exist_ok=True)
    (directory / (name + ".json")).write_text(json.dumps(config))


@pytest.mark.parametrize("mode,name,prefix", [
    ("postgresql", "postgresql", "postgresql"), ("mysql", "mysql", "mysql"),
    ("gauss", "gaussdb", "gauss"),
])
def test_selected_sql_profile_adapts_driver_contract(runtime, mode, name, prefix, monkeypatch):
    (runtime / "etc/conf/persistence.conf").write_text("persistence.mode=" + mode + "\n")
    put(runtime, name, {"database": "fixture_db", "user": "fixture", "port": 1234,
                        "pool_min": 2, "pool_max": 8, "password_env": "FIXTURE_SECRET"})
    monkeypatch.setenv("FIXTURE_SECRET", "fixture")
    conf = app_config.get_persistence_conf()
    assert conf[prefix + "." + ("database" if mode == "gauss" else "name")] == "fixture_db"
    assert conf[prefix + ".username"] == "fixture"
    assert conf[prefix + ".password"] == "fixture"
    assert conf[prefix + ".port"] == 1234
    assert conf[prefix + ".pool.min"] == 2 and conf[prefix + ".pool.max"] == 8
    assert not any(k.startswith("neo4j.") for k in conf)


def test_primary_and_audit_mysql_have_separate_credentials(runtime, monkeypatch):
    (runtime / "etc/conf/persistence.conf").write_text("persistence.mode=mysql\naudit.mysql.enabled=true\n")
    put(runtime, "mysql", {"password_env": "PRIMARY_SECRET"})
    put(runtime, "audit_mysql", {"password_env": "AUDIT_SECRET"})
    monkeypatch.setenv("PRIMARY_SECRET", "primary")
    monkeypatch.setenv("AUDIT_SECRET", "audit")
    monkeypatch.setenv("DB_PASSWORD", "generic")
    conf = app_config.get_persistence_conf()
    assert conf["mysql.password"] == "primary"
    assert conf["audit.mysql.password"] == "audit"


def test_invalid_audit_config_degrades_to_local_only(runtime):
    (runtime / "etc/conf/persistence.conf").write_text("persistence.mode=file\naudit.mysql.enabled=true\n")
    put(runtime, "audit_mysql", {"password": "invalid-literal"})
    conf = app_config.get_persistence_conf()
    assert conf["audit.mysql.enabled"] == "false"
    assert "audit.mysql.password" not in conf


def test_file_mode_does_not_parse_inactive_connections(runtime):
    put(runtime, "mysql", {"password": "invalid"})
    assert app_config.get_persistence_conf() == {"persistence.mode": "file"}


def test_sqlite_profile_reaches_real_provider(runtime):
    from agent_registry.persistence.sqlite_storage import SQLiteStorage
    put(runtime, "sqlite", {"path": "database.db"})
    (runtime / "etc/conf/persistence.conf").write_text("persistence.mode=sqlite\n")
    conf = app_config.get_persistence_conf()
    storage = SQLiteStorage.init(conf)
    try:
        storage.check_connection()
        assert (runtime / "database.db").exists()
    finally:
        storage.close()


def test_graph_profile_loads_only_when_enabled(runtime, monkeypatch):
    put(runtime, "neo4j", {"uri": "bolt://127.0.0.1:7687", "user": "graph",
                           "password_env": "GRAPH_SECRET"})
    monkeypatch.setenv("GRAPH_SECRET", "fixture")
    assert "neo4j.password" not in app_config.get_persistence_conf()
    (runtime / "etc/conf/server.conf").write_text("knowledge_graph.enabled=true\n")
    assert app_config.get_persistence_conf()["neo4j.password"] == "fixture"


def test_vector_profile_passes_uri_and_opaque_token(runtime, monkeypatch):
    from common.vector_db.vector_db_client.config.vector_db_config import get_vectordb_config
    put(runtime, "milvus", {"uri": "http://127.0.0.1:19530", "token_env": "VECTOR_TOKEN"})
    monkeypatch.setenv("VECTOR_TOKEN", "fixture-token")
    config = get_vectordb_config()["milvus"]
    assert config.uri == "http://127.0.0.1:19530" and config.token == "fixture-token"


def test_dotenv_can_select_sqlite_without_modifying_selector_file(runtime):
    (runtime / ".env").write_text("PERSISTENCE_MODE=sqlite\nSQLITE_PATH=local.db\n")
    original = (runtime / "etc/conf/persistence.conf").read_bytes()
    conf = app_config.get_persistence_conf()
    assert conf["sqlite.path"] == str(runtime / "local.db")
    assert (runtime / "etc/conf/persistence.conf").read_bytes() == original


def test_process_control_alias_beats_dotenv_registry_alias(runtime, monkeypatch):
    (runtime / ".env").write_text("REGISTRY_PERSISTENCE_MODE=mysql\nREGISTRY_AUDIT_MYSQL_ENABLED=true\n")
    monkeypatch.setenv("PERSISTENCE_MODE", "sqlite")
    monkeypatch.setenv("AUDIT_MYSQL_ENABLED", "false")
    conf = app_config.get_persistence_conf()
    assert conf["persistence.mode"] == "sqlite" and conf["audit.mysql.enabled"] == "false"


def test_inactive_connection_env_does_not_leak_into_policy_dict(runtime, monkeypatch):
    monkeypatch.setenv("REGISTRY_MYSQL_PASSWORD", "inactive")
    monkeypatch.setenv("REGISTRY_NEO4J_PASSWORD", "inactive")
    conf = app_config.get_persistence_conf()
    assert all("password" not in key for key in conf)


@pytest.mark.parametrize("mode", ["file", "sqlite", "postgresql", "mysql", "gauss"])
@pytest.mark.parametrize("spelling", [str.lower, str.upper, str.title, lambda value: "  " + value.upper() + "  "])
@pytest.mark.parametrize("source", ["file", "dotenv", "process"])
def test_mode_normalized_before_profile_selection(runtime, monkeypatch, mode, spelling, source):
    value = spelling(mode)
    name = connection_profiles.PRIMARY_PROFILES.get(mode)
    if name:
        config = {"path": "selected.db"} if mode == "sqlite" else {
            "database": "selected_db", "user": "selected_user", "password_env": "SELECTED_SECRET"}
        put(runtime, name, config)
        monkeypatch.setenv("SELECTED_SECRET", "synthetic")
    if source == "file":
        (runtime / "etc/conf/persistence.conf").write_text("persistence.mode=" + value + "\n")
    elif source == "dotenv":
        (runtime / ".env").write_text('PERSISTENCE_MODE="' + value + '"\n')
    else:
        monkeypatch.setenv("REGISTRY_PERSISTENCE_MODE", value)
    conf = app_config.get_persistence_conf()
    assert conf["persistence.mode"] == mode
    if mode == "sqlite":
        assert conf["sqlite.path"] == str(runtime / "selected.db")
    elif name:
        prefix = connection_profiles.PREFIXES[name]
        assert conf[prefix + (".database" if mode == "gauss" else ".name")] == "selected_db"
        assert conf[prefix + ".username"] == "selected_user"
        assert conf[prefix + ".password"] == "synthetic"


@pytest.mark.parametrize("mode", ["", "unknown", "gaussdb", "mysql_typo"])
def test_invalid_mode_rejected_before_profile_loading(runtime, monkeypatch, mode):
    monkeypatch.setenv("PERSISTENCE_MODE", mode)
    def fail(*args, **kwargs):
        pytest.fail("Invalid mode must not load any connection profile")
    monkeypatch.setattr(connection_profiles, "provider_config", fail)
    with pytest.raises(ValueError, match="Unknown persistence.mode"):
        app_config.get_persistence_conf()


@pytest.mark.parametrize("source", ["json", "dotenv", "process"])
def test_sqlite_memory_profile_reaches_real_in_memory_database(runtime, monkeypatch, source):
    from agent_registry.persistence.sqlite_storage import SQLiteStorage
    (runtime / "etc/conf/persistence.conf").write_text("persistence.mode=sqlite\n")
    if source == "json":
        put(runtime, "sqlite", {"path": ":memory:"})
    elif source == "dotenv":
        (runtime / ".env").write_text("SQLITE_PATH=:memory:\n")
    else:
        monkeypatch.setenv("REGISTRY_SQLITE_PATH", ":memory:")
    conf = app_config.get_persistence_conf()
    assert conf["sqlite.path"] == ":memory:"
    storage = SQLiteStorage.init(conf)
    try:
        assert storage._conn.execute("PRAGMA database_list").fetchone()[2] == ""
        storage._conn.execute("CREATE TABLE review_probe (value INTEGER)")
        storage._conn.execute("INSERT INTO review_probe VALUES (42)")
        storage._conn.commit()
        assert storage._conn.execute("SELECT value FROM review_probe").fetchone() == (42,)
        assert not (runtime / "data/agents.db").exists()
    finally:
        storage.close()


def test_sqlite_absolute_path_preserved(runtime):
    from agent_registry.persistence.sqlite_storage import SQLiteStorage
    target = runtime / "external" / "selected.db"
    put(runtime, "sqlite", {"path": str(target)})
    conf = connection_profiles.provider_config("sqlite", runtime)
    assert conf["sqlite.path"] == str(target)
    storage = SQLiteStorage.init(conf)
    try:
        assert target.exists()
    finally:
        storage.close()
