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
import { Activity, CheckCircle2, AlertTriangle, XCircle, Layers } from 'lucide-react'
import { STATUS_STYLES } from './status_badge.jsx'

const StatCards = ({ agents }) => {
    const { t } = useTranslation()
    const total = agents.length
    const counts = {
        healthy: agents.filter((a) => a.health_status === 'healthy').length,
        suspect: agents.filter((a) => a.health_status === 'suspect').length,
        offline: agents.filter((a) => a.health_status === 'offline').length,
    }
    const others = total - counts.healthy - counts.suspect - counts.offline

    const cards = [
        { key: 'total', label: t('heartbeat.stat_total'), value: total, icon: Layers, color: 'bg-blue-600', shadow: 'shadow-blue-500/30' },
        { key: 'healthy', label: t('heartbeat.status_healthy'), value: counts.healthy, icon: CheckCircle2, color: 'bg-emerald-500', shadow: 'shadow-emerald-500/30' },
        { key: 'suspect', label: t('heartbeat.status_suspect'), value: counts.suspect, icon: AlertTriangle, color: 'bg-amber-500', shadow: 'shadow-amber-500/30' },
        { key: 'offline', label: t('heartbeat.status_offline'), value: counts.offline, icon: XCircle, color: 'bg-rose-500', shadow: 'shadow-rose-500/30' },
    ]

    const segments = [
        { status: 'healthy', value: counts.healthy },
        { status: 'suspect', value: counts.suspect },
        { status: 'offline', value: counts.offline },
        { status: 'unknown', value: others },
    ].filter((s) => s.value > 0)

    return (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-4">
            {cards.map((card) => (
                <div
                    key={card.key}
                    className="p-5 rounded-2xl border bg-white dark:bg-zinc-900 border-zinc-100 dark:border-zinc-800 flex items-center justify-between animate-in fade-in duration-300"
                >
                    <div>
                        <div className="text-sm font-black uppercase tracking-wider text-zinc-400 dark:text-zinc-500">
                            {card.label}
                        </div>
                        <div className="text-3xl font-black text-zinc-900 dark:text-white mt-1 leading-none">
                            {card.value}
                        </div>
                    </div>
                    <div className={`p-3 rounded-xl text-white shadow-lg ${card.color} ${card.shadow}`}>
                        <card.icon size={22} />
                    </div>
                </div>
            ))}
            {total > 0 && (
                <div className="col-span-2 lg:col-span-4 p-4 rounded-2xl border bg-white dark:bg-zinc-900 border-zinc-100 dark:border-zinc-800 animate-in fade-in duration-300">
                    <div className="flex items-center gap-3 mb-3">
                        <Activity size={14} className="text-zinc-400" />
                        <span className="text-sm font-black uppercase tracking-wider text-zinc-400 dark:text-zinc-500">
                            {t('heartbeat.distribution')}
                        </span>
                    </div>
                    <div className="flex h-2.5 w-full rounded-full overflow-hidden bg-zinc-100 dark:bg-zinc-800">
                        {segments.map((seg) => (
                            <div
                                key={seg.status}
                                title={`${t(`heartbeat.status_${seg.status}`)}: ${seg.value}`}
                                style={{ width: `${(seg.value / total) * 100}%` }}
                                className={`${STATUS_STYLES[seg.status].bar} transition-all duration-500`}
                            />
                        ))}
                    </div>
                </div>
            )}
        </div>
    )
}

export default StatCards
