/* Focus: a live page for one ticket. Everything the page shows comes from /api/t/<id>; everything it does goes
   through POST /api/act (the fixed op table). All text is set with textContent, never innerHTML. */
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
  const toast = (text, kind) => (window.orch ? window.orch.toast(text, kind) : null);

  async function act(op, args) {
    let r;
    try {
      r = await fetch(P + '/api/act', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({op, args})});
    } catch (e) { return {ok: false, status: 0, message: 'Could not reach Focus.'}; }
    if (r.ok) { const d = await r.json(); if (d.view) apply(d.view); return {ok: true, status: r.status, result: d.result, note: d.note}; }
    return {ok: false, status: r.status, message: (await r.text()).slice(0, 300)};
  }

  /* ---- ticket picker (no ticket in the address) ---- */
  if (!TID) {
    document.title = 'Focus · orch';
    root.append(h('div', {class: 'fx-pick'}, h('h1', {text: 'Focus'}), h('p', {class: 'meta', text: 'Pick a ticket to watch.'})));
    fetch(P + '/api/tickets').then(r => r.json()).then(list => {
      const box = root.querySelector('.fx-pick');
      if (!list.length) box.append(h('p', {class: 'muted', text: 'No open tickets.'}));
      for (const t of list) box.append(h('a', {href: P + '/t/' + t.id}, h('span', {class: 'mono key', text: t.id}), h('span', {class: 'grow', text: t.title}), h('span', {class: 'meta', text: t.status})));
    });
    return;
  }

  /* ---- skeleton ---- */
  const els = {};
  let view = null, sel = 0, firstRender = true, shownQs = new Map(), lastFeedKey = '', tab = 0, helpOpen = false;
  const STATE = {needs: 'needs you', stopped: 'stopped', done: 'done'};

  function build() {
    els.rail = h('button', {class: 'btn ghost icon sm', 'data-act': 'rail', 'aria-label': 'Show or hide tasks', 'aria-expanded': 'true', title: 'Tasks ( [ )', icon: 'table'});
    els.key = h('span', {class: 'mono key', text: TID});
    els.title = h('h1', {text: ''});
    els.count = h('span', {text: ''});
    els.bar = h('span');
    els.prog = h('div', {class: 'progress', role: 'progressbar', 'aria-label': 'Tasks done', 'aria-valuemin': '0'}, els.bar);
    els.agent = h('b', {text: 'Agent'});
    els.stateText = h('span', {text: ''});
    els.time = h('span', {class: 't', text: ''});
    els.live = h('span', {class: 'fx-live', role: 'status', 'aria-live': 'polite'}, h('span', {class: 'fx-dot'}), els.agent, els.stateText, els.time);
    els.stopIc = h('span');
    els.stopL = h('span', {class: 'opt', text: 'Stop'});
    els.stop = h('button', {class: 'btn ghost sm', 'data-act': 'stop', title: 'Stop or continue (S)'}, els.stopIc, els.stopL);
    els.fresh = h('button', {class: 'btn ghost sm opt', 'data-act': 'fresh', title: 'Start again without the earlier conversation', text: 'Start fresh instead', hidden: true});
    els.attachBtn = h('button', {class: 'btn ghost sm', 'data-act': 'attach', title: 'Open the live session', hidden: true}, h('span', {icon: 'external'}), h('span', {class: 'opt', text: 'Open live session'}));
    els.full = h('button', {class: 'btn ghost icon sm', 'data-act': 'full', 'aria-label': 'Full screen', 'aria-pressed': 'false', title: 'Full screen (F)', icon: 'expand'});
    els.helpBtn = h('button', {class: 'btn ghost icon sm', 'data-act': 'help', 'aria-label': 'Keyboard shortcuts', title: 'Shortcuts (?)'}, h('kbd', {text: '?'}));
    const top = h('header', {class: 'fx-top'}, els.rail, h('div', {class: 'fx-title'}, els.key, els.title), h('div', {class: 'fx-prog'}, els.count, els.prog), els.live,
      h('div', {class: 'fx-tools'}, els.stop, els.fresh, els.attachBtn, h('span', {class: 'sep opt'}), els.full, els.helpBtn, h('a', {class: 'btn ghost sm', href: INAPP ? '/#ticket/' + TID : '/', target: INAPP ? '_top' : '_self', title: INAPP ? 'Back to the ticket' : 'All tickets'}, h('span', {icon: 'x'}), h('span', {class: 'opt', text: 'Exit'}))));
    els.tasks = h('div', {id: 'fx-tasks'});
    els.helpers = h('div');
    els.railNote = h('p', {class: 'meta', style: false});
    const rail = h('aside', {class: 'fx-rail', 'aria-label': 'Tasks'}, h('div', {}, h('p', {class: 'eyebrow'}, h('span', {text: 'Tasks'}), els.railCount = h('span')), els.tasks), els.helpers, els.railNote);
    els.tabs = [['live', 'Live'], ['proof', 'Proof']].map(([id, label], i) => h('button', {class: 'fx-tab', role: 'tab', id: 'fx-t-' + id, 'aria-controls': 'fx-p-' + id, 'aria-selected': String(i === 0), tabindex: i ? '-1' : '0', title: label + ' (' + (i + 1) + ')', 'data-tab': i, text: label}));
    els.sub = h('span', {class: 'meta', text: ''});
    els.feed = h('div', {class: 'fx-feed', role: 'log', 'aria-label': 'What the agent is doing'});
    els.working = h('div', {class: 'fx-working', hidden: true});
    els.line = h('div');
    els.qs = h('div', {class: 'fx-qwrap'});
    els.paneLive = h('div', {class: 'fx-pane', id: 'fx-p-live', role: 'tabpanel', 'aria-labelledby': 'fx-t-live'}, els.line, els.feed, els.qs, els.working);
    els.paneProof = h('div', {class: 'fx-pane', id: 'fx-p-proof', role: 'tabpanel', 'aria-labelledby': 'fx-t-proof', hidden: true});
    els.attachBox = h('div', {class: 'fx-attach', hidden: true});
    els.msg = h('textarea', {id: 'fx-msg', rows: '1', placeholder: 'Message the agent…', 'aria-label': 'Message to the agent'});
    els.form = h('form', {id: 'fx-form'}, els.msg, h('button', {class: 'btn primary sm', 'aria-label': 'Send', icon: 'send'}));
    els.hint = h('p', {class: 'hint'}, h('span', {}, h('kbd', {text: 'Enter'}), ' send'), h('span', {}, h('kbd', {text: '/'}), ' write'), h('span', {}, h('kbd', {text: '?'}), ' all shortcuts'), els.hintNote = h('span'));
    els.sent = h('p', {class: 'meta', 'aria-live': 'polite'});
    const compose = h('div', {class: 'fx-compose'}, els.form, els.hint);
    const dl = [['Full screen', 'F'], ['Show or hide tasks', '['], ['Write a message', '/'], ['Stop or continue', 'S'], ['Live · Proof', '1 2'], ['Next or previous task', 'J K'], ['Close, leave full screen', 'Esc']];
    els.help = h('div', {class: 'fx-help', id: 'fx-help', hidden: true}, h('div', {class: 'fx-help-card', role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': 'fx-help-t'},
      h('div', {class: 'row'}, h('h2', {id: 'fx-help-t', class: 'grow', text: 'Shortcuts'}), h('button', {class: 'btn ghost icon xs', 'data-act': 'help', 'aria-label': 'Close', icon: 'x'})),
      h('dl', {}, dl.map(([t, k]) => h('div', {}, h('dt', {text: t}), h('dd', {}, k.split(' ').map(x => h('kbd', {text: x}))))))));
    const stage = h('section', {class: 'fx-stage', 'aria-label': 'Agent'}, h('div', {class: 'fx-stage-h', role: 'tablist', 'aria-label': 'Agent view'}, els.tabs, h('span', {class: 'grow'}), els.sub), h('div', {class: 'fx-scan', 'aria-hidden': 'true'}), els.attachBox, els.paneLive, els.paneProof, compose, els.help);
    root.replaceChildren(top, h('div', {class: 'fx-body'}, rail, stage));
    els.stopIc.innerHTML = ic('pause');
    root.querySelectorAll('[data-icon]').forEach(e => { e.innerHTML = ic(e.dataset.icon); });
  }

  /* ---- render ---- */
  const hhmm = at => { try { return new Date(at).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit', hour12: false}); } catch (e) { return ''; } };
  function evText(c) { const ev = (c.evidence || []).slice(-1)[0]; return ev ? String(ev.summary || ev.text || ev.ref || '') : ''; }
  const keyOf = o => JSON.stringify(o);

  function apply(v) {
    const prev = view;
    view = v;
    const t = v.ticket;
    document.title = t.title + ' · Focus';
    els.title.textContent = t.title || '';
    root.dataset.state = v.state;
    if (prev && !root.hasAttribute('data-live')) root.setAttribute('data-live', '');  /* motion only after a live change */
    els.agent.textContent = v.run.agent === 'agent' ? 'Agent' : v.run.agent.charAt(0).toUpperCase() + v.run.agent.slice(1);
    els.stateText.textContent = v.state === 'working' ? (v.generic ? 'running' : 'working') : STATE[v.state];
    els.count.textContent = v.done + ' of ' + v.total;
    els.bar.style.width = (v.total ? Math.round(v.done / v.total * 100) : 0) + '%';
    els.prog.setAttribute('aria-valuemax', String(v.total));
    els.prog.setAttribute('aria-valuenow', String(v.done));
    els.railCount.textContent = v.done + '/' + v.total;
    const running = v.run.running;
    els.stopIc.innerHTML = ic(running ? 'pause' : 'play');
    els.stopL.textContent = running ? 'Stop' : (v.state === 'done' ? 'Start again' : 'Continue');
    els.fresh.hidden = running;
    els.attachBtn.hidden = !(running && v.live);
    els.sub.textContent = running ? (v.live ? 'live session' : 'one run') : (v.run.run ? 'last run ended' : 'not started');
    els.msg.placeholder = 'Message ' + els.agent.textContent + '…';
    els.hintNote.textContent = v.generic && !(running && v.live) ? 'Saved for the next run.' : (running ? 'Goes in after this step.' : '');
    els.railNote.textContent = v.generic ? 'This agent shows its tasks and questions as it ticks them off.' : '';
    renderTasks(v);
    renderHelpers(v);
    renderFeed(v, !firstRender);
    renderQuestions(v);
    renderProof(v);
    renderLine(v);
    els.working.hidden = !(running && v.board.step);
    els.working.replaceChildren(...(running && v.board.step ? [h('span', {class: 'fx-dot'}), h('span', {text: v.board.step})] : []));
    tickTimer();
    firstRender = false;
  }

  function renderTasks(v) {
    const checks = v.ticket.checklist;
    const doing = checks.findIndex(c => !c.done && c.state === 'doing');
    if (sel >= checks.length) sel = Math.max(0, checks.length - 1);
    const key = keyOf([checks.map(c => [c.id, c.text, c.done, c.state, evText(c)]), sel, v.run.running]);
    if (key === els.tasks.dataset.k) return;
    els.tasks.dataset.k = key;
    els.tasks.replaceChildren(...checks.flatMap((c, i) => {
      const cls = c.done ? 'done' : (c.state === 'doing' ? 'doing' : '');
      const row = h('button', {class: 'fx-task ' + cls, 'data-task': String(i), 'aria-current': String(i === (sel === 0 && doing >= 0 && !els.tasks.dataset.picked ? doing : sel))},
        h('span', {class: 'st', icon: c.done ? 'check' : false}), h('span', {}, h('span', {class: 'tt', text: c.text}), h('span', {class: 'sub', text: c.done ? evText(c) : (c.state === 'doing' ? 'working on it' : '')})));
      row.addEventListener('click', () => { sel = i; els.tasks.dataset.picked = '1'; els.tasks.dataset.k = ''; renderTasks(view); });
      const out = [row];
      if (els.tasks.dataset.picked && i === sel) out.push(taskTools(c, i, checks));
      return out;
    }));
    if (!checks.length) els.tasks.append(h('p', {class: 'meta', text: 'No tasks yet.'}));
  }

  function taskTools(c, i, checks) {
    const base = {ticket: TID, check: c.id};
    const btn = (label, fn, extra) => h('button', {class: 'btn ghost xs', text: label, onclick: fn, ...(extra || {})});
    const res = async (p, ok) => { const r = await p; if (!r.ok) toast(r.status === 409 ? 'This task changed meanwhile. Check it and try again.' : r.message, 'error'); else if (ok) toast(ok, 'ok'); };
    const tools = h('div', {class: 'fx-task-tools'},
      btn('Rename', () => {
        const input = h('input', {class: 'input', value: c.text, 'aria-label': 'Task text', maxlength: '200'});
        const form = h('form', {class: 'fx-task-edit'}, input, h('button', {class: 'btn primary xs', text: 'Save'}));
        form.addEventListener('submit', e => { e.preventDefault(); const t = input.value.trim(); if (t && t !== c.text) res(act('check.edit', {...base, text: t, was: c.text, if_revision: view.ticket.revision})); form.remove(); });
        tools.after(form); input.focus();
      }),
      i > 0 && btn('Move up', () => res(act('check.move', {ticket: TID, check: checks[i - 1].id, after: c.id}))),
      i < checks.length - 1 && btn('Move down', () => res(act('check.move', {...base, after: checks[i + 1].id}))),
      c.done && btn('Open again', () => res(act('check.reopen', base))),
      btn('Remove', () => res(act('check.remove', base), 'Removed. It stays in the history.')));
    return tools;
  }

  function renderHelpers(v) {
    const hs = v.board.helpers;
    els.helpers.replaceChildren(...(hs.length ? [h('div', {}, h('p', {class: 'eyebrow'}, h('span', {text: 'Helpers'}), h('span', {text: String(hs.length)})),
      ...hs.map(x => h('div', {class: 'fx-helper'}, h('div', {class: 'row'}, h('span', {class: 'dot working'}), h('span', {class: 'grow', text: x.text})))))] : []));
  }

  function feedItems(v) {
    const items = [];
    for (const e of v.ticket.history || []) items.push({at: e.at, icon: /Asked|waiting/.test(e.text) ? 'note' : (/done/.test(e.text) ? 'check' : 'text'), ok: /done/.test(e.text), text: e.text, who: e.by, you: /^human:/.test(e.by || '') && e.via !== 'cli'});
    for (const e of v.events) {
      if (e.kind === 'tool.start') items.push({at: e.at, icon: 'text', text: e.text});
      else if (e.kind === 'tool.end') items.push({at: e.at, icon: e.data.ok === false ? 'x' : 'check', ok: e.data.ok !== false, text: e.text});
      else if (e.kind === 'helper.start') items.push({at: e.at, icon: 'user', text: 'Helper: ' + e.text});
      else if (e.kind === 'helper.end') items.push({at: e.at, icon: 'check', ok: true, text: 'Helper done: ' + e.text});
    }
    items.sort((a, b) => String(a.at).localeCompare(String(b.at)));
    return items.slice(-80);
  }

  function renderFeed(v, animate) {
    const items = feedItems(v);
    const key = keyOf(items.map(i => [i.at, i.text]));
    if (key === lastFeedKey) return;
    const oldN = els.feed.children.length;
    lastFeedKey = key;
    els.feed.replaceChildren(...items.map((it, i) => {
      const fresh = animate && !reduce && i >= oldN && i === items.length - 1;
      return h('div', {class: 'fx-step' + (i === items.length - 1 && v.run.running ? ' now' : '') + (fresh ? ' enter' : '')}, h('time', {text: hhmm(it.at)}), h('span', {class: 'ic' + (it.ok ? ' good' : ''), icon: it.icon}), h('div', {}, h('span', {class: 'what', text: it.text})));
    }));
    if (!items.length) els.feed.append(h('p', {class: 'fx-empty muted', text: v.run.running ? 'Waiting for the first step…' : 'Nothing has happened yet. Press Continue to start the agent.'}));
    els.paneLive.scrollTop = els.paneLive.scrollHeight;
  }

  function renderQuestions(v) {
    const open = v.ticket.questions.filter(q => q.answer == null);
    const ids = new Set(open.map(q => q.id));
    for (const [id, card] of shownQs) if (!ids.has(id)) { card.node.remove(); shownQs.delete(id); }
    for (const q of open) {
      if (shownQs.has(q.id)) continue;
      const node = h('div', {'data-row': '', class: 'fx-ask-wrap'});
      els.qs.append(node);
      const options = (q.options || []).map(o => ({text: o, suggested: o === q.recommended}));
      const question = {ticket: TID, id: q.id, title: (els.agent.textContent || 'The agent') + ' asks', text: q.text, options};
      if (window.QuestionCard) {
        window.QuestionCard.mount(node, question, {send: async (answer) => {
          const r = await act('answer', {ticket: TID, question: q.id, answer});
          return r.ok ? {status: 200, who: 'you', via: 'focus'} : {status: r.status === 409 ? 409 : (r.status || 0), message: r.message};
        }});
      }
      shownQs.set(q.id, {node});
      if (!firstRender && window.orch) window.orch.needsIn(node);
    }
  }

  function renderProof(v) {
    const done = v.ticket.checklist.filter(c => c.done);
    const chips = [];
    for (const c of done) for (const ev of c.evidence || []) chips.push({c, ev});
    const key = keyOf(chips.map(x => [x.c.id, x.ev.ref, x.ev.summary]));
    els.tabs[1].textContent = 'Proof';
    if (chips.length) els.tabs[1].append(h('sup', {text: ' ' + chips.length}));
    if (key === els.paneProof.dataset.k) return;
    els.paneProof.dataset.k = key;
    els.paneProof.replaceChildren(chips.length
      ? h('div', {class: 'fx-chips'}, chips.map(({c, ev}) => { const wrap = h('div', {title: c.text}); wrap.innerHTML = window.Evidence ? window.Evidence.chip(ev, {}) : ''; return wrap; }))
      : h('p', {class: 'fx-empty muted', text: 'Proof shows here when a task is done.'}));
  }

  function renderLine(v) {
    const u = v.board.usage, d = v.board.denials;
    const lines = [];
    if (u) lines.push(h('p', {class: 'fx-line ' + (u.status === 'limited' ? 'bad' : 'warn'), text: u.text}));
    if (v.attention) lines.push(h('p', {class: 'fx-line warn'}, (v.why || 'Waiting for your OK in the live session.') + ' ', h('button', {class: 'btn ghost xs', 'data-act': 'attach', text: 'Open live session'})));
    if (v.retry_error) lines.push(h('p', {class: 'fx-line bad', text: 'Could not run it again: ' + v.retry_error}));
    if (d.length) lines.push(h('p', {class: 'fx-line warn', text: d[d.length - 1].text + '. It waits for your OK.'}));
    els.line.replaceChildren(...lines);
  }

  /* ---- timer ---- */
  function tickTimer() {
    const v = view;
    if (!v || !v.run.running || !v.run.started_at) { els.time.textContent = ''; return; }
    const s = Math.max(0, Math.floor((Date.now() - Date.parse(v.run.started_at)) / 1000));
    els.time.textContent = Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0');
  }
  setInterval(() => { if (view && view.state === 'working') tickTimer(); }, 1000);

  /* ---- actions ---- */
  async function stopToggle() {
    if (!view) return;
    const r = view.run.running ? await act('run.stop', {ticket: TID}) : await act('run.start', {ticket: TID});
    if (!r.ok) toast(r.message, 'error'); else toast(view.run.running ? 'Started. Same conversation.' : 'Stopped. The work done so far is kept.', 'ok');
  }
  async function startFresh() { const r = await act('run.start', {ticket: TID, fresh: true}); if (!r.ok) toast(r.message, 'error'); else toast('Started fresh from the ticket.', 'ok'); }
  function showAttach() {
    const cmd = 'orch run attach ' + TID + ' --watch';
    els.attachBox.hidden = !els.attachBox.hidden;
    els.attachBox.replaceChildren(h('span', {class: 'meta', text: 'Watch the live session in a terminal:'}), h('code', {class: 'mono', text: cmd}),
      h('button', {class: 'btn ghost xs', text: 'Copy', onclick: () => { try { navigator.clipboard.writeText(cmd); toast('Copied.', 'ok'); } catch (e) { /* select by hand */ } }}));
  }

  function wire() {
    const markFull = on => { root.classList.toggle('is-full', on); els.full.setAttribute('aria-pressed', String(on)); els.full.setAttribute('aria-label', on ? 'Leave full screen' : 'Full screen'); document.body.style.overflow = on ? 'hidden' : ''; };
    const setFull = async on => {
      if (on) { try { await root.requestFullscreen?.(); } catch (e) { /* CSS fallback */ } markFull(true); }
      else { if (document.fullscreenElement) { try { await document.exitFullscreen(); } catch (e) { /* ignore */ } } markFull(false); }
    };
    document.addEventListener('fullscreenchange', () => { if (!document.fullscreenElement && root.classList.contains('is-full')) markFull(false); });
    const toggleRail = () => { const closed = root.classList.toggle('rail-closed'); els.rail.setAttribute('aria-expanded', String(!closed)); };
    if (matchMedia('(max-width: 720px)').matches) toggleRail();
    const toggleHelp = force => { els.help.hidden = force === undefined ? !els.help.hidden : !force; if (!els.help.hidden) els.help.querySelector('button').focus(); };
    const selectTab = i => els.tabs.forEach((b, j) => { const on = i === j; b.setAttribute('aria-selected', String(on)); b.tabIndex = on ? 0 : -1; document.getElementById(b.getAttribute('aria-controls')).hidden = !on; });
    els.tabs.forEach((b, i) => b.addEventListener('click', () => selectTab(i)));
    root.addEventListener('click', e => {
      const a = e.target.closest('[data-act]')?.dataset.act;
      if (a === 'rail') toggleRail(); else if (a === 'full') setFull(!root.classList.contains('is-full')); else if (a === 'help') toggleHelp();
      else if (a === 'stop') stopToggle(); else if (a === 'fresh') startFresh(); else if (a === 'attach') showAttach();
      if (e.target === els.help) toggleHelp(false);
    });
    const grow = () => { els.msg.style.height = 'auto'; els.msg.style.height = Math.min(els.msg.scrollHeight, 120) + 'px'; };
    els.msg.addEventListener('input', grow);
    els.msg.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); els.form.requestSubmit(); } if (e.key === 'Escape') els.msg.blur(); });
    els.form.addEventListener('submit', async e => {
      e.preventDefault();
      const text = els.msg.value.trim();
      if (!text) return;
      els.msg.value = ''; grow();
      const r = await act('run.send', {ticket: TID, text});
      if (!r.ok) { els.msg.value = text; toast(r.message, 'error'); return; }
      toast(r.note || 'Saved for the next run.', 'ok');
    });
    let cur = 0;
    document.addEventListener('keydown', e => {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.target.closest('input,textarea,select')) return;
      const k = e.key;
      if (k === 'Escape') { if (!els.help.hidden) toggleHelp(false); else if (root.classList.contains('is-full')) setFull(false); return; }
      if (k === '?') { e.preventDefault(); toggleHelp(); return; }
      if (!els.help.hidden) return;
      if (k === 'f' || k === 'F') setFull(!root.classList.contains('is-full'));
      else if (k === '[') toggleRail();
      else if (k === '/') { e.preventDefault(); els.msg.focus(); }
      else if (k === 's' || k === 'S') stopToggle();
      else if (k === 'j' || k === 'k') { const n = view ? view.ticket.checklist.length : 0; if (n) { cur = (sel + (k === 'j' ? 1 : -1) + n) % n; sel = cur; els.tasks.dataset.k = ''; els.tasks.dataset.picked = '1'; renderTasks(view); els.tasks.querySelectorAll('.fx-task')[sel]?.focus(); } }
      else if (k === '1' || k === '2') selectTab(+k - 1);
    });
  }

  /* ---- polling ---- */
  let timer = null;
  async function poll() {
    clearTimeout(timer);
    if (!document.hidden) {
      try {
        const r = await fetch(P + '/api/t/' + TID);
        if (r.ok) apply(await r.json());
        else if (r.status === 404 && firstRender) { root.replaceChildren(h('div', {class: 'fx-pick'}, h('h1', {text: 'No such ticket'}), h('a', {href: INAPP ? '/#home' : '/', target: INAPP ? '_top' : '_self', text: 'All tickets'}))); return; }
      } catch (e) { /* try again */ }
    }
    timer = setTimeout(poll, view && view.run.running ? 1500 : 3000);
  }
  document.addEventListener('visibilitychange', () => { if (!document.hidden) poll(); });
  build(); wire(); poll();
})();
