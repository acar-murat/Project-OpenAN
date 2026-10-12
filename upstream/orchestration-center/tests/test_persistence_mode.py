# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Storage-mode validation and fail-fast startup contracts."""

from unittest.mock import Mock

import pytest

from common.util import persistence_mode as modes


@pytest.mark.parametrize("conf,expected,is_db", [
    ({}, "file", False),
    ({"persistence_mode": "file"}, "file", False),
    ({"persistence_mode": "FILE"}, "file", False),
    ({"persistence_mode": "postgresql"}, "postgresql", True),
    ({"persistence_mode": "PostgreSQL"}, "postgresql", True),
    ({"persistence_mode": "mysql"}, "mysql", True),
    ({"persistence_mode": "MySQL"}, "mysql", True),
])
def test_supported_modes(monkeypatch, conf, expected, is_db):
    monkeypatch.setattr(modes, "get_conf", lambda: conf)
    assert modes.persistence_mode() == expected
    assert modes.validate_storage_mode() == expected
    assert modes.is_db_mode() is is_db


def test_explicit_config_does_not_read_process_config(monkeypatch):
    reader = Mock(side_effect=AssertionError("Unexpected process config read"))
    monkeypatch.setattr(modes, "get_conf", reader)
    assert modes.is_db_mode({}) is False
    assert modes.is_db_mode({"persistence_mode": "PostgreSQL"}) is True
    reader.assert_not_called()


@pytest.mark.parametrize("mode", ["sqlite", "postgres", "", None])
def test_unknown_modes_rejected(monkeypatch, mode):
    monkeypatch.setattr(modes, "get_conf", lambda: {"persistence_mode": mode})
    with pytest.raises(ValueError, match="Unsupported persistence_mode"):
        modes.validate_storage_mode()


@pytest.mark.parametrize("https", ["true", "false"])
def test_unknown_mode_stops_startup_before_database_or_server(monkeypatch, https):
    from orchestrate import start

    conf = {"persistence_mode": "sqlite", "enable_https": https}
    monkeypatch.setattr(start, "get_conf", lambda: conf)
    monkeypatch.setattr(modes, "get_conf", lambda: conf)
    effects = []
    for target, name in [
        # The composition root is the storage seam now: it must not even be
        # reached for an unknown mode, let alone build a backend or seed a user.
        (start, "build_context"), (start, "seed_admin_if_empty"),
        (start, "get_conf_singleton"), (start, "CustomUvicornServer"),
        (start.uvicorn, "run"),
    ]:
        effect = Mock(side_effect=AssertionError(f"Unexpected startup effect: {name}"))
        monkeypatch.setattr(target, name, effect)
        effects.append(effect)
    with pytest.raises(ValueError, match="Unsupported persistence_mode.*sqlite"):
        start.main()
    for effect in effects:
        effect.assert_not_called()
