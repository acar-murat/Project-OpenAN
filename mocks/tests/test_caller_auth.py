"""Energy Agent caller authentication (R-EAS-1, EA-14)."""

import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from mocks.common import audit
from mocks.energy_agent.caller_auth import UNAUTHENTICATED, AllowedCallers, CallerAuthMiddleware, current_caller

TOKEN = "orch-to-energy-agent-token-0123456789"


async def whoami(_request):
    return JSONResponse(current_caller())


async def card(_request):
    return JSONResponse({"name": "card"})


INNER = Starlette(routes=[Route("/v1/message:send", whoami, methods=["POST"]),
                          Route("/.well-known/agent-card.json", card)])


def client(env, tmp_path, ip="10.0.0.5"):
    log = audit.AuditLog(tmp_path / "ea.log")
    app = CallerAuthMiddleware(INNER, AllowedCallers.from_env(env), log)
    return TestClient(app, client=(ip, 4000)), log


def test_empty_list_accepts_everyone_and_says_so(tmp_path):
    http, _ = client({}, tmp_path)
    caller = http.post("/v1/message:send").json()
    assert caller["caller"] == UNAUTHENTICATED and caller["source_ip"] == "10.0.0.5"


def test_bearer_from_env_is_accepted_and_others_refused(tmp_path):
    http, log = client({"ENERGY_AGENT_ALLOWED_CALLERS": "bearer:env:ORCH_TOKEN", "ORCH_TOKEN": TOKEN}, tmp_path)
    ok = http.post("/v1/message:send", headers={"Authorization": f"Bearer {TOKEN}"})
    assert ok.status_code == 200 and ok.json()["caller"] == "bearer:env:ORCH_TOKEN"
    for headers in ({}, {"Authorization": "Bearer wrong"}, {"Authorization": f"Basic {TOKEN}"}):
        assert http.post("/v1/message:send", headers=headers).status_code == 401
    lines = log.path.read_text().splitlines()
    assert len(lines) == 3 and all('"caller_rejected"' in line for line in lines)
    assert TOKEN not in log.path.read_text() and "wrong" not in log.path.read_text()
    assert audit.verify(log.path) == []


def test_bearer_from_file(tmp_path):
    secret = tmp_path / "token"
    secret.write_text(TOKEN + "\n")
    http, _ = client({"ENERGY_AGENT_ALLOWED_CALLERS": f"bearer:file:{secret}"}, tmp_path)
    assert http.post("/v1/message:send", headers={"Authorization": f"Bearer {TOKEN}"}).status_code == 200


def test_ip_allowlist(tmp_path):
    env = {"ENERGY_AGENT_ALLOWED_CALLERS": "ip:10.0.0.0/24"}
    inside, _ = client(env, tmp_path, ip="10.0.0.9")
    assert inside.post("/v1/message:send").json()["caller"] == "ip:10.0.0.0/24"
    outside, _ = client(env, tmp_path, ip="10.0.1.9")
    assert outside.post("/v1/message:send").status_code == 401


def test_agent_card_stays_public(tmp_path):
    http, _ = client({"ENERGY_AGENT_ALLOWED_CALLERS": "ip:192.0.2.0/24"}, tmp_path)
    assert http.get("/.well-known/agent-card.json").status_code == 200
    assert http.post("/.well-known/agent-card.json").status_code == 401


@pytest.mark.parametrize("env", [
    {"ENERGY_AGENT_ALLOWED_CALLERS": "bearer:env:SHORT", "SHORT": "too-short"},
    {"ENERGY_AGENT_ALLOWED_CALLERS": f"bearer:{TOKEN}"},
    {"ENERGY_AGENT_ALLOWED_CALLERS": "cn:orchestration"},
])
def test_bad_configuration_fails_at_startup(env):
    with pytest.raises(ValueError):
        AllowedCallers.from_env(env)


def test_caller_reaches_the_control_point_through_the_a2a_app(tmp_path):
    """The verified caller survives the A2A request handler's task hand-off to the executor."""
    host_agent = pytest.importorskip("host_agent.service")
    from a2a.server.agent_execution import AgentExecutor
    from a2a.types import AgentCard, Message, Part, Role
    from google.protobuf.json_format import ParseDict

    seen = []

    class Executor(AgentExecutor):
        async def execute(self, context, event_queue):
            seen.append(current_caller())
            await event_queue.enqueue_event(Message(message_id="r1", context_id=context.context_id,
                                                    role=Role.ROLE_AGENT, parts=[Part(text="ok")]))

        async def cancel(self, context, event_queue):
            pass

    card = ParseDict({"name": "t", "description": "t", "version": "1", "skills": [],
                      "capabilities": {"streaming": False},
                      "supportedInterfaces": [{"url": "http://127.0.0.1:1", "protocolBinding": "HTTP+JSON",
                                               "protocolVersion": "1.0.0"}]}, AgentCard())
    app = CallerAuthMiddleware(host_agent.create_agent_app(card, Executor()),
                               AllowedCallers.from_env({"ENERGY_AGENT_ALLOWED_CALLERS": "ip:10.0.0.0/8"}))
    http = TestClient(app, client=("10.0.0.5", 4000))
    message = {"message": {"messageId": "m1", "role": "ROLE_USER", "parts": [{"text": "hi"}]}}
    response = http.post("/message:send", json=message, headers={"A2A-Version": "1.0"})
    assert response.status_code == 200, response.text
    assert seen and seen[0]["caller"] == "ip:10.0.0.0/8"
    assert http.post("/message:send", json=message, headers={"A2A-Version": "1.0"},
                     ).status_code == 200
    denied = TestClient(app, client=("192.0.2.1", 4000)).post("/message:send", json=message)
    assert denied.status_code == 401 and len(seen) == 2
