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


class FakeNegotiationHandler:
    def __init__(self) -> None:
        self.start_calls: list[dict[str, object]] = []
        self.receive_calls: list[dict[str, object]] = []
        self.continue_calls: list[dict[str, object]] = []

    def start(self, *, input: object, role: object) -> dict[str, object]:
        self.start_calls.append({"input": input, "role": role})
        return {"started": True}

    def receive(self, *, message: str, context: dict[str, object]):
        self.receive_calls.append({"message": message, "context": context})
        return {
            "context": {
                "negotiationType": "target",
                "negotiationId": "neg-1",
                "role": "client",
                "round": 1,
                "status": "in-progress",
                "extra": {},
            },
            "needResponse": True,
            "facts": {"targetItems": []},
            "message": "Please clarify.",
        }

    def continue_(self, *, input: object) -> dict[str, object]:
        self.continue_calls.append({"input": input})
        return {"continued": True}


class FakeLogger:
    def __init__(self) -> None:
        self.info_messages: list[tuple[str, tuple[object, ...]]] = []

    def info(self, message: str, *args: object) -> None:
        self.info_messages.append((message, args))


class FalsyLogger(FakeLogger):
    def __bool__(self) -> bool:
        return False


class NegotiationOrchestratorTest(unittest.TestCase):
    def test_client_orchestrator_start_negotiation_uses_client_role(self) -> None:
        from a2a_t.client.negotiation.negotiation_orchestrator import NegotiationOrchestrator
        from a2a_t.negotiation.common.enums import NegotiationRole, NegotiationType
        from a2a_t.negotiation.common.models import StartNegotiationInput

        handler = FakeNegotiationHandler()
        orchestrator = NegotiationOrchestrator(handler=handler)

        result = orchestrator.start_negotiation(
            StartNegotiationInput(
                type=NegotiationType.TARGET,
                content_text="Please clarify.",
                facts={},
            )
        )

        self.assertEqual(result, {"started": True})
        self.assertEqual(handler.start_calls[0]["role"], NegotiationRole.CLIENT)

    def test_server_orchestrator_start_negotiation_uses_server_role(self) -> None:
        from a2a_t.negotiation.common.enums import NegotiationRole, NegotiationType
        from a2a_t.negotiation.common.models import StartNegotiationInput
        from a2a_t.server.negotiation.negotiation_orchestrator import NegotiationOrchestrator

        handler = FakeNegotiationHandler()
        orchestrator = NegotiationOrchestrator(handler=handler)

        result = orchestrator.start_negotiation(
            StartNegotiationInput(
                type=NegotiationType.INFORMATION,
                content_text="Need more information.",
                facts={},
            )
        )

        self.assertEqual(result, {"started": True})
        self.assertEqual(handler.start_calls[0]["role"], NegotiationRole.SERVER)

    def test_receive_negotiation_returns_public_dict(self) -> None:
        from a2a_t.client.negotiation.negotiation_orchestrator import NegotiationOrchestrator

        orchestrator = NegotiationOrchestrator(
            handler=FakeNegotiationHandler(),
        )

        result = orchestrator.receive_negotiation(
            "message",
            {
                "negotiationType": "target",
                "negotiationId": "neg-1",
                "role": "client",
                "round": 1,
                "status": "in-progress",
                "extra": {},
            },
        )

        self.assertEqual(result["context"]["negotiationId"], "neg-1")
        self.assertEqual(result["needResponse"], True)
        self.assertEqual(result["message"], "Please clarify.")

    def test_continue_negotiation_returns_handler_payload(self) -> None:
        from a2a_t.client.negotiation.negotiation_orchestrator import NegotiationOrchestrator
        from a2a_t.negotiation.common.enums import NegotiationStatus
        from a2a_t.negotiation.common.models import ContinueNegotiationInput, NegotiationContext

        handler = FakeNegotiationHandler()
        orchestrator = NegotiationOrchestrator(
            handler=handler,
        )

        result = orchestrator.continue_negotiation(
            ContinueNegotiationInput(
                context=NegotiationContext.from_context(
                    {
                        "negotiationType": "target",
                        "negotiationId": "neg-1",
                        "role": "client",
                        "round": 1,
                        "status": "in-progress",
                        "extra": {},
                    }
                ),
                status=NegotiationStatus.IN_PROGRESS,
                content_text="Here is the target.",
            )
        )

        self.assertEqual(result, {"continued": True})
        self.assertEqual(len(handler.continue_calls), 1)
        self.assertEqual(handler.continue_calls[0]["input"].context.negotiation_id, "neg-1")

    def test_orchestrator_uses_explicit_logger_even_when_logger_is_falsy(self) -> None:
        from a2a_t.negotiation.common.enums import NegotiationType
        from a2a_t.negotiation.common.models import StartNegotiationInput
        from a2a_t.server.negotiation.negotiation_orchestrator import NegotiationOrchestrator

        logger = FalsyLogger()
        orchestrator = NegotiationOrchestrator(
            handler=FakeNegotiationHandler(),
            logger=logger,
        )

        orchestrator.start_negotiation(
            StartNegotiationInput(
                type=NegotiationType.INFORMATION,
                content_text="Need more information.",
                facts={},
            )
        )

        self.assertIn(
            ("negotiation_start_started role=%s type=%s", ("server", "information")),
            logger.info_messages,
        )

    def test_orchestrator_logs_lifecycle_events_without_message_content(self) -> None:
        from a2a_t.negotiation.common.enums import NegotiationStatus, NegotiationType
        from a2a_t.negotiation.common.models import ContinueNegotiationInput, NegotiationContext, StartNegotiationInput
        from a2a_t.server.negotiation.negotiation_orchestrator import NegotiationOrchestrator

        logger = FakeLogger()
        orchestrator = NegotiationOrchestrator(
            handler=FakeNegotiationHandler(),
            logger=logger,
        )
        start_input = StartNegotiationInput(
            type=NegotiationType.INFORMATION,
            content_text="Need more information.",
            facts={},
        )
        context = {
            "negotiationType": "target",
            "negotiationId": "neg-1",
            "role": "client",
            "round": 1,
            "status": "in-progress",
            "extra": {},
        }

        orchestrator.start_negotiation(start_input)
        orchestrator.receive_negotiation("sensitive message", context)
        orchestrator.continue_negotiation(
            ContinueNegotiationInput(
                context=NegotiationContext.from_context(context),
                status=NegotiationStatus.IN_PROGRESS,
                content_text="sensitive continuation",
            )
        )

        self.assertIn(
            ("negotiation_start_started role=%s type=%s", ("server", "information")),
            logger.info_messages,
        )
        self.assertIn(
            ("negotiation_start_completed role=%s type=%s id=%s status=%s", ("server", None, None, None)),
            logger.info_messages,
        )
        self.assertIn(
            ("negotiation_receive_started role=%s type=%s id=%s", ("server", "target", "neg-1")),
            logger.info_messages,
        )
        self.assertIn(
            (
                "negotiation_receive_completed role=%s type=%s id=%s status=%s",
                ("server", "target", "neg-1", "in-progress"),
            ),
            logger.info_messages,
        )
        self.assertIn(
            (
                "negotiation_continue_started role=%s type=%s id=%s status=%s",
                ("server", "target", "neg-1", "in-progress"),
            ),
            logger.info_messages,
        )
        self.assertIn(
            ("negotiation_continue_completed role=%s type=%s id=%s status=%s", ("server", None, None, None)),
            logger.info_messages,
        )
        self.assertFalse(any("sensitive" in message for message, _ in logger.info_messages))


# --------------------------------------------------------------------------------------
# Deprecation shim round (D1): the retired state-machine packages behind the legacy
# orchestrators this suite pins emit a DeprecationWarning when imported and will be removed
# in the next release. The behavioral assertions above stay untouched; this only pins the
# warning contract of the deprecated entry points this file exercises (the common package
# backing the legacy orchestrator transports).
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("package_name", ("a2a_t.negotiation.common",))
def test_importing_a_deprecated_negotiation_package_warns(package_name: str) -> None:
    module = importlib.import_module(package_name)

    with pytest.warns(DeprecationWarning, match=f"{package_name} package is deprecated since 1\\.1\\.0"):
        importlib.reload(module)
