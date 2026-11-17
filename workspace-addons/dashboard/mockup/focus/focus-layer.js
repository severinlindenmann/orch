/* Focus layer draft (ORCH-251, v3): one always-open layer over every page. Demo data; picks stay in this browser. */
(function () {
  var F = [
    [1, 'Focus start page', 'One screen of every session: who needs you first, then who is working, then tickets without a session.', 'orch run list (signal, waiting on), ticket status, last screen line.', 'New page; data exists.'],
    [2, 'Focus button on every ticket', 'Watch a running ticket, Answer a waiting one, Start one with no session. Same button on the Tickets list and the ticket page.', 'Run signal of the ticket (working, waiting, none). Waiting on a command shows Approve, waiting on a question shows Answer.', 'Small: one button per row.'],
    [3, 'Continue or start fresh', 'Start asks: continue the last conversation, or begin clean with a new context window. Older sessions are listed.', 'The session id kept on the ticket: the next start resumes it. Only the last session is kept today.', 'Medium: a list of older sessions needs new storage.'],
    [4, 'Chat or real terminal', 'Chat is plain messages. Terminal is the real tmux screen: type, copy, paste, like Terminal.app.', 'The ticket’s tmux session. Safe start: read-only screen plus Let me type. Chat shows the helper’s messages and ticket events.', 'Large: a browser terminal (xterm.js + bridge) is new; several viewers shrink one tmux window.'],
    [5, 'Sessions without a ticket', 'Open a Manager, a Chat helper or a plain terminal that belongs to no ticket.', 'Same tmux socket, a name that is not a ticket id.', 'Medium: sessions outside the ticket limit.'],
    [6, 'Always-open layer', 'Focus belongs to the whole dashboard, not one page. Go from Home to Tickets to Review and your terminal stays as you left it. Dock right or bottom.', 'Nothing to store. Cheapest: pages swap softly (Turbo style) so the layer stays; fallback: a pop-out window.', 'Large: today every page is a full load.'],
    [7, 'Full screen', 'The layer takes the whole window: no menu, no page. Esc or the strip brings it back.', 'Nothing.', 'Small.'],
    [8, 'Status strip and side by side', 'A thin strip is always visible: one chip per session, Needs you first. Click to switch at once; show two sessions next to each other.', 'run signal every few seconds. Live slots are limited (live_max): extra starts wait in line; idle sessions close after about an hour.', 'Medium: live updates and the in-line and closed states.'],
    [9, 'Results shelf', 'Pictures, pages, tables and pull requests as small visual cards at the top of a session instead of text.', 'Files attached to the ticket and the PR links on it.', 'Medium: thumbnails per file type.']
  ];
  var S = [
    { k: 'ORCH-238', t: 'Add files and notes to a ticket', s: 'wait', note: 'Waiting for your answer: keep the old file name?', last: 'Asked: keep the old file name?', step: '3 of 5' },
    { k: 'ORCH-228', t: 'Phone width and zoom', s: 'run', note: 'Opening the pull request', last: '● Opening the pull request…', step: '4 of 5' },
    { k: 'ORCH-232', t: 'Insights and usage counts', s: 'run', note: 'Running tests', last: '● node --test tests/insights', step: '2 of 6' },
    { k: 'ORCH-247', t: 'Steer a helper from the dashboard', s: 'idle', note: 'Idle 18 min', last: '> ', step: '5 of 5' },
    { k: 'ORCH-189', t: 'Manager view', s: 'none', note: 'No session', last: '', step: '0 of 4' },
    { k: 'Manager', t: 'No ticket', s: 'run', note: 'Looking after 4 helpers', last: '● orch run list', step: '' }
  ];
  var WORD = { wait: 'Needs you', run: 'Working', idle: 'Idle', none: 'No session' };
  var BTN = { wait: 'Answer', run: 'Watch', idle: 'Open', none: 'Start' };
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  function h(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }
  function btn(text, cls, fn) { var b = h('button', 'btn ' + (cls || 'sm'), text); b.type = 'button'; if (fn) b.addEventListener('click', fn); return b; }
  var store = { get: function (k) { try { return localStorage.getItem(k); } catch (e) { return null; } }, set: function (k, v) { try { localStorage.setItem(k, v); } catch (e) {} } };
  var picks = {}; try { picks = JSON.parse(store.get('fl-picks') || '{}'); } catch (e) {}
  var st = { page: 'tickets', mode: 'right', open: [1, 0], cur: 1, view: 'session', term: 'terminal', split: false, ask: -1, menu: '' };
  var q = new URLSearchParams(location.search);
  ['page', 'mode', 'view', 'term'].forEach(function (k) { if (q.get(k)) st[k] = q.get(k); });
  if (q.get('cur')) st.cur = +q.get('cur'); if (q.get('split')) st.split = true; if (q.get('ask')) st.ask = +q.get('ask'); if (q.get('menu')) st.menu = q.get('menu');
  var logs = {}; S.forEach(function (s, i) { logs[i] = ['$ tmux attach -t ' + s.k.toLowerCase(), s.last]; });

  function mark(n) { var b = h('button', 'fl-n', String(n)); b.type = 'button'; b.dataset.n = n; b.setAttribute('aria-label', 'Feature ' + n + ': ' + F[n - 1][1]); b.addEventListener('click', function () { var r = $('#pick-' + n); if (r) { r.scrollIntoView({ block: 'nearest' }); r.focus(); } }); return b; }
  function dot(s) { var d = h('span', 'fl-dot ' + s); d.setAttribute('role', 'img'); d.setAttribute('aria-label', WORD[s]); return d; }
  function pill(s) { var p = h('span', 'fl-pill ' + s); p.append(dot(s), document.createTextNode(WORD[s])); return p; }
  function openSess(i) { if (st.open.indexOf(i) < 0) st.open.push(i); st.cur = i; st.view = 'session'; st.ask = -1; if (st.mode === 'rail') st.mode = 'right'; render(); }
  function order() { return S.map(function (x, i) { return i; }).sort(function (a, b) { var w = { wait: 0, run: 1, idle: 2, none: 3 }; return w[S[a].s] - w[S[b].s]; }); }

  /* ---------- picks panel ---------- */
  function picker() {
    var box = $('#fl-picks'); box.textContent = '';
    box.append(h('h2', '', 'Your picks'), h('p', 'meta', 'Numbers on the page match these rows. What it does, what orch data it uses, how big the new work is.'));
    F.forEach(function (f) {
      var row = h('div', 'fl-pick'); row.id = 'pick-' + f[0]; row.tabIndex = -1;
      var t = h('div', 'fl-pick-t'); t.append(h('span', 'fl-n static', String(f[0])), h('b', '', f[1])); row.append(t, h('p', '', f[2]));
      var u = h('p', 'meta'); u.append(h('b', '', 'Uses: '), document.createTextNode(f[3])); var w = h('p', 'meta'); w.append(h('b', '', 'To build: '), document.createTextNode(f[4])); row.append(u, w);
      var seg = h('div', 'segmented'); seg.setAttribute('role', 'group'); seg.setAttribute('aria-label', 'Pick for feature ' + f[0]);
      ['keep', 'maybe', 'drop'].forEach(function (o) { var b = btn(o[0].toUpperCase() + o.slice(1), 'sm', function () { picks[f[0]] = picks[f[0]] === o ? '' : o; store.set('fl-picks', JSON.stringify(picks)); paint(); }); b.setAttribute('aria-pressed', picks[f[0]] === o); seg.append(b); });
      row.append(seg); box.append(row);
    });
    var c = btn('Copy my picks', 'sm', function () {
      var txt = F.map(function (f) { return f[0] + '. ' + f[1] + ': ' + (picks[f[0]] || 'no pick'); }).join('\n');
      var done = function () { c.textContent = 'Copied'; setTimeout(function () { c.textContent = 'Copy my picks'; }, 1500); };
      if (navigator.clipboard) navigator.clipboard.writeText(txt).then(done, function () { c.textContent = txt; }); else c.textContent = txt;
    });
    box.append(c);
  }
  function paint() {
    $$('.fl-pick').forEach(function (r) { var n = r.id.slice(5); $$('.segmented button', r).forEach(function (b, i) { b.setAttribute('aria-pressed', picks[n] === ['keep', 'maybe', 'drop'][i]); }); });
    $$('.fl-n:not(.static)').forEach(function (b) { b.dataset.pick = picks[b.dataset.n] || ''; });
    var k = Object.keys(picks).filter(function (n) { return picks[n]; }).length; $('#fl-count').textContent = k + ' of 9 picked';
  }

  /* ---------- the mock pages ---------- */
  function startPop(i) {
    var s = S[i], p = h('div', 'fl-pop'); p.append(h('b', '', 'Start ' + s.k), mark(3));
    p.append(btn('Continue the last conversation', 'primary sm', function () { openSess(i); }), h('span', 'meta', 'Yesterday 16:40 · 4 of 5 steps. The helper remembers what it did.'));
    p.append(btn('New session, clean context', 'sm', function () { openSess(i); }), h('span', 'meta', 'A fresh window; the ticket and its files stay.'));
    return p;
  }
  function ticketBtn(i) {
    var s = S[i], w = h('span', 'fl-act');
    var b = btn(BTN[s.s], s.s === 'wait' ? 'sm' : 'sm', function () { if (s.s === 'none') { st.ask = st.ask === i ? -1 : i; render(); } else openSess(i); });
    w.append(b); if (st.ask === i) w.append(startPop(i)); return w;
  }
  function pageView() {
    var p = h('div', 'fl-pg');
    if (st.page === 'home') {
      p.append(h('h2', '', 'Home'));
      var g = h('div', 'fl-need'); S.filter(function (s) { return s.s === 'wait'; }).forEach(function (s) { var c = h('div', 'fl-card'); c.append(pill('wait'), h('b', '', s.k + ' · ' + s.t), h('span', 'meta', s.note)); c.append(btn('Answer in Focus', 'primary sm', function () { openSess(S.indexOf(s)); })); g.append(c); });
      p.append(h('h3', '', 'Needs you'), g, h('p', 'meta', 'Your other pages work as before. Focus stays open below or beside them.'));
    } else if (st.page === 'review') {
      p.append(h('h2', '', 'Review'), h('p', 'meta', 'Nothing new here for this demo. Switch pages: your Focus session does not reload.'));
    } else {
      p.append(h('h2', '', 'Tickets'));
      var list = h('div', 'fl-rows');
      [0, 1, 2, 3, 4].forEach(function (i) { var s = S[i], r = h('div', 'fl-row'); r.append(dot(s.s), h('span', 'fl-rk', s.k), h('span', 'fl-rt', s.t), h('span', 'meta', WORD[s.s]), ticketBtn(i)); if (i === 0) r.append(mark(2)); list.append(r); });
      p.append(list);
    }
    return p;
  }

  /* ---------- the layer ---------- */
  function shelf() {
    var r = h('div', 'fl-shelf'); r.append(mark(9));
    function card(kind, title, sub) { var c = h('button', 'fl-rc'); c.type = 'button'; var th = h('div', 'fl-th ' + kind); c.append(th, h('b', '', title), h('span', 'meta', sub)); r.append(c); return th; }
    var a = card('shot', 'Phone at 320', 'Screenshot'); a.append(h('i'), h('i'), h('i'));
    var b = card('page', 'Ticket page', 'Open page ↗'); b.append(h('i'), h('i'));
    var cc = card('chart', '6 checks', 'Passed'); [60, 90, 45, 100, 80].forEach(function (v) { var x = h('i'); x.style.setProperty('--v', v + '%'); cc.append(x); });
    var d = card('pr', 'Pull request', '#1252 · running'); d.append(h('em', '', '✓ 5 · ◔ 1'));
    return r;
  }
  function pane(i) {
    var s = S[i], d = h('section', 'fl-pane'); d.setAttribute('aria-label', s.k);
    var top = h('div', 'fl-ph'); top.append(h('b', '', s.k), h('span', 'fl-rt', s.t), pill(s.s));
    if (s.s !== 'none') { var seg = h('div', 'segmented'); ['chat', 'terminal'].forEach(function (m) { var b = btn(m === 'chat' ? 'Chat' : 'Terminal', 'sm', function () { st.term = m; render(); }); b.setAttribute('aria-pressed', st.term === m); seg.append(b); }); top.append(seg, mark(4)); }
    d.append(top);
    if (s.s === 'none') { var e = h('div', 'fl-empty'); e.append(h('b', '', s.k + ' has no session'), startPop(i)); d.append(e); return d; }
    if (i < 5) d.append(shelf());
    var body = h('div', 'fl-body');
    if (st.term === 'terminal') {
      var t = h('pre', 'fl-term'); t.textContent = logs[i].join('\n') + '\n';
      var line = h('label', 'fl-line'); line.append(h('span', '', '> ')); var inp = h('input', 'input'); inp.setAttribute('aria-label', 'Type into ' + s.k); inp.autocomplete = 'off';
      inp.addEventListener('keydown', function (e) { if (e.key === 'Enter' && inp.value) { logs[i].push('> ' + inp.value, '● (demo) sent to the helper'); render(); var n = $('#fl-focus-in-' + i); if (n) n.focus(); } });
      inp.id = 'fl-focus-in-' + i; line.append(inp); var lt = h('label', 'meta fl-lt'); var cb = h('input', 'switch'); cb.type = 'checkbox'; cb.checked = true; cb.setAttribute('aria-label', 'Let me type into the helper’s screen'); lt.append(cb, document.createTextNode(' Let me type (off = watch only)')); body.append(t, line, lt, h('p', 'meta', 'Real tmux in the product: select, copy, paste, edit.'));
    } else {
      var log = h('div', 'fl-chat'); [['Helper', s.note + '.'], ['You', 'Also check 320 px wide.'], ['Helper', 'Done. 320 px passes.']].forEach(function (m) { var b = h('div', 'fl-bub' + (m[0] === 'You' ? ' me' : '')); b.append(h('span', 'meta', m[0]), h('p', '', m[1])); log.append(b); });
      var box = h('div', 'fl-compose'); var inp2 = h('input', 'input'); inp2.placeholder = 'Write a message…'; inp2.setAttribute('aria-label', 'Message'); box.append(inp2, btn('Send', 'sm'));
      body.append(log, box);
    }
    d.append(body); return d;
  }
  function startPage() {
    var d = h('section', 'fl-start'); d.append(mark(1));
    d.append(h('h2', '', 'Focus'));
    var sections = [['wait', 'Needs you'], ['run', 'Working now'], ['idle', 'Idle'], ['none', 'No session']];
    var sl = h('p', 'fl-slots'); sl.append(dot('run'), document.createTextNode(' 3 of 4 live slots used · 1 ticket waiting in line. Idle sessions close after 1 hour.')); d.append(sl);
    sections.forEach(function (sec) {
      var ids = order().filter(function (i) { return S[i].s === sec[0] && i < 5; }); if (!ids.length) return;
      d.append(h('h3', '', sec[1]));
      var g = h('div', 'fl-grid');
      ids.forEach(function (i) { var s = S[i], c = h('div', 'fl-tile ' + s.s); c.append(pill(s.s), h('b', '', s.k + ' · ' + s.t));
        if (s.last) c.append(h('code', 'fl-peek', s.last)); if (s.step) { var bar = h('div', 'fl-bar'); var f = h('i'); f.style.width = (parseInt(s.step, 10) / parseInt(s.step.split(' of ')[1], 10) * 100) + '%'; bar.append(f); c.append(bar, h('span', 'meta', 'Step ' + s.step)); }
        c.append(ticketBtn(i)); if (s.s === 'idle') c.append(btn('Stop, free the slot', 'ghost sm')); if (s.s === 'none') c.append(h('span', 'meta', 'Closed after 1 hour idle. Start continues it.')); g.append(c); });
      d.append(g);
    });
    d.append(h('h3', '', 'Without a ticket'), mark(5));
    var g2 = h('div', 'fl-grid');
    [['Manager', 'Looks after the other helpers (no ticket, no slot)', 5], ['Chat helper', 'Ask anything about the workspace', -1], ['Plain terminal', 'An empty tmux shell', -1]].forEach(function (x) { var c = h('div', 'fl-tile'); c.append(h('b', '', x[0]), h('span', 'meta', x[1])); c.append(btn(x[2] === 5 ? 'Open' : 'New', 'sm', function () { if (x[2] === 5) openSess(5); })); g2.append(c); });
    d.append(g2);
    d.append(h('h3', '', 'Earlier sessions')); var old = h('div', 'fl-rows');
    ['ORCH-228 · yesterday 16:40 · fixed menu', 'ORCH-230 · Mon 10:12 · diagnosis'].forEach(function (t) { var r = h('div', 'fl-row'); r.append(h('span', 'fl-rt', t), btn('Reopen', 'sm')); old.append(r); }); d.append(old);
    return d;
  }
  function layer() {
    var L = h('aside', 'fl-layer'); L.setAttribute('aria-label', 'Focus');
    var tabs = h('div', 'fl-tabs'); tabs.setAttribute('role', 'tablist');
    var home = h('button', 'fl-tab'); home.type = 'button'; home.setAttribute('role', 'tab'); home.setAttribute('aria-selected', st.view === 'start'); home.append(h('span', '', 'Focus')); home.addEventListener('click', function () { st.view = 'start'; render(); }); tabs.append(home);
    st.open.slice().sort(function (a, b) { return order().indexOf(a) - order().indexOf(b); }).forEach(function (i) {
      var b = h('button', 'fl-tab'); b.type = 'button'; b.setAttribute('role', 'tab'); b.setAttribute('aria-selected', st.view === 'session' && st.cur === i); b.append(dot(S[i].s), h('span', '', S[i].k)); if (S[i].s === 'wait') b.append(h('span', 'fl-flag', 'Needs you')); b.addEventListener('click', function () { st.cur = i; st.view = 'session'; render(); }); tabs.append(b);
    });
    tabs.append(btn('+', 'ghost icon sm', function () { st.view = 'start'; render(); }));
    var ctl = h('div', 'fl-ctl');
    if (st.view === 'session') ctl.append(btn(st.split ? 'One' : 'Side by side', 'ghost sm', function () { st.split = !st.split; render(); }), mark(8));
    ctl.append(btn(st.mode === 'bottom' ? 'Move right' : 'Move bottom', 'ghost sm', function () { st.mode = st.mode === 'bottom' ? 'right' : 'bottom'; render(); }), mark(6), btn('⤢', 'ghost icon sm', function () { st.mode = 'full'; render(); }), mark(7), btn('—', 'ghost icon sm', function () { st.mode = 'rail'; render(); }));
    ctl.lastChild.previousSibling && 0;
    ctl.children[ctl.children.length - 1].setAttribute('aria-label', 'Hide Focus, keep the strip');
    var top = h('div', 'fl-top'); top.append(tabs, ctl); L.append(top);
    var body = h('div', 'fl-lbody');
    if (st.view === 'start') body.append(startPage());
    else { body.dataset.split = st.split ? '2' : '1'; body.append(pane(st.cur)); if (st.split) { var other = st.open.filter(function (x) { return x !== st.cur; })[0]; if (other == null) other = 0; body.append(pane(other === st.cur ? 2 : other)); } }
    L.append(body); return L;
  }
  function strip() {
    var s = h('div', 'fl-strip'); s.setAttribute('role', 'toolbar'); s.setAttribute('aria-label', 'Sessions');
    s.append(btn(st.mode === 'rail' ? 'Open Focus' : 'Focus', 'sm', function () { st.mode = st.mode === 'rail' ? 'right' : 'rail'; if (st.mode === 'rail') st.mode = 'rail'; render(); }));
    order().forEach(function (i) { if (i > 4) return; var c = h('button', 'fl-chip ' + S[i].s); c.type = 'button'; c.append(dot(S[i].s), h('span', '', S[i].k), h('span', 'meta', WORD[S[i].s])); c.addEventListener('click', function () { openSess(i); }); s.append(c); });
    s.append(mark(8)); return s;
  }
  function app() {
    var a = $('#fl-app'); a.textContent = ''; a.dataset.mode = st.mode; document.body.classList.toggle('fl-full', st.mode === 'full');
    var nav = h('nav', 'fl-nav'); nav.setAttribute('aria-label', 'Pages');
    [['home', 'Home'], ['tickets', 'Tickets'], ['review', 'Review']].forEach(function (p) { var b = h('button', 'fl-navb', p[1]); b.type = 'button'; b.setAttribute('aria-current', st.page === p[0] ? 'page' : 'false'); b.addEventListener('click', function () { st.page = p[0]; st.ask = -1; render(); }); nav.append(b); });
    nav.append(h('span', 'grow')); var np = h('span', 'meta', 'Focus stays open'); nav.append(np, mark(6));
    var page = h('main', 'fl-page'); page.append(pageView());
    var work = h('div', 'fl-work'); work.append(page); if (st.mode !== 'rail') work.append(layer());
    a.append(nav, work, strip());
  }
  function render() {
    $$('#fl-scenes button').forEach(function (b) { b.setAttribute('aria-pressed', b.dataset.m === st.mode); });
    var keep = document.activeElement && document.activeElement.id; app(); paint(); if (keep) { var k = document.getElementById(keep); if (k) k.focus(); }
  }
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && st.mode === 'full') { st.mode = 'right'; render(); } if ((e.metaKey || e.ctrlKey) && e.key === 'j') { e.preventDefault(); st.mode = st.mode === 'rail' ? 'right' : 'rail'; render(); } });
  $$('#fl-scenes button').forEach(function (b) { b.addEventListener('click', function () { st.mode = b.dataset.m; render(); }); });
  picker(); render();
})();
