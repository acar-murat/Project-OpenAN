# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
# SPDX-License-Identifier: Apache-2.0
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""Single source of truth for the ``persistence_mode`` configuration flag.

``persistence_mode`` selects the workflow-storage backend: ``file`` (default)
keeps JSON documents under ``data/workflow_storage/``; ``postgresql`` or ``mysql`` switches
the pluggable handlers to the database-backed implementations (and, for consumers
that reach the database outside those handlers, such as the user store, whether the
database is available at all).

Every check that used to compare the raw config string inline now goes through
:meth:`is_db_mode`, so renaming the flag or adding a mode touches one file.
Use :meth:`validate_storage_mode` at startup to reject unknown values loudly
instead of silently falling back to file storage.
"""

from common.util.config_util import get_conf

DEFAULT_STORAGE_MODE = "file"

#: Every persistence_mode value this service understands.
KNOWN_STORAGE_MODES = frozenset({"file", "postgresql", "mysql"})


def persistence_mode() -> str:
    """Return the lowercased ``persistence_mode`` config value."""
    # The SQL helpers use the same instance-scoped dialect as the connection.
    from database.utils.connection_provider import current_provider
    provider = current_provider()
    if provider is not None:
        return provider.mode
    return str(get_conf().get("persistence_mode", DEFAULT_STORAGE_MODE)).lower()


def is_db_mode(conf: "dict | None" = None) -> bool:
    """True when storage goes through the database-backed handlers.

    ``conf`` lets callers evaluate the predicate against a config mapping
    they already hold (and lets tests inject one); it defaults to the
    process configuration.
    """
    source = conf if conf is not None else get_conf()
    mode = str(source.get("persistence_mode", DEFAULT_STORAGE_MODE)).lower()
    return mode != DEFAULT_STORAGE_MODE


def validate_storage_mode() -> str:
    """Raise ValueError for an unknown persistence_mode; return the mode."""
    mode = persistence_mode()
    if mode not in KNOWN_STORAGE_MODES:
        raise ValueError(
            f"Unsupported persistence_mode '{mode}'; expected one of {sorted(KNOWN_STORAGE_MODES)}"
        )
    return mode
