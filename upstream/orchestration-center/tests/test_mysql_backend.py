# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""MySQL configuration, resource and dialect contracts without a live server."""

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from database.utils import db_connection, mysql_connection, sql_dialect, table_creation
from database.utils.query_execution import execute_query


@pytest.fixture
def mysql_mode(monkeypatch):
    from common.util import persistence_mode
    monkeypatch.setattr(persistence_mode, "get_conf", lambda: {"persistence_mode": "mysql"})


@pytest.fixture
def backend_dependencies(monkeypatch):
    connect = MagicMock()
    cursor = connect.return_value.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = None
    pool = MagicMock()
    monkeypatch.setattr(mysql_connection.pymysql, "connect", connect)
    monkeypatch.setattr(mysql_connection, "PooledDB", pool)
    return connect, pool


def test_mysql_facade_never_calls_postgres(mysql_mode, monkeypatch):
    backend = MagicMock()
    monkeypatch.setattr(mysql_connection, "get_backend", lambda: backend)
    postgres = MagicMock(side_effect=AssertionError("PostgreSQL must not be used"))
    monkeypatch.setattr(db_connection.psycopg2, "connect", postgres)
    assert db_connection.create_connection() is backend.connection.return_value
    table_creation.create_tables()
    backend.create_tables.assert_called_once()
    postgres.assert_not_called()


def test_unavailable_mysql_does_not_fall_back(mysql_mode, monkeypatch):
    monkeypatch.setattr(mysql_connection, "get_backend", MagicMock(side_effect=RuntimeError("unavailable")))
    postgres = MagicMock()
    monkeypatch.setattr(db_connection.psycopg2, "connect", postgres)
    assert db_connection.create_connection() is None
    with pytest.raises(RuntimeError, match="unavailable"):
        table_creation.create_tables()
    postgres.assert_not_called()


def test_pool_transaction_and_configuration(backend_dependencies):
    connect, pool = backend_dependencies
    backend = mysql_connection.MySQLBackend({"user": "tester", "password": "test-secret"})
    options = pool.call_args.kwargs
    assert options["charset"] == "utf8mb4"
    assert options["autocommit"] is False
    assert options["blocking"] is False
    assert options["reset"] is True
    assert options["ping"] == 1
    assert options["maxconnections"] == 20
    assert options["read_timeout"] == options["write_timeout"] == 30
    assert options["ssl_disabled"] is True
    conn = backend.connection()
    conn.begin.assert_called_once()
    backend.close()
    backend.pool.close.assert_called_once()
    connect.return_value.close.assert_called_once()


def test_tls_verifies_ca_and_hostname(backend_dependencies):
    connect, pool = backend_dependencies
    mysql_connection.MySQLBackend({"user": "tester", "ssl_ca": "trusted.pem"})
    for options in (connect.call_args.kwargs, pool.call_args.kwargs):
        assert options["ssl_verify_cert"] is True
        assert options["ssl_verify_identity"] is True
        assert "ssl_disabled" not in options


@pytest.mark.parametrize("overrides", [
    {"database": "invalid`;DROP DATABASE other"}, {"pool_max": 0},
    {"pool_min": 5, "pool_max": 2}, {"read_timeout": 0},
    {"connect_timeout": -1}, {"port": 70000}, {"user": "<YOUR_DB_USERNAME>"},
])
def test_invalid_settings_fail_before_connect(overrides, backend_dependencies):
    connect, _ = backend_dependencies
    with pytest.raises(ValueError):
        mysql_connection.MySQLBackend({"user": "tester", **overrides})
    connect.assert_not_called()


def test_failed_maintenance_always_closes_connection(backend_dependencies):
    connect, pool = backend_dependencies
    cursor = connect.return_value.cursor.return_value.__enter__.return_value
    cursor.execute.side_effect = RuntimeError("failure")
    with pytest.raises(RuntimeError):
        mysql_connection.MySQLBackend({"user": "tester"})
    connect.return_value.close.assert_called_once()
    pool.assert_not_called()


def test_failed_begin_returns_connection(backend_dependencies):
    _, pool = backend_dependencies
    backend = mysql_connection.MySQLBackend({"user": "tester"})
    conn = pool.return_value.connection.return_value
    conn.begin.side_effect = RuntimeError("failure")
    with pytest.raises(RuntimeError):
        backend.connection()
    conn.close.assert_called_once()


def test_ddl_handles_legacy_users_without_postgres_syntax(backend_dependencies):
    backend = mysql_connection.MySQLBackend({"user": "tester"})
    conn = backend.pool.connection.return_value
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = [("username",), ("password_hash",)]
    backend.create_tables()
    statements = [call.args[0] for call in cursor.execute.call_args_list]
    assert any("AUTO_INCREMENT" in sql for sql in statements)
    assert sum("ADD COLUMN" in sql for sql in statements) == 2
    assert not any("ADD COLUMN IF NOT EXISTS" in sql or "SERIAL" in sql for sql in statements)
    assert any("record_content LONGTEXT" in sql for sql in statements)
    conn.commit.assert_called_once()
    conn.close.assert_called_once()


