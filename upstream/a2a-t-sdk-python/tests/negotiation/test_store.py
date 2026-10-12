from __future__ import annotations

import importlib
import sys
import unittest
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


class InMemoryNegotiationStateStoreTest(unittest.TestCase):
    def test_store_saves_gets_deletes_records(self) -> None:
        from a2a_t.negotiation.common.enums import NegotiationRole, NegotiationStatus, NegotiationType
        from a2a_t.negotiation.common.models import NegotiationContext, NegotiationRecord
        from a2a_t.negotiation.store.in_memory import InMemoryNegotiationStateStore

        store = InMemoryNegotiationStateStore()
        record = NegotiationRecord(
            context=NegotiationContext(
                negotiation_type=NegotiationType.TARGET,
                negotiation_id="neg-store",
                role=NegotiationRole.SERVER,
                round=1,
                status=NegotiationStatus.IN_PROGRESS,
                extra={},
            ),
            last_message="message",
            last_receive_result=None,
            last_continue_result=None,
            last_task_prompt=None,
            created_at="2026-04-18T00:00:00Z",
            updated_at="2026-04-18T00:00:00Z",
        )

        store.save(record)

        self.assertIs(store.get("neg-store"), record)

        store.delete("neg-store")

        self.assertIsNone(store.get("neg-store"))

    def test_cleanup_expired_returns_true(self) -> None:
        from a2a_t.negotiation.store.in_memory import InMemoryNegotiationStateStore

        store = InMemoryNegotiationStateStore()

        self.assertTrue(store.cleanup_expired())


# --------------------------------------------------------------------------------------
# Deprecation shim round (D1): the retired state-machine packages this suite pins emit a
# DeprecationWarning when imported and will be removed in the next release. The behavioral
# assertions above stay untouched; this only pins the warning contract of the deprecated
# entry points this file exercises (store + its common dependency).
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "package_name",
    (
        "a2a_t.negotiation.store",
        "a2a_t.negotiation.common",
    ),
)
def test_importing_a_deprecated_negotiation_package_warns(package_name: str) -> None:
    module = importlib.import_module(package_name)

    with pytest.warns(DeprecationWarning, match=f"{package_name} package is deprecated since 1\\.1\\.0"):
        importlib.reload(module)
