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
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See
#    the License for the specific language governing permissions and limitations
#    under the License.

"""Tests for AgentCard signature validation."""

import base64
import json
import pytest
from unittest.mock import MagicMock, patch

from agent_registry.signature.agent_card_signature_validator import (
    AgentCardSignatureValidator,
    ValidationResult,
    SignatureObject,
    ProtectedHeader,
)


class TestValidationResult:
    def test_valid_result(self):
        r = ValidationResult(is_valid=True)
        assert r.is_valid
        assert r.error_code is None

    def test_invalid_result_with_message(self):
        r = ValidationResult(is_valid=False, error_code="SIG001", error_message="Bad sig")
        assert not r.is_valid
        assert r.error_code == "SIG001"
        assert r.error_message == "Bad sig"


class TestExtractSignatures:
    def test_empty_signatures(self):
        agent = MagicMock()
        agent.signatures = []
        result = AgentCardSignatureValidator._extract_signatures_from_protobuf(agent)
        assert result == []

    def test_extract_valid_signature(self):
        agent = MagicMock()
        sig = MagicMock()
        sig.protected = "eyJhbGciOiJSUzI1NiJ9"
        sig.signature = "base64sig"
        sig.header = None
        agent.signatures = [sig]
        result = AgentCardSignatureValidator._extract_signatures_from_protobuf(agent)
        assert len(result) == 1
        assert result[0].protected == "eyJhbGciOiJSUzI1NiJ9"
        assert result[0].signature == "base64sig"

    def test_skip_missing_protected(self):
        agent = MagicMock()
        sig = MagicMock()
        sig.protected = ""
        sig.signature = "base64sig"
        agent.signatures = [sig]
        result = AgentCardSignatureValidator._extract_signatures_from_protobuf(agent)
        assert result == []

    def test_skip_missing_signature(self):
        agent = MagicMock()
        sig = MagicMock()
        sig.protected = "eyJhbGciOiJSUzI1NiJ9"
        sig.signature = ""
        agent.signatures = [sig]
        result = AgentCardSignatureValidator._extract_signatures_from_protobuf(agent)
        assert result == []


class TestDecodeProtected:
    def test_valid_protected_header(self):
        payload = json.dumps({"alg": "RS256", "kid": "key-001", "typ": "JWT", "jku": "https://keys.example"})
        b64 = base64.urlsafe_b64encode(payload.encode()).rstrip(b'=').decode()
        result = AgentCardSignatureValidator._decode_protected(b64)
        assert result is not None
        assert result.alg == "RS256"
        assert result.kid == "key-001"

    def test_invalid_base64(self):
        result = AgentCardSignatureValidator._decode_protected("!!!not base64!!!")
        assert result is None

    def test_empty_string(self):
        result = AgentCardSignatureValidator._decode_protected("")
        assert result is None


class TestLoadSignatureConfig:
    def test_enabled_when_config_true(self):
        with patch('agent_registry.signature.agent_card_signature_validator.get_conf',
                   return_value={'signature_validation_enabled': 'true'}):
            result = AgentCardSignatureValidator._load_signature_config()
            assert result is True

    def test_disabled_when_config_false(self):
        with patch('agent_registry.signature.agent_card_signature_validator.get_conf',
                   return_value={'signature_validation_enabled': 'false'}):
            result = AgentCardSignatureValidator._load_signature_config()
            assert result is False

    def test_default_true_on_config_error(self):
        with patch('agent_registry.signature.agent_card_signature_validator.get_conf',
                   side_effect=Exception("Config error")):
            result = AgentCardSignatureValidator._load_signature_config()
            assert result is True


class TestValidateAgentCard:
    def test_skip_when_disabled(self):
        mock_fetcher = MagicMock()
        validator = AgentCardSignatureValidator(mock_fetcher)
        validator._signature_validation_enabled = False
        agent = MagicMock()
        result = validator.validate_agent_card(agent)
        assert result.is_valid

    def test_fail_when_no_signatures(self):
        mock_fetcher = MagicMock()
        validator = AgentCardSignatureValidator(mock_fetcher)
        validator._signature_validation_enabled = True
        agent = MagicMock()
        agent.provider.organization = "TestOrg"
        agent.provider.url = "https://test.org"
        agent.name = "TestAgent"
        agent.signatures = []
        result = validator.validate_agent_card(agent)
        assert not result.is_valid
        assert result.error_code == "SIG001"
