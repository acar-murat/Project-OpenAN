# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Registry mechanism tests isolate slots from application import side effects."""

import pytest

from common.custom.default_handle import BaseHandler, HandlerRegistry
from common.custom.interface_type import InterfaceType
from common.util import persistence_mode as modes


class FileHandler(BaseHandler):
    def handle(self):
        return "file"


class OverrideHandler(BaseHandler):
    def handle(self):
        return "override"


@pytest.fixture
def registry(monkeypatch):
    monkeypatch.setattr(HandlerRegistry, "_defaults", {})
    monkeypatch.setattr(HandlerRegistry, "_overrides", {})
    monkeypatch.setattr(modes, "get_conf", lambda: {"persistence_mode": "file"})
    return HandlerRegistry


def test_default_registration_replacement_and_fresh_instances(registry):
    registry.register_default(InterfaceType.SAVE_PSOP, FileHandler)
    first = registry.get_handler(InterfaceType.SAVE_PSOP)
    assert type(first) is FileHandler
    assert registry.get_handler(InterfaceType.SAVE_PSOP) is not first
    registry.register_default(InterfaceType.SAVE_PSOP, OverrideHandler)
    assert type(registry.get_handler(InterfaceType.SAVE_PSOP)) is OverrideHandler


@pytest.mark.parametrize("mode,expected", [
    ("file", FileHandler), ("FILE", FileHandler),
    ("postgresql", OverrideHandler), ("PostgreSQL", OverrideHandler),
])
def test_mode_dispatch_keeps_slots_independent(registry, monkeypatch, mode, expected):
    registry.register_default(InterfaceType.SAVE_PSOP, FileHandler)
    registry.register(InterfaceType.SAVE_PSOP, OverrideHandler)
    monkeypatch.setattr(modes, "get_conf", lambda: {"persistence_mode": mode})
    assert type(registry.get_handler(InterfaceType.SAVE_PSOP)) is expected
    assert registry._defaults[InterfaceType.SAVE_PSOP.value] is FileHandler
    assert registry._overrides[InterfaceType.SAVE_PSOP.value] is OverrideHandler


def test_override_replacement_does_not_replace_file_default(registry, monkeypatch):
    registry.register_default(InterfaceType.SAVE_PSOP, FileHandler)
    registry.register(InterfaceType.SAVE_PSOP, FileHandler)
    registry.register(InterfaceType.SAVE_PSOP, OverrideHandler)
    monkeypatch.setattr(modes, "get_conf", lambda: {"persistence_mode": "postgresql"})
    assert type(registry.get_handler(InterfaceType.SAVE_PSOP)) is OverrideHandler
    assert registry._defaults[InterfaceType.SAVE_PSOP.value] is FileHandler


def test_database_missing_override_never_falls_back_to_file(registry, monkeypatch):
    registry.register_default(InterfaceType.SAVE_PSOP, FileHandler)
    monkeypatch.setattr(modes, "get_conf", lambda: {"persistence_mode": "postgresql"})
    with pytest.raises(ValueError, match="No custom handler registered.*save_psop"):
        registry.get_handler(InterfaceType.SAVE_PSOP)


def test_file_mode_requires_default_even_if_override_exists(registry):
    registry.register(InterfaceType.SAVE_PSOP, OverrideHandler)
    with pytest.raises(ValueError, match="Unknown interface type"):
        registry.get_handler(InterfaceType.SAVE_PSOP)


@pytest.mark.parametrize("slot", ["register_default", "register"])
@pytest.mark.parametrize("invalid", [object, object()])
def test_invalid_handlers_leave_registry_unchanged(registry, slot, invalid):
    with pytest.raises(TypeError):
        getattr(registry, slot)(InterfaceType.SAVE_PSOP, invalid)
    assert registry._defaults == {}
    assert registry._overrides == {}
