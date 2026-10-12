// Copyright (c) 2026 Huawei Technologies Co., Ltd.
// All Rights Reserved.
//
// SPDX-License-Identifier: Apache-2.0
//
//    Licensed under the Apache License, Version 2.0 (the "License"); you may
//    use this file except in compliance with the License. You may obtain a
//    copy of the License at
//
//         http://www.apache.org/licenses/LICENSE-2.0
//
//    Unless required by applicable law or agreed to in writing, software
//    distributed under the License is distributed on an "AS IS" BASIS,
//    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
//    See the License for the specific language governing permissions and
//    limitations under the License.

// Polling hook with visibility awareness: pauses while the tab is hidden and
// refreshes immediately on focus. Changing `intervalMs` only re-arms the
// timer — it never triggers an extra fetch (guards against feedback loops
// with push-triggered refreshes).

import { useCallback, useEffect, useRef, useState } from 'react'

export function useHealthPolling(fetcher, intervalMs = 5000) {
    const [data, setData] = useState(null)
    const [error, setError] = useState(null)
    const [loading, setLoading] = useState(true)
    const [lastUpdated, setLastUpdated] = useState(null)
    const fetcherRef = useRef(fetcher)
    fetcherRef.current = fetcher

    const refresh = useCallback(async () => {
        try {
            const result = await fetcherRef.current()
            setData(result)
            setError(null)
        } catch (e) {
            setError(e)
        } finally {
            setLoading(false)
            setLastUpdated(Date.now())
        }
    }, [])

    // Initial fetch.
    useEffect(() => {
        refresh()
    }, [refresh])

    // Interval timer only — no fetch on re-arm.
    useEffect(() => {
        const timer = setInterval(() => {
            if (document.visibilityState === 'visible') refresh()
        }, intervalMs)
        return () => clearInterval(timer)
    }, [intervalMs, refresh])

    // Immediate refresh when the tab regains focus.
    useEffect(() => {
        const onVisibility = () => {
            if (document.visibilityState === 'visible') refresh()
        }
        document.addEventListener('visibilitychange', onVisibility)
        return () => document.removeEventListener('visibilitychange', onVisibility)
    }, [refresh])

    return { data, error, loading, lastUpdated, refresh }
}
