'use strict';
// Shell: shared state and helpers, router, polling/SSE, delegated event handlers. Loaded LAST (classic script, shares the page-wide scope with pages/*.js).
const snapshot = typeof window.ORCH_SNAPSHOT !== 'undefined';
const main = document.getElementById('content');
const nav = document.getElementById('side-nav');
const array = value => Array.isArray(value) ? value : [];
// Workspace ids are stored as they are (answered_by, history); people read the group member's name. Filled from state.groups.
let wsNames = new Map();
const showWs = value => String(value ?? '').replace(/\bws_[a-zA-Z0-9]{4,}\b/g, id => wsNames.get(id) || '');
const clean = value => showWs(value).replace(/\b(?:ws|t|q|m|ph|wh|b|f)_[a-zA-Z0-9]{4,}\b/g, '').replace(/\s+·\s+·/g, ' · ').trim();
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
  return window.DashHelpers.ago(d.toISOString(), now().getTime());  // one calm format: 'just now', '3 min ago'
};
const tickets = () => array(state?.tickets).filter(t => t.status !== 'dropped');
const addons = () => array(state?.addons);
const ticketOf = id => tickets().find(t => String(t.id) === String(id) || (typeof t.key === 'string' && t.key.toUpperCase() === String(id).toUpperCase()));
const href = id => '#ticket/' + encodeURIComponent(id);
const questions = t => array(t.questions).filter(q => q.answer == null);
const activeTicket = t => !['done', 'dropped'].includes(t.status);
const overdue = t => activeTicket(t) && t.due && t.due < today();
const newer = (a, b) => (Date.parse(b.updated_at) || 0) - (Date.parse(a.updated_at) || 0);
const sorted = list => list.slice().sort((a, b) => Number(!!overdue(b)) - Number(!!overdue(a)) || Number(questions(b).length > 0) - Number(questions(a).length > 0) || newer(a, b));
const statusWord = t => window.DashHelpers.statusWord(t.status, t.started);
const chip = (text, cls = '') => h('span', {className:'chip ' + cls}, text);
const shown = t => snapshot ? t : {...t, status: window.DashHelpers.shownStatus(t, state.runs?.[t.id])};
const statusChip = t => { const s = shown(t); return chip(statusWord(s), s.status === 'active' ? 'active' : ''); };
// Lifecycle order, one word per status: all from helpers.js.
const STATUS_CHOICES = window.DashHelpers.STATUS_CHOICES, MOVE_CHOICES = window.DashHelpers.MOVE_CHOICES;
const moveHome = status => status === 'waiting' ? 'active' : window.DashHelpers.columnOf(status);
const starting = new Set();
// The one chip of a ticket: what the agent or the person has to do now ('' when nothing).
function activityInfo(t) {
  const run = state.runs?.[t.id], live = run?.claim?.live;
  const agent = window.DashHelpers.agentLabel(state.settings, run?.claim);
  const getting = starting.has(t.id) || live?.state === 'starting';
  const busy = getting || (run?.running && !['idle', 'attention'].includes(live?.state));
  const text = getting ? 'Getting started…' : questions(t).length || live?.state === 'attention' ? 'Needs you' : t.status === 'review' ? 'Ready for review' : busy ? agent + ' is working' : '';
  return {run, live, agent, busy, text};
}
const needsList = () => window.DashHelpers.uniqueNeeds(state?.needs);
// one line of the question a waiting ticket asks, under its title
const questionLine = t => { const q = snapshot || window.DashHelpers.inNeeds(needsList(), t.id) ? '' : window.DashHelpers.questionPreview(t); return q ? h('p', {className:'meta question-line'}, clean(q)) : null; };
// "why · just now" under a ticket row's title; board and tree rows keep it under the chip
function activityNote(t) {
  const {live, agent, text} = activityInfo(t);
  const seconds = live?.since ? Math.max(0, Math.floor((Date.now() - Date.parse(live.since)) / 1000)) : null;
  const why = window.DashHelpers.plainWhy(live?.why, agent);
  return !text ? '' : [why, Number.isFinite(seconds) ? window.DashHelpers.ago(live.since, Date.now()) : ''].filter(Boolean).join(' · ');
}
function activity(t, where = '') {
  if (snapshot) return null;
  const {live, busy, text: full} = activityInfo(t);
  if (!full || (where === 'head' && questions(t).length)) return null;  // the banner is the one place for an open question
  if (full === 'Ready for review' && ['head', 'board'].includes(where)) return null;  // the status chip / column already says it: one chip
  const text = full;
  const note = where === 'row' ? '' : activityNote(t);  // in a row the chip sits on the Move to line, the note goes under the title
  const open = live?.state === 'attention' ? liveLinkFor(t) : null;
  return h('div', {className:'activity', 'data-key':'activity-' + t.id}, Object.assign(chip(text, busy && (text === 'Getting started…' || text.endsWith(' is working')) ? 'active activity-pulse' : 'attn'), text === 'Ready for review' ? {title:'Ready for review'} : text === 'Needs you' ? {title:'The agent asked you something'} : {}),
    note ? h('p', {className:'meta'}, note) : null,
    open ? h('a', {className:'btn outline xs', href:open.url, 'data-key':'activity-open-' + t.id}, 'Open the live session') : null);
}
const reviewActions = t => !snapshot && t.status === 'review' ? h('div', {className:'row'}, [['done', 'Mark done'], ['active', 'Send back']].map(([status, label]) => h('button', {type:'button', className:'btn outline xs', 'data-action':'status-set', 'data-ticket':t.id, 'data-status':status}, label))) : null;
const statusItems = (t, scope, choices = MOVE_CHOICES) => choices.map(([value, label]) => h('button', {type:'button', className:'menu-item' + (moveHome(t.status) === value || t.status === value ? ' sel' : ''), role:'menuitemradio', 'aria-checked':moveHome(t.status) === value || t.status === value, 'data-action':'status-set', 'data-ticket':t.id, 'data-status':value, 'data-key':'status-' + scope + '-' + t.id + '-' + value}, label));
// The visible "Move to" control: a labelled button (Apple HIG: a control says what it does; WCAG 2.5.3 label in name).
const statusControl = (t, scope) => {
  if (snapshot) return statusChip(t);
  return h('details', {className:'menu status-menu', 'data-key':'status-menu-' + scope + '-' + t.id}, h('summary', {className:'btn outline xs status-sum', 'aria-label':'Move to… ' + clean(t.title) + ' (now ' + statusWord(shown(t)) + ')'}, 'Move to', iconEl('down')), h('div', {className:'menu-pop', role:'menu', 'aria-label':'Move to'}, statusItems(t, scope)));
};
const heading = (title, sub = '') => h('header', {className:'page-heading', 'data-key':'heading'}, h('h1', {}, clean(title)), sub ? h('p', {className:'muted'}, sub) : null);
const card = (key, title, suffix, body, chevron = false) => h('section', {className:'card', 'data-key':key, id:key === 'needs-you' ? key : null}, h('div', {className:'card-h'}, chevron ? iconEl('down') : null, h('h2', {}, title, suffix ? h('span', {className:'muted'}, ' · ', suffix) : null)), body);
const emptyRow = text => h('div', {className:'card-row muted'}, text);
const newButton = () => snapshot ? null : h('button', {type:'button', className:'btn primary sm', 'data-action':'new'}, 'New ticket');
const firstTicket = () => h('div', {className:'card-row'}, h('p', {className:'grow muted'}, 'Your first ticket starts here.'), newButton());
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
  if (target.matches('[data-settings-agent],[data-settings-permissions]')) target.checked = source.checked;
  if (target.matches('[data-settings-field]')) {
    if (target.type === 'checkbox') target.checked = source.checked;
    else if (target.value !== source.value) target.value = source.value;
  }
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
  wsNames = new Map(['hosted', 'joined'].flatMap(k => array(state?.groups?.[k])).flatMap(g => [...array(g.members), ...array(g.connectable)]).filter(m => m && m.ws && m.name).map(m => [m.ws, String(m.name)]));
  window.dispatchEvent(new CustomEvent('orch:state', {detail: next}));
  render(first ? new Set() : arrived);
}
function route() {
  const hash = location.hash || '#home';
  if (hash === '#settings' && !snapshot && state?.settings) return {kind:'settings', hash};
  if (/^#chat\/ws_[a-z0-9]{10}$/.test(hash) && !snapshot) return {kind:'chat', hash};
  if (['#chat', '#general'].includes(hash) && (state?.chat || state?.general)) return {kind:'chat', hash:'#chat'};
  try {
    if (hash.startsWith('#ticket/')) return {kind:'ticket', id:decodeURIComponent(hash.slice(8)), hash};
    // One address per add-on page: #addon/<name>[/<path>]. The old #open/<name>/<path> forwards to it.
    const open = /^#open\/([a-z][a-z0-9-]{1,31})\/([A-Za-z0-9_./-]*)$/.exec(hash);
    if (open && !open[2].startsWith('/') && !open[2].includes('..') && addons().some(a => a.name === open[1] && a.page)) return {kind:'page', id:open[1], path:open[2], hash:'#addon/' + open[1] + (open[2] ? '/' + open[2] : '')};
    const own = /^#addon\/([a-z][a-z0-9-]{1,31})(?:\/([A-Za-z0-9_./-]*))?$/.exec(hash);
    if (own && !(own[2] || '').startsWith('/') && !(own[2] || '').includes('..') && addons().some(a => a.name === own[1] && a.page)) return {kind:'page', id:own[1], path:own[2] || '', hash};
    if (hash.startsWith('#addon/')) {
      const id = decodeURIComponent(hash.slice(7));
      if (addons().some(a => a.name === id && a.dashboard)) return {kind:'addon', id, hash};
    }
  } catch (_) { /* Malformed links fall back to Home. */ }
  return {kind:hash === '#tickets' ? 'tickets' : hash === '#notes' ? 'notes' : 'home', hash};
}
function render(arrived = new Set()) {
  if (!state) return;
  const r = route(), changed = !!renderedRoute && renderedRoute !== r.hash;
  if (r.kind === 'page' && location.hash !== r.hash) history.replaceState(null, '', r.hash);  // an old #open link shows the one address
  const scroll = [window.scrollX, window.scrollY];
  const active = document.activeElement;
  const activeKey = nodeKey(active);
  const pageName = r.kind === 'settings' ? 'Settings' : (r.kind === 'addon' || r.kind === 'page') ? addonLabel(addons().find(a => a.name === r.id)) : r.kind === 'ticket' ? 'Ticket' : r.kind === 'chat' ? 'Chat' : r.kind === 'tickets' ? 'Tickets' : r.kind === 'notes' ? 'Notes' : 'Home';
  document.getElementById('workspace-name').textContent = clean(state.workspace || 'Workspace');
  document.getElementById('workspace-mode').textContent = window.DashHelpers.footerState(state, snapshot);
  const crumb = document.getElementById('crumb');
  if (r.kind === 'ticket') {
    const tk = ticketOf(r.id);
    crumb.replaceChildren(h('a', {href:'#tickets'}, 'Tickets'), ' / ', typeof tk?.key === 'string' ? tk.key : clean(tk?.title) || 'Ticket');
  } else if (r.kind === 'page') {
    const last = r.path.split('/').filter(Boolean).pop() || '', tk = /^t_[A-Za-z0-9]+$/.test(last) ? ticketOf(last) : null;
    crumb.replaceChildren(pageName, ' › ', typeof tk?.key === 'string' ? tk.key : clean(tk?.title) || last);
  } else crumb.textContent = pageName;
  // On a narrow screen the header is one row: workspace icon, page name, New ticket, "Menu · N".
  const needCount = needsList().length, menuToggle = document.getElementById('menu-toggle');
  menuToggle.textContent = needCount ? 'Menu · ' + needCount : 'Menu';
  menuToggle.setAttribute('aria-label', needCount ? 'Menu, ' + window.DashHelpers.needsYou(needCount) : 'Menu');
  const wsIcon = document.getElementById('topbar-ws'), lookKey = JSON.stringify([state.look?.icon, state.look?.color, state.workspace]);
  if (window.OrchLook && state.look && wsIcon.dataset.look !== lookKey) { wsIcon.dataset.look = lookKey; wsIcon.replaceChildren(window.OrchLook.badge(state.look, clean(state.workspace) || 'Workspace', 26)); }
  const navLink = (url, text, glyph, tail = null) => h('a', {className:'nav-item', href:url, 'aria-current':(r.kind === 'ticket' ? '#tickets' : r.kind === 'home' ? '#home' : r.kind === 'page' ? '#addon/' + encodeURIComponent(r.id) : r.hash) === url ? 'page' : null}, iconEl(glyph), text, tail);
  reconcile(nav, fragment(navLink('#home', 'Home', 'page', needsList().length ? h('span', {className:'count', title:window.DashHelpers.needsYou(needsList().length), 'aria-label':window.DashHelpers.needsYou(needsList().length)}, window.DashHelpers.needsYou(needsList().length)) : null), navLink('#tickets', 'Tickets', 'table'), navLink('#notes', 'Notes', 'text'), state.chat || state.general ? navLink('#chat', 'Chat', 'text', chatBadge()) : null,
    // On a narrow screen the header has no room for "Open helper": it is a Menu item there (CSS shows it only then).
    snapshot ? null : h('button', {type:'button', className:'nav-item nav-helper', 'data-key':'nav-open-agent', 'data-nav':'open-agent'}, iconEl('spark'), 'Open helper'),
    addons().some(a => a.dashboard) ? h('p', {className:'eyebrow'}, 'Add-ons') : null, addons().filter(a => a.dashboard).map(a => navLink('#addon/' + encodeURIComponent(a.name), addonLabel(a), a.dashboard.icon || a.icon))));
  reconcile(document.getElementById('side-settings'), fragment(!snapshot && state.settings ? navLink('#settings', 'Settings', 'user') : null));
  if (changed) {
    for (const [host, mounted] of mounts) { if (main.contains(host)) { mounted.destroy(); mounts.delete(host); } }
    main.replaceChildren();
  }
  reconcile(main, r.kind === 'settings' ? settingsPage() : r.kind === 'home' ? home() : r.kind === 'tickets' ? list() : r.kind === 'notes' ? notesPage() : r.kind === 'chat' ? chatPage() : r.kind === 'ticket' ? detail(ticketOf(r.id)) : r.kind === 'page' ? pageFrame(r) : addonTab(r.id));
  for (const [host, mounted] of mounts) if (!host.isConnected) { mounted.destroy(); mounts.delete(host); }
  main.querySelectorAll('[data-question]').forEach(host => {
    if (!mounts.has(host)) {
      const t = ticketOf(host.dataset.ticket), q = array(t?.questions).find(q => q.id === host.dataset.question);
      if (q) mountQuestion(host, {ticket:t.id, key:typeof t.key === 'string' ? t.key : undefined, id:q.id, title:q.text, text:'', oneTap:true, kind:q.kind, options:array(q.options).map(o => ({text:o, suggested:o === q.recommended}))});
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

// Every notice goes through one scrub: no raw ids, actor names or UTC times reach a person.
if (window.orch && !window.orch.__scrubbed) {
  const rawToast = window.orch.toast.bind(window.orch);
  window.orch.toast = (text, kind) => rawToast(window.DashHelpers.scrubText(text), kind);
  window.orch.__scrubbed = true;
}
// One automatic retry for a change that raced with someone else (typically the agent that just finished):
// reload the ticket, and send the same intent again only while it still applies. `args()` is called again for the new revision.
async function actRetry(op, args, applies) {
  const first = await act(op, args());
  if (first.status !== 409 || snapshot) return first;
  try {
    const res = await fetch('/api/state', {cache:'no-store'});
    if (res.ok) accept(await res.json());
  } catch (_) { return first; }
  if (!applies()) return first;
  return act(op, args());
}
window.orchAct = (op, args) => act(op, args);
async function act(op, args) {
  if (snapshot) return {ok:false, status:0, text:'This is a shared copy.'};
  const before = op === 'run.start' ? ticketOf(args.ticket)?.status : null;
  let succeeded = false;
  if (before) { starting.add(args.ticket); state.tickets = state.tickets.map(t => t.id === args.ticket ? {...t, status:'active'} : t); render(); }
  writing++;
  mutation++;
  try {
    const body = JSON.stringify({op, args});
    const res = await fetch('/api/act', {method:'POST', ...(body.length < 60000 ? {keepalive:true} : {}), headers:{'Content-Type':'application/json', 'X-Orch-Op':String(op)}, body});
    if (res.status !== 200) return {ok:false, status:res.status, text:await res.text()};
    const next = await res.json();
    succeeded = true;
    starting.delete(args.ticket);
    accept(next);
    return {ok:true, status:200, state:next};
  } catch (err) { return {ok:false, status:0, text:err.message || 'Could not reach orch.'}; }
  finally {
    writing--;
    if (before) {
      starting.delete(args.ticket);
      if (!succeeded) { state.tickets = state.tickets.map(t => t.id === args.ticket ? {...t, status:before} : t); window.orch.toast('Could not start the agent.', 'error'); }
      render();
    }
  }
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
    connectionNotice(connection, !!state);
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
document.getElementById('new-ticket').hidden = snapshot;
document.getElementById('new-ticket').addEventListener('click', () => ticketForm());
document.getElementById('open-agent').hidden = snapshot;
document.getElementById('open-agent').addEventListener('click', () => chatOpenAgent());
const toggle = document.getElementById('menu-toggle');
toggle.addEventListener('click', () => {
  const open = toggle.getAttribute('aria-expanded') !== 'true';
  toggle.setAttribute('aria-expanded', String(open));
  document.querySelector('.sidebar').dataset.open = String(open);
});
document.querySelector('.sidebar').addEventListener('click', event => {
  const helper = event.target.closest('[data-nav="open-agent"]');
  if (!event.target.closest('a') && !helper) return;
  toggle.setAttribute('aria-expanded', 'false');
  document.querySelector('.sidebar').dataset.open = 'false';
  if (helper) chatOpenAgent();
});
let dragging = '';
const columnOf = event => event.target.closest?.('.kanban-col');
main.addEventListener('dragstart', event => {
  const card = event.target.closest?.('.ticket-card');
  if (!card || snapshot) return;
  dragging = card.dataset.ticket;
  event.dataTransfer.setData('text/plain', dragging);
  event.dataTransfer.effectAllowed = 'move';
  card.classList.add('dragging');
});
main.addEventListener('dragend', () => { dragging = ''; main.querySelectorAll('.dragging,.drop-target').forEach(n => n.classList.remove('dragging', 'drop-target')); });
main.addEventListener('dragover', event => {
  const col = columnOf(event);
  if (!col || !dragging) return;
  event.preventDefault();
  main.querySelectorAll('.drop-target').forEach(n => { if (n !== col) n.classList.remove('drop-target'); });
  col.classList.add('drop-target');
});
main.addEventListener('drop', event => {
  const col = columnOf(event);
  if (!col || !dragging) return;
  event.preventDefault();
  const id = dragging;
  dragging = '';
  main.querySelectorAll('.dragging,.drop-target').forEach(n => n.classList.remove('dragging', 'drop-target'));
  moveTicket(id, col.dataset.status);
});
main.addEventListener('change', async event => {
  const cap = event.target.closest('[data-key="settings-copies-max"]');
  if (cap) { if (!snapshot && !settingsBusy.has('copies')) settingsSend('copies.set', {max:Number(cap.value)}, 'copies'); return; }
  const perm = event.target.closest('[data-settings-permissions]');
  if (perm) {
    if (snapshot || settingsBusy.has('permissions')) return;
    const mode = perm.dataset.settingsPermissions;
    const send = async () => {
      const result = await settingsSend('config.permissions', mode === 'full' ? {mode, confirm:true} : {mode}, 'permissions');
      if (result.ok) window.orch.toast('Saved. New helper runs use ' + capitalise(mode) + '.', 'ok');
    };
    if (mode !== 'full') { await send(); return; }
    perm.checked = false;  // stays on the old choice until the person says Yes
    settingsConfirm('Let the helper do everything?', FULL_WARNING, '', 'Yes, use Full', send);
    return;
  }
  const control = event.target.closest('[data-settings-agent]');
  if (!control || snapshot || settingsBusy.has('agent')) return;
  const agent = array(state.settings?.agents).find(agent => agent.name === control.dataset.settingsAgent);
  if (!agent) return;
  const result = await settingsSend('config.agent', {name:agent.name}, 'agent');
  if (result.ok) window.orch.toast(agent.label + ' is now the default helper.', 'ok');
});
main.addEventListener('keydown', event => {
  if (event.key === 'Escape' && event.target.closest('.settings-review')) { event.preventDefault(); settingsReviewClose(); return; }
  const settingsTabControl = event.target.closest('[data-action="settings-tab"]');
  if (settingsTabControl && ['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) {
    event.preventDefault();
    const tabs = [...settingsTabControl.parentElement.querySelectorAll('[role="tab"]')];
    const index = tabs.indexOf(settingsTabControl);
    const next = event.key === 'Home' ? tabs[0] : event.key === 'End' ? tabs[tabs.length - 1] : tabs[(index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length];
    settingsTab = next.dataset.tab;
    settingsReview = null;
    render();
    document.getElementById(next.id)?.focus();
    return;
  }
  const tab = event.target.closest('[data-action="ticket-tab"]');
  if (!tab || !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
  event.preventDefault();
  const tabs = [...tab.parentElement.querySelectorAll('[role="tab"]')];
  const index = tabs.indexOf(tab);
  const next = event.key === 'Home' ? tabs[0] : event.key === 'End' ? tabs[tabs.length - 1] : tabs[(index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length];
  selectTicketTab(tab.dataset.ticket, next.dataset.tab);
  document.getElementById(next.id)?.focus();
});
main.addEventListener('click', async event => {
  const menu = event.target.closest('details.menu');
  if (menu && event.target.closest('button,a')) menu.open = false;
  const sendControl = event.target.closest('[data-send-to]');
  if (sendControl) { messageSend(sendControl); return; }
  const row = event.target.closest('[data-addon-act]');
  if (row) { if (!snapshot) addonAct(row); return; }
  const copy = event.target.closest('[data-copy]');
  if (copy) { copyText(copy); return; }
  const control = event.target.closest('[data-action]');
  if (!control) return;
  const action = control.dataset.action;
  if (action === 'tree' || action === 'tree-all') {
    const id = control.dataset.ticket;
    if (action === 'tree-all') treeAll.add(id);
    else if (treeExpanded.has(id)) treeExpanded.delete(id); else treeExpanded.add(id);
    render(); return;
  }
  if (action === 'ticket-tab' || action === 'answer-tab') {
    selectTicketTab(control.dataset.ticket, action === 'answer-tab' ? 'questions' : control.dataset.tab, action === 'answer-tab');
    return;
  }
  if (action === 'group') {
    const group = control.dataset.group;
    if (expanded.has(group)) expanded.delete(group); else expanded.add(group);
    render(); return;
  }
  if (snapshot) return;
  if (action === 'settings-tab') {
    settingsTab = control.dataset.tab;
    settingsReview = null;
    render(); return;
  }
  // Share, the copies switch, Clean up now and "Helpers may mark tickets Done" first show a review (settings.js).
  if (action === 'settings-share') { settingsReviewOpen('share', control); return; }
  if (action === 'workflow-set') { settingsReviewOpen('workflow', control); return; }
  if (action === 'copies-switch') { settingsReviewOpen('copies-switch', control); return; }
  if (action === 'copies-clean') { settingsReviewOpen('copies-clean', control); return; }
  if (action === 'settings-review-ok') { await settingsReviewRun(); return; }
  if (action === 'settings-review-cancel') { settingsReviewClose(); return; }
  if (action === 'private-allow') {
    if (settingsBusy.has('private')) return;
    const p = array(state.settings?.git_private?.pending).find(x => x.name === control.dataset.name);
    if (!p || !p.showable) return;
    const send = async () => {
      const result = await settingsSend('private.allow', {name:p.name, key:p.key}, 'private');
      if (result.ok) window.orch.toast('Allowed on this computer.', 'ok');
      return result;
    };
    settingsConfirm('Allow this command?', pendingText(p), 'preserve-lines scroll-all', 'Allow', send);  // in full, never behind Details
    return;
  }
  if (action === 'private-move') {
    if (settingsBusy.has('private')) return;
    const send = async () => {
      const result = await settingsSend('private.move', {}, 'private');
      if (result.ok) window.orch.toast('Moved. Your files stay here.', 'ok');
      return result;
    };
    settingsConfirm('Move to private?', 'Removes them from the team repo and keeps your files.', '', 'Move to private', send);
    return;
  }
  if (action === 'settings-addon') {
    const addon = array(state.settings?.addons).find(addon => addon.name === control.dataset.name);
    if (!addon || addon.name === 'dashboard' || settingsBusy.has('addon-' + addon.name)) return;
    const send = () => settingsSend('addon.set', {name:addon.name, on:!addon.active}, 'addon-' + addon.name);
    if (addon.active) await send();
    else settingsConfirm('Turn on ' + capitalise(addon.name) + '?', addon.consent, 'preserve-lines', 'Turn on', send);
    return;
  }
  if (action === 'agent') {
    if (control.dataset.op === 'answer') { selectTicketTab(control.dataset.ticket, 'questions', true); return; }
    const op = control.dataset.op;
    if (!['run.start', 'run.stop'].includes(op) || locks.has('agent-bar')) return;
    locks.add('agent-bar'); control.disabled = true;
    const result = await act(op, JSON.parse(control.dataset.args));
    locks.delete('agent-bar'); control.disabled = false;
    render();
    window.orch.toast(result.ok ? (op === 'run.start' ? 'Started' : 'Stopped') : result.text, result.ok ? 'ok' : 'error');
    return;
  }
  if (action === 'task-toggle') { await toggleTask(control.dataset.ticket, control.dataset.check); return; }
  if (action === 'status-set') { await moveTicket(control.dataset.ticket, control.dataset.status); return; }
  if (action === 'view') {
    ticketView = control.dataset.view === 'board' ? 'board' : 'list';
    try { localStorage.setItem('orch.tickets.view', ticketView); } catch (_) { /* fine without storage */ }
    render(); return;
  }
  if (action === 'board-more') { if (boardMore.has('done')) boardMore.delete('done'); else boardMore.add('done'); render(); return; }
  if (action === 'file-preview') { previewFile(control.dataset.ticket, control.dataset.kind, control.dataset.name); return; }
  if (action === 'new') ticketForm();
  if (action === 'inline') startInline(control);
  if (action === 'ref-preview') { previewReference(control); return; }
  if (action === 'copies-mode') { settingsSend('copies.set', {mode:control.dataset.mode}, 'copies'); return; }
  if (action === 'copies-orphaned') {
    (async () => { for (const o of array(state.settings?.copies_disk?.orphaned)) await settingsSend('copies.remove_orphaned', {ws8:o.ws8}, 'copies-clean'); })();
    return;
  }
  if (action === 'copies-retry') {
    (async () => { for (const s of array(state.settings?.copies_disk?.stuck)) await settingsSend('copies.retry', {ticket:s.ticket}, 'copies-clean'); })();
    return;
  }
  if (action === 'copies-setup-edit') { copySetupEditing = true; render(); document.querySelector('[data-key="settings-copy-setup"]')?.focus(); return; }
  if (action === 'copies-setup-cancel') { copySetupEditing = false; render(); return; }
  if (action === 'copies-setup') {
    const result = await settingsSend('copies.set', {setup:document.querySelector('[data-key="settings-copy-setup"]')?.value || ''}, 'copies');
    if (result.ok) { copySetupEditing = false; render(); }
    return;
  }
  if (action === 'link-add') startLinkAdd(control);
  if (action === 'link-remove') { event.preventDefault(); removeLink(control); return; }
  if (action === 'link-refresh') { refreshLinks(control); return; }
  if (action === 'field') startAddonField(control);
  if (action === 'agent-add') openAgentForm(control);
  if (action === 'agent-test') {
    event.preventDefault();
    const n = control.dataset.name;
    if (settingsBusy.has('test-' + n)) return;
    agentTests[n] = {ok:false, reason:'Trying…'};
    const result = await settingsSend('config.agent.test', {name:n}, 'test-' + n);
    agentTests[n] = result.ok && result.state?.test ? result.state.test : {ok:false, reason:result.text || 'Could not try it.'};
    render();
  }
  if (action === 'addon-more') { const n = control.dataset.name; if (addonOpen.has(n)) addonOpen.delete(n); else addonOpen.add(n); render(); }
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
else {
  main.replaceChildren(loadingView());
  refresh();
  let poll = setInterval(refresh, 3000), pending;
  const cadence = up => { clearInterval(poll); poll = setInterval(refresh, up ? 20000 : 3000); };
  if (typeof EventSource !== 'undefined') {
    let stream;
    const connect = () => {
      stream = new EventSource('/api/events');
      stream.onopen = () => cadence(true);
      stream.onerror = () => cadence(false);
      stream.addEventListener('rev', () => { clearTimeout(pending); pending = setTimeout(refresh, 50); });
    };
    connect();
    window.addEventListener('pagehide', () => { stream.close(); cadence(false); });
    window.addEventListener('pageshow', event => { if (event.persisted) connect(); });
  }
}
