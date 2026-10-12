# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Application dispatch bound to the configured storage, not global DB settings."""
from common.custom import BaseHandler, InterfaceType
from orchestrate.persistence.context import current_context


class _StorageHandler(BaseHandler):
    def __init__(self, interface_type: InterfaceType):
        self._interface_type = interface_type

    def handle(self, *args, **kwargs):
        # Resolve on invocation: cached proxies must not retain an old backend
        # or bypass an extension registered after their creation.
        from common.custom import HandlerRegistry

        context = current_context()
        with context.backend.operation_scope():
            handler = HandlerRegistry.get_handler(self._interface_type, mode=context.mode)
            return handler.handle(*args, **kwargs)


def get_storage_handler(interface_type: InterfaceType) -> BaseHandler:
    """Return a lazy handler whose complete call uses the current backend."""
    return _StorageHandler(interface_type)
