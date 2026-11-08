'use strict';
// Tickets list, tree and board.
const expanded = new Set();
const treeExpanded = new Set(), treeSeen = new Set(), treeAll = new Set(), ticketTabs = new Map();
function treeBranch(rows, index) {
  const row = rows[index], t = row.ticket;
  if (!treeSeen.has(t.id)) { treeSeen.add(t.id); treeExpanded.add(t.id); }
  const open = treeExpanded.has(t.id);
  const children = [];
  for (let i = index + 1; i < rows.length && rows[i].depth > row.depth; i++) {
    if (rows[i].depth === row.depth + 1) children.push(i);
  }
  const late = children.filter(i => rows[i].late);
  return fragment(h('div', {className:'card-row ticket-row' + (row.depth ? ' child' : ''), 'data-key':'tree-' + t.id},
    row.children ? h('button', {type:'button', className:'btn ghost icon sm', 'data-action':'tree', 'data-ticket':t.id, 'aria-expanded':open, 'aria-label':(open ? 'Collapse ' : 'Expand ') + clean(t.title)}, h('span', {className:'chevron ' + (open ? '' : 'closed')}, iconEl('down'))) : null,
    h('div', {className:'grow'}, h('h3', {}, h('a', {href:href(t.id)}, clean(t.title))), h('p', {className:'meta'}, [typeof t.key === 'string' ? t.key : '', row.depth ? statusWord(shown(t)) : '', name(t.owner), t.due ? 'Due ' + date(t.due) : '', row.children ? row.done + ' of ' + row.children + ' done' : '', snapshot ? '' : activityNote(t)].filter(Boolean).join(' · ')), questionLine(t),
      !row.depth && row.parentMissing ? h('p', {className:'meta'}, 'Part of a ticket that is not here') : null), activity(t, 'row'), statusControl(t, 'tree')),
    open ? children.filter(i => !rows[i].late || treeAll.has(t.id)).map(i => treeBranch(rows, i)) : null,
    open && late.length && !treeAll.has(t.id) ? h('div', {className:'card-row child', 'data-key':'tree-all-' + t.id}, h('button', {type:'button', className:'btn ghost sm', 'data-action':'tree-all', 'data-ticket':t.id}, 'Show all ' + children.length)) : null);
}
// List or Board (remembered in this browser only).
let ticketView = 'list';
try { if (localStorage.getItem('orch.tickets.view') === 'board') ticketView = 'board'; } catch (_) { /* no storage: the list */ }
const boardMore = new Set();
let boardCol = null;  // narrow screens: the one column shown; null = the first with tickets
const viewToggle = () => snapshot || !tickets().length ? null : h('div', {className:'board-tools row', 'data-key':'board-tools'},
  h('div', {className:'view-toggle', role:'group', 'aria-label':'How to show tickets'}, [['list', 'List', 'text'], ['board', 'Board', 'table']].map(([id, label, icon]) => h('button', {type:'button', className:'btn ghost seg', 'aria-pressed':ticketView === id, 'data-action':'view', 'data-view':id, 'data-key':'view-' + id}, iconEl(icon), label))),
  ticketView === 'board' ? h('span', {className:'board-hint'}, 'Drag a card to move it, or use its ⋯ menu') : null);
