'use strict';
(() => {
  const snapshot = typeof window.ORCH_SNAPSHOT !== 'undefined';
  const main = document.getElementById('content');
  const nav = document.getElementById('side-nav');
  const array = value => Array.isArray(value) ? value : [];
  const clean = value => String(value ?? '').replace(/\b(?:ws|t|q|m|ph|wh|b|f)_[a-zA-Z0-9]{4,}\b/g, '').replace(/\s+·\s+·/g, ' · ').trim();
  const name = value => clean(String(value ?? '').replace(/^(human|agent):/, ''));
  const icon = value => {
    const svg = window.icon(String(value || 'page'));
    return /<(path|rect|circle|polyline|line|ellipse)\b/.test(svg) ? svg : window.icon('page');
  };
  function iconEl(name) {
    const node = document.createElement('span');
    node.className = 'ic-wrap';
    node.innerHTML = icon(name); // ic-wrap: only trusted kit icons use markup.
    return node;
  }
  function append(node, children) {
    for (const child of children.flat(Infinity)) {
      if (child == null || child === false) continue;
      node.appendChild(child instanceof Node ? child : document.createTextNode(String(child)));
    }
    return node;
  }
  function h(tag, attrs = {}, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs)) {
      if (value == null) continue;
      if (key === 'href' && !/^(#|https?:)/i.test(String(value))) continue;
      if (key.startsWith('data-')) node.dataset[key.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = String(value);
      else if (['className', 'hidden', 'disabled'].includes(key)) node[key] = value;
      else node.setAttribute(key, String(value));
    }
    return append(node, children);
  }
  const fragment = (...children) => append(document.createDocumentFragment(), children);
  const capitalise = value => String(value).replace(/^./, c => c.toUpperCase());
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
  const chip = (text, cls = '') => h('span', {className:'chip ' + cls}, text);
  const statusChip = t => chip(activeTicket(t) && (t.status === 'waiting' || questions(t).length) ? 'Blocked' : statusWord(t), activeTicket(t) && (t.status === 'waiting' || questions(t).length) ? 'attn' : t.status === 'active' ? 'active' : '');
  const heading = (title, sub = '') => h('header', {className:'page-heading', 'data-key':'heading'}, h('h1', {}, clean(title)), sub ? h('p', {className:'muted'}, sub) : null);
  const card = (key, title, suffix, body, chevron = false) => h('section', {className:'card', 'data-key':key, id:key === 'needs-you' ? key : null}, h('div', {className:'card-h'}, chevron ? iconEl('down') : null, h('h2', {}, title, suffix ? h('span', {className:'muted'}, ' · ', suffix) : null)), body);
  const emptyRow = text => h('div', {className:'card-row muted'}, text);
  const newButton = () => snapshot ? null : h('button', {type:'button', className:'btn primary sm', 'data-action':'new'}, 'New ticket');
  const firstTicket = () => h('div', {className:'card-row'}, h('p', {className:'grow muted'}, 'Your first ticket starts here.'), newButton());
  function ticketRow(t) {
    const meta = [name(t.owner), t.due ? 'Due ' + date(t.due) : '', statusWord(t)].filter(Boolean);
    const parent = ticketOf(t.parent);
    let late = '';
    if (overdue(t)) {
      const days = Math.round((Date.parse(today()) - Date.parse(t.due)) / 86400000);
      late = chip('Overdue ' + days + (days === 1 ? ' day' : ' days'), 'error');
    }
    return h('div', {className:'card-row ticket-row', 'data-key':'ticket-' + t.id}, h('div', {className:'grow'}, h('h3', {}, h('a', {href:href(t.id)}, clean(t.title))), h('p', {className:'meta'}, meta.join(' · ')), parent ? h('p', {className:'meta'}, 'Part of ', clean(parent.title)) : null), h('div', {className:'row'}, late, statusChip(t)));
  }
  function needRow(row, newest) {
    const t = ticketOf(row.ticket);
    const claim = state.runs?.[row.ticket]?.claim;
    const by = name(row.agent || row.by || claim?.agent || claim?.by);
    const meta = [typeof t?.key === 'string' ? clean(t.key) : '', by, t && clean(t.title)].filter(Boolean).join(' · ');
    const choice = window.DashHelpers.needAction(row);
    const action = snapshot
      ? (t ? h('a', {className:'btn outline sm', href:href(t.id)}, 'Open') : null)
      : h('button', {type:'button', className:'btn outline sm', 'data-action':'need', 'data-need':row.id}, choice.label);
    return h('div', {className:'card-row', 'data-key':'need-' + row.id, 'data-need-row':row.id, 'data-newest':row.id === newest ? '' : null}, h('span', {className:'need-icon ' + (row.tone === 'bad' ? 'bad' : row.tone === 'warn' ? 'warn' : 'muted')}, iconEl(row.tone === 'bad' ? 'stop' : row.tone === 'warn' ? 'shield' : 'note')), h('div', {className:'grow'}, h('h3', {}, clean(row.text)), h('p', {className:'meta'}, meta)), h('time', {datetime:row.since || ''}, age(row.since)), action);
  }
  function home() {
    const needs = array(state.needs);
    const rows = window.DashHelpers.agentRows(state.tickets, state.runs, Date.now());
    const working = rows.filter(row => ['working', 'needs', 'stuck'].includes(row.state));
    const current = sorted(tickets().filter(activeTicket));
    const oldest = needs.map(n => parse(n.since)).filter(Boolean).sort((a, b) => a - b)[0];
    const newest = needs.slice().sort((a, b) => (Date.parse(b.since) || 0) - (Date.parse(a.since) || 0))[0]?.id;
    const history = tickets().flatMap(t => array(t.history).map(entry => ({entry, title:t.title}))).sort((a, b) => (Date.parse(b.entry.at) || 0) - (Date.parse(a.entry.at) || 0)).slice(0, 5);
    const stopped = array(state.services).some(s => s.running === false);
    const banner = stopped ? h('div', {className:'banner attn', 'data-key':'background'}, h('p', {className:'grow'}, 'Background work is not running. Start it so repeating work and checks can run.'), snapshot ? null : h('button', {type:'button', className:'btn outline sm', 'data-action':'start'}, 'Start')) : null;
    const agents = rows.slice(0, 5).map(row => h('div', {className:'card-row', 'data-key':'agent-' + row.agent + '-' + row.ticket}, h('span', {className:'dot ' + (row.state === 'stuck' ? 'needs' : row.state)}), h('div', {className:'grow'}, h('h3', {}, capitalise(name(row.agent) || 'Agent') + ' · ' + ({working:'working', needs:'needs you', stuck:'may be stuck', idle:'idle'}[row.state])), h('p', {className:'meta'}, row.state === 'idle' ? 'Last worked ' + age(row.since) + ' ago' : [clean(ticketOf(row.ticket)?.title), age(row.since)].filter(Boolean).join(' · ')))));
    const links = window.DashHelpers.serviceLinks(state.services, location.origin);
    const recent = history.map(({entry, title}) => {
      const line = clean(window.DashHelpers.historyLine(entry));
      return h('div', {className:'card-row'}, h('div', {className:'grow'}, h('h3', {}, line.length > 80 ? line.slice(0, 79) + '…' : line), h('p', {className:'meta'}, [name(entry.by), clean(title), age(entry.at)].filter(Boolean).join(' · '))));
    });
    return fragment(heading('Today', now().toLocaleDateString('en-GB', {weekday:'long', day:'numeric', month:'long'}) + ' · ' + needs.length + ' need you · ' + working.length + (working.length === 1 ? ' agent working' : ' agents working')), banner,
      h('div', {className:'columns', 'data-key':'columns'}, h('div', {className:'stack', 'data-key':'left'},
        card('needs-you', 'Needs you', needs.length + (oldest ? ' · oldest ' + age(oldest) : ''), needs.length ? needs.map(n => needRow(n, newest)) : emptyRow('Nothing needs you right now.'), true),
        card('your-tickets', 'Your tickets', current.length + ' · ' + current.filter(overdue).length + ' overdue', current.length ? current.map(ticketRow) : firstTicket(), true)),
      h('aside', {className:'stack', 'data-key':'right'},
        card('agents', 'Agents', working.length + ' working', [agents.length ? agents : emptyRow('No agent is working right now.'), links.length ? h('div', {className:'card-row'}, links.map(link => h('a', {className:'meta', href:link.url, target:'_blank', rel:'noopener noreferrer'}, 'Open ' + capitalise(link.label) + ' →'))) : null]),
        card('recently', 'Recently', '', recent.length ? recent : emptyRow('No recent activity.')))));
  }
  const expanded = new Set();
  function list() {
    return fragment(heading('Tickets'), !tickets().length ? card('empty', 'Tickets', '', firstTicket()) : ['active', 'waiting', 'open', 'done', 'dropped'].map(status => {
      const group = sorted(tickets().filter(t => t.status === status));
      if (!group.length) return null;
      const title = {active:'Doing', waiting:'Waiting', open:'Open', done:'Done', dropped:'Dropped'}[status];
      if (!['done', 'dropped'].includes(status)) return card('group-' + status, title, group.length, group.map(ticketRow));
      const open = expanded.has(status);
      return h('section', {className:'card', 'data-key':'group-' + status}, h('button', {type:'button', className:'card-h card-toggle', 'data-action':'group', 'data-group':status, 'aria-expanded':open, 'aria-controls':'group-' + status}, h('span', {className:'chevron ' + (open ? '' : 'closed')}, iconEl('down')), h('span', {}, title + ' · ' + group.length)), h('div', {id:'group-' + status, hidden:!open}, group.map(ticketRow)));
    }));
  }
  function addonValue(row, value) {
    if (value == null || value === '' || (Array.isArray(value) && !value.length)) return '';
    if (row.format === 'time') return [date(value), time(value)].filter(Boolean).join(' ');
    if (row.format === 'cron-human') return String(value);
    if (row.format === 'yes-no') return value === true ? 'Yes' : value === false ? 'No' : '';
    if (row.format === 'chips') return h('div', {className:'chips'}, array(value).map(v => chip(clean(v))));
    return typeof value === 'object' ? '' : clean(value);
  }
  function addonRows(ticket) {
    const rows = addons().flatMap(a => array(a.ticket_view).map(r => [r, (ticket.ext || {})[a.name]]))
      .map(([r, ext]) => [r, ext && typeof ext === 'object' ? addonValue(r, ext[r.field]) : '']).filter(([, v]) => v);
    return rows.length ? h('dl', {className:'addon-rows'}, rows.map(([r, v]) => [h('dt', {}, r.label), h('dd', {}, v)])) : null;
  }
  function detail(t) {
    if (!t) return fragment(heading('Ticket not found'), h('a', {href:'#tickets'}, 'All tickets'));
    const qs = questions(t).map(q => snapshot
      ? card('question-' + q.id, clean(q.text), '', h('div', {className:'card-row'}, h('div', {className:'grow'}, h('p', {className:'muted'}, 'Waiting for an answer'), h('div', {className:'row'}, array(q.options).map(o => chip(clean(o), o === q.recommended ? 'attn' : ''))))))
      : h('div', {'data-key':'question-' + q.id, 'data-question':q.id, 'data-ticket':t.id}));
    // Evidence.chip produces preview buttons; without a preview URL, plain proof chips are clearer.
    const tasks = array(t.checklist).map(task => h('div', {className:'card-row'}, h('span', {className:'muted', 'aria-hidden':'true'}, iconEl(task.done ? 'check' : 'more')), h('div', {className:'grow'}, h('h3', {}, clean(task.text)), h('p', {className:'meta'}, task.done ? 'Done' : 'Not done'), h('div', {className:'row'}, array(task.evidence).map(ev => chip(clean(ev.summary || ev.text || ev.ref || 'Proof')))))));
    const history = array(t.history).slice().sort((a, b) => (Date.parse(b.at) || 0) - (Date.parse(a.at) || 0)).map(entry => h('div', {className:'card-row'}, h('p', {}, [clean(entry.text), name(entry.by), age(entry.at)].filter(Boolean).join(' · '))));
    const field = (label, value, cls = '') => h('div', {}, h('dt', {}, label), h('dd', {className:cls}, value));
    return fragment(h('a', {href:'#tickets', 'data-key':'back'}, 'All tickets'), heading(t.title),
      h('div', {className:'row', 'data-key':'ticket-meta'}, statusChip(t), t.owner ? chip(name(t.owner)) : null, t.due ? chip('Due ' + date(t.due)) : null, snapshot ? null : h('button', {type:'button', className:'btn outline sm', 'data-action':'edit', 'data-ticket':t.id}, 'Edit')),
      t.summary ? h('p', {'data-key':'summary', className:'preserve-lines'}, clean(t.summary)) : null,
      qs, card('tasks', 'Tasks', array(t.checklist).length, tasks.length ? tasks : emptyRow('No tasks yet.')),
      card('history', 'History', '', history.length ? history : emptyRow('No history yet.')), addonRows(t),
      h('details', {'data-key':'more'}, h('summary', {}, 'More details'), h('dl', {className:'ticket-details'}, field('Ticket', t.id, 'mono'), field('Created', date(t.created_at)), field('Updated', date(t.updated_at)), t.note ? field('Note', clean(t.note), 'preserve-lines') : null)));
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
    const navLink = (url, text, glyph, tail = null) => h('a', {className:'nav-item', href:url, 'aria-current':(r.kind === 'ticket' ? '#tickets' : r.kind === 'home' ? '#home' : r.hash) === url ? 'page' : null}, iconEl(glyph), text, tail);
    reconcile(nav, fragment(navLink('#home', 'Home', 'page', array(state.needs).length ? h('span', {className:'count'}, array(state.needs).length) : null), navLink('#tickets', 'Tickets', 'table'),
      h('p', {className:'eyebrow'}, 'Add-ons'), addons().filter(a => a.dashboard).map(a => navLink('#addon/' + encodeURIComponent(a.name), addonLabel(a), a.dashboard.icon || a.icon, h('span', {className:'addon-tag', 'aria-label':'Add-on'}, 'A')))));
    if (changed) {
      for (const [host, mounted] of mounts) { if (main.contains(host)) { mounted.destroy(); mounts.delete(host); } }
      main.replaceChildren();
    }
    reconcile(main, r.kind === 'home' ? home() : r.kind === 'tickets' ? list() : r.kind === 'ticket' ? detail(ticketOf(r.id)) : addonTab(r.id));
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
    return fragment(heading(addonLabel(addons().find(a => a.name === id))), h('div', {id:'addon-body', className:'stack', 'data-name':id}));
  }
  function addonBody(a, res) {
    if (!res) return fragment(h('div', {className:'skeleton addon-loading', role:'status', 'aria-label':'Loading'}));
    const retry = snapshot ? null : h('button', {type:'button', className:'btn outline sm', 'data-action':'retry-addon'}, 'Try again');
    if (res.state === 'error' || !res.view) return fragment(h('section', {className:'card pad stack'}, h('h2', {}, 'Can’t show ', addonLabel(a), ' right now.'), h('p', {}, res.message || 'No answer.', ' Nothing here was changed.'), retry));
    return fragment(h('p', {className:'meta'}, 'As of ', time(res.as_of)),
      res.state === 'stale' ? h('div', {className:'banner attn', role:'status'}, h('p', {className:'grow'}, 'Not up to date. Showing the last answer from ', time(res.as_of), '.'), retry) : null,
      res.view.notice ? h('p', {className:'banner ' + (res.view.notice_tone === 'bad' ? 'error' : ['warn', 'needs-you'].includes(res.view.notice_tone) ? 'attn' : '')}, clean(res.view.notice)) : null, h('div', {id:'addon-blocks'}));
  }
  function paintAddon(id) {
    const host = document.getElementById('addon-body'), a = addons().find(a => a.name === id);
    if (!host || host.dataset.name !== id || !a) return;
    const scroll = [window.scrollX, window.scrollY];
    const template = addonBody(a, addonViews[id]);
    const blocks = template.querySelector('#addon-blocks');
    if (blocks) {
      blocks.append(OrchBlocks.render(addonViews[id].view.blocks));
      if (!blocks.childNodes.length) blocks.append(h('section', {className:'card pad muted'}, 'Nothing to show yet.'));
      blocks.querySelectorAll('.blk').forEach(n => n.classList.add('card'));
      blocks.querySelectorAll('svg').forEach(n => {
        n.replaceWith(iconEl('external'));
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
          let fresh = result.state;
          try {
            if (!fresh) {
              const res = await fetch('/api/state', {cache:'no-store'});
              if (res.ok) fresh = await res.json();
            }
          } catch (_) { /* Keep the original send error if the refresh also fails. */ }
          const win = window.DashHelpers.winningAnswer(fresh?.tickets, q.ticket, q.id);
          // Keep the mounted card and any open dialog intact while accepting the refresh.
          if (fresh) { mutation++; accept(fresh); }
          if (lock && !context.dialog) locks.delete(lock);
          if (win !== null) return {status:409, other:{text:win.text, who:name(win.who), via:win.via}};
          return {status:0, message:result.text};
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
  async function openNeed(row, trigger) {
    if (!row) return;
    const action = window.DashHelpers.needAction(row);
    if (action.kind === 'run') {
      if (trigger.disabled) return;
      trigger.disabled = true;
      const result = await act('run.start', {ticket:row.ticket});
      trigger.disabled = false;
      window.orch.toast(result.ok ? 'Started again' : result.text, result.ok ? 'ok' : 'error');
      return;
    }
    if (action.kind === 'answer' || action.kind === 'review') {
      const {d, actions} = dialog(row.title, 'dialog', 'needs-you');
      const host = el('div');
      d.append(host, actions);
      mountQuestion(host, {ticket:row.ticket, id:row.answer.question, title:row.title, text:row.text, options:array(row.answer.options).map(o => ({text:o, suggested:o === row.answer.recommended}))}, {dialog:d, row:trigger.closest('[data-need-row]'), lock:'needs-you'});
      window.orch.open(d);
    } else if (row.ticket) location.hash = href(row.ticket);
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
  // An add-on row's switch or button: the DOM only carries verb + ticket (blocks.js checked them); the page adds
  // the add-on of the open tab, so a view can never address another add-on.
  async function addonAct(control) {
    const id = route().id;
    if (route().kind !== 'addon' || control.disabled || locks.has('addon-act')) return;
    const send = async () => {
      locks.add('addon-act'); control.disabled = true;
      const result = await act('addon.act', {addon:id, verb:control.dataset.verb, target:control.dataset.target});
      locks.delete('addon-act'); control.disabled = false;
      if (!result.ok) window.orch.toast(result.text || 'That did not work.', 'error');
      await loadAddon(id);
    };
    if (!control.dataset.confirm) return send();
    const {d, actions} = dialog(control.dataset.confirm, 'dialog');
    actions.append(button('Yes', 'primary', async () => { await window.orch.close(d); send(); }));
    d.append(actions);
    window.orch.open(d);
  }
  async function copyText(control) {
    try { await navigator.clipboard.writeText(control.dataset.copy); window.orch.toast('Copied', 'ok'); }
    catch (_) { window.orch.toast('Could not copy. Select the text and copy it.', 'error'); }
  }
  main.addEventListener('click', async event => {
    const row = event.target.closest('[data-addon-act]');
    if (row) { if (!snapshot) addonAct(row); return; }
    const copy = event.target.closest('[data-copy]');
    if (copy) { copyText(copy); return; }
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
      const result = await act('addon.start', {});
      if (!result.ok) window.orch.toast(result.text, 'error');
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

