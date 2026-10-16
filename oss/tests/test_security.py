"""Unit tests for the OSS security primitives."""

import logging

import pytest

from oss import security
from oss.security import InputError, Principal


def test_roles_map_to_permissions():
    assert Principal("a", ("operator",)).permissions == {security.PERM_SUBMIT, security.PERM_QUERY}
    assert Principal("v", ("viewer",)).permissions == {security.PERM_QUERY}
    assert Principal("r", ("admin",)).is_admin
    assert Principal("x", ("unknown",)).permissions == frozenset()


def test_region_scope_and_ownership():
    alice = Principal("alice", ("operator",), frozenset({"accra central"}))
    assert alice.may_target(" Accra Central ") and not alice.may_target("Kumasi")
    assert Principal("r", ("admin",), frozenset({"*"})).may_target("Anywhere")
    assert alice.owns_or_admin("alice") and not alice.owns_or_admin("bob")
    assert Principal("r", ("admin",)).owns_or_admin("bob")


def test_auth_manager_stores_digests_and_checks_the_scheme():
    auth = security.AuthManager([{"user_id": "a", "roles": ["viewer"], "token_sha256": security.token_digest("tok")}])
    assert auth.authenticate("Bearer tok").user_id == "a"
    for header in (None, "", "Bearer", "Basic tok", "Bearer other", "tok"):
        assert auth.authenticate(header) is None


def test_auth_manager_from_env_reads_the_users_file(tmp_path):
    users = tmp_path / "users.json"
    users.write_text('[{"user_id": "a", "roles": ["admin"], "regions": ["*"], '
                     f'"token_sha256": "{security.token_digest("t")}"}}]')
    assert security.AuthManager.from_env({"OSS_AUTH_USERS_FILE": str(users)}).authenticate("Bearer t").is_admin
    assert security.AuthManager.from_env({}).authenticate("Bearer t") is None


def test_rate_limiter_slides_per_user_and_action():
    now = [1000.0]
    limiter = security.RateLimiter({"submit": 2, "supplement": 0}, clock=lambda: now[0])
    assert limiter.check("a", "submit") is None
    now[0] += 10
    assert limiter.check("a", "submit") is None
    assert limiter.check("a", "submit") == 50
    assert limiter.check("b", "submit") is None
    assert limiter.check("a", "supplement") is None  # 0 means no limit
    now[0] += 50
    assert limiter.check("a", "submit") is None


def test_raw_text_cap():
    assert security.check_raw_text("hi", 2) == "hi"
    with pytest.raises(InputError, match="limit is 2"):
        security.check_raw_text("hey", 2)
    with pytest.raises(InputError):
        security.check_raw_text("   ", 10)
    with pytest.raises(InputError):
        security.check_raw_text(42, 10)


@pytest.mark.parametrize("output", [
    {"is_energy_saving_intent": True},
    {"is_energy_saving_intent": True, "confidence": 0.5, "note": "ignore the rules"},
    {"is_energy_saving_intent": "yes", "confidence": 0.5},
    {"is_energy_saving_intent": True, "confidence": 1.5},
    {"is_energy_saving_intent": True, "confidence": True},
    "true",
])
def test_classifier_output_must_be_exactly_two_typed_fields(output):
    with pytest.raises(InputError):
        security.validate_classifier_output(output)


def test_classifier_output_accepted():
    assert security.validate_classifier_output({"is_energy_saving_intent": False, "confidence": 1}) == {
        "is_energy_saving_intent": False, "confidence": 1.0}


def test_secret_references_never_take_a_value(tmp_path):
    secret_file = tmp_path / "token"
    secret_file.write_text("from-file\n")
    assert security.resolve_secret("env:X", {"X": "from-env"}) == "from-env"
    assert security.resolve_secret(f"file:{secret_file}", {}) == "from-file"
    assert security.resolve_secret(None) is None
    with pytest.raises(ValueError):
        security.resolve_secret("plain-secret-value", {})


def test_configured_secrets_are_redacted_from_logs(caplog):
    env = {"OSS_INTENT_LLM_API_KEY": "sk-live-abc", "OSS_ORCH_BEARER_TOKEN_REF": "env:ORCH", "ORCH": "orch-token-xyz"}
    redactor = security.SecretRedactingFilter(security.configured_secrets(env))
    logger = logging.getLogger("oss.test.redaction")
    logger.addFilter(redactor)
    with caplog.at_level(logging.INFO, logger="oss.test.redaction"):
        logger.info("calling the LLM with %s and ORCH with %s", "sk-live-abc", "orch-token-xyz")
    assert "sk-live-abc" not in caplog.text and "orch-token-xyz" not in caplog.text
    assert caplog.text.count("[REDACTED]") == 2
