"""Client-side runtime of the negotiation demo (Java ``NegotiationClient``, in-process).

Drives messages 1 and 3 of the flow:

* message 1: generate the Task-T prompt with missing params via
  ``generate_task_prompt_from_data_with_schema`` and hand it to the server runtime;
* message 3: generate the Task-T prompt with filled params plus the Negotiation-T accept message
  via the strategy, and hand both to the server runtime.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from a2a_t.client.a2at_client import A2ATClient
from a2a_t.core.metadata import (
    NEGOTIATION_CONTEXT_METADATA_KEY,
    TEMPLATE_URI_METADATA_KEY,
    MetadataContent,
    NegotiationContext,
)

from .server_runtime import NegotiationReply, NegotiationRequest, NegotiationServerRuntime, parse_negotiation_context
from .shared.constants import NEGOTIATION_ACCEPT, NEGOTIATION_T_URI, TASK_T_URI, TASK_TEMPLATE
from .shared.scenario_data import ScenarioData
from .shared.strategies import NegotiationStrategy, accept_context, items_from_params


class NegotiationClient:
    """Client runtime generating the outbound prompts of the negotiation demo flow."""

    def __init__(
        self,
        client: A2ATClient,
        strategy: NegotiationStrategy,
        scenario: ScenarioData,
        log_sink: Callable[[str], None] | None = None,
    ) -> None:
        """Create the client runtime over one client facade, strategy and scenario configuration.

        Args:
            client: client facade used for the Task-T prompt generation and the accept message.
            strategy: negotiation message generation strategy (fromData or fromText).
            scenario: scenario accessor carrying the task schema and the parameter maps.
            log_sink: optional sink receiving the flow logs.
        """
        self._client = client
        self._strategy = strategy
        self._scenario = scenario
        self._log_sink = log_sink

    def build_task_prompt(self, params: Mapping[str, object]) -> MetadataContent:
        """Generate one Task-T prompt from structured input and the scenario data schema."""
        return self._client.generate_task_prompt_from_data_with_schema(
            dict(params), self._scenario.task_schema(), TASK_TEMPLATE
        )

    def build_accept(
        self,
        session: NegotiationContext,
        filled_params: Mapping[str, object],
    ) -> MetadataContent:
        """Generate the Negotiation-T accept message continuing the server's session."""
        return self._strategy.generate_accept(
            self._client,
            accept_context(session),
            items_from_params(dict(filled_params)),
            NEGOTIATION_ACCEPT,
        )

    def run_four_message_flow(self, server_runtime: NegotiationServerRuntime) -> dict[str, object]:
        """Run the 4-message flow against the server runtime and return the scenario summary.

        Message 1 sends the missing-params Task-T prompt; message 2 (the server's
        ``INPUT_REQUIRED`` reply) carries the negotiation request; message 3 sends the
        filled-params Task-T prompt together with the Negotiation-T accept; message 4 (the
        server's ``COMPLETED`` reply) carries the diagnosis result.
        """
        # -- message 1: Task-T with missing params --
        self._emit("[client] === message 1: Task-T (params missing) ===")
        task_missing = self.build_task_prompt(self._scenario.missing_params())
        self._emit("[client] Task-T prompt rendered (params missing)")

        reply1 = server_runtime.handle_request(
            NegotiationRequest(metadata={TASK_T_URI: task_missing.prompt_text or ""})
        )
        self._emit("[client] received message 2 (negotiation request)")

        session = parse_negotiation_context(reply1.metadata)
        if session is None:
            raise ValueError("The negotiation request reply carries no negotiation context.")

        # -- message 3: Task-T with filled params + Negotiation-T accept --
        self._emit("[client] === message 3: Task-T (params filled) + Negotiation-T accept ===")
        task_filled = self.build_task_prompt(self._scenario.filled_params())
        self._emit("[client] Task-T prompt rendered (params filled)")

        accept_prompt = self.build_accept(session, self._scenario.filled_params())
        self._emit("[client] Negotiation-T accept rendered")

        request_metadata: dict[str, object] = {
            TASK_T_URI: task_filled.prompt_text,
            NEGOTIATION_T_URI: accept_prompt.prompt_text,
            TEMPLATE_URI_METADATA_KEY: TASK_TEMPLATE,
            NEGOTIATION_CONTEXT_METADATA_KEY: {
                "id": session.id,
                "round": session.round + 1,
                "maxRounds": session.max_rounds,
                "performative": accept_prompt.negotiation_context.performative.value
                if accept_prompt.negotiation_context is not None
                else "ACCEPT",
            },
        }
        reply2 = server_runtime.handle_request(NegotiationRequest(metadata=request_metadata))
        self._emit("[client] received message 4 (diagnosis result)")

        return {
            "scenario": self._scenario.scenario_name,
            "messages": 4,
            "outcome": reply2.state,
            "negotiation_request": reply1.negotiation_prompt_text,
            "diagnosis": reply2.diagnosis or "",
        }

    def _emit(self, message: str) -> None:
        """Write one flow log through the configured sink."""
        if self._log_sink is not None:
            self._log_sink(message)


def summarize(reply: NegotiationReply) -> str:
    """Render one demo reply as a single log line (diagnostics helper)."""
    if reply.diagnosis is not None:
        return f"state={reply.state} diagnosis={reply.diagnosis.splitlines()[0]}"
    return f"state={reply.state} negotiation={reply.negotiation_prompt_text.splitlines()[0]}"