def test_config_env_overrides_file_and_keeps_password_out_of_template(monkeypatch, tmp_path):
    monkeypatch.setattr(mysql_connection, "get_root_path", lambda: str(tmp_path))
    env = {"MYSQL_USER": "env-user", "MYSQL_PASSWORD": "env-secret", "MYSQL_PORT": "3307"}
    from common.util import database_config
    monkeypatch.setattr(database_config, "dotenv_values", lambda path, **kwargs: {"MYSQL_PASSWORD": "dotenv-secret"})
    monkeypatch.setattr(mysql_connection.os, "environ", env)
    config_path = tmp_path / "etc" / "conf" / "db" / "mysql.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(json.dumps({"host": "db", "user": "file-user", "password_env": "MYSQL_PASSWORD"}))
    config = mysql_connection.load_mysql_config()
    assert config["host"] == "db"
    assert config["user"] == "env-user"
    assert config["password"] == "env-secret"
    assert config["port"] == 3307
    template = Path(__file__).resolve().parents[1] / "etc/conf/db/mysql.json.template"
    assert "password" not in json.loads(template.read_text())
    assert "password_env" in json.loads(template.read_text())


def test_missing_secret_fails_and_explicit_empty_password_is_supported(monkeypatch, tmp_path):
    monkeypatch.setattr(mysql_connection, "get_root_path", lambda: str(tmp_path))
    from common.util import database_config
    monkeypatch.setattr(database_config, "dotenv_values", lambda path, **kwargs: {})
    monkeypatch.setattr(mysql_connection.os, "environ", {})
    with pytest.raises(ValueError, match="MYSQL_PASSWORD.*not set"):
        mysql_connection.load_mysql_config()
    monkeypatch.setattr(mysql_connection.os, "environ", {"MYSQL_PASSWORD": "", "MYSQL_USER": "fixture"})
    assert mysql_connection.load_mysql_config()["password"] == ""


def test_mysql_upsert_null_comparison_and_utc(mysql_mode):
    sql = sql_dialect.upsert_sql("psop", "id", ("id", "name", "psop_content"))
    assert "ON DUPLICATE KEY UPDATE" in sql and "AS incoming" in sql
    assert "VALUES(name)" not in sql and "ON CONFLICT" not in sql
    assert sql.count("%s") == 3
    assert sql_dialect.null_safe_equal("password_scheme") == "password_scheme <=> %s"
    value = datetime(2026, 10, 9, 8, 10, tzinfo=timezone(timedelta(hours=8)))
    timestamp = sql_dialect.timestamp_parameter(value)
    assert timestamp == datetime(2026, 10, 9, 0, 10)
    assert sql_dialect.timestamp_iso(timestamp) == "2026-10-09T00:10:00+00:00"
    assert sql_dialect.timestamp_parameter(None) is None


def test_failed_query_rolls_back_before_reuse():
    conn = MagicMock()
    conn.cursor.return_value.execute.side_effect = RuntimeError("bad query")
    _, error = execute_query(conn, "INSERT INTO psop VALUES (%s)", ("id",))
    assert error is not None
    conn.rollback.assert_called_once()
    conn.cursor.return_value.close.assert_called_once()


def test_mysql_config_excluded_from_git_and_container():
    root = Path(__file__).resolve().parents[1]
    for name in (".gitignore", ".dockerignore"):
        assert "etc/conf/mysql_config.json" in (root / name).read_text().splitlines()


def test_environment_only_config_without_materializing_files(monkeypatch, tmp_path):
    monkeypatch.setattr(mysql_connection, "get_root_path", lambda: str(tmp_path))
    from common.util import database_config
    monkeypatch.setattr(database_config, "dotenv_values", lambda path, **kwargs: {})
    monkeypatch.setattr(mysql_connection.os, "environ", {
        "MYSQL_HOST": "test-db", "MYSQL_USER": "tester", "MYSQL_PASSWORD": "secret",
        "MYSQL_DATABASE": "test_schema",
    })
    config = mysql_connection.load_mysql_config()
    assert {key: config[key] for key in ("host", "user", "password", "database")} == {
        "host": "test-db", "user": "tester", "password": "secret", "database": "test_schema",
    }
    assert list(tmp_path.iterdir()) == []


def test_singleton_closes_and_can_be_reinitialized(monkeypatch):
    factory = MagicMock()
    monkeypatch.setattr(mysql_connection, "MySQLBackend", factory)
    monkeypatch.setattr(mysql_connection, "load_mysql_config", lambda: {"user": "tester"})
    monkeypatch.setattr(mysql_connection, "_backend", None)
    first = mysql_connection.get_backend()
    assert mysql_connection.get_backend() is first
    assert factory.call_count == 1
    mysql_connection.close_backend()
    first.close.assert_called_once()
    mysql_connection.get_backend()
    assert factory.call_count == 2


def test_failed_initialization_is_not_cached(monkeypatch):
    factory = MagicMock(side_effect=[RuntimeError("unavailable"), MagicMock()])
    monkeypatch.setattr(mysql_connection, "MySQLBackend", factory)
    monkeypatch.setattr(mysql_connection, "load_mysql_config", lambda: {"user": "tester"})
    monkeypatch.setattr(mysql_connection, "_backend", None)
    with pytest.raises(RuntimeError):
        mysql_connection.get_backend()
    assert mysql_connection._backend is None
    assert mysql_connection.get_backend() is not None


def test_failed_rollback_preserves_original_query_error():
    conn = MagicMock()
    original = RuntimeError("query failed")
    conn.cursor.return_value.execute.side_effect = original
    conn.rollback.side_effect = RuntimeError("connection gone")
    _, error = execute_query(conn, "INSERT INTO psop VALUES (%s)", ("id",))
    assert error is original
    conn.cursor.return_value.close.assert_called_once()
