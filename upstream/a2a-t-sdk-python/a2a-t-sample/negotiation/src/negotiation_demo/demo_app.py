"""Entry point of the offline negotiation closed-loop demo (Java ``NegotiationDemoApp``).

Boots the in-process server runtime (carrying the ``A2ATServer`` facade) and the client runtime
(carrying the ``A2ATClient`` facade), then drives the 4-message flow:

1. client -> Task-T prompt (params missing);
2. server -> Negotiation-T information propose (missing params detected) -> ``INPUT_REQUIRED``;
3. client -> Task-T prompt (params filled) + Negotiation-T accept;
4. server -> diagnosis result -> ``COMPLETED``.

Unlike the Java demo (which requires a real LLM API key and an embedded HTTP server), this sample
runs fully offline: without ``A2AT_LLM_API_KEY`` the scripted mock LLM of
:mod:`negotiation_demo.shared.mock_llm` serves the slot-extraction, content-validation and
negotiation-extraction calls, and the transport is an in-process runtime call.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

from a2a_t.client.a2at_client import A2ATClient
from a2a_t.server.a2at_server import A2ATServer

from .client_runtime import NegotiationClient
from .server_runtime import NegotiationServerRuntime
from .shared.mock_llm import install_mock_llm_if_needed
from .shared.scenario_data import SUPPORTED_LANGUAGES, ScenarioData, resolve_language
from .shared.strategies import FromDataStrategy, FromTextStrategy


def run_demo(
    *,
    use_from_text: bool = False,
    env_path: Path | None = None,
    language: str | None = None,
    log_sink: Callable[[str], None] | None = None,
) -> dict[str, object]:
    """Run the 4-message negotiation flow with an explicit strategy choice.

    Args:
        use_from_text: ``True`` generates the negotiation messages from natural language (one LLM
            content-extraction step each); ``False`` builds the typed records and calls the
            deterministic from-data API (zero LLM calls for the negotiation messages).
        env_path: optional ``.env`` file path; ``None`` reads ``./.env`` when it exists.
        language: optional demo language override (``en-US`` or ``zh-CN``); ``None`` resolves the
            language from the ``.env`` file, defaulting to ``en-US``.
        log_sink: optional sink receiving the flow logs.

    Returns:
        the scenario summary (scenario, message count, outcome, negotiation request, diagnosis).
    """
    resolved_env_path = env_path or Path.cwd() / ".env"
    emit = log_sink or (lambda _message: None)
    resolved_language = language or resolve_language(env_path=resolved_env_path)
    install_mock_llm_if_needed(
        env_path=resolved_env_path,
        language=resolved_language,
        force_language=language is not None,
    )

    scenario = ScenarioData(resolved_language)
    strategy = FromTextStrategy(scenario) if use_from_text else FromDataStrategy(scenario)
    emit(f"[negotiation] strategy: {'fromText (LLM)' if use_from_text else 'fromData (rule-based)'}")
    emit(f"[negotiation] language: {resolved_language}")

    client_facade = A2ATClient(env_path=resolved_env_path)
    server_facade = A2ATServer(env_path=resolved_env_path)
    server_runtime = NegotiationServerRuntime(server_facade, strategy, scenario, log_sink=emit)
    client = NegotiationClient(client_facade, strategy, scenario, log_sink=emit)

    summary = client.run_four_message_flow(server_runtime)
    emit("[negotiation] === Summary ===")
    emit(f"[negotiation] {summary}")
    return summary


def main(argv: list[str] | None = None) -> dict[str, object]:
    """Entry point: parse the ``--fromText`` / ``--language`` flags and run the demo."""
    arguments = list(sys.argv[1:]) if argv is None else list(argv)
    use_from_text = "--fromText" in arguments
    language: str | None = None
    if "--language" in arguments:
        index = arguments.index("--language")
        if index + 1 >= len(arguments):
            raise SystemExit("usage: python -m negotiation_demo [--fromText] [--language en-US|zh-CN]")
        language = arguments[index + 1]
        if language not in SUPPORTED_LANGUAGES:
            raise SystemExit(f"unsupported language {language!r}; expected one of {SUPPORTED_LANGUAGES}")

    return run_demo(
        use_from_text=use_from_text,
        env_path=Path.cwd() / ".env",
        language=language,
        log_sink=print,
    )


if __name__ == "__main__":
    main()
