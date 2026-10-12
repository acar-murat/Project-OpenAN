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

from enum import Enum
from typing import Any, Dict, FrozenSet, Optional


class AuthFailureReason(Enum):
    """Authentication failure reason enum"""
    INVALID_CREDENTIALS = "Invalid credentials"
    MISSING_CREDENTIALS = "Missing credentials"
    INVALID_CERTIFICATE = "Invalid client certificate"
    INVALID_TOKEN = "Invalid bearer token"
    INVALID_TOKEN_FORMAT = "Invalid bearer token format"
    PROVIDER_UNAVAILABLE = "Authentication provider unavailable"
    TEMPORARILY_BANNED = "Temporarily banned due to repeated failures"


class AuthenticationError(Exception):
    """Authentication failure exception"""

    def __init__(self, reason: AuthFailureReason, detail: str = None):
        self.reason = reason
        self.detail = detail
        super().__init__(self.detail)


class AuthorizationError(Exception):
    """Authorization failure: the authenticated identity lacks a required role."""

    def __init__(self, detail: str = "Insufficient permissions"):
        self.detail = detail
        super().__init__(self.detail)


class CallerType(Enum):
    """Caller category after authentication"""
    INTERNAL = "internal"        # main-port callers (agents, orchestration center)
    INTEGRATION = "integration"  # integration access port callers


class CallerRole(Enum):
    """Fixed four-role model for integrating callers"""
    NMS_OSS = "nms_oss"                  # operator NMS/OSS: near-full access
    VENDOR_AGENT = "vendor_agent"        # vendor agent: own cards only
    PARTNER_SERVICE = "partner_service"  # partner value-added service: read + subscribe
    ANALYTICS_TOOL = "analytics_tool"    # O&M/analytics tool: read-only + audit pull


AUTH_METHOD_TOKEN = "token"
AUTH_METHOD_STATIC_BEARER = "static_bearer"
AUTH_METHOD_OAUTH2_JWT = "oauth2_jwt"
AUTH_METHOD_OAUTH2_INTROSPECTION = "oauth2_introspection"
AUTH_METHOD_CERTIFICATE = "certificate"


class Principal:
    """Principal identity after successful authentication.

    ``client_ip`` alone (legacy constructor form) means an internal main-port
    caller with no authenticated identity. Integration access fills in the
    identity, caller type, bound role, and the authentication method used.
    """

    def __init__(self, client_ip: str, identity: str = '',
                 caller_type: CallerType = CallerType.INTERNAL,
                 role: Optional[CallerRole] = None,
                 auth_method: str = '',
                 owner: str = '', subject: str = '', issuer: str = '',
                 client_id: str = '', scopes=None, tenant: str = '',
                 credential_id: str = ''):
        self.client_ip = client_ip
        self.identity = identity
        self.caller_type = caller_type
        self.role = role
        self.auth_method = auth_method
        # Owner bound to this identity (credential owner); empty = not bound
        self.owner = owner
        self.subject = subject or identity
        self.issuer = issuer
        self.client_id = client_id
        self.scopes: FrozenSet[str] = frozenset(scopes or ())
        self.tenant = tenant
        self.credential_id = credential_id or self.subject

    def is_integration(self) -> bool:
        return self.caller_type == CallerType.INTEGRATION

    def audit_identity(self) -> str:
        """Identity string for audit records (never contains the secret)."""
        return self.identity or ''


def authenticate(client_ip: str, request: Any, context: Optional[Dict[str, Any]] = None) -> Principal:
    try:
        return Principal(client_ip=client_ip)
    except Exception as e:
        raise AuthenticationError(AuthFailureReason.INVALID_CREDENTIALS, "Authentication failed") from e
