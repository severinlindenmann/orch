// The click-through of the new Focus (draft D, ORCH-261): every feature as one numbered step with what to do, what
// must be seen and the picture to take at 1280, 1920 and 390 wide. Read by e2e/focus_d/clickthrough.cjs (runs it) and
// by workspace-addons/dashboard/tests/focus_d_clickthrough.test.js (checks the list is complete and CLICKTHROUGH.md is
// current). Source of truth for look and behaviour: the draft D mockup (mockup/focus/focus-v4d.html).
//
// A step is READY when it has `run` and no `waits`: the runner clicks it in the real dashboard and fails on a page
// error, a console error, sideways scroll or a thrown check. A step with `waits` is PENDING: it names the crew task that
// builds it and is listed, not run. When you build a feature: write its `run`, delete its `waits`, then
// `node e2e/focus_d/clickthrough.cjs --write-md` and commit both files.
//
// `draft` is the same step in the draft D mockup (its query string and optional clicks): `--target draft` takes the
// reference pictures there, so every built screen can be put beside the draft it must match.
'use strict';

const SIZES = [[1280, 800], [1920, 1080], [390, 844]];

// The parts the owner listed for this click-through (ORCH-265). Every one must have at least one step.
const AREAS = ['start', 'wall', 'bar', 'layer', 'split', 'sessions', 'chat', 'message box', 'voice', '16 widgets',
  'terminal', 'motion', 'reduced motion', 'phone width'];

// The 16 result widget kinds of draft D (WG in focus-v4d.js), in its order.
const WIDGETS = ['Markdown', 'Text and logs', 'Code', 'JSON and YAML', 'Table', 'Web page', 'PDF', 'Picture',
  'Video and recording', 'Audio', 'Chart', 'Change', 'Pull request or issue link', 'Archive', 'Plain link', 'Unknown file'];

const T = {
  pages: 'Pages change without a full reload (crew task soft-pages)',
  bar: 'The bar under every page (crew task bar)',
  layer: 'The layer: bottom, right, full screen (crew task layer)',
  split: 'Split into one, two or three sessions (crew task split)',
  data: 'Live data for every session (crew task live-data)',
  wall: 'The wall (crew task wall)',
  pin: 'Pin and rename sessions (crew task pin-rename)',
  sessions: 'Start choice, earlier sessions and sessions without a ticket (crew tasks of the Wall and sessions stage)',
  chat: 'Chat (crew tasks of the Chat stage)',
  widgets: 'Result widgets and big overlay in the style guide (ORCH-263)',
  terminal: 'Terminal in the browser, after the security review and the owner\'s choice (Terminal stage)',
  look: 'Look and motion (Look and motion stage)',
};

// Checks the runner can use inside a step.
async function noSideways(page) {
  const over = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  if (over > 1) throw new Error(`the page scrolls sideways by ${over} px`);
}

async function mainHasText(page) {
  await page.waitForFunction(() => {
    const m = document.querySelector('main');
    return m && m.innerText.trim().length > 20 && !m.querySelector('.skeleton, [aria-busy=true]');
  }, null, { timeout: 20000 });
}

// Step 3. The test dashboard reads files only, so it has no add-on list (that comes from the orch command): the step
// adds the live-session add-on to the page's state and answers the switch's one call (focus_preview.set) like the
// server does. Everything else is the real page: Settings row, the click, the address, today's frame, the new page.
async function previewSwitch(page, dash) {
  let on = false;
  const live = { name: 'focus', label: 'Focus', icon: 'target', active: true, removable: true, shipped: false,
    description: 'A live page for one ticket.', page: { path: '/', label: 'Open Focus', live_session: true },
    dashboard: { label: 'Focus', icon: 'target', order: 20 } };
  let last = null;
  const dress = st => {
    st.addons = [...(st.addons || []).filter(a => a.name !== live.name), live];
    st.settings = { ...(st.settings || {}), focus_preview_on: on,
      addons: [...((st.settings || {}).addons || []).filter(a => a.name !== live.name), live] };
    last = st;
    return st;
  };
  await page.route(/\/api\/state(\?.*)?$/, async route => {
    const res = await route.fetch();
    if (res.status() !== 200) return route.fulfill({ response: res });
    route.fulfill({ response: res, json: dress(await res.json()) });
  });
  await page.route('**/api/act', async route => {
    const body = route.request().postDataJSON();
    if (body.op !== 'focus_preview.set') return route.fallback();
    on = body.args.on === true;
    route.fulfill({ json: dress({ ...last }) });
  });
  await page.route('**/addon/focus/**', route => route.fulfill({ contentType: 'text/html',
    body: '<!doctype html><title>Focus</title><main>Today\'s Focus</main>' }));
  const sw = '[data-key="addon-detail-live-preview"]';
  const settings = async want => {
    await page.evaluate(() => { location.hash = '#settings/addons/focus'; });
    await page.waitForSelector(sw, { timeout: 20000 });
    if (await page.getAttribute(sw, 'aria-checked') !== String(!want)) throw new Error('the Preview switch is not ' + (want ? 'off' : 'on') + ' before the click');
    await page.click(sw);
    await page.waitForSelector(`${sw}[aria-checked="${want}"]`, { timeout: 10000 });
  };
  const focusPage = async () => { await page.evaluate(() => { location.hash = '#addon/focus'; }); await page.waitForTimeout(300); };
  await page.goto(dash + '/#settings/addons/focus');
  await page.waitForSelector(sw, { timeout: 20000 });
  await focusPage();
  await page.waitForSelector('iframe.embed', { timeout: 10000 });  // off: today's Focus
  await settings(true);
  await focusPage();
  await page.waitForSelector('[data-key="live-next"]', { timeout: 10000 });
  if (await page.$('iframe.embed')) throw new Error('today\'s Focus still shows with Preview on');
  if ((await page.textContent('[data-key="live-next-tag"]')).trim() !== 'Preview') throw new Error('the new Focus is not marked Preview');
  await settings(false);
  await focusPage();
  await page.waitForSelector('iframe.embed', { timeout: 10000 });  // off again: today's Focus is back
  await settings(true);
  await focusPage();
  await page.waitForSelector('[data-key="live-next"]', { timeout: 10000 });
  await noSideways(page);
}

// Step 13. Preview on without the switch's clicks (step 3 clicks them): the page's state says the switch is on.
async function previewOn(page) {
  const live = { name: 'focus', label: 'Focus', icon: 'target', active: true, removable: true, shipped: false,
    description: 'A live page for one ticket.', page: { path: '/', label: 'Open Focus', live_session: true },
    dashboard: { label: 'Focus', icon: 'target', order: 20 } };
  await page.route(/\/api\/state(\?.*)?$/, async route => {
    const res = await route.fetch();
    if (res.status() !== 200) return route.fulfill({ response: res });
    const st = await res.json();
    st.addons = [...(st.addons || []).filter(a => a.name !== live.name), live];
    st.settings = { ...(st.settings || {}), focus_preview_on: true };
    route.fulfill({ response: res, json: st });
  });
}

// Step 9. The test dashboard has no running helpers, so the step gives the page draft D's 24 sessions (3 need you,
// 1 pinned, 3 working, 9 in line, 8 idle) as extra tickets in its state and as the answer of the live sessions API
// (/api/sessions, ORCH-359: the bar and the panes read it), with the Preview switch on. A pin or a name (session.pin /
// session.name, ORCH-361) is taken by a stand-in, as the real server keeps it in the workspace (this test page has no
// sign-in; the dashboard click-through f-session-pin-name sends them to the real server), and the stand-in list then
// carries it, as the real API does. Everything else is the real page: the bar, its fold, list and search.
const BAR_SESSIONS = [
  ['wait', 'ORCH-238', 'Add files and notes to a ticket'], ['wait', 'ORCH-201', 'Send the weekly summary'],
  ['wait', 'ORCH-214', 'New price list for the shop'], ['run', 'ORCH-228', 'Pages change without a full reload', 'pin'],
  ['run', 'ORCH-232', 'Insights and usage counts'], ['run', 'ORCH-235', 'Check the links on the help pages'],
  ['run', 'ORCH-240', 'Tidy the release notes'],
  ...['Search in the help pages', 'Export tickets to a table', 'Faster first page', 'Monthly report for sales',
    'Tidy the settings page', 'Spelling check in mails', 'New logo on every page', 'Calendar for the team',
    'Backup check every night'].map((t, i) => ['queue', 'ORCH-' + (205 + 2 * i), t]),
  ...['Survey for customers', 'Opening hours page', 'Newsletter for autumn', 'Price page for schools',
    'Photo page for the shop', 'Welcome mail', 'Order form', 'Holiday plan'].map((t, i) => ['idle', 'ORCH-' + (241 + i), t]),
];
// What the stand-in server kept: one pin to start with.
let barPrefs = { pins: { t_bar228: true }, names: {} };
let barState = {};
// Sessions a step ended (step 31): no run in the state, closed in the sessions list, as orch shows a helper that stopped.
let barEnded = new Set();
// Step 5 (ORCH-701): the tickets that wait carry their open question while barAsk is on, so the layer can answer it;
// a ticket in barAnswered has its question answered.
let barAsk = false;
let barAnswered = new Set();
const BAR_QUESTION = { id: 'q1', digest: 'd-q1', text: 'Keep the old file name when the same file is added twice?',
  options: ['Keep the old name', 'Add a number'], answer: null };
async function liveBarState(page) {
  barPrefs = { pins: { t_bar228: true }, names: {} };
  barEnded = new Set();
  barAsk = false;
  barAnswered = new Set();
  const live = { name: 'focus', label: 'Focus', icon: 'target', active: true, removable: true, shipped: false,
    description: 'A live page for one ticket.', page: { path: '/', label: 'Open Focus', live_session: true },
    dashboard: { label: 'Focus', icon: 'target', order: 20 } };
  const HELPER = { wait: 'you', run: 'working', idle: 'idle' };
  await page.route('**/api/act', async route => {
    const body = route.request().postDataJSON();
    if (!['session.pin', 'session.name'].includes(body.op)) return route.fallback();
    const id = body.args.session;
    if (body.op === 'session.pin') barPrefs.pins[id] = body.args.pinned;
    else if (body.args.name) barPrefs.names[id] = body.args.name; else delete barPrefs.names[id];
    route.fulfill({ json: barState });  // the server answers an action with the page's state
  });
  await page.route(/\/api\/state(\?.*)?$/, async route => {
    const res = await route.fetch();
    if (res.status() !== 200) return route.fulfill({ response: res });
    const st = await res.json();
    const base = (st.tickets || [])[0] || {};
    const extra = BAR_SESSIONS.map(([s, key, title]) => ({ ...base, id: 't_bar' + key.slice(5), key, title,
      status: 'active', checks: [], sessions: [],
      questions: barAsk && s === 'wait' ? [{ ...BAR_QUESTION, answer: barAnswered.has('t_bar' + key.slice(5)) ? BAR_QUESTION.options[0] : null }] : [] }));
    st.tickets = [...(st.tickets || []).filter(t => !String(t.id).startsWith('t_bar')), ...extra];
    st.runs = { ...(st.runs || {}) };
    BAR_SESSIONS.forEach(([s, key]) => {
      if (barEnded.has('t_bar' + key.slice(5))) { delete st.runs['t_bar' + key.slice(5)]; return; }
      st.runs['t_bar' + key.slice(5)] = s === 'queue' ? { running: false, hold: 'Waits for a free place' }
        : { running: true, helper: { state: HELPER[s] }, claim: { agent: 'agent:claude' } };
    });
    st.addons = [...(st.addons || []).filter(a => a.name !== live.name), live];
    st.settings = { ...(st.settings || {}), focus_preview_on: true,
      addons: [...((st.settings || {}).addons || []).filter(a => a.name !== live.name), live] };
    if (Array.isArray(st.tickets) && st.workspace) barState = st;  // a full state, not the poll's "unchanged"
    route.fulfill({ response: res, json: st });
  });
  await page.route(/\/api\/sessions(\?.*)?$/, route => route.fulfill({ json: { sessions: barSessions(), lines: 8, age_ms: 0 } }));
  // the stand-in tickets have no earlier sessions or files on the test server (it would answer 404)
  await page.route(/\/api\/(sessions|artifacts)\/t_bar\d+/, route => route.fulfill({ json: route.request().url().includes('/artifacts/') ? { files: [] } : { available: true, sessions: [] } }));
}
// The same 24 sessions as the live sessions API gives them (the shape in workspace-addons/dashboard/.../sessions.py).
const BAR_STATUS = { wait: 'needs-you', run: 'working', queue: 'in-line', idle: 'idle', ended: 'closed' };
const BAR_WORD = { wait: 'Waits for you', run: 'Working', queue: 'In line', idle: 'Idle', ended: 'No session' };
function barSessions() {
  return BAR_SESSIONS.map(([s0, key, title], i) => {
    const s = barEnded.has('t_bar' + key.slice(5)) ? 'ended' : s0;
    const live = s !== 'queue' && s !== 'ended';
    return { id: 't_bar' + key.slice(5), key, title, status: BAR_STATUS[s], word: BAR_WORD[s],
      detail: s === 'run' ? 'Running the tests' : '', waiting_on: [],
      question: s === 'wait' ? 'Keep the old file name when the same file is added twice?' : null,
      lines: live ? ['⏺ Bash(node --test tests/attach.test.js)', '  ⎿ ✔ adds a picture to a ticket (38 ms)',
        '  ⎿ ✔ adds a note below the files (12 ms)', '⏺ ' + title + ': step ' + (2 + (i % 3)) + ' of 5'] : [],
      tool: live ? 'Helper' : null, model: i % 2 ? 'Opus' : 'Sonnet', mode: live ? 'live' : null,
      opened_at: null, open_seconds: live ? (20 + 3 * i) * 60 : null, idle_seconds: s === 'idle' ? 18 * 60 : null,
      closes_in_seconds: s === 'idle' ? 42 * 60 : live ? 3600 : null, last_at: null, kind: '',
      pinned: barPrefs.pins['t_bar' + key.slice(5)] === true, name: barPrefs.names['t_bar' + key.slice(5)] || null };
  });
}
// Step 16: every pane says what its session does, its last lines, tool and model, how long it is open and how long it
// stays, from the live sessions API, and keeps it current without a repaint (the keyboard place stays).
async function paneData(page, dash) {
  await liveBarState(page);
  await page.goto(dash + '/#home');
  await mainHasText(page);
  await page.waitForSelector('#live-bar :is([data-lbar-open="t_bar238"], [data-lbar-list="wait"])', { timeout: 10000 });
  if (!(await page.$('#live-bar [data-lbar-open="t_bar238"]'))) await page.click('#live-bar [data-lbar-list="wait"]');  // a phone: counts only
  await page.click('#live-bar [data-lbar-open="t_bar238"]');
  const body = '#live-dock .live-pane[data-session="t_bar238"] [data-live-body]';
  await page.waitForFunction(b => /Keep the old file name/.test(document.querySelector(b)?.textContent || ''), body, { timeout: 10000 });
  const got = await page.$eval(body, el => ({ now: el.querySelector('[data-live-now]').textContent,
    lines: el.querySelector('[data-live-lines]').textContent, meta: el.querySelector('[data-live-meta]').textContent }));
  if (!/step \d of 5/.test(got.lines)) throw new Error('the pane does not show the last lines: ' + got.lines);
  if (!/^Helper · Sonnet · open \d+ min · stays warm while it waits for you$/.test(got.meta)) throw new Error('the pane meta reads: ' + got.meta);
  const link = `${body} [data-key="live-open-ticket"]`;
  await page.focus(link);
  await page.evaluate(() => window.LiveSessions.refresh());
  await page.waitForTimeout(300);
  if (!(await page.evaluate(l => document.activeElement === document.querySelector(l), link))) throw new Error('a new answer moved the keyboard place');
  // ORCH-679 (checked since ORCH-701): Stop in the pane itself sends the ticket page's run.stop (caught before orch);
  // an idle helper's button says Stop idle helper
  const stops = [];
  await page.route('**/api/act', async route => {
    const b = route.request().postDataJSON();
    if (b.op !== 'run.stop') return route.fallback();
    stops.push(b.args);
    route.fulfill({ json: barState });
  });
  const stop = `${body} [data-key="live-stop"]`;
  const word = (await page.textContent(stop).catch(() => '')).trim();
  if (word !== 'Stop') throw new Error(`the pane of a helper that waits has no Stop (it says "${word}")`);
  await page.click(stop);
  for (let i = 0; i < 20 && !stops.length; i++) await page.waitForTimeout(100);
  if (stops.length !== 1 || stops[0].ticket !== 't_bar238') throw new Error('Stop did not ask orch to stop that helper: ' + JSON.stringify(stops));
  await page.evaluate(() => window.LiveLayer.open('t_bar241'));
  const idle = '#live-dock .live-pane[data-session="t_bar241"] [data-key="live-stop"]';
  await page.waitForSelector(idle, { timeout: 5000 });
  if ((await page.textContent(idle)).trim() !== 'Stop idle helper') throw new Error('an idle helper\'s pane does not say Stop idle helper');
  await page.evaluate(() => window.LiveLayer.open('t_bar238'));
  await noSideways(page);
}

