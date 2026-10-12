"""Deprecated state-machine negotiation demo package (D1 shim round).

This package belongs to the retired state-machine negotiation demo mirrored from the old Java
``negotiation.types`` model package. It is kept unchanged for one release and will be removed in
the next release; importing it emits a :class:`DeprecationWarning`. Note that the legacy facade
methods ``start/receive/continue_negotiation`` still consume this package's input types and are
deprecated with it.
"""

import warnings

from .constants import NEGOTIATION_T_URI, NEGOTIATION_T_URI_NL, TASK_PROMPT_KEY, TASK_PROMPT_KEY_NL
from .enums import NegotiationRole, NegotiationStatus, NegotiationType
from .errors import (
    NegotiationContextError,
    NegotiationInputError,
    NegotiationParseError,
    NegotiationStateError,
    NegotiationTerminalStateError,
)
from .models import (
    ContinueNegotiationInput,
    ContinueResult,
    NegotiationContext,
    NegotiationRecord,
    ReceiveResult,
    StartNegotiationInput,
)

__all__ = [
    "ContinueNegotiationInput",
    "ContinueResult",
    "NEGOTIATION_T_URI",
    "NEGOTIATION_T_URI_NL",
    "NegotiationContext",
    "NegotiationContextError",
    "NegotiationInputError",
    "NegotiationParseError",
    "NegotiationRecord",
    "NegotiationRole",
    "NegotiationStateError",
    "NegotiationStatus",
    "NegotiationTerminalStateError",
    "NegotiationType",
    "ReceiveResult",
    "StartNegotiationInput",
    "TASK_PROMPT_KEY",
    "TASK_PROMPT_KEY_NL",
]

warnings.warn(
    "The a2a_t.negotiation.common package is deprecated since 1.1.0 and will be removed in the "
    "next release; the state-machine negotiation demo is retired. Use the negotiation content "
    "pipeline instead (a2a_t.negotiation.content / generation / validation, exposed by the "
    "A2ATClient and A2ATServer negotiation content methods).",
    DeprecationWarning,
    stacklevel=2,
)
