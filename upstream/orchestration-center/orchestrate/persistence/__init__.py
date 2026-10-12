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

"""Storage ports the application owns, and the backends that implement them.

Importing this package must stay cheap and driver-free: the concrete backends
(and therefore ``psycopg2``/``pymysql``) are imported lazily by
:func:`orchestrate.persistence.factory.create`, so a file-mode deployment never
pays for a database driver it does not use.

The application layer should depend on :class:`StorageContext` and the port
interfaces below -- never on ``database.utils.*`` and never on
``persistence_mode`` directly.
"""

from orchestrate.persistence.contracts import (
    Capability,
    ExecutionRecordRepository,
    PersistenceBackend,
    PreflowRepository,
    PsopRepository,
    UserRepository,
)
from orchestrate.persistence.context import StorageContext, configure_context, current_context
from orchestrate.persistence.errors import (
    StorageConfigError,
    StorageConflictError,
    StorageCorruptionError,
    StorageError,
    StorageUnavailableError,
    StorageValidationError,
)
from orchestrate.persistence.factory import build_context
from orchestrate.persistence.factory import create as create_backend
from orchestrate.persistence.factory import known_modes, register

__all__ = [
    "Capability",
    "ExecutionRecordRepository",
    "PersistenceBackend",
    "PreflowRepository",
    "PsopRepository",
    "StorageConfigError",
    "StorageConflictError",
    "StorageContext",
    "StorageCorruptionError",
    "StorageError",
    "StorageUnavailableError",
    "StorageValidationError",
    "UserRepository",
    "build_context",
    "configure_context",
    "create_backend",
    "current_context",
    "known_modes",
    "register",
]
