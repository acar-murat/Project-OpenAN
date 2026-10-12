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

"""
Audit helpers for the integration access plane.

Every integration operation — success or failure, read or write — produces
an audit record carrying the caller identity (task 4.1 extends the same
identity handling to the main port).
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from common.custom.custom_handle import HandlerRegistry
from common.custom.interface_type import InterfaceType
from common.log.audit_logger import LogLevel, OperationResult, OperatorObject
from common.util.authenticate_util import Principal

_audit_handle = HandlerRegistry.get_handler(InterfaceType.AUDIT)


async def audit_integration(op_name, principal: Principal, success: bool,
                            details: dict, object_name=OperatorObject.AGENT,
                            level=LogLevel.MINOR) -> None:
    """Emit an audit record for a integration operation with caller identity.

    The local audit file is written first (source of truth); the record is
    then mirrored to the customer MySQL sink when configured (async, never
    blocks the request — see audit_sink.py).
    """
    entry = {
        "time": datetime.now(timezone.utc).isoformat(),
        "event_id": uuid.uuid4().hex,
        "operation_name": op_name,
        "level": level,
        "result": OperationResult.SUCCESS if success else OperationResult.FAILURE,
        "object_name": object_name,
        "details": details,
        "client_ip": principal.client_ip,
        "user_name": principal.audit_identity(),
    }
    await _audit_handle.handle(entry)
    from agent_registry.integration.audit_sink import get_audit_sink
    sink = get_audit_sink()
    if sink is not None:
        sink.enqueue(entry)


async def audit_integration_failure(op_name, principal: Principal,
                                    details: dict, object_name=OperatorObject.AGENT) -> None:
    await audit_integration(op_name, principal, False, details, object_name)
