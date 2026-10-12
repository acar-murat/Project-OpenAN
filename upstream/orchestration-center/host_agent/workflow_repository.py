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

from __future__ import annotations

from typing import Any

from workflow_engine import load_psop, search_psop


class OrchestrationWorkflowRepository:
    """HTTP adapter for workflows owned by the Orchestration Center."""

    def __init__(self, *, orch_url: str, ssl_verify: bool = False) -> None:
        self._orch_url = orch_url.rstrip("/")
        self._ssl_verify = ssl_verify

    async def find(self, intent: str) -> Any:
        results = await search_psop(
            self._orch_url,
            intent,
            top_n=3,
            ssl_verify=self._ssl_verify,
        )
        if not results:
            raise RuntimeError("No matching workflow found")
        return await self.get(results[0].workflow_id)

    async def get(self, psop_id: str) -> Any:
        workflow = await load_psop(
            self._orch_url,
            psop_id,
            ssl_verify=self._ssl_verify,
        )
        return workflow
