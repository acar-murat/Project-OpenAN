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


class FakeLogger:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def warning(self, message: str, *args: object) -> None:
        if args:
            message = message % args
        self.messages.append(message)


class NegotiationStateStoreFactoryTest(unittest.TestCase):
    def _env_path(self, name: str) -> Path:
        temp_dir = PROJECT_ROOT / ".tmp_tests" / "negotiation_store_factory"
        temp_dir.mkdir(parents=True, exist_ok=True)
        return temp_dir / name

    def test_build_returns_in_memory_store_for_supported_type(self) -> None:
        from a2a_t.negotiation.store.factory import NegotiationStateStoreFactory
        from a2a_t.negotiation.store.in_memory import InMemoryNegotiationStateStore

        env_path = self._env_path("supported.env")
        env_path.write_text("A2AT_NEGOTIATION_STATE_STORE_TYPE=in_memory\n", encoding="utf-8")

        store = NegotiationStateStoreFactory().build(env_path=env_path)

        self.assertIsInstance(store, InMemoryNegotiationStateStore)

    def test_build_falls_back_to_in_memory_when_env_is_missing(self) -> None:
        from a2a_t.negotiation.store.factory import NegotiationStateStoreFactory
        from a2a_t.negotiation.store.in_memory import InMemoryNegotiationStateStore

        logger = FakeLogger()
        store = NegotiationStateStoreFactory().build(
            env_path=Path("missing.env"),
            logger=logger,
        )

        self.assertIsInstance(store, InMemoryNegotiationStateStore)
        self.assertEqual(len(logger.messages), 1)

    def test_build_falls_back_to_in_memory_for_unsupported_type(self) -> None:
        from a2a_t.negotiation.store.factory import NegotiationStateStoreFactory
        from a2a_t.negotiation.store.in_memory import InMemoryNegotiationStateStore

        logger = FakeLogger()
        env_path = self._env_path("unsupported.env")
        env_path.write_text("A2AT_NEGOTIATION_STATE_STORE_TYPE=file\n", encoding="utf-8")

        store = NegotiationStateStoreFactory().build(
            env_path=env_path,
            logger=logger,
        )

        self.assertIsInstance(store, InMemoryNegotiationStateStore)
        self.assertEqual(len(logger.messages), 1)


# --------------------------------------------------------------------------------------
# Deprecation shim round (D1): the retired state-machine packages this suite pins emit a
# DeprecationWarning when imported and will be removed in the next release. The behavioral
# assertions above stay untouched; this only pins the warning contract of the deprecated
# entry points this file exercises (the store package).
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("package_name", ("a2a_t.negotiation.store",))
def test_importing_a_deprecated_negotiation_package_warns(package_name: str) -> None:
    module = importlib.import_module(package_name)

    with pytest.warns(DeprecationWarning, match=f"{package_name} package is deprecated since 1\\.1\\.0"):
        importlib.reload(module)
