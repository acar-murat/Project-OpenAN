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
Tag handler tests

Tests the tag handler classes for UDS internal service:
- SetTagsHandler
- TagCreateHandler
- TagDeleteHandler
- TagUpdateHandler
- TagGetHandler
- TagListHandler
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from a2a.types import AgentCard

from agent_registry.internal.handlers.set_tags_handler import SetTagsHandler
from agent_registry.internal.handlers.tag_handler import (
    TagCreateHandler, TagDeleteHandler, TagUpdateHandler,
    TagGetHandler, TagListHandler
)
from agent_registry.model.tag import Tag


def create_mock_agent(name, organization):
    """Helper to create mock agent"""
    agent = Mock(spec=AgentCard)
    agent.name = name
    agent.provider = Mock()
    agent.provider.organization = organization
    agent.description = f"{name} description"
    return agent


def create_mock_tag(tag_id, name):
    """Helper to create mock tag entity"""
    tag = Tag(tag_id=tag_id, name=name)
    return tag


class TestSetTagsHandler:
    """Test SetTagsHandler"""

    @pytest.fixture
    def handler(self):
        return SetTagsHandler()

    @pytest.fixture
    def mock_registry(self):
        registry = Mock()
        registry.find_by_key = Mock(return_value=Mock(name="test_agent"))
        registry.get_tag_by_name = Mock(return_value=create_mock_tag("tag1", "production"))
        registry.update_agent_tags = Mock(return_value=True)
        registry.get_agent_tags = Mock(return_value=["production", "v1.0"])
        return registry

    @pytest.fixture
    def mock_config(self):
        return Mock()

    def test_handle_set_tags_success(self, handler, mock_registry, mock_config):
        params = {
            "agent_name": "test_agent",
            "organization": "test_org",
            "tags": ["production"]
        }

        result = handler.handle(params, mock_registry, mock_config)

        assert result["success"] is True
        assert result["message"] == "Tags set successfully"
        assert result["data"]["tag"] == ["production", "v1.0"]
        mock_registry.update_agent_tags.assert_called_once()

    def test_handle_set_tags_missing_params(self, handler, mock_registry, mock_config):
        params = {"tags": ["production"]}

        result = handler.handle(params, mock_registry, mock_config)

        assert result["success"] is False
        assert "Missing required params" in result["error"]

    def test_handle_set_tags_agent_not_found(self, handler, mock_registry, mock_config):
        params = {
            "agent_name": "unknown_agent",
            "organization": "test_org",
            "tags": ["production"]
        }

        mock_registry.find_by_key.return_value = None

        result = handler.handle(params, mock_registry, mock_config)

        assert result["success"] is False
        assert "not found" in result["error"].lower()

    def test_handle_set_tags_invalid_type(self, handler, mock_registry, mock_config):
        params = {
            "agent_name": "test_agent",
            "organization": "test_org",
            "tags": "not_a_list"
        }

        result = handler.handle(params, mock_registry, mock_config)

        assert result["success"] is False
        assert "Invalid param type" in result["error"]

    def test_handle_set_tags_exceed_limit(self, handler, mock_registry, mock_config):
        params = {
            "agent_name": "test_agent",
            "organization": "test_org",
            "tags": ["tag1", "tag2", "tag3", "tag4", "tag5", "tag6", "tag7", "tag8", "tag9", "tag10", "tag11"]
        }

        result = handler.handle(params, mock_registry, mock_config)

        assert result["success"] is False
        assert "exceeds maximum" in result["message"]

    def test_handle_set_tags_nonexistent_tag(self, handler, mock_registry, mock_config):
        params = {
            "agent_name": "test_agent",
            "organization": "test_org",
            "tags": ["nonexistent"]
        }

        mock_registry.get_tag_by_name.return_value = None

        result = handler.handle(params, mock_registry, mock_config)

        assert result["success"] is False
        assert "not found in tag library" in result["message"]


