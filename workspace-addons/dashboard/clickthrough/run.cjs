#!/usr/bin/env node
// Dashboard click-throughs: every dashboard feature done like a person in the real page, on a seeded demo workspace.
//
//   node workspace-addons/dashboard/clickthrough/run.cjs                  every click-through (CI: page-smoke)
//   node workspace-addons/dashboard/clickthrough/run.cjs --only home,checks   only these files (features/<name>.cjs)
//   node workspace-addons/dashboard/clickthrough/run.cjs --list           the features and who covers them, no browser
//   node workspace-addons/dashboard/clickthrough/run.cjs --out DIR        keep a picture of each click-through's end
//   node workspace-addons/dashboard/clickthrough/run.cjs --size 390x844   another window size (default 1280x900)
//   node workspace-addons/dashboard/clickthrough/run.cjs --part 1/2       every 2nd click-through from the 1st (CI runs
//                                                                          the parts as jobs at once, ORCH-1118)
//   node workspace-addons/dashboard/clickthrough/run.cjs --quarantined    only the QUARANTINED ones (nightly, ORCH-2363)
//
// Each click-through (features/*.cjs) does a thing, reloads the page, checks the result is still there, and fails on
// any console error or uncaught exception. The server is the real dashboard with working actions (server.py): a click
// runs this checkout's orch and writes real ticket files in a throw-away home under ~/.orch-test, started with
// `env -i` (HOME, USERPROFILE, ORCH_HOME there, ORCH_HOME_STRICT=1), so the orch of this computer is never touched.
// Chromium runs with --use-mock-keychain --password-store=basic (no keychain window).
//
// The runner records every action the page really sends and every page it shows. A click-through that claims a
// feature in `covers` but never did it fails; with no --only, a feature of the catalogue (catalogue.cjs) that no
// click-through did fails too, by name (with --part: the features its click-throughs claim, and in part 1 also the
// ones nobody claims). The limit of 3 second tries below counts per part. Exit 0 = all passed.
//
// A click-through that fails is tried once more at the end, alone, on a fresh throw-away home, server and browser
// context (ORCH-1132): a pass then counts, and the summary names it ("passed on second try: <file>") so a flaky one
// stays visible. Failed twice = failed. More than 3 failures at once are not tried again (a real break); a known
// unsteady one is not counted and not tried again. Second tries run on as many fresh servers at once as the first
// round has lanes and get only the time the job has left. Each
// click-through has a time limit of 3 minutes, so one hang cannot eat the job. A click-through on the short
// UNSTEADY list (each entry names the ticket that fixes it) still runs, but its failure is printed as
// "FAILED (known unsteady, does not count): <file>" and does not make the run red.
// A click-through on the QUARANTINED list (ORCH-2363) does not run at all, unless named with --only or run with
// --quarantined (nightly on develop and on release branches, the quarantine workflow); the features only it covers
// are not asked for. With --quarantined a failure makes that run red.
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
const ADDONS = ['focus', 'lessons', 'pull-requests', 'factory', 'sync', 'automation', 'browse'];
const UV_RUN = ['uv', 'run', '-q', '--project', path.join(REPO, 'workspace'),
  ...ADDONS.flatMap(n => ['--with-editable', path.join(REPO, 'workspace-addons', n)])];
/** `python -I -c AT_TERMINAL <orch words>`: orch with a terminal as its input, as a person types it. An unattended
 *  orch call (no terminal, no --by) is a helper (ORCH-2108); the person helpers below run this way. Enter is
 *  already typed a few times, so a question orch asks at a terminal (init's name, a y/N) is skipped, never waited on. */
const AT_TERMINAL = "import os, runpy, sys\ntry:\n    import pty\n    m, s = pty.openpty()\n    os.dup2(s, 0)\n    os.close(s)\n"
  + "    os.write(m, b'\\n' * 16)\nexcept (ImportError, OSError):\n    pass\n"
  + "sys.argv = ['orch', *sys.argv[1:]]\nrunpy.run_module('orch', run_name='__main__', alter_sys=True)";
