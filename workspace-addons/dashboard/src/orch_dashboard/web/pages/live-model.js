'use strict';
// ORCH-362: tool, model and open time of a working session (draft D feature 12), on a line at the top of its pane in
// the layer (pages/live-layer.js). Tool · model is a button that opens the model choice; a new model goes through
// `ticket.model` (= `orch ticket model`): orch switches a working helper when it finishes its current step (tools
// that can switch), else the next start uses it. When the live data of every session is there (window.LiveSessions,
// ORCH-359) its tool, model and times are used; until then they come from the state the page already has.

// --- the model (plain data, tested in tests/live_model.test.js) ---
const LIVE_MODEL_NAMES = [['sonnet', 'Sonnet'], ['opus', 'Opus'], ['haiku', 'Haiku'], ['fable', 'Fable']];
const liveModelLabel = name => (LIVE_MODEL_NAMES.find(x => x[0] === name) || [])[1] || '';
// "25 min", "1 h 5 min", "2 h"
function liveModelDur(seconds) {
  const m = Math.max(0, Math.floor((Number(seconds) || 0) / 60));
  return m < 60 ? m + ' min' : Math.floor(m / 60) + ' h' + (m % 60 ? ' ' + (m % 60) + ' min' : '');
}
// The line of one working session: tool, model (and the one it switches to), whether the model can be chosen,
// open time and how long it stays. run = state.runs[id], t = the ticket, agents = state.settings.agents.
function liveModelLine(run, t, agents, now, live) {
  const claim = run?.claim || {}, agent = (Array.isArray(agents) ? agents : []).find(a => a && a.name === claim.agent) || null;
  const tool = (live && typeof live.tool === 'string' && live.tool) || agent?.label || claim.agent || '';
  const canPick = agent ? agent.models === true : !!(t?.model);
  const name = t?.model && liveModelLabel(t.model.name) ? t.model.name : '';
  const model = (live && typeof live.model === 'string' && live.model) || (canPick ? liveModelLabel(name) : '');
  const next = canPick ? liveModelLabel(claim.model_switch?.to) : '';
  const started = Date.parse(claim.started_at || '');
  const open = Number.isFinite(live?.open_seconds) ? live.open_seconds : Number.isFinite(started) ? Math.max(0, (now - started) / 1000) : null;
  const idle = live ? live.status === 'idle' : claim.live?.state === 'idle';
  const left = Number.isFinite(live?.closes_in_seconds) ? live.closes_in_seconds : t?.warmth?.seconds_left;
  const warm = idle ? (Number.isFinite(left) ? 'closes in ' + liveModelDur(left) + ' if left idle' : 'idle')
    : claim.live?.state === 'attention' || live?.status === 'needs-you' ? 'stays warm while it waits for you' : 'stays warm while it works';
  return {tool, model, name, next:next && next !== model ? next : '', canPick, open:open === null ? '' : 'open ' + liveModelDur(open), warm};
}
// What the button says: "Tool · Opus", with "→ Haiku after this step" while a switch waits.
function liveModelText(line) {
  return [line.tool, line.model].filter(Boolean).join(' · ') + (line.next ? ' → ' + line.next + ' after this step' : '');
}

if (typeof module === 'object' && module.exports) {
  module.exports = {LIVE_MODEL_NAMES, liveModelDur, liveModelLine, liveModelText};
} else {
  const ticketOfId = id => (Array.isArray(state?.tickets) ? state.tickets : []).find(t => t.id === id) || null;
  const lineOf = id => liveModelLine(state?.runs?.[id], ticketOfId(id), state?.settings?.agents, Date.now(), window.LiveSessions?.get?.(id) || null);
  // for the dock's repaint key: what the lines show (the open time counts in minutes)
  window.liveModelKey = ids => ids.map(id => { const l = lineOf(id); return [id, liveModelText(l), l.open, l.warm, l.name]; });
  // The line at the top of a working session's pane, and its model menu while open.
  window.liveModelRow = function liveModelRow(sess, s) {
    const l = lineOf(sess.id), menu = 'model:' + sess.id, open = s.menu === menu, text = liveModelText(l);
    if (!text && !l.open) return null;
    const label = sess.key || sess.title;
    return h('div', {className:'live-prow meta', 'data-key':'live-model-row'},
      l.canPick ? h('span', {className:'live-mdl-wrap'},
        h('button', {type:'button', className:'btn ghost sm live-mdl', 'data-live':'menu', 'data-menu':menu, 'aria-expanded':String(open),
          'data-key':'live-model', title:'See or change the model of ' + label}, text),
        open ? h('div', {className:'live-pop', 'data-down':'', role:'group', 'aria-label':l.tool + ': model', 'data-key':'live-model-menu'},
          h('p', {className:'live-pop-h'}, l.tool + ': model'),
          LIVE_MODEL_NAMES.map(([v, word]) => h('button', {type:'button', className:'live-opt', 'data-live-model':v, 'data-session':sess.id,
            'aria-pressed':String((l.next ? l.next === word : l.name === v))}, h('span', {}, word + (l.name === v ? ' (now)' : '')))),
          h('p', {className:'meta'}, 'A new model applies when the helper finishes its current step (or at its next start).')) : null)
        : text ? h('span', {className:'live-tool'}, text) : null,
      l.open ? h('span', {}, l.open) : null,
      h('span', {}, l.warm));
  };
  document.addEventListener('click', async e => {
    const b = e.target.closest?.('#live-dock [data-live-model]');
    if (!b) return;
    const id = b.dataset.session, v = b.dataset.liveModel, t = ticketOfId(id);
    const key = t && window.DashHelpers?.ticketKey ? window.DashHelpers.ticketKey(t) : 'the ticket';
    if (typeof liveLayerDo === 'function') liveLayerDo({type:'menu', menu:'model:' + id}, `.live-pane[data-session="${id.replace(/["\\]/g, '')}"] [data-key="live-model"]`);
    if (t?.model?.name === v && t.model.by !== 'orch') return;
    const r = await act('ticket.model', {ticket:id, model:v});
    window.orch?.toast?.(r.ok ? 'Model ' + liveModelLabel(v) + ' chosen for ' + key + '.' : r.text || 'Could not change the model.', r.ok ? 'ok' : 'error');
  });
}