// Step 13 until the layer exists (crew task layer replaces the stand-in with the real layer): a small open dialog with
// a typed, unsent message in the keep place. Page changes by real links, Back, Forward, a deep link and a reload.
async function staysOpen(page, dash) {
  const go = async hash => {
    await page.locator(`a[href="${hash}"]:visible`).first().click();
    await page.waitForFunction(h => location.hash === h, hash, { timeout: 10000 });
    await mainHasText(page);
  };
  const kept = async where => {
    const st = await page.evaluate(() => ({ mark: window.softMark, open: !!document.querySelector('#keep dialog[open]'),
      typed: document.getElementById('soft-typed')?.value, hash: location.hash }));
    if (st.mark !== 'same page') throw new Error(`${where}: the page loaded again`);
    if (!st.open) throw new Error(`${where}: the dialog in the keep place closed`);
    if (st.typed !== 'Not sent yet') throw new Error(`${where}: the typed text is gone`);
    return st.hash;
  };
  await previewOn(page);
  await page.goto(dash + '/#tickets');  // a deep link
  await mainHasText(page);
  // the steps share one browser: start with the layer at the bar, not where step 10 left it (it is kept per browser)
  await page.evaluate(() => { try { Object.keys(localStorage).filter(k => k.indexOf('orch.live.layer') === 0).forEach(k => localStorage.removeItem(k)); } catch (e) { /* none */ } });
  await page.reload();  // reload keeps the page
  await mainHasText(page);
  if (await page.evaluate(() => location.hash) !== '#tickets') throw new Error('reload left the page');
  await page.evaluate(() => {
    window.softMark = 'same page';
    const d = document.createElement('dialog'), t = document.createElement('textarea'), a = document.createElement('a');
    d.style.cssText = 'position:fixed;inset:35% 8px auto auto;margin:0;width:200px';
    t.id = 'soft-typed'; t.setAttribute('aria-label', 'Message');
    a.href = '/#tickets'; a.id = 'soft-full-link'; a.textContent = 'Tickets';
    d.append(t, a);
    window.orchKeep.mount(d);
    d.show();
  });
  await page.fill('#soft-typed', 'Not sent yet');
  await go('#home');
  await kept('Home');
  await go('#review');
  await kept('Review');
  await page.click('#soft-full-link');  // "/#tickets" would load the page again without the soft change
  await page.waitForFunction(() => location.hash === '#tickets', null, { timeout: 10000 });
  await mainHasText(page);
  await kept('Tickets');
  await page.goBack();
  if (await kept('Back') !== '#review') throw new Error('Back did not go to Review');
  await page.goBack();
  if (await kept('Back twice') !== '#home') throw new Error('Back twice did not go to Home');
  await page.goForward();
  if (await kept('Forward') !== '#review') throw new Error('Forward did not go to Review');
  await mainHasText(page);
  await noSideways(page);
}

// The bar is one row that never wraps and stays inside the page.
async function barIsOneRow(page) {
  const r = await page.evaluate(() => {
    const bar = document.getElementById('live-bar'), sw = bar && bar.querySelector('.lbar-sw');
    if (!bar) return { missing: true };
    const tops = [...sw.children].map(c => Math.round(c.getBoundingClientRect().top));
    const box = bar.getBoundingClientRect();
    return { rows: new Set(tops).size, cut: sw.scrollWidth - sw.clientWidth, h: box.height, bottom: box.bottom, vh: innerHeight };
  });
  if (r.missing) throw new Error('the bar is not under the page');
  if (r.rows > 1 || r.cut > 1) throw new Error(`the bar wraps or cuts (${r.rows} rows, ${r.cut} px cut)`);
  if (r.h > 64) throw new Error(`the bar is ${r.h} px high, more than one row`);
  if (r.bottom > r.vh + 1) throw new Error('the bar is below the screen');
}

// The new page with Preview on, for the steps after step 3: the same dressing of the page's state as previewSwitch
// (the live-session add-on and the setting), plus the one ticket of the test workspace marked as having a working helper.
async function livePreview(page) {
  let one = null;
  const live = { name: 'focus', label: 'Focus', icon: 'target', active: true, removable: true, shipped: false,
    description: 'A live page for one ticket.', page: { path: '/', label: 'Open Focus', live_session: true },
    dashboard: { label: 'Focus', icon: 'target', order: 20 } };
  await page.route(/\/api\/state(\?.*)?$/, async route => {
    const res = await route.fetch();
    if (res.status() !== 200) return route.fulfill({ response: res });
    const st = await res.json();
    st.addons = [...(st.addons || []).filter(a => a.name !== live.name), live];
    st.settings = { ...(st.settings || {}), focus_preview_on: true };
    const first = (st.tickets || [])[0];
    if (first) st.runs = { ...(st.runs || {}), [first.id]: { running: true, state: 'alive' } };
    if (first && !first.key) first.key = 'ORCH-238';  // the test ticket has no key; the pane shows the key, never the raw id
    if (first) one = { id: first.id, key: first.key, title: first.title };
    route.fulfill({ response: res, json: st });
  });
  // the live sessions API (ORCH-359) says the same: the first ticket has a working session
  await page.route(/\/api\/sessions(\?.*)?$/, route => route.fulfill({ json: { lines: 8, age_ms: 0, sessions: one ? [{ ...one,
    status: 'working', word: 'Working', detail: 'Running the tests', waiting_on: [], question: null, lines: ['⏺ Running the tests'],
    tool: 'Helper', model: 'Opus', mode: 'live', opened_at: null, open_seconds: 1500, idle_seconds: null, closes_in_seconds: 3600,
    last_at: null }] : [] } }));
  await page.route('**/addon/focus/**', route => route.fulfill({ contentType: 'text/html',
    body: '<!doctype html><title>Focus</title><main>Today\'s Focus</main>' }));
}

// Step 10: the layer in every place, kept across a page change and a reload.
async function layer(page, dash, width) {
  const phone = width <= 720;
  const panel = m => `#live-dock[data-mode="${m}"] .live-panel[data-mode="${m}"]`;
  const press = async key => { await page.keyboard.press(key); await page.waitForTimeout(50); };
  await livePreview(page);
  // start with nothing kept, without an extra page load (the reload below must keep what this step chose)
  await page.addInitScript(() => { try { if (!sessionStorage.getItem('fd10')) { Object.keys(localStorage).filter(k => k.indexOf('orch.live.layer') === 0).forEach(k => localStorage.removeItem(k)); sessionStorage.setItem('fd10', '1'); } } catch (e) { /* none */ } });
  await page.goto(dash + '/#home');
  await mainHasText(page);
  // the bar: the bar task's #live-bar when it is there, else the layer's own minimal bar
  await page.waitForSelector('#live-dock[data-mode="bar"] :is(#live-bar, [data-key="live-bar"])', { timeout: 10000 });
  if (await page.$('[data-key="live-panel"]')) throw new Error('the layer opened by itself');
  // open from the bar: at the bottom, the page stays usable behind it
  await page.click('[data-key="live-open"]');
  await page.waitForSelector(panel('bottom'), { timeout: 5000 });
  await page.waitForSelector('[data-key="live-pane"] [data-key="live-open-ticket"]');
  if (await page.$eval('[data-key="live-pane"] .live-ph', el => /\bt_[A-Za-z0-9]+/.test(el.textContent))) throw new Error('the pane shows the raw ticket id');
  if (!await page.$eval('[data-key="live-pane"] .key', el => el.textContent.trim() === 'ORCH-238')) throw new Error('the pane does not show the ticket key');
  // the page changes, the layer stays (the same element, never painted again)
  await page.$eval('[data-key="live-panel"]', el => { el.dataset.kept = '1'; });
  for (const hash of ['#tickets', '#review', '#home']) {
    await page.evaluate(h => { location.hash = h; }, hash);
    await mainHasText(page);
  }
  if (!await page.$('[data-key="live-panel"][data-kept="1"]')) throw new Error('the layer did not stay open when the page changed');
  // place: right (a phone has no right; it stays at the bottom)
  await page.click('[data-key="live-place"]');
  await page.waitForSelector('[data-key="live-place-menu"]');
  const right = await page.$('[data-key="live-place-menu"] [data-mode="right"]');
  if (phone && right) throw new Error('a phone offers the right edge');
  if (!phone) {
    await right.click();
    await page.waitForSelector(panel('right'), { timeout: 5000 });
    const [box, main] = await page.evaluate(() => [document.querySelector('.live-panel').getBoundingClientRect().left,
      document.querySelector('#content').getBoundingClientRect().right]);
    if (main > box + 1) throw new Error('the right panel covers the page');
  } else await press('Escape');
  const docked = phone ? 'bottom' : 'right';
  // full screen; Esc goes back one step at a time: full screen, the panel, the bar
  await page.click('[data-key="live-full"]');
  await page.waitForSelector(panel('full'), { timeout: 5000 });
  // the page behind full screen takes no keyboard (ORCH-340)
  if (!(await page.evaluate(() => document.getElementById('content').inert))) throw new Error('the page behind full screen still takes Tab');
  await press('Escape');
  await page.waitForSelector(panel(docked), { timeout: 5000 });
  if (await page.evaluate(() => document.getElementById('content').inert)) throw new Error('the page stayed inert after full screen');
  await press('Escape');
  await page.waitForSelector('#live-dock[data-mode="bar"]', { timeout: 5000 });
  if (await page.$('[data-key="live-panel"]')) throw new Error('Esc left the panel open');
  // Open brings it back where it was; minimise leaves only the bar
  await page.click('[data-key="live-open"]');
  await page.waitForSelector(panel(docked), { timeout: 5000 });
  await page.click('[data-key="live-min"]');
  await page.waitForSelector('#live-dock[data-mode="bar"]', { timeout: 5000 });
  // closed to the side: a slim edge; it opens where it was last
  await page.click('[data-key="live-place"]');
  await page.click('[data-key="live-place-menu"] [data-mode="side"]');
  await page.waitForSelector('#live-dock[data-mode="side"] [data-key="live-edge"]', { timeout: 5000 });
  if (await page.isVisible('#live-dock :is(#live-bar, [data-key="live-bar"])')) throw new Error('the bar still shows with the layer closed to the side');
  await page.click('[data-key="live-edge"]');
  await page.waitForSelector(panel(docked), { timeout: 5000 });
  // size by keyboard, then a reload: same place, same size
  await page.focus('[data-live-grip]');
  await press(phone ? 'ArrowUp' : 'ArrowLeft');
  await press(phone ? 'ArrowUp' : 'ArrowLeft');
  const size = () => page.$eval('.live-panel', (el, w) => Math.round(w ? el.offsetWidth : el.offsetHeight), !phone);
  const before = await size();
  await page.reload();
  await mainHasText(page);
  await page.waitForSelector(panel(docked), { timeout: 10000 });
  const after = await size();
  if (Math.abs(after - before) > 1) throw new Error(`the size was not kept (${before} px before the reload, ${after} px after)`);
  // the picture: the place menu open, as in draft D
  await page.click('[data-key="live-place"]');
  await page.waitForSelector('[data-key="live-place-menu"]');
  await noSideways(page);
}

