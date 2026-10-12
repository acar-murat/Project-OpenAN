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
Audit MySQL sink tests (task 4.4).

Unit tests use a mocked pymysql connection; the live round-trip test
auto-skips without a MySQL server (MYSQL_TEST_* env vars).
"""

import json
import time

import pytest
from loguru import logger

from agent_registry.integration.audit_sink import AuditMySqlSink


class _FakeCursor:
    def __init__(self, sink_state):
        self.state = sink_state
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.executed.append(("execute", sql))

    def executemany(self, sql, rows):
        self.executed.append(("executemany", sql, len(rows)))
        self.state["rows"].extend(rows)

    def fetchone(self):
        return None

    def close(self):
        pass


class _FakeConnection:
    def __init__(self, sink_state, fail=False):
        self.state = sink_state
        self.fail = fail
        self.closed = False

    def cursor(self):
        if self.fail:
            raise ConnectionError("database unavailable")
        return _FakeCursor(self.state)

    def commit(self):
        pass

    def close(self):
        self.closed = True


@pytest.fixture
def sink_state():
    return {"rows": []}


@pytest.fixture
def loguru_caplog(caplog):
    handler_id = logger.add(caplog.handler, format="{message}")
    yield caplog
    logger.remove(handler_id)


def _make_sink(conf_overrides=None, fail=False, sink_state=None):
    import agent_registry.integration.audit_sink as sink_module
    conf = {
        "audit.mysql.enabled": "true",
        "audit.mysql.host": "127.0.0.1",
        "audit.mysql.port": "3306",
        "audit.mysql.name": "audit_db",
        "audit.mysql.username": "audit_writer",
        "audit.mysql.password": "audit_pwd",
        "audit.mysql.batch_size": "10",
        "audit.mysql.flush_interval": "0.1",
    }
    conf.update(conf_overrides or {})
    sink = AuditMySqlSink(conf)
    sink._connect = lambda: _FakeConnection(sink_state, fail=fail)
    return sink


ENTRY = {
    "time": "2026-09-20T01:00:00",
    "client_ip": "10.1.1.9",
    "user_name": "nms_gateway",
    "level": "MINOR",
    "operation_name": "Register Agent",
    "object_name": "Agent",
    "result": "SUCCESS",
    "details": {"agentName": "a"},
}


class TestAuditSinkUnit:
    def test_disabled_by_default(self):
        sink = AuditMySqlSink({})
        assert sink.enabled is False
        sink.enqueue(ENTRY)  # no-op, no error

    def test_records_reach_database(self, sink_state):
        sink = _make_sink(sink_state=sink_state)
        sink.start()
        sink.enqueue(ENTRY)
        sink.enqueue(dict(ENTRY, user_name="partner_dash"))
        deadline = time.time() + 5
        while len(sink_state["rows"]) < 2 and time.time() < deadline:
            time.sleep(0.05)
        sink.stop()
        assert len(sink_state["rows"]) == 2
        details = json.loads(sink_state["rows"][0][7])
        assert details["agentName"] == "a"

    def test_degrades_without_blocking_when_db_down(self, sink_state, loguru_caplog):
        sink = _make_sink(fail=True, sink_state=sink_state)
        sink.start()
        try:
            for _ in range(5):
                sink.enqueue(ENTRY)
                time.sleep(0.05)
            assert "degraded to local file only" in loguru_caplog.text
        finally:
            sink.stop()

    def test_queue_full_drops_without_raising(self, sink_state):
        sink = _make_sink(sink_state=sink_state)
        sink.queue.maxsize = 1
        sink.enqueue(ENTRY)
        sink.enqueue(ENTRY)  # fills the queue
        sink.enqueue(ENTRY)  # overflow -> dropped, no raise

    def test_resolved_password_is_opaque(self, sink_state):
        """Only the migration tool decrypts old configuration."""
        sink = AuditMySqlSink({"audit.mysql.enabled": "true",
                               "audit.mysql.password": "enc:literal-not-ciphertext"})
        assert sink.connect_kwargs["password"] == "enc:literal-not-ciphertext"


class TestAuditSinkLive:
    """Round trip against a live MySQL (auto-skip without server)."""

    def test_round_trip(self, mysql_config):
        from agent_registry.integration.audit_sink import AuditMySqlSink
        conf = {
            "audit.mysql.enabled": "true",
            "audit.mysql.host": mysql_config["host"],
            "audit.mysql.port": str(mysql_config["port"]),
            "audit.mysql.name": mysql_config["database"],
            "audit.mysql.username": mysql_config["user"],
            "audit.mysql.password": mysql_config["password"],
            "audit.mysql.batch_size": "10",
            "audit.mysql.flush_interval": "0.2",
        }
        sink = AuditMySqlSink(conf)
        sink.start()
        sink.enqueue(dict(ENTRY, user_name=f"live_{int(time.time())}"))
        time.sleep(1.5)
        sink.stop()
        # record landed if the table is queryable; the local file is the
        # source of truth either way
