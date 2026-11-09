// Owns the picker, ticket skeleton, tasks, helpers, and results.
(function () {
  'use strict';
  const S = window.FocusStore;
  const {root, ic, TID, P, INAPP, h, toast, helpPanel, els, act, proof, keyOf, stamp, evText} = S;

  function picker() {
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

  function renderTasks(v) {
    const checks = v.ticket.checklist;
    const doing = checks.findIndex(c => !c.done && c.state === 'doing');
    if (S.state.sel >= checks.length) S.state.sel = Math.max(0, checks.length - 1);
    const key = keyOf([checks.map(c => [c.id, c.text, c.done, c.state, evText(c)]), S.state.sel, v.run.running]);
    if (key === els.tasks.dataset.k) return;
    els.tasks.dataset.k = key;
    els.tasks.replaceChildren(...checks.flatMap((c, i) => {
      const cls = c.done ? 'done' : (c.state === 'doing' ? 'doing' : '');
      const row = h('button', {class: 'fx-task ' + cls, 'data-task': String(i), 'aria-current': String(i === (S.state.sel === 0 && doing >= 0 && !els.tasks.dataset.picked ? doing : S.state.sel))},
        h('span', {class: 'st', icon: c.done ? 'check' : false}), h('span', {}, h('span', {class: 'tt', text: c.text}), h('span', {class: 'sub', text: evText(c)})));
      row.addEventListener('click', () => { S.state.sel = i; els.tasks.dataset.picked = '1'; els.tasks.dataset.k = ''; renderTasks(S.state.view); });
      const out = [row];
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
      c.done && btn('Open again', () => res(act('check.reopen', base))),
      btn('Remove', () => res(act('check.remove', base), 'Removed. It stays in the history.')));
    return tools;
  }

  function renderHelpers(v) {
    const hs = v.board.helpers;
    els.helpers.replaceChildren(...(hs.length ? [h('div', {}, h('p', {class: 'eyebrow'}, h('span', {text: 'Helpers'}), h('span', {text: String(hs.length)})),
      ...hs.map(x => h('div', {class: 'fx-helper'}, h('div', {class: 'row'}, h('span', {class: 'dot working'}), h('span', {class: 'grow', text: x.text})))))] : []));
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
      list.length ? null : h('p', {class: 'meta', text: 'Results will appear here when a task is done.'}));  // the title is in the header: shown once
    const completed = window.FocusHelpers.completedAt(v.ticket);
    if (v.state === 'done' && completed) content.append(h('p', {class: 'meta', text: 'Completed ' + stamp(completed).replace(/ (\d\d:)/, ' at $1')}));
    if (primary) content.append(proof.tile(primary, from => proof.open(list, list.indexOf(primary), from)));
    for (const c of done) content.append(h('p', {class: 'fx-result-note', text: '✓ ' + c.text + ' — ' + evText(c)}));
    if (files.length) content.append(h('details', {}, h('summary', {text: 'Details'}), files.map(({c, ev}) => h('p', {class: 'meta', text: c.text + ' · ' + String(ev.ref || '').split('/').pop() + (ev.summary ? ' · ' + ev.summary : '')}))));
    els.paneProof.replaceChildren(content);
  }

  S.register('ticket', {picker, build, renderTasks, taskTools, renderHelpers, renderProof});
})();
