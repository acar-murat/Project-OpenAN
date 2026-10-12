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
from unittest.mock import patch, MagicMock
import common.util.conf_util as conf_util_module
from common.util.conf_util import get_conf_singleton, load_conf_as_dict, load_conf_object
from common.util.conf_obj import ConfObj


class TestConfUtilLazyHolder:

    def setup_method(self):
        # Reset the lazy singleton before each test
        conf_util_module._conf_singleton_obj = None

    def test_get_conf_singleton_returns_conf_obj(self):
        obj = get_conf_singleton()
        assert isinstance(obj, ConfObj)

    def test_get_conf_singleton_caches_result(self):
        obj1 = get_conf_singleton()
        obj2 = get_conf_singleton()
        assert obj1 is obj2

    def test_get_conf_singleton_returns_conf_obj(self):
        obj = conf_util_module.get_conf_singleton()
        assert isinstance(obj, ConfObj)

    def test_module_getattr_raises_for_unknown_attr(self):
        with pytest.raises(AttributeError, match="has no attribute"):
            conf_util_module.nonexistent_attribute

    def test_module_getattr_caches_with_singleton(self):
        obj1 = conf_util_module.conf_singleton_obj
        obj2 = conf_util_module.conf_singleton_obj
        assert obj1 is obj2

    def test_conf_singleton_obj_initial_value_is_none(self):
        # Module-level variable conf_singleton_obj is set to None,
        # but get_conf_singleton() still returns a valid ConfObj
        assert conf_util_module._conf_singleton_obj is None
        obj = conf_util_module.get_conf_singleton()
        assert isinstance(obj, ConfObj)


class TestLoadConfAsDict:

    def test_loads_valid_config_file(self, tmp_path):
        config_file = tmp_path / "test.conf"
        config_file.write_text("ip=0.0.0.0\nport=8080\n")
        result = load_conf_as_dict(str(config_file))
        assert "ip" in result
        assert result["ip"] == "0.0.0.0"

    def test_returns_empty_dict_for_nonexistent_file(self):
        result = load_conf_as_dict("/nonexistent/file.conf")
        assert isinstance(result, dict)


class TestLoadConfObject:

    def test_returns_conf_obj_from_dict(self, tmp_path):
        config_file = tmp_path / "test.conf"
        config_file.write_text("ip=10.0.0.1\nport=9000\n")
        obj = load_conf_object(str(config_file))
        assert isinstance(obj, ConfObj)
        assert obj.ip == "10.0.0.1"