// Step 12: the split. The test workspace has one ticket, so the step uses the bar's 24 sessions of draft D (step 9).
// Every pane has pin, add beside, place, minimise and close; narrow panes keep pin and place in More (draft D).
// Step 26 (ORCH-363): the History tab of a pane lists the ticket's earlier sessions (the last 10, newest first) and
// Reopen starts the helper on one. The list comes from GET /api/sessions/<ticket>; here it is fake data, and the
// Reopen action is caught before orch so nothing starts. The ticket has no working helper, so Reopen can be pressed.
async function history(page, dash) {
  const live = { name: 'focus', label: 'Focus', icon: 'target', active: true, removable: true, shipped: false,
    description: 'A live page for one ticket.', page: { path: '/', label: 'Open Focus', live_session: true },
    dashboard: { label: 'Focus', icon: 'target', order: 20 } };
  let tid = '', st0 = null;
  await page.route(/\/api\/state(\?.*)?$/, async route => {
    const res = await route.fetch();
    if (res.status() !== 200) return route.fulfill({ response: res });
    const st = await res.json();
    st.addons = [...(st.addons || []).filter(a => a.name !== live.name), live];
    st.settings = { ...(st.settings || {}), focus_preview_on: true };
    const first = (st.tickets || [])[0];
    if (first) { tid = first.id; if (!first.key) first.key = 'ORCH-189'; st0 = st; }  // a full state, for the fake Reopen answer
    route.fulfill({ response: res, json: st });
  });
  await page.route('**/addon/focus/**', route => route.fulfill({ contentType: 'text/html',
    body: '<!doctype html><title>Focus</title><main>Today\'s Focus</main>' }));
  const at = h => new Date(Date.now() - h * 3600e3).toISOString();
  const rows = [
    { id: 's-now', label: 'Helper', last_used: at(1), title: 'Write the summary from the survey answers', turns: 24, current: true, reopenable: false },
    { id: 's-mon', label: 'Helper', last_used: at(30), title: 'Read the survey answers and group them', turns: 12, current: false, reopenable: true },
    { id: 's-old', label: 'Helper', last_used: at(200), title: 'First draft of the newsletter', turns: 1, current: false, reopenable: true },
    { id: 's-gone', label: 'Helper', last_used: at(400), title: '', turns: 0, current: false, reopenable: false },
  ];
  await page.route(/\/api\/sessions\/t_[a-z0-9]+$/, route => route.fulfill({ json: { available: true, sessions: rows } }));
  let asked = null;
  await page.route('**/api/act', async route => {
    const body = route.request().postDataJSON();
    if (body.op !== 'session.reopen') return route.fallback();
    asked = body.args;
    route.fulfill({ json: st0 });
  });
  await page.addInitScript(() => { try { Object.keys(localStorage).filter(k => k.indexOf('orch.live.layer') === 0).forEach(k => localStorage.removeItem(k)); } catch (e) { /* none */ } });
  await page.goto(dash + '/#home');
  await mainHasText(page);
  await page.waitForFunction(() => window.LiveLayer && document.getElementById('live-dock'), null, { timeout: 10000 });
  await page.evaluate(id => window.LiveLayer.open(id), tid);
  const pane = '#live-dock .live-pane';
  // History is a button in the pane header; a narrow pane (the phone) has it in its More menu
  const toggle = async (dom = false) => {
    await page.waitForSelector(pane + ' :is([data-key="live-history"], [data-key="live-pane-more"])', { timeout: 5000 });
    const press = sel => dom ? page.$eval(sel, el => el.click()) : page.click(sel);
    if (await page.$(pane + ' [data-key="live-history"]')) return press(pane + ' [data-key="live-history"]');
    await press(pane + ' [data-key="live-pane-more"]');
    await page.waitForSelector(pane + ' [data-key="live-history-item"]', { timeout: 5000 });
    await press(pane + ' [data-key="live-history-item"]');
  };
  await toggle();
  await page.waitForSelector(pane + ' .live-hist-row', { timeout: 5000 });
  if (await page.$(pane + ' [data-key="live-history"][aria-pressed="false"]')) throw new Error('History is not marked as open');
  if (await page.$(pane + ' [data-key="live-more-menu"]')) throw new Error('the More menu stayed open after History');
  const seen = await page.$$eval(pane + ' .live-hist-row', els => els.map(el => ({
    t: el.querySelector('.live-hist-t').textContent, f: el.querySelector('.live-hist-f').textContent,
    use: !!el.querySelector('.chip'), reopen: !!el.querySelector('button'), off: !!el.querySelector('button[disabled]') })));
  if (seen.length !== 4) throw new Error(`the History tab shows ${seen.length} sessions, not 4`);
  if (!seen[0].use || seen[0].reopen) throw new Error('the session in use is not marked In use');
  if (!seen[1].reopen || !seen[2].reopen || seen[1].off) throw new Error('an earlier session has no Reopen');
  if (seen[3].reopen || !/Not on this computer/.test(seen[3].f)) throw new Error('a session that is not on this computer offers Reopen');
  if (seen[2].f.indexOf('1 message ') !== 0) throw new Error(`the plural is wrong: ${seen[2].f}`);
  await noSideways(page);
  await page.click(pane + ' .live-hist-row:nth-child(2) [data-live-hist="reopen"]');
  await page.waitForFunction(() => !document.querySelector('#live-dock .live-pb-hist'), null, { timeout: 5000 });
  if (!asked || asked.session !== 's-mon' || asked.ticket !== tid) throw new Error('Reopen did not ask orch for that session: ' + JSON.stringify(asked));
  // open it again for the picture (the "continues that conversation" toast may sit over the pane's corner)
  await toggle(true);
  await page.waitForSelector(pane + ' .live-hist-row', { timeout: 5000 });
}

// Step 14 (ORCH-362): the Start choice of a ticket with no helper. Continue the last conversation, a fresh start on a
// tool and model (the usual ones preselected), or reopen an earlier session; the helper places in use and the line.
// The tools, places and earlier sessions are fake data; run.start and ticket.model are caught before orch, so
// nothing starts. Then every place is taken: the line shows and a start answers that it waits in line.
async function startChoice(page, dash) {
  const live = { name: 'focus', label: 'Focus', icon: 'target', active: true, removable: true, shipped: false,
    description: 'A live page for one ticket.', page: { path: '/', label: 'Open Focus', live_session: true },
    dashboard: { label: 'Focus', icon: 'target', order: 20 } };
  let tid = '', st0 = null, full = false;
  const others = n => Object.fromEntries(Array.from({ length: n }, (_, i) => ['t_other' + i, { running: true, claim: { mode: 'live' } }]));
  await page.route(/\/api\/state(\?.*)?$/, async route => {
    // always the full state (never "unchanged since"), so the fake places below reach the page
    const res = await route.fetch({ url: route.request().url().replace(/\?.*$/, '') });
    if (res.status() !== 200) return route.fulfill({ response: res });
    const st = await res.json();
    st.rev = 'fake-' + (full ? 'full' : 'free');
    st.addons = [...(st.addons || []).filter(a => a.name !== live.name), live];
    st.settings = { ...(st.settings || {}), focus_preview_on: true, live_max: full ? 4 : 6,
      agents: [{ name: 'claude', label: 'Claude Code', found: true, chosen: true, models: true },
        { name: 'codex', label: 'Codex', found: true, chosen: false, models: false }] };
    const first = (st.tickets || [])[0];
    if (first) { tid = first.id; if (!first.key) first.key = 'ORCH-189'; first.model = { name: 'sonnet', by: 'orch' }; }
    st.runs = { ...Object.fromEntries(Object.entries(st.runs || {}).filter(([k]) => k !== tid)), ...others(4) };
    st.start_line = full ? { waiting: ['t_other8', 't_other9'], why: '4 helpers are working at once, the most you allowed', limit: 4 } : null;
    st0 = st;
    route.fulfill({ response: res, json: st });
  });
  await page.route('**/addon/focus/**', route => route.fulfill({ contentType: 'text/html',
    body: '<!doctype html><title>Focus</title><main>Today\'s Focus</main>' }));
  const at = h => new Date(Date.now() - h * 3600e3).toISOString();
  const rows = [
    { id: 's-mon', label: 'Claude Code', last_used: at(30), title: 'Read the survey answers and group them', turns: 12, current: false, reopenable: true },
    { id: 's-old', label: 'Claude Code', last_used: at(200), title: 'First draft of the newsletter', turns: 1, current: false, reopenable: true },
  ];
  await page.route(/\/api\/sessions\/t_[a-z0-9]+$/, route => route.fulfill({ json: { available: true, sessions: rows } }));
  const asked = [];
  await page.route('**/api/act', async route => {
    const body = route.request().postDataJSON();
    if (!['run.start', 'ticket.model', 'session.reopen'].includes(body.op)) return route.continue();
    asked.push(body);
    if (full && body.op === 'run.start') return route.fulfill({ status: 422, contentType: 'text/plain',
      body: '4 helpers are working at once, the most you allowed. ORCH-189 waits in line and starts when one is finished.' });
    route.fulfill({ json: st0 });
  });
  await page.addInitScript(() => { try { localStorage.removeItem('orch.live.layer'); } catch (e) { /* none */ } });
  await page.goto(dash + '/#home');
  await mainHasText(page);
  await page.waitForFunction(() => window.LiveLayer && document.getElementById('live-dock'), null, { timeout: 10000 });
  await page.evaluate(id => window.LiveLayer.open(id), tid);
  // ORCH-475: the pane shows the kit's Start choice (kit/start-choice.js inline): compact rows, tool and model as small
  // pickers, the newest earlier session with Show more; after a start it stays Starting… and greys every choice with why.
  const pane = '#live-dock .live-pane [data-key="live-start"]';
  await page.waitForSelector(pane + ' [data-key="start-earlier"] .live-hist-row', { timeout: 8000 });
  const seen = await page.$eval(pane, el => ({
    places: el.querySelector('.live-places')?.textContent || '',
    cont: el.querySelector('[data-key="start-continue"]')?.textContent || '',
    tool: (s => s ? [s.value, [...s.options].map(o => o.textContent)] : null)(el.querySelector('select[data-start-pick="tool"]')),
    model: el.querySelector('select[data-start-pick="model"]')?.value || '',
    earlier: el.querySelectorAll('[data-key="start-earlier"] .live-hist-row [data-start="reopen"]').length }));
  if (seen.places !== '4 of 6 places in use') throw new Error('places: ' + seen.places);
  if (!/Continue where it stopped/.test(seen.cont) || !/from /.test(seen.cont)) throw new Error('no Continue with the last conversation: ' + seen.cont);
  if (JSON.stringify(seen.tool) !== JSON.stringify(['claude', ['Claude Code', 'Codex']])) throw new Error('tools: ' + JSON.stringify(seen.tool));
  if (seen.model !== 'sonnet') throw new Error('the usual model is not preselected: ' + seen.model);
  if (seen.earlier !== 2) throw new Error(`${seen.earlier} earlier sessions offer Reopen, not 2`);
  await noSideways(page);
  // one click starts fresh with the usual tool and model: only run.start --fresh goes to orch
  await page.click(pane + ' [data-start="fresh"]');
  await page.waitForTimeout(500);
  if (asked.length !== 1 || asked[0].op !== 'run.start' || !asked[0].args.fresh || asked[0].args.agent) throw new Error('one-click fresh start: ' + JSON.stringify(asked));
  // the faked start never shows a helper: the choice stays Starting… and every choice is greyed and says why
  const busy = await page.$eval(pane, el => ({
    busy: !!el.querySelector('.live-start[aria-busy="true"]'),
    greyed: [...el.querySelectorAll('[data-start="continue"],[data-start="fresh"]')].every(b => b.disabled && /The helper is starting\./.test(document.getElementById(b.getAttribute('aria-describedby'))?.textContent || '')) }));
  if (!busy.busy || !busy.greyed) throw new Error('after a start the choice is not Starting… with reasons: ' + JSON.stringify(busy));
  await page.click(pane + ' [data-start="continue"]', { force: true, timeout: 2000 }).catch(() => {});
  if (asked.length !== 1) throw new Error('a second click while Starting… sent another start: ' + JSON.stringify(asked));
  await noSideways(page);
}

// Step 16, second part (ORCH-362): the model button at the top of a working session's pane opens the model choice;
// the pane's line (ORCH-359) says tool, model, open time and when it closes. The running helper and its live data are
// fake and ticket.model is caught before orch.
async function toolModel(page, dash) {
  const live = { name: 'focus', label: 'Focus', icon: 'target', active: true, removable: true, shipped: false,
    description: 'A live page for one ticket.', page: { path: '/', label: 'Open Focus', live_session: true },
    dashboard: { label: 'Focus', icon: 'target', order: 20 } };
  let tid = '', st0 = null;
  await page.route(/\/api\/state(\?.*)?$/, async route => {
    const res = await route.fetch({ url: route.request().url().replace(/\?.*$/, '') });
    if (res.status() !== 200) return route.fulfill({ response: res });
    const st = await res.json();
    st.rev = 'fake-tool-model';
    st.addons = [...(st.addons || []).filter(a => a.name !== live.name), live];
    st.settings = { ...(st.settings || {}), focus_preview_on: true,
      agents: [{ name: 'claude', label: 'Claude Code', found: true, chosen: true, models: true }] };
    const first = (st.tickets || [])[0];
    if (first) {
      tid = first.id; if (!first.key) first.key = 'ORCH-247';
      first.model = { name: 'opus', by: 'orch' };
      first.warmth = { seconds_left: 42 * 60 };
      st.runs = { ...(st.runs || {}), [tid]: { ticket: tid, running: true, state: 'alive', pending: [],
        claim: { agent: 'claude', mode: 'live', run: 'r-fake', started_at: new Date(Date.now() - 96 * 60e3).toISOString(),
          live: { state: 'idle', since: new Date(Date.now() - 18 * 60e3).toISOString() } } } };
    }
    st0 = st;
    route.fulfill({ response: res, json: st });
  });
  await page.route('**/addon/focus/**', route => route.fulfill({ contentType: 'text/html',
    body: '<!doctype html><title>Focus</title><main>Today\'s Focus</main>' }));
  await page.route(/\/api\/sessions(\?.*)?$/, route => route.fulfill({ json: { lines: 8, age_ms: 0, sessions: tid ? [{ id: tid,
    key: 'ORCH-247', title: 'Tool and model', status: 'idle', word: 'Idle', detail: '', waiting_on: [], question: null, lines: [],
    tool: 'Claude Code', model: 'Opus', mode: 'live', opened_at: null, open_seconds: 96 * 60, idle_seconds: 18 * 60,
    closes_in_seconds: 42 * 60, last_at: null }] : [] } }));
  const asked = [];
  await page.route('**/api/act', async route => {
    const body = route.request().postDataJSON();
    if (body.op !== 'ticket.model') return route.continue();
    asked.push(body);
    route.fulfill({ json: st0 });
  });
  await page.addInitScript(() => { try { localStorage.removeItem('orch.live.layer'); } catch (e) { /* none */ } });
  await page.goto(dash + '/#home');
  await mainHasText(page);
  await page.waitForFunction(() => window.LiveLayer && document.getElementById('live-dock'), null, { timeout: 10000 });
  await page.evaluate(id => window.LiveLayer.open(id), tid);
  const row = '#live-dock .live-pane [data-key="live-model-row"]';
  await page.waitForSelector(row, { timeout: 8000 });
  const text = await page.$eval(row, el => el.textContent);
  if (text !== 'Model: Opus') throw new Error('the model button reads: ' + text);
  const meta = '#live-dock .live-pane [data-live-meta]';
  await page.waitForFunction(m => /open/.test(document.querySelector(m)?.textContent || ''), meta, { timeout: 8000 });
  const line = await page.$eval(meta, el => el.textContent);
  if (line !== 'Claude Code · Opus · open 1 h 36 min · closes in 42 min if left idle') throw new Error('the pane line reads: ' + line);
  if (await page.$('#live-dock [data-key="live-start"]')) throw new Error('a working session offers the Start choice');
  await noSideways(page);
  await page.click(row + ' [data-key="live-model"]');
  await page.waitForSelector('#live-dock [data-key="live-model-menu"]', { timeout: 3000 });
  const menu = await page.$eval('#live-dock [data-key="live-model-menu"]', el => el.textContent);
  if (!/Opus \(now\)/.test(menu) || !/applies when the helper finishes its current step/.test(menu)) throw new Error('model menu: ' + menu);
  await page.click('#live-dock [data-live-model="haiku"]');
  await page.waitForFunction(() => !document.querySelector('#live-dock [data-key="live-model-menu"]'), null, { timeout: 3000 });
  if (asked.length !== 1 || asked[0].args.model !== 'haiku' || asked[0].args.ticket !== tid) throw new Error('the new model did not go to orch: ' + JSON.stringify(asked));
  // open the menu again for the picture
  await page.click(row + ' [data-key="live-model"]');
  await page.waitForSelector('#live-dock [data-key="live-model-menu"]', { timeout: 3000 });
}

