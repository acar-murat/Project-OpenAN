// Copyright (c) 2026 Huawei Technologies Co., Ltd.
// All Rights Reserved.
//
// SPDX-License-Identifier: Apache-2.0
//
//    Licensed under the Apache License, Version 2.0 (the "License"); you may
//    not use this file except in compliance with the License. You may obtain
//    a copy of the License at
//
//         http://www.apache.org/licenses/LICENSE-2.0
//
//    Unless required by applicable law or agreed to in writing, software
//    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
//    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
//    License for the specific language governing permissions and limitations
//    under the License.
import { describe, expect, it } from 'vitest';
import {
    getNegotiationPayload,
    getRequestPayload,
    getResponsePayload,
} from './a2atEvents';

const TASK_T = 'https://projects.tmforum.org/a2aproject/telecommunication/extensions/Task-T/v1';
const NEGOTIATION_T = 'https://projects.tmforum.org/a2aproject/telecommunication/extensions/Negotiation-T/v1';

describe('a2at event adapters', () => {
    it('prefers Task-T extension content over TextPart in agent requests', () => {
        const payload = getRequestPayload({
            agent: 'SPN Domain Agent City1',
            content: {
                parts: [{ text: 'execute diagnosis' }],
                metadata: {
                    [TASK_T]: '## Task Object\nP781-port',
                    templateUri: 'Task-T/network-layer/private-line-complaint/v1',
                },
                extensions: [TASK_T],
            },
        });

        expect(payload.text).toContain('## Task Object');
        expect(payload.metadata[TASK_T]).toContain('P781-port');
        expect(payload.hasA2atContent).toBe(true);
    });

    it('collects A2A-T content from received messages in agent responses', () => {
        const payload = getResponsePayload({
            agent: 'SPN Domain Agent City1',
            response: '',
            received_messages: [{
                task_metadata: {
                    [TASK_T]: 'diagnosis result',
                    templateUri: 'Task-T/network-layer/private-line-complaint/v1',
                },
                artifacts: [],
            }],
        });

        expect(payload.text).toBe('diagnosis result');
        expect(payload.metadata[TASK_T]).toBe('diagnosis result');
        expect(payload.hasA2atContent).toBe(true);
    });

    it('adapts Negotiation-T request and resolved events', () => {
        const request = getNegotiationPayload({
            type: 'negotiation_request',
            data: {
                agent: 'SPN Domain Agent City1',
                request: {
                    received: {
                        task_metadata: {
                            [NEGOTIATION_T]: 'Please provide the access port',
                            negotiationContext: { id: 'n-1', round: 1, maxRounds: 3 },
                        },
                    },
                },
            },
        });
        const resolved = getNegotiationPayload({
            type: 'negotiation_resolved',
            data: {
                agent: 'SPN Domain Agent City1',
                reply: {
                    content: {
                        parts: [{ text: 'host TextPart' }],
                        metadata: {
                            [NEGOTIATION_T]: 'Accept: access port supplied',
                            negotiationContext: { id: 'n-1', round: 1, maxRounds: 3 },
                        },
                    },
                },
            },
        });

        expect(request.text).toBe('Please provide the access port');
        expect(request.context.id).toBe('n-1');
        expect(resolved.text).toContain('access port supplied');
        expect(resolved.context.id).toBe('n-1');
    });
});
