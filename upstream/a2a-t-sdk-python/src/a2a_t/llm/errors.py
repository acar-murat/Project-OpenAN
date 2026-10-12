"""Error types for LLM integration."""

from __future__ import annotations

from typing import Final

from a2a_t.core.errors.catalog import ErrorCatalog
from a2a_t.core.errors.exceptions import A2ATError

#: Message markers identifying an LLM response-contract violation (Java ``RESPONSE_CONTRACT_MARKERS``).
#: An error whose message carries one of these markers is translated to ``llm.response_invalid``
#: at the orchestrator boundary instead of ``llm.invocation_failed``.
RESPONSE_CONTRACT_MARKERS: Final[tuple[str, ...]] = (
    "returned invalid json",
    "returned empty content",
    "must return a json object",
    "response did not include",
)


def is_response_contract_violation(error: BaseException) -> bool:
    """Report whether one error message matches the LLM response-contract violation markers.

    Args:
        error: error raised by an LLM client or an analysis step parsing its response

    Returns:
        whether the error describes a response-contract violation rather than a transport failure
    """
    message = str(error).lower()
    return any(marker in message for marker in RESPONSE_CONTRACT_MARKERS)


class LLMError(A2ATError):
    """Base exception for llm module.

    Part of the :class:`~a2a_t.core.errors.exceptions.A2ATError` tree with the default
    ``infra.internal_error`` code (Java parity: ``LLMError`` extends ``A2ATError`` without its own
    code); the orchestrator boundaries translate it to the step-specific ``llm.*`` catalog code.
    """


class LLMConfigError(LLMError):
    """Raised when llm configuration is invalid (``llm.not_configured``)."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code=ErrorCatalog.LLM_NOT_CONFIGURED)


class LLMRuntimeError(LLMError):
    """Raised when an llm invocation fails at runtime (``llm.invocation_failed``).

    Response-contract violations (invalid JSON, empty content, missing fields) also travel
    through this class; the orchestrator boundary refines them to ``llm.response_invalid`` using
    :func:`is_response_contract_violation`.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message, code=ErrorCatalog.LLM_INVOCATION_FAILED)
