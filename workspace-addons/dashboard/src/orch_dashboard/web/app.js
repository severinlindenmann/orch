'use strict';
(() => {
  const snapshot = typeof window.ORCH_SNAPSHOT !== 'undefined';
  const main = document.getElementById('content');
  const nav = document.getElementById('side-nav');
  const array = value => Array.isArray(value) ? value : [];
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[c]));
  const clean = value => String(value ?? '').replace(/\b(?:ws|t|q|m|ph|wh|b|f)_[a-zA-Z0-9]{4,}\b/g, '').replace(/\s+·\s+·/g, ' · ').trim();
  const name = value => clean(String(value ?? '').replace(/^(human|agent):/, ''));
  const icon = value => {
    const svg = window.icon(String(value || 'page'));
    return /<(path|rect|circle|polyline|line|ellipse)\b/.test(svg) ? svg : window.icon('page');
  };
  const el = (tag, cls, text) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  };
  const button = (text, cls, click) => {
    const node = el('button', 'btn ' + cls, text);
    node.type = 'button';
    node.addEventListener('click', click);
    return node;
  };
  const parse = value => {
    if (!value) return null;
    const d = new Date(/^\d{4}-\d{2}-\d{2}$/.test(String(value)) ? value + 'T00:00:00' : value);
    return Number.isNaN(d.getTime()) ? null : d;
  };
  const date = value => parse(value)?.toLocaleDateString('en-GB', {weekday:'short', day:'numeric', month:'short'}) || '';
  const time = value => parse(value)?.toLocaleTimeString('en-GB', {hour:'2-digit', minute:'2-digit'}) || '';
  let state, renderedRoute = '', fetching = false, writing = 0, serial = 0, mutation = 0;
  const now = () => parse(state?.now) || new Date();
  const today = () => {
    const d = now();
    return [d.getFullYear(), String(d.getMonth() + 1).padStart(2, '0'), String(d.getDate()).padStart(2, '0')].join('-');
  };
  const age = value => {
    const d = parse(value);
    if (!d) return '';
    const mins = Math.max(0, Math.floor((now() - d) / 60000));
    return mins < 60 ? Math.max(1, mins) + ' min' : mins < 1440 ? Math.floor(mins / 60) + ' h' : Math.floor(mins / 1440) + (mins < 2880 ? ' day' : ' days');
  };
  const tickets = () => array(state?.tickets);
  const addons = () => array(state?.addons);
  const ticketOf = id => tickets().find(t => String(t.id) === String(id));
  const href = id => '#ticket/' + encodeURIComponent(id);
  const questions = t => array(t.questions).filter(q => q.answer == null);
  const activeTicket = t => !['done', 'dropped'].includes(t.status);
  const overdue = t => activeTicket(t) && t.due && t.due < today();
  const newer = (a, b) => (Date.parse(b.updated_at) || 0) - (Date.parse(a.updated_at) || 0);
  const sorted = list => list.slice().sort((a, b) => Number(!!overdue(b)) - Number(!!overdue(a)) || Number(questions(b).length > 0) - Number(questions(a).length > 0) || newer(a, b));
  const statusWord = t => questions(t).length ? 'Waiting for an answer' : ({active:'Doing', waiting:'Waiting', open:'Open', done:'Done', dropped:'Dropped'}[t.status] || 'Open');
  const chip = (text, cls = '') => '<span class="chip ' + cls + '">' + esc(text) + '</span>';
  const statusChip = t => chip(activeTicket(t) && (t.status === 'waiting' || questions(t).length) ? 'Blocked' : statusWord(t), activeTicket(t) && (t.status === 'waiting' || questions(t).length) ? 'attn' : t.status === 'active' ? 'active' : '');
  const heading = (title, sub = '') => '<header class="page-heading" data-key="heading"><h1>' + esc(clean(title)) + '</h1>' + (sub ? '<p class="muted">' + esc(sub) + '</p>' : '') + '</header>';
  const card = (key, title, suffix, body, chevron = false) => '<section class="card" data-key="' + esc(key) + '"' + (key === 'needs-you' ? ' id="needs-you"' : '') + '><div class="card-h">' + (chevron ? icon('down') : '') + '<h2>' + esc(title) + (suffix ? '<span class="muted"> · ' + esc(suffix) + '</span>' : '') + '</h2></div>' + body + '</section>';
  const emptyRow = text => '<div class="card-row muted">' + esc(text) + '</div>';
  const newButton = () => snapshot ? '' : '<button type="button" class="btn primary sm" data-action="new">New ticket</button>';
  function ticketRow(t) {
    const meta = [name(t.owner), t.due ? 'Due ' + date(t.due) : '', statusWord(t)].filter(Boolean);
    const parent = ticketOf(t.parent);
    let late = '';
    if (overdue(t)) {
      const days = Math.round((Date.parse(today()) - Date.parse(t.due)) / 86400000);
      late = chip('Overdue ' + days + (days === 1 ? ' day' : ' days'), 'error');
    }
    return '<div class="card-row ticket-row" data-key="ticket-' + esc(t.id) + '"><div class="grow"><h3><a href="' + esc(href(t.id)) + '">' + esc(clean(t.title)) + '</a></h3><p class="meta">' + esc(meta.join(' · ')) + '</p>' + (parent ? '<p class="meta">Part of ' + esc(clean(parent.title)) + '</p>' : '') + '</div><div class="row">' + late + statusChip(t) + '</div></div>';
  }
  function needRow(row, newest) {
    const t = ticketOf(row.ticket);
    const claim = state.runs?.[row.ticket]?.claim;
    const by = name(row.agent || row.by || claim?.agent || claim?.by);
    const meta = [by, t && clean(t.title)].filter(Boolean).join(' · ');
    const answer = row.answer && row.kind !== 'overdue-wait';
    const action = snapshot
      ? (t ? '<a class="btn outline sm" href="' + esc(href(t.id)) + '">Open</a>' : '')
      : '<button type="button" class="btn outline sm" data-action="need" data-need="' + esc(row.id) + '">' + (answer ? 'Answer' : 'Open') + '</button>';
    return '<div class="card-row" data-key="need-' + esc(row.id) + '" data-need-row="' + esc(row.id) + '"' + (row.id === newest ? ' data-newest' : '') + '><span class="need-icon ' + (row.tone === 'bad' ? 'bad' : row.tone === 'warn' ? 'warn' : 'muted') + '">' + icon(row.tone === 'bad' ? 'stop' : row.tone === 'warn' ? 'shield' : 'note') + '</span><div class="grow"><h3>' + esc(clean(row.title)) + '</h3><p class="meta">' + esc(meta) + '</p></div><time datetime="' + esc(row.since || '') + '">' + esc(age(row.since)) + '</time>' + action + '</div>';
  }
  function home() {
    const needs = array(state.needs);
    const working = Object.entries(state.runs || {}).filter(([, r]) => r.running === true);
    const current = sorted(tickets().filter(activeTicket));
    const oldest = needs.map(n => parse(n.since)).filter(Boolean).sort((a, b) => a - b)[0];
    const newest = needs.slice().sort((a, b) => (Date.parse(b.since) || 0) - (Date.parse(a.since) || 0))[0]?.id;
    const history = tickets().flatMap(t => array(t.history)).sort((a, b) => (Date.parse(b.at) || 0) - (Date.parse(a.at) || 0)).slice(0, 5);
    const stopped = array(state.services).some(s => s.running === false);
    const banner = stopped ? '<div class="banner attn" data-key="background"><p class="grow">Background work is not running. Start it so repeating work and checks can run.</p>' + (snapshot ? '' : '<button type="button" class="btn outline sm" data-action="start">Start</button>') + '</div>' : '';
    const agents = working.slice(0, 4).map(([id, run]) => {
      const stale = run.state === 'maybe-stale';
      return '<div class="card-row" data-key="run-' + esc(id) + '"><span class="dot ' + (stale ? 'needs' : 'working') + '"></span><div class="grow"><h3>' + esc(name(run.claim?.agent || run.claim?.by) || 'Agent') + ' · ' + (stale ? 'may be stuck' : 'working') + '</h3><p class="meta">' + esc([clean(ticketOf(id)?.title), age(run.claim?.started_at)].filter(Boolean).join(' · ')) + '</p></div></div>';
    }).join('');
    return heading('Today', now().toLocaleDateString('en-GB', {weekday:'long', day:'numeric', month:'long'}) + ' · ' + needs.length + ' need you · ' + working.length + (working.length === 1 ? ' agent working' : ' agents working')) + banner
      + '<div class="columns" data-key="columns"><div class="stack" data-key="left">'
      + card('needs-you', 'Needs you', needs.length + (oldest ? ' · oldest ' + age(oldest) : ''), needs.map(n => needRow(n, newest)).join('') || emptyRow('Nothing needs you right now.'), true)
      + card('your-tickets', 'Your tickets', current.length + ' · ' + current.filter(overdue).length + ' overdue', current.map(ticketRow).join('') || '<div class="card-row"><p class="grow muted">Your first ticket starts here.</p>' + newButton() + '</div>', true)
      + '</div><aside class="stack" data-key="right">'
      + card('agents', 'Agents', working.length + ' working', agents || emptyRow('No agent is working right now.'))
      + card('recently', 'Recently', '', history.map(h => '<div class="card-row"><div class="grow"><h3>' + esc(clean(h.text).length > 80 ? clean(h.text).slice(0, 79) + '…' : clean(h.text)) + '</h3><p class="meta">' + esc([name(h.by), age(h.at)].filter(Boolean).join(' · ')) + '</p></div></div>').join('') || emptyRow('No recent activity.'))
      + '</aside></div>';
  }
  const expanded = new Set();
  function list() {
    return heading('Tickets') + (!tickets().length ? card('empty', 'Tickets', '', '<div class="card-row"><p class="grow muted">Your first ticket starts here.</p>' + newButton() + '</div>') : ['active', 'waiting', 'open', 'done', 'dropped'].map(status => {
      const group = sorted(tickets().filter(t => t.status === status));
      if (!group.length) return '';
      const title = {active:'Doing', waiting:'Waiting', open:'Open', done:'Done', dropped:'Dropped'}[status];
      if (!['done', 'dropped'].includes(status)) return card('group-' + status, title, group.length, group.map(ticketRow).join(''));
      const open = expanded.has(status);
      return '<section class="card" data-key="group-' + status + '"><button type="button" class="card-h card-toggle" data-action="group" data-group="' + status + '" aria-expanded="' + open + '" aria-controls="group-' + status + '"><span class="chevron ' + (open ? '' : 'closed') + '">' + icon('down') + '</span><span>' + title + ' · ' + group.length + '</span></button><div id="group-' + status + '"' + (open ? '' : ' hidden') + '>' + group.map(ticketRow).join('') + '</div></section>';
    }).join(''));
  }
  function addonValue(row, value) {
    if (value == null || value === '' || (Array.isArray(value) && !value.length)) return '';
    if (row.format === 'time') return esc([date(value), time(value)].filter(Boolean).join(' '));
    if (row.format === 'cron-human') return esc(value);
    if (row.format === 'yes-no') return value === true ? 'Yes' : value === false ? 'No' : '';
    if (row.format === 'chips') return '<div class="chips">' + array(value).map(v => chip(clean(v))).join('') + '</div>';
    return typeof value === 'object' ? '' : esc(clean(value));
  }
  function addonRows(ticket) {
    const rows = addons().flatMap(a => array(a.ticket_view).map(r => [r, (ticket.ext || {})[a.name]]))
      .map(([r, ext]) => [r, ext && typeof ext === 'object' ? addonValue(r, ext[r.field]) : '']).filter(([, v]) => v);
    return rows.length ? '<dl class="addon-rows">' + rows.map(([r, v]) => '<dt>' + esc(r.label) + '</dt><dd>' + v + '</dd>').join('') + '</dl>' : '';
  }
  function detail(t) {
    if (!t) return heading('Ticket not found') + '<a href="#tickets">All tickets</a>';
    const qs = questions(t).map(q => snapshot
      ? card('question-' + q.id, clean(q.text), '', '<div class="card-row"><div class="grow"><p class="muted">Waiting for an answer</p><div class="row">' + array(q.options).map(o => chip(clean(o), o === q.recommended ? 'attn' : '')).join('') + '</div></div></div>')
      : '<div data-key="question-' + esc(q.id) + '" data-question="' + esc(q.id) + '" data-ticket="' + esc(t.id) + '"></div>').join('');
    // Evidence.chip produces preview buttons; without a preview URL, plain proof chips are clearer.
    const tasks = array(t.checklist).map(task => '<div class="card-row"><span class="muted" aria-hidden="true">' + icon(task.done ? 'check' : 'more') + '</span><div class="grow"><h3>' + esc(clean(task.text)) + '</h3><p class="meta">' + (task.done ? 'Done' : 'Not done') + '</p><div class="row">' + array(task.evidence).map(ev => chip(clean(ev.summary || ev.text || ev.ref || 'Proof'))).join('') + '</div></div></div>').join('');
    const history = array(t.history).slice().sort((a, b) => (Date.parse(b.at) || 0) - (Date.parse(a.at) || 0)).map(h => '<div class="card-row"><p>' + esc([clean(h.text), name(h.by), age(h.at)].filter(Boolean).join(' · ')) + '</p></div>').join('');
    return '<a href="#tickets" data-key="back">All tickets</a>' + heading(t.title)
      + '<div class="row" data-key="ticket-meta">' + statusChip(t) + (t.owner ? chip(name(t.owner)) : '') + (t.due ? chip('Due ' + date(t.due)) : '') + (snapshot ? '' : '<button type="button" class="btn outline sm" data-action="edit" data-ticket="' + esc(t.id) + '">Edit</button>') + '</div>'
      + (t.summary ? '<p data-key="summary" class="preserve-lines">' + esc(clean(t.summary)) + '</p>' : '')
      + qs + card('tasks', 'Tasks', array(t.checklist).length, tasks || emptyRow('No tasks yet.'))
      + card('history', 'History', '', history || emptyRow('No history yet.'))
      + addonRows(t)
      + '<details data-key="more"><summary>More details</summary><dl class="ticket-details"><div><dt>Ticket</dt><dd class="mono">' + esc(t.id) + '</dd></div><div><dt>Created</dt><dd>' + esc(date(t.created_at)) + '</dd></div><div><dt>Updated</dt><dd>' + esc(date(t.updated_at)) + '</dd></div>' + (t.note ? '<div><dt>Note</dt><dd class="preserve-lines">' + esc(clean(t.note)) + '</dd></div>' : '') + '</dl></details>';
  }

  // Reconcile matching DOM nodes so polling cannot replace a focused control or a draft.
  const locks = new Set();
  const mounts = new Map();
  const nodeKey = node => node?.nodeType === 1 ? node.dataset.key || node.id || (node.dataset.action ? [node.dataset.action, node.dataset.need, node.dataset.ticket, node.dataset.group].join(':') : '') || (node.tagName === 'A' ? node.getAttribute('href') : '') : '';
  function sync(target, source) {
    if (target.nodeType === 3) { if (target.data !== source.data) target.data = source.data; return; }
    if (target.nodeType !== 1) return;
    if (locks.has(target.dataset.key) || mounts.has(target) || target.id === 'addon-body') return;
    for (const attr of [...target.attributes]) {
      if (attr.name === 'open' && target.tagName === 'DETAILS') continue;
      if (!source.hasAttribute(attr.name)) target.removeAttribute(attr.name);
    }
    for (const attr of [...source.attributes]) {
      if (target.getAttribute(attr.name) !== attr.value) target.setAttribute(attr.name, attr.value);
    }
    reconcile(target, source);
  }
  function reconcile(target, source) {
    const old = [...target.childNodes], used = new Set();
    for (const fresh of [...source.childNodes]) {
      const key = nodeKey(fresh);
      const existing = old.find(n => !used.has(n) && n.nodeType === fresh.nodeType && n.nodeName === fresh.nodeName && (key ? nodeKey(n) === key : !nodeKey(n)));
      const node = existing || fresh;
      const at = target.childNodes[used.size];
      if (node !== at) target.insertBefore(node, at || null);
      if (existing) sync(existing, fresh);
      used.add(node);
    }
    for (const node of old) if (!used.has(node) && !locks.has(node.dataset?.key)) node.remove();
  }
  function patch(target, html) {
    const template = document.createElement('template');
    template.innerHTML = html;
    reconcile(target, template.content);
  }
  const seenNeeds = new Set();
  function accept(next) {
    const first = !state;
    const arrived = new Set(array(next.needs).filter(n => !seenNeeds.has(n.id)).map(n => n.id));
    array(next.needs).forEach(n => seenNeeds.add(n.id));
    state = next;
    render(first ? new Set() : arrived);
  }
  function route() {
    const hash = location.hash || '#home';
    try {
      if (hash.startsWith('#ticket/')) return {kind:'ticket', id:decodeURIComponent(hash.slice(8)), hash};
      if (hash.startsWith('#addon/')) {
        const id = decodeURIComponent(hash.slice(7));
        if (addons().some(a => a.name === id && a.dashboard)) return {kind:'addon', id, hash};
      }
    } catch (_) { /* Malformed links fall back to Home. */ }
    return {kind:hash === '#tickets' ? 'tickets' : 'home', hash};
  }
  function render(arrived = new Set()) {
    if (!state) return;
    const r = route(), changed = !!renderedRoute && renderedRoute !== r.hash;
    const scroll = [window.scrollX, window.scrollY];
    const active = document.activeElement;
    const activeKey = nodeKey(active);
    const pageName = r.kind === 'addon' ? addonLabel(addons().find(a => a.name === r.id)) : r.kind === 'ticket' ? 'Ticket' : r.kind === 'tickets' ? 'Tickets' : 'Home';
    document.getElementById('workspace-name').textContent = clean(state.workspace || 'Workspace');
    document.getElementById('workspace-mode').textContent = snapshot ? 'Shared copy' : 'Local workspace';
    document.getElementById('crumb').textContent = pageName;
    const navLink = (url, text, glyph, tail = '') => '<a class="nav-item" href="' + esc(url) + '"' + ((r.kind === 'ticket' ? '#tickets' : r.kind === 'home' ? '#home' : r.hash) === url ? ' aria-current="page"' : '') + '>' + icon(glyph) + esc(text) + tail + '</a>';
    patch(nav, navLink('#home', 'Home', 'page', array(state.needs).length ? '<span class="count">' + array(state.needs).length + '</span>' : '') + navLink('#tickets', 'Tickets', 'table')
      + '<p class="eyebrow">Add-ons</p>' + addons().filter(a => a.dashboard).map(a => navLink('#addon/' + encodeURIComponent(a.name), addonLabel(a), a.dashboard.icon || a.icon, '<span class="addon-tag" aria-label="Add-on">A</span>')).join(''));
    if (changed) {
      for (const [host, mounted] of mounts) { if (main.contains(host)) { mounted.destroy(); mounts.delete(host); } }
      main.replaceChildren();
    }
    patch(main, r.kind === 'home' ? home() : r.kind === 'tickets' ? list() : r.kind === 'ticket' ? detail(ticketOf(r.id)) : addonTab(r.id));
    for (const [host, mounted] of mounts) if (!host.isConnected) { mounted.destroy(); mounts.delete(host); }
    main.querySelectorAll('[data-question]').forEach(host => {
      if (!mounts.has(host)) {
        const t = ticketOf(host.dataset.ticket), q = array(t?.questions).find(q => q.id === host.dataset.question);
        if (q) mountQuestion(host, {ticket:t.id, id:q.id, title:q.text, text:'', options:array(q.options).map(o => ({text:o, suggested:o === q.recommended}))});
      }
    });
    if (r.kind === 'addon') {
      if (activeAddon !== r.id) startAddon(r.id);
      else if (!document.getElementById('addon-body').childNodes.length) paintAddon(r.id);
    } else {
      clearInterval(addonTimer); activeAddon = null;
    }
    if (!changed && renderedRoute === r.hash && r.kind === 'home') {
      main.querySelectorAll('[data-need-row]').forEach(row => { if (arrived.has(row.dataset.needRow)) window.orch.needsIn(row); });
    }
    if (changed) window.orch.enter(main);
    renderedRoute = r.hash;
    if (!active?.isConnected && activeKey && !document.querySelector('dialog[open]')) {
      [...document.querySelectorAll('a,button,summary')].find(n => nodeKey(n) === activeKey)?.focus({preventScroll:true});
    }
    window.scrollTo(...(changed ? [0, 0] : scroll));
  }

  const addonViews = Object.create(null), addonBusy = new Set();
  let addonTimer, activeAddon = null;
  const addonLabel = a => a?.dashboard?.label || a?.label || a?.name || 'Add-on';
  function addonTab(id) {
    return heading(addonLabel(addons().find(a => a.name === id))) + '<div id="addon-body" class="stack" data-name="' + esc(id) + '"></div>';
  }
  function addonBody(a, res) {
    if (!res) return '<div class="skeleton addon-loading" role="status" aria-label="Loading"></div>';
    const retry = snapshot ? '' : '<button type="button" class="btn outline sm" data-action="retry-addon">Try again</button>';
    if (res.state === 'error' || !res.view) return '<section class="card pad stack"><h2>Can’t show ' + esc(addonLabel(a)) + ' right now.</h2><p>' + esc(res.message || 'No answer.') + ' Nothing here was changed.</p>' + retry + '</section>';
    return '<p class="meta">As of ' + esc(time(res.as_of)) + '</p>'
      + (res.state === 'stale' ? '<div class="banner attn" role="status"><p class="grow">Not up to date. Showing the last answer from ' + esc(time(res.as_of)) + '.</p>' + retry + '</div>' : '')
      + (res.view.notice ? '<p class="banner ' + (res.view.notice_tone === 'bad' ? 'error' : ['warn', 'needs-you'].includes(res.view.notice_tone) ? 'attn' : '') + '">' + esc(clean(res.view.notice)) + '</p>' : '') + '<div id="addon-blocks"></div>';
  }
  function paintAddon(id) {
    const host = document.getElementById('addon-body'), a = addons().find(a => a.name === id);
    if (!host || host.dataset.name !== id || !a) return;
    const scroll = [window.scrollX, window.scrollY];
    const template = document.createElement('div');
    template.innerHTML = addonBody(a, addonViews[id]);
    const blocks = template.querySelector('#addon-blocks');
    if (blocks) {
      blocks.append(OrchBlocks.render(addonViews[id].view.blocks));
      if (!blocks.childNodes.length) blocks.innerHTML = '<section class="card pad muted">Nothing to show yet.</section>';
      blocks.querySelectorAll('.blk').forEach(n => n.classList.add('card'));
      blocks.querySelectorAll('svg').forEach(n => {
        const replacement = el('span');
        replacement.innerHTML = icon('external');
        n.replaceWith(replacement);
      });
      // Block text is supplied by add-ons; keep internal keys out of visible copy.
      const walker = document.createTreeWalker(blocks, NodeFilter.SHOW_TEXT);
      while (walker.nextNode()) walker.currentNode.data = clean(walker.currentNode.data);
    }
    reconcile(host, template);
    host.querySelectorAll('[data-action="retry-addon"]').forEach(n => { n.disabled = false; });
    window.scrollTo(...scroll);
  }
  async function loadAddon(id, manual = false) {
    if (addonBusy.has(id)) return;
    addonBusy.add(id);
    const retry = main.querySelector('[data-action="retry-addon"]');
    if (manual && retry) { retry.disabled = true; retry.textContent = 'Trying…'; }
    try {
      if (snapshot) addonViews[id] = state.views?.[id] || {state:'error', message:'This shared copy has no view.'};
      else {
        const res = await fetch('/api/addon/' + encodeURIComponent(id), {cache:'no-store'});
        if (!res.ok) throw new Error('No answer.');
        addonViews[id] = await res.json();
      }
    } catch (_) {
      addonViews[id] = addonViews[id]?.view ? {...addonViews[id], state:'stale'} : {state:'error', message:'No answer.'};
    } finally { addonBusy.delete(id); }
    if (route().kind === 'addon' && route().id === id) paintAddon(id);
  }
  function startAddon(id) {
    clearInterval(addonTimer);
    activeAddon = id;
    paintAddon(id);
    loadAddon(id);
    if (!snapshot) addonTimer = setInterval(() => loadAddon(id), 15000);
  }

  async function act(op, args) {
    if (snapshot) return {ok:false, status:0, text:'This is a shared copy.'};
    writing++;
    mutation++;
    try {
      const res = await fetch('/api/act', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({op, args})});
      if (res.status !== 200) return {ok:false, status:res.status, text:await res.text()};
      const next = await res.json();
      accept(next);
      return {ok:true, status:200, state:next};
    } catch (err) { return {ok:false, status:0, text:err.message || 'Could not reach orch.'}; }
    finally { writing--; }
  }
  async function refresh() {
    if (snapshot || fetching || writing) return;
    fetching = true;
    const version = mutation;
    const connection = document.getElementById('connection');
    try {
      const res = await fetch('/api/state', {cache:'no-store'});
      if (!res.ok) throw new Error('Could not load the workspace.');
      const next = await res.json();
      if (writing || version !== mutation) return;
      connection.hidden = true;
      if (!state || next.rev !== state.rev) accept(next);
    } catch (_) {
      connection.textContent = state ? 'Can’t refresh right now. Showing the last update; trying again shortly.' : 'Can’t load your workspace right now. Trying again shortly.';
      connection.hidden = false;
    } finally { fetching = false; }
  }
  function dialog(title, cls = 'dialog', lock = '') {
    const d = el('dialog', cls);
    const id = 'dialog-title-' + (++serial);
    const h = el('h2', '', clean(title)); h.id = id;
    d.setAttribute('aria-labelledby', id); d.append(h);
    const trigger = document.activeElement;
    const triggerKey = nodeKey(trigger);
    const actions = el('div', 'actions');
    actions.append(button('Cancel', 'ghost', () => window.orch.close(d)));
    if (lock) locks.add(lock);
    d.addEventListener('close', () => {
      const resolving = d.dataset.resolving === 'true';
      if (lock && !resolving) locks.delete(lock);
      for (const [host, mounted] of mounts) if (d.contains(host)) { mounted.destroy(); mounts.delete(host); }
      d.remove();
      if (!resolving) render();
      if (trigger?.isConnected) trigger.focus({preventScroll:true});
      else if (triggerKey) [...document.querySelectorAll('a,button')].find(n => nodeKey(n) === triggerKey)?.focus({preventScroll:true});
    });
    document.body.append(d);
    return {d, actions};
  }
  function mountQuestion(host, q, context = {}) {
    const mounted = window.QuestionCard.mount(host, {...q, title:clean(q.title), text:clean(q.text)}, {
      send: async answer => {
        const lock = context.lock || host.dataset.key;
        if (lock) locks.add(lock);
        const result = await act('answer', {ticket:q.ticket, question:q.id, answer});
        if (!result.ok) {
          if (lock && !context.dialog) locks.delete(lock);
          return {status:result.status === 409 ? 409 : 0, message:result.text, other:{text:result.text}};
        }
        const answered = array(ticketOf(q.ticket)?.questions).find(x => x.id === q.id);
        const who = name(answered?.answered_by || result.state.who) || 'You';
        // Let the shared card finish its send transition before releasing its host.
        setTimeout(async () => {
          window.orch.toast('Answered · ' + who + ' · dashboard', 'ok');
          if (context.dialog) {
            context.dialog.dataset.resolving = 'true';
            await window.orch.close(context.dialog);
          }
          if (context.row?.isConnected) await window.orch.resolve(context.row);
          if (lock) locks.delete(lock);
          if (host.isConnected && mounts.has(host)) { mounts.get(host).destroy(); mounts.delete(host); }
          render();
          if (!document.querySelector('dialog[open]') && !document.activeElement?.closest('button,a,input,textarea')) {
            main.querySelector('h1')?.setAttribute('tabindex', '-1');
            main.querySelector('h1')?.focus({preventScroll:true});
          }
          refresh();
        }, 0);
        return {status:200, who, via:'dashboard'};
      }
    });
    // The shared component uses the real key for persistence; only its visible label changes.
    const label = host.querySelector('.qmeta .muted');
    if (label) label.textContent = clean(ticketOf(q.ticket)?.title) || 'Ticket';
    mounts.set(host, mounted);
  }
  function openNeed(row, trigger) {
    if (!row) return;
    if (row.answer && row.kind !== 'overdue-wait') {
      const {d, actions} = dialog(row.title, 'dialog', 'needs-you');
      const host = el('div');
      d.append(host, actions);
      mountQuestion(host, {ticket:row.ticket, id:row.answer.question, title:row.title, text:row.text, options:array(row.answer.options).map(o => ({text:o, suggested:o === row.answer.recommended}))}, {dialog:d, row:trigger.closest('[data-need-row]'), lock:'needs-you'});
      window.orch.open(d);
    } else if (ticketOf(row.ticket)) location.hash = href(row.ticket);
    else {
      const a = addons().find(a => a.dashboard && (a.name === row.source || String(row.kind).startsWith(a.name + ':')));
      if (a) location.hash = '#addon/' + encodeURIComponent(a.name);
      else {
        const {d, actions} = dialog(row.title);
        d.append(el('p', 'preserve-lines', clean(row.text || 'No further details.')), actions);
        window.orch.open(d);
      }
    }
  }
  function ticketForm(t) {
    const {d, actions} = dialog(t ? 'Edit ticket' : 'New ticket', t ? 'sheet' : 'dialog', t ? 'ticket-meta' : '');
    const form = el('form'), fields = el('div', 'form-fields'), inputs = {};
    for (const field of (t ? ['owner', 'due', 'note'] : ['title', 'owner', 'due', 'note'])) {
      const label = el('label', '', field.charAt(0).toUpperCase() + field.slice(1) + (field === 'title' ? '' : ' (optional)'));
      const input = el(field === 'note' ? 'textarea' : 'input', 'input');
      input.name = field; input.id = 'field-' + serial + '-' + field;
      if (field !== 'note') input.type = field === 'due' ? 'date' : 'text';
      if (field === 'title') { input.required = true; input.maxLength = 200; }
      input.value = t?.[field] || '';
      label.htmlFor = input.id; label.append(input); fields.append(label); inputs[field] = input;
    }
    const error = el('p', 'bad'); error.setAttribute('role', 'alert');
    const reload = button('Reload ticket', 'outline sm', async () => { await refresh(); await window.orch.close(d); const latest = ticketOf(t?.id); if (latest) ticketForm(latest); });
    reload.hidden = true;
    const submit = el('button', 'btn primary', t ? 'Save changes' : 'Create ticket'); submit.type = 'submit';
    actions.append(submit);
    form.append(fields, error, reload, actions); d.append(form);
    let created = null, creationUnresolved = false;
    form.addEventListener('submit', async event => {
      event.preventDefault();
      if (!form.reportValidity() || submit.disabled || creationUnresolved) return;
      submit.disabled = true; error.textContent = ''; reload.hidden = true;
      const values = Object.fromEntries(Object.entries(inputs).map(([key, input]) => [key, input.value.trim()]));
      let result;
      if (t) result = await act('ticket.edit', {ticket:t.id, owner:values.owner, due:values.due, note:values.note, if_revision:t.revision});
      else {
        if (!created) {
          const previous = new Set(tickets().map(t => t.id));
          result = await act('ticket.new', {title:values.title});
          if (result.ok) {
            created = tickets().filter(t => t.title === values.title && !previous.has(t.id)).sort((a, b) => (Date.parse(b.created_at) || 0) - (Date.parse(a.created_at) || 0))[0];
            if (!created) {
              creationUnresolved = true;
              result = {ok:false, status:0, text:'The ticket was created, but could not be found in the reply. Close this dialog and reload before trying again.'};
            }
          }
        } else result = {ok:true};
        if (result.ok && created && (values.owner || values.due || values.note)) {
          result = await act('ticket.edit', {ticket:created.id, owner:values.owner, due:values.due, note:values.note});
        }
      }
      submit.disabled = creationUnresolved;
      if (!result.ok) {
        error.textContent = result.text + (result.status === 409 ? ' Reload the ticket before trying again.' : '');
        reload.hidden = !(t && result.status === 409);
        if (created) { inputs.title.disabled = true; submit.textContent = 'Save details'; }
        return;
      }
      window.orch.toast(t ? 'Ticket updated' : 'Ticket created', 'ok');
      await window.orch.close(d);
    });
    window.orch.open(d);
  }
  document.getElementById('new-ticket').hidden = snapshot;
  document.getElementById('new-ticket').addEventListener('click', () => ticketForm());
  const toggle = document.getElementById('menu-toggle');
  toggle.addEventListener('click', () => {
    const open = toggle.getAttribute('aria-expanded') !== 'true';
    toggle.setAttribute('aria-expanded', String(open));
    document.querySelector('.sidebar').dataset.open = String(open);
  });
  nav.addEventListener('click', event => {
    if (!event.target.closest('a')) return;
    toggle.setAttribute('aria-expanded', 'false');
    document.querySelector('.sidebar').dataset.open = 'false';
  });
  main.addEventListener('click', async event => {
    const control = event.target.closest('[data-action]');
    if (!control) return;
    const action = control.dataset.action;
    if (action === 'group') {
      const group = control.dataset.group;
      if (expanded.has(group)) expanded.delete(group); else expanded.add(group);
      render(); return;
    }
    if (snapshot) return;
    if (action === 'new') ticketForm();
    if (action === 'edit') ticketForm(ticketOf(control.dataset.ticket));
    if (action === 'need') openNeed(array(state.needs).find(n => n.id === control.dataset.need), control);
    if (action === 'retry-addon') loadAddon(route().id, true);
    if (action === 'start') {
      if (locks.has('background')) return;
      locks.add('background');
      control.disabled = true;
      for (const service of array(state.services).filter(s => s.running === false)) {
        const result = await act('addon.start', {addon:service.addon});
        if (!result.ok) { window.orch.toast(result.text, 'error'); break; }
      }
      locks.delete('background');
      control.disabled = false;
      render();
    }
  });
  window.addEventListener('hashchange', async () => {
    for (const d of document.querySelectorAll('dialog[open]')) await window.orch.close(d);
    render();
  });
  if (snapshot) accept(window.ORCH_SNAPSHOT || {});
  else { refresh(); setInterval(refresh, 3000); }
})();

