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

"""Bundled storage handlers and their registration.

Importing this package registers the handler implementations with
:class:`~common.custom.default_handle.HandlerRegistry`:

- ``file_handlers`` become the *defaults* used when
  ``persistence_mode=file``;
- ``db_handlers`` become the *overrides* used in database mode.

Processes that dispatch through ``HandlerRegistry.get_handler`` must import
this package once (the backend app and the sample-agent server both do).
Third-party overrides register the same way, in their own module.
"""

from common.custom.default_handle import HandlerRegistry
from common.custom.interface_type import InterfaceType
from orchestrate.handlers import db_handlers, file_handlers  # noqa: F401  (side effects used below)

HandlerRegistry.register_default(InterfaceType.SAVE_PSOP, file_handlers.SavePsopHandler)
HandlerRegistry.register_default(InterfaceType.DELETE_PSOP, file_handlers.DeletePsopHandler)
HandlerRegistry.register_default(InterfaceType.GET_ALL_PSOP, file_handlers.GetAllPsopsHandler)
HandlerRegistry.register_default(InterfaceType.GET_PSOP_BY_ID, file_handlers.GetPsopHandler)
HandlerRegistry.register_default(InterfaceType.SAVE_EXECUTION_RECORD, file_handlers.SaveExecutionRecordHandler)
HandlerRegistry.register_default(InterfaceType.LIST_EXECUTION_RECORDS, file_handlers.ListExecutionRecordsHandler)
HandlerRegistry.register_default(InterfaceType.GET_EXECUTION_RECORD, file_handlers.GetExecutionRecordHandler)
HandlerRegistry.register_default(InterfaceType.DELETE_EXECUTION_RECORD, file_handlers.DeleteExecutionRecordHandler)

HandlerRegistry.register(InterfaceType.SAVE_PSOP, db_handlers.CustomSavePsopHandler, bundled=True)
HandlerRegistry.register(InterfaceType.DELETE_PSOP, db_handlers.CustomDeletePsopHandler, bundled=True)
HandlerRegistry.register(InterfaceType.GET_ALL_PSOP, db_handlers.CustomGetAllPsopsHandler, bundled=True)
HandlerRegistry.register(InterfaceType.GET_PSOP_BY_ID, db_handlers.CustomGetPsopHandler, bundled=True)
HandlerRegistry.register(InterfaceType.SAVE_EXECUTION_RECORD, db_handlers.CustomSaveExecutionRecordHandler, bundled=True)
HandlerRegistry.register(InterfaceType.LIST_EXECUTION_RECORDS, db_handlers.CustomListExecutionRecordsHandler, bundled=True)
HandlerRegistry.register(InterfaceType.GET_EXECUTION_RECORD, db_handlers.CustomGetExecutionRecordHandler, bundled=True)
HandlerRegistry.register(InterfaceType.DELETE_EXECUTION_RECORD, db_handlers.CustomDeleteExecutionRecordHandler, bundled=True)

__all__ = ["db_handlers", "file_handlers"]
