# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Agent health state machine."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class HealthStatus(str, Enum):
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    SUSPECT = "suspect"
    OFFLINE = "offline"


@dataclass
class HealthState:
    name: str
    organization: str
    last_heartbeat_at: datetime
    status: HealthStatus
    status_changed_at: datetime


def compute_status(last_seen: datetime, now: datetime, interval: int,
                   failure_threshold: int, grace_period: int) -> HealthStatus:
    """
    Classify an agent by the elapsed time since its last heartbeat.

    healthy:  t <= interval + grace
    suspect:  interval + grace < t <= interval * failure_threshold + grace
    offline:  t > interval * failure_threshold + grace
    """
    elapsed = (now - last_seen).total_seconds()
    if elapsed <= interval + grace_period:
        return HealthStatus.HEALTHY
    if elapsed <= interval * max(failure_threshold, 1) + grace_period:
        return HealthStatus.SUSPECT
    return HealthStatus.OFFLINE
