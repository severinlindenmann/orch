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

// The new page with Preview on, for the steps after step 3: the same dressing of the page's state as previewSwitch
// (the live-session add-on and the setting), plus the one ticket of the test workspace marked as having a working helper.
async function livePreview(page) {
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
    route.fulfill({ response: res, json: st });
  });
  await page.route('**/addon/focus/**', route => route.fulfill({ contentType: 'text/html',
    body: '<!doctype html><title>Focus</title><main>Today\'s Focus</main>' }));
}

// Step 10: the layer in every place, kept across a page change and a reload.
async function layer(page, dash, width) {
  const phone = width <= 720;
  const panel = m => `#live-dock[data-mode="${m}"] .live-panel[data-mode="${m}"]`;
  const press = async key => { await page.keyboard.press(key); await page.waitForTimeout(50); };
  await livePreview(page);
  await page.goto(dash + '/#home');
  await page.evaluate(() => { try { localStorage.removeItem('orch.live.layer'); } catch (e) { /* none */ } });
  await page.reload();
  await mainHasText(page);
  await page.waitForSelector('#live-dock[data-mode="bar"] [data-key="live-bar"]', { timeout: 10000 });
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
  await press('Escape');
  await page.waitForSelector(panel(docked), { timeout: 5000 });
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
  if (await page.$('[data-key="live-bar"]')) throw new Error('the bar still shows with the layer closed to the side');
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
    waits: T.bar,
    do: ['Open Home, then Tickets, then Review.', 'Press the "in line" count in the bar.', 'Type in the list\'s search.'],
    see: ['The bar is under every page, calm, on one line that never wraps.',
      'Chips only for sessions that need you and pinned ones; the rest are counts such as "9 in line".',
      'A count opens a list you can search.'],
    draft: { q: '?page=home&many=1&list=queue' },
  },
  {
    n: 10, pic: 'fd-10-layer', area: 'layer', title: 'The layer at the bottom, on the right, full screen, to the bar, to the side',
    feature: [7],
    do: ['Open a session from the bar.', 'Change to Tickets, Review and Home.', 'Use Place: bottom, right, full screen; press Esc twice.',
      'Open it again, minimise it to the bar, then put it to the side and open it from the edge.', 'Make it larger, then reload the page.'],
    see: ['Each place works and the page stays usable behind it; on a phone there is no right.', 'The layer stays open while the page changes.',
      'Esc goes back one step: full screen, then the panel, then the bar.',
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
    waits: T.split,
    do: ['In the layer press Add beside twice.', 'On one pane use pin, Place, minimise and close.'],
    see: ['Two, then three panes sit next to each other.', 'Every pane has pin, add beside, place, minimise and close.',
      'Closing a pane gives its room to the others.'],
    draft: { q: '?page=home&mode=bottom&split=3' },
  },
  {
    n: 13, pic: 'fd-13-stays-open', area: 'layer', title: 'Focus stays open with typed text and split while you change pages',
    feature: [7], waits: T.pages,
    do: ['Open two sessions side by side, type a message without sending.', 'Change to Home, Tickets and Review, then press Back.'],
    see: ['The layer, its split and the typed text stay as they were.', 'The page itself does not reload (no flash).',
      'Back and links work like before.'],
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
    waits: T.data,
    do: ['Look at a tile and at a pane header.', 'Open the model choice of a running session.'],
    see: ['Tool and model are shown (for example "Claude CLI · Opus").', 'How long it is open and when it closes for being idle.',
      'A new model applies from the next fresh start and says so.'],
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
    waits: T.layer,
    do: ['At 390 wide open Focus, open a session, then try to put the layer on the right.'],
    see: ['The wall is one column.', 'The layer opens at the bottom and shows one session; right falls back to bottom.',
      'Nothing scrolls sideways; every button can be reached.'],
    draft: { q: '?page=focus&cur=ORCH-238&mode=right' },
  },
];

module.exports = { STEPS, AREAS, SIZES, WIDGETS, noSideways, mainHasText, livePreview };
