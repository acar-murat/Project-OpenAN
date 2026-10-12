# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""MySQL connection/configuration/DDL boundary (MySQL 8.0.19+).

The SQL processors keep their DB-API contract. Each checkout begins a
transaction; close rolls it back and returns the dedicated connection to the
pool. Pool exhaustion fails immediately rather than blocking a request forever.
"""

import os
import threading

import pymysql
from dbutils.pooled_db import PooledDB
from loguru import logger

from common.util.config_util import get_root_path
from database.utils.db_connection import validate_database_name


def load_mysql_config() -> dict:
    from database.utils.connection_config import load_connection_config
    return load_connection_config("mysql", get_root_path())


class MySQLBackend:
    def __init__(self, config: dict):
        database = validate_database_name(config.get("database", "orchestration_center"))
        user = config.get("user")
        if not user or user.startswith("<"):
            raise ValueError("MySQL user must be configured")
        minimum = int(config.get("pool_min", 1))
        maximum = int(config.get("pool_max", 20))
        if not 0 <= minimum <= maximum or maximum < 1:
            raise ValueError("MySQL pool requires 0 <= pool_min <= pool_max and pool_max >= 1")
        options = {
            "host": config.get("host", "127.0.0.1"), "port": int(config.get("port", 3306)),
            "user": user, "password": config.get("password", ""), "charset": "utf8mb4",
            "autocommit": False,
        }
        if not 1 <= options["port"] <= 65535:
            raise ValueError("Invalid MySQL port")
        for name, default in (("connect_timeout", 10), ("read_timeout", 30), ("write_timeout", 30)):
            options[name] = int(config.get(name, default))
            if options[name] <= 0:
                raise ValueError(f"MySQL {name} must be positive")
        # Set SQL mode even on an existing server: oversized values must error,
        # not silently truncate workflow content or IDs.
        options["sql_mode"] = "STRICT_TRANS_TABLES,NO_ENGINE_SUBSTITUTION"
        if config.get("ssl_ca"):
            options.update(ssl_ca=config["ssl_ca"], ssl_verify_cert=True, ssl_verify_identity=True)
        else:
            # Explicit local/development plaintext, not opportunistic unverified TLS.
            options["ssl_disabled"] = True
            logger.warning("MySQL TLS is disabled; configure MYSQL_SSL_CA for a verified production connection")
        maintenance = pymysql.connect(**options)
        try:
            with maintenance.cursor() as cursor:
                cursor.execute("SELECT 1 FROM information_schema.SCHEMATA WHERE SCHEMA_NAME = %s", (database,))
                if cursor.fetchone() is None:
                    cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin")
            maintenance.commit()
        finally:
            maintenance.close()
        self.pool = PooledDB(
            creator=pymysql, mincached=minimum, maxcached=maximum,
            maxconnections=maximum, blocking=False, ping=1, reset=True,
            database=database, **options,
        )

    def connection(self):
        conn = self.pool.connection()
        try:
            # DBUtils disables transparent query replay after begin(): a failed
            # write must not be silently replayed with an uncertain commit outcome.
            conn.begin()
            return conn
        except Exception:
            conn.close()
            raise

    def create_tables(self):
        statements = (
            """CREATE TABLE IF NOT EXISTS psop (
                id VARCHAR(255) COLLATE utf8mb4_0900_bin PRIMARY KEY,
                name VARCHAR(1024) NOT NULL, description LONGTEXT, psop_content LONGTEXT
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_bin""",
            """CREATE TABLE IF NOT EXISTS execution_records (
                execution_id VARCHAR(64) COLLATE utf8mb4_0900_bin PRIMARY KEY,
                psop_id VARCHAR(255) NOT NULL, psop_name VARCHAR(1024),
                started_at DATETIME(6), completed_at DATETIME(6), status VARCHAR(32),
                step_count INTEGER DEFAULT 0, record_content LONGTEXT,
                INDEX idx_execution_started (started_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_bin""",
            """CREATE TABLE IF NOT EXISTS users (
                id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                username VARCHAR(64) COLLATE utf8mb4_0900_bin UNIQUE NOT NULL,
                password_hash VARCHAR(128) NOT NULL, salt VARCHAR(64) NOT NULL,
                role VARCHAR(16) DEFAULT 'user', must_change_password BOOLEAN DEFAULT FALSE,
                password_scheme VARCHAR(16) DEFAULT 'legacy',
                created_at DATETIME(6) DEFAULT CURRENT_TIMESTAMP(6)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_bin""",
        )
        conn = self.connection()
        try:
            with conn.cursor() as cursor:
                for statement in statements:
                    cursor.execute(statement)
                # MySQL does not support ADD COLUMN IF NOT EXISTS. Check metadata
                # for upgrades of legacy users tables; no existing rows are lost.
                cursor.execute("SELECT COLUMN_NAME FROM information_schema.COLUMNS "
                               "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'users'")
                columns = {row[0] for row in cursor.fetchall()}
                for name, definition in (
                    ("must_change_password", "BOOLEAN DEFAULT FALSE"),
                    ("password_scheme", "VARCHAR(16) DEFAULT 'legacy'"),
                ):
                    if name not in columns:
                        try:
                            cursor.execute(f"ALTER TABLE users ADD COLUMN {name} {definition}")
                        except pymysql.err.OperationalError as exc:
                            if exc.args[0] != 1060:  # another startup added the column
                                raise
            conn.commit()
        finally:
            conn.close()

    def close(self):
        self.pool.close()


_backend = None
_lock = threading.Lock()


def get_backend() -> MySQLBackend:
    from database.utils.connection_provider import current_provider
    provider = current_provider()
    if provider is not None:
        return provider.mysql_backend()
    global _backend
    with _lock:
        if _backend is None:
            _backend = MySQLBackend(load_mysql_config())
        return _backend


def close_backend():
    global _backend
    with _lock:
        if _backend is not None:
            _backend.close()
            _backend = None
