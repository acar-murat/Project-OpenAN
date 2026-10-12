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
Tag storage tests

Tests the tag storage functionality in FileStorage:
- Tags initialization
- Tags CRUD operations
- Tags persistence
- Tags file handling
"""

import pytest
import json
import os
import tempfile
from a2a.types import AgentCard

from agent_registry.persistence.file_storage import FileStorage


def create_sample_agent(name="test_agent", org="test_org"):
    agent_data = {
        "name": name,
        "provider": {
            "organization": org,
            "url": "https://test.com"
        },
        "description": "Test agent",
        "version": "1.0.0",
        "skills": []
    }
    return AgentCard(**agent_data)


class TestFileStorageTags:
    """Test FileStorage tags functionality"""

    @pytest.fixture
    def temp_dir(self):
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)

    @pytest.fixture
    def file_path(self, temp_dir):
        return os.path.join(temp_dir, "agentcard.json")

    @pytest.fixture
    def tags_file(self, temp_dir):
        return os.path.join(temp_dir, "tags.json")

    @pytest.fixture
    def metadata_file(self, temp_dir):
        return os.path.join(temp_dir, "agentregistry.json")

    @pytest.fixture
    def storage(self, file_path, metadata_file, tags_file):
        return FileStorage(file_path, metadata_file, tags_file)

    @pytest.fixture
    def sample_agent(self):
        return create_sample_agent()

    # ========== Tags Initialization Tests ==========

    def test_tags_initialized_empty(self, storage):
        assert storage._agent_tags_map == {}

    def test_tags_file_created_on_init(self, storage, tags_file):
        assert storage.tags_file == tags_file

    # ========== Tags CRUD Tests ==========

    def test_create_agent_initializes_empty_tags(self, storage, sample_agent):
        storage.create(sample_agent)
        key = (sample_agent.name, sample_agent.provider.organization)
        assert key in storage._agent_tags_map
        assert storage._agent_tags_map[key] == []

    def test_get_tags_for_existing_agent(self, storage, sample_agent):
        storage.create(sample_agent)
        tags = storage.get_agent_tags(sample_agent.name, sample_agent.provider.organization)
        assert tags == []

    def test_get_tags_for_nonexistent_agent(self, storage):
        tags = storage.get_agent_tags("unknown", "unknown_org")
        assert tags == []

    def test_update_tags_full_replacement(self, storage, sample_agent):
        storage.create(sample_agent)
        new_tags = ["production", "v1.0"]
        result = storage.update_agent_tags(
            sample_agent.name, sample_agent.provider.organization, new_tags)
        assert result is True
        tags = storage.get_agent_tags(sample_agent.name, sample_agent.provider.organization)
        assert tags == new_tags

    def test_update_tags_merge_mode(self, storage, sample_agent):
        storage.create(sample_agent)
        storage.update_agent_tags(sample_agent.name, sample_agent.provider.organization, ["tag1"])
        current = storage.get_agent_tags(sample_agent.name, sample_agent.provider.organization)
        merged = list(set(current + ["tag2", "tag3"]))
        result = storage.update_agent_tags(
            sample_agent.name, sample_agent.provider.organization, merged)
        assert result is True
        tags = storage.get_agent_tags(sample_agent.name, sample_agent.provider.organization)
        assert "tag1" in tags
        assert "tag2" in tags
        assert "tag3" in tags

    def test_update_tags_remove_mode(self, storage, sample_agent):
        storage.create(sample_agent)
        storage.update_agent_tags(sample_agent.name, sample_agent.provider.organization,
                                  ["tag1", "tag2", "tag3"])
        current = storage.get_agent_tags(sample_agent.name, sample_agent.provider.organization)
        remaining = [t for t in current if t not in ["tag2"]]
        result = storage.update_agent_tags(
            sample_agent.name, sample_agent.provider.organization, remaining)
        assert result is True
        tags = storage.get_agent_tags(sample_agent.name, sample_agent.provider.organization)
        assert tags == ["tag1", "tag3"]

    def test_update_tags_for_nonexistent_agent(self, storage):
        result = storage.update_agent_tags("unknown", "unknown_org", ["tag"])
        assert result is False

    def test_delete_agent_removes_tags(self, storage, sample_agent):
        storage.create(sample_agent)
        storage.update_agent_tags(sample_agent.name, sample_agent.provider.organization,
                                  ["tag1", "tag2"])
        storage.delete(sample_agent.name, sample_agent.provider.organization)
        key = (sample_agent.name, sample_agent.provider.organization)
        assert key not in storage._agent_tags_map

    # ========== Tags Persistence Tests ==========

    def test_tags_saved_to_file(self, storage, sample_agent, metadata_file):
        storage.create(sample_agent)
        tags = ["production", "v1.0", "chinese_label"]
        storage.update_agent_tags(sample_agent.name, sample_agent.provider.organization, tags)
        assert os.path.exists(metadata_file)
        with open(metadata_file, 'r', encoding='utf-8') as f:
            tags_data = json.load(f)
        assert len(tags_data) > 0
        found = False
        for entry in tags_data:
            if entry["agent_name"] == sample_agent.name and \
               entry["organization"] == sample_agent.provider.organization:
                assert entry["tags"] == tags
                found = True
                break
        assert found

    def test_tags_loaded_from_file(self, file_path, metadata_file, tags_file, sample_agent):
        storage1 = FileStorage(file_path, metadata_file, tags_file)
        storage1.create(sample_agent)
        tags = ["tag1", "tag2"]
        storage1.update_agent_tags(sample_agent.name, sample_agent.provider.organization, tags)
        storage2 = FileStorage(file_path, metadata_file, tags_file)
        loaded_tags = storage2.get_agent_tags(sample_agent.name, sample_agent.provider.organization)
        assert loaded_tags == tags

    def test_tags_persistence_after_multiple_operations(self, storage, sample_agent):
        storage.create(sample_agent)
        storage.update_agent_tags(sample_agent.name, sample_agent.provider.organization,
                                  ["tag1", "tag2"])
        current = storage.get_agent_tags(sample_agent.name, sample_agent.provider.organization)
        merged = list(set(current + ["tag3"]))
        storage.update_agent_tags(sample_agent.name, sample_agent.provider.organization, merged)
        current = storage.get_agent_tags(sample_agent.name, sample_agent.provider.organization)
        remaining = [t for t in current if t not in ["tag1"]]
        storage.update_agent_tags(sample_agent.name, sample_agent.provider.organization, remaining)
        storage2 = FileStorage(storage.file_path, storage.metadata_file, storage.tags_file)
        tags = storage2.get_agent_tags(sample_agent.name, sample_agent.provider.organization)
        assert set(tags) == {"tag2", "tag3"}

    # ========== Find by Tag Tests ==========

    def test_find_by_tag(self, storage):
        agent1 = create_sample_agent("agent1", "org1")
        agent2 = create_sample_agent("agent2", "org2")
        storage.create(agent1)
        storage.create(agent2)
        storage.update_agent_tags(agent1.name, agent1.provider.organization,
                                  ["production", "v1.0"])
        storage.update_agent_tags(agent2.name, agent2.provider.organization,
                                  ["production", "v2.0"])
        agents = storage.find_by_tag("production")
        assert len(agents) == 2
        agents_v1 = storage.find_by_tag("v1.0")
        assert len(agents_v1) == 1

    def test_find_by_tag_empty_result(self, storage, sample_agent):
        storage.create(sample_agent)
        storage.update_agent_tags(sample_agent.name, sample_agent.provider.organization, ["tag1"])
        agents = storage.find_by_tag("nonexistent_tag")
        assert agents == []

    # ========== Edge Cases Tests ==========

    def test_update_tags_duplicate_add(self, storage, sample_agent):
        storage.create(sample_agent)
        storage.update_agent_tags(sample_agent.name, sample_agent.provider.organization, ["tag1"])
        current = storage.get_agent_tags(sample_agent.name, sample_agent.provider.organization)
        merged = list(set(current + ["tag1", "tag2"]))
        storage.update_agent_tags(sample_agent.name, sample_agent.provider.organization, merged)
        tags = storage.get_agent_tags(sample_agent.name, sample_agent.provider.organization)
        assert tags.count("tag1") == 1
        assert "tag2" in tags

    def test_update_tags_remove_nonexistent(self, storage, sample_agent):
        storage.create(sample_agent)
        storage.update_agent_tags(sample_agent.name, sample_agent.provider.organization, ["tag1"])
        current = storage.get_agent_tags(sample_agent.name, sample_agent.provider.organization)
        remaining = [t for t in current if t not in ["tag2"]]
        storage.update_agent_tags(sample_agent.name, sample_agent.provider.organization, remaining)
        tags = storage.get_agent_tags(sample_agent.name, sample_agent.provider.organization)
        assert tags == ["tag1"]

    def test_tags_with_chinese_characters(self, storage, sample_agent):
        storage.create(sample_agent)
        chinese_tags = ["production_env", "test_label", "chinese_tag"]
        storage.update_agent_tags(sample_agent.name, sample_agent.provider.organization,
                                  chinese_tags)
        tags = storage.get_agent_tags(sample_agent.name, sample_agent.provider.organization)
        assert tags == chinese_tags

    def test_tags_with_dot_characters(self, storage, sample_agent):
        storage.create(sample_agent)
        dot_tags = ["v1.0", "v2.0.beta", "app.service"]
        storage.update_agent_tags(sample_agent.name, sample_agent.provider.organization, dot_tags)
        tags = storage.get_agent_tags(sample_agent.name, sample_agent.provider.organization)
        assert tags == dot_tags

    def test_clear_all_tags(self, storage, sample_agent):
        storage.create(sample_agent)
        storage.update_agent_tags(sample_agent.name, sample_agent.provider.organization,
                                  ["tag1", "tag2"])
        storage.update_agent_tags(sample_agent.name, sample_agent.provider.organization, [])
        tags = storage.get_agent_tags(sample_agent.name, sample_agent.provider.organization)
        assert tags == []


class TestFileStorageTagsFileFormat:
    """Test tags file format and structure"""

    @pytest.fixture
    def temp_dir(self):
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)

    def test_tags_file_format(self, temp_dir):
        file_path = os.path.join(temp_dir, "agentcard.json")
        metadata_file = os.path.join(temp_dir, "agentregistry.json")
        tags_file = os.path.join(temp_dir, "tags.json")
        storage = FileStorage(file_path, metadata_file, tags_file)
        agent = create_sample_agent()
        storage.create(agent)
        storage.update_agent_tags(agent.name, agent.provider.organization, ["tag1", "tag2"])
        with open(metadata_file, 'r', encoding='utf-8') as f:
            tags_data = json.load(f)
        assert isinstance(tags_data, list)
        entry = tags_data[0]
        assert "agent_name" in entry
        assert "organization" in entry
        assert "tags" in entry
        assert isinstance(entry["tags"], list)

    def test_tags_file_empty_initially(self, temp_dir):
        file_path = os.path.join(temp_dir, "agentcard.json")
        metadata_file = os.path.join(temp_dir, "agentregistry.json")
        tags_file = os.path.join(temp_dir, "tags.json")
        FileStorage(file_path, metadata_file, tags_file)
        assert not os.path.exists(tags_file) or os.path.getsize(tags_file) == 0
