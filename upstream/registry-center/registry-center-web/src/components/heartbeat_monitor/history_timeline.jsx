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
import { History } from 'lucide-react'
import { STATUS_STYLES } from './status_badge.jsx'

const HistoryTimeline = ({ history }) => {
    const { t } = useTranslation()
    if (!history || history.length === 0) {
        return (
            <div className="h-40 flex items-center justify-center text-zinc-400 text-sm font-bold">
                {t('heartbeat.no_history')}
            </div>
        )
    }
    return (
        <div className="p-5">
            {history.map((entry, idx) => {
                const prevStyle = STATUS_STYLES[entry.previous_health_status] || STATUS_STYLES.unknown
                const newStyle = STATUS_STYLES[entry.health_status] || STATUS_STYLES.unknown
                const d = new Date(entry.changed_at)
                const time = Number.isNaN(d.getTime()) ? entry.changed_at : d.toLocaleString()
                return (
                    <div key={idx} className="flex gap-4">
                        <div className="flex flex-col items-center">
                            <div className={`w-2.5 h-2.5 rounded-full mt-1.5 ${newStyle.dot} ${idx === 0 ? newStyle.glow : ''}`} />
                            {idx < history.length - 1 && (
                                <div className="w-px flex-1 bg-zinc-200 dark:bg-zinc-800" />
                            )}
                        </div>
                        <div className={`pb-6 ${idx === history.length - 1 ? 'pb-0' : ''}`}>
                            <div className="flex items-center gap-2 flex-wrap">
                                <span className={`px-2 py-0.5 rounded-md text-sm font-black uppercase border ${prevStyle.badge}`}>
                                    {t(`heartbeat.status_${entry.previous_health_status || 'unknown'}`)}
                                </span>
                                <span className="text-zinc-400 dark:text-zinc-600 font-black">→</span>
                                <span className={`px-2 py-0.5 rounded-md text-sm font-black uppercase border ${newStyle.badge}`}>
                                    {t(`heartbeat.status_${entry.health_status || 'unknown'}`)}
                                </span>
                            </div>
                            <div className="text-sm font-bold text-zinc-400 dark:text-zinc-500 mt-1.5">
                                {time}
                            </div>
                        </div>
                    </div>
                )
            })}
            <div className="flex items-center gap-2 mt-4 text-sm font-black uppercase tracking-wider text-zinc-400 dark:text-zinc-500">
                <History size={12} />
                {t('heartbeat.timeline_hint')}
            </div>
        </div>
    )
}

export default HistoryTimeline
