import json

from mocks.common import audit


def records(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_records_follow_the_lld_schema_and_chain(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = audit.AuditLog(path)
    first = log.append("policy_decision", outcome="success", trace_id="t-1", resource={"region": "Accra"})
    second = log.append("negotiation_round", outcome="success", trace_id="t-1", detail={"round": 1})

    assert first["prev_hash"] == audit.GENESIS_HASH
    assert second["prev_hash"] == first["hash"]
    assert set(first) >= {"audit_id", "ts", "event", "intent_id", "trace_id", "actor", "resource", "outcome",
                          "reason", "detail_digest", "prev_hash", "hash"}
    assert first["resource"] == {"region": "Accra", "psop_id": None, "execution_id": None}
    assert first["ts"].endswith("Z")
    assert audit.verify(path) == []


def test_a_reopened_log_continues_the_chain(tmp_path):
    path = tmp_path / "audit.jsonl"
    last = audit.AuditLog(path).append("a", outcome="success")
    assert audit.AuditLog(path).append("b", outcome="success")["prev_hash"] == last["hash"]
    assert audit.verify(path) == []


def test_verify_detects_edits_and_gaps(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = audit.AuditLog(path)
    for n in range(3):
        log.append("negotiation_round", outcome="success", detail={"round": n})
    lines = path.read_text().splitlines()

    edited = json.loads(lines[1])
    edited["outcome"] = "failure"
    path.write_text("\n".join([lines[0], json.dumps(edited), lines[2]]) + "\n")
    assert any("line 2: hash" in problem for problem in audit.verify(path))

    path.write_text("\n".join([lines[0], lines[2]]) + "\n")
    assert any("line 2: prev_hash" in problem for problem in audit.verify(path))


def test_secrets_are_redacted_before_hashing(tmp_path):
    path = tmp_path / "audit.jsonl"
    audit.AuditLog(path).append("x", outcome="success",
                                detail={"api_key": "k", "nested": {"Authorization": "Bearer t"}, "round": 1})
    [record] = records(path)
    assert record["detail"] == {"api_key": audit.REDACTED, "nested": {"Authorization": audit.REDACTED}, "round": 1}
    assert "Bearer t" not in path.read_text()


def test_main_reports_the_chain_state(tmp_path, capsys):
    path = tmp_path / "audit.jsonl"
    audit.AuditLog(path).append("x", outcome="denied", reason="policy_violation")
    assert audit.main([str(path)]) == 0
    assert "intact" in capsys.readouterr().out


def test_shared_logs_keep_one_chain_head(tmp_path):
    path = tmp_path / "audit.jsonl"
    assert audit.AuditLog.shared(path) is audit.AuditLog.shared(str(path))
    for _ in range(2):
        audit.AuditLog.shared(path).append("x", outcome="success")
    assert audit.verify(path) == []
