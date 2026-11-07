import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { once } from 'node:events';
import { access, mkdtemp, writeFile, readFile, rm } from 'node:fs/promises';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawn } from 'node:child_process';
import { lintText, termTable, RULES } from './lint.mjs';

test('a typed orch command in the UI is flagged', () => {
  assert.ok(lintText('Try: orch relay send Home "Hello"').some(x => x.rule === 'cli-command'));
  assert.equal(lintText('Send one from the phone.').length, 0);
});

test('wording rules, boundaries, allowances, and purity', () => {
  for (const text of ['Connected over NetBird', 'Evidence', 'Recommended', 'undefined']) assert.ok(lintText(text).length, text);
  assert.deepEqual(lintText('Ticket Proof Suggested scheduled requestor'), []);
  assert.deepEqual(lintText('token', { allow: ['token'] }), []);
  assert.equal(lintText('type DELETE')[0].rule, 'typed-word');
  assert.equal(lintText('[object Object] {{ }}').length, 3);
  assert.deepEqual(lintText('Evidence'), lintText('Evidence'));
  assert.ok(RULES.length);
  assert.equal(termTable(['Ticket ticket', 'Proof']).Ticket, 2);
});

test('browser lane continues after failure and covers controls', { timeout: 19500 }, async t => {
  const { chromium } = await import('playwright');
  try { await access(chromium.executablePath()); } catch { t.skip('Chromium is not installed'); return; }
  const dir = await mkdtemp(fileURLToPath(new URL('./test-run-', import.meta.url)));
  t.after(() => rm(dir, { recursive: true, force: true }));
  const server = http.createServer((req, res) => {
    res.setHeader('Content-Type', 'text/html');
    res.end(`<!doctype html><html lang="en"><title>orch</title><body><nav><a href="#tickets">Tickets</a></nav><main><h1>Needs you</h1><button onclick="document.querySelector('h1').textContent='Saved'">Save</button><button>Untouched</button><button id="icon"><svg width="10" height="10"></svg></button><label>Name<input id="name"></label><div data-user-content>NetBird</div><div hidden>Evidence</div></main></body></html>`);
  });
  server.listen(0, '127.0.0.1'); await once(server, 'listening');
  t.after(() => { server.closeAllConnections(); server.close(); });
  const lane = { lane: 'A', base: 'local', steps: [
    { id: 'A01', page: 'home', actions: [{ do: 'goto', path: '/' }, { do: 'click', sel: 'text=Save', covers: 'home|button|Save' }, { do: 'expect_text', text: 'Saved' }] },
    { id: 'A02', page: 'home', actions: [{ do: 'expect_text', text: 'missing', timeout: 80 }] },
    { id: 'A03', page: 'home', actions: [{ do: 'click_all_census', page: 'home' }] },
  ] };
  const laneFile = join(dir, 'lane.json'), envFile = join(dir, 'env.json');
  await writeFile(laneFile, JSON.stringify(lane));
  await writeFile(envFile, JSON.stringify({ urls: { local: `http://127.0.0.1:${server.address().port}` } }));
  async function execute(out, extra = []) {
    const child = spawn(process.execPath, [fileURLToPath(new URL('./stepper.mjs', import.meta.url)), '--lane', laneFile, '--env', envFile, '--out', out, ...extra], { stdio: ['ignore', 'pipe', 'pipe'] });
    let stderr = ''; child.stderr.on('data', b => { stderr += b; });
    const timer = setTimeout(() => child.kill('SIGKILL'), 17000); timer.unref();
    t.after(() => child.kill());
    const [code] = await once(child, 'exit'); clearTimeout(timer);
    assert.equal(code, 0, stderr);
    return JSON.parse(await readFile(join(out, 'result.json'), 'utf8'));
  }
  const partial = await execute(join(dir, 'partial'), ['--only', 'A01']);
  assert.ok(partial.coverage.percent < 100);
  const result = await execute(join(dir, 'full'));
  assert.deepEqual(result.steps.map(s => s.status), ['pass', 'fail', 'pass']);
  assert.equal(result.coverage.percent, 100);
  assert.ok(result.steps[0].unnamed_controls.some(x => x.key.endsWith('|icon')));
  assert.deepEqual(result.steps[0].lint, []);
  for (const width of [1280, 720, 390]) {
    const shot = result.steps[0].shots.find(s => s.vp === width);
    assert.ok(shot); await access(join(dir, 'full', shot.file));
  }
  await assert.rejects(access(join(dir, 'full', 'trace.zip')), 'no trace unless STEPPER_TRACE is set (traces keep typed values)');
});
