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
  const who = 'who' in over ? over.who : ticketPerson, mode = 'cal' in over ? over.cal : calMode, day = 'day' in over ? over.day : calDay;
  const p = new URLSearchParams();
  if (view) p.set('view', view);
  if (q) p.set('q', q);
  if (who) p.set('who', who);
  if (layout === 'board' || layout === 'calendar') p.set('layout', layout);
  if (layout === 'calendar' && mode === 'week') p.set('cal', 'week');
  if (layout === 'calendar' && day) p.set('day', day);
  const text = p.toString();
  return '#tickets' + (text ? '?' + text : '');
}
let ticketAddressKey = null;
function writeTicketAddress() {
  const next = ticketAddress();
  ticketAddressKey = ticketAddressPart();
  if (typeof history === 'object' && location.hash !== next && (location.hash || '#home').split('?')[0] === '#tickets') history.replaceState(null, '', next);
}
function ticketAddressPart() {
  const full = typeof location === 'object' ? String(location.hash || '') : '', at = full.indexOf('?'), p = new URLSearchParams(at < 0 ? '' : full.slice(at + 1));
  const layout = ['board', 'calendar'].includes(p.get('layout')) ? p.get('layout') : '';
  return (p.get('q') || '') + '|' + (p.get('who') || '') + '|' + layout + (layout === 'calendar' ? '|' + (p.get('cal') || '') + '|' + (p.get('day') || '') : '');
}
function syncTicketAddress() {
  const key = ticketAddressPart();
  if (key === ticketAddressKey) return;
  ticketAddressKey = key;
  const full = String(location.hash || ''), at = full.indexOf('?'), p = new URLSearchParams(at < 0 ? '' : full.slice(at + 1));
  if (ticketSearch !== (p.get('q') || '')) { ticketSearch = p.get('q') || ''; searchFolds.clear(); }
  ticketPerson = p.get('who') || '';
  if (['board', 'calendar'].includes(p.get('layout'))) ticketView = p.get('layout');
  else if (at < 0 || !p.has('layout')) { try { ticketView = storedTicketView(); } catch (_) { ticketView = 'list'; } }
  calMode = p.get('cal') === 'week' ? 'week' : 'month';
  calDay = /^\d{4}-\d{2}-\d{2}$/.test(p.get('day') || '') ? p.get('day') : '';
}
// The layout last picked on this computer: list, board or calendar.
function storedTicketView() { const v = localStorage.getItem('orch.tickets.view'); return v === 'board' || v === 'calendar' ? v : 'list'; }
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
function filterTickets(items, query, mine, me = '', person = '', view = '', group = '') {
  const needle = String(query || '').trim().toLowerCase();
  return items.filter(t => (!mine || (me ? String(t.owner || '') === me : !String(t.owner || '').startsWith('agent:'))) &&
    (!person || String(t.owner || '') === person) && (!group || t.id === group || t.parent === group) && (!view || inView(t, view)) &&
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
function ticketParents(items) {
  return items.map(t => {
    const parent = boardParent(items, t);
    return parent ? {...t, parent:parent.id} : t;
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
const releaseCount = g => g.done + ' of ' + g.total + ' done';
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
function boardParentLine(t) {
  const parent = boardParent(tickets(), t);
  return parent ? h('p', {className:'meta board-parent'}, h('a', {href:href(parent.id)}, (parent.release ? 'Part of the release ' : parent.epic ? 'Part of the epic ' : 'Sub-ticket of ') + clean(parent.title))) : null;
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
function filteredTickets() { return filterTickets(ticketParents(tickets()), ticketSearch, ticketMine, typeof state?.who === 'string' ? state.who : '', ticketPerson, savedView(), ticketGroup); }
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
  const owners = [...new Set(tickets().map(t => String(t.owner || '')).filter(Boolean))].sort();
  const person = owners.length > 1 || ticketPerson ? ticketSelect('Person', 'ticket-person', [['', 'Everyone'], ...owners.map(o => [o, name(o) || o])], ticketPerson, value => { ticketPerson = value; writeTicketAddress(); render(); }) : null;
  const all = tickets(), heads = all.filter(t => all.some(c => c.parent === t.id || (c.parent && c.parent === t.key))).sort((a, b) => String(a.title).localeCompare(String(b.title)));
  const group = heads.length || ticketGroup ? ticketSelect('Part of', 'ticket-group', [['', 'Any ticket'], ...heads.map(t => [t.id, clean(t.title).slice(0, 40)])], ticketGroup, value => { ticketGroup = value; render(); }) : null;
  return [h('span', {className:'grow'}), group, person, h('label', {className:'search-field'}, input)];
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
      h('a', {href:href(t.id)}, window.DashHelpers.keyTag(t, h), clean(t.title)), titleTag(t), helper?.chip || (inRelease ? ticketAttentionChip(t, '') : null)), sub),
    h('td', {className:'due-cell'}, dueCell(t)),
    h('td', {className:'steps'}, stepsCell(t, row)),
    h('td', {className:'numeric spend-cell'}, spendCell(t)),
    h('td', {className:'meta when', title:String(at || '')}, t.quiet_since ? window.DashHelpers.quietWords(t.quiet_since, now()) : at && window.DashHelpers.ago ? (shown(t).status === 'done' ? 'Finished ' : '') + window.DashHelpers.ago(at, Date.now()) : ''),
    h('td', {className:'ticket-actions'}, h('div', {className:'ticket-actions-row'}, ...ticketRowFocus(t, nextAction), ticketMenu(t, 'tree'))));
  node.dataset.depth = String(Math.min(row.depth, 6));
  node.classList.add('row-click');
  node.addEventListener('click', e => { if (!e.target.closest('a,button,select,input,[role="menu"]')) location.hash = href(t.id); });
  return fragment(node, open ? children.map(i => treeBranch(rows, i, section)) : null);
}
const changesLine = t => changesPending(t) ? h('p', {className:'meta changes-pending', 'data-key':'changes-' + t.id}, 'Changes to add') : null;
// A real relative time: when it finished, or when it last changed.
// G2: "No news since 09:20" on a Working ticket quiet for 6 h (the core computes quiet_since).
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
function boardCard(t, nested = false, column = '', here = null) {
  const tasks = array(t.checklist), done = tasks.filter(window.DashHelpers.resolved).length;
  const parts = boardChildren(tickets(), t);
  return h('article', {className:'card ticket-card' + (nested ? ' board-child' : ''), 'data-col':column || null, draggable:snapshot ? null : 'true', 'data-ticket':t.id, 'data-key':'card-' + t.id},
    h('div', {className:'row'}, h('h3', {className:'grow'}, h('a', {href:href(t.id)}, window.DashHelpers.keyTag(t, h), clean(t.title)), titleTag(t)),
      snapshot ? null : h('details', {className:'menu', 'data-key':'card-menu-' + t.id}, h('summary', {className:'btn ghost icon sm move-button', 'aria-label':'Move ' + clean(t.title) + ' to another column'}, iconEl('more')), h('div', {className:'menu-pop', role:'menu'}, statusItems(t, 'card', BOARD_MOVES), laneOrderItems(t, column)))),
    ticketAttentionChip(t, column), waitsLine(t), replacedLine(t),
    !nested ? boardParentLine(t) : null,
    parts.length ? h('div', {className:'board-parts'},
      h('p', {className:'meta'}, (t.release ? 'Release · ' : t.epic ? 'Epic · ' : 'Sub-tickets · ') + parts.filter(c => c.status === 'done').length + ' of ' + parts.length + ' done'),
      parts.filter(part => !(here && here.has(part.id))).map(part => h('a', {className:'board-part', href:href(part.id)}, h('span', {className:'part-title'}, window.DashHelpers.keyTag(part, h), clean(part.title)), ticketAttentionChip(part)))) : null,
    changesLine(t),
    tasks.length ? h('div', {className:'task-progress'}, h('div', {className:'progress', role:'progressbar', 'aria-valuemin':0, 'aria-valuemax':tasks.length, 'aria-valuenow':done, 'aria-label':'Tasks done'}, widthSpan(Math.round(done / tasks.length * 100))), h('span', {className:'meta'}, window.DashHelpers.stepsText(done, tasks.length))) : null,
    ticketNext(t), h('div', {className:'owner-line'}, name(t.owner) ? h('span', {className:'who'}, h('span', {className:'avatar', 'aria-hidden':'true'}, initials(t.owner)), name(t.owner)) : null, t.due ? h('span', {className:'due' + (overdue(t) && String(t.due).includes('T') ? ' bad' : '')}, dueText(t)) : null, quietLine(t), whenLine(t)));
}
const COLUMN_EMPTY = {open:'New tickets land here', ready:'Nothing picked to do next', active:'No helper is working right now', waiting:'No questions for you. All clear',
  blocked:'Nothing waits for a date', review:'Nothing to check', done:'Finished tickets land here', dropped:'Nothing set aside', superseded:'Nothing replaced by another ticket'};
// ORCH-152: the lanes a card can move to from its menu (Needs you comes only from a helper's question).
const BOARD_MOVES = window.DashHelpers.MOVE_CHOICES;
const CAPPED_LANES = ['done', 'dropped', 'superseded'];  // long lanes at the end: 3 cards, then "Show N more"
const boardLane = t => window.DashHelpers.laneOf(t, shown(t).status, questions(t).length > 0);
function board() {
  // Won't do and Superseded tickets are hidden everywhere else; the board shows them in their own lanes.
  const dropped = filterTickets(ticketParents(array(state?.tickets).filter(t => t.status === 'dropped')), ticketSearch, ticketMine, typeof state?.who === 'string' ? state.who : '', ticketPerson, savedView(), ticketGroup);
  const visible = sorted([...filteredTickets(), ...dropped]);
  // ORCH-240: a sub-ticket with its own card anywhere on the board is not listed again inside its parent's card
  // (ORCH-185 did this per lane only). A lane cut short ("Show 3 more") hides cards, so nothing there counts as shown.
  const lanes = window.DashHelpers.LANES.map(([status, label]) => {
    const mine = window.DashHelpers.laneSorted(visible.filter(t => boardLane(t) === status), status);  // ORCH-156: the person's order
    const rows = window.DashHelpers.treeRows(mine), roots = rows.filter(r => !r.depth);
    const capped = CAPPED_LANES.includes(status) && roots.length > 3 && !String(ticketSearch).trim();  // a search shows every hit
    return {status, label, mine, rows, roots, capped, cap:capped && !boardMore.has(status) ? 3 : roots.length};
  }).filter(l => l.mine.length || !['dropped', 'superseded'].includes(l.status));  // ORCH-240: empty set-aside lanes take no room
  const shownHere = new Set(lanes.flatMap(l => l.cap >= l.roots.length ? l.mine.map(t => t.id) : []));
  const cols = lanes.map(({status, label, mine, rows, roots, capped, cap}) => {
    const branch = row => h('div', {className:'board-family', 'data-key':'family-' + row.ticket.id}, boardCard(row.ticket, row.depth > 0, status, shownHere),
      rows.filter(child => child.depth === row.depth + 1 && [row.ticket.id, row.ticket.key].includes(child.ticket.parent)).map(branch));
    return h('section', {className:'kanban-col' + (mine.length ? '' : ' col-collapsed'), 'data-status':status, 'data-key':'col-' + status, 'aria-label':label + ', ' + mine.length},
      h('div', {className:'col-head'}, h('h2', {className:'grow'}, (STATUS_BADGE[status] || STATUS_BADGE.open)[0] + ' ' + label), h('span', {className:'status-count'}, String(mine.length))),
      h('div', {className:'col-body', 'data-key':'col-body-' + status}, roots.slice(0, cap).map(branch), !mine.length ? h('p', {className:'meta board-none', title:COLUMN_EMPTY[status]}, COLUMN_EMPTY[status]) : null,
        capped ? h('button', {type:'button', className:'btn ghost sm show-done', 'data-action':'board-more', 'data-lane':status, 'data-key':'board-more-' + status}, boardMore.has(status) ? 'Show fewer' : 'Show ' + (roots.length - 3) + ' more') : null));
  });
  return h('div', {className:'board', 'data-key':'board'}, h('div', {className:'board-track', title:snapshot ? null : 'Drag a card to move it, or use its ⋯ menu'}, cols));
}
// "Replaced by ORCH-60" on a Superseded card.
function replacedLine(t) {
  if (t.status !== 'dropped' || !t.superseded_by) return null;
  const other = ticketOf(t.superseded_by);
  return h('p', {className:'meta ticket-sub', 'data-key':'replaced-' + t.id}, 'Replaced by ', other ? h('a', {href:href(other.id)}, other.key || clean(other.title)) : 'another ticket');
}
/* ORCH-156: the order inside a lane. The whole lane is sent first to last (every card keeps its place); the cards
   move at once and go back when the save fails. `before`: the card it lands above, null = the end of the lane. */
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
  const ids = laneTickets(lane).map(x => x.id), at = ids.indexOf(t.id);
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
    const n = withQuestions.reduce((sum, t) => sum + questions(t).length, 0);
    return button('Answer ' + n + (n === 1 ? ' question' : ' questions'), 'outline sm group-action', event => {
      const need = needsList().find(x => withQuestions.some(t => t.id === x.ticket));
      if (need) openNeed(need, event.currentTarget); else location.hash = href(withQuestions[0].id);
    });
  }
  if (status === 'review' && group.length) return h('a', {className:'btn outline sm group-action', href:href(group[0].id)}, 'Check ' + group.length + (group.length === 1 ? ' result' : ' results'));
  return null;
}
const searchHead = n => { const q = String(ticketSearch).trim(); return q ? n + (n === 1 ? ' ticket matches “' : ' tickets match “') + q + '”' : 'Ticket · ' + n; };
function ticketTable(visible) {
  const rel = releaseGroups(visible), groups = ticketGroups(visible.filter(t => !rel.inRelease.has(t.id)));
  if (!foldSeen) { foldSeen = true; if ((groups.find(g => g.status === 'done')?.tickets.length || 0) > 5) foldedGroups.add('done'); }
  const body = [];
  releaseFolds(rel.groups);
  for (const group of rel.groups) {
    const status = group.status, rows = window.DashHelpers.treeRows(group.tickets);
    const folds = String(ticketSearch).trim() ? searchFolds : foldedGroups, folded = folds.has(status);
    const toggle = h('button', {type:'button', className:'group-toggle', 'aria-expanded':String(!folded), 'data-key':'group-toggle-' + status}, (folded ? '› ' : '⌄ ') + group.title + ' ', h('span', {className:'meta'}, releaseCount(group)));
    toggle.addEventListener('click', () => { if (folded) folds.delete(status); else folds.add(status); render(); });
    body.push(h('tr', {className:'group-row', 'data-key':'group-' + status}, h('th', {colSpan:6}, h('div', {className:'group-head'}, toggle, folded ? null : releaseOpen(group)))));
    if (!folded) rows.forEach((row, i) => { if (row.depth === 0) body.push(treeBranch(rows, i, status)); });
  }
  for (const status of GROUP_ORDER) {
    const group = groups.find(g => g.status === status), rows = window.DashHelpers.treeRows(group.tickets);
    const roots = rows.map((row, i) => ({row, i})).filter(({row}) => row.depth === 0);
    if (!roots.length) continue;
    // a search shows its hits: every group opens while a search is typed; folding then lasts for that search (ORCH-58)
    const folds = String(ticketSearch).trim() ? searchFolds : foldedGroups;
    const [icon] = STATUS_BADGE[status] || STATUS_BADGE.open, folded = folds.has(status);
    const toggle = h('button', {type:'button', className:'group-toggle', 'aria-expanded':String(!folded), 'data-key':'group-toggle-' + status}, (folded ? '› ' : '⌄ ') + icon + ' ' + group.title + ' ', h('span', {className:'meta'}, String(group.tickets.length)));
    toggle.addEventListener('click', () => { if (folded) folds.delete(status); else folds.add(status); render(); });
    body.push(h('tr', {className:'group-row', 'data-key':'group-' + status}, h('th', {colSpan:6}, h('div', {className:'group-head'}, toggle, groupAction(status, group.tickets, folded)))));
    if (!folded) for (const {i} of roots) body.push(treeBranch(rows, i, status));
  }
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
    if (!roots.length) continue;
    const folds = String(ticketSearch).trim() ? searchFolds : foldedGroups, folded = folds.has(status);
    const shownRows = rows.filter(row => row.depth <= 1), all = phoneMore.has(status), cut = all ? shownRows : shownRows.slice(0, PHONE_ROWS);
    const sec = window.UI.shortGroup({key:'short-' + status, title:isRel ? group.title + ' · ' + releaseCount(group) : group.title, icon:isRel ? (group.finished ? 'done' : 'todo') : SHORT_ICON[status], count:group.tickets.length, folded,
      onToggle:() => { if (folded) folds.delete(status); else folds.add(status); render(); },
      rows:cut.map(row => ({key:typeof row.ticket.key === 'string' ? row.ticket.key : '', title:clean(row.ticket.title), href:href(row.ticket.id), child:row.depth > 0,
        fact:shortFact(row.ticket, isRel ? {...row, parentMissing:false} : row), side:shortSide(row.ticket, row, isRel ? ticketColumn(row.ticket) : status), dataKey:'short-' + row.ticket.id})),
      more:cut.length < shownRows.length ? {label:(shownRows.length - cut.length) + ' more', onClick:() => { phoneMore.add(status); render(); }} : null});
    sec.querySelectorAll('.short-row').forEach(rowEl => rowEl.addEventListener('click', e => {
      if (e.target.closest('a,button')) return;
      const link = rowEl.querySelector('a.short-title'); if (link) location.hash = link.getAttribute('href');
    }));
    sec.querySelector('.card-h button')?.setAttribute('data-key', 'short-toggle-' + status);
    out.push(sec);
  }
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
const calDayHead = (text, isToday) => h('header', {className:'cal-day-h'}, h('span', {className:'cal-num'}, text), isToday ? h('span', {className:'cal-tag'}, 'Today') : null);
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
  return h('div', {className:'card cal-days wide-only', 'data-key':'cal-days'}, h('p', {className:'cal-days-h'}, h('strong', {}, w.name + ': '), w.counts),
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
  const needN = typeof needsYouTotal === 'function' ? needsYouTotal() : 0;
  const pill = needN ? h('span', {className:'badge needs', 'data-key':'needs-pill'}, '● ' + window.DashHelpers.needsYou(needN)) : null;
  const top = [heading('Tickets', 'Every ticket, from Backlog to Done.', {actions:fragment(pill, triageButton())}), viewToggle()];
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
  const start = triageStart(); start.disabled = !triageTotal(n);
  const boxes = TRIAGE_LANES.filter(([id]) => n[id]).map(([id, label]) => {
    const box = h('input', {type:'checkbox', 'data-key':'triage-lane-' + id});
    box.checked = triagePicked.has(id);
    box.addEventListener('change', () => {
      if (box.checked) triagePicked.add(id); else triagePicked.delete(id);
      const total = triageTotal(triageCounts());
      title.textContent = triageTitle(total); start.disabled = !total;
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
  node.setAttribute('data-key', 'triage-start');
  return node;
}
async function startTriage(e) {
  if (typeof changeUnavailable === 'function' && changeUnavailable()) return;
  const lanes = TRIAGE_LANES.map(([id]) => id).filter(id => triagePicked.has(id));
  if (!lanes.length) return;
  const btn = e?.currentTarget; if (btn) btn.disabled = true;
  btn?.closest?.('details')?.removeAttribute('open');
  const known = new Set(tickets().map(t => t.id));
  const result = await act('triage.start', {lanes});
  if (btn) btn.disabled = false;
  if (!result.ok) return window.orch.toast(changeError(result), 'error');
  window.orch.toast('Triage started: a helper is going through the tickets', 'ok');
  const made = tickets().find(t => !known.has(t.id) && String(t.title || '').startsWith('Triage '));
  if (made) location.hash = href(made.id);
}
function ticketNotFound() {
  return fragment(h('section', {className:'not-found', 'data-key':'not-found'}, iconEl('search'), heading("We couldn't find that ticket", 'It may have been dropped or the link is old.'), h('div', {className:'row ticket-not-found'},
    h('a', {className:'btn primary', href:'#tickets'}, 'Go to Tickets'), snapshot ? null : button('New ticket', 'outline', () => ticketForm()),
    button('Search', 'outline', () => { location.hash = '#tickets'; render(); document.querySelector('[data-key="ticket-search"]')?.focus(); }))));
}
