#!/usr/bin/env node
// Dashboard click-throughs: every dashboard feature done like a person in the real page, on a seeded demo workspace.
//
//   node workspace-addons/dashboard/clickthrough/run.cjs                  every click-through (CI: page-smoke)
//   node workspace-addons/dashboard/clickthrough/run.cjs --only home,checks   only these files (features/<name>.cjs)
//   node workspace-addons/dashboard/clickthrough/run.cjs --list           the features and who covers them, no browser
//   node workspace-addons/dashboard/clickthrough/run.cjs --out DIR        keep a picture of each click-through's end
//   node workspace-addons/dashboard/clickthrough/run.cjs --size 390x844   another window size (default 1280x900)
//
// Each click-through (features/*.cjs) does a thing, reloads the page, checks the result is still there, and fails on
// any console error or uncaught exception. The server is the real dashboard with working actions (server.py): a click
// runs this checkout's orch and writes real ticket files in a throw-away home under ~/.orch-test, started with
// `env -i` (HOME, USERPROFILE, ORCH_HOME there, ORCH_HOME_STRICT=1), so the orch of this computer is never touched.
// Chromium runs with --use-mock-keychain --password-store=basic (no keychain window).
//
// The runner records every action the page really sends and every page it shows. A click-through that claims a
// feature in `covers` but never did it fails; with no --only, a feature of the catalogue (catalogue.cjs) that no
// click-through did fails too, by name. Exit 0 = all passed.
'use strict';
const fs = require('node:fs');
const net = require('node:net');
const os = require('node:os');
const path = require('node:path');
const readline = require('node:readline');
const { spawn, execFileSync } = require('node:child_process');
const catalogue = require('./catalogue.cjs');

const REPO = path.resolve(__dirname, '..', '..', '..');
let SIZE = { width: 1280, height: 900 };
/** Add-ons of this checkout the demo home has installed (off until a click-through turns one on, see server.py):
 *  every orch the run starts sees the same ones. */
const ADDONS = ['focus', 'lessons', 'pull-requests', 'factory'];
const UV_RUN = ['uv', 'run', '-q', '--project', path.join(REPO, 'workspace'),
  ...ADDONS.flatMap(n => ['--with-editable', path.join(REPO, 'workspace-addons', n)])];
/** the env of every process of the run: the throw-away home only; ORCH_REPO = this checkout, so the add-ons
 *  above count as shipped and "the newest orch" is read from here, never from the internet */
const runEnv = dir => ({ HOME: dir, USERPROFILE: dir, ORCH_HOME: path.join(dir, 'orch'), ORCH_HOME_STRICT: '1',
  // the stand-in programs of server.py (agent tools, gh) first, for every orch the run starts, not only the server
  PATH: `${path.join(dir, 'bin')}${path.delimiter}${process.env.PATH}`, LANG: 'en_US.UTF-8', ORCH_REPO: REPO,
  UV_CACHE_DIR: process.env.UV_CACHE_DIR || path.join(os.homedir(), '.cache', 'uv') });
const envArgs = env => ['-i', ...Object.entries(env).map(([k, v]) => `${k}=${v}`)];

function args(argv) {
  const o = { only: null, out: null, list: false };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--list') o.list = true;
    else if (a === '--only') o.only = new Set(argv[++i].split(',').map(s => s.replace(/\.cjs$/, '')));
    else if (a === '--out') o.out = path.resolve(argv[++i]);
    else if (a === '--size') { const [w, h] = argv[++i].split('x').map(Number); SIZE = { width: w, height: h }; }
    else throw new Error(`unknown option ${a}`);
  }
  return o;
}

function playwright() {
  for (const p of [process.env.PW_DIR, path.join(os.homedir(), 'orch-dev', 'e2e', 'dashboard', 'node_modules')]) {
    if (p) try { return require(path.join(p, 'playwright')); } catch (e) { /* next */ }
  }
  try { return require('playwright'); } catch (e) { /* global */ }
  return require(path.join(execFileSync('npm', ['root', '-g'], { encoding: 'utf8' }).trim(), 'playwright'));
}

/** an answer that did the thing: 200, or 202 for what runs on by itself (Update) */
const ok = status => status >= 200 && status < 300;

