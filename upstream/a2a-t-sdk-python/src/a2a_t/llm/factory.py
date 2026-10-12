"""Factories for creating LLM provider clients."""

from __future__ import annotations

from typing import Any

from a2a_t.llm.errors import LLMConfigError
from a2a_t.llm.models import LLMClientConfig
from a2a_t.llm.provider import LLMClient
from a2a_t.llm.providers.openai import OpenAIClient


class LLMClientFactory:
    """Registry and factory for provider-facing LLM clients."""

    _clients: dict[str, type[LLMClient]] = {"openai": OpenAIClient}
    _client_defaults: dict[str, dict[str, Any]] = {}

    @classmethod
    def register(cls, provider: str, client_class: type[LLMClient]) -> None:
        """Register a provider client class."""
        normalized_provider = cls._normalize_provider(provider)
        if normalized_provider in cls._clients:
            raise LLMConfigError(f"LLM provider '{normalized_provider}' is already registered")
        cls._clients[normalized_provider] = client_class

    @classmethod
    def create(
        cls,
        provider: str,
        config: LLMClientConfig,
        *,
        logger: Any | None = None,
    ) -> LLMClient:
        """Create an LLM client for a registered provider."""
        normalized_provider = cls._normalize_provider(provider)
        client_class = cls._resolve(normalized_provider)
        return client_class(config, logger=logger)  # type: ignore[call-arg]

    @classmethod
    def available_providers(cls) -> list[str]:
        """List explicitly registered provider names."""
        return sorted(cls._clients.keys())

    @classmethod
    def _normalize_provider(cls, value: object) -> str:
        """Normalize and validate a provider identifier."""
        provider = str(value or "").strip()
        if not provider:
            raise LLMConfigError("LLM provider must be non-empty")
        if provider.lower() != provider or any(character.isspace() for character in provider):
            raise LLMConfigError("LLM provider must use lowercase non-whitespace characters")
        return provider

    @classmethod
    def _resolve(cls, provider: str) -> type[LLMClient]:
        """Resolve a provider client class."""
        client_class = cls._clients.get(provider)
        if client_class is not None:
            return client_class
        available = cls.available_providers()
        raise LLMConfigError(f"Unknown llm provider: {provider}. Available: {available}")
