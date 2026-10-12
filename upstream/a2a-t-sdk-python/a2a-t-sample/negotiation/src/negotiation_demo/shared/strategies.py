"""Negotiation message generation strategies (Java ``NegotiationStrategy`` hierarchy).

Isolates the fromData (rule-based) vs fromText (LLM) difference behind one strategy interface.
Everything else in the demo — Task-T generation, ``validate_task_prompt_and_data_filling``
parameter validation, the reply flow — is identical regardless of which strategy is active: only
the negotiation prompt generation step differs. fromData builds typed content records and calls
the deterministic API (zero LLM calls); fromText converts the items to natural-language text and
lets the SDK's LLM content-extraction step parse it.
"""

from __future__ import annotations

from typing import Protocol

from a2a_t.client.a2at_client import A2ATClient
from a2a_t.core.metadata import MetadataContent, NegotiationContext, NegotiationPerformative
from a2a_t.negotiation.content.enums import NegotiationConclusion
from a2a_t.negotiation.content.models import (
    InformationEndingContent,
    InformationProposeContent,
    NegotiationEndingData,
    NegotiationItem,
    NegotiationProposeData,
)
from a2a_t.server.a2at_server import A2ATServer

from .scenario_data import ScenarioData


class NegotiationStrategy(Protocol):
    """Strategy seam of the negotiation message generation step."""

    def generate_propose(
        self,
        server: A2ATServer,
        context: NegotiationContext,
        missing_items: list[NegotiationItem],
        relationship: str | None,
        template_uri: str,
    ) -> MetadataContent:
        """Generate a propose-phase negotiation message from the missing information items."""
        ...

    def generate_accept(
        self,
        client: A2ATClient,
        context: NegotiationContext,
        filled_items: list[NegotiationItem],
        template_uri: str,
    ) -> MetadataContent:
        """Generate an accept-phase negotiation message from the filled information items."""
        ...


class FromDataStrategy:
    """Rule-based strategy: builds typed records and calls the deterministic fromData API.

    No LLM call is made for the negotiation message generation — the SDK renders the typed content
    directly from the template (the "structured data" path).
    """

    def __init__(self, scenario: ScenarioData) -> None:
        """Create the strategy over one scenario configuration.

        Args:
            scenario: scenario accessor carrying the negotiation phrasing templates.
        """
        self._scenario = scenario

    def generate_propose(
        self,
        server: A2ATServer,
        context: NegotiationContext,
        missing_items: list[NegotiationItem],
        relationship: str | None,
        template_uri: str,
    ) -> MetadataContent:
        """Generate the propose message from typed information content (zero LLM calls)."""
        content = InformationProposeContent(items=missing_items, relationship=relationship)
        return server.generate_negotiation_propose_prompt_from_data(
            NegotiationProposeData(context=context, content=content), template_uri
        )

    def generate_accept(
        self,
        client: A2ATClient,
        context: NegotiationContext,
        filled_items: list[NegotiationItem],
        template_uri: str,
    ) -> MetadataContent:
        """Generate the accept message from typed ending content (zero LLM calls)."""
        content = InformationEndingContent(conclusion=NegotiationConclusion.ACCEPT, items=filled_items)
        return client.generate_negotiation_accept_prompt_from_data(
            NegotiationEndingData(context=context, content=content), template_uri
        )


class FromTextStrategy:
    """LLM-based strategy: converts the items to natural-language text and calls the fromText API.

    The SDK runs one LLM content-extraction step to parse the text into typed content, then renders
    deterministically like the from-data variant. The sentence framing comes from the scenario
    phrasing templates; the item lines follow one generic numbered-list rule.
    """

    def __init__(self, scenario: ScenarioData) -> None:
        """Create the strategy over one scenario configuration.

        Args:
            scenario: scenario accessor carrying the negotiation phrasing templates.
        """
        self._scenario = scenario

    def generate_propose(
        self,
        server: A2ATServer,
        context: NegotiationContext,
        missing_items: list[NegotiationItem],
        relationship: str | None,
        template_uri: str,
    ) -> MetadataContent:
        """Generate the propose message from the natural-language rendering of the items."""
        phrasing = self._scenario.negotiation_phrasing()
        text = phrasing.get("from_text_propose_prefix", "") + _numbered_items(missing_items)
        if relationship:
            text += relationship
        return server.generate_negotiation_propose_prompt_from_text(text, context, template_uri)

    def generate_accept(
        self,
        client: A2ATClient,
        context: NegotiationContext,
        filled_items: list[NegotiationItem],
        template_uri: str,
    ) -> MetadataContent:
        """Generate the accept message from the natural-language rendering of the items."""
        phrasing = self._scenario.negotiation_phrasing()
        text = (
            phrasing.get("from_text_accept_prefix", "")
            + _numbered_items(filled_items)
            + phrasing.get("from_text_accept_suffix", "")
        )
        return client.generate_negotiation_accept_prompt_from_text(text, context, template_uri)


def _numbered_items(items: list[NegotiationItem]) -> str:
    """Render the items as one numbered list: ``N. name：value；`` per item (Java rule).

    The value is omitted when blank; the full-width separators keep the rendering identical to the
    Java demo for both languages.
    """
    lines: list[str] = []
    for index, item in enumerate(items, start=1):
        line = f"{index}. {item.name}"
        if item.value is not None and item.value.strip():
            line += f"：{item.value}"
        lines.append(f"{line}；")
    return "".join(lines)


def items_from_params(params: dict[str, object]) -> list[NegotiationItem]:
    """Build the filled-items list from one parameter map, adapting to any parameter set."""
    return [NegotiationItem(name=str(key), value=str(value)) for key, value in params.items()]


def accept_context(session: NegotiationContext) -> NegotiationContext:
    """Stamp one session context for the client's accept message.

    The accept continues the server's negotiation session: same id and round budget, round advanced
    by one, performative stamped ``ACCEPT`` (the session state travels in the metadata, never in the
    SDK — port plan 7.5).
    """
    return session.next_round().with_performative(NegotiationPerformative.ACCEPT)


def propose_context() -> NegotiationContext:
    """Build the fresh session context of the server's first propose message."""
    import uuid

    return NegotiationContext(
        id=str(uuid.uuid4()),
        round=1,
        max_rounds=NegotiationContext.DEFAULT_MAX_ROUNDS,
        performative=NegotiationPerformative.PROPOSE,
    )
