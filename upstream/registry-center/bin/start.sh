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

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Get the absolute path of the script's directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

ROOT_DIR="${SCRIPT_DIR}/.."
TARGET_DIR="${SCRIPT_DIR}/../agent_registry"

if [ -d "$ROOT_DIR" ]; then
    ROOT_DIR="$(cd "$ROOT_DIR" && pwd)"
    cd "$ROOT_DIR"
    echo "Current working directory: $(pwd)"
else
  echo "The project root path does not exist."
  exit 1
fi

# get user information
CURRENT_USER=$(whoami)
CURRENT_UID=$(id -u)
CURRENT_GID=$(id -g)

# Check if running as root
if [ "$EUID" -eq 0 ]; then
    echo "⚠️  ===== Security Warning ====="
    echo "You are currently running as root!"
    echo "Executing commands as root may pose security risks. Please proceed with caution."
    echo "   It is recommended to use root privileges only when necessary."
    echo "============================="

    read -p "$(echo -e "${YELLOW}Do you want to continue?(y/n): ${NC}")" choice
    case "$choice" in
        [Yy]|[Yy][Ee][Ss])
            echo "Continue to execute..."
            ;;
        *)
            echo "Operation canceled"
            exit 0
            ;;
    esac
fi

# Passing through environment variables to Python
export APP_USER="$CURRENT_USER"
export APP_UID="$CURRENT_UID"
export APP_GID="$CURRENT_GID"
export OPENSSL_CONF="${ROOT_DIR}/etc/conf/custom_openssl.cnf"

# Check if target directory exists
if [ -d "$TARGET_DIR" ]; then
    echo "Target directory exists:$TARGET_DIR"
else
    echo "Error: Target directory does not exist: $TARGET_DIR"
    exit 1
fi

# Check if Python script 'start.py' exists in the target directory
PYTHON_SCRIPT="${TARGET_DIR}/start.py"
if [ -f "$PYTHON_SCRIPT" ]; then
    echo "Python script found:$PYTHON_SCRIPT"
else
    echo "Error: Python script start.py does not exist in $TARGET_DIR"
    exit 1
fi

# Start the Python script
echo "Starting Python script: $PYTHON_SCRIPT"
python3 -m agent_registry.start

EXIT_CODE=$?
echo "$EXIT_CODE"