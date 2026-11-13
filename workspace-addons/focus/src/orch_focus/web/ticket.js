// Owns the picker, ticket skeleton, tasks, helpers, and results.
(function () {
  'use strict';
  const S = window.FocusStore;
  const {root, ic, TID, P, INAPP, h, toast, helpPanel, els, act, proof, keyOf, stamp, evText} = S;

  function picker() {
    document.title = 'Focus · orch';
    root.classList.add('fx-picker');
    root.append(h('header', {class: 'fx-top'}, INAPP ? homeLink() : null, h('span', {class: 'meta fx-workspace', text: 'Focus'}), h('button', {class: 'btn ghost sm', 'data-act': 'help', text: 'Help'})),
      h('main', {class: 'fx-pick'}, h('h1', {text: 'Focus'}), h('p', {class: 'meta fx-sub', text: 'Loading your tickets…'}), skeleton()));
    fetch(P + '/api/tickets').then(r => { if (!r.ok) throw Error(); return r.json(); }).then(payload => {
      const list = payload.tickets;
      root.querySelector('.fx-workspace').textContent = payload.workspace + ' / Focus';
      S.state.pickAttention = window.FocusHelpers.attentionText(list);
      pickerSub();
      const box = root.querySelector('.fx-pick');
      box.querySelector('.fx-skel')?.remove();
      if (!list.some(t => t.status !== 'done')) box.append(emptyState());
      const groups = [['waiting', 'Needs you', 'Answer'], ['review', 'Sent back to you', 'Check'], ['active', 'Working', 'Watch'], ['ready', 'Ready to start', 'Start'], ['open', 'To do', 'Start']];
      /* one line: key, title, the actual next step only when it says more, and a real action chip */
      const rowFor = (t, status, action) => {
        const next = window.FocusHelpers.nextStepText(t, action);
        const finished = status === 'done' && t.closed_at ? stamp(t.closed_at) : '';
        return h('a', {class: 'fx-pick-row', href: P + '/t/' + t.id + (status === 'review' ? '#results' : '')},
          /^t_/.test(t.key || t.id) ? null : h('span', {class: 'mono key', text: t.key}), h('strong', {class: 'grow', text: t.title}),
          next ? h('small', {text: next}) : null, finished ? h('small', {text: 'Finished ' + finished}) : null,
          h('span', {class: 'chip fx-row-chip', text: action}));
      };
      for (const [status, label, action] of groups) {
        const needsYou = window.FocusHelpers.needsYou;
        const rows = list.filter(t => status === 'waiting' ? needsYou(t) : t.status === status);
        if (!rows.length) continue;
        const {shown, more} = window.FocusHelpers.limitGroup(rows);
        const card = h('div', {class: 'card'}, shown.map(t => rowFor(t, status, action)));
        const all = more ? h('button', {class: 'btn ghost sm fx-show-all', type: 'button', text: 'Show all (' + rows.length + ')'}) : null;
        if (all) all.addEventListener('click', () => { card.replaceChildren(...rows.map(t => rowFor(t, status, action))); all.remove(); });
        box.append(h('section', {class: 'fx-pick-group fx-group-' + status}, h('h2', {}, label + ' ', h('span', {class: 'meta', text: '(' + rows.length + ')'})), card, all));
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
      S.views.livenow.hideListed();
    }).catch(() => root.querySelector('.fx-pick').append(h('p', {role: 'alert', text: 'Could not load tickets. Reload to try again.'})));
    S.views.areas.mount(root.querySelector('.fx-pick'));
    S.views.livenow.mount(root.querySelector('.fx-pick'));
    S.views.jobs.mount(root.querySelector('.fx-pick'));
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
  }

  /* the page's shape before the tickets arrive, so nothing jumps */
  function skeleton() {
    return h('div', {class: 'fx-skel', 'aria-hidden': 'true'}, [0, 1, 2].map(() => h('div', {class: 'skeleton fx-skel-row'})));
  }

  const HOME = INAPP ? '/#home' : '/';
  const homeLink = () => h('a', {class: 'btn ghost sm fx-home', href: HOME, target: INAPP ? '_top' : '_self'}, h('span', {'aria-hidden': 'true', text: '←'}), h('span', {text: 'Back to Home'}));
  function emptyState() {
    return h('div', {class: 'fx-empty'}, h('p', {class: 'muted', text: 'No open tickets.'}),
      INAPP ? h('div', {class: 'row'}, h('a', {class: 'btn primary sm', href: '/#new', target: '_top', text: 'Create a ticket'}), homeLink()) : null);
  }

  /* "2 agents are working. One question needs you." The agent count comes from the live cards, the rest from the tickets. */
  function pickerSub() {
    const sub = root.querySelector('.fx-pick > .meta');
    const line = window.FocusHelpers.pickerLine(S.state.pickAgents, S.state.pickAttention);
    if (sub && line && sub.textContent !== line) sub.textContent = line;
  }

  function build() {
    els.rail = h('button', {class: 'btn ghost icon sm', 'data-act': 'rail', 'aria-label': 'Show or hide tasks', 'aria-expanded': 'true', title: 'Tasks ( [ )', icon: 'table'});
    els.key = h('span', {class: 'mono key', text: TID});
    els.title = h('span', {text: ''});
    els.areaChip = h('span', {class: 'chip success fx-area-chip', hidden: true, text: ''});  // the area this ticket works in (a label only)
    els.count = h('span', {text: ''});
    els.bar = h('span');
    els.prog = h('div', {class: 'progress', role: 'progressbar', 'aria-label': 'Tasks done', 'aria-valuemin': '0'}, els.bar);
    els.agent = h('b', {text: ''});
    els.stateText = h('span', {role: 'status', 'aria-live': 'polite', text: ''});
    els.time = h('span', {class: 't', text: ''});
    els.live = h('button', {class: 'fx-live', type: 'button', 'aria-expanded': 'false', 'aria-haspopup': 'dialog', 'aria-controls': 'fx-session'}, h('span', {class: 'fx-dot'}), els.agent, els.stateText, els.time);
    els.stopIc = h('span');
    els.stopL = h('span', {class: 'opt', text: 'Pause work'});
    els.stop = h('button', {class: 'btn ghost sm', 'data-act': 'stop', title: 'Pause work or continue (S)', 'aria-label': 'Pause work'}, els.stopIc, els.stopL);
    els.answer = h('button', {class: 'btn primary sm', 'data-act': 'answer', title: 'Answer the question below', hidden: true, text: 'Answer'});
    /* a fixed list: what does not apply now is greyed out, never removed; desktop-only rows hide on a phone */
    const menuRow = (action, icon, label, cls) => h('button', {type: 'button', 'data-act': action, class: cls || null}, h('span', {icon}), h('span', {text: label}));
    els.fresh = menuRow('fresh', 'plus', 'Start fresh instead', 'fx-risky');
    els.attachBtn = menuRow('attach', 'external', 'Open live session');
    els.full = menuRow('full', 'expand', 'Full screen', 'fx-desktop');
    els.full.setAttribute('aria-pressed', 'false');
    els.helpBtn = menuRow('help', 'text', 'Keyboard shortcuts', 'fx-desktop');
    els.modeBtn = h('button', {class: 'btn sm fx-desktop', type: 'button', 'data-act': 'mode', 'aria-pressed': 'false', text: 'Terminal mode'});
    els.fullBtn = h('button', {class: 'btn sm fx-desktop', type: 'button', 'data-act': 'full', 'aria-pressed': 'false', text: 'Full screen'});
    els.copyBtn = h('button', {class: 'btn ghost sm fx-desktop', type: 'button', 'data-act': 'copy', text: 'Copy link'});
    els.moreBtn = h('button', {class: 'btn ghost icon sm', type: 'button', icon: 'more', 'aria-label': 'More actions', 'aria-expanded': 'false', 'aria-controls': 'fx-action-menu'});
    els.menu = h('div', {class: 'fx-popover fx-action-menu', id: 'fx-action-menu', hidden: true}, els.full, els.helpBtn,
      els.attachBtn, h('hr', {class: 'fx-menu-divider'}), els.fresh);
    els.more = h('div', {class: 'fx-more'}, els.moreBtn, els.menu);
    els.session = h('section', {class: 'fx-popover fx-session', id: 'fx-session', role: 'dialog', 'aria-labelledby': 'fx-session-title', tabindex: '-1', hidden: true});
    els.liveWrap = h('div', {class: 'fx-live-wrap'}, els.live, els.session);
    els.steps = h('div', {class: 'fx-stepper'});
    els.back = S.views.used ? S.views.used.backLink() : null;
    els.mobileTasks = h('button', {class: 'chip fx-mobile-tasks', type: 'button', 'data-act': 'rail', 'aria-controls': 'fx-tasks', 'aria-expanded': 'false'});
    const backToList = h('a', {class: 'btn ghost sm fx-exit', href: (P || '') + '/', target: '_self', title: 'Back to list'}, h('span', {'aria-hidden': 'true', text: '←'}), h('span', {class: 'opt', text: 'Back to list'}));
    const top = h('header', {class: 'fx-top'}, backToList, els.rail, h('div', {class: 'fx-title'}, h('h1', {}, els.title), els.areaChip, h('span', {class: 'fx-key-hidden', hidden: true}, els.key)),
      els.back, h('div', {class: 'fx-prog'}, els.count, els.prog), els.mobileTasks, h('div', {class: 'fx-tools'}, els.modeBtn, els.fullBtn, els.copyBtn, els.stop, els.more));
    /* the status sits in the step bar: Plan · Work · Check · Done, the current step in the accent colour, then the live state */
    els.taskLine = h('span', {class: 'fx-taskline meta', text: ''});
    const stepbar = h('div', {class: 'fx-stepbar'}, els.steps, els.liveWrap, els.taskLine);
    els.tasks = h('div', {id: 'fx-tasks'});
    els.helpers = h('div');
    els.railNote = h('p', {class: 'meta', style: false});
    els.addInput = h('input', {class: 'input', type: 'text', maxlength: '500', placeholder: 'Add a task', 'aria-label': 'Add a task', name: 'task'});
    els.addForm = h('form', {class: 'fx-add-task', id: 'fx-add-task'}, els.addInput);  // one full-width field; Enter adds the task
    const rail = h('aside', {class: 'fx-rail', 'aria-label': 'Tasks'}, h('div', {}, h('p', {class: 'eyebrow'}, h('span', {text: 'Work log'}), els.railCount = h('span')), els.logMeta = h('p', {class: 'meta fx-log-meta', text: ''}), els.tasks), els.helpers, els.railNote, h('div', {class: 'fx-add-wrap'}, els.addForm));
    els.tabs = [['live', 'Live'], ['proof', 'Results'], ['files', 'Files'], ['used', 'What it read']].map(([id, label], i) => h('button', {class: 'fx-tab', role: 'tab', id: 'fx-t-' + id, 'aria-controls': 'fx-p-' + id, 'aria-selected': String(i === 0), tabindex: i ? '-1' : '0', title: label + ' (' + (i + 1) + ')', 'data-tab': i, text: label}));
    els.sub = h('span', {class: 'meta', text: ''});
    els.feed = h('div', {class: 'fx-feed', role: 'log', 'aria-label': 'What the agent is doing'});
    els.working = h('div', {class: 'fx-working', hidden: true});
    els.line = h('div');
    els.qs = h('div', {class: 'fx-qwrap'});
    els.clash = h('div', {class: 'fx-clash-wrap'});  // "budget-2026.xlsx is also open in PIL-1" (used.js)
    els.sent = h('section', {class: 'fx-sent', 'aria-label': 'Sent back to you', hidden: true});
    /* "Your next move": the open question first, with how many wait and, when a phone is paired, the phone hand-off */
    els.qCount = h('span', {class: 'meta', text: ''});
    els.phoneBtn = h('button', {class: 'btn ghost sm', type: 'button', 'data-act': 'phone', hidden: true, text: 'Answer on phone'});
    els.phoneNote = h('p', {class: 'meta fx-phone-note', hidden: true, text: 'Open this ticket on your paired phone. The same question waits there; the helper stays paused until you answer.'});
    els.next = h('section', {class: 'fx-next', 'aria-label': 'Your next move', hidden: true}, h('div', {class: 'fx-next-h'}, h('span', {class: 'eyebrow', text: 'Your next move'}), els.qCount), els.qs, h('div', {class: 'fx-next-f'}, els.phoneBtn), els.phoneNote);
    /* "With Helper": the ticket's own messages and updates, newest last */
    els.withList = h('div', {class: 'fx-with-list'});
    els.withH = h('section', {class: 'fx-with', 'aria-label': 'With Helper', hidden: true}, h('h2', {text: 'With Helper'}), els.withList);
    /* the compact one-line trace: the latest step, a way into the terminal, and the follow switch */
    els.traceText = h('span', {class: 'fx-trace-text meta', text: ''});
    els.follow = h('input', {class: 'switch', type: 'checkbox', role: 'switch', id: 'fx-follow', 'aria-label': 'Follow the helper'});
    els.newPill = h('button', {class: 'btn sm fx-new', type: 'button', 'data-act': 'jump', hidden: true, text: ''});
    els.showTerm = h('button', {class: 'btn ghost sm fx-desktop fx-show-term', type: 'button', 'data-act': 'mode', text: 'Show terminal →'});
    els.trace = h('div', {class: 'fx-trace'}, els.traceText, els.showTerm, els.newPill, h('label', {class: 'fx-follow-l'}, els.follow, h('span', {text: 'Follow the helper'})));
    els.human = h('aside', {class: 'fx-human', 'aria-label': 'Your side'});
    els.paneLive = h('div', {class: 'fx-pane', id: 'fx-p-live', role: 'tabpanel', 'aria-labelledby': 'fx-t-live'}, els.clash, els.next, els.sent, els.line, els.feed, els.working);
    els.paneProof = h('div', {class: 'fx-pane', id: 'fx-p-proof', role: 'tabpanel', 'aria-labelledby': 'fx-t-proof', hidden: true});
    els.paneFiles = h('div', {class: 'fx-pane', id: 'fx-p-files', role: 'tabpanel', 'aria-labelledby': 'fx-t-files', hidden: true});
    els.paneUsed = h('div', {class: 'fx-pane', id: 'fx-p-used', role: 'tabpanel', 'aria-labelledby': 'fx-t-used', hidden: true});
    els.attachBox = h('div', {class: 'fx-attach', hidden: true});
    els.msg = h('textarea', {id: 'fx-msg', rows: '1', placeholder: 'Write a message…', 'aria-label': 'Write a message'});
    els.form = h('form', {id: 'fx-form'}, els.msg, h('button', {class: 'btn sm', 'aria-label': 'Send', text: 'Send ↑'}));
    const compose = els.compose = h('div', {class: 'fx-compose'}, els.form);
    els.help = helpPanel();
    els.review = h('div', {class: 'fx-review', hidden: true}, h('div', {}, h('p', {text: 'Finished. Looks good?'}), h('p', {class: 'meta', text: 'Next step · Check result'})),
      h('button', {class: 'btn', 'data-act': 'changes', text: 'Ask for changes'}), h('button', {class: 'btn primary', 'data-act': 'done', text: 'Accept'}));
    els.complete = h('div', {class: 'fx-review', hidden: true}, h('p', {text: 'You’re all set here.'}));
    const stage = h('section', {class: 'fx-stage', 'aria-label': 'Ticket activity'}, h('div', {class: 'fx-stage-h', role: 'tablist', 'aria-label': 'Focus views'}, els.tabs, h('span', {class: 'grow'}), els.sub), h('div', {class: 'fx-scan', 'aria-hidden': 'true'}), els.attachBox, els.paneLive, els.paneProof, els.paneFiles, els.paneUsed, compose, els.review, els.complete, els.help);
    root.replaceChildren(top, stepbar, els.trace, h('div', {class: 'fx-body'}, rail, stage, els.human));
    els.stopIc.innerHTML = ic('pause');
    root.querySelectorAll('[data-icon]').forEach(e => { e.innerHTML = ic(e.dataset.icon); });
  }

  function renderTasks(v) {
    const checks = v.ticket.checklist;
    const doing = checks.findIndex(c => !c.done && !c.wont_do && c.state === 'doing');
    if (S.state.sel >= checks.length) S.state.sel = Math.max(0, checks.length - 1);
    const mins = c => S.views.live.taskMinutes(v, c.id);
    const done = checks.filter(c => c.done && !c.wont_do).length, skipped = checks.filter(c => c.wont_do).length;
    const total = checks.reduce((n, c) => n + (parseInt(mins(c), 10) || 0), 0);
    els.logMeta.textContent = checks.length ? [done + ' done', skipped ? skipped + ' skipped' : '', total ? total + ' min' : ''].filter(Boolean).join(' · ') : '';
    const key = keyOf([checks.map(c => [c.id, c.text, c.done, c.wont_do, c.reason, c.state, evText(c), mins(c)]), S.state.sel, v.run.running]);
    if (key === els.tasks.dataset.k) return;
    els.tasks.dataset.k = key;
    els.tasks.replaceChildren(...checks.flatMap((c, i) => {
      const cls = c.wont_do ? 'wont' : c.done ? 'done' : (c.state === 'doing' ? 'doing' : '');
      const row = h('button', {class: 'fx-task ' + cls, 'data-task': String(i), 'aria-current': String(i === (S.state.sel === 0 && doing >= 0 && !els.tasks.dataset.picked ? doing : S.state.sel))},
        h('span', {class: 'st', icon: c.done && !c.wont_do ? 'check' : false, text: c.wont_do ? '–' : false}), h('span', {}, h('span', {class: 'tt', text: (c.done && !c.wont_do ? 'Done · ' : '') + c.text}),
          h('span', {class: 'sub', text: c.wont_do ? 'Skipped' + (c.reason ? ' · ' + c.reason : '') : [mins(c), evText(c)].filter(Boolean).join(' · ')})));
      row.addEventListener('click', () => { S.views.live.scrollToTask(c.id); S.state.sel = i; els.tasks.dataset.picked = '1'; els.tasks.dataset.k = ''; renderTasks(S.state.view); });
      const reason = c.wont_do && c.reason && h('details', {class: 'fx-task-reason meta'}, h('summary', {text: 'Reason'}), h('span', {text: c.reason}));
      const out = [reason ? h('div', {}, row, reason) : row];
      if (els.tasks.dataset.picked && i === S.state.sel) out.push(taskTools(c, i, checks));
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
        form.addEventListener('submit', e => { e.preventDefault(); const t = input.value.trim(); if (t && t !== c.text) res(act('check.edit', {...base, text: t, was: c.text, if_revision: S.state.view.ticket.revision})); form.remove(); });
        tools.after(form); input.focus();
      }),
      i > 0 && btn('Move up', () => res(act('check.move', {ticket: TID, check: checks[i - 1].id, after: c.id}))),
      i < checks.length - 1 && btn('Move down', () => res(act('check.move', {...base, after: checks[i + 1].id}))),
      !c.done && !c.wont_do && btn("Won't do", () => {
        const input = h('input', {class: 'input', placeholder: 'Reason (optional)', 'aria-label': 'Reason (optional)', maxlength: '200'});
        const form = h('form', {class: 'fx-task-edit'}, input, h('button', {class: 'btn primary xs', text: 'Save'}));
        form.addEventListener('submit', e => { e.preventDefault(); res(act('check.wont_do', {...base, reason: input.value.trim()})); form.remove(); });
        tools.after(form); input.focus();
      }),
      (c.done || c.wont_do) && btn('Open again', () => res(act('check.reopen', base))),
      btn('Remove', () => res(act('check.remove', base), 'Removed. It stays in the history.')));
    return tools;
  }

  function renderHelpers(v) {
    S.views.used.renderTree(v);  // the main agent and its helpers as a tree; a row filters the Details steps
  }

  function renderProof(v) {
    proof.setPageKey(v.page_key);
    proof.setAgent('Helper');
    const done = v.ticket.checklist.filter(c => c.done && !c.wont_do);
    const list = [];
    for (const c of done) for (const ev of c.evidence || []) list.push({c, ev});
    const key = keyOf([v.ticket.status, v.ticket.closed_at, v.ticket.history, v.run.label, list]);
    const count = window.FocusHelpers.resultCount(v.ticket.checklist);  // tasks, the same unit as "1 of 1 tasks"
    els.tabs[1].textContent = 'Results';
    if (count) els.tabs[1].append(h('sup', {text: ' ' + count}));
    S.views.ticket.showTab(1, !!list.length || ['review', 'done'].includes(v.ticket.status));
    if (key === els.paneProof.dataset.k) return;
    els.paneProof.dataset.k = key;
    const files = list.filter(x => x.ev.type !== 'note');
    const primary = files[files.length - 1] || list[list.length - 1];
    const content = h('div', {class: 'fx-results'}, h('h2', {text: v.state === 'done' ? 'Work completed' : list.length ? 'Ready for your look' : 'No results yet'}),
      list.length ? null : h('p', {class: 'meta', text: 'Results will appear here when a task is done.'}));  // the title is in the header: shown once
    const completed = window.FocusHelpers.completedAt(v.ticket);
    if (v.state === 'done' && completed) content.append(h('p', {class: 'meta', text: 'Completed ' + stamp(completed).replace(/ (\d\d:)/, ' at $1')}));
    if (primary) content.append(proof.tile(primary, from => proof.open(list, list.indexOf(primary), from)));
    for (const c of done) content.append(h('p', {class: 'fx-result-note', text: '✓ ' + c.text + ' — ' + evText(c)}));
    if (files.length) content.append(h('div', {class: 'fx-result-files'}, files.map(({c, ev}) => h('p', {class: 'meta', text: c.text + ' · ' + String(ev.ref || '').split('/').pop() + (ev.summary ? ' · ' + ev.summary : '')}))));
    els.paneProof.replaceChildren(content);
    renderSent(v, list);
  }

  /* "Sent back to you": what the helper handed over, as small cards you can open in place (no PDFs or live pages mounted) */
  function renderSent(v, list) {
    const key = keyOf([v.ticket.status, list.map(x => [x.c.id, x.ev.ref, x.ev.type, x.ev.summary])]);
    if (key === els.sent.dataset.k) return;
    els.sent.dataset.k = key;
    els.sent.hidden = !list.length;
    if (!list.length) { els.sent.replaceChildren(); return; }
    const files = list.filter(x => x.ev.type !== 'note');
    const cards = [...files.map(x => proof.tile(x, from => proof.open(list, list.indexOf(x), from))),
      ...list.filter(x => x.ev.type === 'note').map(({c, ev}) => h('article', {class: 'fx-sent-note card'}, h('p', {class: 'eyebrow', text: 'Result'}), h('strong', {text: c.text}), h('p', {class: 'meta', text: String(ev.text || ev.ref || '')})))];
    const review = v.ticket.status === 'review';
    els.sent.replaceChildren(h('div', {class: 'row'}, h('h2', {class: 'grow', text: 'Sent back to you'}), h('span', {class: 'meta', text: list.length + (list.length === 1 ? ' item' : ' items')})),
      h('div', {class: 'fx-sent-grid'}, cards), ...(review ? [h('p', {class: 'meta', text: 'Checking a result records your feedback. It does not publish anything.'})] : []));
  }

  /* an empty tab is hidden; if it was the open one, Live opens instead */
  function showTab(i, on) {
    const tab = els.tabs && els.tabs[i];
    if (!tab || tab.hidden === !on) return;
    tab.hidden = !on;
    if (!on && tab.getAttribute('aria-selected') === 'true') els.tabs[0].click();
  }

  S.register('ticket', {showTab, picker, pickerSub, build, renderTasks, taskTools, renderHelpers, renderProof});
})();
