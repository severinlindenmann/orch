// Owns the picker, ticket skeleton, tasks, helpers, and results.
(function () {
  'use strict';
  const S = window.FocusStore;
  const {root, ic, TID, P, INAPP, h, toast, helpPanel, els, act, proof, keyOf, stamp, evText} = S;

  const KIND_LABEL = {image: 'Picture', pdf: 'PDF', table: 'Table', page: 'Page', doc: 'Document', code: 'Code', text: 'Note', command: 'Command', commit: 'Change', link: 'Link', missing: 'File', other: 'File'};

  /* A ticket that waits for review, as a result card (master result-card): preview, result name, ticket name, kind,
     local time and one button. The preview is a picture or the first lines of a text file; no preview = a kind label. */
  function resultCard(t) {
    const r = t.result || null;
    const kind = KIND_LABEL[r && r.kind] || 'Result';
    const thumb = h('span', {class: 'thumb', text: kind});
    if (r && typeof r.preview === 'string' && r.preview.startsWith('/api/file?')) {
      const src = P + r.preview;
      if (r.kind === 'image') {  // in the dashboard's sandboxed frame a picture address carries the frame pass
        const img = h('img', {alt: '', loading: 'lazy'}); img.src = window.OrchFrame ? window.OrchFrame.url(src) : src; thumb.replaceChildren(img);
      } else {
        fetch(src).then(x => x.ok && (x.headers.get('Content-Type') || '').startsWith('text/plain') ? x.text() : null)
          .then(txt => { if (txt) thumb.replaceChildren(h('pre', {text: txt.slice(0, 600).split('\n').slice(0, 8).join('\n')})); }).catch(() => {});
      }
    }
    const when = r && r.at ? stamp(r.at) : '';
    return h('a', {class: 'result-card', href: P + '/t/' + t.id + '#results'}, thumb,
      h('span', {class: 'body'}, h('strong', {text: (r && r.name) || t.title}), h('span', {class: 'meta', text: t.title}),
        h('span', {class: 'row'}, h('span', {class: 'chip', text: kind}), h('span', {class: 'meta grow', text: when}), h('span', {class: 'btn outline sm', text: 'Check result'}))));
  }

  function picker() {
    document.title = 'Focus · orch';
    root.classList.add('fx-picker');
    /* inside the dashboard the page has no header of its own: no Back to Home, no crumb, no Help bar */
    root.append(...(INAPP ? [] : [h('header', {class: 'fx-top'}, h('span', {class: 'meta fx-workspace', text: 'Focus'}), h('button', {class: 'btn ghost sm', 'data-act': 'help', text: 'Help'}))]),
      h('main', {class: 'fx-pick'}, h('h1', {text: 'Focus'}), h('p', {class: 'meta fx-sub', text: 'Loading your tickets…'}), skeleton()));
    /* the lists wait for the first Live now answer (at most a few seconds), so nothing moves after they show */
    const tickets = fetch(P + '/api/tickets').then(r => { if (!r.ok) throw Error(); return r.json(); });
    /* Focus opens on this start page, the Helpers list first (ORCH-61); the next ticket that needs the person is one
       button below it, never a jump. */
    tickets.then(payload => S.views.livenow.ready(LIVE_WAIT_MS).then(() => payload)).then(payload => {
      if (!payload) return;
      const list = payload.tickets;
      const next = INAPP ? window.FocusHelpers.nextNeeding(list) : null;
      const crumb = root.querySelector('.fx-workspace'); if (crumb) crumb.textContent = payload.workspace + ' / Focus';
      S.state.pickList = list;
      pickAttention();
      const box = root.querySelector('.fx-pick');
      box.querySelector('.fx-skel')?.remove();
      if (!list.some(t => t.status !== 'done')) box.append(emptyState());
      const groups = [['waiting', 'Needs you', 'Answer'], ['review', 'Sent back to you', 'Check result'], ['active', 'Working', 'Watch'], ['ready', 'Ready to start', 'Start'], ['open', 'To do', 'Start']];
      /* one line: key, title, the actual next step only when it says more, and a real action button */
      const rowFor = (t, status, action) => {
        const next = window.FocusHelpers.nextStepText(t, action);
        const finished = status === 'done' && t.closed_at ? stamp(t.closed_at) : '';
        return h('a', {class: 'fx-pick-row', href: P + '/t/' + t.id + (status === 'review' ? '#results' : '')},
          /^t_/.test(t.key || t.id) ? null : h('span', {class: 'mono key', text: t.key}), h('strong', {class: 'grow', text: t.title}),
          next ? h('small', {text: next}) : null, finished ? h('small', {text: 'Finished ' + finished}) : null,
          h('span', {class: 'btn outline sm', text: action}));  /* a real 32 px button from the master, not a chip */
      };
      if (next) box.append(h('div', {class: 'row'}, h('a', {class: 'btn outline sm', href: P + '/t/' + next.ticket.id + next.hash, text: 'Open the next ticket that needs you'}),
        h('a', {class: 'btn ghost sm', href: '/#home', target: '_top', text: 'See everything on Home'})));
      for (const [status, label, action] of groups) {
        if (INAPP && (status === 'waiting' || status === 'review')) continue;  /* Home lists these; not twice */
        const rows = window.FocusHelpers.groupRows(list, status);
        if (!rows.length) continue;
        const {shown, more} = window.FocusHelpers.limitGroup(rows);
        const cards = status === 'review';  /* results are cards, every other group stays a row */
        const one = t => cards ? resultCard(t) : rowFor(t, status, action);
        const card = h('div', {class: cards ? 'result-grid' : 'card'}, shown.map(one));
        const all = more ? h('button', {class: 'btn ghost sm fx-show-all', type: 'button', text: 'Show all (' + rows.length + ')'}) : null;
        if (all) all.addEventListener('click', () => { card.replaceChildren(...rows.map(one)); all.remove(); });
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
    const toggle = on => { help.hidden = !on; (on ? help.querySelector('button') : helpButton)?.focus(); };
    root.addEventListener('click', e => { if (e.target.closest('[data-act=help]')) toggle(help.hidden); else if (e.target === help) toggle(false); });
    document.addEventListener('keydown', e => {
      if (e.metaKey || e.ctrlKey || e.altKey || e.target.closest('input,textarea,select')) return;
      if (e.key === '?') { e.preventDefault(); toggle(help.hidden); }
      if (!help.hidden && ['Escape', 'x', 'X'].includes(e.key)) toggle(false);
      if (!help.hidden && e.key === 'Tab') { e.preventDefault(); help.querySelector('button').focus(); }
    });
  }

  const LIVE_WAIT_MS = 4000;
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

  /* What needs the person, in the picker line. Inside the dashboard it is the dashboard's own number (the top bar's,
     sent by postMessage), so both say the same (ORCH-63); alone, Focus counts open questions and results itself. */
  function pickAttention() {
    const list = S.state.pickList;
    if (INAPP && Number.isInteger(S.state.dashNeeds)) S.state.pickAttention = window.FocusHelpers.dashCountText(S.state.dashNeeds) + (S.state.dashNeeds ? ' They are on Home.' : '');
    else if (list) S.state.pickAttention = window.FocusHelpers.attentionText(list) + (INAPP && list.some(window.FocusHelpers.needsYou) ? ' They are on Home too.' : '');
    pickerSub();
  }
  if (INAPP) {
    window.addEventListener('message', e => {
      const d = e.data;
      if (e.origin !== location.origin || e.source !== window.parent || !d || d.type !== 'orch.needs.count' || !Number.isInteger(d.count) || d.count < 0) return;
      if (S.state.dashNeeds === d.count) return;
      S.state.dashNeeds = d.count; pickAttention();
    });
    try { window.parent.postMessage({orch: 'needs-count', chan: (window.OrchFrame || {}).chan}, location.origin); } catch (e) { /* not framed */ }
  }

  /* "2 agents are working. One question needs you." The agent count comes from the live cards, the rest from the tickets. */
  function pickerSub() {
    const sub = root.querySelector('.fx-pick > .meta');
    const line = window.FocusHelpers.pickerLine(S.state.pickAgents, S.state.pickAttention);
    if (sub && line && sub.textContent !== line) sub.textContent = line;
  }

  function build() {
    els.rail = h('button', {class: 'btn ghost icon sm', 'data-act': 'rail', 'aria-label': 'Show or hide steps', 'aria-expanded': 'true', title: 'Tasks ( [ )', icon: 'table'});
    els.key = h('span', {class: 'mono key', text: TID});
    els.title = h('span', {text: ''});
    els.areaChip = h('span', {class: 'chip success fx-area-chip', hidden: true, text: ''});  // the area this ticket works in (a label only)
    els.count = h('span', {text: ''});
    els.bar = h('span');
    els.prog = h('div', {class: 'progress', role: 'progressbar', 'aria-label': 'Steps done', 'aria-valuemin': '0'}, els.bar);
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
    els.attachBtn = menuRow('attach', 'external', 'Helper’s screen in a terminal');
    els.interruptBtn = menuRow('interrupt', 'pause', 'Interrupt now');
    els.interruptBtn.title = 'Stop what the helper is doing and read the message in the box now';
    els.full = menuRow('full', 'expand', 'Full screen', 'fx-desktop');
    els.full.setAttribute('aria-pressed', 'false');
    els.helpBtn = menuRow('help', 'text', 'Keyboard shortcuts', 'fx-desktop');
    els.modeBtn = h('button', {class: 'btn sm fx-desktop', type: 'button', 'data-act': 'mode', 'aria-pressed': 'false', text: 'Terminal mode'});
    els.fullBtn = h('button', {class: 'btn sm fx-desktop', type: 'button', 'data-act': 'full', 'aria-pressed': 'false', text: 'Full screen'});
    els.copyBtn = h('button', {class: 'btn ghost sm fx-desktop', type: 'button', 'data-act': 'copy', text: 'Copy link'});
    els.moreBtn = h('button', {class: 'btn ghost icon sm', type: 'button', icon: 'more', 'aria-label': 'More actions', 'aria-expanded': 'false', 'aria-controls': 'fx-action-menu'});
    els.menu = h('div', {class: 'fx-popover fx-action-menu', id: 'fx-action-menu', hidden: true}, INAPP ? null : els.full, els.helpBtn,
      els.attachBtn, els.interruptBtn, h('hr', {class: 'fx-menu-divider'}), els.fresh);
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
    const rail = h('aside', {class: 'fx-rail', 'aria-label': 'Steps'}, h('div', {}, h('p', {class: 'eyebrow'}, h('span', {text: 'Work log'}), els.railCount = h('span')), els.logMeta = h('p', {class: 'meta fx-log-meta', text: ''}), els.tasks), els.helpers, els.railNote, h('div', {class: 'fx-add-wrap'}, els.addForm));
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
    els.phoneLine = h('p', {class: 'handoff', 'aria-live': 'polite', hidden: true});
    els.next = h('section', {class: 'fx-next', 'aria-label': 'Your next move', hidden: true}, h('div', {class: 'fx-next-h'}, h('span', {class: 'eyebrow', text: 'Your next move'}), els.qCount), els.qs, els.phoneLine);
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
      h('button', {class: 'btn', 'data-act': 'changes', text: 'Send back'}), h('button', {class: 'btn primary', 'data-act': 'done', text: 'Looks good'}));
    els.complete = h('div', {class: 'fx-review', hidden: true}, h('p', {text: 'You’re all set here.'}));
    const stage = els.stage = h('section', {class: 'fx-stage', 'aria-label': 'Ticket activity'}, h('div', {class: 'fx-stage-h', role: 'tablist', 'aria-label': 'Focus views'}, els.tabs, h('span', {class: 'grow'}), els.sub), h('div', {class: 'fx-scan', 'aria-hidden': 'true'}), els.attachBox, els.paneLive, els.paneProof, els.paneFiles, els.paneUsed, compose, els.review, els.complete, els.help);
    if (INAPP) { buildShell(top, stepbar, rail, stage); return; }
    root.replaceChildren(top, stepbar, els.trace, h('div', {class: 'fx-body'}, rail, stage, els.human));
    els.stopIc.innerHTML = ic('pause');
    root.querySelectorAll('[data-icon]').forEach(e => { e.innerHTML = ic(e.dataset.icon); });
  }

  /* Inside the dashboard: one shell, three columns (the master .focus3 look). Tickets on the left, the live session
     in the centre with Pause while it writes, one result panel on the right with Looks good / Send back when done.
     The same nodes as the stand-alone page, only arranged differently, so every action keeps working. */
  const DOT = {waiting: 'dot-warn', review: 'dot-warn', active: 'dot-work', done: 'dot-ok'};
  function buildShell(top, stepbar, rail, stage) {
    root.classList.add('fx-shell', 'fx-terminal');
    try { parent.postMessage({orch: 'embed-shell', path: location.pathname, chan: (window.OrchFrame || {}).chan}, location.origin); } catch (e) { /* not framed */ }
    els.ticketList = h('div', {class: 'fx-tickets', role: 'list', 'aria-label': 'Tickets in focus'});
    const left = h('aside', {class: 'focus-list fx-left', 'aria-label': 'Tickets in focus'},
      h('div', {class: 'card-h'}, h('h3', {text: 'Tickets in focus'})), els.ticketList,
      h('div', {class: 'row'}, h('a', {class: 'btn ghost sm', href: '/#home', target: '_top', text: 'See everything on Home'}),
        h('a', {class: 'btn ghost sm', href: P + '/', text: 'All helpers'})), rail);
    /* the ticket page's header line (ORCH-71): ORCH-n · state pill · Step 3 of 4 · 52 min, then the title */
    els.headLine = h('p', {class: 'meta', 'data-key': 'focus-head-line'});
    const head = h('div', {class: 'fx-chead'}, h('div', {class: 'grow'}, els.headLine, h('h1', {}, els.title)), els.stop, els.more);
    stage.prepend(head);
    els.resultEmpty = h('p', {class: 'meta fx-result-empty', text: 'Results appear here as the helper finishes steps.'});
    els.resultHead = h('h2', {text: 'Result so far'});
    root.replaceChildren(h('div', {class: 'focus3 fx-body'}, left, stage, els.human));
    refreshTickets();
    S.subscribe(() => { refreshTickets(); els.resultEmpty.hidden = !els.sent.hidden; });
  }
  let listAt = 0;
  async function refreshTickets() {
    if (Date.now() - listAt < 10000 && els.ticketList.childNodes.length) return;
    listAt = Date.now();
    try {
      const r = await fetch(P + '/api/tickets'); if (!r.ok) return;
      const list = window.FocusHelpers.listOrder((await r.json()).tickets.filter(t => t.status !== 'done' || t.id === TID));
      els.ticketList.replaceChildren(...list.map(t => h('a', {class: 'list-row' + (t.id === TID ? ' cur' : ''), role: 'listitem', href: P + '/t/' + t.id, 'aria-current': t.id === TID ? 'page' : null},
        h('span', {class: window.FocusHelpers.needsYou(t) ? 'dot-warn' : DOT[t.status] || 'dot-work', 'aria-hidden': 'true'}), typeof t.key === 'string' && t.key && !/^t_/.test(t.key) ? h('span', {class: 'key', text: t.key}) : null, h('strong', {class: 'grow', text: t.title}))));
    } catch (e) { /* the list keeps what it had */ }
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
    const content = h('div', {class: 'fx-results'}, h('h2', {text: v.state === 'done' ? 'Work completed' : list.length ? 'Ready for your look' : 'No results yet'}),
      list.length ? null : h('p', {class: 'meta', text: 'Results will appear here when a task is done.'}));  // the title is in the header: shown once
    const completed = window.FocusHelpers.completedAt(v.ticket);
    if (v.state === 'done' && completed) content.append(h('p', {class: 'meta', text: 'Completed ' + stamp(completed).replace(/ (\d\d:)/, ' at $1')}));
    content.append(...resultRows(list));  // the same plain lines as "Result so far" (ORCH-71)
    els.paneProof.replaceChildren(content);
    renderSent(v, list);
  }

  /* One plain line per result: what, what came out, Open (the preview panel, in place). */
  function resultRows(list) {
    return list.map((item, i) => {
      const line = window.FocusHelpers.resultLine(item);
      const open = h('button', {class: 'btn ghost sm', type: 'button', 'aria-haspopup': 'dialog', 'aria-label': 'Open ' + line.what, text: 'Open', onclick: () => proof.open(list, i, open)});
      return h('div', {class: 'card-row', 'data-key': 'result-' + i},
        h('div', {class: 'grow'}, h('strong', {text: line.what}), line.outcome ? h('p', {class: 'meta', text: line.outcome}) : null), open);
    });
  }
  /* "Result so far" / "Sent back to you": one plain line per result (ORCH-71): what it is, what came out, and Open.
     Open shows the result in place (the preview panel); no kinds, commands or file names on the line. */
  function renderSent(v, list) {
    const key = keyOf([v.ticket.status, list.map(x => [x.c.id, x.ev.ref, x.ev.type, x.ev.summary, x.ev.title])]);
    if (key === els.sent.dataset.k) return;
    els.sent.dataset.k = key;
    els.sent.hidden = !list.length;
    if (!list.length) { els.sent.replaceChildren(); return; }
    const rows = resultRows(list);
    const review = v.ticket.status === 'review';
    els.sent.replaceChildren(...(INAPP ? [] : [h('div', {class: 'row'}, h('h2', {class: 'grow', text: 'Sent back to you'}), h('span', {class: 'meta', text: list.length + (list.length === 1 ? ' item' : ' items')}))]),
      ...rows, ...(review ? [h('p', {class: 'meta', text: 'Checking a result records your feedback. It does not publish anything.'})] : []));
  }

  /* Where a question also waits: one quiet line under the answers, "Sent to your phone 12:31. Answer here or there,
     whichever is first." The other way round (answered there) is live.js: the card closes into its own line. */
  function phoneLine(v, now = Date.now()) {
    const qs = (v.ticket && v.ticket.questions) || [];
    const open = qs.filter(q => q.answer == null && typeof q.sent_at === 'string');
    if (open.length) return {text: 'Sent to your phone ' + S.hhmm(open[open.length - 1].sent_at) + '. Answer here or there, whichever is first.', answered: false};
    return null;
  }
  function renderPhoneLine(v) {
    const line = phoneLine(v);
    els.phoneLine.hidden = !line;
    els.phoneLine.classList.toggle('answered', !!(line && line.answered));
    els.phoneLine.textContent = line ? line.text : '';
  }

  /* an empty tab is hidden; if it was the open one, Live opens instead */
  function showTab(i, on) {
    const tab = els.tabs && els.tabs[i];
    if (!tab || tab.hidden === !on) return;
    tab.hidden = !on;
    if (!on && tab.getAttribute('aria-selected') === 'true') els.tabs[0].click();
  }

  S.register('ticket', {resultCard, phoneLine, renderPhoneLine, showTab, refreshTickets, picker, pickerSub, build, renderTasks, taskTools, renderHelpers, renderProof});
})();
