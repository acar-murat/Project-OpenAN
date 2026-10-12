from __future__ import annotations

import uuid
from datetime import datetime, timezone

from a2a_t.negotiation.common.constants import (
    MAX_IN_PROGRESS_NEGOTIATION_ROUND,
    NEGOTIATION_T_URI_NL,
    TASK_PROMPT_KEY_NL,
)
from a2a_t.negotiation.common.enums import NegotiationRole, NegotiationStatus, NegotiationType
from a2a_t.negotiation.common.errors import NegotiationInputError, NegotiationStateError, NegotiationTerminalStateError
from a2a_t.negotiation.common.models import (
    ContinueNegotiationInput,
    NegotiationContext,
    NegotiationRecord,
    ReceiveResult,
    StartNegotiationInput,
)
from a2a_t.negotiation.store.base import NegotiationStateStore
from a2a_t.negotiation.types.base import BaseNegotiationType


class NegotiationHandler:
    """Own negotiation state transitions across start, receive, and continue flows."""

    def __init__(
        self,
        *,
        negotiation_types: dict[NegotiationType, BaseNegotiationType],
        store: NegotiationStateStore,
    ) -> None:
        self._negotiation_types = dict(negotiation_types)
        self._store = store

    def start(self, *, input: StartNegotiationInput, role: NegotiationRole) -> dict[str, object]:
        """Start a negotiation and persist the initial local record."""
        negotiation_type_key = self._normalize_negotiation_type(input.type)
        context = self._create_start_context(
            negotiation_type=negotiation_type_key,
            role=role,
        )
        negotiation_type = self._get_negotiation_type(negotiation_type_key)
        prompt_text = negotiation_type.render_start_prompt(input=input, context=context)
        now = self._utc_now()
        self._store.save(
            NegotiationRecord(
                context=context,
                last_message=prompt_text,
                last_receive_result=None,
                last_continue_result=None,
                last_task_prompt=None,
                created_at=now,
                updated_at=now,
            )
        )
        return self._build_result_map(
            prompt_text=prompt_text,
            context=context,
        )

    def receive(self, *, message: str, context: dict[str, object]) -> dict[str, object]:
        """Validate and process a negotiation message received from the remote peer."""
        parsed_context = NegotiationContext.from_context(context)
        record = self._store.get(parsed_context.negotiation_id)
        if record is None:
            if parsed_context.round != 1:
                raise NegotiationStateError("Negotiation record is missing for non-initial round.")
            now = self._utc_now()
            record = NegotiationRecord(
                context=parsed_context,
                last_message=None,
                last_receive_result=None,
                last_continue_result=None,
                last_task_prompt=None,
                created_at=now,
                updated_at=now,
            )
        elif record.context.status in {NegotiationStatus.AGREED, NegotiationStatus.REJECTED}:
            raise NegotiationTerminalStateError("Cannot receive a terminal negotiation again.")
        elif parsed_context.round != record.context.round + 1:
            raise NegotiationStateError("Incoming negotiation round is inconsistent with local state.")
        elif (
            parsed_context.negotiation_type != record.context.negotiation_type
            or parsed_context.role != record.context.role
        ):
            raise NegotiationStateError("Incoming negotiation context is inconsistent with local state.")

        if (
            parsed_context.status == NegotiationStatus.IN_PROGRESS
            and parsed_context.round >= MAX_IN_PROGRESS_NEGOTIATION_ROUND
        ):
            receive_result = ReceiveResult(
                need_response=True,
                facts={},
                message="Negotiation reached the maximum in-progress round limit. Please reject it.",
            )
            record.context = parsed_context
            record.last_message = message
            record.last_receive_result = receive_result
            record.updated_at = self._utc_now()
            self._store.save(record)
            return self._build_receive_result_map(
                context=parsed_context,
                receive_result=receive_result,
            )

        negotiation_type = self._get_negotiation_type(parsed_context.negotiation_type)
        receive_result = negotiation_type.process_received_message(
            message=message,
            context=parsed_context,
            record=record,
        )
        record.context = parsed_context
        record.last_message = message
        record.last_receive_result = receive_result
        record.updated_at = self._utc_now()
        self._store.save(record)
        return self._build_receive_result_map(
            context=parsed_context,
            receive_result=receive_result,
        )

    def continue_(self, *, input: ContinueNegotiationInput) -> dict[str, object]:
        """Render the next local negotiation message and persist the advanced state."""
        record = self._store.get(input.context.negotiation_id)
        if record is None:
            raise NegotiationStateError("Negotiation record is missing.")
        if record.context.status in {NegotiationStatus.AGREED, NegotiationStatus.REJECTED}:
            raise NegotiationTerminalStateError("Cannot continue a terminal negotiation.")
        if (
            input.context.negotiation_type != record.context.negotiation_type
            or input.context.negotiation_id != record.context.negotiation_id
            or input.context.role != record.context.role
            or input.context.round != record.context.round
            or input.context.status != record.context.status
        ):
            # Continue operations must use the exact local snapshot to avoid diverging branches.
            raise NegotiationStateError("Negotiation continue context is inconsistent with local state.")

        negotiation_type = self._get_negotiation_type(input.context.negotiation_type)
        continue_result = negotiation_type.render_continue_prompt(
            record=record,
            context=input.context,
            status=input.status,
            content_text=input.content_text,
        )
        next_context = self._create_next_context(
            previous=input.context,
            status=input.status,
        )
        record.context = next_context
        record.last_continue_result = continue_result
        record.last_task_prompt = input.content_text
        record.updated_at = self._utc_now()
        self._store.save(record)
        return self._build_result_map(
            prompt_text=continue_result.prompt_text,
            context=next_context,
            final_task_prompt=continue_result.final_task_prompt,
        )

    def _get_negotiation_type(self, negotiation_type: NegotiationType) -> BaseNegotiationType:
        """Resolve the strategy object that implements one negotiation type."""
        try:
            return self._negotiation_types[negotiation_type]
        except KeyError as error:
            raise NegotiationInputError(f"Unsupported negotiation type: {negotiation_type.value}") from error

    @staticmethod
    def _normalize_negotiation_type(value: NegotiationType | str) -> NegotiationType:
        """Normalize external negotiation type values into the shared enum."""
        try:
            return value if isinstance(value, NegotiationType) else NegotiationType(str(value))
        except ValueError as error:
            raise NegotiationInputError(f"Unsupported negotiation type: {value}") from error

    @staticmethod
    def _utc_now() -> datetime:
        """Return the current UTC timestamp used for negotiation record bookkeeping."""
        return datetime.now(timezone.utc)

    @staticmethod
    def _create_start_context(*, negotiation_type: NegotiationType, role: NegotiationRole) -> NegotiationContext:
        """Create the initial context for a newly started negotiation."""
        return NegotiationContext(
            negotiation_type=negotiation_type,
            negotiation_id=str(uuid.uuid4()),
            role=role,
            round=1,
            status=NegotiationStatus.IN_PROGRESS,
            extra={},
        )

    @staticmethod
    def _create_next_context(*, previous: NegotiationContext, status: NegotiationStatus) -> NegotiationContext:
        """Advance a negotiation context to the next round while preserving identity."""
        return NegotiationContext(
            negotiation_type=previous.negotiation_type,
            negotiation_id=previous.negotiation_id,
            role=previous.role,
            round=previous.round + 1,
            status=status,
            extra=dict(previous.extra),
        )

    @staticmethod
    def _build_result_map(
        *,
        prompt_text: str,
        context: NegotiationContext,
        final_task_prompt: str | None = None,
    ) -> dict[str, object]:
        """Build the transport payload returned by start and continue operations."""
        negotiation_data: dict[str, object] = {"message": prompt_text}
        negotiation_data.update(context.to_context())
        result: dict[str, object] = {
            NEGOTIATION_T_URI_NL: negotiation_data,
        }
        if final_task_prompt is not None:
            result[TASK_PROMPT_KEY_NL] = final_task_prompt
        return result

    @staticmethod
    def _build_receive_result_map(
        *,
        context: NegotiationContext,
        receive_result: ReceiveResult,
    ) -> dict[str, object]:
        """Build the transport payload returned by receive operations."""
        return {
            "context": context.to_context(),
            "needResponse": receive_result.need_response,
            "facts": dict(receive_result.facts),
            "message": receive_result.message,
        }
