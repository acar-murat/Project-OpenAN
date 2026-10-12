"""A2A-T identifiers used by the negotiation demo (Java ``DemoConstants``).

Centralizes every A2A-T identifier so the client and server flows reference them from one place.
Template URIs come from the SDK's :mod:`a2a_t.core.standard_templates` constants.
"""

from __future__ import annotations

from a2a_t.core.metadata import NEGOTIATION_T_EXTENSION_URI
from a2a_t.core.standard_templates import (
    INFORMATION_NEGOTIATION_ACCEPT_REJECT_URI,
    INFORMATION_NEGOTIATION_PROPOSE_URI,
    PRIVATE_LINE_COMPLAINT_URI,
)

__all__ = [
    "NEGOTIATION_T_URI",
    "NEGOTIATION_ACCEPT",
    "NEGOTIATION_PROPOSE",
    "TASK_TEMPLATE",
    "TASK_T_URI",
]

#: Task-T extension URI under which the task prompt travels in the demo metadata.
TASK_T_URI = "https://projects.tmforum.org/a2aproject/telecommunication/extensions/Task-T/v1"

#: Negotiation-T extension URI under which the negotiation messages travel in the demo metadata.
NEGOTIATION_T_URI = NEGOTIATION_T_EXTENSION_URI

#: Task-T template URI of the SPN private-line-complaint diagnosis scenario.
TASK_TEMPLATE = PRIVATE_LINE_COMPLAINT_URI

#: Negotiation-T information propose template (request the missing information).
NEGOTIATION_PROPOSE = INFORMATION_NEGOTIATION_PROPOSE_URI

#: Negotiation-T information accept-reject template (accept once the params are filled).
NEGOTIATION_ACCEPT = INFORMATION_NEGOTIATION_ACCEPT_REJECT_URI
