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

"""
Integration access listener unit tests (task 2.1).

Covers the default-off gate and configuration parsing. The enabled-path
HTTPS smoke (real certs + client cert) is part of the end-to-end
acceptance checklist (task 8.2).
"""

from agent_registry.integration.listener import ThirdPartyAccessServer


class TestListenerGate:
    def test_disabled_by_default(self):
        server = ThirdPartyAccessServer({})
        assert server.enabled is False
        server.start()  # no-op: no thread, no socket
        assert server._thread is None

    def test_disabled_by_default_when_config_missing(self):
        server = ThirdPartyAccessServer()
        assert server.enabled is False

    def test_config_parsing(self):
        server = ThirdPartyAccessServer({
            'integration.enabled': 'true',
            'integration.ip': '0.0.0.0',
            'integration.port': '6001',
            'integration.client_cert': 'true',
        })
        assert server.enabled is True
        assert server.host == '0.0.0.0'
        assert server.port == 6001
        assert server.require_client_cert is True

    def test_explicit_disable_string(self):
        server = ThirdPartyAccessServer({'integration.enabled': 'false'})
        assert server.enabled is False

    def test_stop_before_start_is_noop(self):
        server = ThirdPartyAccessServer({})
        server.stop()  # must not raise
