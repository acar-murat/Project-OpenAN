from __future__ import annotations

from dataclasses import dataclass

from .enums import NegotiationRole, NegotiationStatus, NegotiationType
from .errors import NegotiationContextError


@dataclass(slots=True)
class StartNegotiationInput:
    """Carry the input required to open a negotiation."""

    type: NegotiationType
    content_text: str
    facts: dict[str, object]


@dataclass(slots=True)
class ContinueNegotiationInput:
    """Carry the input required to continue an active negotiation."""

    context: "NegotiationContext"
    status: NegotiationStatus
    content_text: str


@dataclass(slots=True)
class NegotiationContext:
    """Represent the transport-safe context shared between negotiation rounds."""

    negotiation_type: NegotiationType
    negotiation_id: str
    role: NegotiationRole
    round: int
    status: NegotiationStatus
    extra: dict[str, object]

    @classmethod
    def from_context(cls, context: dict[str, object]) -> "NegotiationContext":
        """Parse and validate a serialized negotiation context payload."""
        try:
            negotiation_type = NegotiationType(str(context["negotiationType"]))
            negotiation_id = str(context["negotiationId"])
            # role is optional: Java SDK context payload omits it; default to CLIENT.
            raw_role = context.get("role", NegotiationRole.CLIENT.value)
            role = NegotiationRole(str(raw_role))
            round_value = int(str(context["round"]))
            status = NegotiationStatus(str(context["status"]))
            # extra is optional: Java SDK defaults it to empty map.
            extra = context.get("extra", {})
        except (KeyError, TypeError, ValueError) as error:
            raise NegotiationContextError("Invalid negotiation context.") from error

        if not negotiation_id or round_value < 1 or not isinstance(extra, dict):
            raise NegotiationContextError("Invalid negotiation context.")

        return cls(
            negotiation_type=negotiation_type,
            negotiation_id=negotiation_id,
            role=role,
            round=round_value,
            status=status,
            extra=dict(extra),
        )

    def to_context(self) -> dict[str, object]:
        """Serialize the negotiation context into the transport payload shape."""
        return {
            "negotiationType": self.negotiation_type.value,
            "negotiationId": self.negotiation_id,
            "role": self.role.value,
            "round": self.round,
            "status": self.status.value,
            "extra": dict(self.extra),
        }


@dataclass(slots=True)
class ReceiveResult:
    """Represent the local outcome of processing a received negotiation message."""

    need_response: bool
    facts: dict[str, object]
    message: str = ""


@dataclass(slots=True)
class ContinueResult:
    """Represent the prompt emitted when a negotiation is continued locally."""

    prompt_text: str
    final_task_prompt: str | None


@dataclass(slots=True)
class NegotiationRecord:
    """Persist the local state accumulated for one negotiation."""

    context: NegotiationContext
    last_message: str | None
    last_receive_result: ReceiveResult | None
    last_continue_result: ContinueResult | None
    last_task_prompt: str | None
    created_at: object
    updated_at: object
