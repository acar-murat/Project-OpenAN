#!/bin/bash

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

set -euo pipefail

# Stop service by process name
# Usage: ./stop.sh

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Process name
PROCESS_NAME="agent_registry.start"

echo "Stopping service..."

# Find process
PIDS=$(pgrep -f "$PROCESS_NAME" 2>/dev/null || true)

if [ -z "$PIDS" ]; then
    echo -e "${YELLOW}No running service found${NC}"
    exit 0
fi

echo "Found process PID: $PIDS"

# Stop process
for PID in $PIDS; do
    kill -TERM "$PID" 2>/dev/null || true
done

sleep 2

# Check and force stop remaining processes
REMAINING=$(pgrep -f "$PROCESS_NAME" 2>/dev/null || true)
if [ -n "$REMAINING" ]; then
    echo -e "${YELLOW}Process not responding, force stopping...${NC}"
    for PID in $REMAINING; do
        kill -9 "$PID" 2>/dev/null || true
    done
    sleep 1
fi

# Final check: re-fetch PIDs to ensure all processes are stopped
FINAL_CHECK=$(pgrep -f "$PROCESS_NAME" 2>/dev/null || true)
if [ -n "$FINAL_CHECK" ]; then
    echo -e "${RED}Warning: Some processes still running: $FINAL_CHECK${NC}"
    for PID in $FINAL_CHECK; do
        kill -9 "$PID" 2>/dev/null || true
    done
    sleep 1
fi

echo -e "${GREEN}Service stopped${NC}"