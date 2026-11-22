/* Browser page of the relay (ORCH-1197). A browser is a device like a phone: it signs in once with the invitation
   code from the link (#code=pc_…) and then uses the /v1/phone/* API with its own token. Every text from a server
   is put on the page escaped (esc) or as textContent; nothing is ever inserted as HTML from a server. */
(function () {
  'use strict';
  const KEY = 'orch.relay.device';
  const POLL_MS = 10000;
  const FRESH_MS = 5 * 60 * 1000; // a workspace counts as reachable while last_seen is at most 5 minutes old
  const COLORS = ['var(--brand)', 'var(--chart-4)', 'var(--chart-2)', 'var(--chart-3)', 'var(--chart-5)', 'var(--info)'];
  const STATUS = { needs: 'Needs you', working: 'Working', review: 'Ready to check', done: 'Done' };
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const ic = (n, s) => (typeof window.icon === 'function' ? window.icon(n, s) : '');
  // The relay dedupes retries on (device, client_id); a client_id is a UUID (message.schema.json).
  const cid = () => {
    if (crypto.randomUUID) return crypto.randomUUID();
    const b = crypto.getRandomValues(new Uint8Array(16)); b[6] = (b[6] & 15) | 64; b[8] = (b[8] & 63) | 128;
    const x = [...b].map((v) => v.toString(16).padStart(2, '0')).join('');
    return `${x.slice(0, 8)}-${x.slice(8, 12)}-${x.slice(12, 16)}-${x.slice(16, 20)}-${x.slice(20)}`;
  };

  // ---- the device (kept in this browser only) ----
  function loadDev() { try { const d = JSON.parse(localStorage.getItem(KEY) || 'null'); return d && d.id && d.token ? d : null; } catch (_) { return null; } }
  function saveDev(d) { try { localStorage.setItem(KEY, JSON.stringify(d)); } catch (_) { /* private window: signed in for this tab only */ } }
  function dropDev() { try { localStorage.removeItem(KEY); } catch (_) { /* nothing kept */ } }
  let DEV = loadDev();

  class Cut extends Error {}
  async function api(method, path, body, raw) {
    const h = { 'X-Orch-Phone': DEV.id, Authorization: 'Bearer ' + DEV.token };
    let b;
    if (raw) { b = raw; h['Content-Type'] = raw.type || 'application/octet-stream'; } else if (body !== undefined) { b = JSON.stringify(body); h['Content-Type'] = 'application/json'; }
    const r = await fetch(path, { method, headers: h, body: b, credentials: 'omit', cache: 'no-store', referrerPolicy: 'no-referrer' });
    if (r.status === 401) throw new Cut();
    if (!r.ok) { let e = {}; try { e = await r.json(); } catch (_) { /* no body */ } const err = new Error((e.error && e.error.message) || 'Something went wrong. Try again.'); err.status = r.status; throw err; }
    return r.status === 204 ? null : r.json();
  }

  // ---- data ----
  const D = { ws: [], tickets: [], questions: [], messages: [], thread: [], loaded: false };
  const V = { id: null, shown: null, filter: 'all', answered: {}, answeredQ: {}, answerIds: {}, staged: null, sending: false, sendId: null, gen: 0 };

  function reachable(w) { return !!(w && w.last_seen && Date.now() - Date.parse(w.last_seen) <= FRESH_MS); }
  function wsById(id) { return D.ws.find((w) => w.id === id); }
  function tById(id) { return D.tickets.find((t) => t.id === id); }
  // Questions with no ticket in the list (a ticket proposal, or a ticket older than the newest 100) go to the
  // workspace's own conversation, so every open question can be answered.
  function looseQs(wsId) { return D.questions.filter((q) => q.message.from === wsId && !D.tickets.some((t) => t.ws === wsId && t.ticket === q.message.ticket)); }
  function qOpen(t) { return D.questions.filter((q) => q.message.from === t.ws && q.message.ticket === t.ticket && !V.answered[q.message.id]); }
  function status(t) {
    if (qOpen(t).length) return 'needs';
    const s = t.view && t.view.status;
    if (s === 'review') return 'review';
    if (s === 'done' || s === 'dropped') return 'done';
    return 'working';
  }
  function when(iso) {
    if (!iso) return '';
    const d = new Date(iso), now = new Date();
    const hm = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    if (d.toDateString() === now.toDateString()) return hm;
    const y = new Date(now); y.setDate(now.getDate() - 1);
    if (d.toDateString() === y.toDateString()) return 'Yesterday';
    if (now - d < 6 * 864e5) return d.toLocaleDateString([], { weekday: 'short' });
    return d.toLocaleDateString([], { day: 'numeric', month: 'short' });
  }

  async function loadAll() {
    const [ws, up, qs, ms] = await Promise.all([
      api('GET', '/v1/phone/workspaces'),
      api('GET', '/v1/phone/updates?limit=100'),
      api('GET', '/v1/phone/questions'),
      api('GET', '/v1/phone/messages?limit=200'),
    ]);
    D.ws = (Array.isArray(ws) ? ws : ws.items || []).map((w, i) => ({ ...w, c: COLORS[i % COLORS.length] }));
    D.tickets = (up.items || []).map((u) => ({
      id: u.workspace + '/' + u.ticket, ws: u.workspace, ticket: u.ticket, key: u.key || '',
      title: (u.ticket_view && u.ticket_view.title) || u.title || u.key || 'Ticket', view: u.ticket_view || null, at: u.at, last: u.text || '',
    }));
    D.questions = Array.isArray(qs) ? qs : qs.items || [];
    D.messages = Array.isArray(ms) ? ms : ms.items || [];
    D.loaded = true;
  }
  async function loadThread() {
    const t = tById(V.id), gen = V.gen;
    if (!t) { D.thread = []; return; }
    const r = await api('GET', '/v1/phone/updates?workspace=' + encodeURIComponent(t.ws) + '&ticket=' + encodeURIComponent(t.ticket) + '&limit=100');
    // Another conversation was opened while this one loaded: drop the answer, never show it under the wrong title.
    if (gen === V.gen) D.thread = r.items || [];
  }

  // ---- render ----
  const wsb = (w, size = 's32') => `<span class="wsb ${size}" data-c="${esc(w.c)}" aria-hidden="true"><b>${esc((w.name || '?').trim().charAt(0).toUpperCase())}</b></span>`;
  const reachDot = (w) => `<span class="dot ${reachable(w) ? 'ok' : 'idle'}" aria-hidden="true"></span>`;
  const badge = (st) => `<span class="badge ${st === 'review' ? 'needs' : st}">${STATUS[st]}</span>`;

  function questionCard(q, where) {
    const m = q.message, b = m.body || {}, qb = b.question || b;
    const t = D.tickets.find((x) => x.ws === m.from && x.ticket === m.ticket);
    const picked = V.answered[m.id];
    if (picked) {
      const waits = !reachable(wsById(m.from));
      return `<section class="qcard" data-phase="${waits ? 'pending' : 'sent'}"><h3>${esc(qb.title || qb.text)}</h3>
        <p class="qstatus ${waits ? 'notsent' : 'sent'}" role="status">${waits ? 'Your answer waits and is sent when the workspace is reachable again: ' : 'Answered from this browser: '}${esc(picked)}</p></section>`;
    }
    const opts = Array.isArray(qb.options) ? qb.options : [];
    const label = { accept: 'Accept', changes: 'Ask for changes', make: 'Make ticket', not_now: 'Not now' };
    const head = where === 'list' ? `<span class="badge needs">Needs you</span> ${esc(q.workspace_name || '')}${t ? ' · ' + esc(t.key) : ''}` : 'Question';
    return `<section class="qcard" aria-label="Question"><p class="qmeta meta">${head}</p>
      ${qb.title && qb.title !== qb.text ? `<h3>${esc(qb.title)}</h3><p class="muted">${esc(qb.text)}</p>` : `<h3>${esc(qb.text)}</h3>`}
      <div class="qoptions x-qoptions">${opts.map((o) => `<button type="button" class="btn qoption${o === qb.recommended ? ' suggested' : ''}" data-answer="${esc(o)}" data-q="${esc(m.id)}"><span>${esc(label[o] || o)}</span>${o === qb.recommended ? '<span class="suggested-label">Suggested</span>' : ''}</button>`).join('')}</div></section>`;
  }

  function threadItems() {
    const t = tById(V.id);
    const out = [];
    if (t) {
      for (const u of D.thread) out.push({ k: 'helper', at: u.at, text: u.text, kind: u.kind, id: u.id });
      for (const it of D.messages) { const m = it.message; if (m.from === DEV.id && m.to === t.ws && m.ticket === t.ticket) out.push({ k: 'me', at: m.created_at, text: (m.body && m.body.text) || '', files: m.body && m.body.attachments, delivered: it.delivered_at, id: m.id }); }
    } else {
      for (const it of D.messages) {
        const m = it.message;
        if (m.ticket) continue;
        if (m.from === DEV.id && m.to === V.id) out.push({ k: 'me', at: m.created_at, text: (m.body && m.body.text) || '', files: m.body && m.body.attachments, delivered: it.delivered_at, id: m.id });
        else if (m.from === V.id) out.push({ k: 'helper', at: m.created_at, text: (m.body && m.body.text) || '', id: m.id });
      }
    }
    const seen = new Set();
    return out.filter((x) => (seen.has(x.id) ? false : seen.add(x.id))).sort((a, b) => Date.parse(a.at) - Date.parse(b.at));
  }
  const fileChip = (f) => `<span class="file-chip"><span class="file-type">${esc(((f.name || '').split('.').pop() || 'file').slice(0, 4).toUpperCase())}</span><span><strong>${esc(f.name)}</strong><br><span class="meta">${esc(Math.max(1, Math.round((f.size || 0) / 1024)))} KB</span></span></span>`;

  function threadHtml() {
    const w = wsById(V.id) || wsById((tById(V.id) || {}).ws);
    let h = '';
    if (w && !reachable(w)) h += `<div class="banner attn x-banner" role="status"><div class="grow"><strong>${esc(w.name)} is not reachable right now</strong><p>The computer it runs on may be asleep. Your messages wait here and are sent when it is back.</p></div></div>`;
    const items = threadItems();
    if (!items.length) h += `<div class="empty"><p>${tById(V.id) ? 'Nothing here yet.' : 'Write here to start something new. Each new message starts a ticket.'}</p></div>`;
    for (const m of items) {
      if (m.k === 'me') h += `<div class="msg me"><p>${esc(m.text)}</p>${(m.files || []).map(fileChip).join('')}<p class="meta">${m.delivered ? esc(when(m.at)) + ' · Sent' : ic('clock', 12) + ' Waiting to send'}</p></div>`;
      else if (m.kind === 'ack' || m.kind === 'working') h += `<p class="meta x-step">${esc(m.text)}</p>`;
      else h += `<div class="msg"><p class="meta">${m.kind === 'result' ? '<span class="badge done">Result</span> ' : ''}Your helper · ${esc(when(m.at))}</p><p>${esc(m.text)}</p></div>`;
    }
    const t = tById(V.id);
    if (!t && wsById(V.id)) {
      const qs = looseQs(V.id);
      for (const q of Object.values(V.answeredQ)) if (q.message.from === V.id && !D.tickets.some((x) => x.ws === V.id && x.ticket === q.message.ticket) && !qs.some((x) => x.message.id === q.message.id)) qs.push(q);
      for (const q of qs) h += questionCard(q, 'thread');
    }
    if (t) {
      // An answered question leaves the open list at once; its card stays here with the answer for this visit.
      const qs = D.questions.filter((q) => q.message.from === t.ws && q.message.ticket === t.ticket);
      for (const q of Object.values(V.answeredQ)) if (q.message.from === t.ws && q.message.ticket === t.ticket && !qs.some((x) => x.message.id === q.message.id)) qs.push(q);
      for (const q of qs) h += questionCard(q, 'thread');
    }
    return `<div class="msgs">${h}</div>`;
  }

  function composerHtml() {
    const t = tById(V.id), w = wsById(V.id) || wsById(t && t.ws);
    if (!w) return '';
    const note = !reachable(w) ? 'Not reachable. Your message waits until it is back.' : !t ? 'A new message starts a new ticket.' : status(t) === 'done' ? 'Saved for the next run.' : 'Your helper reads it after the current step.';
    const to = t ? 'your helper' : w.name;
    return `<form class="x-composer" data-composer><div class="x-staged" data-staged>${V.staged ? fileChip(V.staged) : ''}</div><div class="x-composer-line">
      <label class="btn icon ghost" aria-label="Add a file">${ic('clip', 18)}<input type="file" class="sr-only" data-attach></label>
      <input class="input" name="text" autocomplete="off" maxlength="20000" aria-label="Message ${esc(to)}" placeholder="Message ${esc(to)}…"${V.sending ? ' readonly' : ''}>
      <button class="btn primary" type="submit"${V.sending ? ' disabled aria-busy="true"' : ''}>${ic('send', 16)}<span class="x-send-word">Send</span></button></div><p class="meta" data-note>${esc(note)}</p></form>`;
  }

  function render() {
    if (!V.id || (!tById(V.id) && !wsById(V.id))) V.id = (D.tickets[0] && D.tickets[0].id) || (D.ws[0] && D.ws[0].id) || null;
    const needs = D.tickets.filter((t) => status(t) === 'needs').length + D.ws.filter((w) => looseQs(w.id).some((q) => !V.answered[q.message.id])).length;
    let h = `<div class="segmented" role="group" aria-label="Show"><button type="button" class="btn" data-filter="all" aria-pressed="${V.filter === 'all'}">All</button><button type="button" class="btn" data-filter="needs" aria-pressed="${V.filter === 'needs'}">Needs you${needs ? ' <span class="count">' + needs + '</span>' : ''}</button></div>`;
    let any = false;
    for (const w of D.ws) {
      const ts = D.tickets.filter((t) => t.ws === w.id && (V.filter === 'all' || status(t) === 'needs'));
      const loose = looseQs(w.id).filter((q) => !V.answered[q.message.id]).length;
      if (V.filter === 'needs' && !ts.length && !loose) continue;
      any = true;
      h += `<section class="b-group" aria-label="${esc(w.name)}"><div class="b-group-h">${wsb(w, 's26')}<strong class="grow truncate">${esc(w.name)}</strong><span class="meta">${reachDot(w)} ${reachable(w) ? 'Online' : 'Not reachable'}</span></div>
        ${V.filter === 'all' || loose ? `<button type="button" class="b-row" data-open="${esc(w.id)}" aria-current="${V.id === w.id}"><span class="${loose ? 'dot needs' : 'b-ic muted'}" aria-hidden="true">${loose ? '' : ic('pencil', 16)}</span><span class="grow"><strong>New message</strong><span class="meta">${loose ? 'Waiting for your answer' : 'Starts a new ticket'}</span></span></button>` : ''}
        ${ts.map((t) => { const st = status(t); return `<button type="button" class="b-row" data-open="${esc(t.id)}" aria-current="${V.id === t.id}"><span class="dot ${st === 'needs' ? 'needs' : st === 'done' ? 'ok' : 'working'}" aria-hidden="true"></span><span class="grow"><strong class="truncate">${esc(t.title)}</strong><span class="meta truncate">${t.key ? '<span class="key">' + esc(t.key) + '</span> · ' : ''}${esc(st === 'needs' ? 'Waiting for your answer' : t.last)}</span></span><span class="meta a-side">${esc(when(t.at))}</span></button>`; }).join('')}</section>`;
    }
    if (!D.ws.length) h += `<div class="empty"><p>No workspace is shared with this browser yet.</p></div>`;
    else if (!any) h += `<div class="empty"><p>Nothing needs you right now.</p></div>`;
    $('#b-list').innerHTML = h;
    const off = D.ws.filter((w) => !reachable(w));
    $('#b-reach').innerHTML = off.length === 1 ? `<span class="badge">${reachDot(off[0])} ${esc(off[0].name)} is not reachable</span>` : off.length > 1 ? `<span class="badge"><span class="dot idle" aria-hidden="true"></span> ${off.length} workspaces are not reachable</span>` : '';
    const t = tById(V.id), w = wsById(V.id) || wsById(t && t.ws);
    const scroll = $('.b-scroll'), keep = scroll ? scroll.scrollTop : null;
    const draft = V.shown === V.id ? $('[data-composer] [name=text]') : null, draftText = draft ? draft.value : '', hadFocus = draft && document.activeElement === draft;
    V.shown = V.id;
    if (!w) { $('#b-thread').innerHTML = ''; return; }
    const v = t && t.view, done = v && typeof v.done === 'number' ? v.done : null, total = v && typeof v.total === 'number' ? v.total : null;
    $('#b-thread').innerHTML = `<header class="b-thread-h"><button type="button" class="btn icon ghost b-back" data-back aria-label="Back to the list">${ic('chevron-right', 18)}</button>
      <div class="grow"><h1 class="truncate">${esc(t ? t.title : w.name)}</h1><span class="meta truncate">${t ? (t.key ? '<span class="key">' + esc(t.key) + '</span> · ' : '') + 'Your helper · ' + esc(w.name) : 'A new message starts a new ticket'}</span></div>
      ${t ? badge(status(t)) + (total ? `<div class="b-steps"><span class="meta">${done} of ${total} steps done</span><div class="progress"><span data-value="${Math.round((done / total) * 100)}"></span></div></div>` : '') : ''}</header>
      <div class="b-scroll">${threadHtml()}</div><div class="b-compose">${composerHtml()}</div>`;
    // Inline style attributes are blocked by the page's content rules; set the few values through the DOM.
    $$('[data-c]').forEach((el) => el.style.setProperty('--c', el.dataset.c));
    $$('.progress [data-value]').forEach((el) => el.style.setProperty('--value', el.dataset.value + '%'));
    const ns = $('.b-scroll');
    if (ns) ns.scrollTop = keep == null ? ns.scrollHeight : keep;
    const nd = $('[data-composer] [name=text]');
    if (nd) { nd.value = draftText; if (hadFocus) nd.focus(); }
    const me = DEV.name || 'This browser';
    $('#me-name').textContent = me; $('#me-letter').textContent = me.charAt(0).toUpperCase(); $('#me-line').textContent = 'Signed in as ' + me;
  }

  function toast(text, bad) {
    let box = $('.toasts');
    if (!box) { box = document.createElement('div'); box.className = 'toasts'; box.setAttribute('role', 'status'); document.body.append(box); }
    box.innerHTML = `<div class="toast${bad ? ' bad' : ''}">${ic(bad ? 'x' : 'check', 16)}<span>${esc(text)}</span></div>`;
    clearTimeout(toast.t); toast.t = setTimeout(() => { box.innerHTML = ''; }, 5000);
  }

  function setState(st) {
    document.body.dataset.state = st;
    $$('[data-show]').forEach((el) => { el.hidden = !el.dataset.show.split(' ').includes(st); });
    $$('[data-signin]').forEach((b) => {
      const busy = st === 'signing';
      b.disabled = busy; b.setAttribute('aria-busy', String(busy));
      b.innerHTML = busy ? '<span class="spinner x-spin" aria-hidden="true"></span> Signing in…' : 'Sign in';
    });
  }
  function cut() { dropDev(); DEV = null; clearInterval(timer); setState('cut'); }

  let timer = null, busy = false;
  async function refresh(withThread) {
    if (busy || !DEV) return;
    busy = true;
    try { await loadAll(); if (withThread !== false) await loadThread(); render(); } catch (e) { if (e instanceof Cut) cut(); } finally { busy = false; }
  }
  async function startApp(welcome) {
    setState('app');
    clearInterval(timer);
    try { await loadAll(); render(); await loadThread(); render(); } catch (e) { if (e instanceof Cut) return cut(); toast('The relay could not be reached. Trying again.', true); }
    if (welcome) toast('You are signed in. This browser is called ' + (DEV.name || 'This browser') + '.');
    timer = setInterval(() => { if (!document.hidden) refresh(); }, POLL_MS);
    if (!startApp.seen) { startApp.seen = true; document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); }); }
  }

  // ---- sign in: the code is read from the part after # and sent only when the person presses Sign in ----
  function codeFromHash() {
    const m = /(?:^#|&)code=(pc_[A-Za-z0-9_-]+)/.exec(location.hash || ''); // base64url code (util::rand_token)
    return m ? m[1] : null;
  }
  // The code leaves the address bar and the history at once; until it is used it waits in this tab only, so a
  // reload before Sign in does not lose it.
  const PENDING = 'orch.relay.code';
  const keepCode = (c) => { try { if (c) sessionStorage.setItem(PENDING, c); else sessionStorage.removeItem(PENDING); } catch (_) { /* tab only */ } };
  let CODE = codeFromHash();
  if (CODE) { history.replaceState(null, '', location.pathname); keepCode(CODE); } else { try { CODE = sessionStorage.getItem(PENDING); } catch (_) { CODE = null; } }
  const useCode = () => { CODE = null; keepCode(null); };

  // Already signed in and a new invitation link was opened: its workspaces are added to this browser.
  // The code sent is the one cleared afterwards: a newer link opened meanwhile stays and is shown next.
  const useSent = (c) => { if (CODE === c) { useCode(); return false; } return true; };
  async function redeem() {
    setState('signing');
    const sent = CODE;
    try {
      const r = await api('POST', '/v1/phone/invitations/redeem', { code: sent });
      if (useSent(sent)) return setState('invite');
      await startApp(false);
      const names = (r.workspaces || []).map((w) => w.name).join(', ');
      toast(names ? 'You can now reach ' + names + '.' : 'The invitation was added.');
    } catch (x) {
      if (x instanceof Cut) return cut();
      if (x.status === 404 || x.status === 410) { if (useSent(sent)) return setState('invite'); await startApp(false); return toast('This invitation no longer works. Ask for a new link.', true); }
      setState('invite');
      const err = $('[data-signin-error]'); err.textContent = 'Signing in did not work. Check the connection and press Sign in again.'; err.hidden = false;
    }
  }
  async function signIn() {
    if (!CODE) return setState('nocode');
    if (DEV) return redeem();
    setState('signing');
    const err = $('[data-signin-error]'); err.hidden = true;
    const sent = CODE;
    try {
      const r = await fetch('/v1/phone/pair', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ code: sent, name: 'Browser' }), credentials: 'omit', cache: 'no-store', referrerPolicy: 'no-referrer' });
      if (r.status === 401 || r.status === 404 || r.status === 410) { return setState(useSent(sent) ? 'invite' : 'used'); }
      if (!r.ok) throw new Error('pair ' + r.status);
      const j = await r.json();
      const newer = useSent(sent);
      DEV = { id: j.phone_id, token: j.token, name: j.name || '' };
      saveDev(DEV);
      if (newer) return setState('invite'); // signed in; the newer link adds its workspaces on Sign in
      startApp(true);
    } catch (_) {
      setState('invite');
      err.textContent = 'Signing in did not work. Check the connection and press Sign in again.'; err.hidden = false;
    }
  }

  // ---- events ----
  document.addEventListener('click', async (e) => {
    const el = e.target.closest('[data-signin],[data-answer],[data-signout],[data-signout-yes],[data-close-dialog],[data-open],[data-back],[data-filter]');
    if (!el) return;
    if (el.matches('[data-signin]')) return signIn();
    if (el.matches('[data-open]')) { if (V.sending) return; V.id = el.dataset.open; V.gen += 1; V.staged = null; V.sendId = null; document.body.dataset.pane = 'thread'; D.thread = []; render(); try { await loadThread(); render(); } catch (x) { if (x instanceof Cut) cut(); } return; }
    if (el.matches('[data-back]')) { document.body.dataset.pane = 'list'; return render(); }
    if (el.matches('[data-filter]')) { V.filter = el.dataset.filter; return render(); }
    if (el.matches('[data-answer]')) {
      const qid = el.dataset.q, ans = el.dataset.answer;
      $$(`[data-q="${CSS.escape(qid)}"]`).forEach((b) => { b.disabled = true; });
      try {
        const id = (V.answerIds[qid] = V.answerIds[qid] || cid()); // a retry of the same answer is not a second one
        await api('POST', '/v1/phone/answer', { question_message_id: qid, answer: ans, client_id: id });
        V.answered[qid] = ans;
        const q = D.questions.find((x) => x.message.id === qid); if (q) V.answeredQ[qid] = q;
        render(); refresh();
      } catch (x) {
        if (x instanceof Cut) return cut();
        if (x.status === 409) { toast(x.message, true); refresh(); return; }
        $$(`[data-q="${CSS.escape(qid)}"]`).forEach((b) => { b.disabled = false; });
        toast(x.message, true);
      }
      return;
    }
    if (el.matches('[data-signout]')) { $$('details[open]').forEach((d) => { d.open = false; }); return $('#signout').showModal(); }
    if (el.matches('[data-close-dialog]')) return el.closest('dialog').close();
    if (el.matches('[data-signout-yes]')) {
      $$('dialog[open]').forEach((d) => d.close());
      try { await api('POST', '/v1/phone/signout'); } catch (x) {
        // 401 = the relay already signed it out. Anything else: the token still works, so stay and say it.
        if (!(x instanceof Cut)) { toast('Signing out did not work. Check the connection and try again.', true); return; }
      }
      dropDev(); DEV = null; clearInterval(timer); setState('left');
    }
  });
  document.addEventListener('input', (e) => { if (e.target.matches('[data-composer] [name=text]') && !V.sending) V.sendId = null; });
  document.addEventListener('change', (e) => {
    if (!e.target.matches('[data-attach]')) return;
    if (V.sending) { e.target.value = ''; return; }
    V.sendId = null;
    const f = e.target.files[0]; if (!f) return;
    if (f.size > 25 * 1024 * 1024) { toast('This file is bigger than 25 MB.', true); e.target.value = ''; return; }
    V.staged = { file: f, name: f.name, size: f.size };
    $('[data-staged]').innerHTML = fileChip(V.staged);
  });
  document.addEventListener('submit', async (e) => {
    const f = e.target.closest('[data-composer]'); if (!f) return;
    e.preventDefault();
    const text = f.elements.text.value.trim();
    if ((!text && !V.staged) || V.sending) return;
    // Everything is read once here: switching the conversation or picking another file while it sends changes nothing.
    const t = tById(V.id), to = t ? t.ws : V.id, staged = V.staged, convo = V.id;
    V.sendId = V.sendId || cid(); // kept for a retry of this same message, so a lost answer never makes a second one
    const sendId = V.sendId;
    V.sending = true; f.querySelector('[type=submit]').disabled = true;
    f.elements.text.readOnly = true; // the text sent and a retry of it stay the same; nothing typed meanwhile is lost
    try {
      const body = { to, client_id: sendId };
      if (text) body.text = text;
      if (t) body.ticket = t.ticket;
      if (staged) {
        if (!staged.blob) staged.blob = await api('POST', '/v1/phone/blobs', undefined, staged.file);
        const mime = /^[a-z]+\/[a-z0-9.+-]+$/i.test(staged.file.type) ? staged.file.type : 'application/octet-stream';
        body.attachments = [{ blob_id: staged.blob.blob_id, kind: mime.startsWith('image/') ? 'image' : 'file', name: staged.name.slice(0, 255) || 'file', size: staged.blob.size, mime }];
      }
      await api('POST', '/v1/phone/send', body);
      V.sendId = null;
      if (V.staged === staged) V.staged = null;
      const box = V.id === convo ? $('[data-composer] [name=text]') : null; if (box) { box.value = ''; box.readOnly = false; }
      V.sending = false;
      await refresh();
      const inp = $('[data-composer] [name=text]'); if (inp) inp.focus();
    } catch (x) {
      V.sending = false;
      if (x instanceof Cut) return cut();
      for (const form of new Set([f, $('[data-composer]')])) if (form) { form.querySelector('[type=submit]').disabled = false; form.elements.text.readOnly = false; }
      toast(x.message, true);
    }
  });

  // ---- start ----
  // A new invitation link opened in this same tab only changes the part after # (no reload).
  window.addEventListener('hashchange', () => {
    const c = codeFromHash(); if (!c) return;
    history.replaceState(null, '', location.pathname); CODE = c; keepCode(c);
    clearInterval(timer); $$('dialog[open]').forEach((d) => d.close()); setState('invite');
  });
  if (DEV && !CODE) startApp(false);
  else setState(CODE ? 'invite' : 'nocode');
})();
