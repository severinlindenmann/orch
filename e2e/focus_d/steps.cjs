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
    if (body.op !== 'focus_preview.set') return route.continue();
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
// (/api/sessions, ORCH-359: the bar and the panes read it), with the Preview switch on. Pinning is
// kept in the browser until the wall stores it. Everything else is the real page: the bar, its fold, list and search.
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
async function liveBarState(page) {
  const live = { name: 'focus', label: 'Focus', icon: 'target', active: true, removable: true, shipped: false,
    description: 'A live page for one ticket.', page: { path: '/', label: 'Open Focus', live_session: true },
    dashboard: { label: 'Focus', icon: 'target', order: 20 } };
  const HELPER = { wait: 'you', run: 'working', idle: 'idle' };
  await page.addInitScript(() => { try { localStorage.setItem('orch.live.pins', JSON.stringify(['t_bar228'])); } catch (e) { /* none */ } });
  await page.route(/\/api\/state(\?.*)?$/, async route => {
    const res = await route.fetch();
    if (res.status() !== 200) return route.fulfill({ response: res });
    const st = await res.json();
    const base = (st.tickets || [])[0] || {};
    const extra = BAR_SESSIONS.map(([s, key, title]) => ({ ...base, id: 't_bar' + key.slice(5), key, title,
      status: 'active', questions: [], checks: [], sessions: [] }));
    st.tickets = [...(st.tickets || []).filter(t => !String(t.id).startsWith('t_bar')), ...extra];
    st.runs = { ...(st.runs || {}) };
    BAR_SESSIONS.forEach(([s, key]) => {
      st.runs['t_bar' + key.slice(5)] = s === 'queue' ? { running: false, hold: 'Waits for a free place' }
        : { running: true, helper: { state: HELPER[s] }, claim: { agent: 'agent:claude' } };
    });
    st.addons = [...(st.addons || []).filter(a => a.name !== live.name), live];
    st.settings = { ...(st.settings || {}), focus_preview_on: true,
      addons: [...((st.settings || {}).addons || []).filter(a => a.name !== live.name), live] };
    route.fulfill({ response: res, json: st });
  });
  await page.route(/\/api\/sessions(\?.*)?$/, route => route.fulfill({ json: { sessions: barSessions(), lines: 8, age_ms: 0 } }));
}
// The same 24 sessions as the live sessions API gives them (the shape in workspace-addons/dashboard/.../sessions.py).
const BAR_STATUS = { wait: 'needs-you', run: 'working', queue: 'in-line', idle: 'idle' };
const BAR_WORD = { wait: 'Waits for you', run: 'Working', queue: 'In line', idle: 'Idle' };
function barSessions() {
  return BAR_SESSIONS.map(([s, key, title], i) => {
    const live = s !== 'queue';
    return { id: 't_bar' + key.slice(5), key, title, status: BAR_STATUS[s], word: BAR_WORD[s],
      detail: s === 'run' ? 'Running the tests' : '', waiting_on: [],
      question: s === 'wait' ? 'Keep the old file name when the same file is added twice?' : null,
      lines: live ? ['⏺ Bash(node --test tests/attach.test.js)', '  ⎿ ✔ adds a picture to a ticket (38 ms)',
        '  ⎿ ✔ adds a note below the files (12 ms)', '⏺ ' + title + ': step ' + (2 + (i % 3)) + ' of 5'] : [],
      tool: live ? 'Helper' : null, model: i % 2 ? 'Opus' : 'Sonnet', mode: live ? 'live' : null,
      opened_at: null, open_seconds: live ? (20 + 3 * i) * 60 : null, idle_seconds: s === 'idle' ? 18 * 60 : null,
      closes_in_seconds: s === 'idle' ? 42 * 60 : live ? 3600 : null, last_at: null };
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
  await page.evaluate(() => { try { localStorage.removeItem('orch.live.layer'); } catch (e) { /* none */ } });
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
  await page.addInitScript(() => { try { if (!sessionStorage.getItem('fd10')) { localStorage.removeItem('orch.live.layer'); sessionStorage.setItem('fd10', '1'); } } catch (e) { /* none */ } });
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
  await page.evaluate(() => { try { localStorage.removeItem('orch.live.layer'); } catch (e) { /* none */ } });
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
  await page.waitForFunction(k => JSON.parse(localStorage.getItem('orch.live.pins') || '[]').includes(k), one, { timeout: 5000 });
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
    waits: T.wall,
    do: ['Open Focus.', 'Watch a working tile for 10 seconds.'],
    see: ['Bands in this order: Pinned, Needs you, Working, In line, Idle, No session.',
      'One summary line on top.', 'Each tile says in one plain sentence what its helper does.',
      'A working tile adds its newest last line by itself.'],
    draft: { q: '?page=focus' },
  },
  {
    n: 5, pic: 'fd-05-needs-you', area: 'wall', title: 'A session that needs you is an orange tile', feature: [2],
    waits: T.wall,
    do: ['Find the tile of the helper that waits for an answer.', 'Open it and answer.'],
    see: ['The tile is orange and first after the pinned ones.', 'Its sentence is the question.',
      'Nothing can be answered on the wall itself; after the answer the tile turns back to Working.'],
    draft: { q: '?page=focus&cur=ORCH-238&view=zoom&ask=1' },
  },
  {
    n: 6, pic: 'fd-06-focus-button', area: 'wall', title: 'Focus button on a ticket and Open ticket on a session',
    feature: [3], waits: T.wall,
    do: ['Open a ticket page.', 'Press its Focus button.', 'In the session press Open ticket.'],
    see: ['The button says Watch, Answer, Open or Start to fit the ticket.', 'The session opens in the layer.',
      'Open ticket goes back to the same ticket page.'],
    draft: { q: '?page=ticket&tk=ORCH-189' },
  },
  {
    n: 7, pic: 'fd-07-pin-name', area: 'wall', title: 'Pin a session and give it your own name', feature: [9],
    waits: T.wall,
    do: ['Pin a working session.', 'Click its name, type a new one and press Enter.'],
    see: ['The pinned session moves to the Pinned band and gets a chip in the bar.', 'The new name shows on its tile, its pane and its chip.'],
    draft: { q: '?page=focus&cur=Manager&view=zoom&ren=1' },
  },
  {
    n: 8, pic: 'fd-08-many', area: 'wall', title: 'Works with 24 and more sessions', feature: [11],
    waits: T.wall,
    do: ['Use a workspace with 24 sessions.', 'Type a word in the filter.', 'Collapse the In line band.'],
    see: ['The wall scrolls; bands collapse and stay collapsed.', 'The filter keeps only the matching tiles.',
      'Counts read right: "1 session", "2 sessions".'],
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
    waits: T.layer,
    do: ['Click a tile on the wall.', 'Press full screen.', 'Press Esc twice.'],
    see: ['The tile grows into a large view.', 'Full screen keeps only a slim strip of the other sessions.',
      'Each Esc goes back one step: full screen, then zoom, then the wall.'],
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
    waits: T.sessions,
    do: ['Open a ticket that has no session and press Start.', 'Look at the three choices and the earlier sessions list.',
      'Pick tool and model and start fresh.'],
    see: ['One question: continue the last conversation, fresh start, or reopen an earlier session.',
      'Up to 10 earlier sessions with date and step.', 'The usual tool and model are preselected: one click starts it.'],
    draft: { q: '?page=focus&cur=ORCH-189&view=zoom&ask=1' },
  },
  {
    n: 15, pic: 'fd-15-no-ticket', area: 'sessions', title: 'Sessions without a ticket', feature: [6],
    waits: T.sessions,
    do: ['Open the New menu in the bar.', 'Start an Empty helper, a Chat helper, a Plain terminal and the Manager.'],
    see: ['The four choices are at the top of Focus and in the New menu.', 'Each new session is pinned by itself.'],
    draft: { q: '?page=focus&menu=new' },
  },
  {
    n: 16, pic: 'fd-16-tool-model', area: 'sessions', title: 'Tool, model and open time on every session', feature: [12],
    do: ['Open a session that needs you from the bar.', 'Look at the pane: what it does now, its last lines and the line under them.'],
    see: ['The open question, the last lines of its screen, then tool and model (for example "Helper · Opus").',
      'How long it is open and how long it stays (warm while it works, or when it closes for being idle).',
      'All of it stays current while you look; the keyboard place does not jump.'],
    async run({ page, dash }) {
      await paneData(page, dash);
    },
    draft: { q: '?page=focus&cur=ORCH-247&view=zoom' },
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
    waits: T.layer,
    do: ['At 390 wide open Focus, open a session, then try to put the layer on the right.'],
    see: ['The wall is one column.', 'The layer opens at the bottom and shows one session; right falls back to bottom.',
      'Nothing scrolls sideways; every button can be reached.'],
    draft: { q: '?page=focus&cur=ORCH-238&mode=right' },
  },
  {
    n: 26, pic: 'fd-26-model-choice', area: 'sessions', title: 'Change the model of a running session', feature: [12],
    waits: T.sessions,
    do: ['Open the model choice of a running session.'],
    see: ['A new model applies from the next fresh start and says so.'],
    draft: { q: '?page=focus&cur=ORCH-247&view=zoom&pm=ORCH-247:model' },
  },
];

module.exports = { STEPS, AREAS, SIZES, WIDGETS, noSideways, mainHasText, liveBarState, barIsOneRow, livePreview };
