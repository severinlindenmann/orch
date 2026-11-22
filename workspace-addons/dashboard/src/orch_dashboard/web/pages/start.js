// One Start (ORCH-475/486): every Start, Continue, Resume and Send-and-start button on the dashboard is the kit's Start
// button (UI.startButton, kit/start-choice.js): one click starts the usual way, the caret opens the Start choice
// (continue, fresh start with tool and model, an earlier session; helper places in use), it says Starting… until the
// helper runs, a double click starts one run, and a greyed choice says why.
// A page puts startHost(t, key, opts) where the button goes; after each render startMount(main) builds the button once
// per host (mounts skip reconcile) and feeds it the newest state. Earlier sessions come from GET /api/sessions/<ticket>.

const startOpts = new Map();  // host key -> {label, continueLabel, style, align, fresh, caretOnly, before, running}
const startSess = new Map();  // ticket id -> {at, data}
// The page's act() without its own "Could not start" notice: the kit says what went wrong (or nothing, for a double click).
const startSend = (op, args) => act(op, args, {quiet:true});
function startSessions(id) {
  const hit = startSess.get(id);
  if (hit && Date.now() - hit.at < 15000) return hit.data;
  startSess.set(id, {at:Date.now(), data:hit?.data || null});
  fetch('/api/sessions/' + encodeURIComponent(id)).then(r => r.ok ? r.json() : {available:false}).catch(() => ({available:false})).then(data => {
    startSess.set(id, {at:Date.now(), data});
    startRefresh(id);
  });
  return hit?.data || null;
}
// What the button needs from the page state, read fresh on every render.
function startFacts(t, o = {}) {
  const run = state?.runs?.[t.id];
  return {name:window.DashHelpers.ticketKey(t) || clean(t.title), sessions:startSessions(t.id), runs:state?.runs || {}, settings:state?.settings || {},
    line:state?.start_line || {}, agents:state?.settings?.agents || [], model:t.model || null, hasSessions:array(t.sessions).length > 0,
    running:o.running !== undefined ? o.running : run?.running === true};
}
// The place of a Start button: a host the page draws like any other node.
// opts: label ('Start helper'), continueLabel ('Continue'), style ('outline'), align, fresh, caretOnly, before(ops), running.
// Until the kit fills it (right after this render) it holds the main button with its word, so the first paint does not jump.
function startHost(t, key, opts = {}) {
  if (snapshot || !t) return null;
  startOpts.set(key, opts);
  // just pressed (ORCH-250): Starting… until the helper runs, never back to Start helper for a moment
  const busy = !!window.UI?.startStarter?.starting(t.id) || (typeof justStarted === 'function' && justStarted(t.id));
  const word = busy ? 'Starting…' : opts.fresh ? opts.label || 'Start fresh' : array(t.sessions).length ? opts.continueLabel || 'Continue' : opts.label || 'Start helper';
  return h('span', {className:'start-host', 'data-key':key, 'data-start-host':t.id},
    h('span', {className:'start-split'}, h('button', {type:'button', className:'btn ' + (opts.style || 'outline') + ' sm', 'data-start':'main', disabled:busy ? '' : null, 'aria-busy':busy ? 'true' : null}, word)));
}
function startBuild(host) {
  const t = ticketOf(host.dataset.startHost), o = startOpts.get(host.dataset.key) || {};
  if (!t) return null;
  const btn = window.UI.startButton(host, {ticket:t.id, send:startSend, toast:(text, kind, again) => window.orch.toast(text, kind || 'ok', again), ...o, ...startFacts(t, o)});
  return {btn, destroy() {}};
}
function startMount(root) {
  if (!root || !window.UI?.startButton) return;
  // A helper the page sees running ends Starting… for its ticket, also for a button that is not on this page any more
  // (a notice, the composer), so no "did not show up" line comes late.
  const st = window.UI.startStarter;
  if (st) Object.entries(state?.runs || {}).forEach(([id, r]) => { if (r?.running === true) st.seen(id, true); });
  root.querySelectorAll('[data-start-host]').forEach(host => {
    let m = mounts.get(host);
    if (!m) { m = startBuild(host); if (m) mounts.set(host, m); return; }
    const t = ticketOf(host.dataset.startHost), o = startOpts.get(host.dataset.key) || {};
    if (t) m.btn.update({...o, ...startFacts(t, o)});
  });
}
// Earlier sessions arrived: the buttons of that ticket redraw (Continue or Start, the list in the choice).
function startRefresh(id) {
  for (const [host, m] of mounts) {
    if (!m.btn || host.dataset.startHost !== id || !host.isConnected) continue;
    const t = ticketOf(id), o = startOpts.get(host.dataset.key) || {};
    if (t) m.btn.update({...o, ...startFacts(t, o)});
  }
  window.liveStartMount?.();  // the live page's pane shows the same list
}
// A Start button outside the page's main area (a notice): built at once, not kept across renders.
function startButtonIn(host, t, opts = {}) {
  if (snapshot || !t || !window.UI?.startButton) return null;
  return window.UI.startButton(host, {ticket:t.id, send:startSend, toast:(text, kind, again) => window.orch.toast(text, kind || 'ok', again), ...opts, ...startFacts(t, opts)});
}
if (typeof module !== 'undefined') module.exports = {startHost, startMount, startFacts};
