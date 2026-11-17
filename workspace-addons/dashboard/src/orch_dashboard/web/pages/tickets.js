'use strict';
// Tickets list, tree and board. Filter preferences last only for this page session.
const expanded = new Set();
const treeExpanded = new Set(), treeSeen = new Set(), treeAll = new Set(), ticketTabs = new Map();
let ticketSearch = '', ticketMine = false, ticketPerson = '';
// Saved views live on the address: #tickets?view=needs-you|working|done-week.
const TICKET_VIEWS = [['', 'All'], ['needs-you', 'Needs you'], ['working', 'Working'], ['backlog', 'To do'], ['done-week', 'Done this week']];
// Views reached only by a link (Home's "All finished today"), with no chip of their own.
const LINK_VIEWS = [['done-today', 'Finished today']];
function savedView() {
  const full = typeof location === 'object' ? String(location.hash || '') : '', at = full.indexOf('?');
  const view = at < 0 ? '' : new URLSearchParams(full.slice(at + 1)).get('view') || '';
  return [...TICKET_VIEWS, ...LINK_VIEWS].some(([id]) => id && id === view) ? view : '';
}
const changesPending = t => t?.bring_back?.state === 'waiting';
function inView(t, view, nowMs = Date.now()) {
  const status = window.DashHelpers.columnOf(shown(t).status);
  if (view === 'needs-you') return (status !== 'done' && (questions(t).length > 0 || status === 'review')) || changesPending(t);
  if (view === 'working') return status === 'active';
  if (view === 'backlog') return status === 'open';
  if (view === 'done-today') { const at = new Date(t.done_at || t.completed_at || t.updated_at); return status === 'done' && at.toDateString() === new Date(nowMs).toDateString(); }
  if (view === 'done-week') { const at = Date.parse(t.done_at || t.updated_at); return status === 'done' && (!Number.isFinite(at) || nowMs - at <= 7 * 86400000); }
  return true;
}
function filterTickets(items, query, mine, me = '', person = '', view = '') {
  const needle = String(query || '').trim().toLowerCase();
  return items.filter(t => (!mine || (me ? String(t.owner || '') === me : !String(t.owner || '').startsWith('agent:'))) &&
    (!person || String(t.owner || '') === person) && (!view || inView(t, view)) &&
    (!needle || keyMatch(t, needle) || [t.title, /^#?\d+$/.test(needle) ? '' : t.key, t.owner, t.note].some(value => String(value || '').toLowerCase().includes(needle))));
}
// ORCH-58: "58" or "ORCH-58" finds that ticket by its number (exact, so 58 is not ORCH-158); words search the text.
function keyMatch(t, needle) {
  const key = String(t.key || '').toLowerCase(), digits = needle.replace(/^#/, '');
  return !!key && (/^\d+$/.test(digits) ? key.split('-').pop() === String(Number(digits)) : key === needle);
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
const blockedTitle = items => items.filter(ticketWaitsOnly).every(t => t.waiting_on?.kind === 'ticket') ? 'Waiting for another ticket' : 'Waiting';
// "Waits for ORCH-56" under a ticket that waits for another one; "Waits until 18:00" for a time.
function waitsLine(t) {
  if (!ticketWaitsOnly(t)) return null;
  const w = t.waiting_on || {};
  let text = '';
  if (w.kind === 'ticket' && w.ref) { const other = tickets().find(o => o.id === w.ref || (o.key && String(o.key).toLowerCase() === String(w.ref).toLowerCase())); text = 'Waits for ' + (other ? other.key || clean(other.title) : 'another ticket'); }
  else if (w.until) text = 'Waits until ' + (window.UI?.stamp ? window.UI.stamp(w.until) : w.until);
  return text ? h('p', {className:'meta ticket-sub', 'data-key':'waits-' + t.id}, text) : null;
}
function boardParentLine(t) {
  const parent = boardParent(tickets(), t);
  return parent ? h('p', {className:'meta board-parent'}, h('a', {href:href(parent.id)}, (parent.epic ? 'Part of the epic ' : 'Sub-ticket of ') + clean(parent.title))) : null;
}
// `section`: the group or column the row sits in; its own status chip is left out there. Done shows when it finished.
function ticketAttentionChip(t, section) {
  const status = shown(t).status;
  if (questions(t).length && status !== 'done') return section === 'waiting' ? null : chip('Needs you', 'attn');
  if (status === 'done') { const at = (typeof ticketDoneEvent === 'function' ? ticketDoneEvent(t)?.at : null) || t.done_at || t.updated_at; return at ? h('span', {className:'meta ticket-finished'}, 'Finished ' + localDay(at)) : null; }
  if (section && (window.DashHelpers.columnOf(status) === section || ticketGroupOf(t) === section || boardLane(t) === section)) return null;
  return statusChip(t);
}
const localDay = at => window.UI?.stamp ? window.UI.stamp(at, {time:false}) : '';
// A helper worked on it before (sessions) but it is not running now: paused, not new. Typed tasks alone are not.
const ticketIsPaused = t => array(t.sessions).length > 0;
function filteredTickets() { return filterTickets(ticketParents(tickets()), ticketSearch, ticketMine, typeof state?.who === 'string' ? state.who : '', ticketPerson, savedView()); }
// A native select styled with the kit's input class (the kit has no custom select yet).
function ticketSelect(label, key, choices, value, onChange) {
  const select = h('select', {className:'input ticket-select', 'aria-label':label, 'data-key':key}, choices.map(([id, text]) => h('option', {value:id, selected:id === value ? '' : null}, text)));
  select.value = value;
  select.addEventListener('change', event => onChange(event.currentTarget.value));
  return select;
}
// Views as chips on the Tickets page: All, Needs me, Working, Done this week, and the ones saved here.
const SAVED_VIEWS = 'orch.tickets.saved';
function savedViews() { try { const v = JSON.parse(localStorage.getItem(SAVED_VIEWS) || '[]'); return Array.isArray(v) ? v.filter(x => x && typeof x.label === 'string') : []; } catch (_) { return []; } }
function writeSavedViews(list) { try { localStorage.setItem(SAVED_VIEWS, JSON.stringify(list.slice(0, 6))); } catch (_) { /* no storage: nothing is kept */ } }
function applySaved(v) { ticketSearch = v.search || ''; ticketPerson = v.person || ''; ticketMine = false; location.hash = v.view ? '#tickets?view=' + v.view : '#tickets'; render(); }
function viewChips() {
  const current = savedView(), filtered = !!(ticketSearch || ticketPerson);
  const chip = (label, active, attrs) => h('a', Object.assign({className:'chip view-chip' + (active ? ' active' : ''), 'aria-current':active ? 'true' : null}, attrs), label);
  const own = savedViews().map((v, i) => { const c = chip(v.label, false, {href:'#tickets', 'data-key':'saved-view-' + i}); c.addEventListener('click', e => { e.preventDefault(); applySaved(v); }); return c; });
  const label = ticketSearch || (ticketPerson && (name(ticketPerson) || ticketPerson)) || ([...TICKET_VIEWS, ...LINK_VIEWS].find(([id]) => id === current) || [])[1] || '';
  const save = h('button', {type:'button', className:'chip view-chip add', 'data-key':'save-view', disabled:filtered || current ? null : '', 'aria-label':'Save this view'}, '+ Save view');
  save.addEventListener('click', () => { if (!label) return; const list = savedViews().filter(v => v.label !== label); list.push({label, view:current, search:ticketSearch, person:ticketPerson}); writeSavedViews(list); render(); });
  return h('div', {className:'view-chips row', role:'group', 'aria-label':'Ticket views', 'data-key':'view-chips'},
    TICKET_VIEWS.map(([id, text]) => chip(id ? text : 'All', id === current && !filtered, {href:id ? '#tickets?view=' + id : '#tickets', 'data-key':'view-chip-' + (id || 'all')})), own, save);
}
function ticketFilters() {
  const input = h('input', {className:'input', type:'search', placeholder:'Search by number or words', 'aria-label':'Search tickets', 'data-key':'ticket-search', value:ticketSearch});
  input.addEventListener('input', event => { ticketSearch = event.currentTarget.value; searchFolds.clear(); render(); });
  const owners = [...new Set(tickets().map(t => String(t.owner || '')).filter(Boolean))].sort();
  const person = owners.length > 1 || ticketPerson ? ticketSelect('Person', 'ticket-person', [['', 'Everyone'], ...owners.map(o => [o, name(o) || o])], ticketPerson, value => { ticketPerson = value; render(); }) : null;
  return [h('span', {className:'grow'}), person, h('label', {className:'search-field'}, input)];
}
function clearTicketFilters() {
  ticketSearch = ''; ticketMine = false; ticketPerson = '';
  if (savedView()) location.hash = '#tickets';
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
  if (!st || !['idle', 'stuck'].includes(st.state)) return null;
  const mins = Number.isFinite(run?.idle_seconds) ? Math.floor(run.idle_seconds / 60) : null;
  return {chip:window.UI?.helperPill ? window.UI.helperPill(st.state, st.word) : chip(st.word, st.state === 'stuck' ? 'danger' : 'outline'),
    line:st.state === 'idle' ? (mins != null ? 'Nothing running for ' + mins + ' min' : 'Nothing running') : st.detail || ''};
}
// Steps as "3/4" with a bar, always on one line (ORCH-62); "–" when there are none.
function stepsCell(t, row) {
  const tasks = array(t.checklist), total = tasks.length || row.children || 0, done = tasks.length ? tasks.filter(window.DashHelpers.resolved).length : row.done || 0;
  if (!total) return h('span', {className:'meta'}, '–');
  return h('div', {className:'step-progress', title:window.DashHelpers.stepsText(done, total)}, h('div', {className:'progress', role:'progressbar', 'aria-label':'Steps done', 'aria-valuemin':0, 'aria-valuemax':total, 'aria-valuenow':done}, widthSpan(Math.round(done / total * 100))),
    h('span', {className:'meta steps-count'}, done + '/' + total));
}
// One table row (a ticket or a part under its parent). `section` is the group it sits in.
function treeBranch(rows, index, section) {
  const row = rows[index], t = row.ticket;
  if (!treeSeen.has(t.id)) { treeSeen.add(t.id); treeExpanded.add(t.id); }
  const open = treeExpanded.has(t.id), children = [];
  for (let i = index + 1; i < rows.length && rows[i].depth > row.depth; i++) if (rows[i].depth === row.depth + 1) children.push(i);
  const next = ticketNext(t), nextText = next?.querySelector('.meta'), nextAction = next?.querySelector('.btn');
  const helper = helperChip(t);
  const sub = changesLine(t) || waitsLine(t) || (nextText ? h('p', {className:'meta ticket-sub'}, nextText.textContent) : null) || (helper?.line ? h('p', {className:'meta ticket-sub'}, helper.line) : null) || (row.parentMissing ? parentLine(t) : null);
  const at = shown(t).status === 'done' ? t.done_at || t.updated_at : t.updated_at;
  const node = h('tr', {className:'ticket-row' + (row.depth ? ' child' : ''), 'data-key':'tree-' + t.id},
    h('td', {className:'ticket-cell'}, h('div', {className:'ticket-line'},
      row.children ? h('button', {type:'button', className:'btn ghost icon sm', 'data-action':'tree', 'data-ticket':t.id, 'aria-expanded':open, 'aria-label':(open ? 'Collapse ' : 'Expand ') + clean(t.title)}, iconEl('down')) : null,
      h('a', {href:href(t.id)}, window.DashHelpers.keyTag(t, h), clean(t.title)), titleTag(t), helper?.chip), sub),
    h('td', {className:'steps'}, stepsCell(t, row)),
    h('td', {className:'meta when', title:String(at || '')}, t.quiet_since ? window.DashHelpers.quietWords(t.quiet_since, now()) : at && window.DashHelpers.ago ? (shown(t).status === 'done' ? 'Finished ' : '') + window.DashHelpers.ago(at, Date.now()) : ''),
    h('td', {className:'ticket-actions'}, h('div', {className:'ticket-actions-row'}, nextAction, ticketMenu(t, 'tree'))));
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
  const at = shown(t).status === 'done' ? t.done_at || t.updated_at : t.updated_at;
  const text = at && window.DashHelpers.ago ? window.DashHelpers.ago(at, Date.now()) : '';
  return text ? h('span', {className:'meta when', title:String(at)}, text) : null;
}
let ticketView = 'list';
try { if (localStorage.getItem('orch.tickets.view') === 'board') ticketView = 'board'; } catch (_) { /* no storage: the list */ }
const boardMore = new Set();
const viewToggle = () => h('div', {className:'board-toolbar row', 'data-key':'board-tools'}, viewChips(),
  h('div', {className:'view-toggle wide-only', role:'group', 'aria-label':'How to show tickets'}, [['list', 'List', 'text'], ['board', 'Board', 'table']].map(([id, label, icon]) => h('button', {type:'button', className:'btn ghost seg', 'aria-pressed':ticketView === id, 'data-action':'view', 'data-view':id, 'data-key':'view-' + id}, iconEl(icon), label))), ticketFilters());
function boardCard(t, nested = false, column = '') {
  const tasks = array(t.checklist), done = tasks.filter(window.DashHelpers.resolved).length;
  const parts = boardChildren(tickets(), t);
  return h('article', {className:'card ticket-card' + (nested ? ' board-child' : ''), 'data-col':column || null, draggable:snapshot ? null : 'true', 'data-ticket':t.id, 'data-key':'card-' + t.id},
    h('div', {className:'row'}, h('h3', {className:'grow'}, h('a', {href:href(t.id)}, window.DashHelpers.keyTag(t, h), clean(t.title)), titleTag(t)),
      snapshot ? null : h('details', {className:'menu', 'data-key':'card-menu-' + t.id}, h('summary', {className:'btn ghost icon sm move-button', 'aria-label':'Move ' + clean(t.title) + ' to another column'}, iconEl('more')), h('div', {className:'menu-pop', role:'menu'}, statusItems(t, 'card', BOARD_MOVES)))),
    ticketAttentionChip(t, column), waitsLine(t), replacedLine(t),
    !nested ? boardParentLine(t) : null,
    parts.length ? h('div', {className:'board-parts'},
      h('p', {className:'meta'}, (t.epic ? 'Epic · ' : 'Steps · ') + parts.filter(c => c.status === 'done').length + ' of ' + parts.length + ' done'),
      parts.map(part => h('a', {className:'board-part', href:href(part.id)}, h('span', {className:'part-title'}, window.DashHelpers.keyTag(part, h), clean(part.title)), ticketAttentionChip(part)))) : null,
    changesLine(t),
    tasks.length ? h('div', {className:'task-progress'}, h('div', {className:'progress', role:'progressbar', 'aria-valuemin':0, 'aria-valuemax':tasks.length, 'aria-valuenow':done, 'aria-label':'Steps done'}, widthSpan(Math.round(done / tasks.length * 100))), h('span', {className:'meta'}, window.DashHelpers.stepsText(done, tasks.length))) : null,
    ticketNext(t), h('div', {className:'owner-line'}, name(t.owner) ? h('span', {className:'who'}, h('span', {className:'avatar', 'aria-hidden':'true'}, initials(t.owner)), name(t.owner)) : null, t.due ? h('span', {className:'due' + (overdue(t) && String(t.due).includes('T') ? ' bad' : '')}, dueText(t)) : null, quietLine(t), whenLine(t)));
}
const COLUMN_EMPTY = {open:'New tickets land here', ready:'Nothing picked to do next', active:'No helper is working right now', waiting:'No questions for you. All clear',
  blocked:'Nothing waits for a date', review:'Nothing to check', done:'Finished tickets land here', dropped:'Nothing set aside', superseded:'Nothing replaced by another ticket'};
// ORCH-152: the lanes a card can move to from its menu (Needs you comes only from a helper's question).
const BOARD_MOVES = window.DashHelpers.LANES.filter(([lane]) => lane !== 'waiting');
const CAPPED_LANES = ['done', 'dropped', 'superseded'];  // long lanes at the end: 3 cards, then "Show N more"
const boardLane = t => window.DashHelpers.laneOf(t, shown(t).status, questions(t).length > 0);
function board() {
  // Won't do and Superseded tickets are hidden everywhere else; the board shows them in their own lanes.
  const dropped = filterTickets(ticketParents(array(state?.tickets).filter(t => t.status === 'dropped')), ticketSearch, ticketMine, typeof state?.who === 'string' ? state.who : '', ticketPerson, savedView());
  const visible = sorted([...filteredTickets(), ...dropped]);
  const cols = window.DashHelpers.LANES.map(([status, label]) => {
    const mine = visible.filter(t => boardLane(t) === status);
    const rows = window.DashHelpers.treeRows(mine), roots = rows.filter(r => !r.depth);
    const capped = CAPPED_LANES.includes(status) && roots.length > 3 && !String(ticketSearch).trim();  // a search shows every hit
    const cap = capped && !boardMore.has(status) ? 3 : roots.length;
    const branch = row => h('div', {className:'board-family', 'data-key':'family-' + row.ticket.id}, boardCard(row.ticket, row.depth > 0, status),
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
  const done = until => { window.orch.close(d); return moveTicket(t.id, 'waiting', false, {data:{waiting_on:{kind:'time', until:utcStamp(until)}}}); };
  const input = h('input', {className:'input', type:'datetime-local', id:'wait-until-' + t.id, 'data-key':'wait-until'});
  const error = h('p', {className:'meta bad', role:'alert', hidden:true});
  const quick = h('div', {className:'row wrap'}, waitChoices().map(([label, at]) => { const when = window.UI?.stamp ? window.UI.stamp(at) : ''; return button(when ? when.charAt(0).toUpperCase() + when.slice(1) : label, 'outline sm', () => done(at)); }));
  const save = button('Wait', 'primary', () => {
    const at = input.value ? new Date(input.value) : null;
    if (!at || Number.isNaN(at.getTime()) || at <= new Date()) { error.textContent = 'Pick a day and time in the future.'; error.hidden = false; input.focus(); return; }
    done(at);
  });
  actions.append(save);
  d.append(h('div', {className:'stack'}, h('p', {className:'meta'}, clean(t.title)), quick,
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
function moveTicket(id, status, undoing = false, extra = {}) {
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
  const groups = ticketGroups(visible);
  if (!foldSeen) { foldSeen = true; if ((groups.find(g => g.status === 'done')?.tickets.length || 0) > 5) foldedGroups.add('done'); }
  const body = [];
  for (const status of GROUP_ORDER) {
    const group = groups.find(g => g.status === status), rows = window.DashHelpers.treeRows(group.tickets);
    const roots = rows.map((row, i) => ({row, i})).filter(({row}) => row.depth === 0);
    if (!roots.length) continue;
    // a search shows its hits: every group opens while a search is typed; folding then lasts for that search (ORCH-58)
    const folds = String(ticketSearch).trim() ? searchFolds : foldedGroups;
    const [icon] = STATUS_BADGE[status] || STATUS_BADGE.open, folded = folds.has(status);
    const toggle = h('button', {type:'button', className:'group-toggle', 'aria-expanded':String(!folded), 'data-key':'group-toggle-' + status}, (folded ? '› ' : '⌄ ') + icon + ' ' + group.title + ' ', h('span', {className:'meta'}, String(group.tickets.length)));
    toggle.addEventListener('click', () => { if (folded) folds.delete(status); else folds.add(status); render(); });
    body.push(h('tr', {className:'group-row', 'data-key':'group-' + status}, h('th', {colSpan:4}, h('div', {className:'group-head'}, toggle, groupAction(status, group.tickets, folded)))));
    if (!folded) for (const {i} of roots) body.push(treeBranch(rows, i, status));
  }
  return h('div', {className:'table-wrap wide-only', 'data-key':'ticket-table'}, h('table', {className:'ticket-table'},
    h('thead', {}, h('tr', {}, [searchHead(visible.length), 'Steps', 'Last change'].map(label => h('th', {scope:'col'}, label)), h('th', {scope:'col'}, h('span', {className:'sr-only'}, 'Actions')))),
    h('tbody', {}, body)));
}
// Phone (ORCH-73, owner 16 Nov): the same groups as short rows (master UI.shortGroup), never a squeezed table.
// One row: number and title, one fact, one thing on the right (Answer where the person is needed, else steps n/m or an
// Idle/Stuck chip). A group shows its first PHONE_ROWS rows, then "n more".
const PHONE_ROWS = 8, phoneMore = new Set();
const SHORT_ICON = {waiting:'needs', review:'check', active:'working', blocked:'todo', ready:'todo', open:'todo', done:'done'};
function shortFact(t, row) {
  const ago = iso => iso && window.DashHelpers.ago ? window.DashHelpers.ago(iso, Date.now()) : '';
  if (questions(t).length && shown(t).status !== 'done') return 'Question' + (ago(t.updated_at) ? ' · ' + ago(t.updated_at) : '');
  if (changesPending(t)) return 'Changes to add';
  const waits = waitsLine(t)?.textContent;
  if (waits) return waits;
  if (t.quiet_since) return window.DashHelpers.quietWords(t.quiet_since, now());
  const helper = helperChip(t);
  if (helper?.line) return helper.line;
  if (row.parentMissing && typeof parentLine === 'function') { const step = parentLine(t)?.textContent; if (step) return step; }
  const at = shown(t).status === 'done' ? t.done_at || t.updated_at : t.updated_at;
  return (shown(t).status === 'done' && at ? 'Finished ' : '') + ago(at);
}
function shortSide(t, row, status) {
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
  const groups = ticketGroups(visible), out = [];
  for (const status of GROUP_ORDER) {
    const group = groups.find(g => g.status === status), rows = window.DashHelpers.treeRows(group.tickets);
    const roots = rows.filter(row => row.depth === 0);
    if (!roots.length) continue;
    const folds = String(ticketSearch).trim() ? searchFolds : foldedGroups, folded = folds.has(status);
    const shownRows = rows.filter(row => row.depth <= 1), all = phoneMore.has(status), cut = all ? shownRows : shownRows.slice(0, PHONE_ROWS);
    const sec = window.UI.shortGroup({key:'short-' + status, title:group.title, icon:SHORT_ICON[status], count:group.tickets.length, folded,
      onToggle:() => { if (folded) folds.delete(status); else folds.add(status); render(); },
      rows:cut.map(row => ({key:typeof row.ticket.key === 'string' ? row.ticket.key : '', title:clean(row.ticket.title), href:href(row.ticket.id), child:row.depth > 0,
        fact:shortFact(row.ticket, row), side:shortSide(row.ticket, row, status), dataKey:'short-' + row.ticket.id})),
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
function list() {
  const visible = filteredTickets();
  const needN = typeof needsYouTotal === 'function' ? needsYouTotal() : 0;
  const top = [heading('Tickets', 'Every ticket, from Backlog to Done.', {actions:needN ? h('span', {className:'badge needs', 'data-key':'needs-pill'}, '● ' + window.DashHelpers.needsYou(needN)) : null}), viewToggle()];
  if (!visible.length && (ticketSearch || ticketMine || ticketPerson || savedView())) return fragment(top, window.UI.state({kind:'empty', title:'No tickets match', text:'Try another view or clear the search.', action:{label:'Show all', onClick:clearTicketFilters}}));
  if (ticketView === 'board' && tickets().length) return fragment(top, h('div', {className:'wide-only', 'data-key':'board-wide'}, board()), window.UI?.shortGroup ? phoneList(visible) : null);
  return fragment(top, !tickets().length ? h('section', {className:'card tickets-empty', 'data-key':'empty'}, h('h2', {}, 'No tickets yet'),
    h('p', {className:'muted'}, 'Describe a job in plain words. A helper plans it, works on it, asks you when it needs a decision, and shows you the result to check.'),
    h('p', {className:'meta', 'aria-hidden':'true'}, STATUS_CHOICES.map(([, label]) => label).join(' → ')), typeof newButton === 'function' ? newButton() : null) : fragment(ticketTable(visible), window.UI?.shortGroup ? phoneList(visible) : null));
}
function ticketNotFound() {
  return fragment(h('section', {className:'not-found', 'data-key':'not-found'}, iconEl('search'), heading("We couldn't find that ticket", 'It may have been dropped or the link is old.'), h('div', {className:'row ticket-not-found'},
    h('a', {className:'btn primary', href:'#tickets'}, 'Go to Tickets'), snapshot ? null : button('New ticket', 'outline', () => ticketForm()),
    button('Search', 'outline', () => { location.hash = '#tickets'; render(); document.querySelector('[data-key="ticket-search"]')?.focus(); }))));
}
