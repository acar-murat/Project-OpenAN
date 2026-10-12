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
Audit sink to a customer-operated MySQL database (task 4.4).

Integration audit records are mirrored asynchronously to the operator's
MySQL database: a bounded in-memory queue feeds a background writer thread
that batches inserts. Design guarantees:

- The local audit file is the source of truth and is always written first;
  database unavailability degrades to local-only plus a rate-limited
  warning — business requests are never blocked by the sink.
- The database account must be a dedicated, minimal-privilege account;
  the resolved password is opaque; the connection uses TLS
  when the server supports it (ssl_disabled not set).
- Switch/batching live in persistence.conf; connection is db/audit_mysql.json.
"""

import json
import queue
import threading
import time
from typing import Dict, Optional

from loguru import logger

_DDL = """
CREATE TABLE IF NOT EXISTS integration_audit_records (
    id             BIGINT       NOT NULL AUTO_INCREMENT,
    time           VARCHAR(64)  NOT NULL,
    client_ip      VARCHAR(64)  NOT NULL,
    user_name      VARCHAR(100) NOT NULL DEFAULT '',
    level          VARCHAR(20)  NOT NULL DEFAULT '',
    operation_name VARCHAR(64)  NOT NULL DEFAULT '',
    object_name    VARCHAR(50)  NOT NULL DEFAULT '',
    result         VARCHAR(20)  NOT NULL DEFAULT '',
    details        TEXT         NULL,
    created_at     DATETIME     DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY idx_tp_audit_time (time),
    KEY idx_tp_audit_user (user_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""

_INSERT = """
INSERT INTO integration_audit_records
    (time, client_ip, user_name, level, operation_name, object_name, result, details)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
"""

_WARN_INTERVAL_SECONDS = 30


class AuditMySqlSink:
    """Asynchronous batch writer of audit records into customer MySQL."""

    def __init__(self, conf: dict):
        self.enabled = str(conf.get('audit.mysql.enabled', 'false')).lower() == 'true'
        if not self.enabled:
            return
        self.queue: "queue.Queue" = queue.Queue(maxsize=10000)
        self.batch_size = int(conf.get('audit.mysql.batch_size', 50))
        self.flush_interval = float(conf.get('audit.mysql.flush_interval', 2))
        self._warn_last = 0.0
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

        password_raw = str(conf.get('audit.mysql.password', '') or '')
        # Profile loader already resolved the secret. Do not interpret an opaque
        # password as ciphertext; old encrypted configuration is migration-only.
        password = password_raw
        self.connect_kwargs = dict(
            host=str(conf.get('audit.mysql.host', 'localhost')),
            port=int(conf.get('audit.mysql.port', 3306)),
            database=str(conf.get('audit.mysql.name', 'registry_center')),
            user=str(conf.get('audit.mysql.username', 'a2a_user')),
            password=password,
            connect_timeout=int(conf.get('audit.mysql.connect_timeout', 10)),
            charset='utf8mb4',
            autocommit=True,
        )
        logger.info(f"Audit MySQL sink enabled: {self.connect_kwargs['host']}:"
                    f"{self.connect_kwargs['port']}/{self.connect_kwargs['database']}")

    def start(self) -> None:
        if not self.enabled or self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._consume, daemon=True, name="audit-mysql-sink")
        self._thread.start()

    def stop(self) -> None:
        if self._thread is None:
            return
        self._stop_event.set()
        self._thread.join(timeout=10)
        self._thread = None

    def enqueue(self, entry: dict) -> None:
        """Queue one audit record. Never raises and never blocks the caller."""
        if not self.enabled:
            return
        try:
            record = {
                'time': entry.get('time', ''),
                'client_ip': entry.get('client_ip', ''),
                'user_name': entry.get('user_name', ''),
                'level': entry.get('level', ''),
                'operation_name': entry.get('operation_name', ''),
                'object_name': str(entry.get('object_name', '')),
                'result': entry.get('result', ''),
                'details': json.dumps(entry.get('details', {}), ensure_ascii=False),
            }
            self.queue.put_nowait(record)
        except queue.Full:
            self._warn_rate_limited("audit sink queue full; record kept in local file only")
        except Exception as e:  # pragma: no cover - defensive
            self._warn_rate_limited(f"audit sink enqueue failed: {e}")

    def _warn_rate_limited(self, message: str) -> None:
        now = time.monotonic()
        if now - self._warn_last >= _WARN_INTERVAL_SECONDS:
            self._warn_last = now
            logger.warning(message)

    def _connect(self):
        import pymysql
        return pymysql.connect(**self.connect_kwargs)

    def _ensure_schema(self, conn):
        with conn.cursor() as cur:
            cur.execute(_DDL)

    def _consume(self) -> None:
        conn = None
        while not self._stop_event.is_set():
            try:
                batch = self._drain_batch()
                if not batch:
                    time.sleep(min(self.flush_interval, 0.5))
                    continue
                if conn is None:
                    conn = self._connect()
                    self._ensure_schema(conn)
                self._write_batch(conn, batch)
            except Exception as e:
                self._warn_rate_limited(
                    f"audit MySQL sink degraded to local file only: {e}")
                try:
                    if conn:
                        conn.close()
                except Exception:
                    pass
                conn = None
                time.sleep(min(self.flush_interval, 0.5))
        if conn:
            try:
                conn.close()
            except Exception:
                pass

    def _drain_batch(self):
        batch = []
        try:
            batch.append(self.queue.get(timeout=self.flush_interval))
        except queue.Empty:
            return batch
        while len(batch) < self.batch_size:
            try:
                batch.append(self.queue.get_nowait())
            except queue.Empty:
                break
        return batch

    def _write_batch(self, conn, batch) -> None:
        rows = [(r['time'], r['client_ip'], r['user_name'], r['level'],
                 r['operation_name'], r['object_name'], r['result'], r['details'])
                for r in batch]
        with conn.cursor() as cur:
            cur.executemany(_INSERT, rows)
        logger.debug(f"Audit sink wrote {len(rows)} records to customer MySQL")


_sink: Optional[AuditMySqlSink] = None


def start_audit_sink(conf: dict) -> None:
    """Create and start the sink when audit.mysql.enabled=true (called from start.py)."""
    global _sink
    sink = AuditMySqlSink(conf)
    if sink.enabled:
        sink.start()
        _sink = sink


def stop_audit_sink() -> None:
    global _sink
    if _sink is not None:
        _sink.stop()
        _sink = None


def get_audit_sink() -> Optional[AuditMySqlSink]:
    return _sink
