'use strict';
// Tickets list, tree and board. Filter preferences last only for this page session.
const expanded = new Set();
const treeExpanded = new Set(), treeSeen = new Set(), treeAll = new Set(), ticketTabs = new Map();
let ticketSearch = '', ticketMine = false, ticketPerson = '', ticketGroup = '';
// ORCH-1081: the Calendar layout shows a month or a week; calDay is a day in it ('' = today).
let calMode = 'month', calDay = '';
// Saved views live on the address: #tickets?view=needs-you|this-week|stuck|working|waiting|done-week.
const TICKET_VIEWS = [['', 'All'], ['needs-you', 'Needs you'], ['this-week', 'This week'], ['stuck', 'Stuck'], ['working', 'Working'], ['waiting', 'Waiting'], ['backlog', 'Backlog'], ['done-week', 'Done this week']];
// Views reached only by a link (Home's "All finished today"), with no chip of their own.
const LINK_VIEWS = [['done-today', 'Finished today']];
function savedView() {
  const full = typeof location === 'object' ? String(location.hash || '') : '', at = full.indexOf('?');
  const view = at < 0 ? '' : new URLSearchParams(full.slice(at + 1)).get('view') || '';
  return [...TICKET_VIEWS, ...LINK_VIEWS].some(([id]) => id && id === view) ? view : '';
}
// The address also holds the search words and the board: #tickets?view=working&q=invoice&layout=board.
// The calendar adds its week view and shown day: #tickets?layout=calendar&cal=week&day=2026-11-16.
// ticketAddress builds it from the shown state (one place), syncTicketAddress adopts it when it was changed from outside (reload, Back, a shared link).
function ticketAddress(over = {}) {
  const view = 'view' in over ? over.view : savedView(), q = 'q' in over ? over.q : String(ticketSearch).trim(), layout = 'layout' in over ? over.layout : ticketView;
  const who = 'who' in over ? over.who : ticketPerson, part = 'part' in over ? over.part : ticketGroup, mode = 'cal' in over ? over.cal : calMode, day = 'day' in over ? over.day : calDay;
  const p = new URLSearchParams();
  if (view) p.set('view', view);
  if (q) p.set('q', q);
  if (who) p.set('who', who);
  if (part) p.set('part', part);
  if (layout === 'board' || layout === 'calendar') p.set('layout', layout);
  if (layout === 'calendar' && mode === 'week') p.set('cal', 'week');
  if (layout === 'calendar' && day) p.set('day', day);
  const text = p.toString();
  return '#tickets' + (text ? '?' + text : '');
}
let ticketAddressKey = null;
function writeTicketAddress() {
  const next = ticketAddress();
  if (typeof history === 'object' && location.hash !== next && (location.hash || '#home').split('?')[0] === '#tickets') history.replaceState(null, '', next);
  ticketAddressKey = ticketAddressPart();  // after the write, so Back to the old address is seen as a change
}
function ticketAddressPart() {
  const full = typeof location === 'object' ? String(location.hash || '') : '', at = full.indexOf('?'), p = new URLSearchParams(at < 0 ? '' : full.slice(at + 1));
  const layout = ['board', 'calendar'].includes(p.get('layout')) ? p.get('layout') : '';
  return (p.get('q') || '') + '|' + (p.get('who') || '') + '|' + (p.get('part') || '') + '|' + layout + (layout === 'calendar' ? '|' + (p.get('cal') || '') + '|' + (p.get('day') || '') : '');
}
function syncTicketAddress() {
  const key = ticketAddressPart();
  if (key === ticketAddressKey) return;
  ticketAddressKey = key;
  const full = String(location.hash || ''), at = full.indexOf('?'), p = new URLSearchParams(at < 0 ? '' : full.slice(at + 1));
  if (ticketSearch !== (p.get('q') || '')) { ticketSearch = p.get('q') || ''; searchFolds.clear(); }
  ticketPerson = p.get('who') || '';
  ticketGroup = p.get('part') || '';
  if (['board', 'calendar'].includes(p.get('layout'))) ticketView = p.get('layout');
  else if (at < 0 || !p.has('layout')) { try { ticketView = storedTicketView(); } catch (_) { ticketView = 'list'; } }
  calMode = p.get('cal') === 'week' ? 'week' : 'month';
  calDay = window.DashHelpers?.calendar ? window.DashHelpers.calendar.okDay(p.get('day')) : '';  // an impossible day (2026-02-30) means today
}
// The layout last picked on this computer: list, board or calendar.
function storedTicketView() { const v = localStorage.getItem('orch.tickets.view'); return v === 'board' || v === 'calendar' ? v : 'list'; }
// ORCH-523: with 10,000 tickets the page can neither hold nor draw every ticket. /api/state carries the open and
// recently finished ones (ORCH-522); /api/tickets brings older finished tickets a page at a time and searches every
// ticket on the server. Each group and lane draws its first rows and the next ones when its end scrolls into view.
const ROWS_STEP = 50, LANE_STEP = 30, rowsCap = new Map(), moreHandlers = new Map();
const capOf = (key, step = ROWS_STEP) => rowsCap.get(key) || step;
const finished = {key:null, rows:new Map(), next:0, total:null, busy:false, end:false};
const hits = {key:null, want:null, rows:[], next:null, total:0, busy:false, timer:null};
const pagingOn = () => !snapshot && typeof fetch === 'function';
function filterParams() { const p = {}; if (ticketPerson) p.who = ticketPerson; if (ticketMine) p.mine = '1'; if (ticketGroup) p.group = ticketGroup; return p; }
async function fetchTickets(params) {
  const r = await fetch('/api/tickets?' + new URLSearchParams(params), {credentials:'same-origin'});
  if (!r.ok) throw new Error('tickets ' + r.status);
  return r.json();
}
// The next page of finished tickets for the shown filters (newest finished first); rows already in the state win.
function loadFinished() {
  if (!pagingOn()) return;
  const key = JSON.stringify(filterParams());
  if (finished.key !== key) Object.assign(finished, {key, rows:new Map(), next:0, total:null, end:false});
  if (finished.busy || finished.end) return;
  finished.busy = true;
  fetchTickets({...filterParams(), status:'done', offset:finished.next, limit:ROWS_STEP}).then(out => {
    if (finished.key !== key) return;
    const items = array(out.items);
    for (const t of items) finished.rows.set(t.id, t);
    finished.total = Number(out.total) || 0; finished.next += items.length; finished.end = out.next == null || !items.length;
  }).catch(() => { finished.end = true; }).finally(() => { finished.busy = false; render(); });
}
const finishedHere = () => finished.key === JSON.stringify(filterParams());
// How many finished tickets there are for the shown filters: the server's count, else the state's (no filter), else null.
function finishedTotal() {
  if (finishedHere() && finished.total != null) return finished.total;
  const n = state?.ticket_counts?.by_status?.done;
  return !ticketPerson && !ticketMine && !ticketGroup && Number.isFinite(n) ? n : null;
}
function moreFinished(loaded) {
  if (!pagingOn() || savedView() || String(ticketSearch).trim()) return false;
  if (finishedHere() && finished.end) return false;
  const total = finishedTotal();
  return total == null ? !finishedHere() : total > loaded;
}
function pageRows() {
  const own = tickets();
  if (!finished.rows.size || !finishedHere()) return own;
  const have = new Set(own.map(t => t.id));
  return [...own, ...[...finished.rows.values()].filter(t => !have.has(t.id))];
}
// A typed search runs on the server over every ticket (ORCH-523); until its answer arrives the page filters what it holds.
function searchKey() { const q = String(ticketSearch).trim(); return q ? JSON.stringify([q, filterParams()]) : ''; }
const searchServed = () => !!hits.key && hits.key === searchKey();
function wantSearch() {
  const key = searchKey();
  if (!key || !pagingOn() || hits.want === key) return;
  hits.want = key; clearTimeout(hits.timer);
  hits.timer = setTimeout(() => searchPage(key, 0), 250);
}
function searchPage(key, offset) {
  if (offset && hits.busy) return;
  hits.busy = true;
  const [q, params] = JSON.parse(key);
  fetchTickets({...params, q, offset, limit:ROWS_STEP}).then(out => {
    if (hits.want !== key) return;
    hits.rows = offset ? [...hits.rows, ...array(out.items)] : array(out.items);
    hits.key = key; hits.next = out.next ?? null; hits.total = Number(out.total) || 0;
  }).catch(() => { if (hits.want === key && !offset) hits.want = null; }).finally(() => { hits.busy = false; render(); });
}
// The mark at the end of a cut group: drawn as "Loading more…", it shows the next rows (or fetches them) once seen.
function moreMark(key, hidden, fetchMore, step = ROWS_STEP) {
  moreHandlers.set(key, () => { if (hidden > 0) { rowsCap.set(key, capOf(key, step) + step); render(); } else if (fetchMore) fetchMore(); });
  return h('p', {className:'meta load-more', role:'status', 'data-more':key, 'data-key':'more-' + key}, 'Loading more…');
}
let moreWatch = null;
function armLoadMore(root) {
  if (!root || typeof IntersectionObserver !== 'function') return;
  moreWatch ||= new IntersectionObserver(entries => { for (const e of entries) if (e.isIntersecting) moreHandlers.get(e.target.dataset.more)?.(); }, {rootMargin:'400px 0px'});
  moreWatch.disconnect();
  root.querySelectorAll('[data-more]').forEach(el => moreWatch.observe(el));
}
const changesPending = t => t?.bring_back?.state === 'waiting';
function inView(t, view, nowMs = Date.now()) {
  const status = window.DashHelpers.columnOf(shown(t).status);
  // ORCH-236: exactly what the one Needs you number counts (open questions and results to check), so the header and the
  // filter agree; changes waiting to be added show on Home and on the card, not here.
  if (view === 'needs-you') return status !== 'done' && (questions(t).length > 0 || status === 'review');
  if (view === 'working') return status === 'active';
  if (view === 'this-week') return window.DashHelpers.inThisWeek(t, status, nowMs);
  if (view === 'stuck') return isStuck(t);
  if (view === 'waiting') return ticketWaitsOnly(t) || status === 'blocked';  // the Waiting lane: no question for a person, it waits for a time, a ticket or the outside
  if (view === 'backlog') return status === 'open';
  if (view === 'done-today') { const at = new Date(window.DashHelpers.doneAt(t)); return status === 'done' && at.toDateString() === new Date(nowMs).toDateString(); }
  if (view === 'done-week') { const at = Date.parse(window.DashHelpers.doneAt(t)); return status === 'done' && (!Number.isFinite(at) || nowMs - at <= 7 * 86400000); }
  return true;
}
// ORCH-189: Stuck = the core's rule (old question, no news for a day, past due) or a stuck helper.
function isStuck(t) {
  if (window.DashHelpers.columnOf(shown(t).status) === 'done') return false;
  return !!t.stuck || window.DashHelpers.helperState(state?.runs?.[t.id], t)?.state === 'stuck';
}
// ORCH-1716: one person, one entry. Owners are typed by hand and by helpers, so "Severin", "severin", the computer's
// login ("lume") and the placeholder "owner" all mean the person using this dashboard (state.who). The same rule as
// owner_key in ticketpages.py, so the server's search finds the same tickets.
function ownerKey(owner, me = typeof state?.who === 'string' ? state.who : '', login = typeof state?.login === 'string' ? state.login : '') {
  const low = v => String(v || '').trim().toLowerCase().replace(/^[a-z]+:/, '').trim(), o = low(owner), m = low(me);
  return m && (o === m || o === 'owner' || (low(login) && o === low(login))) ? m : o;
}
function filterTickets(items, query, mine, me = '', person = '', view = '', group = '') {
  const needle = String(query || '').trim().toLowerCase(), who = person ? ownerKey(person, me) : '';
  return items.filter(t => (!mine || (me ? String(t.owner || '') === me : !String(t.owner || '').startsWith('agent:'))) &&
    (!who || ownerKey(t.owner, me) === who) && (!group || t.id === group || t.parent === group) && (!view || inView(t, view)) &&
    (!needle || keyMatch(t, needle) || [t.title, /^#?\d+$/.test(needle) ? '' : t.key, t.owner, t.note].some(value => String(value || '').toLowerCase().includes(needle))));
}
// ORCH-58: "58" or "ORCH-58" finds that ticket by its number (exact, so 58 is not ORCH-158); words search the text.
// ORCH-236: the key typed without its dash ("orch58", "orch 58") finds it too.
function keyMatch(t, needle) {
  const key = String(t.key || '').toLowerCase(), digits = needle.replace(/^#/, ''), flat = v => v.replace(/[\s-]+/g, '');
  return !!key && (/^\d+$/.test(digits) ? key.split('-').pop() === String(Number(digits)) : key === needle || flat(key) === flat(needle));
}
function boardChildren(all, t) {
  return window.DashHelpers.childrenOf ? window.DashHelpers.childrenOf(all, t) : all.filter(child => child.id !== t.id && child.parent && (child.parent === t.id || child.parent === t.key));
}
function boardParent(all, t) {
  return window.DashHelpers.parentOf ? window.DashHelpers.parentOf(all, t) : all.find(parent => parent.id !== t.id && t.parent && (parent.id === t.parent || parent.key === t.parent));
}
function ticketParents(items) {  // boardParent for every ticket, with maps (ORCH-523: thousands of rows)
  const byId = new Map(), byKey = new Map(), holder = new Map();
  for (const t of items) { if (!byId.has(t.id)) byId.set(t.id, t); if (t.key && !byKey.has(String(t.key).toLowerCase())) byKey.set(String(t.key).toLowerCase(), t); }
  // like boardParent: the children lists count only with the shared helper (DashHelpers.parentOf)
  if (window.DashHelpers?.parentOf) for (const t of items) for (const c of Array.isArray(t.children) ? t.children : []) if (!holder.has(c)) holder.set(c, t);
  return items.map(t => {
    const named = t.parent ? byId.get(t.parent) || byKey.get(String(t.parent).toLowerCase()) : null;
    const parent = named && named.id !== t.id ? named : holder.get(t.id);
    return parent && parent.id !== t.id ? {...t, parent:parent.id} : t;
  });
}
// ORCH-62: a waiting ticket without an open question only waits (for another ticket, a time or the outside): its own
// group, never Needs you, and not counted as Needs you.
const ticketWaitsOnly = t => window.DashHelpers.columnOf(shown(t).status) === 'waiting' && !questions(t).length;
function ticketGroupOf(t) { return ticketWaitsOnly(t) ? 'blocked' : ticketColumn(t); }
function ticketGroups(items) {
  const groups = ['waiting', 'active', 'blocked', 'ready', 'open', 'review', 'done'].map(status => ({status, title:status === 'blocked' ? blockedTitle(items) : window.DashHelpers.STATUS_WORD[status], tickets:[]}));
  // ORCH-62: every ticket sits in the group of its OWN status, so a group's count is the rows it shows and equals its
  // filter. A part whose parent is in another group stands alone with a "Sub-ticket of <parent>" line.
  for (const t of items) groups.find(group => group.status === ticketGroupOf(t))?.tickets.push(t);
  return groups;
}
// ORCH-37 (owner picked B): a release is a ticket of its own; the epics and tickets that ship together sit under it.
// On the list each release is its own group above the status groups: its whole tree (epic, then task) in one place,
// every row with its own status chip. Releases with work left come first (lowest first: 26 before 27), finished ones
// after them, folded. Tickets in no release stay in their status group as before.
function releaseGroups(items) {
  const all = tickets(), seen = new Set(), out = [];
  const releaseAbove = t => { for (let p = window.DashHelpers.parentOf(all, t), n = 0; p && n < 50; p = window.DashHelpers.parentOf(all, p), n++) if (p.release) return p; return null; };
  const tops = all.filter(t => t && t.release && !releaseAbove(t));
  const shownIds = new Set(items.map(t => t.id));
  for (const rel of tops) {
    const inside = [];
    for (let grow = [rel]; grow.length;) { const next = []; for (const p of grow) for (const c of window.DashHelpers.childrenOf(all, p)) if (!seen.has(c.id) && c.id !== rel.id) { seen.add(c.id); inside.push(c); next.push(c); } grow = next; }
    const members = inside.filter(t => shownIds.has(t.id));
    if (!members.length && !shownIds.has(rel.id)) continue;
    seen.add(rel.id);
    const done = inside.filter(t => window.DashHelpers.columnOf(shown(t).status) === 'done').length;
    out.push({status:'release:' + rel.id, release:rel, title:clean(rel.title), tickets:members, done, total:inside.length, finished:inside.length > 0 && done === inside.length});
  }
  const cmp = (a, b) => a.title.localeCompare(b.title, undefined, {numeric:true, sensitivity:'base'});
  out.sort((a, b) => a.finished - b.finished || (a.finished ? cmp(b, a) : cmp(a, b)));
  return {groups:out, inRelease:seen};
}
const releaseCount = g => g.total ? g.done + ' of ' + g.total + ' done' : 'No tickets yet';  // ORCH-906: not '0 of 0 done'
const releaseFoldSeen = new Set();
function releaseFolds(groups) {  // a finished release starts folded, once; the person's own fold or unfold then stays
  for (const g of groups) if (!releaseFoldSeen.has(g.status)) { releaseFoldSeen.add(g.status); if (g.finished) foldedGroups.add(g.status); }
}
const releaseOpen = g => h('a', {className:'btn ghost sm group-action', href:href(g.release.id), 'data-key':'release-open-' + g.release.id}, 'Open release');
const blockedTitle = items => items.filter(ticketWaitsOnly).every(t => t.waiting_on?.kind === 'ticket') ? 'Waiting for another ticket' : 'Waiting';
// "Waits for ORCH-56" under a ticket that waits for another one; "Waits until 18:00" for a time.
function waitsLine(t) {
  if (!ticketWaitsOnly(t)) return null;
  const text = clean(window.DashHelpers.waitWords(t, tickets(), window.UI?.stamp));
  return text ? h('p', {className:'meta ticket-sub', 'data-key':'waits-' + t.id}, text) : null;
}
// `section`: the group or column the row sits in; its own status chip is left out there. Done shows when it finished.
function ticketAttentionChip(t, section) {
  const status = shown(t).status;
  if (questions(t).length && status !== 'done') return section === 'waiting' ? null : chip('Needs you', 'attn');
  if (status === 'done') { const at = window.DashHelpers.doneAt(t); return at ? h('span', {className:'meta ticket-finished'}, 'Finished ' + localDay(at)) : null; }
  if (section && (window.DashHelpers.columnOf(status) === section || ticketGroupOf(t) === section || boardLane(t) === section)) return null;
  return statusChip(t);
}
const localDay = at => window.UI?.stamp ? window.UI.stamp(at, {time:false}) : '';
// A helper worked on it before (sessions) but it is not running now: paused, not new. Typed tasks alone are not.
const ticketIsPaused = t => array(t.sessions).length > 0;
function filteredTickets() {
  const me = typeof state?.who === 'string' ? state.who : '';
  wantSearch();
  if (searchServed()) {  // the server searched every ticket for these words, person and group; the view is chosen here
    const own = new Map(tickets().map(t => [t.id, t]));
    return filterTickets(ticketParents(hits.rows.map(t => own.get(t.id) || t)), '', false, me, '', savedView(), '');
  }
  return filterTickets(ticketParents(pageRows()), ticketSearch, ticketMine, me, ticketPerson, savedView(), ticketGroup);
}
// A native select styled with the kit's input class (the kit has no custom select yet).
function ticketSelect(label, key, choices, value, onChange) {
  const select = h('select', {className:'input ticket-select', 'aria-label':label, 'data-key':key}, choices.map(([id, text]) => h('option', {value:id, selected:id === value ? '' : null}, text)));
  select.value = value;
  select.addEventListener('change', event => onChange(event.currentTarget.value));
  return select;
}
// Views as chips on the Tickets page: All, Needs you, Working, To do, Done this week. ORCH-236 (owner, 17 Nov): no
// saved views of one's own.
function viewChips() {
  const current = savedView(), filtered = !!(ticketSearch || ticketPerson || ticketGroup);
  const chip = (label, active, attrs) => h('a', Object.assign({className:'chip view-chip' + (active ? ' active' : ''), 'aria-current':active ? 'true' : null}, attrs), label);
  return h('div', {className:'view-chips row', role:'group', 'aria-label':'Ticket views', 'data-key':'view-chips'},
    TICKET_VIEWS.map(([id, text]) => chip(id ? (id === 'stuck' ? stuckLabel() : text) : 'All', id === current && !filtered, {href:ticketAddress({view:id}), 'data-key':'view-chip-' + (id || 'all')})));
}
function stuckLabel() {
  const n = ticketParents(tickets()).filter(isStuck).length;
  return n ? 'Stuck ' + n : 'Stuck';
}
function ticketFilters() {
  const input = h('input', {className:'input', type:'search', placeholder:'Search tickets', 'aria-label':'Search tickets', 'data-key':'ticket-search', value:ticketSearch});
  input.addEventListener('input', event => { ticketSearch = event.currentTarget.value; searchFolds.clear(); writeTicketAddress(); render(); });
  const people = ticketOwners(tickets()), picked = ticketPerson ? ownerKey(ticketPerson) : '';
  const person = people.length > 1 || ticketPerson ? ticketSelect('Person', 'ticket-person', [['', 'Everyone'], ...people], picked, value => { ticketPerson = value; writeTicketAddress(); render(); }) : null;
  const all = tickets(), parents = new Set(all.map(c => c.parent).filter(Boolean)), heads = all.filter(t => parents.has(t.id) || (t.key && parents.has(t.key))).sort((a, b) => String(a.title).localeCompare(String(b.title)));
  const group = heads.length || ticketGroup ? ticketSelect('Part of', 'ticket-group', [['', 'Any ticket'], ...heads.map(t => [t.id, boardShort(t.title, 40)])], ticketGroup, value => { ticketGroup = value; writeTicketAddress(); render(); }) : null;
  return [h('span', {className:'grow'}), group, person, h('label', {className:'search-field'}, input)];
}
// The Person choices: one [key, name] per person (ownerKey), named as "You: ..." says when it is the person, else the
// first spelling that starts with a capital letter.
function ticketOwners(list) {
  const byKey = new Map(), me = typeof state?.who === 'string' ? state.who : '';
  for (const t of list) {
    const raw = name(t.owner), key = raw ? ownerKey(t.owner) : '';
    if (!key) continue;
    const label = me && key === ownerKey(me) ? name(me) : raw, had = byKey.get(key);
    if (!had || (!/^\p{Lu}/u.test(had) && /^\p{Lu}/u.test(label))) byKey.set(key, label);
  }
  return [...byKey].sort((a, b) => a[1].localeCompare(b[1]));
}
function clearTicketFilters() {
  ticketSearch = ''; ticketMine = false; ticketPerson = ''; ticketGroup = '';
  if (savedView()) location.hash = ticketAddress({view:''}); else writeTicketAddress();
  const input = document.querySelector('[data-key="ticket-search"]');
  if (input) input.value = '';
  render(); input?.focus();
}
const initials = value => String(name(value) || '').split(/\s+/).filter(Boolean).slice(0, 2).map(w => w[0].toUpperCase()).join('');
const widthSpan = pct => { const node = h('span', {}); node.style.width = pct + '%'; return node; };
function ticketNext(t) {
  const status = shown(t).status, need = needsList().find(n => n.ticket === t.id);
  let text = '', action = null;
  if (questions(t).length || (status === 'waiting' && !ticketWaitsOnly(t))) {
    text = window.DashHelpers.questionPreview(t) || need?.title || '';
    if (!snapshot) {
      action = button('Answer', 'outline sm', event => {
        const current = needsList().find(n => n.ticket === t.id);
        if (current) openNeed(current, event.currentTarget);
        else { ticketTabs.set(t.id, 'questions'); location.hash = href(t.id); }
      });
    }
    if (text) text = 'Question: ' + text;
  } else if (status === 'review') {
    action = h('a', {className:'btn outline sm', href:href(t.id)}, 'Check result');
  } else if (['open', 'ready'].includes(status) && !state.runs?.[t.id]?.running && !starting.has(t.id)) {
    // ORCH-69 (owner picked A, 16 Nov): no Start helper / Resume button on board and list cards; starting a helper
    // costs budget, so it is never the easiest click. Start it from the ticket page or from Home.
    if (ticketIsPaused(t)) text = 'Paused' + (t.updated_at ? ' ' + localDay(t.updated_at) : '');
  }
  return text || action ? h('div', {className:'row ticket-next'}, text ? h('span', {className:'meta'}, clean(text)) : null, action) : null;
}
// The new live page (Preview, draft D feature 3): every row gets the ticket's session button. When it says Answer it takes the
// place of the row's own Answer, so a row never shows two.
function ticketRowFocus(t, nextAction) {
  const live = typeof liveFocusButton === 'function' ? liveFocusButton(t) : null;
  if (!live) return [nextAction];
  return live.dataset.verb === 'Answer' && nextAction?.textContent === 'Answer' ? [live] : [nextAction, live];
}
function ticketMenu(t, scope) {
  if (snapshot) return null;
  const menu = statusControl(t, scope), summary = menu.querySelector('summary');
  summary.replaceChildren(iconEl('more'));
  summary.className = 'btn ghost icon sm move-button';
  return menu;
}
// Status badge of a table row: icon + the shared word (Backlog, To do, Working, Needs you, Waiting, Check, Done, ...).
const STATUS_BADGE = {open:['○', 'todo'], ready:['○', 'todo'], active:['◉', 'working'], waiting:['!', 'needs'], blocked:['◷', 'todo'], review:['◇', 'review'], done:['✓', 'done'], dropped:['–', 'todo'], superseded:['→', 'todo']};
function ticketColumn(t) { const status = shown(t).status; return questions(t).length && status !== 'done' ? 'waiting' : window.DashHelpers.columnOf(status); }
// ORCH-62: the group says the status; a row carries a chip only when its helper is Idle or Stuck.
function helperChip(t) {
  const run = state?.runs?.[t.id], st = window.DashHelpers.helperState(run, t);
  if ((!st || st.state !== 'stuck') && t.stuck && window.DashHelpers.columnOf(shown(t).status) !== 'done') {
    return {chip:window.UI?.helperPill ? window.UI.helperPill('stuck', 'Stuck') : chip('Stuck', 'danger'), line:window.DashHelpers.stuckWords(t, Date.now())};
  }
  if (!st || !['idle', 'stuck'].includes(st.state)) return null;
  const mins = Number.isFinite(run?.idle_seconds) ? Math.floor(run.idle_seconds / 60) : null;
  return {chip:window.UI?.helperPill ? window.UI.helperPill(st.state, st.word) : chip(st.word, st.state === 'stuck' ? 'danger' : 'outline'),
    line:st.state === 'idle' ? (mins != null ? 'Nothing running for ' + mins + ' min' : 'Nothing running') : st.detail || ''};
}
// Steps as "3/4" with a bar, always on one line (ORCH-62); "–" when there are none.
function stepsCell(t, row) {
  const tasks = array(t.checklist), total = tasks.length || row.children || 0, done = tasks.length ? tasks.filter(window.DashHelpers.resolved).length : row.done || 0;
  if (!total) return h('span', {className:'meta'}, '–');
  return h('div', {className:'step-progress', title:window.DashHelpers.stepsText(done, total)}, h('div', {className:'progress', role:'progressbar', 'aria-label':'Tasks done', 'aria-valuemin':0, 'aria-valuemax':total, 'aria-valuenow':done}, widthSpan(Math.round(done / total * 100))),
    h('span', {className:'meta steps-count'}, done + '/' + total));
}
// ORCH-189: the due day (red when past, amber today) and helper time · money at list price; "–" when none.
function dueCell(t) {
  if (!t.due) return h('span', {className:'meta'}, '–');
  const late = window.DashHelpers.columnOf(shown(t).status) !== 'done' && (t.stuck === 'overdue' || overdue(t));
  const today = !late && String(t.due).slice(0, 10) === new Date(now()).toLocaleDateString('sv');
  return h('span', {className:late ? 'bad' : today ? 'warn' : ''}, dueText(t).replace(/^Due /, ''));  // the column head says Due
}
function spendCell(t) { const words = window.DashHelpers.spendWords(t.spend); return h('span', {className:'meta', title:words ? undefined : 'Not recorded'}, words || '–'); }
// One table row (a ticket or a part under its parent). `section` is the group it sits in.
function treeBranch(rows, index, section) {
  const row = rows[index], t = row.ticket;
  if (!treeSeen.has(t.id)) { treeSeen.add(t.id); treeExpanded.add(t.id); }
  const open = treeExpanded.has(t.id), children = [];
  for (let i = index + 1; i < rows.length && rows[i].depth > row.depth; i++) if (rows[i].depth === row.depth + 1) children.push(i);
  const next = ticketNext(t), nextText = next?.querySelector('.meta'), nextAction = next?.querySelector('.btn');
  const helper = helperChip(t);
  const inRelease = String(section || '').startsWith('release:');
  const sub = changesLine(t) || waitsLine(t) || (nextText ? h('p', {className:'meta ticket-sub'}, nextText.textContent) : null) || (helper?.line ? h('p', {className:'meta ticket-sub'}, helper.line) : null) || (row.parentMissing && !inRelease ? parentLine(t) : null);
  const at = shown(t).status === 'done' ? window.DashHelpers.doneAt(t) : t.updated_at;
  const node = h('tr', {className:'ticket-row' + (row.depth ? ' child' : ''), 'data-key':'tree-' + t.id},
    h('td', {className:'ticket-cell'}, h('div', {className:'ticket-line'},
      row.children ? h('button', {type:'button', className:'btn ghost icon sm', 'data-action':'tree', 'data-ticket':t.id, 'aria-expanded':open, 'aria-label':(open ? 'Collapse ' : 'Expand ') + clean(t.title)}, iconEl('down')) : null,
      h('a', {href:href(t.id)}, window.DashHelpers.keyTag(t, h), clean(t.title)), window.DashHelpers.kindTag(t, h), titleTag(t), prepareWord(t), helper?.chip || (inRelease ? ticketAttentionChip(t, '') : null)), sub),
    h('td', {className:'due-cell'}, dueCell(t)),
    h('td', {className:'steps'}, stepsCell(t, row)),
    h('td', {className:'numeric spend-cell'}, spendCell(t)),
    h('td', {className:'meta when' + (t.quiet_since ? ' quiet' : ''), title:String(at || '')}, t.quiet_since ? window.DashHelpers.quietWords(t.quiet_since, now()) : at && window.DashHelpers.ago ? (shown(t).status === 'done' ? 'Finished ' : '') + window.DashHelpers.ago(at, Date.now()) : ''),
    h('td', {className:'ticket-actions'}, h('div', {className:'ticket-actions-row'}, ...ticketRowFocus(t, nextAction), ticketMenu(t, 'tree'))));
  node.dataset.depth = String(Math.min(row.depth, 6));
  node.classList.add('row-click');
  node.addEventListener('click', e => { if (!e.target.closest('a,button,select,input,[role="menu"]')) location.hash = href(t.id); });
  return fragment(node, open ? children.map(i => treeBranch(rows, i, section)) : null);
}
// ORCH-742 (look B): a saved ticket in Backlog says quietly where Prepare stands; Prepared means described, not checked
function prepareWord(t) {
  const p = t && t.status === 'open' && t.prepare && typeof t.prepare === 'object' ? t.prepare.state : '';
  if (p === 'preparing') return h('span', {className:'prepare-word', 'data-key':'prepare-word-' + t.id}, '· Preparing…');
  if (p === 'prepared') return h('span', {className:'prepare-word', title:'Described by the helper, not checked', 'data-key':'prepare-word-' + t.id}, '· Prepared');
  return null;
}
const changesLine = t => changesPending(t) ? h('p', {className:'meta changes-pending', 'data-key':'changes-' + t.id}, 'Changes to add') : null;
// A real relative time: when it finished, or when it last changed.
// G2: "Quiet since 09:20" on a Working ticket quiet for 6 h (the core computes quiet_since).
function quietLine(t) {
  const text = t.quiet_since ? window.DashHelpers.quietWords(t.quiet_since, now()) : '';
  return text ? h('span', {className:'meta quiet', 'data-key':'quiet-' + t.id}, text) : null;
}
function whenLine(t) {
  const at = shown(t).status === 'done' ? window.DashHelpers.doneAt(t) : t.updated_at;
  const text = at && window.DashHelpers.ago ? window.DashHelpers.ago(at, Date.now()) : '';
  return text ? h('span', {className:'meta when', title:String(at)}, text) : null;
}
let ticketView = 'list';
try { ticketView = storedTicketView(); } catch (_) { /* no storage: the list */ }
const boardMore = new Set();
const viewToggle = () => h('div', {className:'board-toolbar row', 'data-key':'board-tools'}, viewChips(),
  h('div', {className:'view-toggle', role:'group', 'aria-label':'How to show tickets'}, [['list', 'List', 'text'], ['board', 'Board', 'table'], ['calendar', 'Calendar', 'calendar']].map(([id, label, icon]) => h('button', {type:'button', className:'btn ghost seg', 'aria-pressed':ticketView === id, 'data-action':'view', 'data-view':id, 'data-key':'view-' + id}, iconEl(icon), label))), ticketFilters());
/* ORCH-576 (owner picked draft C, 18 Nov): every status is a row of small tiles, the most urgent row first. A tile is
   the title (2 lines) and one line: tasks, ONE signal, the ticket it is part of, one add-on icon, ⋯. Kit: .status-row,
   .ticket-tile, .parts-bar, .kind-tag, .scope-bar (widgets.css). Drag, the ⋯ menu and the moves are the same as before. */
const BOARD_ROWS = ['waiting', 'review', 'active', 'blocked', 'ready', 'open', 'done', 'dropped', 'superseded'];
const BOARD_FOLDED = ['done', 'dropped', 'superseded'];  // long rows at the end start folded: one click shows them
const boardOpen = new Set(), boardPartsOpen = new Set();
let boardScope = null;  // {root, mark} = a ticket and all its parts; {pair:[a, b], words} = waits for / replaced by
const BOARD_TONE = {waiting:'needs-you', review:'review', active:'working', blocked:'paused', ready:'text-muted', open:'text-faint', done:'done', dropped:'border-strong', superseded:'border-strong'};
const boardTone = lane => 'var(--' + (BOARD_TONE[lane] || 'text-faint') + ')';
const boardDot = lane => { const dot = h('span', {className:'sdot', 'aria-hidden':'true'}); dot.style?.setProperty('--c', boardTone(lane)); return dot; };
const boardLaneName = lane => (window.DashHelpers.LANES.find(([id]) => id === lane) || [lane, lane])[1];
const boardKind = t => t.release ? 'Release' : t.epic ? 'Epic' : '';
const boardShort = (text, n) => { const s = clean(text); return s.length > n ? s.slice(0, n - 1).trimEnd() + '…' : s; };
// Two rows of tiles before "Show N more"; a tile is at least 260 px wide (one column on the phone).
const boardTileColumns = () => { const w = (typeof document !== 'undefined' && document.getElementById('content')?.clientWidth) || 1200; return Math.max(1, Math.floor((w - (w > 720 ? 200 : 32)) / 266)); };
// A ticket and every ticket inside it, all levels.
function boardFamily(root) {
  const all = tickets(), ids = new Set();
  const walk = t => { if (!t || ids.has(t.id)) return; ids.add(t.id); boardChildren(all, t).forEach(walk); };
  walk(root); return ids;
}
const boardAncestors = t => { const out = []; for (let p = boardParent(tickets(), t); p && !out.includes(p); p = boardParent(tickets(), p)) out.unshift(p); return out; };
// The parts bar: one block per part, coloured by the row it is in, and "2/8" (an epic or release says "2/3 done").
function boardPartsBar(t, parts, open) {
  const done = parts.filter(p => boardLane(p) === 'done').length, order = BOARD_ROWS.slice().reverse();
  const blocks = parts.slice().sort((a, b) => order.indexOf(boardLane(b)) - order.indexOf(boardLane(a))).map(p => { const i = h('i', {}); i.style?.setProperty('--c', boardTone(boardLane(p))); return i; });
  const segs = h('span', {className:'parts-segs'}, blocks); segs.style?.setProperty('--n', String(parts.length));
  const words = done + ' of ' + parts.length + (t.release || t.epic ? ' tickets in this ' + boardKind(t).toLowerCase() : ' sub-tickets') + ' done';
  return h('button', {type:'button', className:'parts-bar', 'data-action':'board-parts', 'data-ticket':t.id, 'aria-expanded':open ? 'true' : 'false', title:words, 'aria-label':words, 'data-key':'parts-' + t.id},
    segs, h('span', {className:'tile-num'}, done + '/' + parts.length + (t.release || t.epic ? ' done' : '')));
}
// Add-on facts on a ticket: pull request states on its links and the fields an add-on shows on cards (show_on_card).
const BOARD_FACT_ORDER = ['bad', 'active', 'watch', 'info', 'good'];
const boardFactTone = word => /fail|conflict|error|red|blocked/i.test(word) ? 'bad' : /running|pending|behind|queued|draft/i.test(word) ? 'active' : /pass|green|merged|ready|done/i.test(word) ? 'good' : 'info';
function boardFacts(t) {
  const out = [], seen = new Set();
  for (const ref of array(t.refs)) {
    const v = ref?.view || {};
    if (!v.addon || !v.status) continue;
    seen.add(v.addon);
    out.push({tone:boardFactTone(v.status), icon:v.icon || 'link', text:clean((v.title || v.label || 'Link') + ': ' + v.status), url:ref.url});
  }
  for (const a of typeof addons === 'function' ? addons() : []) {
    const f = a.ticket_fields;
    if (!f || !array(f.show_on_card).length || seen.has(a.name)) continue;
    const ext = (t.ext || {})[a.name] || {};
    for (const key of f.show_on_card) {
      const value = ext[key];
      if (value == null || value === '') continue;
      const field = array(f.fields).find(x => x.key === key), label = field?.options?.find(o => o.value === value)?.label || String(value);
      out.push({tone:boardFactTone(label), icon:a.dashboard?.icon || a.icon || 'cards', text:clean((field?.title || key) + ': ' + label)});
    }
  }
  return out.sort((x, y) => BOARD_FACT_ORDER.indexOf(x.tone) - BOARD_FACT_ORDER.indexOf(y.tone));
}
function boardFactsIcon(t) {
  const facts = boardFacts(t);
  if (!facts.length) return null;
  const top = facts[0], words = facts.map(f => f.text).join(' · ');
  return h('details', {className:'menu tile-addon', 'data-key':'addon-' + t.id},
    h('summary', {className:'tile-icon', 'data-tone':top.tone, title:words, 'aria-label':words}, iconEl(top.icon), facts.length > 1 ? h('span', {className:'tile-num'}, String(facts.length)) : null),
    h('div', {className:'menu-pop tile-facts', role:'dialog', 'aria-label':'What add-ons say'}, facts.map(f => h('div', {className:'tile-fact', 'data-tone':f.tone}, iconEl(f.icon),
      h('div', {}, h('p', {}, f.text), f.url ? h('a', {href:f.url, target:'_blank', rel:'noopener'}, 'Open') : null)))));
}
// The one signal of a tile, most important first.
function boardSignal(t, lane, parts) {
  const status = shown(t).status;
  if (questions(t).length && status !== 'done') {
    return snapshot ? h('span', {className:'tile-sig warn'}, 'Needs you') : button('Answer', 'outline xs tile-answer', event => {
      const current = needsList().find(n => n.ticket === t.id);
      if (current) openNeed(current, event.currentTarget);
      else { ticketTabs.set(t.id, 'questions'); location.hash = href(t.id); }
    });
  }
  if (status === 'review') return h('a', {className:'btn outline xs', href:href(t.id)}, 'Check result');
  if (t.due && overdue(t)) return h('span', {className:'tile-sig warn'}, dueText(t));
  const helper = helperChip(t);
  if (helper) return h('span', {className:'tile-sig' + (/stuck/i.test(helper.line) || t.stuck ? ' bad' : '')}, helper.line || 'Idle');
  if (typeof changesPending === 'function' && changesPending(t)) return h('span', {className:'tile-sig warn'}, 'Changes to add');
  if (lane === 'superseded') {
    const other = ticketOf(t.superseded_by);
    return h('button', {type:'button', className:'tile-sig tile-link', 'data-action':'board-pair', 'data-ticket':t.id, 'data-other':other?.id || '', title:'Replaced by ' + clean(other?.key || '') + ' ' + clean(other?.title || '')}, 'Replaced by: ' + clean(other?.title || 'another ticket'));
  }
  if (status === 'done') { const at = window.DashHelpers.doneAt(t); return at ? h('span', {className:'tile-sig'}, 'Finished ' + localDay(at)) : null; }
  if (t.waiting_on?.kind === 'ticket') {
    const other = ticketOf(t.waiting_on.ref);
    return h('button', {type:'button', className:'tile-sig tile-link', 'data-action':'board-pair', 'data-ticket':t.id, 'data-other':other?.id || '', title:'Waits for ' + clean(other?.key || t.waiting_on.ref || '') + ' ' + clean(other?.title || '')}, 'Waits for: ' + clean(other?.title || t.waiting_on.ref || 'another ticket'));
  }
  if (ticketWaitsOnly(t)) {
    const text = clean(window.DashHelpers.waitWords(t, tickets(), window.UI?.stamp)).replace(/^Waits /, '').replace(/^until /, 'Until ');
    if (text) return h('span', {className:'tile-sig', title:text}, text);
  }
  if (ticketIsPaused(t) && ['open', 'ready'].includes(status) && !state.runs?.[t.id]?.running) return h('span', {className:'tile-sig'}, 'Paused');
  if (parts.length && !t.release && !t.epic) return boardPartsBar(t, parts, boardPartsOpen.has(t.id));
  const quiet = t.quiet_since ? window.DashHelpers.quietWords(t.quiet_since, now()) : '';
  if (quiet) return h('span', {className:'tile-sig'}, quiet);
  if (t.due) return h('span', {className:'tile-sig'}, dueText(t));
  return null;
}
function boardCard(t, lane = '') {
  const tasks = array(t.checklist), done = tasks.filter(window.DashHelpers.resolved).length;
  const parts = familyOf().kids.get(t.id) || [], parent = boardParent(tickets(), t), kind = boardKind(t);
  const open = boardPartsOpen.has(t.id) && parts.length;
  const late = t.due && overdue(t) && (questions(t).length || shown(t).status === 'review');
  const partOf = parent && boardScope?.root !== parent.id ? h('button', {type:'button', className:'tile-part-of tile-link', 'data-action':'board-scope', 'data-ticket':parent.id, 'data-mark':t.id, title:'Part of ' + clean(parent.key || '') + ' ' + clean(parent.title) + '. Show all its parts'}, 'Part of: ' + clean(parent.title)) : null;
  const card = h('article', {className:'ticket-tile' + (boardScope?.mark === t.id ? ' tile-mark' : ''), 'data-col':lane || null, draggable:snapshot ? null : 'true', 'data-ticket':t.id, 'data-key':'card-' + t.id},
    h('h3', {className:'tile-title'}, kind ? h('span', {className:'kind-tag', 'data-kind':kind.toLowerCase()}, kind) : null,
      h('a', {href:href(t.id), title:clean((t.key ? t.key + ' · ' : '') + t.title)}, window.DashHelpers.keyTag(t, h), clean(t.title)), titleTag(t)),
    h('div', {className:'tile-foot'},
      (kind && parts.length) ? boardPartsBar(t, parts, open) : tasks.length ? h('span', {className:'tile-num', title:window.DashHelpers.stepsText(done, tasks.length)}, done + '/' + tasks.length + ' tasks') : null,
      late ? h('span', {className:'tile-late', title:dueText(t), 'aria-label':dueText(t)}, iconEl('clock')) : null,
      boardSignal(t, lane, parts), partOf, h('span', {className:'grow'}), boardFactsIcon(t),
      snapshot ? null : h('details', {className:'menu', 'data-key':'card-menu-' + t.id}, h('summary', {className:'tile-icon move-button', 'aria-label':'Move ' + clean(t.title) + ' to another column'}, iconEl('more')), h('div', {className:'menu-pop', role:'menu'}, statusItems(t, 'card', BOARD_MOVES), laneOrderItems(t, lane)))),
    open ? h('div', {className:'tile-parts', 'data-key':'tile-parts-' + t.id}, parts.map(p => h('a', {className:'tile-part', href:href(p.id)},
      boardDot(boardLane(p)), window.DashHelpers.keyTag(p, h), h('span', {className:'grow tile-part-title'}, clean(p.title)), h('span', {className:'meta'}, boardLaneName(boardLane(p))))),
      h('button', {type:'button', className:'tile-link', 'data-action':'board-scope', 'data-ticket':t.id}, 'Show them on the board')) : null);
  card.style?.setProperty('--c', questions(t).length ? 'var(--needs-you)' : boardTone(lane));
  return card;
}
const COLUMN_EMPTY = {open:'New tickets land here', ready:'Nothing picked to do next', active:'No helper is working right now', waiting:'No questions for you. All clear',
  blocked:'Nothing waits for a date', review:'Nothing to check', done:'Finished tickets land here', dropped:'Nothing set aside', superseded:'Nothing replaced by another ticket'};
// ORCH-152: the lanes a card can move to from its menu (Needs you comes only from a helper's question).
const BOARD_MOVES = window.DashHelpers.MOVE_CHOICES;
const CAPPED_LANES = BOARD_ROWS;  // every row: two rows of tiles, then "Show N more"
const boardLane = t => window.DashHelpers.laneOf(t, shown(t).status, questions(t).length > 0);
// The bar over a scoped board: "In Release 27 › Parts of epic ORCH-546 Fast fix path · Done · 3 tickets, all levels".
function boardScopeBar(members) {
  const where = BOARD_ROWS.map(lane => [lane, members.filter(t => boardLane(t) === lane).length]).filter(([, n]) => n).map(([lane, n]) => n + ' ' + boardLaneName(lane).toLowerCase()).join(' · ');
  let head, up = null;
  if (boardScope.pair) {
    const [a, b] = boardScope.pair.map(ticketOf);
    head = h('p', {className:'scope-title'}, window.DashHelpers.keyTag(a, h), clean(a?.title), h('span', {className:'meta'}, ' ' + boardScope.words + ' '), window.DashHelpers.keyTag(b, h), clean(b?.title));
  } else {
    const root = ticketOf(boardScope.root), kind = boardKind(root), ups = boardAncestors(root), parts = boardChildren(tickets(), root);
    up = ups.length ? h('p', {className:'scope-up meta'}, 'In ', ups.map((p, i) => [i ? ' › ' : '', h('button', {type:'button', className:'tile-link', 'data-action':'board-scope', 'data-ticket':p.id}, (boardKind(p) && !clean(p.title).startsWith(boardKind(p)) ? boardKind(p) + ' ' : '') + boardShort(p.title, 32))])) : null;
    head = h('p', {className:'scope-title'}, 'Parts of ' + (kind ? kind.toLowerCase() + ' ' : ''), window.DashHelpers.keyTag(root, h), clean(root.title), ' ',
      h('span', {className:'chip outline sm'}, boardLaneName(boardLane(root))), parts.length ? boardPartsBar(root, parts, false) : null);
  }
  const count = boardScope.pair ? '' : members.length + (members.length === 1 ? ' ticket' : ' tickets') + ', all levels · ';
  return h('div', {className:'scope-bar', role:'status', 'data-key':'scope-bar'}, h('div', {className:'grow'}, up, head, h('p', {className:'meta'}, count + where)),
    h('button', {type:'button', className:'btn outline sm', 'data-action':'board-scope-clear', 'data-key':'scope-clear'}, 'Back to all tickets'));
}
function board() {
  // Won't do and Superseded tickets are hidden everywhere else; the board shows them in their own rows.
  const who = typeof state?.who === 'string' ? state.who : '';
  // "Part of" on the board shows the ticket and every ticket inside it (all levels), like a click on "Part of: …".
  if (ticketGroup && !boardScope) boardScope = {root:ticketGroup, group:true};
  if (boardScope?.group && ticketGroup !== boardScope.root) boardScope = null;
  if (boardScope && !boardScope.pair && !ticketOf(boardScope.root)) boardScope = null;
  const group = boardScope ? '' : ticketGroup;
  const dropped = filterTickets(ticketParents(array(state?.tickets).filter(t => t.status === 'dropped')), ticketSearch, ticketMine, who, ticketPerson, savedView(), group);
  let visible = sorted([...filterTickets(ticketParents(pageRows()), ticketSearch, ticketMine, who, ticketPerson, savedView(), group), ...dropped]);
  if (boardScope) {
    const ids = boardScope.pair ? new Set(boardScope.pair) : boardFamily(ticketOf(boardScope.root));
    visible = visible.filter(t => ids.has(t.id) && t.id !== boardScope.root);
  }
  const search = String(ticketSearch).trim(), cols = boardTileColumns();
  const rows = BOARD_ROWS.map(status => {
    const label = boardLaneName(status), mine = window.DashHelpers.laneSorted(visible.filter(t => boardLane(t) === status), status);  // ORCH-156: the person's order
    // ORCH-523: Done counts every finished ticket (most are not on the page) and loads more as its end scrolls into view
    const fetchMore = status === 'done' && !boardScope && moreFinished(mine.length) ? loadFinished : null, total = boardScope ? mine.length : groupCount(status, mine.length);
    if (!mine.length && (boardScope || ['dropped', 'superseded'].includes(status))) return null;  // ORCH-240: empty set-aside rows take no room
    const folded = BOARD_FOLDED.includes(status) && !boardOpen.has(status) && !search && !boardScope;
    const capped = !boardScope && !search && mine.length > cols * 2;  // a search or a scope shows every hit
    const cap = capped && !boardMore.has(status) ? cols * 2 : mine.length;
    const body = !mine.length ? h('p', {className:'meta status-row-none'}, COLUMN_EMPTY[status])
      : folded ? h('button', {type:'button', className:'tile-link status-row-none', 'data-action':'board-open', 'data-lane':status, 'data-key':'board-open-' + status}, 'Show ' + total)
      : [h('div', {className:'tile-grid', 'data-key':'grid-' + status}, mine.slice(0, cap).map(t => boardCard(t, status))),
        capped || (BOARD_FOLDED.includes(status) && boardOpen.has(status)) ? h('div', {className:'row status-row-foot'},
          capped ? h('button', {type:'button', className:'btn ghost sm show-done', 'data-action':'board-more', 'data-lane':status, 'data-key':'board-more-' + status}, boardMore.has(status) ? 'Show fewer' : 'Show ' + (Math.max(mine.length, total) - cols * 2) + ' more') : null,
          BOARD_FOLDED.includes(status) && boardOpen.has(status) ? h('button', {type:'button', className:'btn ghost sm', 'data-action':'board-open', 'data-lane':status, 'data-key':'board-fold-' + status}, 'Fold') : null) : null,
        fetchMore && (!capped || boardMore.has(status)) ? moreMark('lane-' + status, 0, fetchMore) : null];
    const dot = boardDot(status);
    return h('section', {className:'status-row' + (mine.length ? '' : ' is-empty'), 'data-status':status, 'data-key':'col-' + status, 'aria-label':label + ', ' + total},
      h('div', {className:'status-row-h'}, dot, h('h2', {}, label), h('span', {className:'status-count count-n'}, String(total))),
      h('div', {className:'status-row-main', 'data-key':'col-body-' + status}, body));
  }).filter(Boolean);
  const members = boardScope ? visible : [];
  return h('div', {className:'board status-rows', 'data-key':'board'}, boardScope ? boardScopeBar(members) : null,
    h('div', {className:'status-rows-track', title:snapshot ? null : 'Drag a tile to another row, or use its ⋯ menu'}, rows));
}
// Tiles glide to their new place after a move, a filter or "Show more" (render keeps them by key). Nothing moves with
// reduced motion.
function boardTileRects(root) {
  if (!root.querySelector('.status-rows')) return null;
  return new Map([...root.querySelectorAll('.ticket-tile[data-ticket]')].map(el => [el.dataset.ticket, el.getBoundingClientRect()]));
}
function boardGlide(root, before) {
  if (!before || matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  root.querySelectorAll('.ticket-tile[data-ticket]').forEach(el => {
    const b = before.get(el.dataset.ticket);
    if (!b) { el.animate?.([{opacity:0, transform:'translateY(4px)'}, {opacity:1, transform:'none'}], {duration:200, easing:'cubic-bezier(0, 0.4, 0, 1)'}); return; }
    const a = el.getBoundingClientRect(), dx = b.left - a.left, dy = b.top - a.top;
    if ((dx || dy) && Math.abs(dy) < innerHeight * 2) el.animate?.([{transform:'translate(' + dx + 'px, ' + dy + 'px)'}, {transform:'none'}], {duration:200, easing:'cubic-bezier(0.4, 0, 0, 1)'});
  });
}
// "Replaced by ORCH-60" on a Superseded card.
function replacedLine(t) {
  if (t.status !== 'dropped' || !t.superseded_by) return null;
  const other = ticketOf(t.superseded_by);
  return h('p', {className:'meta ticket-sub', 'data-key':'replaced-' + t.id}, 'Replaced by ', other ? h('a', {href:href(other.id)}, other.key || clean(other.title)) : 'another ticket');
}
/* ORCH-156: the order inside a lane. The whole lane is sent first to last (every card keeps its place); the cards
   move at once and go back when the save fails. `before`: the card it lands above, null = the end of the lane. */
// Parents and parts of every ticket, worked out once per state (ORCH-523: each board card asked over all tickets).
// The same rules as DashHelpers.parentOf / childrenOf: the parent field (id or key), else a parent's children list.
let familyMemo = {of:null};
function familyOf() {
  if (familyMemo.of === state?.tickets) return familyMemo;
  const all = tickets(), byId = new Map(all.map(t => [t.id, t])), kids = new Map(), parent = new Map();
  for (const t of ticketParents(all)) if (t.parent && byId.has(t.parent)) parent.set(t.id, byId.get(t.parent));
  const add = (pid, c) => { if (pid === c.id) return; const list = kids.get(pid) || []; if (!list.includes(c)) list.push(c); kids.set(pid, list); };
  const byKey = new Map(all.filter(t => t.key).map(t => [String(t.key).toLowerCase(), t]));
  for (const c of all) { const p = c.parent && (byId.get(c.parent) || byKey.get(String(c.parent).toLowerCase())); if (p) add(p.id, c); }
  for (const p of all) for (const id of array(p.children)) if (byId.has(id)) add(p.id, byId.get(id));
  for (const list of kids.values()) list.sort(window.DashHelpers.creationOrder);
  familyMemo = {of:state?.tickets, kids, parent};
  return familyMemo;
}
// The ids of a lane in its order, once per state (every card's Move up / Move down asks).
let laneMemo = {of:null, runs:null, lanes:new Map()};
function laneIds(lane) {
  if (laneMemo.of !== state?.tickets || laneMemo.runs !== state?.runs) laneMemo = {of:state?.tickets, runs:state?.runs, lanes:new Map()};
  if (!laneMemo.lanes.has(lane)) laneMemo.lanes.set(lane, laneTickets(lane).map(t => t.id));
  return laneMemo.lanes.get(lane);
}
function laneTickets(lane) {
  return window.DashHelpers.laneSorted(sorted(array(state?.tickets).filter(t => boardLane(t) === lane)), lane);
}
function orderInLane(id, lane, before) {
  if (snapshot || !lane || locks.has('order-' + lane) || changeUnavailable()) return Promise.resolve();
  const was = laneTickets(lane).map(t => t.id), ids = window.DashHelpers.laneReorder(was, id, before);
  if (ids.join() === was.join()) return Promise.resolve();
  const old = new Map(array(state.tickets).map(t => [t.id, t.lane_order]));
  const place = new Map(ids.map((x, i) => [x, {lane, n:i + 1}]));
  state.tickets = state.tickets.map(t => place.has(t.id) ? {...t, lane_order:place.get(t.id)} : t);
  locks.add('order-' + lane); render();
  return act('ticket.order', {lane, tickets:ids}).then(result => {
    locks.delete('order-' + lane);
    if (!result.ok) {
      state.tickets = state.tickets.map(t => place.has(t.id) ? {...t, lane_order:old.get(t.id)} : t);
      window.orch.toast(changeError(result), 'error');
    }
    render();
  });
}
// Move up / Move down in the card menu: the same order by keyboard, no dragging needed.
function laneStep(id, lane, step) {
  const ids = laneTickets(lane).map(t => t.id), at = ids.indexOf(id);
  if (at < 0) return Promise.resolve();
  if (step < 0) return at > 0 ? orderInLane(id, lane, ids[at - 1]) : Promise.resolve();
  return at < ids.length - 1 ? orderInLane(id, lane, ids[at + 2] ?? null) : Promise.resolve();
}
function laneOrderItems(t, lane) {
  if (!lane) return null;
  const ids = laneIds(lane), at = ids.indexOf(t.id);
  if (at < 0 || ids.length < 2) return null;
  return [['up', 'Move up', at > 0], ['down', 'Move down', at < ids.length - 1]].filter(x => x[2]).map(([dir, label]) =>
    h('button', {type:'button', className:'menu-item', role:'menuitem', 'data-action':'lane-' + dir, 'data-ticket':t.id, 'data-lane':lane, 'data-key':'lane-' + dir + '-' + t.id}, label));
}
/* ORCH-152: a move to a lane. Waiting asks for the date it waits until, Superseded for the ticket that replaces it;
   every other lane moves at once (with Undo). */
function moveToLane(id, lane, from) {
  const t = ticketOf(id);
  if (!t || snapshot) return Promise.resolve();
  if (lane === 'blocked') return askWaitUntil(t, from);
  if (lane === 'superseded') return askReplacedBy(t, from);
  const data = window.DashHelpers.laneMove(lane);
  if (!data) return Promise.resolve();
  const {status, ...more} = data;
  if (lane === 'dropped' && t.status === 'dropped' && !t.superseded_by) return Promise.resolve();
  return moveTicket(id, status, false, lane === 'dropped' && !t.superseded_by ? {} : {data:more});
}
// Quick choices for Waiting, all at 09:00 local time: one click each.
function waitChoices(now = new Date()) {
  const at = days => { const d = new Date(now.getFullYear(), now.getMonth(), now.getDate() + days, 9, 0); return d; };
  const monday = (8 - now.getDay()) % 7 || 7;
  return [['Tomorrow', at(1)], ['Next Monday', at(monday)], ['In a week', at(7)]];
}
const utcStamp = d => d.toISOString().replace(/\.\d{3}Z$/, 'Z');
function askWaitUntil(t, from) {
  const {d, actions} = dialog('Wait until when?');
  // ORCH-235: what it waits for (optional), shown on the ticket next to the date
  const why = h('input', {className:'input', type:'text', maxLength:200, id:'wait-why-' + t.id, 'data-key':'wait-why', placeholder:'For example: the price list from the supplier'});
  const done = until => {
    window.orch.close(d);
    const reason = why.value.trim(), wait = {kind:'time', until:utcStamp(until), ...(reason ? {ref:reason} : {})};
    return moveTicket(t.id, 'waiting', false, {data:{waiting_on:wait}});
  };
  const input = h('input', {className:'input', type:'datetime-local', id:'wait-until-' + t.id, 'data-key':'wait-until'});
  const error = h('p', {className:'meta bad', role:'alert', hidden:true});
  const quick = h('div', {className:'row wrap'}, waitChoices().map(([label, at]) => { const when = window.UI?.stamp ? window.UI.stamp(at) : ''; return button(when ? when.charAt(0).toUpperCase() + when.slice(1) : label, 'outline sm', () => done(at)); }));
  const save = button('Wait', 'primary', () => {
    const at = input.value ? new Date(input.value) : null;
    if (!at || Number.isNaN(at.getTime()) || at <= new Date()) { error.textContent = 'Pick a day and time in the future.'; error.hidden = false; input.focus(); return; }
    done(at);
  });
  actions.append(save);
  d.append(h('div', {className:'stack'}, h('p', {className:'meta'}, clean(t.title)),
    h('label', {className:'field', for:why.id}, 'What does it wait for?', why), quick,
    h('label', {className:'field', for:input.id}, 'Or pick a day and time', input), error,
    h('p', {className:'meta'}, 'On that day it shows on Home again.')), actions);
  d.showModal();
  return Promise.resolve();
}
function askReplacedBy(t, from) {
  const {d, actions} = dialog('Which ticket replaces it?');
  const others = sorted(tickets().filter(o => o.id !== t.id && activeTicket(o)));
  const select = h('select', {className:'input', id:'replaced-by-' + t.id, 'data-key':'replaced-by'},
    h('option', {value:''}, 'Choose a ticket'), others.map(o => h('option', {value:o.id}, (o.key ? o.key + ' ' : '') + clean(o.title))));
  const error = h('p', {className:'meta bad', role:'alert', hidden:true});
  const save = button('Move to Superseded', 'primary', () => {
    if (!select.value) { error.textContent = 'Choose the ticket that replaces it.'; error.hidden = false; select.focus(); return; }
    window.orch.close(d);
    moveTicket(t.id, 'dropped', false, {data:{superseded_by:select.value}});
  });
  actions.append(save);
  d.append(h('div', {className:'stack'}, h('p', {className:'meta'}, clean(t.title)),
    h('label', {className:'field', for:select.id}, 'Replaced by', select), error), actions);
  d.showModal();
  select.focus();
  return Promise.resolve();
}
const movePending = new Map();
// Optimistic: the card moves and the notice (with Undo) shows at once; a failed save puts the card back.
// `extra`: more arguments of the change (Accept on a ticket in Review sends the review tip it showed).
function offerStart(id) {
  const toast = window.orch.toast('No helper is working on it yet.', 'ok');
  if (!toast?.querySelector) return;
  // the one Start button (ORCH-475): one click starts, the caret opens the Start choice, Starting… until it runs
  const start = h('span', {className:'start-host', 'data-action':'offer-start'});
  const look = {align:'start'};
  look.style = 'ghost';  // a quiet button in a notice
  if (!startButtonIn(start, ticketOf(id), look)) return;
  toast.querySelector('button[aria-label="Dismiss notification"]')?.before(start);
}
/* ORCH-235: Done on a ticket whose sub-tickets are not all finished asks once (no typed word): "Mark Done anyway"
   or Cancel. Resolves true to go on. */
function confirmOpenKids(t, open) {
  return new Promise(resolve => {
    const {d, actions} = dialog('Mark Done with open sub-tickets?');
    let yes = false;
    d.addEventListener('close', () => resolve(yes));
    const names = open.slice(0, 3).map(k => k.key || clean(k.title)).join(', ') + (open.length > 3 ? ' and ' + (open.length - 3) + ' more' : '');
    actions.append(button('Mark Done anyway', 'primary', () => { yes = true; window.orch.close(d); }));
    d.append(h('div', {className:'stack'}, h('p', {className:'meta'}, clean(t.title)),
      h('p', {}, (open.length === 1 ? '1 sub-ticket is' : open.length + ' sub-tickets are') + ' not done yet: ' + names + '.')), actions);
    d.showModal();
  });
}
function moveTicket(id, status, undoing = false, extra = {}) {
  if (status === 'done' && !undoing && extra.quiet !== true && !extra.kids_ok) {
    const t = ticketOf(id), open = t && t.status !== 'done' && window.DashHelpers?.childrenOf ? window.DashHelpers.childrenOf(tickets(), t).filter(activeTicket) : [];
    if (open.length && !snapshot) return confirmOpenKids(t, open).then(yes => yes ? moveTicket(id, status, false, {...extra, kids_ok:true}) : undefined);
  }
  if ('kids_ok' in extra) { extra = {...extra}; delete extra.kids_ok; }
  const quiet = extra.quiet === true;  // the caller shows one toast for a whole batch
  if ('quiet' in extra) { extra = {...extra}; delete extra.quiet; }
  if (status === 'done' && !extra.review_tip) extra = {...extra, review_tip:'none'}; // this view showed no review tip
  const more = extra.data || {};  // ORCH-152: a wait date or the replacing ticket, written with the status
  if ('data' in extra) { extra = {...extra}; delete extra.data; }
  const t = ticketOf(id), lock = 'status-' + id;
  const same = t && t.status === status && Object.keys(more).every(k => JSON.stringify(t[k] ?? null) === JSON.stringify(more[k]));
  if (!t || same || snapshot || locks.has(lock) || changeUnavailable()) return Promise.resolve();
  const previous = t.status, revision = t.revision;
  // Undo puts back what the lane needed: the wait of a waiting ticket, the replacing ticket of a Superseded one.
  const before = previous === 'waiting' && t.waiting_on ? {waiting_on:t.waiting_on} : previous === 'dropped' && t.superseded_by ? {superseded_by:t.superseded_by} : {};
  locks.add(lock);
  const set = (value, fields = {}) => { state.tickets = state.tickets.map(x => x.id === id ? {...x, status:value, ...(value !== 'waiting' ? {waiting_on:null} : {}), ...(value !== 'dropped' ? {superseded_by:undefined} : {}), ...fields} : x); };
  document.querySelectorAll('[data-key="ticket-' + id + '"],[data-key="family-' + id + '"]').forEach(n => n.classList.add('status-leaving'));
  set(status, more);
  const unfade = () => document.querySelectorAll('.status-leaving').forEach(n => n.classList.remove('status-leaving'));
  const fade = new Promise(resolve => setTimeout(resolve, matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 160)).then(() => { unfade(); render(); });
  const lanes = window.DashHelpers?.LANES, lane = lanes && window.DashHelpers.laneOf({...t, status, ...more}, status, false);
  const label = (lanes && lanes.find(([id]) => id === lane)?.[1]) || STATUS_CHOICES.find(([value]) => value === status)?.[1] || status;
  const toast = quiet ? null : window.orch.toast(undoing ? 'Moved back' : 'Moved to ' + label, 'ok');
  if (!undoing && toast?.querySelector) {
    const undo = h('button', {type:'button', className:'btn ghost sm', 'data-action':'undo-move'}, 'Undo');
    undo.addEventListener('click', async () => { toast.remove(); await movePending.get(id); moveTicket(id, previous, true, {data:before}); });
    toast.querySelector('button[aria-label="Dismiss notification"]')?.before(undo);
  }
  const run = (async () => {
    let result;
    try { result = await actRetry('ticket.patch', () => ({...extra, ticket:id, data:{status, ...more}, if_revision:(ticketOf(id) || t).revision || revision}), () => { const now = ticketOf(id); return !!now && now.status === previous; }); }
    catch (err) { result = {ok:false, status:0, text:String(err?.message || err)}; }
    await fade;
    locks.delete(lock);
    if (!result.ok) { set(previous, before); toast?.remove?.(); window.orch.toast(changeError(result), 'error'); }
    unfade();
    render();
    // ORCH-248 (owner 17 Nov): a move to Working by hand starts no helper; offer Start instead of the silent fall back to To do.
    if (result.ok && status === 'active' && !undoing && !quiet && state.runs?.[id]?.running !== true) offerStart(id);
  })();
  movePending.set(id, run);
  run.finally(() => { if (movePending.get(id) === run) movePending.delete(id); });
  return run;
}
const GROUP_ORDER = ['waiting', 'review', 'active', 'blocked', 'ready', 'open', 'done'];
const foldedGroups = new Set(), searchFolds = new Set();
let foldSeen = false;
// The group's main action for all its tickets: "Answer 2 questions" opens the first question, "Check 3 results" the first result.
function groupAction(status, group, folded = foldedGroups.has(status)) {
  if (snapshot || folded) return null;
  const withQuestions = group.filter(t => questions(t).length);
  if (status === 'waiting' && withQuestions.length) {
    // ORCH-1716: the number counts tickets, as the group's own number does (a ticket can hold two questions)
    const n = withQuestions.length;
    return button('Answer ' + n + (n === 1 ? ' ticket' : ' tickets'), 'outline sm group-action', event => {
      const need = needsList().find(x => withQuestions.some(t => t.id === x.ticket));
      if (need) openNeed(need, event.currentTarget); else location.hash = href(withQuestions[0].id);
    });
  }
  if (status === 'review' && group.length) return h('a', {className:'btn outline sm group-action', href:href(group[0].id)}, 'Check ' + group.length + (group.length === 1 ? ' result' : ' results'));
  return null;
}
const searchHead = n => { const q = String(ticketSearch).trim(); if (q && searchServed() && !savedView()) n = Math.max(n, hits.total); return q ? n + (n === 1 ? ' ticket matches “' : ' tickets match “') + q + '”' : 'Ticket · ' + n; };
// The number on a group: for Done the server's count when only part of the finished tickets are here (ORCH-523).
const groupCount = (status, n) => status === 'done' && !savedView() && !String(ticketSearch).trim() ? Math.max(n, finishedTotal() || 0) : n;
const searchMore = () => searchServed() && hits.next != null ? () => searchPage(hits.key, hits.next) : null;
function ticketTable(visible) {
  const rel = releaseGroups(visible), groups = ticketGroups(visible.filter(t => !rel.inRelease.has(t.id)));
  if (!foldSeen) { foldSeen = true; if (groupCount('done', groups.find(g => g.status === 'done')?.tickets.length || 0) > 5) foldedGroups.add('done'); }
  const body = [];
  releaseFolds(rel.groups);
  for (const group of rel.groups) {
    const status = group.status, rows = window.DashHelpers.treeRows(group.tickets);
    const folds = String(ticketSearch).trim() ? searchFolds : foldedGroups, folded = folds.has(status);
    const toggle = h('button', {type:'button', className:'group-toggle', 'aria-expanded':String(!folded), 'data-key':'group-toggle-' + status}, (folded ? '› ' : '⌄ ') + group.title + ' ', h('span', {className:'meta'}, releaseCount(group)));
    toggle.addEventListener('click', () => { if (folded) folds.delete(status); else folds.add(status); render(); });
    body.push(h('tr', {className:'group-row', 'data-key':'group-' + status}, h('th', {colSpan:6}, h('div', {className:'group-head'}, toggle, folded ? null : releaseOpen(group)))));
    if (folded) continue;
    const roots = rows.map((row, i) => ({row, i})).filter(({row}) => row.depth === 0), cap = capOf('list-' + status);
    for (const {i} of roots.slice(0, cap)) body.push(treeBranch(rows, i, status));
    if (roots.length > cap) body.push(h('tr', {className:'group-row', 'data-key':'more-row-' + status}, h('td', {colSpan:6}, moreMark('list-' + status, roots.length - cap))));
  }
  for (const status of GROUP_ORDER) {
    const group = groups.find(g => g.status === status), rows = window.DashHelpers.treeRows(group.tickets);
    const roots = rows.map((row, i) => ({row, i})).filter(({row}) => row.depth === 0);
    if (!roots.length && !(status === 'done' && moreFinished(0))) continue;  // Done shows with the server's count (ORCH-523)
    // a search shows its hits: every group opens while a search is typed; folding then lasts for that search (ORCH-58)
    const folds = String(ticketSearch).trim() ? searchFolds : foldedGroups;
    const [icon] = STATUS_BADGE[status] || STATUS_BADGE.open, folded = folds.has(status);
    const toggle = h('button', {type:'button', className:'group-toggle', 'aria-expanded':String(!folded), 'data-key':'group-toggle-' + status}, (folded ? '› ' : '⌄ ') + icon + ' ' + group.title + ' ', h('span', {className:'meta'}, String(groupCount(status, group.tickets.length))));
    toggle.addEventListener('click', () => { if (folded) folds.delete(status); else folds.add(status); render(); });
    body.push(h('tr', {className:'group-row', 'data-key':'group-' + status}, h('th', {colSpan:6}, h('div', {className:'group-head'}, toggle, groupAction(status, group.tickets, folded)))));
    if (folded) continue;
    const cap = capOf('list-' + status), fetchMore = status === 'done' && moreFinished(group.tickets.length) ? loadFinished : null;
    for (const {i} of roots.slice(0, cap)) body.push(treeBranch(rows, i, status));
    if (roots.length > cap || fetchMore) body.push(h('tr', {className:'group-row', 'data-key':'more-row-' + status}, h('td', {colSpan:6}, moreMark('list-' + status, roots.length - cap, fetchMore))));
  }
  const more = searchMore();
  if (more) body.push(h('tr', {className:'group-row', 'data-key':'more-row-search'}, h('td', {colSpan:6}, moreMark('search', 0, more))));
  // This week: one total line of helper time and money under the table
  if (savedView() === 'this-week') {
    const total = window.DashHelpers.spendTotal(visible);
    body.push(h('tr', {className:'group-row', 'data-key':'week-total'}, h('th', {colSpan:3}, h('span', {className:'meta'}, 'This week')),
      h('th', {className:'numeric'}, h('span', {className:'meta'}, window.DashHelpers.spendWords(total) || '–')), h('th', {colSpan:2})));
  }
  const heads = [[searchHead(visible.length), ''], ['Due', ''], ['Tasks', ''], ['Time · cost', 'numeric'], ['Last change', '']];
  return h('div', {className:'table-wrap wide-only', 'data-key':'ticket-table'}, h('table', {className:'ticket-table'},
    h('thead', {}, h('tr', {}, heads.map(([label, cls]) => h('th', {scope:'col', className:cls || null}, label)), h('th', {scope:'col'}, h('span', {className:'sr-only'}, 'Actions')))),
    h('tbody', {}, body)));
}
// Phone (ORCH-73, owner 16 Nov): the same groups as short rows (master UI.shortGroup), never a squeezed table.
// One row: number and title, one fact, one thing on the right (Answer where the person is needed, else steps n/m or an
// Idle/Stuck chip). A group shows its first PHONE_ROWS rows, then "n more".
const PHONE_ROWS = 8, phoneMore = new Set();
const SHORT_ICON = {waiting:'needs', review:'check', active:'working', blocked:'todo', ready:'todo', open:'todo', done:'done'};
function shortFact(t, row) {
  const ago = iso => iso && window.DashHelpers.ago ? window.DashHelpers.ago(iso, Date.now()) : '';
  if (questions(t).length && shown(t).status !== 'done') { const since = window.DashHelpers.askedAt(t, needsList()); return 'Question' + (ago(since) ? ' · ' + ago(since) : ''); }
  if (changesPending(t)) return 'Changes to add';
  const waits = waitsLine(t)?.textContent;
  if (waits) return waits;
  if (t.quiet_since) return window.DashHelpers.quietWords(t.quiet_since, now());
  const helper = helperChip(t);
  if (helper?.line) return helper.line;
  if (t.due && shown(t).status !== 'done') { const due = dueText(t); return /^(Due|Late)\b/.test(due) ? due : 'Due ' + due; }  // ORCH-189: the due day is the one fact when set
  if (row.parentMissing && typeof parentLine === 'function') { const step = parentLine(t)?.textContent; if (step) return step; }
  const at = shown(t).status === 'done' ? window.DashHelpers.doneAt(t) : t.updated_at;
  return (shown(t).status === 'done' && at ? 'Finished ' : '') + ago(at);
}
function shortSide(t, row, status) {
  // ORCH-1716: a result to check says Check result at every width (the computer row shows it first, the session button
  // only on hover); the phone has room for one thing, so it is that one
  if (!snapshot && shown(t).status === 'review' && !questions(t).length) return h('a', {className:'btn outline sm', href:href(t.id)}, 'Check result');
  const live = typeof liveFocusButton === 'function' ? liveFocusButton(t) : null;
  if (live) return live;
  if (!snapshot && questions(t).length && shown(t).status !== 'done') return button('Answer', 'outline sm', event => {
    event.stopPropagation();
    const need = needsList().find(x => x.ticket === t.id);
    if (need) openNeed(need, event.currentTarget); else location.hash = href(t.id);
  });
  const helper = helperChip(t);
  if (helper) return helper.chip;
  const tasks = array(t.checklist), total = tasks.length || row.children || 0;
  if (!total) return null;
  const done = tasks.length ? tasks.filter(window.DashHelpers.resolved).length : row.done || 0;
  const pill = h('span', {className:'pill ' + ({active:'working', done:'done', waiting:'needs'}[status] || ''), title:window.DashHelpers.stepsText(done, total)});
  if (window.UI?.statusIcon) pill.append(window.UI.statusIcon(SHORT_ICON[status] || 'todo'));
  pill.append(done + '/' + total);
  return pill;
}
function phoneList(visible) {
  const rel = releaseGroups(visible), groups = ticketGroups(visible.filter(t => !rel.inRelease.has(t.id))), out = [];
  releaseFolds(rel.groups);
  const order = [...rel.groups, ...GROUP_ORDER.map(status => groups.find(g => g.status === status))];
  for (const group of order) {
    const status = group.status, rows = window.DashHelpers.treeRows(group.tickets), isRel = !!group.release;
    const roots = rows.filter(row => row.depth === 0);
    if (!roots.length && !(!isRel && status === 'done' && moreFinished(0))) continue;
    const folds = String(ticketSearch).trim() ? searchFolds : foldedGroups, folded = folds.has(status);
    const shownRows = rows.filter(row => row.depth <= 1), all = phoneMore.has(status), cut = shownRows.slice(0, all ? capOf('phone-' + status) : PHONE_ROWS);
    const fetchMore = !isRel && status === 'done' && moreFinished(group.tickets.length) ? loadFinished : null, total = isRel ? group.tickets.length : groupCount(status, group.tickets.length);
    const sec = window.UI.shortGroup({key:'short-' + status, title:isRel ? group.title + ' · ' + releaseCount(group) : group.title, icon:isRel ? (group.finished ? 'done' : 'todo') : SHORT_ICON[status], count:total, folded,
      onToggle:() => { if (folded) folds.delete(status); else folds.add(status); render(); },
      rows:cut.map(row => ({key:typeof row.ticket.key === 'string' ? row.ticket.key : '', title:clean(row.ticket.title), href:href(row.ticket.id), child:row.depth > 0,
        fact:[window.DashHelpers.kindWord(row.ticket), shortFact(row.ticket, isRel ? {...row, parentMissing:false} : row)].filter(Boolean).join(' · '), side:shortSide(row.ticket, row, isRel ? ticketColumn(row.ticket) : status), dataKey:'short-' + row.ticket.id})),
      more:!all && (cut.length < shownRows.length || fetchMore) ? {label:Math.max(shownRows.length - cut.length, total - cut.length) + ' more', onClick:() => { phoneMore.add(status); render(); }} : null});
    sec.querySelectorAll('.short-row').forEach(rowEl => rowEl.addEventListener('click', e => {
      if (e.target.closest('a,button')) return;
      const link = rowEl.querySelector('a.short-title'); if (link) location.hash = link.getAttribute('href');
    }));
    sec.querySelector('.card-h button')?.setAttribute('data-key', 'short-toggle-' + status);
    out.push(sec);
    if (all && !folded && (cut.length < shownRows.length || fetchMore)) out.push(moreMark('phone-' + status, shownRows.length - cut.length, fetchMore));
  }
  const more = searchMore();
  if (more) out.push(moreMark('phone-search', 0, more));
  return h('div', {className:'phone-only short-list', 'data-key':'ticket-short'}, out);
}
/* ORCH-1081 (owner picked draft C, 20 Nov): the Calendar layout. Month = the weeks as rows (Mon-Fri and one Weekend
   cell; this week tallest, past weeks only "1 done"), Week = one full-width row per day with readable cards. Late
   tickets leave their day for one Late list on the left; on the phone Late comes first, past weeks fold, then a list
   per day. Only the due day counts. Looks: master widgets.css .cal-* (gallery: Tickets calendar). */
const CAL = () => window.DashHelpers.calendar;
const calToggled = new Set();  // phone groups the person folded or opened (Late starts open, past weeks folded)
const calIcon = t => window.UI.statusIcon(SHORT_ICON[ticketColumn(t)] || 'todo');
const calWord = t => statusWord(shown(t));
const calTone = t => overdue(t) ? 'late' : shown(t).status === 'done' ? 'done' : CAL().dayOf(t.due) === today() ? 'today' : '';
const calWasDue = t => 'Was due ' + CAL().dayShort(CAL().dayOf(t.due)) + (CAL().time(t.due) ? ', ' + CAL().time(t.due) : '');
const calLabel = t => [[typeof t.key === 'string' ? t.key : '', clean(t.title)].filter(Boolean).join(' '), calWord(t), name(t.owner), overdue(t) ? calWasDue(t) : dueText(t)].filter(Boolean).join(', ');
const calKey = t => window.DashHelpers.keyTag(t, h);
// A ticket as one line on a day: status icon, key and title, then time and person (with the status word on the phone).
function calChip(t, o = {}) {
  const meta = o.meta === false ? '' : [o.word ? calWord(t) : '', CAL().time(t.due), name(t.owner)].filter(Boolean).join(' · ');
  return h('a', {className:'cal-chip', href:href(t.id), 'data-tone':calTone(t) || null, title:clean(t.title), 'aria-label':calLabel(t), 'data-key':'cal-chip-' + (o.at || '') + t.id},
    calIcon(t), h('span', {className:'cal-chip-t'}, calKey(t), clean(t.title)), meta ? h('span', {className:'cal-chip-m'}, meta) : null);
}
// A readable card for the week: status word, key and title, person, due time.
function calCard(t) {
  const tone = calTone(t), time = CAL().time(t.due), who = name(t.owner);
  const pill = h('span', {className:'pill ' + ({active:'working', done:'done', waiting:'needs'}[ticketColumn(t)] || '')}, calIcon(t), calWord(t));
  return h('a', {className:'cal-card', href:href(t.id), 'data-tone':tone || null, 'data-key':'cal-card-' + t.id},
    h('span', {className:'cal-card-s'}, pill), h('span', {className:'cal-card-t'}, calKey(t), clean(t.title)),
    h('span', {className:'cal-card-who'}, who ? [h('span', {className:'avatar sm', 'aria-hidden':'true'}, initials(t.owner)), who] : null),
    h('span', {className:'cal-card-due'}, tone === 'today' ? chip(time ? 'Due ' + time : 'Today', 'warning') : time && tone !== 'done' ? h('span', {className:'cal-time'}, time) : null));
}
// A row of a day's whole list and of the phone groups (the master short row).
const calRow = (t, fact, side = null) => ({key:typeof t.key === 'string' ? t.key : '', title:clean(t.title), href:href(t.id), fact, side, dataKey:'cal-row-' + t.id});
const calLateRow = t => calRow(t, [name(t.owner), calWord(t), calWasDue(t)].filter(Boolean).join(' · '), chip('Late', 'danger'));
const calDueRow = t => calRow(t, [name(t.owner), calWord(t), CAL().time(t.due) ? 'Due ' + CAL().time(t.due) : ''].filter(Boolean).join(' · '),
  calTone(t) === 'today' ? chip('Today', 'warning') : null);
const calMore = (day, n) => h('button', {type:'button', className:'btn ghost xs cal-more', 'data-action':'cal-day', 'data-day':day, 'data-key':'cal-more-' + day}, '+' + n + ' more');
const calNumText = day => CAL().num(day) === 1 ? '1 ' + CAL().dayShort(day).split(' ')[2] : String(CAL().num(day));
const calDayHead = (text, isToday) => h('header', {className:'cal-dhead'}, h('span', {className:'cal-num'}, text), isToday ? h('span', {className:'cal-tag'}, 'Today') : null);
// The date beside a day's list (week rows and phone): Fri / 20 / Today.
function calDate(day, plan) {
  const rel = day === plan.today ? 'Today' : day === CAL().add(plan.today, 1) ? 'Tomorrow' : '';
  return h('header', {className:'cal-date'}, h('span', {className:'cal-dow'}, CAL().DOW[CAL().dow(day)]), h('span', {className:'cal-dnum'}, String(CAL().num(day))), rel ? h('span', {className:'cal-rel'}, rel) : null);
}
function calDayBody(d, when) {
  if (when === 'past') return d.items.length ? h('button', {type:'button', className:'btn ghost xs cal-done', 'data-action':'cal-day', 'data-day':d.day, 'data-key':'cal-done-' + d.day}, window.UI.statusIcon('done'), d.items.length + ' done') : null;
  const show = CAL().cut(d.items);
  return [show.map(t => calChip(t, {meta:when !== 'later', at:'m'})), d.items.length > show.length ? calMore(d.day, d.items.length - show.length) : null];
}
const calCell = (d, when) => h('div', {className:'cal-cell', 'data-today':d.today ? '' : null, 'aria-label':CAL().dayLong(d.day), 'data-key':'cal-cell-' + d.day},
  calDayHead(calNumText(d.day), d.today), calDayBody(d, when));
// Saturday and Sunday share one cell.
const calWeekend = (a, b, when) => h('div', {className:'cal-cell cal-we', 'data-today':a.today || b.today ? '' : null, 'aria-label':CAL().dayLong(a.day) + ' and ' + CAL().dayLong(b.day), 'data-key':'cal-cell-' + a.day},
  calDayHead('Sat ' + CAL().num(a.day) + ' · Sun ' + CAL().num(b.day), a.today || b.today), calDayBody(a, when), calDayBody(b, when));
function calMonthGrid(plan) {
  return h('div', {className:'card cal-grid wide-only', 'data-key':'cal-grid'},
    h('div', {className:'cal-head', 'aria-hidden':'true'}, h('span', {}), CAL().DOW.slice(0, 5).map(d => h('span', {}, d)), h('span', {}, 'Weekend')),
    plan.weeks.map(w => h('section', {className:'cal-row', 'data-when':w.when, 'aria-label':w.name, 'data-key':'cal-row-' + w.mon},
      h('button', {type:'button', className:'cal-wk', title:'Show this week', 'data-action':'cal-week', 'data-day':w.mon, 'data-key':'cal-wk-' + w.mon},
        h('strong', {}, w.name), w.name === w.range ? null : h('span', {className:'meta'}, w.range), h('span', {className:'meta'}, w.counts)),
      w.days.slice(0, 5).map(d => calCell(d, w.when)), calWeekend(w.days[5], w.days[6], w.when))));
}
function calWeekRows(plan) {
  const w = plan.weeks[0];
  return h('div', {className:'card cal-drows wide-only', 'data-key':'cal-drows'}, h('p', {className:'cal-drows-h'}, h('strong', {}, w.name + ': '), w.counts),
    w.days.map(d => h('section', {className:'cal-drow', 'data-today':d.today ? '' : null, 'data-none':d.items.length ? null : '', 'aria-label':CAL().dayLong(d.day), 'data-key':'cal-drow-' + d.day},
      calDate(d.day, plan), h('div', {className:'cal-items'}, d.items.length ? d.items.map(calCard) : h('p', {className:'meta cal-none'}, d.all ? 'Nothing else due' : 'Nothing due')))));
}
function calLane(plan) {
  return h('aside', {className:'card cal-lane wide-only', 'aria-label':'Late tickets', 'data-key':'cal-lane'},
    h('header', {className:'card-h'}, h('span', {className:'dot-err', 'aria-hidden':'true'}), h('h2', {}, 'Late'), h('span', {className:'cal-count'}, String(plan.late.length))),
    plan.late.length ? plan.late.map(t => h('a', {className:'cal-late', href:href(t.id), 'data-key':'cal-late-' + t.id},
      h('span', {className:'cal-late-t'}, calKey(t), clean(t.title)), h('span', {className:'cal-late-m'}, h('b', {}, calWasDue(t)), [name(t.owner), calWord(t)].filter(Boolean).map(x => ' · ' + x).join(''))))
      : h('p', {className:'meta cal-lane-none'}, 'Nothing is late.'));
}
const calFolded = (key, start) => calToggled.has(key) ? !start : start;
const calGroup = (key, title, rows, start, icon) => window.UI.shortGroup({key:'cal-g-' + key, title, icon, count:rows.length, folded:calFolded(key, start),
  onToggle:() => { if (calToggled.has(key)) calToggled.delete(key); else calToggled.add(key); render(); }, rows});
// The phone: Late first and open, past weeks folded with counts, then each week with a list per day.
function calPhone(plan) {
  const out = [];
  if (plan.late.length) { const late = calGroup('late', 'Late', plan.late.map(calLateRow), false); late.classList.add('cal-plate'); out.push(late); }
  for (const w of plan.weeks) {
    const days = w.days.filter(d => d.items.length);
    if (w.when === 'past' && plan.mode === 'month') {
      const ts = days.flatMap(d => d.items);
      if (ts.length) out.push(calGroup('w' + w.mon, w.name === w.range ? w.range : w.name + ', ' + w.range, ts.map(t => calRow(t, [name(t.owner), calWord(t), 'Due ' + CAL().dayShort(CAL().dayOf(t.due))].filter(Boolean).join(' · '))), true, 'done'));
      continue;
    }
    out.push(h('div', {className:'cal-pwk', 'data-key':'cal-pwk-' + w.mon}, h('h3', {}, w.name), w.name === w.range ? null : h('span', {className:'meta'}, w.range)));
    out.push(days.length ? h('div', {className:'card cal-pdays', 'data-key':'cal-pdays-' + w.mon}, days.map(d => { const show = CAL().cut(d.items);
      return h('section', {className:'cal-prow', 'data-today':d.today ? '' : null, 'aria-label':CAL().dayLong(d.day), 'data-key':'cal-prow-' + d.day}, calDate(d.day, plan),
        h('div', {className:'cal-plist'}, show.map(t => calChip(t, {word:true, at:'p'})), d.items.length > show.length ? calMore(d.day, d.items.length - show.length) : null)); }))
      : h('p', {className:'meta cal-none', 'data-key':'cal-pnone-' + w.mon}, 'Nothing due'));
  }
  return h('div', {className:'phone-only cal-phone', 'data-key':'cal-phone'}, out);
}
const calPlan = visible => CAL().plan(visible, {now:now(), mode:calMode, day:calDay, statusOf:t => shown(t).status});
function calendarView(visible) {
  const plan = calPlan(visible), unit = plan.mode === 'week' ? 'week' : 'month';
  const step = (dir, label, glyph) => h('button', {type:'button', className:'btn outline icon sm', 'aria-label':label + ' ' + unit, 'data-action':'cal-step', 'data-dir':String(dir), 'data-key':'cal-step-' + dir}, iconEl(glyph));
  const bar = h('div', {className:'cal-bar', 'data-key':'cal-bar'},
    h('div', {className:'cal-nav'}, step(-1, 'Previous', 'chevron-left'), step(1, 'Next', 'chevron-right'), h('button', {type:'button', className:'btn outline sm', 'data-action':'cal-today', 'data-key':'cal-today'}, 'Today')),
    h('h2', {className:'t-sect cal-title', 'aria-live':'polite', 'data-key':'cal-title'}, plan.title), h('span', {className:'grow'}),
    h('div', {className:'view-toggle', role:'group', 'aria-label':'How much to show', 'data-key':'cal-modes'}, [['month', 'Month'], ['week', 'Week']].map(([id, label]) =>
      h('button', {type:'button', className:'btn ghost seg', 'aria-pressed':plan.mode === id, 'data-action':'cal-mode', 'data-mode':id, 'data-key':'cal-mode-' + id}, label))));
  const n = plan.noDue;
  const nodate = n ? h('p', {className:'cal-nodate', 'data-key':'cal-nodate'}, h('span', {}, (n === 1 ? '1 ticket has' : n + ' tickets have') + ' no due date, so ' + (n === 1 ? 'it is' : 'they are') + ' not on the calendar.'),
    h('button', {type:'button', className:'btn ghost sm', 'data-action':'view', 'data-view':'list', 'data-key':'cal-to-list'}, 'Show them in the list')) : null;
  return h('div', {className:'cal-page', 'data-key':'calendar'}, bar,
    h('div', {className:'cal-body', 'data-key':'cal-body'}, calLane(plan), plan.mode === 'week' ? calWeekRows(plan) : calMonthGrid(plan), calPhone(plan)), nodate);
}
// "+N more", a past day's "1 done": that day's whole list in a side sheet (full width on the phone).
function calOpenDay(day) {
  const d = CAL().plan(filteredTickets(), {now:now(), mode:'week', day, statusOf:t => shown(t).status}).weeks[0].days.find(x => x.day === day);
  const ts = d ? d.items : [];
  const list = h('div', {className:'card cal-list'}); ts.forEach(t => list.append(window.UI.shortRow(calDueRow(t))));
  const body = h('div', {className:'cal-daylist'}, h('p', {className:'meta'}, ts.length + (ts.length === 1 ? ' ticket due' : ' tickets due')), list);
  const {d: sheet} = dialog(CAL().dayLong(day), 'sheet');  // the kit adds Close
  sheet.append(body); window.orch.open(sheet);
  body.addEventListener('click', e => { if (e.target.closest('a')) window.orch.close(sheet); });
}
// The calendar's own buttons (app.js hands every data-action click on the Tickets page here first).
function calendarAction(action, control) {
  if (action === 'cal-mode') calMode = control.dataset.mode === 'week' ? 'week' : 'month';
  else if (action === 'cal-today') calDay = '';
  else if (action === 'cal-step') { const at = calDay || today(), next = CAL().step(calMode, at, Number(control.dataset.dir) || 1, today());
    calDay = next === today() || (calMode === 'week' && CAL().monday(next) === CAL().monday(today())) ? '' : next; }
  else if (action === 'cal-week') { const mon = control.dataset.day; calMode = 'week'; calDay = mon === CAL().monday(today()) ? '' : mon; }
  else if (action === 'cal-day') { calOpenDay(control.dataset.day); return true; }
  else return false;
  writeTicketAddress(); render();
  return true;
}
function list() {
  syncTicketAddress();
  const visible = filteredTickets();
  // the needs-you number shows only on the Review badge of the menu (ORCH-1616, owner: less noise)
  const top = [heading('Tickets', 'Every ticket, from Backlog to Done.', {actions:fragment(triageButton())}), viewToggle()];
  if (!visible.length && (ticketSearch || ticketMine || ticketPerson || ticketGroup || savedView())) return fragment(top, window.UI.state({kind:'empty', title:'No tickets match', text:'Try another view or clear the search.', action:{label:'Show all', onClick:clearTicketFilters}}));
  // ORCH-240: the Board on the phone too (lanes side by side, swipe to the next one)
  if (ticketView === 'board' && tickets().length) return fragment(top, h('div', {'data-key':'board-wide'}, board()));
  if (ticketView === 'calendar' && tickets().length) return fragment(top, calendarView(visible));
  return fragment(top, !tickets().length ? h('section', {className:'card tickets-empty', 'data-key':'empty'}, h('h2', {}, 'No tickets yet'),
    h('p', {className:'muted'}, 'Describe a job in plain words. A helper plans it, works on it, asks you when it needs a decision, and shows you the result to check.'),
    h('p', {className:'meta', 'aria-hidden':'true'}, STATUS_CHOICES.map(([, label]) => label).join(' → ')), typeof newButton === 'function' ? newButton() : null) : fragment(ticketTable(visible), window.UI?.shortGroup ? phoneList(visible) : null));
}
// ORCH-151: one helper goes through the tickets of the lanes the person picks (orch triage --start --lanes ...);
// it opens the new Triage ticket. Lane ids and rules match the board lanes and core triage.lane_of.
const TRIAGE_LANES = [['backlog', 'Backlog'], ['todo', 'To do'], ['working', 'Working'], ['needs-you', 'Needs you'], ['waiting', 'Waiting'],
  ['check', 'Check'], ['done', 'Done'], ['wont-do', "Won't do"], ['superseded', 'Superseded']];
const triagePicked = new Set(['backlog', 'todo', 'working', 'needs-you', 'waiting', 'check']);
// The board's own lane rule (DashHelpers.laneOf, ORCH-152), named with the lane ids core triage takes.
const TRIAGE_ID = {open:'backlog', ready:'todo', active:'working', waiting:'needs-you', blocked:'waiting', review:'check', done:'done', dropped:'wont-do', superseded:'superseded'};
function triageLane(t) {
  const asks = (t.questions || []).some(q => q && q.answer == null);
  return TRIAGE_ID[window.DashHelpers.laneOf(t, t.status, asks)] || 'backlog';
}
function triageCounts() {
  const n = Object.fromEntries(TRIAGE_LANES.map(([id]) => [id, 0]));
  for (const t of tickets()) n[triageLane(t)]++;
  return n;
}
const triageTotal = n => [...triagePicked].reduce((sum, id) => sum + (n[id] || 0), 0);
const triageTitle = total => total ? 'Triage · ' + (total === 1 ? '1 ticket' : total + ' tickets') : 'Pick a lane with tickets';
function triageButton() {
  const n = triageCounts();
  if (snapshot || !tickets().length) return null;
  const title = h('strong', {'data-key':'triage-title'}, triageTitle(triageTotal(n)));
  const start = triageStart(); start.disabled = triageStarting || !triageTotal(n);
  const boxes = TRIAGE_LANES.filter(([id]) => n[id]).map(([id, label]) => {
    const box = h('input', {type:'checkbox', 'data-key':'triage-lane-' + id});
    box.checked = triagePicked.has(id);
    box.addEventListener('change', () => {
      if (box.checked) triagePicked.add(id); else triagePicked.delete(id);
      const total = triageTotal(triageCounts());
      title.textContent = triageTitle(total); start.disabled = triageStarting || !total;
    });
    return h('label', {className:'check-label'}, box, label + ' · ' + n[id]);
  });
  // Owner pick 17 Nov (draft B): count and Start triage on one line, lanes in two columns, one short line under.
  // Starting a helper is never a one-click accident (UX D2/M1): the menu says what happens, then Start triage.
  return h('details', {className:'menu', 'data-key':'triage'}, h('summary', {className:'btn outline sm'}, iconEl('spark'), 'Triage'),
    h('div', {className:'menu-pop menu-pop-wide', role:'dialog', 'aria-label':'Triage'},
      h('div', {className:'row between'}, title, start),
      h('div', {className:'grid-2', role:'group', 'aria-label':'Lanes to go through'}, boxes),
      h('p', {className:'meta'}, 'A helper updates, groups and closes them. Each change gets a line.')));
}
function triageStart() {
  const node = button('Start triage', 'outline sm', startTriage);
  node.setAttribute('data-key', 'triage-start'); node.setAttribute('data-keep-open', '');
  if (triageStarting) triageBusy(node, true);  // a redraw while orch opens the ticket keeps the busy look
  return node;
}
// ORCH-1096: the menu stays open and shows the kit's starting moment (UI.launch, as New ticket does; without it the
// button turns into "Starting…" with a spinner) while orch opens the Triage ticket; the page then opens that ticket by id at once and
// starts the helper there, where the ticket says "Getting started…". Starting the helper inside triage.start kept
// the page grey for ~30 s before it moved.
let triageStarting = false;  // kept off the button: a redraw during the request makes a new one
function triageBusy(btn, on) {
  if (!btn) return;
  if (on) {
    btn.setAttribute('aria-busy', 'true'); btn.disabled = true;
    btn.replaceChildren?.(h('span', {className:'spinner', 'aria-hidden':'true'}), 'Starting…');
  } else {
    btn.removeAttribute?.('aria-busy'); btn.disabled = false;
    btn.replaceChildren?.('Start triage');
  }
}
async function startTriage(e) {
  if (typeof changeUnavailable === 'function' && changeUnavailable()) return;
  const lanes = TRIAGE_LANES.map(([id]) => id).filter(id => triagePicked.has(id));
  if (!lanes.length) return;
  if (triageStarting) return;
  triageStarting = true;
  const btn = e?.currentTarget;
  triageBusy(btn, true);
  // The kit's starting moment (UI.launch, the one New ticket shows) in the menu while it is there; else the button alone.
  const pop = btn?.closest?.('.menu-pop'), kids = pop ? [...pop.children] : [];
  const launch = pop && window.UI?.launch ? window.UI.launch({title:'Starting…', sub:triageTitle(triageTotal(triageCounts())), steps:['Making the Triage list', 'Opening it']}) : null;
  if (launch) { kids.forEach(k => { k.hidden = true; }); pop.append(launch.el); }
  const known = new Set(tickets().map(t => t.id));
  let result;
  try { result = await act('triage.start', {lanes}); } finally { triageStarting = false; }
  const now = typeof document === 'object' && document.querySelector?.('[data-key="triage-start"]') || btn;
  triageBusy(now, false);
  if (!result.ok) {
    if (launch) { launch.fail(); kids.forEach(k => { k.hidden = false; }); }
    return window.orch.toast(changeError(result), 'error');
  }
  launch?.step(1);
  now?.closest?.('details')?.removeAttribute('open');
  const id = result.state?.created?.id || tickets().find(t => !known.has(t.id) && String(t.title || '').startsWith('Triage '))?.id;
  if (!id) return window.orch.toast('The Triage ticket is open on the board. Start a helper on it there.', 'ok');
  location.hash = href(id);
  const run = await act('run.start', {ticket:id}, {quiet:true});
  window.orch.toast(run.ok ? 'Triage started: a helper is going through the tickets'
    : run.queued ? 'The Triage ticket is open and waits for a free helper.'
    : 'The Triage ticket is open, but the helper did not start: ' + run.text, run.ok || run.queued ? 'ok' : 'error');
}
function ticketNotFound() {
  return fragment(h('section', {className:'not-found', 'data-key':'not-found'}, iconEl('search'), heading("We couldn't find that ticket", 'It may have been dropped or the link is old.'), h('div', {className:'row ticket-not-found'},
    h('a', {className:'btn primary', href:'#tickets'}, 'Go to Tickets'), snapshot ? null : button('New ticket', 'outline', () => openNewTicket()),
    button('Search', 'outline', () => { location.hash = '#tickets'; render(); document.querySelector('[data-key="ticket-search"]')?.focus(); }))));
}
