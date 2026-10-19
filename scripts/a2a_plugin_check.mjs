#!/usr/bin/env node
/**
 * Runs HQ's A2A-T client plugin (a2a-client-connector) against our mock MAE and checks every
 * point of its contract (docs/henan-demo.md, "A2A-T plugin contract").
 *
 *   node scripts/a2a_plugin_check.mjs --plugin <path to the plugin's index.js> [--url http://127.0.0.1:8091/]
 *
 * The plugin bundle is HQ's and is not in this repository: pass the path of its index.js (or
 * dist/index.js). Needs Node >= 22.3 (the plugin uses process.getBuiltinModule) and a running
 * mock MAE (`python scripts/dev.py up mae`). The bundle is loaded the way the plugin's own
 * test-client.mjs loads it, and its tools are called directly: no NextAgent and no LLM.
 */
import { readFileSync } from 'node:fs';

const args = process.argv.slice(2);
const arg = (name, fallback) => {
  const i = args.indexOf(`--${name}`);
  return i >= 0 && args[i + 1] ? args[i + 1] : fallback;
};
const pluginPath = arg('plugin', process.env.A2A_PLUGIN_BUNDLE);
const agentUrl = arg('url', 'http://127.0.0.1:8091/');
if (!pluginPath) {
  console.error('usage: node scripts/a2a_plugin_check.mjs --plugin <plugin index.js> [--url <mock MAE base URL>]');
  process.exit(2);
}

function evaluateBundle(src) {
  const exports = new Map();
  let body = src.replace(/\r?\n\/\/# sourceMappingURL=.*$/u, '').replace(/\bexport\s*\{([^}]*)\}\s*;?/gu, (_s, list) => {
    for (const raw of list.split(',')) {
      const entry = raw.trim();
      if (!entry) continue;
      const m = /^([A-Za-z_$][\w$]*)(?:\s+as\s+([A-Za-z_$][\w$]*|default))?$/.exec(entry);
      if (m === null) throw new Error(`export entry invalid: ${entry}`);
      exports.set(m[2] ?? m[1], m[1]);
    }
    return '';
  });
  let ret = exports.get('default');
  if (ret === undefined) {
    body = body.replace(/\bexport\s+default\b/u, 'const __pluginDefault =');
    ret = '__pluginDefault';
  }
  return Function(`"use strict";\n${body}\n;return ${ret};`)();
}