class TestTagCreateHandler:
    """Test TagCreateHandler"""

    @pytest.fixture
    def handler(self):
        return TagCreateHandler()

    @pytest.fixture
    def mock_registry(self):
        registry = Mock()
        registry.create_tag = Mock(return_value=create_mock_tag("test_id", "test_tag"))
        return registry

    @pytest.fixture
    def mock_config(self):
        return Mock()

    def test_handle_create_tag_success(self, handler, mock_registry, mock_config):
        params = {"name": "new_tag"}

        result = handler.handle(params, mock_registry, mock_config)

        assert result["success"] is True
        assert result["data"]["name"] == "test_tag"
        assert "created successfully" in result["message"]

    def test_handle_create_tag_missing_name(self, handler, mock_registry, mock_config):
        params = {}

        result = handler.handle(params, mock_registry, mock_config)

        assert result["success"] is False
        assert "Missing required parameter" in result["error"]

    def test_handle_create_tag_duplicate(self, handler, mock_registry, mock_config):
        params = {"name": "existing_tag"}
        mock_registry.create_tag.return_value = None

        result = handler.handle(params, mock_registry, mock_config)

        assert result["success"] is False
        assert "Failed to create tag" in result["error"]


class TestTagGetHandler:
    """Test TagGetHandler"""

    @pytest.fixture
    def handler(self):
        return TagGetHandler()

    @pytest.fixture
    def mock_registry(self):
        registry = Mock()
        registry.get_tag = Mock(return_value=create_mock_tag("test_id", "test_tag"))
        registry.get_tag_by_name = Mock(return_value=create_mock_tag("test_id", "test_tag"))
        return registry

    @pytest.fixture
    def mock_config(self):
        return Mock()

    def test_handle_get_tag_by_id(self, handler, mock_registry, mock_config):
        params = {"tag_id": "test_id"}

        result = handler.handle(params, mock_registry, mock_config)

        assert result["success"] is True
        assert result["data"]["tag_id"] == "test_id"
        assert result["data"]["name"] == "test_tag"

    def test_handle_get_tag_by_name(self, handler, mock_registry, mock_config):
        params = {"name": "test_tag"}

        result = handler.handle(params, mock_registry, mock_config)

        assert result["success"] is True
        assert result["data"]["tag_id"] == "test_id"

    def test_handle_get_tag_missing_params(self, handler, mock_registry, mock_config):
        params = {}

        result = handler.handle(params, mock_registry, mock_config)

        assert result["success"] is False
        assert "Missing required parameter" in result["error"]

    def test_handle_get_tag_not_found(self, handler, mock_registry, mock_config):
        params = {"tag_id": "nonexistent"}
        mock_registry.get_tag.return_value = None

        result = handler.handle(params, mock_registry, mock_config)

        assert result["success"] is False
        assert "not found" in result["error"].lower()


class TestTagUpdateHandler:
    """Test TagUpdateHandler"""

    @pytest.fixture
    def handler(self):
        return TagUpdateHandler()

    @pytest.fixture
    def mock_registry(self):
        registry = Mock()
        registry.get_tag = Mock(return_value=create_mock_tag("test_id", "old_name"))
        registry.update_tag = Mock(return_value=True)
        return registry

    @pytest.fixture
    def mock_config(self):
        return Mock()

    def test_handle_update_tag_success(self, handler, mock_registry, mock_config):
        mock_registry.get_tag.return_value = create_mock_tag("test_id", "new_name")
        params = {"tag_id": "test_id", "name": "new_name"}

        result = handler.handle(params, mock_registry, mock_config)

        assert result["success"] is True
        assert "updated successfully" in result["message"]

    def test_handle_update_tag_missing_params(self, handler, mock_registry, mock_config):
        params = {"tag_id": "test_id"}

        result = handler.handle(params, mock_registry, mock_config)

        assert result["success"] is False
        assert "Missing required parameters" in result["error"]

    def test_handle_update_tag_failed(self, handler, mock_registry, mock_config):
        params = {"tag_id": "test_id", "name": "new_name"}
        mock_registry.update_tag.return_value = False

        result = handler.handle(params, mock_registry, mock_config)

        assert result["success"] is False
        assert "Failed to update tag" in result["error"]


