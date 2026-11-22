/* ORCH-1197 draft: preview data and behaviour only. Nothing here talks to a server. */
const qs = new URLSearchParams(location.search);
const START = qs.get('state') || 'invite';
const S = { state: START === 'unreachable' ? 'app' : START, reach: START === 'unreachable' ? 'off' : 'ok', answered: null, extra: {}, staged: null };
const WS = {
  sev: { name: "Severin's workspace", letter: 'S' },
  mkt: { name: 'Marketing', letter: 'M' },
};
const TICKETS = [
  { id: 'orch-41', ws: 'sev', key: 'ORCH-41', title: 'Spring newsletter', status: 'needs', done: 2, total: 4, time: '09:41', last: 'Which subject line?' },
  { id: 'orch-38', ws: 'sev', key: 'ORCH-38', title: 'Price list 2027', status: 'working', done: 1, total: 3, time: '09:20', last: 'Applying the new prices to 42 lines' },
  { id: 'mkt-14', ws: 'mkt', key: 'MKT-14', title: 'Customer story: Bakery Frey', status: 'working', done: 2, total: 5, time: '08:55', last: 'Interview notes sorted, writing the first part' },
  { id: 'mkt-12', ws: 'mkt', key: 'MKT-12', title: 'Trade fair flyer', status: 'done', done: 3, total: 3, time: 'Yesterday', last: 'The flyer is ready: A5, front and back' },
];
const QUESTION = {
  ticket: 'orch-41', title: 'Which subject line?', text: 'The draft is ready. Pick the line people see in their inbox.',
  options: ['Spring is here: three new things to try', 'Your April update from Severin', 'Open day on 12 April: come by'], recommended: 0,
};
const THREADS = {
  'orch-41': [
    { k: 'me', t: '08:52', text: "Can you write the spring newsletter? My notes are attached. Same tone as last year's.", file: { name: 'Newsletter-notes.pdf', size: '240 KB' } },
    { k: 'step', text: 'Step 1 of 4 done: Notes read' },
    { k: 'helper', t: '09:14', text: 'I read your notes and wrote a first draft with three parts: the new opening hours, the spring offer and the open day on 12 April.' },
    { k: 'step', text: 'Step 2 of 4 done: Draft written' },
    { k: 'q' },
  ],
  'orch-38': [
    { k: 'me', t: 'Yesterday', text: 'Please update the price list for 2027: plus 3 % on all services, rounded to 5.' },
    { k: 'step', text: 'Step 1 of 3 done: 2026 list found' },
    { k: 'helper', t: '09:20', text: 'Working on it. I am applying the new prices to 42 lines and will show you the list before anything is sent.' },
  ],
  'mkt-14': [
    { k: 'me', t: 'Mon', text: 'Write a short customer story from the interview with Bakery Frey.' },
    { k: 'helper', t: '08:55', text: 'The interview notes are sorted. I am writing the first part now.' },
  ],
  'mkt-12': [
    { k: 'me', t: 'Tue', text: 'We need a flyer for the trade fair in May.' },
    { k: 'helper', t: 'Yesterday', label: 'Result', text: 'The flyer is ready: A5, front and back, with the stand number.' },
    { k: 'step', text: 'Done' },
  ],
  sev: [
    { k: 'helper', t: 'Mon', text: 'Hello Max. Write here to start something new. Each new message starts a ticket.' },
    { k: 'step', text: 'Started: ORCH-41 · Spring newsletter' },
  ],
  mkt: [
    { k: 'helper', t: 'Mon', text: 'Hello Max. Write here to start something new. Each new message starts a ticket.' },
  ],
};
const STATUS = { needs: 'Needs you', working: 'Working', done: 'Done' };
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const ticket = (id) => TICKETS.find((t) => t.id === id);
const wsOf = (id) => (WS[id] ? id : ticket(id).ws);
const offline = (id) => S.reach === 'off' && wsOf(id) === 'sev';
const needsCount = () => TICKETS.filter((t) => t.status === 'needs').length;
const badge = (st) => `<span class="badge ${st}">${STATUS[st]}</span>`;
const wsb = (id, size = 's32') => `<span class="wsb ${size} x-ws-${id}" aria-hidden="true"><b>${WS[id].letter}</b></span>`;
const reachWord = (id) => (S.reach === 'off' && id === 'sev' ? 'Not reachable' : 'Online');
const reachDot = (id) => `<span class="dot ${S.reach === 'off' && id === 'sev' ? 'idle' : 'ok'}" aria-hidden="true"></span>`;
const fileChip = (f) => `<a class="file-chip" href="#" data-file><span class="file-type">PDF</span><span><strong>${esc(f.name)}</strong><br><span class="meta">${esc(f.size)}</span></span></a>`;

