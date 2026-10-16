"""OSS audit rules: event set, write-failure policy, idempotency and the upstream export."""

import json

import pytest

from mocks.common.audit import AuditLog, verify
from oss.audit import EVENTS, AuditService, AuditWriteError, to_upstream
from oss.security import Principal
from oss.tests.conftest import records


class FlakyStore:
    """An AuditLog whose writes fail while ``down`` is set."""

    def __init__(self, path):
        self._log = AuditLog(path)
        self.path = self._log.path
        self.down = False

    def append(self, event, **fields):
        if self.down:
            raise OSError("database unavailable")
        return self._log.append(event, **fields)


def test_the_thirteen_events_and_nothing_else(audit_service):
    assert len(EVENTS) == 13
    with pytest.raises(ValueError):
        audit_service.record("something_else")


def test_terminal_event_is_written_once_per_intent(audit_service):
    assert audit_service.record("workflow_completed", intent_id="i-1") is not None
    assert audit_service.record("workflow_failed", intent_id="i-1") is None
    assert audit_service.record("workflow_completed", intent_id="i-2") is not None
    assert [r["intent_id"] for r in records(audit_service)] == ["i-1", "i-2"]


def test_terminal_once_survives_a_restart(tmp_path):
    first = AuditService(AuditLog(tmp_path / "a.log"), tmp_path / "spool")
    first.record("workflow_rejected", intent_id="i-1")
    again = AuditService(AuditLog(tmp_path / "a.log"), tmp_path / "spool")
    assert again.record("workflow_completed", intent_id="i-1") is None


def test_watcher_events_are_idempotent(audit_service):
    key = ("exec-1", "negotiation_round", "2026-10-16T08:00:00Z")
    assert audit_service.record("negotiation_summary", intent_id="i-1", watcher_key=key) is not None
    assert audit_service.record("negotiation_summary", intent_id="i-1", watcher_key=key) is None


def test_workflow_started_fails_closed(tmp_path):
    store = FlakyStore(tmp_path / "a.log")
    service = AuditService(store, tmp_path / "spool")
    store.down = True
    with pytest.raises(AuditWriteError):
        service.record("workflow_started", intent_id="i-1")
    assert not list((tmp_path / "spool").glob("*.json"))


def test_other_events_are_spooled_replayed_in_order_and_alerted(tmp_path):
    store = FlakyStore(tmp_path / "a.log")
    service = AuditService(store, tmp_path / "spool", spool_alert_seconds=60)
    store.down = True
    assert service.record("negotiation_summary", intent_id="i-1") is None
    assert service.record("workflow_completed", intent_id="i-1") is None
    # A spooled terminal event still counts as written.
    assert service.record("workflow_failed", intent_id="i-1") is None
    assert len(list((tmp_path / "spool").glob("*.json"))) == 2
    assert not service.stuck_spool()
    oldest = json.loads(sorted((tmp_path / "spool").glob("*.json"))[0].read_text())["spooled_at"]
    assert service.stuck_spool(now=oldest + 61)
    assert service.flush_spool() == 0  # still down: nothing replayed, nothing lost
    store.down = False
    assert service.flush_spool() == 2
    assert [r["event"] for r in records(service)] == ["negotiation_summary", "workflow_completed"]
    assert all("spooled_at" in r["detail"] for r in records(service))
    assert verify(store.path) == []


def test_secrets_and_raw_text_never_reach_the_log(audit_service):
    audit_service.record("intent_received", intent_id="i-1",
                         detail={"raw_text": "please save energy", "api_key": "sk-123", "nested": {"token": "t"}})
    line = audit_service._store.path.read_text()
    assert "please save energy" not in line and "sk-123" not in line and '"t"' not in line


def test_raw_text_kept_when_compliance_allows(tmp_path):
    service = AuditService(AuditLog(tmp_path / "a.log"), tmp_path / "spool", store_raw_text=True)
    service.record("intent_received", detail={"raw_text": "please save energy"})
    assert records(service)[0]["detail"]["raw_text"] == "please save energy"


def test_read_requires_admin_and_is_audited(audit_service):
    audit_service.record("intent_received", intent_id="i-1")
    with pytest.raises(PermissionError):
        audit_service.read(Principal("alice", ("operator",)))
    result = audit_service.read(Principal("root", ("admin",)), source_ip="10.0.0.9", intent_id="i-1")
    assert [r["event"] for r in result] == ["intent_received"]
    last = records(audit_service)[-1]
    assert last["event"] == "audit_read" and last["actor"]["user_id"] == "root"
    assert last["detail"]["intent_id"] == "i-1"


# A Registry Center audit line from its Security Guide (the upstream format).
UPSTREAM_LINE = ('{"time": "2026-05-06T06:39:05Z", "clientIP": "127.0.0.1", "userName": "", "level": "General", '
                 '"operationName": "Register Agent", "object": "Agent", "result": "Success", '
                 '"details": {"agentName": "RAN Energy Saving Agent"}}')


def test_upstream_export_matches_the_registry_format(audit_service):
    record = audit_service.record("permission_denied", outcome="denied", intent_id="i-1", reason="region_not_permitted",
                                  actor={"user_id": "bob", "source_ip": "10.1.2.3", "roles": ["operator"]},
                                  resource={"region": "Accra Central"})
    exported = to_upstream(record)
    upstream = json.loads(UPSTREAM_LINE)
    assert set(exported) == set(upstream)
    assert exported["time"].endswith("Z") and len(exported["time"]) == len(upstream["time"])
    assert exported == {
        "time": exported["time"], "clientIP": "10.1.2.3", "userName": "bob", "level": "Critical",
        "operationName": "Permission Denied", "object": "Energy Saving Intent", "result": "Failure",
        "details": {"auditId": record["audit_id"], "intentId": "i-1", "traceId": None, "region": "Accra Central",
                    "outcome": "denied", "message": "region_not_permitted", "hash": record["hash"]},
    }
