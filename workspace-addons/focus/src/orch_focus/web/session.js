// Owns worked time, session details, and terminal attachment.
(function () {
  'use strict';
  const S = window.FocusStore;
  const {h, TID, toast, els, stamp, hhmm} = S;

  const workedNow = () => S.state.workedBase + (S.state.clockWorking ? Math.max(0, performance.now() - S.state.workedAt) / 1000 : 0);
  function syncTimer(v) {
    const server = Math.max(0, Number(v.run.worked) || 0), current = workedNow();
    S.state.workedBase = S.state.view && Math.abs(server - current) <= 3 ? Math.max(server, current) : server;
    S.state.workedAt = performance.now();
    S.state.clockWorking = v.state === 'working';
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
  if (TID) setInterval(() => { if (S.state.view && S.state.clockWorking) tickTimer(); }, 1000);

  function showAttach() {
    // waiting for an OK: the person must type in the session, so no --watch; the short key (DM1-12) works too
    const ok = !!(S.state.view && S.state.view.attention), key = (els.key && els.key.textContent) || TID;
    const cmd = 'orch run attach ' + key + (ok ? '' : ' --watch');
    els.attachBox.hidden = !els.attachBox.hidden;
    els.attachBox.replaceChildren(h('span', {class: 'meta', text: ok ? 'Answer it in a terminal (Ctrl-b d to leave):' : 'Watch the live session in a terminal:'}), h('code', {class: 'mono', text: cmd}),
      h('button', {class: 'btn ghost xs', text: 'Copy', onclick: () => { try { navigator.clipboard.writeText(cmd); toast('Copied.', 'ok'); } catch (e) { /* select by hand */ } }}));
  }

  S.register('session', {syncTimer, tickTimer, workedNow, duration, renderSession, showAttach});
})();
