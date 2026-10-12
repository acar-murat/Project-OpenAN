"""Top-level prompt package for A2A-T."""

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = [
    "PromptReference",
    "TaskPromptMetadata",
    "TaskPromptFormatError",
    "format_task_prompt",
    "parse_task_prompt_metadata",
    "TaskPromptRenderer",
    "TaskPromptRenderError",
    "collapse_sections",
    "drop_sections",
]

_EXPORTS: dict[str, tuple[str, str]] = {
    "PromptReference": ("a2a_t.prompt.common.models", "PromptReference"),
    "TaskPromptMetadata": ("a2a_t.prompt.common.models", "TaskPromptMetadata"),
    "TaskPromptFormatError": ("a2a_t.prompt.common.errors", "TaskPromptFormatError"),
    "format_task_prompt": ("a2a_t.prompt.common.task_prompt_format", "format_task_prompt"),
    "parse_task_prompt_metadata": ("a2a_t.prompt.common.task_prompt_format", "parse_task_prompt_metadata"),
    "TaskPromptRenderer": ("a2a_t.prompt.task_rendering", "TaskPromptRenderer"),
    "TaskPromptRenderError": ("a2a_t.prompt.task_rendering.errors", "TaskPromptRenderError"),
    "collapse_sections": ("a2a_t.prompt.task_rendering", "collapse_sections"),
    "drop_sections": ("a2a_t.prompt.task_rendering", "drop_sections"),
}


def __getattr__(name: str) -> Any:
    try:
        module_name, attr_name = _EXPORTS[name]
    except KeyError as error:
        raise AttributeError(f"module 'a2a_t.prompt' has no attribute {name!r}") from error

    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value
