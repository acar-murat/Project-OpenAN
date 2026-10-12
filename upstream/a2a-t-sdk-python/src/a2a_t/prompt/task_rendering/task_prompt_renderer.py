from __future__ import annotations

from collections.abc import Mapping

from .sectioned_renderer import collapse_sections


class TaskPromptRenderer:
    """Render task prompt templates into plain prompt bodies (collapse policy).

    Thin orchestrator-facing adapter over :func:`collapse_sections`: the task prompt
    pipeline keeps the section scaffolding and collapses standalone slot lines to their
    slot values (Java ``TaskPromptRenderer``). The ``scenario_code`` / ``language`` /
    ``description`` arguments exist for orchestrator wiring only — they are not part of
    the rendering grammar, mirroring the Java renderer which does not receive them
    either.
    """

    def render(
        self,
        *,
        template_text: str,
        slots: Mapping[str, str | None],
        scenario_code: str,
        language: str,
        description: str,
    ) -> str:
        """Render a processed task prompt body from a template and extracted slots."""
        return collapse_sections(template_text, slots)
