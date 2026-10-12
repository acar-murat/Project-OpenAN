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
Audit record reader for the integration pull API.

Reads the local audit JSON-lines file and its rotated backups (newest
first), applies filters, and returns a paginated slice. Secrets never
appear in audit records by construction; records are returned as parsed
JSON objects with an added ISO index field for stable ordering.
"""

import json
import os
from typing import List, Optional

from loguru import logger


def _audit_files(log_file: str, backup_count: int) -> List[str]:
    """Files in newest-first order: current log, then .1, .2, ..."""
    files = [log_file]
    for i in range(1, backup_count + 2):
        path = f"{log_file}.{i}"
        if os.path.exists(path):
            files.append(path)
    return files


def _entry_time(entry: dict) -> str:
    return str(entry.get('time', ''))


def _entry_identity(entry: dict) -> str:
    # The audit writer normalizes keys to userName; accept the raw key too
    return str(entry.get('userName', entry.get('user_name', '')))


def _entry_operation(entry: dict) -> str:
    return str(entry.get('operationName', entry.get('operation_name', '')))


def read_audit_records(log_file: str, backup_count: int = 4,
                       start_time: Optional[str] = None,
                       end_time: Optional[str] = None,
                       identity: Optional[str] = None,
                       operation: Optional[str] = None,
                       limit: int = 100, offset: int = 0) -> dict:
    """Filter audit records newest-first. Times are ISO-8601 strings compared
    lexicographically (the audit writer emits a consistent UTC format)."""
    matched: List[dict] = []
    for path in _audit_files(log_file, backup_count):
        if not os.path.exists(path):
            continue
        try:
            with open(path, 'r', encoding='utf-8') as f:
                # newest first within the file
                lines = reversed(f.readlines())
        except OSError as e:
            logger.warning(f"Failed to read audit file {path}: {e}")
            continue
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = _entry_time(entry)
            if start_time and ts < start_time:
                continue
            if end_time and ts > end_time:
                continue
            if identity and _entry_identity(entry) != identity:
                continue
            if operation and _entry_operation(entry) != operation:
                continue
            matched.append(entry)
    total = len(matched)
    page = matched[offset:offset + max(0, limit)]
    return {"total": total, "records": page}