class TestTagDeleteHandler:
    """Test TagDeleteHandler"""

    @pytest.fixture
    def handler(self):
        return TagDeleteHandler()

    @pytest.fixture
    def mock_registry(self):
        registry = Mock()
        registry.get_tag = Mock(return_value=create_mock_tag("test_id", "test_tag"))
        registry.find_agents_by_tag = Mock(return_value=[])
        registry.delete_tag = Mock(return_value=True)
        return registry

    @pytest.fixture
    def mock_config(self):
        return Mock()

    def test_handle_delete_tag_success(self, handler, mock_registry, mock_config):
        params = {"tag_id": "test_id"}

        result = handler.handle(params, mock_registry, mock_config)

        assert result["success"] is True
        assert "deleted successfully" in result["message"]

    def test_handle_delete_tag_missing_param(self, handler, mock_registry, mock_config):
        params = {}

        result = handler.handle(params, mock_registry, mock_config)

        assert result["success"] is False
        assert "Missing required parameter" in result["error"]

    def test_handle_delete_tag_not_found(self, handler, mock_registry, mock_config):
        params = {"tag_id": "nonexistent"}
        mock_registry.get_tag.return_value = None

        result = handler.handle(params, mock_registry, mock_config)

        assert result["success"] is False
        assert "not found" in result["error"].lower()

    def test_handle_delete_tag_in_use(self, handler, mock_registry, mock_config):
        params = {"tag_id": "test_id"}
        mock_agent = create_mock_agent("agent1", "org1")
        mock_registry.find_agents_by_tag.return_value = [mock_agent]

        result = handler.handle(params, mock_registry, mock_config)

        assert result["success"] is False
        assert "used by" in result["message"]


class TestTagListHandler:
    """Test TagListHandler"""

    @pytest.fixture
    def handler(self):
        return TagListHandler()

    @pytest.fixture
    def mock_registry(self):
        registry = Mock()
        registry.list_tags = Mock(return_value=[
            create_mock_tag("id1", "tag1"),
            create_mock_tag("id2", "tag2"),
        ])
        return registry

    @pytest.fixture
    def mock_config(self):
        return Mock()

    def test_handle_list_tags_success(self, handler, mock_registry, mock_config):
        params = {}

        result = handler.handle(params, mock_registry, mock_config)

        assert result["success"] is True
        assert result["data"]["count"] == 2
        assert len(result["data"]["tags"]) == 2
        assert result["data"]["tags"][0]["name"] == "tag1"

    def test_handle_list_tags_empty(self, handler, mock_registry, mock_config):
        params = {}
        mock_registry.list_tags.return_value = []

        result = handler.handle(params, mock_registry, mock_config)

        assert result["success"] is True
        assert result["data"]["count"] == 0
        assert result["data"]["tags"] == []


class TestTagHandlerIntegration:
    """Integration tests for tag handlers"""

    @pytest.fixture
    def mock_registry(self):
        registry = Mock()
        registry.find_by_key = Mock(return_value=Mock(name="test_agent"))
        registry.get_tag_by_name = Mock(return_value=create_mock_tag("tag_id_1", "production"))
        registry.update_agent_tags = Mock(return_value=True)
        registry.get_agent_tags = Mock(return_value=["production"])
        registry.create_tag = Mock(return_value=create_mock_tag("tag_id_1", "production"))
        registry.get_tag = Mock(return_value=create_mock_tag("tag_id_1", "production"))
        registry.delete_tag = Mock(return_value=True)
        registry.find_agents_by_tag = Mock(return_value=[])
        registry.list_tags = Mock(return_value=[create_mock_tag("tag_id_1", "production")])
        return registry

    @pytest.fixture
    def mock_config(self):
        return Mock()

    def test_create_tag_then_assign_to_agent(self, mock_registry, mock_config):
        """Test creating a tag and then assigning it to an agent"""
        create_handler = TagCreateHandler()
        set_handler = SetTagsHandler()

        create_result = create_handler.handle(
            {"name": "production"}, mock_registry, mock_config
        )
        assert create_result["success"] is True

        set_result = set_handler.handle(
            {"agent_name": "test_agent", "organization": "test_org", "tags": ["production"]},
            mock_registry, mock_config
        )
        assert set_result["success"] is True

    def test_delete_tag_when_not_in_use(self, mock_registry, mock_config):
        """Test deleting a tag that is not assigned to any agent"""
        delete_handler = TagDeleteHandler()

        result = delete_handler.handle(
            {"tag_id": "tag_id_1"}, mock_registry, mock_config
        )
        assert result["success"] is True
