// Copyright (c) 2026 Huawei Technologies Co., Ltd.
// All Rights Reserved.
//
// SPDX-License-Identifier: Apache-2.0

import React, {act} from 'react';
import {createRoot} from 'react-dom/client';
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {ErrorBoundaryImpl} from './index.jsx';

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const Broken = () => {
    throw new Error('');
};

let shouldThrow = true;
const Recoverable = () => {
    if (shouldThrow) throw new Error('');
    return <div>recovered</div>;
};

describe('error boundary translations', () => {
    let container;
    let root;

    beforeEach(() => {
        shouldThrow = true;
        container = document.createElement('div');
        document.body.appendChild(container);
        root = createRoot(container);
        vi.spyOn(console, 'error').mockImplementation(() => {});
    });

    afterEach(() => {
        act(() => root.unmount());
        container.remove();
        vi.restoreAllMocks();
    });

    it('renders translated fallback labels and resets on retry', () => {
        const t = (key) => ({
            'error_boundary.title': '发生错误',
            'error_boundary.message': '该区域发生了意外错误。',
            'error_boundary.try_again': '重试',
        })[key];

        act(() => root.render(
            <ErrorBoundaryImpl t={t}>
                <Recoverable/>
            </ErrorBoundaryImpl>,
        ));

        expect(container.textContent).toContain('发生错误');
        expect(container.textContent).toContain('该区域发生了意外错误。');
        expect(container.textContent).toContain('重试');

        shouldThrow = false;
        const retry = [...container.querySelectorAll('button')]
            .find((button) => button.textContent.includes('重试'));
        act(() => retry.click());
        expect(container.textContent).toBe('recovered');
    });

    it('prefers a supplied fallback', () => {
        act(() => root.render(
            <ErrorBoundaryImpl t={(key) => key} fallback={<div>custom fallback</div>}>
                <Broken/>
            </ErrorBoundaryImpl>,
        ));

        expect(container.textContent).toBe('custom fallback');
    });
});
