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
import pytest
from common.util.cipher_util import decrypt


class TestDecrypt:

    def test_decrypt_returns_bytes(self):
        result = decrypt("hello")
        assert isinstance(result, bytes)

    def test_decrypt_encodes_string(self):
        result = decrypt("test123")
        assert result == b"test123"

    def test_decrypt_empty_string(self):
        result = decrypt("")
        assert result == b""

    def test_decrypt_utf8_encoding(self):
        result = decrypt("abc")
        assert result.decode("utf-8") == "abc"