async function split(page, dash, width) {
  const phone = width <= 720;
  const panes = () => page.$$eval('#live-dock .live-pane', els => els.map(el => {
    const r = el.getBoundingClientRect();
    return { key: el.dataset.session, on: el.dataset.on !== undefined, x: Math.round(r.left), y: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height) };
  }));
  const count = async n => {
    await page.waitForFunction(k => document.querySelectorAll('#live-dock .live-pane').length === k, n, { timeout: 5000 });
    return panes();
  };
  const inPane = (key, what) => `#live-dock .live-pane[data-session="${key}"] [data-key="${what}"]`;
  // pin, add beside, place, minimise and close on every pane (pin and place through More when the pane is narrow)
  const controls = async () => {
    for (const p of await panes()) {
      const has = async what => !!await page.$(inPane(p.key, what));
      const more = await has('live-pane-more');
      if (!more && !(await has('live-pin') && await has('live-pane-place'))) throw new Error(`the pane of ${p.key} has no pin or place`);
      if (!phone && !await has('live-beside')) throw new Error(`the pane of ${p.key} has no add beside`);
      if (!await has('live-min') || !await has('live-close')) throw new Error(`the pane of ${p.key} has no minimise or close`);
      if (more) {
        await page.click(inPane(p.key, 'live-pane-more'));
        await page.waitForSelector('[data-key="live-more-menu"] [data-key="live-pin"]', { timeout: 5000 });
        if (!await page.$('[data-key="live-more-menu"] [data-live="place"][data-mode="bottom"]')) throw new Error(`More of ${p.key} has no place`);
        await page.keyboard.press('Escape');
        await page.waitForSelector('[data-key="live-more-menu"]', { state: 'detached', timeout: 5000 });
      }
    }
  };
  const sideBySide = (list, stacked) => list.every((p, i) => !i || (stacked ? p.y > list[i - 1].y && p.x === list[0].x : p.x > list[i - 1].x && p.y === list[0].y));
  await liveBarState(page);
  await page.goto(dash + '/#home');
  await page.evaluate(() => { try { Object.keys(localStorage).filter(k => k.indexOf('orch.live.layer') === 0).forEach(k => localStorage.removeItem(k)); } catch (e) { /* none */ } });
  await page.reload();
  await mainHasText(page);
  await page.waitForSelector('#live-dock[data-mode="bar"] #live-bar [data-key="live-open"]', { timeout: 10000 });
  await page.click('[data-key="live-open"]');
  let list = await count(1);
  await controls();
  if (phone) {
    // a phone shows one session at a time: no add beside; a second session from the bar takes the pane
    if (await page.$('[data-key="live-beside"]')) throw new Error('a phone offers add beside');
    await page.evaluate(() => window.LiveLayer.beside('t_bar232'));
    list = await count(1);
    if (list[0].key !== 't_bar232') throw new Error('on a phone the second session does not take the pane');
  } else {
    // Add beside twice: two, then three panes next to each other; the third is the most
    await page.click('[data-key="live-beside"]');
    list = await count(2);
    if (!sideBySide(list)) throw new Error('two panes do not sit next to each other');
    await page.click(inPane(list[0].key, 'live-beside'));
    list = await count(3);
    if (!sideBySide(list)) throw new Error('three panes do not sit next to each other');
    if (!list[2].on || list.filter(p => p.on).length !== 1) throw new Error('the new pane is not the selected one');
    if (!await page.$eval(inPane(list[0].key, 'live-beside'), b => b.disabled)) throw new Error('add beside still works with three panes');
    await controls();
  }
  // the split stays while the page changes (the same element, never painted again)
  await page.$eval('[data-key="live-panel"]', el => { el.dataset.kept = '1'; });
  for (const hash of ['#tickets', '#review', '#home']) {
    await page.evaluate(h => { location.hash = h; }, hash);
    await mainHasText(page);
  }
  if (!await page.$('[data-key="live-panel"][data-kept="1"]')) throw new Error('the split did not stay when the page changed');
  if ((await panes()).length !== list.length) throw new Error('the split lost a pane when the page changed');
  // pin one pane
  const one = list[0].key;
  if (await page.$(inPane(one, 'live-pane-more'))) {
    await page.click(inPane(one, 'live-pane-more'));
    await page.click('[data-key="live-more-menu"] [data-key="live-pin"]');
  } else await page.click(inPane(one, 'live-pin'));
  await page.waitForFunction(k => window.LiveSessions.pins.includes(k), one, { timeout: 5000 });
  if (!await page.evaluate(k => window.LiveLayer.pins.includes(k), one)) throw new Error('the pin was not kept');
  // place from a pane: on the right the panes stack; then back to the bottom (a phone has no right)
  const place = async mode => {
    if (await page.$(inPane(one, 'live-pane-more'))) await page.click(inPane(one, 'live-pane-more'));
    else await page.click(inPane(one, 'live-pane-place'));
    const opt = await page.$(`#live-dock .live-pane .live-pop [data-live="place"][data-mode="${mode}"]`);
    if (!opt) return false;
    await opt.click();
    await page.waitForSelector(`#live-dock[data-mode="${mode}"] .live-panel[data-mode="${mode}"]`, { timeout: 5000 });
    return true;
  };
  if (await place('right') === phone) throw new Error(phone ? 'a phone offers the right edge' : 'the pane has no right place');
  if (!phone) {
    if (!sideBySide(await panes(), true)) throw new Error('on the right the panes are not stacked');
    await place('bottom');
  } else await page.keyboard.press('Escape');
  // minimise to the bar; Open brings the split back
  await page.click(inPane(one, 'live-min'));
  await page.waitForSelector('#live-dock[data-mode="bar"]', { timeout: 5000 });
  await page.click('[data-key="live-open"]');
  list = await count(list.length);
  // close one pane: the others take its room
  if (!phone) {
    const room = list.reduce((a, p) => a + p.w, 0), gone = list[1].key;
    await page.click(inPane(gone, 'live-close'));
    const left = await count(2);
    if (left.some(p => p.key === gone)) throw new Error('the closed pane is still there');
    const now = left.reduce((a, p) => a + p.w, 0);
    if (Math.abs(now - room) > 2) throw new Error(`the others did not take the room (${room} px before, ${now} px after)`);
    // the picture: three panes again, as in draft D
    await page.click(inPane(left[0].key, 'live-beside'));
    await count(3);
  } else {
    await page.click(inPane(list[0].key, 'live-close'));
    await page.waitForSelector('#live-dock[data-mode="bar"]', { timeout: 5000 });
    await page.click('[data-key="live-open"]');
    await count(1);
  }
  await page.waitForTimeout(300);
  await noSideways(page);
}

// Step 15. Sessions without a ticket (ORCH-364). The test dashboard has no orch to start helpers, so the step answers
// the one start call (session.new) like the server does: the core makes the session (`orch session new <kind>`, tested
// in workspace/tests/test_sessions.py) and the next state lists it in state.sessions, a helper with its run; the live
// sessions API (/api/sessions) lists the open ones with their kind, as sessions.py no_ticket builds them. Everything
// else is the real page: the bar's New menu, the buttons at the top of Focus, the layer, the pins.
const NO_TICKET = [['empty', 'Empty helper', 't_ntempty01'], ['chat', 'Chat helper', 't_ntchat001'],
  ['terminal', 'Plain terminal', 't_ntterm001'], ['manager', 'Manager', 't_ntmanag01']];
async function noTicket(page, dash, width) {
  const phone = width <= 720;
  const live = { name: 'focus', label: 'Focus', icon: 'target', active: true, removable: true, shipped: false,
    description: 'A live page for one ticket.', page: { path: '/', label: 'Open Focus', live_session: true },
    dashboard: { label: 'Focus', icon: 'target', order: 20 } };
  const made = [], calls = [];
  let last = null;
  const dress = st => {
    st.addons = [...(st.addons || []).filter(a => a.name !== live.name), live];
    st.settings = { ...(st.settings || {}), focus_preview_on: true };
    st.sessions = made.map(([kind, title, id]) => ({ id, kind, title, open: true }));
    st.runs = { ...(st.runs || {}) };
    made.forEach(([kind, , id]) => { if (kind !== 'terminal') st.runs[id] = { running: true, helper: { state: kind === 'empty' ? 'working' : 'idle' }, claim: { agent: 'agent:claude' } }; });
    st.rev = 'nt-' + made.length;
    last = st;
    return st;
  };
  await page.route(/\/api\/state(\?.*)?$/, async route => {
    const res = await route.fetch();
    if (res.status() !== 200) return route.fulfill({ response: res });
    const st = await res.json();
    route.fulfill({ response: res, json: st.unchanged && last ? dress({ ...last }) : dress(st) });
  });
  await page.route(/\/api\/sessions(\?.*)?$/, route => route.fulfill({ json: { lines: 8, age_ms: 0, sessions: made.map(([kind, title, id]) => ({
    id, key: '', title, kind, status: kind === 'empty' ? 'working' : 'idle', word: kind === 'empty' ? 'Working' : kind === 'terminal' ? 'Open' : 'Idle',
    detail: '', waiting_on: [], question: null, lines: [], tool: kind === 'terminal' ? null : 'Claude Code', model: null,
    mode: kind === 'terminal' ? null : 'live', opened_at: null, open_seconds: null, idle_seconds: null, closes_in_seconds: null, last_at: null,
    pinned: true, name: null })) } }));  // orch pins a session without a ticket until it is unpinned (ORCH-361)
  await page.route('**/api/act', async route => {
    const body = route.request().postDataJSON();
    if (body.op !== 'session.new') return route.continue();
    calls.push(body.args.kind);
    const one = NO_TICKET.find(n => n[0] === body.args.kind);
    if (!one) return route.fulfill({ status: 400, body: 'Choose an empty helper, a chat helper, a plain terminal or the Manager.' });
    if (!made.includes(one)) made.push(one);
    route.fulfill({ json: dress({ ...last }) });
  });
  await page.goto(dash + '/#home');
  await mainHasText(page);
  await page.waitForSelector('#live-bar [data-lbar-new]', { timeout: 10000 });
  const menu = async () => {
    await page.click('#live-bar [data-lbar-new]');
    await page.waitForSelector('#live-bar [data-key="lbar-new-menu"]', { timeout: 5000 });
    return page.$$eval('#live-bar [data-lbar-kind]', els => els.map(el => [el.dataset.lbarKind, el.innerText.replace(/\s+/g, ' ').trim()]));
  };
  // the New menu: four choices with draft D's words; Esc closes it
  const first = await menu();
  const words = first.map(x => x[1]).join(' | ');
  for (const [kind, title] of NO_TICKET) if (!first.some(x => x[0] === kind && x[1].startsWith(title))) throw new Error(`the New menu has no ${title}: ${words}`);
  if (!/A helper with no ticket and no task yet/.test(words) || !/Looks after all helpers/.test(words)) throw new Error(`the New menu does not say what each one does: ${words}`);
  await page.keyboard.press('Escape');
  await page.waitForSelector('#live-bar [data-key="lbar-new-menu"]', { state: 'detached', timeout: 5000 });
  // start each one from the menu: it opens in the layer and is pinned by itself
  for (const [kind, title, id] of NO_TICKET) {
    await menu();
    await page.click(`#live-bar [data-lbar-kind="${kind}"]`);
    await page.waitForSelector(`#live-dock .live-pane[data-session="${id}"]`, { timeout: 10000 });
    const head = await page.textContent(`#live-dock .live-pane[data-session="${id}"] .live-pt`);
    if (head.trim() !== title) throw new Error(`the pane of the ${title} says "${head.trim()}"`);
    const pins = await page.evaluate(() => window.LiveSessions?.pins || []);  // kept by orch for the workspace (ORCH-361)
    if (!pins.includes(id)) throw new Error(`the ${title} is not pinned`);
    if (await page.$(`#live-dock .live-pane[data-session="${id}"] [data-key="live-open-ticket"]`)) throw new Error(`the ${title} offers Open ticket`);
  }
  if (calls.join() !== 'empty,chat,terminal,manager') throw new Error(`the start calls were ${calls.join()}`);
  // the bar shows them as pinned sessions: chips by name on a wide screen, the pinned count on a phone
  const barText = await page.textContent('#live-bar');
  if (phone) {
    const pinned = await page.getAttribute('#live-bar [data-lbar-list="pin"]', 'aria-label');
    if (pinned !== 'Pinned: 4 sessions') throw new Error(`the bar says "${pinned}", not 4 pinned sessions`);
  } else {
    for (const [, title] of NO_TICKET) {
      if (!barText.includes(title) && !await page.$('#live-bar [data-lbar-list="pin"]')) throw new Error(`the bar does not show the ${title}`);
    }
  }
  // the menu now offers to go to the open ones; a second New starts nothing
  const again = await menu();
  if (!again.every(x => /Already open: go to it/.test(x[1]))) throw new Error(`the New menu does not say they are open: ${again.map(x => x[1]).join(' | ')}`);
  await page.click('#live-bar [data-lbar-kind="manager"]');
  await page.waitForSelector('#live-bar [data-key="lbar-new-menu"]', { state: 'detached', timeout: 5000 });
  if (calls.length !== 4) throw new Error('a second New of the Manager started another one');
  // the same four at the top of Focus, and the open sessions on the page
  await page.locator('#live-dock [data-key="live-min"]:visible').first().click().catch(() => {});
  await page.evaluate(() => { location.hash = '#addon/focus'; });
  await page.waitForSelector('[data-key="live-new"] [data-live-new="empty"]', { timeout: 10000 });
  const buttons = await page.$$eval('[data-key="live-new"] [data-live-new]', els => els.map(el => el.innerText.trim()));
  if (buttons.join('|') !== NO_TICKET.map(n => n[1]).join('|')) throw new Error(`the top of Focus has ${buttons.join(', ')}`);
  // the wall shows them in the Pinned band (a session without a ticket is pinned until it is unpinned, ORCH-361)
  for (const [, title, id] of NO_TICKET) {
    if (!await page.$(`[data-band="pin"] [data-tile="${id}"]`)) throw new Error(`the wall does not show the ${title} as pinned`);
  }
  await page.click('[data-key="live-new"] [data-live-new="chat"]');
  await page.waitForSelector('#live-dock .live-pane[data-session="t_ntchat001"]', { timeout: 10000 });
  if (calls.length !== 4) throw new Error('the Chat helper button on Focus started a second one');
  await menu();  // the picture: Focus with the New menu open, as in draft D
  await noSideways(page);
}

// Step 6: the Focus button on the ticket page and on every ticket row, and Open ticket back from the session. The test
// workspace has one ticket, so the step adds four with the run states the button speaks for (Preview on).
const FOCUS_TICKETS = [['run', 'ORCH-189', 'New price list for the shop', 'Watch'], ['wait', 'ORCH-190', 'Send the weekly summary', 'Answer'],
  ['idle', 'ORCH-191', 'Tidy the release notes', 'Open'], ['none', 'ORCH-192', 'Opening hours page', 'Start']];
