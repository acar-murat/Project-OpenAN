# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Instance-bound SQL resources with a scoped adapter for the shared SQL processors.

The context is reset after each operation (including exceptions), so concurrent
requests/backends never inherit another instance's connection or SQL dialect.
"""
from contextlib import contextmanager
from contextvars import ContextVar
import threading

from database.utils.connection_config import load_connection_config

_provider = ContextVar("sql_connection_provider", default=None)


def current_provider():
    return _provider.get()


@contextmanager
def connection_scope(provider):
    token = _provider.set(provider)
    try:
        yield
    finally:
        _provider.reset(token)


class SqlConnectionProvider:
    def __init__(self, mode, config=None):
        self.mode = mode
        self._config = dict(config) if config is not None else None
        self._mysql = None
        self._verified = False
        self._closed = False
        self.users_observed = False
        self._lock = threading.RLock()

    @property
    def config(self):
        with self._lock:
            if self._config is None:
                self._config = load_connection_config(self.mode)
            return self._config

    def connection(self):
        import psycopg2
        from psycopg2 import sql
        from database.utils.db_connection import validate_database_name
        with self._lock:
            if self._closed:
                raise RuntimeError("Storage backend has been closed")
            if self.mode == "mysql":
                return self.mysql_backend().connection()
            config = self.config
            database = validate_database_name(config["database"])
            if not self._verified:
                conn = psycopg2.connect(**{**config, "database": "postgres"})
                try:
                    conn.autocommit = True
                    with conn.cursor() as cursor:
                        cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", (database,))
                        if cursor.fetchone() is None:
                            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
                finally:
                    conn.close()
                self._verified = True
        return psycopg2.connect(**config)

    def mysql_backend(self):
        with self._lock:
            if self._closed:
                raise RuntimeError("Storage backend has been closed")
            if self._mysql is None:
                from database.utils.mysql_connection import MySQLBackend
                self._mysql = MySQLBackend(self.config)
            return self._mysql

    def close(self):
        with self._lock:
            self._closed = True
            if self._mysql is not None:
                self._mysql.close()
                self._mysql = None
