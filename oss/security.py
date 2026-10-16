"""OSS security controls (LLD v10.4 §11.2, requirements R-SEC-1 … R-SEC-7).

OSS is the only component that knows the end user, so every user-specific
control lives here: authentication, RBAC, region scope, object ownership,
input handling, rate limits and secret handling. ``oss.app`` applies them in
the fixed processing order.

Environment:

* ``OSS_AUTH_USERS_FILE``: JSON list of users, the development stand-in for the
  deployment's SSO/OIDC. Each entry is ``{"user_id", "roles", "regions",
  "token_sha256"}``; only the SHA-256 of a bearer token is stored, never the token.
  ``regions`` may hold ``"*"`` for every region.
* ``OSS_RAW_TEXT_MAX_CHARS``: cap on ``raw_text`` (default 2000).
* ``OSS_RATE_LIMIT_SUBMIT_PER_MIN`` / ``OSS_RATE_LIMIT_SUPPLEMENT_PER_MIN``: per-user
  limits (default 10 and 20; ``0`` turns a limit off).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import math
import os
import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PERM_SUBMIT = "energy_saving:submit"
PERM_QUERY = "energy_saving:query"
PERM_ADMIN = "energy_saving:admin"

#: Role → permissions (R-SEC-1). ``admin`` also sees every intent (R-SEC-4).
ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "admin": frozenset({PERM_SUBMIT, PERM_QUERY, PERM_ADMIN}),
    "operator": frozenset({PERM_SUBMIT, PERM_QUERY}),
    "viewer": frozenset({PERM_QUERY}),
}
ALL_REGIONS = "*"

#: The classifier may return exactly these fields (LLD §11.1, R-SEC-5).
CLASSIFIER_FIELDS = {"is_energy_saving_intent": bool, "confidence": float}


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass(frozen=True)
class Principal:
    user_id: str
    roles: tuple[str, ...] = ()
    regions: frozenset[str] = field(default_factory=frozenset)

    @property
    def permissions(self) -> frozenset[str]:
        return frozenset().union(*(ROLE_PERMISSIONS.get(role, frozenset()) for role in self.roles))

    def can(self, permission: str) -> bool:
        return permission in self.permissions

    @property
    def is_admin(self) -> bool:
        return self.can(PERM_ADMIN)

    def may_target(self, region: str) -> bool:
        """Region scope (R-SEC-3): case-insensitive match against the user's allowed set."""
        return ALL_REGIONS in self.regions or region.strip().casefold() in self.regions

    def owns_or_admin(self, owner_id: str) -> bool:
        """Object ownership (R-SEC-4)."""
        return self.is_admin or hmac.compare_digest(self.user_id, owner_id)

    def as_actor(self, source_ip: str | None) -> dict[str, Any]:
        return {"user_id": self.user_id, "source_ip": source_ip, "roles": list(self.roles)}


class AuthManager:
    """Bearer-token authentication against a user table of token digests.

    Production replaces this with the deployment's SSO/OIDC or session check; the
    contract stays the same: ``authenticate`` returns a ``Principal`` or ``None``.
    """

    def __init__(self, users: Iterable[Mapping[str, Any]]) -> None:
        self._by_digest: dict[str, Principal] = {}
        for user in users:
            principal = Principal(
                user_id=str(user["user_id"]),
                roles=tuple(user.get("roles") or ()),
                regions=frozenset(str(r).strip().casefold() if r != ALL_REGIONS else r
                                  for r in user.get("regions") or ()),
            )
            self._by_digest[str(user["token_sha256"]).lower()] = principal

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> AuthManager:
        env = os.environ if env is None else env
        path = env.get("OSS_AUTH_USERS_FILE")
        return cls(json.loads(Path(path).read_text(encoding="utf-8")) if path else [])

    def authenticate(self, authorization: str | None) -> Principal | None:
        """The principal for one ``Authorization: Bearer <token>`` header value, else ``None``."""
        if not authorization:
            return None
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            return None
        wanted = token_digest(token.strip())
        for known, principal in self._by_digest.items():
            if hmac.compare_digest(known, wanted):
                return principal
        return None


