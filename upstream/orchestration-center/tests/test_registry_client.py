# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Tests for orchestrate/registry_client/client.py and client_factory.py.

Uses httpx.MockTransport to avoid live HTTP calls.
"""

import json
from unittest.mock import MagicMock, patch

import httpx
import pytest

from orchestrate.registry_client.client import AgentRegistryClient
from orchestrate.registry_client.client_factory import AgentRegistryClientFactory


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_transport(status_code=200, json_data=None):
    """Create a mock transport that returns a fixed response."""
    if json_data is None:
        json_data = {}

    def handler(request):
        return httpx.Response(status_code, json=json_data)

    return httpx.MockTransport(handler)


async def _make_client_with_transport(transport, base_url="http://test:5000"):
    client = AgentRegistryClient(base_url, timeout=5, ssl_verify=False)
    # Inject a mock httpx client
    client._client = httpx.AsyncClient(transport=transport, timeout=5)
    return client


# ===========================================================================
# AgentRegistryClient
# ===========================================================================

class TestAgentRegistryClient:
    @pytest.mark.asyncio
    async def test_list_exact_returns_agent_cards(self):
        transport = _make_mock_transport(json_data={"agentCards": [{"name": "agent1"}]})
        client = await _make_client_with_transport(transport)
        result = await client.list_exact()
        assert result == [{"name": "agent1"}]
        await client.close()

    @pytest.mark.asyncio
    async def test_list_exact_returns_data_field(self):
        transport = _make_mock_transport(json_data={"data": [{"name": "agent2"}]})
        client = await _make_client_with_transport(transport)
        result = await client.list_exact()
        assert result == [{"name": "agent2"}]
        await client.close()

    @pytest.mark.asyncio
    async def test_list_exact_empty(self):
        transport = _make_mock_transport(json_data={})
        client = await _make_client_with_transport(transport)
        result = await client.list_exact()
        assert result == []
        await client.close()

    @pytest.mark.asyncio
    async def test_list_exact_with_params(self):
        captured_params = {}

        def handler(request):
            captured_params.update(request.url.params)
            return httpx.Response(200, json={"agentCards": []})

        transport = httpx.MockTransport(handler)
        client = await _make_client_with_transport(transport)
        await client.list_exact(name="test_agent", organization="org1")
        assert captured_params["name"] == "test_agent"
        assert captured_params["organization"] == "org1"
        await client.close()

    @pytest.mark.asyncio
    async def test_list_exact_non_json_response(self):
        def handler(request):
            return httpx.Response(200, text="not json", headers={"content-type": "text/plain"})

        transport = httpx.MockTransport(handler)
        client = await _make_client_with_transport(transport)
        result = await client.list_exact()
        assert result == []
        await client.close()

    @pytest.mark.asyncio
    async def test_register_with_dict(self):
        transport = _make_mock_transport(201, json_data={"agentCards": [{"name": "new_agent"}]})
        client = await _make_client_with_transport(transport)
        result = await client.register({"name": "new_agent", "description": "test"})
        assert result["agentCards"][0]["name"] == "new_agent"
        await client.close()

    @pytest.mark.asyncio
    async def test_register_non_json_response(self):
        def handler(request):
            return httpx.Response(201, text="created", headers={"content-type": "text/plain"})

        transport = httpx.MockTransport(handler)
        client = await _make_client_with_transport(transport)
        result = await client.register({"name": "agent"})
        # Non-JSON 200/201 -> returns the dict back
        assert result["agentCards"][0]["name"] == "agent"
        await client.close()

    @pytest.mark.asyncio
    async def test_get_found(self):
        transport = _make_mock_transport(200, json_data={"name": "agent1"})
        client = await _make_client_with_transport(transport)
        result = await client.get("agent1", "org1")
        assert result["name"] == "agent1"
        await client.close()

    @pytest.mark.asyncio
    async def test_get_not_found(self):
        """get() checks status_code==404, but _request raises_for_status
        on 404 first. So get() on a 404 endpoint raises HTTPError."""
        def handler(request):
            return httpx.Response(404, json={"error": "not found"})

        transport = httpx.MockTransport(handler)
        client = await _make_client_with_transport(transport)
        with pytest.raises(httpx.HTTPError):
            await client.get("nonexistent", "org1")
        await client.close()

    @pytest.mark.asyncio
    async def test_deregister_success(self):
        transport = _make_mock_transport(200, json_data={"deleted": True})
        client = await _make_client_with_transport(transport)
        result = await client.deregister("agent1", "org1")
        assert result == {"deleted": True}
        await client.close()

    @pytest.mark.asyncio
    async def test_deregister_non_json_204(self):
        def handler(request):
            return httpx.Response(204, text="", headers={"content-type": "text/plain"})

        transport = httpx.MockTransport(handler)
        client = await _make_client_with_transport(transport)
        result = await client.deregister("agent1", "org1")
        assert result is True
        await client.close()

    @pytest.mark.asyncio
    async def test_update_full_success(self):
        transport = _make_mock_transport(200, json_data={"updated": True})
        client = await _make_client_with_transport(transport)
        result = await client.update_full("agent1", "org1", MagicMock())
        assert result == {"updated": True}
        await client.close()

    @pytest.mark.asyncio
    async def test_search_by_task(self):
        transport = _make_mock_transport(200, json_data=[{"name": "agent1"}])
        client = await _make_client_with_transport(transport)
        result = await client.search_by_task("summarize")
        assert result == [{"name": "agent1"}]
        await client.close()

    @pytest.mark.asyncio
    async def test_list_all_delegates_to_list_exact(self):
        transport = _make_mock_transport(json_data={"agentCards": [{"name": "a1"}]})
        client = await _make_client_with_transport(transport)
        result = await client.list_all()
        assert result == [{"name": "a1"}]
        await client.close()

    @pytest.mark.asyncio
    async def test_request_http_error_raises(self):
        def handler(request):
            return httpx.Response(500, json={"error": "server error"})

        transport = httpx.MockTransport(handler)
        client = await _make_client_with_transport(transport)
        with pytest.raises(httpx.HTTPError):
            await client._request("GET", "/rest/v1/registry-center/agent-cards")
        await client.close()

    @pytest.mark.asyncio
    async def test_close_idempotent(self):
        client = AgentRegistryClient("http://test:5000", ssl_verify=False)
        await client.close()  # client was never created
        # Should not raise

    @pytest.mark.asyncio
    async def test_close_after_use(self):
        transport = _make_mock_transport(json_data={"agentCards": []})
        client = await _make_client_with_transport(transport)
        await client.list_exact()
        await client.close()
        assert client._client is None


# ===========================================================================
# AgentRegistryClientFactory
# ===========================================================================

class TestAgentRegistryClientFactory:
    def test_create_client_default(self):
        with patch("orchestrate.registry_client.client_factory.get_conf") as mock_conf:
            mock_conf.return_value = {
                "agent_registry_url": "http://registry:5000",
                "client_verify_server": "false",
            }
            factory = AgentRegistryClientFactory()
            client = factory.create_client()
            assert client.base_url == "http://registry:5000"
            assert client.ssl_verify is False

    def test_create_client_explicit_url(self):
        with patch("orchestrate.registry_client.client_factory.get_conf") as mock_conf:
            mock_conf.return_value = {"agent_registry_url": "http://default:5000"}
            factory = AgentRegistryClientFactory()
            client = factory.create_client(base_url="http://custom:6000")
            assert client.base_url == "http://custom:6000"

    def test_create_client_ssl_verify_true(self):
        with patch("orchestrate.registry_client.client_factory.get_conf") as mock_conf:
            mock_conf.return_value = {
                "agent_registry_url": "http://registry:5000",
                "client_verify_server": "true",
            }
            factory = AgentRegistryClientFactory()
            client = factory.create_client()
            assert client.ssl_verify is True

    def test_create_client_with_config(self):
        with patch("orchestrate.registry_client.client_factory.get_conf") as mock_conf:
            mock_conf.return_value = {"agent_registry_url": "http://r:5000"}
            factory = AgentRegistryClientFactory(config={"timeout": 60, "ssl_verify": "false"})
            # Don't pass timeout so the factory uses config["timeout"] = 60
            client = factory.create_client(timeout=0)
            assert client.timeout == 60
            assert client.ssl_verify is False

    def test_create_from_env(self):
        with patch("orchestrate.registry_client.client_factory.get_conf") as mock_conf:
            mock_conf.return_value = {
                "agent_registry_url": "http://env:5000",
                "client_verify_server": "false",
            }
            factory = AgentRegistryClientFactory()
            client = factory.create_from_env()
            assert client.base_url == "http://env:5000"

    def test_default_url_fallback(self):
        with patch("orchestrate.registry_client.client_factory.get_conf") as mock_conf:
            mock_conf.return_value = {}
            factory = AgentRegistryClientFactory()
            assert factory.default_base_url == "http://127.0.0.1:5000"