const freePort = () => new Promise((ok, no) => {
  const s = net.createServer();
  s.once('error', no);
  s.listen(0, '127.0.0.1', () => { const p = s.address().port; s.close(() => ok(p)); });
});

/** The seeded server in its own throw-away home. Resolves {base, ids, token(), stop()}. */
async function serve() {
  const root = path.join(os.homedir(), '.orch-test');
  fs.mkdirSync(root, { recursive: true });
  const dir = fs.mkdtempSync(path.join(root, 'clickthrough-'));
  const port = await freePort();
  const env = runEnv(dir);
  const child = spawn('env', [...envArgs(env), ...UV_RUN, 'python', path.join(__dirname, 'server.py'), dir, String(port)],
    { cwd: REPO, stdio: ['pipe', 'pipe', 'pipe'] });
  let log = '';
  child.stderr.on('data', d => { log = (log + d).slice(-4000); });
  const lines = readline.createInterface({ input: child.stdout });
  const waiting = [], forgetting = [];
  let ready;
  const started = new Promise((ok, no) => {
    ready = ok;
    child.once('exit', c => no(new Error(`click-through server exited (${c}): ${log.slice(-800)}`)));
    setTimeout(() => no(new Error(`click-through server did not start in 4 minutes: ${log.slice(-800)}`)), 240000);
  });
  lines.on('line', l => {
    if (l.startsWith('ready ')) { const [, base, ...rest] = l.split(' '); ready({ base, ids: JSON.parse(rest.join(' ')) }); }
    else if (l.startsWith('token ') && waiting.length) waiting.shift()(l.slice(6).trim());
    else if (l === 'forgot update-info' && forgetting.length) forgetting.shift()();
  });
  const stop = () => {
    // first the workspace's own services (dashboard, add-on pages): they keep writing into .orch while it is removed
    for (const ws of fs.existsSync(dir) ? fs.readdirSync(dir) : []) {
      if (!fs.existsSync(path.join(dir, ws, '.orch'))) continue;
      try {
        execFileSync('env', [...envArgs(env), ...UV_RUN, 'python', '-I', '-m', 'orch', 'stop'],
          { cwd: path.join(dir, ws), stdio: 'ignore', timeout: 60000 });
      } catch (e) { /* nothing running */ }
    }
    try { child.stdin.end(); process.kill(child.pid); } catch (e) { /* gone */ }
    // a helper run the page started (its tmux and wrapper) outlives the server: stop every process that names this
    // run's own folder, and nothing else
    try {
      for (const l of execFileSync('ps', ['-ax', '-o', 'pid=,command='], { encoding: 'utf8', maxBuffer: 1 << 26 }).split('\n')) {
        const m = /^\s*(\d+)\s+(.*)$/.exec(l);
        if (m && m[2].includes(dir + path.sep) && Number(m[1]) !== process.pid) try { process.kill(Number(m[1])); } catch (e) { /* gone */ }
      }
    } catch (e) { /* no ps */ }
    // a process that was just stopped can still write a last file: retry instead of failing on ENOTEMPTY / EBUSY
    if (path.dirname(dir) === root && path.basename(dir).startsWith('clickthrough-')) {
      try { fs.rmSync(dir, { recursive: true, force: true, maxRetries: 10, retryDelay: 300 }); } catch (e) {
        console.error(`could not remove the throw-away folder ${dir}: ${e.code || e.message}`);
      }
    }
  };
  try {
    const { base, ids } = await started;
    const token = () => new Promise(ok => { waiting.push(ok); child.stdin.write('token\n'); });
    const forgetUpdateInfo = () => new Promise(ok => { forgetting.push(ok); child.stdin.write('forget-update-info\n'); });
    return { base, ids, dir, token, forgetUpdateInfo, stop, log: () => log };
  } catch (e) { stop(); throw e; }
}

/** A signed-in browser context: the page secret is in localStorage, the session cookie in the context. */
async function signIn(browser, srv) {
  const ctx = await browser.newContext({ viewport: SIZE });
  const page = await ctx.newPage();
  await page.goto(`${srv.base}/#launch=${await srv.token()}`);
  await page.waitForFunction(() => !!localStorage.getItem('orch_page_secret'), null, { timeout: 30000 });
  await page.waitForLoadState('load');
  await page.close();
  return ctx;
}

