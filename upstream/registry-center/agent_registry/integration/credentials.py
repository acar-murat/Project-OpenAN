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

"""Provisioned identities for static Bearer tokens and mTLS certificates."""

import os
from dataclasses import dataclass
from typing import Dict, Tuple

from loguru import logger

from common.util.app_config import get_root_path, load_conf_as_dict, resolve_env_vars
from common.util.authenticate_util import CallerRole

_PREFIX = "credential."
_FIELDS = ("identity", "token_hash", "role", "owner", "enabled", "cn")


@dataclass(frozen=True)
class CredentialEntry:
    credential_id: str
    identity: str
    role: CallerRole
    owner: str
    token_hash: str = ''
    cn: str = ''


def _default_file() -> str:
    return os.path.join(get_root_path(), "etc", "conf", "integration_credentials.conf")


def load_credentials(path: str = '') -> Tuple[Dict[str, CredentialEntry], Dict[str, CredentialEntry]]:
    """Load entries keyed by credential id and certificate CN."""
    path = path or _default_file()
    if not os.path.isabs(path):
        path = os.path.join(get_root_path(), path)
    if not os.path.exists(path):
        logger.warning(f"Credential file {path} not found; integration access has no credentials")
        return {}, {}
    raw = resolve_env_vars(load_conf_as_dict(path))
    grouped: Dict[str, Dict[str, str]] = {}
    for key, value in raw.items():
        if not key.startswith(_PREFIX) or not value:
            continue
        parts = key[len(_PREFIX):].split('.')
        if len(parts) != 2 or parts[1] not in _FIELDS:
            logger.warning(f"Ignoring unsupported credential key: {key}")
            continue
        grouped.setdefault(parts[0], {})[parts[1]] = str(value).strip()

    tokens: Dict[str, CredentialEntry] = {}
    certificates: Dict[str, CredentialEntry] = {}
    for credential_id, fields in grouped.items():
        if fields.get('enabled', 'true').lower() == 'false':
            continue
        cn = fields.get('cn', '')
        identity = fields.get('identity', '') or cn
        token_hash = fields.get('token_hash', '').lower()
        if not identity or (not token_hash and not cn):
            logger.warning(f"Credential entry '{credential_id}' missing identity and token_hash/cn; skipped")
            continue
        if token_hash and (len(token_hash) != 64 or any(c not in '0123456789abcdef' for c in token_hash)):
            logger.warning(f"Credential entry '{credential_id}' has invalid token_hash; skipped")
            continue
        try:
            role = CallerRole(fields.get('role', ''))
        except ValueError:
            logger.warning(f"Credential entry '{credential_id}' has invalid role; skipped")
            continue
        entry = CredentialEntry(credential_id, identity, role,
                                fields.get('owner', '') or identity, token_hash, cn)
        if token_hash:
            if credential_id in tokens:
                logger.warning(f"Duplicate credential id '{credential_id}'; keeping first")
            tokens.setdefault(credential_id, entry)
        if cn:
            if cn in certificates:
                logger.warning(f"Duplicate certificate CN '{cn}'; keeping first")
            certificates.setdefault(cn, entry)
    identities = {entry.identity for entry in tokens.values()} | {
        entry.identity for entry in certificates.values()
    }
    for entry in list(tokens.values()) + list(certificates.values()):
        if entry.owner != entry.identity and entry.owner in identities:
            logger.warning(
                f"Credential owner '{entry.owner}' matches another identity; "
                "owner is attribution metadata and grants no access")
    return tokens, certificates
