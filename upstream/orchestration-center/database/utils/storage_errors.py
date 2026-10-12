# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Classify actual SQL failures without probing or importing optional drivers."""

from typing import NoReturn
from loguru import logger

from orchestrate.persistence.errors import (
    StorageConflictError, StorageError, StorageUnavailableError, StorageValidationError,
)


def require_connection(conn):
    if conn is None:
        raise StorageUnavailableError("Unable to connect to database")
    return conn


def close_resource(resource) -> None:
    """Cleanup must not replace an operation's result or its classified error."""
    try:
        resource.close()
    except Exception:
        logger.warning("Database resource cleanup failed")


def classify_error(error: Exception, operation: str) -> StorageError:
    if isinstance(error, StorageError):
        return error
    state = getattr(error, "pgcode", None) or getattr(error, "sqlstate", None)
    code = error.args[0] if error.args and isinstance(error.args[0], int) else None
    driver = type(error).__module__
    base_names = {base.__name__ for base in type(error).__mro__}
    connection_failure = (
        driver.startswith("psycopg2") and state is None
        and bool(base_names & {"OperationalError", "InterfaceError"})
    ) or (driver.startswith("pymysql") and "InterfaceError" in base_names) or (
        driver.startswith("dbutils") and "TooManyConnectionsError" in base_names
    )
    if connection_failure or isinstance(error, (ConnectionError, TimeoutError, OSError)) or (
        isinstance(state, str) and (state.startswith("08") or state in {
            "53300", "53400", "57P01", "57P02", "57P03", "57014", "40001", "40P01",
        })
    ) or code in {1040, 1042, 1047, 1158, 1159, 1160, 1161, 1205, 1213, 2002, 2003, 2006, 2013, 2055}:
        return StorageUnavailableError(f"{operation}: storage unavailable")
    if state == "23505" or code == 1062:
        return StorageConflictError(f"{operation}: record already exists")
    if (isinstance(state, str) and state.startswith("22")) or code in {1264, 1366, 1406}:
        return StorageValidationError(f"{operation}: invalid stored value")
    # Permission, SQL syntax and programming failures are not transient outages.
    # Never expose a driver message, query, connection string or credential.
    return StorageError(f"{operation}: database operation failed")


def raise_storage_error(error: Exception, operation: str) -> NoReturn:
    mapped = classify_error(error, operation)
    if mapped is error:
        raise mapped
    raise mapped from error
