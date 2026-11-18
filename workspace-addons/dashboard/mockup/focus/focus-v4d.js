/* Focus draft D (ORCH-251): the live wall of draft B with the bar and layer of draft A. Demo data only; picks stay in this browser. */
(function () {
  'use strict';
  var KEY = 'orch-focus-v4d-picks', IMG = '../../../../workspace/src/orch_ui/static/demo-image.svg';
  var F = [
    [1, 'Live wall', 'Focus opens on every session in bands: Pinned, Needs you, Working, In line, Idle and no session. One summary line on top; each tile says in a plain sentence what its helper does and shows its last lines live.', 'orch run list gives the signal per ticket (working, idle, waiting); the sentence comes from the helper messages, the peek from the read-only screen, refreshed every few seconds.', 'Medium', 'a new page; the data exists', { page: 'focus', view: 'wall' }],
    [2, 'Needs you is an orange tile', 'A session that waits for you is its normal tile, in orange, first after the pinned ones, with the question as its one sentence. You open it to answer; nothing is decided on the wall.', 'The "waiting on" value of orch run list plus the open question on the ticket; the answer is sent into the session.', 'Small', 'a colour and a sort order', { page: 'focus', view: 'wall', need: 'ORCH-238' }],
    [3, 'Focus button and Open ticket', 'Every ticket has one Focus button (Watch, Answer, Open or Start). Every session has Open ticket to go the other way.', 'The run signal of the ticket decides the word on the button; the session name is the ticket id.', 'Small', 'one button per ticket, one link per session', { page: 'ticket', tk: 'ORCH-189' }],
    [4, 'Continue, fresh start or an earlier session', 'Start asks one thing: continue the last conversation, make a fresh start, or reopen an earlier session from the history list.', 'The session id is kept on the ticket, so the next start resumes it. Built (ORCH-363): orch keeps the last 10 sessions per ticket and Reopen continues one (orch run start --session). Built (ORCH-362): the Start choice on orch run start (--fresh, --agent), with the helper places in use and the line.', 'Medium', 'the Start choice is new', { page: 'focus', view: 'zoom', cur: 'ORCH-189', need: 'ORCH-189' }],
    [5, 'Chat or real terminal', 'Chat shows plain messages with results inside. Terminal is the real screen of the helper: click it and type, select, copy and paste like in the Terminal app.', 'Every helper runs in its own tmux session. Chat is helper messages plus ticket events; no transcript exists.', 'Large', 'a terminal in the browser (xterm.js and a bridge) is new', { page: 'focus', view: 'zoom', cur: 'ORCH-228', term: true }],
    [6, 'Sessions without a ticket', 'Empty helper, Chat helper, Plain terminal and Manager are buttons at the top of Focus and in the New menu of the bar. They are pinned by default.', 'The same per-workspace tmux socket, with a name that is not a ticket id. To build: orch starts helpers only on tickets today.', 'Medium', 'sessions outside the ticket limit need rules', { page: 'home', mode: 'bar', menu: 'new' }],
    [7, 'Focus on every page, split in up to 3', 'A calm bar under every page opens Focus at the bottom, on the right or full screen. Inside, 1, 2 or 3 sessions sit next to each other. Every pane has its own small controls: pin, add one beside, move, minimise and close.', 'Pages are separate full loads today. Cheapest honest path: soft page swaps that keep the layer; fallback: a pop-out window. Each pane attaches to its own tmux session.', 'Large', 'no layer survives a page change today', { page: 'home', mode: 'bottom', panes: ['ORCH-228', 'ORCH-232', 'Manager'], cur: 'ORCH-228', term: true }],
    [8, 'Zoom and full screen', 'Click a session and it grows into a large view. Full screen removes everything but a slim strip of the other sessions, and can be split too. Esc goes one step back.', 'Nothing new in orch: the same session, drawn bigger.', 'Small', 'layout only', { page: 'focus', view: 'zoom', cur: 'ORCH-232', term: true, full: true }],
    [9, 'Pin and name', 'Pin any session to keep it first on the wall and in the bar. Click its name to give it your own.', 'To build: a pinned flag and a display name per session, kept next to the session id.', 'Small', 'two small values to store', { page: 'focus', view: 'zoom', cur: 'Manager', ren: 'Manager' }],
    [10, 'Result widgets with a big preview', 'Every kind of result gets a small widget and a big preview on top of the page: documents, code, tables, pages, PDFs, pictures, recordings, charts, changes. The Widgets page is the proposal, one real example each.', 'Files and evidence attached to the ticket, and the links on it. The style guide already previews pictures, PDFs, pages, tables, Markdown, code, text, audio and video; charts, changes and the tree view are new.', 'Medium', 'one widget and one preview per type, built once in the style guide', { page: 'focus', view: 'zoom', cur: 'ORCH-228', term: false, ov: { src: 'ORCH-228', i: 0 } }, ['See the widget proposal', { page: 'widgets' }]],
    [11, 'Works with 20 to 30 sessions', 'The bar shows the sessions that need you and your pinned ones; everything else is a count such as "9 in line" that opens a list you can search. The wall bands collapse, scroll and filter.', 'The same run list, grouped by signal. Live places are limited (8 in this demo): the other tickets wait in line and start by themselves.', 'Small', 'grouping and a search box', { page: 'home', mode: 'bar', many: true, list: 'queue' }],
    [12, 'Tool and model, seen and chosen', 'Every session shows its tool and model (' + window.MW_TOOLS.t1.label + ' · Opus, ' + window.MW_TOOLS.t2.label + ' · GPT-5), how long it has been open and when it closes for being idle. A new session or a fresh start lets you pick tool and model; the usual one is preselected, so it stays one click.', 'orch picks a model per ticket (the small one first) and a person can move it up. Built (ORCH-362): tool and model at a fresh start (orch run start --agent, orch ticket model) and on the line of every pane. A new model applies when the helper finishes its current step (or at its next start).', 'Medium', 'a choice at the start and a label per session', { page: 'home', mode: 'bar', menu: 'new' }],
    [13, 'Files, screenshots and voice in the message box', 'Attach files, paste or drop a screenshot, and see each one as a small preview before you send. Speak instead of typing: the words land in the box for you to check and edit, never sent by themselves.', 'Attachments to a helper message exist today (the composer: paste a screenshot or drop files, up to 25 MB each). Voice needs the relay turned on, which has a speech-to-text key, so the microphone only shows then. To build and to check: recording in the browser and the text coming back.', 'Medium', 'previews before sending; voice is new', { page: 'focus', view: 'zoom', cur: 'ORCH-228', term: false, att: true, voice: 'done' }]
  ];
  var HIST = [['Yesterday 16:40', 'step 2 of 4', 'Made the sketch, then stopped'], ['12 Nov 10:15', 'step 1 of 4', 'Read the ticket and asked about the size of the job'], ['11 Nov 09:02', 'step 1 of 4', 'First try, went off track']];
  var S = [
    { k: 'ORCH-238', t: 'Add files and notes to a ticket', kind: 'ticket', s: 'wait', tool: 't1', up: 64, step: [3, 5], now: 'Waits for your answer.', qn: 4,
      q: { t: 'Keep the old file name when the same file is added twice?', why: 'The helper suggests keeping it: links people already shared keep working.', a: ['Keep the old name', 'Use the new name'] },
      lines: ['⏺ Bash(node --test tests/attach.test.js)', '  ⎿ ✔ adds a picture to a ticket (38 ms)', '  ⎿ ✔ adds a note below the files (12 ms)', '⏺ The upload works. One thing only you can decide:', '  Keep the old file name when the same file is added twice?', '  1. Keep the old name (suggested)', '  2. Use the new name', '  Waiting for your answer…'],
      chat: [['e', 'Step 2 done: files can be dropped on a ticket', '14:21'], ['h', 'Uploading works for pictures, pages and tables. Notes sit below the files.', '14:38', 0, 0], ['h', 'One thing I need from you before I go on: when the same file is added twice, should the old name stay?', '14:52', 1]],
      files: [['img', 'ticket-files.png', 'Picture · 14:36'], ['table', 'upload-sizes.csv', 'Table · 3 rows', [['Picture', '2.1 MB'], ['Page', '48 KB'], ['Table', '12 KB']]]] },
    { k: 'ORCH-228', t: 'Phone width and zoom', kind: 'ticket', s: 'run', tool: 't1', model: 'Opus', up: 38, step: [4, 5], now: 'Opening the pull request.',
      lines: ['⏺ All 3 widths pass: 1280, 1920 and 390.', '⏺ Bash(git push -u origin fix/phone-width)', '  ⎿ branch fix/phone-width set up to track origin', '⏺ Writing the pull request text.', '⏺ Bash(gh pr create --base develop --draft)', '  ⎿ Creating pull request…'],
      feed: ['  ⎿ pull request 1318 opened as a draft', '⏺ Linking the pull request to the ticket.', '  ⎿ linked', '⏺ Waiting for the checks: 3 of 12 green.', '⏺ Waiting for the checks: 7 of 12 green.', '⏺ Waiting for the checks: 11 of 12 green.'],
      chat: [['e', 'Step 3 done: the page fits a phone at 390', '14:31'], ['h', 'The Home page no longer scrolls sideways on a phone. Here is the picture.', '14:40', 0, 0], ['h', 'Opening the pull request now. I will tell you when the checks are green.', '15:02', 0, 4]],
      files: [['img', 'home-390.png', 'Picture · 14:39'], ['html', 'phone-widths.html', 'Page · before and after'], ['chart', 'Width check', 'Chart · 3 widths'], ['table', 'widths.csv', 'Table · 3 rows', [['1280', 'fits'], ['1920', 'fits'], ['390', 'fits']]], ['pr', 'Pull request 1318', 'Draft · 3 of 12 checks green', [['State', 'Draft'], ['Checks', '3 of 12 green'], ['Changes', '6 files']]], ['link', 'Notes on phone widths', 'Link · team wiki']] },
    { k: 'ORCH-232', t: 'Insights and usage counts', kind: 'ticket', s: 'run', tool: 't2', up: 22, step: [2, 6], now: 'Running the tests.',
      lines: ['⏺ Bash(node --test tests/insights.test.js)', '  ⎿ ✔ counts skills per day (41 ms)', '  ⎿ ✔ counts keys that were never used (9 ms)', '  ⎿ ✔ empty workspace shows zero, not an error (6 ms)'],
      feed: ['  ⎿ ✔ week view adds up to the day view (17 ms)', '  ⎿ ✔ a failed call counts as failed (8 ms)', '  ⎿ ℹ tests 14 · pass 14 · fail 0', '⏺ Bash(uv run python -m pytest -q tests/test_insights.py)', '  ⎿ ......................  22 passed in 3.1s', '⏺ Tests are green. Drawing the usage chart next.', '⏺ Running the tests once more after the chart.'],
      chat: [['e', 'Step 1 done: counts are collected per day', '13:58'], ['h', 'The counts are in. I am running the tests before I draw the chart.', '15:04', 0, 0]],
      files: [['chart', 'Usage by day', 'Chart · 14 days'], ['html', 'insights-preview.html', 'Page · draft'], ['link', 'usage-raw.json', 'Link · data file']] },
    { k: 'ORCH-247', t: 'Steer a helper from the dashboard', kind: 'ticket', s: 'idle', sl: 'Idle 18 min', tool: 't1', model: 'Opus', up: 96, close: 42, step: [5, 5], now: 'Finished and merged. Ready for your review.',
      lines: ['⏺ Bash(orch ref wait ORCH-247 --merge)', '  ⎿ 12 of 12 checks green · merged', '⏺ Done. The Steer button is on the ticket page and', '  pull request 1309 is merged. Ready for your review.'],
      chat: [['e', 'Step 5 done: merged on all tests passed', '14:44'], ['h', 'Finished. You can try the Steer button on any working ticket.', '14:45', 0, 0]],
      files: [['pr', 'Pull request 1309', 'Merged · 12 of 12 checks green', [['State', 'Merged'], ['Checks', '12 of 12 green'], ['Changes', '9 files']]], ['img', 'steer-button.png', 'Picture · 14:30']] },
    { k: 'ORCH-189', t: 'Manager view', kind: 'ticket', s: 'none', sl: 'No session', tool: 't1', last: 'yesterday 16:40', step: [2, 4], now: 'Stopped at step 2 of 4, yesterday 16:40.',
      lines: ['⏺ Stopped at step 2 of 4: the sketch is attached.', '  Next would be the list of helpers.', '', '  Session ended yesterday 16:40'],
      chat: [['e', 'Step 2 done: sketch of the Manager view', 'yesterday 16:31'], ['h', 'I stopped here. The sketch is on the shelf; the helper list is next.', 'yesterday 16:40', 0, 0]],
      files: [['img', 'manager-sketch.png', 'Picture · yesterday']] },
    { k: 'Manager', t: 'Looks after the helpers', kind: 'free', s: 'run', tool: 't1', up: 185, pin: true, now: '4 helpers are live. One waits for you. Nothing is stuck.',
      lines: ['⏺ Bash(orch run list)', '  ⎿ ORCH-238  waiting   an answer from you', '    ORCH-228  working   step 4 of 5', '    ORCH-232  working   step 2 of 6', '    ORCH-247  idle      18 min', '⏺ 4 helpers are live. One waits for you. Nothing is stuck.'],
      feed: ['⏺ Checked again: no change.', '⏺ ORCH-228 opened its pull request.', '⏺ Checked again: tests on ORCH-232 are green.', '⏺ ORCH-247 is idle; it closes by itself after about an hour.'],
      chat: [['h', 'I look at every helper once a minute. One waits for you: ORCH-238.', '15:05', 0, 0]],
      files: [['table', 'helpers.csv', 'Table · 3 rows', [['ORCH-228', 'working'], ['ORCH-232', 'working'], ['ORCH-238', 'waits for you']]]] }
  ];
  var S0 = JSON.stringify(S), EXTRA = null;
  var MORE = [['201', 'Newsletter for November', 'wait'], ['214', 'Price list as a table', 'wait'], ['203', 'Welcome mail for new customers', 'run'], ['205', 'Search in the help pages', 'queue'], ['207', 'Export tickets to a table', 'queue'], ['209', 'Faster first page', 'queue'], ['211', 'Monthly report for sales', 'queue'], ['216', 'Tidy the settings page', 'queue'], ['218', 'Spelling check in mails', 'queue'], ['219', 'New logo on every page', 'queue'], ['222', 'Reminder one day before', 'queue'], ['224', 'Sort the customer list', 'queue'], ['226', 'Holiday notice', 'none'], ['229', 'Bigger text on phones', 'none'], ['231', 'Old links that end nowhere', 'none'], ['234', 'Invoice as a file', 'none'], ['236', 'Colours of the charts', 'none'], ['240', 'Support answers as drafts', 'none']];
  var QS = [{ t: 'Send the newsletter today or on Monday morning?', why: 'The helper suggests Monday: more people open it.', a: ['Send on Monday', 'Send today'] }, { t: 'Show prices with or without tax?', why: 'The helper suggests with tax: it is what customers pay.', a: ['With tax', 'Without tax'] }];
  var NOWS = ['Writing the first draft.', 'Running the tests.', 'Reading the files on the ticket.', 'Taking pictures at three widths.', 'Fixing two failed checks.', 'Waiting for the checks.'];
  var ST = { wait: ['◆', 'Needs you'], run: ['●', 'Working'], idle: ['◐', 'Idle'], none: ['○', 'No session'], queue: ['◷', 'In line'], open: ['▸', 'Open'] };
  var ORDER = { wait: 0, run: 1, open: 2, idle: 3, queue: 4, none: 5 };
  var PAGES = { focus: 'Focus', home: 'Home', tickets: 'Tickets', ticket: 'Tickets', review: 'Review', widgets: 'Widgets' };
  var AG = window.MW_TOOLS, TOOL = { t1: AG.t1.label, t2: AG.t2.label, shell: 'Plain terminal' };
  var NEW = [['Empty helper', 'A helper with no ticket and no task yet'], ['Chat helper', 'Ask anything, no ticket'], ['Plain terminal', 'An empty terminal in this workspace'], ['Manager', 'Looks after all helpers']];
  var st = { page: 'focus', view: 'wall', cur: 'ORCH-238', term: false, mode: 'bar', last: 'bottom', full: false, ask: false, ren: '', menu: '', list: '', lq: '', f: '', col: {}, panes: ['ORCH-238'], act: 0, pm: '', ov: null, nt: 't1', nm: 'Sonnet', voice: '', vk: '', many: false, sheet: false, feat: 0, marks: false, tk: 'ORCH-238' };
  var drafts = {}, picks = {}, uid = 0, feedAt = 0;
  var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  try { picks = JSON.parse(localStorage.getItem(KEY) || '{}') || {}; } catch (e) { picks = {}; }

  function $(id) { return document.getElementById(id); }
  function esc(x) { return String(x).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function at(o) { var h = ''; for (var k in o) if (o[k] !== undefined && o[k] !== null && o[k] !== false) h += ' ' + k + '="' + esc(o[k]) + '"'; return h; }
  function btn(cls, act, inner, o) { return '<button class="' + cls + '" type="button" data-act="' + act + '"' + at(o || {}) + '>' + inner + '</button>'; }
  function has(k) { return S.some(function (s) { return s.k === k; }); }
  function by(k) { for (var i = 0; i < S.length; i++) if (S[i].k === k) return S[i]; return S[0]; }
  function live(s) { return s.s === 'run' || s.s === 'wait' || s.s === 'idle' || s.s === 'open'; }
  function max() { return st.many ? 8 : 6; }
  function used() { return S.filter(function (s) { return s.kind !== 'shell' && live(s); }).length; }
  function sorted() { return S.slice().sort(function (a, b) { var w = (b.s === 'wait' ? 1 : 0) - (a.s === 'wait' ? 1 : 0); return w || (b.pin ? 1 : 0) - (a.pin ? 1 : 0) || ORDER[a.s] - ORDER[b.s]; }); }
  function phone() { return window.innerWidth <= 720; }
  function nm(s) { return s.name || s.t; }
  function word(s) { return s.sl && (s.s === 'idle' || s.s === 'none') ? s.sl : ST[s.s][1]; }
  function now(s) { return s.q ? s.q.t : (s.now || word(s)); }
  function dur(m) { return m < 60 ? m + ' min' : Math.floor(m / 60) + ' h ' + (m % 60 ? (m % 60) + ' min' : ''); }
  function warm(s) {
    if (s.kind === 'shell') return 'stays open until you close it';
    if (s.s === 'idle') return 'closes in ' + (s.close || 40) + ' min if left idle';
    if (s.s === 'none') return 'closed, the conversation is kept';
    if (s.s === 'queue') return 'starts when a place is free';
    return s.s === 'wait' ? 'stays warm while it waits for you' : 'stays warm while it works';
  }
  function grp(o) { return o.s === 'run' || o.s === 'open' ? 'run' : (o.s === 'queue' ? 'queue' : 'idle'); }
  function isOpen() { var m = eff(); return (m !== 'bar' && m !== 'side') || zoomed(); }
  function shownIn(o) { return isOpen() && (zoomed() || phone() ? o.k === st.cur : st.panes.indexOf(o.k) >= 0); }
  function inChip(o) { return o.s === 'wait' || o.pin || shownIn(o); }
  function zoomed() { return st.page === 'focus' && st.view === 'zoom' && !st.full; }
  function eff() { return st.full ? 'full' : (zoomed() ? (st.mode === 'side' ? 'side' : 'bar') : (phone() && st.mode === 'right' ? 'bottom' : st.mode)); }
  function stat(s, bare) { return '<span class="mw-st" data-s="' + s.s + '"><span class="mw-sym" aria-hidden="true">' + ST[s.s][0] + '</span>' + (bare ? '<span class="sr-only">' + word(s) + '</span>' : word(s)) + '</span>'; }
  function mk(n) { if (!st.marks) return ''; return btn('mw-mk', 'feat', n, { 'data-n': n, 'data-pick': picks[n] || '', 'data-on': st.sheet && st.feat === n ? 1 : false, 'aria-label': 'Feature ' + n + ': ' + F[n - 1][1] }); }
  function ic(d) { return '<svg class="ic" viewBox="0 0 24 24" aria-hidden="true">' + d + '</svg>'; }
  var I = {
    pin: ic('<path d="M9 3h6l-1 6 4 4H6l4-4z"/><path d="M12 13v8"/>'),
    full: ic('<path d="M8 3H3v5m13-5h5v5M3 16v5h5m8 0h5v-5"/>'),
    exit: ic('<path d="M3 8h5V3m8 0v5h5M3 16h5v5m8 0v-5h5"/>'),
    right: ic('<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M14 4v16"/>'),
    bottom: ic('<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 13h18"/>'),
    side: ic('<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M18 4v16"/><path d="m10 9 3 3-3 3"/>'),
    beside: ic('<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M12 4v16M16 10v4M14 12h4"/>'),
    prev: ic('<path d="m14 6-6 6 6 6"/>'), next: ic('<path d="m10 6 6 6-6 6"/>'),
    down: ic('<path d="m6 9 6 6 6-6"/>'), up: ic('<path d="m6 15 6-6 6 6"/>'),
    back: ic('<path d="M11 5l-7 7 7 7M4 12h16"/>'), plus: ic('<path d="M12 5v14M5 12h14"/>'), minus: ic('<path d="M5 12h14"/>'),
    file: ic('<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4"/>'), play: ic('<circle cx="12" cy="12" r="9"/><path d="m10 8 6 4-6 4z"/>'), wave: ic('<path d="M4 10v4M8 6v12M12 9v6M16 4v16M20 10v4"/>'),
    clip: ic('<path d="m20 11-8 8a5 5 0 0 1-7-7l8-8a3.5 3.5 0 0 1 5 5l-8 8a2 2 0 0 1-3-3l7-7"/>'), mic: ic('<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>'), stop: ic('<rect x="7" y="7" width="10" height="10" rx="1"/>'),
    x: ic('<path d="M6 6l12 12M18 6 6 18"/>'), more: ic('<circle cx="5" cy="12" r="1.5"/><circle cx="12" cy="12" r="1.5"/><circle cx="19" cy="12" r="1.5"/>'), ext: ic('<path d="M14 4h6v6M20 4l-9 9M18 14v6H4V6h6"/>'),
    t1: ic('<path d="M12 3v18M4.2 7.5l15.6 9M19.8 7.5l-15.6 9"/>'), t2: ic('<path d="m8 7-5 5 5 5m8-10 5 5-5 5"/>'), shell: ic('<rect x="3" y="4" width="18" height="16" rx="2"/><path d="m7 9 3 3-3 3m5 0h5"/>'),
    img: ic('<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="2"/><path d="m5 18 5-5 4 4 2-2 3 3"/>'),
    html: ic('<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c3 3 3 15 0 18M12 3c-3 3-3 15 0 18"/>'),
    table: ic('<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 10h18M3 15h18M10 4v16"/>'),
    chart: ic('<path d="M4 3v17h17M8 16v-4m5 4V7m5 9v-6"/>'),
    pr: ic('<circle cx="6" cy="6" r="2.5"/><circle cx="6" cy="18" r="2.5"/><circle cx="18" cy="18" r="2.5"/><path d="M6 8.5v7M9 6h5a4 4 0 0 1 4 4v5.5"/>'),
    link: ic('<path d="m10 14 4-4m-6 6-1 1a4 4 0 0 1-6-6l4-4a4 4 0 0 1 6 0m2 2 1-1a4 4 0 0 1 6 6l-4 4a4 4 0 0 1-6 0"/>')
  };
  var TH = {
    img: '<svg viewBox="0 0 120 72" preserveAspectRatio="xMidYMin slice" aria-hidden="true"><rect class="mw-f0" width="120" height="72" rx="4"/><rect class="mw-f1" width="120" height="10" rx="4"/><rect class="mw-f1" x="6" y="16" width="24" height="50" rx="2"/><rect class="mw-f2" x="36" y="16" width="44" height="8" rx="2"/><rect class="mw-f1" x="36" y="30" width="78" height="14" rx="2"/><rect class="mw-f1" x="36" y="50" width="78" height="14" rx="2"/></svg>',
    html: '<svg viewBox="0 0 120 72" preserveAspectRatio="xMidYMin slice" aria-hidden="true"><rect class="mw-f0" width="120" height="72" rx="4"/><rect class="mw-f5" width="120" height="22" rx="4"/><rect class="mw-f2" x="10" y="8" width="46" height="6" rx="2"/><rect class="mw-f1" x="10" y="30" width="100" height="5" rx="2"/><rect class="mw-f1" x="10" y="40" width="84" height="5" rx="2"/><rect class="mw-f1" x="10" y="50" width="92" height="5" rx="2"/><rect class="mw-f3" x="10" y="60" width="30" height="6" rx="2"/></svg>',
    chart: '<svg viewBox="0 0 120 72" preserveAspectRatio="xMidYMax slice" aria-hidden="true"><rect class="mw-f0" width="120" height="72" rx="4"/><path class="mw-l1" d="M10 62h100"/><rect class="mw-f3" x="14" y="40" width="12" height="22" rx="2"/><rect class="mw-f3" x="32" y="30" width="12" height="32" rx="2"/><rect class="mw-f3" x="50" y="36" width="12" height="26" rx="2"/><rect class="mw-f3" x="68" y="18" width="12" height="44" rx="2"/><rect class="mw-f2" x="86" y="10" width="12" height="52" rx="2"/></svg>'
  };
  var BL = 0; /* how far the bar is folded: 0 all chips, 1 pinned as a count, 2 counts as More, 3 symbols and counts only */
  var GRP = { run: ['●', 'working', 'Working'], queue: ['◷', 'in line', 'In line'], idle: ['◐', 'idle', 'Idle'] };
  var MODELS = { t1: AG.t1.models, t2: AG.t2.models };
  var KIND = { file: 'file', img: 'picture', html: 'page', table: 'table', chart: 'chart', pr: 'pull request', link: 'link' };
  function mdl(s) { return s.model || AG[s.tool || 't1'].usual; }
  function tlabel(s) { return s.kind === 'shell' ? TOOL.shell : TOOL[s.tool || 't1'] + ' · ' + mdl(s); }
  function tool(s) { var t = s.kind === 'shell' ? 'shell' : (s.tool || 't1'); return '<span class="mw-tool">' + I[t] + tlabel(s) + '</span>'; }
  /* tool and model for a new session or a fresh start: the usual choice is preselected, so starting stays one click */
  function pickHTML() {
    var sg = function (label, list, cur, act, name) { return '<span class="segmented" role="group" aria-label="' + label + '">' + list.map(function (x) { return btn('btn sm', act, name ? name(x) : x, { 'data-v': x, 'aria-pressed': String(cur === x) }); }).join('') + '</span>'; };
    return '<div class="mw-pick" role="group" aria-label="Runs on"><span class="mw-bl">Runs on</span>' + sg('Tool', ['t1', 't2'], st.nt, 'ntool', function (x) { return TOOL[x]; }) + sg('Model', MODELS[st.nt], st.nm, 'nmodel') + mk(12) + '</div>';
  }
  function meta(s, bare) { return '<span class="mw-meta meta">' + (bare ? '' : tool(s)) + (live(s) && s.up !== undefined ? '<span>open ' + dur(s.up) + '</span>' : '') + '<span>' + warm(s) + '</span></span>'; }

  /* ---------- result widgets: one per type, a plain link for the rest (would live in the style guide) ---------- */
  var WG = [
    ['md', 'Markdown', '.md', 'release-notes.md', 'Document · 38 lines', 'Rendered headings and the first lines', 'The whole document, rendered, with Show source', 'yes'],
    ['txt', 'Text and logs', '.txt .log', 'test-run.log', 'Log · 214 lines', 'The last lines, in a fixed-width font', 'The whole text, wrapped, with search', 'yes'],
    ['code', 'Code', '.py .js .ts .sh .css', 'attach.py', 'Code · 64 lines', 'A few highlighted lines with line numbers', 'The whole file, highlighted, with line numbers and Copy', 'yes'],
    ['json', 'JSON and YAML', '.json .yaml', 'settings.json', 'Data · 3 keys', 'A tree you can fold, with counts', 'The whole tree, every branch can fold; Show source', 'check'],
    ['table', 'Table', '.csv .xlsx', 'price-list.csv', 'Table · 3 columns · 12 rows', 'The first rows and the column count', 'All rows, sticky header, pick columns', 'yes'],
    ['html', 'Web page', '.html', 'phone-widths.html', 'Page · before and after', 'A small live preview', 'The page itself, shut off from the dashboard, with Open in a new tab', 'yes'],
    ['pdf', 'PDF', '.pdf', 'offer-acme.pdf', 'PDF · 4 pages', 'The first page and the page count', 'All pages to scroll, with Download', 'yes'],
    ['img', 'Picture', '.png .jpg .svg .gif', 'home-390.png', 'Picture · 390 × 844', 'A thumbnail', 'The picture, fit or full size', 'yes'],
    ['video', 'Video and recording', '.mp4 .webm', 'walkthrough.mp4', 'Video · 0:42', 'A still picture with the length', 'A player with normal controls, no autoplay', 'yes'],
    ['audio', 'Audio', '.mp3 .wav', 'voice-note.mp3', 'Audio · 1:15', 'A wave line with the length', 'A player; the words as text when there is a transcript', 'yes'],
    ['chart', 'Chart', 'numbers from a result', 'Usage by day', 'Chart · 14 days', 'Bars or a line', 'The chart large, with the numbers as a table below', 'new'],
    ['change', 'Change', '.diff and pull requests', 'Phone width fix', 'Change · 6 files', 'Files changed, lines added and removed, checks', 'File by file: what was added and removed', 'check'],
    ['prl', 'Pull request or issue link', 'links to GitHub', 'Pull request 1318', 'Draft · 3 of 12 checks green', 'Its state and the checks', 'State, checks one by one, and the link', 'new'],
    ['zip', 'Archive', '.zip', 'export-november.zip', 'Archive · 14 files', 'How many files and the first names', 'The list of files with sizes, with Download', 'check'],
    ['link', 'Plain link', 'any address', 'Notes on phone widths', 'wiki.example.com/phone-widths', 'An icon, the title and the address; no widget', 'No preview: it opens in a new tab', 'yes'],
    ['unknown', 'Unknown file', 'anything else', 'layout-v3.sketch', 'File · 4.2 MB', 'An icon, the name and the size', 'A plain sentence that it cannot be shown, with Download', 'yes']
  ];
  var WI = { table: 'table', html: 'html', img: 'img', chart: 'chart', change: 'pr', prl: 'pr', link: 'link', video: 'play', audio: 'wave' };
  var WHAVE = { yes: 'In the style guide preview today', check: 'To check', 'new': 'New' };
  var PDF = '<svg viewBox="0 0 120 72" preserveAspectRatio="xMidYMin slice" aria-hidden="true"><rect class="mw-f0" width="120" height="72" rx="4"/><rect class="mw-fp" x="34" y="6" width="52" height="66"/><rect class="mw-f2" x="40" y="13" width="26" height="4"/><rect class="mw-fi" x="40" y="23" width="40" height="2"/><rect class="mw-fi" x="40" y="29" width="36" height="2"/><rect class="mw-fi" x="40" y="35" width="40" height="2"/><rect class="mw-fi" x="40" y="45" width="24" height="2"/><rect class="mw-fi" x="40" y="51" width="40" height="2"/><rect class="mw-fi" x="40" y="57" width="32" height="2"/></svg>';
  var VID = '<svg viewBox="0 0 120 72" preserveAspectRatio="xMidYMid slice" aria-hidden="true"><rect class="mw-f0" width="120" height="72" rx="4"/><rect class="mw-f1" x="8" y="10" width="46" height="52" rx="3"/><rect class="mw-f1" x="60" y="10" width="52" height="24" rx="3"/><rect class="mw-f1" x="60" y="38" width="52" height="24" rx="3"/><circle class="mw-f5" cx="60" cy="36" r="13"/><path class="mw-f2" d="m56 29 12 7-12 7z"/></svg>';
  var WAV = '<svg viewBox="0 0 120 36" preserveAspectRatio="none" aria-hidden="true"><rect class="mw-f0" width="120" height="36" rx="4"/><path class="mw-lw" d="M8 18v0M12 14v8M16 10v16M20 15v6M24 8v20M28 13v10M32 16v4M36 9v18M40 12v12M44 15v6M48 6v24M52 11v14M56 16v4M60 13v10M64 8v20M68 14v8M72 16v4M76 10v16M80 13v10M84 15v6M88 9v18M92 14v8M96 16v4M100 12v12M104 15v6M108 17v2"/></svg>';
  function ln(n, h) { return '<span class="mw-cl2"><i>' + n + '</i>' + h + '</span>'; }
  var CODE = [ln(12, '<span class="tok-keyword">def</span> <span class="tok-func">keep_name</span>(old, new):'), ln(13, '    <span class="tok-comment"># the first name stays, links keep working</span>'), ln(14, '    <span class="tok-keyword">if</span> old.name == new.name:'), ln(15, '        <span class="tok-keyword">return</span> old.name'), ln(16, '    <span class="tok-keyword">return</span> <span class="tok-func">unique</span>(new.name)'), ln(17, ''), ln(18, '<span class="tok-keyword">def</span> <span class="tok-func">unique</span>(name):'), ln(19, '    stem, ext = <span class="tok-func">split</span>(name)'), ln(20, '    <span class="tok-keyword">return</span> <span class="tok-string">f"{stem}-2{ext}"</span>')];
  var LOG = ['15:04:02 ✔ counts skills per day (41 ms)', '15:04:02 ✔ counts keys that were never used (9 ms)', '15:04:03 ✔ empty workspace shows zero, not an error (6 ms)', '15:04:03 ✔ week view adds up to the day view (17 ms)', '15:04:03 ℹ tests 14 · pass 14 · fail 0'];
  var PRICES = [['Plan', 'Per month', 'Per year'], ['Starter', '19', '190'], ['Team', '49', '490'], ['Company', '129', '1290'], ['Extra seat', '9', '90']];
  var CHG = [['dashboard/static/home.css', '+48', '−12'], ['dashboard/static/shell.css', '+31', '−9'], ['dashboard/pages/home.js', '+22', '−14'], ['tests/test_phone_width.py', '+23', '−3']];
  var ZIP = [['tickets.csv', '48 KB'], ['files/home-390.png', '212 KB'], ['files/offer-acme.pdf', '1.1 MB'], ['files/release-notes.md', '3 KB']];
  function grid(rows, head) { return '<span class="mw-gr" data-c="' + rows[0].length + '">' + rows.map(function (r, i) { return r.map(function (c) { return '<span' + (head && !i ? ' class="mw-gh"' : '') + '>' + esc(c) + '</span> '; }).join(''); }).join('') + '</span>'; }
  function tbl(rows, cap, head) { return '<table class="mw-rx mw-ovtable"><caption class="sr-only">' + esc(cap) + '</caption>' + (head ? '<thead><tr>' + rows[0].map(function (c) { return '<th scope="col">' + esc(c) + '</th>'; }).join('') + '</tr></thead>' : '') + '<tbody>' + rows.slice(head ? 1 : 0).map(function (r) { return '<tr>' + r.map(function (c, i) { return i ? '<td>' + esc(c) + '</td>' : '<th scope="row">' + esc(c) + '</th>'; }).join('') + '</tr>'; }).join('') + '</tbody></table>'; }
  /* the small card of a proposed widget (inside a button: spans only) */
  function wsmall(id) {
    if (id === 'md') return '<span class="mw-md"><b>Release notes, week 46</b><span>• Phone pages no longer scroll sideways</span><span>• Files and notes can be added to a ticket</span></span>';
    if (id === 'txt') return '<span class="mw-mono">' + LOG.slice(-3).map(esc).join('\n') + '</span>';
    if (id === 'code') return '<span class="mw-mono">' + CODE.slice(0, 4).join('') + '</span>';
    if (id === 'json') return '<span class="mw-tree"><span>▸ widths <i>3 items</i></span><span>▸ limits <i>2 keys</i></span><span>theme <i>"dark"</i></span></span>';
    if (id === 'table') return grid(PRICES.slice(0, 4), true);
    if (id === 'html') return '<span class="mw-thumb">' + TH.html + '</span>';
    if (id === 'pdf') return '<span class="mw-thumb">' + PDF + '</span>';
    if (id === 'img') return '<span class="mw-thumb">' + TH.img + '</span>';
    if (id === 'video') return '<span class="mw-thumb">' + VID + '</span>';
    if (id === 'audio') return '<span class="mw-thumb mw-wave">' + WAV + '</span>';
    if (id === 'chart') return '<span class="mw-thumb">' + TH.chart + '</span>';
    if (id === 'change') return kv([['Files', '6 changed'], ['Lines', '+124 added, −38 removed'], ['Checks', '3 of 12 green']]);
    if (id === 'prl') return kv([['State', 'Draft'], ['Checks', '3 of 12 green']]);
    if (id === 'zip') return kv(ZIP.slice(0, 2).concat([['and 12 more', '']]));
    return '<span class="meta">No preview for this type</span>';
  }
  /* the big preview of a proposed widget */
  function wbig(id) {
    if (id === 'md') return '<div class="mw-doc"><h3>Release notes, week 46</h3><p>Two changes are ready for review. Nothing needs a decision from you.</p><ul><li>Phone pages no longer scroll sideways (ORCH-228).</li><li>Files and notes can be added to a ticket (ORCH-238).</li><li>The Steer button is on every working ticket (ORCH-247).</li></ul><h3>Known gaps</h3><p>The usage chart is still a draft. The newsletter waits for a date.</p></div>';
    if (id === 'txt') return '<pre class="mw-screen mw-ovtext">' + ['15:04:01 node --test tests/insights.test.js'].concat(LOG).map(esc).join('\n') + '</pre>';
    if (id === 'code') return '<pre class="mw-screen mw-ovtext">' + CODE.join('') + '</pre>';
    if (id === 'json') return '<div class="mw-doc mw-tree2"><details open><summary>widths <i>3 items</i></summary><p>1280</p><p>1920</p><p>390</p></details><details open><summary>limits <i>2 keys</i></summary><p>file_mb: 25</p><p>live_helpers: 6</p></details><p>theme: "dark"</p></div>';
    if (id === 'table') return tbl(PRICES, 'price-list.csv', true) + '<p class="meta">5 of 12 rows · 3 columns</p>';
    if (id === 'html') return '<iframe class="mw-ovframe" src="review-preview.html" title="phone-widths.html"></iframe>';
    if (id === 'pdf') return '<div class="mw-ovpic mw-ovpdf">' + PDF + '</div><p class="meta">Page 1 of 4</p>';
    if (id === 'img') return '<div class="mw-ovpic">' + TH.img + '</div>';
    if (id === 'video') return '<div class="mw-ovpic">' + VID + '</div><p class="meta">0:00 of 0:42 · press play to start</p>';
    if (id === 'audio') return '<div class="mw-ovpic mw-wave">' + WAV + '</div><p class="meta">0:00 of 1:15</p><div class="mw-doc"><h3>The words</h3><p>Please keep the old file name, and add a note for the support team.</p></div>';
    if (id === 'chart') return '<div class="mw-ovpic">' + TH.chart + '</div>' + tbl([['Day', 'Uses'], ['Mon', '41'], ['Tue', '56'], ['Wed', '38'], ['Thu', '72'], ['Fri', '88']], 'Usage by day', true);
    if (id === 'change') return tbl([['File', 'Added', 'Removed']].concat(CHG), 'Files changed', true) + '<pre class="mw-screen mw-ovtext"><span class="mw-del">- .home { min-width: 480px; }</span>\n<span class="mw-add">+ .home { min-width: 0; }</span>\n<span class="mw-add">+ .home .card { overflow-wrap: anywhere; }</span></pre>';
    if (id === 'prl') return tbl([['State', 'Draft'], ['Checks', '3 of 12 green, 9 running'], ['Changes', '6 files'], ['Asked by', 'the helper on ORCH-228']], 'Pull request 1318') + '<p class="meta">Opens on GitHub in a new tab.</p>';
    if (id === 'zip') return tbl([['File', 'Size']].concat(ZIP), 'export-november.zip', true) + '<p class="meta">4 of 14 files</p>';
    return '<div class="mw-doc"><p>This kind of file cannot be shown here. You can download it and open it on your computer.</p><p><span class="btn outline sm">Download</span></p></div>';
  }
  function files(src) {
    if (src === '*') return WG.map(function (w) { return [w[0] === 'link' ? 'link' : 'w', w[3], w[4]]; });
    if (src.indexOf('att:') === 0) return by(src.slice(4)).att || [];
    if (src.indexOf('sent:') === 0) return by(src.slice(5)).sent || [];
    return by(src).files || [];
  }
  function kv(rows) { return '<span class="mw-kv">' + rows.map(function (r) { return '<span>' + esc(r[0]) + '</span> <span>' + esc(r[1]) + '</span> '; }).join('') + '</span>'; }
  function widget(f, src, i, small) {
    var t = f[0];
    if (t === 'link') return '<a class="mw-wl" href="review-preview.html" target="_blank" rel="noopener" data-type="link">' + I.link + '<span class="mw-rn">' + esc(f[1]) + '</span><span class="meta">' + esc(f[2]) + ' · opens in a new tab</span>' + I.ext + '</a>';
    var body = TH[t] ? '<span class="mw-thumb">' + TH[t] + '</span>' : (f[3] && !(small && t === 'pr') ? kv(f[3].slice(0, 3)) : '');
    return btn('mw-wg', 'ov', '<span class="mw-wh2">' + (I[t] || I.file) + '<span class="mw-rn">' + esc(f[1]) + '</span></span>' + body + '<span class="meta">' + esc(f[2]) + '</span>', { 'data-src': src, 'data-i': i, 'data-type': t, 'data-small': small ? 1 : false, 'aria-label': 'Open a big preview of ' + KIND[t] + ' ' + f[1] });
  }
  function ovHTML() {
    if (!st.ov) return '';
    var L = files(st.ov.src), f = L[st.ov.i]; if (!f || f[0] === 'link') return '';
    var ids = L.map(function (x, i) { return i; }).filter(function (i) { return L[i][0] !== 'link'; }), at0 = ids.indexOf(st.ov.i), t = f[0], body, wid = st.ov.src === '*' ? WG[st.ov.i][0] : '';
    if (wid) body = wbig(wid);
    else if (t === 'file') body = '<div class="mw-doc"><p>This kind of file cannot be shown here. You can download it and open it on your computer.</p></div>';
    else if (t === 'html') body = '<iframe class="mw-ovframe" src="review-preview.html" title="' + esc(f[1]) + '"></iframe>';
    else if (TH[t]) body = '<div class="mw-ovpic">' + TH[t] + '</div>';
    else body = '<table class="mw-rx mw-ovtable"><caption class="sr-only">' + esc(f[1]) + '</caption><tbody>' + (f[3] || []).map(function (r) { return '<tr><th scope="row">' + esc(r[0]) + '</th><td>' + esc(r[1]) + '</td></tr>'; }).join('') + '</tbody></table>' + (t === 'pr' ? '<p class="meta">A pull request is the set of changes the helper asks to add. It goes in when all checks are green.</p>' : '');
    var one = ids.length < 2;
    return '<div class="mw-ovscrim" data-act="ovclose"></div><section class="mw-ovbox" role="dialog" aria-modal="true" aria-label="Preview of ' + esc(f[1]) + '"><header class="mw-ovh">' + (I[wid ? WI[wid] : t] || I.file) + '<h2>' + esc(f[1]) + '</h2><span class="meta">' + esc(f[2]) + (one ? '' : ' · ' + (at0 + 1) + ' of ' + ids.length) + '</span><span class="grow"></span>' + (one ? '' : btn('btn icon sm ghost', 'ovnav', I.prev, { 'data-d': -1, 'aria-label': 'Previous result' }) + btn('btn icon sm ghost', 'ovnav', I.next, { 'data-d': 1, 'aria-label': 'Next result' })) + btn('btn sm ghost', 'ovclose', I.x + '<span>Close</span>', { id: 'mw-ovx' }) + '</header><div class="mw-ovb" data-type="' + (wid === 'html' ? 'html' : t) + '">' + body + '</div></section>';
  }
  function ovStep(d) {
    var L = files(st.ov.src), ids = L.map(function (x, i) { return i; }).filter(function (i) { return L[i][0] !== 'link'; });
    st.ov.i = ids[(ids.indexOf(st.ov.i) + d + ids.length) % ids.length]; render(d < 0 ? '[data-act=ovnav][data-d="-1"]' : '[data-act=ovnav][data-d="1"]');
  }
  function shelf(s, withMk) {
    var h = '<aside class="mw-shelf" aria-label="Results"><div class="mw-sh"><h2>Results</h2>' + (withMk ? mk(10) : '') + '</div>';
    if (!s.files || !s.files.length) return h + '<p class="meta">Nothing yet. Pictures, pages and tables show up here.</p></aside>';
    var w = '', l = '';
    s.files.forEach(function (f, i) { if (f[0] === 'link') l += widget(f, s.k, i); else w += widget(f, s.k, i, true); });
    return h + '<div class="mw-res-list">' + w + '</div>' + (l ? '<div class="mw-links">' + l + '</div>' : '') + '</aside>';
  }

  /* ---------- pieces of a session ---------- */
  function steps(s) {
    if (!s.step) return '<span class="meta">No ticket</span>';
    var h = '<span class="mw-steps" role="img" aria-label="Step ' + s.step[0] + ' of ' + s.step[1] + '">';
    for (var i = 1; i <= s.step[1]; i++) h += '<i' + (i <= s.step[0] ? ' data-on="1"' : '') + '></i>';
    return h + '</span><span class="meta">Step ' + s.step[0] + ' of ' + s.step[1] + '</span>';
  }
  /* the question card already shows the question: its terminal lines and chat message stay out while it is open */
  function shown(s) { return s.q && s.qn ? s.lines.slice(0, -s.qn) : s.lines; }
  function screenText(s) {
    var l = shown(s).slice(), t = s.typed || '';
    if (!live(s)) return l.join('\n');
    if (s.kind === 'shell') l[l.length - 1] = l[l.length - 1] + ' ' + t; else l.push('> ' + t);
    return l.join('\n');
  }
  function peekText(s) { return shown(s).filter(function (x) { return x.trim(); }).slice(-3).join('\n'); }
  function qHTML(s, quiet) {
    return '<div class="mw-q" role="group" aria-label="Question from the helper"><p class="mw-qt">' + esc(s.q.t) + '</p><p class="meta">' + esc(s.q.why) + '</p><div class="mw-ans">' + btn('btn ' + (quiet ? 'outline' : 'primary'), 'answer', esc(s.q.a[0]), { 'data-k': s.k, 'data-a': 0 }) + btn('btn outline', 'answer', esc(s.q.a[1]), { 'data-k': s.k, 'data-a': 1 }) + '</div></div>';
  }
  function chatMsgs(s) {
    return s.chat.filter(function (m) { return !(s.q && m[3]); }).map(function (m, i) {
      if (m[0] === 'e') return '<p class="mw-ev meta"><span aria-hidden="true">✓</span> ' + esc(m[1]) + ' · ' + esc(m[2]) + '</p>';
      var f = m[4] !== undefined && s.files && s.files[m[4]] && m[1].indexOf('picture') + m[1].indexOf('pull request') > -2 ? s.files[m[4]] : null;
      var sent = (m[5] || []).map(function (x) { return '<div class="mw-inmsg">' + widget(s.sent[x], 'sent:' + s.k, x, true) + '</div>'; }).join('');
      return '<div class="mw-msg" data-w="' + m[0] + '"><span class="meta">' + (m[0] === 'y' ? 'You' : 'Helper') + ' · ' + esc(m[2]) + '</span>' + (m[1] ? '<p>' + esc(m[1]) + '</p>' : '') + (f ? '<div class="mw-inmsg">' + widget(f, s.k, m[4], true) + '</div>' : '') + (sent ? '<div class="mw-sent">' + sent + '</div>' : '') + '</div>';
    }).join('');
  }
  function attHTML(s) {
    if (!s.att || !s.att.length) return '';
    return '<div class="mw-atts" role="group" aria-label="Attached, not sent yet">' + s.att.map(function (f, i) {
      return '<span class="mw-att">' + btn('mw-attb', 'ov', (f[0] === 'img' ? '<span class="mw-thumb">' + TH.img + '</span>' : (I[f[0]] || I.file)) + '<span class="mw-rn">' + esc(f[1]) + '</span><span class="meta">' + esc(f[2]) + '</span>', { 'data-src': 'att:' + s.k, 'data-i': i, 'aria-label': 'Open a big preview of ' + f[1] }) + btn('btn icon xs ghost', 'attx', I.x, { 'data-k': s.k, 'data-i': i, 'aria-label': 'Remove ' + f[1] }) + '</span>';
    }).join('') + '</div>';
  }
  function chatHTML(s, prim, withMk) {
    var id = 'mw-i' + (++uid), rec = st.voice === 'rec' && st.vk === s.k, done = st.voice === 'done' && st.vk === s.k;
    var h = '<div class="mw-chat" data-chat="' + esc(s.k) + '" role="log" aria-label="Messages and ticket events">' + chatMsgs(s) + '</div><form class="mw-comp" data-k="' + esc(s.k) + '" data-f="chat">' + attHTML(s);
    if (rec) h += '<div class="mw-voice" role="status"><span class="mw-level" aria-hidden="true">' + WAV + '</span><span>Listening <span data-vt="1">0:04</span></span><span class="grow"></span>' + btn('btn outline sm', 'voice', I.stop + '<span>Stop</span>', { 'data-k': s.k, 'data-v': 'done' }) + btn('btn sm ghost', 'voice', 'Cancel', { 'data-k': s.k, 'data-v': '' }) + '</div>';
    h += '<div class="mw-crow">' + btn('btn icon ghost', 'attach', I.clip, { 'data-k': s.k, 'aria-label': 'Attach files', title: 'Attach files. You can also paste a screenshot or drop files here, up to 25 MB each.' }) + '<label class="sr-only" for="' + id + '">Message to the helper on ' + esc(s.k) + '</label><input class="input" id="' + id + '" data-d="c:' + esc(s.k) + '" value="' + esc(drafts['c:' + s.k] || '') + '" placeholder="Message the helper" autocomplete="off">' + (rec ? '' : btn('btn icon ghost', 'voice', I.mic, { 'data-k': s.k, 'data-v': 'rec', 'aria-label': 'Speak', title: 'Speak instead of typing' })) + (withMk ? mk(13) : '') + '<button class="btn ' + (prim ? 'primary' : 'outline') + '" type="submit">Send</button></div>';
    if (done) h += '<p class="meta mw-vhint">From your voice. Check the words, change what is wrong, then send.</p>';
    return h + '</form>';
  }
  function termHTML(s) {
    return '<div class="mw-term"><div class="mw-tbar"><span class="meta">Terminal · click and type · select text to copy it</span>' + btn('btn xs ghost', 'copyterm', 'Copy', { 'data-k': s.k }) + '</div><pre class="mw-screen" data-screen="' + esc(s.k) + '" tabindex="0" role="textbox" aria-multiline="true" aria-label="Terminal of ' + esc(s.k) + '. Type here, Enter sends the line.">' + esc(screenText(s)) + '</pre></div>';
  }
  function histHTML(s) {
    return '<div class="mw-old"><h3>Earlier sessions</h3><ul>' + HIST.map(function (x, i) {
      return '<li><span class="mw-hd">' + x[0] + '</span><span class="meta">reached ' + x[1] + '</span><span class="mw-hs">' + x[2] + '</span>' + btn('btn outline sm', 'reopen', 'Reopen', { 'data-k': s.k, 'data-i': i, 'aria-label': 'Reopen the session from ' + x[0] }) + '</li>';
    }).join('') + '</ul><p class="meta">orch keeps the last 10 sessions of this ticket on this computer.</p></div>';
  }
  function startHTML(s, withMk) {
    var on = live(s);
    var h = '<div class="mw-start"><h2>' + (on ? 'This session and earlier ones' : 'Start a helper on this ' + (s.kind === 'ticket' ? 'ticket' : 'session')) + (withMk ? mk(4) : '') + '</h2>';
    h += '<p class="meta">A start uses 1 of ' + max() + ' helper places. If all are in use it waits in line. Now ' + used() + ' of ' + max() + ' are in use.</p>';
    if (on) h += '<p class="mw-warn"><span aria-hidden="true">!</span> Changing the session interrupts the work in progress.</p>';
    h += '<div class="mw-choices">';
    if (on) h += '<div class="mw-choice"><h3>Keep going</h3><p class="meta">Nothing changes. The helper keeps its conversation.</p>' + btn('btn outline', 'askoff', 'Keep going') + '</div>';
    else h += '<div class="mw-choice"><h3>Continue where it stopped</h3><p class="meta">Keeps the last conversation' + (s.last ? ' from ' + esc(s.last) : '') + '. Best when the work is half done.</p>' + btn('btn outline', 'start', 'Continue', { 'data-how': 'continue', 'data-k': s.k }) + '</div>';
    h += '<div class="mw-choice"><h3>Fresh start</h3><p class="meta">The helper reads the ticket again. The earlier talk is not used. Best when it went off track.</p>' + pickHTML() + btn('btn outline', 'start', 'Start again', { 'data-how': 'clean', 'data-k': s.k, 'aria-label': 'Fresh start on ' + s.k }) + '</div></div>';
    return h + histHTML(s) + '</div>';
  }
  function seg(term, withMk) {
    return '<span class="mw-view"><span class="segmented" role="group" aria-label="View">' + btn('btn sm', 'view', 'Chat', { 'data-v': 'chat', 'aria-pressed': String(!term) }) + btn('btn sm', 'view', 'Terminal', { 'data-v': 'term', 'aria-pressed': String(!!term) }) + '</span>' + (withMk ? mk(5) : '') + '</span>';
  }
  function pinBtn(s) { return btn('btn icon sm ghost', 'pin', I.pin, { 'data-k': s.k, 'aria-pressed': String(!!s.pin), 'aria-label': (s.pin ? 'Unpin ' : 'Pin ') + s.k }); }
  function besideBtn(s) { return live(s) ? btn('btn icon sm ghost mw-nophone', 'beside', I.beside, { 'data-k': s.k, 'aria-label': 'Open ' + s.k + ' beside what is open in Focus' }) : ''; }
  function tkLink(s) { return s.kind === 'ticket' ? btn('mw-tkl', 'ticket', 'Open ticket', { 'data-k': s.k, 'aria-label': 'Open ticket ' + s.k }) : ''; }
  function pane(k, size, o) {
    o = o || {};
    var s = by(k), asking = s.s === 'none' || (o.main && st.ask), term = s.kind === 'shell' || st.term, id = 'mw-i' + (++uid);
    var segOk = s.kind !== 'shell' && !asking && s.s !== 'queue', qOut = size === 'md' && s.q && !asking;
    var h = '<section class="mw-pane" data-size="' + size + '" data-s="' + s.s + '" data-k="' + esc(s.k) + '"' + (o.main ? ' data-on="1"' : '') + ' aria-label="' + esc(s.k + ', ' + nm(s)) + '"><header class="mw-ph">' + (o.pre || '') + stat(s, !!o.narrow) + '<span class="mw-key">' + esc(s.k) + '</span>';
    if (o.main && st.ren === s.k) h += '<form class="mw-ren" data-f="ren" data-k="' + esc(s.k) + '"><label class="sr-only" for="' + id + '">Name of this session</label><input class="input" id="' + id + '" value="' + esc(nm(s)) + '" maxlength="60" autocomplete="off"><button class="btn outline sm" type="submit">Save name</button></form>';
    else if (o.main) h += btn('mw-pt truncate', 'ren', esc(nm(s)), { 'data-k': s.k, title: 'Click to rename', 'aria-label': 'Rename ' + nm(s) }) + (o.mk ? mk(9) : '');
    else if (o.sel) h += btn('mw-pt truncate', 'act', esc(nm(s)), { 'data-k': s.k, 'aria-label': 'Select the pane of ' + s.k });
    else h += '<span class="mw-pt truncate">' + esc(nm(s)) + '</span>';
    if (!o.compact && segOk && size === 'lg') h += seg(term, o.mk);
    h += o.ctl ? ctlHTML(s, o) : (o.tools || '');
    ['place', 'model', 'more'].forEach(function (kd) { if (pmOpen(s.k, kd)) h += paneMenu(s, kd, o); });
    var r2 = o.compact ? '' : (segOk && size !== 'lg' ? seg(term, false) : '') + (o.tools2 || '') + (size === 'sm' ? '' : mdlBtn(s, o.main) + meta(s, true) + (o.mk ? mk(12) : '') + tkLink(s));
    if (r2) h += '<span class="mw-prow">' + r2 + '</span>';
    h += '</header><div class="mw-pb">' + (qOut ? '<div class="mw-qwrap">' + qHTML(s, o.quiet) + '</div>' : '') + '<div class="mw-pmain">';
    if (asking) h += startHTML(s, o.mk);
    else if (s.s === 'queue') h += '<div class="mw-start"><h2>In line</h2><p class="meta">All ' + max() + ' helper places are in use. This one starts by itself when a place is free. Idle helpers close after about an hour.</p></div>';
    else h += (s.q && !qOut ? qHTML(s, o.quiet) : '') + (term ? termHTML(s) : chatHTML(s, o.prim && !s.q, o.mk));
    h += '</div>' + (size === 'sm' || o.noshelf ? '' : shelf(s, o.mk)) + '</div></section>';
    return h;
  }
  function pmOpen(k, kind) { return st.pm === k + '|' + kind; }
  function pmBtn(s, kind, icon, label) { return btn('btn icon sm ghost', 'pm', icon, { 'data-k': s.k, 'data-kind': kind, 'aria-expanded': String(pmOpen(s.k, kind)), 'aria-label': label, title: label }); }
  function paneMenu(s, kind, o) {
    var it = function (act, label, x) { x = x || {}; x['data-k'] = s.k; return btn('mw-opt', act, label, x); }, m = eff(), segOk = s.kind !== 'shell' && live(s) && s.s !== 'queue';
    var place = it('mode', I.bottom + '<span>At the bottom</span>', { 'data-m': 'bottom', 'aria-pressed': String(m === 'bottom') }) + '<span class="mw-nophone">' + it('mode', I.right + '<span>On the right</span>', { 'data-m': 'right', 'aria-pressed': String(m === 'right') }) + '</span>' + it('full', I.full + '<span>Full screen</span>', { 'aria-pressed': String(m === 'full') });
    if (kind === 'place') return '<div class="mw-pmenu" role="group" aria-label="Where Focus sits"><p class="mw-poph">Where Focus sits</p>' + place + '</div>';
    if (kind === 'model') return '<div class="mw-pmenu" role="group" aria-label="Model"><p class="mw-poph">' + TOOL[s.tool || 't1'] + ': model</p>' + MODELS[s.tool || 't1'].map(function (x) { return it('smodel', x + (x === mdl(s) ? ' (now)' : ''), { 'data-v': x, 'aria-pressed': String((s.next || mdl(s)) === x) }); }).join('') + '<p class="meta">A new model applies when the helper finishes its current step (or at its next start).</p></div>';
    return '<div class="mw-pmenu" role="group" aria-label="More for ' + esc(s.k) + '">' + (segOk ? it('view', st.term ? 'Show chat' : 'Show terminal', { 'data-v': st.term ? 'chat' : 'term' }) : '') + (s.kind !== 'shell' ? it('ask', 'History') + it('pm', 'Model: ' + mdl(s), { 'data-kind': 'model' }) : '') + (o.narrow ? it('pin', s.pin ? 'Unpin' : 'Pin') + place : '') + (s.kind === 'ticket' ? it('ticket', 'Open ticket') : '') + '</div>';
  }
  function ctlHTML(s, o) {
    var h = '<span class="mw-ctl">';
    if (!o.narrow) h += pinBtn(s);
    h += btn('btn icon sm ghost mw-nophone', 'addpane', I.plus, { disabled: o.n >= 3 ? 'disabled' : false, 'aria-label': 'Add a session beside this one', title: o.n >= 3 ? 'Three sessions is the most' : 'Add a session beside this one' });
    if (!o.narrow) h += pmBtn(s, 'place', I[eff() === 'right' ? 'right' : 'bottom'], 'Where Focus sits');
    h += btn('btn icon sm ghost', 'min', I.down, { 'aria-label': 'Minimise to the bar', title: 'Minimise to the bar' });
    h += btn('btn icon sm ghost', 'closepane', I.x, { 'data-k': s.k, 'aria-label': o.n > 1 ? 'Close this pane' : 'Close Focus', title: o.n > 1 ? 'Close this pane' : 'Close Focus (the bar stays)' });
    if (o.compact) h += pmBtn(s, 'more', I.more, 'More for ' + s.k);
    return h + '</span>';
  }
  function mdlBtn(s, can) {
    if (s.kind === 'shell') return tool(s);
    var t = I[s.tool || 't1'] + tlabel(s) + (s.next && s.next !== mdl(s) ? ' → ' + s.next + ' after this step' : '');
    return can ? btn('mw-mdl', 'pm', t, { 'data-k': s.k, 'data-kind': 'model', 'aria-expanded': String(pmOpen(s.k, 'model')), title: 'See or change the model' }) : '<span class="mw-tool">' + t + '</span>';
  }
  function histBtn(s) { return s.kind !== 'shell' ? btn('btn sm ghost', st.ask ? 'askoff' : 'ask', 'History', { 'aria-pressed': String(!!st.ask && live(s)) }) : ''; }
  function paneTools(s) { return pinBtn(s); }

  /* ---------- Focus page: the wall in bands, and zoom ---------- */
  function tileActs(s) { return '<span class="grow"></span>' + tkLink(s) + (s.s === 'none' ? btn('btn outline sm', 'zoom', 'Start', { 'data-k': s.k }) : '') + pinBtn(s) + besideBtn(s); }
  function openB(s, cls, inner) { return btn(cls, 'zoom', inner, { 'data-k': s.k, 'aria-label': 'Open ' + s.k + ', ' + nm(s) + ', ' + word(s) }); }
  function tile(s) {
    return '<article class="mw-tile mw-work" data-tile="' + esc(s.k) + '" data-s="' + s.s + '">' + openB(s, 'mw-topen', '<span class="mw-thead">' + stat(s) + '<span class="mw-key">' + esc(s.k) + '</span></span><span class="mw-tt">' + esc(nm(s)) + '</span><span class="mw-now" data-now="' + esc(s.k) + '">' + esc(now(s)) + '</span>' + (live(s) ? '<span class="mw-peek" data-peek="' + esc(s.k) + '" aria-hidden="true">' + esc(peekText(s)) + '</span>' : '')) + meta(s) + '<footer class="mw-tfoot">' + steps(s) + tileActs(s) + '</footer></article>';
  }
  function line(s) {
    return '<div class="mw-line" data-tile="' + esc(s.k) + '" data-s="' + s.s + '">' + openB(s, 'mw-lopen', stat(s) + '<span class="mw-key">' + esc(s.k) + '</span><span class="mw-tt">' + esc(nm(s)) + '</span><span class="mw-lnow" data-now="' + esc(s.k) + '">' + esc(now(s)) + '</span>') + '<span class="mw-lmeta meta">' + tool(s) + '<span>' + warm(s) + '</span></span>' + tkLink(s) + (s.s === 'none' ? btn('btn outline sm', 'zoom', 'Start', { 'data-k': s.k }) : '') + pinBtn(s) + '</div>';
  }
  function band(id, title, list, draw, cls, empty, extra) {
    var col = !!st.col[id];
    return '<section class="mw-band" data-band="' + id + '"><div class="mw-bh"><h2>' + btn('mw-bt', 'col', '<span class="mw-chev" aria-hidden="true">' + (col ? '▸' : '▾') + '</span>' + title + ' (' + list.length + ')', { 'data-id': id, 'aria-expanded': String(!col) }) + '</h2>' + (extra || '') + '</div>' + (col ? '' : (list.length ? '<div class="' + cls + '">' + list.map(draw).join('') + '</div>' : '<p class="meta mw-none">' + empty + '</p>')) + '</section>';
  }
  function bandsHTML() {
    var f = st.f.trim().toLowerCase(), all = sorted().filter(function (s) { return !f || (s.k + ' ' + nm(s) + ' ' + word(s)).toLowerCase().indexOf(f) >= 0; });
    var pin = all.filter(function (s) { return s.pin; }), rest = all.filter(function (s) { return !s.pin; });
    var act = rest.filter(function (s) { return s.s === 'wait' || grp(s) === 'run'; }), inl = rest.filter(function (s) { return s.s !== 'wait' && grp(s) === 'queue'; }), idle = rest.filter(function (s) { return s.s !== 'wait' && grp(s) === 'idle'; });
    if (f && !all.length) return '<p class="meta mw-none">No session matches "' + esc(st.f) + '".</p>';
    return (pin.length || !f ? band('pin', 'Pinned', pin, tile, 'mw-works', 'Nothing is pinned. Pin a session to keep it here.', mk(9)) : '') + band('run', 'Needs you and working', act, tile, 'mw-works', 'No helper is working on a ticket.', mk(2)) + (inl.length ? band('queue', 'In line', inl, line, 'mw-lines', '') : '') + band('idle', 'Idle and no session', idle, line, 'mw-lines', 'Every ticket has a working helper.');
  }
  function wallHTML() {
    var c = { wait: 0, run: 0, queue: 0, idle: 0 };
    S.forEach(function (s) { c[s.s === 'wait' ? 'wait' : grp(s)]++; });
    var part = function (n, g, w) { return n ? '<span class="mw-st" data-s="' + g + '"><span class="mw-sym" aria-hidden="true">' + ST[g][0] + '</span>' + n + ' ' + w + '</span>' : ''; };
    var h = '<div class="mw-wall"><header class="mw-wh"><div><div class="mw-h1"><h1>Live</h1>' + mk(1) + '</div><p class="mw-hero" role="status">' + (c.wait ? part(c.wait, 'wait', c.wait === 1 ? 'needs you' : 'need you') : '<span class="mw-st">Nobody needs you</span>') + part(c.run, 'run', 'working') + part(c.queue, 'queue', 'in line') + part(c.idle, 'idle', 'idle') + '</p><p class="meta">' + S.length + ' sessions · ' + used() + ' of ' + max() + ' helper places in use</p></div>';
    h += '<div class="mw-new" role="group" aria-label="New session without a ticket">' + mk(6) + NEW.map(function (o) { return btn('btn outline sm', 'new', (has(o[0]) ? '' : '<span aria-hidden="true">+</span> ') + o[0], { 'data-k': o[0], title: has(o[0]) ? 'Already open: go to it' : o[1] }); }).join('') + '</div></header>';
    h += pickHTML();
    h += '<div class="mw-tools"><label class="sr-only" for="mw-filter">Filter sessions</label><input class="input" id="mw-filter" type="search" placeholder="Filter by name, ticket or status" value="' + esc(st.f) + '" autocomplete="off">' + mk(11) + '</div>';
    return h + '<div id="mw-bands" class="mw-bands"' + (st.many ? ' data-many="1"' : '') + '>' + bandsHTML() + '</div></div>';
  }
  function zoomHTML() {
    var s = by(st.cur);
    var tools = histBtn(s) + paneTools(s) + '<span class="mw-view">' + mk(8) + btn('btn icon sm ghost', 'full', I.full, { 'aria-label': 'Full screen' }) + '</span>';
    return '<div class="mw-zoom"><h1 class="sr-only">Focus: ' + esc(s.k) + '</h1>' + pane(s.k, 'lg', { main: true, prim: true, mk: true, pre: btn('btn sm ghost', 'back', I.back + '<span>Wall</span>'), tools: tools }) + '</div>';
  }

  /* ---------- mock pages ---------- */
  function verb(s) { return { wait: 'Answer', run: 'Watch', idle: 'Open', none: 'Start', queue: 'In line', open: 'Open' }[s.s]; }
  function fbtn(s, long) { return btn('btn outline sm', 'focus', verb(s) + (long ? ' in Focus' : ''), { 'data-k': s.k, 'aria-label': verb(s) + ' ' + s.k + ' in Focus' }); }
  function row(s) { return '<div class="mw-row">' + stat(s) + '<span class="mw-key">' + esc(s.k) + '</span>' + btn('mw-rt', 'ticket', esc(s.t), { 'data-k': s.k }) + fbtn(s) + '</div>'; }
  function tks() { return S.filter(function (s) { return s.kind === 'ticket'; }); }
  var SAMPLES = [['img', 'home-390.png', 'Picture · 14:39'], ['html', 'phone-widths.html', 'Page · before and after'], ['table', 'widths.csv', 'Table · 3 rows', [['1280', 'fits'], ['1920', 'fits'], ['390', 'fits']]], ['chart', 'Usage by day', 'Chart · 14 days'], ['pr', 'Pull request 1318', 'Draft · 3 of 12 checks green', [['State', 'Draft'], ['Checks', '3 of 12 green'], ['Changes', '6 files']]], ['link', 'Notes on phone widths', 'Link · team wiki']];
  var PG = {
    home: function () {
      var need = tks().filter(function (s) { return s.s === 'wait'; }), work = tks().filter(function (s) { return s.s === 'run'; }).slice(0, 5);
      return '<div class="mw-pg"><h1>Home</h1><p class="meta">The Focus bar stays under every page. Open a session from it, type a line, then change page: it is still there.</p><section class="card pad"><h2>Needs you</h2>' + (need.length ? need.map(row).join('') : '<p class="meta">Nothing needs you right now.</p>') + '</section><section class="card pad"><h2>Working now</h2>' + work.map(row).join('') + '</section></div>';
    },
    tickets: function () {
      return '<div class="mw-pg"><div class="mw-h1"><h1>Tickets</h1>' + mk(3) + '</div><p class="meta">Click a title to open the ticket. The button opens its helper in Focus.</p><section class="card pad" aria-label="All tickets">' + tks().map(row).join('') + '</section></div>';
    },
    ticket: function () {
      var s = by(st.tk), names = ['Read the ticket', 'Sketch the change', 'Build it', 'Test it at three widths', 'Open the pull request', 'Get it merged'];
      var h = '<div class="mw-pg"><p class="meta">' + btn('mw-tkl', 'page', '‹ All tickets', { 'data-p': 'tickets' }) + '</p><div class="mw-h1"><h1>' + esc(s.t) + '</h1>' + mk(3) + '</div><p class="mw-thead mw-tkhead">' + stat(s) + '<span class="mw-key">' + esc(s.k) + '</span>' + meta(s) + '</p><div class="mw-two"><section class="card pad"><h2>Steps</h2><ol class="mw-cl">';
      for (var i = 1; i <= s.step[1]; i++) h += '<li' + (i <= s.step[0] ? ' data-on="1"' : '') + '><span aria-hidden="true">' + (i <= s.step[0] ? '✓' : '○') + '</span> ' + names[i - 1] + (i <= s.step[0] ? '<span class="sr-only"> (done)</span>' : '') + '</li>';
      h += '</ol><div class="mw-ans">' + fbtn(s, true) + '</div></section><section class="card pad"><h2>Results</h2><p class="meta">The same widgets as in Focus.</p><div class="mw-res-list">' + (s.files || []).map(function (f, i) { return f[0] === 'link' ? '' : widget(f, s.k, i, true); }).join('') + '</div><div class="mw-links">' + (s.files || []).map(function (f, i) { return f[0] === 'link' ? widget(f, s.k, i) : ''; }).join('') + '</div></section></div><section class="card pad">' + histHTML(s) + '</section></div>';
      return h;
    },
    review: function () {
      return '<div class="mw-pg"><h1>Review</h1><p class="meta">Results that wait for your look. Focus stays open while you check them.</p><section class="card pad mw-rev"><span class="mw-thumb">' + TH.img + '</span><div><h2>Steer a helper from the dashboard</h2><p class="meta">ORCH-247 · merged on all tests passed · 1 picture, 1 pull request</p><div class="mw-ans">' + btn('btn outline sm', 'focus', 'Open in Focus', { 'data-k': 'ORCH-247' }) + '</div></div></section><section class="card pad mw-rev"><span class="mw-thumb">' + TH.html + '</span><div><h2>Newsletter draft</h2><p class="meta">A page to read · no helper is running</p><div class="mw-ans"><a class="btn outline sm" href="newsletter-preview.html" target="_blank" rel="noopener">Open page</a></div></div></section></div>';
    },
    widgets: function () {
      var n = WG.filter(function (w) { return picks['w:' + w[0]]; }).length;
      var h = '<div class="mw-pg mw-wpage"><div class="mw-h1"><h1>Widgets</h1>' + mk(10) + '</div><p>Proposal: result widgets. One real example of each kind of result a helper can hand back: small as it sits beside a session or on a ticket, big when you click it.</p><p class="meta">They would live in the style guide and be reusable on ticket pages too, not only in Focus. <span role="status">' + n + ' of ' + WG.length + ' picked</span></p><div class="mw-wtable">';
      WG.forEach(function (w, i) {
        var id = w[0], small = id === 'link' ? '<a class="mw-wl" href="review-preview.html" target="_blank" rel="noopener">' + I.link + '<span class="mw-rn">' + esc(w[3]) + '</span><span class="meta">' + esc(w[4]) + ' · opens in a new tab</span>' + I.ext + '</a>' : btn('mw-wg', 'ov', '<span class="mw-wh2">' + (I[WI[id]] || I.file) + '<span class="mw-rn">' + esc(w[3]) + '</span></span>' + wsmall(id) + '<span class="meta">' + esc(w[4]) + '</span>', { 'data-src': '*', 'data-i': i, 'data-type': id, 'aria-label': 'Open the big preview of ' + w[3] });
        h += '<section class="mw-wrow" aria-label="' + esc(w[1]) + '"><div class="mw-wtype"><h2>' + esc(w[1]) + '</h2><span class="mw-key">' + esc(w[2]) + '</span><span class="chip' + (w[7] === 'yes' ? ' success' : (w[7] === 'new' ? ' info' : '')) + '">' + WHAVE[w[7]] + '</span></div><div class="mw-wsmall"><span class="mw-bl">Small: ' + esc(w[5].charAt(0).toLowerCase() + w[5].slice(1)) + '</span>' + small + '</div><div class="mw-wbig"><span class="mw-bl">Big preview</span><p>' + esc(w[6]) + '</p></div><div class="mw-wpick"><span class="segmented" role="group" aria-label="Your pick for ' + esc(w[1]) + '">';
        ['Keep', 'Maybe', 'Drop'].forEach(function (p) { h += btn('btn sm', 'pick', p, { 'data-n': 'w:' + id, 'data-p': p.toLowerCase(), 'aria-pressed': String(picks['w:' + id] === p.toLowerCase()) }); });
        h += '</span></div></section>';
      });
      return h + '</div><p class="meta">' + btn('mw-tkl', 'page', '‹ Back to Focus', { 'data-p': 'focus' }) + '</p></div>';
    }
  };

  /* ---------- the layer: bar on every page, a panel (bottom, right, full) split in up to 3, or closed to the side ---------- */
  function inList(o, l) { var w = o.s === 'wait'; return l === 'wait' ? w : (l === 'pin' ? !!o.pin && !w : (!w && !o.pin && (l === 'more' || grp(o) === l))); }
  var LIST = { wait: ['◆', 'need you', 'Needs you'], pin: ['', 'pinned', 'Pinned'], run: GRP.run, queue: GRP.queue, idle: GRP.idle, more: ['', 'more', 'More sessions'] };
  function chip(o) {
    var on = shownIn(o);
    return btn('mw-swb', 'switch', stat(o, true) + '<span class="mw-cn">' + esc(o.name || o.k) + '</span>', { 'data-k': o.k, 'data-s': o.s, 'aria-pressed': String(on), title: nm(o) });
  }
  function cnt(l, compact) {
    var n = sorted().filter(function (o) { return inList(o, l); }).length; if (!n) return '';
    var sym = l === 'pin' ? I.pin : (l === 'more' ? I.more : '<span class="mw-st" data-s="' + l + '"><span class="mw-sym" aria-hidden="true">' + LIST[l][0] + '</span></span>');
    var text = compact ? sym + n : (l === 'pin' ? sym + 'Pinned (' + n + ')' : (l === 'more' ? 'More (' + n + ')' : n + ' ' + LIST[l][1])) + I.up;
    return btn('mw-swb mw-grp', 'list', text, { 'data-l': l, 'aria-expanded': String(st.list === l), 'aria-label': compact ? n + ' ' + LIST[l][1] : null });
  }
  function chipsHTML() {
    var all = sorted(), need = all.filter(function (o) { return o.s === 'wait'; }), pin = all.filter(function (o) { return inList(o, 'pin'); }), open = all.filter(function (o) { return shownIn(o) && o.s !== 'wait' && !o.pin; });
    var grpH = function (g, label, list) { return '<span class="mw-bg" role="group" data-g="' + g + '" aria-label="' + (g === 'pin' ? 'Pinned' : label) + '"><span class="mw-bl">' + label + '</span>' + list.map(chip).join('') + '</span>'; };
    if (BL >= 3) return ['wait', 'pin', 'run', 'queue', 'idle'].map(function (l) { return cnt(l, true); }).join('') + mk(11);
    var h = grpH('wait', need.length ? 'Needs you' : 'All calm', need);
    if (pin.length) h += BL >= 1 ? cnt('pin') : grpH('pin', I.pin, pin);
    if (open.length && BL < 2) h += grpH('open', 'Open', open);
    return h + (BL >= 2 ? cnt('more') : cnt('run') + cnt('queue') + cnt('idle')) + mk(11);
  }
  function listRows() {
    var q = st.lq.trim().toLowerCase(), l = sorted().filter(function (o) { return inList(o, st.list) && (!q || (o.k + ' ' + nm(o)).toLowerCase().indexOf(q) >= 0); });
    return l.length ? l.map(function (o) { return btn('mw-opt mw-lrow', 'switch', stat(o) + '<span class="mw-key">' + esc(o.k) + '</span><span class="mw-rn">' + esc(nm(o)) + '</span><span class="meta">' + esc(tlabel(o)) + '</span>', { 'data-k': o.k }); }).join('') : '<p class="meta">No session matches.</p>';
  }
  function popHTML(mode) {
    if (st.menu === 'new') return '<div class="mw-pop" role="group" aria-label="New session without a ticket"><p class="mw-poph">New session without a ticket</p>' + pickHTML() + '<div class="mw-plist">' + NEW.map(function (o) { return btn('mw-opt', 'new', '<strong>' + o[0] + '</strong><span class="meta">' + (has(o[0]) ? 'Already open: go to it' : o[1]) + '</span>', { 'data-k': o[0] }); }).join('') + '</div><p class="meta">' + used() + ' of ' + max() + ' helper places in use</p></div>';
    if (st.menu === 'pos') {
      var po = function (act, m, icon, label, on, cls) { return btn('mw-opt mw-posopt' + (cls || ''), act, icon + '<span>' + label + '</span>', { 'data-m': m, 'aria-pressed': String(on) }); };
      return '<div class="mw-pop" role="group" aria-label="Where Focus sits"><p class="mw-poph">Where Focus sits</p><div class="mw-plist">' + po('mode', 'bottom', I.bottom, 'At the bottom', mode === 'bottom') + po('mode', 'right', I.right, 'On the right', mode === 'right', ' mw-nophone') + po('full', '', I.full, 'Full screen', false) + po('mode', 'bar', I.down, 'Bar only', mode === 'bar') + po('mode', 'side', I.side, 'Closed to the side', false) + '</div></div>';
    }
    if (st.list) {
      var n = sorted().filter(function (o) { return inList(o, st.list); }).length;
      return '<div class="mw-pop mw-pop-list" role="group" aria-label="' + LIST[st.list][2] + '"><p class="mw-poph">' + LIST[st.list][2] + ' (' + n + ')</p>' + (n >= 9 ? '<label class="sr-only" for="mw-lq">Search these sessions</label><input class="input" id="mw-lq" type="search" placeholder="Search these sessions" value="' + esc(st.lq) + '" autocomplete="off">' : '') + '<div class="mw-plist" id="mw-plist">' + listRows() + '</div></div>';
    }
    return '';
  }
  function barHTML(mode) {
    var full = mode === 'full', tiny = BL >= 3;
    var h = '<div class="mw-bar" role="group" aria-label="Focus bar" data-fold="' + BL + '">' + btn('mw-home', 'home', '<b>Live</b>', { title: 'Focus start page' }) + (full ? '' : mk(7));
    h += '<nav class="mw-sw" aria-label="Sessions">' + chipsHTML() + '</nav>';
    if (full) return h + popHTML(mode) + '<span class="meta mw-hint">Esc to leave</span>' + btn('btn icon sm ghost', 'full', I.exit, { 'aria-label': 'Leave full screen' }) + '</div>';
    h += btn('btn sm ghost', 'menu', I.plus + (tiny ? '' : '<span>New</span>'), { 'data-m': 'new', 'aria-expanded': String(st.menu === 'new'), 'aria-label': tiny ? 'New' : null, title: 'New session without a ticket' });
    if (zoomed()) return h + popHTML(mode) + '</div>';
    if (mode === 'bar') h += btn('btn sm ghost', 'mode', I.up + (tiny ? '' : '<span>Open</span>'), { 'data-m': phone() ? 'bottom' : st.last, 'aria-label': tiny ? 'Open' : null, title: 'Open Live where it was last' }) + btn('btn icon sm ghost mw-pos', 'menu', I[st.last === 'right' ? 'right' : 'bottom'], { 'data-m': 'pos', 'aria-expanded': String(st.menu === 'pos'), 'aria-label': 'Place' , title: 'Where Focus sits' });
    else { var pl = mode === 'right' ? 'Right' : 'Bottom'; h += btn('btn sm ghost mw-pos', 'menu', I[mode === 'right' ? 'right' : 'bottom'] + (tiny ? '' : '<span>' + pl + '</span>') + I.up, { 'data-m': 'pos', 'aria-expanded': String(st.menu === 'pos'), 'aria-label': tiny ? pl : null, title: 'Where Focus sits' }); }
    return h + popHTML(mode) + '</div>';
  }
  function layerHTML() {
    var mode = eff(), w = S.filter(function (x) { return x.s === 'wait'; }).length;
    if (mode === 'side') return btn('mw-edge', 'mode', '<span class="mw-edget">Live</span>' + (w ? '<span class="mw-cnt" data-s="wait"><span aria-hidden="true">◆</span> ' + w + '</span>' : ''), { 'data-m': st.last, 'aria-label': 'Open Live again. ' + (w ? w + ' waiting for you' : 'Nothing is waiting') });
    var panel = '', full = mode === 'full', n = st.panes.length;
    if (mode !== 'bar') panel = '<div class="mw-panel" data-mode="' + mode + '" data-n="' + n + '">' + st.panes.map(function (k, i) {
      var s = by(k), on = i === st.act, narrow = n > 1 && (mode === 'right' || phone() || (window.innerWidth - 240) / n < 480);
      return pane(k, full ? 'lg' : 'md', { main: on, sel: !on, ctl: true, compact: n > 1, narrow: narrow, n: n, noshelf: n > 1 || (full && window.innerWidth < 1600), tools2: on && n === 1 ? histBtn(s) : '', prim: on, quiet: !on });
    }).join('') + '</div>';
    return full ? barHTML(mode) + panel : panel + barHTML(mode);
  }

  /* ---------- features sheet ---------- */
  function sheetHTML() {
    var n = F.filter(function (f) { return picks[f[0]]; }).length;
    var h = '<header class="mw-shh"><div><h2>Features</h2><p class="meta" role="status">' + n + ' of ' + F.length + ' picked</p><label class="mw-marks"><input class="switch" type="checkbox" id="mw-marks"' + (st.marks ? ' checked' : '') + '><span>Show feature numbers</span></label></div>' + btn('btn icon sm ghost', 'sheet', I.x, { 'aria-label': 'Close features' }) + '</header><div class="mw-feats">';
    F.forEach(function (f) {
      h += '<article class="mw-feat" id="mw-f' + f[0] + '"' + (st.feat === f[0] ? ' data-on="1"' : '') + '><h3><span class="mw-mk" data-pick="' + (picks[f[0]] || '') + '" aria-hidden="true">' + f[0] + '</span>' + esc(f[1]) + '</h3><p>' + esc(f[2]) + '</p><p class="meta"><strong>In orch:</strong> ' + esc(f[3]) + '</p><p class="meta"><strong>New work:</strong> ' + f[4] + ', ' + esc(f[5]) + '.</p><div class="mw-frow"><span class="segmented" role="group" aria-label="Your pick for ' + esc(f[1]) + '">';
      ['Keep', 'Maybe', 'Drop'].forEach(function (p) { h += btn('btn sm', 'pick', p, { 'data-n': f[0], 'data-p': p.toLowerCase(), 'aria-pressed': String(picks[f[0]] === p.toLowerCase()) }); });
      h += '</span>' + btn('btn sm ghost', 'show', 'Show me', { 'data-n': f[0] }) + (f[7] ? btn('btn sm ghost', 'show', f[7][0], { 'data-n': f[0], 'data-more': 1 }) : '') + '</div></article>';
    });
    return h + '</div><footer class="mw-shf">' + btn('btn outline', 'copy', 'Copy my picks') + '<span class="meta" id="mw-copied" role="status"></span></footer>';
  }

  /* ---------- render ---------- */
  function syncPanes() {
    if (!has(st.cur)) st.cur = S[0].k;
    st.panes = st.panes.filter(has).filter(function (k, i, a) { return a.indexOf(k) === i; }).slice(0, 3);
    if (st.panes.indexOf(st.cur) < 0) { st.act = Math.max(0, Math.min(st.act, st.panes.length - 1)); st.panes[st.act] = st.cur; }
    var ord = sorted().map(function (o) { return o.k; }); /* panes sit in the same order as the chips in the bar */
    st.panes.sort(function (a, b) { return ord.indexOf(a) - ord.indexOf(b); });
    st.act = st.panes.indexOf(st.cur);
    if (st.pm && !has(st.pm.split('|')[0])) st.pm = '';
  }
  function render(focusSel) {
    uid = 0; syncPanes();
    var b = document.body, mode = eff();
    b.dataset.mwPage = st.page; b.dataset.mwView = st.page === 'focus' ? st.view : '';
    b.dataset.mwSheet = st.sheet ? '1' : ''; b.dataset.mwLayer = mode; b.dataset.mwSplit = mode === 'bar' || mode === 'side' ? '' : st.panes.length;
    $('mw-page').innerHTML = st.page === 'focus' ? (st.view === 'zoom' ? zoomHTML() : wallHTML()) : PG[st.page]();
    var L = $('mw-layer'), nav; L.dataset.mode = mode;
    /* the bar never wraps: beside the right dock and on phones it is symbols and counts; elsewhere it folds only as far as needed */
    BL = phone() || (mode === 'right' && window.innerWidth < 1700) ? 3 : 0; L.innerHTML = layerHTML();
    while (BL < 3 && (nav = q1('.mw-bar .mw-sw')) && nav.scrollWidth > nav.clientWidth + 1) { BL++; L.innerHTML = layerHTML(); }
    var sh = $('mw-sheet'); sh.innerHTML = sheetHTML(); sh.inert = !st.sheet; sh.setAttribute('aria-hidden', String(!st.sheet));
    var ov = $('mw-ov'), oh = ovHTML(); ov.innerHTML = oh; ov.hidden = !oh; if (!oh) st.ov = null;
    Array.prototype.forEach.call(b.children, function (c) { if (c !== ov && c !== sh && c.tagName !== 'SCRIPT') c.inert = !!oh; }); if (oh) sh.inert = true; /* the page behind a preview cannot be reached */
    $('mw-crumb').textContent = PAGES[st.page] + (st.page === 'ticket' ? ' › ' + st.tk : '');
    $('mw-fbtn').setAttribute('aria-expanded', String(st.sheet));
    $('mw-many').checked = st.many;
    document.querySelectorAll('.sidebar .nav-item[aria-label]').forEach(function (a) { var p = a.getAttribute('aria-label').toLowerCase(); if (PAGES[p]) { if (PAGES[p] === PAGES[st.page]) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current'); } });
    document.querySelectorAll('.mw-screen,.mw-chat').forEach(function (x) { x.scrollTop = x.scrollHeight; });
    /* a menu or list opens right above the button that opened it */
    var pop = q1('.mw-pop'), pb = pop && q1(st.menu ? '[data-act=menu][data-m="' + st.menu + '"]' : '[data-act=list][data-l="' + st.list + '"]');
    if (pb) { var bar = pop.parentNode, x = pb.getBoundingClientRect().left - bar.getBoundingClientRect().left; pop.style.left = Math.max(8, Math.min(x, bar.clientWidth - pop.offsetWidth - 8)) + 'px'; }
    url();
    if (oh && !focusSel) focusSel = '#mw-ovx';
    if (focusSel) { var t = document.querySelector(focusSel); if (t) t.focus(); }
  }
  function url() {
    var p = ['page=' + st.page];
    if (st.page === 'focus') p.push('view=' + st.view);
    if (st.page === 'ticket') p.push('tk=' + encodeURIComponent(st.tk));
    p.push('mode=' + (st.full ? 'full' : st.mode), 'cur=' + encodeURIComponent(st.panes[0]));
    if (st.panes.length > 1) { p.push('split=' + st.panes.length, 'cur2=' + encodeURIComponent(st.panes[1])); if (st.panes[2]) p.push('cur3=' + encodeURIComponent(st.panes[2])); if (st.act) p.push('act=' + (st.act + 1)); }
    if (st.term) p.push('term=1');
    if (st.ask) p.push('ask=1');
    if (st.ren) p.push('ren=1');
    if (st.many) p.push('many=1');
    if (st.list) p.push('list=' + st.list);
    if (st.menu) p.push('menu=' + st.menu);
    if (st.pm) p.push('pm=' + encodeURIComponent(st.pm.replace('|', ':')));
    if (st.nt !== 't1' || st.nm !== 'Sonnet') p.push('tool=' + st.nt, 'model=' + encodeURIComponent(st.nm));
    if ((by(st.cur).att || []).length) p.push('att=1');
    if (st.voice) p.push('voice=' + st.voice);
    if (st.f) p.push('q=' + encodeURIComponent(st.f));
    if (st.ov) p.push('res=' + encodeURIComponent(st.ov.src) + ':' + st.ov.i);
    if (st.marks) p.push('marks=1');
    if (st.sheet) p.push('sheet=' + (st.feat || 1));
    try { history.replaceState(null, '', '?' + p.join('&')); } catch (e) { /* file pages may refuse */ }
  }
  function refresh() {
    document.querySelectorAll('[data-screen]').forEach(function (el) {
      var near = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
      el.textContent = screenText(by(el.dataset.screen));
      if (near) el.scrollTop = el.scrollHeight;
    });
    document.querySelectorAll('[data-now]').forEach(function (el) { el.textContent = now(by(el.dataset.now)); });
    document.querySelectorAll('[data-peek]').forEach(function (el) { el.textContent = peekText(by(el.dataset.peek)); });
  }
  function refreshChat(k) {
    document.querySelectorAll('[data-chat]').forEach(function (el) { if (el.dataset.chat === k) { el.innerHTML = chatMsgs(by(k)); el.scrollTop = el.scrollHeight; } });
  }
  function say(t) { $('mw-live').textContent = t; }
  function push(s, line) {
    s.lines.push(line); if (s.lines.length > 60) s.lines.shift();
    if (/^⏺ (?!Bash\(|Read\()/.test(line)) s.now = line.slice(2);
  }
  /* motion: a thing grows or moves from where it was to where it is now (transform and opacity only; off with reduced motion) */
  function flip(el, from) {
    if (!el || !from || reduce || !el.animate) return;
    var to = el.getBoundingClientRect(); if (!to.width || !to.height || !from.width) return;
    var cs = getComputedStyle(document.documentElement);
    el.animate([{ transformOrigin: '0 0', transform: 'translate(' + (from.left - to.left) + 'px,' + (from.top - to.top) + 'px) scale(' + from.width / to.width + ',' + from.height / to.height + ')', opacity: 0.6 }, { transformOrigin: '0 0', transform: 'none', opacity: 1 }],
      { duration: parseFloat(cs.getPropertyValue('--dur-slow')) || 240, easing: (cs.getPropertyValue('--ease-move') || 'ease-out').trim() });
  }
  function q1(sel) { return document.querySelector(sel); }
  function rectOf(sel) { var e = q1(sel); return e ? e.getBoundingClientRect() : null; }
  function sel(k) { return '[data-tile="' + k + '"]'; }
  function clip(t, done) {
    var fb = function () { var a = document.createElement('textarea'); a.value = t; a.className = 'sr-only'; document.body.appendChild(a); a.select(); try { document.execCommand('copy'); } catch (e) { /* no clipboard */ } a.remove(); done(); };
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(t).then(done, fb); else fb();
  }

  /* ---------- actions ---------- */
  function zoom(k) {
    var from = rectOf(sel(k));
    st.cur = k; st.view = 'zoom'; st.page = 'focus'; st.full = false; st.ask = false; st.ren = ''; st.menu = ''; st.list = '';
    render('.mw-zoom [data-act=back]');
    flip(q1('.mw-zoom .mw-pane'), from);
  }
  function back() {
    var from = rectOf('.mw-zoom .mw-pane');
    st.view = 'wall'; st.full = false; st.ask = false; st.ren = '';
    render(sel(st.cur) + ' [data-act=zoom]');
    flip(q1(sel(st.cur)), from);
  }
  function openSess(k) {
    st.cur = k; st.ask = false; st.ren = ''; st.menu = ''; st.list = '';
    if (!zoomed() && (st.mode === 'bar' || st.mode === 'side')) st.mode = phone() ? 'bottom' : (st.last || 'bottom');
  }
  function answer(k, i) {
    var s = by(k); if (!s.q) return;
    var a = s.q.a[i];
    s.q = null; s.s = 'run';
    push(s, '> ' + (i + 1)); push(s, '⏺ ' + a + '. Going on with step ' + (s.step ? Math.min(s.step[1], s.step[0] + 1) : 2) + '.');
    s.chat.push(['y', a, 'now'], ['h', 'Thanks. I go on with the next step.', 'now']);
    s.feed = ['⏺ Bash(node --test tests/attach.test.js)', '  ⎿ ✔ all tests pass (22 ms)', '⏺ Writing a short note about the choice.'];
    say('Answer sent to ' + k + '. The helper is working again.');
    render(sel(k) + ' [data-act=zoom],.mw-pane[data-k="' + k + '"] input');
  }
  function begin(s, lines, ev) {
    var was = live(s);
    lines.forEach(function (l) { push(s, l); });
    s.chat.push(['e', ev, 'now']); s.q = null; s.sl = ''; s.up = 0;
    if (!was && s.kind !== 'shell' && used() >= max()) { s.s = 'queue'; s.now = 'Waits in line for a free helper place.'; say(s.k + ' waits in line for a free helper place.'); }
    else { s.s = 'run'; s.feed = ['⏺ Read(ticket notes)', '⏺ Planning the next step.', '⏺ Working on the next step.']; say('Helper started on ' + s.k + '.'); }
    st.ask = false;
    render('.mw-pane[data-k="' + s.k + '"] input');
  }
  function start(k, how) {
    var s = by(k);
    if (how === 'clean') { s.lines = []; if (s.kind !== 'shell') { s.tool = st.nt; s.model = st.nm; s.next = ''; } begin(s, ['⏺ Fresh start.', '⏺ Reading the ticket and its files.'], 'Fresh start: the helper reads the ticket again'); }
    else begin(s, ['', '⏺ Resuming the last conversation.', '⏺ Picking up where it stopped.'], 'Continued the last conversation');
  }
  function create(k) {
    var T = { 'Manager': ['Looks after the helpers', 'Ready.', '⏺ Looking at every helper once a minute.'], 'Chat helper': ['Ask anything', 'Ready for your question.', '⏺ Hello. Ask me anything about this workspace.'], 'Empty helper': ['No ticket, no task yet', 'Waiting for a first task.', '⏺ Ready. Tell me what to do.'] };
    if (!has(k)) {
      if (k === 'Plain terminal') S.push({ k: k, t: 'No helper, just a terminal', kind: 'shell', s: 'open', up: 0, pin: true, now: 'An empty terminal, ready for you.', lines: ['Last login: today 15:06', 'demo@workspace ~ %'], chat: [], files: [] });
      else {
        var fullUp = used() >= max(), t = T[k] || T['Empty helper'];
        S.push({ k: k, t: t[0], kind: 'free', tool: st.nt, model: st.nm, s: fullUp ? 'queue' : 'run', up: 0, pin: true, now: fullUp ? 'Waits in line for a free helper place.' : t[1], lines: [t[2]], chat: [['h', t[2].slice(2), 'now']], files: [] });
      }
      say(k + ' opened and pinned.');
    }
    st.menu = '';
    if (st.page === 'focus') zoom(k); else { openSess(k); render('.mw-panel input, .mw-panel pre'); }
  }
  function pin(k) {
    var s = by(k), from = rectOf(sel(k));
    s.pin = !s.pin;
    render('[data-act=pin][data-k="' + k + '"]');
    flip(q1(sel(k)), from);
    say(k + (s.pin ? ' pinned: it comes first now.' : ' unpinned.'));
  }
  function beside(k) {
    var closed = st.mode === 'bar' || st.mode === 'side';
    if (closed) { st.mode = phone() ? 'bottom' : (st.last || 'bottom'); st.panes = [k]; st.act = 0; }
    else if (st.panes.indexOf(k) < 0) { if (st.panes.length < 3) st.panes.push(k); else st.panes[2] = k; }
    st.cur = k; st.ask = false; st.ren = '';
    render('.mw-pane[data-on] .mw-pt');
    flip(q1('.mw-panel .mw-pane[data-k="' + k + '"]'), rectOf(sel(k)));
  }
  function addPane() {
    var next = sorted().filter(function (o) { return live(o) && st.panes.indexOf(o.k) < 0; })[0]; if (!next || st.panes.length > 2) return;
    st.panes.push(next.k); st.cur = next.k; st.ask = false; st.ren = '';
    render('.mw-pane[data-on] .mw-pt'); say(next.k + ' added beside. Pick another session in the bar to change it.');
  }
  var DEMO = [['img', 'home-390.png', 'Picture · 212 KB'], ['table', 'price-list.csv', 'Table · 14 KB', [['Starter', '19'], ['Team', '49'], ['Company', '129']]]];
  function attach(s, list) { s.att = (s.att || []).concat(list); say(list.length + (list.length === 1 ? ' file' : ' files') + ' attached. Nothing is sent yet.'); }
  function fromFiles(fl) {
    return Array.prototype.map.call(fl, function (f) { var e = (f.name.split('.').pop() || '').toLowerCase(), t = /^(png|jpe?g|gif|svg|webp)$/.test(e) ? 'img' : (/^(csv|xlsx)$/.test(e) ? 'table' : (e === 'html' ? 'html' : 'file')); return [t, f.name || 'screenshot.png', KIND[t].charAt(0).toUpperCase() + KIND[t].slice(1) + ' · ' + (f.size > 1048576 ? (f.size / 1048576).toFixed(1) + ' MB' : Math.max(1, Math.round(f.size / 1024)) + ' KB')]; });
  }
  function closePane(k) {
    var i = st.panes.indexOf(k); if (i < 0) return;
    if (st.panes.length < 2) { setMode('bar'); return; }
    st.panes.splice(i, 1); st.act = Math.max(0, Math.min(st.act > i ? st.act - 1 : st.act, st.panes.length - 1)); st.cur = st.panes[st.act]; st.ask = false; st.ren = '';
    render('.mw-pane[data-on] .mw-pt');
  }
  function many(on) {
    st.many = on;
    if (on) {
      if (!EXTRA) EXTRA = MORE.map(function (m, i) {
        var s = { k: 'ORCH-' + m[0], t: m[1], kind: 'ticket', s: m[2], tool: i % 3 === 1 ? 't2' : 't1', up: 12 + i * 7, step: [1 + i % 4, 4 + i % 3], now: NOWS[i % NOWS.length], lines: ['⏺ Read(ticket notes)', '⏺ ' + NOWS[i % NOWS.length]], chat: [['h', NOWS[i % NOWS.length], '15:0' + (i % 10), 0, 0]], files: [] };
        if (m[2] === 'wait') { s.q = QS[i % 2]; s.now = 'Waits for your answer.'; }
        if (m[2] === 'idle') { s.sl = 'Idle ' + (9 + i * 3) + ' min'; s.close = 51 - i * 3; s.now = 'Finished its step. Nothing to do right now.'; }
        if (m[2] === 'none') { s.sl = 'No session'; s.last = 'last week'; s.now = 'Closed after an hour idle. The conversation is kept.'; }
        if (m[2] === 'queue') { s.now = 'Waits in line for a free helper place.'; s.lines = []; s.chat = []; s.step = [0, 4 + i % 3]; }
        if (m[2] === 'run' && i % 3 === 0) s.feed = ['⏺ ' + NOWS[(i + 1) % NOWS.length], '⏺ ' + NOWS[(i + 2) % NOWS.length]];
        return s;
      });
      S = S.concat(EXTRA.filter(function (e) { return !has(e.k); }));
      EXTRA.forEach(function (e) { if (e.s === 'run' && used() > max()) { e.s = 'queue'; e.now = 'Waits in line for a free helper place.'; e.feed = null; } });
    } else {
      S = S.filter(function (s) { return !EXTRA || EXTRA.indexOf(s) < 0; });
      if (!has(st.cur)) st.cur = S[0].k; if (!has(st.tk)) st.tk = S[0].k; st.list = '';
    }
  }
  function setPage(p) {
    st.page = p; st.ask = false; st.ren = ''; st.menu = ''; st.list = '';
    if (p === 'focus') st.view = 'wall';
    var sb = q1('.sidebar'); if (sb) { sb.removeAttribute('data-open'); $('mw-menu').setAttribute('aria-expanded', 'false'); }
    render();
    var m = $('content'); if (m) m.focus({ preventScroll: true });
    window.scrollTo(0, 0);
    say(PAGES[p] + ' page. Focus stays open.');
  }
  function setMode(m) {
    if (m === 'bottom' || m === 'right') st.last = m;
    st.mode = m; st.full = false; st.menu = ''; st.list = '';
    render(m === 'side' ? '.mw-edge' : '[data-act=menu][data-m=pos]');
  }
  function need(k) {
    var o = JSON.parse(S0).filter(function (s) { return s.k === k; })[0], s = by(k);
    if (o && (s.k !== k || s.s !== o.s)) { if (s.k === k) S[S.indexOf(s)] = o; else S.push(o); }
  }
  function show(n, more) {
    var o = more ? F[n - 1][7][1] : F[n - 1][6];
    if (o.need) need(o.need);
    st.full = false; st.ask = false; st.ren = ''; st.menu = ''; st.list = ''; st.ov = null; st.f = ''; st.mode = 'bar';
    if (!!o.many !== st.many) many(!!o.many);
    Object.keys(o).forEach(function (k) { if (k !== 'need' && k !== 'many') st[k] = Array.isArray(o[k]) ? o[k].slice() : (o[k] && typeof o[k] === 'object' ? JSON.parse(JSON.stringify(o[k])) : o[k]); });
    if (!o.panes) { st.panes = [st.cur]; st.act = 0; }
    st.voice = o.voice || ''; st.vk = st.cur; if (o.att) by(st.cur).att = DEMO.slice(); if (o.voice === 'done') drafts['c:' + st.cur] = 'Please keep the old file name, and add a note for the support team.';
    delete st.att;
    if (st.mode === 'bottom' || st.mode === 'right') st.last = st.mode;
    st.feat = n; st.marks = true; if (window.innerWidth <= 900 || o.full || o.ov) st.sheet = false;
    render();
  }
  function openSheet(n) {
    st.sheet = true; st.feat = n || st.feat; st.full = false;
    render();
    var t = n ? $('mw-f' + n) : null;
    if (t) { t.scrollIntoView({ block: 'nearest' }); var bt = t.querySelector('button'); if (bt) bt.focus(); }
    else { var c = q1('#mw-sheet button'); if (c) c.focus(); }
  }

  document.addEventListener('click', function (e) {
    var menu = e.target.closest('#mw-menu');
    if (menu) { var sb = q1('.sidebar'), on = sb.getAttribute('data-open') !== 'true'; if (on) sb.setAttribute('data-open', 'true'); else sb.removeAttribute('data-open'); menu.setAttribute('aria-expanded', String(on)); return; }
    var nav = e.target.closest('.sidebar .nav-item[aria-label], .sidebar .brand');
    if (nav) { var p = nav.classList.contains('brand') ? 'home' : nav.getAttribute('aria-label').toLowerCase(); if (PAGES[p]) { e.preventDefault(); setPage(p); return; } }
    var b = e.target.closest('[data-act]');
    if (!b) { if ((st.menu || st.list || st.pm) && !e.target.closest('.mw-pop, .mw-pmenu')) { st.menu = ''; st.list = ''; st.pm = ''; render(); } return; }
    var a = b.dataset.act, k = b.dataset.k, s;
    if (a === 'pm') { var pk = k + '|' + b.dataset.kind; st.pm = st.pm === pk ? '' : pk; st.menu = ''; st.list = ''; render(st.pm ? '.mw-pmenu .mw-opt' : '[data-act=pm][data-k="' + k + '"][data-kind=' + b.dataset.kind + ']'); return; }
    if (st.pm) { st.pm = ''; if (k && has(k) && (a === 'ask' || a === 'view')) st.cur = k; }
    if (a === 'ntool') { st.nt = b.dataset.v; st.nm = AG[st.nt].usual; render('[data-act=ntool][data-v=' + st.nt + ']'); return; }
    if (a === 'nmodel') { st.nm = b.dataset.v; render('[data-act=nmodel][aria-pressed=true]'); return; }
    if (a === 'smodel') { s = by(k); s.next = b.dataset.v === mdl(s) ? '' : b.dataset.v; render('[data-act=pm][data-k="' + k + '"][data-kind=model]'); say(s.next ? 'Model ' + s.next + ' chosen for ' + s.k + '.' : 'The model stays ' + mdl(s) + '.'); return; }
    if (a === 'min') { setMode('bar'); return; }
    if (a === 'attach') { attach(by(k), DEMO.filter(function (d) { return !(by(k).att || []).some(function (x) { return x[1] === d[1]; }); })); render('.mw-comp[data-k="' + k + '"] input'); return; }
    if (a === 'attx') { by(k).att.splice(+b.dataset.i, 1); render('.mw-comp[data-k="' + k + '"] input'); return; }
    if (a === 'voice') {
      st.voice = b.dataset.v; st.vk = k;
      if (st.voice === 'done') drafts['c:' + k] = ((drafts['c:' + k] || '') + ' Please keep the old file name, and add a note for the support team.').trim();
      render('.mw-comp[data-k="' + k + '"] ' + (st.voice === 'rec' ? '[data-act=voice]' : 'input')); say(st.voice === 'rec' ? 'Listening.' : (st.voice ? 'Your words are in the box. Nothing is sent yet.' : 'Voice cancelled.')); return;
    }
    if (a === 'zoom') zoom(k);
    else if (a === 'back') back();
    else if (a === 'home') { if (st.page === 'focus' && st.view === 'zoom') back(); else setPage('focus'); }
    else if (a === 'page') setPage(b.dataset.p);
    else if (a === 'ticket') { st.tk = k; setPage('ticket'); }
    else if (a === 'switch') { openSess(k); render('.mw-bar [data-act=switch][data-k="' + k + '"]'); }
    else if (a === 'focus') { openSess(k); render('.mw-pane[data-on] .mw-pmain button, .mw-pane[data-on] .mw-pmain input, .mw-pane[data-on] pre'); }
    else if (a === 'act') { st.cur = k; st.ask = false; st.ren = ''; render('.mw-pane[data-on] .mw-pt'); }
    else if (a === 'beside') beside(k);
    else if (a === 'addpane') addPane();
    else if (a === 'closepane') closePane(k);
    else if (a === 'view') { st.term = b.dataset.v === 'term'; render('.mw-pane[data-on] [data-act=view][data-v=' + b.dataset.v + '], [data-act=view][data-v=' + b.dataset.v + ']'); }
    else if (a === 'full') { st.full = !st.full; st.menu = ''; st.list = ''; if (st.full) st.sheet = false; render('[data-act=full]'); }
    else if (a === 'mode') setMode(b.dataset.m);
    else if (a === 'menu') { st.menu = st.menu === b.dataset.m ? '' : b.dataset.m; st.list = ''; render(st.menu ? '.mw-pop .mw-opt' : '[data-act=menu][data-m=' + b.dataset.m + ']'); }
    else if (a === 'list') { st.list = st.list === b.dataset.l ? '' : b.dataset.l; st.menu = ''; st.lq = ''; render(st.list ? '#mw-lq, .mw-pop .mw-opt' : '[data-act=list][data-l=' + b.dataset.l + ']'); }
    else if (a === 'col') { st.col[b.dataset.id] = !st.col[b.dataset.id]; render('[data-act=col][data-id=' + b.dataset.id + ']'); }
    else if (a === 'pin') pin(k);
    else if (a === 'ren') { st.ren = k; render('.mw-ren input'); var ri = q1('.mw-ren input'); if (ri) ri.select(); }
    else if (a === 'answer') answer(k, +b.dataset.a);
    else if (a === 'start') start(k, b.dataset.how);
    else if (a === 'reopen') { s = by(k); begin(s, ['', '⏺ Reopened the session from ' + HIST[+b.dataset.i][0] + '.'], 'Reopened the session from ' + HIST[+b.dataset.i][0]); }
    else if (a === 'ask') { st.ask = true; render('.mw-start button'); }
    else if (a === 'askoff') { st.ask = false; render('[data-act=ask]'); }
    else if (a === 'new') create(k);
    else if (a === 'ov') { st.ov = { src: b.dataset.src, i: +b.dataset.i }; render('#mw-ovx'); }
    else if (a === 'ovnav') ovStep(+b.dataset.d);
    else if (a === 'ovclose') closeOv();
    else if (a === 'copyterm') clip(screenText(by(k)), function () { b.textContent = 'Copied'; say('Terminal text copied.'); });
    else if (a === 'feat') openSheet(+b.dataset.n);
    else if (a === 'sheet') { if (st.sheet) { st.sheet = false; render('#mw-fbtn'); } else openSheet(0); }
    else if (a === 'show') show(+b.dataset.n, b.dataset.more);
    else if (a === 'pick') { var n = b.dataset.n; picks[n] = picks[n] === b.dataset.p ? '' : b.dataset.p; try { localStorage.setItem(KEY, JSON.stringify(picks)); } catch (er) { /* private window */ } render('[data-act=pick][data-n="' + n + '"][data-p=' + b.dataset.p + ']'); }
    else if (a === 'copy') clip('Focus draft D: my picks\n' + F.map(function (f) { return f[0] + '. ' + f[1] + ': ' + (picks[f[0]] || 'not picked'); }).join('\n') + '\n\nResult widgets\n' + WG.map(function (w) { return w[1] + ': ' + (picks['w:' + w[0]] || 'not picked'); }).join('\n'), function () { var c = $('mw-copied'); if (c) c.textContent = 'Copied'; });
  });
  function closeOv() { var o = st.ov; st.ov = null; render(o ? '[data-act=ov][data-src="' + o.src + '"][data-i="' + o.i + '"]' : ''); }
  document.addEventListener('change', function (e) {
    if (e.target.id === 'mw-marks') { st.marks = e.target.checked; render('#mw-marks'); }
    if (e.target.id === 'mw-many') { many(e.target.checked); render('#mw-many'); say(e.target.checked ? 'Demo shows 24 sessions.' : 'Demo shows 6 sessions.'); }
  });
  document.addEventListener('input', function (e) {
    var t = e.target, d = t.dataset && t.dataset.d;
    if (d) { drafts[d] = t.value; if (st.voice === 'done') st.voice = ''; }
    else if (t.id === 'mw-filter') { st.f = t.value; $('mw-bands').innerHTML = bandsHTML(); url(); }
    else if (t.id === 'mw-lq') { st.lq = t.value; $('mw-plist').innerHTML = listRows(); }
  });
  document.addEventListener('submit', function (e) {
    var f = e.target.closest('form[data-f]'); if (!f) return;
    e.preventDefault();
    var inp = f.querySelector('input'), v = inp.value.trim(), s = by(f.dataset.k);
    if (f.dataset.f === 'ren') { s.name = v && v !== s.t ? v : ''; st.ren = ''; render('[data-act=ren]'); say('Name saved.'); return; }
    var at2 = s.att || [];
    if (!v && !at2.length) return;
    inp.value = ''; drafts[inp.dataset.d] = '';
    {
      s.sent = s.sent || []; var ix = at2.map(function (f) { s.sent.push(f); return s.sent.length - 1; });
      s.att = []; if (st.vk === s.k) st.voice = '';
      s.chat.push(['y', v, 'now', 0, undefined, ix]); s.lines.push('> ' + (v || '(files)') + (ix.length ? ' [' + ix.length + ' attached]' : ''));
      if (ix.length || f.querySelector('.mw-vhint')) { render('.mw-comp[data-k="' + s.k + '"] input'); }
      setTimeout(function () { s.chat.push(['h', 'Got it. I take that into account.', 'now']); s.lines.push('⏺ Got it. I take that into account.'); refreshChat(s.k); refresh(); }, 600);
      refreshChat(s.k); refresh();
    }
  });
  function termKey(s, key) {
    var t = s.typed || '';
    if (key === 'Enter') {
      if (!t.trim()) return;
      s.typed = '';
      if (s.kind === 'shell') { s.lines[s.lines.length - 1] += ' ' + t; s.lines.push('demo terminal: nothing was run', 'demo@workspace ~ %'); }
      else { s.lines.push('> ' + t); setTimeout(function () { s.lines.push('⏺ Got it: "' + t + '". I take that into account.'); refresh(); }, 500); }
    } else if (key === 'Backspace') s.typed = t.slice(0, -1);
    else s.typed = t + key;
    refresh(); document.querySelectorAll('[data-screen]').forEach(function (x) { if (by(x.dataset.screen) === s) x.scrollTop = x.scrollHeight; });
  }
  /* files and screenshots: paste into the message box, or drop anywhere on the pane */
  document.addEventListener('paste', function (e) {
    var cf = e.target.closest && e.target.closest('.mw-comp'), fl = e.clipboardData && e.clipboardData.files;
    if (cf && fl && fl.length) { e.preventDefault(); attach(by(cf.dataset.k), fromFiles(fl)); render('.mw-comp[data-k="' + cf.dataset.k + '"] input'); }
  });
  document.addEventListener('dragover', function (e) { if (e.target.closest && e.target.closest('.mw-pane')) e.preventDefault(); });
  document.addEventListener('drop', function (e) {
    var pn = e.target.closest && e.target.closest('.mw-pane'), fl = e.dataTransfer && e.dataTransfer.files; if (!pn || !fl || !fl.length) return;
    e.preventDefault(); attach(by(pn.dataset.k), fromFiles(fl)); render('.mw-comp[data-k="' + pn.dataset.k + '"] input');
  });
  document.addEventListener('paste', function (e) {
    var scr = e.target.closest && e.target.closest('pre[data-screen]'); if (!scr) return;
    e.preventDefault(); termKey(by(scr.dataset.screen), ((e.clipboardData && e.clipboardData.getData('text')) || '').replace(/\s+/g, ' '));
  });
  document.addEventListener('keydown', function (e) {
    var scr = e.target.closest && e.target.closest('pre[data-screen]');
    if (scr && !e.ctrlKey && !e.metaKey && !e.altKey && (e.key === 'Enter' || e.key === 'Backspace' || e.key.length === 1)) { e.preventDefault(); termKey(by(scr.dataset.screen), e.key); return; }
    if (st.ov) {
      if (e.key === 'Tab') { var fs = $('mw-ov').querySelectorAll('button, a[href], iframe'), f0 = fs[0], f1 = fs[fs.length - 1]; if (e.shiftKey && document.activeElement === f0) { e.preventDefault(); f1.focus(); } else if (!e.shiftKey && document.activeElement === f1) { e.preventDefault(); f0.focus(); } return; }
      if (e.key === 'Escape') closeOv(); else if (e.key === 'ArrowLeft') ovStep(-1); else if (e.key === 'ArrowRight') ovStep(1);
      return;
    }
    if ((e.ctrlKey || e.metaKey) && (e.key === 'j' || e.key === 'J')) {
      e.preventDefault();
      if (st.full) { st.full = false; render(); }
      else if (zoomed()) back();
      else setMode(st.mode === 'bar' || st.mode === 'side' ? (st.last || 'bottom') : 'bar');
      return;
    }
    if (e.key !== 'Escape') return;
    if (st.sheet) { st.sheet = false; render('#mw-fbtn'); }
    else if (st.pm) { var pk2 = st.pm.split('|'); st.pm = ''; render('[data-act=pm][data-k="' + pk2[0] + '"][data-kind=' + pk2[1] + ']'); }
    else if (st.voice === 'rec') { st.voice = ''; render('[data-act=voice]'); }
    else if (st.menu || st.list) { var w = st.menu ? '[data-act=menu][data-m=' + st.menu + ']' : '[data-act=list]'; st.menu = ''; st.list = ''; render(w); }
    else if (st.ren) { st.ren = ''; render('[data-act=ren]'); }
    else if (st.full) { st.full = false; render('[data-act=menu][data-m=pos], [data-act=full]'); }
    else if (st.ask && live(by(st.cur))) { st.ask = false; render('[data-act=ask]'); }
    else if (zoomed()) back();
  });
  var rz; window.addEventListener('resize', function () { clearTimeout(rz); rz = setTimeout(function () { render(); }, 150); });
  var vt0 = 4; setInterval(function () { var e = q1('[data-vt]'); if (e) { vt0++; e.textContent = Math.floor(vt0 / 60) + ':' + ('0' + vt0 % 60).slice(-2); } else vt0 = 4; }, 1000);
  /* live: one working session gets its next line every few seconds */
  setInterval(function () {
    var w = S.filter(function (s) { return s.s === 'run' && s.feed && s.feed.length; }); if (!w.length) return;
    var s = w[feedAt++ % w.length]; s.fi = (s.fi || 0);
    push(s, s.feed[s.fi++ % s.feed.length]); refresh();
  }, 2400);

  /* ---------- start: read the link ---------- */
  (function () {
    var q = new URLSearchParams(location.search), v, ov = document.createElement('div');
    ov.id = 'mw-ov'; ov.className = 'mw-ov'; ov.hidden = true; document.body.appendChild(ov);
    if (q.get('many') === '1') many(true);
    if (PG[v = q.get('page')] || v === 'focus') st.page = v;
    if ((v = q.get('cur')) && has(v)) { st.cur = v; if (by(v).kind === 'ticket') st.tk = v; }
    if ((v = q.get('tk')) && has(v)) st.tk = v;
    st.panes = [st.cur];
    var n = Math.max(1, Math.min(3, +q.get('split') || 1));
    ['cur2', 'cur3'].slice(0, n - 1).forEach(function (c) { var k = q.get(c); if (k && has(k) && st.panes.indexOf(k) < 0) st.panes.push(k); });
    sorted().forEach(function (o) { if (st.panes.length < n && live(o) && st.panes.indexOf(o.k) < 0) st.panes.push(o.k); });
    v = +q.get('act'); if (v >= 1 && v <= st.panes.length) st.cur = st.panes[v - 1];
    v = q.get('mode');
    if (v === 'full') st.full = true;
    else if (/^(bar|bottom|right|side)$/.test(v || '')) { st.mode = v; if (v === 'bottom' || v === 'right') st.last = v; }
    if (q.get('view') === 'zoom' || q.get('ask') === '1' || q.get('ren') === '1') st.view = 'zoom';
    st.term = q.get('term') === '1';
    st.ask = q.get('ask') === '1' && live(by(st.cur));
    if (q.get('ren') === '1') st.ren = st.cur;
    if (/^(wait|pin|run|queue|idle|more)$/.test(v = q.get('list') || '')) st.list = v;
    if (/^(new|pos)$/.test(v = q.get('menu') || '')) st.menu = v;
    if (MODELS[v = q.get('tool')]) { st.nt = v; st.nm = MODELS[v].indexOf(q.get('model')) >= 0 ? q.get('model') : AG[v].usual; }
    else if (MODELS.t1.indexOf(q.get('model')) >= 0) st.nm = q.get('model');
    if ((v = q.get('pm'))) { var pc = v.lastIndexOf(':'); if (pc > 0 && has(v.slice(0, pc)) && /^(place|model|more)$/.test(v.slice(pc + 1))) st.pm = v.slice(0, pc) + '|' + v.slice(pc + 1); }
    if (q.get('att') === '1') by(st.cur).att = DEMO.slice();
    if (/^(rec|done)$/.test(v = q.get('voice') || '')) { st.voice = v; st.vk = st.cur; if (v === 'done') drafts['c:' + st.cur] = 'Please keep the old file name, and add a note for the support team.'; }
    st.f = q.get('q') || '';
    if ((v = q.get('res'))) { var c = v.lastIndexOf(':'), src = v.slice(0, c), ri = +v.slice(c + 1); if ((src === '*' || has(src.replace(/^(att|sent):/, ''))) && files(src)[ri]) st.ov = { src: src, i: ri }; }
    st.marks = q.get('marks') === '1';
    if ((v = q.get('sheet'))) { st.sheet = true; st.feat = +v >= 1 && +v <= F.length ? +v : 0; }
    document.body.dataset.mwBoot = '1'; /* a page that opens with the sheet shows it at once, without the slide */
    render();
    if (st.sheet && st.feat) { var t = $('mw-f' + st.feat); if (t) { var fe = t.parentNode; fe.scrollTop = t.offsetTop - fe.offsetTop; } }
    setTimeout(function () { delete document.body.dataset.mwBoot; }, 300);
  })();
})();
