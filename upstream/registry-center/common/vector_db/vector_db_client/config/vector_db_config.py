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
from typing import Dict

from common.util.connection_profiles import load_connection_config


class VectorDBType(Enum):
    Milvus = 'milvus'

def convert_vectordb_type(vectordb_type:str)->VectorDBType:
    for member in VectorDBType:
        if member.value == vectordb_type:
            return member
    raise ValueError("Unsupported vector database type")

class VectorDBConfig:
    vectordb_type:VectorDBType
    description:str
    uri:str
    version:str

    def __init__(self,vectordb_type:str,config:dict):
        self.vectordb_type = convert_vectordb_type(vectordb_type)
        self.description = config['description']
        self.uri = config['uri']
        self.version = config['version']
        self.token = config.get('token', '')

def get_vectordb_config() -> Dict[str, VectorDBConfig]:
    config = load_connection_config("milvus")
    return {"milvus": VectorDBConfig("milvus", config)}

def get_vectordb_config_by_type(vectordb_type: VectorDBType) -> VectorDBConfig:
    # No import-time file read: a disabled vector index needs no connection.
    return get_vectordb_config().get(vectordb_type.value)
