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

import re
from datetime import UTC, datetime

from loguru import logger

from samples.agents.negotiation_base_agent import NegotiationBaseAgentExecutor

SPN_DOMAIN_PROMPT = """
You are an SPN Domain Agent simulator for City1 (Yuedong (Eastern Guangdong)) OMC.
You receive a private-line fault diagnosis task for the Yuedong (Eastern Guangdong) area.
Based on the received task, simulate a diagnosis result.

IMPORTANT: Yuedong (Eastern Guangdong) side has a FAULT. Your response must include:

1. 诊断结果类型: 诊断成功
2. 诊断结果详细信息: 粤东地市OMC诊断结果 - 端口Down, 光功率-28dBm(低于阈值), 存在故障
3. 修复方案: 更换粤东侧OMC端口光模块, 恢复端口Down状态。此修复方案需要人工授权后执行。
   修复方案字段: needs_authorization=true, risk_level=medium
4. 故障根因列表:
   - 故障根因名称: 粤东侧OMC端口光模块故障
   - 详细描述: 客户A粤东-粤西间专线中断, 粤东OMC告警端口Down, 光功率-28dBm低于正常阈值
   - 修复建议: 更换粤东侧OMC端口光模块, 需要人工授权后执行
   - 资源对象标识: port-yuedong-omc-01
   - 资源对象类型: 端口
   - 资源对象名称: 粤东OMC端口01
   - 详细位置: 粤东地市OMC机房

Format your response in Chinese as a structured diagnosis report.

Task content: {task}
"""

RECOVERY_PROMPT = """
你是SPN领域粤东OMC抢通执行专家。用一句话报告抢通成功结果，提及粤东OMC端口恢复Up、专线业务恢复。中文。

诊断信息：
{diagnosis}
"""


class SpnDomainAgentExecutor(NegotiationBaseAgentExecutor):

    def __init__(self) -> None:
        super().__init__(
            agent_prompt_template=SPN_DOMAIN_PROMPT,
            expected_task_object="P781-珠江新城-PTN7900-23-TPA1EG24-17(cvlan=100)",
        )

    def _execute_task(self, user_input: str, task_id: str = None, context_id: str = None) -> str:
        """Return diagnosis through Task-T and publish recovery only via Notification-T."""
        diagnosis = super()._execute_task(user_input, task_id, context_id)
        self._self_trigger_recovery(diagnosis, user_input, task_id)
        return diagnosis

    def _self_trigger_recovery(
        self,
        diagnosis_result: str,
        task_input: str,
        task_id: str | None,
    ) -> None:
        """Check authorization whitelist and execute recovery if authorized.

        Mirrors Java's selfTriggerRecovery: checks the pre-positioned
        Authorization-T whitelist policy, executes recovery if the fault
        matches the whitelist, and pushes the result via Notification-T.
        """
        policy = self.get_authorization_policy()
        in_whitelist = (
            policy is not None
            and policy != ""
            and ("业务抢通" in policy or "光模块" in policy or "授权" in policy)
        )
        port = self._extract_value(task_input, "接入端口名称")
        event_id = self._extract_value(task_input, "OSS侧事件流水号")
        if in_whitelist:
            logger.info("[SPN-Domain-Agent] Fault in whitelist, self-triggering recovery")
            recovery_result = self._llm_recovery(diagnosis_result)
            logger.info(
                f"[SPN-Domain-Agent] Recovery result reported via Notification-T: {recovery_result}"
            )
            result = "成功"
            failure_reason = ""
            authorized = "是"
        else:
            logger.info("[SPN-Domain-Agent] Fault not in whitelist, refusing recovery")
            recovery_result = "操作不在白名单内，拒绝执行抢通。"
            result = "失败"
            failure_reason = recovery_result
            authorized = "否"
        self.push_notification_result({
            "业务抢通方案执行状态": "已结束",
            "投诉诊断任务流水号": task_id or "unknown-task",
            "OSS侧事件流水号": event_id or "unknown-event",
            "接入端口名称": port or "unknown-port",
            "是否已授权OMC自动抢通": authorized,
            "业务抢通方案名称": "光模块更换及端口恢复",
            "业务抢通方案详情": recovery_result,
            "业务抢通方案执行结束时间": datetime.now(UTC).isoformat(),
            "业务抢通方案执行结果": result,
            "业务抢通方案执行失败原因": failure_reason,
        })

    @staticmethod
    def _extract_value(task_input: str, label: str) -> str:
        match = re.search(rf"{re.escape(label)}[：:]\s*[\"“]?([^；\n\"”]+)", task_input)
        return match.group(1).strip() if match else ""

    def _llm_recovery(self, diagnosis: str) -> str:
        """Generate recovery result via LLM."""
        prompt = RECOVERY_PROMPT.format(diagnosis=diagnosis)
        try:
            _, result = self.llm.ask_llm(prompt)
            if result:
                return result
        except Exception as e:
            logger.warning(f"[SPN-Domain-Agent] LLM recovery failed: {e}")
        return "粤东OMC端口光模块已更换，端口恢复Up，专线业务恢复正常。"
