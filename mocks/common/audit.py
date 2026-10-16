"""Append-only, hash-chained audit log (LLD v10.4 §11.3 and §11.11).

Each record is one JSON line with the §11.3 schema. ``hash`` is the SHA-256 of
the record's canonical JSON (keys sorted, ``hash`` left out), and ``prev_hash``
is the previous record's ``hash``, so an edited, removed or reordered line
breaks the chain. ``verify`` finds the breaks; run it as the periodic verifier:

    python -m mocks.common.audit PATH

Payloads are redacted before they are hashed or written: any key that looks
like a credential is replaced, so no secret reaches the log (§11.2).

The OSS audit store will use the same record shape in a database with an
insert-only role; this file-backed version serves the mock Energy Agent's
local log and the tests.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

GENESIS_HASH = "0" * 64
REDACTED = "[REDACTED]"
SECRET_KEY = re.compile(r"(api[_-]?key|token|secret|password|authorization|credential|cookie)", re.I)
OUTCOMES = ("success", "failure", "denied")


def redact(value: Any) -> Any:
    """A copy of ``value`` with every credential-like key's value replaced."""
    if isinstance(value, dict):
        return {key: REDACTED if SECRET_KEY.search(str(key)) else redact(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [redact(item) for item in value]
    return value


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode()


def digest(value: Any) -> str:
    """SHA-256 of the canonical JSON of ``value``; used for price tables and payloads."""
    return hashlib.sha256(canonical(value)).hexdigest()


def record_hash(record: dict[str, Any]) -> str:
    return digest({key: item for key, item in record.items() if key != "hash"})


class AuditLog:
    """Appends §11.3 records to a JSON-lines file and chains them by hash.

    Use ``AuditLog.shared(path)`` when several objects in one process write the
    same file (one ControlPoint per workflow execution), so they share one lock
    and one chain head.
    """

    _shared: dict[Path, AuditLog] = {}
    _shared_lock = threading.Lock()

    @classmethod
    def shared(cls, path: str | Path) -> AuditLog:
        key = Path(path).resolve()
        with cls._shared_lock:
            if key not in cls._shared:
                cls._shared[key] = cls(key)
            return cls._shared[key]

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._prev_hash = self._last_hash()

    def _last_hash(self) -> str:
        if not self.path.exists():
            return GENESIS_HASH
        last = None
        with self.path.open(encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    last = line
        return json.loads(last)["hash"] if last else GENESIS_HASH

    def append(self, event: str, *, outcome: str, intent_id: str | None = None, trace_id: str | None = None,
               actor: dict[str, Any] | None = None, resource: dict[str, Any] | None = None,
               reason: str | None = None, detail: dict[str, Any] | None = None) -> dict[str, Any]:
        if outcome not in OUTCOMES:
            raise ValueError(f"outcome must be one of {OUTCOMES}, not {outcome!r}")
        detail = redact(detail or {})
        with self._lock:
            record = {
                "audit_id": str(uuid.uuid4()),
                "ts": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                "event": event,
                "intent_id": intent_id,
                "trace_id": trace_id,
                "actor": {"user_id": None, "source_ip": None, "roles": [], **(actor or {})},
                "resource": {"region": None, "psop_id": None, "execution_id": None, **(resource or {})},
                "outcome": outcome,
                "reason": reason,
                "detail": detail,
                "detail_digest": digest(detail),
                "prev_hash": self._prev_hash,
            }
            record["hash"] = record_hash(record)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
                handle.flush()
            self._prev_hash = record["hash"]
        return record


def verify(path: str | Path) -> list[str]:
    """Every break in the chain at ``path``, as ``"line N: ..."``; empty when the log is intact."""
    problems = []
    prev = GENESIS_HASH
    with Path(path).open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                problems.append(f"line {number}: not JSON")
                prev = None
                continue
            if prev is not None and record.get("prev_hash") != prev:
                problems.append(f"line {number}: prev_hash does not match the previous record (gap or reorder)")
            if record.get("hash") != record_hash(record):
                problems.append(f"line {number}: hash does not match the record (edited)")
            if record.get("detail_digest") != digest(record.get("detail") or {}):
                problems.append(f"line {number}: detail_digest does not match detail (edited)")
            prev = record.get("hash")
    return problems


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: python -m mocks.common.audit PATH", file=sys.stderr)
        return 2
    problems = verify(argv[0])
    for problem in problems:
        print(problem)
    print("audit chain intact" if not problems else f"{len(problems)} problem(s) found")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
