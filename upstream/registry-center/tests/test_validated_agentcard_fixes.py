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

"""Tests for the ProtectedHeader model, validate_status, and base64 padding."""

import base64
import json
import pytest

from agent_registry.signature.agent_card_signature_validator import (
    AgentCardSignatureValidator,
)


class TestSignatureBase64Padding:
    def test_no_padding_needed(self):
        payload = json.dumps({"alg": "RS256", "kid": "key1", "jku": "https://keys.example"})
        b64 = base64.urlsafe_b64encode(payload.encode()).rstrip(b'=').decode()
        result = AgentCardSignatureValidator._decode_protected(b64)
        assert result is not None
        assert result.alg == "RS256"

    def test_padding_needed_one(self):
        payload = json.dumps({"alg": "RS256", "kid": "k1", "jku": "https://a.b"})
        b64 = base64.urlsafe_b64encode(payload.encode()).rstrip(b'=').decode()
        result = AgentCardSignatureValidator._decode_protected(b64)
        assert result is not None

    def test_already_padded(self):
        payload = json.dumps({"alg": "RS256", "kid": "k1", "jku": "https://a.b"})
        b64 = base64.urlsafe_b64encode(payload.encode()).decode()
        result = AgentCardSignatureValidator._decode_protected(b64)
        assert result is not None

    def test_invalid_returns_none(self):
        result = AgentCardSignatureValidator._decode_protected("!!!invalid!!!")
        assert result is None

    def test_empty_string(self):
        result = AgentCardSignatureValidator._decode_protected("")
        assert result is None