async function focusButton(page, dash, width) {
  const phone = width <= 720;
  const live = { name: 'focus', label: 'Focus', icon: 'target', active: true, removable: true, shipped: false,
    description: 'A live page for one ticket.', page: { path: '/', label: 'Open Focus', live_session: true },
    dashboard: { label: 'Focus', icon: 'target', order: 20 } };
  const HELPER = { wait: 'you', run: 'working', idle: 'idle' };
  const id = key => 't_fb' + key.slice(5);
  await page.route(/\/api\/state(\?.*)?$/, async route => {
    const res = await route.fetch();
    if (res.status() !== 200) return route.fulfill({ response: res });
    const st = await res.json();
    const base = (st.tickets || [])[0] || {};
    const extra = FOCUS_TICKETS.map(([s, key, title]) => ({ ...base, id: id(key), key, title, status: s === 'none' ? 'ready' : 'active',
      questions: s === 'wait' ? [{ id: 'q1', text: 'Send it to the whole team or only to sales?', options: ['Whole team', 'Only sales'] }] : [],
      checks: [], sessions: [] }));
    st.tickets = [...(st.tickets || []).filter(t => !String(t.id).startsWith('t_fb')), ...extra];
    st.runs = { ...(st.runs || {}) };
    FOCUS_TICKETS.forEach(([s, key]) => { if (s !== 'none') st.runs[id(key)] = { running: true, helper: { state: HELPER[s] }, claim: { agent: 'agent:claude' } }; });
    st.addons = [...(st.addons || []).filter(a => a.name !== live.name), live];
    st.settings = { ...(st.settings || {}), focus_preview_on: true,
      addons: [...((st.settings || {}).addons || []).filter(a => a.name !== live.name), live] };
    route.fulfill({ response: res, json: st });
  });
  // the added tickets have no files on disk: their ticket pages get an empty list of results
  await page.route(/\/api\/artifacts\/t_fb/, route => route.fulfill({ json: { files: [] } }));
  // the Start choice of a ticket with no helper lists its earlier sessions (ORCH-362): none for these fake tickets
  await page.route(/\/api\/sessions\/t_fb/, route => route.fulfill({ json: { available: true, sessions: [] } }));
  await page.goto(dash + '/#tickets');
  await page.evaluate(() => { try { Object.keys(localStorage).filter(k => k.indexOf('orch.live.layer') === 0).forEach(k => localStorage.removeItem(k)); } catch (e) { /* none */ } });
  await page.reload();
  await mainHasText(page);
  // every ticket row has its Focus button, with the word that fits the ticket
  const rowSel = phone ? k => `[data-key="short-${id(k)}"]` : k => `[data-key="tree-${id(k)}"]`;
  for (const [, key, , verb] of FOCUS_TICKETS) {
    const b = `${rowSel(key)} [data-key="live-session-btn"]`;
    await page.waitForSelector(b, { timeout: 10000 });
    const word = (await page.textContent(b)).trim();
    if (word !== verb) throw new Error(`the row of ${key} says "${word}", not "${verb}"`);
    if (await page.$$eval(`${rowSel(key)} button`, els => els.filter(e => e.textContent.trim() === 'Answer').length) > 1) throw new Error(`the row of ${key} shows two Answer buttons`);
  }
  // a row's button opens that session in the layer, the list stays
  await page.click(`${rowSel('ORCH-191')} [data-key="live-session-btn"]`);
  await page.waitForSelector(`#live-dock .live-pane[data-session="${id('ORCH-191')}"]`, { timeout: 5000 });
  if (await page.evaluate(() => location.hash) !== '#tickets') throw new Error('the row\'s Focus button left the list');
  if (!await page.evaluate(() => !!document.activeElement?.closest('#live-dock'))) throw new Error('the keyboard did not move into the session');
  // the ticket page: "Watch in Focus" opens its session; Open ticket comes back to the same page
  await page.evaluate(h => { location.hash = h; }, '#ticket/' + id('ORCH-189'));
  await mainHasText(page);
  const strip = `[data-key="ticket-strip-${id('ORCH-189')}"] [data-key="live-session-btn"]`;
  await page.waitForSelector(strip, { timeout: 10000 });
  if ((await page.textContent(strip)).trim() !== 'Watch in Focus') throw new Error('the ticket page does not say Watch in Focus');
  if (await page.$('[data-key="watch-live"]')) throw new Error('today\'s Watch live still shows with Preview on');
  await page.click(strip);
  const pane = `#live-dock .live-pane[data-session="${id('ORCH-189')}"]`;
  await page.waitForSelector(pane, { timeout: 5000 });
  if (!await page.$eval(`${pane} .key`, el => el.textContent.trim() === 'ORCH-189')) throw new Error('the pane does not show the ticket key');
  // from full screen too: Open ticket steps out of it so the ticket page shows
  await page.click(`${pane} [data-key="live-full"]`);
  await page.waitForSelector('#live-dock[data-mode="full"]', { timeout: 5000 });
  await page.evaluate(() => { location.hash = '#home'; });
  await mainHasText(page);
  await page.click(`${pane} [data-key="live-open-ticket"]`);
  await page.waitForFunction(h => location.hash === h, '#ticket/' + id('ORCH-189'), { timeout: 10000 });
  await page.waitForSelector(`[data-key="ticket-strip-${id('ORCH-189')}"]`, { timeout: 10000 });
  if (await page.$('#live-dock[data-mode="full"]')) throw new Error('Open ticket left the ticket page hidden behind full screen');
  // ORCH-676: the layer steps down to the bar so the ticket page is usable; the session stays and Open brings it back
  await page.waitForSelector('#live-dock[data-mode="bar"]', { timeout: 5000 });
  if (!await page.evaluate(k => window.LiveLayer.panes.includes(k), id('ORCH-189'))) throw new Error('the session closed when Open ticket was pressed');
  await page.click('[data-key="live-open"]');
  await page.waitForSelector(pane, { timeout: 5000 });
  // a narrow pane keeps Open ticket in More as well (draft D)
  if (await page.$(`${pane} [data-key="live-pane-more"]`)) {
    await page.click(`${pane} [data-key="live-pane-more"]`);
    await page.waitForSelector('[data-key="live-more-menu"] [data-key="live-more-ticket"]', { timeout: 5000 });
    await page.keyboard.press('Escape');
  }
  // a ticket with no helper: "Start in Focus" opens its pane, where the start is offered
  await page.evaluate(h => { location.hash = h; }, '#ticket/' + id('ORCH-192'));
  await mainHasText(page);
  const start = `[data-key="ticket-strip-${id('ORCH-192')}"] [data-key="live-session-btn"]`;
  await page.waitForSelector(start, { timeout: 10000 });
  if ((await page.textContent(start)).trim() !== 'Start in Focus') throw new Error('a ticket with no helper does not say Start in Focus');
  await page.click(start);
  await page.waitForSelector(`#live-dock .live-pane[data-session="${id('ORCH-192')}"]`, { timeout: 5000 });
  // the picture: the working ticket's page with its session open, as in draft D
  await page.evaluate(h => { location.hash = h; }, '#ticket/' + id('ORCH-189'));
  await mainHasText(page);
  await page.click(strip);
  await page.waitForSelector(pane, { timeout: 5000 });
  await page.waitForTimeout(300);
  await noSideways(page);
}

// Steps 4, 5, 8 and 11: the wall (ORCH-360) with draft D's 24 sessions of step 9 (liveBarState). Each step starts with
// nothing kept in this browser (folded bands, the layer's place) but keeps what it chose itself across its reload.
async function wallPage(page, dash, tag, sessions, opts = {}) {
  await liveBarState(page);
  barAsk = !!opts.ask;
  if (sessions) await page.route(/\/api\/sessions(\?.*)?$/, route => route.fulfill({ json: { sessions: sessions(), lines: 8, age_ms: 0 } }));
  await page.addInitScript(t => { try { if (sessionStorage.getItem('wall') !== t) { localStorage.removeItem('orch.live.wall'); Object.keys(localStorage).filter(k => k.indexOf('orch.live.layer') === 0).forEach(k => localStorage.removeItem(k)); sessionStorage.setItem('wall', t); } } catch (e) { /* none */ } }, tag);
  await page.goto(dash + '/#addon/focus');
  await page.waitForSelector('[data-key="live-wall"] .wall-band', { timeout: 15000 });
}
const tileOf = id => `[data-key="live-wall"] [data-tile="${id}"]`;
async function wallBands(page) {
  return page.$$eval('[data-key="live-wall"] .wall-band', els => els.map(el => el.dataset.band));
}

// Step 4: bands in draft D's order, one summary line, one sentence per tile, and a working tile's peek adds its newest
// line by itself (the sessions API answers with one more line each time).
async function wall(page, dash) {
  let tick = 0;
  await wallPage(page, dash, 'fd4', () => {
    const list = barSessions();
    tick += 1;
    const s = list.find(x => x.id === 't_bar232');
    s.lines = [...s.lines, '⏺ Checked part ' + tick];
    return list;
  });
  const order = await wallBands(page);
  if (order.join(',') !== 'pin,need,queue,idle') throw new Error('the bands are ' + order.join(', ') + ', not Pinned, Needs you and working, In line, Idle');
  const hero = await page.textContent('[data-key="wall-hero"]');
  for (const w of ['3 need you', '4 working', '9 in line', '8 idle']) if (!hero.includes(w)) throw new Error(`the summary line misses "${w}": ${hero}`);
  if ((await page.textContent('[data-key="wall-total"]')).trim() !== '24 sessions') throw new Error('the summary does not say 24 sessions');
  const empty = await page.$$eval('[data-key="live-wall"] .wall-tile [data-wall-now]', els => els.filter(el => !el.textContent.trim()).length);
  if (empty) throw new Error(`${empty} tiles say nothing about what their helper does`);
  if (/\bt_[A-Za-z0-9]{3,}/.test(await page.textContent('[data-key="live-wall"]'))) throw new Error('the wall shows a raw ticket id');
  const peek = `${tileOf('t_bar232')} [data-wall-peek]`;
  const first = Number((/Checked part (\d+)/.exec(await page.textContent(peek)) || [])[1]);
  await page.waitForFunction(([sel, n]) => { const m = /Checked part (\d+)/.exec(document.querySelector(sel)?.textContent || ''); return m && Number(m[1]) > n; }, [peek, first], { timeout: 10000 });
  await noSideways(page);
}

// Step 5: the three sessions that wait for an answer are orange tiles first after the pinned band, their sentence is the
// question, nothing on the wall answers; once answered (the API says working) the tile turns back to Working.
async function needsYou(page, dash) {
  let answered = false;
  await wallPage(page, dash, 'fd5', () => barSessions().map(s => answered && s.id === 't_bar238'
    ? { ...s, status: 'working', word: 'Working', detail: 'Keeps the old file name', question: null } : s), { ask: true });
  const need = await page.$$eval('[data-band="need"] .wall-tile', els => els.map(el => [el.dataset.tile, el.dataset.s]));
  if (need.slice(0, 3).some(([, s]) => s !== 'needs-you') || need.slice(3).some(([, s]) => s === 'needs-you')) throw new Error('the needs-you tiles are not first: ' + need.map(x => x.join(' ')).join(', '));
  const [orange, plain, want] = await page.evaluate(([a, b]) => {
    const c = el => getComputedStyle(el).borderTopColor, t = document.createElement('span');
    t.style.color = 'var(--needs-you)'; document.body.append(t);
    const goal = getComputedStyle(t).color; t.remove();
    return [c(document.querySelector(a)), c(document.querySelector(b)), goal];
  }, [tileOf('t_bar238'), tileOf('t_bar232')]);
  if (orange !== want || orange === plain) throw new Error(`the needs-you tile is not orange (${orange}, working ${plain}, orange ${want})`);
  if (!/Keep the old file name/.test(await page.textContent(`${tileOf('t_bar238')} [data-wall-now]`))) throw new Error('the orange tile does not say the question');
  if (await page.$(`${tileOf('t_bar238')} :is(input, textarea, select, [data-answer], .question-card)`)) throw new Error('the wall itself offers an answer');
  // ORCH-675 (checked since ORCH-701): the layer shows the question with one button per option and a field for an own
  // answer; a click on an option is the answer (the act is caught before orch), then the question leaves the pane
  const asked = [];
  await page.route('**/api/act', async route => {
    const body = route.request().postDataJSON();
    if (body.op !== 'answer') return route.fallback();
    asked.push(body.args);
    barAnswered.add(body.args.ticket);
    // orch answers an action with the new state: the question now has its answer
    const st = { ...barState, tickets: (barState.tickets || []).map(t => t.id !== body.args.ticket ? t
      : { ...t, questions: (t.questions || []).map(q => q.id === body.args.question ? { ...q, answer: body.args.answer } : q) }) };
    route.fulfill({ json: st });
  });
  await page.click(`${tileOf('t_bar238')} [data-wall-open]`);
  await page.waitForSelector('#live-dock .live-pane[data-session="t_bar238"]', { timeout: 5000 });
  const ask = '#live-dock .live-pane[data-session="t_bar238"] [data-live-ask]';
  await page.waitForSelector(`${ask}:not([hidden]) [data-key="live-ask-option-0"]`, { timeout: 10000 })
    .catch(() => { throw new Error('the layer does not offer the options of the waiting question'); });
  const box = await page.$eval(ask, el => ({ q: el.querySelector('.live-ask-q')?.textContent || '',
    opts: [...el.querySelectorAll('[data-key^="live-ask-option-"]')].map(b => b.textContent),
    own: !!el.querySelector('[data-key="live-ask-text"]'), send: !!el.querySelector('[data-key="live-ask-send"]') }));
  if (!/Keep the old file name/.test(box.q)) throw new Error('the layer does not say the question: ' + box.q);
  if (box.opts.join('|') !== BAR_QUESTION.options.join('|')) throw new Error('the layer shows the options ' + box.opts.join(', '));
  if (!box.own || !box.send) throw new Error('the layer has no field and Send for an own answer');
  await page.click(`${ask} [data-key="live-ask-option-0"]`);
  for (let i = 0; i < 20 && !asked.length; i++) await page.waitForTimeout(100);
  if (asked.length !== 1 || asked[0].ticket !== 't_bar238' || asked[0].question !== 'q1' || asked[0].answer !== BAR_QUESTION.options[0]) {
    throw new Error('the option did not answer the question: ' + JSON.stringify(asked));
  }
  await page.waitForSelector(`${ask}[hidden]`, { state: 'attached', timeout: 10000 })
    .catch(() => { throw new Error('the answered question stayed in the layer'); });
  // the answer redraws the question box and the keyboard falls back to the page (ORCH-709); until that is fixed the
  // step puts it back into the pane, so the Esc below still has the layer to close
  await page.focus('#live-dock .live-pane[data-session="t_bar238"]');
  answered = true;
  await page.evaluate(() => window.LiveSessions.refresh());
  await page.waitForFunction(sel => document.querySelector(sel)?.dataset.s === 'working', tileOf('t_bar238'), { timeout: 10000 });
  // the picture: the wall with its orange tiles, the layer at the bar
  answered = false;
  await page.keyboard.press('Escape');
  await page.evaluate(() => window.LiveSessions.refresh());
  await page.waitForFunction(sel => document.querySelector(sel)?.dataset.s === 'needs-you', tileOf('t_bar238'), { timeout: 10000 });
  await page.waitForSelector('#live-dock[data-mode="bar"]', { timeout: 5000 });
  await noSideways(page);
}

