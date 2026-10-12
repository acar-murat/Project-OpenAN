# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""P1-1: an extension that replaces a query handler must still be consumed.

Before this fix, retrieval read through the storage port, and the port called
the bundled query functions directly. A deployment that registered its own
GET_ALL_PSOP / GET_PSOP_BY_ID handler therefore *saved* through that handler and
then failed to read its own rows back, because reads took a different path.

The fix keeps the port as the single read path but lets a registered extension
win, and deliberately never calls the bundled handler from inside the port:
that would dispatch back into the port (circular delegation).
"""

from common.custom.default_handle import BaseHandler, HandlerRegistry
from common.custom.interface_type import InterfaceType
from orchestrate.persistence import StorageContext, create_backend


class _ExtensionListHandler(BaseHandler):
    calls = 0

    def handle(self, *args, **kwargs):
        type(self).calls += 1
        return ["from-extension"]


class _ExtensionByIdHandler(BaseHandler):
    def handle(self, psop_id, *args, **kwargs):
        return f"from-extension:{psop_id}"


def _restore_bundled_handlers():
    from orchestrate.handlers import db_handlers

    HandlerRegistry.register(InterfaceType.GET_ALL_PSOP, db_handlers.CustomGetAllPsopsHandler, bundled=True)
    HandlerRegistry.register(InterfaceType.GET_PSOP_BY_ID, db_handlers.CustomGetPsopHandler, bundled=True)


def test_bundled_handlers_are_not_reported_as_extensions():
    """The bundled handlers must not look like extensions.

    If they did, the port would call them and they would call the port back.
    """
    import orchestrate.handlers  # noqa: F401  registers the bundled handlers

    assert HandlerRegistry.get_extension_override(InterfaceType.GET_ALL_PSOP) is None
    assert HandlerRegistry.get_extension_override(InterfaceType.GET_PSOP_BY_ID) is None


def test_extension_query_handler_wins_over_the_bundled_query(monkeypatch):
    from common.util import persistence_mode
    monkeypatch.setattr(persistence_mode, "get_conf", lambda: {"persistence_mode": "postgresql"})
    import orchestrate.handlers  # noqa: F401
    from orchestrate.handlers import db_handlers

    assert HandlerRegistry.get_extension_override(InterfaceType.GET_ALL_PSOP) is not db_handlers.CustomGetAllPsopsHandler

    _ExtensionListHandler.calls = 0
    HandlerRegistry.register(InterfaceType.GET_ALL_PSOP, _ExtensionListHandler)
    HandlerRegistry.register(InterfaceType.GET_PSOP_BY_ID, _ExtensionByIdHandler)
    try:
        assert HandlerRegistry.get_extension_override(InterfaceType.GET_ALL_PSOP) is _ExtensionListHandler

        context = StorageContext(create_backend("postgresql"))
        repository = context.psops_for(None)

        assert repository.list_summaries() == ["from-extension"]
        assert repository.get("wf-1") == "from-extension:wf-1"
        assert _ExtensionListHandler.calls == 1
    finally:
        _restore_bundled_handlers()

    # After the extension is gone, the port is back on its own implementation.
    assert HandlerRegistry.get_extension_override(InterfaceType.GET_ALL_PSOP) is None