/** Record what the page does: ops sent (with their answer) and the router kinds it showed. */
function recorder(page, base) {
  const rec = { ops: [], pages: new Set(), errors: [], refusedOk: new Set(), failed: [] };
  page.on('response', r => { if (r.status() >= 400) rec.failed.push(`${r.status()} ${r.request().method()} ${r.url().replace(base, '')}`); });
  page.on('pageerror', e => rec.errors.push(`uncaught exception: ${String(e.message).slice(0, 300)}`));
  page.on('console', m => {
    if (m.type() !== 'error') return;
    const t = m.text();
    // Chromium logs every 4xx answer as a console error; an action a click-through expects to be refused is fine
    if (/Failed to load resource: the server responded with a status of 4\d\d/.test(t) && rec.ops.some(o => o.status >= 400 && rec.refusedOk.has(o.op))) return;
    // name the address of a failed load (Chromium's line does not)
    rec.errors.push(`console error: ${t.slice(0, 300)}${/Failed to load resource/.test(t) && rec.failed.length ? ` (${rec.failed.at(-1)})` : ''}`);
  });
  page.on('response', async r => {
    const req = r.request();
    if (req.method() !== 'POST' || !r.url().startsWith(base + '/api/act')) return;
    let op = req.headers()['x-orch-op'];
    if (!op) try { op = JSON.parse(req.postData() || '{}').op; } catch (e) { /* not JSON */ }
    const hit = { op, status: r.status(), text: '' };
    rec.ops.push(hit);  // before any await: the console line of a 4xx comes right after the answer
    if (!ok(r.status())) try { hit.text = (await r.text()).slice(0, 200); } catch (e) { /* gone */ }
  });
  return rec;
}

const PAGE_KIND = () => {
  // eslint-disable-next-line no-undef
  if (typeof route !== 'function') return null;
  // eslint-disable-next-line no-undef
  const r = route();
  return r.kind === 'settings' ? `settings/${r.tab}` : r.kind;
};

