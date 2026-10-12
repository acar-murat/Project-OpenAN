// Copyright (c) 2026 Huawei Technologies Co., Ltd.
// All Rights Reserved.
//
// SPDX-License-Identifier: Apache-2.0

import {createInstance} from 'i18next';
import {beforeEach, describe, expect, it} from 'vitest';
import {PLUGIN_I18N_NAMESPACE, registerPluginI18n} from './plugin-i18n.js';

describe('plugin i18n registration', () => {
    let i18n;

    beforeEach(async () => {
        i18n = createInstance();
        await i18n.init({
            lng: 'en',
            fallbackLng: 'en',
            resources: {
                en: {translation: {common: {confirm: 'Portal confirm'}}},
                zh: {translation: {common: {confirm: 'Portal 确认'}}},
            },
        });
    });

    it('registers both languages in an isolated namespace', () => {
        expect(registerPluginI18n(i18n)).toBe(true);

        expect(i18n.t('common.confirm')).toBe('Portal confirm');
        expect(i18n.t('common.confirm', {ns: PLUGIN_I18N_NAMESPACE})).toBe('Confirm');
        expect(i18n.hasResourceBundle('en', PLUGIN_I18N_NAMESPACE)).toBe(true);
        expect(i18n.hasResourceBundle('zh', PLUGIN_I18N_NAMESPACE)).toBe(true);
    });

    it('does not overwrite an existing plugin bundle when mounted again', () => {
        i18n.addResourceBundle('en', PLUGIN_I18N_NAMESPACE, {common: {confirm: 'Customized'}}, true, true);

        registerPluginI18n(i18n);

        expect(i18n.t('common.confirm', {ns: PLUGIN_I18N_NAMESPACE})).toBe('Customized');
    });

    it('registers resources independently for a new i18n instance', async () => {
        const anotherInstance = createInstance();
        await anotherInstance.init({lng: 'zh'});

        registerPluginI18n(i18n);
        expect(registerPluginI18n(anotherInstance)).toBe(true);
        expect(anotherInstance.hasResourceBundle('zh', PLUGIN_I18N_NAMESPACE)).toBe(true);
    });
});
