# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
# SPDX-License-Identifier: Apache-2.0
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""
Integration audit identity tests (task 4.1).

Verifies audit records carry the authenticated caller identity on both the
main port (certificate CN) and the integration port (appcode).
"""

import pytest

from agent_registry import server as server_module
from agent_registry.integration import audit as audit_module
from agent_registry.integration.audit import audit_integration
from common.log.audit_logger import OperationName
from common.util.authenticate_util import CallerRole, CallerType, Principal


class _Recorder:
    def __init__(self):
        self.entries = []

    async def handle(self, entry):
        self.entries.append(entry)


@pytest.fixture
def recorder(monkeypatch):
    rec = _Recorder()
    monkeypatch.setattr(server_module, "audit_handle", rec)
    monkeypatch.setattr(audit_module, "_audit_handle", rec)
    return rec


def _integration_principal(identity="svc_app"):
    return Principal(client_ip="10.1.1.9", identity=identity,
                     caller_type=CallerType.INTEGRATION,
                     role=CallerRole.NMS_OSS, owner=identity)


@pytest.mark.asyncio
async def test_main_port_audit_carries_caller_identity(recorder):
    await server_module._audit_result(OperationName.REGISTER_AGENT, True,
                                      {"agentName": "a"}, "1.2.3.4", caller="cert_cn")
    entry = recorder.entries[0]
    assert entry["user_name"] == "cert_cn"
    assert entry["client_ip"] == "1.2.3.4"
    assert entry["result"].value if hasattr(entry["result"], "value") else entry["result"]


@pytest.mark.asyncio
async def test_main_port_audit_without_caller_keeps_empty(recorder):
    """Backward compatibility: no identity available -> userName stays empty."""
    await server_module._audit_result(OperationName.REGISTER_AGENT, True,
                                      {"agentName": "a"}, "1.2.3.4")
    assert recorder.entries[0]["user_name"] == ""


@pytest.mark.asyncio
async def test_main_port_audit_failure_carries_caller(recorder):
    await server_module._audit_failure(OperationName.REGISTER_AGENT,
                                       {"agentName": "a"}, "1.2.3.4", caller="cn_x")
    assert recorder.entries[0]["user_name"] == "cn_x"


@pytest.mark.asyncio
async def test_integration_audit_carries_appcode(recorder):
    principal = _integration_principal("nms_gateway")
    await audit_integration(OperationName.REGISTER_AGENT, principal, True,
                            {"agentName": "a"})
    entry = recorder.entries[0]
    assert entry["user_name"] == "nms_gateway"
    assert entry["client_ip"] == "10.1.1.9"


@pytest.mark.asyncio
async def test_integration_failure_audit_carries_claimed_appcode(recorder):
    """Failed integration requests still record who tried (anti-probing-safe)."""
    probe = Principal(client_ip="10.1.1.9", identity="ghost_app")
    await audit_integration(OperationName.REGISTER_AGENT, probe, False,
                            {"message": "authentication failed"})
    entry = recorder.entries[0]
    assert entry["user_name"] == "ghost_app"
    assert "authentication failed" in entry["details"]["message"]


# ---------- task 4.2: main-port read audit switch ----------

@pytest.mark.asyncio
async def test_main_port_read_audit_disabled_by_default(recorder, monkeypatch):
    monkeypatch.setattr(server_module, "config", {"audit.read_operations": "false"})
    await server_module._maybe_audit_read(OperationName.QUERY_AGENT,
                                          {"name": "a"}, "1.2.3.4", caller="cn")
    assert recorder.entries == []


@pytest.mark.asyncio
async def test_main_port_read_audit_enabled(recorder, monkeypatch):
    monkeypatch.setattr(server_module, "config", {"audit.read_operations": "true"})
    await server_module._maybe_audit_read(OperationName.QUERY_AGENT,
                                          {"name": "a"}, "1.2.3.4", caller="cn")
    assert len(recorder.entries) == 1
    assert recorder.entries[0]["user_name"] == "cn"
    assert recorder.entries[0]["operation_name"] == OperationName.QUERY_AGENT


# ---------- task 4.3: audit pull API reader ----------

def test_read_audit_records_filters_and_paginates(tmp_path):
    import json as _json
    from agent_registry.integration.audit_query import read_audit_records
    log_file = tmp_path / "audit.log"
    entries = [
        {"time": "2026-09-20T01:00:00", "user_name": "app_a",
         "operation_name": "Register Agent", "details": {"n": 1}},
        {"time": "2026-09-20T02:00:00", "user_name": "app_b",
         "operation_name": "Query Agent", "details": {"n": 2}},
        {"time": "2026-09-20T03:00:00", "user_name": "app_a",
         "operation_name": "Query Agent", "details": {"n": 3}},
    ]
    log_file.write_text("\n".join(_json.dumps(e) for e in entries) + "\n", encoding="utf-8")

    result = read_audit_records(str(log_file), backup_count=1)
    assert result["total"] == 3
    # newest first
    assert result["records"][0]["details"]["n"] == 3

    by_identity = read_audit_records(str(log_file), identity="app_a")
    assert by_identity["total"] == 2

    by_op = read_audit_records(str(log_file), operation="Query Agent")
    assert by_op["total"] == 2

    by_window = read_audit_records(str(log_file), start_time="2026-09-20T02:00:00")
    assert by_window["total"] == 2

    paged = read_audit_records(str(log_file), limit=1, offset=1)
    assert paged["total"] == 3
    assert paged["records"][0]["details"]["n"] == 2


# ---------- task 5.1: ban tracker ----------

class TestBanTracker:
    def test_bans_after_threshold(self):
        from agent_registry.integration.ban import BanTracker
        tracker = BanTracker(threshold=3, cooldown_seconds=60)
        assert tracker.record_failure("app") is False
        assert tracker.record_failure("app") is False
        assert tracker.record_failure("app") is True  # just banned
        assert tracker.is_banned("app") is True
        assert tracker.remaining_seconds("app") > 0

    def test_cooldown_lifts_ban(self):
        from agent_registry.integration.ban import BanTracker
        now = [1000.0]
        tracker = BanTracker(threshold=1, cooldown_seconds=30, clock=lambda: now[0])
        assert tracker.record_failure("app") is True
        assert tracker.is_banned("app") is True
        now[0] += 31
        assert tracker.is_banned("app") is False

    def test_success_clears_counter(self):
        from agent_registry.integration.ban import BanTracker
        tracker = BanTracker(threshold=2, cooldown_seconds=60)
        tracker.record_failure("app")
        tracker.record_success("app")
        assert tracker.record_failure("app") is False  # counter was reset

    def test_empty_key_ignored(self):
        from agent_registry.integration.ban import BanTracker
        tracker = BanTracker(threshold=1)
        assert tracker.record_failure("") is False
        assert tracker.is_banned("") is False
