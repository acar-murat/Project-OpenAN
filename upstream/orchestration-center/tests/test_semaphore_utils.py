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
import pytest
import anyio
from fastapi import HTTPException
from common.util.semaphore_utils import try_acquire_semaphore


class TestTryAcquireSemaphore:

    @pytest.mark.asyncio
    async def test_acquire_success(self):
        sem = anyio.Semaphore(2)
        async with try_acquire_semaphore(sem):
            pass

    @pytest.mark.asyncio
    async def test_acquire_then_release(self):
        sem = anyio.Semaphore(2)
        assert sem.value == 2
        async with try_acquire_semaphore(sem):
            assert sem.value == 1
        assert sem.value == 2

    @pytest.mark.asyncio
    async def test_busy_raises_503(self):
        sem = anyio.Semaphore(1)
        # Acquire semaphore to fill it, then try to acquire again
        sem.acquire_nowait()
        with pytest.raises(HTTPException) as exc_info:
            async with try_acquire_semaphore(sem):
                pass
        assert exc_info.value.status_code == 503

    @pytest.mark.asyncio
    async def test_busy_custom_detail(self):
        sem = anyio.Semaphore(1)
        sem.acquire_nowait()
        with pytest.raises(HTTPException) as exc_info:
            async with try_acquire_semaphore(sem, busy_detail="Custom busy message"):
                pass
        assert exc_info.value.detail == "Custom busy message"

    @pytest.mark.asyncio
    async def test_semaphore_zero_capacity(self):
        sem = anyio.Semaphore(0)
        with pytest.raises(HTTPException) as exc_info:
            async with try_acquire_semaphore(sem):
                pass
        assert exc_info.value.status_code == 503
