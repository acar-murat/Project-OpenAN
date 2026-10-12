// Copyright (c) 2026 Huawei Technologies Co., Ltd.
// All Rights Reserved.
//
// SPDX-License-Identifier: Apache-2.0

import {describe, expect, it} from 'vitest';
import {defaultGateway} from '@/service/api.js';
import {getInitialServerConfig} from './config.js';

const storageWith = (value) => ({
    getItem: () => value,
});

describe('server connection defaults', () => {
    it('uses the gateway strategy when no preference has been saved', () => {
        expect(getInitialServerConfig(storageWith(null))).toMatchObject({
            mode: 'nginx',
            nginxUrl: defaultGateway,
        });
    });

    it('falls back to the gateway strategy for malformed saved data', () => {
        expect(getInitialServerConfig(storageWith('{broken'))).toMatchObject({
            mode: 'nginx',
            nginxUrl: defaultGateway,
        });
    });

    it('preserves an explicit direct connection preference', () => {
        const saved = JSON.stringify({mode: 'ip', ip: '192.0.2.10', port: '5001'});

        expect(getInitialServerConfig(storageWith(saved))).toMatchObject({
            mode: 'ip',
            ip: '192.0.2.10',
            port: '5001',
        });
    });
});
