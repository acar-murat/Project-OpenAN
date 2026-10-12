from __future__ import annotations

from pathlib import Path
from typing import Any

from a2a_t.negotiation.common.enums import NegotiationType
from a2a_t.negotiation.handling import NegotiationHandler
from a2a_t.negotiation.rendering import NegotiationPromptRenderer
from a2a_t.negotiation.store import NegotiationStateStoreFactory
from a2a_t.negotiation.types import (
    FeasibilityNegotiationType,
    InformationNegotiationType,
    TargetNegotiationType,
)

from .negotiation_orchestrator import NegotiationOrchestrator


class ClientNegotiationOrchestratorBuilder:
    """Assemble the client-side negotiation runtime."""

    def __init__(
        self,
        *,
        prompt_renderer_cls: type = NegotiationPromptRenderer,
        store_factory: NegotiationStateStoreFactory | None = None,
        handler_cls: type = NegotiationHandler,
        orchestrator_cls: type = NegotiationOrchestrator,
    ) -> None:
        self._prompt_renderer_cls = prompt_renderer_cls
        self._store_factory = store_factory or NegotiationStateStoreFactory()
        self._handler_cls = handler_cls
        self._orchestrator_cls = orchestrator_cls

    def build(
        self,
        *,
        env_path: str | Path | None = None,
        logger: Any | None = None,
    ) -> NegotiationOrchestrator:
        """Build a client negotiation orchestrator with all supported negotiation types."""
        prompt_renderer = self._prompt_renderer_cls()
        store = self._build_store(env_path=env_path, logger=logger)
        handler = self._handler_cls(
            negotiation_types={
                NegotiationType.INFORMATION: InformationNegotiationType(prompt_renderer=prompt_renderer),
                NegotiationType.TARGET: TargetNegotiationType(prompt_renderer=prompt_renderer),
                NegotiationType.FEASIBILITY: FeasibilityNegotiationType(prompt_renderer=prompt_renderer),
            },
            store=store,
        )
        return self._orchestrator_cls(  # type: ignore[no-any-return]
            handler=handler,
            logger=logger,
        )

    def _build_store(self, *, env_path: str | Path | None, logger: Any | None) -> object:
        """Resolve the negotiation state store configured for the client runtime."""
        return self._store_factory.build(
            env_path=env_path,
            logger=logger,
        )
