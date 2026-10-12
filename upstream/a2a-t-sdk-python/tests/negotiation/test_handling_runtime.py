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


class NegotiationHandlingRuntimeTest(unittest.TestCase):
    def _target_types(self):
        from a2a_t.negotiation.common.enums import NegotiationType
        from a2a_t.negotiation.rendering.negotiation_prompt_renderer import NegotiationPromptRenderer
        from a2a_t.negotiation.types.target import TargetNegotiationType

        return {
            NegotiationType.TARGET: TargetNegotiationType(prompt_renderer=NegotiationPromptRenderer()),
        }

    def test_handler_start_returns_fixed_key_map_and_saves_record(self) -> None:
        from a2a_t.negotiation.common.constants import NEGOTIATION_T_URI_NL
        from a2a_t.negotiation.common.enums import NegotiationRole, NegotiationType
        from a2a_t.negotiation.common.models import StartNegotiationInput
        from a2a_t.negotiation.handling.negotiation_handler import NegotiationHandler
        from a2a_t.negotiation.store.in_memory import InMemoryNegotiationStateStore

        store = InMemoryNegotiationStateStore()
        handler = NegotiationHandler(
            negotiation_types=self._target_types(),
            store=store,
        )

        payload = handler.start(
            input=StartNegotiationInput(
                type=NegotiationType.TARGET,
                content_text="Please clarify the request.",
                facts={"targetItems": [{"name": "intent"}]},
            ),
            role=NegotiationRole.CLIENT,
        )

        self.assertIn(NEGOTIATION_T_URI_NL, payload)
        negotiation_data = payload[NEGOTIATION_T_URI_NL]
        self.assertEqual(negotiation_data["message"], "Please clarify the request.")
        self.assertTrue(negotiation_data["negotiationId"])
        self.assertIsNotNone(store.get(negotiation_data["negotiationId"]))

    def test_handler_receive_allows_first_round_without_existing_record(self) -> None:
        from a2a_t.negotiation.common.enums import NegotiationRole, NegotiationStatus, NegotiationType
        from a2a_t.negotiation.handling.negotiation_handler import NegotiationHandler
        from a2a_t.negotiation.store.in_memory import InMemoryNegotiationStateStore

        handler = NegotiationHandler(
            negotiation_types=self._target_types(),
            store=InMemoryNegotiationStateStore(),
        )

        result = handler.receive(
            message="Clarify intent",
            context={
                "negotiationType": "target",
                "negotiationId": "neg-receive",
                "role": "client",
                "round": 1,
                "status": "in-progress",
                "extra": {},
            },
        )

        self.assertTrue(result["needResponse"])
        self.assertEqual(result["context"]["negotiationType"], NegotiationType.TARGET.value)
        self.assertEqual(result["context"]["role"], NegotiationRole.CLIENT.value)
        self.assertEqual(result["context"]["status"], NegotiationStatus.IN_PROGRESS.value)
        self.assertEqual(result["facts"], {})
        self.assertEqual(result["message"], "Clarify intent")

    def test_handler_continue_returns_map_with_incremented_round(self) -> None:
        from a2a_t.negotiation.common.enums import NegotiationRole, NegotiationStatus, NegotiationType
        from a2a_t.negotiation.common.models import (
            ContinueNegotiationInput,
            NegotiationContext,
            NegotiationRecord,
            ReceiveResult,
        )
        from a2a_t.negotiation.handling.negotiation_handler import NegotiationHandler
        from a2a_t.negotiation.store.in_memory import InMemoryNegotiationStateStore

        store = InMemoryNegotiationStateStore()
        context = NegotiationContext(
            negotiation_type=NegotiationType.TARGET,
            negotiation_id="neg-continue",
            role=NegotiationRole.CLIENT,
            round=1,
            status=NegotiationStatus.IN_PROGRESS,
            extra={},
        )
        store.save(
            NegotiationRecord(
                context=context,
                last_message="old",
                last_receive_result=ReceiveResult(need_response=True, facts={"targetItems": []}),
                last_continue_result=None,
                last_task_prompt=None,
                created_at="t1",
                updated_at="t1",
            )
        )
        handler = NegotiationHandler(
            negotiation_types=self._target_types(),
            store=store,
        )

        payload = handler.continue_(
            input=ContinueNegotiationInput(
                context=context,
                status=NegotiationStatus.IN_PROGRESS,
                content_text="Here is the target.",
            )
        )

        negotiation_data = payload[
            "https://projects.tmforum.org/a2aproject/telecommunication/extensions/Negotiation-T/NL/v1"
        ]
        self.assertEqual(negotiation_data["round"], 2)
        self.assertEqual(negotiation_data["message"], "Here is the target.")

    def test_handler_receive_terminal_message_returns_need_response_false(self) -> None:
        from a2a_t.negotiation.common.enums import NegotiationRole, NegotiationStatus, NegotiationType
        from a2a_t.negotiation.common.models import NegotiationContext, NegotiationRecord
        from a2a_t.negotiation.handling.negotiation_handler import NegotiationHandler
        from a2a_t.negotiation.store.in_memory import InMemoryNegotiationStateStore

        store = InMemoryNegotiationStateStore()
        store.save(
            NegotiationRecord(
                context=NegotiationContext(
                    negotiation_type=NegotiationType.TARGET,
                    negotiation_id="neg-terminal",
                    role=NegotiationRole.CLIENT,
                    round=1,
                    status=NegotiationStatus.IN_PROGRESS,
                    extra={},
                ),
                last_message="old",
                last_receive_result=None,
                last_continue_result=None,
                last_task_prompt=None,
                created_at="t1",
                updated_at="t1",
            )
        )
        handler = NegotiationHandler(
            negotiation_types=self._target_types(),
            store=store,
        )

        result = handler.receive(
            message="Clarify intent",
            context={
                "negotiationType": "target",
                "negotiationId": "neg-terminal",
                "role": "client",
                "round": 2,
                "status": "agreed",
                "extra": {},
            },
        )

        self.assertFalse(result["needResponse"])

    def test_handler_receive_rejects_incoming_round_that_skips_local_progress(self) -> None:
        from a2a_t.negotiation.common.enums import NegotiationRole, NegotiationStatus, NegotiationType
        from a2a_t.negotiation.common.errors import NegotiationStateError
        from a2a_t.negotiation.common.models import NegotiationContext, NegotiationRecord
        from a2a_t.negotiation.handling.negotiation_handler import NegotiationHandler
        from a2a_t.negotiation.store.in_memory import InMemoryNegotiationStateStore

        store = InMemoryNegotiationStateStore()
        store.save(
            NegotiationRecord(
                context=NegotiationContext(
                    negotiation_type=NegotiationType.TARGET,
                    negotiation_id="neg-round-skip",
                    role=NegotiationRole.CLIENT,
                    round=2,
                    status=NegotiationStatus.IN_PROGRESS,
                    extra={},
                ),
                last_message="old",
                last_receive_result=None,
                last_continue_result=None,
                last_task_prompt=None,
                created_at="t1",
                updated_at="t1",
            )
        )
        handler = NegotiationHandler(
            negotiation_types=self._target_types(),
            store=store,
        )

        with self.assertRaises(NegotiationStateError):
            handler.receive(
                message="Clarify intent",
                context={
                    "negotiationType": "target",
                    "negotiationId": "neg-round-skip",
                    "role": "client",
                    "round": 4,
                    "status": "in-progress",
                    "extra": {},
                },
            )

    def test_handler_continue_rejects_context_round_mismatch(self) -> None:
        from a2a_t.negotiation.common.enums import NegotiationRole, NegotiationStatus, NegotiationType
        from a2a_t.negotiation.common.errors import NegotiationStateError
        from a2a_t.negotiation.common.models import ContinueNegotiationInput, NegotiationContext, NegotiationRecord
        from a2a_t.negotiation.handling.negotiation_handler import NegotiationHandler
        from a2a_t.negotiation.store.in_memory import InMemoryNegotiationStateStore

        store = InMemoryNegotiationStateStore()
        store.save(
            NegotiationRecord(
                context=NegotiationContext(
                    negotiation_type=NegotiationType.TARGET,
                    negotiation_id="neg-continue-mismatch",
                    role=NegotiationRole.CLIENT,
                    round=2,
                    status=NegotiationStatus.IN_PROGRESS,
                    extra={},
                ),
                last_message="old",
                last_receive_result=None,
                last_continue_result=None,
                last_task_prompt=None,
                created_at="t1",
                updated_at="t1",
            )
        )
        handler = NegotiationHandler(
            negotiation_types=self._target_types(),
            store=store,
        )

        with self.assertRaises(NegotiationStateError):
            handler.continue_(
                input=ContinueNegotiationInput(
                    context=NegotiationContext(
                        negotiation_type=NegotiationType.TARGET,
                        negotiation_id="neg-continue-mismatch",
                        role=NegotiationRole.CLIENT,
                        round=1,
                        status=NegotiationStatus.IN_PROGRESS,
                        extra={},
                    ),
                    status=NegotiationStatus.IN_PROGRESS,
                    content_text="Here is the target.",
                )
            )

    def test_handler_receive_returns_reject_guidance_when_incoming_round_hits_limit(self) -> None:
        from a2a_t.negotiation.common.constants import MAX_IN_PROGRESS_NEGOTIATION_ROUND
        from a2a_t.negotiation.common.enums import NegotiationRole, NegotiationStatus, NegotiationType
        from a2a_t.negotiation.common.models import NegotiationContext, NegotiationRecord
        from a2a_t.negotiation.handling.negotiation_handler import NegotiationHandler
        from a2a_t.negotiation.store.in_memory import InMemoryNegotiationStateStore

        store = InMemoryNegotiationStateStore()
        previous_round = MAX_IN_PROGRESS_NEGOTIATION_ROUND - 1
        store.save(
            NegotiationRecord(
                context=NegotiationContext(
                    negotiation_type=NegotiationType.TARGET,
                    negotiation_id="neg-round-limit",
                    role=NegotiationRole.CLIENT,
                    round=previous_round,
                    status=NegotiationStatus.IN_PROGRESS,
                    extra={},
                ),
                last_message="old",
                last_receive_result=None,
                last_continue_result=None,
                last_task_prompt=None,
                created_at="t1",
                updated_at="t1",
            )
        )
        handler = NegotiationHandler(
            negotiation_types=self._target_types(),
            store=store,
        )

        result = handler.receive(
            message="Clarify intent",
            context={
                "negotiationType": "target",
                "negotiationId": "neg-round-limit",
                "role": "client",
                "round": MAX_IN_PROGRESS_NEGOTIATION_ROUND,
                "status": "in-progress",
                "extra": {},
            },
        )

        self.assertTrue(result["needResponse"])
        self.assertEqual(
            result["message"], "Negotiation reached the maximum in-progress round limit. Please reject it."
        )


# --------------------------------------------------------------------------------------
# Deprecation shim round (D1): the retired state-machine packages this suite pins emit a
# DeprecationWarning when imported and will be removed in the next release. The behavioral
# assertions above stay untouched; this only pins the warning contract of the deprecated
# entry points this file exercises (handling + its store/types/rendering/common dependencies).
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "package_name",
    (
        "a2a_t.negotiation.handling",
        "a2a_t.negotiation.store",
        "a2a_t.negotiation.types",
        "a2a_t.negotiation.rendering",
        "a2a_t.negotiation.common",
    ),
)
def test_importing_a_deprecated_negotiation_package_warns(package_name: str) -> None:
    module = importlib.import_module(package_name)

    with pytest.warns(DeprecationWarning, match=f"{package_name} package is deprecated since 1\\.1\\.0"):
        importlib.reload(module)
