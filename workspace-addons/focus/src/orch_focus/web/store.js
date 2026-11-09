// Owns shared DOM, environment, state, and registry; textContent, never innerHTML.
(function () {
  'use strict';
  const root = document.getElementById('fx');
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const ic = (n, s = 16) => (window.icon ? window.icon(n, s) : '');
  const m = location.pathname.match(/\/(t_[a-z0-9]{6,16})$/);
  const TID = m && m[1];
  const P = document.documentElement.dataset.prefix || '';  // set when the dashboard shows this page under its own address
  const INAPP = !!P;

  function h(tag, attrs, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === false || v == null) continue;
      if (k === 'class') el.className = v;
      else if (k === 'text') el.textContent = v;
      else if (k === 'icon') el.innerHTML = ic(v);
      else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v === true ? '' : v);
    }
    for (const kid of kids.flat()) if (kid != null) el.append(kid);
    return el;
  }
  function helpPanel() {
    const keys = groups => groups.map(([heading, rows]) => h('section', {}, h('h3', {text: heading}), h('dl', {}, rows.map(([label, key]) => h('div', {}, h('dt', {text: label}), h('dd', {}, h('kbd', {text: key})))))));
    return h('div', {class: 'fx-help', id: 'fx-help', hidden: true}, h('div', {class: 'fx-help-card', role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': 'fx-help-t'},
      h('p', {class: 'meta', text: 'Focus help'}), h('div', {class: 'row'}, h('h2', {id: 'fx-help-t', class: 'grow', text: 'A few useful keys'}), h('button', {class: 'btn ghost icon', 'data-act': 'help', 'aria-label': 'Close', icon: 'x'})),
      h('p', {class: 'meta', text: 'Everything is also a click away.'}), h('div', {class: 'fx-help-grid'}, keys([
        ['Move around', [['Show help', '?'], ['Close a panel', 'Esc'], ['Next control', 'Tab'], ['Show or hide tasks', '['], ['Full screen', 'F'], ['Live · Results', '1 / 2']]],
        ['Write and choose', [['Write a message', '/'], ['Send a message', 'Enter'], ['Choose a button', 'Space'], ['Stop or continue', 'S'], ['Next or previous task', 'J / K']]],
      ]))));
  }
  // Own copy of the dashboard status words; started + idle is Paused.
  const STATUS_WORD = {open: 'Not started', ready: 'Not started', active: 'Working', waiting: 'Needs you', review: 'Ready for review', done: 'Done', dropped: 'Dropped'};
  const statusWord = t => (t.started && ['open', 'ready', 'idle'].includes(t.status)) ? 'Paused' : STATUS_WORD[t.status] || 'Not started';
  const toast = (text, kind) => (window.orch ? window.orch.toast(text, kind) : null);
  const proof = window.FocusProof.create({h, ic, P, TID, toast});

  // Embedded under the dashboard (P = "/addon/focus"): a person's click is sent to the dashboard's own act
  // endpoint, which holds the page session and mints the proof (H1). Focus never trusts forwarded headers.
  const EMBED_HUMAN = new Set(['answer', 'ticket.done', 'run.send', 'check.wont_do', 'check.reopen', 'check.edit', 'check.remove']);
  async function actEmbedded(op, args) {
    const dop = op === 'ticket.done' ? 'ticket.patch' : op;
    const dargs = op === 'ticket.done' ? {ticket: args.ticket, data: {status: 'done'}, if_revision: args.if_revision} : args;
    let r;
    try {
      r = await fetch('/api/act', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({op: dop, args: dargs})});
    } catch (e) { return {ok: false, status: 0, message: 'Could not reach the dashboard.'}; }
    if (!r.ok) return {ok: false, status: r.status, message: (await r.text()).slice(0, 300)};
    try { await store.poll(); } catch (e) { /* the next poll shows it */ }
    return {ok: true, status: r.status, result: null, note: null};
  }

  async function act(op, args) {
    if (P && EMBED_HUMAN.has(op)) return actEmbedded(op, args);
    let r;
    try {
      r = await fetch(P + '/api/act', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({op, args})});
    } catch (e) { return {ok: false, status: 0, message: 'Could not reach Focus.'}; }
    if (r.ok) { const d = await r.json(); if (d.view) store.apply(d.view); return {ok: true, status: r.status, result: d.result, note: d.note}; }
    return {ok: false, status: r.status, message: (await r.text()).slice(0, 300)};
  }

  const els = {};
  const STATE = {needs: 'Needs you', waiting: 'Paused', stopped: 'Paused', done: 'Done'};

  const hhmm = at => { try { return new Date(at).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit', hour12: false}); } catch (e) { return ''; } };
  const evText = c => window.FocusHelpers.outcome(c);
  // When a proof was added, in the person's own time: "today 16:05", "yesterday 09:12", "5 Nov 09:12".
  function stamp(at) {
    const d = new Date(at), now = new Date();
    if (!at || isNaN(d.getTime())) return '';
    const day = x => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
    const diff = Math.round((day(now) - day(d)) / 86400000), t = hhmm(at);
    if (diff === 0) return 'today ' + t;
    if (diff === 1) return 'yesterday ' + t;
    return d.getDate() + ' ' + ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][d.getMonth()] + (d.getFullYear() !== now.getFullYear() ? ' ' + d.getFullYear() : '') + ' ' + t;
  }
  const keyOf = o => JSON.stringify(o);

  // a raw actor id inside a line ("agent:<name> finished the work") is shown as its name, like the dashboard's plainNames()
  const plainNames = text => String(text ?? '').replace(/\b(?:agent|human):([A-Za-z0-9_.@-]+)/g, (_, n) => n.charAt(0).toUpperCase() + n.slice(1));

  const state = {
    view: null, sel: 0, firstRender: true, shownQs: new Map(), lastFeedKey: '',
    tab: 0, changesRequested: false, prevQuestionLabel: undefined,
    workedBase: 0, workedAt: 0, clockWorking: false,
  };
  const subscribers = new Set();
  const store = window.FocusStore = {
    root, reduce, ic, TID, P, INAPP, h, toast, helpPanel, STATUS_WORD, statusWord, STATE,
    hhmm, stamp, keyOf, plainNames, evText, els, act, proof, state, views: {},
    register(name, def) { store.views[name] = def; },
    subscribe(fn) { subscribers.add(fn); return () => subscribers.delete(fn); },
    notify(v) { for (const fn of subscribers) fn(v); },
  };
})();
