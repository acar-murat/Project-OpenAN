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

"""Pluggable-handler mechanism (BaseHandler / HandlerRegistry / InterfaceType).

``common.custom`` intentionally stays free of orchestration imports: it only
provides the extension mechanism. The bundled business handlers (file-mode
defaults and the database-backed implementations) live in
``orchestrate.handlers``, which registers them on import.
"""

from common.custom.default_handle import BaseHandler, HandlerRegistry
from common.custom.interface_type import InterfaceType

__all__ = ["BaseHandler", "HandlerRegistry", "InterfaceType"]
