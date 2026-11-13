// Owns bootstrap, applying views, wiring, and polling; textContent, never innerHTML.
(function () {
  'use strict';
  const S = window.FocusStore;
  const {root, ic, TID, P, INAPP, h, toast, statusWord, els, act, proof} = S;

  function apply(v) {
    const prev = S.state.view;
    S.views.session.syncTimer(v);
    S.state.view = v;
    if (prev && prev.ticket.status !== v.ticket.status) S.state.changesRequested = false;
    const t = v.ticket;
    document.title = t.title + ' · Focus';
    els.title.textContent = t.title || '';
    els.key.textContent = typeof t.key === 'string' && t.key ? t.key : TID;  /* the short key people use, e.g. DM1-12 */
    root.dataset.state = v.state;
    if (prev && !root.hasAttribute('data-live')) root.setAttribute('data-live', '');  /* motion only after a live change */
    els.agent.textContent = 'Helper';  // never the vendor's name on screen
    const stateText = window.FocusHelpers.sessionState(v).pill || statusWord(t);
    const shownText = window.FocusHelpers.holdText(v) || stateText;  /* why orch waits, in the core's words; gone when it clears */
    if (els.stateText.textContent !== shownText) els.stateText.textContent = shownText;
    els.live.toggleAttribute('data-hold', shownText !== stateText);
    const phase = window.FocusHelpers.phase(v);
    els.steps.replaceChildren(...['Plan', 'Work', 'Check', 'Done'].map((name, i) => h('span', {'aria-current': i === phase ? 'step' : null, text: name})));
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
    els.stopL.textContent = running ? 'Pause work' : 'Continue';
    els.stop.setAttribute('aria-label', running ? 'Pause work' : 'Continue');
    els.compose.hidden = v.state === 'done' || S.state.tab >= 2 || (S.state.tab === 1 && t.status === 'review' && !S.state.changesRequested);  /* a done ticket is a read-only board; Continue starts a run */
    /* an open question: Answer is the main action; Continue and Start fresh wait until it is answered */
    const asking = v.ticket.questions.some(q => q.answer == null);
    els.answer.hidden = !asking;
    els.stop.hidden = (asking && !running) || (!running && !hasStarted);
    els.fresh.disabled = running || asking || !hasStarted;
    els.review.hidden = S.state.tab !== 1 || t.status !== 'review' || asking || running;
    els.complete.hidden = v.state !== 'done';
    els.attachBtn.disabled = !(running && v.live);
    els.sub.textContent = '';
    /* whose turn it is, and where the work is */
    const turn = v.state === 'done' ? 'Finished' : asking || t.status === 'review' ? 'Your turn' : running ? 'Helper’s turn' : '';
    const base = els.stateText.textContent.split(' · ')[0];
    if (turn && !base.startsWith('Finished') && turn !== 'Finished') els.stateText.textContent = base + ' · ' + turn;
    const now = t.checklist.find(c => !c.done && !c.wont_do);
    els.taskLine.textContent = v.total && now ? 'Task ' + (v.done + 1) + ' of ' + v.total + ' · ' + now.text : '';
    if (!S.state.changesRequested) els.msg.placeholder = 'Write a message…';
    els.feed.setAttribute('aria-label', 'What ' + els.agent.textContent + ' is doing');
    els.railNote.textContent = '';
    S.views.ticket.renderTasks(v);
    S.views.ticket.renderHelpers(v);
    S.views.live.renderFeed(v, !S.state.firstRender);
    S.views.live.renderQuestions(v);
    S.views.live.renderNext(v);
    S.views.live.renderWith(v);
    S.views.live.followUpdate(S.views.live.renderTrace(v), S.state.firstRender);
    S.views.ticket.renderProof(v);
    S.views.used.renderUsed(v);
    S.views.used.renderFiles(v);
    S.views.live.renderLine(v);
    S.views.live.renderWorking(v);
    S.views.session.tickTimer();
    S.views.session.renderSession(v);
    if (root.classList.contains('fx-terminal') && ((S.state.firstRender && (['review', 'done'].includes(t.status) || location.hash === '#results')) || (t.status === 'done' && prev?.ticket.status !== 'done'))) els.tabs[1].click();
    S.state.firstRender = false;
    S.notify(v);
  }

  /* Compact is the default; Terminal mode adds the task rail and the tabs. The choice is remembered. */
  /* In Terminal mode the person's side (next move, sent back, With Helper, composer) is its own column beside the
     output; in compact it sits in the one column, as before. The same nodes move, so nothing is drawn twice. */
  function placeHuman(terminal) {
    if (terminal) els.human.replaceChildren(els.next, els.sent, els.withH, els.review, els.complete, els.compose);
    else {
      els.paneLive.insertBefore(els.next, els.line); els.paneLive.insertBefore(els.sent, els.line);
      els.paneLive.insertBefore(els.withH, els.line);
      els.help.before(els.compose, els.review, els.complete);  /* back in the stage: composer, then the review bar */
    }
  }
  function setMode(terminal) {
    placeHuman(terminal);
    root.classList.toggle('fx-terminal', terminal);
    els.modeBtn.setAttribute('aria-pressed', String(terminal));
    els.modeBtn.textContent = terminal ? 'Compact view' : 'Terminal mode';
    els.showTerm.hidden = terminal;
    try { localStorage.setItem('focus-mode', terminal ? 'terminal' : 'compact'); } catch (e) { /* not kept */ }
  }
  async function copyLink() {
    const url = location.origin + location.pathname;
    try { await navigator.clipboard.writeText(url); toast('Link copied', 'ok'); } catch (e) { toast('Copy this address: ' + url, 'error'); }
  }

  function wire() {
    let saved = ''; try { saved = localStorage.getItem('focus-mode') || ''; } catch (e) { /* none */ }
    setMode(saved === 'terminal');
    const markFull = on => { root.classList.toggle('is-full', on); els.fullBtn.setAttribute('aria-pressed', String(on)); els.fullBtn.textContent = on ? 'Exit full screen' : 'Full screen'; els.full.setAttribute('aria-pressed', String(on)); els.full.lastElementChild.textContent = on ? 'Leave full screen' : 'Full screen'; els.full.setAttribute('aria-label', on ? 'Leave full screen' : 'Full screen'); document.body.style.overflow = on ? 'hidden' : ''; };
    const setFull = async on => {
      if (on) { try { await root.requestFullscreen?.(); } catch (e) { /* CSS fallback */ } markFull(true); }
      else { if (document.fullscreenElement) { try { await document.exitFullscreen(); } catch (e) { /* ignore */ } } markFull(false); }
    };
    document.addEventListener('fullscreenchange', () => { if (!document.fullscreenElement && root.classList.contains('is-full')) markFull(false); });
    const toggleRail = () => { const closed = root.classList.toggle('rail-closed'); els.rail.setAttribute('aria-expanded', String(!closed)); els.mobileTasks.setAttribute('aria-expanded', String(!closed)); };
    const narrow = matchMedia('(max-width: 720px)');
    if (narrow.matches) toggleRail();
    narrow.addEventListener('change', e => { root.classList.toggle('rail-closed', e.matches); els.rail.setAttribute('aria-expanded', String(!e.matches)); els.mobileTasks.setAttribute('aria-expanded', String(!e.matches)); });
    /* The composer is pinned at the bottom on a phone: the pane keeps that much room below its last row. */
    if (typeof ResizeObserver !== 'undefined') new ResizeObserver(() => root.style.setProperty('--fx-compose-h', els.compose.offsetHeight + 'px')).observe(els.compose);
    const toggleHelp = force => { els.help.hidden = force === undefined ? !els.help.hidden : !force; if (!els.help.hidden) els.help.querySelector('button').focus(); else els.moreBtn.focus(); };
    const selectTab = i => { if (els.tabs[i].hidden) return; S.state.tab = i; els.review.hidden = i !== 1 || S.state.view?.ticket.status !== 'review' || S.state.view?.run.running || S.state.view?.state === 'needs'; els.compose.hidden = S.state.view?.state === 'done' || i >= 2 || (i === 1 && S.state.view?.ticket.status === 'review' && !S.state.changesRequested); els.tabs.forEach((b, j) => { const on = i === j; b.setAttribute('aria-selected', String(on)); b.tabIndex = on ? 0 : -1; document.getElementById(b.getAttribute('aria-controls')).hidden = !on; }); };
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
    const armFresh = on => { els.fresh.classList.toggle('fx-confirm', on); els.fresh.lastElementChild.textContent = on ? 'Click again to start fresh' : 'Start fresh instead'; };
    const closePopovers = () => {
      armFresh(false);
      setPopover(els.menu, els.moreBtn, false);
      setPopover(els.session, els.live, false);
    };
    /* Following starts off; reading pauses it (scroll away) and it never scrolls the view while it is off. */
    try { S.state.follow = localStorage.getItem('focus-follow') === '1'; } catch (e) { S.state.follow = false; }
    els.follow.checked = S.state.follow;
    els.follow.addEventListener('change', () => { S.state.follow = els.follow.checked; try { localStorage.setItem('focus-follow', S.state.follow ? '1' : '0'); } catch (e) { /* not kept */ } if (S.state.follow) S.views.live.jumpToNew(); });
    els.paneLive.addEventListener('scroll', () => { if (!els.newPill.hidden && S.views.live.atBottom()) S.views.live.jumpToNew(); }, {passive: true});
    els.moreBtn.addEventListener('click', () => {
      const open = els.menu.hidden; closePopovers(); setPopover(els.menu, els.moreBtn, open);
      if (open) [...els.menu.querySelectorAll('button:not(:disabled)')].find(b => b.offsetParent !== null)?.focus();
    });
    els.live.addEventListener('click', () => {
      const open = els.session.hidden; closePopovers();
      if (S.state.view) S.views.session.renderSession(S.state.view);
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
      if (e.target.closest('[data-act]')?.disabled) return;  // a greyed-out menu row does nothing, even if the click gets through
      const a = e.target.closest('[data-act]')?.dataset.act;
      /* Start fresh asks once: the first click turns the row into its own confirm, the second starts */
      if (a === 'fresh' && !els.fresh.disabled && !els.fresh.classList.contains('fx-confirm')) { armFresh(true); return; }
      if (els.menu.contains(e.target) && e.target.closest('button')) { closePopovers(); els.moreBtn.focus(); }
      if (a === 'mode') setMode(!root.classList.contains('fx-terminal'));
      else if (a === 'jump') S.views.live.jumpToNew();
      else if (a === 'phone') { els.phoneNote.hidden = !els.phoneNote.hidden; els.phoneBtn.setAttribute('aria-expanded', String(!els.phoneNote.hidden)); }
      else if (a === 'copy') copyLink();
      else if (a === 'rail') toggleRail(); else if (a === 'full') setFull(!root.classList.contains('is-full')); else if (a === 'help') toggleHelp();
      else if (a === 'answer') S.views.live.focusQuestion(); else if (a === 'stop') S.views.live.stopToggle(); else if (a === 'fresh') { armFresh(false); S.views.live.startFresh(); } else if (a === 'attach') S.views.session.showAttach();
      else if (a === 'all-work') { S.views.used.pickAgent(null, false); const head = els.feed.querySelector('h2'); if (head) { head.tabIndex = -1; head.focus(); } }
      else if (a === 'changes') { S.state.changesRequested = true; els.compose.hidden = false; els.msg.placeholder = 'What would you like changed?'; els.msg.focus(); }
      else if (a === 'done') {
        const button = e.target.closest('button'); button.disabled = true;
        act('ticket.done', {ticket: TID, if_revision: S.state.view.ticket.revision}).then(r => { button.disabled = false; if (!r.ok) toast(r.message, 'error'); });
      }
      if (e.target === els.help) toggleHelp(false);
    });
    const grow = () => { els.msg.style.height = 'auto'; els.msg.style.height = Math.min(els.msg.scrollHeight, 120) + 'px'; };
    els.msg.addEventListener('input', grow);
    els.msg.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); els.form.requestSubmit(); } if (e.key === 'Escape') els.msg.blur(); });
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
      else if (k === 's' || k === 'S') S.views.live.stopToggle();
      else if (k === 'j' || k === 'k') { const n = S.state.view ? S.state.view.ticket.checklist.length : 0; if (n) { cur = (S.state.sel + (k === 'j' ? 1 : -1) + n) % n; S.state.sel = cur; els.tasks.dataset.k = ''; els.tasks.dataset.picked = '1'; S.views.ticket.renderTasks(S.state.view); els.tasks.querySelectorAll('.fx-task')[S.state.sel]?.focus(); } }
      else if (k === '1' || k === '2' || k === '3' || k === '4') selectTab(+k - 1);
    });
  }

  S.apply = apply; S.poll = poll;
  if (!TID) { S.views.ticket.picker(); return; }

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
        else if (r.status === 404 && S.state.firstRender) { busy = false; root.replaceChildren(h('div', {class: 'fx-pick'}, h('h1', {text: 'No such ticket'}), h('a', {href: INAPP ? '/#home' : '/', target: INAPP ? '_top' : '_self', text: 'All tickets'}))); return; }
      } catch (e) { /* try again */ }
    }
    busy = false; lastFetch = Date.now();
    if (again) { again = false; timer = setTimeout(poll, 500); return; }
    timer = setTimeout(poll, live ? (S.state.view && S.state.view.run.running ? 1500 : 15000) : S.state.view && S.state.view.run.running ? 1500 : 3000);
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
  S.views.ticket.build(); S.views.compose.mount(); wire(); poll();
})();
