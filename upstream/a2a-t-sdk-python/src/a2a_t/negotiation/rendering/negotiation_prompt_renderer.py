from __future__ import annotations

from a2a_t.negotiation.common.enums import NegotiationType


class NegotiationPromptRenderer:
    """Render negotiation messages into the transport payload text."""

    def render(self, *, negotiation_type: NegotiationType, message: str) -> str:
        """Render a negotiation message for the given negotiation type."""
        return message

    def render_start(self, *, negotiation_type: NegotiationType, message: str) -> str:
        """Render the opening message for a negotiation."""
        return self.render(
            negotiation_type=negotiation_type,
            message=message,
        )

    def render_continue(
        self,
        *,
        negotiation_type: NegotiationType,
        message: str,
    ) -> str:
        """Render a follow-up message for a negotiation."""
        return self.render(
            negotiation_type=negotiation_type,
            message=message,
        )
