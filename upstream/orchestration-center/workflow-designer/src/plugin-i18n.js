// Copyright (c) 2026 Huawei Technologies Co., Ltd.
// All Rights Reserved.
//
// SPDX-License-Identifier: Apache-2.0

import en from '@/locales/en.json';
import zh from '@/locales/zh.json';

export const PLUGIN_I18N_NAMESPACE = 'orchestration-center';

const resources = {en, zh};

export function registerPluginI18n(i18n) {
    if (!i18n || typeof i18n.addResourceBundle !== 'function') {
        return false;
    }

    for (const [language, bundle] of Object.entries(resources)) {
        i18n.addResourceBundle(language, PLUGIN_I18N_NAMESPACE, bundle, true, false);
    }
    return true;
}
