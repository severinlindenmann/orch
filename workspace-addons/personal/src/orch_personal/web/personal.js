/* Personal (Preview): Home of tiles, Notes, Meetings and Add a part. Every text from the workspace or a note is inserted as a
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
      const acts = el('div', 'row-acts', button(n.action, 'btn outline sm', () => n.part === 'ways' ? wayAct(n.changed ? 'way_on' : 'way_check', n.way, n.name)
        : n.part === 'calendar' ? calNeed(n) : n.part === 'meetings' ? (location.hash = '#meetings') : openFolder()));
      if (n.suggestion) acts.append(button('Not now', 'btn ghost sm', () => calAct('cal_decline', {id: n.suggestion}, 'Turned down.')));
      row.append(acts);
      card.append(row);
    }
    return card;
  }
  function tile(t) {
    const tone = {ok: 'done', empty: 'working', stopped: 'attn'}[t.state] || '';
    const card = el('article', 'card part-tile');
    card.append(el('div', 'card-h', el('h2', null, link('#' + t.part, 'part-tile-link', t.label)), el('span', 'badge ' + tone, t.status)));
    const body = el('div', 'part-tile-body', el('p', 'glance', el('strong', null, t.line), t.changed ? el('span', 'side meta', (t.changed_word || 'changed') + ' ' + when(t.changed)) : null));
    if (t.source) body.append(el('p', 'meta', t.source));
    card.append(body, el('div', 'part-tile-foot meta', 'Helpers can use: ' + t.uses));
    return card;
  }
  // Ways in: the person's own scripts that reach a source on this computer; each is off until turned on here
  async function wayAct(op, way, name) {
    try {
      const r = await act(op, {way});
      const row = Array.isArray(r) ? r[0] : r;
      say(row ? name + ': ' + row.words : 'Done.');
      today = null; route();
    } catch (e) { say(e.message); }
  }
  function waysCard(rows) {
    const card = el('section', 'card');
    card.append(el('div', 'card-h', el('h2', null, 'Ways in'), el('span', 'meta', 'Each checks itself once a day')));
    const pill = {works: ['done', 'ok'], permission: ['needs', 'needs'], stopped: ['failed', 'bad'], off: ['', 'idle']};
    for (const w of rows) {
      // one line: the reason when it needs you (the fix button is in Needs you now), else when it last worked
      const seen = !w.on ? 'off until you turn it on' : w.problem ? w.problem : w.last_worked ? 'last worked ' + when(w.last_worked) : 'has not worked yet';
      const [pc, dc] = pill[w.status] || pill.off;
      const text = el('div', 'grow', el('p', null, el('strong', null, w.name), ' ', el('span', ('pill ' + pc).trim(), el('span', 'dot ' + dc), w.words)),
        el('p', 'meta', seen));
      const btn = w.on ? button('Turn off', 'btn outline sm', () => wayAct('way_off', w.way, w.name))
        : button('Turn on', 'btn outline sm', () => wayAct('way_on', w.way, w.name));
      card.append(el('div', 'list-row', text, btn));
    }
    return card;
  }
  function activityCard(rows) {
    const card = el('section', 'card');
    card.append(el('div', 'card-h', el('h2', null, 'What helpers did with it lately'), el('span', 'meta', 'Last 7 days')));
    if (!rows.length) card.append(el('p', 'pad muted', 'Helpers have not used Personal yet.'));
    for (const a of rows) {
      card.append(el('div', 'list-row', el('span', 'meta', when(a.at)), el('span', 'grow', ({notes: 'Notes: ', meetings: 'Meetings: ', ways: 'Ways in: ', calendar: 'Calendar: '}[a.part] || '') + a.what),
        a.ticket_key ? el('span', 'chip', a.ticket_key) : null));
    }
    return card;
  }
  function home() {
    const out = [];
    if (today.needs_you.length) out.push(needsCard(today.needs_you));
    const grid = el('div', 'tile-grid');
    today.parts.forEach(t => grid.append(tile(t)));
    grid.append(link('#parts', 'part-tile-add', el('strong', null, 'Add a part'), el('span', 'meta', 'Messages and Mail come next')));
    out.push(grid);
    if (today.ways && today.ways.length) out.push(waysCard(today.ways));
    if (!today.parts.length) out.unshift(state('empty', 'Nothing is added yet', 'Add Notes or Calendar first. Helpers can use nothing until you choose.'));
    out.push(activityCard(today.activity));
    out.push(el('p', 'footnote meta', 'Helpers use: orch personal today · They get only what the rules of each part allow.'));
    return out;
  }

  // --- Notes -----------------------------------------------------------------------------------------------
  function ruleSelect(label, help, name, value, words, part = 'notes') {
    const sel = el('select', 'input');
    sel.setAttribute('aria-label', label);
    for (const [k, w] of Object.entries(words)) { const o = el('option', null, w); o.value = k; o.selected = k === value; sel.append(o); }
    sel.addEventListener('change', async () => {
      try { await act('rules', {part, [name]: sel.value}); say('Saved. Helpers follow it from now on.'); today = null; }
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


  // --- Calendar --------------------------------------------------------------------------------------------
  // Times come in the calendar's own zone as text (2026-11-18T09:00+01:00): read straight from the text, so the page
  // shows the same hours as the Calendar app whatever the browser's zone is.
  const DAY = 864e5;
  const iso = d => d.toISOString().slice(0, 10);
  const dayOf = s => new Date(s.slice(0, 10) + 'T12:00:00Z');
  const addDays = (s, n) => iso(new Date(dayOf(s).getTime() + n * DAY));
  const monday = s => addDays(s, -((dayOf(s).getUTCDay() + 6) % 7));
  const hm = s => s.slice(11, 16);
  const mins = s => +s.slice(11, 13) * 60 + +s.slice(14, 16);
  const fmtDay = (s, opts) => dayOf(s).toLocaleDateString('en-GB', {timeZone: 'UTC', ...opts});
  const weekNo = s => { const d = dayOf(s); d.setUTCDate(d.getUTCDate() + 3 - (d.getUTCDay() + 6) % 7);
    const y = new Date(Date.UTC(d.getUTCFullYear(), 0, 4)); return 1 + Math.round(((d - y) / DAY - 3 + (y.getUTCDay() + 6) % 7) / 7); };
  let calFrom = null, calHidden = new Set();
  // a timed event is on day d when it starts that day, or started before and runs past its midnight
  const onDay = (e, d) => e.start.slice(0, 10) === d || (e.start.slice(0, 10) < d && (e.end.slice(0, 10) > d || (e.end.slice(0, 10) === d && mins(e.end) > 0)));

  async function calAct(op, args, ok) {
    try { const r = await act(op, args); say(ok || (r && r.words ? 'Calendar: ' + r.words : 'Saved.')); today = null; route(); }
    catch (e) { say(e.message); }
  }
  function calNeed(n) {
    if (n.suggestion) return calAct('cal_accept', {id: n.suggestion}, 'Opened in the Calendar app. Save it there.');
    return calAct(n.action === 'Allow calendars' ? 'cal_allow' : 'cal_check', {});
  }
  async function addCalendar() {
    try { await act('add', {part: 'calendar'}); today = null; say('Calendar is on. Allow calendars once on this Mac.'); location.hash = '#calendar'; route(); }
    catch (e) { say(e.message); }
  }
  function calEvent(e, cals, cls) {
    const c = cals[e.cal] || {};
    const a = el('div', ('cal-ev cal-' + (c.color % 6) + ' ' + (cls || '') + (e.declined ? ' declined' : '') + (e.free && !e.all_day ? ' free' : '')).trim(),
      el('span', 'cal-ev-t', e.title || 'Busy'), el('span', 'meta', (e.all_day ? '' : hm(e.start) + ' · ') + (c.title || '')));
    a.dataset.cal = e.cal;
    a.title = (e.all_day ? 'All day' : hm(e.start) + '–' + hm(e.end)) + ' · ' + (e.title || 'Busy') + ' · ' + (c.title || '') + (e.declined ? ' · declined' : '');
    return a;
  }
  function calWeek(w, cals) {
    const days = [...Array(7)].map((_, i) => addDays(w.from, i));
    const todayIso = iso(new Date());
    const timed = w.events.filter(e => !e.all_day);
    let lo = 8, hi = 18;
    timed.forEach(e => { if (e.start.slice(0, 10) >= w.from) lo = Math.min(lo, Math.floor(mins(e.start) / 60));
      hi = Math.max(hi, e.end.slice(0, 10) > e.start.slice(0, 10) ? 24 : Math.ceil(mins(e.end) / 60)); });
    const grid = el('div', 'cal-week');
    grid.style.setProperty('--rows', String((hi - lo) * 4));
    const head = el('div', 'cal-week-head', el('span'));
    const all = el('div', 'cal-week-all', el('span', 'meta', 'All day'));
    const body = el('div', 'cal-week-body');
    const hours = el('div', 'cal-hours');
    for (let h = lo; h < hi; h++) hours.append(el('span', 'meta', String(h).padStart(2, '0') + ':00'));
    body.append(hours);
    for (const d of days) {
      const isToday = d === todayIso;
      head.append(el('div', 'cal-day-h' + (isToday ? ' today' : ''), el('strong', null, fmtDay(d, {weekday: 'short', day: 'numeric'}))));
      const allDay = el('div', 'cal-day-all' + (isToday ? ' today' : ''));
      w.events.filter(e => e.all_day && e.start <= d && e.end > d).forEach(e => allDay.append(calEvent(e, cals)));
      all.append(allDay);
      const col = el('div', 'cal-day' + (isToday ? ' today' : ''));
      // events that overlap share the day side by side; one alone takes the whole width
      const lanes = [], placed = [];
      let cluster = [], clusterEnd = -1;
      const close = () => { const k = Math.max(...cluster.map(x => x.lane)) + 1; cluster.forEach(x => { x.k = k; }); cluster = []; };
      timed.filter(e => onDay(e, d)).forEach(e => {
        // an event over midnight shows on each day it covers, cut to that day
        const s = e.start.slice(0, 10) === d ? mins(e.start) : lo * 60;
        const end = e.end.slice(0, 10) > d ? hi * 60 : Math.max(mins(e.end), s + 15);
        if (s >= clusterEnd && cluster.length) { close(); lanes.length = 0; }
        let lane = lanes.findIndex(x => x <= s); if (lane < 0) { lane = lanes.length; lanes.push(0); } lanes[lane] = end;
        clusterEnd = Math.max(clusterEnd, end);
        const x = {e, s, end, lane}; cluster.push(x); placed.push(x);
      });
      if (cluster.length) close();
      const gcd = (a, b) => b ? gcd(b, a % b) : a;
      const n = placed.reduce((m, x) => m * x.k / gcd(m, x.k), 1);  // every cluster's share is a whole number of columns
      col.style.gridTemplateColumns = 'repeat(' + n + ', minmax(0, 1fr))';
      placed.forEach(x => {
        const ev = calEvent(x.e, cals);
        ev.style.gridRow = (Math.floor((x.s - lo * 60) / 15) + 1) + ' / span ' + Math.max(2, Math.ceil((x.end - x.s) / 15));
        const w = n / x.k;
        ev.style.gridColumn = (x.lane * w + 1) + ' / span ' + w;
        col.append(ev);
      });
      body.append(col);
    }
    grid.append(head, all, body);
    // phone: one list per day
    const list = el('div', 'cal-days');
    for (const d of days) {
      const evs = w.events.filter(e => e.all_day ? e.start <= d && e.end > d : onDay(e, d));
      if (!evs.length) continue;
      const card = el('section', 'card');
      card.append(el('div', 'card-h', el('h2', null, fmtDay(d, {weekday: 'short', day: 'numeric', month: 'short'})), d === todayIso ? el('span', 'badge working', 'Today') : null));
      evs.forEach(e => { const c = cals[e.cal] || {};
        const row = el('div', 'list-row', el('span', 'when meta', e.all_day ? 'All day' : (e.start.slice(0, 10) === d ? hm(e.start) : '') + '–' + (e.end.slice(0, 10) === d ? hm(e.end) : '')),
          el('div', 'grow', el('strong', null, e.title || 'Busy'), el('p', 'meta', c.title || '')), el('span', 'cal-dot cal-' + (c.color % 6)));
        row.dataset.cal = e.cal; card.append(row); });
      list.append(card);
    }
    if (!list.children.length) list.append(el('p', 'muted', 'Nothing in this week.'));
    return [grid, list];
  }
  function calHide() {
    document.querySelectorAll('#view [data-cal]').forEach(n => { n.hidden = calHidden.has(n.dataset.cal); });
  }
  function sourcesCard(w, levels) {
    const card = el('section', 'card');
    card.append(el('div', 'card-h', el('h2', null, 'Sources'), el('span', 'meta', 'You see all of them. Each one starts closed to helpers.')));
    for (const c of w.calendars) {
      const sel = el('select', 'input');
      sel.setAttribute('aria-label', 'Helpers can use from ' + c.title);
      for (const [k, word] of Object.entries(levels)) { const o = el('option', null, word); o.value = k; o.selected = k === c.level; sel.append(o); }
      sel.addEventListener('change', () => calAct('cal_level', {id: c.id, level: sel.value}, c.title + ': helpers can use ' + levels[sel.value].toLowerCase() + '.'));
      const text = el('div', 'grow', el('p', null, el('span', 'cal-dot cal-' + (c.color % 6)), ' ', el('strong', null, c.title)),
        el('p', 'meta', [c.account, c.shared ? 'shared' : null, 'through the Calendar app on this computer'].filter(Boolean).join(' · ')));
      const right = el('div', 'row');
      if (c.suggest_level && c.level === 'nothing') {
        right.append(button('Share ' + levels[c.suggest_level].toLowerCase(), 'btn outline sm', () => calAct('cal_level', {id: c.id, level: c.suggest_level}, c.title + ': saved.')));
      }
      right.append(sel);
      card.append(el('div', 'list-row', text, right));
    }
    return card;
  }
  function calRulesCard(moves, words) {
    const card = el('section', 'card');
    card.append(el('div', 'card-h', el('h2', null, 'What helpers may do'), el('span', 'meta', 'Changes apply at once')));
    card.append(el('div', 'rule-row', el('div', null, el('strong', null, 'See when you are busy'), el('p', 'meta', 'Only in calendars you share above. Helpers plan around your meetings without seeing what they are.')), el('span', 'meta', 'Per calendar')));
    card.append(el('div', 'rule-row', el('div', null, el('strong', null, 'Read titles and people'), el('p', 'meta', 'Only in calendars set to “Busy times, titles and people”. People by name, never their email. Never places, notes or links.')), el('span', 'meta', 'Per calendar')));
    const sel = el('select', 'input');
    sel.setAttribute('aria-label', 'Add or move an event');
    for (const [k, word] of Object.entries(words)) { const o = el('option', null, word); o.value = k; o.selected = k === moves; sel.append(o); }
    sel.addEventListener('change', () => calAct('cal_moves', {moves: sel.value}, 'Saved. Helpers follow it from now on.'));
    card.append(el('div', 'rule-row', el('div', null, el('strong', null, 'Add or move an event'), el('p', 'meta', 'A helper suggests a time; it is in your calendar only after you add it.')), sel));
    return card;
  }
  async function calendarScreen() {
    if (!today.parts.some(p => p.part === 'calendar')) {
      return [state('empty', 'Calendar is not added yet', 'Add it to see work, private and family calendars in one week. Helpers see nothing until you choose.', {label: 'Add Calendar', onClick: addCalendar})];
    }
    calFrom = calFrom || monday(iso(new Date()));
    let d;
    try { d = await read('/api/calendar?from=' + calFrom); }
    catch (e) {
      const st = (today.parts.find(p => p.part === 'calendar') || {}).status;
      if (/permission|Allow calendars|System Settings|access/i.test(e.message) || st === 'Needs your permission') {
        const why = /choose Allow calendars/.test(e.message) ? 'macOS asks you once. Your calendars stay on this computer.' : e.message;
        return [state('empty', 'Allow orch to read your calendars', why,
          {label: 'Allow calendars', onClick: () => calAct('cal_allow', {})})];
      }
      return [state('error', 'Your calendars can’t be read', e.message, {label: 'Try again', onClick: () => calAct('cal_check', {})})];
    }
    if (!d.on) return [state('empty', 'Calendar is not added yet', 'Add it to see your week.', {label: 'Add Calendar', onClick: addCalendar})];
    const w = d.week, cals = {};
    w.calendars.forEach(c => { cals[c.id] = c; });
    const out = [];
    const end = addDays(w.from, 6);
    const bar = el('div', 'row between');
    const legend = el('div', 'cal-legend', el('span', 'meta', 'Show here:'));
    for (const c of w.calendars) {
      const box = el('input'); box.type = 'checkbox'; box.checked = !calHidden.has(c.id);
      box.addEventListener('change', () => { box.checked ? calHidden.delete(c.id) : calHidden.add(c.id); calHide(); });
      legend.append(el('label', 'cal-' + (c.color % 6), box, el('span', 'cal-dot'), c.title, el('span', 'meta', c.account)));
    }
    const nav = el('div', 'row',
      button('Previous', 'btn ghost sm', () => { calFrom = addDays(calFrom, -7); route(); }),
      button('This week', 'btn outline sm', () => { calFrom = null; route(); }),
      button('Next', 'btn ghost sm', () => { calFrom = addDays(calFrom, 7); route(); }));
    nav.firstChild.setAttribute('aria-label', 'Previous week');
    nav.lastChild.setAttribute('aria-label', 'Next week');
    bar.append(el('div', null, el('h2', null, fmtDay(w.from, {day: 'numeric'}) + ' to ' + fmtDay(end, {day: 'numeric', month: 'short', year: 'numeric'})),
      el('p', 'meta', 'Week ' + weekNo(w.from) + ' · read from your Calendar app ' + when(w.read_at))), nav);
    const top = el('section', 'card pad stack');
    top.append(bar, legend);
    out.push(top);
    if (w.note) out.push(el('p', 'note', w.note));
    for (const o of w.overlaps.slice(0, 3)) {
      out.push(el('div', 'banner attn', el('strong', null, fmtDay(o.at, {weekday: 'short'}) + ' ' + hm(o.at) + ': two things at once. '),
        o.a.title + ' (' + o.a.calendar + ') and ' + o.b.title + ' (' + o.b.calendar + ') overlap by ' + o.minutes + ' minutes.'));
    }
    const weekCard = el('section', 'card');
    weekCard.append(...calWeek(w, cals));
    out.push(weekCard, sourcesCard(w, d.levels), calRulesCard(w.moves, d.moves_words));
    const acts = (today.activity || []).filter(a => a.part === 'calendar');
    out.push(activityCard(acts));
    out.push(el('p', 'footnote meta', 'Helpers use: orch personal calendar week · Calendar text is data for helpers, never orders.'));
    setTimeout(calHide);
    return out;
  }
  // --- Meetings --------------------------------------------------------------------------------------------
  const MEET_SUB = 'Calls recorded on this computer arrive here with who said what, a summary and the next steps. Ask everyone on the call before you record.';
  function meetWhen(m) {
    return [when(m.started), m.minutes ? m.minutes + ' min' : '', m.source].filter(Boolean).join(' · ');
  }
  async function meetAct(op, args, done) {
    try { const r = await act(op, args); today = null; say(done(r)); route(); }
    catch (e) { say(e.message); }
  }
  function waitingCard(w) {
    const card = el('section', 'card');
    if (w.state === 'waiting') {
      card.append(el('div', 'card-h', el('h2', null, 'Did everyone on the call agree to the recording?'), el('span', 'badge needs', 'Needs you')));
      card.append(el('div', 'pad stack-sm',
        el('p', null, el('strong', null, w.title), ' ', el('span', 'meta', meetWhen(w))),
        w.people.length ? el('p', 'meta', 'With ' + w.people.join(', ')) : null,
        el('p', 'muted', 'Nothing of it is read until you say so. By law everyone on the call must agree before you record; telling them is not enough.')));
      card.append(el('div', 'part-tile-foot',
        button('Yes, everyone agreed', 'btn primary', () => meetAct('meet_agree', {key: w.key, yes: true}, () => 'Saved. The meeting arrives here in a moment.').then(() => meetAct('meet_pickup', {}, r => r.taken ? 'The meeting arrived.' : 'It arrives at the next look.'))),
        button('No', 'btn outline', () => meetAct('meet_agree', {key: w.key, yes: false}, () => 'It is never read. It stays in your recorder; delete it there.'))));
    } else {
      card.append(el('div', 'card-h', el('h2', null, w.title + ' could not be taken in'), el('span', 'badge attn', 'Stopped')));
      card.append(el('p', 'pad muted', w.problem || 'The recorder did not hand it over.'));
      card.append(el('div', 'part-tile-foot', button('Try again', 'btn outline', () => meetAct('meet_pickup', {}, r => r.taken ? 'The meeting arrived.' : (r.problems[0] || 'Nothing new.')))));
    }
    return card;
  }
  function meetRulesCard(r) {
    const card = el('section', 'card');
    card.append(el('div', 'card-h', el('h2', null, 'What helpers may do'), el('span', 'meta', 'Changes apply at once')));
    card.append(ruleSelect('Read meetings', 'Transcript, summary and next steps. Helpers on a ticket use only what is attached to it, unless you allow all meetings.', 'read', r.meetings.read,
      {never: 'Never', attached: 'Only in a ticket you attach it to', all: 'All meetings'}, 'meetings'));
    card.append(ruleSelect('Write a missing summary', 'When the recorder gave no summary, a helper may write it and the next steps.', 'write', r.meetings.write,
      {never: 'Never', add: 'Only where there is none', change: 'Write and change'}, 'meetings'));
    card.append(el('div', 'rule-row', el('div', null, el('strong', null, 'The sound'), el('p', 'meta', 'It stays in orch Companion on this computer.')), el('span', 'badge', 'Never')));
    return card;
  }
  function dueDay(d) {
    // a plain day (2026-11-20) reads as "Fri 20 Nov"; anything else the recorder wrote stays as it is
    if (!/^\d{4}-\d{2}-\d{2}$/.test(d || '')) return d || '';
    return new Date(d + 'T12:00:00').toLocaleDateString([], {weekday: 'short', day: 'numeric', month: 'short'});
  }
  async function meetingPanel(id, calm) {
    const panel = el('article', 'split-panel stack');
    panel.tabIndex = -1;
    let m;
    try { m = await read('/api/meeting?id=' + encodeURIComponent(id)); }
    catch (e) { panel.append(state('error', 'This meeting can’t be shown', e.message)); return panel; }
    panel.append(link('#meetings', 'btn ghost sm phone-only', 'All meetings'));
    panel.append(el('div', 'row between', el('h2', null, m.title), el('span', 'meta', meetWhen(m) + (m.arrived ? ' · arrived ' + when(m.arrived) : ''))));
    if (m.people.length) panel.append(el('p', 'meta', m.people.join(', ') + ' and you'));
    panel.append(el('h3', null, 'Summary'), el('p', m.summary ? 'reading' : 'muted', m.summary || 'No summary yet. The recorder gave none; a helper can write it if you allow it below.'));
    const open = m.steps.filter(s => !s.ticket);
    panel.append(el('h3', null, open.length ? 'Next steps, proposed as tickets' : 'Next steps'));
    if (!m.steps.length) panel.append(el('p', 'muted', 'Nobody took a next step in this meeting.'));
    const box = el('div', 'card');
    const ticked = new Set(open.map(s => s.n));
    // one filled button per screen: an answer waiting above (did everyone agree?) keeps this one outlined
    const make = button('', calm ? 'btn outline' : 'btn primary', async () => {
      if (!ticked.size) return;
      make.disabled = true;
      await meetAct('meet_tickets', {id: m.id, steps: [...ticked]}, r => r.made.length === 1 ? 'Made 1 ticket: ' + r.made[0].key : 'Made ' + r.made.length + ' tickets.');
    });
    const label = () => { make.textContent = ticked.size === 1 ? 'Make 1 ticket' : 'Make ' + ticked.size + ' tickets'; make.disabled = !ticked.size; };
    for (const s of m.steps) {
      const said = [s.who && 'Said by ' + s.who, s.due && 'until ' + dueDay(s.due)].filter(Boolean).join(' · ');
      const text = el('span', 'grow', el('strong', null, s.text), said ? el('span', 'subline', said) : null);
      if (s.ticket) {
        box.append(el('div', 'list-row', text, el('span', 'chip', m.keys[s.ticket] || s.ticket)));
      } else {
        const c = el('input'); c.type = 'checkbox'; c.checked = true; c.setAttribute('aria-label', 'Make a ticket: ' + s.text);
        c.addEventListener('change', () => { c.checked ? ticked.add(s.n) : ticked.delete(s.n); label(); });
        box.append(el('label', 'list-row check-label', c, text, el('span', 'meta', 'New ticket · To do')));
      }
    }
    if (m.steps.length) panel.append(box);
    if (open.length) {
      label();
      panel.append(el('div', 'row', make), el('p', 'meta', 'The ticked steps become new tickets in To do, each with the summary and next steps attached. No helper starts one until you start it.'));
    }
    panel.append(el('h3', null, 'Transcript'));
    const lines = el('div', 'card');
    const paint = all => {
      lines.replaceChildren();
      (all ? m.transcript : m.transcript.slice(0, 8)).forEach(x => lines.append(el('div', 'list-row', el('span', 'meta', (x.who || '?') + ' ' + x.at), el('span', 'grow', x.text))));
      if (!all && m.transcript.length > 8) lines.append(el('div', 'list-row', button('Show all ' + m.transcript.length + ' lines', 'btn ghost sm', () => paint(true))));
      if (!m.transcript.length) lines.append(el('p', 'pad muted', 'The recorder gave no transcript.'));
    };
    paint(false);
    panel.append(lines);
    panel.append(el('div', 'row', button('Use in a ticket', 'btn outline', () => openUse({id: m.id, title: m.title, part: 'meetings'})),
      button('Delete from Personal', 'btn ghost', () => openDelete(m))));
    const side = el('div', 'card');
    side.append(el('div', 'card-h', el('h3', null, 'On the ticket side'), el('span', 'meta', 'Helpers on a ticket use only what is attached to it')));
    if (!m.tickets_using.length) side.append(el('p', 'pad muted', 'Not attached to a ticket yet.'));
    m.tickets_using.forEach(t => side.append(el('div', 'list-row', el('span', 'chip', m.keys[t] || t), el('span', 'grow meta', 'Attached from Personal: this meeting'))));
    panel.append(side);
    return panel;
  }
  // A call running now (orch Companion): one line on Meetings, refreshed every 5 s while Meetings is open.
  function clock(iso) { const t = new Date(iso); return isNaN(t) ? '' : t.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit', hourCycle: 'h23'}); }
  function nowStrip(n) {
    const card = el('section', 'card', el('div', 'pad row',
      el('span', 'pill', el('span', 'dot' + (n.state === 'call' ? ' live' : n.state === 'quiet' ? ' needs' : ' idle')), n.words),
      n.state === 'call' && n.since ? el('span', 'meta', 'since ' + clock(n.since)) : null,
      n.state === 'ended' && n.ended ? el('span', 'meta', 'at ' + clock(n.ended)) : null,
      n.hint ? el('span', 'meta', n.hint) : null));
    card.id = 'meet-now';
    card.setAttribute('aria-live', 'polite');
    return card;
  }
  let nowTimer = null;
  function watchNow() {
    if (nowTimer) return;
    nowTimer = setInterval(async () => {
      const cur = document.getElementById('meet-now');
      if (!cur || document.hidden || !location.hash.startsWith('#meetings')) return;
      try { const d = await read('/api/meetings'); if (d.now) cur.replaceWith(nowStrip(d.now)); } catch (e) { /* the next look tries again */ }
    }, 5000);
  }
  // Calls the recorder has not finished yet: being transcribed, or the recorder's own plain words about a problem.
  function pendingCard(items) {
    const card = el('section', 'card', el('div', 'card-h', el('h2', null, 'Not ready yet')));
    card.id = 'meet-pending';
    items.forEach(p => card.append(el('div', 'pad stack-sm', el('p', null, el('strong', null, p.title), ' ', el('span', 'meta', [when(p.started), p.source].filter(Boolean).join(' · '))), el('p', 'muted', p.words))));
    return card;
  }
  async function meetingsScreen(id) {
    let rules, d;
    try { rules = await read('/api/rules'); } catch (e) { return [state('error', 'Meetings can’t be shown', e.message)]; }
    if (!rules.meetings || !rules.meetings.on) return [state('empty', 'Meetings is not added yet', 'Add it to see your recorded calls here.', {label: 'Add Meetings', onClick: () => addPart('meetings')})];
    try { d = await read('/api/meetings'); } catch (e) { return [state('error', 'Meetings can’t be read', e.message), meetRulesCard(rules)]; }
    const out = d.waiting.map(waitingCard);
    if ((d.pending || []).length) out.push(pendingCard(d.pending));
    if (d.now) { out.unshift(nowStrip(d.now)); watchNow(); }
    const look = button('Look for new meetings', 'btn outline sm', () => meetAct('meet_pickup', {}, r =>
      r.problems.length ? r.problems[0] : [r.taken ? r.taken + ' arrived.' : '', r.new ? r.new + ' new, waiting for your answer.' : ''].filter(Boolean).join(' ') || 'Nothing new.'));
    const rec = d.recorders.length ? 'From ' + d.recorders.map(w => w.name).join(', ') + (d.recorders[0].last_worked ? ' · last looked ' + when(d.recorders[0].last_worked) : '') : '';
    if (!d.meetings.length) {
      out.push(d.recorders.length
        ? state('empty', 'No meeting has arrived yet', 'A call you record arrives here when it is finished, after you said that everyone agreed.', {label: 'Look for new meetings', onClick: () => look.click()})
        : state('empty', 'No recorder yet', 'Meetings come from a recorder on this computer, such as Yogurt. Turn it on under Ways in on Personal; until then nothing arrives.'));
      out.push(meetRulesCard(rules), el('p', 'footnote meta', d.consent));
      return out;
    }
    if (!id && matchMedia('(min-width: 721px)').matches) id = d.meetings[0].id;
    const split = el('section', 'split-view');
    if (location.hash.startsWith('#meetings/')) split.dataset.picked = '';
    const list = el('div', 'split-list card');
    list.append(el('div', 'pad stack-sm', look, rec ? el('p', 'meta', rec) : null));
    const day = new Date().toDateString();
    const groups = [['Today', d.meetings.filter(m => new Date(m.started).toDateString() === day)], ['Earlier', d.meetings.filter(m => new Date(m.started).toDateString() !== day)]];
    for (const [g, items] of groups) {
      if (!items.length) continue;
      list.append(el('div', 'card-h', el('h2', null, g)));
      for (const m of items) {
        const row = el('div', 'list-row' + (m.id === id ? ' cur' : ''));
        const sub = [when(m.started), m.minutes + ' min', m.tickets ? m.tickets + (m.tickets === 1 ? ' ticket made' : ' tickets made') : m.steps ? m.steps + ' next steps' : m.has_summary ? 'no next steps' : 'no summary yet'];
        const a = link('#meetings/' + encodeURIComponent(m.id), 'grow', m.title, el('span', 'subline', sub.join(' · ')));
        if (m.id === id) a.setAttribute('aria-current', 'true');
        row.append(a);
        list.append(row);
      }
    }
    split.append(list, id ? await meetingPanel(id, d.waiting.length > 0) : el('div', 'split-panel muted', 'Pick a meeting to read it.'));
    out.push(split, meetRulesCard(rules), el('p', 'footnote meta', d.consent + ' Helpers use: orch personal meetings show <meeting>.'));
    return out;
  }
  function openDelete(m) {
    $('delete-what').textContent = m.title;
    $('delete-ok').onclick = async () => { $('delete-dialog').close(); location.hash = '#meetings'; await meetAct('meet_delete', {id: m.id}, () => 'Deleted from Personal. Your recorder still has it.'); };
    $('delete-dialog').showModal();
  }
  $('delete-cancel').addEventListener('click', () => $('delete-dialog').close());

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
    const meetOn = today.parts.some(p => p.part === 'meetings');
    yours.append(partRow('Meetings', 'Record calls on this computer; get the transcript, a summary and next steps here. Ask everyone on the call before you record.',
      'the recorder on this computer', meetOn ? el('span', 'badge done', 'On') : button('Add Meetings', 'btn primary sm', () => addPart('meetings'))));
    const calOn = today.parts.some(p => p.part === 'calendar');
    yours.append(partRow('Calendar', 'Work, private and family calendars in one week view.', 'the Calendar app on this computer',
      calOn ? el('span', 'badge done', 'On') : button('Add Calendar', 'btn primary sm', addCalendar)));
    const soon = el('section', 'card');
    soon.append(el('div', 'card-h', el('h2', null, 'Coming next'), el('span', 'meta', 'Each through a way in on this computer')));
    today.soon.forEach(s => soon.append(partRow(s.label, s.text, null, el('span', 'badge', 'Soon'))));
    const later = el('section', 'card');
    later.append(el('div', 'card-h', el('h2', null, 'Coming later')));
    today.later.forEach(s => later.append(partRow(s.label, s.text, null, el('span', 'badge', 'Later'))));
    return [yours, soon, later, el('p', 'footnote meta', 'A part shows nothing and a helper can use nothing until you add it. Turning one off closes it to helpers; your files stay where they are.')];
  }
  async function addPart(part) {
    if (part === 'notes') return addNotes();
    try { await act('add', {part}); today = null; say('Meetings is on.'); location.hash = '#' + part; route(); }
    catch (e) { say(e.message); }
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
    $('use-what').textContent = (n.part === 'meetings' ? 'Meeting: ' : 'Note: ') + n.title;
    $('use-allow').textContent = n.part === 'meetings'
      ? 'Helpers on that ticket can read this meeting with its whole transcript. Never the sound.'
      : 'Helpers on that ticket can read this note. Nothing in your notes folder changes.';
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
    try { await act('use', {ticket: pick.value, id: useFrom.id, part: useFrom.part || 'notes'}); $('use-dialog').close(); say('Attached to the ticket.'); route(); }
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
    const h = decodeURIComponent(location.hash.slice(1)) || (['notes', 'meetings', 'calendar', 'parts'].includes(start) ? start : '');
    view.setAttribute('aria-busy', 'true');
    try { if (!today) today = await read('/api/today'); }
    catch (e) {
      view.replaceChildren(e.signIn ? state('empty', 'Sign in to see Personal', e.message) : state('error', 'Personal can’t be shown right now', e.message));
      view.setAttribute('aria-busy', 'false'); return; }
    let out;
    const [screen, ...rest] = h.split('/');
    const head = (title, sub) => { $('page-title').firstChild.textContent = title + ' '; $('page-sub').textContent = sub; };
    if (screen === 'calendar') { head('Calendar', 'Work, private and family in one week. What helpers may see is set under Sources.'); out = await calendarScreen(); }
    else if (screen === 'notes') { head('Notes', 'What you and your helpers know, as linked notes. Click a link to follow it.'); out = await notesScreen(rest.join('/') || null); }
    else if (screen === 'meetings') { head('Meetings', MEET_SUB); out = await meetingsScreen(rest.join('/') || null); }
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