// Step 7: pin a working session from its tile: it moves to the Pinned band and the bar shows it with the pinned ones.
// Open it, click its name in the pane header, type a new one and press Enter: the tile, the pane and the bar say the new
// name. The server keeps both (session.pin / session.name): they stay after a reload. Unpin moves the tile back.
async function pinName(page, dash, width) {
  const phone = width <= 720, id = 't_bar232', NAME = 'Usage counts for the owner';
  await wallPage(page, dash, 'fd7');
  const band = async () => page.$eval(tileOf(id), el => el.closest('.wall-band')?.dataset.band);
  if (await band() !== 'need') throw new Error('the working session does not start in Needs you and working');
  await page.click(`${tileOf(id)} [data-wall-pin]`);
  await page.waitForSelector(`[data-band="pin"] [data-tile="${id}"]`, { timeout: 5000 });
  // the page is drawn again when the server answers; the keyboard is back on the pin button within a frame
  await page.waitForFunction(i => document.activeElement?.dataset.wallPin === i, id, { timeout: 2000 }).catch(() => { throw new Error('pinning moved the keyboard place'); });
  if (await page.getAttribute(`${tileOf(id)} [data-wall-pin]`, 'aria-pressed') !== 'true') throw new Error('the pin button does not say pinned');
  // the bar: a chip with the pinned ones, or (folded) the pinned count, or (folded further) inside More
  const barPinned = async () => {
    if (await page.$('#live-bar [data-g="pin"]')) return !!(await page.$(`#live-bar [data-g="pin"] [data-lbar-open="${id}"]`));
    if (await page.$('#live-bar [data-lbar-list="pin"]')) return (await page.getAttribute('#live-bar [data-lbar-list="pin"]', 'aria-label')) === 'Pinned: 2 sessions';
    await page.click('#live-bar [data-lbar-list="more"]');
    const there = !!(await page.waitForSelector(`#live-bar [data-lbar-open="${id}"]`, { timeout: 5000 }).catch(() => null));
    await page.keyboard.press('Escape');
    return there;
  };
  if (!(await barPinned())) throw new Error('the bar does not show the pinned session');
  // the name: in the pane header of the open session (draft D: click the name, type, Enter)
  await page.click(`${tileOf(id)} [data-wall-open]`);
  const pane = `#live-dock .live-pane[data-session="${id}"]`;
  await page.click(`${pane} [data-key="live-rename"]`);
  const input = `${pane} [data-key="live-ren-input"]`;
  await page.waitForSelector(input, { timeout: 5000 });
  if (!(await page.evaluate(sel => document.activeElement === document.querySelector(sel), input))) throw new Error('the name field does not have the keyboard');
  await page.fill(input, NAME);
  await page.press(input, 'Enter');
  await page.waitForFunction(([sel, n]) => document.querySelector(sel)?.textContent === n, [`${pane} [data-key="live-rename"]`, NAME], { timeout: 5000 }).catch(() => { throw new Error('the pane does not show the new name'); });
  await page.waitForFunction(sel => document.activeElement === document.querySelector(sel), `${pane} [data-key="live-rename"]`, { timeout: 2000 })
    .catch(() => { throw new Error('after saving the keyboard is not back on the name'); });
  const shown = async () => ({
    tile: (await page.textContent(`${tileOf(id)} .wall-tt`)).trim(),
    pane: await page.$(`${pane} [data-key="live-rename"]`) ? (await page.textContent(`${pane} [data-key="live-rename"]`)).trim() : '',
    chip: await page.$(`#live-bar [data-lbar-open="${id}"]`) ? (await page.textContent(`#live-bar [data-lbar-open="${id}"]`)).trim() : null,
  });
  const check = async when => {
    const got = await shown();
    if (got.tile !== NAME) throw new Error(`${when}: the tile says "${got.tile}"`);
    if (got.pane !== NAME) throw new Error(`${when}: the pane says "${got.pane}"`);
    if (got.chip !== null && !got.chip.includes(NAME)) throw new Error(`${when}: the chip says "${got.chip}"`);
    if (got.chip === null && !(await page.$('#live-bar :is([data-lbar-list="pin"], [data-lbar-list="more"])'))) throw new Error(`${when}: the bar shows no pinned session`);
    if (await band() !== 'pin') throw new Error(`${when}: the session is not in the Pinned band`);
  };
  await check('after saving');
  // kept by the server: a reload (the same page, the layer as it was) shows both
  await page.reload();
  await page.waitForSelector(`[data-band="pin"] [data-tile="${id}"]`, { timeout: 15000 }).catch(() => { throw new Error('after a reload the session is not pinned'); });
  // a reload never opens full screen (step 10): open the session again from its tile
  if (!(await page.$(`${pane} [data-key="live-rename"]`))) await page.click(`${tileOf(id)} [data-wall-open]`);
  await page.waitForSelector(`${pane} [data-key="live-rename"]`, { timeout: 10000 }).catch(() => { throw new Error('after a reload the pane does not open'); });
  await check('after a reload');
  // unpin moves it back; the name stays
  await page.keyboard.press('Escape');
  await page.waitForSelector('#live-dock[data-mode="bar"]', { timeout: 5000 }).catch(() => {});
  await page.click(`${tileOf(id)} [data-wall-pin]`);
  await page.waitForFunction(sel => document.querySelector(sel)?.closest('.wall-band')?.dataset.band === 'need', tileOf(id), { timeout: 5000 }).catch(() => { throw new Error('unpin did not move the tile back'); });
  if ((await page.textContent(`${tileOf(id)} .wall-tt`)).trim() !== NAME) throw new Error('unpinning lost the name');
  // pinned again for the picture: the Pinned band with the new name
  await page.click(`${tileOf(id)} [data-wall-pin]`);
  await page.waitForSelector(`[data-band="pin"] [data-tile="${id}"]`, { timeout: 5000 });
  await noSideways(page);
}

// Step 8: 24 sessions: the long bands scroll inside themselves, the filter keeps only matching tiles, a folded band
// stays folded after a reload, and counts read right.
async function manySessions(page, dash, width) {
  await wallPage(page, dash, 'fd8');
  if (!(await page.$('[data-key="wall-bands"][data-many]'))) throw new Error('24 sessions do not count as many');
  if (width > 720) {
    const scrolls = await page.$eval('[data-band="queue"] .wall-lines', el => getComputedStyle(el).overflowY);
    if (scrolls !== 'auto') throw new Error('the long In line band does not scroll inside itself');
  }
  await page.fill('[data-wall-filter]', 'logo');
  await page.waitForFunction(() => document.querySelectorAll('[data-key="live-wall"] [data-tile]').length === 1, null, { timeout: 5000 });
  const head = await page.textContent('[data-band="queue"] .wall-bt');
  if (!/In line \(1\)/.test(head)) throw new Error(`the In line band says "${head.trim()}" for one match`);
  if ((await page.textContent('[data-key="wall-total"]')).trim() !== '24 sessions') throw new Error('the filter changed the total');
  await page.fill('[data-wall-filter]', 'nothing like this');
  await page.waitForSelector('[data-key="wall-nomatch"]', { timeout: 5000 });
  await page.fill('[data-wall-filter]', '');
  await page.waitForFunction(() => document.querySelectorAll('[data-key="live-wall"] [data-tile]').length === 24, null, { timeout: 5000 });
  await page.click('[data-wall-fold="queue"]');
  await page.waitForSelector('[data-wall-fold="queue"][aria-expanded="false"]', { timeout: 5000 });
  if (await page.$('[data-band="queue"] [data-tile]')) throw new Error('the folded band still shows its sessions');
  if (!(await page.evaluate(() => document.activeElement?.dataset.wallFold === 'queue'))) throw new Error('folding moved the keyboard place');
  await page.reload();
  await page.waitForSelector('[data-key="live-wall"] .wall-band', { timeout: 15000 });
  if (!(await page.$('[data-wall-fold="queue"][aria-expanded="false"]'))) throw new Error('the folded band opened again after a reload');
  const tall = await page.evaluate(() => document.documentElement.scrollHeight > innerHeight);
  if (!tall) throw new Error('24 sessions fit without scrolling: the wall does not show them');
  await noSideways(page);
}

// Step 11: a tile zooms into the layer; full screen; Esc goes back one step: full screen, then the panel, then the wall.
async function zoom(page, dash, width) {
  const phone = width <= 720;
  await wallPage(page, dash, 'fd11');
  await page.waitForSelector('#live-dock[data-mode="bar"]', { timeout: 10000 });
  await page.click(`${tileOf('t_bar232')} [data-wall-open]`);
  const pane = '.live-pane[data-session="t_bar232"]';
  await page.waitForSelector(`#live-dock:is([data-mode="bottom"], [data-mode="right"]) ${pane}`, { timeout: 5000 });
  if (!(await page.evaluate(p => document.querySelector(p).contains(document.activeElement), pane))) throw new Error('the keyboard did not move into the zoomed session');
  const docked = await page.$eval('#live-dock', el => el.dataset.mode);
  if (phone && docked !== 'bottom') throw new Error('a phone opened the session on the right');
  await page.click(`${pane} [data-key="live-full"]`);
  await page.waitForSelector(`#live-dock[data-mode="full"] ${pane}`, { timeout: 5000 });
  if (!(await page.isVisible('#live-dock[data-mode="full"] #live-bar'))) throw new Error('full screen keeps no strip of the other sessions');
  await page.keyboard.press('Escape');
  await page.waitForSelector(`#live-dock[data-mode="${docked}"] ${pane}`, { timeout: 5000 });
  await page.focus(`${pane} [data-key="live-full"]`);
  await page.keyboard.press('Escape');
  await page.waitForSelector('#live-dock[data-mode="bar"]', { timeout: 5000 });
  if (!(await page.isVisible(tileOf('t_bar232')))) throw new Error('the wall is not back after Esc');
  // the picture: the zoomed session in full screen, as in draft D
  await page.click(`${tileOf('t_bar232')} [data-wall-open]`);
  await page.waitForSelector('#live-dock ' + pane, { timeout: 5000 });
  await page.click(`${pane} [data-key="live-full"]`);
  await page.waitForSelector(`#live-dock[data-mode="full"] ${pane}`, { timeout: 5000 });
  await page.waitForTimeout(300);
  await noSideways(page);
}

// Step 28 (ORCH-345): an epic with its helpers, as one group. The state gets the epic "Autumn newsletter" and its four
// sub-tickets (parent chain), the live sessions API answers with their sessions and the group (sessions.py `groups`):
// the main helper and "Write the texts" work (two small helpers inside), "Build the mail page" needs you, "Check the
// links" is in line, "Send a test to the team" has no session yet. One other session works outside the group.
const GROUP = [
  ['ORCH-300', 'Autumn newsletter', 'working', 0], ['ORCH-301', 'Write the texts', 'working', 1],
  ['ORCH-302', 'Build the mail page', 'needs-you', 1], ['ORCH-303', 'Send a test to the team', 'closed', 1],
  ['ORCH-304', 'Check the links', 'in-line', 1], ['ORCH-12', 'Tidy the release notes', 'working', -1],
];
const GWORD = { working: 'Working', 'needs-you': 'Waits for you', 'in-line': 'In line', closed: 'No session' };
const GRANK = { 'needs-you': 0, working: 1, 'in-line': 2 };
const gid = key => 't_grp' + key.slice(5);
const SMALL = [{ what: 'Draft intro', seconds: 180 }, { what: 'Draft offers', seconds: 60 }];
async function groupState(page) {
  const live = { name: 'focus', label: 'Focus', icon: 'target', active: true, removable: true, shipped: false,
    description: 'A live page for one ticket.', page: { path: '/', label: 'Open Focus', live_session: true },
    dashboard: { label: 'Focus', icon: 'target', order: 20 } };
  const HELPER = { working: 'working', 'needs-you': 'you' };
  await page.addInitScript(() => {
    try {
      if (sessionStorage.getItem('grp') !== '1') {
        localStorage.setItem('orch.live.layer', '{}');
        localStorage.setItem('orch.live.pins', '[]');
        sessionStorage.setItem('grp', '1');
      }
    } catch (e) { /* none */ }
  });
  // the dashboard's own state with the group's tickets and runs on top (also the answer to a send: the page takes it whole)
  const shape = st => {
    const base = (st.tickets || [])[0] || {};
    const extra = GROUP.map(([key, title, , depth]) => ({ ...base, id: gid(key), key, title, status: 'active', questions: [], checks: [],
      sessions: [], parent: depth === 1 ? gid('ORCH-300') : null }));
    st.tickets = [...(st.tickets || []).filter(t => !String(t.id).startsWith('t_grp')), ...extra];
    st.runs = { ...(st.runs || {}) };
    GROUP.forEach(([key, , s]) => {
      if (s === 'in-line') st.runs[gid(key)] = { running: false, hold: 'Waits for a free place' };
      else if (s !== 'closed') st.runs[gid(key)] = { running: true, helper: { state: HELPER[s] }, claim: { agent: 'agent:claude' } };
    });
    st.addons = [...(st.addons || []).filter(a => a.name !== live.name), live];
    st.settings = { ...(st.settings || {}), focus_preview_on: true,
      addons: [...((st.settings || {}).addons || []).filter(a => a.name !== live.name), live] };
    return st;
  };
  await page.route(/\/api\/state(\?.*)?$/, async route => {
    const res = await route.fetch();
    if (res.status() !== 200) return route.fulfill({ response: res });
    route.fulfill({ response: res, json: shape(await res.json()) });
  });
  const sessions = GROUP.filter(([, , s]) => s !== 'closed').map(([key, title, s]) => ({ id: gid(key), key, title, status: s, word: GWORD[s],
    detail: s === 'working' ? 'Writing the offers section' : '', waiting_on: [], question: s === 'needs-you' ? 'Which header picture for the mail page?' : null,
    lines: s === 'working' ? ['⏺ ' + title + ': step 2 of 4'] : [], tool: s === 'in-line' ? null : 'Claude Code', model: 'Opus', mode: s === 'in-line' ? null : 'live',
    opened_at: null, open_seconds: s === 'in-line' ? null : 1500, idle_seconds: null, closes_in_seconds: null, last_at: null, kind: '',
    parent: key === 'ORCH-300' || key === 'ORCH-12' ? null : gid('ORCH-300'), small: key === 'ORCH-301' ? SMALL : [] }))
    .sort((a, b) => GRANK[a.status] - GRANK[b.status]);
  const group = { id: gid('ORCH-300'), key: 'ORCH-300', title: 'Autumn newsletter', kind: 'epic',
    members: GROUP.filter(([, , , d]) => d >= 0).map(([key, title, s, depth]) => ({ id: gid(key), key, title, depth, main: depth === 0,
      status: s, word: GWORD[s], small: key === 'ORCH-301' ? SMALL : [] })) };
  await page.route(/\/api\/sessions(\?.*)?$/, route => route.fulfill({ json: { sessions, groups: [group], lines: 8, age_ms: 0 } }));
  await page.route(/\/api\/act$/, async route => {
    const r = await route.fetch({ url: new URL('/api/state', route.request().url()).href, method: 'GET' });
    await route.fulfill({ json: shape(await r.json()) });
  });
}
// The epic is one orange tile; a click opens the helper that needs you with the group beside it; a click on a row swaps
// the session in that pane and the message box names who receives it; small helpers are watch only.
async function groups(page, dash, width) {
  await groupState(page);
  await page.goto(dash + '/#addon/focus');
  const tile = `[data-key="live-wall"] [data-tile="${gid('ORCH-300')}"]`;
  await page.waitForSelector(tile, { timeout: 15000 });
  const t = await page.textContent(tile);
  for (const w of ['Autumn newsletter', '3 helpers', '2 small helpers', '1 needs you', 'Build the mail page']) if (!t.includes(w)) throw new Error(`the group tile misses "${w}": ${t}`);
  if (await page.getAttribute(tile, 'data-s') !== 'needs-you') throw new Error('one helper needs you, but the group tile is not orange');
  for (const k of ['ORCH-301', 'ORCH-302', 'ORCH-304']) if (await page.$(`[data-key="live-wall"] [data-tile="${gid(k)}"]`)) throw new Error(`${k} has its own tile beside its group`);
  await page.click(`${tile} [data-wall-open]`);
  const pane = `#live-dock .live-pane[data-session="${gid('ORCH-302')}"]`;
  await page.waitForSelector(`${pane} [data-key="live-group"]`, { timeout: 10000 });
  const rows = await page.textContent(`${pane} [data-key="live-group"]`);
  for (const w of ['Main helper', 'Write the texts', 'Draft intro', 'Small helper', 'watch only', 'Send a test to the team', 'Check the links', 'Earlier sessions']) if (!rows.includes(w)) throw new Error(`the switcher misses "${w}"`);
  await page.click(`${pane} [data-key="live-group-${gid('ORCH-301')}"]`);
  const next = `#live-dock .live-pane[data-session="${gid('ORCH-301')}"]`;
  await page.waitForSelector(`${next} [data-key="live-msg-to"]`, { timeout: 10000 });
  const to = (await page.textContent(`${next} [data-key="live-msg-to"]`)).trim();
  if (to !== 'Message to: Write the texts (ORCH-301). Only this helper gets it.') throw new Error('the message box says: ' + to);
  if (await page.getAttribute(`${next} [data-key="live-group-${gid('ORCH-301')}"]`, 'aria-current') !== 'true') throw new Error('the shown helper is not marked in the switcher');
  if ((await page.$$('#live-dock .live-pane')).length !== 1) throw new Error('the swap opened a second pane');
  await page.fill(`${next} [data-live-msg-text]`, 'Use the short intro.');
  const sent = page.waitForRequest(r => r.url().endsWith('/api/act') && r.method() === 'POST' && (r.postData() || '').includes('run.send'));
  await page.click(`${next} [data-key="live-msg-send"]`);
  const body = (await sent).postData() || '';
  if (!body.includes(gid('ORCH-301')) || !body.includes('Use the short intro.')) throw new Error('the message did not go to Write the texts: ' + body.slice(0, 200));
  await page.click(`${next} [data-key="live-group-${gid('ORCH-300')}"]`);
  const main = `#live-dock .live-pane[data-session="${gid('ORCH-300')}"] [data-key="live-msg-to"]`;
  await page.waitForSelector(main, { timeout: 10000 });
  if (!(await page.textContent(main)).includes('the main helper')) throw new Error('the main helper is not named in its message box');
  if (width <= 720 && await page.getAttribute('#live-dock [data-key="live-group"]', 'data-mode') !== 'strip') throw new Error('on a phone the switcher is not a strip');
  await noSideways(page);
}