/** The helpers a click-through gets. */
function tools(page, srv, rec, shots = null) {
  const settle = async () => {
    await page.waitForFunction(() => document.querySelector('main') && !document.querySelector('main .sk-title'), null, { timeout: 20000 });
    await page.waitForTimeout(150);
    const k = await page.evaluate(PAGE_KIND);
    if (k) rec.pages.add(`page:${k}`);
  };
  const t = {
    page, ids: srv.ids, base: srv.base,
    /** the demo workspace folder (in the throw-away home) */
    workspace: path.join(srv.dir, 'Pilatus'),
    /** the throw-away home itself (stand-in programs leave their marks here) */
    home: srv.dir,
    /** where the local stand-ins listen (server.py): {publish: {url, workspace, token}, relay: {...}, head} */
    get standins() { return JSON.parse(fs.readFileSync(path.join(srv.dir, 'standins.json'), 'utf8')); },
    /** run this checkout's orch in the demo workspace as the stand-in helper would (env -i, the throw-away home);
     *  for what only a helper can do (a chat reply, a proposal). Returns stdout; throws on a non-zero exit. */
    orch(...words) {
      return execFileSync('env', [...envArgs({ ...runEnv(srv.dir), ORCH_AGENT: 'standin' }), ...UV_RUN, 'python', '-I', '-m', 'orch', ...words],
        { cwd: path.join(srv.dir, 'Pilatus'), encoding: 'utf8', timeout: 120000 });
    },
    /** like orch(...), but as the person at the computer (no helper mark): what a person types in a terminal */
    orchAsPerson(...words) {
      return execFileSync('env', [...envArgs(runEnv(srv.dir)), ...UV_RUN, 'python', '-I', '-m', 'orch', ...words],
        { cwd: path.join(srv.dir, 'Pilatus'), encoding: 'utf8', timeout: 120000 });
    },
    /** orch as the person at the computer in another folder of the throw-away home (a second workspace) */
    orchIn(dir, ...words) {
      if (!path.resolve(dir).startsWith(srv.dir + path.sep)) throw new Error('orchIn: not inside the throw-away home: ' + dir);
      return execFileSync('env', [...envArgs(runEnv(srv.dir)), ...UV_RUN, 'python', '-I', '-m', 'orch', ...words],
        { cwd: dir, encoding: 'utf8', timeout: 120000 });
    },
    /** git in a folder of the throw-away home, with no settings of this computer and a made-up author */
    git(dir, ...words) {
      if (!path.resolve(dir).startsWith(srv.dir + path.sep)) throw new Error('git: not inside the throw-away home: ' + dir);
      return execFileSync('env', [...envArgs({ PATH: process.env.PATH, HOME: srv.dir, GIT_CONFIG_GLOBAL: '/dev/null', GIT_CONFIG_SYSTEM: '/dev/null',
        GIT_AUTHOR_NAME: 'Test', GIT_AUTHOR_EMAIL: 'test@example.com', GIT_COMMITTER_NAME: 'Test', GIT_COMMITTER_EMAIL: 'test@example.com' }), 'git', ...words],
      { cwd: dir, encoding: 'utf8', timeout: 60000 });
    },
    /** run a short Python snippet with this checkout's orch importable (same env as orch(...)); args follow */
    python(code, ...rest) {
      return execFileSync('env', [...envArgs(runEnv(srv.dir)), ...UV_RUN, 'python', '-I', '-c', code, ...rest],
        { cwd: path.join(srv.dir, 'Pilatus'), encoding: 'utf8', timeout: 120000 });
    },
    /** open a dashboard address (`#tickets`, `#ticket/<id>`, `#settings/agent`) and wait until it is drawn */
    async open(hash = '#home') { await page.goto(`${srv.base}/${hash}`); await settle(); },
    /** reload the page and wait until it is drawn again: what is shown now came from the files, not the page's memory */
    async reload() { await page.reload(); await settle(); },
    /** wait until the page has drawn the current address (after a click that changed it) */
    settle,
    /** run fn and wait for the action `op` it sends; returns {status, text}. `refused: true` = a 4xx is the expected answer */
    async act(op, fn, { refused = false, timeout = 60000 } = {}) {
      if (refused) rec.refusedOk.add(op);
      const before = rec.ops.length;
      await fn();
      const t0 = Date.now();
      while (Date.now() - t0 < timeout) {
        const hit = rec.ops.slice(before).find(o => o.op === op);
        if (hit) {
          if (!refused && !ok(hit.status)) throw new Error(`${op} was refused (${hit.status}): ${hit.text}`);
          if (refused && ok(hit.status)) throw new Error(`${op} was expected to be refused, but went through`);
          await page.waitForTimeout(200);
          return hit;
        }
        await page.waitForTimeout(100);
      }
      throw new Error(`the page did not send ${op}`);
    },
    /** after a change made outside the page (orch(...), a file): tell the page's server a settings file changed and
     *  wait until its /api/state passes check(state) (checked here in Node). Returns that state. */
    async until(check, what, secs = 60) {
      const cfg = path.join(srv.dir, 'Pilatus', '.orch', 'config.toml');
      let s = null;
      for (let i = 0; i < secs * 2; i++) {
        if (i % 6 === 0) { const now = new Date(); fs.utimesSync(cfg, now, now); }
        s = await page.evaluate(async () => (await fetch('/api/state', { cache: 'no-store' })).json());
        if (check(s)) return s;
        await page.waitForTimeout(500);
      }
      throw new Error(`the page's state never showed ${what}`);
    },
    /** the page server checks for a newer orch at most every 10 minutes: forget its last answer */
    forgetUpdateInfo: () => srv.forgetUpdateInfo(),
    /** turn on an add-on of this checkout that server.py installed (a person's consent here, then on) */
    addonOn(name) {
      t.python('import sys; from pathlib import Path; from orch import addons; addons.record_consent(Path(sys.argv[1]), sys.argv[2])',
        path.join(srv.dir, 'Pilatus'), name);
      return t.orchAsPerson('addon', 'add', name, '--project-only');
    },
    /** with --out: keep pictures of the page now at the UX checklist sizes, <file>-<name>-<w>.png (a state worth
     *  showing in a review), with `el` (a locator) scrolled into view; the window goes back to its size after */
    async shot(name, el = null) {
      if (!shots) return;
      const was = page.viewportSize();
      for (const [w, h] of [[1280, 800], [1920, 1080], [390, 844]]) {
        await page.setViewportSize({ width: w, height: h });
        await page.waitForTimeout(400);
        if (el) await el.scrollIntoViewIfNeeded().catch(() => {});
        await page.screenshot({ path: `${shots}-${name}-${w}.png` });
      }
      await page.setViewportSize(was);
      await page.waitForTimeout(200);
    },
    /** fail with a plain message unless cond */
    must(cond, msg) { if (!cond) throw new Error(msg); },
    /** the visible text of the page's main area */
    text: () => page.locator('main').innerText(),
  };
  return t;
}

