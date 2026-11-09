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
    root.classList.add('fx-picker');
    root.append(h('header', {class: 'fx-top'}, h('span', {class: 'meta fx-workspace', text: 'Focus'}), h('button', {class: 'btn ghost sm', 'data-act': 'help', text: 'Help'})),
      h('main', {class: 'fx-pick'}, h('p', {class: 'eyebrow', text: 'One ticket at a time'}), h('h1', {text: 'Where shall we focus?'}), h('p', {class: 'meta', text: 'Choose a ticket to take its next step.'})));
    fetch(P + '/api/tickets').then(r => { if (!r.ok) throw Error(); return r.json(); }).then(payload => {
      const list = payload.tickets;
      root.querySelector('.fx-workspace').textContent = payload.workspace + ' / Focus';
      root.querySelector('.fx-pick > .meta').textContent = window.FocusHelpers.attentionText(list);
      const box = root.querySelector('.fx-pick');
      if (!list.length) box.append(h('p', {class: 'muted', text: 'No open tickets.'}));
      const groups = [['waiting', 'Needs you', 'Answer'], ['review', 'Check result', 'Check'], ['active', 'Working', 'Watch'], ['ready', 'Ready to start', 'Start'], ['open', 'To do', 'Start']];
      const rowFor = (t, status, action) => {
        const next = t.next_step || action;
        return h('a', {href: P + '/t/' + t.id + (status === 'review' ? '#results' : '')},
          h('div', {class: 'grow'}, h('span', {class: 'mono key', text: t.key || t.id}), h('strong', {text: t.title}),
            h('small', {text: 'Next step · ' + next})), h('span', {class: 'row-action', text: next}));
      };
      for (const [status, label, action] of groups) {
        const rows = list.filter(t => t.status === status);
        if (!rows.length) continue;
        box.append(h('section', {class: 'fx-pick-group fx-group-' + status}, h('h2', {}, label + ' ', h('span', {class: 'meta', text: '(' + rows.length + ')'})),
          h('div', {class: 'card'}, rows.map(t => rowFor(t, status, action)))));
      }
      const done = list.filter(t => t.status === 'done').sort((a, b) => String(b.closed_at || '').localeCompare(String(a.closed_at || '')));
      if (done.length) {
        const search = h('input', {class: 'input', type: 'search', placeholder: 'Search finished tickets', 'aria-label': 'Search finished tickets', name: 'done-search'});
        const card = h('div', {class: 'card'});
        const paint = () => {
          const q = search.value.trim().toLowerCase();
          const rows = q ? done.filter(t => ((t.key || '') + ' ' + t.title).toLowerCase().includes(q)) : done.slice(0, 5);  /* the last five by default; a search looks through all */
          card.replaceChildren(...(rows.length ? rows.map(t => rowFor(t, 'done', 'View')) : [h('p', {class: 'meta fx-none', text: 'No finished ticket matches.'})]));
        };
        search.addEventListener('input', paint); paint();
        box.append(h('section', {class: 'fx-pick-group fx-group-done'}, h('div', {class: 'row'}, h('h2', {class: 'grow'}, 'Done ', h('span', {class: 'meta', text: '(' + done.length + ')'})), done.length > 5 ? search : null), card));
      }
    }).catch(() => root.querySelector('.fx-pick').append(h('p', {role: 'alert', text: 'Could not load tickets. Reload to try again.'})));
    /* ---- Running now: every run Focus started, each with Stop; Stop all asks once (a plain click) ---- */
    const procBox = h('section', {class: 'fx-procs', hidden: true});
    root.querySelector('.fx-pick').append(procBox);
    const minutes = at => { const m = Math.max(0, Math.floor((Date.now() - Date.parse(at)) / 60000)); return isNaN(m) ? '' : m < 1 ? 'just now' : m + ' min'; };
    const CHIP = {working: ['Working', 'good'], paused: ['Paused', ''], needs: ['Waiting for you', 'needs-you']};
    let stopping = false;
    const loadProcs = async () => {
      if (stopping || document.hidden) return;
      try { const r = await fetch(P + '/api/procs'); if (r.ok) paintProcs((await r.json()).procs || []); } catch (e) { /* next round */ }
    };
    const stopCall = async (op, args) => {
      stopping = true;
      let r;
      try { r = await fetch(P + '/api/act', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({op, args})}); } catch (e) { r = null; }
      stopping = false;
      if (!r || !r.ok) { toast(r ? (await r.text()).slice(0, 200) : 'Could not reach Focus.', 'error'); loadProcs(); return; }
      const d = await r.json(); paintProcs(d.procs || []);
      toast(d.failed ? 'Some did not stop.' : 'Stopped.', d.failed ? 'error' : 'ok');
    };
    const confirmAll = n => {
      const d = h('dialog', {class: 'dialog fx-confirm', 'aria-labelledby': 'fx-stopall-t'}, h('h2', {id: 'fx-stopall-t', text: 'Stop all ' + n + '?'}),
        h('div', {class: 'actions'}, h('button', {class: 'btn ghost', text: 'Keep running', onclick: () => d.close()}),
          h('button', {class: 'btn primary', text: 'Stop all', onclick: () => { d.close(); stopCall('proc.stop_all', {}); }})));
      d.addEventListener('close', () => d.remove());
      document.body.append(d); d.showModal();
    };
    function paintProcs(rows) {
      procBox.hidden = !rows.length;
      const waiting = rows.filter(x => x.state === 'needs').length;
      procBox.replaceChildren(...(rows.length ? [
        h('div', {class: 'row fx-procs-h'}, h('h2', {class: 'grow'}, 'Running now ', h('span', {class: 'meta', text: '(' + rows.length + (waiting ? ', ' + waiting + ' waiting for you' : '') + ')'})),
          h('button', {class: 'btn outline sm', 'data-act': 'stop-all', text: 'Stop all', onclick: () => confirmAll(rows.length)})),
        h('div', {class: 'card'}, rows.map(x => {
          const [word, tone] = CHIP[x.state] || CHIP.working;
          return h('div', {class: 'fx-proc'},
            h('div', {class: 'row'}, h('span', {class: 'grow'}, h('strong', {text: x.label}), ' on ', h('span', {class: 'mono key', text: x.key || x.ticket}), ' ', x.title),
              h('span', {class: 'chip ' + tone, text: word}), h('span', {class: 'meta', text: minutes(x.started_at)}),
              h('button', {class: 'btn ghost sm', 'data-act': 'stop-one', 'aria-label': 'Stop ' + x.label + ' on ' + (x.key || x.title), text: 'Stop', onclick: () => stopCall('proc.stop', {ticket: x.ticket, run: x.run})})),
            h('details', {}, h('summary', {text: 'Details'}),
              h('p', {class: 'meta'}, x.started_at ? 'Started ' + new Date(x.started_at).toLocaleString([], {day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false}) + ' · ' : '', h('a', {href: P + '/t/' + x.ticket, text: x.key || 'Open ticket'}), x.pid ? ' · process ' + x.pid : '')));
        }))] : []));
    }
    loadProcs(); setInterval(loadProcs, 5000);
    document.addEventListener('visibilitychange', () => { if (!document.hidden) loadProcs(); });
    const help = helpPanel(); root.append(help);
    const helpButton = root.querySelector('[data-act=help]');
    const toggle = on => { help.hidden = !on; (on ? help.querySelector('button') : helpButton).focus(); };
    root.addEventListener('click', e => { if (e.target.closest('[data-act=help]')) toggle(help.hidden); else if (e.target === help) toggle(false); });
    document.addEventListener('keydown', e => {
      if (e.metaKey || e.ctrlKey || e.altKey || e.target.closest('input,textarea,select')) return;
      if (e.key === '?') { e.preventDefault(); toggle(help.hidden); }
      if (!help.hidden && ['Escape', 'x', 'X'].includes(e.key)) toggle(false);
      if (!help.hidden && e.key === 'Tab') { e.preventDefault(); help.querySelector('button').focus(); }
    });
    return;
  }

  /* ---- skeleton ---- */
  const els = {};
  let view = null, sel = 0, firstRender = true, shownQs = new Map(), lastFeedKey = '', tab = 0, changesRequested = false;
  const STATE = {needs: 'Needs you', waiting: 'Paused', stopped: 'Paused', done: 'Done'};

  function build() {
    els.rail = h('button', {class: 'btn ghost icon sm', 'data-act': 'rail', 'aria-label': 'Show or hide tasks', 'aria-expanded': 'true', title: 'Tasks ( [ )', icon: 'table'});
    els.key = h('span', {class: 'mono key', text: TID});
    els.title = h('h1', {text: ''});
    els.count = h('span', {text: ''});
    els.bar = h('span');
    els.prog = h('div', {class: 'progress', role: 'progressbar', 'aria-label': 'Tasks done', 'aria-valuemin': '0'}, els.bar);
    els.agent = h('b', {text: ''});
    els.stateText = h('span', {role: 'status', 'aria-live': 'polite', text: ''});
    els.time = h('span', {class: 't', text: ''});
    els.live = h('button', {class: 'fx-live', type: 'button', 'aria-expanded': 'false', 'aria-haspopup': 'dialog', 'aria-controls': 'fx-session'}, h('span', {class: 'fx-dot'}), els.agent, els.stateText, els.time);
    els.stopIc = h('span');
    els.stopL = h('span', {class: 'opt', text: 'Stop'});
    els.stop = h('button', {class: 'btn ghost sm', 'data-act': 'stop', title: 'Stop or continue (S)'}, els.stopIc, els.stopL);
    els.answer = h('button', {class: 'btn primary sm', 'data-act': 'answer', title: 'Answer the question below', hidden: true, text: 'Answer'});
    const menuRow = (action, icon, label, hidden = false) => h('button', {type: 'button', 'data-act': action, hidden}, h('span', {icon}), h('span', {text: label}));
    els.fresh = menuRow('fresh', 'plus', 'Start fresh instead', true);
    els.attachBtn = menuRow('attach', 'external', 'Open live session', true);
    els.full = menuRow('full', 'expand', 'Full screen');
    els.full.setAttribute('aria-pressed', 'false');
    els.helpBtn = menuRow('help', 'text', 'Keyboard shortcuts');
    els.moreBtn = h('button', {class: 'btn ghost icon sm', type: 'button', icon: 'more', 'aria-label': 'More actions', 'aria-expanded': 'false', 'aria-controls': 'fx-action-menu'});
    els.menu = h('div', {class: 'fx-popover fx-action-menu', id: 'fx-action-menu', hidden: true}, els.attachBtn, els.full, els.helpBtn, els.fresh);
    els.more = h('div', {class: 'fx-more'}, els.moreBtn, els.menu);
    els.session = h('section', {class: 'fx-popover fx-session', id: 'fx-session', role: 'dialog', 'aria-labelledby': 'fx-session-title', tabindex: '-1', hidden: true});
    els.liveWrap = h('div', {class: 'fx-live-wrap'}, els.live, els.session);
    els.phoneInput = h('input', {type: 'checkbox', role: 'switch'});
    els.phone = h('label', {class: 'fx-phone', hidden: true}, els.phoneInput, 'Send questions to my phone');
    els.steps = h('div', {class: 'fx-stepper'});
    const top = h('header', {class: 'fx-top'}, els.rail, h('div', {class: 'fx-title'}, h('div', {class: 'meta'}, 'Focus / ', els.key), els.title, els.steps), h('div', {class: 'fx-prog'}, els.count, els.prog), els.liveWrap,
      h('div', {class: 'fx-tools'}, els.phone, els.stop, els.more, h('a', {class: 'btn ghost sm fx-exit', 'aria-label': 'Exit Focus', href: INAPP ? '/#ticket/' + TID : '/', target: INAPP ? '_top' : '_self', title: INAPP ? 'Back to the ticket' : 'All tickets'}, h('span', {icon: 'x'}), h('span', {class: 'opt', text: 'Exit'}))));
    els.tasks = h('div', {id: 'fx-tasks'});
    els.helpers = h('div');
    els.railNote = h('p', {class: 'meta', style: false});
    els.addInput = h('input', {class: 'input', type: 'text', maxlength: '500', placeholder: 'Add a task', 'aria-label': 'Add a task', name: 'task'});
    els.addForm = h('form', {class: 'fx-add-task'}, els.addInput, h('button', {class: 'btn ghost icon sm', type: 'submit', 'aria-label': 'Add task', icon: 'plus'}));
    const rail = h('aside', {class: 'fx-rail', 'aria-label': 'Tasks'}, h('div', {}, h('p', {class: 'eyebrow'}, h('span', {text: 'Tasks'}), els.railCount = h('span')), els.tasks), els.helpers, els.railNote, els.addForm);
    els.tabs = [['live', 'Live'], ['proof', 'Results']].map(([id, label], i) => h('button', {class: 'fx-tab', role: 'tab', id: 'fx-t-' + id, 'aria-controls': 'fx-p-' + id, 'aria-selected': String(i === 0), tabindex: i ? '-1' : '0', title: label + ' (' + (i + 1) + ')', 'data-tab': i, text: label}));
    els.sub = h('span', {class: 'meta', text: ''});
    els.feed = h('div', {class: 'fx-feed', role: 'log', 'aria-label': 'What the agent is doing'});
    els.working = h('div', {class: 'fx-working', hidden: true});
    els.line = h('div');
    els.qs = h('div', {class: 'fx-qwrap'});
    els.paneLive = h('div', {class: 'fx-pane', id: 'fx-p-live', role: 'tabpanel', 'aria-labelledby': 'fx-t-live'}, els.qs, els.line, els.feed, els.working);
    els.paneProof = h('div', {class: 'fx-pane', id: 'fx-p-proof', role: 'tabpanel', 'aria-labelledby': 'fx-t-proof', hidden: true});
    els.attachBox = h('div', {class: 'fx-attach', hidden: true});
    els.msg = h('textarea', {id: 'fx-msg', rows: '1', placeholder: 'Message the agent…', 'aria-label': 'Message to the agent'});
    els.form = h('form', {id: 'fx-form'}, els.msg, h('button', {class: 'btn sm', 'aria-label': 'Send', text: 'Send ↑'}));
    els.messageLabel = h('label', {for: 'fx-msg', text: 'Message the agent'});
    const compose = els.compose = h('div', {class: 'fx-compose'}, els.messageLabel, els.form);
    els.help = helpPanel();
    els.review = h('div', {class: 'fx-review', hidden: true}, h('div', {}, h('p', {text: 'Finished. Looks good?'}), h('p', {class: 'meta', text: 'Next step · Check result'})),
      h('button', {class: 'btn', 'data-act': 'changes', text: 'Ask for changes'}), h('button', {class: 'btn primary', 'data-act': 'done', text: 'Accept'}));
    els.complete = h('div', {class: 'fx-review', hidden: true}, h('p', {text: 'You’re all set here.'}));
    const stage = h('section', {class: 'fx-stage', 'aria-label': 'Ticket activity'}, h('div', {class: 'fx-stage-h', role: 'tablist', 'aria-label': 'Focus views'}, els.tabs, h('span', {class: 'grow'}), els.sub), h('div', {class: 'fx-scan', 'aria-hidden': 'true'}), els.attachBox, els.paneLive, els.paneProof, compose, els.review, els.complete, els.help);
    els.mobileTasks = h('button', {class: 'fx-mobile-tasks', 'data-act': 'rail', 'aria-controls': 'fx-tasks', 'aria-expanded': 'false'});
    root.replaceChildren(top, els.mobileTasks, h('div', {class: 'fx-body'}, rail, stage));
    els.stopIc.innerHTML = ic('pause');
    root.querySelectorAll('[data-icon]').forEach(e => { e.innerHTML = ic(e.dataset.icon); });
  }

  /* ---- render ---- */
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

  function apply(v) {
    const prev = view;
    syncTimer(v);
    view = v;
    if (prev && prev.ticket.status !== v.ticket.status) changesRequested = false;
    const t = v.ticket;
    document.title = t.title + ' · Focus';
    els.title.textContent = t.title || '';
    els.key.textContent = typeof t.key === 'string' && t.key ? t.key : TID;  /* the short key people use, e.g. DM1-12 */
    root.dataset.state = v.state;
    if (prev && !root.hasAttribute('data-live')) root.setAttribute('data-live', '');  /* motion only after a live change */
    els.agent.textContent = v.run.label;
    const stateText = v.state === 'working' ? 'Working' : v.state === 'stopped' ? (t.status === 'review' ? STATUS_WORD.review : t.started || v.run.run ? 'Paused' : statusWord(t)) : STATE[v.state];
    if (els.stateText.textContent !== stateText) els.stateText.textContent = stateText;
    const phase = window.FocusHelpers.phase(v);
    els.steps.replaceChildren(...['Plan', 'Work', 'Check', 'Done'].map((name, i) => h('span', {'aria-current': i === phase ? 'step' : null, text: name})));
    els.phone.hidden = v.capabilities?.phone_mode !== true;
    els.phoneInput.checked = v.phone_mode === true;
    els.phoneInput.title = 'Send questions to my phone';
    els.mobileTasks.textContent = 'Tasks ' + v.done + '/' + v.total;
    els.review.querySelector('p').textContent = els.agent.textContent + ' finished — check the result';
    els.count.textContent = v.done + ' of ' + v.total;
    els.bar.style.width = (v.total ? Math.round(v.done / v.total * 100) : 0) + '%';
    els.prog.setAttribute('aria-valuemax', String(v.total));
    els.prog.setAttribute('aria-valuenow', String(v.done));
    els.railCount.textContent = v.total ? v.done + ' of ' + v.total : '0';
    const running = v.run.running;
    const hasStarted = t.started || v.run.run || ['review', 'done'].includes(t.status);
    els.stopIc.innerHTML = ic(running ? 'pause' : 'play');
    els.stopL.textContent = running ? 'Stop' : 'Continue';
    els.compose.hidden = v.state === 'done' || (tab === 1 && t.status === 'review' && !changesRequested);  /* a done ticket is a read-only board; Continue starts a run */
    /* an open question: Answer is the main action; Continue and Start fresh wait until it is answered */
    const asking = v.ticket.questions.some(q => q.answer == null);
    els.answer.hidden = !asking;
    els.stop.hidden = (asking && !running) || (!running && !hasStarted);
    els.fresh.hidden = running || asking || !hasStarted;
    els.review.hidden = tab !== 1 || t.status !== 'review' || asking || running;
    els.complete.hidden = v.state !== 'done';
    els.attachBtn.hidden = !(running && v.live);
    els.sub.textContent = '';
    els.msg.placeholder = 'Message ' + els.agent.textContent + '…';
    els.msg.setAttribute('aria-label', 'Message ' + els.agent.textContent);
    els.feed.setAttribute('aria-label', 'What ' + els.agent.textContent + ' is doing');
    els.messageLabel.textContent = 'Message ' + els.agent.textContent;
    els.railNote.textContent = '';
    renderTasks(v);
    renderHelpers(v);
    renderFeed(v, !firstRender);
    renderQuestions(v);
    renderProof(v);
    renderLine(v);
    els.working.hidden = true;
    els.working.replaceChildren(...(running && v.board.step ? [h('span', {class: 'fx-dot'}), h('span', {text: v.board.step})] : []));
    tickTimer();
    renderSession(v);
    if ((firstRender && (['review', 'done'].includes(t.status) || location.hash === '#results')) || (t.status === 'done' && prev?.ticket.status !== 'done')) els.tabs[1].click();
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
        h('span', {class: 'st', icon: c.done ? 'check' : false}), h('span', {}, h('span', {class: 'tt', text: c.text}), h('span', {class: 'sub', text: evText(c)})));
      row.addEventListener('click', () => { sel = i; els.tasks.dataset.picked = '1'; els.tasks.dataset.k = ''; renderTasks(view); });
      const out = [row];
      if (els.tasks.dataset.picked && i === sel) out.push(taskTools(c, i, checks));
      return out;
    }));
    if (!checks.length) els.tasks.append(h('p', {class: 'meta', text: 'No tasks yet'}));
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

  // The ticket lines orch writes itself, in the same plain words as the CLI and the dashboard.
  function plainLine(text, checklist) {
    const task = id => { const c = (checklist || []).find(x => x.id === id); return c && c.text ? ': ' + c.text : ''; };
    const addon = k => k.replace(/-/g, ' ').replace(/^./, c => c.toUpperCase());
    let m;
    if ((m = /^Added check (c\d+)$/.exec(text))) return 'Added a task' + task(m[1]);
    if ((m = /^Check (c\d+) done$/.exec(text))) return 'Finished a task' + task(m[1]);
    if (/^Asked q\d+, waiting$/.test(text)) return 'Asked a question';
    if ((m = /^Answered q\d+: ([\s\S]*)$/.exec(text))) return 'Answered a question: ' + m[1];
    if ((m = /^(?:Patched status \(status|Status) \w+ -> (\w+)/.exec(text))) return 'Moved to ' + (STATUS_WORD[m[1]] || m[1]);
    if ((m = /^Set ext\.([a-z][a-z0-9-]*)$/.exec(text))) return 'Updated ' + addon(m[1]) + ' settings';
    return plainNames(text);
  }

  // a raw actor id inside a line ("agent:<name> finished the work") is shown as its name, like the dashboard's plainNames()
  const plainNames = text => String(text ?? '').replace(/\b(?:agent|human):([A-Za-z0-9_.@-]+)/g, (_, n) => n.charAt(0).toUpperCase() + n.slice(1));

  function feedItems(v) {
    const items = [];
    for (const e of v.ticket.history || []) items.push({at: e.at, icon: /Asked|waiting/.test(e.text) ? 'note' : (/done/.test(e.text) ? 'check' : 'text'), ok: /done/.test(e.text), text: plainLine(String(e.text || ''), v.ticket.checklist), who: e.by, you: /^human:/.test(e.by || '') && e.via !== 'cli'});
    for (const e of v.events) {
      if (e.kind === 'tool.start') items.push({at: e.at, icon: 'text', text: plainNames(e.text)});
      else if (e.kind === 'tool.end') items.push({at: e.at, icon: e.data.ok === false ? 'x' : 'check', ok: e.data.ok !== false, text: e.text});
      else if (e.kind === 'helper.start') items.push({at: e.at, icon: 'user', text: 'Helper: ' + e.text});
      else if (e.kind === 'helper.end') items.push({at: e.at, icon: 'check', ok: true, text: 'Helper done: ' + e.text});
    }
    items.sort((a, b) => String(a.at).localeCompare(String(b.at)));
    return items.slice(-80);
  }

  function renderFeed(v) {
    const key = keyOf([v.ticket.checklist, v.state, v.run.running, v.run.run, v.ticket.started, v.board.step, v.events, v.ticket.history]);
    if (key === lastFeedKey) return;
    lastFeedKey = key;
    const asking = v.ticket.questions.some(q => q.answer == null);
    const checks = v.ticket.checklist;
    if (!v.run.running && !v.run.run && !v.ticket.started && v.state !== 'done' && !asking && !checks.length) {
      els.feed.replaceChildren(h('div', {class: 'fx-start'}, h('span', {class: 'empty-symbol', text: '◌'}),
        h('h2', {text: 'Give ' + els.agent.textContent + ' the first step'}),
        h('p', {text: els.agent.textContent + ' hasn’t started yet. Start it and watch it plan the tasks here.'}),
        h('p', {class: 'meta', text: 'Next step · Start ' + els.agent.textContent}), h('button', {class: 'btn primary', 'data-act': 'stop', text: 'Start ' + els.agent.textContent})));
      return;
    }
    const story = checks.filter(c => c.done || c.state === 'doing');
    const heading = asking ? 'Before the question' : v.state === 'done' ? 'Work completed' : v.run.running ? 'The work is taking shape' : 'Work so far';
    const nodes = [h('h2', {text: heading})];
    if (!asking) nodes.push(h('p', {class: 'meta', text: v.done + ' of ' + v.total + ' tasks finished.'}));
    for (const c of story) nodes.push(h('article', {class: 'fx-story' + (!c.done && v.run.running ? ' now' : '')},
      h('h3', {text: (c.done ? '✓ ' : v.run.running ? 'Now: ' : '') + c.text}),
      h('p', {text: evText(c) || (!c.done && v.run.running ? v.board.step || 'Working on this task.' : '')})));
    if (v.run.running && !story.some(c => !c.done)) nodes.push(h('article', {class: 'fx-story now'}, h('h3', {text: v.board.step || 'Waiting for the first step…'})));
    if (!v.run.running && !asking && v.state !== 'done' && v.ticket.status !== 'review' && !v.ticket.started && !v.run.run) nodes.push(h('button', {class: 'btn primary', 'data-act': 'stop', text: 'Start ' + els.agent.textContent}));
    const details = h('details', {class: 'fx-history'}, h('summary', {text: 'Details'}));
    for (const it of feedItems(v)) details.append(h('div', {class: 'fx-step'}, h('time', {text: hhmm(it.at)}), h('span', {icon: it.icon}), h('span', {text: it.text})));
    nodes.push(details);
    els.feed.replaceChildren(...nodes);
  }

  let prevQuestionLabel;
  function renderQuestions(v) {
    const open = v.ticket.questions.filter(q => q.answer == null);
    if (prevQuestionLabel !== v.run.label) { for (const card of shownQs.values()) card.node.remove(); shownQs.clear(); prevQuestionLabel = v.run.label; }
    const ids = new Set(open.map(q => q.id));
    for (const [id, card] of shownQs) if (!ids.has(id)) { card.node.remove(); shownQs.delete(id); }
    for (const q of open) {
      // m1-api question fields: sent_to_phone or delivered, strict booleans only.
      const delivered = q.sent_to_phone === true;
      if (shownQs.has(q.id)) { shownQs.get(q.id).receipt.hidden = !delivered; continue; }
      const node = h('div', {'data-row': '', class: 'fx-ask-wrap'});
      els.qs.append(node);
      const options = (q.options || []).map(o => ({text: o, suggested: o === q.recommended}));
      const question = {ticket: TID, key: typeof v.ticket.key === 'string' ? v.ticket.key : undefined, id: q.id, title: q.text, text: els.agent.textContent + ' waits for you. After you answer it continues in the same conversation.', options};
      if (window.QuestionCard) {
        window.QuestionCard.mount(node, question, {send: async (answer) => {
          const r = await act('answer', {ticket: TID, question: q.id, answer});
          return r.ok ? {status: 200, who: 'you', via: 'focus'} : {status: r.status === 409 ? 409 : (r.status || 0), message: r.message};
        }});
      }
      const own = node.querySelector('.qoptions .quiet');
      if (own) own.textContent = 'Write your own…';
      const card = node.querySelector('.qcard');
      if (card) card.prepend(h('p', {class: 'meta', text: 'Next step · Answer ' + els.agent.textContent}));
      const receipt = h('span', {class: 'fx-receipt', hidden: !delivered, title: 'Also sent to your phone', 'aria-label': 'Also sent to your phone', role: 'img'});
      receipt.innerHTML = '<svg width=16 height=16 viewBox="0 0 24 24" fill=none stroke=currentColor stroke-width=1.5 aria-hidden=true><rect x=7 y=2 width=10 height=20 rx=2 /><path d="M10 18h4" /></svg>';
      (card || node).append(receipt);
      shownQs.set(q.id, {node, receipt});
      if (!firstRender && window.orch) window.orch.needsIn(node);
    }
  }

  function renderProof(v) {
    proof.setPageKey(v.page_key);
    proof.setAgent(v.run.label);
    const done = v.ticket.checklist.filter(c => c.done);
    const list = [];
    for (const c of done) for (const ev of c.evidence || []) list.push({c, ev});
    const key = keyOf([v.ticket.status, v.ticket.closed_at, v.ticket.history, v.run.label, list]);
    els.tabs[1].textContent = 'Results';
    if (list.length) els.tabs[1].append(h('sup', {text: ' ' + list.length}));
    if (key === els.paneProof.dataset.k) return;
    els.paneProof.dataset.k = key;
    const files = list.filter(x => x.ev.type !== 'note');
    const primary = files[files.length - 1] || list[list.length - 1];
    const content = h('div', {class: 'fx-results'}, h('h2', {text: v.state === 'done' ? 'Work completed' : list.length ? 'Ready for your look' : 'No results yet'}),
      h('p', {class: 'meta', text: list.length ? v.ticket.title : 'Results will appear here when a task is done.'}));
    const completed = window.FocusHelpers.completedAt(v.ticket);
    if (v.state === 'done' && completed) content.append(h('p', {class: 'meta', text: 'Completed ' + stamp(completed).replace(/ (\d\d:)/, ' at $1')}));
    if (primary) content.append(proof.tile(primary, from => proof.open(list, list.indexOf(primary), from)));
    for (const c of done) content.append(h('p', {class: 'fx-result-note', text: '✓ ' + c.text + ' — ' + evText(c)}));
    if (files.length) content.append(h('details', {}, h('summary', {text: 'Details'}), files.map(({c, ev}) => h('p', {class: 'meta', text: c.text + ' · ' + String(ev.ref || '').split('/').pop() + (ev.summary ? ' · ' + ev.summary : '')}))));
    els.paneProof.replaceChildren(content);
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

  /* ---- worked time: polling corrects drift, without small backward jumps ---- */
  let workedBase = 0, workedAt = 0, clockWorking = false;
  const workedNow = () => workedBase + (clockWorking ? Math.max(0, performance.now() - workedAt) / 1000 : 0);
  function syncTimer(v) {
    const server = Math.max(0, Number(v.run.worked) || 0), current = workedNow();
    workedBase = view && Math.abs(server - current) <= 3 ? Math.max(server, current) : server;
    workedAt = performance.now();
    clockWorking = v.state === 'working';
  }
  function tickTimer() {
    const s = Math.floor(workedNow());
    els.time.textContent = s ? Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0') : '';
  }
  const duration = seconds => {
    const minutes = Math.floor(Math.max(0, Number(seconds) || 0) / 60);
    return minutes < 1 ? 'under 1 min' : minutes < 60 ? minutes + ' min' : Math.floor(minutes / 60) + ' h ' + minutes % 60 + ' min';
  };
  function renderSession(v) {
    const fact = (label, value) => h('div', {class: 'fx-session-fact'}, h('span', {class: 'muted', text: label}), h('span', {text: value}));
    els.session.replaceChildren(h('h2', {id: 'fx-session-title', text: 'This session'}),
      fact('Worked', duration(workedNow())), fact('Paused', duration(v.run.paused)), fact('Started', stamp(v.run.first) || '—'));
    const context = v.board.context;
    if (context) {
      const reused = Math.max(0, Math.min(100, Number(context.reused) || 0));
      els.session.append(h('section', {class: 'fx-saved-context'}, h('h3', {text: 'Saved context'}),
        h('p', {class: 'meta', text: v.run.label + ' remembers this conversation, ' + reused + '% reused, so replies are faster and cheaper.'}),
        h('div', {class: 'progress', role: 'progressbar', 'aria-label': 'Saved context reused', 'aria-valuemin': '0', 'aria-valuemax': '100', 'aria-valuenow': String(reused)}, h('span', {style: 'width:' + reused + '%'})),
        h('p', {class: 'meta', text: 'Refreshed ' + hhmm(context.at)})));
    }
  }
  setInterval(() => { if (view && clockWorking) tickTimer(); }, 1000);

  /* ---- actions ---- */
  function focusQuestion() {
    const host = els.qs.querySelector('button,input,textarea') || els.qs;
    els.qs.scrollIntoView({block: 'center'});
    if (host === els.qs) els.qs.tabIndex = -1;
    host.focus();
  }
  async function stopToggle() {
    if (!view) return;
    if (!view.run.running && view.ticket.questions.some(q => q.answer == null)) { focusQuestion(); return; }
    const r = view.run.running ? await act('run.stop', {ticket: TID}) : await act('run.start', {ticket: TID});
    if (!r.ok) toast(r.message, 'error'); else toast(view.run.running ? 'Started. Same conversation.' : 'Stopped. The work done so far is kept.', 'ok');
  }
  async function startFresh() { const r = await act('run.start', {ticket: TID, fresh: true}); if (!r.ok) toast(r.message, 'error'); else toast('Started fresh from the ticket.', 'ok'); }
  function showAttach() {
    // waiting for an OK: the person must type in the session, so no --watch; the short key (DM1-12) works too
    const ok = !!(view && view.attention), key = (els.key && els.key.textContent) || TID;
    const cmd = 'orch run attach ' + key + (ok ? '' : ' --watch');
    els.attachBox.hidden = !els.attachBox.hidden;
    els.attachBox.replaceChildren(h('span', {class: 'meta', text: ok ? 'Answer it in a terminal (Ctrl-b d to leave):' : 'Watch the live session in a terminal:'}), h('code', {class: 'mono', text: cmd}),
      h('button', {class: 'btn ghost xs', text: 'Copy', onclick: () => { try { navigator.clipboard.writeText(cmd); toast('Copied.', 'ok'); } catch (e) { /* select by hand */ } }}));
  }

  function wire() {
    const markFull = on => { root.classList.toggle('is-full', on); els.full.setAttribute('aria-pressed', String(on)); els.full.lastElementChild.textContent = on ? 'Leave full screen' : 'Full screen'; els.full.setAttribute('aria-label', on ? 'Leave full screen' : 'Full screen'); document.body.style.overflow = on ? 'hidden' : ''; };
    const setFull = async on => {
      if (on) { try { await root.requestFullscreen?.(); } catch (e) { /* CSS fallback */ } markFull(true); }
      else { if (document.fullscreenElement) { try { await document.exitFullscreen(); } catch (e) { /* ignore */ } } markFull(false); }
    };
    document.addEventListener('fullscreenchange', () => { if (!document.fullscreenElement && root.classList.contains('is-full')) markFull(false); });
    const toggleRail = () => { const closed = root.classList.toggle('rail-closed'); els.rail.setAttribute('aria-expanded', String(!closed)); els.mobileTasks.setAttribute('aria-expanded', String(!closed)); };
    const narrow = matchMedia('(max-width: 720px)');
    if (narrow.matches) toggleRail();
    narrow.addEventListener('change', e => { root.classList.toggle('rail-closed', e.matches); els.rail.setAttribute('aria-expanded', String(!e.matches)); els.mobileTasks.setAttribute('aria-expanded', String(!e.matches)); });
    const toggleHelp = force => { els.help.hidden = force === undefined ? !els.help.hidden : !force; if (!els.help.hidden) els.help.querySelector('button').focus(); else els.moreBtn.focus(); };
    const selectTab = i => { tab = i; els.review.hidden = i !== 1 || view?.ticket.status !== 'review' || view?.run.running || view?.state === 'needs'; els.compose.hidden = view?.state === 'done' || (i === 1 && view?.ticket.status === 'review' && !changesRequested); els.tabs.forEach((b, j) => { const on = i === j; b.setAttribute('aria-selected', String(on)); b.tabIndex = on ? 0 : -1; document.getElementById(b.getAttribute('aria-controls')).hidden = !on; }); };
    els.tabs.forEach((b, i) => b.addEventListener('click', () => selectTab(i)));
    const setPopover = (panel, button, open) => {
      panel.hidden = !open;
      button.setAttribute('aria-expanded', String(open));
      if (open) {
        // Clamp the floating panel to the board and viewport without moving siblings.
        panel.style.transform = '';
        const rect = panel.getBoundingClientRect(), board = root.getBoundingClientRect();
        const left = Math.max(8, board.left + 8), right = Math.min(innerWidth - 8, board.right - 8);
        const dx = Math.max(left - rect.left, Math.min(0, right - rect.right));
        panel.style.transform = 'translateX(' + dx + 'px)';
      }
    };
    const closePopovers = () => {
      setPopover(els.menu, els.moreBtn, false);
      setPopover(els.session, els.live, false);
    };
    els.moreBtn.addEventListener('click', () => {
      const open = els.menu.hidden; closePopovers(); setPopover(els.menu, els.moreBtn, open);
      if (open) els.menu.querySelector('button:not([hidden])').focus();
    });
    els.live.addEventListener('click', () => {
      const open = els.session.hidden; closePopovers();
      if (view) renderSession(view);
      setPopover(els.session, els.live, open);
      if (open) els.session.focus();
    });
    document.addEventListener('click', e => {
      if (!els.more.contains(e.target) && !els.liveWrap.contains(e.target)) closePopovers();
    });
    window.addEventListener('resize', closePopovers);
    document.addEventListener('keydown', e => {
      if (e.key !== 'Escape' || (els.menu.hidden && els.session.hidden)) return;
      const button = els.menu.hidden ? els.live : els.moreBtn;
      closePopovers(); button.focus(); e.preventDefault(); e.stopImmediatePropagation();
    }, true);
    root.addEventListener('click', e => {
      if (els.menu.contains(e.target) && e.target.closest('button')) { closePopovers(); els.moreBtn.focus(); }
      const a = e.target.closest('[data-act]')?.dataset.act;
      if (a === 'rail') toggleRail(); else if (a === 'full') setFull(!root.classList.contains('is-full')); else if (a === 'help') toggleHelp();
      else if (a === 'answer') focusQuestion(); else if (a === 'stop') stopToggle(); else if (a === 'fresh') startFresh(); else if (a === 'attach') showAttach();
      else if (a === 'changes') { changesRequested = true; els.compose.hidden = false; els.msg.placeholder = 'What would you like changed?'; els.msg.focus(); }
      else if (a === 'done') {
        const button = e.target.closest('button'); button.disabled = true;
        act('ticket.done', {ticket: TID, if_revision: view.ticket.revision}).then(r => { button.disabled = false; if (!r.ok) toast(r.message, 'error'); });
      }
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
    els.addForm.addEventListener('submit', async e => {
      e.preventDefault();
      const text = els.addInput.value.trim();
      if (!text) return;
      els.addInput.disabled = true;
      const r = await act('check.add', {ticket: TID, text});
      els.addInput.disabled = false;
      if (!r.ok) { toast(r.message, 'error'); els.addInput.focus(); return; }
      els.addInput.value = '';
      toast('Task added', 'ok');
    });
    els.phoneInput.addEventListener('change', async () => {
      els.phoneInput.disabled = true;
      try { const r = await act('mobile.set', {on: els.phoneInput.checked}); if (!r.ok) toast(r.message, 'error'); await poll(); }
      finally { els.phoneInput.disabled = false; }
    });
    let cur = 0;
    document.addEventListener('keydown', e => {
      if (e.metaKey || e.ctrlKey || e.altKey || proof.isOpen()) return;
      if (e.target.closest('input,textarea,select')) return;
      const k = e.key;
      if (k === 'Escape' || (!els.help.hidden && k.toLowerCase() === 'x')) { if (!els.help.hidden) toggleHelp(false); else if (root.classList.contains('is-full')) setFull(false); return; }
      if (k === '?') { e.preventDefault(); toggleHelp(); return; }
      if (!els.help.hidden) {
        if (k === 'Tab') { e.preventDefault(); els.help.querySelector('button').focus(); }
        return;
      }
      if (k === 'f' || k === 'F') setFull(!root.classList.contains('is-full'));
      else if (k === '[') toggleRail();
      else if (k === '/') { e.preventDefault(); els.msg.focus(); }
      else if (k === 's' || k === 'S') stopToggle();
      else if (k === 'j' || k === 'k') { const n = view ? view.ticket.checklist.length : 0; if (n) { cur = (sel + (k === 'j' ? 1 : -1) + n) % n; sel = cur; els.tasks.dataset.k = ''; els.tasks.dataset.picked = '1'; renderTasks(view); els.tasks.querySelectorAll('.fx-task')[sel]?.focus(); } }
      else if (k === '1' || k === '2') selectTab(+k - 1);
    });
  }

  /* ---- polling ---- */
  let timer = null, fresh = false, live = false;
  let busy = false, again = false, lastFetch = 0;
  async function poll() {
    clearTimeout(timer);
    if (busy) { again = true; return; }  // one request at a time, so an older answer never lands after a newer one
    busy = true;
    if (!document.hidden) {
      try {
        const f = fresh; fresh = false;  // a push that arrives during the fetch stays set for the next one
        const r = await fetch(P + '/api/t/' + TID + (f ? '?fresh=1' : ''));
        if (r.ok) apply(await r.json());
        else if (r.status === 404 && firstRender) { busy = false; root.replaceChildren(h('div', {class: 'fx-pick'}, h('h1', {text: 'No such ticket'}), h('a', {href: INAPP ? '/#home' : '/', target: INAPP ? '_top' : '_self', text: 'All tickets'}))); return; }
      } catch (e) { /* try again */ }
    }
    busy = false; lastFetch = Date.now();
    if (again) { again = false; timer = setTimeout(poll, 500); return; }
    timer = setTimeout(poll, live ? (view && view.run.running ? 1500 : 15000) : view && view.run.running ? 1500 : 3000);
  }
  document.addEventListener('visibilitychange', () => { if (!document.hidden) poll(); });
  /* A push (server-sent events) tells the page at once when a ticket or run file changed; the poll above is the
     slow fallback while the stream is up and the normal pace while it is down. Under the dashboard the stream is
     the dashboard's own (same origin, no proxy); opened directly it is Focus's own. */
  if (typeof EventSource !== 'undefined') {
    let stream, pending;
    const connect = () => {
      stream = new EventSource('/api/events');
      stream.onopen = () => { live = true; };
      stream.onerror = () => { live = false; };
      stream.addEventListener('rev', () => { clearTimeout(pending); pending = setTimeout(() => { fresh = true; poll(); }, Math.max(30, 500 - (Date.now() - lastFetch))); });
    };
    connect();
    window.addEventListener('pagehide', () => { stream.close(); live = false; });
    window.addEventListener('pageshow', e => { if (e.persisted) connect(); });
  }
  build(); wire(); poll();
})();
