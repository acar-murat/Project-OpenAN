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
const EXTENSION_URI_PATTERN = /telecommunication\/extensions\/(Task|Negotiation|Authorization|Notification)-T\/v1/i;
const A2AT_METADATA_KEYS = new Set(['templateUri', 'negotiationContext']);

const asArray = (value) => (Array.isArray(value) ? value : value ? [value] : []);

export const isA2atExtensionKey = (key) => (
    typeof key === 'string' && (EXTENSION_URI_PATTERN.test(key) || A2AT_METADATA_KEYS.has(key))
);

export const getExtensionLabel = (key) => {
    const match = String(key).match(/extensions\/([^/]+(?:\/[^/]+)*)$/i);
    return match?.[1] || key;
};

const collectSources = (sources, seen = new WeakSet()) => {
    const result = [];
    for (const source of asArray(sources)) {
        if (!source || typeof source !== 'object' || seen.has(source)) continue;
        seen.add(source);
        result.push(source);
        result.push(...collectSources(Object.values(source), seen));
    }
    return result;
};

export function getA2atMetadata(...sources) {
    const metadata = {};
    for (const source of collectSources(sources)) {
        const candidates = [source.metadata, source.task_metadata];
        for (const candidate of candidates) {
            if (!candidate || typeof candidate !== 'object') continue;
            for (const [key, value] of Object.entries(candidate)) {
                if (!isA2atExtensionKey(key) || value === null || value === undefined) continue;
                if (!(key in metadata)) metadata[key] = value;
            }
        }
    }
    return metadata;
}

export function getPartsText(payload) {
    const parts = payload?.parts;
    if (!Array.isArray(parts)) return '';
    return parts
        .map(part => {
            if (typeof part === 'string') return part;
            if (typeof part?.text === 'string') return part.text;
            if (part?.data && typeof part.data === 'object') return JSON.stringify(part.data, null, 2);
            return '';
        })
        .filter(Boolean)
        .join('\n\n');
}

export function getReceivedMessages(data) {
    const sources = [data?.response, data];
    for (const source of sources) {
        if (Array.isArray(source?.received_messages)) return source.received_messages;
    }
    return [];
}

export function getReceivedMessageText(message) {
    const artifacts = Array.isArray(message?.artifacts) ? message.artifacts : [];
    const artifactText = artifacts
        .map(artifact => getPartsText(artifact))
        .filter(Boolean)
        .join('\n\n');
    const messageText = getPartsText(message?.message);
    return [artifactText, messageText].filter(Boolean).join('\n\n');
}

function getExtensionText(metadata) {
    return Object.entries(metadata || {})
        .filter(([key, value]) => EXTENSION_URI_PATTERN.test(key) && typeof value === 'string')
        .map(([, value]) => value)
        .join('\n\n');
}

export function getA2atContentText(payload) {
    if (!payload) return '';
    if (typeof payload === 'string') return payload;
    const extensionText = getExtensionText(getA2atMetadata(payload));
    return extensionText || getPartsText(payload);
}

export function getRequestPayload(data) {
    const legacy = data?.request;
    const content = data?.content ?? (legacy && typeof legacy === 'object' ? legacy : { text: legacy });
    return {
        content,
        metadata: getA2atMetadata(content),
        text: getA2atContentText(content),
        hasA2atContent: Boolean(getExtensionText(getA2atMetadata(content))),
    };
}

export function getResponsePayload(data) {
    const response = typeof data?.response === 'string'
        ? { text: data.response }
        : data?.response || {};
    const received = getReceivedMessages(data);
    const metadata = getA2atMetadata(response, ...received);
    const extensionText = getExtensionText(metadata);
    const receivedText = received.map(getReceivedMessageText).filter(Boolean).join('\n\n');
    return {
        content: response,
        received,
        metadata,
        text: extensionText || receivedText || response.text || '',
        hasA2atContent: Boolean(extensionText),
    };
}

export function getNegotiationPayload(event) {
    const data = event?.data || {};
    const type = event?.type || '';
    if (type === 'negotiation_request') {
        const received = data.request?.received;
        return {
            kind: 'request',
            metadata: getA2atMetadata(received),
            text: getA2atContentText(received)
                || data.request?.concern
                || data.request?.clarification
                || '',
            context: data.request?.received?.task_metadata?.negotiationContext,
            error: '',
        };
    }
    if (type === 'negotiation_resolved') {
        const reply = data.reply || {};
        return {
            kind: 'resolved',
            metadata: getA2atMetadata(reply.content),
            text: getA2atContentText(reply.content)
                || reply.clarification
                || '',
            context: reply.content?.metadata?.negotiationContext,
            error: '',
        };
    }
    return {
        kind: 'failed',
        metadata: {},
        text: data.error || '',
        context: null,
        error: data.error || '',
    };
}
