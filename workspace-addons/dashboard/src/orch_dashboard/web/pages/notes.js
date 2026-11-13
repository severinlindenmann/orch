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
// Done tickets with an outcome, newest done first, filtered by the search text.
function notesList(items, query = '') {
  const needle = String(query || '').trim().toLowerCase();
  return items.filter(t => t.status === 'done' && Object.keys(outcomeOf(t)).length)
    .filter(t => !needle || [t.title, t.key, ...Object.values(outcomeOf(t))].some(v => String(v || '').toLowerCase().includes(needle)))
    .sort((a, b) => noteTime(b) - noteTime(a));
}
// The headline is what changed (or the why when nothing says what); the line under it is the why (or what is left out).
function noteWords(t) {
  const o = outcomeOf(t), first = String(o.changed || o.why || '').split('\n')[0].trim();
  return {headline:first.length > 110 ? first.slice(0, 107) + '...' : first, detail:o.changed ? o.why || o.not_included || '' : o.not_included || ''};
}
const DAY_MS = 86400000;
function noteDay(at, now = Date.now()) {
  const d = new Date(at), n = new Date(now);
  if (!at || Number.isNaN(d.getTime())) return ['Earlier', ''];
  const day = x => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime(), diff = Math.round((day(n) - day(d)) / DAY_MS);
  const long = d.toLocaleDateString(undefined, {day:'numeric', month:'long', ...(d.getFullYear() !== n.getFullYear() ? {year:'numeric'} : {})});
  return [diff === 0 ? 'Today' : diff === 1 ? 'Yesterday' : d.toLocaleDateString(undefined, {weekday:'long'}), long];
}
function noteClock(at) {
  const d = new Date(at);
  return Number.isNaN(d.getTime()) ? '' : String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
}
function noteWho(t) {
  const by = ticketDoneEvent(t)?.by;
  return by ? name(by) : '';
}
const noteLink = t => '#note/' + encodeURIComponent(t.id);
function noteRow(t) {
  const {headline, detail} = noteWords(t), at = doneAt(t), who = noteWho(t), parent = tickets().find(p => p.id === t.parent && p.id !== t.id);
  return h('a', {className:'note-row', href:noteLink(t), 'data-key':'note-' + t.id},
    h('span', {className:'note-thumb', 'aria-hidden':'true'}, h('i'), h('i'), h('i'), h('i')),
    h('span', {className:'grow'}, h('strong', {}, clean(headline)), detail ? h('span', {className:'muted'}, clean(detail)) : null,
      h('span', {className:'meta'}, clean(t.title) + (parent ? ' · Step of ' + clean(parent.title) : ''))),
    h('span', {className:'note-time'}, h('span', {className:'meta'}, [who, noteClock(at)].filter(Boolean).join(' · ')), h('span', {className:'subline'}, 'Open note →')));
}
function notesPage() {
  const input = h('input', {className:'input', type:'search', placeholder:'Search what changed and why', 'aria-label':'Search notes', 'data-key':'notes-search', value:notesSearch});
  input.addEventListener('input', event => { notesSearch = event.currentTarget.value; render(); });
  const notes = notesList(tickets(), notesSearch);
  const anyNotes = tickets().some(t => t.status === 'done' && Object.keys(outcomeOf(t)).length);
  const days = [];
  for (const t of notes) {
    const [label, long] = noteDay(doneAt(t)), last = days[days.length - 1];
    if (last && last.label === label && last.long === long) last.notes.push(t); else days.push({label, long, notes:[t]});
  }
  const count = tickets().filter(t => t.status === 'done' && Object.keys(outcomeOf(t)).length).length;
  return fragment(heading('Notes', 'What changed and why, from finished tickets.'),
    h('div', {className:'row between notes-tools', 'data-key':'notes-tools'}, h('span', {className:'badge'}, count + (count === 1 ? ' note' : ' notes') + ' from finished work'), input),
    !notes.length ? h('section', {className:'card empty state-empty notes-empty', 'data-key':'notes-empty'}, h('span', {className:'file-type', 'aria-hidden':'true'}, '—'),
      h('h2', {}, anyNotes ? 'No notes match your search' : 'No notes from finished work yet'),
      h('p', {}, anyNotes ? 'Try a different word, or clear the search.' : 'Finished tickets can have notes without a summary. Open your finished work to review or add one.'),
      anyNotes ? null : h('a', {className:'btn primary', href:'#tickets'}, 'View finished tickets')) :
    h('div', {className:'note-grid'}, h('div', {className:'stack notes-days'}, days.map(d => h('section', {'data-key':'notes-' + d.label + d.long},
      h('div', {className:'section-head'}, h('h2', {}, d.label), h('span', {className:'meta'}, d.long)), h('div', {className:'card'}, d.notes.map(noteRow))))),
      h('aside', {className:'card context-card'}, h('h2', {}, 'A record of finished work'),
        h('p', {className:'muted'}, 'Notes keep the result close to the ticket: what changed, who changed it and when.'))));
}
// One note on its own page: #note/<ticket id>.
function notePage(t) {
  const back = h('a', {className:'btn outline sm', href:'#notes'}, '← All notes');
  if (!t || t.status !== 'done' || !Object.keys(outcomeOf(t)).length) {
    return fragment(heading('Note not found', '', {actions:back}), h('section', {className:'card empty state-empty', 'data-key':'note-gone'}, h('span', {className:'file-type', 'aria-hidden':'true'}, '—'),
      h('h2', {}, 'This note is no longer available'), h('p', {}, 'Go back to Notes to find another result, or open the source ticket.'),
      h('a', {className:'btn primary', href:'#notes'}, 'Back to Notes')));
  }
  const o = outcomeOf(t), {headline} = noteWords(t), at = doneAt(t), who = noteWho(t);
  const when = at ? window.DashHelpers.stamp(at, Date.now()) : '';
  const rest = NOTE_LABELS.filter(([key]) => o[key] && !(key === 'changed' || (key === 'why' && !o.changed)));
  const log = array(t.history).slice(-4).reverse().map(e => h('li', {}, h('span', {}, clean(e.text || e.kind || 'Update')), h('span', {className:'meta'}, [e.at ? window.DashHelpers.stamp(e.at, Date.now()) : '', e.by ? name(e.by) : ''].filter(Boolean).join(' · '))));
  const copy = h('button', {className:'btn ghost sm', type:'button'}, 'Copy link');
  copy.addEventListener('click', () => window.UI?.copy ? UI.copy(location.href) : null);
  return fragment(heading(headline, 'A note from ' + clean(t.title) + '.', {actions:back}),
    h('div', {className:'note-grid'},
      h('article', {className:'card', 'data-key':'note-' + t.id}, h('header', {className:'card-h'}, h('span', {className:'file-type'}, 'Note'), h('span', {className:'grow'}, [who, when].filter(Boolean).join(' · ')), h('span', {className:'badge done'}, '✓ Finished work')),
        h('div', {className:'document-note'}, h('h2', {}, clean(headline)),
          rest.map(([key, label]) => key === 'why' ? h('div', {}, h('p', {className:'eyebrow'}, label), h('blockquote', {className:'preserve-lines'}, clean(o[key]))) : h('div', {}, h('p', {className:'eyebrow'}, label), h('p', {className:'muted preserve-lines'}, clean(o[key])))),
          h('p', {className:'muted'}, 'From “' + clean(t.title) + '”.')),
        h('div', {className:'preview-actions'}, copy)),
      h('aside', {className:'stack'},
        h('section', {className:'card context-card'}, h('h2', {}, 'Source ticket'), h('a', {className:'plain-link', href:href(t.id)}, clean(t.title) + ' →'),
          h('dl', {className:'detail-list'}, h('div', {}, h('dt', {}, 'Status'), h('dd', {}, h('span', {className:'badge done'}, '✓ Done'))),
            t.owner ? h('div', {}, h('dt', {}, 'Owner'), h('dd', {}, name(t.owner))) : null,
            who ? h('div', {}, h('dt', {}, 'Finished by'), h('dd', {}, [who, when].filter(Boolean).join(' · '))) : null)),
        log.length ? h('section', {className:'card context-card'}, h('h2', {}, 'What happened'), h('ol', {className:'mini-log'}, log)) : null)));
}
