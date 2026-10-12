// Copyright (c) 2026 Huawei Technologies Co., Ltd.
// All Rights Reserved.
//
// SPDX-License-Identifier: Apache-2.0

import {defaultIp, defaultPort, defaultGateway, shouldDefaultToGateway} from '@/service/api.js';

export const getInitialServerConfig = (storage = localStorage) => {
    const autoMode = shouldDefaultToGateway() ? 'nginx' : 'ip';
    const defaults = {mode: autoMode, ip: defaultIp, port: defaultPort, nginxUrl: defaultGateway};
    const saved = storage.getItem('server_config');
    if (!saved) return defaults;

    try {
        const parsed = JSON.parse(saved);
        return {
            ...defaults,
            ...parsed,
            nginxUrl: parsed.nginxUrl || parsed.gatewayUrl || defaults.nginxUrl,
        };
    } catch {
        return defaults;
    }
};
