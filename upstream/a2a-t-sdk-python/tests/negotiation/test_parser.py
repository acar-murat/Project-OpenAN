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


class NegotiationContextParseTest(unittest.TestCase):
    def test_from_context_returns_negotiation_context(self) -> None:
        from a2a_t.negotiation.common.enums import NegotiationRole, NegotiationStatus, NegotiationType
        from a2a_t.negotiation.common.models import NegotiationContext

        context = NegotiationContext.from_context(
            {
                "negotiationType": "information",
                "negotiationId": "neg-1",
                "role": "client",
                "round": 3,
                "status": "in-progress",
                "extra": {},
            }
        )

        self.assertEqual(context.negotiation_type, NegotiationType.INFORMATION)
        self.assertEqual(context.negotiation_id, "neg-1")
        self.assertEqual(context.role, NegotiationRole.CLIENT)
        self.assertEqual(context.round, 3)
        self.assertEqual(context.status, NegotiationStatus.IN_PROGRESS)

    def test_from_context_rejects_invalid_root_fields(self) -> None:
        from a2a_t.negotiation.common.errors import NegotiationContextError
        from a2a_t.negotiation.common.models import NegotiationContext

        with self.assertRaises(NegotiationContextError):
            NegotiationContext.from_context(
                {
                    "negotiationType": "unknown",
                    "negotiationId": "neg-1",
                    "role": "client",
                    "round": 0,
                    "status": "in-progress",
                    "extra": {},
                }
            )


# --------------------------------------------------------------------------------------
# Deprecation shim round (D1): the retired state-machine packages this suite pins emit a
# DeprecationWarning when imported and will be removed in the next release. The behavioral
# assertions above stay untouched; this only pins the warning contract of the deprecated
# entry points this file exercises (the common model/parser package).
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("package_name", ("a2a_t.negotiation.common",))
def test_importing_a_deprecated_negotiation_package_warns(package_name: str) -> None:
    module = importlib.import_module(package_name)

    with pytest.warns(DeprecationWarning, match=f"{package_name} package is deprecated since 1\\.1\\.0"):
        importlib.reload(module)
