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

"""Async semaphore utilities for FastAPI endpoint concurrency control."""

from contextlib import asynccontextmanager
from typing import AsyncIterator

import anyio
from fastapi import HTTPException

@asynccontextmanager
async def try_acquire_semaphore(semaphore: anyio.Semaphore, busy_detail: str = "Server is busy") -> AsyncIterator[None]:
    """Acquire a semaphore with non-blocking semantics, raising 503 if busy.

    Usage::

        async with try_acquire_semaphore(my_semaphore):
            # ... do work ...
    """
    acquired = False
    try:
        semaphore.acquire_nowait()
        acquired = True
        yield
    except anyio.WouldBlock:
        raise HTTPException(status_code=503, detail=busy_detail)
    finally:
        if acquired:
            semaphore.release()
