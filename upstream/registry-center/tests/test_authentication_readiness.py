# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Local provider readiness, separate from callers' credential failures."""
from unittest.mock import AsyncMock

import httpx
import pytest

from agent_registry.integration.authn import ThirdPartyAuthnHandler, token_fingerprint
from agent_registry.main_auth import MainTokenPolicy


def auth_config(tmp_path, state="valid", mode="static_bearer"):
    path = tmp_path / "credentials.conf"
    token = token_fingerprint("synthetic-token", "synthetic-hmac")
    content = ("credential.test.identity=test-vendor\ncredential.test.role=vendor_agent\n"
               f"credential.test.token_hash={token}\n")
    if state == "disabled":
        content += "credential.test.enabled=false\n"
    elif state == "invalid":
        content = content.replace(token, "invalid-hash")
    elif state == "empty":
        content = ""
    if state != "missing":
        path.write_text(content, encoding="utf-8")
    return {"owner.identity.mode": "token", "integration.auth.mode": mode,
            "integration.auth.fingerprint_key": "synthetic-fingerprint",
            "integration.auth.static.hmac_key": "synthetic-hmac",
            "integration.credential.file": str(path)}


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["missing", "empty", "disabled", "invalid"])
async def test_unusable_static_credentials_do_not_install_main_policy(tmp_path, state):
    policy = MainTokenPolicy()
    with pytest.raises(ValueError, match="enabled valid token credential"):
        await policy.start(auth_config(tmp_path, state))
    assert policy.handler is None


@pytest.mark.asyncio
async def test_valid_policy_is_ready_and_closed_on_shutdown(tmp_path):
    policy = MainTokenPolicy()
    await policy.start(auth_config(tmp_path))
    policy.validate_configuration()
    await policy.close()
    with pytest.raises(ValueError, match="unavailable"):
        policy.validate_configuration()


@pytest.mark.asyncio
async def test_health_and_authentication_fail_closed_if_an_unready_handler_is_installed(tmp_path, monkeypatch):
    from agent_registry import server, main_auth
    from agent_registry.agent_registry.agent_card_signer import AgentCardSigner
    conf = auth_config(tmp_path, "missing")
    monkeypatch.setattr(server, "config", conf)
    monkeypatch.setattr(server, "get_registry", lambda: object())
    monkeypatch.setattr(server, "_registry_signer", AgentCardSigner(sign_enabled=False))
    policy = MainTokenPolicy()
    policy.handler = ThirdPartyAuthnHandler(config=conf)
    monkeypatch.setattr(main_auth, "main_token_policy", policy)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as client:
            assert (await client.get("/health")).status_code == 503
            assert (await client.get("/rest/v1/registry-center/agent-cards",
                                    headers={"Authorization": "Bearer synthetic-token"})).status_code == 503
    finally:
        await policy.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["oauth2_jwt", "oauth2_introspection"])
async def test_oauth_readiness_does_not_require_static_credentials_or_call_iam(tmp_path, mode):
    conf = auth_config(tmp_path, "missing", mode)
    conf.update({"integration.oauth2.issuer": "https://iam.invalid", "integration.oauth2.audience": "registry",
                 "integration.oauth2.jwks_uri": "https://iam.invalid/keys",
                 "integration.oauth2.introspection_uri": "https://iam.invalid/introspect",
                 "integration.oauth2.client_id": "synthetic-client", "integration.oauth2.client_secret": "synthetic-secret"})
    policy = MainTokenPolicy()
    try:
        await policy.start(conf)
        policy.validate_configuration()
    finally:
        await policy.close()


@pytest.mark.asyncio
async def test_selected_mtls_provider_checks_bindings_without_requiring_tokens(tmp_path):
    conf = auth_config(tmp_path, "empty", "mtls")
    handler = ThirdPartyAuthnHandler(config=conf)
    with pytest.raises(ValueError, match="certificate identity binding"):
        handler.validate_configuration()
    await handler.aclose()
    (tmp_path / "credentials.conf").write_text(
        "credential.client.identity=client\ncredential.client.role=partner_service\ncredential.client.cn=synthetic-client\n",
        encoding="utf-8")
    handler = ThirdPartyAuthnHandler(config=conf)
    try:
        handler.validate_configuration()
    finally:
        await handler.aclose()


@pytest.mark.asyncio
async def test_integration_lifespan_validates_and_cleans_owned_handler(monkeypatch):
    from agent_registry.integration.app import integration_lifespan, integration_app
    from common.custom.custom_handle import HandlerRegistry
    from common.custom.interface_type import InterfaceType
    class InvalidHandler:
        aclose = AsyncMock()
        def validate_configuration(self):
            raise ValueError("synthetic-unready")
    handler = InvalidHandler()
    monkeypatch.setitem(HandlerRegistry._instances, InterfaceType.INTEGRATION_AUTHENTICATE.value, handler)
    with pytest.raises(ValueError, match="synthetic-unready"):
        async with integration_lifespan(integration_app):
            pytest.fail("Unready handler entered service lifespan")
    handler.aclose.assert_awaited_once()
