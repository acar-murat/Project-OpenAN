"""Deprecated state-machine negotiation demo package (D1 shim round).

This package belongs to the retired state-machine negotiation demo mirrored from the old Java
``negotiation.rendering`` package. It is kept unchanged for one release and will be removed in the
next release; importing it emits a :class:`DeprecationWarning`.
"""

import warnings

from .negotiation_prompt_renderer import NegotiationPromptRenderer

__all__ = [
    "NegotiationPromptRenderer",
]

warnings.warn(
    "The a2a_t.negotiation.rendering package is deprecated since 1.1.0 and will be removed in the "
    "next release; the state-machine negotiation demo is retired. Use the negotiation content "
    "pipeline instead (a2a_t.negotiation.content / generation / validation, exposed by the "
    "A2ATClient and A2ATServer negotiation content methods).",
    DeprecationWarning,
    stacklevel=2,
)
