# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Pure persistence selector rules shared by configuration and runtime."""
SQL_PERSISTENCE_MODES = ('postgresql', 'sqlite', 'gauss', 'mysql')
FILE_PERSISTENCE_MODE = 'file'
KNOWN_PERSISTENCE_MODES = (FILE_PERSISTENCE_MODE,) + SQL_PERSISTENCE_MODES


def validate_persistence_mode(mode: str) -> str:
    """Normalize before profile selection; never silently select another store."""
    normalized = str(mode or '').strip().lower()
    if normalized not in KNOWN_PERSISTENCE_MODES:
        raise ValueError(
            f"Unknown persistence.mode '{mode}'. "
            f"Supported: {', '.join(KNOWN_PERSISTENCE_MODES)}"
        )
    return normalized
