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

from agent_registry.integration.authn import token_fingerprint
from agent_registry.integration.credentials import load_credentials
from common.util.authenticate_util import CallerRole


def _write(tmp_path, text):
    path = tmp_path / 'credentials.conf'
    path.write_text(text, encoding='utf-8')
    return str(path)


def test_loads_static_digest_and_certificate_entries(tmp_path):
    digest = token_fingerprint('token', 'key')
    path = _write(tmp_path,
        f'credential.static.identity=svc\ncredential.static.token_hash={digest}\n'
        'credential.static.role=nms_oss\n'
        'credential.cert.identity=vendor\ncredential.cert.cn=vendor-cn\n'
        'credential.cert.role=vendor_agent\n')
    tokens, certs = load_credentials(path)
    assert tokens['static'].token_hash == digest
    assert tokens['static'].role == CallerRole.NMS_OSS
    assert certs['vendor-cn'].identity == 'vendor'


def test_plaintext_or_invalid_digest_is_rejected(tmp_path):
    path = _write(tmp_path,
        'credential.bad.identity=svc\ncredential.bad.token_hash=plaintext-token\n'
        'credential.bad.role=nms_oss\ncredential.bad.secret=also-plaintext\n')
    tokens, certs = load_credentials(path)
    assert tokens == {}
    assert certs == {}


def test_disabled_entry_is_not_loaded(tmp_path):
    digest = 'a' * 64
    path = _write(tmp_path,
        f'credential.off.identity=svc\ncredential.off.token_hash={digest}\n'
        'credential.off.role=nms_oss\ncredential.off.enabled=false\n')
    assert load_credentials(path) == ({}, {})


def test_certificate_identity_defaults_to_cn(tmp_path):
    path = _write(tmp_path,
        'credential.cert.cn=partner-cn\ncredential.cert.role=partner_service\n')
    _, certs = load_credentials(path)
    assert certs['partner-cn'].identity == 'partner-cn'
