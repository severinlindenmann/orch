/* One Start (ORCH-475/487): this page's Start is the kit's Start button (kit/start-choice.js), the same one the
   dashboard shows: one click starts the usual way (Continue when an earlier session can be picked up, else Start
   helper), the caret opens the Start choice, it says Starting… until the helper runs, a double click starts one run,
   and a greyed choice says why. Focus can only start on the ticket's own tool (no tool or model pick here), and it
   reopens an earlier session with session.continue. */
(() => {
  'use strict';
  const S = window.FocusStore;
  let btn = null, sessions = null, sessionsAt = 0, last = null;
  /* the kit's ops in this page's words: Focus's act answers {ok, message}; Reopen is session.continue here */
  const send = async (op, args) => {
    if (op === 'ticket.model' || (op === 'run.start' && args && args.agent)) return {ok: false, text: 'Pick the tool and model on the ticket page.'};
    const r = await S.act(op === 'session.reopen' ? 'session.continue' : op, op === 'session.reopen' ? {ticket: args.ticket, session: args.session} : args);
    return {ok: !!r.ok, text: r.message || ''};
  };
  function loadSessions() {
    if (Date.now() - sessionsAt < 15000) return;
    sessionsAt = Date.now();
    fetch(S.P + '/api/t/' + S.TID + '/sessions').then(r => r.ok ? r.json() : {available: false}).catch(() => ({available: false}))
      .then(d => { sessions = d; if (last) update(last); });
  }
  function facts(v) {
    const label = (S.els && S.els.agent && S.els.agent.textContent) || 'Helper';
    return {name: (v.ticket && (v.ticket.key || v.ticket.title)) || 'this ticket', sessions, running: !!(v.run && v.run.running),
      hasSessions: !!(v.ticket && v.ticket.started) || !!(v.run && v.run.run), runs: {}, settings: {}, line: {},
      agents: [{name: 'helper', label, models: false, chosen: true}]};
  }
  function update(v) {
    last = v;
    if (!btn || !v) return;
    loadSessions();
    btn.update(facts(v));
  }
  function mount(host, v) {
    if (btn || !host || !window.UI || !window.UI.startButton) return;
    btn = window.UI.startButton(host, Object.assign({ticket: S.TID, send, label: 'Start helper', continueLabel: 'Continue',
      toast: (text, kind) => (window.orch ? window.orch.toast(text, kind || 'ok') : null)}, facts(v || {ticket: {}, run: {}})));
    loadSessions();
  }
  S.startButton = {mount, update, start: how => btn && btn.start(how), open: () => btn && btn.open(), ready: () => !!btn};
})();