async function main() {
  const o = args(process.argv.slice(2));
  const all = catalogue.clickthroughs();
  if (o.list) {
    for (const c of all) console.log(`${c.file}: ${c.name}\n   ${(c.covers || []).join(' ')}`);
    const cov = catalogue.coverage();
    console.log(`\n${cov.features.length} features, ${cov.missing.length} without a click-through${cov.missing.length ? ': ' + cov.missing.join(' ') : ''}`);
    return 0;
  }
  const todo = all.filter(c => !o.only || o.only.has(c.file.replace(/\.cjs$/, '')));
  if (o.only && todo.length !== o.only.size) throw new Error(`no such click-through: ${[...o.only].filter(n => !all.some(c => c.file === n + '.cjs')).join(', ')}`);
  if (o.out) fs.mkdirSync(o.out, { recursive: true });
  const srv = await serve();
  const { chromium } = playwright();
  const browser = await chromium.launch({ args: ['--use-mock-keychain', '--password-store=basic'] });
  const done = new Set(), results = [];
  try {
    const ctx = await signIn(browser, srv);
    for (const c of todo) {
      const page = await ctx.newPage();
      const rec = recorder(page, srv.base);
      const problems = [];
      const t0 = Date.now();
      try {
        await c.run(tools(page, srv, rec, o.out ? path.join(o.out, c.file.replace(/\.cjs$/, '')) : null));
      } catch (e) {
        problems.push(String(e.message).split('\n')[0]);
      }
      if (o.out) await page.screenshot({ path: path.join(o.out, c.file.replace(/\.cjs$/, '.png')) }).catch(() => {});
      await page.close();
      problems.push(...new Set(rec.errors));
      const did = new Set([...rec.ops.filter(x => ok(x.status) || rec.refusedOk.has(x.op)).map(x => x.op), ...rec.pages]);
      const claimedNotDone = (c.covers || []).filter(k => !did.has(k));
      if (!problems.length && claimedNotDone.length) problems.push(`says it covers ${claimedNotDone.join(', ')} but never did it`);
      if (!problems.length) for (const k of c.covers || []) done.add(k);
      results.push({ c, problems, secs: ((Date.now() - t0) / 1000).toFixed(1) });
      console.log(`${problems.length ? 'FAILED' : 'passed'}  ${c.name} (${c.file}, ${results.at(-1).secs}s)`);
      for (const p of problems) console.log(`        ${p}`);
      if (problems.length && rec.ops.length) console.log(`        actions sent: ${rec.ops.map(x => `${x.op} ${x.status}`).join(', ')}`);
    }
  } finally {
    await browser.close();
    srv.stop();
  }
  const failed = results.filter(r => r.problems.length);
  let missing = [];
  if (!o.only) {
    missing = catalogue.features().filter(k => !done.has(k));
    if (missing.length) {
      console.log('\nThese dashboard features have no passing click-through (add one in workspace-addons/dashboard/clickthrough/features/):');
      for (const k of missing) console.log(`  - ${k}`);
    }
  }
  console.log(`\n${results.length - failed.length} of ${results.length} click-throughs passed${o.only ? '' : `; ${catalogue.features().length - missing.length} of ${catalogue.features().length} features done`}.`);
  return failed.length || missing.length ? 1 : 0;
}

module.exports = { tools };

if (require.main === module) main().then(c => process.exit(c), e => { console.error(e); process.exit(1); });