// Steps 29 to 32 (ORCH-663, the clean end-to-end test of the new Focus): what a person does besides the draft's own
// features, each found working on a fresh workspace with real helpers and kept here on the 24 stand-in sessions.
const panesNow = page => page.evaluate(() => window.LiveLayer.panes);
const inDock = page => page.evaluate(() => !!document.activeElement?.closest?.('#live-dock'));
// A second tab a step opens: its page errors and console errors fail the step like the first tab's.
function watchTab(p) {
  const bad = [];
  p.on('pageerror', e => bad.push(`second tab: page error: ${String(e.message).slice(0, 160)}`));
  p.on('console', m => { if (m.type() === 'error') bad.push(`second tab: console error: ${m.text().slice(0, 160)}`); });
  return () => { if (bad.length) throw new Error([...new Set(bad)].join(' | ')); };
}

// Step 25: at phone width one session shows at a time, right falls back to bottom, Add beside opens instead of splitting.
async function phone(page, dash, width) {
  await wallPage(page, dash, 'fd25');
  await page.click(`${tileOf('t_bar238')} [data-wall-open]`);
  await page.waitForSelector('[data-key="live-panel"]', { timeout: 5000 });
  if (width > 720) {
    await page.evaluate(() => window.LiveLayer.place('right'));
    await page.waitForTimeout(300);
    if (await page.evaluate(() => window.LiveLayer.mode) !== 'right') throw new Error('a wide screen cannot put the layer on the right');
    return;
  }
  await page.evaluate(() => { window.LiveLayer.place('right'); window.LiveLayer.beside('t_bar201'); });
  await page.waitForTimeout(300);
  const st = await page.evaluate(() => ({ mode: window.LiveLayer.mode, n: document.querySelector('[data-key="live-panel"]').dataset.n,
    shown: [...new Set([...document.querySelectorAll('#live-dock [data-key="live-panel"] [data-session]')].map(e => e.dataset.session))] }));
  if (st.mode !== 'bottom') throw new Error(`on a phone the layer went to ${st.mode}, not the bottom`);
  if (st.n !== '1') throw new Error(`on a phone ${st.n} sessions show at once, not one`);
  if (st.shown.length !== 1 || st.shown[0] !== 't_bar201') throw new Error(`Add beside on a phone should show ORCH-201 instead, it shows ${st.shown.join(', ')}`);
  if (await page.$('#live-dock [data-key="live-pane-place"]')) throw new Error('on a phone a pane still offers Place');
  await noSideways(page);
}

// Step 29: a ticket's address opened in a new tab shows the wall with that session in the layer; an address of a ticket
// that does not exist shows the wall and nothing breaks.
async function address(page, dash) {
  await liveBarState(page);
  await page.goto(dash + '/#addon/focus/t/t_bar201');
  await page.waitForSelector('[data-key="live-wall"] .wall-band', { timeout: 15000 });
  await page.waitForFunction(() => window.LiveLayer?.panes?.includes('t_bar201'), null, { timeout: 8000 })
    .catch(() => { throw new Error('the address of ORCH-201 did not open its session in the layer'); });
  await page.waitForSelector('#live-dock [data-key="live-panel"]', { timeout: 5000 });
  // ORCH-677 (checked since ORCH-701): the keyboard is in the session's pane
  await page.waitForFunction(() => !!document.activeElement?.closest('#live-dock .live-pane[data-session="t_bar201"]'), null, { timeout: 5000 })
    .catch(() => { throw new Error('the address of ORCH-201 opened its session but the keyboard is not in its pane'); });
  const other = await page.context().newPage();
  const otherOk = watchTab(other);
  try {
    await liveBarState(other);
    await other.goto(dash + '/#addon/focus/t/t_nothere1');
    await other.waitForSelector('[data-key="live-wall"] .wall-band', { timeout: 15000 });
    if ((await panesNow(other)).includes('t_nothere1')) throw new Error('an unknown ticket address opened an empty pane');
    await other.waitForFunction(() => /There is no ticket with this address\./.test(document.body.innerText), null, { timeout: 8000 })
      .catch(() => { throw new Error('an unknown ticket address does not say so'); });
    otherOk();
  } finally { await other.close(); }
}

// Step 30: keyboard only. Tab reaches a tile, Enter opens it with the keyboard in the layer, Esc goes back one step at
// a time until the bar, and the keyboard lands on the bar's Open.
async function keyboard(page, dash) {
  await wallPage(page, dash, 'fd30');
  let found = false;
  for (let i = 0; i < 120 && !found; i++) {
    await page.keyboard.press('Tab');
    found = await page.evaluate(() => document.activeElement?.dataset?.wallOpen === 't_bar238');
  }
  if (!found) throw new Error('Tab never reached the tile of ORCH-238');
  await page.keyboard.press('Enter');
  await page.waitForFunction(() => window.LiveLayer?.panes?.includes('t_bar238'), null, { timeout: 5000 });
  await page.waitForTimeout(200);
  if (!(await inDock(page))) throw new Error('after Enter the keyboard is not in the layer');
  const mode0 = await page.evaluate(() => window.LiveLayer.mode);
  if (mode0 !== 'bottom') throw new Error(`Enter opened the layer ${mode0}, not at the bottom`);
  await page.keyboard.press('Escape');
  await page.waitForTimeout(250);
  const mode1 = await page.evaluate(() => window.LiveLayer.mode);
  if (mode1 !== 'bar') throw new Error(`one Esc from the layer at the bottom went to ${mode1}, not the bar`);
  if (!(await page.evaluate(() => document.activeElement?.matches?.('[data-key="live-open"]')))) throw new Error('after Esc the keyboard is not on the bar\'s Open');
}

// Step 31: two tabs. A pin and a new name made in one tab show in the other on its next look (no reload).
async function twoTabs(page, dash) {
  const other = await page.context().newPage();
  const otherOk = watchTab(other);
  try {
    await wallPage(other, dash, 'fd31b');
    await wallPage(page, dash, 'fd31a');  // the stand-in server's pins start fresh here
    await page.click(`${tileOf('t_bar232')} [data-wall-pin]`);
    await page.evaluate(() => window.LiveLayer.open('t_bar232'));
    await page.click('#live-dock [data-live="rename"][data-session="t_bar232"]');
    await page.keyboard.press('ControlOrMeta+A');
    await page.keyboard.type('Usage page (mine)');
    await page.keyboard.press('Enter');
    await other.waitForFunction(() => window.LiveLayer?.pins?.includes('t_bar232'), null, { timeout: 10000 })
      .catch(() => { throw new Error('the pin made in one tab did not show in the other'); });
    await other.waitForFunction(() => /Usage page \(mine\)/.test(document.querySelector('[data-tile="t_bar232"]')?.innerText || ''), null, { timeout: 10000 })
      .catch(() => { throw new Error('the name given in one tab did not show in the other'); });
    otherOk();
  } finally { await other.close(); }
}

// Step 32: a session that ends while it is open: its tile leaves Working and its pane offers the Start choice.
async function ended(page, dash) {
  await wallPage(page, dash, 'fd32');
  await page.evaluate(() => window.LiveLayer.open('t_bar235'));
  await page.waitForSelector('#live-dock [data-live-lines], #live-dock [data-key="live-panel"]', { timeout: 5000 });
  barEnded.add('t_bar235');
  await page.waitForSelector('#live-dock [data-key="live-start"]', { timeout: 15000 })
    .catch(() => { throw new Error('the pane of a session that ended does not offer Start'); });
  const s = await page.getAttribute(tileOf('t_bar235'), 'data-s');
  if (s !== 'closed') throw new Error(`the tile of a session that ended says ${s}, not closed`);
}

