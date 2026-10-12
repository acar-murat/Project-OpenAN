# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Connection profiles owned by the orchestration storage boundary."""
from common.util.database_config import DatabaseProfile, load_profile
from common.util.config_util import get_root_path

COMMON = dict(host="127.0.0.1", database="orchestration_center", connect_timeout=10)
BOUNDS = dict(port=(1, 65535), connect_timeout=(1, 86400))
PROFILES = {
    "postgresql": DatabaseProfile(
        {**COMMON, "port": 5432},
        {"host": ("POSTGRES_HOST", "DB_HOST"), "port": ("POSTGRES_PORT", "DB_PORT"),
         "database": ("POSTGRES_DATABASE", "DB_NAME"), "user": ("POSTGRES_USER", "DB_USERNAME"),
         "connect_timeout": ("POSTGRES_CONNECT_TIMEOUT", "PG_CONNECT_TIMEOUT", "DB_CONNECT_TIMEOUT"),
         "sslmode": ("POSTGRES_SSLMODE",), "sslrootcert": ("POSTGRES_SSLROOTCERT",)},
        {"password": ("POSTGRES_PASSWORD", "DB_PASSWORD")}, ("user", "password"), BOUNDS,
        ("sslrootcert",)),
    "mysql": DatabaseProfile(
        {**COMMON, "port": 3306, "pool_min": 1, "pool_max": 20,
         "read_timeout": 30, "write_timeout": 30, "ssl_ca": ""},
        {"host": ("MYSQL_HOST", "DB_HOST"), "port": ("MYSQL_PORT", "DB_PORT"),
         "database": ("MYSQL_DATABASE", "DB_NAME"), "user": ("MYSQL_USER", "DB_USERNAME"),
         "pool_min": ("MYSQL_POOL_MIN", "DB_POOL_MIN"), "pool_max": ("MYSQL_POOL_MAX", "DB_POOL_MAX"),
         "connect_timeout": ("MYSQL_CONNECT_TIMEOUT", "DB_CONNECT_TIMEOUT"),
         "read_timeout": ("MYSQL_READ_TIMEOUT",), "write_timeout": ("MYSQL_WRITE_TIMEOUT",),
         "ssl_ca": ("MYSQL_SSL_CA",)},
        {"password": ("MYSQL_PASSWORD", "DB_PASSWORD")}, ("user", "password"),
        {**BOUNDS, "pool_min": (0, 10000), "pool_max": (1, 10000),
         "read_timeout": (1, 86400), "write_timeout": (1, 86400)}, ("ssl_ca",)),
}


def load_connection_config(mode, root=None):
    if mode not in PROFILES:
        raise ValueError("Unsupported SQL connection profile")
    return load_profile(mode, PROFILES[mode], root or get_root_path())

