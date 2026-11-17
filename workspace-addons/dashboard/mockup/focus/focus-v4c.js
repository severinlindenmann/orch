/* Focus v4c draft (ORCH-251): "Calm inbox". Focus as a messenger: sessions are chats, one conversation,
   one composer, Terminal is a flip of the same pane. Demo data only; picks stay in this browser. */
(function () {
  'use strict';
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  function h(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }
  function btn(text, cls, fn, fk) { var b = h('button', 'btn ' + (cls || 'sm'), text); b.type = 'button'; b.dataset.fk = fk || 'b:' + text; if (fn) b.addEventListener('click', fn); return b; }
  var store = { get: function (k) { try { return localStorage.getItem(k); } catch (e) { return null; } }, set: function (k, v) { try { localStorage.setItem(k, v); } catch (e) {} } };
  function toast(m, undo) { try { window.UI.toast(m, undo); } catch (e) {} }

  /* ---------- icons and small pictures (static markup, colours from tokens) ---------- */
  var IC = {
    full: '<path d="M3 6V3h3M10 3h3v3M13 10v3h-3M6 13H3v-3"/>',
    min: '<path d="M3 12h10"/>',
    more: '<circle cx="3.5" cy="8" r=".6"/><circle cx="8" cy="8" r=".6"/><circle cx="12.5" cy="8" r=".6"/>',
    back: '<path d="M10 3 5 8l5 5"/>',
    chat: '<path d="M2.5 3h11v8H7l-3 2.5V11H2.5z"/>',
    find: '<circle cx="7" cy="7" r="4"/><path d="m10 10 3.5 3.5"/>',
    plus: '<path d="M8 3v10M3 8h10"/>',
    close: '<path d="m4 4 8 8M12 4l-8 8"/>',
    flip: '<path d="M3 5h9l-2.5-2.5M13 11H4l2.5 2.5"/>',
    page: '<path d="M4 2h6l3 3v9H4z"/><path d="M10 2v3h3"/>',
    term: '<rect x="2" y="3" width="12" height="10" rx="1.5"/><path d="m5 6.5 2 1.5-2 1.5M8.5 10H11"/>',
    split: '<rect x="2" y="3" width="12" height="10" rx="1.5"/><path d="M8 3v10"/>'
  };
  function ico(n, size) { var s = h('span', 'c-ic'); s.setAttribute('aria-hidden', 'true'); s.innerHTML = '<svg viewBox="0 0 16 16" width="' + (size || 16) + '" height="' + (size || 16) + '" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">' + IC[n] + '</svg>'; return s; }
  var GL = {
    wait: '<circle cx="8" cy="8" r="7" fill="currentColor"/><path d="M8 4.5v4.2M8 11.4v.2" stroke="var(--bg)" stroke-width="2" stroke-linecap="round"/>',
    run: '<circle cx="8" cy="8" r="6" fill="none" stroke="currentColor" stroke-width="2" opacity=".35"/><path d="M8 2a6 6 0 0 1 6 6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
    idle: '<circle cx="8" cy="8" r="6" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M6.3 5.5v5M9.7 5.5v5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>',
    none: '<circle cx="8" cy="8" r="6" fill="none" stroke="currentColor" stroke-width="1.5" stroke-dasharray="2 2.6"/>'
  };
  function glyph(s) { var g = h('span', 'c-g ' + s); g.setAttribute('aria-hidden', 'true'); g.innerHTML = '<svg viewBox="0 0 16 16" width="16" height="16">' + GL[s] + '</svg>'; return g; }
  var TH = {
    shot: '<rect width="120" height="76" fill="var(--bg)"/><rect width="26" height="76" fill="var(--sidebar)"/><rect x="5" y="8" width="16" height="3" rx="1.5" fill="var(--brand)"/><rect x="5" y="18" width="14" height="2" rx="1" fill="var(--surface-3)"/><rect x="5" y="24" width="16" height="2" rx="1" fill="var(--surface-3)"/><rect x="5" y="30" width="12" height="2" rx="1" fill="var(--surface-3)"/><rect x="34" y="8" width="40" height="5" rx="2" fill="var(--text-muted)"/><rect x="34" y="20" width="78" height="20" rx="3" fill="var(--surface)" stroke="var(--border)"/><rect x="40" y="27" width="34" height="3" rx="1.5" fill="var(--text-faint)"/><rect x="94" y="25" width="14" height="8" rx="2" fill="var(--brand)"/><rect x="34" y="46" width="78" height="20" rx="3" fill="var(--surface)" stroke="var(--border)"/><rect x="40" y="53" width="48" height="3" rx="1.5" fill="var(--text-faint)"/>',
    phone: '<rect width="120" height="76" fill="var(--bg)"/><rect x="42" y="5" width="36" height="66" rx="5" fill="var(--surface)" stroke="var(--border-strong)"/><rect x="47" y="12" width="18" height="3" rx="1.5" fill="var(--text-muted)"/><rect x="47" y="20" width="26" height="10" rx="2" fill="var(--surface-3)"/><rect x="47" y="34" width="26" height="10" rx="2" fill="var(--surface-3)"/><rect x="47" y="48" width="26" height="10" rx="2" fill="var(--surface-3)"/><rect x="47" y="62" width="26" height="4" rx="2" fill="var(--brand)"/>',
    page: '<rect width="120" height="76" fill="var(--surface)"/><rect width="120" height="12" fill="var(--surface-3)"/><circle cx="7" cy="6" r="2" fill="var(--text-faint)"/><circle cx="14" cy="6" r="2" fill="var(--text-faint)"/><rect x="24" y="3" width="70" height="6" rx="3" fill="var(--bg)"/><rect x="8" y="20" width="44" height="4" rx="2" fill="var(--text-muted)"/><rect x="8" y="30" width="48" height="38" rx="3" fill="var(--bg)" stroke="var(--border)"/><rect x="64" y="30" width="48" height="38" rx="3" fill="var(--bg)" stroke="var(--brand)"/><rect x="14" y="37" width="24" height="3" rx="1.5" fill="var(--text-faint)"/><rect x="70" y="37" width="24" height="3" rx="1.5" fill="var(--brand)"/>',
    csv: '<rect width="120" height="76" fill="var(--bg)"/><rect x="6" y="6" width="108" height="12" fill="var(--surface-3)"/><path d="M6 18h108M6 30h108M6 42h108M6 54h108M6 66h108M6 6v60M46 6v60M82 6v60M114 6v60" stroke="var(--border)" fill="none"/><rect x="10" y="22" width="26" height="3" rx="1.5" fill="var(--text-faint)"/><rect x="50" y="22" width="18" height="3" rx="1.5" fill="var(--text-faint)"/><rect x="86" y="22" width="12" height="3" rx="1.5" fill="var(--success)"/><rect x="10" y="34" width="20" height="3" rx="1.5" fill="var(--text-faint)"/><rect x="50" y="34" width="22" height="3" rx="1.5" fill="var(--text-faint)"/><rect x="86" y="34" width="12" height="3" rx="1.5" fill="var(--success)"/><rect x="10" y="46" width="28" height="3" rx="1.5" fill="var(--text-faint)"/><rect x="50" y="46" width="14" height="3" rx="1.5" fill="var(--text-faint)"/><rect x="86" y="46" width="12" height="3" rx="1.5" fill="var(--warning)"/>',
    chart: '<rect width="120" height="76" fill="var(--bg)"/><path d="M12 8v56h100" stroke="var(--border-strong)" fill="none"/><rect x="20" y="22" width="12" height="42" rx="2" fill="var(--working)"/><rect x="38" y="34" width="12" height="30" rx="2" fill="var(--working)"/><rect x="56" y="14" width="12" height="50" rx="2" fill="var(--brand)"/><rect x="74" y="44" width="12" height="20" rx="2" fill="var(--working)"/><rect x="92" y="52" width="12" height="12" rx="2" fill="var(--working)"/>',
    pr: '<rect width="120" height="76" fill="var(--surface-2)"/><circle cx="40" cy="20" r="6" fill="none" stroke="var(--text-muted)" stroke-width="2.5"/><circle cx="40" cy="56" r="6" fill="none" stroke="var(--text-muted)" stroke-width="2.5"/><circle cx="80" cy="56" r="6" fill="none" stroke="var(--brand)" stroke-width="2.5"/><path d="M40 26v24M80 50V34a8 8 0 0 0-8-8H58m5-6-6 6 6 6" fill="none" stroke="var(--text-muted)" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>'
  };
  var KIND = { shot: 'Picture', phone: 'Picture', page: 'Web page', csv: 'Table', chart: 'Chart', pr: 'Pull request' };
  function thumb(kind) { var s = h('span', 'c-thumb'); s.setAttribute('aria-hidden', 'true'); s.innerHTML = '<svg viewBox="0 0 120 76" preserveAspectRatio="xMidYMid slice">' + TH[kind] + '</svg>'; return s; }

  /* ---------- demo data ---------- */
  var WORD = { wait: 'Needs you', run: 'Working', idle: 'Idle', none: 'Not started' };
  var OPEN = { wait: 'Answer', run: 'Watch', idle: 'Open', none: 'Start' };
  var LIVE_MAX = 6;
  function word(x) { return x.s === 'none' && x.ran ? 'Stopped' : WORD[x.s]; }
  var S = [
    { k: 'ORCH-238', t: 'Add files and notes to a ticket', s: 'wait', tk: 1, ran: 1, last: 'Keep the old file name?', time: '2 min', step: [3, 5],
      thread: [
        { e: 'Continued the earlier conversation · 14:02' },
        { m: 'I read the ticket. Adding files works now: drag a file onto the ticket, or paste a picture.', at: '14:05' },
        { files: [{ kind: 'shot', name: 'add-files-1280.png', note: 'The new Add files box' }, { kind: 'phone', name: 'add-files-390.png', note: 'Same box on a phone' }] },
        { m: 'One thing I should not decide for you.', at: '14:21' },
        { ask: 'Keep the old file name?', sub: 'When someone adds report.pdf and a report.pdf is already on the ticket.', opts: ['Keep both, name the new one report (2).pdf', 'Replace the old file'], rec: 0 }
      ],
      log: ['● Step 3 of 5: Save the file next to the ticket', '  Read   workspace/src/orch/files.py', '  Edit   workspace/src/orch/files.py  (+38 −4)', '  Bash   uv run pytest tests/test_files.py -q', '  ⎿ 14 passed in 3.1s', '', '● Asked you: Keep the old file name?', '  1. Keep both, name the new one report (2).pdf', '  2. Replace the old file', '  Waiting for your answer…'] },
    { k: 'ORCH-228', t: 'Phone width and zoom', s: 'run', tk: 1, ran: 1, last: 'Opening the pull request', time: 'now', step: [4, 5],
      thread: [
        { e: 'Started clean · 13:40' },
        { m: 'Three screens scrolled sideways on a phone. All three are fixed, and text now stays readable at 200% zoom.', at: '14:12' },
        { files: [{ kind: 'phone', name: 'home-390.png', note: 'Home on a phone, after' }, { kind: 'page', name: 'before-after.html', note: 'Before and after, side by side' }, { kind: 'csv', name: 'widths.csv', note: '12 screens, 3 widths, all fit' }] },
        { live: 'Opening the pull request', sub: 'Step 4 of 5 · about 2 minutes' },
        { files: [{ kind: 'pr', name: 'Phone width and zoom', note: '#1312 · checks running, 3 of 7 green' }] }
      ],
      log: ['● Step 4 of 5: Open the pull request', '  Bash   node --test tests/phone.test.js', '  ⎿ tests 22 · pass 22 · fail 0', '  Bash   git push -u origin fix/phone-width', '  ⎿ branch fix/phone-width pushed', '  Bash   gh pr create --base develop --draft', '  ⎿ https://github.com/…/pull/1312', '', '● Opening the pull request… (esc to interrupt)'] },
    { k: 'ORCH-232', t: 'Insights and usage counts', s: 'run', tk: 1, ran: 1, last: 'Running tests', time: 'now', step: [2, 6],
      thread: [
        { e: 'Continued the earlier conversation · 13:55' },
        { m: 'I counted which skills the helpers used this week. Publish is used most, Sync was never used.', at: '14:18' },
        { files: [{ kind: 'chart', name: 'Skills used this week', note: 'Publish 41 · Relay 30 · Sync 0' }, { kind: 'csv', name: 'usage.csv', note: '5 skills, 7 days' }] },
        { live: 'Running tests', sub: 'Step 2 of 6 · 41 of 96 passed so far' }
      ],
      log: ['● Step 2 of 6: Count skill use per day', '  Edit   workspace-addons/insights/counts.py  (+52 −9)', '  Bash   node --test tests/insights', '  ⎿ ✔ counts per day (12ms)', '  ⎿ ✔ empty week shows zero (4ms)', '  ⎿ 41 of 96 passed, still running…'] },
    { k: 'ORCH-247', t: 'Steer a helper from the dashboard', s: 'idle', tk: 1, ran: 1, last: 'All 5 steps done', time: '18 min', step: [5, 5],
      thread: [
        { e: 'Started clean · 11:20' },
        { m: 'All 5 steps are done and the pull request is merged. You can send a helper a message from the ticket now.', at: '14:06' },
        { files: [{ kind: 'pr', name: 'Steer a helper from the dashboard', note: '#1304 · merged, all checks green' }, { kind: 'page', name: 'steer-demo.html', note: 'Try it: a page you can click' }] },
        { e: 'Idle for 18 min. It closes by itself after about an hour; the conversation is kept.' }
      ],
      log: ['● All 5 steps done. Pull request #1304 merged.', '', '> '] },
    { k: 'ORCH-189', t: 'Manager view', s: 'none', tk: 1, ran: 1, stopAt: 'yesterday 16:40', last: 'Last conversation yesterday 16:40', time: 'yesterday', step: [0, 4],
      thread: [
        { e: 'Started yesterday · 16:12' },
        { m: 'My plan has 4 steps: a list of live helpers, their last line, a Stop button, and tests. I have not started step 1.', at: 'yesterday 16:38' },
        { e: 'Stopped · yesterday 16:40' }
      ],
      log: [] },
    { k: 'Manager', t: 'Looks after the other helpers', s: 'run', tk: 0, last: 'Looking after 4 helpers', time: 'now', step: null,
      thread: [
        { e: 'Started this morning · 08:30' },
        { m: 'Four helpers are live. One waits for you: Add files and notes asks whether to keep the old file name. The other three are fine.', at: '14:22' },
        { m: 'Manager view has no helper. Its last conversation stopped yesterday after planning 4 steps.', at: '14:22' }
      ],
      log: ['● orch run list', '  ⎿ ORCH-238  waiting   an answer from you', '  ⎿ ORCH-228  working   step 4 of 5', '  ⎿ ORCH-232  working   step 2 of 6', '  ⎿ ORCH-247  idle      18 min', '', '● Checking again in 5 minutes…'] }
  ];
  var F = [
    { t: 'Focus is an inbox', what: 'Every helper is one line, like a chat: who needs you is on top, then who is working, who is idle and who is stopped.', how: 'orch run list gives each ticket its signal (working, idle, waiting) and what it waits on; the last line comes from the read-only screen.', size: 'Medium', why: 'a new start page; the data exists', show: { page: 'focus', mode: 'bubble', view: 'list', term: 'chat', cur: 0, split: false } },
    { t: 'Open Focus from a ticket', what: 'Every ticket has one button that says what happens: Answer, Watch, Open or Start.', how: 'The run signal of that ticket picks the word; a ticket with no session gets Start.', size: 'Small', why: 'one button per ticket', show: { page: 'tickets', mode: 'bubble' } },
    { t: 'Continue or start clean', what: 'A stopped ticket offers two choices: go on with the last conversation, or begin with a fresh memory. The line above says how many live places are free.', how: 'The session id is kept on the ticket, so the next start resumes it. Only the last conversation is kept today. Live places are limited; extra starts wait in line.', size: 'Small', why: 'two buttons; a list of older conversations would need new storage', show: { page: 'focus', mode: 'bubble', view: 'chat', term: 'chat', cur: 4, split: false } },
    { t: 'One conversation', what: 'The helper’s updates are short cards, its questions have answer buttons right there, and you type in one box.', how: 'Helper messages, ticket events and open questions (orch ask) in time order; orch run send delivers what you type. No transcript is stored.', size: 'Medium', why: 'a thread view over data that exists', show: { page: 'focus', mode: 'bubble', view: 'chat', term: 'chat', cur: 0, split: false } },
    { t: 'Flip to the terminal', what: 'One switch turns the same pane into the helper’s real terminal: type, copy and paste like in the Mac Terminal. What you type there stays there.', how: 'The ticket’s own tmux session (orch run attach). There is no terminal in the browser today.', size: 'Large', why: 'needs a browser terminal and a bridge to tmux', show: { page: 'focus', mode: 'bubble', view: 'chat', term: 'terminal', cur: 1, split: false } },
    { t: 'Chats without a ticket', what: 'A Manager, a free chat or a plain terminal that belongs to no ticket sits in its own section.', how: 'The same tmux socket, with a name that is not a ticket id.', size: 'Medium', why: 'sessions outside the ticket limit', show: { page: 'focus', mode: 'bubble', view: 'chat', term: 'chat', cur: 5, split: false } },
    { t: 'Always open, on every page', what: 'Once opened, Focus stays docked on the right or at the bottom while you go from Home to Tickets to Review. The page makes room for it; what you typed is still there. Closed, it is a small bubble with the number that needs you.', how: 'Nothing new to store. Pages swap softly so the open dock survives; fallback: a pop-out window.', size: 'Large', why: 'today every page is a full load', show: { page: 'home', mode: 'right', view: 'chat', term: 'terminal', cur: 1 } },
    { t: 'Full screen', what: 'Only the conversation, centred. No menu, no list, no page. A thin strip on top shows who needs you. Esc brings everything back.', how: 'Nothing: it is a view of the same pane; the strip reads the run signal.', size: 'Small', why: 'layout only', show: { mode: 'full', view: 'chat', cur: 1, split: false } },
    { t: 'Jump anywhere', what: 'Ctrl or Cmd+K: type a ticket, “new chat”, “manager” or “terminal” and press Enter. Switching has no load time.', how: 'The run list is already in the page; every live session stays connected.', size: 'Small', why: 'a list filter over data in the page', show: { pal: true } },
    { t: 'Results you can see', what: 'Pictures, web pages, tables, charts and pull requests appear as small pictures in the conversation, not as text. Click one to see it larger and open it.', how: 'The files and evidence on the ticket and the pull request links on it.', size: 'Medium', why: 'a small preview per file type', show: { page: 'focus', mode: 'bubble', view: 'chat', term: 'chat', cur: 1, split: false } },
    { t: 'Side by side', what: 'Two helpers next to each other on a wide screen. The list fills the side you clicked last.', how: 'Every helper has its own tmux session, so two can show at once. Two viewers of one terminal share its size.', size: 'Medium', why: 'two live panes; hidden on narrow screens', show: { page: 'focus', mode: 'bubble', view: 'chat', term: 'chat', term2: 'terminal', cur: 0, cur2: 1, split: true, pane: 0 } }
  ];
  var PAGES = { home: 'Home', tickets: 'Tickets', review: 'Review', focus: 'Focus' };

  /* ---------- state ---------- */
  var picks = {}; try { picks = JSON.parse(store.get('fv4c-picks') || '{}'); } catch (e) {}
  var st = { page: 'focus', mode: 'bubble', last: 'right', view: 'list', term: 'chat', term2: 'chat', cur: 0, cur2: -1, split: false, pane: 0, sheet: false, feat: 0, pal: false, marks: true, big: '' };
  var q = new URLSearchParams(location.search);
  if (PAGES[q.get('page')]) st.page = q.get('page');
  if (/^(bubble|right|bottom|full)$/.test(q.get('mode') || '')) st.mode = q.get('mode');
  if (/^(list|chat)$/.test(q.get('view') || '')) st.view = q.get('view');
  if (/^(chat|terminal)$/.test(q.get('term') || '')) st.term = q.get('term');
  if (/^(chat|terminal)$/.test(q.get('term2') || '')) st.term2 = q.get('term2');
  if (q.get('cur') && S[+q.get('cur')]) { st.cur = +q.get('cur'); if (!q.get('view')) st.view = 'chat'; }
  if (q.get('ask') && S[+q.get('ask')]) { st.cur = +q.get('ask'); st.view = 'chat'; st.term = 'chat'; }
  if (q.get('split') && q.get('split') !== '0') { st.split = true; if (!q.get('view')) st.view = 'chat'; }
  if (q.get('cur2') && S[+q.get('cur2')]) st.cur2 = +q.get('cur2');
  if (q.get('sheet')) st.sheet = true;
  if (q.get('feat')) { st.feat = +q.get('feat') || 0; st.sheet = true; }
  if (q.get('pal')) st.pal = true;
  if (q.get('marks') === '0') st.marks = false;
  if (st.mode === 'right' || st.mode === 'bottom') st.last = st.mode;
  var nChat = 0, nTerm = 0;

  function needs() { return S.filter(function (s) { return s.s === 'wait'; }).length; }
  function used() { return S.filter(function (s) { return s.tk && s.s !== 'none'; }).length; }
  function narrow() { return window.innerWidth <= 720; }
  function activeFk(name) { return name + (st.split && st.pane === 1 ? '2' : ''); }
  function set(o) { Object.keys(o).forEach(function (k) { st[k] = o[k]; }); if (st.mode === 'right' || st.mode === 'bottom') st.last = st.mode; render(); }
  function openSess(i, extra) {
    var o = { view: 'chat' }, p = st.split && st.pane === 1;
    if (p) { if (i === st.cur) o.cur = st.cur2; o.cur2 = i; } else { if (st.split && i === st.cur2) o.cur2 = st.cur; o.cur = i; }
    if (st.page !== 'focus' && st.mode === 'bubble') o.mode = st.last;
    if (extra) Object.keys(extra).forEach(function (k) { o[k === 'term' && p ? 'term2' : k] = extra[k]; });
    if (S[i].shell) o[p ? 'term2' : 'term'] = 'terminal';
    set(o);
  }
  function go(p) { set({ page: p }); }
  function leaveFull() { set({ mode: st.page === 'focus' ? 'bubble' : st.last }); }
  function toggleLayer() { if (st.mode === 'full') return leaveFull(); if (st.page === 'focus') return; set({ mode: st.mode === 'bubble' ? st.last : 'bubble' }); }

  function mark(n) {
    var b = h('button', 'c-n', String(n)); b.type = 'button'; b.dataset.fk = 'n' + n; if (picks[n]) b.dataset.pick = picks[n];
    b.setAttribute('aria-label', 'Feature ' + n + ': ' + F[n - 1].t); b.title = F[n - 1].t;
    b.addEventListener('click', function (e) { e.stopPropagation(); set({ sheet: true, feat: n }); }); return b;
  }
  function withMark(node, n) { if (st.marks) node.append(mark(n)); return node; }

  /* ---------- inbox: the list ---------- */
  function row(i) {
    var s = S[i], b = h('button', 'c-row ' + s.s); b.type = 'button'; b.dataset.fk = 'row' + i; b.dataset.i = i;
    var body = h('span', 'c-row-b'), l1 = h('span', 'c-row-1'), l2 = h('span', 'c-row-2');
    l1.append(h('span', 'c-row-t', s.tk ? s.t : s.k), h('span', 'c-row-time', s.time));
    l2.append(h('span', 'c-word ' + s.s, word(s)), h('span', 'c-row-last', ' · ' + s.last));
    body.append(l1, l2);
    b.append(glyph(s.s), body); b.addEventListener('click', function () { openSess(i); }); return b;
  }
  function closeBtn(fk) { var mn = btn('', 'ghost icon sm', function () { set({ mode: 'bubble' }); }, fk); mn.setAttribute('aria-label', 'Close Focus to the bubble'); mn.title = 'Close to the bubble (Ctrl/Cmd+J)'; mn.append(ico('min')); return mn; }
  function list(variant) {
    var box = h('nav', 'c-list'); box.setAttribute('aria-label', 'Helpers');
    var head = h('div', 'c-list-h'), title = h(st.page === 'focus' && variant === 'page' ? 'h1' : 'h2', 'c-list-t', 'Focus');
    head.append(withMark(title, 1));
    if (variant !== 'page') head.append(closeBtn('min'));
    box.append(head);
    var jump = h('button', 'c-jump'); jump.type = 'button'; jump.dataset.fk = 'jump'; jump.append(ico('find'), h('span', 'c-jump-t', 'Jump to a helper'), h('kbd', '', 'Ctrl K'));
    jump.addEventListener('click', function () { openPal(); });
    var jw = h('div', 'c-jump-w'); jw.append(jump); box.append(withMark(jw, 9));
    var scroll = h('div', 'c-list-s');
    var groups = [['Needs you', function (s) { return s.tk && s.s === 'wait'; }], ['Working', function (s) { return s.tk && s.s === 'run'; }], ['Idle', function (s) { return s.tk && s.s === 'idle'; }], ['Stopped', function (s) { return s.tk && s.s === 'none' && s.ran; }], ['Not started', function (s) { return s.tk && s.s === 'none' && !s.ran; }], ['Without a ticket', function (s) { return !s.tk; }, 1]];
    groups.forEach(function (g, gi) {
      var idx = []; S.forEach(function (s, i) { if (g[1](s)) idx.push(i); });
      if (!idx.length && !g[2]) return;
      var sec = h('section', 'c-sec' + (gi === 0 ? ' need' : '')), t = h('h3', 'c-sec-t', g[0] + (gi === 0 ? ' · ' + idx.length : ''));
      if (g[2]) withMark(t, 6);
      sec.append(t); idx.forEach(function (i) { sec.append(row(i)); });
      if (g[2]) {
        var two = h('div', 'c-new2');
        [['New chat', 'plus', newChat, 'newchat'], ['New terminal', 'term', newTerm, 'newterm']].forEach(function (n) { var nb = h('button', 'c-row c-new'); nb.type = 'button'; nb.dataset.fk = n[3]; nb.append(ico(n[1]), h('span', 'c-row-t', n[0])); nb.addEventListener('click', n[2]); two.append(nb); });
        sec.append(two);
      }
      scroll.append(sec);
    });
    if (!needs()) scroll.prepend(h('p', 'c-calm meta', 'Nobody needs you right now.'));
    box.append(scroll, h('p', 'c-list-f meta', used() + ' of ' + LIVE_MAX + ' live places in use. Idle helpers close after an hour.'));
    return box;
  }

  /* ---------- inbox: the conversation ---------- */
  function fileCard(f, first) {
    var id = f.kind + ':' + f.name, big = st.big === id, w = h('span', 'c-file-w' + (big ? ' big' : '')), b = h('button', 'c-file' + (big ? ' big' : '')); b.type = 'button'; b.dataset.fk = 'f:' + id;
    b.setAttribute('aria-expanded', String(big)); b.title = big ? 'Make it small again' : 'See it larger';
    var cap = h('span', 'c-file-c'); cap.append(h('span', 'c-file-k', KIND[f.kind]), h('span', 'c-file-n', f.name), h('span', 'c-file-s', f.note));
    b.append(thumb(f.kind), cap); b.addEventListener('click', function () { set({ big: big ? '' : id }); });
    w.append(b);
    if (big) w.append(btn(f.kind === 'pr' ? 'Open the pull request' : 'Open ' + f.name, 'outline sm', function () { toast('Demo: ' + f.name + ' would open in a new tab.'); }, 'open:' + id));
    if (first && st.marks) w.append(mark(10));
    return w;
  }
  function nextStep(s) { return s.step ? 'Step ' + Math.min(s.step[0] + 1, s.step[1]) + ' of ' + s.step[1] : 'Just started'; }
  function answer(s, it, text) {
    it.done = text; s.thread.push({ you: text }, { m: 'Thanks. I will do that and carry on.', at: 'now' }, { live: 'Working on the next step', sub: nextStep(s) });
    s.s = 'run'; s.last = 'Working on the next step'; s.time = 'now'; s.log.push('> ' + text, '', '● Carrying on with the next step…'); render();
  }
  function start(s, clean) {
    var at = s.stopAt || 'a moment ago', prev = s.thread.filter(function (x) { return !x.live && !x.old; });
    s.s = 'run'; s.ran = 1; s.time = 'now'; s.last = clean ? 'Reading the ticket' : 'Picking up where it stopped';
    if (clean) s.thread = [{ e: 'Started clean · a new helper with a fresh memory' }, { old: 'Earlier conversation · ' + at, prev: prev, at: at }, { m: 'Hello. I am reading the ticket from the start and will show you a plan first.', at: 'now' }, { live: 'Reading the ticket', sub: 'Just started' }];
    else s.thread = prev.concat([{ e: 'Continued the conversation from ' + at }, { m: 'I remember where we were and pick it up now.', at: 'now' }, { live: 'Picking up where it stopped', sub: nextStep(s) }]);
    s.log = ['$ orch run start ' + s.k + (clean ? ' --fresh' : ''), clean ? '● New conversation. Reading the ticket…' : '● Resumed the earlier conversation.', ''];
    render();
  }
  function reopen(s, it) {
    s.thread = it.prev.concat([{ e: 'Reopened from ' + it.at }, { m: 'I am back in the earlier conversation and remember where we were.', at: 'now' }, { live: 'Picking up where it stopped', sub: nextStep(s) }]);
    s.last = 'Reopened from ' + it.at; s.time = 'now'; s.log.push('', '● Reopened the earlier conversation.'); render();
  }
  function stop(s) {
    var snap = { s: s.s, last: s.last, time: s.time, stopAt: s.stopAt, n: s.thread.length, ln: s.log.length };
    s.s = 'none'; s.ran = 1; s.stopAt = 'a moment ago'; s.last = 'Stopped just now'; s.time = 'now'; s.thread.push({ e: 'Stopped · just now' }); s.log.push('', '[stopped]');
    render();
    toast((s.tk ? s.t : s.k) + ' stopped. The conversation is kept.', function () { s.s = snap.s; s.last = snap.last; s.time = snap.time; s.stopAt = snap.stopAt; s.thread.length = snap.n; s.log.length = snap.ln; render(); });
  }
  function startCard(s) {
    var card = h('div', 'c-start'), t = h('h2', 'c-start-t', 'No helper is working on this ticket'), free = LIVE_MAX - used();
    card.append(glyph('none'), withMark(t, 3), h('p', 'meta', s.ran ? 'Its last conversation stopped ' + (s.stopAt || 'a moment ago') + '.' : 'Nobody has worked on it yet.'));
    card.append(h('p', 'c-cost', free > 0 ? free + ' of ' + LIVE_MAX + ' live places free. Starting uses one.' : 'No live place is free. It starts when one frees up.'));
    var two = h('div', 'c-two');
    if (s.ran) { var a = h('div', 'c-choice'); a.append(btn('Continue last conversation', 'outline', function () { start(s, false); }), h('p', 'meta', 'It remembers the plan and goes on where it stopped.')); two.append(a); }
    var b = h('div', 'c-choice'); b.append(btn('Start clean', 'outline', function () { start(s, true); }), h('p', 'meta', 'A new helper with a fresh memory reads the ticket again.'));
    two.append(b); card.append(two); return card;
  }
  function lastLive(s) { for (var i = s.thread.length - 1; i >= 0; i--) if (s.thread[i].live) return s.thread[i]; return null; }
  function openAsk(s) { if (s.s === 'none') return null; for (var i = 0; i < s.thread.length; i++) if (s.thread[i].ask && !s.thread[i].done) return s.thread[i]; return null; }
  function thread(s, pane) {
    var box = h('div', 'c-thread'); box.setAttribute('role', 'log'); box.setAttribute('aria-label', 'Conversation with the helper'); box.tabIndex = 0;
    var inner = h('div', 'c-col'), firstFile = !pane, m4 = !pane, stopped = s.s === 'none' && s.tk;
    if (!s.thread.length && !stopped) inner.append(h('p', 'c-event', s.shell ? 'A plain terminal has no conversation.' : 'Say what you need. This chat belongs to no ticket.'));
    s.thread.forEach(function (it) {
      if (it.e) inner.append(h('p', 'c-event', it.e));
      else if (it.m) { var m = h('div', 'c-msg'); m.append(h('p', '', it.m), h('span', 'c-at', it.at)); if (m4 && st.marks) { m.append(mark(4)); m4 = false; } inner.append(m); }
      else if (it.you) inner.append(h('div', 'c-msg you', it.you));
      else if (it.files) { var fr = h('div', 'c-files'); it.files.forEach(function (f) { fr.append(fileCard(f, firstFile)); firstFile = false; }); inner.append(fr); }
      else if (it.live) { if (s.s !== 'run' || it !== lastLive(s)) return; var lv = h('div', 'c-live'); lv.setAttribute('role', 'status'); var lt = h('span', 'c-live-t'); lt.append(h('strong', '', it.live), h('span', 'meta', it.sub)); lv.append(glyph('run'), lt); inner.append(lv); }
      else if (it.old) { var o = h('div', 'c-old'); o.append(h('span', 'meta', it.old + ' · kept'), btn('Open it again', 'ghost sm', function () { reopen(s, it); })); inner.append(o); }
      else if (it.ask) {
        var qc = h('div', 'c-ask' + (it.done || stopped ? ' done' : '')); qc.append(h('span', 'c-word ' + (stopped || it.done ? '' : 'wait'), it.done ? 'Answered' : stopped ? 'Asked before it stopped' : 'The helper asks'), h('h2', 'c-ask-q', it.ask), h('p', 'meta', it.sub));
        if (it.done) qc.append(h('p', 'c-ask-a', 'You: ' + it.done));
        else if (!stopped) { var or = h('div', 'c-ask-o'); it.opts.forEach(function (o2, n) { or.append(btn(o2, n === it.rec ? 'primary' : 'outline', function () { answer(s, it, o2); })); }); qc.append(or, h('p', 'meta', 'Or type another answer below.')); }
        inner.append(qc);
      }
    });
    if (stopped) inner.append(startCard(s));
    box.append(inner); return box;
  }
  function send(s, text) {
    text = text.trim(); if (!text) return; s.draft = '';
    var a = openAsk(s); if (a) return answer(s, a, text);
    s.thread.push({ you: text }, { m: 'Got it. I will take that into account.', at: 'now' });
    if (s.s === 'idle') { s.s = 'run'; s.last = 'Working on your message'; s.time = 'now'; s.thread.push({ live: 'Working on your message', sub: 'Just started' }); }
    render();
  }
  function composer(s, hasAsk, sfx) {
    var f = h('form', 'c-composer'), col = h('div', 'c-col c-comp-in');
    var ta = h('textarea', 'input c-ta'); ta.rows = 2; ta.dataset.fk = 'composer' + sfx; ta.value = s.draft || '';
    ta.placeholder = hasAsk ? 'Type another answer…' : 'Message the helper…'; ta.setAttribute('aria-label', (hasAsk ? 'Answer the helper on ' : 'Message the helper on ') + s.k);
    ta.addEventListener('input', function () { s.draft = ta.value; });
    ta.addEventListener('keydown', function (e) { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(s, ta.value); } });
    var sb = h('button', 'btn ' + (hasAsk ? 'outline' : 'primary'), 'Send'); sb.type = 'submit'; sb.dataset.fk = 'send' + sfx;
    f.addEventListener('submit', function (e) { e.preventDefault(); send(s, ta.value); });
    col.append(ta, sb); f.append(col); return f;
  }
  function terminal(s, sfx) {
    var wrap = h('div', 'c-term-w'), pre = h('pre', 'c-term'); pre.setAttribute('role', 'log'); pre.setAttribute('aria-label', 'Terminal of ' + s.k); pre.tabIndex = 0;
    var off = s.s === 'none' && s.tk;
    pre.textContent = (off && !s.log.length) ? 'No helper is running on ' + s.k + '.\nSwitch to Conversation to start one.' : ['tmux · ' + s.k.toLowerCase().replace(/\s+/g, '-') + ' · demo, not a real terminal', ''].concat(s.log).join('\n');
    wrap.append(pre);
    if (!off) {
      var f = h('form', 'c-term-in'), lab = h('label', 'c-prompt', s.shell ? '$' : '>'), inp = h('input', 'c-term-i'); inp.type = 'text'; inp.id = 'c-term-i' + sfx; lab.htmlFor = inp.id; inp.dataset.fk = 'term' + sfx;
      inp.setAttribute('aria-label', 'Type in the terminal of ' + s.k); inp.autocomplete = 'off'; inp.spellcheck = false; inp.value = s.tdraft || ''; inp.placeholder = 'Type here, press Enter';
      inp.addEventListener('input', function () { s.tdraft = inp.value; });
      /* terminal and conversation stay separate: a typed line goes to the terminal only */
      f.addEventListener('submit', function (e) { e.preventDefault(); var v = inp.value; if (!v.trim()) return; s.tdraft = ''; s.log.push((s.shell ? '$ ' : '> ') + v); render(); });
      f.append(lab, inp); wrap.append(f);
    }
    return wrap;
  }
  function menu(s, variant, sfx) {
    var d = h('details', 'c-more'), sm = h('summary', 'btn ghost icon sm'); sm.setAttribute('aria-label', 'More for ' + s.k); sm.title = 'More'; sm.dataset.fk = 'more' + sfx; sm.append(ico('more'));
    var m = h('div', 'menu c-menu'); m.setAttribute('role', 'menu');
    function mi(text, fn, cls) { var b = h('button', 'menu-item' + (cls ? ' ' + cls : ''), text); b.type = 'button'; b.setAttribute('role', 'menuitem'); b.addEventListener('click', function () { d.open = false; fn(); }); m.append(b); }
    if (st.page !== 'focus' && variant !== 'full') { if (variant !== 'right') mi('Move to the right', function () { set({ mode: 'right' }); }); if (variant !== 'bottom') mi('Move to the bottom', function () { set({ mode: 'bottom' }); }); }
    if (s.tk && s.s !== 'none') mi('Start clean with a fresh memory', function () { s.stopAt = 'a moment ago'; start(s, true); });
    var danger = null;
    if (s.tk && s.s !== 'none') danger = ['Stop this helper', function () { stop(s); }];
    if (!s.tk && s.k !== 'Manager') danger = ['Close this ' + (s.shell ? 'terminal' : 'chat'), function () { var i = S.indexOf(s); S.splice(i, 1); set({ cur: 0, cur2: -1, split: false, pane: 0, view: 'list' }); }];
    if (danger) { if (m.children.length) { var hr = h('div', 'c-menu-sep'); hr.setAttribute('role', 'separator'); m.append(hr); } mi(danger[0], danger[1], 'danger'); }
    if (!m.children.length) return null;
    d.append(sm, m); return d;
  }
  function markRows() { var on = st.split && st.pane === 1 ? st.cur2 : st.cur; $$('.c-row[data-i]').forEach(function (r) { if (+r.dataset.i === on) r.setAttribute('aria-current', 'true'); else r.removeAttribute('aria-current'); }); }
  function setPane(p) {
    if (!st.split || st.pane === p) return; st.pane = p;
    $$('.c-conv').forEach(function (c) { c.classList.toggle('on', +c.dataset.pane === p); }); markRows(); syncUrl();
  }
  function conv(variant, pane) {
    var s = S[pane ? st.cur2 : st.cur] || S[0], ask = openAsk(s), tkey = pane ? 'term2' : 'term', term = s.shell ? 'terminal' : st[tkey], sfx = pane ? '2' : '', marks = st.marks && !pane;
    var box = h('section', 'c-conv' + (st.split && st.pane === pane ? ' on' : '')); box.setAttribute('aria-label', s.k + ', ' + s.t); box.dataset.pane = pane;
    box.addEventListener('pointerdown', function () { setPane(pane); }, true); box.addEventListener('focusin', function () { setPane(pane); });
    var head = h('header', 'c-head'), hin = h('div', 'c-col c-head-in');
    if (variant !== 'full') { var bk = btn('', 'ghost icon sm c-back', function () { set({ view: 'list' }); }, 'back' + sfx); bk.setAttribute('aria-label', 'Back to all helpers'); bk.append(ico('back')); hin.append(bk); }
    var tt = h('div', 'c-title'), t1 = h('h2', 'c-title-1', s.tk ? s.t : s.k), t2 = h('p', 'c-title-2');
    t2.append(glyph(s.s), h('span', 'c-word ' + s.s, word(s)), h('span', 'c-title-m', (s.tk ? ' · ' + s.k : ' · no ticket') + (s.step && s.s !== 'none' ? ' · step ' + s.step[0] + ' of ' + s.step[1] : '')));
    tt.append(t1, t2); hin.append(tt);
    var seg = h('div', 'segmented c-flip'); seg.setAttribute('role', 'group'); seg.setAttribute('aria-label', 'Show as');
    [['chat', 'Conversation'], ['terminal', 'Terminal']].forEach(function (v) { var o = {}; o[tkey] = v[0]; var b = btn(v[1], 'sm', function () { set(o); }, 'flip-' + v[0] + sfx); b.setAttribute('aria-pressed', String(term === v[0])); if (s.shell && v[0] === 'chat') { b.disabled = true; b.title = 'A plain terminal has no conversation'; } seg.append(b); });
    var fw = h('div', 'c-flip-w'); fw.append(seg); if (marks) fw.append(mark(5)); hin.append(fw);
    var acts = h('div', 'c-acts');
    if (pane) { var cx = btn('', 'ghost icon sm', function () { set({ split: false, pane: 0 }); }, 'split-x'); cx.setAttribute('aria-label', 'Close this side'); cx.title = 'Close this side'; cx.append(ico('close')); acts.append(cx); }
    else {
      if (variant !== 'right') { var sp = btn('', 'ghost icon sm c-split-b', function () { set({ split: !st.split, pane: 0, view: 'chat' }); }, 'split'); sp.setAttribute('aria-label', 'Side by side: show two helpers'); sp.setAttribute('aria-pressed', String(st.split)); sp.title = 'Side by side'; sp.append(ico('split')); acts.append(sp); if (marks) { var m11 = mark(11); m11.classList.add('c-split-b'); acts.append(m11); } }
      if (variant === 'full') { var lf = btn('', 'outline sm', leaveFull, 'full'); lf.append(document.createTextNode('Leave full screen '), h('kbd', '', 'Esc')); acts.append(lf); }
      else { var fb2 = btn('', 'ghost icon sm', function () { set({ mode: 'full', view: 'chat' }); }, 'full'); fb2.setAttribute('aria-label', 'Full screen: only this conversation'); fb2.title = 'Full screen'; fb2.append(ico('full')); acts.append(fb2); if (marks) acts.append(mark(8)); }
    }
    var mm = menu(s, variant, sfx); if (mm) acts.append(mm);
    if (!pane && (variant === 'right' || (variant === 'bottom' && narrow()))) acts.append(closeBtn('min2'));
    hin.append(acts); head.append(hin); box.append(head);
    if (term === 'terminal') box.append(terminal(s, sfx));
    else { box.append(thread(s, pane)); if (!(s.s === 'none' && s.tk)) box.append(composer(s, !!ask, sfx)); }
    return box;
  }
  function strip() {
    var n = h('nav', 'c-strip'); n.setAttribute('aria-label', 'Helpers that need you'); var any = false;
    S.forEach(function (s, i) {
      if (s.s !== 'wait') return; any = true;
      var b = h('button', 'c-pillb'); b.type = 'button'; b.dataset.fk = 'strip' + i; if (i === st.cur) b.setAttribute('aria-current', 'true');
      b.append(glyph('wait'), h('span', 'c-word wait', 'Needs you'), h('span', 'c-pillb-t', s.tk ? s.t : s.k)); b.addEventListener('click', function () { openSess(i, { term: 'chat' }); }); n.append(b);
    });
    if (!any) n.append(h('span', 'meta', 'Nobody needs you right now.'));
    return n;
  }
  function inbox(variant) {
    var b = h('div', 'c-inbox'); b.dataset.variant = variant; b.dataset.view = variant === 'full' ? 'chat' : st.view;
    if (variant === 'full') b.append(strip()); else b.append(list(variant));
    if (st.split && variant !== 'right') { var w = h('div', 'c-split'); w.append(conv(variant, 0), conv(variant, 1)); b.append(w); }
    else b.append(conv(variant, 0));
    return b;
  }
  function newChat() { nChat++; S.push({ k: 'Chat ' + nChat, t: 'No ticket', s: 'idle', tk: 0, last: 'Ready for your first message', time: 'now', step: null, thread: [], log: ['● New chat. No ticket.', ''] }); closePal(true); openSess(S.length - 1, { term: 'chat' }); var c = $('[data-fk=' + activeFk('composer') + ']'); if (c) c.focus(); }
  function newTerm() { nTerm++; S.push({ k: 'Terminal ' + nTerm, t: 'No ticket', s: 'idle', tk: 0, shell: 1, last: 'Plain terminal', time: 'now', step: null, thread: [], log: ['~/workspace $ '] }); closePal(true); openSess(S.length - 1, { term: 'terminal' }); var c = $('[data-fk=' + activeFk('term') + ']'); if (c) c.focus(); }

  /* ---------- the other pages (mock) ---------- */
  function pageHead(title, line) { var d = h('div', 'c-pg-h'); d.append(h('h1', '', title), h('p', 'meta', line)); return d; }
  function tRow(i, n2) {
    var s = S[i], r = h('div', 'c-trow'); var w = h('span', 'c-trow-s'); w.append(glyph(s.s), h('span', 'c-word ' + s.s, word(s)));
    var t = h('span', 'c-trow-t'); t.append(h('strong', '', s.t), h('span', 'meta', s.k + (s.s === 'none' ? ' · ' + s.last : ' · step ' + s.step[0] + ' of ' + s.step[1])));
    var b = btn(OPEN[s.s], 'outline sm', function () { openSess(i, { term: 'chat', mode: st.mode === 'bubble' ? st.last : st.mode }); }, 'open' + i); b.setAttribute('aria-label', OPEN[s.s] + ': ' + s.t + ' in Focus');
    r.append(t, w, b); if (n2 && st.marks) r.append(mark(2)); return r;
  }
  var PG = {
    home: function () {
      var p = h('div', 'c-pg'); p.append(pageHead('Home', 'Monday · ' + (needs() ? needs() + ' helper needs you' : 'nobody needs you') + ', ' + S.filter(function (s) { return s.s === 'run' && s.tk; }).length + ' are working.'));
      var c = h('section', 'card c-card'); c.append(h('h2', '', 'Needs you')); var any = false;
      S.forEach(function (s, i) { if (s.s === 'wait') { any = true; c.append(tRow(i, false)); } }); if (!any) c.append(h('p', 'meta', 'Nothing right now.')); p.append(c);
      var w = h('section', 'card c-card'); w.append(h('h2', '', 'Working now')); S.forEach(function (s, i) { if (s.s === 'run' && s.tk) w.append(tRow(i, false)); }); p.append(w);
      p.append(h('p', 'meta', 'Try it: open Focus with the round bubble, flip to Terminal, type a line, then change the page in the side menu. Focus stays open as you left it.')); return p;
    },
    tickets: function () {
      var p = h('div', 'c-pg'); p.append(pageHead('Tickets', 'Each ticket has one button into Focus. The word says what will happen.'));
      var c = h('section', 'card c-card'); var first = true; S.forEach(function (s, i) { if (s.tk) { c.append(tRow(i, first)); first = false; } }); p.append(c); return p;
    },
    review: function () {
      var p = h('div', 'c-pg'); p.append(pageHead('Review', 'Results the helpers finished and want you to look at.'));
      [['Steer a helper from the dashboard', 'page', 'steer-demo.html'], ['Phone width and zoom', 'phone', 'home-390.png']].forEach(function (r) { var c = h('section', 'card c-card c-rev'); var t = h('div', ''); t.append(h('h2', '', r[0]), h('p', 'meta', r[2])); c.append(thumb(r[1]), t); p.append(c); });
      return p;
    }
  };
  function bubble() {
    var w = h('div', 'c-bubble-w'), b = h('button', 'c-bubble'); b.type = 'button'; b.dataset.fk = 'bubble'; var n = needs();
    b.setAttribute('aria-label', 'Open Focus' + (n ? ': ' + n + (n === 1 ? ' helper needs you' : ' helpers need you') : ': nobody needs you')); b.title = 'Focus (Ctrl/Cmd+J)';
    b.append(ico('chat', 24)); if (n) b.append(h('span', 'c-bubble-n', String(n)));
    b.addEventListener('click', function () { var o = { mode: st.last }; var wi = -1; S.forEach(function (s, i) { if (wi < 0 && s.s === 'wait') wi = i; }); if (wi >= 0 && !st.split) { o.cur = wi; o.view = 'chat'; o.term = 'chat'; } set(o); });
    w.append(b); if (st.marks) w.append(mark(7)); return w;
  }

  /* ---------- features sheet ---------- */
  function sheet() {
    var a = h('aside', 'c-sheet'); a.setAttribute('role', 'dialog'); a.setAttribute('aria-label', 'Features'); a.id = 'c-sheet';
    var top = h('div', 'c-sheet-top'), hd = h('div', 'c-sheet-h'); var x = btn('', 'ghost icon sm', function () { set({ sheet: false, feat: 0 }); var f = $('#c-feat-btn'); if (f) f.focus(); }, 'sheet-x'); x.setAttribute('aria-label', 'Close Features'); x.append(ico('close'));
    hd.append(h('h2', '', 'Features'), x);
    var done = Object.keys(picks).filter(function (k) { return picks[k]; }).length, bar = h('div', 'c-sheet-bar'); var cnt = h('span', 'meta', done + ' of ' + F.length + ' picked'); cnt.setAttribute('role', 'status');
    bar.append(cnt, btn('Copy my picks', 'outline sm', function () {
      var txt = 'Focus v4c (calm inbox) picks\n' + F.map(function (f, i) { return (i + 1) + '. ' + f.t + ': ' + (picks[i + 1] || 'no pick'); }).join('\n');
      var ok = function () { toast('Picks copied'); }; try { if (window.UI && UI.copyText) UI.copyText(txt).then(ok); else navigator.clipboard.writeText(txt).then(ok); } catch (e) {}
    }));
    top.append(hd, bar); a.append(top);
    var lab = h('label', 'c-marks'), cb = h('input', 'switch'); cb.type = 'checkbox'; cb.checked = st.marks; cb.dataset.fk = 'marks'; cb.addEventListener('change', function () { set({ marks: cb.checked }); }); lab.append(cb, h('span', '', 'Show the numbers on the product')); a.append(lab);
    F.forEach(function (f, i) {
      var n = i + 1, c = h('article', 'c-feat' + (st.feat === n ? ' on' : '')); c.id = 'c-feat-' + n;
      var t = h('h3', 'c-feat-t'); var num = h('span', 'c-n static', String(n)); if (picks[n]) num.dataset.pick = picks[n]; t.append(num, h('span', '', f.t)); c.append(t, h('p', '', f.what));
      var dl = h('dl', 'c-feat-d'); dl.append(h('dt', '', 'How in orch'), h('dd', '', f.how), h('dt', '', 'New work'), h('dd', '', f.size + ': ' + f.why)); c.append(dl);
      var r = h('div', 'c-feat-r'), seg = h('div', 'segmented'); seg.setAttribute('role', 'group'); seg.setAttribute('aria-label', 'Your pick for ' + f.t);
      ['keep', 'maybe', 'drop'].forEach(function (p) { var b = btn(p.charAt(0).toUpperCase() + p.slice(1), 'sm', function () { picks[n] = picks[n] === p ? '' : p; store.set('fv4c-picks', JSON.stringify(picks)); render(); }, 'pick' + n + p); b.setAttribute('aria-pressed', String(picks[n] === p)); seg.append(b); });
      r.append(seg, btn('Show me', 'ghost sm', function () { showMe(n); }, 'show' + n)); c.append(r); a.append(c);
    });
    return a;
  }
  function showMe(n) {
    var o = {}, sh = F[n - 1].show; Object.keys(sh).forEach(function (k) { o[k] = sh[k]; }); o.feat = n; o.big = '';
    if (n === 3 && S[4] && S[4].k === 'ORCH-189' && S[4].s !== 'none') { S[4].s = 'none'; S[4].stopAt = 'a moment ago'; S[4].last = 'Stopped just now'; S[4].time = 'now'; S[4].thread = S[4].thread.filter(function (x) { return !x.live; }); S[4].thread.push({ e: 'Stopped · just now' }); }
    if (n === 8 && !o.page) o.page = st.page;
    if (window.innerWidth < 1500 || o.mode === 'full' || o.pal) o.sheet = false;
    var pal2 = o.pal; delete o.pal; set(o); if (pal2) openPal();
  }

  /* ---------- command palette ---------- */
  var pal = { q: '', i: 0 };
  function cmds() {
    var out = [], ord = S.map(function (s, i) { return i; }).sort(function (a, b) { var w = { wait: 0, run: 1, idle: 2, none: 3 }; return w[S[a].s] - w[S[b].s]; });
    var p = st.split && st.pane === 1, tkey = p ? 'term2' : 'term';
    ord.forEach(function (i) { var s = S[i]; out.push({ t: s.tk ? s.k + ' · ' + s.t : s.k, hint: word(s), s: s.s, key: (s.k + ' ' + s.t + ' ' + word(s)).toLowerCase(), run: function () { closePal(true); openSess(i); } }); });
    out.push({ t: 'New chat', ic: 'chat', hint: 'No ticket', key: 'new chat helper', run: newChat });
    out.push({ t: 'New terminal', ic: 'term', hint: 'No ticket', key: 'new terminal plain shell tmux', run: newTerm });
    out.push({ t: st[tkey] === 'terminal' ? 'Show the conversation' : 'Show the terminal', ic: 'flip', hint: 'Flip this pane', key: 'terminal conversation flip switch chat', run: function () { closePal(true); openSess(p ? st.cur2 : st.cur, { term: st[tkey] === 'terminal' ? 'chat' : 'terminal' }); } });
    out.push({ t: st.split ? 'One helper at a time' : 'Side by side', ic: 'split', hint: 'Two helpers', key: 'side by side split two several', run: function () { closePal(true); set({ split: !st.split, pane: 0, view: 'chat', mode: st.page !== 'focus' && st.mode !== 'full' ? 'bottom' : st.mode }); } });
    out.push({ t: 'Full screen', ic: 'full', hint: 'Only the conversation', key: 'full screen zen focus', run: function () { closePal(true); set({ mode: 'full', view: 'chat' }); } });
    Object.keys(PAGES).forEach(function (pg) { out.push({ t: 'Go to ' + PAGES[pg], ic: 'page', hint: 'Page', key: 'go page ' + pg, run: function () { closePal(true); go(pg); } }); });
    var qq = pal.q.trim().toLowerCase(); return qq ? out.filter(function (c) { return c.key.indexOf(qq) >= 0 || c.t.toLowerCase().indexOf(qq) >= 0; }) : out;
  }
  function drawPal() {
    var host = $('#c-pal-host'); host.textContent = ''; if (!st.pal) return;
    var sc = h('div', 'c-scrim'); sc.addEventListener('click', function (e) { if (e.target === sc) closePal(); });
    var d = h('div', 'c-pal'); d.setAttribute('role', 'dialog'); d.setAttribute('aria-modal', 'true'); d.setAttribute('aria-label', 'Jump to');
    var inp = h('input', 'input c-pal-i'); inp.type = 'text'; inp.value = pal.q; inp.placeholder = 'Type a ticket, “new chat”, “manager”, “terminal”…'; inp.setAttribute('aria-label', 'Jump to a helper or an action'); inp.setAttribute('role', 'combobox'); inp.setAttribute('aria-expanded', 'true'); inp.setAttribute('aria-controls', 'c-pal-l'); inp.autocomplete = 'off';
    var ul = h('ul', 'c-pal-l'); ul.id = 'c-pal-l'; ul.setAttribute('role', 'listbox');
    function fill() {
      var cs = cmds(); if (pal.i >= cs.length) pal.i = Math.max(0, cs.length - 1); ul.textContent = '';
      cs.forEach(function (c, i) { var li = h('li', 'c-pal-o'); li.id = 'c-pal-o' + i; li.setAttribute('role', 'option'); li.setAttribute('aria-selected', String(i === pal.i)); li.append(c.s ? glyph(c.s) : ico(c.ic), h('span', 'c-pal-t', c.t), h('span', 'c-word ' + (c.s || ''), c.hint)); li.addEventListener('click', c.run); ul.append(li); });
      if (!cs.length) ul.append(h('li', 'c-pal-e meta', 'Nothing matches. Try a ticket name or “new chat”.'));
      inp.setAttribute('aria-activedescendant', cs.length ? 'c-pal-o' + pal.i : ''); var on = $('[aria-selected=true]', ul); if (on && on.scrollIntoView) on.scrollIntoView({ block: 'nearest' });
    }
    inp.addEventListener('input', function () { pal.q = inp.value; pal.i = 0; fill(); });
    /* the palette is modal: Tab stays in the field (the list is driven with the arrows) */
    d.addEventListener('keydown', function (e) {
      var cs = cmds();
      if (e.key === 'Tab') { e.preventDefault(); inp.focus(); }
      else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); if (cs.length) pal.i = (pal.i + (e.key === 'ArrowDown' ? 1 : -1) + cs.length) % cs.length; fill(); }
      else if (e.key === 'Enter') { e.preventDefault(); if (cs[pal.i]) cs[pal.i].run(); }
    });
    var foot = h('p', 'c-pal-f meta'); foot.append(h('kbd', '', '↑'), h('kbd', '', '↓'), document.createTextNode(' choose  '), h('kbd', '', 'Enter'), document.createTextNode(' open  '), h('kbd', '', 'Esc'), document.createTextNode(' close'));
    d.append(inp, ul, foot); sc.append(d); host.append(sc); fill(); inp.focus();
  }
  var palBack = null;
  function openPal() { palBack = document.activeElement && document.activeElement.dataset ? document.activeElement.dataset.fk : null; pal.q = ''; pal.i = 0; st.pal = true; drawPal(); }
  function closePal(quiet) { if (!st.pal) return; st.pal = false; drawPal(); if (!quiet && palBack) { var n = $('[data-fk="' + palBack + '"]'); if (n) n.focus(); } }

  /* ---------- render ---------- */
  function syncUrl() {
    var p = new URLSearchParams(); p.set('page', st.page); p.set('mode', st.mode); p.set('view', st.view); p.set('term', st.term); p.set('cur', String(st.cur));
    if (st.split) { p.set('split', '1'); p.set('cur2', String(st.cur2)); p.set('term2', st.term2); }
    if (st.sheet) p.set('sheet', '1'); if (st.feat) p.set('feat', String(st.feat)); if (!st.marks) p.set('marks', '0');
    try { history.replaceState(null, '', location.pathname + '?' + p.toString()); } catch (e) {}
  }
  function render() {
    if (!S[st.cur]) st.cur = 0;
    if (st.split && (!S[st.cur2] || st.cur2 === st.cur)) { st.cur2 = -1; S.forEach(function (s, i) { if (st.cur2 < 0 && i !== st.cur && s.s === 'run') st.cur2 = i; }); if (st.cur2 < 0) st.cur2 = st.cur === 0 ? 1 : 0; }
    if (!st.split) st.pane = 0;
    var act = document.activeElement, fk = act && act.dataset ? act.dataset.fk : null;
    var stage = $('#c-stage'), layer = $('#c-layer'), sh = $('#c-sheet-host'), body = document.body;
    var full = st.mode === 'full', onFocus = st.page === 'focus', dock = !full && !onFocus && st.mode !== 'bubble' ? st.mode : '';
    body.classList.toggle('c-zen', full); body.classList.toggle('c-has-sheet', st.sheet);
    body.classList.toggle('c-dock-right', dock === 'right'); body.classList.toggle('c-dock-bottom', dock === 'bottom');
    var sb = $('.shell-body'); if (sb) body.style.setProperty('--c-left', Math.max(0, Math.round(sb.getBoundingClientRect().left)) + 'px');
    stage.textContent = ''; layer.textContent = '';
    var nav = h('nav', 'segmented c-pages'); nav.setAttribute('aria-label', 'Demo pages');
    Object.keys(PAGES).forEach(function (p) { var b = btn(PAGES[p], 'sm', function () { go(p); }, 'pg-' + p); b.setAttribute('aria-pressed', String(st.page === p)); nav.append(b); });
    stage.append(nav);
    if (onFocus) { if (!full) stage.append(inbox('page')); } else stage.append(PG[st.page]());
    if (full) { var fp = h('div', 'c-panel'); fp.dataset.mode = 'full'; fp.append(inbox('full')); layer.append(fp); }
    else if (!onFocus) {
      if (st.mode === 'bubble') layer.append(bubble());
      else { var pn = h('div', 'c-panel'); pn.dataset.mode = st.mode; pn.setAttribute('role', 'complementary'); pn.setAttribute('aria-label', 'Focus'); pn.append(inbox(st.mode)); layer.append(pn); }
    }
    markRows();
    sh.textContent = ''; if (st.sheet) { sh.append(sheet()); if (st.feat) { var fc = $('#c-feat-' + st.feat); if (fc && fc.scrollIntoView) fc.scrollIntoView({ block: 'center' }); } }
    $$('.sidebar a[data-page]').forEach(function (a) { if (a.dataset.page === st.page) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current'); });
    var fbn = $('#c-feat-btn'); if (fbn) fbn.setAttribute('aria-expanded', String(st.sheet));
    $$('.c-thread,.c-term').forEach(function (n) { n.scrollTop = n.scrollHeight; });
    if (fk) { var again = $('[data-fk="' + fk + '"]'); if (again && again !== document.activeElement) { try { again.focus({ preventScroll: true }); } catch (e) {} } }
    syncUrl();
  }

  /* ---------- wiring ---------- */
  var want = { Home: 'home', Tickets: 'tickets', Review: 'review', Focus: 'focus' };
  $$('.sidebar a.nav-item').forEach(function (a) { var p = want[a.getAttribute('aria-label')]; if (!p) return; a.dataset.page = p; a.dataset.fk = 'side-' + p; a.addEventListener('click', function (e) { e.preventDefault(); go(p); }); });
  var fb = $('#c-feat-btn'); if (fb) { fb.dataset.fk = 'feat-btn'; fb.addEventListener('click', function () { set({ sheet: !st.sheet, feat: 0 }); }); }
  document.addEventListener('keydown', function (e) {
    var k = (e.key || '').toLowerCase(), mod = e.ctrlKey || e.metaKey;
    if (mod && k === 'k') { e.preventDefault(); if (st.pal) closePal(); else openPal(); return; }
    if (mod && k === 'j') { e.preventDefault(); toggleLayer(); return; }
    if (k === 'escape') {
      if (st.pal) { e.preventDefault(); closePal(); return; }
      var om = $('details.c-more[open]'); if (om) { om.open = false; var sm = $('summary', om); if (sm) sm.focus(); return; }
      if (st.sheet) { set({ sheet: false, feat: 0 }); if (fb) fb.focus(); return; }
      if (st.mode === 'full') leaveFull();
    }
  });
  document.addEventListener('click', function (e) { var om = $('details.c-more[open]'); if (om && !om.contains(e.target)) om.open = false; });
  var wasNarrow = narrow(), lastLeft = '';
  window.addEventListener('resize', function () { var sb = $('.shell-body'), l = sb ? String(Math.round(sb.getBoundingClientRect().left)) : ''; if (narrow() !== wasNarrow || l !== lastLeft) { wasNarrow = narrow(); lastLeft = l; render(); } });
  render(); if (st.pal) openPal();
})();
