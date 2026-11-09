'use strict';
// Notes page: read-only list of done tickets that say what changed and why. The search text lasts only for this page session.
let notesSearch = '';
// NOTE_LABELS and outcomeOf live in ticket.js (the ticket card uses them too).
function noteTime(t) { return Date.parse(t.updated_at || t.created_at || '') || 0; }
// Done tickets with an outcome, newest first, filtered by the search text, grouped by parent ticket.
// A ticket whose parent is not in the list (or has none) is its own group; groups are ordered by their newest note.
function notesGroups(items, query = '') {
  const needle = String(query || '').trim().toLowerCase();
  const byId = new Map(items.map(t => [t.id, t]));
  const notes = items.filter(t => t.status === 'done' && Object.keys(outcomeOf(t)).length)
    .filter(t => !needle || [t.title, t.key, ...Object.values(outcomeOf(t))].some(v => String(v || '').toLowerCase().includes(needle)))
    .sort((a, b) => noteTime(b) - noteTime(a));
  const groups = [];
  for (const t of notes) {
    const parent = byId.get(t.parent), id = parent ? parent.id : t.id;
    let group = groups.find(g => g.id === id);
    if (!group) groups.push(group = {id, parent:parent || null, notes:[]});
    group.notes.push(t);
  }
  return groups;
}
function noteEntry(t) {
  const o = outcomeOf(t), when = t.updated_at ? window.DashHelpers.stamp(t.updated_at, Date.now()) : '';
  const total = array(t.checklist).length;
  return h('div', {className:'note-entry', 'data-key':'note-' + t.id},
    h('div', {className:'note-head meta'}, [when, h('a', {href:href(t.id)}, clean(t.title)), total ? total + (total === 1 ? ' step' : ' steps') : null].filter(Boolean).flatMap((x, i) => i ? [' · ', x] : [x])),
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
      g.parent ? h('div', {className:'card-h'}, h('h2', {}, 'Step of ', h('a', {href:href(g.parent.id)}, clean(g.parent.title)))) : null,
      g.notes.map(noteEntry))));
}
