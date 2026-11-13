'use strict';
// Tickets list, tree and board. Filter preferences last only for this page session.
const expanded = new Set();
const treeExpanded = new Set(), treeSeen = new Set(), treeAll = new Set(), ticketTabs = new Map();
let ticketSearch = '', ticketMine = false, ticketPerson = '';
// Saved views live on the address: #tickets?view=needs-you|working|done-week.
const TICKET_VIEWS = [['', 'All tickets'], ['needs-you', 'Needs me'], ['working', 'Working now'], ['done-week', 'Done this week']];
function savedView() {
  const full = typeof location === 'object' ? String(location.hash || '') : '', at = full.indexOf('?');
  const view = at < 0 ? '' : new URLSearchParams(full.slice(at + 1)).get('view') || '';
  return TICKET_VIEWS.some(([id]) => id && id === view) ? view : '';
}
const changesPending = t => t?.bring_back?.state === 'waiting';
function inView(t, view, nowMs = Date.now()) {
  const status = window.DashHelpers.columnOf(shown(t).status);
  if (view === 'needs-you') return (status !== 'done' && (questions(t).length > 0 || ['waiting', 'review'].includes(status))) || changesPending(t);
  if (view === 'working') return status === 'active';
  if (view === 'done-week') { const at = Date.parse(t.done_at || t.updated_at); return status === 'done' && (!Number.isFinite(at) || nowMs - at <= 7 * 86400000); }
  return true;
}
function filterTickets(items, query, mine, me = '', person = '', view = '') {
  const needle = String(query || '').trim().toLowerCase();
  return items.filter(t => (!mine || (me ? String(t.owner || '') === me : !String(t.owner || '').startsWith('agent:'))) &&
    (!person || String(t.owner || '') === person) && (!view || inView(t, view)) &&
    (!needle || [t.title, t.key, t.owner, t.note].some(value => String(value || '').toLowerCase().includes(needle))));
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
function ticketGroups(items) {
  const groups = ['waiting', 'active', 'open', 'review', 'done'].map(status => [status, window.DashHelpers.STATUS_WORD[status]]).map(([status, title]) => ({status, title, tickets:[]}));
  const byId = new Map(items.map(t => [t.id, t]));
  const own = t => { const column = window.DashHelpers.columnOf(shown(t).status); return questions(t).length || column === 'waiting' ? 'waiting' : column; };
  // A part sits under its parent in the parent's group, whatever its own status is (its status chip still says it).
  const rootOf = t => { const seen = new Set(); while (t && byId.has(t.parent) && !seen.has(t.id)) { seen.add(t.id); t = byId.get(t.parent); } return t; };
  for (const t of items) groups.find(group => group.status === own(rootOf(t)))?.tickets.push(t);
  return groups;
}
function boardParentLine(t) {
  const parent = boardParent(tickets(), t);
  return parent ? h('p', {className:'meta board-parent'}, h('a', {href:href(parent.id)}, 'Step of ' + clean(parent.title))) : null;
}
// `section`: the group or column the row sits in; its own status chip is left out there. Done shows when it finished.
function ticketAttentionChip(t, section) {
  const status = shown(t).status;
  if (questions(t).length && status !== 'done') return section === 'waiting' ? null : chip('Needs you', 'attn');
  if (status === 'done') { const at = (typeof ticketDoneEvent === 'function' ? ticketDoneEvent(t)?.at : null) || t.done_at || t.updated_at; return at ? h('span', {className:'meta ticket-finished'}, 'Finished ' + localDay(at)) : null; }
  if (section && window.DashHelpers.columnOf(status) === section) return null;
  return statusChip(t);
}
const localDay = at => { const d = new Date(at); return Number.isFinite(d.getTime()) ? d.toLocaleDateString(undefined, {weekday:'short', day:'numeric', month:'short'}) : ''; };
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
function ticketFilters() {
  const input = h('input', {className:'input', type:'search', placeholder:'Search tickets…', 'aria-label':'Search tickets', 'data-key':'ticket-search', value:ticketSearch});
  input.addEventListener('input', event => { ticketSearch = event.currentTarget.value; render(); });
  const active = TICKET_VIEWS.find(([id]) => id && id === savedView());
  const chipEl = active ? h('a', {className:'chip active view-chip', href:'#tickets', 'data-key':'ticket-view-chip', 'aria-label':'Showing ' + active[1] + '. Show all tickets'}, active[1], ' ✕') : null;
  const owners = [...new Set(tickets().map(t => String(t.owner || '')).filter(Boolean))].sort();
  const person = owners.length > 1 || ticketPerson ? ticketSelect('Person', 'ticket-person', [['', 'Everyone'], ...owners.map(o => [o, name(o) || o])], ticketPerson, value => { ticketPerson = value; render(); }) : null;
  return [chipEl, h('span', {className:'grow'}), person, h('label', {className:'search-field'}, input)];
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
  if (status === 'waiting' || questions(t).length) {
    text = window.DashHelpers.questionPreview(t) || need?.title || '';
    if (!snapshot) {
      action = button('Answer', 'outline sm', event => {
        const current = needsList().find(n => n.ticket === t.id);
        if (current) openNeed(current, event.currentTarget);
        else { ticketTabs.set(t.id, 'questions'); location.hash = href(t.id); }
      });
    }
    if (text) text = 'Next step: ' + text;
  } else if (status === 'review') {
    action = h('a', {className:'btn outline sm', href:href(t.id)}, 'Check result');
  } else if (['open', 'ready'].includes(status) && !state.runs?.[t.id]?.running && !starting.has(t.id)) {
    const paused = ticketIsPaused(t);
    if (paused) text = 'Paused' + (t.updated_at ? ' ' + localDay(t.updated_at) : '');
    if (!snapshot) action = button(paused ? 'Resume' : 'Start helper', 'outline sm', async event => {
      if (changeUnavailable()) return;
      const control = event.currentTarget;
      if (control.disabled) return;
      control.disabled = true;
      const result = await act('run.start', {ticket:t.id});
      control.disabled = false;
      if (!result.ok) window.orch.toast(changeError(result), 'error');
    });
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
// Status badge of a table row: icon + the shared word (To do, Working, Needs you, Check, Done).
const STATUS_BADGE = {open:['○', 'todo'], active:['◉', 'working'], waiting:['!', 'needs'], review:['◇', 'review'], done:['✓', 'done']};
function ticketColumn(t) { const status = shown(t).status; return questions(t).length && status !== 'done' ? 'waiting' : window.DashHelpers.columnOf(status); }
function statusBadge(t) {
  const column = ticketColumn(t), [icon, cls] = STATUS_BADGE[column] || STATUS_BADGE.open;
  return h('span', {className:'badge ' + cls}, icon + ' ' + (window.DashHelpers.STATUS_WORD[column] || column));
}
function stepsCell(t, row) {
  const tasks = array(t.checklist), total = tasks.length || row.children || 0, done = tasks.length ? tasks.filter(window.DashHelpers.resolved).length : row.done || 0;
  if (ticketColumn(t) === 'waiting') return h('span', {className:'meta'}, 'Question for you');
  if (!total) return h('span', {className:'meta'}, '–');
  return h('div', {className:'step-progress'}, h('div', {className:'progress', role:'progressbar', 'aria-label':'Steps done', 'aria-valuemin':0, 'aria-valuemax':total, 'aria-valuenow':done}, widthSpan(Math.round(done / total * 100))),
    h('span', {className:'meta'}, window.DashHelpers.stepsText(done, total)));
}
// One table row (a ticket or a part under its parent). `section` is the group it sits in.
function treeBranch(rows, index, section) {
  const row = rows[index], t = row.ticket;
  if (!treeSeen.has(t.id)) { treeSeen.add(t.id); treeExpanded.add(t.id); }
  const open = treeExpanded.has(t.id), children = [];
  for (let i = index + 1; i < rows.length && rows[i].depth > row.depth; i++) if (rows[i].depth === row.depth + 1) children.push(i);
  const next = ticketNext(t), nextText = next?.querySelector('.meta'), nextAction = next?.querySelector('.btn');
  const sub = changesLine(t) || (nextText ? h('p', {className:'meta ticket-sub'}, nextText.textContent) : null) || (row.parentMissing ? parentLine(t) : null);
  const at = shown(t).status === 'done' ? t.done_at || t.updated_at : t.updated_at;
  const node = h('tr', {className:'ticket-row' + (row.depth ? ' child' : ''), 'data-key':'tree-' + t.id},
    h('td', {className:'ticket-cell'}, h('div', {className:'ticket-line'},
      row.children ? h('button', {type:'button', className:'btn ghost icon sm', 'data-action':'tree', 'data-ticket':t.id, 'aria-expanded':open, 'aria-label':(open ? 'Collapse ' : 'Expand ') + clean(t.title)}, iconEl('down')) : null,
      h('a', {href:href(t.id)}, clean(t.title)), titleTag(t)), sub),
    h('td', {}, statusBadge(t)),
    h('td', {}, name(t.owner) ? h('span', {className:'who'}, h('span', {className:'avatar', 'aria-hidden':'true'}, initials(t.owner)), name(t.owner)) : h('span', {className:'meta'}, '–')),
    h('td', {}, stepsCell(t, row)),
    h('td', {className:'meta when', title:String(at || '')}, at && window.DashHelpers.ago ? (shown(t).status === 'done' ? 'Finished ' : '') + window.DashHelpers.ago(at, Date.now()) : ''),
    h('td', {className:'ticket-actions'}, h('div', {className:'ticket-actions-row'}, nextAction, ticketMenu(t, 'tree'))));
  node.dataset.depth = String(Math.min(row.depth, 6));
  return fragment(node, open ? children.map(i => treeBranch(rows, i, section)) : null);
}
const changesLine = t => changesPending(t) ? h('p', {className:'meta changes-pending', 'data-key':'changes-' + t.id}, 'Changes to add') : null;
// A real relative time: when it finished, or when it last changed.
function whenLine(t) {
  const at = shown(t).status === 'done' ? t.done_at || t.updated_at : t.updated_at;
  const text = at && window.DashHelpers.ago ? window.DashHelpers.ago(at, Date.now()) : '';
  return text ? h('span', {className:'meta when', title:String(at)}, text) : null;
}
let ticketView = 'list';
try { if (localStorage.getItem('orch.tickets.view') === 'board') ticketView = 'board'; } catch (_) { /* no storage: the list */ }
const boardMore = new Set();
const viewToggle = () => h('div', {className:'board-toolbar row', 'data-key':'board-tools'},
  h('div', {className:'view-toggle', role:'group', 'aria-label':'How to show tickets'}, [['list', 'List', 'text'], ['board', 'Board', 'table']].map(([id, label, icon]) => h('button', {type:'button', className:'btn ghost seg', 'aria-pressed':ticketView === id, 'data-action':'view', 'data-view':id, 'data-key':'view-' + id}, iconEl(icon), label))), ticketFilters());
function boardCard(t, nested = false, column = '') {
  const tasks = array(t.checklist), done = tasks.filter(window.DashHelpers.resolved).length;
  const parts = boardChildren(tickets(), t);
  return h('article', {className:'card ticket-card' + (nested ? ' board-child' : ''), draggable:snapshot ? null : 'true', 'data-ticket':t.id, 'data-key':'card-' + t.id},
    h('div', {className:'row'}, h('h3', {className:'grow'}, h('a', {href:href(t.id)}, clean(t.title)), titleTag(t)),
      snapshot ? null : h('details', {className:'menu', 'data-key':'card-menu-' + t.id}, h('summary', {className:'btn ghost icon sm move-button', 'aria-label':'Move ' + clean(t.title) + ' to another column'}, iconEl('more')), h('div', {className:'menu-pop', role:'menu'}, statusItems(t, 'card', STATUS_CHOICES)))),
    ticketAttentionChip(t, column),
    !nested ? boardParentLine(t) : null,
    parts.length ? h('div', {className:'board-parts'},
      h('p', {className:'meta'}, 'Steps · ' + parts.filter(c => c.status === 'done').length + ' of ' + parts.length + ' done'),
      parts.map(part => h('a', {className:'board-part', href:href(part.id)}, h('span', {className:'part-title'}, clean(part.title)), ticketAttentionChip(part)))) : null,
    changesLine(t),
    tasks.length ? h('div', {className:'task-progress'}, h('div', {className:'progress', role:'progressbar', 'aria-valuemin':0, 'aria-valuemax':tasks.length, 'aria-valuenow':done, 'aria-label':'Steps done'}, widthSpan(Math.round(done / tasks.length * 100))), h('span', {className:'meta'}, window.DashHelpers.stepsText(done, tasks.length))) : null,
    ticketNext(t), h('div', {className:'owner-line'}, name(t.owner) ? h('span', {className:'who'}, h('span', {className:'avatar', 'aria-hidden':'true'}, initials(t.owner)), name(t.owner)) : null, t.due ? h('span', {className:'due'}, date(t.due)) : null, whenLine(t)));
}
const COLUMN_EMPTY = {open:'Nothing to start', active:'No helper is working right now', waiting:'No questions for you. All clear', review:'Nothing to check', done:'Finished tickets land here'};
function board() {
  const visible = sorted(filteredTickets());
  const cols = STATUS_CHOICES.map(([status, label]) => {
    const mine = visible.filter(t => window.DashHelpers.columnOf(shown(t).status) === status);
    const rows = window.DashHelpers.treeRows(mine), roots = rows.filter(r => !r.depth);
    const cap = status === 'done' && !boardMore.has('done') ? 3 : roots.length;
    const branch = row => h('div', {className:'board-family', 'data-key':'family-' + row.ticket.id}, boardCard(row.ticket, row.depth > 0, status),
      rows.filter(child => child.depth === row.depth + 1 && [row.ticket.id, row.ticket.key].includes(child.ticket.parent)).map(branch));
    return h('section', {className:'kanban-col', 'data-status':status, 'data-key':'col-' + status, 'aria-label':label + ', ' + mine.length},
      h('div', {className:'col-head'}, h('h2', {className:'grow'}, (STATUS_BADGE[status] || STATUS_BADGE.open)[0] + ' ' + label), h('span', {className:'status-count'}, String(mine.length))),
      h('div', {className:'col-body', 'data-key':'col-body-' + status}, roots.slice(0, cap).map(branch), !mine.length ? h('p', {className:'meta board-none'}, COLUMN_EMPTY[status]) : null,
        status === 'done' && roots.length > 3 ? h('button', {type:'button', className:'btn ghost sm show-done', 'data-action':'board-more', 'data-key':'board-more'}, boardMore.has('done') ? 'Show fewer' : 'Show ' + (roots.length - 3) + ' more') : null));
  });
  return h('div', {className:'board', 'data-key':'board'}, h('div', {className:'board-track', title:snapshot ? null : 'Drag a card to move it, or use its ⋯ menu'}, cols));
}
const movePending = new Map();
// Optimistic: the card moves and the notice (with Undo) shows at once; a failed save puts the card back.
// `extra`: more arguments of the change (Accept on a ticket in Review sends the review tip it showed).
function moveTicket(id, status, undoing = false, extra = {}) {
  if (status === 'done' && !extra.review_tip) extra = {...extra, review_tip:'none'}; // this view showed no review tip
  const t = ticketOf(id), lock = 'status-' + id;
  if (!t || t.status === status || snapshot || locks.has(lock) || changeUnavailable()) return Promise.resolve();
  const previous = t.status, revision = t.revision;
  locks.add(lock);
  const set = value => { state.tickets = state.tickets.map(x => x.id === id ? {...x, status:value} : x); };
  document.querySelectorAll('[data-key="ticket-' + id + '"],[data-key="family-' + id + '"]').forEach(n => n.classList.add('status-leaving'));
  set(status);
  const unfade = () => document.querySelectorAll('.status-leaving').forEach(n => n.classList.remove('status-leaving'));
  const fade = new Promise(resolve => setTimeout(resolve, matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 160)).then(() => { unfade(); render(); });
  const label = STATUS_CHOICES.find(([value]) => value === status)?.[1] || status;
  const toast = window.orch.toast(undoing ? 'Moved back' : 'Moved to ' + label, 'ok');
  if (!undoing && toast?.querySelector) {
    const undo = h('button', {type:'button', className:'btn ghost sm', 'data-action':'undo-move'}, 'Undo');
    undo.addEventListener('click', async () => { toast.remove(); await movePending.get(id); moveTicket(id, previous, true); });
    toast.querySelector('button[aria-label="Dismiss notification"]')?.before(undo);
  }
  const run = (async () => {
    let result;
    try { result = await actRetry('ticket.patch', () => ({...extra, ticket:id, data:{status}, if_revision:(ticketOf(id) || t).revision || revision}), () => { const now = ticketOf(id); return !!now && now.status === previous; }); }
    catch (err) { result = {ok:false, status:0, text:String(err?.message || err)}; }
    await fade;
    locks.delete(lock);
    if (!result.ok) { set(previous); toast?.remove?.(); window.orch.toast(changeError(result), 'error'); }
    unfade();
    render();
  })();
  movePending.set(id, run);
  run.finally(() => { if (movePending.get(id) === run) movePending.delete(id); });
  return run;
}
const GROUP_ORDER = ['waiting', 'review', 'active', 'open', 'done'];
const foldedGroups = new Set();
let foldSeen = false;
function ticketTable(visible) {
  const groups = ticketGroups(visible);
  if (!foldSeen) { foldSeen = true; if ((groups.find(g => g.status === 'done')?.tickets.length || 0) > 5) foldedGroups.add('done'); }
  const body = [];
  for (const status of GROUP_ORDER) {
    const group = groups.find(g => g.status === status), rows = window.DashHelpers.treeRows(group.tickets);
    const roots = rows.map((row, i) => ({row, i})).filter(({row}) => row.depth === 0);
    if (!roots.length) continue;
    const [icon] = STATUS_BADGE[status] || STATUS_BADGE.open, folded = foldedGroups.has(status);
    const toggle = h('button', {type:'button', className:'group-toggle', 'aria-expanded':String(!folded), 'data-key':'group-toggle-' + status}, (folded ? '› ' : '⌄ ') + icon + ' ' + group.title + ' ', h('span', {className:'meta'}, String(group.tickets.length)));
    toggle.addEventListener('click', () => { if (foldedGroups.has(status)) foldedGroups.delete(status); else foldedGroups.add(status); render(); });
    body.push(h('tr', {className:'group-row', 'data-key':'group-' + status}, h('th', {colSpan:6}, toggle)));
    if (!folded) for (const {i} of roots) body.push(treeBranch(rows, i, status));
  }
  return h('div', {className:'table-wrap', 'data-key':'ticket-table'}, h('table', {className:'ticket-table'},
    h('thead', {}, h('tr', {}, ['Ticket · ' + visible.length, 'Status', 'Owner', 'Steps done', 'Last change'].map(label => h('th', {scope:'col'}, label)), h('th', {scope:'col'}, h('span', {className:'sr-only'}, 'Actions')))),
    h('tbody', {}, body)));
}
function list() {
  const visible = filteredTickets();
  const needN = typeof needsYouTotal === 'function' ? needsYouTotal() : 0;
  const top = [heading('Tickets', 'Every ticket, from To do to Done.', {actions:needN ? h('span', {className:'badge needs', 'data-key':'needs-pill'}, '● ' + window.DashHelpers.needsYou(needN)) : null}), viewToggle()];
  if (!visible.length && (ticketSearch || ticketMine || ticketPerson || savedView())) return fragment(top, h('div', {className:'card card-row'}, h('p', {className:'grow'}, 'No tickets match.'), button('Clear', 'outline sm', clearTicketFilters)));
  if (ticketView === 'board' && tickets().length) return fragment(top, board());
  return fragment(top, !tickets().length ? h('section', {className:'card tickets-empty', 'data-key':'empty'}, h('h2', {}, 'No tickets yet'),
    h('p', {className:'muted'}, 'Describe a job in plain words. A helper plans it, works on it, asks you when it needs a decision, and shows you the result to check.'),
    h('p', {className:'meta', 'aria-hidden':'true'}, STATUS_CHOICES.map(([, label]) => label).join(' → ')), typeof newButton === 'function' ? newButton() : null) : ticketTable(visible));
}
function ticketNotFound() {
  return fragment(h('section', {className:'not-found', 'data-key':'not-found'}, iconEl('search'), heading("We couldn't find that ticket", 'It may have been dropped or the link is old.'), h('div', {className:'row ticket-not-found'},
    h('a', {className:'btn primary', href:'#tickets'}, 'Go to Tickets'), snapshot ? null : button('New ticket', 'outline', () => ticketForm()),
    button('Search', 'outline', () => { location.hash = '#tickets'; render(); document.querySelector('[data-key="ticket-search"]')?.focus(); }))));
}
