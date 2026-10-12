"""Scenario configuration of the negotiation demo (Java ``ScenarioData``).

Loads the bundled ``resources/scenario.json``. The demo code contains only generic assembly rules
(how to iterate slots, how to merge metadata); every scenario-specific value lives in the JSON file:
the Task-T parameter schema, the missing/filled parameter maps driving the 4-message flow, the
negotiation phrasing templates and the diagnosis result templates — one section per language.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_RESOURCES_DIR = Path(__file__).resolve().parents[3] / "resources"

#: Supported demo languages (each needs a section in the scenario file and mock responses).
SUPPORTED_LANGUAGES = ("en-US", "zh-CN")

#: Marker value that only the filled-params input carries; the scripted mock LLM uses it to tell
#: the missing-params calls and the filled-params calls apart.
FILLED_PARAMS_MARKER = "event-id-20260511-09013"


def _scenario_document() -> dict[str, Any]:
    """Load the scenario document, keyed by language."""
    with (_RESOURCES_DIR / "scenario.json").open(encoding="utf-8") as file:
        document: dict[str, Any] = json.load(file)
    return document


def resolve_language(env_path: Path | None = None) -> str:
    """Resolve the demo language from the ``.env`` file, defaulting to ``en-US``.

    Args:
        env_path: optional ``.env`` file path; ``None`` reads ``./.env`` when it exists.

    Returns:
        the configured language when it is one of the supported languages, else ``en-US``.
    """
    raw_value = ""
    candidates = [env_path, Path.cwd() / ".env"]
    for candidate in candidates:
        if candidate is not None and candidate.exists():
            from dotenv import dotenv_values

            raw_value = str(dotenv_values(candidate).get("A2AT_LANGUAGE", "") or "")
            break
    language = raw_value.strip() or "en-US"
    return language if language in SUPPORTED_LANGUAGES else "en-US"


class ScenarioData:
    """Language-scoped accessor over one section of the bundled scenario document."""

    def __init__(self, language: str) -> None:
        """Create the accessor of one language section.

        Args:
            language: one of :data:`SUPPORTED_LANGUAGES`.

        Raises:
            ValueError: when the language has no section in the scenario file.
        """
        document = _scenario_document()
        if language not in document:
            raise ValueError(f"Scenario resource has no section for language {language!r}.")
        self._language = language
        self._section: dict[str, Any] = document[language]
        self._document = document

    @property
    def language(self) -> str:
        """The language this accessor is scoped to."""
        return self._language

    @property
    def scenario_name(self) -> str:
        """The human-readable scenario name."""
        return str(self._document.get("scenario", ""))

    def task_schema(self) -> dict[str, Any]:
        """Parameter schema passed to ``validate_task_prompt_and_data_filling``."""
        schema = self._section["task_schema"]
        return dict(schema)

    def missing_params(self) -> dict[str, Any]:
        """Scenario data with a missing required param, triggering the server-side negotiation."""
        return dict(self._section["missing_params"])

    def filled_params(self) -> dict[str, Any]:
        """Scenario data with all params filled, completing the negotiation."""
        return dict(self._section["filled_params"])

    def negotiation_phrasing(self) -> dict[str, str]:
        """Negotiation phrasing templates: ``missing_item_hint``, ``propose_relationship``, ..."""
        return dict(self._section["negotiation_phrasing"])

    def diagnosis_templates(self) -> dict[str, str]:
        """Diagnosis result templates: ``result_line``, ``detail_line``, ``advice_line``."""
        return dict(self._section["diagnosis"])
