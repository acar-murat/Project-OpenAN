"""Common utilities and shared components for a2a_t."""

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = ["prompt_resources", "prompt_runtime"]

_LAZY_IMPORTS = {
    "prompt_resources": "a2a_t.common.prompt_resources",
    "prompt_runtime": "a2a_t.common.prompt_runtime",
}


def __getattr__(name: str) -> Any:
    module_name = _LAZY_IMPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module 'a2a_t.common' has no attribute {name!r}")
    module = import_module(module_name)
    globals()[name] = module
    return module
