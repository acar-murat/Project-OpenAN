from __future__ import annotations

from a2a_t.negotiation.common.models import NegotiationRecord


class InMemoryNegotiationStateStore:
    """Persist negotiation records in process memory."""

    def __init__(self) -> None:
        self._records: dict[str, NegotiationRecord] = {}

    def get(self, negotiation_id: str) -> NegotiationRecord | None:
        """Return the negotiation record for the given identifier."""
        return self._records.get(negotiation_id)

    def save(self, record: NegotiationRecord) -> None:
        """Persist or replace a negotiation record by its identifier."""
        self._records[record.context.negotiation_id] = record

    def delete(self, negotiation_id: str) -> None:
        """Delete a negotiation record when it exists."""
        self._records.pop(negotiation_id, None)

    def cleanup_expired(self) -> bool:
        """Report success for the no-op cleanup used by the in-memory store."""
        return True
