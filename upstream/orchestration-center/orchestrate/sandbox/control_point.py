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

from workflow_engine import (
    MessageContent,
    NegotiationReply,
    RouteDecision,
    TaskResult,
)

from orchestrate.sandbox.i18n import translate


class SandboxControlPoint:
    """Generic sandbox policy; it never contains business-specific rules."""

    def __init__(
        self,
        *,
        orch_url: str | None = None,
        ssl_verify: bool = False,
        lang: str = "zh",
    ) -> None:
        del orch_url, ssl_verify
        self.lang = lang

    async def on_task(self, request):
        return MessageContent.text(translate(
            self.lang,
            "stub.task_content",
            step_name=request.step_name,
            instruction=request.instruction,
        ))

    async def on_self_task(self, request):
        result = translate(
            self.lang,
            "sandbox_control_point.self_task_result",
            step_name=request.step_name,
        )
        return TaskResult.succeeded((result,))

    async def on_route(self, request):
        return RouteDecision.allow(translate(
            self.lang,
            "sandbox_control_point.route_allowed",
        ))

    async def on_negotiation(self, request):
        return NegotiationReply.send(MessageContent.text(translate(
            self.lang,
            "stub.negotiation_completed",
        )))