/** the env of every process of the run: the throw-away home only; ORCH_REPO = this checkout, so the add-ons
 *  above count as shipped and "the newest orch" is read from here, never from the internet */
const runEnv = dir => ({ HOME: dir, USERPROFILE: dir, ORCH_HOME: path.join(dir, 'orch'), ORCH_HOME_STRICT: '1',
  // the stand-in programs of server.py (agent tools, gh) first, for every orch the run starts, not only the server
  PATH: `${path.join(dir, 'bin')}${path.delimiter}${process.env.PATH}`, LANG: 'en_US.UTF-8', ORCH_REPO: REPO, ORCH_NO_TOOL_CHECK: '1',
  UV_CACHE_DIR: process.env.UV_CACHE_DIR || path.join(os.homedir(), '.cache', 'uv') });
const envArgs = env => ['-i', ...Object.entries(env).map(([k, v]) => `${k}=${v}`)];

function args(argv) {
  const o = { only: null, out: null, list: false, part: null, quarantined: false };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--list') o.list = true;
    else if (a === '--quarantined') o.quarantined = true;
    else if (a === '--only') o.only = new Set(argv[++i].split(',').map(s => s.replace(/\.cjs$/, '')));
    else if (a === '--out') o.out = path.resolve(argv[++i]);
    else if (a === '--part') {
      const m = /^(\d+)\/(\d+)$/.exec(argv[++i] || '');
      if (!m || +m[1] < 1 || +m[1] > +m[2]) throw new Error('--part wants N/M, for example 1/2');
      o.part = { n: +m[1], of: +m[2] };
    }
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
  // the account's own home, as server.py checks it: on this Mac's runner HOME is the job's throwaway folder (ORCH-1125)
  const root = path.join(os.userInfo().homedir, '.orch-test');
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

/** The context still gets the page's state and still holds the page secret: a click-through that logged the
 *  browser out (m-token-login) and failed before it logged in again leaves neither (#2456). */
async function loggedIn(ctx, base) {
  try {
    if (!(await ctx.request.get(`${base}/api/state`)).ok()) return false;
    const here = (await ctx.storageState()).origins.find(x => x.origin === new URL(base).origin);
    return !!(here && here.localStorage.some(x => x.name === 'orch_page_secret' && x.value));
  } catch { return false; }
}

/** After each click-through of a lane: the same context when it is still logged in, else a fresh one from
 *  again(), so one failed login step does not make every later click-through of the lane fail with 401/403. */
async function stayLoggedIn(ctx, base, again, file = '') {
  if (await loggedIn(ctx, base)) return ctx;
  await ctx.close().catch(() => {});
  console.log(`        after ${file || 'a click-through'}: the browser was logged out, logged in again for the next ones`);
  return again();
}

/** Record what the page does: ops sent (with their answer) and the router kinds it showed. */
function recorder(page, base) {
  const rec = { ops: [], pages: new Set(), errors: [], refusedOk: new Set(), failed: [], offAddons: new Set(), offViews404: 0, slowOk: new Set(), slow503: 0, signedOut: false };
  page.on('response', r => {
    if (r.status() < 400) return;
    const line = `${r.status()} ${r.request().method()} ${r.url().replace(base, '')}`;
    rec.failed.push(line);
    // the page warms add-on views in the background from its own copy of the state, which lags the server by a poll:
    // the view of an add-on the click-through itself just turned off (addonOff) may answer 404 once; that is fine
    const m = /^404 GET \/api\/addon\/([^/?]+)$/.exec(line);
    if (m && rec.offAddons.has(decodeURIComponent(m[1]))) rec.offViews404++;
    // an add-on page's own answer that is still being built the first time says 503 "slow to answer" and the page
    // shows Try again; a click-through that waits it out names that address (slowOk) and those 503s are not counted
    const s = /^503 GET ([^?]+)/.exec(line);
    if (s && [...rec.slowOk].some(a => (a instanceof RegExp ? a.test(s[1]) : a === s[1]))) rec.slow503++;
  });
  // the login routes (ORCH-1035): a login with a token, how this browser is signed in, its profile, Log out
  page.on('response', r => {
    const m = /^\/session(?:\/(me|profile|logout))?$/.exec(r.url().replace(base, '').split('?')[0]);
    if (!m || r.status() >= 400) return;
    if (m[1]) rec.pages.add(`session:${m[1]}`);
    else if (/"login"/.test(r.request().postData() || '')) rec.pages.add('session:login');
  });
  page.on('pageerror', e => rec.errors.push(`uncaught exception: ${String(e.message).slice(0, 300)}`));
  page.on('console', m => {
    if (m.type() !== 'error') return;
    const t = m.text();
    // Chromium logs every 4xx answer as a console error; an action a click-through expects to be refused is fine
    if (/Failed to load resource: the server responded with a status of 4\d\d/.test(t) && rec.ops.some(o => o.status >= 400 && rec.refusedOk.has(o.op))) return;
    // a click-through that logs the browser out on purpose: every read is refused until it logs in again (ORCH-481)
    if (/Failed to load resource: the server responded with a status of 401/.test(t) && rec.signedOut) return;
    // and a wrong token it types on the login screen on purpose is refused (ORCH-1851)
    if (/status of 403/.test(t) && rec.signedOut && rec.failed.at(-1) === '403 POST /session') return;
    if (/Failed to load resource: the server responded with a status of 404/.test(t) && rec.offViews404 > 0) { rec.offViews404--; return; }
    if (/Failed to load resource: the server responded with a status of 503/.test(t) && rec.slow503 > 0) { rec.slow503--; return; }
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
  const openMore = async () => {
    const closed = page.locator('details[data-key^="settings-more-"]:not([open]) > summary:visible');
    for (let n = await closed.count(); n > 0; n--) await closed.first().click();
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
    /** like orch(...), but as the person at the computer (no helper mark, a terminal as input): what a person types */
    orchAsPerson(...words) {
      return execFileSync('env', [...envArgs(runEnv(srv.dir)), ...UV_RUN, 'python', '-I', '-c', AT_TERMINAL, ...words],
        { cwd: path.join(srv.dir, 'Pilatus'), encoding: 'utf8', timeout: 120000 });
    },
    /** orch as the person at the computer in another folder of the throw-away home (a second workspace) */
    orchIn(dir, ...words) {
      if (!path.resolve(dir).startsWith(srv.dir + path.sep)) throw new Error('orchIn: not inside the throw-away home: ' + dir);
      return execFileSync('env', [...envArgs(runEnv(srv.dir)), ...UV_RUN, 'python', '-I', '-c', AT_TERMINAL, ...words],
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
    /** an older Settings kept its technical switches in a closed "More" fold (ORCH-300): open any such fold, as a person does */
    openMore,
    /** open a dashboard address (`#tickets`, `#ticket/<id>`, `#settings/agent`) and wait until it is drawn */
    async open(hash = '#home') { await page.goto(`${srv.base}/${hash}`); await settle(); await openMore(); },
    /** reload the page and wait until it is drawn again: what is shown now came from the files, not the page's memory */
    async reload() { await page.reload(); await settle(); await openMore(); },
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
    /** turn an add-on off again (as the person) and wait until the page's state no longer lists it; the page may still
     *  ask once for that add-on's view in the meantime (its state lags a poll), and that 404 is not counted as an error */
    async addonOff(name) {
      rec.offAddons.add(name);
      t.orchAsPerson('addon', 'remove', name);
      return t.until(s => !(s.addons || []).some(a => a.name === name), `${name} off again`);
    },
    /** the page's own GET at `address` (such as '/addon/factory/api/home') may answer 503 while its first answer is
     *  still being built (the page says Try again); the click-through waits that out, so those 503s are no error.
     *  A RegExp names every address it matches (an order whose id is known only later) */
    slowOk(address) { rec.slowOk.add(address); },
    /** the browser is signed out on purpose (signedOut(true)) until signedOut(false): the page's refused reads (401)
     *  meanwhile are no error */
    signedOut(on = true) { rec.signedOut = !!on; },
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
    /** the page text once it shows every one of `parts` (strings or regexps; a function of the text for "no longer
     *  shows"), or as it is after `secs`: a reloaded
     *  page draws from its last copy and fills in what it fetches after that (a ticket's files, a newer state), so a
     *  check right after a reload waits for it instead of reading the first picture (ORCH-1652, issue 2589) */
    async seen(parts, secs = 15) {
      const has = t => (typeof parts === 'function' ? parts(t) : parts.every(x => (x instanceof RegExp ? x.test(t) : t.includes(x))));
      let t = '';
      for (const end = Date.now() + secs * 1000; ;) {
        t = await page.locator('main').innerText().catch(() => '');
        if ((t && has(t)) || Date.now() > end) return t;  // an empty read (the page between two drawings) is not an answer
        await page.waitForTimeout(250);
      }
    },
  };
  return t;
}

/** ` (at f-x.cjs:31: <that line>)`: the step of the click-through that failed or waited, read from the error's stack */
function where(e) {
  const m = /([^\s()]*\/features\/([\w.-]+\.cjs)):(\d+):\d+/.exec(String(e && e.stack || ''));
  if (!m) return '';
  let src = '';
  try { src = fs.readFileSync(m[1], 'utf8').split('\n')[Number(m[3]) - 1].trim().slice(0, 160); } catch (_) { /* gone */ }
  return ` (at ${m[2]}:${m[3]}${src ? ': ' + src : ''})`;
}
/** A failed click-through's problem: its first line and where, then what it showed after the first line (the page
 *  text most errors carry), so a red run says what was on screen (ORCH-1770: only "Contacts:" was left of it). */
function problemLine(e) {
  // the first line that says something: an error can start with an empty line (a command's own output)
  const lines = String(e && e.message || e).split('\n');
  while (lines.length > 1 && !lines[0].trim()) lines.shift();
  const [first, ...rest] = lines.map((l, i) => i ? l : l.trim());
  const shown = rest.join('\n').trim().slice(0, 600);
  return first + where(e) + (shown ? '\n          ' + shown.replace(/\n/g, '\n          ') : '');
}

/** What one click-through on a shared lane server can leave behind that breaks a later one there (ORCH-1652): a git
 *  folder in the workspace (d-private made one with no commit, so k-copies-cleanup skipped its own first commit and
 *  no copy could be made: red in about a second, only when both landed on the same lane) and the copy settings of
 *  this computer (orch home copies.json: when, how many, what runs in a new copy, the debug log switch).
 *  Also the workspace Chat's day files: a message one click-through wrote hides the empty Chat of the next one.
 *  seedState reads them right after the server started; restoreSeed puts them back after each click-through of the
 *  first round and names what it put back, so a click-through never depends on which ones ran before it on its lane
 *  (each passes alone on a fresh server: that is the second try). */
function seedState(srv) {
  const read = f => { try { return fs.readFileSync(f); } catch (_) { return null; } };
  const copies = path.join(srv.dir, 'orch', 'copies.json');
  const chat = path.join(srv.dir, 'Pilatus', '.orch', 'chat');
  return { git: fs.existsSync(path.join(srv.dir, 'Pilatus', '.git')), copies, copiesText: read(copies), read,
    chat, chatDays: chatDays(chat) };
}

/** the workspace Chat's day files (`.orch/chat/<day>.json`, one level): name -> content */
function chatDays(dir) {
  const out = new Map();
  let names = [];
  try { names = fs.readdirSync(dir); } catch (_) { return out; }
  for (const n of names) {
    if (!/^\d{4}-\d{2}-\d{2}\.json$/.test(n)) continue;
    try { out.set(n, fs.readFileSync(path.join(dir, n))); } catch (_) { /* gone meanwhile */ }
  }
  return out;
}

function restoreSeed(srv, seed, file, log = console.log) {
  const put = [];
  const dotGit = path.join(srv.dir, 'Pilatus', '.git');
  if (!seed.git && fs.existsSync(dotGit)) {
    fs.rmSync(dotGit, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
    put.push('removed the git folder it made in the workspace');
  }
  const now = seed.read(seed.copies);
  if (!(now === null ? seed.copiesText === null : seed.copiesText !== null && now.equals(seed.copiesText))) {
    if (seed.copiesText === null) fs.rmSync(seed.copies, { force: true });
    else fs.writeFileSync(seed.copies, seed.copiesText);
    put.push('put the settings of this computer back (copies, debug log)');
  }
  // the Chat as seeded: l-phone-clear wants an empty Chat (its three suggestions), e-chat writes to it first when
  // both share a lane (23 Nov, run 45123932612: "the Chat page shows 0 suggestions")
  if (seed.chatDays) {
    const days = chatDays(seed.chat);
    let changed = false;
    for (const [n, buf] of days) {
      const was = seed.chatDays.get(n);
      if (!was) { fs.rmSync(path.join(seed.chat, n), { force: true }); changed = true; }
      else if (!buf.equals(was)) { fs.writeFileSync(path.join(seed.chat, n), was); changed = true; }
    }
    for (const [n, was] of seed.chatDays) {
      if (!days.has(n)) { fs.mkdirSync(seed.chat, { recursive: true }); fs.writeFileSync(path.join(seed.chat, n), was); changed = true; }
    }
    if (changed) put.push('put the Chat back as it was');
  }
  if (put.length) log(`        after ${file}: ${put.join(', ')}`);
  return put;
}

/** A time limit for one click-through (the slowest takes about a minute on CI): a hang fails it by name instead of
 *  eating the whole job. */
const STEP_LIMIT_MS = 180000;
/** At most this many failed click-throughs are tried a second time: more failures at once are a real break, and a
 *  fresh server for each would only stretch a red job. */
const MAX_RETRIES = 3;
/** Known unsteady click-throughs: each still runs and is printed, but a failure does not make the run red (nor do
 *  the features only it covers). The owner decided click-throughs must not hold up queue groups (20 Nov); this is
 *  the bridge until the named ticket fixes the click-through. Keep it short (a test allows at most 3) and remove an
 *  entry as soon as its ticket is done. */
const UNSTEADY = {
  'r-factory-idea-to-start.cjs': 'ORCH-1118',  // failed twice in one run in group #2220 (Running after a reload; 404)
};
/** Quarantined click-throughs (ORCH-2363, owner 27 Nov): they made most red merge queue groups, so they are out of
 *  the queue and of every default run; the quarantine workflow runs them alone (--quarantined) nightly on develop and
 *  on release branches, where a red run opens or refreshes one "later" ticket (release keeper). Each entry names the
 *  ticket that fixes it; remove the entry when it is fixed and green there again. */
const QUARANTINED = {
  'a-board-families.cjs': 'ORCH-2153',
  'f-sync-page.cjs': 'ORCH-2363',
  'q-automation-repeats.cjs': 'ORCH-2363',
};
/** No second try starts after this long, and every second try must end by RUN_END_MS (the CI job stops at 15
 *  minutes, its setup takes about one): a second try gets only the time that is left, so a slow first round (run
 *  45082995989: 12 minutes) still leaves room to try its failures again instead of none (ORCH-1652). */
const RETRY_DEADLINE_MS = 13 * 60000;
const RUN_END_MS = 13 * 60000 + 30000;
/** A second try that would get less than this is not started (a fresh server alone takes about 15 seconds). */
const MIN_RETRY_MS = 45000;
/** The first round runs on this many seeded servers at once, each with its own throw-away home and browser context
 *  (ORCH-1402: one after the other the suite took 14m45s of the job's 15). Each click-through already passes alone on
 *  a fresh server (the second try), so none needs another one's leftovers. CLICKTHROUGH_LANES=1 runs them in a row. */
const LANES = Math.max(1, Number(process.env.CLICKTHROUGH_LANES) || 2);

/** promise, or a plain error after ms; the timer is always cleared when it settles (an unref timer let Node 20 end a pending test as cancelled) */
function withTimeout(promise, ms, what) {
  let timer;
  const late = new Promise((_, no) => {
    timer = setTimeout(() => no(new Error(`${what} took longer than ${Math.round(ms / 1000)}s and was stopped`)), ms);
  });
  return Promise.race([promise, late]).finally(() => clearTimeout(timer));
}

/** Every click-through once, then each failed one once more from a clean state (fresh(c, limitMs) runs it on a
 *  fresh server and browser context, stopped after limitMs). A pass on the second try counts as a pass and is named,
 *  so flakes stay visible; failed twice = failed. first(c, lane) and fresh(c, limitMs) resolve {c, problems, ...};
 *  between() runs after the first round. With lanes > 1 the first round runs that many at once, each lane taking
 *  the next click-through in the list when it is free, and so do the second tries; results keep the list's order.
 *  A known unsteady one is neither counted toward the limit nor tried again: its failure never makes the run red,
 *  so a second try would only take a server and time from the others (ORCH-1629, ORCH-1652). No second try starts
 *  after `deadline`, and each gets at most the time left until `end` (none when less than MIN_RETRY_MS is left). */
async function runAll(todo, { first, fresh, between = async () => {}, maxRetries = MAX_RETRIES, deadline = Infinity,
  end = Infinity, now = Date.now, log = console.log, lanes = 1, unsteady = UNSTEADY, limit = STEP_LIMIT_MS }) {
  const results = new Array(todo.length);
  const pool = async (n, items, fn) => {
    let next = 0;
    const lane = async k => { while (next < items.length) { const i = next++; await fn(items[i], k); } };
    await Promise.all(Array.from({ length: Math.max(1, Math.min(n, items.length)) }, (_, k) => lane(k)));
  };
  await pool(lanes, todo.map((c, i) => i), async (i, k) => { results[i] = await first(todo[i], k); });
  await between();
  const failed = results.filter(r => r.problems.length && !unsteady[r.c.file]);
  const secondTry = [];
  if (failed.length > maxRetries) {
    log(`\n${failed.length} click-throughs failed: more than ${maxRetries}, so none is tried again.`);
    return { results, secondTry };
  }
  await pool(lanes, failed, async r => {
    const left = Math.min(limit, end - now());
    if (now() > deadline || left < MIN_RETRY_MS) { log(`no time left for a second try of ${r.c.file}`); return; }
    log(`\ntrying ${r.c.file} once more on a fresh server (at most ${Math.round(left / 1000)}s)`);
    const again = await fresh(r.c, left);
    if (!again.problems.length) {
      results[results.indexOf(r)] = again;
      secondTry.push(r.c.file);
    }
  });
  return { results, secondTry };
}

/** One click-through on a new page of ctx: its problems, the features it did, its time. */
async function runOne(ctx, srv, c, o) {
  const page = await ctx.newPage();
  const rec = recorder(page, srv.base);
  const problems = [];
  const t0 = Date.now();
  try {
    await withTimeout(c.run(tools(page, srv, rec, o.out ? path.join(o.out, c.file.replace(/\.cjs$/, '')) : null)), o.limit || STEP_LIMIT_MS, c.file);
  } catch (e) {
    problems.push(problemLine(e));
  }
  if (o.out) await withTimeout(page.screenshot({ path: path.join(o.out, c.file.replace(/\.cjs$/, '.png')) }), 30000, 'the picture').catch(() => {});
  await withTimeout(page.close(), 30000, 'closing the page').catch(() => {});
  problems.push(...new Set(rec.errors));
  const did = new Set([...rec.ops.filter(x => ok(x.status) || rec.refusedOk.has(x.op)).map(x => x.op), ...rec.pages]);
  const claimedNotDone = (c.covers || []).filter(k => !did.has(k));
  if (!problems.length && claimedNotDone.length) problems.push(`says it covers ${claimedNotDone.join(', ')} but never did it`);
  const r = { c, problems, secs: ((Date.now() - t0) / 1000).toFixed(1) };
  console.log(`${problems.length ? 'FAILED' : 'passed'}  ${c.name} (${c.file}, ${r.secs}s)`);
  for (const p of problems) console.log(`        ${p}`);
  if (problems.length && rec.ops.length) console.log(`        actions sent: ${rec.ops.map(x => `${x.op} ${x.status}`).join(', ')}`);
  return r;
}

async function main() {
  const started = Date.now();
  const o = args(process.argv.slice(2));
  const all = catalogue.clickthroughs();
  if (o.list) {
    for (const c of all) console.log(`${c.file}: ${c.name}\n   ${(c.covers || []).join(' ')}`);
    const cov = catalogue.coverage();
    console.log(`\n${cov.features.length} features, ${cov.missing.length} without a click-through${cov.missing.length ? ': ' + cov.missing.join(' ') : ''}`);
    return 0;
  }
  const picked = pick(all, o);
  if (o.only && picked.length !== o.only.size) throw new Error(`no such click-through: ${[...o.only].filter(n => !all.some(c => c.file === n + '.cjs')).join(', ')}`);
  const todo = o.part ? part(picked, o.part) : picked;
  if (o.part) console.log(`part ${o.part.n} of ${o.part.of}: ${todo.length} of ${picked.length} click-throughs`);
  if (o.out) fs.mkdirSync(o.out, { recursive: true });
  const nLanes = Math.max(1, Math.min(LANES, todo.length));
  // every lane's server starts at once; a server that does not start stops the ones that did
  const booted = await Promise.allSettled(Array.from({ length: nLanes }, () => serve()));
  let servers = booted.filter(x => x.status === 'fulfilled').map(x => x.value);
  const broken = booted.find(x => x.status === 'rejected');
  if (broken) { for (const one of servers) one.stop(); throw broken.reason; }
  const { chromium } = playwright();
  // a fake microphone that is always allowed (ORCH-422: the voice note click-through records with it)
  const browser = await chromium.launch({ args: ['--use-mock-keychain', '--password-store=basic', '--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream'] });
  let run;
  const spent = [];   // the fresh servers of the second tries, stopped at the end
  try {
    const ctxs = await Promise.all(servers.map(one => signIn(browser, one)));
    const seeds = servers.map(seedState);
    if (nLanes > 1) console.log(`${todo.length} click-throughs on ${nLanes} servers at once`);
    run = await runAll(todo, {
      lanes: nLanes,
      first: async (c, k) => {
        const r = await runOne(ctxs[k], servers[k], c, o);
        restoreSeed(servers[k], seeds[k], c.file);
        ctxs[k] = await stayLoggedIn(ctxs[k], servers[k].base, () => signIn(browser, servers[k]), c.file);
        return r;
      },
      between: async () => {
        await Promise.all(ctxs.map(x => x.close().catch(() => {})));
        for (const one of servers) one.stop();
        servers = [];
      },
      // the second try: a new throw-away home and server and a new browser context, as for the first round. Its
      // server start and sign-in count toward the time it got, so it still ends in time; its server is stopped only
      // after every second try ended (stop() waits on orch in a blocking call, which would stall the other lane)
      fresh: async (c, limitMs) => {
        const t0 = Date.now();
        const starting = serve();
        let one = null;
        try {
          one = await withTimeout(starting, limitMs, 'starting a fresh server');
          spent.push(one);
          const fctx = await withTimeout(signIn(browser, one), Math.max(1000, limitMs - (Date.now() - t0)), 'the sign-in');
          const left = Math.min(o.limit || STEP_LIMIT_MS, limitMs - (Date.now() - t0));
          try {
            if (left < 10000) return { c, problems: ['no time left for the second try after its server started'] };
            return await runOne(fctx, one, c, { ...o, limit: left });
          } finally { await fctx.close().catch(() => {}); }
        } catch (e) {
          if (!one) starting.then(late => spent.push(late), () => {});   // a server that came up too late is stopped too
          return { c, problems: [`the second try did not start: ${String(e.message).split('\n')[0]}`] };
        }
      },
      deadline: started + RETRY_DEADLINE_MS,
      end: started + RUN_END_MS,
    });
  } finally {
    await browser.close();
    for (const one of [...servers, ...spent]) one.stop();
  }
  const { results, secondTry } = run;
  const wanted = o.only || o.quarantined ? null : partFeatures(all, todo, notQuarantined(all, catalogue.features()), o.part);
  const v = verdict(results, wanted);
  if (v.missing.length) {
    console.log('\nThese dashboard features have no passing click-through (add one in workspace-addons/dashboard/clickthrough/features/):');
    for (const k of v.missing) console.log(`  - ${k}`);
  }
  const nFeatures = (wanted || []).length;
  console.log(`\n${results.length - v.failed.length - v.unsteady.length} of ${results.length} click-throughs passed${!wanted ? '' : `; ${nFeatures - v.missing.length - v.excused.length} of ${nFeatures} features done`}.`);
  if (secondTry.length) console.log(`passed on second try: ${secondTry.join(', ')}`);
  for (const r of v.unsteady) console.log(`FAILED (known unsteady, does not count): ${r.c.file} (${UNSTEADY[r.c.file]} fixes it)`);
  if (v.failed.length) console.log(`failed: ${v.failed.map(r => r.c.file).join(', ')}`);
  return v.code;
}

/** The click-throughs a run does: the --only names; with --quarantined only the QUARANTINED ones; else all but those. */
function pick(all, o, quarantined = QUARANTINED) {
  if (o.only) return all.filter(c => o.only.has(c.file.replace(/\.cjs$/, '')));
  return all.filter(c => Boolean(quarantined[c.file]) === Boolean(o.quarantined));
}

/** The features a default run asks for: none that only quarantined click-throughs cover (they are not run). */
function notQuarantined(all, features, quarantined = QUARANTINED) {
  const by = list => new Set(list.flatMap(c => c.covers || []));
  const kept = by(all.filter(c => !quarantined[c.file])), parked = by(all.filter(c => quarantined[c.file]));
  return features.filter(k => kept.has(k) || !parked.has(k));
}

/** The click-throughs of part {n, of}: every of-th one from the n-th, so the long ones spread over the parts. */
function part(all, { n, of }) {
  return all.filter((c, i) => i % of === n - 1);
}

/** The features a run must have done: all of them without a part; in a part the ones its click-throughs cover, and
 *  in part 1 also those no click-through covers at all (so a feature nobody claims still fails, once). */
function partFeatures(all, todo, features, p) {
  if (!p) return features;
  const has = (list, k) => list.some(c => (c.covers || []).includes(k));
  return features.filter(k => has(todo, k) || (p.n === 1 && !has(all, k)));
}

/** The run's verdict. failed: what makes it red; unsteady: failures of the UNSTEADY list (printed, not counted);
 *  missing: features (when given) no passing click-through did, except those only a failed unsteady one covers
 *  (excused). code: 1 = red. */
function verdict(results, features, unsteady = UNSTEADY) {
  const bad = results.filter(r => r.problems.length);
  const failed = bad.filter(r => !unsteady[r.c.file]);
  const shaky = bad.filter(r => unsteady[r.c.file]);
  const done = new Set(), shakyCovers = new Set();
  for (const r of results) if (!r.problems.length) for (const k of r.c.covers || []) done.add(k);
  for (const r of shaky) for (const k of r.c.covers || []) shakyCovers.add(k);
  const notDone = (features || []).filter(k => !done.has(k));
  const missing = notDone.filter(k => !shakyCovers.has(k));
  const excused = notDone.filter(k => shakyCovers.has(k));
  return { failed, unsteady: shaky, missing, excused, code: failed.length || missing.length ? 1 : 0 };
}

module.exports = { tools, recorder, where, loggedIn, stayLoggedIn, runAll, withTimeout, verdict, part, partFeatures, pick, notQuarantined, seedState, restoreSeed, UNSTEADY, QUARANTINED };

if (require.main === module) main().then(c => process.exit(c), e => { console.error(e); process.exit(1); });
