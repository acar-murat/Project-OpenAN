# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Connection/dialect/cache ownership regressions without live DB credentials."""
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock

import pytest

from database.utils import connection_provider, user_store, sql_dialect, db_connection
from orchestrate.handlers import psop_processor
from orchestrate.persistence.sql_backend import SqlPersistenceBackend


def test_concurrent_repositories_use_their_own_provider(monkeypatch):
    pg = SqlPersistenceBackend("postgresql", {"connection_config": {"database": "first"}})
    mysql = SqlPersistenceBackend("mysql", {"connection_config": {"database": "second"}})
    def probe():
        provider = connection_provider.current_provider()
        statement = sql_dialect.upsert_sql("psop", "id", ("id", "name"))
        return provider.config["database"], ("ON DUPLICATE" in statement)
    monkeypatch.setattr(psop_processor, "get_all_psops", probe)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(backend.psops().list_summaries) for backend in (pg, mysql) * 10]
        assert [future.result() for future in futures] == [("first", False), ("second", True)] * 10
    assert connection_provider.current_provider() is None


def test_exception_resets_scope(monkeypatch):
    backend = SqlPersistenceBackend("mysql")
    def fail():
        raise RuntimeError("fixture")
    monkeypatch.setattr(psop_processor, "get_all_psops", fail)
    with pytest.raises(RuntimeError):
        backend.psops().list_summaries()
    assert connection_provider.current_provider() is None


def test_user_presence_is_not_shared_across_databases(monkeypatch):
    first = SqlPersistenceBackend("mysql")
    second = SqlPersistenceBackend("postgresql")
    first._provider.users_observed = True
    monkeypatch.setattr(user_store, "_any_user_exists_cache", True)
    monkeypatch.setattr(user_store, "create_connection", lambda: MagicMock())
    monkeypatch.setattr(user_store, "execute_query", lambda *args: ([], None))
    assert first.users().has_any() is True
    assert second.users().has_any() is False


def test_config_resolves_once_per_backend_and_close_is_owned(monkeypatch):
    seen = []
    monkeypatch.setattr(connection_provider, "load_connection_config",
                        lambda mode: seen.append(mode) or {"user": "fixture"})
    first = connection_provider.SqlConnectionProvider("mysql")
    second = connection_provider.SqlConnectionProvider("mysql")
    assert first.config == first.config
    assert seen == ["mysql"]
    assert second.config == first.config
    assert seen == ["mysql", "mysql"]
    first._mysql, second._mysql = MagicMock(), MagicMock()
    pool = first._mysql
    first.close()
    first.close()
    pool.close.assert_called_once()
    second._mysql.close.assert_not_called()
    with pytest.raises(RuntimeError, match="closed"):
        first.connection()


def test_startup_seed_uses_user_port(monkeypatch):
    from orchestrate import start
    users = MagicMock()
    users.has_any.return_value = False
    monkeypatch.setattr(start, "current_context", lambda: MagicMock(users=users))
    assert start.seed_admin_if_empty("fixture")
    users.create.assert_called_once_with("admin", "fixture", "admin", True)

