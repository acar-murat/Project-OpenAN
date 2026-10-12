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
from fastapi.testclient import TestClient
from unittest.mock import Mock, patch, MagicMock
from agent_registry.agent_registry.jwk_provider import JWKProvider, CertLoadError
from jwt.api_jwk import PyJWK


@pytest.fixture(scope="module")
def client():
    with patch('agent_registry.agent_registry.jwk_provider.JWKProvider') as mock_class:
        provider_instance = Mock()

        jwk_mock = MagicMock(spec=PyJWK)
        jwk_mock._jwk_data = {
            "kty": "RSA",
            "n": "test_n_value",
            "e": "test_e_value",
            "alg": "RS256",
            "use": "sig",
            "key_ops": ["verify"]
        }

        provider_instance.get_jwk_set.return_value = [jwk_mock]
        mock_class.return_value = provider_instance

        from agent_registry.server import app, config
        config['enable_https'] = 'true'
        config['registry.sign.enabled'] = 'true'

        yield TestClient(app)


@pytest.mark.skip(reason="Requires server config file with TLS and signing enabled")
def test_get_jwks_success(client):
    response = client.get("/rest/v1/registry-center/keys")
    assert response.status_code == 200

    data = response.json()
    assert "keys" in data
    assert len(data["keys"]) == 1

    jwk = data["keys"][0]
    assert jwk["kty"] == "RSA"
    assert jwk["n"] == "test_n_value"
    assert jwk["e"] == "test_e_value"
    assert jwk["alg"] == "RS256"
    assert jwk["use"] == "sig"
    assert jwk["key_ops"] == ["verify"]


@pytest.mark.skip(reason="Requires server config file with TLS and signing enabled")
def test_get_jwks_rate_limit_exceeded(client):
    for i in range(5):
        response = client.get("/rest/v1/registry-center/keys")
        assert response.status_code == 200

    for i in range(5):
        response = client.get("/rest/v1/registry-center/keys")
        if response.status_code == 200:
            continue
        assert response.status_code == 429
        assert "Too Many" in response.json()["detail"]
        break


@pytest.mark.skip(reason="Requires server config file with TLS and signing enabled")
def test_get_jwks_internal_error():
    with patch('agent_registry.server.jwk_provider.get_jwk_set',
               side_effect=CertLoadError("Failed to load certificate")), \
         patch('agent_registry.server.async_hit', return_value=True):
        from agent_registry.server import app, config
        config['enable_https'] = 'true'
        config['registry.sign.enabled'] = 'true'

        test_client = TestClient(app)

        with patch('loguru.logger.error') as mock_logger:
            response = test_client.get("/rest/v1/registry-center/keys")
            assert response.status_code == 500
            assert "Failed to load certificate" in response.json()["detail"]
            mock_logger.assert_called()
