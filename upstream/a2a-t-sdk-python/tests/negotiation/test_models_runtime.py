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


class NegotiationModelsRuntimeTest(unittest.TestCase):
    def test_negotiation_context_to_context_uses_protocol_field_names(self) -> None:
        from a2a_t.negotiation.common.enums import NegotiationRole, NegotiationStatus, NegotiationType
        from a2a_t.negotiation.common.models import NegotiationContext

        context = NegotiationContext(
            negotiation_type=NegotiationType.INFORMATION,
            negotiation_id="neg-1",
            role=NegotiationRole.CLIENT,
            round=2,
            status=NegotiationStatus.IN_PROGRESS,
            extra={"x": "y"},
        )

        self.assertEqual(
            context.to_context(),
            {
                "negotiationType": "information",
                "negotiationId": "neg-1",
                "role": "client",
                "round": 2,
                "status": "in-progress",
                "extra": {"x": "y"},
            },
        )

    def test_negotiation_context_from_context_uses_protocol_field_names(self) -> None:
        from a2a_t.negotiation.common.enums import NegotiationRole, NegotiationStatus, NegotiationType
        from a2a_t.negotiation.common.models import NegotiationContext

        context = NegotiationContext.from_context(
            {
                "negotiationType": "information",
                "negotiationId": "neg-3",
                "role": "server",
                "round": 4,
                "status": "agreed",
                "extra": {},
            }
        )

        self.assertEqual(context.negotiation_type, NegotiationType.INFORMATION)
        self.assertEqual(context.negotiation_id, "neg-3")
        self.assertEqual(context.role, NegotiationRole.SERVER)
        self.assertEqual(context.round, 4)
        self.assertEqual(context.status, NegotiationStatus.AGREED)


# --------------------------------------------------------------------------------------
# Deprecation shim round (D1): the retired state-machine packages this suite pins emit a
# DeprecationWarning when imported and will be removed in the next release. The behavioral
# assertions above stay untouched; this only pins the warning contract of the deprecated
# entry points this file exercises (the common model package).
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("package_name", ("a2a_t.negotiation.common",))
def test_importing_a_deprecated_negotiation_package_warns(package_name: str) -> None:
    module = importlib.import_module(package_name)

    with pytest.warns(DeprecationWarning, match=f"{package_name} package is deprecated since 1\\.1\\.0"):
        importlib.reload(module)
