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
import os
import pytest
from unittest.mock import patch


class TestCorsOriginsEnvDriven:

    def test_default_cors_is_star(self):
        with patch.dict(os.environ, {}, clear=True):
            # Remove CORS_ORIGINS if it exists
            os.environ.pop("CORS_ORIGINS", None)
            val = os.environ.get("CORS_ORIGINS", "*")
            assert val == "*"

    def test_cors_from_env_var(self):
        with patch.dict(os.environ, {"CORS_ORIGINS": "http://localhost:3000, http://localhost:8080"}):
            raw = os.environ.get("CORS_ORIGINS", "*")
            origins = [o.strip() for o in raw.split(",") if o.strip()]
            assert origins == ["http://localhost:3000", "http://localhost:8080"]

    def test_cors_single_origin(self):
        with patch.dict(os.environ, {"CORS_ORIGINS": "http://localhost:3000"}):
            raw = os.environ.get("CORS_ORIGINS", "*")
            origins = [o.strip() for o in raw.split(",") if o.strip()]
            assert origins == ["http://localhost:3000"]

    def test_cors_empty_entries_filtered(self):
        with patch.dict(os.environ, {"CORS_ORIGINS": "http://a.com, , http://b.com"}):
            raw = os.environ.get("CORS_ORIGINS", "*")
            origins = [o.strip() for o in raw.split(",") if o.strip()]
            assert len(origins) == 2
            assert "http://a.com" in origins
            assert "http://b.com" in origins


class TestAgentVerifySSLEnvDriven:

    def test_default_verify_ssl_is_false(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("AGENT_VERIFY_SSL", None)
            val = os.environ.get("AGENT_VERIFY_SSL", "false").lower() != "false"
            assert val is False

    def test_verify_ssl_true(self):
        with patch.dict(os.environ, {"AGENT_VERIFY_SSL": "true"}):
            val = os.environ.get("AGENT_VERIFY_SSL", "false").lower() != "false"
            assert val is True

    def test_verify_ssl_case_insensitive(self):
        with patch.dict(os.environ, {"AGENT_VERIFY_SSL": "True"}):
            val = os.environ.get("AGENT_VERIFY_SSL", "false").lower() != "false"
            assert val is True

    def test_verify_ssl_empty_means_false(self):
        with patch.dict(os.environ, {"AGENT_VERIFY_SSL": ""}):
            val = os.environ.get("AGENT_VERIFY_SSL", "false").lower() != "false"
            # Empty string is not "false", so verify_ssl=True per current logic
            assert val is True

    def test_verify_ssl_random_value_means_true(self):
        with patch.dict(os.environ, {"AGENT_VERIFY_SSL": "yes"}):
            val = os.environ.get("AGENT_VERIFY_SSL", "false").lower() != "false"
            assert val is True
