/* Draft 605c: click-through behaviour only. Text goes in through textContent. */
(() => {
  'use strict';
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const q = new URLSearchParams(location.search);
  const toast = (m, undo) => { if (window.UI && UI.toast) UI.toast(m, undo); };
  const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text) e.textContent = text; return e; };
  const done = (b, text) => { const p = el('span', 'pill done', text); b.replaceWith(p); return p; };

  $$('[data-stub]').forEach(a => a.addEventListener('click', e => { e.preventDefault(); toast(a.dataset.stub + ' is not part of this draft'); }));

  /* To sort: filter by kind (own URL), file, ticket, give */
  const list = $('#sort-list');
  const count = () => {
    if (!list) return;
    const n = $$('[data-item]', list).length;
    $$('[data-count]').forEach(c => { c.textContent = String(n); c.hidden = n === 0; });
    const t = $('[data-count-text]'); if (t) t.textContent = n ? n + ' new' : 'all sorted';
    const empty = $('#sort-empty');
    if (n === 0 && empty && window.UI && UI.state) {
      empty.hidden = false;
      empty.replaceChildren(UI.state({ kind: 'empty', title: 'Nothing to sort', text: 'New calls, mail and chats land here as they come in.', action: { label: 'Open the calendar', onClick: () => { location.href = 'calendar.html'; } } }));
    } else if (empty) empty.hidden = true;
  };
  if (list) {
    const show = q.get('show') || 'all';
    $$('[data-show]').forEach(c => { if (c.dataset.show === show) c.setAttribute('aria-current', 'page'); });
    $$('[data-item]', list).forEach(i => { i.hidden = show !== 'all' && i.dataset.item !== show; });
  }
  $$('[data-file]').forEach(b => b.addEventListener('click', () => {
    const card = b.closest('[data-item]'), next = card.nextSibling, parent = card.parentNode, title = card.dataset.title;
    card.remove(); count();
    toast('"' + title + '" filed under ' + b.dataset.file, () => { parent.insertBefore(card, next); count(); });
  }));
  $$('[data-file-note]').forEach(b => b.addEventListener('click', () => { const t = b.dataset.fileNote; done(b, 'Filed under ' + t); toast('Filed under ' + t); }));
  $$('[data-ticket]').forEach(b => b.addEventListener('click', () => { const t = b.dataset.ticket; done(b, 'Ticket made'); toast('Ticket made: ' + t); }));
  $$('[data-ticket-all]').forEach(b => b.addEventListener('click', () => {
    const open = $$('[data-ticket]', b.closest('section')); open.forEach(x => done(x, 'Ticket made'));
    done(b, '3 tickets made'); toast('3 tickets made from the next steps');
  }));
  $$('[data-give]').forEach(b => b.addEventListener('click', () => { const t = b.dataset.give; const p = el('span', 'pill working', 'With a helper, draft only'); b.replaceWith(p); toast('A helper is drafting for "' + t + '". The draft comes back into this note.'); }));
  /* File under: change the proposed place */
  $$('[data-pick]').forEach(o => o.addEventListener('click', () => {
    const d = o.closest('details'), card = o.closest('[data-item]'), name = o.dataset.pick;
    $('summary', d).textContent = name; d.open = false;
    const why = d.nextElementSibling; if (why) why.textContent = 'your choice';
    const f = $('[data-file]', card); if (f) { f.dataset.file = name; f.hidden = false; }
  }));

  /* Calendar: show or hide a calendar */
  $$('[data-cal-toggle]').forEach(s => s.addEventListener('change', () => {
    $$('[data-cal="' + s.dataset.calToggle + '"]').forEach(e => { e.hidden = !s.checked; });
  }));

  /* Connected tools */
  $$('[data-tool-switch]').forEach(s => s.addEventListener('change', () => {
    const card = s.closest('[data-tool]'); const label = $('[data-onoff]', card);
    if (label) label.textContent = s.checked ? 'On' : 'Off';
    $$('.segmented input', card).forEach(i => { i.disabled = !s.checked; });
    toast(s.dataset.toolSwitch + (s.checked ? ' is on' : ' is off. Helpers no longer see it.'));
  }));
  $$('.segmented input[type=radio]').forEach(i => i.addEventListener('change', () => toast('Saved. Helpers can use: ' + i.parentNode.textContent.trim().toLowerCase())));
  $$('[data-signin]').forEach(b => b.addEventListener('click', () => { const banner = b.closest('[data-needs]'); banner.hidden = true; toast('Signed in. Private mail is coming in again.'); }));
  $$('[data-add]').forEach(b => b.addEventListener('click', () => {
    const name = b.dataset.add;
    if (name === 'Obsidian folder') { location.href = 'empty.html'; return; }
    done(b, 'On'); toast(name + ' added. Change what helpers can use on Connected tools.');
  }));

  /* Helper view: whose context (own URL), log filter (own URL) */
  const who = q.get('for') || 'lea';
  $$('[data-for]').forEach(a => a.setAttribute('aria-pressed', String(a.dataset.for === who)));
  $$('[data-for-panel]').forEach(p => { p.hidden = p.dataset.forPanel !== who; });
  const did = q.get('did') || 'all';
  $$('[data-didf]').forEach(c => { if (c.dataset.didf === did) c.setAttribute('aria-current', 'page'); });
  $$('[data-did]').forEach(r => { r.hidden = did !== 'all' && r.dataset.did !== did; });

  /* Master state and stat builders */
  if (window.UI) {
    const stats = $('#person-stats');
    if (stats && UI.stat) stats.append(UI.stat('Meetings, 30 days', '3'), UI.stat('Mail threads', '4'), UI.stat('Chats', '1'), UI.stat('Open next steps', '2'));
    const empty = $('#empty-state');
    if (empty && UI.state) empty.append(UI.state({ kind: 'empty', title: 'No notes yet', text: 'Notes from your Obsidian folder appear here within a minute of the first read.', action: { label: 'Read the folder now', onClick: () => toast('Reading the folder. 0 of about 320 notes so far.') } }));
    const err = $('#error-state');
    if (err && UI.state) err.append(UI.state({ kind: 'error', title: 'The recorder is not answering', text: 'Your MacBook was last seen today 09:40. Calls are not recorded until it is back. Earlier notes are kept.', action: { label: 'Try again', onClick: () => toast('Still no answer from the recorder. Open it on your Mac.', null, 'error') } }));
  }
})();
