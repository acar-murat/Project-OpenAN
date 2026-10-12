# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Actual handler dispatch, not a patched repository-only connection source."""
from types import SimpleNamespace

import pytest

from common.custom import HandlerRegistry, InterfaceType
from common.util import persistence_mode
from database.utils import connection_provider
from orchestrate.core.shared_handlers import SharedHandlers
from orchestrate.handlers import db_handlers
from orchestrate.handlers.dispatch import get_storage_handler
from orchestrate.persistence import context, StorageContext
from orchestrate.persistence.sql_backend import SqlPersistenceBackend


@pytest.fixture
def bound_backend(monkeypatch):
    backend = SqlPersistenceBackend("mysql", {"connection_config": {"database": "bound_db"}})
    monkeypatch.setattr(context, "_persistence_context", StorageContext(backend))
    # This global mode deliberately disagrees with the configured instance.
    monkeypatch.setattr(persistence_mode, "get_conf", lambda: {"persistence_mode": "file"})
    for attr in ("_save_handle", "_delete_handle", "_retrieval"):
        monkeypatch.setattr(SharedHandlers, attr, None)
    return backend


@pytest.mark.parametrize("method,processor", [("save_psop", "custom_save_psop"),
                                             ("delete_psop", "custom_delete_psop")])
def test_shared_handlers_use_context_mode_and_provider(bound_backend, monkeypatch, method, processor):
    def probe(*args):
        assert connection_provider.current_provider() is bound_backend._provider
        return "bound"
    monkeypatch.setattr(db_handlers, processor, probe)
    assert getattr(SharedHandlers, method)().handle(SimpleNamespace()) == "bound"
    assert connection_provider.current_provider() is None


def test_cached_shared_handler_resolves_current_context_at_execution(bound_backend, monkeypatch):
    def probe(*args):
        return connection_provider.current_provider().config["database"]
    monkeypatch.setattr(db_handlers, "custom_save_psop", probe)
    handler = SharedHandlers.save_psop()
    assert handler.handle(None) == "bound_db"
    other = SqlPersistenceBackend("postgresql", {"connection_config": {"database": "other_db"}})
    monkeypatch.setattr(context, "_persistence_context", StorageContext(other))
    assert handler.handle(None) == "other_db"


def test_extension_subclass_calls_super_once_with_bound_provider(bound_backend, monkeypatch):
    seen = []
    class Extension(db_handlers.CustomSavePsopHandler):
        def handle(self, *args, **kwargs):
            seen.append("extension")
            return super().handle(*args, **kwargs)
    def probe(*args, **kwargs):
        assert connection_provider.current_provider() is bound_backend._provider
        seen.append("processor")
        return "saved"
    monkeypatch.setattr(db_handlers, "custom_save_psop", probe)
    monkeypatch.setattr(HandlerRegistry, "_overrides", dict(HandlerRegistry._overrides))
    monkeypatch.setattr(HandlerRegistry, "_bundled_overrides", dict(HandlerRegistry._bundled_overrides))
    handler = SharedHandlers.save_psop()
    HandlerRegistry.register(InterfaceType.SAVE_PSOP, Extension)
    assert handler.handle(None) == "saved"
    assert seen == ["extension", "processor"]


def test_failure_does_not_leak_provider(bound_backend, monkeypatch):
    def fail(*args):
        assert connection_provider.current_provider() is bound_backend._provider
        raise RuntimeError("synthetic")
    monkeypatch.setattr(db_handlers, "custom_save_psop", fail)
    with pytest.raises(RuntimeError, match="synthetic"):
        SharedHandlers.save_psop().handle(None)
    assert connection_provider.current_provider() is None


@pytest.mark.parametrize("mode", ["mysql", "postgresql"])
@pytest.mark.parametrize("interface,processor", [
    (InterfaceType.SAVE_PSOP, "custom_save_psop"),
    (InterfaceType.DELETE_PSOP, "custom_delete_psop"),
    (InterfaceType.GET_ALL_PSOP, "get_all_psops"),
    (InterfaceType.GET_PSOP_BY_ID, "get_psop_by_id"),
    (InterfaceType.SAVE_EXECUTION_RECORD, "db_save_execution_record"),
    (InterfaceType.LIST_EXECUTION_RECORDS, "db_list_execution_records"),
    (InterfaceType.GET_EXECUTION_RECORD, "db_get_execution_record"),
    (InterfaceType.DELETE_EXECUTION_RECORD, "db_delete_execution_record"),
])
def test_all_handlers_bind_mode_dialect_and_restore_outer_scope(monkeypatch, mode, interface, processor):
    from database.utils.sql_dialect import upsert_sql
    backend = SqlPersistenceBackend(mode, {"connection_config": {"database": "selected"}})
    monkeypatch.setattr(context, "_persistence_context", StorageContext(backend))
    monkeypatch.setattr(persistence_mode, "get_conf", lambda: {"persistence_mode": "file"})
    def probe(*args, **kwargs):
        assert connection_provider.current_provider() is backend._provider
        assert persistence_mode.persistence_mode() == mode
        sql = upsert_sql("psop", "id", ("id", "name"))
        assert ("ON DUPLICATE KEY" in sql) == (mode == "mysql")
        return args, kwargs
    monkeypatch.setattr(db_handlers, processor, probe)
    outer = object()
    with connection_provider.connection_scope(outer):
        assert get_storage_handler(interface).handle("probe", flag=True) == (("probe",), {"flag": True})
        assert connection_provider.current_provider() is outer
    assert connection_provider.current_provider() is None


def test_file_dispatch_does_not_construct_sql_provider(monkeypatch):
    from orchestrate.persistence.file_backend import FilePersistenceBackend
    from orchestrate.handlers import file_handlers
    monkeypatch.setattr(context, "_persistence_context", StorageContext(FilePersistenceBackend()))
    monkeypatch.setattr(persistence_mode, "get_conf", lambda: {"persistence_mode": "mysql"})
    monkeypatch.setattr(connection_provider.SqlConnectionProvider, "__init__",
                        lambda *args, **kwargs: pytest.fail("File dispatch must not construct SQL resources"))
    monkeypatch.setattr(file_handlers.SavePsopHandler, "handle", lambda *args: "file")
    assert get_storage_handler(InterfaceType.SAVE_PSOP).handle(None) == "file"


def test_concurrent_dispatch_does_not_cross_instance_scopes(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier, local
    from orchestrate.handlers import dispatch

    selected, barrier = local(), Barrier(2)
    monkeypatch.setattr(dispatch, "current_context", lambda: selected.context)
    monkeypatch.setattr(persistence_mode, "get_conf", lambda: {"persistence_mode": "file"})
    def probe(*args):
        provider = connection_provider.current_provider()
        barrier.wait(timeout=5)
        assert connection_provider.current_provider() is provider
        return provider.mode, provider.config["database"]
    monkeypatch.setattr(db_handlers, "custom_save_psop", probe)
    def call(mode):
        backend = SqlPersistenceBackend(mode, {"connection_config": {"database": mode + "_db"}})
        selected.context = StorageContext(backend)
        try:
            result = get_storage_handler(InterfaceType.SAVE_PSOP).handle(None)
            assert connection_provider.current_provider() is None
            return result
        finally:
            backend.close()
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(call, ("mysql", "postgresql")))
    assert results == [("mysql", "mysql_db"), ("postgresql", "postgresql_db")]
