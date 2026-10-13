"""Register a mock agent's AgentCard in the Registry Center."""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import httpx

log = logging.getLogger("mock-registry")


def register(registry_url: str, card: dict[str, Any]) -> bool:
    """``POST /rest/v1/registry-center/agent-cards``; True when registered or already there."""
    headers = {}
    token = os.environ.get("REGISTRY_ACCESS_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    url = registry_url.rstrip("/") + "/rest/v1/registry-center/agent-cards"
    try:
        response = httpx.post(url, json={"agentCards": [card]}, headers=headers, timeout=10, trust_env=False)
    except httpx.HTTPError as exc:
        log.warning("registry registration failed: %s", exc)
        return False
    if response.status_code in (200, 201):
        log.info("registered %s with %s", card["name"], registry_url)
        return True
    if response.status_code == 409:
        log.info("%s already registered with %s", card["name"], registry_url)
        return True
    log.warning("registry registration failed: HTTP %s %s", response.status_code, response.text[:300])
    return False


def register_with_retry(registry_url: str, card: dict[str, Any], timeout: float) -> None:
    """Keep trying until the Registry Center accepts the card (it may start after the agent)."""
    deadline = time.monotonic() + timeout
    while not register(registry_url, card) and time.monotonic() < deadline:
        time.sleep(2)


def find_card(registry_url: str, organization: str, name: str) -> dict[str, Any] | None:
    """Return a registered AgentCard, or None if the registry does not list it."""
    url = f"{registry_url.rstrip('/')}/rest/v1/registry-center/agent-cards/{organization}/{name}"
    try:
        response = httpx.get(url, timeout=10, trust_env=False)
    except httpx.HTTPError:
        return None
    cards = response.json().get("agentCards", []) if response.status_code == 200 else []
    return cards[0] if cards else None
