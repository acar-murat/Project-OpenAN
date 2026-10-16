"""OSS audit service (LLD v10.4 §11.3, requirements R-AUD-1 … R-AUD-10).

Wraps the hash-chained store from ``mocks.common.audit`` with the OSS rules:

* only the thirteen §11.3 event types are accepted;
* ``workflow_started`` fails closed: if it cannot be written, ``AuditWriteError``
  is raised and the caller must not submit (R-AUD-8);
* every other event that cannot be written is spooled as a file in
  ``OSS_AUDIT_SPOOL_DIR`` and replayed in order by ``flush_spool``; a spool entry
  older than ``OSS_AUDIT_SPOOL_ALERT_SECONDS`` is reported by ``stuck_spool``;
* terminal events are written once per ``intent_id`` and watcher events once per
  ``(execution_id, type, timestamp)`` (R-AUD-2, R-AUD-3);
* ``raw_text`` is replaced by its SHA-256 unless ``OSS_AUDIT_STORE_RAW_TEXT=true``
  (R-AUD-9, open item O-5);
* reads need ``energy_saving:admin`` and are themselves audited as ``audit_read``
  (R-AUD-4);
* ``to_upstream`` maps a record onto the six-element format the Registry and
  Orchestration Center write, so one parser handles every log (R-AUD-10).

Retention (``OSS_AUDIT_RETENTION_DAYS``) is read but not applied: the period and
archive target are still open (O-24), and pruning a hash chain needs a signed
checkpoint that has not been designed yet.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
import uuid
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any, Protocol

from mocks.common.audit import AuditLog
from oss.security import Principal

log = logging.getLogger("oss.audit")

EVENTS = (
    "auth_failure", "permission_denied", "intent_received", "intent_not_energy_saving",
    "parameter_supplement", "workflow_started", "negotiation_summary", "workflow_completed",
    "workflow_failed", "workflow_rejected", "workflow_stream_lost", "execution_linked", "audit_read",
)
TERMINAL_EVENTS = frozenset({"workflow_completed", "workflow_failed", "workflow_rejected", "workflow_stream_lost"})
FAIL_CLOSED_EVENTS = frozenset({"workflow_started"})

#: Upstream ``level`` per event: denials and network-changing steps are Critical.
_CRITICAL = frozenset({"auth_failure", "permission_denied", "workflow_started", "audit_read"})
_UPSTREAM_OBJECT = {"audit_read": "Audit Log", "execution_linked": "Execution"}


class AuditWriteError(RuntimeError):
    """A fail-closed event could not be written; the action it guards must not run."""


class AuditStore(Protocol):
    path: Path

    def append(self, event: str, **fields: Any) -> dict[str, Any]: ...


def iter_records(path: Path) -> Iterator[dict[str, Any]]:
    if not path.exists():
        return
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


class AuditService:
    def __init__(self, store: AuditStore, spool_dir: str | Path, *, store_raw_text: bool = False,
                 spool_alert_seconds: float = 300, retention_days: int | None = None) -> None:
        self._store = store
        self._spool = Path(spool_dir)
        self._spool.mkdir(parents=True, exist_ok=True)
        self._store_raw_text = store_raw_text
        self._spool_alert_seconds = spool_alert_seconds
        self.retention_days = retention_days
        self._lock = threading.Lock()
        self._terminal: set[str] = set()
        self._seen_watcher_keys: set[str] = set()
        for record in iter_records(store.path):
            self._remember(record)
        for entry in self._spool_entries():
            self._remember(json.loads(entry.read_text(encoding="utf-8")))

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> AuditService:
        env = os.environ if env is None else env
        log_path = env.get("OSS_AUDIT_LOG_PATH", ".dev/oss/audit.log")
        retention = env.get("OSS_AUDIT_RETENTION_DAYS")
        return cls(
            AuditLog.shared(log_path),
            env.get("OSS_AUDIT_SPOOL_DIR") or str(Path(log_path).parent / "spool"),
            store_raw_text=env.get("OSS_AUDIT_STORE_RAW_TEXT", "false").lower() == "true",
            spool_alert_seconds=float(env.get("OSS_AUDIT_SPOOL_ALERT_SECONDS") or 300),
            retention_days=int(retention) if retention else None,
        )

    # Writing ---------------------------------------------------------------------

    def record(self, event: str, *, outcome: str = "success", intent_id: str | None = None,
               trace_id: str | None = None, actor: dict[str, Any] | None = None,
               resource: dict[str, Any] | None = None, reason: str | None = None,
               detail: dict[str, Any] | None = None, watcher_key: tuple[Any, ...] | None = None,
               ) -> dict[str, Any] | None:
        """Write one event. Returns the record, or ``None`` when it was a duplicate or was spooled."""
        if event not in EVENTS:
            raise ValueError(f"unknown audit event {event!r}")
        fields = {"outcome": outcome, "intent_id": intent_id, "trace_id": trace_id, "actor": actor,
                  "resource": resource, "reason": reason, "detail": self._scrub(detail or {})}
        key = json.dumps([str(part) for part in watcher_key]) if watcher_key else None
        with self._lock:
            if event in TERMINAL_EVENTS and intent_id in self._terminal:
                log.info("ignoring a second terminal event %s for intent %s", event, intent_id)
                return None
            if key is not None and key in self._seen_watcher_keys:
                return None
            if key is not None:
                fields["detail"] = {**fields["detail"], "watcher_key": key}
            self._remember({"event": event, "intent_id": intent_id, "detail": fields["detail"]})
        try:
            return self._store.append(event, **fields)
        except Exception as exc:
            if event in FAIL_CLOSED_EVENTS:
                with self._lock:
                    self._forget(event, intent_id, key)
                raise AuditWriteError(f"could not write {event}: {exc}") from exc
            self._spool_write(event, fields)
            log.warning("audit store unavailable; spooled %s (%s)", event, exc)
            return None

    def _scrub(self, detail: dict[str, Any]) -> dict[str, Any]:
        if "raw_text" in detail and not self._store_raw_text:
            text = detail.pop("raw_text") or ""
            detail = {**detail, "raw_text_sha256": hashlib.sha256(str(text).encode()).hexdigest()}
        return detail

    def _remember(self, record: Mapping[str, Any]) -> None:
        if record.get("event") in TERMINAL_EVENTS and record.get("intent_id"):
            self._terminal.add(record["intent_id"])
        key = (record.get("detail") or {}).get("watcher_key")
        if key:
            self._seen_watcher_keys.add(key)

    def _forget(self, event: str, intent_id: str | None, key: str | None) -> None:
        if event in TERMINAL_EVENTS:
            self._terminal.discard(intent_id)
        if key is not None:
            self._seen_watcher_keys.discard(key)

    # Spool -----------------------------------------------------------------------

    def _spool_entries(self) -> list[Path]:
        return sorted(self._spool.glob("*.json"))

    def _spool_write(self, event: str, fields: dict[str, Any]) -> None:
        entry = {"event": event, "spooled_at": time.time(), **fields}
        name = f"{time.time_ns():020d}-{uuid.uuid4().hex[:8]}.json"
        tmp = self._spool / f".{name}.tmp"
        with tmp.open("w", encoding="utf-8") as handle:
            json.dump(entry, handle, ensure_ascii=False, default=str)
            handle.flush()
            os.fsync(handle.fileno())
        tmp.replace(self._spool / name)

    def flush_spool(self) -> int:
        """Replay spooled events in order; stop at the first failure. Returns how many were written."""
        written = 0
        for path in self._spool_entries():
            entry = json.loads(path.read_text(encoding="utf-8"))
            event = entry.pop("event")
            spooled_at = entry.pop("spooled_at")
            entry["detail"] = {**(entry.get("detail") or {}), "spooled_at": spooled_at}
            try:
                self._store.append(event, **entry)
            except Exception as exc:
                log.warning("audit spool replay stopped at %s: %s", path.name, exc)
                break
            path.unlink()
            written += 1
        return written

    def stuck_spool(self, now: float | None = None) -> bool:
        """True when the oldest spooled event is older than the alert threshold (raise an alert)."""
        entries = self._spool_entries()
        if not entries:
            return False
        oldest = json.loads(entries[0].read_text(encoding="utf-8"))["spooled_at"]
        stuck = (now or time.time()) - oldest > self._spool_alert_seconds
        if stuck:
            log.error("audit spool stuck: %d event(s), oldest %.0f s old", len(entries), (now or time.time()) - oldest)
        return stuck

    # Reading ---------------------------------------------------------------------

    def read(self, principal: Principal, *, source_ip: str | None = None, intent_id: str | None = None,
             event: str | None = None, limit: int = 100, export: str | None = None) -> list[dict[str, Any]]:
        """Records for an admin, newest last; raises ``PermissionError`` for anyone else.

        The read is audited before any data is returned, and fails closed like ``workflow_started``.
        """
        if not principal.is_admin:
            raise PermissionError("energy_saving:admin is required to read audit logs")
        query = {"intent_id": intent_id, "event": event, "limit": limit, "export": export}
        try:
            self._store.append("audit_read", outcome="success", actor=principal.as_actor(source_ip),
                               detail={key: value for key, value in query.items() if value is not None})
        except Exception as exc:
            raise AuditWriteError(f"could not write audit_read: {exc}") from exc
        records = [r for r in iter_records(self._store.path)
                   if (intent_id is None or r.get("intent_id") == intent_id)
                   and (event is None or r.get("event") == event)]
        return records[-limit:] if limit > 0 else records


def to_upstream(record: Mapping[str, Any]) -> dict[str, Any]:
    """The upstream six-element shape (time, client IP, user name, operation name, target, result)
    plus ``level`` and ``details``, as the Registry Center and ``common/log/audit_logger.py`` write it."""
    actor = record.get("actor") or {}
    resource = {k: v for k, v in (record.get("resource") or {}).items() if v is not None}
    event = record["event"]
    return {
        "time": str(record["ts"]).split(".")[0].rstrip("Z") + "Z",
        "clientIP": actor.get("source_ip") or "",
        "userName": actor.get("user_id") or "",
        "level": "Critical" if event in _CRITICAL else "General",
        "operationName": event.replace("_", " ").title(),
        "object": _UPSTREAM_OBJECT.get(event, "Energy Saving Intent"),
        "result": "Success" if record.get("outcome") == "success" else "Failure",
        "details": {
            "auditId": record.get("audit_id"),
            "intentId": record.get("intent_id"),
            "traceId": record.get("trace_id"),
            **resource,
            **({"outcome": record["outcome"]} if record.get("outcome") == "denied" else {}),
            **({"message": record["reason"]} if record.get("reason") else {}),
            "hash": record.get("hash"),
        },
    }
