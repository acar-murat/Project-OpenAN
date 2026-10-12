from __future__ import annotations

import logging
from typing import Any

from a2a_t.negotiation.common.enums import NegotiationRole
from a2a_t.negotiation.common.models import ContinueNegotiationInput, StartNegotiationInput

_LOGGER = logging.getLogger(__name__)


class BaseNegotiationOrchestrator:
    """Expose the shared negotiation handler behind a role-specific facade."""

    def __init__(self, *, handler: Any, role: NegotiationRole, logger: Any | None = None) -> None:
        self._handler = handler
        self._role = role
        self._logger = logger if logger is not None else _LOGGER

    def start_negotiation(self, input: StartNegotiationInput) -> dict[str, object]:
        """Start a negotiation from the bound local role."""
        self._log_info("negotiation_start_started role=%s type=%s", self._role.value, input.type.value)
        result: dict[str, object] = self._handler.start(input=input, role=self._role)
        self._log_result("negotiation_start_completed role=%s type=%s id=%s status=%s", result)
        return result

    def receive_negotiation(self, message: str, context: dict[str, object]) -> dict[str, object]:
        """Process a negotiation message received from the remote peer."""
        self._log_info(
            "negotiation_receive_started role=%s type=%s id=%s",
            self._role.value,
            context.get("negotiationType"),
            context.get("negotiationId"),
        )
        result: dict[str, object] = self._handler.receive(
            message=message,
            context=context,
        )
        self._log_result("negotiation_receive_completed role=%s type=%s id=%s status=%s", result)
        return result

    def continue_negotiation(self, input: ContinueNegotiationInput) -> dict[str, object]:
        """Continue a negotiation from the bound local role."""
        self._log_info(
            "negotiation_continue_started role=%s type=%s id=%s status=%s",
            self._role.value,
            input.context.negotiation_type.value,
            input.context.negotiation_id,
            input.status.value,
        )
        result: dict[str, object] = self._handler.continue_(input=input)
        self._log_result("negotiation_continue_completed role=%s type=%s id=%s status=%s", result)
        return result

    def _log_result(self, message: str, result: dict[str, object]) -> None:
        context = result.get("context")
        if not isinstance(context, dict):
            context = {}
        self._log_info(
            message,
            self._role.value,
            context.get("negotiationType"),
            context.get("negotiationId"),
            context.get("status"),
        )

    def _log_info(self, message: str, *args: object) -> None:
        self._logger.info(message, *args)