const STEPS = [
  {
    n: 1, pic: 'fd-01-dashboard', area: 'start', title: 'The dashboard opens', feature: [],
    do: ['Open the dashboard link of the test workspace.'],
    see: ['Home shows its content, no loading shape stays.', 'At 390 wide nothing scrolls sideways.'],
    async run({ page, dash }) {
      await page.goto(dash + '/#home');
      await mainHasText(page);
      await noSideways(page);
    },
    draft: { q: '?page=home' },
  },
  {
    n: 2, pic: 'fd-02-focus-today', area: 'start', title: 'Today\'s Focus still works with Preview off', feature: [], focus: true,
    do: ['Leave the Preview switch off.', 'Open Focus from the side bar.'],
    see: ['Today\'s Focus opens with its list of live helpers.', 'Nothing of the new Focus shows.'],
    async run({ page, focus }) {
      await page.goto(focus + '/');
      await page.waitForSelector('.fx-livenow .helper-row', { timeout: 20000 });
      await noSideways(page);
    },
  },
  {
    n: 3, pic: 'fd-03-preview-on', area: 'start', title: 'Turn the new Focus on with the Preview switch', feature: [],
    do: ['Open Settings and turn on the Preview switch for the new Focus.', 'Open Focus from the side bar.'],
    see: ['Focus opens as the new Focus, marked Preview (the wall of step 4 fills it).', 'The switch is marked Preview.',
      'Turning it off again brings back today\'s Focus.'],
    async run({ page, dash }) {
      await previewSwitch(page, dash);
    },
    draft: { q: '' },
  },
  {
    n: 4, pic: 'fd-04-wall', area: 'wall', title: 'The live wall in bands', feature: [1],
    do: ['Open Focus.', 'Watch a working tile for 10 seconds.'],
    see: ['Bands in this order: Pinned, Needs you and working, In line, Idle and no session.',
      'One summary line on top.', 'Each tile says in one plain sentence what its helper does.',
      'A working tile adds its newest last line by itself.'],
    async run({ page, dash }) {
      await wall(page, dash);
    },
    draft: { q: '?page=focus' },
  },
  {
    n: 5, pic: 'fd-05-needs-you', area: 'wall', title: 'A session that needs you is an orange tile', feature: [2],
    do: ['Find the tile of the helper that waits for an answer.', 'Open it and answer.'],
    see: ['The tile is orange and first after the pinned ones.', 'Its sentence is the question.',
      'Nothing can be answered on the wall itself; the layer shows the question with its options and a field for an own answer.',
      'One click on an option answers it; the question leaves the pane and the tile turns back to Working.'],
    async run({ page, dash }) {
      await needsYou(page, dash);
    },
    draft: { q: '?page=focus&cur=ORCH-238&view=zoom&ask=1' },
  },
  {
    n: 6, pic: 'fd-06-focus-button', area: 'wall', title: 'Focus button on a ticket and Open ticket on a session',
    feature: [3],
    do: ['Open Tickets and press the Focus button of a row.', 'Open a ticket page and press its Focus button.',
      'In the session press Open ticket, also from full screen.'],
    see: ['Every ticket row and every ticket page has the button; it says Watch, Answer, Open or Start to fit the ticket.',
      'The session opens in the layer and the page stays.', 'Open ticket goes back to the same ticket page; the session stays open.'],
    async run({ page, dash, width }) {
      await focusButton(page, dash, width);
    },
    draft: { q: '?page=ticket&tk=ORCH-189' },
  },
  {
    n: 7, pic: 'fd-07-pin-name', area: 'wall', title: 'Pin a session and give it your own name', feature: [9],
    do: ['Pin a working session.', 'Click its name, type a new one and press Enter.'],
    see: ['The pinned session moves to the Pinned band and gets a chip in the bar.', 'The new name shows on its tile, its pane and its chip.',
      'Both stay after a reload; Unpin moves it back.'],
    async run({ page, dash, width }) {
      await pinName(page, dash, width);
    },
    draft: { q: '?page=focus&cur=Manager&view=zoom&ren=1' },
  },
  {
    n: 8, pic: 'fd-08-many', area: 'wall', title: 'Works with 24 and more sessions', feature: [11],
    do: ['Use a workspace with 24 sessions.', 'Type a word in the filter.', 'Collapse the In line band.'],
    see: ['The wall scrolls; bands collapse and stay collapsed.', 'The filter keeps only the matching tiles.',
      'Counts read right: "1 session", "2 sessions".'],
    async run({ page, dash, width }) {
      await manySessions(page, dash, width);
    },
    draft: { q: '?page=focus&many=1' },
  },
  {
    n: 9, pic: 'fd-09-bar', area: 'bar', title: 'The bar under every page', feature: [7, 11],
    do: ['Open Home, then Tickets, then Review.', 'Press the "in line" count in the bar.', 'Type in the list\'s search.'],
    see: ['The bar is under every page, calm, on one line that never wraps.',
      'Chips only for sessions that need you and pinned ones; the rest are counts such as "9 in line".',
      'A count opens a list you can search.'],
    async run({ page, dash }) {
      await liveBarState(page);
      for (const where of ['#home', '#tickets', '#review']) {
        await page.goto(dash + '/' + where);
        await mainHasText(page);
        await page.waitForSelector('#live-bar .lbar-sw', { timeout: 10000 });
        await barIsOneRow(page);
        await noSideways(page);
      }
      const words = await page.textContent('#live-bar');
      if (!/ORCH-238|Needs you|3/.test(words)) throw new Error('the bar does not show the sessions that need you');
      // the "in line" count, or the More count it folded into when the row is short
      const count = (await page.$('#live-bar [data-lbar-list="queue"]')) ? 'queue' : 'more';
      await page.click(`#live-bar [data-lbar-list="${count}"]`);
      await page.waitForSelector('#live-bar .lbar-pop .lbar-row', { timeout: 5000 });
      const head = await page.textContent('#live-bar .lbar-pop-h');
      if (count === 'queue' && head.trim() !== 'In line (9)') throw new Error(`the list says "${head}", not "In line (9)"`);
      await page.fill('#live-bar [data-lbar-q]', 'logo');
      await page.waitForFunction(() => document.querySelectorAll('#live-bar .lbar-row').length === 1, null, { timeout: 5000 });
      if (!/New logo on every page/.test(await page.textContent('#live-bar .lbar-list'))) throw new Error('the search does not find "logo"');
      await page.fill('#live-bar [data-lbar-q]', '');
      await page.waitForFunction(n => document.querySelectorAll('#live-bar .lbar-row').length >= n, 9, { timeout: 5000 });
      await noSideways(page);
    },
    draft: { q: '?page=home&many=1&list=queue' },
  },
  {
    n: 10, pic: 'fd-10-layer', area: 'layer', title: 'The layer at the bottom, on the right, full screen, to the bar, to the side',
    feature: [7],
    do: ['Open a session from the bar.', 'Change to Tickets, Review and Home.', 'Use Place: bottom, right, full screen; press Esc twice.',
      'Open it again, minimise it to the bar, then put it to the side and open it from the edge.', 'Make it larger, then reload the page.'],
    see: ['Each place works and the page stays usable behind it; on a phone there is no right.', 'The layer stays open while the page changes.',
      'Esc goes back one step: full screen, then the panel, then the bar.', 'In full screen Tab stays in the layer.',
      'Minimise leaves only the bar; to the side leaves a slim edge.', 'After the reload the layer opens where it was last, at the same size.'],
    async run({ page, dash, width }) {
      await layer(page, dash, width);
    },
    draft: { q: '?page=home&mode=right&menu=pos' },
  },
  {
    n: 11, pic: 'fd-11-zoom', area: 'layer', title: 'Zoom and full screen, Esc goes one step back', feature: [8],
    do: ['Click a tile on the wall.', 'Press full screen.', 'Press Esc twice.'],
    see: ['The tile opens large in the layer, the keyboard in it.', 'Full screen keeps only a slim strip of the other sessions.',
      'Each Esc goes back one step: full screen, then the layer, then the wall.'],
    async run({ page, dash, width }) {
      await zoom(page, dash, width);
    },
    draft: { q: '?page=focus&cur=ORCH-232&view=zoom&term=1&mode=full' },
  },
  {
    n: 12, pic: 'fd-12-split', area: 'split', title: 'Split into two and three sessions with the pane controls', feature: [7],
    do: ['In the layer press Add beside twice.', 'Change to Tickets, Review and Home.', 'On one pane use pin, Place, minimise and close.'],
    see: ['Two, then three panes sit next to each other; on the right they are stacked.', 'Every pane has pin, add beside, place, minimise and close.',
      'The split stays while the page changes.', 'Closing a pane gives its room to the others.',
      'On a phone one session shows at a time and there is no add beside.'],
    async run({ page, dash, width }) {
      await split(page, dash, width);
    },
    draft: { q: '?page=home&mode=bottom&split=3' },
  },
  {
    n: 13, pic: 'fd-13-stays-open', area: 'layer', title: 'Focus stays open with typed text and split while you change pages',
    feature: [7],
    do: ['Open two sessions side by side, type a message without sending.', 'Change to Home, Tickets and Review, then press Back.'],
    see: ['The layer, its split and the typed text stay as they were.', 'The page itself does not reload (no flash).',
      'Back and links work like before.'],
    async run({ page, dash }) {
      await staysOpen(page, dash);
    },
    draft: { q: '?page=tickets&mode=bottom&split=2' },
  },
  {
    n: 14, pic: 'fd-14-start', area: 'sessions', title: 'Start: continue, fresh start or an earlier session', feature: [4, 12],
    do: ['Open a ticket that has no session and press Start.', 'Look at the three choices and the earlier sessions list.',
      'Pick tool and model and start fresh.'],
    see: ['One question: continue the last conversation, fresh start, or reopen an earlier session.',
      'Up to 10 earlier sessions with date and step.', 'The usual tool and model are preselected: one click starts it.',
      'How many helper places are in use; when all are taken, how many wait in line, and a start waits in line.'],
    async run({ page, dash }) {
      await startChoice(page, dash);
    },
    okConsole: /status of 422 \(Unprocessable/i,  // the start that waits in line: orch refuses it and puts it in line
    draft: { q: '?page=focus&cur=ORCH-189&view=zoom&ask=1' },
  },
  {
    n: 15, pic: 'fd-15-no-ticket', area: 'sessions', title: 'Sessions without a ticket', feature: [6],
    do: ['Open the New menu in the bar.', 'Start an Empty helper, a Chat helper, a Plain terminal and the Manager.',
      'Open Focus and press one of the four buttons at its top.'],
    see: ['The four choices are at the top of Focus and in the New menu.', 'Each new session opens in the layer and is pinned by itself.',
      'One that is open already says "Already open: go to it" and is not started twice.'],
    async run({ page, dash, width }) {
      await noTicket(page, dash, width);
    },
    draft: { q: '?page=focus&menu=new' },
  },
  {
    n: 16, pic: 'fd-16-tool-model', area: 'sessions', title: 'Tool, model and open time on every session', feature: [12],
    do: ['Open a session that needs you from the bar.', 'Look at the pane: what it does now, its last lines and the line under them.',
      'Press Stop in the pane; open an idle session and read its Stop button.',
      'Open the model choice of a working session and pick another model.'],
    see: ['The open question, the last lines of its screen, then tool and model (for example "Helper · Opus").',
      'How long it is open and how long it stays (warm while it works, or when it closes for being idle).',
      'All of it stays current while you look; the keyboard place does not jump.',
      'Stop in the pane stops its helper; an idle helper\'s button says Stop idle helper.',
      'A new model applies when the helper finishes its current step (or at its next start) and says so.'],
    async run({ page, dash }) {
      await paneData(page, dash);
      await page.unrouteAll({ behavior: 'ignoreErrors' });
      await page.goto('about:blank');  // the same #home address would not load the page again
      await toolModel(page, dash);
    },
    draft: { q: '?page=focus&cur=ORCH-247&view=zoom&pm=ORCH-247:model' },
  },
  {
    n: 17, pic: 'fd-17-chat', area: 'chat', title: 'Chat: messages with the results inside', feature: [5],
    waits: T.chat,
    do: ['Open a session in Chat view.', 'Read the messages and press a result inside one.'],
    see: ['Plain messages with time; step events between them.', 'Results show as small widgets and open big.'],
    draft: { q: '?page=focus&cur=ORCH-228&view=zoom' },
  },
  {
    n: 18, pic: 'fd-18-message-box', area: 'message box', title: 'Files and screenshots in the message box, with a preview before sending',
    feature: [13], waits: T.chat,
    do: ['Attach a file, paste a screenshot, drop a second file.', 'Remove one, then send.'],
    see: ['Each one shows as a small preview before sending.', 'Removing one takes it out; the sent message carries the rest.'],
    draft: { q: '?page=focus&cur=ORCH-238&view=zoom&att=1' },
  },
  {
    n: 19, pic: 'fd-19-voice', area: 'voice', title: 'Voice into the message box', feature: [13],
    waits: T.chat,
    do: ['With the relay on, press the microphone and speak.', 'Stop, read the words in the box, edit them.', 'Turn the relay off.'],
    see: ['While listening the button says so and Esc cancels.', 'The words land in the box and are never sent by themselves.',
      'With the relay off there is no microphone.'],
    draft: { q: '?page=focus&cur=ORCH-238&view=zoom&voice=done' },
  },
  {
    n: 20, pic: 'fd-20-widgets', area: '16 widgets', title: 'All 16 result widgets, small and big', feature: [10],
    waits: T.widgets,
    do: ['Open the style guide, section Results.', 'Open each widget big, use the arrows to go to the next one, close with Esc.'],
    see: ['One small widget for each of the 16 kinds: ' + WIDGETS.join(', ') + '.',
      'Each opens big in an overlay; arrows step through, Esc closes and gives the focus back.',
      'Empty, loading and error look like the style guide states.'],
    draft: { q: '?page=widgets' },
  },
  {
    n: 21, pic: 'fd-21-widgets-ticket', area: '16 widgets', title: 'The same widgets on a ticket page', feature: [10],
    waits: T.widgets,
    do: ['Open a ticket with results.', 'Open one result big.'],
    see: ['The ticket shows the same widgets as Focus.', 'The big overlay is the same one.'],
    draft: { q: '?page=ticket&tk=ORCH-228&res=ORCH-228:0' },
  },
  {
    n: 22, pic: 'fd-22-terminal', area: 'terminal', title: 'A real terminal: type, select, copy and paste', feature: [5],
    waits: T.terminal,
    do: ['Switch a session to Terminal.', 'Click in it and type a command, select text, copy it, paste it back.'],
    see: ['It behaves like the Terminal app: typing, selection, copy and paste.', 'Copy all copies the screen text.',
      'It can only be reached from this computer.'],
    draft: { q: '?page=focus&cur=ORCH-232&view=zoom&term=1' },
  },
  {
    n: 23, pic: 'fd-23-motion', area: 'motion', title: 'Opening, zooming, pinning and splitting animate', feature: [7, 8, 9],
    waits: T.look,
    do: ['Open the layer, zoom a tile, pin a session, add a pane beside, each once.'],
    see: ['Each change moves smoothly and quickly, nothing jumps.', 'The picture is taken after the move ends.'],
    draft: { q: '?page=focus&cur=ORCH-228&view=zoom' },
  },
  {
    n: 24, pic: 'fd-24-reduced-motion', area: 'reduced motion', title: 'With reduced motion everything stays still',
    feature: [7, 8, 9], waits: T.look, reduce: true,
    do: ['Turn on reduced motion in the system settings.', 'Repeat step 23.'],
    see: ['Every change happens at once, without movement.', 'The live last lines still update.'],
    draft: { q: '?page=focus&cur=ORCH-228&view=zoom' },
  },
  {
    n: 25, pic: 'fd-25-phone', area: 'phone width', title: 'Phone width: one session at a time', feature: [7],
    do: ['At 390 wide open Focus, open a session, then try to put the layer on the right.'],
    see: ['The wall is one column.', 'The layer opens at the bottom and shows one session; right falls back to bottom.',
      'Nothing scrolls sideways; every button can be reached.'],
    async run({ page, dash, width }) {
      await phone(page, dash, width);
    },
    draft: { q: '?page=focus&cur=ORCH-238&mode=right' },
  },
  {
    n: 26, pic: 'fd-26-history', area: 'sessions', title: 'Earlier sessions in the History tab, reopened with one click', feature: [4],
    do: ['Open a session in the layer and press History (in More when the pane is narrow).', 'Press Reopen on an earlier session.'],
    see: ['Up to 10 sessions of the ticket, newest first, each with its time, first message and number of messages.',
      'The session in use says In use; one that is not on this computer has no Reopen.',
      'Reopen starts the helper on that conversation and the list closes.'],
    async run({ page, dash }) {
      await history(page, dash);
    },
    draft: { q: '?page=focus&cur=ORCH-189&view=zoom&ask=1' },
  },
  {
    n: 27, pic: 'fd-27-model-choice', area: 'sessions', title: 'Change the model of a running session', feature: [12],
    waits: T.sessions,
    do: ['Open the model choice of a running session.'],
    see: ['A new model applies from the next fresh start and says so.'],
    draft: { q: '?page=focus&cur=ORCH-247&view=zoom&pm=ORCH-247:model' },
  },
  {
    n: 28, pic: 'fd-28-groups', area: 'layer', title: 'An epic and its helpers in one place', feature: [],
    do: ['Open Focus while an epic has a main helper and helpers on its tickets.', 'Click the epic\'s tile.',
      'Click another helper in the list beside the session, then write it a message.'],
    see: ['The epic is one tile with its helpers counted ("3 helpers · 2 small helpers"), orange while one of them needs you.',
      'The click opens the helper that needs you, with the main helper, every helper, the small helpers (watch only) and Earlier sessions beside it.',
      'A click on a helper shows it in the same pane; the message box says who gets the message.',
      'On a phone the list is one line that scrolls inside itself.'],
    async run({ page, dash, width }) {
      await groups(page, dash, width);
    },
    draft: { q: '?page=focus&cur=ORCH-228&view=zoom' },
  },
  {
    n: 29, pic: 'fd-29-address', area: 'layer', title: 'The address of a ticket opens its session', feature: [3],
    do: ['Open the address of a ticket\'s session (#addon/focus/t/<ticket>) in a new tab.', 'Open the address of a ticket that does not exist.'],
    see: ['The wall shows with that session open in the layer, the keyboard in its pane.',
      'An unknown ticket shows the wall, opens nothing and says "There is no ticket with this address."'],
    async run({ page, dash }) {
      await address(page, dash);
    },
    draft: { q: '?page=focus&cur=ORCH-201&view=zoom' },
  },
  {
    n: 30, pic: 'fd-30-keyboard', area: 'wall', title: 'Keyboard only: wall, layer and back to the bar', feature: [8],
    do: ['Without a mouse, press Tab until a tile is marked, then Enter.', 'Press Esc until the layer is back in the bar.'],
    see: ['Enter opens the session in the layer with the keyboard in it.', 'Each Esc goes back one step; at the end the keyboard is on the bar.'],
    async run({ page, dash }) {
      await keyboard(page, dash);
    },
    draft: { q: '?page=focus&cur=ORCH-238&view=zoom' },
  },
  {
    n: 31, pic: 'fd-31-two-tabs', area: 'sessions', title: 'Two tabs: a pin and a name show in both', feature: [11],
    do: ['Open Focus in two tabs.', 'In one, pin a session and give it a name.'],
    see: ['The other tab shows the pin and the name within a few seconds, without a reload.'],
    async run({ page, dash }) {
      await twoTabs(page, dash);
    },
    draft: { q: '?page=focus' },
  },
  {
    n: 32, pic: 'fd-32-ended', area: 'sessions', title: 'A session that ends while it is open', feature: [4],
    do: ['Open a working session in the layer.', 'Let its helper stop.'],
    see: ['Its tile leaves Working and says No session.', 'Its pane offers the Start choice.'],
    async run({ page, dash }) {
      await ended(page, dash);
    },
    draft: { q: '?page=focus&cur=ORCH-235&view=zoom&ask=1' },
  },
];

module.exports = { STEPS, AREAS, SIZES, WIDGETS, noSideways, mainHasText, liveBarState, barIsOneRow, livePreview };
