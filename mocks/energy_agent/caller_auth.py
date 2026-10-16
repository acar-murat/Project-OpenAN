"""Energy Agent caller authentication (LLD v10.4 §11.11, R-EAS-1, backlog EA-14).

An ASGI middleware in front of the agent's A2A routes: a request is served only
when it carries an identity listed in ``ENERGY_AGENT_ALLOWED_CALLERS``. The list
is comma-separated; each entry is one of

* ``bearer:env:NAME`` / ``bearer:file:/path``: an ``Authorization: Bearer`` token
  whose value is read from that variable or file (the secret never sits in the list);
* ``ip:CIDR``: a source address range, for deployments where the network policy
  (R-SEC-8) already pins ORCH's address.

Mutual TLS is the transport-level option: set ``MOCK_ENERGY_AGENT_TLS_CERT``,
``MOCK_ENERGY_AGENT_TLS_KEY`` and ``MOCK_ENERGY_AGENT_TLS_CLIENT_CA`` and the
server refuses any TLS client without a certificate from that CA (see
``mocks/energy_agent/__main__.py``). Which of these the production A2A-T SDK
server supports is still open item O-25.

An empty list turns the check off (development); the agent then logs a warning
at startup and audit records name the caller as unauthenticated. The agent card
paths stay public so the Registry and ORCH can read the card.

Refused requests get ``401`` and a ``caller_rejected`` record in the agent's
audit log. Accepted requests set ``current_caller()`` for the ControlPoint, which
writes the verified caller into every policy and negotiation record.
"""

from __future__ import annotations

import contextvars
import hmac
import ipaddress
import json
import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mocks.common import audit

log = logging.getLogger("mock-energy-agent.caller-auth")

PUBLIC_PATHS = frozenset({"/.well-known/agent-card.json", "/.well-known/agent.json"})
UNAUTHENTICATED = "unauthenticated (ENERGY_AGENT_ALLOWED_CALLERS is empty)"

_current_caller: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar("caller", default=None)


def current_caller() -> dict[str, Any]:
    """The caller of the request being served, as an audit ``actor``."""
    return _current_caller.get() or {"user_id": None, "source_ip": None, "roles": [], "caller": "unknown"}


def _secret(ref: str, env: Mapping[str, str]) -> str:
    kind, _, target = ref.partition(":")
    if kind == "env" and target:
        value = env.get(target, "")
    elif kind == "file" and target:
        value = Path(target).read_text(encoding="utf-8").strip()
    else:
        raise ValueError(f"bearer entries need env:NAME or file:/path, not {ref!r}")
    if len(value.encode()) < 32:
        # Same floor ORCH applies to its own static bearer tokens.
        raise ValueError(f"the bearer token from {ref} must be at least 32 bytes")
    return value


@dataclass(frozen=True)
class AllowedCallers:
    tokens: tuple[tuple[str, str], ...] = ()  # (label, token)
    networks: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = ()

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> AllowedCallers:
        env = os.environ if env is None else env
        tokens, networks = [], []
        for entry in (env.get("ENERGY_AGENT_ALLOWED_CALLERS") or "").split(","):
            entry = entry.strip()
            if not entry:
                continue
            kind, _, value = entry.partition(":")
            if kind == "bearer":
                tokens.append((f"bearer:{value}", _secret(value, env)))
            elif kind == "ip":
                networks.append(ipaddress.ip_network(value, strict=False))
            else:
                raise ValueError(f"unknown ENERGY_AGENT_ALLOWED_CALLERS entry {entry!r}")
        return cls(tuple(tokens), tuple(networks))

    @property
    def enabled(self) -> bool:
        return bool(self.tokens or self.networks)

    def identify(self, authorization: str | None, source_ip: str | None) -> str | None:
        """The label of the matching entry, or ``None`` when the caller is not allowed."""
        scheme, _, token = (authorization or "").partition(" ")
        if scheme.lower() == "bearer" and token:
            for label, expected in self.tokens:
                if hmac.compare_digest(token.strip().encode(), expected.encode()):
                    return label
        if source_ip and self.networks:
            try:
                address = ipaddress.ip_address(source_ip)
            except ValueError:
                return None
            for network in self.networks:
                if address in network:
                    return f"ip:{network}"
        return None


class CallerAuthMiddleware:
    def __init__(self, app, allowed: AllowedCallers, audit_log: audit.AuditLog | None = None) -> None:
        self.app = app
        self.allowed = allowed
        self.audit_log = audit_log
        if not allowed.enabled:
            log.warning("ENERGY_AGENT_ALLOWED_CALLERS is empty: every caller is accepted (development only)")

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        source_ip = (scope.get("client") or (None,))[0]
        actor = {"user_id": None, "source_ip": source_ip, "roles": []}
        if not self.allowed.enabled:
            label = UNAUTHENTICATED
        elif scope["method"] == "GET" and scope["path"] in PUBLIC_PATHS:
            await self.app(scope, receive, send)
            return
        else:
            headers = {key.decode().lower(): value.decode() for key, value in scope.get("headers", [])}
            label = self.allowed.identify(headers.get("authorization"), source_ip)
        if label is None:
            if self.audit_log is not None:
                self.audit_log.append("caller_rejected", outcome="denied", actor=actor,
                                      reason="caller_not_allowed",
                                      detail={"method": scope["method"], "path": scope["path"]})
            body = json.dumps({"error": "unauthenticated", "message": "caller is not allowed"}).encode()
            await send({"type": "http.response.start", "status": 401,
                        "headers": [(b"content-type", b"application/json"), (b"www-authenticate", b"Bearer")]})
            await send({"type": "http.response.body", "body": body})
            return
        token = _current_caller.set({**actor, "caller": label})
        try:
            await self.app(scope, receive, send)
        finally:
            _current_caller.reset(token)
