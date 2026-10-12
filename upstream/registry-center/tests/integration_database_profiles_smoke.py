# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: Apache-2.0
"""Real launcher, HTTP/verified HTTPS and SQLite profile/selector regressions.

Run: python tests/integration_database_profiles_smoke.py
Uses only generated temporary configuration, certificates and data.
"""
import json
import os
from pathlib import Path
import sqlite3
import ssl
import subprocess
import sys
import tempfile
import time

import httpx

from integration_oauth_smoke import REPO, configure, free_port, override_config


def run():
    parent = Path(tempfile.mkdtemp(prefix='registry-database-profile-smoke-'))
    results = []
    cases = [('file', 'SQLITE', 'relative'),
             ('dotenv', '  Sqlite  ', 'memory'),
             ('process', '  SQLITE  ', 'absolute')]
    for https in (False, True):
        for source, mode, target in cases:
            root = parent / f'{"https" if https else "http"}-{source}'
            port = free_port()
            configure(root, port, free_port(), free_port(), False, 'synthetic-secret')
            override_config(root, {'enable_https': str(https).lower(), 'integration.enabled': 'false'})
            directory = root / 'etc/conf'
            for name in ('server.conf.example', 'persistence.conf.example'):
                (directory / name).write_bytes((REPO / 'etc/conf' / name).read_bytes())
            disk = root / 'selected.db'
            path = ':memory:' if target == 'memory' else ('selected.db' if target == 'relative' else str(disk))
            (directory / 'db/sqlite.json').write_text(json.dumps({'path': path}), encoding='utf-8')
            (directory / 'persistence.conf').write_text(
                'persistence.mode=' + (mode if source == 'file' else 'file') + '\n', encoding='utf-8')
            env = {k: v for k, v in os.environ.items()
                   if not k.startswith(('REGISTRY_', 'DB_', 'SQLITE_', 'LLM_'))
                   and k not in ('DATABASE_CONFIG_DIR', 'PERSISTENCE_MODE')}
            env.update(PYTHONPATH=str(REPO), PYTHONUNBUFFERED='1',
                       LLM_CONFIG_FILE=str(root / 'absent-models.yaml'))
            if source == 'dotenv':
                (root / '.env').write_text('PERSISTENCE_MODE="' + mode + '"\nSQLITE_PATH=:memory:\n', encoding='utf-8')
            elif source == 'process':
                env.update(REGISTRY_PERSISTENCE_MODE=mode, REGISTRY_SQLITE_PATH=path)
            originals = {p: p.read_bytes() for p in directory.rglob('*') if p.is_file()}
            context = ssl.create_default_context(cafile=str(root / 'ca.cer'))
            url = f'{"https://localhost" if https else "http://127.0.0.1"}:{port}/rest/v1/registry-center'
            checks = []
            def expect(response, status):
                assert response.status_code == status, (source, target, response.status_code, response.text)
                checks.append(status)
                return response
            with (root / 'service.log').open('w', encoding='utf-8') as log:
                proc = subprocess.Popen([sys.executable, str(REPO / 'tests/integration_oauth_smoke.py'),
                    '--serve', str(root)], cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT)
                try:
                    with httpx.Client(verify=context, trust_env=False, timeout=5,
                                      headers={'X-SSL-Client-DN': 'CN=profile-smoke-owner'}) as client:
                        deadline = time.monotonic() + 40
                        while time.monotonic() < deadline:
                            if proc.poll() is not None:
                                raise RuntimeError('Startup failed: ' + str(root / 'service.log'))
                            try:
                                response = client.get(url + '/agent-cards')
                                if response.status_code == 200:
                                    break
                            except httpx.HTTPError:
                                pass
                            time.sleep(0.1)
                        else:
                            raise RuntimeError('Startup timed out: ' + str(root / 'service.log'))
                        expect(response, 200)
                        card = {'name': 'ProfileProbe', 'provider': {'organization': 'ProbeOrg', 'url': 'https://example.org'},
                            'description': 'profile smoke', 'version': '1.0.0', 'capabilities': {'streaming': False},
                            'defaultInputModes': ['text/plain'], 'defaultOutputModes': ['text/plain'], 'skills': []}
                        endpoint = url + '/agent-cards/ProbeOrg/ProfileProbe'
                        expect(client.post(url + '/agent-cards', json={'agentCards': [card]}), 201)
                        response = expect(client.get(endpoint), 200)
                        assert 'ProfileProbe' in response.text
                        expect(client.get(url + '/agent-cards', params={'organization': 'ProbeOrg'}), 200)
                        card['description'] = 'updated profile smoke'
                        expect(client.put(endpoint, json={'agentCards': [card]}), 200)
                        assert 'updated profile smoke' in expect(client.get(endpoint), 200).text
                        if target != 'memory':
                            assert disk.exists(), 'Selected SQLite profile was ignored'
                            with sqlite3.connect(disk) as conn:
                                assert conn.execute('SELECT COUNT(*) FROM agent_card').fetchone()[0] == 1
                        expect(client.delete(endpoint), 200)
                        assert expect(client.get(endpoint), 200).json() == {'agentCards': []}
                        assert not (root / 'data/agents.db').exists(), 'Default database was silently selected'
                        if target == 'memory':
                            assert not disk.exists() and not (root / ':memory:').exists()
                        assert all(p.read_bytes() == data for p, data in originals.items())
                        results.append({'https': https, 'source': source, 'target': target,
                                        'http_statuses': checks, 'configuration_unchanged': True})
                finally:
                    if proc.poll() is None:
                        proc.terminate()
                    try:
                        proc.wait(timeout=12)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=5)
    (parent / 'observations.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
    print('ARTIFACT_ROOT=' + str(parent))
    print(f'PASS {len(results)} real-launcher scenarios; {sum(len(r["http_statuses"]) for r in results)} HTTP assertions; '
          'verified HTTPS, SQLite read/write/update/delete, correct profile selection and memory semantics')


if __name__ == '__main__':
    run()
