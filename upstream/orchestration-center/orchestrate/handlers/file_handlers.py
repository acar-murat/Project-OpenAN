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

"""File-mode storage handlers: thin adapters over the WorkflowStorage facade."""

from orchestrate.core.workflow_search_result import WorkflowSearchResult
from orchestrate.workflow_storage_instance import get_workflow_storage
from common.custom.default_handle import BaseHandler


class SavePsopHandler(BaseHandler):
    def handle(self, *args, **kwargs):
        return get_workflow_storage().save_psop(*args)


class GetAllPsopsHandler(BaseHandler):
    def handle(self, *args, **kwargs):
        results = []
        storage = get_workflow_storage()
        for wf_id in storage.list_psops():
            psop = storage.load_psop(wf_id)
            if psop:
                results.append(WorkflowSearchResult(
                    workflow_id=psop.id,
                    workflow_type="psop",
                    name=psop.name,
                    description=psop.description,
                    tags=psop.tags,
                    created_at=psop.created_at,
                    user_intent=psop.user_intent,
                    related_preflow=psop.related_preflow,
                ))
        return results


class GetPsopHandler(BaseHandler):
    def handle(self, *args, **kwargs):
        storage = get_workflow_storage()
        return storage.load_psop(*args)


class DeletePsopHandler(BaseHandler):
    def handle(self, *args, **kwargs):
        return get_workflow_storage().delete_psop(*args)


class SaveExecutionRecordHandler(BaseHandler):
    def handle(self, *args, **kwargs):
        return get_workflow_storage().save_execution_record(*args)


class ListExecutionRecordsHandler(BaseHandler):
    def handle(self, *args, **kwargs):
        return get_workflow_storage().list_execution_records()


class GetExecutionRecordHandler(BaseHandler):
    def handle(self, *args, **kwargs):
        return get_workflow_storage().load_execution_record(*args)


class DeleteExecutionRecordHandler(BaseHandler):
    def handle(self, *args, **kwargs):
        return get_workflow_storage().delete_execution_record(*args)
