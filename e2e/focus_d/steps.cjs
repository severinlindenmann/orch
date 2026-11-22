// The click-through of the new Focus (draft D, ORCH-261): every feature as one numbered step with what to do, what
// must be seen and the picture to take at 1280, 1440, 1920 and 390 wide. Read by e2e/focus_d/clickthrough.cjs (runs it) and
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

const SIZES = [[1280, 800], [1440, 900], [1920, 1080], [390, 844]];  // 1440 and 390: the owner's widths for Focus (ORCH-816)

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

// The newest message of each chat in the layer is whole: inside the chat and above the message box; while a question
// waits, the question (its orange card, or its line when the card has no answers) is whole above the message box
// instead, and the chat scrolls under it (ORCH-1361).
async function newestWhole(page, where) {
  const look = () => page.evaluate(() => [...document.querySelectorAll('#live-dock .live-chat:not([hidden])')].map(chat => {
    // a waiting question is the newest thing: then it must be whole instead
    const ask = chat.closest('.live-pb')?.querySelector(':scope > :is([data-live-ask], [data-live-now][data-live-q]):not([hidden])');
    const last = ask || [...chat.children].filter(el => el.getClientRects().length).pop();
    if (!last) return null;
    const r = last.getBoundingClientRect(), c = chat.getBoundingClientRect();
    const box = chat.closest('.live-pb')?.querySelector(':scope > .live-msg'), pb = chat.closest('.live-pb').getBoundingClientRect();
    const bottom = Math.min(ask ? Infinity : c.bottom, pb.bottom, box ? box.getBoundingClientRect().top : Infinity), top = Math.max(ask ? -Infinity : c.top, pb.top);
    return r.top >= top - 1 && r.bottom <= bottom + 1 ? null : `"${last.innerText.trim().replace(/\s+/g, ' ').slice(0, 30)}" ${Math.round(r.top)}-${Math.round(r.bottom)} shown ${Math.round(top)}-${Math.round(bottom)}`;
  }).filter(Boolean));
  let cut = await look();
  for (let i = 0; cut.length && i < 15; i++) { await page.waitForTimeout(200); cut = await look(); }  // it follows after a resize
  if (cut.length) throw new Error(`${where}: the newest message is cut off: ${cut.join('; ')}`);
}

// No text in the layer is under 12 px or off the SX-2 type scale (size/line height), the terminal aside (ORCH-1361).
async function layerTextScale(page, where) {
  const off = await page.evaluate(() => {
    const scale = new Set(['28/36', '20/28', '16/24', '14/20', '13/18', '12/16']), out = new Set();
    const dock = document.getElementById('live-dock'); if (!dock) return [];
    const tw = document.createTreeWalker(dock, NodeFilter.SHOW_TEXT);
    while (tw.nextNode()) {
      const el = tw.currentNode.parentElement;
      if (!tw.currentNode.textContent.trim() || !el.getClientRects().length || el.closest('.term, pre, code, .sr-only')) continue;
      const cs = getComputedStyle(el), k = `${parseFloat(cs.fontSize)}/${parseFloat(cs.lineHeight) || cs.lineHeight}`;
      if (!scale.has(k)) out.add(`${k} "${el.textContent.trim().slice(0, 24)}"`);
    }
    // the words typed into a field and its placeholder are never under 12 px either
    for (const f of dock.querySelectorAll('input:not([type=hidden]), textarea')) {
      if (f.getClientRects().length && parseFloat(getComputedStyle(f).fontSize) < 12) out.add(`${getComputedStyle(f).fontSize} field "${f.placeholder || f.name}"`);
    }
    return [...out];
  });
  if (off.length) throw new Error(`${where}: text off the type scale: ${off.slice(0, 5).join(', ')}`);
}

// ORCH-1328: every pane of a session that waits on a question shows the orange card with its answer buttons (a split
// pane and the phone sheet showed only the bold words); nothing in a pane is cut by another part or runs out of it.
async function askCardsInPanes(page) {
  const waits = BAR_SESSIONS.filter(([s]) => s === 'wait').map(([, key]) => 't_bar' + key.slice(5));
  await page.waitForFunction(ids => [...document.querySelectorAll('#live-dock .live-pane')].filter(p => ids.includes(p.dataset.session))
    .every(p => p.querySelector('[data-live-ask]:not([hidden]) [data-key="live-ask-option-0"]')), waits, { timeout: 8000 })
    .catch(() => { throw new Error('a pane that waits on a question has no question card with answer buttons'); });
  const bad = await page.evaluate(ids => {
    const out = [], t = document.createElement('span');
    t.style.color = 'var(--needs-you)'; document.body.append(t);
    const orange = getComputedStyle(t).color; t.remove();
    const shown = el => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0 ? r : null; };
    for (const p of document.querySelectorAll('#live-dock .live-pane')) {
      const name = p.dataset.session, card = p.querySelector('[data-live-ask]:not([hidden])');
      if (ids.includes(name) && card && getComputedStyle(card).borderTopColor !== orange) out.push(name + ': the question card is not orange');
      // ORCH-1568: the answer buttons show inside the pane, not scrolled away in a short split pane (fd-12 at 1280)
      if (ids.includes(name) && card) {
        const pb = p.querySelector('.live-pb[data-live-body]'), box = (pb || p).getBoundingClientRect();
        for (const b of card.querySelectorAll('[data-key^="live-ask-option-"]')) {
          const r = b.getBoundingClientRect(), cr = card.getBoundingClientRect();
          if (!(r.height > 0 && r.top >= cr.top - 1 && r.bottom <= cr.bottom + 1 && r.top >= box.top - 1 && r.bottom <= box.bottom + 1)) {
            const kids = pb ? [...pb.children].map(k => `${k.className || k.tagName}:${Math.round(k.getBoundingClientRect().height)}`).join(',') : '';
            out.push(name + `: an answer button of the question card is cut off (pane ${Math.round(box.height)} px: ${kids})`);
            break;
          }
        }
      }
      // the header is one row of icon buttons beside the title where it fits
      const head = p.querySelector('.live-ph'), title = head && shown(head.querySelector('.live-pt'));
      if (head?.dataset.compact !== undefined) for (const b of head.querySelectorAll('.live-ctl > .btn')) {
        const r = shown(b);
        if (r && b.querySelector('.live-word:not(.sr-only)')) out.push(name + ': a header button of a narrow pane shows its word');
        if (r && !(b.getAttribute('aria-label') || b.textContent.trim())) out.push(name + ': a header button has no name');
        if (r && !b.title) out.push(name + ': a header button has no tooltip');
        if (r && window.innerWidth > 720 && title && r.top >= title.bottom - 1) out.push(name + ': the header buttons wrap under the title');
      }
      // the empty-chat line and the chat are not covered by the message box
      const msg = p.querySelector('.live-msg'), chat = p.querySelector('[data-live-chat]:not([hidden])');
      const m = msg && shown(msg), c = chat && shown(chat);
      if (m && c && c.bottom > m.top + 1) out.push(name + `: the chat runs under the message box by ${Math.round(c.bottom - m.top)} px`);
      // nor does the pane have more than it can show: then the sticky message box covers the chat as soon as a line is a
      // little taller on another machine (ORCH-1457: 4 px to spare here, 36 px under the box on CI's Linux)
      const body = p.querySelector('.live-pb[data-live-body]');
      if (m && c && body && body.scrollHeight > body.clientHeight + 1) out.push(name + `: the pane has ${body.scrollHeight - body.clientHeight} px more than it shows`);
      const empty = chat?.querySelector('.live-chat-empty'), e = empty && shown(empty);
      if (e && c && (e.bottom > c.bottom + 1 || e.top < c.top - 1)) out.push(name + ': the line "No messages yet" is cut');
    }
    return out;
  }, waits);
  if (bad.length) throw new Error(bad.join('; '));
}

// At phone width the layer is a sheet over most of the screen (ORCH-1328): to tap something of the page under it a
// person minimises the sheet to the bar first, so the test does the same when the sheet covers the target.
async function tapAbove(page, sel) {
  await page.waitForSelector(sel, { timeout: 10000 });
  await page.$eval(sel, el => el.scrollIntoView({ block: 'center' }));
  const covered = await page.$eval(sel, el => { const r = el.getBoundingClientRect(), top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2); return !!top && !el.contains(top) && !!top.closest('#live-dock'); });
  if (covered) {
    await page.click('#live-dock [data-key="live-min"], #live-dock [data-key="live-pane-more"]');
    if (await page.$('[data-key="live-more-menu"] [data-key="live-more-min"]')) await page.click('[data-key="live-more-menu"] [data-key="live-more-min"]');
    await page.waitForSelector('#live-dock[data-mode="bar"]', { timeout: 5000 });
  }
  await page.click(sel);
}

async function mainHasText(page) {
  await page.waitForFunction(() => {
    const m = document.querySelector('main');
    return m && m.innerText.trim().length > 20 && !m.querySelector('.skeleton, [aria-busy=true]');
  }, null, { timeout: 20000 });
}

// Steps 2 and 3. The test dashboard reads files only, so it has no add-on list (that comes from the orch command): the
// steps add the live-session add-on to the page's state, as an updated workspace has it. Nothing else is set: Focus is
// the new Focus with no switch (ORCH-816). Everything else is the real page: the side bar, the address, Settings.
async function focusIsNew(page, dash) {
  const live = { name: 'focus', label: 'Focus', icon: 'target', active: true, removable: true, shipped: false,
    description: 'A live page for one ticket.', page: { path: '/', label: 'Open Focus', live_session: true },
    dashboard: { label: 'Focus', icon: 'target', order: 20 } };
  await page.route(/\/api\/state(\?.*)?$/, async route => {
    const res = await route.fetch();
    if (res.status() !== 200) return route.fulfill({ response: res });
    const st = await res.json();
    st.addons = [...(st.addons || []).filter(a => a.name !== live.name), live];
    st.settings = { ...(st.settings || {}), addons: [...((st.settings || {}).addons || []).filter(a => a.name !== live.name), live] };
    route.fulfill({ response: res, json: st });
  });
  await page.goto(dash + '/#home');
  await mainHasText(page);
  const link = page.locator('a[href="#addon/focus"]').first();
  await link.waitFor({ state: 'attached', timeout: 20000 });  // the side bar's Focus link (folded away at phone width)
  if (await link.isVisible()) await link.click(); else await page.evaluate(() => { location.hash = '#addon/focus'; });
  await page.waitForSelector('[data-key="live-next"]', { timeout: 10000 });
  if (await page.$('iframe.embed')) throw new Error('the old Focus page shows');
  if (/Preview|today.s Focus/.test(await page.textContent('main'))) throw new Error('Focus still says Preview or names an old Focus');
  await noSideways(page);
}

async function noPreviewSwitch(page) {
  await page.evaluate(() => { location.hash = '#settings/addons/focus'; });
  // the Typing switch sits in the add-on's closed "More" fold (ORCH-478): open it first
  await page.waitForSelector('[data-key="settings-more-addon-focus"] summary', { timeout: 20000 });
  await page.evaluate(() => { const d = document.querySelector('[data-key="settings-more-addon-focus"]'); if (d && !d.open) d.querySelector('summary').click(); });
  await page.waitForSelector('[data-key="addon-detail-typing"]', { timeout: 20000 });
  if (await page.$('[data-key="addon-detail-live-preview"]')) throw new Error('Focus settings still have a Preview switch');
  if (/Preview|today.s Focus/.test(await page.textContent('main'))) throw new Error('Focus settings still say Preview');
  await noSideways(page);
}

// Step 13. The page's state has the live-session add-on.
async function previewOn(page) {
  const live = { name: 'focus', label: 'Focus', icon: 'target', active: true, removable: true, shipped: false,
    description: 'A live page for one ticket.', page: { path: '/', label: 'Open Focus', live_session: true },
    dashboard: { label: 'Focus', icon: 'target', order: 20 } };
  await page.route(/\/api\/state(\?.*)?$/, async route => {
    const res = await route.fetch();
    if (res.status() !== 200) return route.fulfill({ response: res });
    const st = await res.json();
    st.addons = [...(st.addons || []).filter(a => a.name !== live.name), live];
    route.fulfill({ response: res, json: st });
  });
}

