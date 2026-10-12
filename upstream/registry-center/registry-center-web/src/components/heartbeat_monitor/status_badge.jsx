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

import { useTranslation } from 'react-i18next'

export const STATUS_STYLES = {
    healthy: {
        dot: 'bg-emerald-500',
        glow: 'shadow-[0_0_6px_#10b981]',
        badge: 'bg-emerald-50 dark:bg-emerald-900/20 text-emerald-700 dark:text-emerald-400 border-emerald-200 dark:border-emerald-800',
        bar: 'bg-emerald-500',
    },
    suspect: {
        dot: 'bg-amber-500',
        glow: 'shadow-[0_0_6px_#f59e0b]',
        badge: 'bg-amber-50 dark:bg-amber-900/20 text-amber-700 dark:text-amber-400 border-amber-200 dark:border-amber-800',
        bar: 'bg-amber-500',
    },
    offline: {
        dot: 'bg-rose-500',
        glow: 'shadow-[0_0_6px_#f43f5e]',
        badge: 'bg-rose-50 dark:bg-rose-900/20 text-rose-700 dark:text-rose-400 border-rose-200 dark:border-rose-800',
        bar: 'bg-rose-500',
    },
    unknown: {
        dot: 'bg-zinc-400',
        glow: '',
        badge: 'bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400 border-zinc-200 dark:border-zinc-700',
        bar: 'bg-zinc-400',
    },
}

const StatusBadge = ({ status, withLabel = true, pulse = false }) => {
    const { t } = useTranslation()
    const style = STATUS_STYLES[status] || STATUS_STYLES.unknown
    return (
        <span
            className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg border text-sm font-black uppercase tracking-wide ${style.badge}`}
        >
            <span
                className={`w-2 h-2 rounded-full ${style.dot} ${style.glow} ${pulse ? 'animate-pulse-soft' : ''}`}
            />
            {withLabel && t(`heartbeat.status_${status || 'unknown'}`)}
        </span>
    )
}

export default StatusBadge
