'use strict';
// Tickets list, tree and board. Filter preferences last only for this page session.
const expanded = new Set();
const treeExpanded = new Set(), treeSeen = new Set(), treeAll = new Set(), ticketTabs = new Map();
let ticketSearch = '', ticketMine = false;
function filterTickets(items, query, mine, me = '') {
  const needle = String(query || '').trim().toLowerCase();
  return items.filter(t => (!mine || (me ? String(t.owner || '') === me : !String(t.owner || '').startsWith('agent:'))) &&
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
  const groups = [['waiting', 'Needs you'], ['active', 'Working'], ['open', 'Not started'], ['review', 'Ready for review'], ['done', 'Done']].map(([status, title]) => ({status, title, tickets:[]}));
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
function ticketAttentionChip(t) {
  return questions(t).length && shown(t).status !== 'done' ? chip('Needs you', 'attn') : statusChip(t);
}
function filteredTickets() { return filterTickets(ticketParents(tickets()), ticketSearch, ticketMine, typeof state?.who === 'string' ? state.who : ''); }
function ticketFilters() {
  const input = h('input', {className:'input', type:'search', placeholder:'Search tickets', 'aria-label':'Search tickets', 'data-key':'ticket-search', value:ticketSearch});
  input.addEventListener('input', event => { ticketSearch = event.currentTarget.value; render(); });
  const mine = button('Mine', 'outline sm', () => { ticketMine = !ticketMine; render(); });
  mine.setAttribute('aria-pressed', String(ticketMine)); mine.dataset.key = 'ticket-mine';
  return h('div', {className:'row ticket-filters', 'data-key':'ticket-filters'}, input, mine);
}
function clearTicketFilters() {
  ticketSearch = ''; ticketMine = false;
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
    text = window.DashHelpers.questionPreview(t) || need?.title || 'Answer the question';
    if (!snapshot) {
      action = button('Answer', 'outline sm', event => {
        const current = needsList().find(n => n.ticket === t.id);
        if (current) openNeed(current, event.currentTarget);
        else { ticketTabs.set(t.id, 'questions'); location.hash = href(t.id); }
      });
    }
  } else if (status === 'review') {
    text = 'Read the result'; action = h('a', {className:'btn outline sm', href:href(t.id)}, 'Check result');
  } else if (['open', 'ready'].includes(status) && !state.runs?.[t.id]?.running && !starting.has(t.id)) {
    text = 'Let the helper begin';
    if (!snapshot) action = button('Start helper', 'outline sm', async event => {
      if (changeUnavailable()) return;
      const control = event.currentTarget;
      if (control.disabled) return;
      control.disabled = true;
      const result = await act('run.start', {ticket:t.id});
      control.disabled = false;
      if (!result.ok) window.orch.toast(changeError(result), 'error');
    });
  } else if (status === 'active') {
    const task = array(t.checklist).find(task => !window.DashHelpers.resolved(task));
    text = task?.text || task?.title || '';
  }
  return text || action ? h('div', {className:'row ticket-next'}, text ? h('span', {className:'meta'}, 'Next step: ' + clean(text)) : null, action) : null;
}
function ticketMenu(t, scope) {
  if (snapshot) return null;
  const menu = statusControl(t, scope), summary = menu.querySelector('summary');
  summary.replaceChildren(iconEl('more'));
  summary.className = 'btn ghost icon sm move-button';
  return menu;
}
function treeBranch(rows, index) {
  const row = rows[index], t = row.ticket;
  if (!treeSeen.has(t.id)) { treeSeen.add(t.id); treeExpanded.add(t.id); }
  const open = treeExpanded.has(t.id), children = [];
  for (let i = index + 1; i < rows.length && rows[i].depth > row.depth; i++) if (rows[i].depth === row.depth + 1) children.push(i);
  const tasks = array(t.checklist);
  const node = h('div', {className:'card-row ticket-row' + (row.depth ? ' child' : ''), 'data-key':'tree-' + t.id},
    row.children ? h('button', {type:'button', className:'btn ghost icon sm', 'data-action':'tree', 'data-ticket':t.id, 'aria-expanded':open, 'aria-label':(open ? 'Collapse ' : 'Expand ') + clean(t.title)}, iconEl('down')) : null,
    h('div', {className:'grow'}, h('h3', {}, h('a', {href:href(t.id)}, typeof t.key === 'string' ? h('span', {className:'meta mono'}, t.key + ' ') : null, clean(t.title))), ticketNext(t),
      row.children ? h('p', {className:'meta'}, row.done + ' of ' + row.children + ' steps done') : null,
      row.parentMissing ? parentLine(t) : null),
    h('div', {className:'row ticket-meta'}, ticketAttentionChip(t), tasks.length ? h('span', {className:'meta'}, tasks.filter(window.DashHelpers.resolved).length + '/' + tasks.length) : null,
      name(t.owner) ? h('span', {className:'avatar', title:name(t.owner), 'aria-label':name(t.owner)}, initials(t.owner)) : null,
      t.due ? h('span', {className:'meta'}, date(t.due)) : null, ticketMenu(t, 'tree')));
  node.style.marginLeft = Math.min(row.depth, 6) * 20 + 'px';
  return fragment(node, open ? children.map(i => treeBranch(rows, i)) : null);
}
let ticketView = 'list';
try { if (localStorage.getItem('orch.tickets.view') === 'board') ticketView = 'board'; } catch (_) { /* no storage: the list */ }
const boardMore = new Set();
const viewToggle = () => h('div', {className:'board-tools row', 'data-key':'board-tools'},
  h('div', {className:'view-toggle', role:'group', 'aria-label':'How to show tickets'}, [['list', 'List', 'text'], ['board', 'Board', 'table']].map(([id, label, icon]) => h('button', {type:'button', className:'btn ghost seg', 'aria-pressed':ticketView === id, 'data-action':'view', 'data-view':id, 'data-key':'view-' + id}, iconEl(icon), label))), ticketFilters());
function boardCard(t, nested = false) {
  const tasks = array(t.checklist), done = tasks.filter(window.DashHelpers.resolved).length;
  const parts = boardChildren(tickets(), t);
  return h('article', {className:'card ticket-card' + (nested ? ' board-child' : ''), draggable:snapshot ? null : 'true', 'data-ticket':t.id, 'data-key':'card-' + t.id},
    h('div', {className:'row'}, h('span', {className:'mono key grow'}, typeof t.key === 'string' ? t.key : ''),
      snapshot ? null : h('details', {className:'menu', 'data-key':'card-menu-' + t.id}, h('summary', {className:'btn ghost icon sm move-button', 'aria-label':'Move ' + clean(t.title) + ' to another column'}, iconEl('more')), h('div', {className:'menu-pop', role:'menu'}, statusItems(t, 'card', STATUS_CHOICES)))),
    h('h3', {}, h('a', {href:href(t.id)}, clean(t.title))), ticketAttentionChip(t),
    !nested ? boardParentLine(t) : null,
    parts.length ? h('div', {className:'board-parts'},
      h('p', {className:'meta'}, 'Steps · ' + parts.filter(c => c.status === 'done').length + ' of ' + parts.length + ' done'),
      parts.map(part => h('a', {className:'board-part', href:href(part.id)}, h('span', {className:'mono'}, part.key || ''), h('span', {className:'part-title'}, clean(part.title)), ticketAttentionChip(part)))) : null,
    ticketNext(t), h('div', {className:'owner-line'}, name(t.owner) ? h('span', {className:'avatar', title:name(t.owner), 'aria-label':name(t.owner)}, initials(t.owner)) : null, t.due ? h('span', {className:'due'}, date(t.due)) : null),
    tasks.length ? h('div', {className:'task-progress'}, h('div', {className:'progress', role:'progressbar', 'aria-valuemin':0, 'aria-valuemax':tasks.length, 'aria-valuenow':done, 'aria-label':'Tasks done'}, widthSpan(Math.round(done / tasks.length * 100))), h('span', {className:'meta'}, done + '/' + tasks.length)) : null);
}
const COLUMN_HINT = {open:'Ideas to plan', active:'The agent is on it', waiting:'A question for you', review:'Ready for your look', done:'Finished work'};
function board() {
  const visible = sorted(filteredTickets());
  const cols = STATUS_CHOICES.map(([status, label]) => {
    const mine = visible.filter(t => window.DashHelpers.columnOf(shown(t).status) === status);
    const rows = window.DashHelpers.treeRows(mine), roots = rows.filter(r => !r.depth);
    const cap = status === 'done' && !boardMore.has('done') ? 3 : roots.length;
    const branch = row => h('div', {className:'board-family', 'data-key':'family-' + row.ticket.id}, boardCard(row.ticket, row.depth > 0),
      rows.filter(child => child.depth === row.depth + 1 && [row.ticket.id, row.ticket.key].includes(child.ticket.parent)).map(branch));
    return h('section', {className:'kanban-col', 'data-status':status, 'data-key':'col-' + status, 'aria-label':label + ', ' + mine.length},
      h('div', {className:'col-head'}, h('h2', {className:'grow'}, label), h('span', {className:'status-count'}, String(mine.length))), h('p', {className:'meta column-hint'}, COLUMN_HINT[status]),
      roots.slice(0, cap).map(branch), !mine.length ? h('p', {className:'meta board-none'}, 'Nothing here') : null,
      status === 'done' && roots.length > 3 ? h('button', {type:'button', className:'btn ghost sm show-done', 'data-action':'board-more', 'data-key':'board-more'}, boardMore.has('done') ? 'Show fewer' : 'Show ' + (roots.length - 3) + ' more') : null);
  });
  return h('div', {className:'board', 'data-key':'board'}, snapshot ? null : h('p', {className:'board-hint'}, 'Drag a card to move it, or use its ⋯ menu'), h('div', {className:'board-track'}, cols));
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
function list() {
  const visible = filteredTickets();
  const top = [heading('Tickets'), viewToggle()];
  if (!visible.length && (ticketSearch || ticketMine)) return fragment(top, h('div', {className:'card card-row'}, h('p', {className:'grow'}, 'No tickets match.'), button('Clear', 'outline sm', clearTicketFilters)));
  if (ticketView === 'board' && tickets().length) return fragment(top, board());
  return fragment(top, !tickets().length ? card('empty', 'Tickets', '', firstTicket()) : ticketGroups(visible).map(({status, title, tickets:items}) => {
    const rows = window.DashHelpers.treeRows(items);
    const group = rows.map((row, i) => ({row, i})).filter(({row}) => row.depth === 0);
    if (!group.length) return null;
    const body = group.map(({i}) => treeBranch(rows, i));
    if (status !== 'done') return card('group-' + status, title, items.length, body);
    const open = expanded.has(status);
    return h('section', {className:'card', 'data-key':'group-' + status}, h('button', {type:'button', className:'card-h card-toggle', 'data-action':'group', 'data-group':status, 'aria-expanded':open, 'aria-controls':'group-' + status}, iconEl('down'), h('span', {}, 'Done (' + items.length + ')')), h('div', {id:'group-' + status, hidden:!open}, body));
  }));
}
function ticketNotFound() {
  return fragment(h('section', {className:'not-found', 'data-key':'not-found'}, iconEl('search'), heading("We couldn't find that ticket", 'It may have been dropped or the link is old.'), h('div', {className:'row ticket-not-found'},
    h('a', {className:'btn primary', href:'#tickets'}, 'Go to Tickets'), snapshot ? null : button('New ticket', 'outline', () => ticketForm()),
    button('Search', 'outline', () => { location.hash = '#tickets'; render(); document.querySelector('[data-key="ticket-search"]')?.focus(); }))));
}
