// Copyright (c) 2026 Huawei Technologies Co., Ltd.
// All Rights Reserved.
//
// SPDX-License-Identifier: Apache-2.0

import React, {act} from 'react';
import {createRoot} from 'react-dom/client';
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import Header from './index.jsx';

vi.mock('../setting/index.jsx', () => ({default: () => null}));
vi.mock('../password_change/index.jsx', () => ({
    default: ({isOpen}) => isOpen ? <div data-testid="password-modal">password modal</div> : null,
}));

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

describe('standalone header account actions', () => {
    let container;
    let root;

    beforeEach(() => {
        container = document.createElement('div');
        document.body.appendChild(container);
        root = createRoot(container);
    });

    afterEach(() => {
        act(() => root.unmount());
        container.remove();
    });

    const renderHeader = (overrides = {}) => {
        const props = {
            currentTab: 'orchestration',
            onTabChange: vi.fn(),
            isDark: false,
            setIsDark: vi.fn(),
            lang: 'en',
            onLangChange: vi.fn(),
            t: (key) => key,
            ...overrides,
        };
        act(() => root.render(<Header {...props}/>));
        return props;
    };

    it('shows the current user and invokes logout in authenticated standalone mode', () => {
        const props = renderHeader({onLogout: vi.fn(), currentUser: 'alice'});

        expect(container.textContent).toContain('alice');
        const logout = [...container.querySelectorAll('button')]
            .find((button) => button.textContent.includes('login.logout'));
        act(() => logout.click());
        expect(props.onLogout).toHaveBeenCalledOnce();
    });

    it('opens the password change dialog', () => {
        renderHeader({onLogout: vi.fn(), currentUser: 'alice'});

        const changePassword = container.querySelector('[aria-label="login.change_password"]');
        act(() => changePassword.click());
        expect(container.querySelector('[data-testid="password-modal"]')).not.toBeNull();
    });

    it('hides account actions when authentication is disabled', () => {
        renderHeader();

        expect(container.textContent).not.toContain('login.logout');
        expect(container.querySelector('[aria-label="login.change_password"]')).toBeNull();
    });
});
