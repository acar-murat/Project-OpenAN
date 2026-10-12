from __future__ import annotations

from dataclasses import dataclass

from a2a_t.common.prompt_resources import PromptResourceAccess
from a2a_t.prompt.validation.json_schema_slot_validator import JsonSchemaSlotValidator


@dataclass(slots=True)
class PromptRuntimeComponents:
    """Group the shared prompt runtime services built from configuration.

    Every prompt-pipeline resource read goes through the single resource access object (D31); the
    JSON-schema slot validator is the only stateless helper shared by the client and server flows.
    """

    resource_access: PromptResourceAccess
    json_schema_slot_validator: JsonSchemaSlotValidator
