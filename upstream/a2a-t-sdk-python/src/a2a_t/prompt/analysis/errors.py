from __future__ import annotations

from a2a_t.core.errors.exceptions import A2ATError


class PromptAnalysisError(A2ATError):
    """Base class for shared prompt analysis errors.

    Part of the :class:`~a2a_t.core.errors.exceptions.A2ATError` tree with the default
    ``infra.internal_error`` code (Java parity: the analysis exceptions extend ``A2ATError``
    without their own code). Orchestrator boundaries translate them to the step-specific catalog
    code, for example ``llm.response_invalid`` for a response-contract violation or
    ``scenario.not_matched`` during scenario recognition.
    """

    def __init__(self, message: str, **context: object) -> None:
        super().__init__(message)
        self.context = context


class ScenarioRecognitionError(PromptAnalysisError):
    """Raised when scenario recognition output is invalid."""


class SlotExtractionError(PromptAnalysisError):
    """Raised when slot extraction output is invalid."""
