# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""The contract matrix: what each registered mode must and must not provide.

Driven by the registry itself, so a backend cannot be added without stating its
contract here. Nothing here opens a connection: constructing a backend and
building a context must stay cheap and offline, which is what lets the CLI and
the test suite run without a database.
"""

import pytest

from orchestrate.persistence import (
    Capability,
    ExecutionRecordRepository,
    PersistenceBackend,
    PreflowRepository,
    PsopRepository,
    StorageContext,
    StorageValidationError,
    create_backend,
    known_modes,
)

# mode -> does it provide a user store?
EXPECTED_CONTRACTS = {
    "file": False,
    "postgresql": True,
    "mysql": True,
}


def test_every_registered_mode_states_its_contract():
    assert set(known_modes()) == set(EXPECTED_CONTRACTS), (
        "a persistence mode was added or removed: state its contract in EXPECTED_CONTRACTS"
    )


@pytest.mark.parametrize("mode", sorted(EXPECTED_CONTRACTS))
def test_mode_exposes_exactly_its_declared_contract(mode):
    backend = create_backend(mode)
    context = StorageContext(backend)
    has_users = EXPECTED_CONTRACTS[mode]

    assert backend.mode == mode
    assert context.mode == mode
    assert isinstance(backend, PersistenceBackend)

    # Capability is declared, never probed: callers branch on this flag.
    assert context.has_users is has_users
    assert context.supports(Capability.USERS) is has_users

    assert isinstance(context.psops, PsopRepository)
    assert isinstance(context.executions, ExecutionRecordRepository)
    assert isinstance(context.preflows, PreflowRepository)
    assert isinstance(context.psops_for(None), PsopRepository)

    if has_users:
        assert context.users is not None
    else:
        # Asking for a repository the backend does not have must be a clear
        # error, not an AttributeError three call frames later.
        with pytest.raises(StorageValidationError):
            context.users


@pytest.mark.parametrize("mode", sorted(EXPECTED_CONTRACTS))
def test_assembling_a_backend_touches_no_database(mode):
    # check_ready() is the only entry point allowed to reach the network, and it
    # is deliberately not called: assembly has to stay safe offline.
    context = StorageContext(create_backend(mode))

    assert context.mode == mode
