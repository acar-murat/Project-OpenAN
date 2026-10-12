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
import pytest
from common.util.authenticate_util import authenticate, Principal, AuthenticationError, AuthFailureReason


class TestAuthenticate:

    def test_returns_principal_with_client_ip(self):
        result = authenticate("192.168.1.1", None, None)
        assert isinstance(result, Principal)
        assert result.client_ip == "192.168.1.1"

    def test_returns_principal_with_any_ip(self):
        result = authenticate("10.0.0.5", {}, {})
        assert result.client_ip == "10.0.0.5"


class TestPrincipal:

    def test_stores_client_ip(self):
        p = Principal("127.0.0.1")
        assert p.client_ip == "127.0.0.1"


class TestAuthenticationError:

    def test_stores_reason_and_detail(self):
        err = AuthenticationError(AuthFailureReason.INVALID_CREDENTIALS, "bad token")
        assert err.reason == AuthFailureReason.INVALID_CREDENTIALS
        assert err.detail == "bad token"

    def test_none_detail(self):
        err = AuthenticationError(AuthFailureReason.INVALID_CREDENTIALS)
        assert err.detail is None


class TestAuthFailureReason:

    def test_invalid_credentials_value(self):
        assert AuthFailureReason.INVALID_CREDENTIALS.value == "Invalid credentials"
