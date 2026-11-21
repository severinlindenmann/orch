/* Personal (Preview): Home of tiles, Notes and Add a part. Every text from the workspace or a note is inserted as a
   text node, never as HTML. Reads and clicks go to this add-on's server through the dashboard. */
'use strict';
(() => {
  const prefix = document.documentElement.dataset.prefix || '';
  const $ = id => document.getElementById(id);
  const view = $('view');
  let today = null, notes = null, useFrom = null;

  function el(tag, cls, ...kids) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    for (const k of kids) if (k !== null && k !== undefined) e.append(k instanceof Node ? k : String(k));
    return e;
  }
  function link(href, cls, ...kids) { const a = el('a', cls, ...kids); a.href = href; return a; }
  function button(label, cls, onClick) {
    const b = el('button', cls, label); b.type = 'button'; b.addEventListener('click', onClick); return b;
  }
  function say(text) {
    $('announcement').textContent = text;
    if (window.UI && UI.toast) UI.toast(text);
  }
  function when(iso) {
    if (!iso) return '';
    const d = new Date(iso), now = new Date();
    const hm = d.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'});
    if (d.toDateString() === now.toDateString()) return 'today ' + hm;
    if (now - d < 6 * 864e5) return d.toLocaleDateString([], {weekday: 'short'}) + ' ' + hm;
    return d.toLocaleDateString([], {day: 'numeric', month: 'short'});
  }
  // action: {label, onClick}; the master empty state draws the one button itself
  function state(kind, title, text, action) {
    const host = el('section', 'state-host');
    if (window.UI && UI.state) host.append(UI.state({kind, title, text, action}));
    else host.append(el('p', null, title + (text ? ' ' + text : '')), action ? button(action.label, 'btn primary', action.onClick) : null);
    return host;
  }

  const SIGN_IN = 'Personal is private. Open the dashboard with a sign-in link from orch (run orch start on the computer).';
  const NO_REACH = 'Personal does not answer. Reload the page; if it stays, run orch start.';
  async function read(path) {
    let r;
    try { r = await fetch(prefix + path, {signal: AbortSignal.timeout(15000), credentials: 'same-origin'}); }
    catch (e) { throw new Error(NO_REACH); }
    const body = await r.json().catch(() => null);
    if (r.status === 409 && body && body.error) throw new Error(body.error);
    // 401: the dashboard knows no sign-in in this browser; 403: Personal refused it. Neither is fixed by a reload.
    if (r.status === 401 || r.status === 403) { const e = new Error(SIGN_IN); e.signIn = true; throw e; }
    if (!r.ok || !body) throw new Error('Personal could not be read. Reload the page.');
    return body;
  }
  async function act(op, args) {
    let r;
    try {
      r = await fetch(prefix + '/api/act', {method: 'POST', credentials: 'same-origin',
        headers: {'Content-Type': 'application/json'}, body: JSON.stringify({op, args})});
    } catch (e) { throw new Error(NO_REACH); }
    const body = await r.json().catch(() => null);
    if (!r.ok || !body || body.error) throw new Error((body && body.error) || 'That did not work. Reload the page and try again.');
    return body.result;
  }

  // --- Home ------------------------------------------------------------------------------------------------
  function needsCard(needs) {
    const card = el('section', 'card');
    card.append(el('div', 'card-h', el('h2', null, 'Needs you now'), el('span', 'meta', needs.length + (needs.length === 1 ? ' thing' : ' things'))));
    for (const n of needs) {
      const row = el('div', 'list-row');
      row.append(el('span', 'dot-warn'), el('div', 'grow', el('strong', null, n.title), el('p', 'meta', n.text)));
      row.append(button(n.action, 'btn outline sm', () => openFolder()));
      card.append(row);
    }
    return card;
  }
  function tile(t) {
    const tone = {ok: 'done', empty: 'working', stopped: 'attn'}[t.state] || '';
    const card = el('article', 'card part-tile');
    card.append(el('div', 'card-h', el('h2', null, link('#' + t.part, 'part-tile-link', t.label)), el('span', 'badge ' + tone, t.status)));
    const body = el('div', 'part-tile-body', el('p', 'glance', el('strong', null, t.line), t.changed ? el('span', 'side meta', 'changed ' + when(t.changed)) : null));
    if (t.source) body.append(el('p', 'meta', t.source));
    card.append(body, el('div', 'part-tile-foot meta', 'Helpers can use: ' + t.uses));
    return card;
  }
  function activityCard(rows) {
    const card = el('section', 'card');
    card.append(el('div', 'card-h', el('h2', null, 'What helpers did with it lately'), el('span', 'meta', 'Last 7 days')));
    if (!rows.length) card.append(el('p', 'pad muted', 'Helpers have not used Personal yet.'));
    for (const a of rows) {
      card.append(el('div', 'list-row', el('span', 'meta', when(a.at)), el('span', 'grow', (a.part === 'notes' ? 'Notes: ' : '') + a.what),
        a.ticket_key ? el('span', 'chip', a.ticket_key) : null));
    }
    return card;
  }
  function home() {
    const out = [];
    if (today.needs_you.length) out.push(needsCard(today.needs_you));
    const grid = el('div', 'tile-grid');
    today.parts.forEach(t => grid.append(tile(t)));
    grid.append(link('#parts', 'part-tile-add', el('strong', null, 'Add a part'), el('span', 'meta', 'Meetings, Calendar, Messages and Mail come next')));
    out.push(grid);
    if (!today.parts.length) out.unshift(state('empty', 'Nothing is added yet', 'Add Notes first: your notes folder, with the links between notes.'));
    out.push(activityCard(today.activity));
    out.push(el('p', 'footnote meta', 'Helpers use: orch personal today · They get only what the rules of each part allow.'));
    return out;
  }

  // --- Notes -----------------------------------------------------------------------------------------------
  function ruleSelect(label, help, name, value, words) {
    const sel = el('select', 'input');
    sel.setAttribute('aria-label', label);
    for (const [k, w] of Object.entries(words)) { const o = el('option', null, w); o.value = k; o.selected = k === value; sel.append(o); }
    sel.addEventListener('change', async () => {
      try { await act('rules', {[name]: sel.value}); say('Saved. Helpers follow it from now on.'); today = null; }
      catch (e) { say(e.message); sel.value = value; }
    });
    return el('div', 'rule-row', el('div', null, el('strong', null, label), el('p', 'meta', help)), sel);
  }
  function rulesCard(r) {
    const card = el('section', 'card');
    card.append(el('div', 'card-h', el('h2', null, 'What helpers may do'), el('span', 'meta', 'Changes apply at once')));
    card.append(ruleSelect('Read notes', 'Helpers on a ticket use only what is attached to it, unless you allow all notes.', 'read', r.notes.read, r.read));
    card.append(ruleSelect('Write notes', 'New notes go into the folder “From helpers”; yours are not changed.', 'write', r.notes.write, r.write));
    card.append(el('div', 'rule-row', el('div', null, el('strong', null, 'Delete notes'), el('p', 'meta', 'Only you.')), el('span', 'badge', 'Never')));
    return card;
  }
  function body(text, titles) {
    // [[Target]] / [[Target|alias]] become links to the note; everything else stays plain text
    const p = el('div', 'reading stack-sm');
    for (const para of text.split(/\n{2,}/)) {
      const line = el('p');
      let last = 0;
      for (const m of para.matchAll(/\[\[([^\]\n|#]+)(?:#[^\]\n|]*)?(?:\|([^\]\n]+))?\]\]/g)) {
        line.append(para.slice(last, m.index));
        const target = m[1].trim(), id = Object.keys(titles).find(i => i === target || titles[i].toLowerCase() === target.toLowerCase().split('/').pop());
        line.append(id ? link('#notes/' + encodeURIComponent(id), 'wikilink', m[2] || target) : (m[2] || target));
        last = m.index + m[0].length;
      }
      line.append(para.slice(last));
      p.append(line);
    }
    return p;
  }
  function chips(ids, titles) {
    const row = el('div', 'row');
    if (!ids.length) row.append(el('span', 'meta', 'None'));
    ids.forEach(i => row.append(link('#notes/' + encodeURIComponent(i), 'chip', titles[i] || i)));
    return row;
  }
  async function notePanel(id) {
    const panel = el('article', 'split-panel stack');
    panel.tabIndex = -1;
    let n;
    try { n = await read('/api/note?id=' + encodeURIComponent(id)); }
    catch (e) { panel.append(state('error', 'This note can’t be shown', e.message)); return panel; }
    panel.append(link('#notes', 'btn ghost sm phone-only', 'All notes'));
    panel.append(el('div', 'row between', el('h2', null, n.title), el('span', 'meta', (n.group ? n.group + ' · ' : '') + 'changed ' + when(n.changed))));
    panel.append(body(n.text, n.titles));
    panel.append(el('div', 'grid-2', el('div', 'stack-sm', el('h3', null, 'Links to'), chips(n.links, n.titles)),
      el('div', 'stack-sm', el('h3', null, 'Linked from'), chips(n.linked_from, n.titles))));
    const actions = el('div', 'row');
    actions.append(button('Use in a ticket', 'btn primary', () => openUse(n)));
    if (n.app_link) actions.append(link(n.app_link, 'btn outline', 'Open in my notes app'));
    panel.append(actions);
    const side = el('div', 'card');
    side.append(el('div', 'card-h', el('h3', null, 'On the ticket side'), el('span', 'meta', 'Helpers on a ticket use only what is attached to it')));
    if (!n.tickets.length) side.append(el('p', 'pad muted', 'Not attached to a ticket yet.'));
    n.tickets.forEach(t => side.append(el('div', 'list-row', el('span', 'chip', t), el('span', 'grow meta', 'Attached from Personal: this note'))));
    panel.append(side);
    return panel;
  }
  async function notesScreen(id) {
    let rules;
    try { rules = await read('/api/rules'); } catch (e) { return [state('error', 'Notes can’t be shown', e.message)]; }
    if (!rules.notes || !rules.notes.on) return [state('empty', 'Notes is not added yet', 'Add it to see your notes here.', {label: 'Add Notes', onClick: addNotes})];
    if (!rules.notes.folder) {
      return [state('empty', 'No notes yet', 'Choose the folder with your notes. They show up here with their links, and nothing in the folder is changed.',
        {label: 'Choose folder', onClick: openFolder}), rulesCard(rules)];
    }
    try { notes = await read('/api/notes'); } catch (e) { return [state('error', 'Your notes can’t be read', e.message, {label: 'Choose folder', onClick: openFolder}), rulesCard(rules)]; }
    if (!notes.notes.length) return [state('empty', 'This folder has no notes yet', 'Notes are .md files. Add one in your notes app and reload.'), rulesCard(rules)];
    if (!id && matchMedia('(min-width: 721px)').matches) id = notes.notes[0].id;  // wide: the newest note is open, as in the draft
    const picked = location.hash.startsWith('#notes/');
    const split = el('section', 'split-view');
    if (picked) split.dataset.picked = '';
    const list = el('div', 'split-list card');
    const find = el('input', 'input');
    find.type = 'search'; find.placeholder = 'Find in your notes'; find.setAttribute('aria-label', 'Find in your notes');
    const rows = el('div');
    const paint = items => {
      rows.replaceChildren();
      const groups = {};
      items.forEach(n => (groups[n.group] = groups[n.group] || []).push(n));
      for (const g of Object.keys(groups).sort()) {
        rows.append(el('div', 'card-h', el('h2', null, g || 'Notes')));
        for (const n of groups[g]) {
          const row = el('div', 'list-row' + (n.id === id ? ' cur' : ''));
          const a = link('#notes/' + encodeURIComponent(n.id), 'grow', n.title, el('span', 'subline', when(n.changed) + ' · ' + (n.links.length + n.linked_from.length) + ' links'));
          if (n.id === id) a.setAttribute('aria-current', 'true');
          row.append(a);
          if (n.snippet) row.append(el('span', 'subline', n.snippet));
          rows.append(row);
        }
      }
      if (!items.length) rows.append(el('p', 'pad muted', 'No note has these words.'));
    };
    let timer = null;
    find.addEventListener('input', () => {
      clearTimeout(timer);
      timer = setTimeout(async () => {
        const q = find.value.trim();
        if (!q) return paint(notes.notes);
        try { paint((await read('/api/find?q=' + encodeURIComponent(q))).notes); } catch (e) { say(e.message); }
      }, 200);
    });
    list.append(el('div', 'pad', find), rows);
    paint(notes.notes);
    split.append(list, id ? await notePanel(id) : el('div', 'split-panel muted', 'Pick a note to read it with its links.'));
    return [split, rulesCard(rules), el('p', 'footnote meta', 'Helpers use: orch personal notes find "Helvetia" · Notes are data for helpers, never orders.')];
  }

  // --- Add a part ------------------------------------------------------------------------------------------
  function partRow(title, text, through, right) {
    return el('div', 'list-row', el('div', 'grow', el('strong', null, title), el('p', 'meta', text), through ? el('p', 'meta', 'Connects through: ' + through) : null), right);
  }
  function addScreen() {
    const yours = el('section', 'card');
    yours.append(el('div', 'card-h', el('h2', null, 'Yours')));
    const notesOn = today.parts.some(p => p.part === 'notes');
    yours.append(partRow('Notes', 'Your knowledge as linked notes that helpers can look things up in.', 'the notes folder on this computer',
      notesOn ? el('span', 'badge done', 'On') : button('Add Notes', 'btn primary sm', addNotes)));
    const soon = el('section', 'card');
    soon.append(el('div', 'card-h', el('h2', null, 'Coming next'), el('span', 'meta', 'Through one private connection to your notebook')));
    today.soon.forEach(s => soon.append(partRow(s.label, s.text, null, el('span', 'badge', 'Soon'))));
    const later = el('section', 'card');
    later.append(el('div', 'card-h', el('h2', null, 'Coming later')));
    today.later.forEach(s => later.append(partRow(s.label, s.text, null, el('span', 'badge', 'Later'))));
    return [yours, soon, later, el('p', 'footnote meta', 'A part shows nothing and a helper can use nothing until you add it. Turning one off closes it to helpers; your files stay where they are.')];
  }
  async function addNotes() {
    try { await act('add', {part: 'notes'}); today = null; say('Notes is on. Choose the folder with your notes.'); location.hash = '#notes'; route(); }
    catch (e) { say(e.message); }
  }

  // --- dialogs ---------------------------------------------------------------------------------------------
  function openFolder() { $('folder-error').hidden = true; $('folder-dialog').showModal(); $('folder-path').focus(); }
  $('folder-cancel').addEventListener('click', () => $('folder-dialog').close());
  $('folder-ok').addEventListener('click', async () => {
    const path = $('folder-path').value.trim();
    if (!path) { $('folder-error').textContent = 'Type the folder of your notes.'; $('folder-error').hidden = false; return; }
    try { await act('folder', {path}); $('folder-dialog').close(); today = null; say('Notes reads this folder now.'); location.hash = '#notes'; route(); }
    catch (e) { $('folder-error').textContent = e.message; $('folder-error').hidden = false; }
  });
  async function openUse(n) {
    useFrom = n;
    $('use-what').textContent = 'Note: ' + n.title;
    const box = $('use-tickets');
    box.replaceChildren(el('legend', 'sr-only', 'Pick a ticket'));
    let list = [];
    try { list = (await read('/api/tickets')).tickets; } catch (e) { say(e.message); return; }
    if (!list.length) box.append(el('p', 'muted', 'There is no open ticket. Make one on Tickets first.'));
    list.forEach((t, i) => {
      const r = el('input'); r.type = 'radio'; r.name = 'use-ticket'; r.value = t.id; r.checked = i === 0;
      box.append(el('label', 'list-row', r, el('div', 'grow', el('strong', null, (t.key ? t.key + ' ' : '') + t.title), el('p', 'meta', t.status))));
    });
    $('use-ok').disabled = !list.length;
    $('use-dialog').showModal();
  }
  $('use-cancel').addEventListener('click', () => $('use-dialog').close());
  $('use-ok').addEventListener('click', async () => {
    const pick = document.querySelector('input[name=use-ticket]:checked');
    if (!pick || !useFrom) return;
    try { await act('use', {ticket: pick.value, id: useFrom.id}); $('use-dialog').close(); say('Attached to the ticket.'); route(); }
    catch (e) { say(e.message); }
  });

  // --- router ----------------------------------------------------------------------------------------------
  function nav(current) {
    const box = $('parts-nav');
    box.replaceChildren();
    const items = [['', 'All'], ...today.parts.map(p => [p.part, p.label])];
    items.forEach(([k, label]) => { const a = link('#' + k, null, label); if (current === k) a.setAttribute('aria-current', 'page'); box.append(a); });
    box.hidden = today.parts.length === 0;
  }
  async function route() {
    const start = location.pathname.split('/').pop();  // /addon/personal/notes opens Notes (the dashboard's deep link)
    const h = decodeURIComponent(location.hash.slice(1)) || (['notes', 'parts'].includes(start) ? start : '');
    view.setAttribute('aria-busy', 'true');
    try { if (!today) today = await read('/api/today'); }
    catch (e) {
      view.replaceChildren(e.signIn ? state('empty', 'Sign in to see Personal', e.message) : state('error', 'Personal can’t be shown right now', e.message));
      view.setAttribute('aria-busy', 'false'); return; }
    let out;
    const [screen, ...rest] = h.split('/');
    const head = (title, sub) => { $('page-title').firstChild.textContent = title + ' '; $('page-sub').textContent = sub; };
    if (screen === 'notes') { head('Notes', 'What you and your helpers know, as linked notes. Click a link to follow it.'); out = await notesScreen(rest.join('/') || null); }
    else if (screen === 'parts') { head('Add a part', 'One click adds it. You choose what helpers may do before anything is read.'); out = addScreen(); }
    else { head('Personal', 'What needs you, then each part at a glance. You see everything; helpers use only what you turned on.'); out = home(); }
    $('add-link').hidden = screen === 'parts';
    nav(screen === 'parts' ? null : (screen || ''));
    view.replaceChildren(...out);
    view.setAttribute('aria-busy', 'false');
  }
  addEventListener('hashchange', route);
  route();
})();
