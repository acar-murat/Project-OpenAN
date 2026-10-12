from __future__ import annotations

from typing import Any

from a2a_t.negotiation.common.enums import NegotiationRole
from a2a_t.negotiation.runtime.base_negotiation_orchestrator import BaseNegotiationOrchestrator


class NegotiationOrchestrator(BaseNegotiationOrchestrator):
    """Bind the shared negotiation runtime to the server role."""

    def __init__(self, *, handler: Any, logger: Any | None = None) -> None:
        super().__init__(
            handler=handler,
            role=NegotiationRole.SERVER,
            logger=logger,
        )
