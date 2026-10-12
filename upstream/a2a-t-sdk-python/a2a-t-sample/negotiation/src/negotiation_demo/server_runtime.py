"""Server-side runtime of the negotiation demo (Java ``NegotiationAgentExecutor``).

Receives one demo request carrying the Task-T prompt (plus, on the second turn, the
Negotiation-T accept message), validates the Task-T prompt through the SDK
(``validate_task_prompt_and_data_filling``) to discover which parameters are missing, and reacts:

* message 1 (params missing): builds the missing-items list from the validation result and
  generates a Negotiation-T information-propose message via the strategy (fromData or fromText),
  replying with ``INPUT_REQUIRED``;
* message 3 (params filled): accepts the negotiation, emits the diagnosis result derived from the
  extracted params and replies with ``COMPLETED``.

Nothing is hardcoded: the missing items, the accept content and the diagnosis are all derived from
the Task-T prompt through the SDK APIs, so the demo supports arbitrary Task-T inputs. The flow runs
in-process — the demo replaces the Java embedded HTTP server with a direct runtime call.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from a2a_t.core.errors.exceptions import ContentValidationError
from a2a_t.core.metadata import (
    NEGOTIATION_CONTEXT_METADATA_KEY,
    TEMPLATE_URI_METADATA_KEY,
    MetadataContent,
    NegotiationContext,
    NegotiationPerformative,
)
from a2a_t.core.validation_pipeline import FilledParamData
from a2a_t.negotiation.content.models import NegotiationItem
from a2a_t.server.a2at_server import A2ATServer

from .shared.constants import NEGOTIATION_PROPOSE, NEGOTIATION_T_URI, TASK_T_URI, TASK_TEMPLATE
from .shared.scenario_data import ScenarioData
from .shared.strategies import NegotiationStrategy, propose_context

#: Parameter keys the SDK injects as negotiation-context parameters (not business slots).
_CONTEXT_PARAM_KEYS = ("id", "round", "maxRounds")

#: Reply states of the two demo branches (Java task states).
STATE_INPUT_REQUIRED = "INPUT_REQUIRED"
STATE_COMPLETED = "COMPLETED"


@dataclass(slots=True)
class NegotiationRequest:
    """One inbound demo request: the A2A metadata map of the message."""

    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class NegotiationReply:
    """One outbound demo reply: the task state plus the reply metadata and diagnosis."""

    state: str
    metadata: dict[str, object] = field(default_factory=dict)
    diagnosis: str | None = None

    @property
    def negotiation_prompt_text(self) -> str:
        """The rendered negotiation message text of the reply, empty when there is none."""
        value = self.metadata.get(NEGOTIATION_T_URI)
        return str(value) if value is not None else ""


class NegotiationServerRuntime:
    """Server runtime driving messages 2 and 4 of the negotiation demo flow."""

    def __init__(
        self,
        server: A2ATServer,
        strategy: NegotiationStrategy,
        scenario: ScenarioData,
        log_sink: Callable[[str], None] | None = None,
    ) -> None:
        """Create the runtime over one server facade, strategy and scenario configuration.

        Args:
            server: server facade used for validation and negotiation generation.
            strategy: negotiation message generation strategy (fromData or fromText).
            scenario: scenario accessor carrying the task schema, phrasing and diagnosis templates.
            log_sink: optional sink receiving the flow logs.
        """
        self._server = server
        self._strategy = strategy
        self._scenario = scenario
        self._log_sink = log_sink

    def handle_request(self, request: NegotiationRequest) -> NegotiationReply:
        """Handle one inbound request and produce the reply of the demo flow."""
        metadata = request.metadata or {}
        task_prompt = str(metadata.get(TASK_T_URI, ""))
        has_negotiation = bool(metadata.get(NEGOTIATION_T_URI))
        self._emit(f"[server] received task prompt, hasNegMsg={has_negotiation}")

        params: FilledParamData | None
        try:
            params = self._server.validate_task_prompt_and_data_filling(
                task_prompt, self._scenario.task_schema(), TASK_TEMPLATE
            )
            self._emit(f"[server] extracted params: {params.data}")
            missing_items = self._find_missing_items(params)
        except ContentValidationError as error:
            self._emit("[server] validation rejected, extracting missing items from errors")
            params = None
            missing_items = self._missing_items_from_errors(error.errors)

        if missing_items:
            return self._handle_missing_params(metadata, missing_items)
        assert params is not None
        return self._handle_filled_params(params)

    # -- message 2: params missing -> Negotiation-T information propose -> INPUT_REQUIRED --

    def _handle_missing_params(
        self,
        request_metadata: dict[str, object],
        missing_items: list[NegotiationItem],
    ) -> NegotiationReply:
        """Generate the negotiation request for the missing items and reply INPUT_REQUIRED."""
        self._emit("[server] === message 2: params missing -> negotiation request ===")
        self._emit(f"[server] missing items: {[(item.name, item.value) for item in missing_items]}")

        relationship = None
        if len(missing_items) > 1:
            relationship = self._scenario.negotiation_phrasing().get("propose_relationship")

        negotiation_prompt = self._strategy.generate_propose(
            self._server,
            propose_context(),
            missing_items,
            relationship,
            NEGOTIATION_PROPOSE,
        )
        self._emit("[server] negotiation request rendered")

        reply_metadata = _reply_metadata(negotiation_prompt, request_metadata)
        self._emit("[server] -> INPUT_REQUIRED")
        return NegotiationReply(state=STATE_INPUT_REQUIRED, metadata=reply_metadata)

    # -- message 4: params filled -> diagnosis result -> COMPLETED --

    def _handle_filled_params(self, params: FilledParamData) -> NegotiationReply:
        """Emit the diagnosis result derived from the extracted params and reply COMPLETED."""
        self._emit("[server] === message 4: params filled -> diagnosis result ===")
        diagnosis = diagnose(params, self._scenario)
        self._emit("[server] diagnosis result emitted")
        self._emit("[server] -> COMPLETED")
        reply_metadata = {TASK_T_URI: diagnosis, TEMPLATE_URI_METADATA_KEY: TASK_TEMPLATE}
        return NegotiationReply(state=STATE_COMPLETED, metadata=reply_metadata, diagnosis=diagnosis)

    def _find_missing_items(self, params: FilledParamData) -> list[NegotiationItem]:
        """Find parameters that are missing (``None`` or blank) from the validated params."""
        missing: list[NegotiationItem] = []
        for key, value in params.data.items():
            if key in _CONTEXT_PARAM_KEYS:
                continue
            if _is_missing(value):
                missing.append(self._missing_item(str(key)))
        return missing

    def _missing_items_from_errors(self, errors: Any) -> list[NegotiationItem]:
        """Build the missing-items list from the semantic validation errors of a rejection."""
        missing: list[NegotiationItem] = []
        for error in errors or []:
            slot_name = getattr(error, "slot_name", None)
            if isinstance(slot_name, str) and slot_name.strip():
                missing.append(self._missing_item(slot_name))
        return missing

    def _missing_item(self, slot_name: str) -> NegotiationItem:
        """Build one missing-item entry from the scenario phrasing and slot description."""
        template = self._scenario.negotiation_phrasing().get("missing_item_hint", "{slot}")
        description = _slot_description(self._scenario.task_schema(), slot_name)
        hint = template.replace("{slot}", slot_name).replace("{description}", description or "")
        return NegotiationItem(name=slot_name, value=hint)

    def _emit(self, message: str) -> None:
        """Write one flow log through the configured sink."""
        if self._log_sink is not None:
            self._log_sink(message)


def diagnose(params: FilledParamData, scenario: ScenarioData) -> str:
    """Render the diagnosis result from the extracted params and the scenario templates."""
    templates = scenario.diagnosis_templates()
    rendered_params = "; ".join(f"{key}: {value}" for key, value in params.data.items())
    lines = [
        templates.get("result_line", ""),
        templates.get("detail_line", "").replace("{params}", rendered_params),
        templates.get("advice_line", ""),
    ]
    return "\n".join(line for line in lines if line)


def _reply_metadata(
    negotiation_prompt: MetadataContent,
    request_metadata: dict[str, object],
) -> dict[str, object]:
    """Merge the generated negotiation message metadata with the carried negotiation context."""
    metadata = negotiation_prompt.build_metadata_content()
    carried_context = request_metadata.get(NEGOTIATION_CONTEXT_METADATA_KEY)
    if carried_context is not None:
        metadata[NEGOTIATION_CONTEXT_METADATA_KEY] = carried_context
    return metadata


def _slot_description(task_schema: dict[str, object], slot_name: str) -> str | None:
    """Look up the description of one slot in the scenario Task-T schema."""
    properties = task_schema.get("properties")
    if isinstance(properties, dict):
        slot = properties.get(slot_name)
        if isinstance(slot, dict):
            description = slot.get("description")
            if isinstance(description, str) and description.strip():
                return description
    return None


def _is_missing(value: object) -> bool:
    """Report whether one parameter value is missing (``None`` or blank)."""
    return value is None or (isinstance(value, str) and not value.strip())


def parse_negotiation_context(metadata: dict[str, object]) -> NegotiationContext | None:
    """Parse the negotiation context carried in one reply metadata map.

    The context travels as the nested ``negotiationContext`` map (``id`` / ``round`` /
    ``maxRounds`` / ``performative``); ``None`` when the reply carries no session context.
    """
    raw = metadata.get(NEGOTIATION_CONTEXT_METADATA_KEY)
    if not isinstance(raw, dict):
        return None
    performative = NegotiationPerformative.try_parse(str(raw.get("performative", "") or ""))
    if performative is None:
        return None
    return NegotiationContext(
        id=str(raw.get("id", "")),
        round=int(raw.get("round", 1)),
        max_rounds=int(raw.get("maxRounds", NegotiationContext.DEFAULT_MAX_ROUNDS)),
        performative=performative,
    )
