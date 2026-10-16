import pytest
from fastapi.testclient import TestClient

from mocks.common.audit import AuditLog
from oss import audit as oss_audit
from oss import security
from oss.app import create_app

TOKENS = {"alice": "alice-token", "bob": "bob-token", "vera": "vera-token", "root": "root-token"}
USERS = [
    {"user_id": "alice", "roles": ["operator"], "regions": ["Accra Central"]},
    {"user_id": "bob", "roles": ["operator"], "regions": ["Kumasi"]},
    {"user_id": "vera", "roles": ["viewer"], "regions": ["*"]},
    {"user_id": "root", "roles": ["admin"], "regions": ["*"]},
]

UC1_FIELDS = {"region": "Accra Central", "saving_target": "maximized_energy_saving",
              "experience_target": "10 Mbps floor"}


def bearer(user: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKENS[user]}"}


@pytest.fixture
def auth():
    return security.AuthManager([{**u, "token_sha256": security.token_digest(TOKENS[u["user_id"]])} for u in USERS])


@pytest.fixture
def audit_service(tmp_path):
    return oss_audit.AuditService(AuditLog(tmp_path / "audit.log"), tmp_path / "spool")


def records(service):
    return list(oss_audit.iter_records(service._store.path))


@pytest.fixture
def make_client(auth, audit_service):
    def make(**overrides):
        app = create_app(auth=auth, audit=overrides.pop("audit", audit_service), **overrides)
        return TestClient(app, client=("10.1.2.3", 5555))
    return make
