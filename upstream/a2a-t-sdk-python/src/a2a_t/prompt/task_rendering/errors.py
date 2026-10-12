from __future__ import annotations

from a2a_t.core.errors.catalog import ErrorCatalog
from a2a_t.core.errors.exceptions import A2ATBusinessError


class TaskPromptRenderError(A2ATBusinessError):
    """Raised when a task prompt cannot be rendered.

    Java parity (``TaskPromptRenderException``): carries the ``template.render_failed`` code with
    the concrete rendering problem as the ``reason`` fact. The template URI is not known to the
    renderer and is supplied by the orchestrator that catches this error.
    """

    def __init__(self, message: str) -> None:
        super().__init__(ErrorCatalog.TEMPLATE_RENDER_FAILED, {"reason": message}, message=message)
