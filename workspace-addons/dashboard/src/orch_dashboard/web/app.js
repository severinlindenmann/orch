'use strict';
// Shell: shared state and helpers, router, polling/SSE, delegated event handlers. Loaded LAST (classic script, shares the page-wide scope with pages/*.js).
const snapshot = typeof window.ORCH_SNAPSHOT !== 'undefined';
const main = document.getElementById('content');
const nav = document.getElementById('side-nav');
const array = value => Array.isArray(value) ? value : [];
// Workspace ids are stored as they are (answered_by, history); people read the group member's name. Filled from state.groups.
let wsNames = new Map();
const showWs = value => String(value ?? '').replace(/\bws_[a-zA-Z0-9]{4,}\b/g, id => wsNames.get(id) || '');
// Test-run tags in front ("[E2E] ") and machine stamps at the end ("[1731400000]", "[2026-11-12T10:00Z]") are not part of the title.
const TAG_HEAD = /^(?:\s*\[[^\]\n]{1,24}\]\s*)+/, TAG_TAIL = /(?:\s*\[(?:\d{4,}|\d{4}-\d{2}-\d{2}(?:[T ][\d:.]+)?(?:Z|[+-]\d{2}:?\d{2})?|\d{8}T?\d{0,6}Z?)\])+\s*$/;
const cleanIds = value => showWs(value).replace(/\b(?:ws|t|q|m|ph|wh|b|f)_[a-zA-Z0-9]{4,}\b/g, '').replace(/\s+·\s+·/g, ' · ').trim();
const clean = value => { const text = cleanIds(value); return text.replace(TAG_HEAD, '').replace(TAG_TAIL, '').trim() || text; };
// One text node of a page cleaned like clean(), keeping one space where it had one at either end: a title split
// around a ticket number ('ORCH-1098' + ' team chat draft') must not lose its space (report r-1127-0539-ws-3).
const cleanTextNode = data => { const c = clean(data), lead = /^\s/.test(data) ? ' ' : '', tail = /\s$/.test(data) ? ' ' : ''; return c ? lead + c + tail : lead || tail; };
// The tags clean() hides, in order ("[R] ... [0722]" -> "[R] [0722]"); shown muted after the title only when two visible
// tickets would otherwise look identical.
const hiddenTags = value => { const text = cleanIds(value), head = text.match(TAG_HEAD), tail = text.replace(TAG_HEAD, '').match(TAG_TAIL); return [head && head[0], tail && tail[0]].filter(Boolean).map(x => x.trim().replace(/\]\s*\[/g, '] [')).join(' '); };
function titleTag(t, all = null) {
  const base = clean(t.title).toLowerCase(), tag = hiddenTags(t.title);
  if (!tag || !base || clean(t.title) === cleanIds(t.title)) return null;
  const same = (all || (typeof tickets === 'function' ? tickets() : [])).filter(o => o.id !== t.id && clean(o.title).toLowerCase() === base);
  return same.length ? h('span', {className:'meta title-tag'}, ' ' + tag) : null;
}
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
    // a route (#), a web address, or a path on this site (/x; never //x or /\x, which leave the site). A tab or
    // line break is dropped by the browser, so "/\t/x" would become "//x": such an address is no link either.
    if (key === 'href' && (!/^(#|https?:|\/(?![\/\\]))/i.test(String(value)) || /[\t\n\r]/.test(String(value)))) continue;
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
// One date and time format everywhere: the master kit's UI.stamp ("today 10:32", "Mon 08:00", "14 Nov 2026, 10:32").
const date = value => window.UI?.stamp ? window.UI.stamp(value, {time:false}) : (parse(value)?.toLocaleDateString('en-GB', {day:'numeric', month:'short', year:'numeric'}) || '');
const time = value => window.UI?.stamp ? window.UI.stamp(value) : (parse(value)?.toLocaleTimeString('en-GB', {hour:'2-digit', minute:'2-digit'}) || '');
let state, renderedRoute = '', renderedKind = '', fetching = false, writing = 0, serial = 0, mutation = 0;
// Not signed in: every data read needs the sign-in (ORCH-481). The page then shows only the sign-in notice
// (session.js) and stops asking; a sign-in link reloads the page.
let signedOut = false;
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
// Every ticket, Won't do and Superseded too: their board cards open the ticket page and can move back.
const sameTicket = (t, id) => t && (String(t.id) === String(id) || (typeof t.key === 'string' && t.key.toUpperCase() === String(id).toUpperCase()));
// ORCH-522: the live state holds open and recently finished tickets, as rows cut short ("slim": the last history lines
// and proofs). The ticket page reads one whole ticket from GET /api/ticket/<id>, kept here; a newer live row reads it again.
const fullTickets = new Map(), fullLoading = new Set(), fullMissing = new Set();
function loadFullTicket(ref) {
  const key = String(ref);
  if (snapshot || fullLoading.has(key)) return null;
  fullLoading.add(key);
  return fetch('/api/ticket/' + encodeURIComponent(key), {cache:'no-store'})
    .then(res => res.ok ? res.json() : (res.status === 404 ? (fullMissing.add(key), null) : Promise.reject(new Error(String(res.status)))))
    .then(body => { const t = body?.ticket; if (t?.id) { fullTickets.set(t.id, t); fullMissing.delete(key); } else if (body) fullMissing.add(key); return t || null; })
    .catch(() => { fullMissing.add(key); return null; })
    .finally(() => { fullLoading.delete(key); if (typeof render === 'function') render(); });
}
const fullAsked = new Map();  // ticket id -> the live row's updated_at it was read again for (once per change, also when that read fails)
const PART_FIELDS = ['children', 'parts_done', 'parts_total'];
// The live row of a ticket, by id or key. ORCH-2388: it was a scan of every ticket at each call (250 to 400 ms of the
// Review page at 10,000 tickets); now one look-up in an index built once per ticket list. A row that is not where the
// index says (a list changed in place) or not in it falls back to the scan, so the answer is always the scan's.
const ticketRowIndex = new WeakMap();
const liveRowOf = id => {
  const list = array(state?.tickets);
  let ix = ticketRowIndex.get(list);
  if (!ix || ix.n !== list.length) {
    ix = {n:list.length, ids:new Map(), keys:new Map()};
    list.forEach((t, i) => {
      if (!t) return;
      const tid = String(t.id), key = typeof t.key === 'string' ? t.key.toUpperCase() : null;
      if (!ix.ids.has(tid)) ix.ids.set(tid, i);
      if (key !== null && !ix.keys.has(key)) ix.keys.set(key, i);
    });
    ticketRowIndex.set(list, ix);
  }
  const a = ix.ids.get(String(id)), b = ix.keys.get(String(id).toUpperCase());
  const i = a === undefined ? b : b === undefined ? a : Math.min(a, b);  // the first row that fits, as the scan gives
  return i !== undefined && sameTicket(list[i], id) ? list[i] : list.find(t => sameTicket(t, id));
};
const ticketOf = id => {
  const row = liveRowOf(id);
  if (row && !row.slim) return row;
  const full = row ? fullTickets.get(row.id) : [...fullTickets.values()].find(t => sameTicket(t, id));
  if (!full) return row;
  if (row) {
    const at = String(row.updated_at || '');
    if (at > String(full.updated_at || '') && fullAsked.get(row.id) !== at) { fullAsked.set(row.id, at); loadFullTicket(row.id); }  // changed since: read again once, show the last whole copy meanwhile
    // its parts are counted at every build, also when only a part changed (the ticket's own time stays): the live row's count
    for (const k of PART_FIELDS) if (k in row) full[k] = row[k];
    // a Looks good still being saved (review.js acceptOverlay) marks the live row Done: the whole copy shows it too
    if (row.accept_saving || 'accept_was' in row) return {...full, status: row.status, accept_saving: row.accept_saving, accept_was: row.accept_was};
  }
  return full;
};
const href = id => '#ticket/' + encodeURIComponent(id);
const questions = t => array(t.questions).filter(q => q.answer == null);
const activeTicket = t => !['done', 'dropped'].includes(t.status);
const overdue = t => window.DashHelpers.dueLate(t.due, t.status, now());
// ORCH-185: a day-only due says which day: "Fri 20 Nov" (the year only when it is not this year), never a bare "Fri".
const dueDay = value => {
  const d = parse(value); if (!d) return '';
  if (String(value).slice(0, 10) === today()) return 'today';
  return d.toLocaleDateString('en-GB', {weekday:'short', day:'numeric', month:'short', ...(d.getFullYear() !== now().getFullYear() ? {year:'numeric'} : {})}).replace(',', '');
};
const dueText = t => window.DashHelpers.dueWords(t.due, t.status, now()) || (t.due ? dueDay(t.due) : '');  // "Due 18:30" / "Late since 18:30", else the day
const newer = (a, b) => (Date.parse(b.updated_at) || 0) - (Date.parse(a.updated_at) || 0);
const sorted = list => list.slice().sort((a, b) => Number(!!overdue(b)) - Number(!!overdue(a)) || Number(questions(b).length > 0) - Number(questions(a).length > 0) || newer(a, b));
// A ticket that only waits (a date, another ticket, the outside) says Waiting, not Needs you; Superseded says so.
const statusWord = t => { const lane = window.DashHelpers.laneOf(t, t.status, questions(t).length > 0); return lane === 'blocked' ? 'Waiting' : lane === 'superseded' ? 'Superseded' : window.DashHelpers.changesAsked(t) ? 'Changes asked' : window.DashHelpers.statusWord(t.status, t.started); };
const chip = (text, cls = '') => h('span', {className:'chip ' + cls}, text);
const shown = t => snapshot ? t : {...t, status: window.DashHelpers.shownStatus(t, state.runs?.[t.id])};
const statusChip = t => { const s = shown(t); return chip(statusWord(s), s.status === 'active' ? 'active' : ''); };
// Lifecycle order, one word per status: all from helpers.js.
const STATUS_CHOICES = window.DashHelpers.STATUS_CHOICES, MOVE_CHOICES = window.DashHelpers.MOVE_CHOICES;
const moveHome = status => status === 'waiting' ? 'active' : window.DashHelpers.columnOf(status);
const laneHere = t => window.DashHelpers.laneOf(t, shown(t).status, questions(t).length > 0);
const starting = new Set();
// A helper's session appears only after it registers, so right after a successful Start the server still says "no session":
// for a minute the ticket page must not fall back to Not started / Start helper (ORCH-250).
const startedAt = new Map();
const justStarted = id => Date.now() - (startedAt.get(id) || 0) < 60000;
// The one chip of a ticket: what the agent or the person has to do now ('' when nothing).
function activityInfo(t) {
  const run = state.runs?.[t.id], live = run?.claim?.live;
  const agent = window.DashHelpers.agentLabel(state.settings, run?.claim);
  const getting = starting.has(t.id) || live?.state === 'starting';
  // a running helper shows the core's one state word (ORCH-61), the same as Home and the live page
  const helper = window.DashHelpers.helperState(run, t);
  if (helper && !starting.has(t.id)) {
    const busy = ['working', 'starting'].includes(helper.state);
    return {run, live, agent, busy, helper, text:helper.word};
  }
  const busy = getting || (run?.running && !['idle', 'attention'].includes(live?.state));
  const text = getting ? 'Getting started…' : questions(t).length || live?.state === 'attention' ? 'Needs you' : t.status === 'review' ? window.DashHelpers.statusWord('review') : busy ? agent + ' is working' : '';
  return {run, live, agent, busy, text};
}
const needsList = () => window.DashHelpers.uniqueNeeds(state?.needs);
// one line of the question a waiting ticket asks, under its title
const questionLine = t => { const q = snapshot || window.DashHelpers.inNeeds(needsList(), t.id) ? '' : window.DashHelpers.questionPreview(t); return q ? h('p', {className:'meta question-line'}, clean(q)) : null; };
// "why · just now" under a ticket row's title; board and tree rows keep it under the chip
function activityNote(t) {
  const {live, agent, helper, text} = activityInfo(t);
  if (helper && helper.state !== 'working') return helper.detail || '';
  const seconds = live?.since ? Math.max(0, Math.floor((Date.now() - Date.parse(live.since)) / 1000)) : null;
  const why = window.DashHelpers.plainWhy(live?.why, agent);
  return !text ? '' : [why, Number.isFinite(seconds) ? window.DashHelpers.ago(live.since, Date.now()) : ''].filter(Boolean).join(' · ');
}
function activity(t, where = '') {
  if (snapshot) return null;
  const {live, busy, helper, text: full} = activityInfo(t);
  if (!full || (where === 'head' && questions(t).length)) return null;  // the banner is the one place for an open question
  if (full === window.DashHelpers.statusWord('review') && ['head', 'board'].includes(where)) return null;  // the status chip / column already says it: one chip
  const text = full;
  const note = where === 'row' ? '' : activityNote(t);  // in a row the chip sits on the Move to line, the note goes under the title
  const open = live?.state === 'attention' ? liveLinkFor(t) : null;
  return h('div', {className:'activity', 'data-key':'activity-' + t.id}, Object.assign(helper ? (window.UI?.helperPill ? window.UI.helperPill(helper.state, helper.word) : chip(text, busy ? 'active' : '')) : chip(text, busy && (text === 'Getting started…' || text.endsWith(' is working')) ? 'active activity-pulse' : 'attn'), text === window.DashHelpers.statusWord('review') ? {title:'Ready for you to review'} : text === 'Needs you' ? {title:'The agent asked you something'} : {}),
    note ? h('p', {className:'meta'}, note) : null,
    open ? h('a', {className:'btn outline xs', href:open.url, 'data-key':'activity-open-' + t.id}, 'Open the live session') : null);
}
const reviewActions = t => !snapshot && t.status === 'review' ? h('div', {className:'row'}, [['done', 'Looks good'], ['active', 'Send back']].map(([status, label]) => h('button', {type:'button', className:'btn outline xs', 'data-action':'status-set', 'data-ticket':t.id, 'data-status':status}, label))) : null;
const statusSel = (t, value) => value === 'blocked' || value === 'superseded' || (t.status === 'dropped' && value === 'dropped') ? laneHere(t) === value : t.status !== 'dropped' && (moveHome(t.status) === value || t.status === value);
const statusItems = (t, scope, choices = MOVE_CHOICES) => choices.map(([value, label]) => h('button', {type:'button', className:'menu-item' + (statusSel(t, value) ? ' sel' : ''), role:'menuitemradio', 'aria-checked':statusSel(t, value), 'data-action':'status-set', 'data-ticket':t.id, 'data-status':value, 'data-key':'status-' + scope + '-' + t.id + '-' + value}, label));
// The visible "Move to" control: a labelled button (Apple HIG: a control says what it does; WCAG 2.5.3 label in name).
const statusControl = (t, scope) => {
  if (snapshot) return statusChip(t);
  return h('details', {className:'menu status-menu', 'data-key':'status-menu-' + scope + '-' + t.id}, h('summary', {className:'btn outline xs status-sum', 'aria-label':'Move to… ' + clean(t.title) + ' (now ' + statusWord(shown(t)) + ')'}, 'Move to', iconEl('down')), h('div', {className:'menu-pop', role:'menu', 'aria-label':'Move to'}, statusItems(t, scope)));
};
// Page header: one top for every page (owner D1, ORCH-2282), the master UI.pageTop. Title + one muted line, Settings
// first on the right and the page's one filled button last; a page inside another page gets `back` ({label, href}),
// '← Tickets' above its name. The plain frame below only when the kit is not loaded (a test without the master).
const heading = (title, sub = '', {actions = null, back = null, settings = null} = {}) => window.UI?.pageTop && typeof sub === 'string'
  ? window.UI.pageTop({title:clean(title), text:sub, back, settings, actions:actions ? [actions] : [], key:'heading'})
  : h('header', {className:'page-heading', 'data-key':'heading'},
    h('div', {}, h('h1', {}, clean(title)), sub ? h('p', {className:'muted'}, sub) : null),
    actions ? h('div', {className:'page-heading-actions'}, actions) : null);
// Loading shapes that match the page they stand in for; `section` is a part of a page (add-on body, chat history ...).
function skeletonFor(kind) {
  const bar = cls => h('div', {className:'skeleton ' + cls, 'aria-hidden':'true'});
  // The person last looked at tickets as a board: the loading shape is then columns, not rows.
  const boardChosen = () => { try { return localStorage.getItem('orch.tickets.view') === 'board'; } catch (_) { return false; } };
  const stack = (n, cls = 'sk-card') => h('div', {className:'sk-stack', 'aria-hidden':'true'}, Array.from({length:n}, () => bar(cls)));
  const shape = kind === 'home' ? [bar('sk-title'), h('div', {className:'sk-columns', 'aria-hidden':'true'}, stack(3), stack(1))]
    : kind === 'tickets' ? [bar('sk-title'), bar('sk-toolbar'), boardChosen()
      ? h('div', {className:'sk-board', 'aria-hidden':'true'}, [3, 2, 1, 2].map(n => stack(n)))  // columns, like the board
      : stack(5, 'sk-row')]
    : kind === 'ticket' ? [bar('sk-title'), h('div', {className:'sk-columns sk-ticket', 'aria-hidden':'true'}, h('div', {className:'sk-stack'}, bar('sk-card sk-story'), bar('sk-card')), h('div', {className:'sk-stack sk-side'}, bar('sk-card')))]
    : kind === 'section' ? [stack(3, 'sk-row')]
    : kind === 'settings' ? [bar('sk-title'), h('div', {className:'sk-columns sk-settings', 'aria-hidden':'true'}, h('div', {className:'sk-side'}, Array.from({length:4}, () => bar('sk-tab'))), h('div', {className:'sk-stack'}, bar('sk-card sk-short'), bar('sk-card'), bar('sk-card sk-short')))]
    : [bar('sk-title'), stack(3)];
  return h('div', {className:'skeleton-page sk-' + kind, 'data-key':'loading', 'aria-busy':'true'}, h('p', {className:'sr-only', role:'status'}, 'Loading…'), shape);
}
// A small part of a page still loading (a card row, a side list): master skeleton lines in place of a bare "Loading…",
// shown after 300 ms (skeleton-late); the words stay for screen readers only.
function skeletonLines(label = 'Loading…', n = 2, key = 'loading-lines') {
  return h('div', {className:'skeleton-late stack-sm', 'aria-busy':'true', 'data-key':key}, h('p', {className:'sr-only', role:'status'}, label),
    Array.from({length:n}, (_, i) => h('span', {className:'skeleton line' + (n > 1 && i === n - 1 ? ' short' : ''), 'aria-hidden':'true'})));
}
// One menu entry; `here` is the address of the page shown, which gets aria-current.
function navEntry(here, url, text, glyph, tail = null) {
  // The spoken name starts with the words on screen and then says the count ("Review, 1 needs you"; label in name, #2243)
  const said = tail ? (tail.getAttribute?.('aria-label') || tail.textContent || '').trim() : '';
  return h('a', {className:'nav-item', href:url, 'aria-label':said ? text + ', ' + said : text, 'aria-current':here === url ? 'page' : null}, NAV_ICON[glyph] ? navIcon(glyph) : iconEl(glyph), h('span', {className:'nav-label'}, text), tail);
}
// The menu before the state is there (report r-1118-2330, ORCH-692): on a busy machine the first state can take
// seconds after 'orch start', and the menu stayed empty until then. Home, Tickets and Review never depend on the
// state, so they show at once; the sidebar says it is still loading until render() draws the rest (Chat, add-ons,
// Settings) into the same entries.
function startNav(hash) {
  const k = String(hash || '').split('?')[0], kind = k.replace(/^#/, '').split('/')[0];
  const here = !kind || kind === 'home' ? '#home' : kind === 'ticket' ? '#tickets' : k;
  document.getElementById('side-menu')?.setAttribute('aria-busy', 'true');
  reconcile(nav, fragment(navEntry(here, '#home', 'Home', 'home'), navEntry(here, '#tickets', 'Tickets', 'tickets'), navEntry(here, '#review', 'Review', 'review')));
}
// The skeleton for an address before the state is there (no state needed).
function hashKind(hash) {
  const k = String(hash || '').split('?')[0].replace(/^#/, '').split('/')[0];
  return k === 'ticket' ? 'ticket' : k === 'tickets' ? 'tickets' : k === 'settings' ? 'settings' : ['addon', 'open', 'chat', 'general'].includes(k) ? 'page' : 'home';
}
// #addon/<name> of an add-on that is installed but off: say so and offer the switch (ORCH-242), not a bare 404.
function offAddonName(hash) {
  const m = /^#addon\/([a-z][a-z0-9-]{1,31})(?:[/#?]|$)/.exec(hash || '');
  const row = m && array(state?.settings?.addons).find(a => a && a.name === m[1]);
  return row && !row.active && !addons().some(a => a.name === m[1]) ? m[1] : null;
}
// The name a person sees for an add-on row: its menu label (Relay), not its folder name (relay).
function addonRowLabel(row) {
  return String(row?.label || '').trim() || capitalise(row?.name || '');
}
function notFoundPage() {
  const off = offAddonName(location.hash);
  if (off) {
    // D5 (26 Nov): the page keeps its name; one notice under it with one green button (the Turn on of Settings).
    const row = array(state?.settings?.addons).find(a => a && a.name === off), label = addonRowLabel(row);
    return fragment(heading(label, '', {settings:addonSettingsHref(off)}),
      pageNotice({what:label + ' is turned off.', still:'Your tickets and everything else still work.', dataKey:'addon-off',
        action:snapshot ? null : h('button', {type:'button', className:'btn primary sm', 'data-action':'settings-addon', 'data-name':off, 'data-key':'addon-off-on', disabled:settingsBusy.has('addon-' + off)}, 'Turn on ' + label)}));
  }
  return fragment(heading('Page not found', 'Your workspace is still here. Choose where to go next.'),
    h('div', {className:'state-frame', 'data-key':'not-found'}, h('section', {className:'card error-hero'},
      h('span', {className:'error-number', 'aria-hidden':'true'}, '404'),
      h('h2', {}, 'We couldn’t find that page'),
      h('p', {className:'muted'}, 'The link may be out of date, or the page may have moved.', h('br'), 'Your workspace is still here.'),
      h('div', {className:'actions row'}, h('a', {className:'btn primary sm', href:'#home'}, 'Go to Home'),
        h('a', {className:'btn ghost sm', href:'#settings/addons'}, 'Check installed add-ons')))));
}
// Sidebar icons (trusted constants, same drawings as the design).
const NAV_ICON = {
  home:'<path d="m3 10 9-7 9 7v10H3z"/><path d="M9 20v-7h6v7"/>',
  tickets:'<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16m6-16v16"/>',
  review:'<rect x="3" y="3" width="18" height="18" rx="2"/><path d="m8 12 3 3 5-6"/>',
  notes:'<path d="M5 3h14v18H5zM8 8h8m-8 4h8m-8 4h5"/>',
  chat:'<path d="M4 4h16v12H9l-5 4z"/><path d="M8 8h8m-8 4h5"/>',
  addons:'<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
  book:'<path d="M12 6c-2-1.5-5-2-8-2v14c3 0 6 .5 8 2 2-1.5 5-2 8-2V4c-3 0-6 .5-8 2zM12 6v14"/>',
  settings:'<circle cx="12" cy="12" r="3"/><path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/>',
  more:'<path d="m6 9 6 6 6-6"/>',
  less:'<path d="m6 15 6-6 6 6"/>',
  edit:'<path d="m4 20 1-4L16 5l3 3L8 19z"/>',
  done:'<path d="M20 6 9 17l-5-5"/>',
  sideClose:'<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16m7-11-3 3 3 3"/>',
  sideOpen:'<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16m4-11 3 3-3 3"/>',
};
function navIcon(name) {
  const node = document.createElement('span');
  node.className = 'ic-wrap';
  node.innerHTML = '<svg class="ic" viewBox="0 0 24 24" aria-hidden="true">' + NAV_ICON[name] + '</svg>'; // ic-wrap: trusted static nav icons only.
  return node;
}
const VIEWS_OPEN = 'orch.nav.views';
const viewsOpen = () => { try { return localStorage.getItem(VIEWS_OPEN) === 'open'; } catch (_) { return false; } };
// The menu's add-ons (ORCH-1184, tidied by owner D2 A, ORCH-2283): the person keeps the ones they use in the menu, in
// their own order; the rest wait under More. Kept in this browser; a browser that refuses storage still shows the menu
// with the first add-ons in the list.
// O-34 (owner, 28 Nov): no menu row edits the list. Two ways to edit it are built for the owner to pick one:
//   A (default)  Settings › General › Menu (show or hide, drag or arrows for the order), reached from a quiet '…' beside
//                'Add-ons' in the menu (#settings/menu);
//   B            in the menu itself: drag a row, or its '…' (Move up, Move down, Hide from menu; Show in menu under More).
// ?menu=a or ?menu=b in the address chooses for this browser. Both write the same list (NAV_PINS, in menu order).
const NAV_PINS = 'orch.nav.pins', NAV_KNOWN = 'orch.nav.known', NAV_MORE = 'orch.nav.more', NAV_SIDE = 'orch.nav.side', NAV_EDIT = 'orch.nav.edit', PINNED_FIRST = 6;
const navMemory = new Map();  // the same choices for this page view when the browser refuses storage
const navRead = key => { try { const v = localStorage.getItem(key); if (v != null) return v; } catch (_) { /* no storage */ } return navMemory.has(key) ? navMemory.get(key) : null; };
const navWrite = (key, value) => { navMemory.set(key, value); try { localStorage.setItem(key, value); } catch (_) { /* fine without storage */ } };
const navList = key => { try { const v = JSON.parse(navRead(key) || 'null'); return Array.isArray(v) ? v : null; } catch (_) { return null; } };
try { const want = new URLSearchParams(location.search).get('menu'); if (want === 'a' || want === 'b') navWrite(NAV_EDIT, want); } catch (_) { /* no address to read */ }
const navEditB = () => navRead(NAV_EDIT) === 'b';
// The add-ons in the menu, in the person's order. The first time: the first PINNED_FIRST. An add-on turned on later
// arrives in the list (the person just chose it); only one the person moved out waits under More. A page that lives in
// Settings (manifest place = "settings") starts under More and goes into the list only when the person puts it there.
function navPinned(pages) {
  const names = pages.filter(a => a.dashboard?.place !== 'settings').map(a => a.name), known = navList(NAV_KNOWN);
  let pins = navList(NAV_PINS) || names.slice(0, PINNED_FIRST);
  const fresh = known ? names.filter(n => !known.includes(n)) : [];
  if (!known || fresh.length) {
    pins = pins.concat(fresh);
    navWrite(NAV_PINS, JSON.stringify(pins));
    navWrite(NAV_KNOWN, JSON.stringify([...new Set([...(known || []), ...names])]));
  }
  return window.DashHelpers.menuShown(pins, pages.map(a => a.name)).map(n => pages.find(a => a.name === n));
}
// The person's choice changes: a page goes into the menu (at its end) or under More; a page moves right before another
// (null: to the end) or one step. Add-ons that are turned off now keep their place in the list.
function menuPins(pages) { navPinned(pages); return navList(NAV_PINS) || []; }  // writes the first choice when there is none yet
function menuToggle(pages, name) {
  const pins = menuPins(pages), on = pins.includes(name);
  navWrite(NAV_PINS, JSON.stringify(on ? pins.filter(n => n !== name) : pins.concat(name)));
  return !on;
}
const menuMoveBefore = (pages, name, before) => navWrite(NAV_PINS, JSON.stringify(window.DashHelpers.laneReorder(menuPins(pages), name, before)));
const menuMoveStep = (pages, name, dir) => navWrite(NAV_PINS, JSON.stringify(window.DashHelpers.menuStep(menuPins(pages), pages.map(a => a.name), name, dir)));
const navMoreOpen = () => navRead(NAV_MORE) === 'open';
// The add-ons the menu lists: every add-on with a page except Contacts (a top-level entry); pages that live in Settings
// (place = "settings") wait under More (D2 A: nothing is hidden for good).
const menuPages = () => addons().filter(a => a.dashboard && a.dashboard.panel !== 'phone');
let lastOk = 0, lastFetch = 0;
function paintUpdated() {
  const node = document.getElementById('updated');
  if (!node) return;
  const banner = document.getElementById('connection');
  const down = banner && banner.hidden === false && banner.dataset.kind !== 'slow';
  // unreachable or failing: the real time of the last good answer, never a fresh-looking "just now"
  const text = !lastOk ? '' : down ? ' · Last updated ' + new Date(lastOk).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'}) : ' · ' + window.DashHelpers.updatedText(lastOk, Date.now());
  if (node.textContent !== text) node.textContent = text;
}
const card = (key, title, suffix, body, chevron = false) => h('section', {className:'card', 'data-key':key, id:key === 'needs-you' ? key : null}, h('div', {className:'card-h'}, chevron ? iconEl('down') : null, h('h2', {}, title, suffix ? h('span', {className:'muted'}, ' · ', suffix) : null)), body);
// The one master empty/error state for a page area (UI.state); a plain line if the kit is not loaded. `action`
// ({label, onClick}): its one next step, a button (an error's Try again).
const stateNote = (title, text = '', kind = 'empty', action = null) => window.UI?.state ? window.UI.state({kind, title, text, ...(action ? {action} : {})}) : h('p', {className:'meta'}, title + (text ? ' ' + text : ''));
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
  if (locks.has(target.dataset.key) || mounts.has(target) || target.id === 'addon-body' || target.classList.contains('fv-pthumb')) return;  // a live thumbnail keeps its frame
  if (target.dataset.resultsHost !== undefined && target.dataset.resultsHost === source.dataset?.resultsHost) return;  // result widgets fill themselves (pages/results-feed.js)
  for (const attr of [...target.attributes]) {
    if (attr.name === 'open' && target.tagName === 'DETAILS') continue;
    if (target.classList.contains('ui-native-select') && ['class', 'tabindex', 'aria-hidden'].includes(attr.name)) continue;  // set by kit/select.js
    if (!source.hasAttribute(attr.name)) target.removeAttribute(attr.name);
  }
  for (const attr of [...source.attributes]) {
    if (target.classList.contains('ui-native-select') && attr.name === 'class') continue;
    if (target.getAttribute(attr.name) === attr.value) continue;
    // style-src 'self' refuses a style ATTRIBUTE set from script; the same declarations through the style object are allowed
    if (attr.name === 'style') target.style.cssText = attr.value;
    else target.setAttribute(attr.name, attr.value);
  }
  reconcile(target, source);
  if (target.matches('[data-settings-agent],[data-settings-permissions],[data-sync-where]')) target.checked = source.checked;
  if (target.matches('[data-pick]')) { target.checked = source.checked; target.indeterminate = source.dataset.mixed === 'true'; }
  if (target.matches('[data-settings-field]')) {
    if (target.type === 'checkbox') target.checked = source.checked;
    else if (target.value !== source.value) target.value = source.value;
  }
}
function reconcile(target, source) {
  const old = [...target.childNodes], used = new Set();
  for (const fresh of [...source.childNodes]) {
    const key = nodeKey(fresh);
    // A select enhanced by kit/select.js sits inside a .ui-select wrapper: match the wrapper to the plain select of the new tree.
    const base = n => n.classList?.contains('ui-select') ? n.querySelector('select') || n : n;
    const existing = old.find(n => !used.has(n) && n.nodeType === fresh.nodeType && base(n).nodeName === fresh.nodeName && (key ? nodeKey(base(n)) === key : !nodeKey(base(n))));
    const node = existing || fresh;
    const at = target.childNodes[used.size];
    if (node !== at) target.insertBefore(node, at || null);
    if (existing) sync(base(existing), fresh);
    used.add(node);
  }
  for (const node of old) if (!used.has(node) && !locks.has(node.dataset?.key)) node.remove();
}
const seenNeeds = new Set();
function asBrowserPerson(next) {  // a token login (login.js, ORCH-1035): this browser's profile is "you", not the computer's
  const p = window.orchBrowserPerson;
  if (!p || !next) return next;
  return {...next, who: p, me: next.me == null ? next.me : p, people: next.people ? {...next.people, me: p} : next.people};
}
window.addEventListener('orch:person', () => { if (state) accept(state); });
function accept(next) {
  if (typeof acceptOverlay === 'function') next = acceptOverlay(next);  // a Looks good still being saved (ORCH-548)
  next = asBrowserPerson(next);
  const first = !state;
  const arrived = new Set(array(next.needs).filter(n => !seenNeeds.has(n.id)).map(n => n.id));
  array(next.needs).forEach(n => seenNeeds.add(n.id));
  state = next;
  if ('person_names' in next) window.DashHelpers.setPersonNames(next.person_names);  // live page only  // human:pr_... reads as the name
  wsNames = new Map([...['hosted', 'joined'].flatMap(k => array(state?.groups?.[k])).flatMap(g => [...array(g.members), ...array(g.connectable)]),
    ...array(typeof chatDm === 'object' ? chatDm.contacts : [])].filter(m => m && m.ws && m.name).map(m => [m.ws, String(m.name)]));
  window.dispatchEvent(new CustomEvent('orch:state', {detail: next}));
  render(first ? new Set() : arrived);
}
function route() {
  const r = pageRoute();
  // The live-session add-on's addresses show the live page (pages/live.js); it has no page of its own to embed
  return r.kind === 'page' && typeof livePageOf === 'function' && livePageOf(r.id) ? {...r, kind:'live'} : r;
}
function pageRoute() {
  const full = location.hash || '#home', query = full.indexOf('?'), hash = query < 0 ? full : full.slice(0, query) || '#home';
  // #new is the New ticket page (ORCH-1037: its own page, no longer a window over Home).
  // The Notes page is gone: its "What changed" is on Home, and old note links land there.
  if (hash === '#notes' || hash.startsWith('#note/')) { history.replaceState(null, '', '#home'); return {kind:'home', hash:'#home'}; }
  // `orch review link` prints .../#/review: the same page
  if (hash === '#/review') { history.replaceState(null, '', '#review'); return {kind:'review', hash:'#review'}; }
  // ORCH-1804: #review?ticket=<id> is Review with that ticket beside the deck; opening or closing it is no page change,
  // nor is a switch of its tab (tab=, term=; ORCH-2185)
  if (hash === '#review') {
    const rest = (query < 0 ? '' : full.slice(query + 1)).split('&').filter(p => p && !/^(ticket|tab|term)=/.test(p)).join('&');
    return {kind:'review', hash:'#review' + (rest ? '?' + rest : '')};
  }
  if (hash === '#new') { if (!snapshot) return {kind:'new', hash:'#new'}; history.replaceState(null, '', '#home'); return {kind:'home', hash:'#home'}; }
  // #settings is General; #settings/<tab> opens that tab (r.hash stays #settings so switching tabs is not a page change).
  const settingsHash = /^#settings(?:\/(general|menu|people|agent|helper|phone|contacts|about|addons(?:\/[a-z][a-z0-9-]{1,31})?))?$/.exec(hash);
  if (settingsHash && !snapshot && state?.settings) { const [named, addon] = (settingsHash[1] || 'general').split('/'), tab = {helper:'agent', contacts:'phone', menu:'general'}[named] || named; return {kind:'settings', hash:'#settings', tab, addon:addon || null, ...(named === 'menu' ? {at:'menu'} : {})}; }  // #settings/menu: General, at its Menu section (O-34)
  // the Documentation page (book icon next to Settings, pages/docs.js): #docs, #docs/<page>, #docs/g-<group>
  const docsHash = /^#docs(?:\/([a-z][a-z0-9-]{1,41}))?$/.exec(hash);
  if (docsHash && !snapshot) return {kind:'docs', at:docsHash[1] || '', hash};
  if (/^#chat\/ws_[a-z0-9]{10}$/.test(hash) && !snapshot) return {kind:'chat', hash};
  // a ticket's chat on the Chats page (pages/ticketchat.js, ORCH-1168)
  if (/^#chat\/t_[a-z0-9]{6,16}$/.test(hash) && !snapshot && (state?.chat || state?.general || Array.isArray(state?.ticket_chats))) return {kind:'chat', hash};
  if (['#chat', '#general'].includes(hash) && (state?.chat || state?.general)) return {kind:'chat', hash:'#chat'};
  try {
    if (hash.startsWith('#ticket/')) return {kind:'ticket', id:decodeURIComponent(hash.slice(8)), hash};
    // the helper's browser, live (pages/livebrowse.js, ORCH-1493)
    if (/^#browser\/t_[a-z0-9]{4,32}$/.test(hash) && !snapshot) return {kind:'browser', id:hash.slice(9), hash};
    // One address per add-on page: #addon/<name>[/<path>]. The old #open/<name>/<path> forwards to it.
    const open = /^#open\/([a-z][a-z0-9-]{1,31})\/([A-Za-z0-9_./-]*)$/.exec(hash);
    if (open && !open[2].startsWith('/') && !open[2].includes('..') && addons().some(a => a.name === open[1] && a.page)) return {kind:'page', id:open[1], path:open[2], hash:'#addon/' + open[1] + (open[2] ? '/' + open[2] : '')};
    // An add-on page's own place can follow a second # (#addon/factory/#/order/<id>/proposal, Home's link to a
    // proposal): it goes to the frame as the page's own hash.
    const own = /^#addon\/([a-z][a-z0-9-]{1,31})(?:\/([A-Za-z0-9_./-]*))?(?:#([A-Za-z0-9_/-]*))?$/.exec(hash);
    if (own && !(own[2] || '').startsWith('/') && !(own[2] || '').includes('..') && addons().some(a => a.name === own[1] && a.page)) return {kind:'page', id:own[1], path:own[2] || '', ...(own[3] ? {inner:own[3]} : {}), hash};
    if (hash.startsWith('#addon/')) {
      const id = decodeURIComponent(hash.slice(7));
      if (addons().some(a => a.name === id && a.dashboard)) return {kind:'addon', id, hash};
    }
  } catch (_) { /* Malformed links show Page not found. */ }
  // a known page this workspace does not offer (no chat, a shared copy's settings) stays Home, as before
  const kind = {'#home':'home', '#tickets':'tickets', '#review':'review', '#settings':'home', '#chat':'home', '#general':'home'}[hash] || (hash.startsWith('#chat/') ? 'home' : '');
  return kind ? {kind, hash:full} : {kind:'notfound', hash:full};
}
// THE needs-you number goes to the shown add-on page orch ships (same origin, that frame only), so a page that shows it says the same
// number as the top bar (ORCH-63). Sent on every header paint and when the page asks ({orch:'needs-count'}).
function needsCountFrame() {
  const r = route(), frame = document.querySelector('iframe.embed[data-key="embed"]');
  if (snapshot || r.kind !== 'page' || !state?.addons?.find?.(a => a.name === r.id)?.shipped) return null;
  return frame?.contentWindow || null;
}
function postNeedsCount(n) {
  const win = needsCountFrame();
  try { win?.postMessage({type:'orch.needs.count', count:n}, '*'); } catch (_) { /* the page was left */ }  // the frame's origin is opaque (sandboxed)
}
globalThis.addEventListener?.('message', e => {
  const chan = e.origin === 'null' && !!e.data?.chan && e.data.chan === globalThis.orchFrameChan?.();  // sandboxed frame: its code
  if ((e.origin !== location.origin && !chan) || e.data?.orch !== 'needs-count' || !state) return;
  if (e.source && e.source === needsCountFrame()) postNeedsCount(needsYouTotal());
});
// Touch sizes follow the window, never the frame (W-001, W-006): a framed add-on page beside the Focus panel is narrower
// than a phone, but the window is a wide one with a mouse. The dashboard tells each frame whether the window is wide
// (kit/frame.js marks its page, the kit's 44 px touch rules stand down there): when the frame asks, when it has
// loaded, and when the window crosses the phone width. A yes or no only, to this page's own frames.
const windowWide = () => !!globalThis.matchMedia?.('(min-width: 721px)').matches;
function postWindowWide(win) {
  try { win?.postMessage({type:'orch.window', wide:windowWide()}, '*'); } catch (_) { /* the page was left */ }  // the frame's origin is opaque (sandboxed)
}
const embedFrames = () => [...(globalThis.document?.querySelectorAll?.('iframe.embed') || [])];
globalThis.addEventListener?.('message', e => {
  if (e.data?.orch !== 'frame-window' || !e.source) return;
  if (embedFrames().some(f => f.contentWindow === e.source)) postWindowWide(e.source);
});
globalThis.document?.addEventListener?.('load', e => { if (e.target?.matches?.('iframe.embed')) postWindowWide(e.target.contentWindow); }, true);
globalThis.matchMedia?.('(min-width: 721px)').addEventListener?.('change', () => embedFrames().forEach(f => postWindowWide(f.contentWindow)));
// An add-on page moved inside itself (ORCH-241): the address follows it without a history entry of its own (the
// frame's move made one, so Back goes back inside the frame) and without drawing the page again.
function followAddress(hash) {
  history.replaceState(null, '', hash);
  renderedRoute = route().hash;
}
// Add-ons in the menu (ORCH-1184, D2 A; O-34): the ones the person keeps, in their order, then More (n) that unfolds
// the rest in place. No row edits the list. Way A: a quiet '…' beside 'Add-ons' opens Settings › Menu. Way B: each row
// can be dragged and has its own '…'. The page that is open stays in the menu even when it is under More and More is closed.
// stage = "preview" in the add-on's manifest: not finished yet, a small Preview tag beside its name
const stageTag = a => a.dashboard?.stage === 'preview' ? h('span', {className:'badge', title:'Not finished yet'}, 'Preview') : null;
function navAddons(pages, here, navLink) {
  const pinned = navPinned(pages), rest = pages.filter(a => !pinned.includes(a)), open = navMoreOpen();
  const url = a => '#addon/' + encodeURIComponent(a.name), own = navEditB() && !snapshot;
  const item = (label, attrs) => h('button', {type:'button', className:'menu-item', role:'menuitem', ...attrs}, label);
  const row = a => {
    const label = addonLabel(a), link = navLink(url(a), label, a.dashboard.icon || a.icon, stageTag(a));
    if (!own) return h('div', {className:'nav-row', 'data-key':'nav-row-' + a.name}, link);
    const at = pinned.indexOf(a), on = at >= 0;
    return h('div', {className:'nav-row nav-row-own', 'data-key':'nav-row-' + a.name, 'data-menu-row':a.name, draggable:on ? 'true' : null}, link,
      h('details', {className:'menu nav-row-menu', 'data-key':'nav-row-menu-' + a.name},
        h('summary', {className:'btn ghost icon xs nav-row-more', 'data-key':'nav-row-more-' + a.name, 'aria-label':label + ': change the menu', title:'Change the menu'}, iconEl('more')),
        h('div', {className:'menu-pop', role:'menu'},
          on && at > 0 ? item('Move up', {'data-menu-step':'-1', 'data-name':a.name, 'data-key':'nav-up-' + a.name}) : null,
          on && at < pinned.length - 1 ? item('Move down', {'data-menu-step':'1', 'data-name':a.name, 'data-key':'nav-down-' + a.name}) : null,
          item(on ? 'Hide from menu' : 'Show in menu', {'data-menu-pin':a.name, 'data-key':'nav-pin-' + a.name}))));
  };
  const shownRest = open ? rest : rest.filter(a => here === url(a));
  const word = open ? 'Fewer' : 'More (' + rest.length + ')';
  return h('div', {className:'nav-addons', 'data-key':'nav-addons'},
    h('div', {className:'nav-head'}, h('p', {className:'eyebrow'}, 'Add-ons'),
      own || snapshot || !state?.settings ? null : h('a', {className:'btn ghost icon xs nav-edit', href:'#settings/menu', 'data-key':'nav-edit', 'aria-label':'Edit menu', title:'Edit menu'}, iconEl('more'))),
    pinned.length ? h('nav', {'aria-label':'Add-ons', 'data-key':'nav-pinned'}, pinned.map(row)) : null,
    rest.length ? h('button', {type:'button', className:'nav-item nav-more', 'data-key':'nav-more', 'aria-expanded':String(open), 'aria-controls':open ? 'nav-rest' : null, 'aria-label':word}, navIcon(open ? 'less' : 'more'), h('span', {className:'nav-label'}, word)) : null,
    shownRest.length ? h('nav', {id:'nav-rest', 'aria-label':'More add-ons', 'data-key':'nav-rest'}, shownRest.map(row)) : null);
}
// Settings › General › Menu (O-34, way A): one row per add-on page. The switch keeps it in the menu or under More; a row
// in the menu is dragged to its place, or moved with its two arrows (keyboard). Saved at once, in this browser.
function menuSettingsCard() {
  const pages = menuPages();
  if (snapshot || navEditB() || !pages.length) return null;
  const pinned = navPinned(pages), rows = [...pinned, ...pages.filter(a => !pinned.includes(a))];
  // the first page has no way up and the last no way down: an empty place of the same size, never a dead button
  const arrow = (a, dir, none) => none ? h('span', {className:'btn ghost icon sm menu-no-arrow', 'aria-hidden':'true'})
    : h('button', {type:'button', className:'btn ghost icon sm', 'aria-label':'Move ' + addonLabel(a) + (dir < 0 ? ' up' : ' down'), title:dir < 0 ? 'Move up' : 'Move down', 'data-menu-step':String(dir), 'data-name':a.name, 'data-key':'settings-menu-' + (dir < 0 ? 'up-' : 'down-') + a.name}, iconEl(dir < 0 ? 'chevron-up' : 'chevron-down'));
  return h('div', {className:'stack', 'data-key':'settings-menu'}, h('h2', {className:'set-sub', id:'settings-menu', tabindex:'-1'}, 'Menu'),
    h('p', {className:'meta'}, 'Choose the add-on pages in the menu and their order. Drag a row or use its arrows. A page you turn off waits under More. Kept in this browser.'),
    h('div', {className:'card menu-order', role:'list', 'aria-label':'Add-on pages in the menu'}, rows.map(a => {
      const at = pinned.indexOf(a), on = at >= 0, label = addonLabel(a);
      return h('div', {className:'card-row menu-order-row' + (on ? '' : ' off'), role:'listitem', 'data-key':'settings-menu-row-' + a.name, 'data-menu-row':a.name, draggable:on ? 'true' : null},
        h('span', {className:'menu-grip', 'aria-hidden':'true'}, on ? iconEl('grip') : null),
        h('div', {className:'grow'}, h('h3', {}, label, stageTag(a) ? ' ' : null, stageTag(a))),
        on ? arrow(a, -1, at === 0) : null, on ? arrow(a, 1, at === pinned.length - 1) : null,
        h('span', {className:'switch-text', 'aria-hidden':'true'}, on ? 'On' : 'Off'),
        h('button', {type:'button', className:'switch', role:'switch', 'aria-checked':String(on), 'aria-label':label + ' in the menu', 'data-menu-pin':a.name, 'data-key':'settings-menu-pin-' + a.name}));
    })));
}
function render(arrived = new Set()) {
  if (!state) return;
  // ORCH-2159: changing Tickets filters is an in-page update. Keep the search input, caret and scroll.
  const r = route(), sameTickets = r.kind === 'tickets' && renderedRoute.split('?')[0] === '#tickets' && ticketAddressKey === ticketAddressPart();
  const changed = !!renderedRoute && renderedRoute !== r.hash && !sameTickets, first = !renderedRoute, was = renderedRoute;
  if (r.kind === 'settings') { settingsTab = r.tab; settingsAddon = r.addon; }
  if ((r.kind === 'page' || r.kind === 'live') && location.hash !== r.hash) history.replaceState(null, '', r.hash);  // an old #open link shows the one address
  const scroll = [window.scrollX, window.scrollY];
  const active = document.activeElement;
  const activeKey = nodeKey(active);
  const pageName = r.kind === 'settings' ? 'Settings' : (r.kind === 'addon' || r.kind === 'page' || r.kind === 'live') ? addonLabel(addons().find(a => a.name === r.id)) : r.kind === 'ticket' ? 'Ticket' : r.kind === 'browser' ? 'Browser' : r.kind === 'chat' ? 'Chat' : r.kind === 'tickets' ? 'Tickets' : r.kind === 'review' ? 'Review' : r.kind === 'new' ? 'New ticket' : r.kind === 'docs' ? 'Documentation' : r.kind === 'notfound' ? (offAddonName(r.hash) ? 'Add-on turned off' : 'Page not found') : 'Home';
  // ORCH-2176 (messenger draft, option A): the top bar's Chat button is not on the Chat page, which is the chat already
  document.getElementById('open-agent').hidden = snapshot || r.kind === 'chat';
  document.getElementById('workspace-name').textContent = clean(state.settings?.ws_name || state.workspace || 'Workspace');
  document.getElementById('workspace-mode').textContent = window.DashHelpers.footerState(state, snapshot);
  const crumb = document.getElementById('crumb');
  let title = pageName;
  if (r.kind === 'ticket') {
    const tk = ticketOf(r.id);
    title = clean(tk?.title) || 'Ticket';
    // ORCH-70: the ticket number alone (the page's own title says the rest), so the top bar stays one row
    const key = window.DashHelpers.ticketKey(tk);
    crumb.replaceChildren(...[h('a', {href:'#tickets'}, 'Tickets'), ' › ', key ? h('span', {className:'key', title}, key) : title]);
    if (window.DashHelpers.ticketKey(tk)) title = window.DashHelpers.ticketKey(tk) + ' ' + title;
  } else if (r.kind === 'page') {
    const last = r.path.split('/').filter(Boolean).pop() || '', tk = /^t_[A-Za-z0-9]+$/.test(last) ? ticketOf(last) : null;
    title = clean(tk?.title) || last || pageName;
    crumb.replaceChildren(...(last ? [h('a', {href:'#addon/' + encodeURIComponent(r.id)}, pageName), ' › ', title] : [pageName]));
  } else if (r.kind === 'docs' && r.at && docsTitle(r.at)) {
    title = docsTitle(r.at);
    crumb.replaceChildren(h('a', {href:'#docs'}, pageName), ' › ', title);
  } else if (r.kind === 'new') crumb.replaceChildren(h('a', {href:'#tickets'}, 'Tickets'), ' › ', pageName);
  else crumb.textContent = pageName;
  document.title = title + ' · orch';
  paintUpdated();
  // On a narrow screen the header is one row: workspace icon, page name, New ticket, "Menu · N".
  const needCount = needsYouTotal(), menuToggle = document.getElementById('menu-toggle');
  // ORCH-1616 (owner, less noise): the needs-you number shows in ONE place, the Review badge (the side menu, or the
  // bottom bar on a phone); the top bar and the Menu button no longer repeat it
  if (menuToggle.textContent !== 'Menu') menuToggle.textContent = 'Menu';
  menuToggle.removeAttribute('aria-label');
  postNeedsCount(needCount);
  // A development build says so on every page (issue 957), so nobody takes it for a release; the link opens About & updates
  const buildMark = document.getElementById('topbar-build');
  if (buildMark) buildMark.hidden = state.build !== 'development';
  // New ticket is always an outline (design guide, UX checklist B2): every page keeps its own one filled button, Home's
  // Review all included (report r-1116-1748, ORCH-61)
  const newTicket = document.querySelector('#new-ticket'), newCls = 'btn outline sm';
  if (newTicket && newTicket.className !== newCls) newTicket.className = newCls;
  if (newTicket) newTicket.hidden = snapshot || r.kind === 'new';  // on its own page the button would go nowhere
  const wsIcon = document.getElementById('topbar-ws'), lookKey = JSON.stringify([state.look?.icon, state.look?.color, state.workspace]);
  if (window.OrchLook && state.look && wsIcon.dataset.look !== lookKey) { wsIcon.dataset.look = lookKey; wsIcon.replaceChildren(window.OrchLook.badge(state.look, clean(state.workspace) || 'Workspace', 26)); }
  const here = r.kind === 'notfound' ? '' : r.kind === 'ticket' || r.kind === 'new' ? '#tickets' : r.kind === 'home' ? '#home' : r.kind === 'page' || r.kind === 'live' ? '#addon/' + encodeURIComponent(r.id) : r.kind === 'docs' ? '#docs' : r.hash.split('?')[0];
  const navLink = (url, text, glyph, tail = null) => navEntry(here, url, text, glyph, tail);
  const needsWords = window.DashHelpers.needsYou(needCount), contactsAddon = addons().find(a => a.dashboard?.panel === 'phone' && a.dashboard);
  // The needs-you number sits on Review (the page that lists exactly those questions and results), not on Home (ORCH-63)
  document.getElementById('side-menu')?.removeAttribute('aria-busy');
  reconcile(nav, fragment(navLink('#home', 'Home', 'home'), navLink('#tickets', 'Tickets', 'tickets'),
    snapshot ? null : navLink('#review', 'Review', 'review', needCount ? h('span', {className:'count', title:needsWords, 'aria-label':needsWords}, String(needCount)) : null),
    state.chat || state.general ? navLink('#chat', 'Chat', 'chat', chatBadge()) : null,
    // Relay (the phone and workspaces add-on) is a top-level entry, not inside the Add-ons fold-out
    contactsAddon ? navLink('#addon/' + encodeURIComponent(contactsAddon.name), addonLabel(contactsAddon), contactsAddon.dashboard.icon || contactsAddon.icon) : null));
  paintTabbar(here, needCount, needsWords);
  const pages = menuPages();  // Contacts is above; a place=settings page waits under More
  const sideAddons = document.getElementById('side-addons');
  if (sideAddons) reconcile(sideAddons, fragment(pages.length ? navAddons(pages, here, navLink) : null));
  showMarkedRow();
  // Settings and, beside it, the Documentation book (ORCH-735): a page about how orch and each add-on work
  // icons in the one-row person block (ORCH-1880), their words on hover
  reconcile(document.getElementById('side-settings'), fragment(!snapshot && state.settings ? h('a', {className:'nav-item nav-icon-only', href:'#settings', 'aria-label':'Settings', title:'Settings', 'aria-current':here === '#settings' ? 'page' : null}, navIcon('settings')) : null,
    snapshot ? null : h('a', {className:'nav-item nav-icon-only', href:'#docs', 'aria-label':'Documentation', title:'Documentation', 'aria-current':here === '#docs' ? 'page' : null}, navIcon('book'))));
  if (changed) {
    for (const [host, mounted] of mounts) { if (main.contains(host)) { mounted.destroy(); mounts.delete(host); } }
    main.replaceChildren();
  }
  // ORCH-576: where the board tiles are now, so they glide to their new place after this render
  const tileRects = r.kind === 'tickets' && !changed && typeof boardTileRects === 'function' ? boardTileRects(main) : null;
  // a page that cannot be drawn softly loads once the normal way (pages/soft.js)
  try {
  reconcile(main, r.kind === 'settings' ? settingsPage() : r.kind === 'home' ? home() : r.kind === 'tickets' ? list() : r.kind === 'review' ? reviewPage() : r.kind === 'docs' ? docsPage() : r.kind === 'chat' ? chatPage() : r.kind === 'new' ? newTicketPage() : r.kind === 'ticket' ? detail(ticketOf(r.id)) : r.kind === 'page' ? pageFrame(r) : r.kind === 'live' ? liveNextPage(r) : r.kind === 'browser' ? liveBrowsePage(r.id) : r.kind === 'notfound' ? notFoundPage() : addonTab(r.id));
  } catch (err) {
    if (changed && typeof SoftNav === 'object' && SoftNav.fallBack(r.hash)) return;
    throw err;
  }
  if (tileRects) boardGlide(main, tileRects);
  for (const [host, mounted] of mounts) if (!host.isConnected) { mounted.destroy(); mounts.delete(host); }
  if (typeof armLoadMore === 'function') armLoadMore(main);  // lists draw more rows as their end scrolls into view (ORCH-523)
  if (typeof liveDockSync === 'function') liveDockSync();  // the layer of the live page, outside main
  if (typeof liveOpenFromAddress === 'function') liveOpenFromAddress(r);  // a ticket's address opens its session (ORCH-465)
  if (typeof resultsFillAll === 'function') resultsFillAll(document);  // result widgets on tiles, in chat and on the ticket page
  if (r.kind === 'review') mountReview(main);
  if (r.kind === 'docs') mountDocs(main, r);
  if (r.kind === 'chat' && typeof mountChatBoxes === 'function') mountChatBoxes(main);  // the Chat message box (pages/chat.js)
  if (r.kind === 'ticket' || (r.kind === 'review' && typeof reviewTicketId === 'function' && reviewTicketId())) mountTicketTalk(main);  // the ticket beside Review too (ORCH-1804)
  if (typeof mountLiveBrowse === 'function') mountLiveBrowse(main);
  if (r.kind === 'new') mountNewTicket(main);
  if (typeof startMount === 'function') startMount(main);  // every Start button (pages/start.js)
  main.querySelectorAll('[data-question]').forEach(host => {
    if (!mounts.has(host)) {
      const t = ticketOf(host.dataset.ticket), q = array(t?.questions).find(q => q.id === host.dataset.question);
      // ORCH-2140 W3: on the ticket page the question already stands above its card, so the card is the plain one
      if (q) mountQuestion(host, {ticket:t.id, key:typeof t.key === 'string' ? t.key : undefined, id:q.id, digest:q.digest, title:q.text, text:'', oneTap:true, kind:q.kind, options:array(q.options).map(o => ({text:o, suggested:o === q.recommended}))}, {plain:!!host.closest('.ticket-page .next-question, .ticket-page .ticket-question')});
    }
  });
  const shown = shownAddon();
  if (shown) {
    if (activeAddon !== shown) startAddon(shown);
    else if (!document.getElementById('addon-body')?.childNodes.length) paintAddon(shown);
  } else {
    clearInterval(addonTimer); activeAddon = null;
  }
  if (!changed && renderedRoute === r.hash && r.kind === 'home') {
    main.querySelectorAll('[data-need-row]').forEach(row => { if (arrived.has(row.dataset.needRow)) window.orch.needsIn(row); });
  }
  if (changed) window.orch.enter(main);
  window.paintLiveBar?.();  // the live bar under every page (pages/livebar.js)
  renderedRoute = r.hash;
  if (!active?.isConnected && activeKey && !document.querySelector('dialog[open]')) {
    [...document.querySelectorAll('a,button,summary')].find(n => nodeKey(n) === activeKey)?.focus({preventScroll:true});
  }
  const soft = typeof SoftNav === 'object' ? SoftNav : null;
  // Another kind of page, or the focused control went with the old page: the keyboard place and a screen reader
  // follow to the new page (#1350). A pick inside the same kind of page (a chat thread, a doc) keeps the keyboard place.
  const lost = !document.activeElement || document.activeElement === document.body || !document.activeElement.isConnected;
  if (soft && changed && !document.querySelector('dialog[open]') && (r.kind !== renderedKind || lost)) soft.arrive(main, title);
  renderedKind = r.kind;
  window.scrollTo(...(changed ? (soft ? soft.scrollAfterChange() : [0, 0]) : scroll));
  if (soft) { soft.hold(false); if (changed || first) soft.said(first ? '' : was, r.hash, r.kind); }
  warmAddons();
  // #settings/menu (the menu's 'Edit menu'): the Menu section comes into view once and takes the keyboard position
  if (r.kind === 'settings' && r.at === 'menu') {
    const head = menuAt === location.hash ? null : document.getElementById('settings-menu');
    if (head) { menuAt = location.hash; head.scrollIntoView({block:'start'}); head.focus({preventScroll:true}); }
  } else menuAt = '';
}
let menuAt = '';
// Pointing at an add-on in the menu starts fetching its view, so the click finds it ready.
document.addEventListener('pointerover', event => {
  const link = event.target.closest?.('.sidebar a[href^="#addon/"]');
  if (link) warmAddonView(decodeURIComponent(link.getAttribute('href').slice(7)));
});

// Every notice goes through one scrub: no raw ids, actor names or UTC times reach a person.
if (window.orch && !window.orch.__scrubbed) {
  const rawToast = window.orch.toast.bind(window.orch);
  // One shared toast (kit/components.js): one at a time, Dismiss, paused while hovered or focused, errors stay.
  window.orch.toast = (text, kind, undo) => window.UI?.toast ? window.UI.toast(window.DashHelpers.scrubText(text), undo, kind) : rawToast(window.DashHelpers.scrubText(text), kind);
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
window.orchAct = (op, args, opts) => act(op, args, opts);
window.orchActId = () => newActId();  // one id a form keeps for its retries (ORCH-580)
// An add-on change restarts the running services about a second after its answer (orch.restartlater), this
// page's server too. Until the new server answers, nothing on the page asks it: the poll, the live sessions and the
// debug log wait (window.orchQuiet), and this one wait reads the state once it is back (ORCH-1034: every poll hit
// the closed port, the browser logged refused connections and the page said it could not reach the workspace).
// The same run answering twice (`boot` unchanged) means nothing restarted: its answer is taken.
let restartHold = 0, restartWaits = 0;  // two changes at once: the page stays quiet until the last wait ends
// ORCH-1739: an add-on run restarts orch at its end; pages/addon-add.js says when (it keeps reading only the run).
window.orchQuiet = () => (restartWaits > 0 && Date.now() < restartHold) || !!window.addonJobQuiet?.();
async function afterRestart(boot, tries = 24, pause = 1500, head = 2500) {
  const wait = ms => new Promise(done => setTimeout(done, ms));
  restartWaits++;  // never longer than the waits, even if one is cut short
  restartHold = Math.max(restartHold, Date.now() + head + (tries + 2) * pause);
  try {
    await wait(head);
    let same = 0;
    for (let i = 0; i < tries; i++) {
      if (i) await wait(pause);
      let now = null, next = null;
      try {
        const res = await fetch('/api/state?fresh=1', {cache:'no-store'});
        if (!res.ok) continue;
        now = res.headers?.get?.('X-Orch-Boot') || null;
        if (boot && now === boot && ++same < 2) continue;  // the old run, not stopped yet
        next = await res.json();  // the body can break off too while the server stops
      } catch (_) { continue; }  // still restarting
      serverBoot = now || serverBoot;
      if (next && !next.delta) accept(next);
      return next && !next.delta ? next : null;
    }
    return null;
  } finally { if (--restartWaits <= 0) { restartWaits = 0; restartHold = 0; } }
}
// Turning an add-on on or off: when the answer is lost on the way (the server restarted), the state read once the
// server is back says if it worked (the add-on's switch). `settle` false: an answered change returns at once, the
// caller sends its next step before the restart and waits once after it (Remove: off, then uninstall).
// Back but not changed: the click never reached the server (it was still restarting, e.g. from a Remove just before:
// ORCH-1045), so it is sent once more; turning on or off twice does no harm.
async function addonSet(name, on, tries = 24, pause = 1500, settle = true, again = true) {
  const boot = serverBoot;
  const result = await act('addon.set', {name, on}, {check:false});  // the server restarts: its click ids are gone
  if (snapshot || (!result.ok && result.status !== 0)) return result;
  if (result.ok && !settle) return result;
  return addonWait(name, async () => {
    const next = await afterRestart(boot, tries, pause);
    if (result.ok || !next) return result;
    const row = array(next.settings?.addons).find(a => a && a.name === name);
    if (row && !!row.active === on) return {ok:true, status:200, state:next, recovered:true};
    return again ? addonSet(name, on, tries, pause, settle, false) : result;
  });
}
// Uninstall an add-on (`orch addon uninstall`, refused while it is on: turn it off first). The services restart
// like for the switch; the row leaves the list at once and the state read after the restart confirms it. The
// uninstall goes right after an answered turn-off, before that restart: a wait in between left a page that was
// reloaded meanwhile with the add-on only turned off (seen in the walk of this change).
async function addonUninstall(name, tries = 24, pause = 1500, again = true) {
  const still = rows => array(rows).some(a => a && a.name === name);
  if (array(state.settings?.addons).find(a => a && a.name === name)?.active) {
    const off = await addonSet(name, false, tries, pause, false);
    if (!off.ok) return off;
  }
  const boot = serverBoot;  // after a lost turn-off this is already the restarted run
  const result = await act('addon.uninstall', {name}, {check:false});
  if (snapshot || (!result.ok && result.status !== 0)) return result;
  if (result.ok && state?.settings) { state.settings.addons = array(state.settings.addons).filter(a => !(a && a.name === name)); render(); }
  return addonWait(name, async () => {
    const next = await afterRestart(boot, tries, pause);
    if (result.ok || !next) return result;
    if (!still(next.settings?.addons)) return {ok:true, status:200, state:next, recovered:true};
    return again ? addonUninstall(name, tries, pause, false) : result;  // never arrived: once more, like the switch
  });
}
// While the page waits for its server to come back after an add-on change, the add-on's button and switch say so
// (ORCH-1046) instead of a bare "Failed to fetch"; when it is still not back, one plain sentence says what to do.
const addonWaiting = new Set();
let addonWaitPaint = () => render();  // the catalogue dialog paints itself too while it is open
const ADDON_WAIT_TEXT = 'Waiting for orch to restart…';
const ADDON_SLOW = 'orch is still restarting. Wait a moment, then try again.';
async function addonWait(name, wait) {
  const outer = !addonWaiting.has(name);  // the click sent once more waits inside the first wait
  if (outer) { addonWaiting.add(name); addonWaitPaint(); }
  try {
    const r = await wait();
    return r.ok || r.status !== 0 ? r : {...r, ok:false, status:0, text:ADDON_SLOW};
  } finally { if (outer) { addonWaiting.delete(name); addonWaitPaint(); } }
}
// The button a person just pressed shows the kit's busy state at once (aria-busy + aria-disabled), before the
// answer comes, and until it came (ORCH-102: a click showed nothing for seconds while helpers ran).
let pressed = null;
document.addEventListener('click', event => {
  const control = event.target.closest?.('button, .btn');
  pressed = control ? {control, at:Date.now()} : null;
}, true);
function busyOn() {
  const p = pressed;
  pressed = null;
  if (!p || Date.now() - p.at > 1500 || !p.control.isConnected || p.control.getAttribute('aria-busy') === 'true') return null;
  const was = p.control.getAttribute('aria-disabled');
  p.control.setAttribute('aria-busy', 'true');
  p.control.setAttribute('aria-disabled', 'true');
  return {control:p.control, was};
}
function busyOff(busy) {
  if (!busy) return;
  busy.control.removeAttribute('aria-busy');
  if (busy.was === null) busy.control.removeAttribute('aria-disabled'); else busy.control.setAttribute('aria-disabled', busy.was);
}
// opts.quiet: no "Could not start" notice of its own (the kit's Start button says what went wrong, pages/start.js).
// opts.id: the click id to send (a form keeps one for its retries, ORCH-580); opts.check false: no lost-answer check.
async function act(op, args, opts = {}) {
  if (snapshot) return {ok:false, status:0, text:'This is a shared copy.'};
  const busy = busyOn();
  // Prepare (Save without starting, ORCH-738) keeps the ticket in Backlog: it is never shown as Working at once
  const before = op === 'run.start' && !args.prepare ? ticketOf(args.ticket)?.status : null;
  let succeeded = false, queued = false;
  if (before) { starting.add(args.ticket); state.tickets = state.tickets.map(t => t.id === args.ticket ? {...t, status:'active'} : t); render(); }
  writing++;
  mutation++;
  const id = opts.id || newActId();
  const boot = serverBoot;  // the run of the dashboard this click goes to, as far as the page knows
  let sent = false;
  try {
    const body = JSON.stringify({op, args});
    const headers = {'Content-Type':'application/json', 'X-Orch-Op':String(op), 'X-Orch-Act-Id':id};
    if (state?.rev) headers['X-Orch-Have'] = String(state.rev);
    let next;
    try {
      const res = await fetch('/api/act', {method:'POST', ...(body.length < 60000 ? {keepalive:true} : {}), headers, body});
      sent = true;
      noteBoot(res);
      if (res.status !== 200) { const text = window.DashHelpers.answerText(res.status, await res.text()); queued = op === 'run.start' && /waits in line/i.test(text); return {ok:false, status:res.status, text, queued}; }
      next = await actAnswer(await res.json());
    } catch (err) {
      // No answer, or a cut one (ERR_CONTENT_LENGTH_MISMATCH): did the click go through?
      if (opts.check === false) throw err;
      const lost = await actLost(id, boot);
      if (!lost.ok) return lost;
      succeeded = true;
      if (before) startedAt.set(args.ticket, Date.now());
      starting.delete(args.ticket);
      return lost;
    }
    succeeded = true;
    if (before) startedAt.set(args.ticket, Date.now());
    starting.delete(args.ticket);
    accept(next);
    return {ok:true, status:200, state:next};
  } catch (err) { return {ok:false, status:0, text:window.DashHelpers.answerText(0, ''), sent}; }
  finally {
    busyOff(busy);
    writing--;
    if (!writing && refreshAgain) refresh();  // a change notice that came during the write
    if (before) {
      starting.delete(args.ticket);
      // a start orch put in line (every helper place in use) is not a failure: the caller says it waits in line
      if (!succeeded) { state.tickets = state.tickets.map(t => t.id === args.ticket ? {...t, status:before} : t); if (!queued && !opts.quiet) window.orch.toast('Could not start the helper' + (ticketOf(args.ticket)?.title ? ' on ' + ticketOf(args.ticket).title : '') + '.', 'error'); }
      render();
    }
  }
}
// Every click carries an id made here (ORCH-580). The server runs an id once: a repeat (a retry, a double click)
// gets the first result. When the answer is lost on the way, the page asks the server whether the click went
// through before it says anything, and says which it was.
function newActId() {
  const c = window.crypto;
  if (c?.randomUUID) return c.randomUUID();
  const b = new Uint8Array(16); c?.getRandomValues ? c.getRandomValues(b) : b.forEach((_, i) => { b[i] = Math.random() * 256; });
  return [...b].map(x => x.toString(16).padStart(2, '0')).join('');
}
const LOST_NOT_DONE = 'The answer did not arrive, and orch checked: it was not done. Nothing was saved, try again.';
const LOST_UNKNOWN = 'The answer did not arrive and orch could not tell whether it went through. Look in the ticket list before you try again.';
// Which run of the dashboard the page talks to (X-Orch-Boot): a restarted one has forgotten every click id, so its
// "unknown" never means "not done".
let serverBoot = null;
// Note the run of the dashboard an answer came from. A new run (the dashboard restarted, e.g. after an add-on was
// added or removed in Settings) knows none of the frame passes this page holds: drop them, so the shown add-on page
// is opened again with a fresh one instead of staying blank (ORCH-1055). The page is drawn again whichever answer
// noticed it (a failed click's too: the next refresh sees the same run). True when the run changed.
function noteBoot(res) {
  const was = serverBoot;
  serverBoot = res.headers?.get?.('X-Orch-Boot') || serverBoot;
  const restarted = !!was && serverBoot !== was;
  if (restarted && typeof framesForget === 'function') { framesForget(); setTimeout(() => render(), 0); }
  return restarted;
}
// The answer was lost: ask whether this id went through (a few tries, the server may still be at it). `boot`: the
// run of the dashboard the click was sent to; "unknown" from another run (restarted meanwhile) cannot tell.
async function actLost(id, boot, tries = 20, pause = 1500) {
  for (let i = 0; i < tries; i++) {
    if (i) await new Promise(done => setTimeout(done, pause));
    let st = null;
    try {
      const res = await fetch('/api/act/status?id=' + encodeURIComponent(id), {cache:'no-store'});
      if (res.ok) st = await res.json();
    } catch (_) { /* not reachable yet */ }
    if (!st || st.state === 'running') continue;
    if (st.state !== 'done') {
      if (!boot || st.boot !== boot) return {ok:false, status:0, text:LOST_UNKNOWN, lost:'unknown'};
      return {ok:false, status:0, text:LOST_NOT_DONE, lost:'not-done'};
    }
    let full = null;
    try {
      const res = await fetch('/api/state', {cache:'no-store'});
      if (res.ok) full = await res.json();
    } catch (_) { /* the click went through all the same */ }
    if (full && !full.delta) accept(full);
    return {ok:true, status:200, state:{...(full && !full.delta ? full : state), ...(st.reply || {})}, recovered:true};
  }
  return {ok:false, status:0, text:LOST_UNKNOWN, lost:'unknown'};
}
// A click's answer may be only what changed since the revision this page holds (ORCH-580): merged here; one
// that does not fit is replaced by the whole state, with the click's own keys kept (the server lists them in `reply`).
async function actAnswer(next) {
  if (!next || !next.delta) return next;
  const merged = window.DashHelpers.applyStateDelta(state, next);
  if (merged) return merged;
  const own = Object.fromEntries((Array.isArray(next.reply) ? next.reply : []).filter(k => next.set && k in next.set).map(k => [k, next.set[k]]));
  const res = await fetch('/api/state', {cache:'no-store'});
  if (!res.ok) throw new Error('Could not load the workspace.');
  return {...(await res.json()), ...own};
}
// A notice that comes while a fetch or a change is under way is kept, never dropped: that fetch may have read the
// tickets before the change (load_state reads tickets first, run status last), so one more fetch follows it.
let refreshAgain = false;
let wantFull = false;  // the last delta did not fit the state held: ask for the whole state once
async function refresh() {
  if (snapshot || signedOut) return;
  if (window.orchQuiet()) return;  // an add-on change restarts the server: afterRestart reads the state once it is back
  if (fetching || writing) { refreshAgain = true; return; }
  fetching = true;
  refreshAgain = false;
  lastFetch = Date.now();
  const version = mutation;
  const connection = document.getElementById('connection');
  let failKind = 'offline';  // nothing came back; 'error' when the server answered with a failure
  const late = setTimeout(() => { if (connection.hidden) connectionNotice(connection, !!state, 'slow'); }, 4000);
  try {
    // Say which revision we hold: an unchanged state comes back as a few bytes, not the whole state again.
    const have = state?.rev && !wantFull ? '?have=' + encodeURIComponent(state.rev) : '';
    wantFull = false;
    const res = await fetch('/api/state' + have, {cache:'no-store'});
    if (res.status === 401) {  // no sign-in: not a lost connection, and no loading shapes that never fill
      signedOut = true;
      connection.hidden = true;
      if (!state) main.replaceChildren();
      document.getElementById('side-menu')?.removeAttribute('aria-busy');  // settled: the login covers the page
      return;
    }
    if (!res.ok) { failKind = 'error'; throw new Error('Could not load the workspace.'); }
    noteBoot(res);
    let next = await res.json();
    if (next.delta) {  // only what changed since the revision held (ORCH-517); a delta that does not fit: the whole state
      const merged = window.DashHelpers.applyStateDelta(state, next);
      if (!merged) { wantFull = true; refreshAgain = true; return; }
      next = merged;
    }
    if (next.unchanged && state) {
      if (writing || version !== mutation) { refreshAgain = true; return; }
      connection.hidden = true;
      lastOk = Date.now();
      paintUpdated();
      return;
    }
    if (writing || version !== mutation) { refreshAgain = true; return; }
    connection.hidden = true;
    lastOk = Date.now();
    paintUpdated();
    // rev is the server's hash of the whole state (every ticket field, runs, needs ...); without one, always take it.
    window.DiagTrail?.install(window).state(state?.rev, next.rev, res.headers.get('X-State-Age-Ms'));  // client vs server revision, cache age
    if (!state || !next.rev || next.rev !== state.rev) accept(next);
  } catch (_) {
    connectionNotice(connection, !!state, failKind);
  } finally {
    clearTimeout(late);
    if (connection.dataset.kind === 'slow' && !connection.hidden) { connection.hidden = true; holdChanges(); paintUpdated(); }
    else if (connection.hidden) holdChanges();
    fetching = false;
    if (refreshAgain && !writing) refresh();
  }
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
    // The trigger is already focused (kit/overlay.js, ORCH-2060); only a trigger the render above replaced is found again
    if (!trigger?.isConnected && triggerKey && !document.querySelector('dialog[open]')) [...document.querySelectorAll('a,button')].find(n => nodeKey(n) === triggerKey)?.focus({preventScroll:true});
  });
  document.body.append(d);
  return {d, actions};
}
document.getElementById('new-ticket').hidden = snapshot;
document.getElementById('new-ticket').addEventListener('click', () => openNewTicket());
// Keyboard shortcuts (persona test F6): "/" goes to the ticket search, "n" opens New ticket. Never while typing or with a window open.
function shortcutFor(e, typing, windowOpen) {
  if (e.defaultPrevented || e.altKey || e.ctrlKey || e.metaKey || typing || windowOpen) return '';
  return e.key === '/' ? 'search' : e.key === 'n' ? 'new' : '';
}
document.addEventListener('keydown', e => {
  const t = e.target, typing = !!(t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName || '')));
  const what = shortcutFor(e, typing, !!document.querySelector('dialog[open]'));
  if (!what || snapshot) return;
  e.preventDefault();
  if (what === 'new') { openNewTicket(); return; }
  const focusSearch = () => document.querySelector('[data-key="ticket-search"]')?.focus();
  if (route().kind !== 'tickets') { location.hash = '#tickets'; setTimeout(focusSearch, 0); } else focusSearch();
});
// ORCH-2149 (7): the room a dashboard-drawn page keeps for its scrollbar (0 where scrollbars lie over the page), for
// the top bar of a framed add-on page. Read from the page itself with the gutter on: a scrolling box does not tell
// (a browser may draw its own bars over the content and still keep the page's gutter).
try {
  const html = document.documentElement, was = html.style.scrollbarGutter;
  html.style.scrollbarGutter = 'stable';
  const room = Math.max(0, Math.round(window.innerWidth - html.getBoundingClientRect().width));
  html.style.scrollbarGutter = was;
  html.style.setProperty('--scrollbar-w', room + 'px');
} catch (_) { /* no layout (a test page): the top bar keeps its own padding */ }
document.getElementById('open-agent').hidden = snapshot;
document.getElementById('open-agent').addEventListener('click', () => chatOpenAgent());
document.getElementById('report-problem').hidden = snapshot;
document.getElementById('report-problem').addEventListener('click', () => reportOpen());
const toggle = document.getElementById('menu-toggle');
// The side menu opens from the top-bar Menu button (tablet) or from More in the phone bottom bar (ORCH-73).
function setMenu(open) {
  toggle.setAttribute('aria-expanded', String(open));
  document.querySelector('.sidebar').dataset.open = String(open);
  const more = document.querySelector('#tabbar [data-tab="more"]');
  if (more) more.setAttribute('aria-expanded', String(open));
  if (open && more) window.scrollTo(0, 0);
}
toggle.addEventListener('click', () => setMenu(toggle.getAttribute('aria-expanded') !== 'true'));
// The open phone menu covers the page: going anywhere (a bottom-bar tab, a link, the back button) closes it.
document.addEventListener('click', event => { if (event.target.closest?.('#tabbar a')) setMenu(false); });
document.querySelector('.sidebar').addEventListener('click', event => {
  const helper = event.target.closest('[data-nav="open-agent"]');
  if (!event.target.closest('a') && !helper) return;
  setMenu(false);
  if (helper) chatOpenAgent();
});
// The icon rail (721-1279 px) lets its list stick out for the hover labels; on a short screen (150% zoom) that list ran
// under the foot (report r-1117-1256-ws-2). Mark it .cramped while it does not fit: then it scrolls (master CSS).
const sideScroll = document.querySelector('.sidebar-scroll');
if (sideScroll && window.ResizeObserver) {
  const fit = () => sideScroll.classList.toggle('cramped', sideScroll.scrollHeight > sideScroll.clientHeight + 1);
  const watch = new ResizeObserver(fit);
  watch.observe(sideScroll);
  for (const part of sideScroll.children) watch.observe(part);
}
// D2 (ORCH-2315): the open page always shows in the menu, marked. When the list scrolls (a short window, 1280x772), the
// marked row is moved into its view once per page, never hidden under the foot. Only the list scrolls, not the page.
var sideShownFor = '';
function showMarkedRow() {
  const list = document.querySelector('.sidebar-scroll'), row = list?.querySelector('[aria-current="page"]');
  if (!row || sideShownFor === location.hash) return;
  sideShownFor = location.hash;
  const box = list.getBoundingClientRect(), r = row.getBoundingClientRect();
  if (r.bottom > box.bottom) list.scrollTop += r.bottom - box.bottom + 8;
  else if (r.top < box.top) list.scrollTop -= box.top - r.top + 8;
}
// Phone bottom bar (ORCH-73, master UI.tabbar): Home, Tickets, Review with the one needs-you number, More = the side menu.
// Shown only up to 720 px (master CSS); the top bar comes back while the side menu is open.
function paintTabbar(here, needCount, needsWords) {
  if (!window.UI?.tabbar) return;
  const open = document.querySelector('.sidebar')?.dataset.open === 'true';
  const items = [{key:'home', label:'Home', href:'#home', current:here === '#home'}, {key:'tickets', label:'Tickets', href:'#tickets', current:here === '#tickets'},
    snapshot ? null : {key:'review', label:'Review', href:'#review', current:here === '#review', count:needCount, countLabel:needsWords},
    {key:'more', label:'More', expanded:open, current:!!here && !['#home', '#tickets', '#review'].includes(here), controls:'side-menu', testid:'tabbar-more', onClick:() => setMenu(document.querySelector('.sidebar').dataset.open !== 'true')}].filter(Boolean);
  let bar = document.getElementById('tabbar');
  if (!bar || bar.children.length !== items.length) {
    bar?.remove();
    bar = window.UI.tabbar(items, {id:'tabbar', label:'Main'});
    bar.dataset.testid = 'tabbar';
    document.body.append(bar);
  } else window.UI.tabbar.update(bar, items);
}
let dragging = '';
const columnOf = event => event.target.closest?.('.status-row');  // ORCH-576: a status row is the drop target
main.addEventListener('dragstart', event => {
  const card = event.target.closest?.('.ticket-tile');
  if (!card || snapshot) return;
  dragging = card.dataset.ticket;
  event.dataTransfer.setData('text/plain', dragging);
  event.dataTransfer.effectAllowed = 'move';
  card.classList.add('dragging');
  main.querySelector('.status-rows')?.classList.add('is-dragging');
});
const dragClear = () => main.querySelectorAll('.dragging,.drop-target,.drop-before,.is-dragging').forEach(n => n.classList.remove('dragging', 'drop-target', 'drop-before', 'is-dragging'));
main.addEventListener('dragend', () => { dragging = ''; dragClear(); });
main.addEventListener('dragover', event => {
  const col = columnOf(event);
  if (!col || !dragging) return;
  event.preventDefault();
  main.querySelectorAll('.drop-target').forEach(n => { if (n !== col) n.classList.remove('drop-target'); });
  if (!col.classList.contains('drop-target')) { col.classList.add('drop-target'); col.dataset.say = 'Move to ' + (col.querySelector('h2')?.textContent || ''); }
  // a thin bar shows where it lands: above the tile under the pointer
  const over = event.target.closest?.('.ticket-tile');
  main.querySelectorAll('.drop-before').forEach(n => { if (n !== over) n.classList.remove('drop-before'); });
  if (over && over.dataset.ticket !== dragging) over.classList.add('drop-before');
});
main.addEventListener('drop', event => {
  const col = columnOf(event);
  if (!col || !dragging) return;
  event.preventDefault();
  const id = dragging;
  dragging = '';
  const overTile = event.target.closest?.('.ticket-tile')?.dataset.ticket;
  dragClear();
  const t = ticketOf(id), lane = col.dataset.status;
  if (t && boardLane(t) === lane) {  // ORCH-156: inside its own lane a drop puts the card above the one it lands on
    const over = overTile;
    orderInLane(id, lane, over && over !== id ? over : over === id ? id : null);
    return;
  }
  moveToLane(id, lane, col);
});
main.addEventListener('change', async event => {
  const right = event.target.closest('[data-people-right]');
  if (right) { await peopleRight(right); return; }
  const whose = event.target.closest('[data-people-phone]');
  if (whose) { await peopleTie(whose); return; }
  const cap = event.target.closest('[data-key="settings-copies-max"]');
  if (cap) { if (!snapshot && !settingsBusy.has('copies')) settingsSend('copies.set', {max:Number(cap.value)}, 'copies'); return; }
  const most = event.target.closest('[data-key="settings-live-max"]');
  if (most) {
    if (snapshot) return;
    const v = most.value === 'none' ? null : Number(most.value);
    const result = await settingsChoose('live', v, () => settingsSend('live.set', {max:v}, 'live'));
    if (result?.ok) window.orch.toast(v ? 'Up to ' + v + ' helpers at once.' : 'No limit: any number of helpers at once.', 'ok');
    return;
  }
  const perm = event.target.closest('[data-settings-permissions]');
  if (perm) {
    if (snapshot) return;
    const mode = perm.dataset.settingsPermissions;
    const send = async () => {
      const result = await settingsChoose('permissions', mode, () => settingsSend('config.permissions', mode === 'full' ? {mode, confirm:true} : {mode}, 'permissions'));
      if (result?.ok) window.orch.toast('Saved. New helper runs use ' + capitalise(mode) + '.', 'ok');
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
  const enter = event.key === 'Enter' && event.target.closest('[data-people-enter]');
  if (enter && !snapshot) { event.preventDefault(); peopleAction(enter.dataset.peopleEnter, enter); return; }
  if (event.key === 'Escape' && event.target.closest('.settings-review')) { event.preventDefault(); settingsReviewClose(); return; }
  const settingsTabControl = event.target.closest('[data-action="settings-tab"]');
  if (settingsTabControl && ['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) {
    event.preventDefault();
    const tabs = [...settingsTabControl.parentElement.querySelectorAll('[role="tab"]')];
    const index = tabs.indexOf(settingsTabControl);
    const next = event.key === 'Home' ? tabs[0] : event.key === 'End' ? tabs[tabs.length - 1] : tabs[(index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length];
    settingsGo(next.dataset.tab);
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
// A choice in an add-on view (radio block): the saved one is redrawn from the add-on's answer, never from the click.
main.addEventListener('change', event => {
  const pick = event.target.closest?.('input[data-pick]');  // ORCH-2034: a tick in the Tickets list
  if (pick) { pickTicket(pick.dataset.pick, pick.checked); return; }
  const radio = event.target.closest?.('input[data-radio-verb],input[data-radio-go]');
  if (radio) addonRadio(radio);
});
main.addEventListener('click', async event => {
  const menu = event.target.closest('details.menu');
  // data-keep-open: a button that shows its own progress in the menu and closes it itself (Start triage, ORCH-1096)
  if (menu && event.target.closest('button,a') && !event.target.closest('[data-keep-open]')) menu.open = false;
  const convSend = event.target.closest('[data-conv-send]');
  if (convSend) { convSendClick(convSend); return; }
  const sendControl = event.target.closest('[data-send-to]');
  if (sendControl) { messageSend(sendControl); return; }
  // Contacts (ORCH-1203): Accept and Stop trusting are a signed-in person's own clicks; the page sends only the
  // checked id, the fingerprint that was shown and the name typed beside it.
  // List and panel (split block): choosing an item and Open log stay on the page (no request).
  const pick = event.target.closest('[data-split-pick]');
  if (pick) { event.preventDefault(); OrchBlocks.splitPick(pick.closest('.blk-split'), pick.dataset.splitPick); return; }
  const showLog = event.target.closest('[data-split-log]');
  if (showLog) { OrchBlocks.splitLogShow(showLog.closest('.blk-split'), showLog.dataset.splitLog); return; }
  const row = event.target.closest('[data-addon-act]');
  if (row) { if (!snapshot) addonAct(row); return; }
  const allow = event.target.closest('[data-sync-allow]');
  if (allow) { if (!snapshot) syncAllow(allow.dataset.syncAllow); return; }
  const edit = event.target.closest('[data-addon-edit]');
  if (edit) { if (!snapshot) repeatsDialog(edit.dataset.addonEdit, shownAddon()); return; }
  const prompt = event.target.closest('[data-addon-prompt]');
  if (prompt) { promptDialog(prompt); return; }
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
  if (action === 'settings-tab') { settingsGo(control.dataset.tab); return; }
  // Share, the copies switch, Clean up now and "Helpers may mark tickets Done" first show a review (settings.js).
  if (action === 'settings-share') { settingsReviewOpen('share', control); return; }
  if (action === 'workflow-set') { settingsReviewOpen('workflow', control); return; }
  if (action === 'reviewer-set') { await reviewerSwitch(); return; }
  if (action === 'reviewer-kind') { await reviewerKindToggle(control); return; }
  if (action === 'release-merge-set') { await releaseMergeSwitch(); return; }
  if (action === 'prepare-set') { await prepareSwitch(); return; }
  if (action.startsWith('people-')) { await peopleAction(action, control); return; }
  if (action === 'auto-reviewer-set') { await reviewSwitch('auto'); return; }
  if (action === 'away-set') { await reviewSwitch('away'); return; }
  if (action === 'reviewer-mode-set') { await reviewSwitch('propose'); return; }
  if (action === 'diag-set') { await diagSwitch(); return; }
  if (action === 'auto-update-set') { await autoUpdateSwitch(); return; }
  if (action === 'update-check-report') { reportOpen(); return; }
  if (action === 'update-check-ok') { const r = await act('update.check.dismiss', {}); if (!r.ok) window.orch.toast(r.text, 'error'); return; }
  if (action === 'update-check-back') {
    const to = String(control.dataset.to || '');
    if (!/^[1-9][0-9]{0,5}(\.[1-9][0-9]{0,3})?$/.test(to)) return;
    location.hash = '#settings/about';  // the same steps as any update: Downloading, Installing, Restarting, Done
    await updStart(to);
    return;
  }
  if (action === 'auto-update-note-ok') { const r = await act('update.note.dismiss', {}); if (!r.ok) window.orch.toast(r.text, 'error'); return; }
  if (action === 'session-typing') {
    if (settingsBusy.has('session-typing')) return;
    const on = state.settings?.typing_on !== true;
    const result = await settingsSend('typing.set', {on}, 'session-typing');
    if (result.ok) window.orch.toast(on ? 'You can type into the helper\u2019s screen.' : 'Typing into the helper\u2019s screen is off.', 'ok');
    return;
  }
  if (action === 'terminal-typing') {
    if (settingsBusy.has('terminal-typing')) return;
    const on = state.settings?.terminal_typing_on !== true;
    const result = await settingsSend('terminal-typing.set', {on}, 'terminal-typing');
    if (result.ok) window.orch.toast(on ? 'You can type into the plain terminal.' : 'Typing into the plain terminal is off.', 'ok');
    return;
  }
  if (action === 'diag-delete-reports') { await diagDelete(); return; }
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
  if (action === 'addon-catalog') { if (!snapshot) addonCatalog(); return; }
  if (action === 'relay-reconnect') { await relayReconnect(control); return; }
  if (action === 'relay-connect') { await relayConnect(); return; }
  if (action === 'relay-note') { await relayNote(); return; }
  if (action === 'addon-shared') { if (!settingsBusy.has('shared')) await settingsSend('look.shared', {on:control.dataset.on === 'true'}, 'shared'); return; }
  if (action === 'settings-addon') {
    const addon = array(state.settings?.addons).find(addon => addon.name === control.dataset.name);
    if (!addon || addon.name === 'dashboard' || settingsBusy.has('addon-' + addon.name)) return;
    const send = async () => {
      // Turning off: the link and the page go at once, not after the services restart (ORCH-242).
      const before = state.addons;
      const wasActive = addon.active;
      if (wasActive) { state.addons = array(before).filter(a => a.name !== addon.name); addon.active = false; }
      const result = await settingsSend('addon.set', {name:addon.name, on:!wasActive}, 'addon-' + addon.name, (_, a) => addonSet(a.name, a.on));
      if (!result.ok && wasActive) { state.addons = before; addon.active = true; render(); }
      return result;
    };
    if (addon.active) await send();
    else settingsConfirm('Turn on ' + addonRowLabel(addon) + '?', addon.consent, 'preserve-lines', 'Turn on', send);
    return;
  }
  if (action === 'addon-remove') {
    const addon = array(state.settings?.addons).find(addon => addon.name === control.dataset.name);
    if (!addon || addon.name === 'dashboard' || settingsBusy.has('addon-' + addon.name)) return;
    const send = async () => {
      settingsBusy.add('addon-' + addon.name); render();
      const result = await addonUninstall(addon.name);
      settingsBusy.delete('addon-' + addon.name);
      window.orch.toast(result.ok ? 'Removed.' : result.text, result.ok ? 'ok' : 'error');
      if (result.ok) { settingsBack = null; location.hash = '#settings/addons'; }
      render();
    };
    settingsConfirm('Remove ' + addonRowLabel(addon) + '?', 'It is turned off and removed. Your tickets stay as they are. You can add it again any time.', '', 'Remove', send);
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
    const named = ticketOf(JSON.parse(control.dataset.args).ticket), what = named ? ' on ' + (named.title || named.key || 'the ticket') : '';
    window.orch.toast(result.ok ? (op === 'run.start' ? 'Helper started' : 'Helper stopped') + what : result.text, result.ok ? 'ok' : 'error');
    return;
  }
  if (action === 'task-toggle') { await toggleTask(control.dataset.ticket, control.dataset.check); return; }
  if (action === 'status-set') { await moveToLane(control.dataset.ticket, control.dataset.status, control); return; }
  if (action === 'bulk-set') { await bulkAction(control); return; }  // ORCH-2034: pick several (pages/tickets.js)
  if (action === 'bulk-clear') { picked.clear(); render(); return; }
  if (action === 'lane-up' || action === 'lane-down') { control.closest('details')?.removeAttribute('open'); await laneStep(control.dataset.ticket, control.dataset.lane, action === 'lane-up' ? -1 : 1); return; }
  if (action === 'view') {
    ticketView = ['board', 'calendar'].includes(control.dataset.view) ? control.dataset.view : 'list';
    try { localStorage.setItem('orch.tickets.view', ticketView); } catch (_) { /* fine without storage */ }
    writeTicketAddress();
    render(); return;
  }
  if (action.startsWith('cal-') && calendarAction(action, control)) return;  // ORCH-1081: the Tickets calendar
  if (action === 'board-more') { const lane = control.dataset.lane || 'done'; if (boardMore.has(lane)) boardMore.delete(lane); else boardMore.add(lane); render(); return; }
  // ORCH-576: rows open and fold, a tile's parts list, and the scoped board (a ticket and all its parts; waits for; replaced by)
  if (action === 'board-open') { const lane = control.dataset.lane; if (boardOpen.has(lane)) boardOpen.delete(lane); else boardOpen.add(lane); render(); return; }
  if (action === 'board-parts') { if (!control.closest('.ticket-tile')) return; const id = control.dataset.ticket; if (boardPartsOpen.has(id)) boardPartsOpen.delete(id); else boardPartsOpen.add(id); render(); return; }
  if (action === 'board-scope') { boardScope = {root:control.dataset.ticket, mark:control.dataset.mark || null}; render(); main.querySelector('.scope-bar')?.scrollIntoView({block:'nearest'}); return; }
  if (action === 'board-pair') { const t = ticketOf(control.dataset.ticket), other = control.dataset.other; if (!t || !other) return; boardScope = {pair:[t.id, other], mark:other, words:t.superseded_by ? 'is replaced by' : 'waits for'}; render(); return; }
  if (action === 'board-scope-clear') { if (boardScope?.group) { ticketGroup = ''; writeTicketAddress(); } boardScope = null; render(); return; }
  if (action === 'file-preview') { previewFile(control.dataset.ticket, control.dataset.kind, control.dataset.name); return; }
  if (action === 'new') openNewTicket();
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
    agentTests[n] = result.ok && result.state?.test ? result.state.test : {ok:false, reason:result.text || 'Could not try it. Try again.'};
    render();
  }
  if (action === 'addon-more') { const n = control.dataset.name; if (addonOpen.has(n)) addonOpen.delete(n); else addonOpen.add(n); render(); }
  if (action === 'need') openNeed(array(state.needs).find(n => n.id === control.dataset.need), control);
  if (action === 'retry-addon') loadAddon(shownAddon(), true);
  if (action === 'start') {
    if (locks.has('background')) return;
    locks.add('background');
    // Starting… while it starts (ORCH-475): disabled, so a double click starts it once. It starts background work, not a
    // helper on a ticket, so there is no Start choice here.
    const was = control.textContent;
    control.disabled = true;
    control.setAttribute('aria-busy', 'true');
    control.textContent = 'Starting…';
    const result = await act('addon.start', {});
    if (!result.ok) window.orch.toast(result.text, 'error');
    locks.delete('background');
    control.disabled = false;
    control.removeAttribute('aria-busy');
    control.textContent = was;
    render();
  }
});
window.addEventListener('hashchange', async event => {
  if (document.querySelector('.sidebar')?.dataset.open === 'true') setMenu(false);
  noteSettingsBack(event?.oldURL, location.hash);  // D6: an add-on's settings go back to the page they were opened from
  // a dialog in the keep place (the layer) stays open across the page change (pages/soft.js)
  const soft = typeof SoftNav === 'object' ? SoftNav : null;
  soft?.hold(true);
  for (const d of soft ? soft.dialogsToClose() : document.querySelectorAll('dialog[open]')) await window.orch.close(d);
  if (!state && !snapshot) startNav(location.hash);  // a click before the first state still moves the menu's mark
  render();
  soft?.hold(false);  // render() returns early before the state arrives: scrolls must not stay unremembered (ORCH-340)
});
document.getElementById('side-nav')?.addEventListener('toggle', event => {
  if (!event.target.matches?.('details.nav-group')) return;
  try { localStorage.setItem(VIEWS_OPEN, event.target.open ? 'open' : 'closed'); } catch (_) { /* fine without storage */ }
}, true);
// More / Fewer in the menu (ORCH-1184, D2 A). The keyboard stays on the button pressed.
document.getElementById('side-addons')?.addEventListener('click', event => {
  if (!event.target.closest?.('.nav-more')) return;
  // More on the closed menu (icons only) opens the menu with the list unfolded
  if (sideClosed()) { navWrite(NAV_MORE, 'open'); setSide(false); }
  else navWrite(NAV_MORE, navMoreOpen() ? 'closed' : 'open');
  render();
  document.querySelector('#side-addons .nav-more')?.focus({preventScroll:true});
});
// Editing the menu (O-34): in the menu or under More, one step up or down, or dragged to a place. The same three moves
// for Settings › Menu (way A) and for the rows of the menu itself (way B). Each is saved at once and said aloud; the
// keyboard stays on the control used, or on the nearest one when that is gone.
function menuSay(text) { const said = document.getElementById('page-said'); if (said) said.textContent = text; }
function menuChanged(text, keys) {
  render();
  menuSay(text);
  for (const key of keys) {
    const node = document.querySelector('[data-key="' + CSS.escape(key) + '"]');
    if (node && !node.disabled) { node.focus({preventScroll:true}); return; }
  }
}
document.addEventListener('click', event => {
  const pin = event.target.closest?.('[data-menu-pin]'), step = event.target.closest?.('[data-menu-step]');
  if (!pin && !step) return;
  const pages = menuPages(), name = pin ? pin.dataset.menuPin : step.dataset.name, page = pages.find(a => a.name === name);
  if (!page) return;
  const label = addonLabel(page), inMenu = !!event.target.closest('#side-addons');
  event.target.closest('details.menu')?.removeAttribute('open');
  if (pin) {
    const on = menuToggle(pages, name);
    if (inMenu && !on) navWrite(NAV_MORE, 'open');  // the hidden page stays in sight, under More, with Show in menu
    return menuChanged(label + (on ? ' is in the menu.' : ' waits under More.'), inMenu ? ['nav-row-more-' + name, 'nav-more'] : [pin.dataset.key]);
  }
  const dir = Number(step.dataset.menuStep) < 0 ? -1 : 1;
  menuMoveStep(pages, name, dir);
  const at = navPinned(pages).findIndex(a => a.name === name) + 1;
  menuChanged(label + ' is number ' + at + ' in the menu.', inMenu ? ['nav-row-more-' + name] : [step.dataset.key, 'settings-menu-' + (dir < 0 ? 'down-' : 'up-') + name]);
});
let menuDrag = '';
const menuDropAt = event => {
  const row = menuDrag ? event.target.closest?.('[data-menu-row][draggable="true"]') : null;
  if (!row) return null;
  const box = row.getBoundingClientRect();
  return {row, after:event.clientY > box.top + box.height / 2};
};
const menuDragClear = () => document.querySelectorAll('[data-menu-row]:is(.dragging,.drop-before,.drop-after)').forEach(n => n.classList.remove('dragging', 'drop-before', 'drop-after'));
document.addEventListener('dragstart', event => {
  const row = event.target.closest?.('[data-menu-row][draggable="true"]');
  if (!row) return;
  menuDrag = row.dataset.menuRow;
  event.dataTransfer.setData('text/plain', menuDrag);
  event.dataTransfer.effectAllowed = 'move';
  row.classList.add('dragging');
});
document.addEventListener('dragover', event => {
  const at = menuDropAt(event);
  if (!at) return;
  event.preventDefault();
  event.dataTransfer.dropEffect = 'move';
  document.querySelectorAll('[data-menu-row]:is(.drop-before,.drop-after)').forEach(n => { if (n !== at.row) n.classList.remove('drop-before', 'drop-after'); });
  at.row.classList.toggle('drop-before', !at.after);
  at.row.classList.toggle('drop-after', at.after);
});
document.addEventListener('drop', event => {
  const at = menuDropAt(event);
  if (!at) return;
  event.preventDefault();
  const pages = menuPages(), name = menuDrag, shown = navPinned(pages).map(a => a.name).filter(n => n !== name);
  const target = at.row.dataset.menuRow, before = at.after ? (shown[shown.indexOf(target) + 1] ?? null) : target;
  menuDrag = ''; menuDragClear();
  if (target === name) return;
  menuMoveBefore(pages, name, before);
  const page = pages.find(a => a.name === name);
  menuChanged((page ? addonLabel(page) : 'The page') + ' is number ' + (navPinned(pages).findIndex(a => a.name === name) + 1) + ' in the menu.', []);
});
document.addEventListener('dragend', () => { menuDrag = ''; menuDragClear(); });
// Open / close the menu (ORCH-1184): from 1280 px a button beside the orch name closes the menu to its icons and opens it
// again; the choice stays in this browser. Narrower screens keep their own icon rail and the phone its More.
const sideToggle = document.getElementById('side-toggle');
const sideClosed = () => document.querySelector('.shell')?.dataset.side === 'rail' && window.matchMedia('(min-width:1280px)').matches;  // the closed menu shows only from 1280 px
function setSide(closed) {
  const shell = document.querySelector('.shell');
  if (!shell) return;
  if (closed) shell.dataset.side = 'rail'; else delete shell.dataset.side;
  navWrite(NAV_SIDE, closed ? 'rail' : 'wide');
  if (!sideToggle) return;
  const word = closed ? 'Open menu' : 'Close menu';
  sideToggle.setAttribute('aria-expanded', String(!closed));
  sideToggle.setAttribute('aria-label', word);
  sideToggle.title = word;
  sideToggle.replaceChildren(navIcon(closed ? 'sideOpen' : 'sideClose'));
}
setSide(navRead(NAV_SIDE) === 'rail');
sideToggle?.addEventListener('click', () => setSide(document.querySelector('.shell')?.dataset.side !== 'rail'));
// Prefetch: resting 65 ms on a nav link refreshes a state older than 5 s (never on Save-Data).
let prefetchTimer;
const prefetch = event => {
  if (!event.target.closest?.('.sidebar a.nav-item') || snapshot || navigator.connection?.saveData) return;
  clearTimeout(prefetchTimer);
  prefetchTimer = setTimeout(() => { if (!fetching && !writing && Date.now() - lastFetch > 5000) refresh(); }, 65);
};
document.querySelector('.sidebar')?.addEventListener('mouseover', prefetch);
document.querySelector('.sidebar')?.addEventListener('focusin', prefetch);
document.querySelector('.sidebar')?.addEventListener('mouseout', () => clearTimeout(prefetchTimer));
if (snapshot) accept(window.ORCH_SNAPSHOT || {});
else {
  main.replaceChildren(skeletonFor(hashKind(location.hash)));
  startNav(location.hash);  { const k = String(location.hash || '').split('?')[0].replace(/^#/, '').split('/')[0]; const names = {tickets:'Tickets', ticket:'Ticket', chat:'Chat', settings:'Settings', docs:'Documentation'}; if (names[k]) document.getElementById('crumb').textContent = names[k]; }
  // A sign-in link (#launch=) is spent by session.js while the page loads (ORCH-1670): the data, the polls and the
  // event stream start once this browser has its session, so the page needs no stop and no second load.
  const live = () => {
    setInterval(paintUpdated, 30000);
    if (typeof MutationObserver === 'function') new MutationObserver(() => holdChanges()).observe(main, {childList:true, subtree:true});
    refresh();
    // A hidden tab does not poll (nobody sees the answer); it refreshes once when it is shown again.
    const whenShown = fn => () => { if (document.visibilityState !== 'hidden') fn(); };
    let poll = setInterval(whenShown(refresh), 3000), pending;
    const cadence = up => { clearInterval(poll); poll = setInterval(whenShown(refresh), up ? 20000 : 3000); };
    document.addEventListener('visibilitychange', whenShown(refresh));
    if (typeof EventSource !== 'undefined') {
      const onRev = () => { clearTimeout(pending); pending = setTimeout(whenShown(refresh), 50); };
      sharedEvents(window, onRev, cadence);
    }
  };
  if (window.orchSignIn) window.orchSignIn.then(live); else live();
}
// One event stream per browser, not one per tab (ORCH-102): a browser opens at most 6 connections to this server,
// and every open tab held one for good, so a new tab or a cold load waited behind them. The tab that holds the
// lock opens the stream and tells the other tabs; when it closes, the next tab takes the lock and the stream.
// Without locks or BroadcastChannel (an old browser) each tab keeps its own stream, as before.
function sharedEvents(win, onRev, onUp) {
  const own = () => {
    let stream;
    const connect = () => {
      stream = new win.EventSource('/api/events');
      stream.onopen = () => onUp(true);
      stream.onerror = () => onUp(false);
      stream.addEventListener('rev', onRev);
    };
    connect();
    win.addEventListener('pagehide', () => { stream.close(); onUp(false); });
    win.addEventListener('pageshow', event => { if (event.persisted) connect(); });
  };
  if (!win.navigator?.locks || typeof win.BroadcastChannel === 'undefined') return own();
  const channel = new win.BroadcastChannel('orch-events');
  let up = false, leading = null;
  const say = what => { try { channel.postMessage(what); } catch (_) { /* the other tabs poll */ } };
  channel.onmessage = event => {
    if (event.data === 'rev') onRev();
    else if (event.data === 'up' || event.data === 'down') onUp(event.data === 'up');
    else if (event.data === 'hello' && leading) say(up ? 'up' : 'down');  // a new tab asks how the stream is
  };
  const lead = () => win.navigator.locks.request('orch-events', () => new Promise(release => {
    const stream = new win.EventSource('/api/events');
    leading = {stream, release};
    stream.onopen = () => { up = true; onUp(true); say('up'); };
    stream.onerror = () => { up = false; onUp(false); say('down'); };
    stream.addEventListener('rev', () => { onRev(); say('rev'); });
  })).catch(() => {});
  win.addEventListener('pagehide', () => {
    if (leading) { leading.stream.close(); leading.release(); leading = null; say('down'); }
    onUp(false);
  });
  win.addEventListener('pageshow', event => { if (event.persisted) lead(); });
  lead();
  say('hello');
}
