"""OSS intent boundary with the §11.2 controls applied in the fixed order.

Processing order for ``POST /api/v1/energy-saving/intents`` (LLD v10.4 §11.2, R-INT-14; do not reorder):

    authenticate → RBAC → rate limit → input cap → audit intent_received → classify →
    validate parameters → region scope → audit workflow_started (fail closed) → submit

The classifier, the parameter extractor and the Orchestration Center submitter are
injected, so the LLM and ORCH client can be swapped without touching the controls.
The defaults are deterministic stubs for tests and local runs. Intents live in
memory here; the real store is OSS-2.

Run locally: ``uvicorn oss.app:app --port 8095`` with ``OSS_AUTH_USERS_FILE`` set.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from mocks.common.audit import digest
from oss import audit as oss_audit
from oss import security
from oss.security import PERM_ADMIN, PERM_QUERY, PERM_SUBMIT, InputError, Principal

log = logging.getLogger("oss")

REQUIRED_FIELDS = ("region", "saving_target", "experience_target")
#: The only fields that ever leave OSS for the Orchestration Center (R-SEC-5): never raw_text.
FORWARDED_FIELDS = ("intent_id", "trace_id", "region", "saving_target", "experience_target",
                    "operation_type", "task_description")

Classifier = Callable[[str], Any]
Extractor = Callable[[str], dict[str, Any]]
Submitter = Callable[[dict[str, Any]], dict[str, Any]]


def keyword_classifier(raw_text: str) -> dict[str, Any]:
    """Deterministic stand-in for the LLM classifier (OSS-5)."""
    hit = any(word in raw_text.casefold() for word in ("energy", "saving", "power"))
    return {"is_energy_saving_intent": hit, "confidence": 0.9 if hit else 0.1}


def no_extraction(_raw_text: str) -> dict[str, Any]:
    return {}


def stub_submitter(request: dict[str, Any]) -> dict[str, Any]:
    return {"workflow_execution_id": f"stub-{uuid.uuid4()}"}


def orchestration_request(intent: dict[str, Any]) -> dict[str, Any]:
    return {key: intent.get(key) for key in FORWARDED_FIELDS}


def create_app(*, auth: security.AuthManager, audit: oss_audit.AuditService,
               rate_limiter: security.RateLimiter | None = None, raw_text_max_chars: int = 2000,
               classifier: Classifier = keyword_classifier, extractor: Extractor = no_extraction,
               submitter: Submitter = stub_submitter) -> FastAPI:
    app = FastAPI(title="OSS energy-saving intents")
    limiter = rate_limiter or security.RateLimiter({})
    intents: dict[str, dict[str, Any]] = {}
    app.state.intents = intents

    def source_ip(request: Request) -> str | None:
        return request.client.host if request.client else None

    def error(status: int, code: str, message: str, headers: dict[str, str] | None = None) -> JSONResponse:
        return JSONResponse({"error": code, "message": message}, status_code=status, headers=headers)

    def authorize(request: Request, permission: str) -> Principal | JSONResponse:
        principal = auth.authenticate(request.headers.get("authorization"))
        if principal is None:
            audit.record("auth_failure", outcome="denied", reason="identity_not_established",
                         actor={"source_ip": source_ip(request)},
                         detail={"method": request.method, "path": request.url.path})
            return error(401, "unauthenticated", "identity not established")
        if not principal.can(permission):
            audit.record("permission_denied", outcome="denied", reason=f"missing {permission}",
                         actor=principal.as_actor(source_ip(request)),
                         detail={"permission": permission, "path": request.url.path})
            return error(403, "forbidden", f"{permission} is required")
        return principal

    def rate_limited(principal: Principal, action: str) -> JSONResponse | None:
        retry_after = limiter.check(principal.user_id, action)
        if retry_after is None:
            return None
        return error(429, "rate_limited", f"too many {action} requests", {"Retry-After": str(retry_after)})

    def visible_intent(principal: Principal, intent_id: str) -> dict[str, Any] | None:
        intent = intents.get(intent_id)
        # Another user's intent reads as missing, so ids cannot be probed (R-SEC-4).
        return intent if intent is not None and principal.owns_or_admin(intent["user_id"]) else None

    def advance(request: Request, principal: Principal, intent: dict[str, Any]) -> JSONResponse:
        """Validate parameters, check region scope, audit workflow_started and submit."""
        missing = [name for name in REQUIRED_FIELDS if not intent.get(name)]
        if missing:
            intent["status"] = "awaiting_supplement"
            return JSONResponse({"handled": True, "intent_id": intent["intent_id"],
                                 "status": "awaiting_supplement", "missing_fields": missing})
        actor = principal.as_actor(source_ip(request))
        resource = {"region": intent["region"]}
        if not principal.may_target(intent["region"]):
            audit.record("permission_denied", outcome="denied", reason="region_not_permitted",
                         intent_id=intent["intent_id"], trace_id=intent["trace_id"], actor=actor,
                         resource=resource, detail={"region": intent["region"]})
            return error(403, "region_not_permitted", f"you may not target region {intent['region']!r}")
        intent["operation_type"] = intent.get("operation_type") or "Create"
        intent["task_description"] = (f"{intent['operation_type']} energy saving for {intent['region']}: "
                                      f"saving {intent['saving_target']}, experience {intent['experience_target']}")
        body = orchestration_request(intent)
        try:
            audit.record("workflow_started", intent_id=intent["intent_id"], trace_id=intent["trace_id"],
                         actor=actor, resource=resource, detail={"request_digest": digest(body)})
        except oss_audit.AuditWriteError:
            log.exception("workflow_started could not be audited; not submitting")
            return error(503, "audit_unavailable", "the audit store is unavailable; nothing was submitted")
        result = submitter(body)
        intent["status"] = "submitted"
        intent["workflow_execution_id"] = result.get("workflow_execution_id")
        return JSONResponse({"handled": True, "intent_id": intent["intent_id"],
                             "status": "submitted_to_orchestration",
                             "workflow_execution_id": intent["workflow_execution_id"]}, status_code=202)

    @app.post("/api/v1/energy-saving/intents")
    async def submit_intent(request: Request):
        principal = authorize(request, PERM_SUBMIT)
        if isinstance(principal, JSONResponse):
            return principal
        if (limited := rate_limited(principal, "submit")) is not None:
            return limited
        try:
            body = await request.json()
            raw_text = security.check_raw_text(body.get("raw_text"), raw_text_max_chars)
        except InputError as exc:
            return error(413 if exc.code == "raw_text_too_long" else 422, exc.code, str(exc))
        except (ValueError, AttributeError):
            return error(422, "invalid_body", "the body must be a JSON object")
        intent_id, trace_id = str(uuid.uuid4()), body.get("trace_id") or uuid.uuid4().hex
        actor = principal.as_actor(source_ip(request))
        audit.record("intent_received", intent_id=intent_id, trace_id=trace_id, actor=actor,
                     detail={"raw_text": raw_text, "session_id": body.get("session_id")})
        try:
            verdict = security.validate_classifier_output(classifier(raw_text))
        except InputError as exc:
            log.warning("classifier output refused: %s", exc)
            return error(502, exc.code, "the intent classifier returned an invalid result")
        if not verdict["is_energy_saving_intent"]:
            audit.record("intent_not_energy_saving", intent_id=intent_id, trace_id=trace_id, actor=actor,
                         detail=verdict)
            return JSONResponse({"handled": False})
        extracted = extractor(raw_text) or {}
        intent = {"intent_id": intent_id, "trace_id": trace_id, "user_id": principal.user_id,
                  "session_id": body.get("session_id"), "status": "received", "operation_type": None,
                  # Explicit request fields win over what was extracted from the text.
                  **{name: body.get(name) or extracted.get(name) for name in REQUIRED_FIELDS}}
        intents[intent_id] = intent
        return advance(request, principal, intent)

    @app.post("/api/v1/energy-saving/intents/{intent_id}/supplement")
    async def supplement_intent(intent_id: str, request: Request):
        principal = authorize(request, PERM_SUBMIT)
        if isinstance(principal, JSONResponse):
            return principal
        if (limited := rate_limited(principal, "supplement")) is not None:
            return limited
        intent = visible_intent(principal, intent_id)
        if intent is None:
            return error(404, "not_found", "no such intent")
        if intent["status"] != "awaiting_supplement":
            return error(409, "not_awaiting_supplement", f"intent is {intent['status']}")
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError
        except ValueError:
            return error(422, "invalid_body", "the body must be a JSON object")
        if body.get("session_id") != intent.get("session_id"):
            return error(409, "session_mismatch", "session_id does not match the intent")
        supplied = {name: body[name] for name in REQUIRED_FIELDS if body.get(name)}
        intent.update(supplied)
        audit.record("parameter_supplement", intent_id=intent_id, trace_id=intent["trace_id"],
                     actor=principal.as_actor(source_ip(request)), detail={"fields": sorted(supplied)})
        return advance(request, principal, intent)

    @app.get("/api/v1/energy-saving/intents/{intent_id}/status")
    async def intent_status(intent_id: str, request: Request):
        principal = authorize(request, PERM_QUERY)
        if isinstance(principal, JSONResponse):
            return principal
        intent = visible_intent(principal, intent_id)
        if intent is None:
            return error(404, "not_found", "no such intent")
        return {"intent_id": intent_id, "workflow_state": intent["status"].upper(),
                "artifacts": intent.get("artifacts", []), "counter_proposal": intent.get("counter_proposal"),
                "final_report": intent.get("final_report"), "failure_reason": intent.get("failure_reason")}

    @app.get("/api/v1/energy-saving/audit-logs")
    async def audit_logs(request: Request, intent_id: str | None = None, event: str | None = None,
                         limit: int = 100, format: str = "native"):
        principal = authorize(request, PERM_ADMIN)
        if isinstance(principal, JSONResponse):
            return principal
        try:
            records = audit.read(principal, source_ip=source_ip(request), intent_id=intent_id, event=event,
                                 limit=limit, export=format if format != "native" else None)
        except oss_audit.AuditWriteError:
            return error(503, "audit_unavailable", "the audit store is unavailable")
        if format == "upstream":
            records = [oss_audit.to_upstream(record) for record in records]
        return {"records": records}

    return app


def _default_app() -> FastAPI:
    security.install_secret_redaction()
    return create_app(auth=security.AuthManager.from_env(), audit=oss_audit.AuditService.from_env(),
                      rate_limiter=security.RateLimiter.from_env(), raw_text_max_chars=security.raw_text_limit())


def __getattr__(name: str) -> Any:
    # ``uvicorn oss.app:app`` builds the app from the environment on first use, not at import time.
    if name == "app":
        return _default_app()
    raise AttributeError(name)
