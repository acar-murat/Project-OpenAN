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

from samples.agents.negotiation_base_agent import NegotiationBaseAgentExecutor

RAN_AGENT_PROMPT = """
You are a Radio Access Network (RAN) Agent simulator in the telecommunications field.
Based on the received task, simulate a focused response using details from the task description. Keep the response directly tied to the task scope.

Task content: {task}
"""


_CONFLICT_MARKERS_ZH = ("节能", "SLA", "冲突")
_CONFLICT_MARKERS_EN = ("energy-saving", "sla", "conflict")


def _is_conflict_scenario(task_text: str) -> bool:
    if not task_text:
        return False
    if all(marker in task_text for marker in _CONFLICT_MARKERS_ZH):
        return True
    lower = task_text.lower()
    has_energy = (
        "energy-saving" in lower or "energy saving" in lower or "energy_save" in lower
    )
    return has_energy and all(m in lower for m in ("sla", "conflict"))


class RanAgentExecutor(NegotiationBaseAgentExecutor):

    def __init__(self) -> None:
        super().__init__(agent_prompt_template=RAN_AGENT_PROMPT)

    async def _handle_task(self, context, metadata):
        user_input = context.get_user_input()
        if _is_conflict_scenario(user_input):
            return await self._request_negotiation(
                context,
                {"原始任务": user_input},
                ("SLA授权方案",),
            )
        return await super()._handle_task(context, metadata)

    def _negotiation_item_description(self, name: str) -> str:
        if name == "SLA授权方案":
            return "请提供兼顾节能目标与直播业务SLA保障的授权方案"
        return super()._negotiation_item_description(name)