// Step 9. The test dashboard has no running helpers, so the step gives the page draft D's 24 sessions (3 need you,
// 1 pinned, 3 working, 9 in line, 8 idle) as extra tickets in its state and as the answer of the live sessions API
// (/api/sessions, ORCH-359: the bar and the panes read it), with the live-session add-on. A pin or a name (session.pin /
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
async function liveBarState(page, tweak = null) {
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
    const base = (st.tickets || []).find(t => t.id !== WIDGET_ID) || {};  // not the demo ticket of every widget kind
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
    st.settings = { ...(st.settings || {}), 
      addons: [...((st.settings || {}).addons || []).filter(a => a.name !== live.name), live] };
    if (tweak) tweak(st);
    if (Array.isArray(st.tickets) && st.workspace) barState = st;  // a full state, not the poll's "unchanged"
    route.fulfill({ response: res, json: st });
  });
  await page.route(/\/api\/sessions(\?.*)?$/, route => route.fulfill({ json: { sessions: barSessions(), lines: 8, age_ms: 0 } }));
  // the stand-in tickets have no earlier sessions or files on the test server (it would answer 404)
  await page.route(/\/api\/(sessions|artifacts)\/t_bar\d+/, route => route.fulfill({ json: route.request().url().includes('/artifacts/') ? { files: [] } : { available: true, sessions: [] } }));
}
// The same 24 sessions as the live sessions API gives them (the shape in workspace-addons/dashboard/.../sessions.py).
const BAR_STATUS = { wait: 'needs-you', run: 'working', queue: 'in-line', idle: 'idle', ended: 'closed' };
const BAR_WORD = { wait: 'Needs you', run: 'Working', queue: 'In line', idle: 'Idle', ended: 'No session' };
function barSessions() {
  return BAR_SESSIONS.map(([s0, key, title], i) => {
    const s = barEnded.has('t_bar' + key.slice(5)) ? 'ended' : s0;
    const live = s !== 'queue' && s !== 'ended';
    return { id: 't_bar' + key.slice(5), key, title, status: BAR_STATUS[s], word: BAR_WORD[s],
      detail: s === 'run' ? 'Running the tests' : '', waiting_on: [],
      question: s === 'wait' ? 'Keep the old file name when the same file is added twice?' : null,
      lines: live ? ['⏺ Bash(node --test tests/attach.test.js)', '  ⎿ ✔ adds a picture to a ticket (38 ms)',
        '  ⎿ ✔ adds a note below the files (12 ms)', '⏺ ' + title + ': step ' + (2 + (i % 3)) + ' of 5'] : [],
      tool: live ? 'Claude Code' : null, model: i % 2 ? 'Opus' : 'Sonnet', mode: live ? 'live' : null,
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
  if (!/^Claude Code · Sonnet · open \d+ min · stays warm while it waits for you$/.test(got.meta)) throw new Error('the pane meta reads: ' + got.meta);
  const link = `${body} [data-key="live-open-ticket"]`;
  await page.focus(link);
  await page.evaluate(() => window.LiveSessions.refresh());
  await page.waitForTimeout(300);
  if (!(await page.evaluate(l => document.activeElement === document.querySelector(l), link))) throw new Error('a new answer moved the keyboard place');
  // ORCH-679, since ORCH-817: the pane of a ticket's helper has Stop (ends the current step: run.interrupt) and End
  // session (asks once, then the ticket page's run.stop); both caught before orch. In the header of a wide or compact
  // pane, in More on a phone.
  const acts = [];
  await page.route('**/api/act', async route => {
    const b = route.request().postDataJSON();
    if (!['run.interrupt', 'run.stop'].includes(b.op)) return route.fallback();
    acts.push([b.op, b.args.ticket]);
    route.fulfill({ json: barState });
  });
  const pane = '#live-dock .live-pane[data-session="t_bar238"]';
  const inMore = !(await page.$(`${pane} [data-key="live-stop"]`));
  const stop = `${pane} [data-key="${inMore ? 'live-more-stop' : 'live-stop'}"]`;
  if (inMore) await page.click(`${pane} [data-key="live-pane-more"]`);
  const word = (await page.textContent(stop, { timeout: 5000 }).catch(() => '')).trim();
  // in More, Stop carries its line next to it (ORCH-1362): "Stop" + what it does
  if (!/^Stop(Ends the current step|$)/.test(word)) throw new Error(`the pane of a helper that waits has no Stop (it says "${word}")`);
  await page.click(stop);
  for (let i = 0; i < 20 && !acts.length; i++) await page.waitForTimeout(100);
  if (acts.length !== 1 || acts[0].join() !== 'run.interrupt,t_bar238') throw new Error('Stop did not ask orch to stop the current step: ' + JSON.stringify(acts));
  if (inMore && !(await page.$(`${pane} [data-key="live-more-end"]`))) await page.click(`${pane} [data-key="live-pane-more"]`);
  await page.click(`${pane} [data-key="${inMore ? 'live-more-end' : 'live-end'}"]`);
  await page.click(`${pane} [data-key="live-end-yes"]`, { timeout: 5000 });
  for (let i = 0; i < 20 && acts.length < 2; i++) await page.waitForTimeout(100);
  if (acts.length !== 2 || acts[1].join() !== 'run.stop,t_bar238') throw new Error('End session did not ask orch to stop that helper: ' + JSON.stringify(acts));
  await page.unroute('**/api/act');
  await page.evaluate(() => window.LiveLayer.open('t_bar238'));
  await noSideways(page);
}

// Step 17 (ORCH-687): a ticket's pane opens in Chat: its done step, what the helper said about it with the pull
// request inside, an earlier question with your answer, and the waiting question as an orange card above. Answering
// it there sends the answer (the stand-in server marks it answered, as orch does) and it moves into the chat as yours;
// a message from the box shows at once. Terminal shows the helper's screen; the choice stays after a reload.
// ORCH-1360: Tab from the top of the page never stops on something the Focus layer covers (the page scrolls it clear,
// a full-screen layer makes the page inert), and a chat that is longer than its pane scrolls with the keyboard.
async function noTabUnderLayer(page, stops = 40) {
  await page.evaluate(() => { document.activeElement?.blur?.(); window.scrollTo(0, 0); });
  await page.mouse.click(1, 1).catch(() => {});
  for (let i = 0; i < stops; i++) {
    await page.keyboard.press('Tab');
    const hit = await page.evaluate(() => {
      const el = document.activeElement, dock = document.getElementById('live-dock');
      if (!el || el === document.body || !dock || dock.contains(el)) return '';
      const r = el.getBoundingClientRect();
      if (!r.width || !r.height) return '';
      const top = document.elementFromPoint(Math.min(Math.max(r.left + r.width / 2, 0), innerWidth - 1), Math.min(Math.max(r.top + r.height / 2, 0), innerHeight - 1));
      return top && dock.contains(top) ? (el.getAttribute('aria-label') || el.textContent || el.tagName).trim().replace(/\s+/g, ' ').slice(0, 60) : '';
    });
    if (hit) throw new Error(`Tab stop ${i + 1} is under the Focus layer: ${hit}`);
  }
}
async function chatScrollsByKeyboard(page, chat) {
  const scroller = await page.evaluate(c => {
    const log = document.querySelector(c);
    if (!log || log.tabIndex < 0) return 'unfocusable';
    for (let el = log; el && !el.matches('.live-pane'); el = el.parentElement) if (el.scrollHeight > el.clientHeight + 4 && /auto|scroll/.test(getComputedStyle(el).overflowY)) { el.scrollTop = 0; return 'yes'; }
    return 'short';
  }, chat);
  if (scroller === 'unfocusable') throw new Error('the chat log cannot be reached by keyboard');
  if (scroller === 'short') return;  // nothing to scroll in this pane size
  await page.focus(chat);
  const before = await page.evaluate(c => { let n = 0; for (let el = document.querySelector(c); el && !el.matches('.live-pane'); el = el.parentElement) n += el.scrollTop; return n; }, chat);
  await page.keyboard.press('End');
  await page.keyboard.press('PageDown');
  await page.waitForTimeout(500);  // keyboard scrolling is animated
  const after = await page.evaluate(c => { let n = 0; for (let el = document.querySelector(c); el && !el.matches('.live-pane'); el = el.parentElement) n += el.scrollTop; return n; }, chat);
  if (!(after > before)) {
    const why = await page.evaluate(c => { const a = document.activeElement; const out = ['focus ' + (a?.className || a?.tagName)];
      for (let el = document.querySelector(c); el && !el.matches('.live-pane'); el = el.parentElement) out.push(`${el.className} ${el.scrollTop}/${el.scrollHeight}/${el.clientHeight} ${getComputedStyle(el).overflowY}`);
      return out.join(' | '); }, chat);
    throw new Error(`the chat does not scroll with End / Page Down (${before} -> ${after}; ${why})`);
  }
}
async function chatView(page, dash) {
  await fakeTermStream(page);  // Terminal below shows the screen (ORCH-744)
  let answered = '';
  const sent = [];
  const tweak = st => {
    const t = (st.tickets || []).find(x => x.id === 't_bar238');
    if (!t) return;
    t.checklist = [
      { id: 'c1', text: 'Files can be dropped on a ticket', done: true, evidence: [
        { type: 'note', ref: 'node --test tests/attach.test.js', summary: 'Uploading works for pictures, pages and tables. Notes sit below the files.', by: 'agent:claude', at: '2026-11-19T14:21:00Z' },
        { type: 'pr', ref: 'https://github.com/severinlindenmann/orch/pull/1309', by: 'agent:claude', at: '2026-11-19T14:21:00Z' }] },
      { id: 'c2', text: 'Keep or change the file name', done: false, evidence: [] }];
    t.history = [{ at: '2026-11-19T14:02:00Z', by: 'agent:factory', via: 'cli', text: 'Claude started', chat_message: false }];
    t.questions = [
      { id: 'q1', text: 'Should notes sit above or below the files?', options: ['Below', 'Above'], answer: 'Below', answered_by: 'human:demo', asked_at: '2026-11-19T14:30:00Z', answered_at: '2026-11-19T14:33:00Z' },
      { id: 'q2', digest: 'd2', text: 'Keep the old file name when the same file is added twice?', options: ['Keep the old name', 'Use the new name'],
        answer: answered || null, answered_by: answered ? 'human:demo' : undefined, asked_at: '2026-11-19T14:52:00Z', answered_at: answered ? new Date().toISOString() : undefined }];
  };
  await liveBarState(page, tweak);
  await page.route('**/api/act', async route => {
    const body = route.request().postDataJSON();
    if (body.op === 'answer' && body.args.ticket === 't_bar238' && body.args.question === 'q2') answered = body.args.answer;
    else if (body.op === 'run.send' && body.args.ticket === 't_bar238') sent.push(body.args.text);
    else return route.fallback();
    const st = JSON.parse(JSON.stringify(barState));
    tweak(st);
    if (body.op === 'run.send') st.send_result = { id: 'p_17', delivered: 1, state: 'idle' };  // as the server answers
    route.fulfill({ json: st });
  });
  await page.goto(dash + '/#home');
  await mainHasText(page);
  await page.evaluate(() => { try { localStorage.removeItem('orch.live.view'); } catch {} });
  await page.waitForSelector('#live-bar :is([data-lbar-open="t_bar238"], [data-lbar-list="wait"])', { timeout: 10000 });
  if (!(await page.$('#live-bar [data-lbar-open="t_bar238"]'))) await page.click('#live-bar [data-lbar-list="wait"]');  // a phone: counts only
  await page.click('#live-bar [data-lbar-open="t_bar238"]');
  const pane = '#live-dock .live-pane[data-session="t_bar238"]', chat = `${pane} [data-live-chat]`;
  await page.waitForFunction(c => /Step 1 done/.test(document.querySelector(c)?.textContent || ''), chat, { timeout: 10000 });
  const rows = await page.$$eval(`${chat} > *`, els => els.map(el => (el.dataset.w || 'e') + ' ' + el.textContent.replace(/\s+/g, ' ').trim()));
  const want = [/^e ✓ The helper started/, /^e ✓ Step 1 done: Files can be dropped on a ticket/, /^h Helper · .*Uploading works/,
    /^h Helper · .*above or below the files\?$/, /^y Demo · .*Below$|^y You · .*Below$/];
  if (rows.length !== want.length || want.some((re, i) => !re.test(rows[i]))) throw new Error('the chat reads:\n' + rows.join('\n'));
  if (await page.isVisible(`${pane} [data-live-lines]`)) throw new Error('Chat also shows the last lines');
  // ORCH-697: the step's pull request is a result widget inside its message; a click opens it big
  const prw = `${chat} .live-chat-msg .result[data-type="pr"]`;
  await page.waitForSelector(prw, { timeout: 10000 });
  if (!/Pull request 1309/.test(await page.textContent(prw))) throw new Error('the pull request widget does not name pull request 1309');
  const ask = `${pane} [data-live-ask]`;
  if (!/Keep the old file name/.test(await page.textContent(ask))) throw new Error('the waiting question is not shown above the chat');
  if (rows.some(r => /Keep the old file name/.test(r))) throw new Error('the waiting question is also a chat message');
  const [edge, goal] = await page.evaluate(a => {
    const t = document.createElement('span'); t.style.color = 'var(--needs-you)'; document.body.append(t);
    const g = getComputedStyle(t).color; t.remove();
    return [getComputedStyle(document.querySelector(a)).borderTopColor, g];
  }, ask);
  if (edge !== goal) throw new Error(`the question card is not orange (${edge}, want ${goal})`);
  await noSideways(page);
  await chatScrollsByKeyboard(page, chat);
  await noTabUnderLayer(page);
  // answer inside the chat
  await page.click(`${ask} [data-key="live-ask-option-0"]`);
  // ORCH-1359: the toast offers Undo; the answer is sent when its Undo window (about 5 s) ends
  await page.waitForSelector('#ui-toasts .ui-toast button:text-is("Undo")', { timeout: 5000 }).catch(() => { throw new Error('the answer toast offers no Undo'); });
  await page.waitForFunction(([c, a]) => /Keep the old name/.test(document.querySelector(c)?.textContent || '') && document.querySelector(a)?.hidden, [chat, ask], { timeout: 15000 });
  if (answered !== 'Keep the old name') throw new Error('the answer sent was ' + JSON.stringify(answered));
  // a message from the box shows as yours at once
  await page.fill(`${pane} [data-live-msg-text]`, 'Please also try a PDF.');
  await page.click(`${pane} [data-key="live-msg-send"]`);
  await page.waitForFunction(c => /You · [^]*Please also try a PDF\./.test(document.querySelector(c)?.textContent || ''), chat, { timeout: 10000 });
  if (sent.join() !== 'Please also try a PDF.') throw new Error('the message sent was ' + JSON.stringify(sent));
  // Terminal: the helper's screen; the choice stays after a reload; back to Chat
  const pick = async v => {
    if (await page.isVisible(`${pane} [data-key="live-view-${v}"]`)) return page.click(`${pane} [data-key="live-view-${v}"]`);
    await page.click(`${pane} [data-key="live-pane-more"]`);  // a narrow pane: the choice is in More
    await page.click(`${pane} [data-key="live-more-view"]`);
  };
  await pick('term');
  await page.waitForFunction(p => document.querySelector(p + ' [data-live-body]')?.dataset.liveView === 'term', pane, { timeout: 5000 });
  await page.waitForSelector(`${pane} .term`, { timeout: 5000 });  // the real screen (ORCH-744) where the last lines were
  if (await page.isVisible(chat)) throw new Error('Terminal does not show the screen instead of the chat');
  await page.reload();
  await mainHasText(page);
  await page.waitForFunction(p => document.querySelector(p + ' [data-live-body]')?.dataset.liveView === 'term', pane, { timeout: 10000 });
  await pick('chat');
  await page.waitForFunction(c => { const el = document.querySelector(c); return el && !el.hidden && /Step 1 done/.test(el.textContent); }, chat, { timeout: 5000 });
  answered = '';  // the picture: the chat with the waiting question above it
  await page.evaluate(() => window.LiveSessions.refresh());
  await page.reload();
  await mainHasText(page);
  await page.waitForFunction(a => { const el = document.querySelector(a); return el && !el.hidden; }, ask, { timeout: 10000 });
  await newestWhole(page, 'with a waiting question');
  await layerTextScale(page, 'chat');
  await noSideways(page);
}

// Steps 20 and 21 (ORCH-697): the result widgets. The demo ticket (widgets_ticket.json) has one result of every kind:
// e2e/focus_insights/dashboard_server.py writes its files into the test workspace and the real server reads them; the
// ticket joins the page's state here and the list of its result files comes from a stand-in, as orch lists them.
const WIDGET_DEMO = require('./widgets_ticket.json');
const WIDGET_ID = WIDGET_DEMO.ticket.id;
const WIDGET_KINDS = ['md', 'text', 'code', 'data', 'table', 'page', 'pdf', 'picture', 'video', 'audio', 'chart', 'change', 'pr', 'archive', 'link', 'file'];
function widgetFiles() {
  const fs = require('node:fs'), path = require('node:path');
  const samples = path.join(__dirname, '..', '..', 'workspace', 'src', 'orch_ui', 'static', 'samples');
  // made in the order listed, the picture last: the tile shows it as the newest result
  return Object.entries(WIDGET_DEMO.files).map(([name, f], i) => ({ name, mtime: name === 'home-390.svg' ? '2026-11-19T14:40:00Z' : `2026-11-19T13:${String(30 + i).padStart(2, '0')}:00Z`,
    size: f.sample ? fs.statSync(path.join(samples, f.sample)).size : Buffer.byteLength(f.text) }));
}
// The overlay: open from a widget, step through with the arrow keys, Esc closes and the keyboard is back on the opener.
async function overlayRound(page, opener, want, keys = false) {
  await page.locator(opener).first().scrollIntoViewIfNeeded();
  // keys: open it from the keyboard (a phone sheet with the Results strip leaves the chat a few lines; the message box
  // stays over the lower part of a widget there, so a click in its middle would land on the box)
  if (keys) { await page.locator(opener).first().focus(); await page.keyboard.press('Enter'); } else await page.locator(opener).first().click();
  const dlg = 'dialog.result-overlay[open]';
  await page.waitForSelector(dlg, { timeout: 5000 });
  const titles = [await page.textContent(`${dlg} .result-ov-title`)];
  const pos = await page.textContent(`${dlg} .result-ov-pos`);
  const total = Number((/of (\d+)/.exec(pos) || [])[1] || 1);
  if (want && total < want) throw new Error(`the overlay steps through ${total} results, want ${want}`);
  for (let i = 1; i < total; i++) {
    await page.keyboard.press('ArrowRight');
    titles.push(await page.textContent(`${dlg} .result-ov-title`));
  }
  if (new Set(titles).size !== total) throw new Error('the arrows do not reach every result: ' + titles.join(', '));
  await page.keyboard.press('Escape');
  await page.waitForFunction(d => !document.querySelector(d), dlg, { timeout: 5000 });
  const back = await page.evaluate(o => { const el = document.querySelector(o); return !!el && document.activeElement === el; }, opener);
  if (!back) throw new Error('after Esc the keyboard is not back on the widget that opened the overlay');
  return titles;
}
// Step 20: the 16 widgets in the style guide, small, each opens big, the arrows go through, Esc closes; the states.
async function widgetsGuide(page, dash) {
  await page.goto(dash + '/styleguide/#result-widgets');
  await page.waitForSelector('#rw-grid [data-type]', { timeout: 15000 });
  const kinds = await page.$$eval('#rw-grid [data-type]', els => els.map(el => el.dataset.type));
  const miss = WIDGET_KINDS.filter(k => !kinds.includes(k));
  if (kinds.length !== 16 || miss.length) throw new Error(`the style guide shows ${kinds.length} widgets; missing: ${miss.join(', ')}`);
  await overlayRound(page, '#rw-grid .result[data-type="md"] .result-open', 15);
  for (const st of ['empty', 'loading', 'error', 'large']) if (!(await page.$(`#rw-states .result[data-state="${st}"]`))) throw new Error(`no ${st} state in the style guide`);
  await page.locator('#rw-grid').scrollIntoViewIfNeeded();
  await noSideways(page);
}
// Step 21: the demo ticket's results on its wall tile (the newest, small, "+N more"), inside its session's chat (each
// step's results in that step's message) and on its ticket page (all 16 kinds); a click opens the same overlay.
// Extra pictures of a step's middle states for the Look stop, only when FD_EXTRA names a folder (not part of the run).
// ORCH-1356: the Results shelf of a ticket's pane, placed as draft D does: a column beside the chat in the bottom layer
// (from 900 px) and in full screen, a one-row strip above the chat on the right and on a phone; an empty line without results.
async function shelfView(page, dash, width) {
  await liveBarState(page, st => {
    const none = (st.tickets || []).find(x => x.id === 't_bar201');
    if (none) Object.assign(none, { checklist: [], refs: [], evidence: [] });
    const t = (st.tickets || []).find(x => x.id === 't_bar238');
    if (t) t.checklist = [{ id: 'c1', text: 'Files can be dropped on a ticket', done: true, evidence: [
      { type: 'pr', ref: 'https://github.com/severinlindenmann/orch/pull/1309', by: 'agent:claude', at: '2026-11-19T14:21:00Z' }] }];
  });
  await page.addInitScript(() => { try { Object.keys(localStorage).filter(k => k.indexOf('orch.live.layer') === 0).forEach(k => localStorage.removeItem(k)); } catch (e) { /* none */ } });
  await page.goto(dash + '/#home');
  await mainHasText(page);
  const open = async id => {
    await page.waitForSelector(`#live-bar :is([data-lbar-open="${id}"], [data-lbar-list])`, { timeout: 10000 });
    if (!(await page.isVisible(`#live-bar [data-lbar-open="${id}"]`))) await page.click('#live-bar [data-lbar-list="wait"]');  // a phone: counts only
    await page.click(`#live-bar [data-lbar-open="${id}"]`);
  };
  // a ticket with no results: the shelf says so in one line
  await open('t_bar201');
  const empty = '#live-dock .live-pane[data-session="t_bar201"] .live-shelf';
  await page.waitForFunction(sel => /Nothing yet\. Pictures, pages and tables show up here\./.test(document.querySelector(sel)?.textContent || ''), empty, { timeout: 10000 });
  await page.click('#live-dock .live-pane[data-session="t_bar201"] [data-key="live-close"]');
  await page.waitForSelector('#live-dock .live-pane[data-session="t_bar201"]', { state: 'detached', timeout: 5000 });
  // a ticket with a result: the widget sits on the shelf, outside the chat
  await open('t_bar238');
  const inPane = '.live-pane[data-session="t_bar238"]', pane = `#live-dock ${inPane}`, shelf = `${pane} .live-shelf`;
  await page.waitForSelector(`${shelf} .result[data-type="pr"]`, { timeout: 10000 });
  if ((await page.getAttribute(shelf, 'aria-label')) !== 'Results') throw new Error('the shelf is not called Results');
  if (!/Pull request 1309/.test(await page.textContent(`${shelf} .result[data-type="pr"]`))) throw new Error('the shelf does not show pull request 1309');
  const where = () => page.evaluate(p => {
    const sh = document.querySelector(p + ' .live-shelf').getBoundingClientRect(), pb = document.querySelector(p + ' .live-pbw > .live-pb').getBoundingClientRect();
    return sh.left >= pb.right - 1 ? 'beside' : sh.bottom <= pb.top + 1 ? 'above' : 'overlap';
  }, pane);
  const mode = async m => {
    await page.click('[data-key="live-place"]');
    await page.click(`[data-key="live-place-menu"] [data-mode="${m}"]`);
    await page.waitForSelector(`#live-dock[data-mode="${m}"] ${inPane} .live-shelf .result`, { timeout: 5000 });
  };
  if (width < 900) {  // a phone, and the bottom layer under 900 px: a strip above the chat
    if (await where() !== 'above') throw new Error('on a phone the shelf is not a strip above the chat');
    const h = await page.$eval(shelf, el => el.getBoundingClientRect().height);
    if (h > 160) throw new Error(`on a phone the strip takes ${Math.round(h)} px; it should be one row`);
    return;
  }
  if (!(await page.$('#live-dock[data-mode="bottom"]'))) await mode('bottom');
  if (await where() !== 'beside') throw new Error('in the bottom layer the shelf is not a column beside the chat');
  const w = await page.$eval(shelf, el => Math.round(el.getBoundingClientRect().width));
  if (Math.abs(w - 360) > 2) throw new Error(`the shelf in the bottom layer is ${w} px wide, draft D has 360`);
  await mode('right');
  if (await where() !== 'above') throw new Error('on the right the shelf is not a strip above the chat');
  await extraShot(page, 'fd-34-shelf-right', width);
  await page.click(`${pane} :is([data-key="live-full"], [data-key="live-pane-more"])`);
  if (await page.$('[data-key="live-more-full"]')) await page.click('[data-key="live-more-full"]');
  await page.waitForSelector(`#live-dock[data-mode="full"] ${inPane} .live-shelf .result`, { timeout: 5000 });
  if (await where() !== 'beside') throw new Error('in full screen the shelf is not a column beside the chat');
  const wf = await page.$eval(shelf, el => Math.round(el.getBoundingClientRect().width));
  if (Math.abs(wf - 320) > 2) throw new Error(`the shelf in full screen is ${wf} px wide, draft D has 320`);
  await extraShot(page, 'fd-34-shelf-full', width);
  await page.keyboard.press('Escape');
  await page.waitForSelector('#live-dock:not([data-mode="full"])', { timeout: 5000 });
  if (!(await page.$('#live-dock[data-mode="bottom"]'))) await mode('bottom');
  await page.waitForSelector(`${shelf} .result`, { timeout: 5000 });
}
async function extraShot(page, name, width) {
  const dir = process.env.FD_EXTRA;
  if (!dir || !width) return;
  await page.waitForTimeout(300);
  await page.screenshot({ path: require('node:path').join(dir, `${name}-${width}.png`) });
}
async function widgetsTicket(page, dash, width) {
  await liveBarState(page, st => {
    st.tickets = [...(st.tickets || []).filter(t => t.id !== WIDGET_ID), JSON.parse(JSON.stringify(WIDGET_DEMO.ticket))];
    st.runs = { ...(st.runs || {}), [WIDGET_ID]: { running: true, helper: { state: 'working' }, claim: { agent: 'agent:claude' } } };
  });
  const files = widgetFiles();
  await page.route(`**/api/artifacts/${WIDGET_ID}`, route => route.fulfill({ json: { available: true, files } }));
  const demo = { id: WIDGET_ID, key: WIDGET_DEMO.ticket.key, title: WIDGET_DEMO.ticket.title, status: 'working', word: 'Working',
    detail: 'Checking the previews', waiting_on: [], question: null, lines: ['⏺ Bash(node --test tests/attach.test.js)', '  ⎿ ✔ a table shows its rows (7 ms)'],
    tool: 'Claude Code', model: 'Opus', mode: 'live', opened_at: null, open_seconds: 34 * 60, idle_seconds: null, closes_in_seconds: 3600,
    last_at: null, kind: '', pinned: true, name: null };
  await page.route(/\/api\/sessions(\?.*)?$/, route => route.fulfill({ json: { sessions: [demo, ...barSessions()], lines: 8, age_ms: 0 } }));
  await page.addInitScript(() => { try { localStorage.removeItem('orch.live.wall'); localStorage.removeItem('orch.live.view'); Object.keys(localStorage).filter(k => k.indexOf('orch.live.layer') === 0).forEach(k => localStorage.removeItem(k)); } catch (e) { /* none */ } });
  // 1. the wall tile: the newest result, small, and "+N more"
  await page.goto(dash + '/#addon/focus');
  const tile = tileOf(WIDGET_ID);
  await page.waitForSelector(`${tile} .wall-results .result`, { timeout: 15000 });
  const onTile = await page.$$eval(`${tile} .wall-results .result`, els => els.map(el => el.dataset.type));
  if (onTile.join() !== 'picture') throw new Error(`the tile shows ${onTile.join(', ') || 'nothing'}, want the newest result, the picture`);
  const more = (await page.textContent(`${tile} .result-more`)).trim();
  if (!/^\+\d+ more$/.test(more)) throw new Error('the tile does not say how many more results: ' + more);
  await overlayRound(page, `${tile} .wall-results .result-open`, 15);
  await page.locator(tile).scrollIntoViewIfNeeded();
  await extraShot(page, 'fd-21a-tile', width);
  // 2. the session's chat: each step's results inside its message
  await page.click(`${tile} [data-wall-open]`);
  const chat = `#live-dock .live-pane[data-session="${WIDGET_ID}"] [data-live-chat]`;
  await page.waitForFunction(c => document.querySelectorAll(c + ' .live-chat-msg .results-host [data-type]').length >= 7, chat, { timeout: 15000 });
  const inChat = await page.$$eval(`${chat} .live-chat-msg`, els => els.map(m => [...m.querySelectorAll('.results-host [data-type]')].map(r => r.dataset.type).sort().join(',')).filter(Boolean));
  if (inChat.join(' | ') !== 'md,pr,text | link,page,picture,video') throw new Error('the chat messages carry: ' + inChat.join(' | '));
  await overlayRound(page, `${chat} .live-chat-msg .result[data-type="picture"] .result-open`, 15, width <= 720);
  await extraShot(page, 'fd-21b-chat', width);
  // the layer goes to the bar, so the ticket page is seen whole (the session stays open in the bar)
  await page.click(`#live-dock .live-pane[data-session="${WIDGET_ID}"] [data-key="live-min"]`).catch(() => page.keyboard.press('Escape'));
  // 3. the ticket page: every kind, the same overlay
  await page.evaluate(id => { location.hash = '#ticket/' + id; }, WIDGET_ID);
  const host = `[data-key="ticket-results-${WIDGET_ID}"]`;
  await page.waitForFunction(h => { const el = document.querySelector(h); return el && el.querySelectorAll('[data-type]').length >= 16 && !el.querySelector('[data-state="loading"]'); }, host, { timeout: 15000 });
  const onPage = await page.$$eval(`${host} [data-type]`, els => [...new Set(els.map(el => el.dataset.type))]);
  const miss = WIDGET_KINDS.filter(k => !onPage.includes(k));
  if (miss.length) throw new Error('the ticket page misses the widgets: ' + miss.join(', '));
  const broken = await page.$$eval(`${host} .result[data-state="error"]`, els => els.map(el => el.querySelector('.result-name')?.textContent));
  if (broken.length) throw new Error('these results could not be read: ' + broken.join(', '));
  if ((await page.textContent(`[data-key="results-widgets"] h2`)).trim() !== 'Results') throw new Error('the card is not called Results');
  await overlayRound(page, `${host} .result[data-type="chart"] .result-open`, 15);
  await page.locator(host).scrollIntoViewIfNeeded();
  await noSideways(page);
}

// Step 19 (ORCH-696): voice into the message box. The relay is on in the page's state (the relay add-on on and
// connected, as Settings reads it); the sound goes to POST /api/voice/words, answered here as the dashboard does with
// the local relay stand-in (workspace/tests/fakes.py: "Please keep the old file name."). The fake microphone of the
// browser speaks. The real server with the stand-in itself: workspace-addons/dashboard/tests/test_voice.py.
async function voiceBox(page, dash) {
  let relayOn = true;
  const heard = [], sent = [];
  await liveBarState(page, st => {
    const relay = { name: 'relay', label: 'Relay', active: relayOn, detail: relayOn ? { connected: true, address: 'https://relay.example', workspaces: [] } : null };
    st.settings = { ...(st.settings || {}), addons: [...((st.settings || {}).addons || []).filter(a => a.name !== 'relay'), relay] };
  });
  await page.route('**/api/voice/words', async route => {
    const r = route.request(), kind = (r.headers()['content-type'] || '').split(';')[0];
    heard.push({ kind, size: (r.postDataBuffer() || Buffer.alloc(0)).length });
    if (!/^audio\/(webm|mp4|m4a|wav)$/.test(kind) || !heard[heard.length - 1].size) return route.fulfill({ status: 415, contentType: 'text/plain', body: 'no' });
    route.fulfill({ json: { text: 'Please keep the old file name.' } });
  });
  await page.route('**/api/act', async route => {
    const body = route.request().postDataJSON();
    if (body.op === 'run.send') { sent.push(body.args.text); return route.fulfill({ json: barState }); }
    return route.fallback();
  });
  const pane = '#live-dock .live-pane[data-session="t_bar238"]', mic = `${pane} [data-key="live-voice"]`;
  const strip = `${pane} [data-key="live-voice-strip"]`, box = `${pane} [data-live-msg-text]`;
  const openPane = async () => {
    await page.goto('about:blank');  // the same #home address would not load the page again
    await page.goto(dash + '/#home');
    await mainHasText(page);
    await page.waitForSelector('#live-bar :is([data-lbar-open="t_bar238"], [data-lbar-list="wait"])', { timeout: 10000 });
    if (!(await page.$(pane))) {
      if (!(await page.$('#live-bar [data-lbar-open="t_bar238"]'))) await page.click('#live-bar [data-lbar-list="wait"]');  // a phone: counts only
      await page.click('#live-bar [data-lbar-open="t_bar238"]');
    }
    await page.waitForSelector(box, { timeout: 10000 });
  };
  const speak = async () => {
    await page.click(mic);
    await page.waitForFunction(s => /Listening \d:\d\d/.test(document.querySelector(s)?.textContent || ''), strip, { timeout: 10000 });
    if (await page.isVisible(mic)) throw new Error('the microphone still shows while listening');
    await page.waitForTimeout(1300);
    await page.click(`${pane} [data-key="live-voice-stop"]`);
    await page.waitForFunction(b => /Please keep the old file name\./.test(document.querySelector(b)?.value || ''), box, { timeout: 10000 });
  };
  await page.goto(dash + '/#home');
  await mainHasText(page);
  await page.evaluate(() => { try { localStorage.removeItem('orch.live.view'); } catch {} });
  await openPane();
  await page.waitForSelector(mic, { timeout: 10000 });
  // a blocked microphone: one plain sentence, nothing recorded
  await page.evaluate(() => {
    window.__gum = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
    navigator.mediaDevices.getUserMedia = () => Promise.reject(new DOMException('blocked', 'NotAllowedError'));
  });
  await page.click(mic);
  await page.waitForFunction(p => /^The microphone is blocked for this page; allow it in the browser, then try again\.$/.test(document.querySelector(p + ' [data-key="live-voice-error"]')?.textContent || ''), pane, { timeout: 10000 });
  await page.evaluate(() => { navigator.mediaDevices.getUserMedia = window.__gum; });
  // listening says so; Esc cancels only the voice (the panel stays open), nothing is turned into words
  await page.click(mic);
  await page.waitForFunction(s => /Listening \d:\d\d/.test(document.querySelector(s)?.textContent || ''), strip, { timeout: 10000 });
  await noSideways(page);
  if (process.env.FD_SHOTS) {  // a folder: a picture of the listening strip too, for the look review
    await page.$eval(`${pane} [data-key="live-msg"]`, f => f.scrollIntoView({ block: 'end' }));
    await page.waitForTimeout(1200);
    await page.screenshot({ path: `${process.env.FD_SHOTS}/fd-19-voice-listening-${page.viewportSize().width}.png` });
  }
  await page.keyboard.press('Escape');
  await page.waitForFunction(([s, m]) => !document.querySelector(s) && document.querySelector(m), [strip, mic], { timeout: 10000 });
  if (heard.length) throw new Error('a cancelled recording was turned into words');
  if (await page.$(`${pane} [data-key="live-voice-error"]`)) throw new Error('the old refusal is still shown after a new try');
  // closing the pane while listening stops the microphone; nothing is turned into words
  await page.evaluate(() => {
    const ask = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
    window.__streams = [];
    navigator.mediaDevices.getUserMedia = async c => { const st = await ask(c); window.__streams.push(st); return st; };
  });
  await page.click(mic);
  await page.waitForFunction(s => /Listening \d:\d\d/.test(document.querySelector(s)?.textContent || ''), strip, { timeout: 10000 });
  await page.click(`${pane} [data-key="live-close"]`);
  await page.waitForFunction(() => window.__streams.length && window.__streams.every(st => st.getTracks().every(t => t.readyState === 'ended')), null, { timeout: 5000 })
    .catch(() => { throw new Error('the microphone keeps listening after its pane closed'); });
  if (heard.length) throw new Error('a recording of a closed pane was turned into words');
  await openPane();
  await page.waitForSelector(mic, { timeout: 10000 });
  // speak, stop: the words land in the box with the line under it, and nothing is sent
  await page.fill(box, 'Thanks.');
  await page.dispatchEvent(box, 'input');
  await speak();
  if (heard.length !== 1 || !/^audio\//.test(heard[0].kind) || !heard[0].size) throw new Error('the recording sent: ' + JSON.stringify(heard));
  if ((await page.inputValue(box)) !== 'Thanks. Please keep the old file name.') throw new Error('the box reads ' + JSON.stringify(await page.inputValue(box)));
  if (!/^From your voice\. Check the words, change what is wrong, then send\.$/.test(await page.textContent(`${pane} [data-key="live-voice-done"]`))) throw new Error('the line under the words is missing');
  await page.waitForTimeout(1500);
  if (sent.length) throw new Error('the words were sent by themselves: ' + JSON.stringify(sent));
  // change them: the line goes on the first key, the words stay
  await page.focus(box);
  await page.keyboard.press('End');
  await page.keyboard.type(' And add a note.');
  if (await page.$(`${pane} [data-key="live-voice-done"]`)) throw new Error('the line stays while changing the words');
  if (!/file name\. And add a note\.$/.test(await page.inputValue(box))) throw new Error('the change did not land: ' + await page.inputValue(box));
  if (sent.length) throw new Error('changing the words sent them');
  // the relay off: no microphone, no hint to turn it on
  relayOn = false;
  await openPane();
  await page.waitForTimeout(500);
  if (await page.$(mic)) throw new Error('the microphone shows with the relay off');
  if (/relay|microphone|speak/i.test(await page.textContent(`${pane} [data-key="live-msg"]`))) throw new Error('the box hints at the relay while it is off');
  // on again, for the picture: the words in the box, ready to check
  relayOn = true;
  await page.fill(box, '');
  await page.dispatchEvent(box, 'input');
  await openPane();
  await page.waitForSelector(mic, { timeout: 10000 });
  await speak();
  if (await page.$eval(box, b => b.scrollHeight > b.clientHeight + 1)) throw new Error('the words do not fit in the box to check them');
  await noSideways(page);
  await page.$eval(`${pane} [data-key="live-msg"]`, f => f.scrollIntoView({ block: 'end' }));  // the picture: the box with the words, ready to check
}
// Step 18 (ORCH-695): the message box of a ticket's pane takes files by the clip, a pasted screenshot and a file dropped
// on the pane; each shows as a preview (a picture's thumbnail or a file chip) that can be taken out before Send. Send
// puts the files on the ticket (ticket.attach) and then tells the helper (run.send), the ticket page's one way. The sent
// message carries the files as small previews and stays after a reload (orch lists it in run status sent_input).
const PNG = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==';
async function messageBox(page, dash) {
  const attached = [], sent = [];
  const tweak = st => {
    const t = (st.tickets || []).find(x => x.id === 't_bar238');
    if (!t) return;
    t.questions = [];
    t.checklist = [{ id: 'c1', text: 'Files can be dropped on a ticket', done: false, evidence: [] }];
    t.history = [{ at: new Date(Date.now() - 30 * 60e3).toISOString(), by: 'agent:factory', via: 'cli', text: 'Claude started', chat_message: false }];
    // relay voice on, as in draft D: the microphone shows beside Send (ORCH-1568; without relay it is hidden, R1.1)
    const relay = { name: 'relay', label: 'Relay', active: true, detail: { connected: true, address: 'https://relay.example', workspaces: [] } };
    st.settings = { ...(st.settings || {}), addons: [...((st.settings || {}).addons || []).filter(a => a.name !== 'relay'), relay] };
    const run = st.runs?.t_bar238;
    if (run) run.sent_input = sent.map((text, i) => ({ id: 'p_18' + i, text, at: new Date(Date.now() - 60e3).toISOString(), by: st.me || 'human:demo', read: true }));
  };
  await liveBarState(page, tweak);
  await page.route('**/api/act', async route => {
    const body = route.request().postDataJSON();
    if (body.args?.ticket !== 't_bar238' || !['ticket.attach', 'run.send'].includes(body.op)) return route.fallback();
    const st = JSON.parse(JSON.stringify(barState));
    if (body.op === 'ticket.attach') { attached.push(...body.args.files.map(f => f.name)); st.attached = { saved: body.args.files.map(f => f.name), failed: [] }; }
    else { sent.push(body.args.text); st.send_result = { id: 'p_18', delivered: 1, state: 'idle' }; }
    tweak(st);
    route.fulfill({ json: st });
  });
  await page.route(/\/api\/file\?/, route => route.fulfill({ contentType: 'image/png', body: Buffer.from(PNG, 'base64') }));
  await page.goto(dash + '/#home');
  await mainHasText(page);
  await page.waitForSelector('#live-bar :is([data-lbar-open="t_bar238"], [data-lbar-list="wait"])', { timeout: 10000 });
  if (!(await page.$('#live-bar [data-lbar-open="t_bar238"]'))) await page.click('#live-bar [data-lbar-list="wait"]');  // a phone: counts only
  await page.click('#live-bar [data-lbar-open="t_bar238"]');
  const pane = '#live-dock .live-pane[data-session="t_bar238"]', box = `${pane} [data-key="live-msg-box"]`, tiles = `${box} .attachment-tile`;
  const chat = `${pane} [data-live-chat]`;
  await page.waitForSelector(`${box} [data-live-msg-text]`, { timeout: 10000 });
  const hint = await page.textContent(box);
  if (!/up to 10 files, 25 MB each/.test(hint)) throw new Error('the box does not say its limits in plain words: ' + hint);
  // the clip opens the file choice
  const [chooser] = await Promise.all([page.waitForEvent('filechooser'), page.click(`${box} [data-attach]`)]);
  await chooser.setFiles({ name: 'notes.md', mimeType: 'text/markdown', buffer: Buffer.from('# Notes\nKeep the old name.\n') });
  // a screenshot pasted into the box, a file dropped on the pane (on the chat, not on the box)
  await page.evaluate(([b, png]) => {
    const dt = new DataTransfer();
    dt.items.add(new File([Uint8Array.from(atob(png), c => c.charCodeAt(0))], 'image.png', { type: 'image/png' }));
    document.querySelector(b + ' [data-live-msg-text]').dispatchEvent(new ClipboardEvent('paste', { clipboardData: dt, bubbles: true, cancelable: true }));
  }, [box, PNG]);
  await page.evaluate(c => {
    const dt = new DataTransfer();
    dt.items.add(new File(['second file\n'], 'second.txt', { type: 'text/plain' }));
    const at = document.querySelector(c);
    for (const type of ['dragenter', 'dragover', 'drop']) at.dispatchEvent(new DragEvent(type, { dataTransfer: dt, bubbles: true, cancelable: true }));
  }, chat);
  await page.waitForFunction(t => document.querySelectorAll(t).length === 3 && !document.querySelector(t + ' progress:not([value="100"])'), tiles, { timeout: 5000 });
  const names = await page.$$eval(`${tiles} .attachment-name`, els => els.map(el => el.textContent));
  if (names[0] !== 'notes.md' || !/^Screenshot \d\d-\d\d\.png$/.test(names[1]) || names[2] !== 'second.txt') throw new Error('the previews read: ' + names.join(', '));
  if (!(await page.$(`${tiles}:nth-child(2) img`)) || !(await page.$(`${tiles}:nth-child(1) .attachment-kind`))) throw new Error('a picture shows no thumbnail, or a file no chip');
  // a file over the limit is refused in plain words and not added
  await page.evaluate(b => {
    const dt = new DataTransfer();
    dt.items.add(new File([new Uint8Array(26 * 1024 * 1024)], 'huge.png', { type: 'image/png' }));
    document.querySelector(b + ' [data-live-msg-text]').dispatchEvent(new ClipboardEvent('paste', { clipboardData: dt, bubbles: true, cancelable: true }));
  }, box);
  const err = await page.textContent(`${box} .attachment-error`);
  if (!/larger than 25 MB/.test(err) || (await page.$$(tiles)).length !== 3) throw new Error('a file over 25 MB was not refused plainly: ' + err);
  if (attached.length || sent.length) throw new Error('something was sent before Send');
  await noSideways(page);
  // take one out, then send
  await page.click(`${tiles}:nth-child(1) .attachment-remove`);
  await page.waitForFunction(t => document.querySelectorAll(t).length === 2, tiles, { timeout: 3000 });
  await page.fill(`${box} [data-live-msg-text]`, 'Here is what I see.');
  await page.click(`${box} [data-key="live-msg-send"]`);
  await page.waitForFunction(t => document.querySelectorAll(t).length === 0, tiles, { timeout: 8000 });
  if (attached.length !== 2 || attached[0] !== names[1] || attached[1] !== 'second.txt') throw new Error('the files put on the ticket: ' + attached.join(', '));
  if (sent.length !== 1 || !sent[0].startsWith('Here is what I see.\n\nI added 2 files to this ticket: ' + names[1] + ', second.txt.')) throw new Error('the message sent: ' + JSON.stringify(sent));
  const mine = `${chat} .live-chat-msg[data-w="y"]`;
  const shows = async where => {
    await page.waitForFunction(m => { const el = document.querySelectorAll(m); const last = el[el.length - 1];
      return last && /Here is what I see\./.test(last.textContent) && last.querySelectorAll('.live-chat-file').length === 2; }, mine, { timeout: 10000 })
      .catch(async () => { throw new Error(where + ': the chat reads ' + (await page.textContent(chat))); });
    if (/I added 2 files/.test(await page.textContent(chat))) throw new Error(where + ': the file line shows as words');
    if (!(await page.$(`${mine} .live-chat-file img`))) throw new Error(where + ': the sent picture has no thumbnail');
  };
  await shows('after Send');
  // the sent message stays after a reload
  await page.reload();
  await mainHasText(page);
  await page.waitForSelector(chat, { timeout: 10000 });
  await shows('after a reload');
  // the picture: two previews waiting in the box under the sent message
  const [again] = await Promise.all([page.waitForEvent('filechooser'), page.click(`${box} [data-attach]`)]);
  await again.setFiles([{ name: 'home-390.png', mimeType: 'image/png', buffer: Buffer.from(PNG, 'base64') },
    { name: 'test-run.log', mimeType: 'text/plain', buffer: Buffer.from('ok 1 adds a picture\n') }]);
  await page.waitForFunction(t => document.querySelectorAll(t).length === 2 && !document.querySelector(t + ' progress:not([value="100"])'), tiles, { timeout: 5000 });
  await newestWhole(page, 'with two files waiting');
  await layerTextScale(page, 'message box');
  await noSideways(page);  // ORCH-1362: an error toast with Try again keeps clear of the message box and its Send button (the check runs after)
  await page.evaluate(() => window.liveFail('Could not end the session: the helper did not answer.', 'x', () => {}));
  await page.waitForSelector('#ui-toasts .ui-toast button:text-is("Try again")', { timeout: 3000 });
}

// Step 13 until the layer exists (crew task layer replaces the stand-in with the real layer): a small open dialog with
// a typed, unsent message in the keep place. Page changes by real links, Back, Forward, a deep link and a reload.
async function staysOpen(page, dash, width) {
  // ORCH-1568: the real layer, two panes side by side (one on a phone) and words typed in a pane's message box stay
  // while the page changes; the step ends on Review with the panes in sight (the old stand-in box is gone)
  const phone = width <= 720;
  const nav = hash => phone ? `.tabbar a[href="${hash}"]` : `.sidebar a[href="${hash}"]`;
  const go = async hash => {
    await page.locator(`${nav(hash)}:visible, a[href="${hash}"]:visible`).first().click();
    await page.waitForFunction(h => location.hash === h, hash, { timeout: 10000 });
    await mainHasText(page);
  };
  let want = 0;
  const kept = async where => {
    const st = await page.evaluate(() => ({ mark: window.softMark, hash: location.hash,
      kept: !!document.querySelector('#live-dock [data-key="live-panel"][data-kept="1"]'),
      panes: document.querySelectorAll('#live-dock .live-pane').length,
      typed: document.querySelector('#live-dock .live-pane .live-msg textarea')?.value,
      stray: [...document.querySelectorAll('body > dialog, #keep > dialog')].filter(d => d.open).length }));
    if (st.mark !== 'same page') throw new Error(`${where}: the page loaded again`);
    if (!st.kept) throw new Error(`${where}: the layer closed or was painted again`);
    if (st.panes !== want) throw new Error(`${where}: the layer shows ${st.panes} panes, not ${want}`);
    if (st.typed !== 'Not sent yet') throw new Error(`${where}: the typed text is gone`);
    if (st.stray) throw new Error(`${where}: a stray box floats over the page`);
    return st.hash;
  };
  await liveBarState(page);
  barAsk = true;  // the waiting tickets carry their open question, as in step 12: the card shows its answer buttons
  await page.goto(dash + '/#tickets');  // a deep link
  await mainHasText(page);
  // the steps share one browser: start with the layer at the bar, not where an earlier step left it (it is kept per browser)
  await page.evaluate(() => { try { Object.keys(localStorage).filter(k => k.indexOf('orch.live.layer') === 0).forEach(k => localStorage.removeItem(k)); } catch (e) { /* none */ } });
  await page.reload();  // reload keeps the page
  await mainHasText(page);
  if (await page.evaluate(() => location.hash) !== '#tickets') throw new Error('reload left the page');
  await page.waitForSelector('#live-dock[data-mode="bar"] #live-bar [data-key="live-open"]', { timeout: 10000 });
  await page.click('[data-key="live-open"]');
  await page.waitForFunction(() => document.querySelectorAll('#live-dock .live-pane').length === 1, null, { timeout: 5000 });
  want = 1;
  if (!phone) {
    await page.click('#live-dock [data-key="live-beside"]');
    await page.waitForSelector('[data-key="live-beside-menu"] [data-key="live-beside-pick"]', { timeout: 5000 });
    await page.click('[data-key="live-beside-menu"] [data-key="live-beside-pick"]');
    await page.waitForFunction(() => document.querySelectorAll('#live-dock .live-pane').length === 2, null, { timeout: 5000 });
    want = 2;
  }
  await motionQuiet(page);
  await page.fill('#live-dock .live-pane .live-msg textarea', 'Not sent yet');
  await page.evaluate(() => { window.softMark = 'same page'; document.querySelector('#live-dock [data-key="live-panel"]').dataset.kept = '1'; });
  // a phone's sheet covers the page: its tab bar stays reachable under it
  await go('#home');
  await kept('Home');
  await go('#review');
  await kept('Review');
  // a full link ("/#tickets") is changed softly too, else it would load the page again: a link for the test only,
  // removed right after the click so no box stays over the page
  await page.evaluate(() => {
    const a = document.createElement('a');
    a.href = '/#tickets'; a.id = 'soft-full-link'; a.textContent = 'Tickets';
    document.querySelector('main').prepend(a);
  });
  await page.$eval('#soft-full-link', a => a.click());  // a phone's sheet covers the top of the page
  await page.waitForFunction(() => location.hash === '#tickets', null, { timeout: 10000 });
  await page.evaluate(() => document.getElementById('soft-full-link')?.remove());
  await mainHasText(page);
  await kept('Tickets');
  await page.goBack();
  if (await kept('Back') !== '#review') throw new Error('Back did not go to Review');
  await page.goBack();
  if (await kept('Back twice') !== '#home') throw new Error('Back twice did not go to Home');
  await page.goForward();
  if (await kept('Forward') !== '#review') throw new Error('Forward did not go to Review');
  await mainHasText(page);
  await motionQuiet(page);
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

// The terminal bridge's stream (GET /api/term/stream) needs the sign-in, which the click-through does not have: a
// pane that shows Terminal gets a stand-in stream with a fake screen, so no step reads a refusal (ORCH-880).
async function fakeTermStream(page, allowed = true) {
  const screen = { cols: 80, rows: 24, data: Buffer.from(TERM_SCREEN, 'utf8').toString('base64'), allowed };
  // the stream stays open like the bridge's (a routed answer would end and make the page reconnect): a stand-in
  // EventSource for this one address sends hello and the screen once
  await page.addInitScript(sc => {
    const Real = window.EventSource;
    window.EventSource = function (url) {
      if (!/\/api\/term\/stream\?/.test(String(url))) return new Real(url);
      const on = {}, es = { readyState: 1, url: String(url), addEventListener: (t, f) => { on[t] = f; }, close() { es.readyState = 2; } };
      window.termStreams = (window.termStreams || []).concat(es.url);
      setTimeout(() => { on.hello?.({ data: JSON.stringify({ typing_allowed: sc.allowed !== false, page: 'pg-ct' }) }); on.screen?.({ data: JSON.stringify(sc) }); }, 50);
      return es;
    };
  }, screen);
  // one page types at a time (ORCH-883): Let me type claims it; the stand-in always says yes
  await page.route('**/api/term/typing', route => route.fulfill({ json: {} }));
}

// Focus, for the steps after step 3: the same dressing of the page's state as focusIsNew
// (the live-session add-on), plus the one ticket of the test workspace marked as having a working helper.
async function liveFocus(page) {
  let one = null;
  await fakeTermStream(page);
  const live = { name: 'focus', label: 'Focus', icon: 'target', active: true, removable: true, shipped: false,
    description: 'A live page for one ticket.', page: { path: '/', label: 'Open Focus', live_session: true },
    dashboard: { label: 'Focus', icon: 'target', order: 20 } };
  await page.route(/\/api\/state(\?.*)?$/, async route => {
    const res = await route.fetch();
    if (res.status() !== 200) return route.fulfill({ response: res });
    const st = await res.json();
    st.addons = [...(st.addons || []).filter(a => a.name !== live.name), live];
    const first = (st.tickets || [])[0];
    if (first) st.runs = { ...(st.runs || {}), [first.id]: { running: true, state: 'alive' } };
    if (first && !first.key) first.key = 'ORCH-238';  // the test ticket has no key; the pane shows the key, never the raw id
    if (first) one = { id: first.id, key: first.key, title: first.title };
    route.fulfill({ response: res, json: st });
  });
  // the live sessions API (ORCH-359) says the same: the first ticket has a working session
  await page.route(/\/api\/sessions(\?.*)?$/, route => route.fulfill({ json: { lines: 8, age_ms: 0, sessions: one ? [{ ...one,
    status: 'working', word: 'Working', detail: 'Running the tests', waiting_on: [], question: null, lines: ['⏺ Running the tests'],
    tool: 'Claude Code', model: 'Opus', mode: 'live', opened_at: null, open_seconds: 1500, idle_seconds: null, closes_in_seconds: 3600,
    last_at: null }] : [] } }));
  await page.route('**/addon/focus/**', route => route.fulfill({ contentType: 'text/html',
    body: '<!doctype html><title>Focus</title><main>Today\'s Focus</main>' }));
}

// Step 22: the terminal view (ORCH-744) on the terminal bridge (ORCH-743). The stream (GET /api/term/stream) is fake
// data here; what is typed and the sizes are only recorded. Watching only first: keys and a paste send nothing; Let me
// type turns typing on; a paste with a line end asks first; Ctrl+C with a selection copies instead of stopping.
const TERM_SCREEN = ['\x1b[1m⏺ \x1b[0mRunning the tests for the export.', '  \x1b[32m✔\x1b[0m counts skills per day \x1b[2m(41 ms)\x1b[0m',
  '  \x1b[32m✔\x1b[0m empty workspace shows zero', '  \x1b[31m✖\x1b[0m week view adds up to the day view', '',
  '\x1b[7m> \x1b[0m'].join('\r\n');
async function terminalView(page, dash, width) {
  const typed = [], sizes = [];
  await page.context().grantPermissions(['clipboard-read', 'clipboard-write']);
  await liveFocus(page);  // with the stand-in stream (fakeTermStream)
  await page.route('**/api/term/input', route => { typed.push(route.request().postDataJSON().data); route.fulfill({ json: {} }); });
  await page.route('**/api/term/size', route => { sizes.push(route.request().postDataJSON()); route.fulfill({ json: {} }); });
  await page.addInitScript(() => { try { Object.keys(localStorage).filter(k => k.indexOf('orch.live.') === 0).forEach(k => localStorage.removeItem(k)); } catch (e) { /* none */ } });
  await page.goto(dash + '/#home');
  await mainHasText(page);
  await page.click('[data-key="live-open"]');
  await page.waitForSelector('[data-key="live-pane"]', { timeout: 5000 });
  // a ticket's pane shows the terminal in Terminal view (Chat | Terminal: in the header, or in More when the pane is
  // narrow); before that switch is on develop, the plain terminal session shows it (it has no chat view)
  let pane = '.live-pane';
  if (await page.$('[data-key="live-view-term"]')) await page.click('[data-key="live-view-term"]');
  else if (await page.$('[data-key="live-pane-more"]') && await (async () => { await page.click('[data-key="live-pane-more"]'); return !!await page.$('[data-key="live-more-view"]'); })()) await page.click('[data-key="live-more-view"]');
  else {
    await page.keyboard.press('Escape').catch(() => {});
    const id = 't_ntterm001', made = [];
    let last = null;
    const dress = st => { st.sessions = made.map(() => ({ id, kind: 'terminal', title: 'Plain terminal', open: true })); st.rev = 'pt-' + made.length; last = st; return st; };
    await page.route(/\/api\/state(\?.*)?$/, async route => {
      const res = await route.fetch();
      if (res.status() !== 200) return route.fulfill({ response: res });
      const st = await res.json();
      st.addons = [...(st.addons || []).filter(a => a.name !== 'focus'), { name: 'focus', label: 'Focus', icon: 'target', active: true, removable: true, shipped: false,
        description: 'A live page for one ticket.', page: { path: '/', label: 'Open Focus', live_session: true }, dashboard: { label: 'Focus', icon: 'target', order: 20 } }];
      st.settings = { ...(st.settings || {}), focus_preview_on: true };
      route.fulfill({ response: res, json: st.unchanged && last ? dress({ ...last }) : dress(st) });
    });
    await page.route(/\/api\/sessions(\?.*)?$/, route => route.fulfill({ json: { lines: 8, age_ms: 0, sessions: made.map(() => ({ id, key: '', title: 'Plain terminal',
      kind: 'terminal', status: 'idle', word: 'Open', detail: '', waiting_on: [], question: null, lines: [], tool: null, model: null, mode: null,
      opened_at: null, open_seconds: null, idle_seconds: null, closes_in_seconds: null, last_at: null, pinned: true, name: null })) } }));
    await page.route('**/api/act', async route => {
      const body = route.request().postDataJSON();
      if (body.op !== 'session.new' || body.args.kind !== 'terminal') return route.continue();
      made.push(id);
      route.fulfill({ json: dress({ ...last }) });
    });
    await page.reload();  // the page reads the dressed state from the start
    await mainHasText(page);
    await page.waitForSelector('#live-bar [data-lbar-new]', { timeout: 10000 });
    await page.click('#live-bar [data-lbar-new]');
    await page.click('#live-bar [data-lbar-kind="terminal"]');
    pane = `#live-dock .live-pane[data-session="${id}"]`;
    await page.waitForSelector(pane, { timeout: 10000 });
  }
  await page.waitForSelector(pane + ' .term[data-state="live"] .xterm canvas', { timeout: 5000 });
  if (!(await page.evaluate(() => window.termStreams || [])).some(u => /\/api\/term\/stream\?ticket=t_/.test(u))) throw new Error('the pane did not open the bridge stream');
  const term = pane + ' .term', box = pane + ' .term .xterm-screen';
  if (await page.$eval(term, el => el.dataset.typing) !== 'off') throw new Error('the terminal did not start watching only');
  // the screen text, read back through Copy (the screen is drawn on a canvas)
  await page.click(term + ' [data-key="term-copy"]');
  if (!/week view adds up/.test(await page.evaluate(() => navigator.clipboard.readText()))) throw new Error('Copy did not copy the helper\'s screen');
  // watching only: a key and a paste send nothing
  await page.click(box);
  await page.keyboard.type('x');
  await page.$eval(term + ' .xterm-helper-textarea', el => { const d = new DataTransfer(); d.setData('text/plain', 'ls'); el.dispatchEvent(new ClipboardEvent('paste', { clipboardData: d, bubbles: true, cancelable: true })); });
  await page.waitForTimeout(150);
  if (typed.length) throw new Error('keys went out while watching only');
  // Let me type, then a command
  await page.click(term + ' [data-key="term-type"]');
  if (await page.$eval(term, el => el.dataset.typing) !== 'on') throw new Error('Let me type did not turn typing on');
  // the keys go where the screen has the keyboard: wait for it, then for what went out (a busy first width is slow)
  await page.waitForFunction(t => document.activeElement?.matches(t + ' .xterm-helper-textarea'), term, { timeout: 3000 });
  await page.keyboard.type('ls');
  await page.keyboard.press('Enter');
  for (let i = 0; i < 20 && typed.join('') !== 'ls\r'; i++) await page.waitForTimeout(100);
  if (typed.join('') !== 'ls\r') throw new Error(`typing sent ${JSON.stringify(typed)}`);
  // a paste with a line end asks first; Cancel sends nothing
  await page.$eval(term + ' .xterm-helper-textarea', el => { const d = new DataTransfer(); d.setData('text/plain', 'echo one\necho two\n'); el.dispatchEvent(new ClipboardEvent('paste', { clipboardData: d, bubbles: true, cancelable: true })); });
  await page.waitForSelector(term + ' .term-ask:not([hidden])', { timeout: 2000 });
  if (!/2 lines/.test(await page.textContent(term + ' .term-ask'))) throw new Error('the paste question does not say how many lines');
  await page.click(term + ' [data-key="term-paste-no"]');
  // select text with the mouse and press Ctrl+C: it copies, nothing goes to the helper
  const r = await page.$eval(box, el => { const b = el.getBoundingClientRect(); return { x: b.x, y: b.y }; });
  await page.mouse.move(r.x + 4, r.y + 4);
  await page.mouse.down();
  await page.mouse.move(r.x + 200, r.y + 30, { steps: 5 });
  await page.mouse.up();
  await page.keyboard.press('Control+c');
  await page.waitForTimeout(150);
  if (typed.join('') !== 'ls\r') throw new Error(`a cancelled paste or Ctrl+C with a selection went out: ${JSON.stringify(typed)}`);
  // the screen follows its box while typing (desktop: the pane is a different size than 80 x 24)
  await page.waitForTimeout(400);
  if (width > 720 && !sizes.length) throw new Error('no new size went to the helper while typing');
  if (sizes.some(z => !(z.cols >= 10 && z.cols <= 500 && z.rows >= 3 && z.rows <= 300))) throw new Error(`a size out of range: ${JSON.stringify(sizes)}`);
  await page.click(box);
  await noSideways(page);
}

// Step 10: the layer in every place, kept across a page change and a reload.
async function layer(page, dash, width) {
  const phone = width <= 720;
  const panel = m => `#live-dock[data-mode="${m}"] .live-panel[data-mode="${m}"]`;
  const press = async key => { await page.keyboard.press(key); await page.waitForTimeout(50); };
  await liveFocus(page);
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
  // a compact pane (on the right, on a phone) keeps Full screen in More (ORCH-463)
  if (await page.$('#live-dock .live-pane [data-key="live-full"]')) await page.click('[data-key="live-full"]');
  else {
    await page.click('#live-dock .live-pane [data-key="live-pane-more"]');
    await page.click('[data-key="live-more-menu"] [data-key="live-more-full"]');
  }
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
    st.settings = { ...(st.settings || {}), live_max: full ? 4 : 6,
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
  // the choice opens at its top and is back there after a start, never under the pane header (ORCH-1361)
  const atTop = () => page.$eval(pane, el => el.closest('.live-pb')?.scrollTop || 0);
  if (await atTop()) throw new Error('the Start choice does not open at its top');
  await layerTextScale(page, 'Start choice');
  await noSideways(page);
  // one click starts fresh with the usual tool and model: only run.start --fresh goes to orch. The pane is scrolled
  // to its end first, as a person reaching a lower button in a short pane would (the start must bring it back up)
  await page.$eval(pane, el => { const pb = el.closest('.live-pb'); if (pb) pb.scrollTop = pb.scrollHeight; });
  await page.click(pane + ' [data-start="fresh"]');
  await page.waitForTimeout(500);
  if (asked.length !== 1 || asked[0].op !== 'run.start' || !asked[0].args.fresh || asked[0].args.agent) throw new Error('one-click fresh start: ' + JSON.stringify(asked));
  // the faked start never shows a helper: the choice stays Starting… and every choice is greyed and says why
  const busy = await page.$eval(pane, el => ({
    busy: !!el.querySelector('.live-start[aria-busy="true"]'),
    greyed: [...el.querySelectorAll('[data-start="continue"],[data-start="fresh"]')].every(b => b.disabled && /The helper is starting\./.test(document.getElementById(b.getAttribute('aria-describedby'))?.textContent || '')) }));
  if (!busy.busy || !busy.greyed) throw new Error('after a start the choice is not Starting… with reasons: ' + JSON.stringify(busy));
  if (await atTop()) throw new Error('after a start the Start choice is not shown from its top');
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
    st.settings = { ...(st.settings || {}), 
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
    return { key: el.dataset.session, on: el.dataset.on !== undefined, tight: el.dataset.tight !== undefined, x: Math.round(r.left), y: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height) };
  }));
  const count = async n => {
    await page.waitForFunction(k => document.querySelectorAll('#live-dock .live-pane').length === k, n, { timeout: 5000 });
    await motionQuiet(page);  // the panes slide to their new place (step 23): measure where they end
    return panes();
  };
  const inPane = (key, what) => `#live-dock .live-pane[data-session="${key}"] [data-key="${what}"]`;
  // pin, add beside, place, minimise and close on every pane (pin and place through More when the pane is narrow)
  const controls = async () => {
    for (const p of await panes()) {
      const has = async what => !!await page.$(inPane(p.key, what));
      const more = await has('live-pane-more'), inHead = await has('live-pin') && await has('live-pane-place');
      if (!more && !inHead) throw new Error(`the pane of ${p.key} has no pin or place`);
      // draft D: a pane with room shows pin and place in its header (ORCH-1568); a tight one folds them into More
      if (!phone && !p.tight && !inHead) throw new Error(`the pane of ${p.key} has room but its header has no pin and place`);
      if (!phone && !await has('live-beside')) throw new Error(`the pane of ${p.key} has no add beside`);
      if (!(await has('live-min') || more) || !await has('live-close')) throw new Error(`the pane of ${p.key} has no minimise or close`);
      if (more && !inHead) {
        await page.click(inPane(p.key, 'live-pane-more'));
        await page.waitForSelector('[data-key="live-more-menu"] [data-key="live-pin"]', { timeout: 5000 });
        if (!await page.$('[data-key="live-more-menu"] [data-live="place"][data-mode="bottom"]')) throw new Error(`More of ${p.key} has no place`);
        if (!await has('live-min') && !await page.$('[data-key="live-more-menu"] [data-key="live-more-min"]')) throw new Error(`the pane of ${p.key} has no minimise`);
        await page.keyboard.press('Escape');
        await page.waitForSelector('[data-key="live-more-menu"]', { state: 'detached', timeout: 5000 });
      }
    }
  };
  // Add beside asks which session (ORCH-463): open its menu, pick the first one offered
  const addBeside = async sel => {
    await page.click(sel);
    await page.waitForSelector('[data-key="live-beside-menu"] [data-key="live-beside-pick"]', { timeout: 5000 });
    await page.click('[data-key="live-beside-menu"] [data-key="live-beside-pick"]');
  };
  const sideBySide = (list, stacked) => list.every((p, i) => !i || (stacked ? p.y > list[i - 1].y && p.x === list[0].x : p.x > list[i - 1].x && p.y === list[0].y));
  await liveBarState(page);
  barAsk = true;  // the waiting tickets carry their open question, as orch's state does
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
    await addBeside('[data-key="live-beside"]');
    list = await count(2);
    if (!sideBySide(list)) throw new Error('two panes do not sit next to each other');
    await addBeside(inPane(list[0].key, 'live-beside'));
    list = await count(3);
    if (!sideBySide(list)) throw new Error('three panes do not sit next to each other');
    if (!list[2].on || list.filter(p => p.on).length !== 1) throw new Error('the new pane is not the selected one');
    // ORCH-1362: with three panes Add beside is not greyed; its menu says why and offers no session
    if (await page.$eval(inPane(list[0].key, 'live-beside'), b => b.disabled)) throw new Error('add beside is greyed with three panes');
    await page.click(inPane(list[0].key, 'live-beside'));
    const none = (await page.textContent('[data-key="live-beside-menu"] [data-key="live-beside-none"]', { timeout: 5000 }).catch(() => '')).trim();
    if (!/^Three sessions show at once/.test(none)) throw new Error(`add beside with three panes does not say why (it says "${none}")`);
    if (await page.$('[data-key="live-beside-menu"] [data-key="live-beside-pick"]')) throw new Error('add beside offers a fourth session');
    await page.keyboard.press('Escape');
    await page.waitForSelector('[data-key="live-beside-menu"]', { state: 'detached', timeout: 5000 });
    await controls();
    await askCardsInPanes(page);
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
  if (await page.$(inPane(one, 'live-pin'))) await page.click(inPane(one, 'live-pin'));
  else {
    await page.click(inPane(one, 'live-pane-more'));
    await page.click('[data-key="live-more-menu"] [data-key="live-pin"]');
  }
  await page.waitForFunction(k => window.LiveSessions.pins.includes(k), one, { timeout: 5000 });
  if (!await page.evaluate(k => window.LiveLayer.pins.includes(k), one)) throw new Error('the pin was not kept');
  // place from a pane: on the right the panes stack; then back to the bottom (a phone has no right)
  const place = async mode => {
    if (await page.$(inPane(one, 'live-pane-place'))) await page.click(inPane(one, 'live-pane-place'));
    else await page.click(inPane(one, 'live-pane-more'));
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
  if (await page.$(inPane(one, 'live-min'))) await page.click(inPane(one, 'live-min'));
  else {  // a narrow pane keeps Minimise in More (ORCH-463)
    await page.click(inPane(one, 'live-pane-more'));
    await page.click('[data-key="live-more-menu"] [data-key="live-more-min"]');
  }
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
    await addBeside(inPane(left[0].key, 'live-beside'));
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

// Step 33. Permission mode of a session without a ticket (ORCH-818). Like step 15 the test dashboard has no orch to
// start helpers, so the step answers session.new like the core does (`orch session new <kind> --permission-mode <m>`,
// tested in workspace/tests/test_sessionmode.py) and the next state carries state.session_modes as the server builds
// it (data.load_session_modes). Everything else is the real page: the New menu's Permissions row, the pane's line.
async function permModes(page, dash, width) {
  // FD_SHOTS=<folder>: also pictures of the warning and the pane's line (for the ticket), not only the end
  const extra = async name => process.env.FD_SHOTS && (await page.waitForTimeout(600), page.screenshot({ path: require('node:path').join(process.env.FD_SHOTS, `fd-33-${name}-${width}.png`) }));
  const live = { name: 'focus', label: 'Focus', icon: 'target', active: true, removable: true, shipped: false,
    description: 'A live page for one ticket.', page: { path: '/', label: 'Open Focus', live_session: true },
    dashboard: { label: 'Focus', icon: 'target', order: 20 } };
  const id = 't_ntmanag01', calls = [];
  const LABEL = { ask: 'Default', edits: 'Accept edits', auto: 'Auto', full: 'Bypass permissions' };
  const ws = { top: 'full', warned: false, remembered: 'auto', running: null };
  const rank = m => ['ask', 'edits', 'auto', 'full'].indexOf(m);
  const modes = () => Object.fromEntries(['manager', 'empty', 'chat'].map(k => {
    const cur = k === 'manager' && rank(ws.remembered) <= rank(ws.top) ? ws.remembered : ws.top;
    const run = k === 'manager' ? ws.running : null;
    return [k, { current: cur, label: LABEL[cur], full_warned: ws.warned, running: run, running_label: run ? LABEL[run] : null,
      choices: Object.keys(LABEL).map(m => ({ mode: m, label: LABEL[m], allowed: rank(m) <= rank(ws.top) })) }];
  }));
  let last = null;
  const dress = st => {
    st.addons = [...(st.addons || []).filter(a => a.name !== live.name), live];
    st.settings = { ...(st.settings || {}), focus_preview_on: true };
    st.sessions = ws.running ? [{ id, kind: 'manager', title: 'Manager', open: true }] : [];
    st.runs = { ...(st.runs || {}) };
    if (ws.running) st.runs[id] = { running: true, helper: { state: 'idle' }, claim: { agent: 'agent:claude' } };
    st.session_modes = modes();
    st.rev = 'pm-' + calls.length + '-' + ws.top + '-' + ws.warned;
    last = st;
    return st;
  };
  await page.route(/\/api\/state(\?.*)?$/, async route => {
    const res = await route.fetch();
    if (res.status() !== 200) return route.fulfill({ response: res });
    const st = await res.json();
    route.fulfill({ response: res, json: st.unchanged && last ? dress({ ...last }) : dress(st) });
  });
  await page.route(/\/api\/sessions(\?.*)?$/, route => route.fulfill({ json: { lines: 8, age_ms: 0, sessions: ws.running ? [{
    id, key: '', title: 'Manager', kind: 'manager', status: 'idle', word: 'Idle', detail: '', waiting_on: [], question: null, lines: [],
    tool: 'Claude Code', model: null, mode: 'live', opened_at: null, open_seconds: null, idle_seconds: null, closes_in_seconds: null,
    last_at: null, pinned: true, name: null }] : [] } }));
  await page.route('**/api/act', async route => {
    const body = route.request().postDataJSON();
    if (body.op !== 'session.new') return route.continue();
    calls.push([body.args.kind, body.args.permissions || '']);
    const m = body.args.permissions;
    if (m && rank(m) > rank(ws.top)) return route.fulfill({ status: 422, body: 'Bypass permissions is not allowed in this workspace.' });
    if (m) { ws.remembered = m; if (m === 'full') ws.warned = true; }
    ws.running = m || ws.remembered;
    route.fulfill({ json: dress({ ...last }) });
  });
  await page.goto(dash + '/#home');
  await mainHasText(page);
  await page.waitForSelector('#live-bar [data-lbar-new]', { timeout: 10000 });
  const openMenu = async () => {
    await page.click('#live-bar [data-lbar-new]');
    await page.waitForSelector('#live-bar [data-key="lbar-perm"]', { timeout: 5000 });
  };
  // the New menu has the tool's four modes; nothing picked: the Manager says it starts in its own (Auto)
  await openMenu();
  const segs = await page.$$eval('#live-bar [data-lbar-perm]', els => els.map(el => el.innerText.trim()));
  if (segs.join('|') !== 'Default|Accept edits|Auto|Bypass permissions') throw new Error(`the Permissions row has ${segs.join(', ')}`);
  const mgr = () => page.textContent('#live-bar [data-lbar-kind="manager"]');
  if (!/Auto/.test(await mgr())) throw new Error(`the Manager does not say its mode: ${await mgr()}`);
  // Bypass permissions: one plain warning the first time, the Manager says it starts so
  await page.click('#live-bar [data-lbar-perm="full"]');
  await page.waitForSelector('#live-bar [data-key="lbar-perm-warn"]', { timeout: 3000 });
  await extra('warning');
  if (!/Bypass permissions/.test(await mgr())) throw new Error(`the Manager does not say Bypass permissions: ${await mgr()}`);
  await page.click('#live-bar [data-lbar-kind="manager"]');
  await page.waitForSelector(`#live-dock .live-pane[data-session="${id}"] [data-key="live-perm"]`, { timeout: 10000 });
  if (JSON.stringify(calls[0]) !== '["manager","full"]') throw new Error(`the start sent ${JSON.stringify(calls[0])}`);
  const line = () => page.textContent(`#live-dock .live-pane[data-session="${id}"] [data-key="live-perm"]`);
  if ((await line()).trim() !== 'Permissions: Bypass permissions') throw new Error(`the pane says "${(await line()).trim()}"`);
  await extra('pane');
  // the pane goes on in another mode (the same conversation): Auto
  await page.click(`#live-dock .live-pane[data-session="${id}"] [data-key="live-perm"]`);
  await page.waitForSelector('#live-dock [data-key="live-perm-menu"]', { timeout: 3000 });
  const now = await page.textContent('#live-dock [data-live-perm="full"]');
  if (!/\(now\)/.test(now)) throw new Error(`the menu does not mark the mode in use: ${now}`);
  await extra('pane-menu');
  await page.click('#live-dock [data-live-perm="auto"]');
  await page.waitForFunction(() => /Permissions: Auto$/.test(document.querySelector('#live-dock [data-key="live-perm"]')?.textContent.trim() || ''), null, { timeout: 5000 });
  if (JSON.stringify(calls[1]) !== '["manager","auto"]') throw new Error(`the restart sent ${JSON.stringify(calls[1])}`);
  // a workspace that does not allow Bypass permissions: the segment is off and says why
  ws.top = 'auto'; ws.warned = false;
  await page.reload();
  await mainHasText(page);
  await page.locator('#live-dock [data-key="live-min"]:visible').first().click().catch(() => {});
  await page.waitForSelector('#live-bar [data-lbar-new]', { timeout: 10000 });
  await openMenu();
  const off = await page.$eval('#live-bar [data-lbar-perm="full"]', el => [el.disabled, el.title]);
  if (!off[0] || !/Not allowed in this workspace/.test(off[1])) throw new Error(`Bypass permissions is not off: ${off}`);
  await page.click('#live-bar [data-lbar-perm="edits"]');
  await page.waitForSelector('#live-bar [data-lbar-perm="edits"][aria-pressed="true"]', { timeout: 3000 });
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
  // the plain terminal opens the bridge stream (ORCH-743/744); here it answers that the screen is not there
  await page.route(/\/api\/term\/stream(\?.*)?$/, route => route.fulfill({ status: 200, contentType: 'text/event-stream',
    body: 'retry: 600000\n\nevent: hello\ndata: {"typing_allowed": false}\n\nevent: end\ndata: {"state": "none"}\n\n' }));
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
// workspace has one ticket, so the step adds four with the run states the button speaks for.
const FOCUS_TICKETS = [['run', 'ORCH-189', 'New price list for the shop', 'Watch'], ['wait', 'ORCH-190', 'Send the weekly summary', 'Answer'],
  ['idle', 'ORCH-191', 'Tidy the release notes', 'Open'], ['none', 'ORCH-192', 'Opening hours page', 'Start']];
async function focusButton(page, dash, width) {
  const phone = width <= 720;
  const live = { name: 'focus', label: 'Focus', icon: 'target', active: true, removable: true, shipped: false,
    description: 'A live page for one ticket.', page: { path: '/', label: 'Open Focus', live_session: true },
    dashboard: { label: 'Focus', icon: 'target', order: 20 } };
  const HELPER = { wait: 'you', run: 'working', idle: 'idle' };
  const id = key => 't_fb' + key.slice(5);
  let answered = null, lastState = null;  // the answer the pane sent; the page's state as last served
  const unasked = st => ({ ...st, tickets: st.tickets.map(t => t.id === id('ORCH-190') ? { ...t, questions: [] } : t) });
  await page.route('**/api/act', async route => {
    const body = route.request().postDataJSON();
    if (body.op !== 'answer' || body.args.ticket !== id('ORCH-190') || !lastState) return route.fallback();
    answered = body.args.answer;
    await new Promise(r => setTimeout(r, 300));  // the answer takes a moment, as with orch: the buttons wait disabled
    route.fulfill({ json: unasked(lastState) });  // the server answers an action with the page's state
  });
  await page.route(/\/api\/state(\?.*)?$/, async route => {
    const res = await route.fetch();
    if (res.status() !== 200) return route.fulfill({ response: res });
    const st = await res.json();
    const base = (st.tickets || []).find(t => t.id !== WIDGET_ID) || {};  // not the demo ticket of every widget kind
    const extra = FOCUS_TICKETS.map(([s, key, title]) => ({ ...base, id: id(key), key, title, status: s === 'none' ? 'ready' : 'active',
      questions: s === 'wait' ? [{ id: 'q1', text: 'Send it to the whole team or only to sales?', options: ['Whole team', 'Only sales'] }] : [],
      checks: [], sessions: [] }));
    st.tickets = [...(st.tickets || []).filter(t => !String(t.id).startsWith('t_fb')), ...extra];
    st.runs = { ...(st.runs || {}) };
    FOCUS_TICKETS.forEach(([s, key]) => { if (s !== 'none') st.runs[id(key)] = { running: true, helper: { state: HELPER[s] }, claim: { agent: 'agent:claude' } }; });
    st.addons = [...(st.addons || []).filter(a => a.name !== live.name), live];
    st.settings = { ...(st.settings || {}), 
      addons: [...((st.settings || {}).addons || []).filter(a => a.name !== live.name), live] };
    lastState = st;
    route.fulfill({ response: res, json: answered ? unasked(st) : st });
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
  // ORCH-709: the waiting question answered with the keyboard in its pane; the keyboard stays in the pane (never by
  // hand here) and Esc steps the layer back to the bar
  await tapAbove(page, `${rowSel('ORCH-190')} [data-key="live-session-btn"]`);
  const waitPane = `#live-dock .live-pane[data-session="${id('ORCH-190')}"]`;
  await page.waitForSelector(`${waitPane} [data-live-ask] [data-key="live-ask-option-0"]`, { timeout: 5000 });
  await page.focus(`${waitPane} [data-key="live-ask-option-0"]`);
  await page.keyboard.press('Enter');
  await page.waitForFunction(p => document.querySelector(p + ' [data-live-ask]')?.hidden, waitPane, { timeout: 10000 });
  for (let i = 0; i < 80 && answered === null; i++) await page.waitForTimeout(100);  // sent after the Undo window (ORCH-1359)
  if (answered !== 'Whole team') throw new Error('the answer sent was ' + JSON.stringify(answered));
  await page.waitForTimeout(100);
  const at = await page.evaluate(p => { const a = document.activeElement; return document.querySelector(p)?.contains(a) ? '' : (a?.tagName || 'nothing'); }, waitPane);
  if (at) throw new Error('after the answer the keyboard is on ' + at + ', not in the pane');
  await page.keyboard.press('Escape');
  await page.waitForSelector('#live-dock[data-mode="bar"]', { timeout: 5000 }).catch(() => { throw new Error('Esc after the answer did not step the layer back'); });
  // the ticket page: "Watch in Focus" opens its session; Open ticket comes back to the same page
  await page.evaluate(h => { location.hash = h; }, '#ticket/' + id('ORCH-189'));
  await mainHasText(page);
  const strip = `[data-key="ticket-strip-${id('ORCH-189')}"] [data-key="live-session-btn"]`;
  await page.waitForSelector(strip, { timeout: 10000 });
  if ((await page.textContent(strip)).trim() !== 'Watch in Focus') throw new Error('the ticket page does not say Watch in Focus');
  if (await page.$('[data-key="watch-live"]')) throw new Error('the old Watch live still shows');
  await page.click(strip);
  const pane = `#live-dock .live-pane[data-session="${id('ORCH-189')}"]`;
  await page.waitForSelector(pane, { timeout: 5000 });
  if (!await page.$eval(`${pane} .key`, el => el.textContent.trim() === 'ORCH-189')) throw new Error('the pane does not show the ticket key');
  // from full screen too: Open ticket steps out of it so the ticket page shows
  // a compact pane (narrower than 1200 px, a phone) keeps Full screen in More (ORCH-463)
  if (await page.$(`${pane} [data-key="live-full"]`)) await page.click(`${pane} [data-key="live-full"]`);
  else {
    await page.click(`${pane} [data-key="live-pane-more"]`);
    await page.click('[data-key="live-more-menu"] [data-key="live-more-full"]');
  }
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
  // a ticket with no helper: one start button in the header (ORCH-1466); "Open in Focus" in the ⋯ menu opens its pane,
  // where the start is offered
  await page.evaluate(h => { location.hash = h; }, '#ticket/' + id('ORCH-192'));
  await mainHasText(page);
  const head = `[data-key="ticket-strip-${id('ORCH-192')}"]`;
  await page.waitForSelector(`${head} [data-key="ticket-menu-${id('ORCH-192')}"] > summary`, { timeout: 10000 });
  if (await page.$(`${head} [data-key="live-session-btn"]`)) throw new Error('a ticket with no helper still shows a second start (Start in Focus) beside Start helper');
  await page.click(`${head} [data-key="ticket-menu-${id('ORCH-192')}"] > summary`);
  const start = `${head} [data-key="ticket-open-layer"]`;
  await page.waitForSelector(start, { timeout: 5000 });
  if ((await page.textContent(start)).trim() !== 'Open in Focus') throw new Error('the ⋯ menu of a ticket with no helper has no Open in Focus');
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
  // ORCH-1358: the wall never says less than Home's number, which also counts what needs the person outside these
  // sessions: the test workspace's own open questions and results (the core's count, ORCH-476) come on top of the 3.
  const own = await page.evaluate(() => fetch('/api/state').then(r => r.json())
    .then(s => (s.counts?.needs_you?.items || []).filter(i => !String(i.ticket).startsWith('t_bar')).length));
  for (const w of [(3 + own) + ' need you', '4 working', '9 in line', '8 idle']) if (!hero.includes(w)) throw new Error(`the summary line misses "${w}": ${hero}`);
  const total = (await page.textContent('[data-key="wall-total"]')).trim();
  if (!/^24 sessions · \d+( of \d+)? helper places? in use$/.test(total)) throw new Error('the summary does not say 24 sessions and the helper places in use: ' + total);
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
  for (let i = 0; i < 80 && !asked.length; i++) await page.waitForTimeout(100);  // sent after the Undo window (ORCH-1359)
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
  if (!(await page.textContent('[data-key="wall-total"]')).trim().startsWith('24 sessions · ')) throw new Error('the filter changed the total');
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
  // a compact pane (narrower than 1200 px, a phone) keeps Full screen in More (ORCH-463)
  if (await page.$(`${pane} [data-key="live-full"]`)) await page.click(`${pane} [data-key="live-full"]`);
  else { await page.click(`${pane} [data-key="live-pane-more"]`); await page.click('[data-key="live-more-menu"] [data-key="live-more-full"]'); }
  await page.waitForSelector(`#live-dock[data-mode="full"] ${pane}`, { timeout: 5000 });
  if (!(await page.isVisible('#live-dock[data-mode="full"] #live-bar'))) throw new Error('full screen keeps no strip of the other sessions');
  await page.keyboard.press('Escape');
  await page.waitForSelector(`#live-dock[data-mode="${docked}"] ${pane}`, { timeout: 5000 });
  await page.focus(`${pane} :is([data-key="live-full"], [data-key="live-pane-more"])`);
  await page.keyboard.press('Escape');
  await page.waitForSelector('#live-dock[data-mode="bar"]', { timeout: 5000 });
  if (!(await page.isVisible(tileOf('t_bar232')))) throw new Error('the wall is not back after Esc');
  // the picture: the zoomed session in full screen, as in draft D
  await page.click(`${tileOf('t_bar232')} [data-wall-open]`);
  await page.waitForSelector('#live-dock ' + pane, { timeout: 5000 });
  // a compact pane (narrower than 1200 px, a phone) keeps Full screen in More (ORCH-463)
  if (await page.$(`${pane} [data-key="live-full"]`)) await page.click(`${pane} [data-key="live-full"]`);
  else { await page.click(`${pane} [data-key="live-pane-more"]`); await page.click('[data-key="live-more-menu"] [data-key="live-more-full"]'); }
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
const GWORD = { working: 'Working', 'needs-you': 'Needs you', 'in-line': 'In line', closed: 'No session' };
const GRANK = { 'needs-you': 0, working: 1, 'in-line': 2 };
const gid = key => 't_grp' + key.slice(5);
const SMALL = [{ what: 'Draft intro', seconds: 180 }, { what: 'Draft offers', seconds: 60 }];
async function groupState(page, tweak = null) {
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
    const base = (st.tickets || []).find(t => t.id !== WIDGET_ID) || {};  // not the demo ticket of every widget kind
    const extra = GROUP.map(([key, title, , depth]) => ({ ...base, id: gid(key), key, title, status: 'active', questions: [], checks: [],
      sessions: [], parent: depth === 1 ? gid('ORCH-300') : null }));
    if (tweak) tweak(extra);
    st.tickets = [...(st.tickets || []).filter(t => !String(t.id).startsWith('t_grp')), ...extra];
    st.runs = { ...(st.runs || {}) };
    GROUP.forEach(([key, , s]) => {
      if (s === 'in-line') st.runs[gid(key)] = { running: false, hold: 'Waits for a free place' };
      else if (s !== 'closed') st.runs[gid(key)] = { running: true, helper: { state: HELPER[s] }, claim: { agent: 'agent:claude' } };
    });
    st.addons = [...(st.addons || []).filter(a => a.name !== live.name), live];
    st.settings = { ...(st.settings || {}), 
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
  await tapAbove(page, `${tile} [data-wall-open]`);
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

// Step 35 (ORCH-1600, owner): more room for the terminal in full screen. The helper list on the left and Results on the
// right fold to a narrow strip and open again, remembered after a reload; in the Terminal view the waiting question sits
// at the top of the Results column instead of above the screen, and goes back above it while Results is folded.
async function foldView(page, dash, width) {
  await groupState(page, extra => {
    const t = extra.find(x => x.key === 'ORCH-302');
    t.questions = [{ id: 'q1', text: 'Which header picture for the mail page?', options: ['The autumn leaves', 'The shop window'], answer: null }];
  });
  await fakeTermStream(page, false);  // typing is off in this workspace: the terminal offers the way to the switch
  await page.addInitScript(() => { try { if (sessionStorage.getItem('fold') !== '1') { localStorage.removeItem('orch.live.fold'); localStorage.removeItem('orch.live.view'); sessionStorage.setItem('fold', '1'); } } catch (e) { /* none */ } });
  await page.goto(dash + '/#addon/focus');
  const tile = `[data-key="live-wall"] [data-tile="${gid('ORCH-300')}"]`;
  await page.waitForSelector(tile, { timeout: 15000 });
  await tapAbove(page, `${tile} [data-wall-open]`);
  const pane = `#live-dock .live-pane[data-session="${gid('ORCH-302')}"]`;
  await page.waitForSelector(`${pane} [data-live-ask]:not([hidden])`, { timeout: 10000 });
  if (width <= 720) {  // a phone: the list is a strip and Results a row on top; there is nothing to fold
    if (await page.isVisible(`${pane} .live-fold`)) throw new Error('a fold button shows on a phone');
    await noSideways(page);
    return;
  }
  await page.click(`${pane} :is([data-key="live-full"], [data-key="live-pane-more"])`);
  if (await page.$('[data-key="live-more-full"]')) await page.click('[data-key="live-more-full"]');
  await page.waitForSelector(`#live-dock[data-mode="full"] .live-pane[data-session="${gid('ORCH-302')}"] .live-shelf`, { timeout: 5000 });
  await page.waitForTimeout(600);  // the pane grows into full screen first (motion); a click during it hits the leaving picture
  await page.click(`${pane} [data-key="live-view-term"]`);
  await page.waitForSelector(`${pane} [data-key="live-view-term"][aria-pressed="true"]`, { timeout: 5000 })
  await page.waitForSelector(`${pane} .live-shelf > [data-live-ask]:not([hidden])`, { timeout: 5000 });
  await page.waitForSelector(`${pane} [data-key="term-settings"]:not([hidden])`, { timeout: 5000 });
  if (await page.getAttribute(`${pane} [data-key="term-settings"]`, 'href') !== '#settings/addons/focus') throw new Error('Turn typing on does not lead to the Focus settings');
  if ((await page.textContent(`${pane} .term-say`)).trim() !== 'Watching only') throw new Error('the typing line says it twice: ' + await page.textContent(`${pane} .term-say`));
  if (await page.isVisible(`${pane} .live-shelf-list > .meta`)) throw new Error('"Nothing yet" shows under the question in the Results column');
  const title = await page.$eval(`${pane} .live-pt`, el => el.scrollWidth <= el.clientWidth + 1);
  if (!title) throw new Error('the title of the pane is cut in full screen');
  await extraShot(page, 'fd-35-fold-open', width);
  const inHead = async k => !!(await page.$(`${pane} .live-ctl > [data-key="${k}"]`));
  if (width < 1500) {  // Pin, Add beside and Minimise are in More, so the title fits
    for (const k of ['live-pin', 'live-beside', 'live-min']) if (await inHead(k)) throw new Error(`${k} is still in the header at ${width}`);
    await page.click(`${pane} [data-key="live-pane-more"]`);
    for (const k of ['live-pin', 'live-more-beside', 'live-more-min']) if (!(await page.$(`[data-key="live-more-menu"] [data-key="${k}"]`))) throw new Error(`More misses ${k}`);
    await page.click('[data-key="live-more-menu"] [data-key="live-more-beside"]');
    if (!(await page.evaluate(() => !!document.activeElement?.closest?.('#live-dock .live-pop')))) throw new Error('Add beside from More leaves the keyboard outside its choice');
    await page.keyboard.press('Escape');
    if (!(await page.evaluate(() => document.activeElement?.dataset?.key === 'live-pane-more'))) throw new Error('Esc in Add beside does not go back to More');
  } else for (const k of ['live-pin', 'live-beside', 'live-min']) if (!(await inHead(k))) throw new Error(`${k} is not in the header at ${width}`);
  const wide = sel => page.$eval(sel, el => Math.round(el.getBoundingClientRect().width));
  const termBefore = await wide(`${pane} .live-pb[data-live-body]`);
  await page.click(`${pane} [data-key="live-fold-left"]`);
  await page.click(`${pane} [data-key="live-fold-right"]`);
  await page.waitForSelector(`${pane}[data-fold-left][data-fold-right]`, { timeout: 5000 });
  if (await wide(`${pane} [data-key="live-group"]`) > 56) throw new Error('the folded helper list is still wide');
  if (await wide(`${pane} .live-shelf`) > 56) throw new Error('the folded Results column is still wide');
  const termAfter = await wide(`${pane} .live-pb[data-live-body]`);
  if (termAfter < termBefore + 400) throw new Error(`folding gave the terminal ${termAfter - termBefore} px, expected the room of both sides`);
  if (!(await page.$(`${pane} .live-pb[data-live-body] > [data-live-ask]:not([hidden])`))) throw new Error('with Results folded the question is not above the terminal');
  if (await page.getAttribute(`${pane} [data-key="live-fold-right"]`, 'aria-label') !== 'Show results') throw new Error('the folded Results button does not say Show results');
  await page.mouse.move(width / 2, 400);  // no hover on an arrow while comparing them or in the picture
  await page.waitForTimeout(250);  // the hover colour fades out
  const looks = await page.evaluate(p => ['left', 'right'].map(sd => { const c = getComputedStyle(document.querySelector(`${p} [data-key="live-fold-${sd}"]`)); return [c.borderTopWidth, c.borderTopStyle, c.backgroundColor, c.outlineStyle, c.boxShadow].join(' '); }), pane);
  if (looks[0] !== looks[1]) throw new Error('the two fold arrows look different: ' + looks.join(' | '));
  await extraShot(page, 'fd-35-fold-closed', width);
  await page.reload();
  await page.waitForSelector(`${pane}[data-fold-left][data-fold-right]`, { timeout: 10000 });
  await page.click(`${pane} [data-key="live-fold-left"]`);
  await page.click(`${pane} [data-key="live-fold-right"]`);
  await page.waitForSelector(`${pane}:not([data-fold-left]):not([data-fold-right]) .live-shelf > [data-live-ask]:not([hidden])`, { timeout: 5000 });
  await page.click(`${pane} [data-key="live-view-chat"]`);
  await page.waitForSelector(`${pane} .live-pb[data-live-body] > [data-live-ask]:not([hidden])`, { timeout: 5000 });  // the chat keeps it on top
  await noSideways(page);
  await page.keyboard.press('Escape');
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
  await wallPage(page, dash, 'fd25', null, { ask: true });
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
  // ORCH-1328: the layer is a sheet over most of the screen, the bar under it stays one row
  const sheet = await page.evaluate(() => {
    const p = document.querySelector('[data-key="live-panel"]').getBoundingClientRect(), bar = document.querySelector('#live-bar');
    const rows = new Set([...bar.querySelectorAll('button, a')].filter(b => b.getBoundingClientRect().height > 0).map(b => Math.round(b.getBoundingClientRect().top / 8)));
    return { share: p.height / window.innerHeight, rows: rows.size, barH: bar.getBoundingClientRect().height };
  });
  if (sheet.share < 0.55) throw new Error(`on a phone the layer covers only ${Math.round(sheet.share * 100)}% of the screen, not a sheet`);
  if (sheet.rows > 1 || sheet.barH > 64) throw new Error(`on a phone the Focus bar takes ${sheet.rows} rows`);
  await askCardsInPanes(page);
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
  // ORCH-1358: the pane header follows the same session list: an ended session never says Working
  const head = await page.$eval('#live-dock .live-pane[data-session="t_bar235"]', el => el.querySelector('.pill')?.textContent || '');
  if (/Working/.test(head)) throw new Error('the pane of a session that ended still says ' + head);
}

// Steps 23 and 24 (ORCH-1329): the motion of draft D. A recorder in the page notes every animation that starts in the
// layer, on the wall and in the big overlay (CSS keyframes and script moves; colour changes on hover and a working
// spinner are no change and left out) and the layout shift that no click caused. The same tour runs both steps: the
// big overlay in the style guide opens and closes, a tile zooms into the layer, full screen and back, Add beside twice
// and a pane closes (one session at a time on a phone), the layer goes back to the bar, a tile is pinned, and a tile
// opens again for the picture. Step 23: each change moves, only transform and opacity, at most 240 ms, layout shift at
// most 0.1. Step 24 (reduced motion): nothing moves, every change is still there at once, the last lines still update.
const MOTION_OK = new Set(['transform', 'opacity', 'transformOrigin', 'offset', 'computedOffset', 'easing', 'composite']);
async function motionWatch(page) {
  await page.evaluate(() => {
    const seen = new WeakSet();
    window.__motion = []; window.__shift = 0;
    try {
      new PerformanceObserver(l => { for (const e of l.getEntries()) if (!e.hadRecentInput) window.__shift += e.value; }).observe({ type: 'layout-shift' });
    } catch (e) { /* no layout-shift entries in this browser */ }
    const tick = () => {
      for (const a of document.getAnimations()) {
        if (seen.has(a)) continue;
        seen.add(a);
        if (typeof CSSTransition === 'function' && a instanceof CSSTransition && !/^(transform|opacity|translate|scale)$/.test(a.transitionProperty)) continue;  // hover colours
        const fx = a.effect, t = fx && fx.getTiming ? fx.getTiming() : {}, el = fx && fx.target;
        if (t.iterations === Infinity || !el || !el.closest) continue;
        if (!el.closest('#live-dock, [data-key="live-wall"], dialog.result-overlay')) continue;
        const cls = typeof el.className === 'string' ? el.className.split(' ')[0] : '';
        window.__motion.push({ what: cls || el.tagName.toLowerCase(), name: a.animationName || a.transitionProperty || 'script', ms: Number(t.duration) || 0,
          props: [...new Set(fx.getKeyframes().flatMap(k => Object.keys(k)))], at: performance.now() });
      }
      requestAnimationFrame(tick);
    };
    tick();
  });
}
const motionNow = page => page.evaluate(() => performance.now());
async function motionSince(page, at) {
  await page.waitForTimeout(350);  // the longest move is 240 ms
  return page.evaluate(t => window.__motion.filter(m => m.at >= t), at);
}
async function motionQuiet(page) {
  await page.waitForFunction(() => !document.getAnimations().some(a => a.playState === 'running' && a.effect && a.effect.getTiming().iterations !== Infinity
    && !(typeof CSSTransition === 'function' && a instanceof CSSTransition && !/^(transform|opacity|translate|scale)$/.test(a.transitionProperty))), null, { timeout: 3000 }).catch(() => {});
}
async function motionTour(page, dash, width, reduce) {
  const phone = width <= 720, moved = [];
  const step = async (label, act, want) => {
    const at = await motionNow(page);
    await act().catch(async e => {
      const dock = await page.evaluate(() => { const d = document.getElementById('live-dock'); return d ? `the layer is ${d.dataset.mode}, ${d.querySelectorAll('.live-pane').length} panes` : 'no layer'; }).catch(() => '');
      throw new Error(`${label}: ${e.message.split('\n')[0]} (${dock})`);
    });
    const got = await motionSince(page, at);
    moved.push(...got.map(m => ({ ...m, label })));
    if (reduce) {
      if (got.length) throw new Error(`with reduced motion "${label}" still moves: ${got.map(m => m.what + ' ' + m.name).join(', ')}`);
    } else if (want && !got.some(m => m.what === want)) {
      throw new Error(`"${label}" does not move (${want}); it moved: ${got.map(m => m.what + ' ' + m.name).join(', ') || 'nothing'}`);
    }
  };
  const pane = id => `.live-pane[data-session="${id}"]`;
  const inPane = (id, what) => `#live-dock ${pane(id)} [data-key="${what}"]`;
  const count = n => page.waitForFunction(k => document.querySelectorAll('#live-dock .live-pane').length === k, n, { timeout: 5000 });
  const full = async id => {
    if (await page.$(inPane(id, 'live-full'))) return page.click(inPane(id, 'live-full'));
    await page.click(inPane(id, 'live-pane-more'));
    await page.click('[data-key="live-more-menu"] [data-key="live-more-full"]');
  };
  // 1. the big overlay (style guide): opens and closes
  await page.goto(dash + '/styleguide/#result-widgets');
  await page.waitForSelector('#rw-grid .result[data-type="md"] .result-open', { timeout: 15000 });
  await motionWatch(page);
  const opener = '#rw-grid .result[data-type="md"] .result-open';
  await page.locator(opener).scrollIntoViewIfNeeded();
  await step('open the big overlay', async () => {
    await page.click(opener);
    await page.waitForSelector('dialog.result-overlay[open]', { timeout: 2000 });
  }, 'dialog');
  await page.keyboard.press('Escape');
  await page.waitForFunction(() => !document.querySelector('dialog.result-overlay[open]'), null, { timeout: 5000 });
  // 2. Focus: the live last lines keep coming (step 24 checks they still update)
  let tick = 0;
  await wallPage(page, dash, reduce ? 'fd24' : 'fd23', () => {
    const list = barSessions();
    tick += 1;
    const s = list.find(x => x.id === 't_bar232');
    s.lines = [...s.lines, '⏺ Checked part ' + tick];
    return list;
  });
  await page.waitForSelector('#live-dock[data-mode="bar"]', { timeout: 10000 });
  await motionWatch(page);
  if (reduce) {
    const peek = `${tileOf('t_bar232')} [data-wall-peek]`, n = await page.textContent(peek);
    await page.waitForFunction(([sel, was]) => (document.querySelector(sel)?.textContent || '') !== was, [peek, n], { timeout: 10000 })
      .catch(() => { throw new Error('with reduced motion the last lines on the tile stop updating'); });
  }
  // the timing of each step: a change with reduced motion is there at once (no waiting for a move)
  const quick = reduce ? 400 : 5000;
  await step('zoom a tile into the layer', async () => {
    await page.click(`${tileOf('t_bar232')} [data-wall-open]`);
    await page.waitForSelector(`#live-dock:is([data-mode="bottom"], [data-mode="right"]) ${pane('t_bar232')}`, { timeout: quick });
  }, 'live-pane');
  await step('full screen', async () => {
    await full('t_bar232');
    await page.waitForSelector(`#live-dock[data-mode="full"] ${pane('t_bar232')}`, { timeout: quick });
  }, 'live-panel');
  await step('leave full screen', async () => {
    await page.keyboard.press('Escape');
    await page.waitForSelector(`#live-dock:is([data-mode="bottom"], [data-mode="right"]) ${pane('t_bar232')}`, { timeout: quick });
  }, 'live-panel');
  if (phone) {
    // one session at a time: Open beside takes the pane, the new one grows out of its tile
    await step('open another session from the wall', async () => {
      await page.click(`${tileOf('t_bar235')} [data-wall-beside]`);
      await page.waitForSelector('#live-dock ' + pane('t_bar235'), { timeout: quick });
    }, 'live-pane');
  } else {
    await step('add a pane beside', async () => {
      await page.click(`${tileOf('t_bar235')} [data-wall-beside]`);
      await count(2);
    }, 'live-pane');
    await step('add a third pane', async () => {
      await page.click(`${tileOf('t_bar240')} [data-wall-beside]`);
      await count(3);
    }, 'live-pane');
    await step('close a pane', async () => {
      await page.click(inPane('t_bar240', 'live-close'));
      await count(2);
    }, 'live-pane');
  }
  await step('back to the bar', async () => {
    await page.focus(`#live-dock .live-pane [data-key="live-close"]`);
    await page.keyboard.press('Escape');
    await page.waitForSelector('#live-dock[data-mode="bar"]', { timeout: quick });
  }, 'live-panel');
  if (await page.$('#live-dock .live-panel:not([data-leaving])')) throw new Error('the panel is still there after it closed');
  await step('pin a session', async () => {
    await page.click(`${tileOf('t_bar235')} [data-wall-pin]`);
    await page.waitForSelector(`[data-band="pin"] [data-tile="t_bar235"]`, { timeout: quick });
  }, 'wall-tile');
  // the picture: the session open in the layer again, after the move ended
  await step('zoom again for the picture', async () => {
    await page.click(`${tileOf('t_bar232')} [data-wall-open]`);
    await page.waitForSelector(`#live-dock:is([data-mode="bottom"], [data-mode="right"]) ${pane('t_bar232')}`, { timeout: quick });
  }, 'live-pane');
  await motionQuiet(page);
  if (!reduce) {
    const long = moved.filter(m => m.ms > 240);
    if (long.length) throw new Error('these moves take longer than 240 ms: ' + long.map(m => `${m.label}: ${m.what} ${m.name} ${m.ms} ms`).join('; '));
    const other = moved.filter(m => m.props.some(p => !MOTION_OK.has(p)));
    if (other.length) throw new Error('these moves animate more than transform and opacity: ' + other.map(m => `${m.label}: ${m.what} ${m.name} (${m.props.join(', ')})`).join('; '));
  }
  const shift = await page.evaluate(() => window.__shift);
  if (shift > 0.1) throw new Error(`the layout shifts by ${shift.toFixed(3)} without a click (at most 0.1)`);
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
    n: 2, pic: 'fd-02-focus-new', area: 'start', title: 'Focus opens as the new Focus', feature: [],
    do: ['Open Focus from the side bar (at phone width from its address).'],
    see: ['Focus opens as the new Focus (the wall of step 4 fills it), with no Preview mark.', 'No old Focus page shows.',
      'At 390 wide nothing scrolls sideways.'],
    async run({ page, dash }) {
      await focusIsNew(page, dash);
    },
  },
  {
    n: 3, pic: 'fd-03-no-switch', area: 'start', title: 'Focus has no Preview switch', feature: [],
    do: ['Open Settings, Add-ons, Focus.'],
    see: ['The Typing switch is there; there is no Preview switch and no word Preview.'],
    async run({ page, dash }) {
      await focusIsNew(page, dash);
      await noPreviewSwitch(page);
    },
  },
  {
    n: 4, pic: 'fd-04-wall', area: 'wall', title: 'The live wall in bands', feature: [1],
    do: ['Open Focus.', 'Watch a working tile for 10 seconds.'],
    see: ['Bands in this order: Pinned, Needs you and working, In line, Idle and no session.',
      'One summary line on top, with the number of sessions and of helper places in use.', 'Each tile says in one plain sentence what its helper does.',
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
    // the draft picture ends like the built step: the wall with the orange tile (ORCH-1568)
    draft: { q: '?page=focus' },
  },
  {
    n: 6, pic: 'fd-06-focus-button', area: 'wall', title: 'Focus button on a ticket and Open ticket on a session',
    feature: [3],
    do: ['Open Tickets and press the Focus button of a row.', 'Press Answer on a waiting row and answer with the keyboard, then Esc.',
      'Open a ticket page and press its Focus button.', 'In the session press Open ticket, also from full screen.'],
    see: ['Every ticket row has the button; it says Watch, Answer, Open or Start to fit the ticket. A ticket page with a helper working has Watch in Focus; with no helper, Open in Focus is in its ⋯ menu (one start button, ORCH-1466).',
      'The session opens in the layer and the page stays.', 'After the answer the keyboard stays in the session; Esc steps back to the bar.',
      'Open ticket goes back to the same ticket page; the session stays open.'],
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
      'With three panes Add beside is not greyed: its menu says three is the most and to close one first.',
      'The split stays while the page changes.', 'Closing a pane gives its room to the others.',
      'On a phone one session shows at a time and there is no add beside.',
      'A waiting question shows its orange card with answer buttons in every pane; the header is one row of icon buttons beside the title.'],
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
    async run({ page, dash, width }) {
      await staysOpen(page, dash, width);
    },
    draft: { q: '?page=review&mode=bottom&split=2' },
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
    see: ['The open question, the last lines of its screen, then tool and model (for example "Claude Code · Opus").',
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
    n: 17, pic: 'fd-17-chat', area: 'chat', title: 'Chat: messages and ticket events, questions answered inside', feature: [5],
    do: ['Open a session: it opens in Chat.', 'Answer its waiting question in the orange card and send a message.',
      'Switch to Terminal, reload, switch back to Chat.'],
    see: ['Plain messages with time; done steps and other events as lines between them; the pull request inside the message.',
      'The waiting question is an orange card above the chat, not a message; once answered it moves into the chat as yours.',
      'A sent message shows at once; Terminal shows the helper’s screen and the choice stays after a reload.',
      'Tab never stops on the page under the layer, and a long chat scrolls with the keyboard.'],
    run: ({ page, dash }) => chatView(page, dash),
    draft: { q: '?page=focus&cur=ORCH-228&view=zoom' },
  },
  {
    n: 18, pic: 'fd-18-message-box', area: 'message box', title: 'Files and screenshots in the message box, with a preview before sending',
    feature: [13],
    do: ['Attach a file, paste a screenshot, drop a second file.', 'Remove one, then send.', 'Reload the page.'],
    see: ['Each one shows as a small preview before sending.', 'Removing one takes it out; the sent message carries the rest.',
      'The box says its limits in plain words; a file over 25 MB is refused.', 'The sent message and its files stay after a reload.'],
    run: ({ page, dash }) => messageBox(page, dash),
    draft: { q: '?page=focus&cur=ORCH-238&view=zoom&att=1' },
  },
  {
    n: 19, pic: 'fd-19-voice', area: 'voice', title: 'Voice into the message box', feature: [13],
    do: ['With the relay on, press the microphone and speak.', 'Stop, read the words in the box, edit them.', 'Turn the relay off.'],
    see: ['While listening the button says so and Esc cancels.', 'The words land in the box and are never sent by themselves.',
      'With the relay off there is no microphone.', 'A blocked microphone or nothing heard is one plain sentence.'],
    run: ({ page, dash }) => voiceBox(page, dash),
    draft: { q: '?page=focus&cur=ORCH-238&view=zoom&voice=done' },
  },
  {
    n: 20, pic: 'fd-20-widgets', area: '16 widgets', title: 'All 16 result widgets, small and big', feature: [10],
    do: ['Open the style guide, section Results.', 'Open each widget big, use the arrows to go to the next one, close with Esc.'],
    see: ['One small widget for each of the 16 kinds: ' + WIDGETS.join(', ') + '.',
      'Each opens big in an overlay; arrows step through, Esc closes and gives the focus back.',
      'Empty, loading and error look like the style guide states.'],
    run: ({ page, dash }) => widgetsGuide(page, dash),
    draft: { q: '?page=widgets' },
  },
  {
    n: 21, pic: 'fd-21-widgets-ticket', area: '16 widgets', title: 'The same widgets on a tile, in the chat and on a ticket page', feature: [10],
    do: ['Open Focus and look at the tile of a ticket with results; open its result big.',
      'Open the session: each finished step carries its results inside its message; open one big.',
      'Open the ticket page and open one result big.'],
    see: ['The tile shows the newest result small and how many more there are.',
      'The chat shows the files, check runs and pull request of a step inside that step\'s message.',
      'The ticket page shows every result of the ticket as the same widgets as Focus, all 16 kinds from its real files, evidence and links.',
      'The big overlay is the same one everywhere: arrows step through, Esc closes and gives the focus back.'],
    run: ({ page, dash, width }) => widgetsTicket(page, dash, width),
    // a helper's web page shows in a frame with an empty sandbox: its own script is refused on purpose
    okConsole: /Blocked script execution in '[^']*\/view\/t_widget16\//,
    draft: { q: '?page=ticket&tk=ORCH-228&res=ORCH-228:0' },
  },
  {
    n: 22, pic: 'fd-22-terminal', area: 'terminal', title: 'A real terminal: type, select, copy and paste', feature: [5],
    do: ['Switch a session to Terminal.', 'Press a key: nothing is sent (watching only).', 'Turn on Let me type, type a command and press Enter.',
      'Paste two lines, then Cancel.', 'Select text and copy it.'],
    see: ['The helper\'s real screen with its colours; it starts watching only.', 'Keys go to the helper only after Let me type.',
      'A paste with a line end asks first.', 'Selecting and copying works like on any page; Copy copies the selection or the screen.',
      'While typing the screen follows the size of its pane.', 'It can only be reached from this computer (the bridge, ORCH-743).'],
    async run({ page, dash, width }) {
      await terminalView(page, dash, width);
    },
    draft: { q: '?page=focus&cur=ORCH-232&view=zoom&term=1' },
  },
  {
    n: 23, pic: 'fd-23-motion', area: 'motion', title: 'Opening, zooming, pinning and splitting animate', feature: [7, 8, 9],
    do: ['Open a result big and close it.', 'Zoom a tile into the layer, go full screen and back.',
      'Add two panes beside and close one (a phone: open another session from the wall).', 'Put the layer back in the bar, pin a session, zoom a tile again.'],
    see: ['Each change moves smoothly and quickly, nothing jumps: the pane grows out of its tile, the panes slide to their new place, the panel fades out when it closes, a pinned tile slides to the Pinned band.',
      'Only transform and opacity move, each move at most 240 ms, layout shift at most 0.1.', 'The picture is taken after the move ends.'],
    async run({ page, dash, width }) {
      await motionTour(page, dash, width, false);
    },
    draft: { q: '?page=focus&cur=ORCH-228&view=zoom' },
  },
  {
    n: 24, pic: 'fd-24-reduced-motion', area: 'reduced motion', title: 'With reduced motion everything stays still',
    feature: [7, 8, 9], reduce: true,
    do: ['Turn on reduced motion in the system settings.', 'Repeat step 23.'],
    see: ['Every change happens at once, without movement.', 'The live last lines still update.'],
    async run({ page, dash, width }) {
      await motionTour(page, dash, width, true);
    },
    draft: { q: '?page=focus&cur=ORCH-228&view=zoom' },
  },
  {
    n: 25, pic: 'fd-25-phone', area: 'phone width', title: 'Phone width: one session at a time', feature: [7],
    do: ['At 390 wide open Focus, open a session, then try to put the layer on the right.'],
    see: ['The wall is one column.', 'The layer opens at the bottom and shows one session; right falls back to bottom.',
      'Nothing scrolls sideways; every button can be reached.',
      'The layer is a sheet over most of the screen with the question card and its buttons; the Focus bar under it stays one row.'],
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
      'An unknown ticket shows the wall, opens nothing and says "There is no ticket with this address. Find it on the Tickets page." with an Open Tickets button'],
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
    // the draft picture ends like the built step: back at the bar over the wall (ORCH-1568)
    draft: { q: '?page=focus' },
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
    see: ['Its tile leaves Working and says No session.', 'Its pane header no longer says Working.', 'Its pane offers the Start choice.'],
    async run({ page, dash }) {
      await ended(page, dash);
    },
    draft: { q: '?page=focus&cur=ORCH-235&view=zoom&ask=1' },
  },
  {
    n: 33, pic: 'fd-33-permissions', area: 'sessions', title: 'Start the Manager in a chosen permission mode', feature: [6],
    do: ['Open the New menu in the bar and pick Bypass permissions in its Permissions row.', 'Start the Manager.',
      'In its pane press "Permissions: Bypass permissions" and pick Auto.', 'In a workspace that allows at most Auto, open the New menu.'],
    see: ['The row shows the tool\'s modes: Default, Accept edits, Auto, Bypass permissions.',
      'Bypass permissions shows one plain warning the first time; the Manager starts in it and its pane says "Permissions: Bypass permissions".',
      'Auto ends the session and goes on with the same conversation; the pane says "Permissions: Auto".',
      'Bypass permissions is off when the workspace does not allow it and says why.'],
    async run({ page, dash, width }) {
      await permModes(page, dash, width);
    },
    draft: { q: '?page=focus&menu=new' },
  },
  {
    n: 34, pic: 'fd-34-shelf', area: 'chat', title: 'Results shelf beside or above the chat', feature: [10],
    do: ['Open a session whose ticket has no results, then one with a pull request.', 'Place Focus at the bottom, on the right, in full screen; then on a phone.'],
    see: ['Without results the shelf says "Nothing yet. Pictures, pages and tables show up here."',
      'The results sit on a shelf called Results, the same widgets as on the ticket page; a click opens them big.',
      'At the bottom (from 900 px wide) a 360 px column beside the chat; in full screen a 320 px column; on the right and on a phone a one-row strip above the chat.'],
    run: ({ page, dash, width }) => shelfView(page, dash, width).catch(async e => { await extraShot(page, 'fd-34-shelf-failed', width).catch(() => {}); throw e; }),
    draft: { q: '?page=focus&cur=ORCH-228&view=zoom' },
  },
  {
    n: 35, pic: 'fd-35-fold', area: 'terminal', title: 'More room for the terminal: fold the sides away', feature: [],
    do: ['Open a helper of an epic that waits for an answer, in full screen, and pick Terminal.',
      'Press the arrow beside the helper list and the one beside Results; reload the page; press them again.'],
    see: ['In the Terminal view the waiting question sits at the top of the Results column, not above the terminal; "Nothing yet" hides under it.',
      'The pane title shows whole; under 1500 px wide Pin, Add beside and Minimise are in More. The terminal line says "Watching only" beside Turn typing on.',
      'Each side folds to a narrow strip with its arrow (both arrows look the same) and the terminal takes the room; the question goes back above the terminal while Results is folded.',
      'After a reload the sides stay folded; the arrows open them again. On a phone there is nothing to fold.'],
    run: ({ page, dash, width }) => foldView(page, dash, width).catch(async e => { await extraShot(page, 'fd-35-fold-failed', width).catch(() => {}); throw e; }),
    draft: { q: '?page=focus&cur=ORCH-228&view=zoom' },
  },
];

module.exports = { STEPS, AREAS, SIZES, WIDGETS, noSideways, mainHasText, liveBarState, barIsOneRow, liveFocus };
