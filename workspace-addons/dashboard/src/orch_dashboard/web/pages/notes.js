'use strict';
// Notes page: read-only list of done tickets that say what changed and why. The search text lasts only for this page session.
let notesSearch = '';
// NOTE_LABELS and outcomeOf live in ticket.js (the ticket card uses them too).
// When the ticket was marked done: done_at when the ticket has one, else the last "done" history line, else updated_at.
function doneAt(t) {
  if (typeof t.done_at === 'string' && t.done_at) return t.done_at;
  const event = array(t.history).slice().reverse().find(e => e && (e.kind === 'done' || /(?:->|to) done\b|^Done\b/i.test(e.text || '')));
  return event?.at || t.updated_at || t.created_at || '';
}
function noteTime(t) { return Date.parse(doneAt(t)) || 0; }
// Done tickets with an outcome, newest done first, filtered by the search text, grouped by parent ticket.
// A group is a parent and its sub-tickets: `head` is the parent's own note (when it has one), `notes` the sub-tickets' notes,
// `parent` the parent ticket when the head has no note of its own. A ticket never sits under itself.
// A ticket with no parent is a group of its own. Groups are ordered by their newest note.
function notesGroups(items, query = '') {
  const needle = String(query || '').trim().toLowerCase();
  const byId = new Map(items.map(t => [t.id, t]));
  const notes = items.filter(t => t.status === 'done' && Object.keys(outcomeOf(t)).length)
    .filter(t => !needle || [t.title, t.key, ...Object.values(outcomeOf(t))].some(v => String(v || '').toLowerCase().includes(needle)))
    .sort((a, b) => noteTime(b) - noteTime(a));
  const groups = [];
  for (const t of notes) {
    const parent = byId.get(t.parent), id = parent && parent.id !== t.id ? parent.id : t.id;
    let group = groups.find(g => g.id === id);
    if (!group) groups.push(group = {id, parent:id === t.id ? null : parent, head:null, notes:[]});
    if (id === t.id) { group.head = t; group.parent = null; } else group.notes.push(t);
  }
  return groups;
}
function childCount(t) {
  return window.DashHelpers.childrenOf ? window.DashHelpers.childrenOf(tickets(), t).length : tickets().filter(c => c.id !== t.id && c.parent && (c.parent === t.id || c.parent === t.key)).length;
}
function noteEntry(t) {
  const o = outcomeOf(t), at = doneAt(t), when = at ? window.DashHelpers.stamp(at, Date.now()) : '';
  const steps = childCount(t);
  return h('div', {className:'note-entry', 'data-key':'note-' + t.id},
    h('div', {className:'note-head meta'}, [when, h('a', {href:href(t.id)}, clean(t.title)), steps ? steps + (steps === 1 ? ' step' : ' steps') : null].filter(Boolean).flatMap((x, i) => i ? [' · ', x] : [x])),
    h('dl', {className:'why'}, NOTE_LABELS.filter(([key]) => o[key]).flatMap(([key, label]) => [h('dt', {}, label), h('dd', {}, clean(o[key]))])));
}
function notesPage() {
  const input = h('input', {className:'input', type:'search', placeholder:'Search what changed and why', 'aria-label':'Search notes', 'data-key':'notes-search', value:notesSearch});
  input.addEventListener('input', event => { notesSearch = event.currentTarget.value; render(); });
  const groups = notesGroups(tickets(), notesSearch);
  const anyNotes = tickets().some(t => t.status === 'done' && Object.keys(outcomeOf(t)).length);
  return fragment(heading('Notes', 'What changed and why, from finished tickets.'),
    h('div', {className:'row notes-tools', 'data-key':'notes-tools'}, input),
    !groups.length ? h('p', {className:'card muted notes-empty', 'data-key':'notes-empty'}, anyNotes ? 'No notes match your search.' : 'Finished tickets will show what changed and why here.') : null,
    groups.map(g => h('section', {className:'card notes-group', 'data-key':'notes-' + g.id},
      g.head ? noteEntry(g.head) : null,
      g.parent ? h('div', {className:'card-h'}, h('h2', {}, 'Step of ', h('a', {href:href(g.parent.id)}, clean(g.parent.title)))) : null,
      g.head && g.notes.length ? h('div', {className:'note-steps'}, g.notes.map(noteEntry)) : g.notes.map(noteEntry))));
}
