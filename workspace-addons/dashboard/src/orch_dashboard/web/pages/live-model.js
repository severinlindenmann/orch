'use strict';
// ORCH-362: the model choice of a working session (draft D feature 12), on a line at the top of its pane in the layer
// (pages/live-layer.js). The pane's live line (ORCH-359, liveMeta in pages/livesessions.js) already says tool, model,
// open time and how long it stays; this adds the button that opens the model choice. A new model goes through
// `ticket.model` (= `orch ticket model`): orch switches a working helper when it finishes its current step (tools
// that can switch), else the next start uses it.

// --- the model (plain data, tested in tests/live_model.test.js) ---
const LIVE_MODEL_NAMES = [['sonnet', 'Sonnet'], ['opus', 'Opus'], ['haiku', 'Haiku'], ['fable', 'Fable']];
const liveModelLabel = name => (LIVE_MODEL_NAMES.find(x => x[0] === name) || [])[1] || '';
// What the model button needs of one working session: tool, model (and the one it switches to), whether the model
// can be chosen. run = state.runs[id], t = the ticket, agents = state.settings.agents, live = its live data (ORCH-359).
function liveModelLine(run, t, agents, live) {
  const claim = run?.claim || {}, agent = (Array.isArray(agents) ? agents : []).find(a => a && a.name === claim.agent) || null;
  const tool = (live && typeof live.tool === 'string' && live.tool) || agent?.label || '';
  const canPick = agent ? agent.models === true : !!(t?.model);
  const name = t?.model && liveModelLabel(t.model.name) ? t.model.name : '';
  const model = (live && typeof live.model === 'string' && live.model) || (canPick ? liveModelLabel(name) : '');
  const next = canPick ? liveModelLabel(claim.model_switch?.to) : '';
  return {tool, model, name, next:next && next !== model ? next : '', canPick};
}
// The model button in the pane: "Model: Opus", with "→ Haiku after this step" while a switch waits ('' = no choice).
// The Empty helper has no ticket in the list (ORCH-710): its model comes from the sessions without a ticket.
function liveModelSessionTicket(sessions, id) {
  const s = (Array.isArray(sessions) ? sessions : []).find(x => x && x.id === id && x.kind === 'empty');
  return s ? {id, model:s.model ? {name:s.model} : null, title:s.title} : null;
}
// What Undo of a model choice goes back to: the model a person had chosen, else orch picks again ('auto').
function liveModelUndo(t) {
  const m = t?.model;
  return m && liveModelLabel(m.name) && m.by !== 'orch' ? m.name : 'auto';
}
function liveModelPick(line) {
  if (!line.canPick) return '';
  return 'Model: ' + (line.model || 'the usual one') + (line.next ? ' → ' + line.next + ' after this step' : '');
}

if (typeof module === 'object' && module.exports) {
  module.exports = {LIVE_MODEL_NAMES, liveModelLine, liveModelPick, liveModelSessionTicket, liveModelUndo};
} else {
  const ticketOfId = id => (Array.isArray(state?.tickets) ? state.tickets : []).find(t => t.id === id) || liveModelSessionTicket(state?.sessions, id);
  const lineOf = id => liveModelLine(state?.runs?.[id], ticketOfId(id), state?.settings?.agents, window.LiveSessions?.get?.(id) || null);
  // for the dock's repaint key: what the model button shows
  window.liveModelKey = ids => ids.map(id => { const l = lineOf(id); return [id, liveModelPick(l), l.name]; });
  // The line at the top of a working session's pane, and its model menu while open.
  window.liveModelRow = function liveModelRow(sess, s) {
    const l = lineOf(sess.id), menu = 'model:' + sess.id, open = s.menu === menu, text = liveModelPick(l);
    if (!text) return null;
    const label = sess.key || sess.title;
    return h('div', {className:'live-prow meta', 'data-key':'live-model-row'},
      h('span', {className:'live-mdl-wrap'},
        h('button', {type:'button', className:'btn ghost sm live-mdl', 'data-live':'menu', 'data-menu':menu, 'aria-expanded':String(open),
          'data-key':'live-model', title:'See or change the model of ' + label}, text),
        open ? h('div', {className:'live-pop', 'data-down':'', role:'group', 'aria-label':(l.tool || 'Helper') + ': model', 'data-key':'live-model-menu'},
          h('p', {className:'live-pop-h'}, (l.tool || 'Helper') + ': model'),
          LIVE_MODEL_NAMES.map(([v, word]) => h('button', {type:'button', className:'live-opt', 'data-live-model':v, 'data-session':sess.id,
            'aria-pressed':String((l.next ? l.next === word : l.name === v))}, h('span', {}, word + (l.name === v ? ' (now)' : '')))),
          h('p', {className:'meta'}, 'A new model applies when the helper finishes its current step (or at its next start).')) : null));
  };
  document.addEventListener('click', async e => {
    const b = e.target.closest?.('#live-dock [data-live-model]');
    if (!b) return;
    const id = b.dataset.session, v = b.dataset.liveModel, t = ticketOfId(id);
    const key = t && !t.status && t.title ? 'the ' + t.title : t && window.DashHelpers?.ticketKey ? window.DashHelpers.ticketKey(t) : 'the ticket';
    if (typeof liveLayerDo === 'function') liveLayerDo({type:'menu', menu:'model:' + id}, `.live-pane[data-session="${id.replace(/["\\]/g, '')}"] [data-key="live-model"]`);
    if (t?.model?.name === v && t.model.by !== 'orch') return;
    const back = liveModelUndo(t);
    const pick = async () => {
      const r = await act('ticket.model', {ticket:id, model:v});
      if (!r.ok) { (window.liveFail || ((t, f) => window.orch?.toast?.(t || f, 'error')))(r.text, 'Could not change the model.', pick); return; }
      // Undo puts the model back as it was, or lets orch pick again (ORCH-1359)
      const undo = async () => {
        const u = await act('ticket.model', {ticket:id, model:back});
        if (u.ok) window.orch?.toast?.(back === 'auto' ? 'orch picks the model again.' : 'Model back to ' + liveModelLabel(back) + '.', 'ok');
        else (window.liveFail || ((t, f) => window.orch?.toast?.(t || f, 'error')))(u.text, 'Could not put the model back.', undo);
      };
      window.orch?.toast?.('Model ' + liveModelLabel(v) + ' chosen for ' + key + '.', 'ok', undo);
    };
    await pick();
  });
}