class RateLimiter:
    """Sliding one-minute window per ``(user, action)`` (R-SEC-6)."""

    def __init__(self, per_minute: Mapping[str, int], clock: Callable[[], float] = time.monotonic) -> None:
        self._limits = {action: limit for action, limit in per_minute.items() if limit > 0}
        self._clock = clock
        self._hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> RateLimiter:
        env = os.environ if env is None else env
        return cls({
            "submit": int(env.get("OSS_RATE_LIMIT_SUBMIT_PER_MIN") or 10),
            "supplement": int(env.get("OSS_RATE_LIMIT_SUPPLEMENT_PER_MIN") or 20),
        })

    def check(self, user_id: str, action: str) -> int | None:
        """Record one call; return ``None`` if allowed, else the seconds to wait (``Retry-After``)."""
        limit = self._limits.get(action)
        if limit is None:
            return None
        now = self._clock()
        with self._lock:
            hits = self._hits[(user_id, action)]
            while hits and now - hits[0] >= 60:
                hits.popleft()
            if len(hits) >= limit:
                return max(1, math.ceil(60 - (now - hits[0])))
            hits.append(now)
        return None


class InputError(ValueError):
    """Input refused by R-SEC-5; ``code`` is the error returned to the caller."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def raw_text_limit(env: Mapping[str, str] | None = None) -> int:
    env = os.environ if env is None else env
    return int(env.get("OSS_RAW_TEXT_MAX_CHARS") or 2000)


def check_raw_text(raw_text: Any, max_chars: int) -> str:
    if not isinstance(raw_text, str) or not raw_text.strip():
        raise InputError("raw_text_missing", "raw_text must be a non-empty string")
    if len(raw_text) > max_chars:
        raise InputError("raw_text_too_long", f"raw_text is {len(raw_text)} characters; the limit is {max_chars}")
    return raw_text


def validate_classifier_output(output: Any) -> dict[str, Any]:
    """Accept exactly the two classifier fields with the right types; anything else is refused.

    A model that echoes extra fields (for example text injected through ``raw_text``)
    fails here instead of carrying that text further.
    """
    if not isinstance(output, dict) or set(output) != set(CLASSIFIER_FIELDS):
        raise InputError("classifier_output_invalid",
                         f"classifier output must have exactly {sorted(CLASSIFIER_FIELDS)}")
    if not isinstance(output["is_energy_saving_intent"], bool):
        raise InputError("classifier_output_invalid", "is_energy_saving_intent must be a boolean")
    confidence = output["confidence"]
    if isinstance(confidence, bool) or not isinstance(confidence, int | float) or not 0.0 <= confidence <= 1.0:
        raise InputError("classifier_output_invalid", "confidence must be a number from 0 to 1")
    return {"is_energy_saving_intent": output["is_energy_saving_intent"], "confidence": float(confidence)}


# Secrets (R-SEC-7) -------------------------------------------------------------

def resolve_secret(ref: str | None, env: Mapping[str, str] | None = None) -> str | None:
    """Resolve a secret reference: ``env:NAME`` or ``file:/path``. Plain values are refused,
    so a secret never sits in configuration itself."""
    if not ref:
        return None
    env = os.environ if env is None else env
    kind, _, target = ref.partition(":")
    if kind == "env" and target:
        return env.get(target) or None
    if kind == "file" and target:
        return Path(target).read_text(encoding="utf-8").strip() or None
    raise ValueError("a secret reference must be env:NAME or file:/path, not a value")


class SecretRedactingFilter(logging.Filter):
    """Masks every configured secret value in log records, whatever logger emitted them."""

    def __init__(self, secrets: Iterable[str | None]) -> None:
        super().__init__()
        self._secrets = sorted({s for s in secrets if s and len(s) >= 4}, key=len, reverse=True)

    def filter(self, record: logging.LogRecord) -> bool:
        if self._secrets:
            message = record.getMessage()
            for secret in self._secrets:
                message = message.replace(secret, "[REDACTED]")
            record.msg, record.args = message, None
        return True


#: Environment variables that hold a secret value directly, and ones that hold a reference to one.
SECRET_VALUE_VARS = ("OSS_INTENT_LLM_API_KEY",)
SECRET_REF_VARS = ("OSS_ORCH_BEARER_TOKEN_REF",)


def configured_secrets(env: Mapping[str, str] | None = None) -> list[str]:
    env = os.environ if env is None else env
    values = [env.get(name) for name in SECRET_VALUE_VARS]
    values += [resolve_secret(env.get(name), env) for name in SECRET_REF_VARS]
    return [value for value in values if value]


def install_secret_redaction(env: Mapping[str, str] | None = None) -> SecretRedactingFilter:
    """Attach the redacting filter to every root handler, so no configured secret reaches a log."""
    redactor = SecretRedactingFilter(configured_secrets(env))
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(level=logging.INFO)
    for handler in root.handlers:
        handler.addFilter(redactor)
    return redactor