let pass = 0;
let fail = 0;
const check = (name, ok, detail = '') => {
  if (ok) pass += 1;
  else fail += 1;
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${ok || !detail ? '' : `  -- ${detail}`}`);
};
const short = (value) => JSON.stringify(value)?.slice(0, 240);

process.env.A2A_AGENT_URL = agentUrl;
process.env.A2A_WAIT_MS ??= '15000';
const plugin = evaluateBundle(readFileSync(pluginPath, 'utf8'));
const provider = plugin.providers[0];
const descriptors = await provider.discovery.listAll();
const context = { toolDependencies: { httpClient: { fetch } } };
const invoke = async (id, input) => {
  const descriptor = descriptors.find((d) => d.capabilityId === id);
  const result = await provider.executor.invoke(descriptor, { arguments: input }, new AbortController().signal, context);
  return result.structuredPayload ?? {};
};
const artifactText = (r) => (r.artifacts ?? []).flatMap((a) => (a.parts ?? []).map((p) => p.text ?? '')).join('\n');
const optimisationResult = (r) => {
  for (const text of artifactText(r).split('\n')) {
    try {
      const value = JSON.parse(text);
      if (value?.serviceManagement?.RanOptimizationResult) return value.serviceManagement.RanOptimizationResult;
    } catch {
      // not JSON
    }
  }
  return undefined;
};
const origin = new URL(agentUrl).origin;

console.log(`A2A-T plugin contract check against ${agentUrl}\n`);

// 1. AgentCard at GET / without the version header.
const cardResponse = await fetch(`${origin}/`);
const card = await cardResponse.json().catch(() => ({}));
check('GET / returns the AgentCard without A2A-Version', cardResponse.ok && typeof card.name === 'string');
check('AgentCard has supportedInterfaces[0].url', /^https?:\/\//u.test(card.supportedInterfaces?.[0]?.url ?? ''));
const discover = await invoke('a2a_discover_agents', {});
check('a2a_discover_agents reads name, streaming and skills', discover.name === card.name && discover.streaming === true
  && (discover.skills ?? []).every((s) => s.id && s.name && s.description), short(discover));
const skillIds = (discover.skills ?? []).map((s) => s.id);
check('skills include energy-saving and ran-complaint-optimization',
  skillIds.includes('energy-saving') && skillIds.includes('ran-complaint-optimization'), skillIds.join(','));

// 2. A2A-Version is required on every other call.
for (const [method, path] of [['POST', '/message:send'], ['GET', '/ops/omc/status?issueId=x']]) {
  const r = await fetch(`${origin}${path}`, { method, headers: { 'Content-Type': 'application/json' },
    body: method === 'POST' ? '{"message":{"messageId":"m","role":"ROLE_USER","parts":[{"text":"x"}]}}' : undefined });
  const body = await r.json().catch(() => ({}));
  check(`${method} ${path.split('?')[0]} without A2A-Version is a 400 with an error body`,
    r.status === 400 && typeof body.error?.message === 'string', `HTTP ${r.status} ${short(body)}`);
}

// 3. SSE frames: id:N lines, task -> statusUpdate -> artifactUpdate -> terminal statusUpdate. The
// plugin's own mock also sets "final": true; A2A 1.0 has no such field, so we check that the
// plugin stops on the terminal state without it (the a2a_send_task checks below).
const streamResponse = await fetch(`${origin}/message:stream`, {
  method: 'POST', headers: { 'Content-Type': 'application/json', 'A2A-Version': '1.0' },
  body: JSON.stringify({ message: { messageId: 'sse-1', role: 'ROLE_USER', parts: [{ text: 'region: Zhengzhou' }],
    metadata: { skill: 'energy-saving' } } }),
});
const frames = (await streamResponse.text()).split('\n\n').filter((f) => f.trim());
const events = frames.map((f) => JSON.parse(f.split('\n').find((l) => l.startsWith('data:')).slice(5)));
check('message:stream frames are "id:N\\ndata:{json}"', frames.every((f, i) => f.startsWith(`id:${i + 1}\ndata:`)),
  frames[0]?.slice(0, 80));
check('stream order: task, statusUpdate, artifactUpdate, terminal statusUpdate',
  'task' in events[0] && events.some((e) => e.statusUpdate) && events.some((e) => e.artifactUpdate)
  && events.at(-1).statusUpdate?.status?.state === 'TASK_STATE_COMPLETED');

// 4. Energy saving through the plugin, streaming and blocking.
const energyStream = await invoke('a2a_send_task', { text: 'region: Zhengzhou', skillId: 'energy-saving', mode: 'stream' });
check('a2a_send_task (stream) energy saving completes with artifacts',
  energyStream.state === 'TASK_STATE_COMPLETED' && artifactText(energyStream).includes('IntentReport'), short(energyStream));
const energySend = await invoke('a2a_send_task', { text: '{"region": "Zhengzhou"}', mode: 'send' });
check('a2a_send_task (send) returns a terminal Task with artifacts[].parts[].text',
  energySend.state === 'TASK_STATE_COMPLETED' && artifactText(energySend).length > 0, short(energySend));
const getTask = await invoke('a2a_get_task', { taskId: energySend.taskId });
check('a2a_get_task follows up the task', getTask.stateClass === 'success', short(getTask));

// 5. INPUT_REQUIRED and the missing-parameter phrases.
const input = await invoke('a2a_send_task', { text: 'please save energy', skillId: 'energy-saving', mode: 'stream' });
check('energy saving without a region is INPUT_REQUIRED with a 请补充 message',
  input.state === 'TASK_STATE_INPUT_REQUIRED' && input.needsAction === 'input'
  && (input.agentMessages ?? []).some((m) => m.includes('请补充')), short(input));
const prose = await invoke('a2a_send_task', { text: 'the cell near the station is slow', mode: 'stream' });
check('pure prose fails with 未解析出任务参数 and needsUserInput', prose.needsUserInput === true
  && String(prose.error).includes('未解析出任务参数'), short(prose));
const noCgi = await invoke('a2a_send_task', { text: '{"problemType": "UP_LOW_THROUGHPUT"}', mode: 'send' });
check('missing objectId fails with 缺少必选参数 and needsUserInput', noCgi.needsUserInput === true
  && String(noCgi.error).includes('缺少必选参数'), short(noCgi));
const badCgi = await invoke('a2a_send_task', { text: 'objectId: cell-17\nproblemType: UP_LOW_THROUGHPUT', mode: 'stream' });
check('a non-CGI objectId fails with 必须是小区 CGI', badCgi.needsUserInput === true
  && String(badCgi.error).includes('必须是小区 CGI'), short(badCgi));
const badType = await invoke('a2a_send_task', { text: '{"objectId": "460-00-617089-1103", "problemType": "SLOW"}' });
check('an unknown problemType fails with 取值无效', badType.needsUserInput === true
  && String(badType.error).includes('取值无效'), short(badType));

// 6. Work orders: ledger entry with a result, ledger entry without one ("Exist"), and a new one.
const diagnosed = await invoke('a2a_query_result', { issueId: 'HA-XNLC-PY-20260908-09674481' });
check('a2a_query_result finds statuses and advices for a diagnosed work order',
  diagnosed.hasResult === true && diagnosed.statuses?.length > 0 && diagnosed.advices?.length > 0, short(diagnosed));
const pendingId = 'HN-ZZ-JS-20261015-00031752';
const pending = await invoke('a2a_query_result', { issueId: pendingId });
check('a2a_query_result is hasResult=false (empty arrays) before diagnosis',
  pending.hasResult === false && Array.isArray(pending.statuses) && pending.statuses.length === 0, short(pending));
const exist = await invoke('a2a_send_task', { text: JSON.stringify({ issueId: pendingId, objectId: '460-00-617089-1103',
  problemType: 'UP_LOW_THROUGHPUT' }), skillId: 'ran-complaint-optimization' });
const existResult = optimisationResult(exist);
check('known issueId returns serviceManagement.RanOptimizationResult with workOrderStatus Exist',
  exist.state === 'TASK_STATE_COMPLETED' && existResult?.workOrderStatus === 'Exist', short(exist));
const after = await invoke('a2a_query_result', { issueId: pendingId });
check('a2a_query_result has the result after diagnosis', after.hasResult === true, short(after));
const created = await invoke('a2a_send_task', { text: 'objectId: 460-00-617089-2201\nproblemType: WEAK_COVERAGE\nrat: NR' });
check('new work order from "key: value" lines is Created', optimisationResult(created)?.workOrderStatus === 'Created',
  short(created));

console.log(`\n${fail === 0 ? 'All' : fail} ${fail === 0 ? `${pass} checks passed` : `of ${pass + fail} checks failed`}`);
process.exit(fail === 0 ? 0 : 1);
