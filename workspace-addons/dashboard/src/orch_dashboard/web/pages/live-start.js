'use strict';
// ORCH-362: the Start choice of a session pane in the layer (pages/live-layer.js, draft D feature 4 and 12). A ticket
// with no helper shows one question: continue the last conversation, a fresh start on the tool and model picked here
// (the usual ones preselected, so it stays one click), or reopen an earlier session (the History task's list,
// pages/live-history.js). It says how many helper places are in use and how many tickets wait in line. Starting a
// helper costs, so no start button is filled (UX checklist D2, draft D).
// Everything goes through the existing start path: `run.start` (= `orch run start`, `--fresh`, `--agent`),
// `ticket.model` (= `orch ticket model`) and `session.reopen` (= `orch run start --session`).

// --- the model (plain data, tested in tests/live_start.test.js) ---
const LIVE_START_MODELS = [['sonnet', 'Sonnet'], ['opus', 'Opus'], ['haiku', 'Haiku'], ['fable', 'Fable']];
const liveStartPlural = (n, one, many) => n + ' ' + (n === 1 ? one : many);
// Helper places: how many are in use (live helpers), the most allowed (null = no limit), who waits in line.
function liveStartPlaces(runs, settings, line) {
  const rows = runs && typeof runs === 'object' ? Object.values(runs) : [];
  const used = rows.filter(r => r && r.running === true && (r.claim?.mode || 'live') === 'live').length;
  const max = Number.isInteger(settings?.live_max) && settings.live_max > 0 ? settings.live_max : null;
  const waiting = Array.isArray(line?.waiting) ? line.waiting.filter(x => typeof x === 'string') : [];
  return {used, max, waiting, full:max !== null && used >= max};
}
// The places line above the choices, in plain words with the right singular and plural.
function liveStartPlacesText(p) {
  const wait = p.waiting.length ? liveStartPlural(p.waiting.length, 'ticket waits', 'tickets wait') + ' in line.' : '';
  if (p.max === null) {
    const now = p.used ? liveStartPlural(p.used, 'helper is', 'helpers are') + ' working now.' : 'No helper is working now.';
    return [now, wait].filter(Boolean).join(' ');
  }
  if (p.full) return [(p.max === 1 ? 'The one helper place is in use.' : 'All ' + p.max + ' helper places are in use.'), wait,
    'A start waits in line and begins by itself when a place is free.'].filter(Boolean).join(' ');
  return ['A start uses 1 of ' + liveStartPlural(p.max, 'helper place', 'helper places') + '. Now ' + p.used + ' of ' + p.max + ' ' + (p.used === 1 ? 'is' : 'are') + ' in use.', wait].filter(Boolean).join(' ');
}
// Where this ticket stands in the line ("2 of 3"), or null when it does not wait.
function liveStartInLine(p, id) {
  const at = p.waiting.indexOf(id);
  return at < 0 ? null : {at:at + 1, of:p.waiting.length};
}
// The tools a fresh start can run on (found on this computer) and the usual one (chosen for this workspace).
function liveStartTools(agents) {
  const tools = (Array.isArray(agents) ? agents : []).filter(a => a && typeof a.name === 'string' && a.found !== false)
    .map(a => ({name:a.name, label:String(a.label || a.name), models:a.models === true, chosen:a.chosen === true}));
  const usual = (tools.find(t => t.chosen) || tools[0] || null)?.name || '';
  return {tools, usual};
}
// The model the ticket runs on now: a person's choice, orch's pick, else Sonnet (orch's small first pick).
function liveStartModel(t) {
  const m = t?.model, name = m && LIVE_START_MODELS.some(x => x[0] === m.name) ? m.name : '';
  return {name:name || 'sonnet', auto:!name || m.by === 'orch'};
}
// What a fresh start sends: the tool only when it is not the usual one, the model only when the person changed it.
function liveStartFresh(ticket, pick, usualTool, model) {
  const ops = [];
  if (pick.model && pick.model !== model.name) ops.push(['ticket.model', {ticket, model:pick.model}]);
  ops.push(['run.start', {ticket, fresh:true, ...(pick.tool && pick.tool !== usualTool ? {agent:pick.tool} : {})}]);
  return ops;
}
// The last conversation that Continue picks up (the newest earlier session on this computer), or null.
function liveStartLast(rows) {
  return (Array.isArray(rows) ? rows : []).find(r => r.reopen) || null;
}
// A start that orch put in line answers with a refusal saying so: that is not a failure.
function liveStartQueued(text) {
  return /waits in line/i.test(String(text || ''));
}

if (typeof module === 'object' && module.exports) {
  module.exports = {LIVE_START_MODELS, liveStartPlaces, liveStartPlacesText, liveStartInLine, liveStartTools,
    liveStartModel, liveStartFresh, liveStartLast, liveStartQueued};
} else {
  // --- the page ---
  // ORCH-475: the pane shows the kit's Start choice itself (UI.startButton inline, kit/start-choice.js; facts from
  // pages/start.js), the same one every Start button's caret opens: Starting… until the helper runs, one run for a double
  // click, greyed choices say why. The functions above stay the plain model the tests check.
  const placesNow = () => liveStartPlaces(state?.runs, state?.settings, state?.start_line);
  const ticketOfId = id => (Array.isArray(state?.tickets) ? state.tickets : []).find(t => t.id === id) || null;
  const built = new WeakMap();  // pane host -> the kit's Start choice
  // the layer draws its panes again when the line changes (the choice says where the ticket waits)
  window.liveStartKey = () => { const p = placesNow(); return [p.max, p.waiting]; };
  // The pane body of a ticket with no helper: a host the kit fills after the layer painted (liveStartMount).
  window.liveStartBody = function liveStartBody(sess) {
    return h('div', {className:'live-start-host', 'data-key':'live-start', 'data-live-start-host':sess.id});
  };
  window.liveStartMount = function liveStartMount() {
    if (!window.UI?.startButton || typeof startFacts !== 'function') return;
    document.querySelectorAll('#live-dock [data-live-start-host]').forEach(host => {
      const t = ticketOfId(host.dataset.liveStartHost);
      if (!t) return;
      const facts = {...startFacts(t), running:false};  // the pane shows only while no helper runs on it
      const w = built.get(host);
      if (w) { w.update(facts); return; }
      // after a press the choice shows from its top, so the title and Starting… are seen, never under the pane header
      // (ORCH-1361): the button pressed may sit lower in a short pane that was scrolled to reach it
      const top = () => { const pb = host.closest('.live-pb'); if (pb) pb.scrollTop = 0; };
      built.set(host, window.UI.startButton(host, {ticket:t.id, inline:true, send:(op, args) => { top(); return act(op, args, {quiet:true}); },
        toast:(text, kind) => window.orch?.toast?.(text, kind || 'ok'), ...facts}));
    });
  };
}