const initials = value => String(name(value) || '').split(/\s+/).filter(Boolean).slice(0, 2).map(w => w[0].toUpperCase()).join('');
// a width through the style object: the page's CSP refuses style attributes
const widthSpan = pct => { const node = h('span', {}); node.style.width = pct + '%'; return node; };
function boardCard(t) {
  const tasks = array(t.checklist), done = tasks.filter(task => task.done).length;
  const who = name(t.owner);
  return h('article', {className:'card ticket-card', draggable:snapshot ? null : 'true', 'data-ticket':t.id, 'data-key':'card-' + t.id},
    h('div', {className:'row'}, h('span', {className:'mono key grow'}, typeof t.key === 'string' ? t.key : ''), null,
      snapshot ? null : h('details', {className:'menu', 'data-key':'card-menu-' + t.id}, h('summary', {className:'btn ghost icon sm move-button', 'aria-label':'Move ' + clean(t.title) + ' to another column'}, iconEl('more')), h('div', {className:'menu-pop', role:'menu'}, statusItems(t, 'card', STATUS_CHOICES)))),
    h('h3', {}, h('a', {href:href(t.id)}, clean(t.title))),
    h('div', {className:'owner-line'}, who ? [h('span', {className:'avatar', 'aria-hidden':'true'}, initials(who)), who] : null, t.due ? h('span', {className:'due' + (overdue(t) ? ' bad' : '')}, date(t.due)) : null),
    questionLine(t), activity(t, 'board'), reviewActions(t), cardLinks(t),
    tasks.length ? h('div', {className:'task-progress'}, h('div', {className:'progress', role:'progressbar', 'aria-valuemin':'0', 'aria-valuemax':String(tasks.length), 'aria-valuenow':String(done), 'aria-label':'Tasks done'}, widthSpan(Math.round(done / tasks.length * 100))), h('span', {className:'meta'}, done + '/' + tasks.length)) : null);
}
const COLUMN_EMPTY = {open:'New tickets show here.', active:'Tickets being worked on show here.', waiting:'Tickets waiting for an answer show here.', review:'Tickets to check show here.', done:'Finished tickets show here.'};
function board() {
  const visible = sorted(tickets().filter(t => t.status !== 'dropped'));
  const counts = {};
  STATUS_CHOICES.forEach(([status]) => { counts[status] = visible.filter(t => window.DashHelpers.columnOf(t.status) === status).length; });
  const shown = boardCol in counts ? boardCol : window.DashHelpers.firstColumnWithTickets(counts);
  const cols = STATUS_CHOICES.map(([status, label]) => {
    const mine = visible.filter(t => window.DashHelpers.columnOf(t.status) === status);
    const cap = status === 'done' && !boardMore.has('done') ? 3 : mine.length;
    return h('section', {className:'kanban-col' + (status === shown ? ' is-shown' : ''), 'data-status':status, 'data-key':'col-' + status, 'aria-label':label + ', ' + mine.length},
      h('div', {className:'col-head'}, h('span', {className:'dot idle'}), h('h2', {}, label), h('span', {className:'status-count'}, String(mine.length))),
      mine.slice(0, cap).map(boardCard), !mine.length ? h('p', {className:'meta board-none'}, COLUMN_EMPTY[status] || 'Nothing here') : null,
      status === 'done' && mine.length > 3 ? h('button', {type:'button', className:'btn ghost sm show-done', 'data-action':'board-more', 'data-key':'board-more'}, boardMore.has('done') ? 'Show fewer' : 'Show ' + (mine.length - 3) + ' more') : null);
  });
  return h('div', {className:'board', 'data-key':'board'},
    h('div', {className:'status-jumps', 'data-key':'status-jumps'}, STATUS_CHOICES.map(([status, label]) => h('button', {type:'button', 'data-action':'board-jump', 'data-status':status, 'aria-pressed':String(status === shown)}, window.DashHelpers.columnChipLabel(label, counts[status])))),
    h('div', {className:'board-track'}, cols));
}
async function moveTicket(id, status) {
  const t = ticketOf(id), lock = 'status-' + id;
  if (!t || t.status === status || locks.has(lock)) return;
  locks.add(lock);
  const result = await act('ticket.patch', {ticket:t.id, data:{status}, if_revision:t.revision});
  locks.delete(lock);
  render();
  const label = STATUS_CHOICES.find(([value]) => value === status)?.[1] || status;
  window.orch.toast(result.ok ? 'Moved to ' + label : result.text + (result.status === 409 ? ' Reload the page and try again.' : ''), result.ok ? 'ok' : 'error');
}
function list() {
  const rows = window.DashHelpers.treeRows(tickets().filter(t => t.status !== 'dropped'));
  if (ticketView === 'board' && tickets().length) return fragment(heading('Tickets'), viewToggle(), board());
  return fragment(heading('Tickets'), viewToggle(), !tickets().length ? card('empty', 'Tickets', '', firstTicket()) : STATUS_CHOICES.map(([status, title]) => {
    const group = rows.map((row, i) => ({row, i})).filter(({row}) => row.depth === 0 && window.DashHelpers.columnOf(row.ticket.status) === status);
    if (!group.length) return null;
    const body = group.map(({i}) => treeBranch(rows, i));
    if (!['done', 'dropped'].includes(status)) return card('group-' + status, title, group.length, body);
    const open = expanded.has(status);
    return h('section', {className:'card', 'data-key':'group-' + status}, h('button', {type:'button', className:'card-h card-toggle', 'data-action':'group', 'data-group':status, 'aria-expanded':open, 'aria-controls':'group-' + status}, h('span', {className:'chevron ' + (open ? '' : 'closed')}, iconEl('down')), h('span', {}, title + ' · ' + group.length)), h('div', {id:'group-' + status, hidden:!open}, body));
  }));
}
