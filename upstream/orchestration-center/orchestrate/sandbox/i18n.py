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

"""Resource-file backed messages for sandbox reports."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

_LOCALE_DIR = Path(__file__).parent / "locales"


class _SafeFormatDict(dict[str, Any]):
    def __missing__(self, key: str) -> str:
        return f"{{{key}}}"


def normalize_language(lang: str | None) -> str:
    value = str(lang or "zh").lower()
    return "zh" if value.startswith("zh") else "en"


def _lookup(resource: dict[str, Any], key: str) -> str | None:
    value: Any = resource
    for part in key.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value if isinstance(value, str) else None


@lru_cache(maxsize=8)
def _load_language(language: str) -> dict[str, Any]:
    path = _LOCALE_DIR / f"{language}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def translate(lang: str | None, key: str, **params: Any) -> str:
    """Return a resource message with safe named interpolation."""
    language = normalize_language(lang)
    template = _lookup(_load_language(language), key)
    if template is None:
        template = _lookup(_load_language("en"), key)
    if template is None:
        return key
    if params:
        return template.format_map(_SafeFormatDict(**params))
    return template
