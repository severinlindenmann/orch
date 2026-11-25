/* Review overhaul drafts (ORCH-2163, 25 Nov 2026). Every page is drawn with the master's own classes
   (components.css, widgets.css); nothing here is built in the product. <body data-draft="r1-a"> picks the screen.
   All markup below is fixed text of this file; nothing comes from a person or the network. */
(function () {
  const A = '../../review/assets/';
  const C = window.RO_CARDS || [];
  const h = (tag, cls, ...kids) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    kids.flat().forEach(k => { if (k != null && k !== false) n.append(k.nodeType ? k : document.createTextNode(String(k))); });
    return n;
  };
  const at = (n, o) => { Object.entries(o).forEach(([k, v]) => n.setAttribute(k, v)); return n; };
  const ic = (name, size = 16) => { const s = h('span', 'ic-wrap'); s.innerHTML = window.icon(name, size); s.style.display = 'inline-flex'; return s; };
  const btn = (cls, label, icon) => at(h('button', 'btn ' + cls, icon ? ic(icon, 16) : null, label), { type: 'button' });
  const chip = (cls, text) => h('span', 'chip ' + cls, text);
  const lane = l => C.filter(c => c.lane === l);
  const phone = () => window.matchMedia('(max-width: 720px)').matches;

  /* ---- the dashboard shell, as review/review.html ---- */
  function shell(count, sub, title = 'Review') {
    const nav = [['Home', 'm3 10 9-7 9 7v10H3z'], ['Tickets', 'M3 4h18v16H3zM9 4v16m6-16v16'], ['Review', 'M3 3h18v18H3zm5 9 3 3 5-6'], ['Chat', 'M4 4h16v12H9l-5 4z']];
    const side = h('aside', 'sidebar');
    side.id = 'side-menu';
    side.innerHTML = '<a class="brand" href="#" aria-label="orch home"><svg class="brand-mark" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M19 10a8 8 0 1 1-5-6" stroke="currentColor" stroke-width="2"/><circle cx="11" cy="12" r="3" fill="currentColor"/><circle cx="19" cy="5" r="2" fill="var(--brand)"/></svg><span class="brand-word">orch</span></a>'
      + '<details class="workspace"><summary class="ws-switch" aria-label="Choose workspace"><span class="wsb">O</span><span class="ws-text"><strong>ORCH Development</strong><span class="meta">Workspace</span></span><span class="ws-chev" aria-hidden="true">⌄</span></summary></details>'
      + '<div class="sidebar-scroll"><nav aria-label="Main">' + nav.map(([n, d]) => '<a class="nav-item" href="#"' + (n === 'Review' ? ' aria-current="page"' : '') + '><svg class="ic" viewBox="0 0 24 24" aria-hidden="true"><path d="' + d + '"/></svg><span class="nav-label">' + n + '</span>' + (n === 'Review' && count ? '<span class="count">' + count + '</span>' : '') + '</a>').join('') + '</nav></div>';
    const top = h('header', 'topbar', h('span', 'meta', title + ' ', h('span', 'badge needs', 'Draft')),
      h('div', 'topbar-actions', at(h('a', 'btn outline sm', ic('plus', 16), 'New ticket'), { href: '#' })));
    const main = at(h('main', 'page'), { id: 'content', 'aria-label': title });
    main.append(h('div', 'page-heading', h('div', '', h('h1', '', title), sub ? h('p', '', sub) : null)));
    document.body.className = 'has-shell';
    document.body.append(h('div', 'shell', side, h('div', 'shell-body', top, main)));
    const tab = h('nav', 'tabbar');
    tab.innerHTML = '<a href="#"><span class="tab-label">Home</span></a><a href="#"><span class="tab-label">Tickets</span></a><a href="#" aria-current="page"><span class="tab-label">Review</span>' + (count ? '<span class="count">' + count + '</span>' : '') + '</a><button type="button"><span class="tab-label">More</span></button>';
    document.body.append(tab);
    return main;
  }

  /* ---- shared pieces ---- */
  const img = (src, alt) => at(h('img'), { src: A + src, alt: alt || '' });
  const row = (o) => {
    const r = at(h('button', 'review-row' + (o.current ? ' is-current' : '')), { type: 'button' });
    let lead = h('span', 'review-row-icon', ic(o.icon, 16));
    if (o.thumb) { lead = h('span', 'opt-thumb', img(o.thumb, '')); lead.dataset.type = 'img'; Object.assign(lead.style, { width: '48px', height: '36px', flex: 'none', minHeight: '0' }); }
    r.append(lead, h('span', 'review-row-text', h('span', 'review-row-title', o.title), o.sub ? h('span', 'review-row-sub' + (o.soon ? ' soon' : ''), o.sub) : null));
    return h('div', 'review-li', r);
  };
  const group = (name, count, rows) => h('div', 'review-group has-head',
    h('h3', 'review-group-head', h('span', 'review-group-name', name), count != null ? h('span', 'review-group-count', count) : null), rows);
  const listCard = (title, groups) => h('aside', phone() ? 'card' : 'card review-side',
    h('div', 'review-list-head', h('h2', 'review-list-title', title)), h('div', 'review-list-groups', groups));
  const THUMBS = ['home-proposal.jpg', 'layout-b.png', 'home-today.jpg', 'layout-c.png'];
  /* the ten things of 25 Nov that need the person, by what they ask */
  const R = (cur) => ({
    decide: row({ icon: 'comment', title: 'Test every change alone, or only in the merge queue?', sub: 'A helper waits for this · ORCH-2123', soon: true, current: cur === 'decide' }),
    stuck: row({ icon: 'pause', title: 'Faster automatic checks: the work stopped', sub: 'A check failed 3 times · ORCH-1118', soon: true }),
    live: [row({ icon: 'pull', title: 'Release 50', sub: '3 test walks passed · ORCH-120' }), row({ icon: 'pull', title: 'Two changes to the automatic checks', sub: 'Both tested · ORCH-1118' })],
    do: [row({ icon: 'user', title: 'Check the new Companion menu on your Mac', sub: '3 steps · ORCH-1722' }), row({ icon: 'user', title: 'Two commands for the hourly check', sub: '2 steps · ORCH-950' })],
    look: lane('look').map((c, i) => row({ icon: 'image', thumb: THUMBS[i % 4], title: c.title, sub: c.files + ' pictures · ' + c.key, current: cur === 'look' && !i })),
  });

  /* a card of the deck in normal flow (the master's .swipe-card.in-pair), with the answer bar under it */
  const card = (o) => {
    const head = h('div', 'swipe-head', h('h3', '', o.title),
      h('div', 'swipe-meta', h('span', 'swipe-kind', ic(o.icon || 'check', 14), o.kind), o.need ? h('span', 'swipe-need' + (o.soon ? ' soon' : ''), o.need) : null, h('span', 'swipe-key', o.key)),
      o.text ? h('p', 'swipe-text', o.text) : null, o.why ? h('p', 'swipe-why', o.why) : null);
    return h('article', 'swipe-card in-pair', head, o.body || null);
  };
  const act = (cls, label, icon) => at(h('button', 'swipe-act ' + cls, icon ? h('span', 'ring', ic(icon, 18)) : null, h('span', 'act-label', label)), { type: 'button' });
  const bar = (then, acts) => h('div', 'swipe-actions', then ? h('p', 'swipe-bar-then', h('b', '', then[0]), ' ' + then[1]) : null,
    h('div', 'swipe-acts-row', btn('ghost sm', 'Later'), h('span', 'grow'), acts));
  const deck = (c, b) => { const d = h('section', 'swipe swipe-desk'); d.style.position = 'static'; d.append(c, b); return d; };
  const preview = (type, ...kids) => { const p = h('div', 'swipe-preview', kids); p.dataset.type = type; p.style.cursor = 'default'; return p; };
  const doc = (...kids) => preview('doc', h('div', 'doc', kids));
  /* pictures side by side at a fixed height: [file, label, overlay, height] */
  const minis = (...pairs) => { const g = h('div', 'row'); g.style.alignItems = 'flex-start'; g.style.flexWrap = 'nowrap'; pairs.forEach(([src, label, over, ht]) => { const t = h('span', 'opt-thumb', img(src, label)); t.dataset.type = 'img'; Object.assign(t.style, { height: (ht || 120) + 'px', flex: 'none', display: 'block' }); if (over) t.append(over); const c = h('div', 'stack', t, h('span', 'meta', label)); c.style.flex = '1'; c.style.minWidth = '0'; c.style.gap = 'var(--s1)'; g.append(c); }); return g; };
  const tools = (...names) => { const t = h('span', 'row'); Object.assign(t.style, { position: 'absolute', right: 'var(--s2)', top: 'var(--s2)', gap: 'var(--s1)' }); names.forEach(([i, l]) => t.append(at(h('span', phone() ? 'btn icon sm' : 'btn sm', ic(i, 14), phone() ? null : l), { style: 'background:var(--surface-2)', title: l }))); return t; };
  const pin = (n, x, y) => { const p = h('span', 'swipe-pin', h('span', '', String(n))); p.style.left = x + '%'; p.style.top = y + '%'; return p; };
  /* a table on a phone: one row per line, the first cell as its title and the others named under it */
  const stackRows = (head, rows) => rows.map(r => { const g = h('div', 'grow', h('h3', '', r[0] || 'Same need')); r.slice(1).forEach((x, i) => { if (x !== '' && x != null) g.append(h('p', 'meta', head[i + 1] + ': ', x)); }); return h('div', 'card-row', g); });
  const tableCard = (title, head, rows, foot) => {
    if (phone()) return h('section', 'card', h('div', 'card-h', h('h2', '', title)), stackRows(head, rows), foot ? h('div', 'card-row', h('p', 'meta grow', foot)) : null);
    const t = h('table', 'tbl'); t.append(h('thead', '', h('tr', '', ...head.map(x => h('th', '', x)))));
    const b = h('tbody'); rows.forEach(r => b.append(h('tr', '', ...r.map((x, i) => { const td = h('td', '', i === r.length - 1 && typeof x === 'string' && x.startsWith('orch') ? h('code', 'mono', x) : x); td.style.whiteSpace = 'normal'; return td; })))); t.append(b);
    return h('section', 'card', h('div', 'card-h', h('h2', '', title)), h('div', 'table-wrap', t), foot ? h('div', 'card-row', h('p', 'meta grow', foot)) : null);
  };
  const layout = (left, right) => { const l = h('div', 'review-layout'); l.append(h('div', 'stack review-rail', left), h('div', 'stack review-main', right)); return l; };
  const tabs = (items) => { const n = at(h('nav', 'segmented'), { 'aria-label': 'Show' }); items.forEach(([t, c, on]) => n.append(at(h('button', 'btn sm', t + ' ', h('span', 'meta', c)), { type: 'button', 'aria-pressed': String(!!on) }))); return n; };
  const code = (lines) => { const p = h('pre', 'cmd-block-out', lines.join('\n')); p.style.maxHeight = 'none'; return h('div', 'cmd-block', p); };
  const paused = () => h('div', 'banner slim info', ic('pause', 16), h('div', 'grow', h('strong', '', 'Automation is paused.'), ' One helper starts when you turn it on.'), btn('outline sm', 'Turn on'));

  /* the first card on the list drafts: the one real decision of that day */
  const decideCard = () => deck(card({ title: 'Test every change alone, or only in the merge queue?', kind: 'Decide', icon: 'comment', need: 'A helper waits for this', soon: true, key: 'ORCH-2123',
    text: 'Our rules say every change gets its own quick test. This week the tests run only in the merge queue, to save test time. One of the two has to change.',
    body: h('div', 'swipe-preview plain', h('div', 'stack', at(h('button', 'swipe-opt', h('span', 'opt-title', h('b', '', 'Keep testing in the merge queue '), h('span', 'chip active', 'Suggested')), h('span', 'opt-text meta', 'Nothing changes this week. One line of the rules is rewritten.')), { type: 'button', 'aria-pressed': 'true' }),
      at(h('button', 'swipe-opt', h('span', 'opt-title', h('b', '', 'Test every change alone again')), h('span', 'opt-text meta', 'Safer per change, about 3 times the test time.')), { type: 'button' }))) }),
    bar(['If you pick the first:', 'the helper writes the new rule line and shows it to you before it applies.'], [act('talk', 'Comment', 'comment'), act('ok suggested', 'Keep testing in the merge queue', 'check')]));

  /* "What the Reviewer did" (the rail card the product has today), now carrying the load */
  const reviewerCard = () => {
    const s = h('section', 'card');
    s.append(h('div', 'card-h', h('h2', '', 'What the Reviewer did'), h('span', 'grow'), h('span', 'meta', 'today')));
    s.append(h('div', 'card-row', ic('check', 16), h('div', 'grow', h('h3', '', 'Accepted · 11'), h('p', 'meta', 'Finished, every part you asked for has evidence, nothing to look at.'))));
    lane('accepted').slice(0, phone() ? 2 : 3).forEach(c => s.append(h('div', 'card-row', h('span', 'meta', '✓'), h('div', 'grow', h('p', '', c.title), h('p', 'meta', c.key + ' · all tests passed, every step has evidence')), btn('ghost sm', 'Undo'))));
    s.append(h('div', 'card-row', h('span', 'meta', '✓'), h('p', 'meta grow', 'and 8 more, each with its own Undo, lower on this page')));
    s.append(h('div', 'card-row', ic('undo', 16), h('div', 'grow', h('h3', '', 'Sent back to the helper · 17'), h('p', 'meta', 'A part of what you asked for was still open, or a picture was missing. The helper finishes it first.'))));
    s.append(h('div', 'card-row', ic('cards', 16), h('div', 'grow', h('h3', '', 'Put on one card · 3'), h('p', 'meta', 'The three test walks of Release 50 are on the Release 50 card.'))));
    return s;
  };

  const P = {};

  /* ===== R1 what reaches the person ===== */
  P['r1-a'] = () => {
    const m = shell(10, '10 things need you. 2 hold up work now.');
    const g = R('decide');
    const list = listCard('Needs you', [group('Holds up work now', 2, [g.decide, g.stuck]), group('Put it live', 2, g.live), group('Try it yourself', 2, g.do), group('Look at the result', 4, g.look)]);
    m.append(paused());
    if (phone()) m.append(list, reviewerCard());
    else m.append(layout([list], [decideCard(), reviewerCard()]));
  };
  P['r1-b'] = () => {
    const m = shell(10, '10 things need you. 28 more were checked by the Reviewer and wait for one click.');
    m.append(tabs([['Needs you', 10, false], ['Checked by the Reviewer', 28, true], ['Answered', '', false]]));
    const s = h('section', 'card');
    s.append(h('div', 'card-h', h('h2', '', 'The Reviewer would accept these 11'), h('span', 'grow'), btn('outline sm', 'Accept all 11')));
    lane('accepted').slice(0, phone() ? 3 : 5).forEach(c => s.append(h('div', 'card-row', ic('check', 16), h('div', 'grow', h('h3', '', c.title), h('p', 'meta', c.key + ' · all tests passed, every step has evidence')), btn('ghost sm', 'Open'), btn('ghost sm', 'Accept'))));
    s.append(h('div', 'card-row', h('p', 'meta grow', 'and 6 more, lower on this page')));
    const b = h('section', 'card');
    b.append(h('div', 'card-h', h('h2', '', 'The Reviewer would send these 17 back'), h('span', 'grow'), btn('outline sm', 'Send all 17 back')));
    lane('back').slice(0, phone() ? 2 : 3).forEach(c => b.append(h('div', 'card-row', ic('undo', 16), h('div', 'grow', h('h3', '', c.title), h('p', 'meta', c.key + ' · a part of what you asked for is still open')), btn('ghost sm', 'Open'), btn('ghost sm', 'Send back'))));
    b.append(h('div', 'card-row', h('p', 'meta grow', 'and 14 more, lower on this page')));
    m.append(s, b);
  };

  /* ===== R2 grouping and order of the list ===== */
  const r2 = (sub, groups) => { const m = shell(10, sub); const list = listCard('Needs you', groups); m.append(layout(phone() ? [] : [list], [phone() ? list : decideCard()])); };
  P['r2-a'] = () => { const g = R('decide'); r2('10 things need you. 2 hold up work now.', [group('Holds up work now', 2, [g.decide, g.stuck]), group('Put it live', 2, g.live), group('Try it yourself', 2, g.do), group('Look at the result', 4, g.look)]); };
  P['r2-b'] = () => { const g = R('decide'); r2('10 things need you. 2 hold up work now.', [group('Holds up work now', 2, [g.decide, g.stuck]), group('Waiting, oldest first', 8, [...g.do, ...g.live, ...g.look])]); };
  P['r2-c'] = () => {
    const g = R('decide');
    r2('10 things need you, in 9 pieces of work.', [['Faster automatic checks', [g.stuck, g.live[1]]], ['Rules for testing', [g.decide]], ['Release 50', [g.live[0]]], ['Companion app', [g.do[0]]], ['Hourly check of relay and publish', [g.do[1]]], ['Empty states of the pages', [g.look[0]]], ['Add-on install', [g.look[1]]], ['Review page', [g.look[2]]], ['Dead ends to the terminal', [g.look[3]]]]
      .map(([n, rows]) => group(n, rows.length > 1 ? rows.length + ' waiting' : null, rows)));
  };

  /* ===== R3 the card catalogue ===== */
  const yesno = () => h('div', 'row', btn('outline sm', 'No'), btn('outline sm suggested', 'Yes'));
  const diff = () => h('div', 'doc-diff', h('div', 'doc-line del', '− Send'), h('div', 'doc-line add', '+ Send to 312 people'));
  const numbers = () => { const d = h('div', 'doc-chart'); [['Before', 100, '4.2 s'], ['After', 43, '1.8 s']].forEach(([l, v, t]) => { const p = h('div', 'progress'); const f = h('span'); f.style.width = v + '%'; p.append(f); d.append(h('div', 'doc-bar', h('span', '', l), p, h('span', '', t))); }); return d; };
  const steps = () => h('div', 'stack', ...['Open the menu in the menu bar', 'Switch one workspace on', 'Restart your Mac'].map((t, i) => { const l = h('label', 'row', at(h('input'), { type: 'checkbox', ...(i ? {} : { checked: '' }) }), h('span', '', t)); l.style.flexWrap = 'nowrap'; return l; }), h('div', 'row', btn('outline sm', 'Something did not work'), btn('outline sm suggested', 'It worked')));
  const stuckBody = () => h('div', 'stack', h('p', 'meta', 'Stopped at “Send the booking mail”. orch tried again twice.'), h('div', 'row', btn('outline sm', 'Start fresh'), btn('outline sm suggested', 'Nudge')));
  const live = () => h('div', 'stack', h('div', 'doc-chips', chip('success', 'All 14 checks passed'), chip('', '3 files changed')), h('div', 'row', btn('outline sm', 'See the changes'), btn('primary sm', 'Put it live')));
  const wcard = (name, icon, when, body, can, by) => {
    const s = h('section', 'card');
    s.append(h('div', 'card-h', ic(icon, 16), h('h2', '', name), h('span', 'grow'), by ? h('span', 'tag', by) : null));
    s.append(h('div', 'card-row', h('p', 'meta grow', 'Use when: ' + when)));
    const b = h('div', 'card-row'); b.style.display = 'block'; b.style.padding = 'var(--s4)'; b.append(body); s.append(b);
    s.append(h('div', 'card-row', h('span', 'meta grow', can)));
    return s;
  };
  const grid = (kids) => { const g = h('div', 'grid-3', kids); g.style.alignItems = 'start'; return g; };
  P['r3-a'] = () => {
    const m = shell(0, 'Five kinds of card, named by what you do. A helper can make four of them; orch makes the fifth.', 'Review: the five cards');
    m.append(grid([
      wcard('Decide', 'comment', 'a helper needs your answer: yes or no, or one of up to four ways.', h('div', 'stack', minis(['layout-a.png', 'A · As today'], ['layout-b.png', 'B · Suggested']), h('p', 'meta', 'Without pictures it is the question and its answers:'), yesno()), 'Pictures open large · Comment'),
      wcard('Look at the result', 'image', 'work is finished and there is something to see or read.', h('div', 'stack', minis(['home-today.jpg', 'Before'], ['home-proposal.jpg', 'After']), h('p', 'meta', 'Inside it, whatever the helper attached:'), h('div', 'doc-chips', ...['Before and after', 'Pictures', 'A document', 'Changed words', 'Numbers', 'A page to open'].map(t => chip('', t)))), 'Pictures open large · Comment'),
      wcard('Put it live', 'pull', 'a tested change is ready and only you may release it.', live(), 'Comment'),
      wcard('Try it yourself', 'user', 'something only you can do on your own computer: steps to try, a sign-in, one command.', steps(), 'Comment'),
      wcard('Stuck', 'pause', 'work stopped and orch could not get it going again.', stuckBody(), 'Comment', 'Made by orch'),
    ]));
    m.append(h('h2', 'sec-title', 'Inside “Look at the result”: the helper attaches, orch lays it out'), grid([
      wcard('Changed words', 'diff', 'the helper attached old and new wording.', diff(), 'Comment on a line'),
      wcard('Numbers', 'chart', 'the helper attached a few numbers.', numbers(), 'Comment on a line'),
      wcard('A document', 'file', 'the helper attached a text or PDF.', h('div', 'doc', h('p', 'doc-headline', 'Weekly report for the café'), h('p', 'meta', 'Sales were 8,420, 6% above last week. The first Sunday opening brought 900 in four hours.')), 'Comment on a paragraph'),
    ]));
  };
  P['r3-b'] = () => {
    const m = shell(0, 'Twelve kinds of card in four families. Each attachment gets its own kind.', 'Review: twelve cards');
    const fam = (t, kids) => m.append(h('h2', 'sec-title', t), grid(kids));
    fam('Answer: you decide', [wcard('Question', 'comment', 'a yes or no, or a few short answers.', yesno(), 'Comment'), wcard('Choice', 'cards', 'two to four ways, each with a picture or a line.', minis(['layout-a.png', 'A · As today'], ['layout-b.png', 'B · Suggested']), 'Open large · Mark a spot · Comment')]);
    fam('Look: you judge a result', [wcard('Before and after', 'compare', 'something looks different now.', minis(['home-today.jpg', 'Before'], ['home-proposal.jpg', 'After']), 'Open large · Mark a spot · Comment'),
      wcard('Pictures', 'image', 'new screens or images, up to six.', minis(['email-desktop.png', 'Email on a computer'], ['sale-banner.png', 'Website banner']), 'Open large · Mark a spot · Comment'),
      wcard('Document', 'file', 'a text, a PDF or a page to read.', h('div', 'doc', h('p', 'doc-headline', 'Weekly report for the café'), h('p', 'meta', 'Page 1 of 2 · Weekly report.pdf')), 'Comment on a line · Comment'),
      wcard('Changed words', 'diff', 'wording or a setting changed.', diff(), 'Comment on a line · Comment'),
      wcard('Numbers', 'chart', 'a few numbers that changed.', numbers(), 'Comment on a line · Comment'),
      wcard('Test result', 'test', 'what was run and how it ended.', h('div', 'doc-chips', chip('success', 'All 213 passed')), 'Comment')]);
    fam('Click: only you may press it', [wcard('Put it live', 'pull', 'a tested change only you may release.', live(), 'Comment'), wcard('Run it', 'code', 'one command only you may run.', h('div', 'cmd-block', h('div', 'cmd-block-cmd', h('code', '', 'az login'), btn('outline sm', 'Run it now'))), 'Comment')]);
    fam('Help: the work needs you in person', [wcard('Try it yourself', 'user', 'steps on your own computer.', steps(), 'Comment'), wcard('Stuck', 'pause', 'work stopped.', stuckBody(), 'Comment')]);
  };

  /* ===== R4 open large, point at a place, comment: the same everywhere ===== */
  const resultCard = (mode) => {
    const over = mode === 'b' ? h('span', '', tools(['expand', 'Open large']), pin(1, 62, 58)) : mode === 'a' ? tools(['expand', 'Open large'], ['pin', 'Mark a spot']) : tools(['expand', 'Open large']);
    const pics = minis(['email-desktop.png', 'Email on a computer', over, 220], ['email-phone.png', 'Email on a phone', null, 220]);
    pics.style.padding = '0 var(--s5) var(--s4)';
    const p2 = h('p', '', 'The offer is 20% off all beans from 20 to 27 March with the code SPRING20, as you wrote in the ticket.');
    const p3 = h('p', '', 'The list has 312 people: regulars, online shop customers and people who only get the newsletter.');
    let said = null;
    if (mode === 'a') { const mk = h('mark', '', '20% off all beans from 20 to 27 March'); mk.style.background = 'var(--warning-soft)'; mk.style.color = 'var(--text)'; p2.replaceChildren('The offer is ', mk, ' with the code SPRING20, as you wrote in the ticket.'); said = h('div', 'banner slim attn', ic('comment', 16), h('div', 'grow', h('strong', '', 'On the marked words'), h('p', '', '“Make it 15%, and only until the 25th.”'))); }
    if (mode === 'b') { [p2, p3].forEach(p => { p.style.outline = '1px dashed var(--border-strong)'; p.style.outlineOffset = 'var(--s1)'; p.style.borderRadius = 'var(--radius)'; }); p2.style.outline = '1px solid var(--warning)'; said = h('div', 'banner slim attn', ic('comment', 16), h('div', 'grow', h('strong', '', '2 · On this paragraph'), h('p', '', '“Make it 15%, and only until the 25th.”'))); }
    const d = doc(h('p', 'doc-headline', 'The spring sale email is written, with a phone version and a banner.'), p2, said, p3);
    const mode_b = mode === 'b' ? h('div', 'banner slim info', ic('comment', 16), h('div', 'grow', h('strong', '', 'Comment is on.'), ' Click a picture or a paragraph, or write about the whole card.'), btn('outline sm', 'Whole card'), btn('ghost sm', 'Done')) : null;
    if (mode_b) mode_b.style.margin = '0 var(--s5) var(--s4)';
    const n = mode === 'c' ? 1 : mode === 'b' ? 2 : 1;
    const whole = mode === 'c' ? h('div', 'banner slim attn', ic('comment', 16), h('div', 'grow', h('strong', '', 'Your comment'), h('p', '', '“Make it 15%, and only until the 25th. The button in the email is too small.”'))) : null;
    if (whole) whole.style.margin = 'var(--s4) var(--s5)';
    return deck(card({ title: 'Spring sale email', kind: 'Look at the result', icon: 'image', need: 'Sends Friday 08:00', soon: true, key: 'DT-53', body: h('div', '', mode_b, pics, d, whole) }),
      bar(['If you send it back:', 'the helper changes it and shows it to you again. Nothing is sent on Friday until you say it looks good.'], [act('talk', 'Comment · ' + n, 'comment'), act('ok', 'Looks good as it is', 'check'), act('ok suggested', n > 1 ? 'Send back with ' + n + ' comments' : 'Send back with 1 comment', 'undo')]));
  };
  const r4 = (mode, sub) => { const m = shell(10, sub); const l = h('div', 'stack'); l.style.maxWidth = '760px'; l.append(resultCard(mode)); m.append(l); };
  P['r4-a'] = () => r4('a', 'Draft: a tool per kind of content. Pictures: open large and mark a spot. Text: mark the words. No zoom on text.');
  P['r4-b'] = () => r4('b', 'Draft: one Comment button. Press it and what you can point at lights up. Only pictures open large.');
  P['r4-c'] = () => r4('c', 'Draft: the least. Pictures open large. One comment box for the whole card, no pointing.');
  /* Now: the real deck of develop with its viewer open on a text card (the master's own code, nothing drawn) */
  P['r4-now'] = () => {
    const m = shell(43, '43 things wait on you, most urgent first.');
    const d = at(h('section'), { id: 'deck' }); m.append(d);
    const item = { id: 'n1', kind: 'check', kindLabel: 'Check', icon: 'check', ticket: 'ORCH-1996', title: 'Bug hunt: F2 CLI on Windows-like inputs (BOM/CRLF ticket files, read-only/locked files, umlaut paths)', why: 'The helper says this is ready for your check.', okLabel: 'Looks good',
      preview: { type: 'doc', heading: 'BOM ticket files, read-only/locked ticket files and BOM settings.local.json fixed with tests in PR 2962 (R1.6, R8.2).', paras: ['1. Failing tests for BOM/CRLF ticket files, read-only/locked files, umlaut paths — tests/test_ticket_fixtures.py + tests/test_init.py; 4 failed before fix; PR https://github.com/severinlindenmann/orch/pull/2962', '2. Fix ticket readers, write/read refusals, settings BOM in workspace/src/orch — PR https://github.com/severinlindenmann/orch/pull/2962; targeted tests 89 passed (1 env-only fail: host disk full)', 'Runner reviews and queues it.'] } };
    window.UI.swipeDeck(d, [item], { mode: phone() ? 'phone' : 'desk' });
    setTimeout(() => { const b = d.querySelector('.swipe-expand'); if (b) b.click(); setTimeout(() => { const p = [...document.querySelectorAll('.swipe-viewer .btn')].find(x => /spot/i.test(x.textContent)); if (p) p.click(); }, 150); }, 150);
  };

  /* ===== R5 how a helper picks the card ===== */
  P['r5-now'] = () => {
    const m = shell(0, 'What a helper reads today before it puts a card on Review.', 'How a helper picks a card: today');
    m.append(h('section', 'card pad stack', h('h2', '', 'From the orch skill, as it is'),
      code(['orch ask <id> "Home: which layout?" --choose "Home layout" --option "A=As today:files/a.png" --option "B=Recent first:files/b.png" --suggest B --then "..."',
        'orch ask <id> "New intro text" --draft "Intro" --file files/intro.md --then "I use it." --ok "Use it"',
        'orch ask <id> "Before or after?" --draft "Header" --before files/old.png --after files/new.png --then "..."',
        'orch ask <id> "..." --draft "<title>" --ci-shots <pull request address> --then "..."',
        'orch ask <id> "Merge release 3?" --link "Release 3" --open <pull request address> --merge --then "..."',
        'orch ask <id> "Turn on release walks?" --run "orch config set ..." --option "Leave it off for now"',
        'Other cards: --draft, --plan, --link (with --open <address>), --before F --after F.',
        'Write the card as a JSON file and pass it with --file card.json on --draft or --plan:',
        '  {"headline": "...", "progress": {...}, "chips": [...], "flow": [...], "chart": {...}, "diff": [...], "details": [...]}']),
      h('p', 'meta', 'Nine flags and a JSON format. Nothing says when a card should not be made at all, and a finished ticket always becomes a Check card with the helper’s own step list.')));
    m.append(tableCard('What that gave on 25 Nov', ['What the helper wanted', 'What it made', 'What you got'], [
      ['Tell you a release is out and ask you to try it', 'A choice card: “It worked / Something did not work”', 'A 78-word title with the steps hidden in it'],
      ['Say it could not start', 'A choice card: “Try again / Leave it”', 'A card for something you switched off yourself'],
      ['Hand over finished work', '35 Check cards', 'Step lists with file names and pull request numbers; 20 of them had a part still open']]));
  };
  P['r5-a'] = () => {
    const m = shell(0, 'Draft: one command, orch ask. The helper says what it needs and attaches what it has; orch picks the card, or says no.', 'How a helper picks a card');
    m.append(tableCard('The helper answers one question: what do I need from the person?', ['The helper needs', 'and attaches', 'orch makes', 'The helper writes'], [
      ['An answer', 'two to four answers and the one it suggests', 'Decide', 'orch ask <id> "…" --option Yes --option No --suggest Yes'],
      ['', 'a picture or a line per way', 'Decide, with pictures', 'orch ask <id> "…" --option "A=As today:a.png" --option "B=New:b.png" --suggest B'],
      ['A look at finished work', 'pictures, a PDF, old and new wording, numbers, an address', 'Look at the result', 'orch ask <id> "…" --file new.png --before old.png'],
      ['A release only the person may make', 'the pull request', 'Put it live', 'orch ask <id> "…" --merge <address>'],
      ['The person to do something', 'the steps, one per line, or one command', 'Try it yourself', 'orch ask <id> "…" --steps steps.txt | --run "<command>"'],
      ['Nothing: it only reports', '', 'No card', 'orch ticket summary <id> "…"']],
      'The helper never names a card or a layout: the files it attaches decide. Finished work is not asked about at all: it goes to the Reviewer, and a card is made only for what the Reviewer leaves to the person.'));
    m.append(h('section', 'card pad stack', h('h2', '', 'Three things orch refuses, each with the next step'),
      code(['$ orch ask ORCH-2157 "The helper could not start: automation is paused." --option "Try again" --option "Leave it"',
        'Not asked: this reports a state, it is not a decision. The person sees "Automation is paused" on Home and Review.',
        'Next: orch wait ORCH-2157 --until <time>, or stop here.',
        '',
        '$ orch ask ORCH-1722 "orch Companion 0.1.2 … is published. Your Companion updates itself within 6 hours (or install it: …"',
        'Not asked: a question is one sentence (this one has 78 words). Put the steps in a file, one per line.',
        'Next: orch ask ORCH-1722 "Does the new Companion menu work on your Mac?" --steps steps.txt --option "It worked" --option "Something did not work"',
        '',
        '$ orch ask ORCH-2123 "Which test policy should be binding?"',
        'Not asked: a question needs two to four answers and the one you suggest.',
        'Next: orch ask ORCH-2123 "…" --option "<answer>" --option "<answer>" --suggest "<answer>"'])));
  };
  P['r5-b'] = () => {
    const m = shell(0, 'Draft: the nine flags stay as they are. The skill gets one table, and orch warns instead of refusing.', 'How a helper picks a card');
    m.append(tableCard('One table in the skill', ['When', 'Use', 'Never'], [
      ['You need a decision', '--option … --suggest …', 'a question longer than one sentence'],
      ['Something looks different', '--draft … --before … --after …', 'a text that describes the picture'],
      ['Several ways', '--choose with a picture per option', 'more than four options'],
      ['A file to read', '--draft … --file …', 'the file pasted into the question'],
      ['Only the person may release or run it', '--link … --merge / --run', 'a choice card with “Done / Not now”'],
      ['You only report', 'no card: orch ticket summary', 'a card with one answer']]));
    m.append(h('section', 'card pad stack', h('h2', '', 'orch warns, the card is still made'),
      code(['$ orch ask ORCH-1722 "orch Companion 0.1.2 … is published. Your Companion updates itself within 6 hours (or install it: …"',
        'Asked (q4). Hint: the question has 78 words; people read one sentence.',
        'Next: orch review wait ORCH-1722'])));
  };

  /* ===== R6 the result card ===== */
  const r6list = () => listCard('Needs you', [group('Look at the result', 4, R('look').look)]);
  const r6pics = (ht) => { const p = minis(['home-today.jpg', 'Before', tools(['expand', 'Open large']), ht], ['home-proposal.jpg', 'After', tools(['expand', 'Open large']), ht]); p.style.padding = '0 var(--s5) var(--s4)'; return p; };
  const r6 = (c) => { const m = shell(10, '10 things need you. 2 hold up work now.'); m.append(layout(phone() ? [] : [r6list()], [c])); };
  P['r6-a'] = () => r6(deck(card({ title: 'The empty pages now say what to do next', kind: 'Look at the result', icon: 'image', key: 'ORCH-2017', why: 'Five pages showed a blank box when they had nothing yet. Each now has one sentence and one button.',
    body: h('div', '', r6pics(phone() ? 130 : 240), doc(h('p', '', 'Everything you asked for is done and tested. 10 pictures: the five pages, each before and after.'), h('p', 'meta', 'What the helper did: 5 steps, each with its evidence, on the ticket.'))) }),
    bar(['If it looks good:', 'the ticket is done. Nothing else starts.'], [act('talk', 'Comment', 'comment'), act('no', 'Send back', 'x'), act('ok suggested', 'Looks good', 'check')])));
  P['r6-a2'] = () => {
    const open = h('div', 'banner slim attn', ic('pause', 16), h('div', 'grow', h('strong', '', 'One part is still open'), h('p', '', 'You asked for: pictures at three widths. You got: two. The helper could not take the phone picture after two tries.')));
    open.style.margin = '0 var(--s5) var(--s4)';
    r6(deck(card({ title: 'The empty pages now say what to do next', kind: 'Look at the result', icon: 'image', need: 'One part is still open', soon: true, key: 'ORCH-2017', why: 'Five pages showed a blank box when they had nothing yet. Each now has one sentence and one button.',
      body: h('div', '', open, r6pics(phone() ? 130 : 240), doc(h('p', '', 'Everything else you asked for is done and tested.'), h('p', 'meta', 'What the helper did: 5 steps, each with its evidence, on the ticket.'))) }),
      bar(['If you send it back:', 'the helper tries the open part again. If you close it, the ticket is done without the phone picture.'], [act('talk', 'Comment', 'comment'), act('ok', 'Close it without that part', 'check'), act('ok suggested', 'Send back', 'undo')])));
  };
  P['r6-b'] = () => {
    const rows = [['Each empty page says what to do next', h('span', '', chip('success', 'Done'), ' 5 pages, pictures below')], ['Same look as the style guide', h('span', '', chip('success', 'Done'), ' the master empty state')], ['Pictures at three widths', h('span', '', chip('attn', 'Open'), ' the phone picture is missing')]];
    const t = phone() ? h('div', '', stackRows(['You asked for', 'You got'], rows)) : (() => { const t = h('table', 'tbl'); t.append(h('thead', '', h('tr', '', h('th', '', 'You asked for'), h('th', '', 'You got')))); const b = h('tbody'); rows.forEach(r => b.append(h('tr', '', ...r.map(x => { const td = h('td', '', x); td.style.whiteSpace = 'normal'; return td; })))); t.append(b); return h('div', 'table-wrap', t); })();
    const pics = r6pics(phone() ? 130 : 200); pics.style.padding = 'var(--s4) var(--s5)';
    r6(deck(card({ title: 'UX pass: empty states of dashboard and add-on pages (weakest five fixed)', kind: 'Look at the result', icon: 'image', key: 'ORCH-2017', body: h('div', '', preview('table', t), pics) }),
      bar(['If you send it back:', 'the helper tries the open part again.'], [act('talk', 'Comment', 'comment'), act('ok', 'Close it without that part', 'check'), act('ok suggested', 'Send back', 'undo')])));
  };

  const run = P[document.body.dataset.draft];
  if (run) run();
})();