function questionCard(where) {
  const t = ticket(QUESTION.ticket);
  if (S.answered !== null) {
    const waits = offline(QUESTION.ticket);
    return `<section class="qcard" data-phase="${waits ? 'pending' : 'sent'}"><p class="qmeta meta">${esc(t.key)} · ${esc(t.title)}</p><h3>${esc(QUESTION.title)}</h3>
      <p class="qstatus ${waits ? 'notsent' : 'sent'}" role="status">${waits ? 'Your answer waits and is sent when the workspace is reachable again: ' : 'Answered from this browser: '}${esc(QUESTION.options[S.answered])}</p></section>`;
  }
  return `<section class="qcard" aria-label="Question"><p class="qmeta meta">${where === 'home' ? '<span class="badge needs">Needs you</span> ' + esc(WS[t.ws].name) + ' · ' + esc(t.key) + ' · ' + esc(t.title) : 'Question'}</p>
    <h3>${esc(QUESTION.title)}</h3><p class="muted">${esc(QUESTION.text)}</p>
    <div class="qoptions x-qoptions">${QUESTION.options.map((o, i) => `<button type="button" class="btn qoption${i === QUESTION.recommended ? ' suggested' : ''}" data-answer="${i}"><span>${esc(o)}</span>${i === QUESTION.recommended ? '<span class="suggested-label">Suggested</span>' : ''}</button>`).join('')}</div></section>`;
}
function threadHtml(id) {
  const items = [...THREADS[id], ...(S.extra[id] || [])];
  let h = '';
  if (offline(id)) h += `<div class="banner attn x-banner" role="status"><div class="grow"><strong>${esc(WS.sev.name)} is not reachable right now</strong><p>The computer it runs on may be asleep. Your messages wait here and are sent when it is back.</p></div></div>`;
  for (const m of items) {
    if (m.k === 'me') h += `<div class="msg me"><p>${esc(m.text)}</p>${m.file ? fileChip(m.file) : ''}<p class="meta">${m.wait ? icon('clock', 12) + ' Waiting to send' : esc(m.t) + ' · Sent'}</p></div>`;
    else if (m.k === 'helper') h += `<div class="msg"><p class="meta">${m.label ? '<span class="badge done">' + esc(m.label) + '</span> ' : ''}Claude · helper · ${esc(m.t)}</p><p>${esc(m.text)}</p></div>`;
    else if (m.k === 'step') h += `<p class="meta x-step">${esc(m.text)}</p>`;
    else if (m.k === 'q') h += questionCard('thread');
  }
  return `<div class="msgs">${h}</div>`;
}
function composerHtml(id) {
  const name = WS[id] ? WS[id].name : 'Claude';
  const note = offline(id) ? 'Not reachable. Your message waits until it is back.' : WS[id] ? 'A new message starts a new ticket.' : ticket(id).status === 'done' ? 'Saved for the next run.' : 'Your helper reads it after the current step.';
  return `<form class="x-composer" data-composer="${id}"><div class="x-staged" data-staged>${S.staged ? fileChip(S.staged) : ''}</div><div class="x-composer-line">
    <label class="btn icon ghost" aria-label="Add a file">${icon('clip', 18)}<input type="file" class="sr-only" data-attach></label>
    <input class="input" name="text" autocomplete="off" aria-label="Message ${esc(name)}" placeholder="Message ${esc(name)}…">
    <button class="btn primary" type="submit">${icon('send', 16)}<span class="x-send-word">Send</span></button></div><p class="meta">${note}</p></form>`;
}
function toast(text) {
  let box = $('.toasts');
  if (!box) { box = document.createElement('div'); box.className = 'toasts'; box.setAttribute('role', 'status'); document.body.append(box); }
  box.innerHTML = `<div class="toast">${icon('check', 16)}<span>${esc(text)}</span></div>`;
  clearTimeout(toast.t); toast.t = setTimeout(() => { box.innerHTML = ''; }, 5000);
}
function setState(st, opts = {}) {
  S.state = st;
  document.body.dataset.state = st;
  document.body.dataset.reach = S.reach;
  $$('[data-show]').forEach((el) => { el.hidden = !el.dataset.show.split(' ').includes(st); });
  $$('[data-signin]').forEach((b) => {
    const busy = st === 'joining';
    b.disabled = busy; b.setAttribute('aria-busy', String(busy));
    b.innerHTML = busy ? '<span class="spinner x-spin" aria-hidden="true"></span> Connecting…' : 'Sign in';
  });
  if (st === 'app') { render(); if (opts.welcome) toast('You are signed in. This browser is called Max laptop.'); }
}
document.addEventListener('click', (e) => {
  const el = e.target.closest('[data-signin],[data-answer],[data-signout],[data-signout-yes],[data-close-dialog],[data-file]');
  if (!el) return;
  if (el.matches('[data-signin]')) { setState('joining'); setTimeout(() => setState('app', { welcome: true }), 1200); }
  else if (el.matches('[data-answer]')) {
    S.answered = Number(el.dataset.answer);
    const t = ticket(QUESTION.ticket); t.status = 'working'; t.last = offline(t.id) ? 'Your answer waits to be sent' : 'Subject line chosen, preparing the send list';
    render();
  }
  else if (el.matches('[data-signout]')) { $$('details[open]').forEach((d) => { d.open = false; }); $('#signout').showModal(); }
  else if (el.matches('[data-signout-yes]')) { $$('dialog[open]').forEach((d) => d.close()); setState('left'); }
  else if (el.matches('[data-close-dialog]')) el.closest('dialog').close();
  else if (el.matches('[data-file]')) { e.preventDefault(); toast('In the real page the file opens here.'); }
});
document.addEventListener('change', (e) => {
  if (!e.target.matches('[data-attach]')) return;
  const f = e.target.files[0]; if (!f) return;
  S.staged = { name: f.name, size: Math.max(1, Math.round(f.size / 1024)) + ' KB' };
  $('[data-staged]', e.target.closest('form')).innerHTML = fileChip(S.staged);
});
document.addEventListener('submit', (e) => {
  const f = e.target.closest('[data-composer]'); if (!f) return;
  e.preventDefault();
  const id = f.dataset.composer, text = f.elements.text.value.trim();
  if (!text && !S.staged) return;
  (S.extra[id] = S.extra[id] || []).push({ k: 'me', t: 'Now', text: text || 'File', file: S.staged, wait: offline(id) });
  S.staged = null;
  if (!offline(id)) setTimeout(() => { S.extra[id].push({ k: 'helper', t: 'Now', text: 'Got it. I will take this into the next step.' }); render(); }, 1400);
  render();
  const inp = $('[data-composer] [name=text]'); if (inp) inp.focus();
});
/* Preview switcher (not part of the product) */
function previewSwitcher() {
  if (qs.get('shots') === '1') return;
  const items = [['invite', 'Invitation'], ['joining', 'Connecting'], ['app', 'Signed in'], ['unreachable', 'Not reachable'], ['used', 'Link used or expired'], ['cut', 'Signed out by the owner'], ['left', 'Signed out']];
  const d = document.createElement('details'); d.className = 'x-preview'; d.setAttribute('aria-label', 'Preview controls');
  d.innerHTML = '<summary>Preview</summary><div class="x-preview-options">' + items.map(([k, l]) => `<a class="btn xs ghost" href="?state=${k}" ${k === START ? 'aria-current="true"' : ''}>${l}</a>`).join('') + '<a class="btn xs ghost" href="../index.html">All drafts</a></div>';
  document.body.append(d);
}
/* Draft B: two panes. On a phone one pane at a time (data-pane). */
const V = { id: qs.get('id') || 'orch-41', filter: 'all' };
document.body.dataset.pane = qs.get('view') === 'thread' ? 'thread' : 'list';
function render() {
  const n = needsCount();
  let h = `<div class="segmented" role="group" aria-label="Show"><button type="button" class="btn" data-filter="all" aria-pressed="${V.filter === 'all'}">All</button><button type="button" class="btn" data-filter="needs" aria-pressed="${V.filter === 'needs'}">Needs you${n ? ' <span class="count">' + n + '</span>' : ''}</button></div>`;
  let any = false;
  for (const id of Object.keys(WS)) {
    const ts = TICKETS.filter((t) => t.ws === id && (V.filter === 'all' || t.status === 'needs'));
    if (V.filter === 'needs' && !ts.length) continue;
    any = true;
    h += `<section class="b-group" aria-label="${esc(WS[id].name)}"><div class="b-group-h">${wsb(id, 's26')}<strong class="grow truncate">${esc(WS[id].name)}</strong><span class="meta">${reachDot(id)} ${reachWord(id)}</span></div>
      ${V.filter === 'all' ? `<button type="button" class="b-row" data-open="${id}" aria-current="${V.id === id}"><span class="b-ic muted">${icon('pencil', 16)}</span><span class="grow"><strong>New message</strong><span class="meta">Starts a new ticket</span></span></button>` : ''}
      ${ts.map((t) => `<button type="button" class="b-row" data-open="${t.id}" aria-current="${V.id === t.id}"><span class="dot ${t.status === 'needs' ? 'needs' : t.status === 'working' ? 'working' : 'ok'}" aria-hidden="true"></span><span class="grow"><strong class="truncate">${esc(t.title)}</strong><span class="meta truncate"><span class="key">${t.key}</span> · ${esc(t.status === 'needs' ? 'Waiting for your answer' : t.last)}</span></span><span class="meta a-side">${t.time}</span></button>`).join('')}</section>`;
  }
  if (!any) h += `<div class="empty"><p>Nothing needs you right now.</p></div>`;
  $('#b-list').innerHTML = h;
  $('#b-reach').innerHTML = S.reach === 'off' ? `<span class="badge">${reachDot('sev')} ${esc(WS.sev.name)} is not reachable</span>` : '';
  const t = ticket(V.id), w = WS[wsOf(V.id)];
  const scroll = $('.b-scroll'), keep = scroll ? scroll.scrollTop : 0;
  $('#b-thread').innerHTML = `<header class="b-thread-h"><button type="button" class="btn icon ghost b-back" data-back aria-label="Back to the list">${icon('chevron-right', 18)}</button>
    <div class="grow"><h1 class="truncate">${t ? esc(t.title) : esc(w.name)}</h1><span class="meta truncate">${t ? '<span class="key">' + t.key + '</span> · Claude · helper · ' + esc(w.name) : 'A new message starts a new ticket'}</span></div>
    ${t ? badge(t.status) + `<div class="b-steps"><span class="meta">${t.done} of ${t.total} steps done</span><div class="progress"><span style="--value:${Math.round((t.done / t.total) * 100)}%"></span></div></div>` : ''}</header>
    <div class="b-scroll">${threadHtml(V.id)}</div><div class="b-compose">${composerHtml(V.id)}</div>`;
  $('.b-scroll').scrollTop = keep;
}
document.addEventListener('click', (e) => {
  const el = e.target.closest('[data-open],[data-back],[data-filter]'); if (!el) return;
  if (el.dataset.open) { V.id = el.dataset.open; document.body.dataset.pane = 'thread'; render(); $('.b-scroll').scrollTop = 0; return; }
  if (el.hasAttribute('data-back')) document.body.dataset.pane = 'list'; else V.filter = el.dataset.filter;
  render();
});
previewSwitcher();
setState(S.state);
