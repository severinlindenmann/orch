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
  const liveStartPick = new Map();  // ticket id -> {tool, model} the person picked (this page only)
  const liveStartBusy = new Set();
  const placesNow = () => liveStartPlaces(state?.runs, state?.settings, state?.start_line);
  const ticketOfId = id => (Array.isArray(state?.tickets) ? state.tickets : []).find(t => t.id === id) || null;
  const pickOf = id => {
    const t = ticketOfId(id), tools = liveStartTools(state?.settings?.agents), was = liveStartPick.get(id) || {};
    const tool = tools.tools.some(x => x.name === was.tool) ? was.tool : tools.usual;
    return {tools, tool, model:was.model || liveStartModel(t).name, cur:liveStartModel(t)};
  };
  window.liveStartKey = () => {
    const p = placesNow();
    return [p.used, p.max, p.waiting, [...liveStartPick], [...liveStartBusy], [...liveHistData].map(([k, x]) => [k, JSON.stringify(x.data || null)]), (state?.settings?.agents || []).map(a => [a.name, a.found, a.chosen, a.models])];
  };
  const seg = (label, list, cur, what, id) => h('span', {className:'segmented', role:'group', 'aria-label':label},
    list.map(([v, text]) => h('button', {type:'button', className:'btn sm', 'data-live-start':'pick', 'data-what':what, 'data-v':v,
      'data-session':id, 'aria-pressed':String(cur === v)}, text)));
  // Tool and model of a fresh start: the usual ones preselected; a tool orch passes no model to says so.
  function pickRow(id) {
    const p = pickOf(id), tool = p.tools.tools.find(x => x.name === p.tool);
    return h('div', {className:'live-pick', role:'group', 'aria-label':'Runs on', 'data-key':'live-start-pick'},
      h('span', {className:'live-pick-l'}, 'Runs on'),
      p.tools.tools.length > 1 ? seg('Tool', p.tools.tools.map(x => [x.name, x.label]), p.tool, 'tool', id)
        : tool ? h('span', {className:'chip'}, tool.label) : null,
      !tool || tool.models ? seg('Model', LIVE_START_MODELS, p.model, 'model', id)
        : h('span', {className:'meta'}, 'This tool uses its own model.'));
  }
  // The pane body of a ticket with no helper: the Start choice, or where it waits in line.
  window.liveStartBody = function liveStartBody(sess) {
    const p = placesNow(), line = liveStartInLine(p, sess.id), busy = liveStartBusy.has(sess.id);
    const places = h('p', {className:'meta live-places', 'data-key':'live-start-places', 'data-full':p.full ? '' : null}, liveStartPlacesText(p));
    if (line) return h('div', {className:'live-start', 'data-key':'live-start'},
      h('h3', {className:'live-start-h'}, 'In line'),
      h('p', {}, (sess.key || 'This ticket') + ' is number ' + line.at + ' of ' + line.of + ' in line. It starts by itself when a place is free.'),
      places);
    if (typeof liveHistLoad === 'function') liveHistLoad(sess.id);
    const v = typeof liveHistView === 'function' ? liveHistView(liveHistData.get(sess.id)?.data, new Date(),
      window.UI?.stamp ? (at, now) => window.UI.stamp(at.toISOString(), {now:now.toISOString()}) : null) : {state:'empty', rows:[]};
    const last = liveStartLast(v.rows), hasLast = !!last || v.state === 'loading';
    const label = sess.key || sess.title;
    return h('div', {className:'live-start', 'data-key':'live-start', 'aria-busy':busy ? 'true' : null},
      h('h3', {className:'live-start-h'}, 'Start a helper on this ticket'),
      places,
      h('div', {className:'live-choices'},
        hasLast ? h('div', {className:'live-choice', 'data-key':'live-start-continue'},
          h('h4', {}, 'Continue where it stopped'),
          h('p', {className:'meta'}, 'Keeps the last conversation' + (last ? ' from ' + last.day : '') + '. Best when the work is half done.'),
          h('button', {type:'button', className:'btn outline sm', 'data-live-start':'continue', 'data-session':sess.id, disabled:busy,
            'aria-label':'Continue the last conversation on ' + label}, 'Continue')) : null,
        h('div', {className:'live-choice', 'data-key':'live-start-fresh'},
          h('h4', {}, 'Fresh start'),
          h('p', {className:'meta'}, hasLast ? 'The helper reads the ticket again. The earlier talk is not used. Best when it went off track.' : 'The helper reads the ticket and starts on the first step.'),
          pickRow(sess.id),
          h('button', {type:'button', className:'btn outline sm', 'data-live-start':'fresh', 'data-session':sess.id, disabled:busy,
            'aria-label':'Fresh start on ' + label}, hasLast ? 'Start again' : 'Start'))),
      v.state === 'list' && typeof liveHistList === 'function' ? liveHistList(sess, v, false, busy) : null);
  };
  const toast = (text, kind) => window.orch?.toast?.(text, kind);
  async function go(id, ops, how) {
    const key = ticketOfId(id) && window.DashHelpers?.ticketKey ? window.DashHelpers.ticketKey(ticketOfId(id)) : 'the ticket';
    liveStartBusy.add(id);
    if (typeof liveLayerPaint === 'function') liveLayerPaint();
    let r = {ok:true};
    for (const [op, args] of ops) {
      r = await act(op, args);
      if (!r.ok) break;
    }
    liveStartBusy.delete(id);
    if (r.ok) {
      liveStartPick.delete(id);
      if (typeof liveHistData !== 'undefined') liveHistData.delete(id);
      toast(how === 'continue' ? 'The helper continues the last conversation on ' + key + '.' : 'Fresh start on ' + key + ': the helper reads the ticket again.', 'ok');
    } else if (liveStartQueued(r.text)) toast(key + ' waits in line for a free helper place.', 'ok');
    else toast(r.text || 'Could not start the helper.', 'error');
    if (typeof liveLayerPaint === 'function') liveLayerPaint();
    document.querySelector(`#live-dock .live-pane[data-session="${id.replace(/["\\]/g, '')}"] [data-key="live-close"]`)?.focus({preventScroll:true});
  }
  document.addEventListener('click', e => {
    const b = e.target.closest?.('#live-dock [data-live-start]');
    if (!b || b.disabled) return;
    const id = b.dataset.session, what = b.dataset.liveStart;
    if (!id || liveStartBusy.has(id)) return;
    if (what === 'pick') {
      const p = pickOf(id), next = {tool:p.tool, model:p.model};
      if (b.dataset.what === 'tool') next.tool = b.dataset.v; else next.model = b.dataset.v;
      liveStartPick.set(id, next);
      if (typeof liveLayerPaint === 'function') liveLayerPaint();
      document.querySelector(`#live-dock .live-pane[data-session="${id.replace(/["\\]/g, '')}"] [data-live-start="pick"][data-what="${b.dataset.what}"][aria-pressed="true"]`)?.focus({preventScroll:true});
      return;
    }
    if (what === 'continue') go(id, [['run.start', {ticket:id}]], 'continue');
    else if (what === 'fresh') { const p = pickOf(id); go(id, liveStartFresh(id, p, p.tools.usual, p.cur), 'fresh'); }
  });
}
