'use strict';
// The terminal view of a session in the layer (ORCH-744, draft D feature 5): the helper's real screen drawn by the
// master terminal (kit term.js, UI.term) where the pane shows Terminal. Watching only by default: keys go out only
// after the person turns on "Let me type", and the server checks again (the typing setting and the sign-in).
// One terminal per session is kept while its pane is open, so a repaint of the layer keeps its screen, its typing
// state and the keyboard. The screen comes from GET /api/term (the bridge, ORCH-743), once a second per shown pane
// while the page is visible; keys go to POST /api/term/keys, a new size while typing to POST /api/term/size.
const LIVE_TERM_EVERY = 1000;      // ms between two reads of one screen
const LIVE_TERM_KEEP = 30000;      // ms a terminal no pane shows is kept (a pane closed and opened again)
const liveTerms = new Map();       // session id -> {ui, seen, busy, fails}

// Whether a pane body shows the terminal: a ticket's pane when its view is Terminal (pages/livechat.js), or always
// when there is no chat view in it. A session without a ticket has no screen through the bridge yet.
function liveTermWanted(body) {
  if (!body || body.dataset.liveKind) return false;
  return body.dataset.liveView === 'term' || !body.querySelector('[data-live-chat]');
}
// The answer of a POST in the shape UI.term wants: {ok, status, text}.
async function liveTermPost(path, payload) {
  try {
    const r = await fetch(path, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
    return {ok:r.ok, status:r.status, text:r.ok ? '' : (await r.text()).slice(0, 300)};
  } catch (e) {
    return {ok:false, status:0, text:''};
  }
}
function liveTermFor(id, label) {
  let t = liveTerms.get(id);
  if (t) return t;
  const ui = window.UI.term({
    label,
    onKeys: async items => {
      const r = await liveTermPost('/api/term/keys', {ticket:id, items});
      if (r.ok) setTimeout(() => liveTermRead(id), 120);  // the answer to a key shows at once, not at the next second
      else if (r.status === 403) window.orch?.toast?.(r.text || 'Sign in to type here: open the dashboard with a sign-in link from orch.', 'error');
      else if (r.status === 409) window.orch?.toast?.('The helper’s screen has closed; those keys were not sent.', 'error');
      else window.orch?.toast?.(r.text.slice(0, 120) || 'The screen did not take that. Try again.', 'error');
      return r;
    },
    onSize: async size => {
      const r = await liveTermPost('/api/term/size', {ticket:id, cols:size.cols, rows:size.rows});
      if (r.ok) setTimeout(() => liveTermRead(id), 120);
    },
  });
  t = {ui, seen:Date.now(), busy:false, fails:0};
  liveTerms.set(id, t);
  liveTermRead(id);
  return t;
}
async function liveTermRead(id) {
  const t = liveTerms.get(id);
  if (!t || t.busy) return;
  t.busy = true;
  try {
    const r = await fetch('/api/term?ticket=' + encodeURIComponent(id), {cache:'no-store'});
    if (!r.ok) throw new Error(String(r.status));
    t.ui.update(await r.json());
    t.fails = 0;
  } catch (e) {
    t.fails += 1;
    if (t.fails > 1) t.ui.show('error');  // one missed read is not worth a word
  }
  t.busy = false;
}
// Called by liveLayerFill for every pane body with its live session (null: no helper, then the pane says so itself):
// puts the session's terminal in the body when it shows Terminal, and
// hides the plain last lines there. The same element moves into a body the layer drew again.
function liveTermApply(body, live) {
  if (typeof window !== 'object' || !window.UI?.term) return;
  const id = body.dataset.liveBody, on = !!live && liveTermWanted(body);
  const pre = body.querySelector('[data-live-lines]');
  if (!on) {
    const t = liveTerms.get(id);
    if (t && t.ui.el.parentNode === body) { t.ui.setTyping(false); t.ui.el.remove(); }
    return;
  }
  const label = body.closest('.live-pane')?.querySelector('.live-pt')?.textContent || 'the helper';
  const t = liveTermFor(id, label);
  t.seen = Date.now();
  if (t.ui.el.parentNode !== body) {
    if (pre) pre.after(t.ui.el); else body.append(t.ui.el);
    t.ui.back();
  }
  if (pre) pre.hidden = true;
}
// One clock for every shown terminal; a terminal no pane shows stops reading and is dropped after a while.
function liveTermTick() {
  if (document.hidden) return;
  const now = Date.now();
  for (const [id, t] of liveTerms) {
    if (document.contains(t.ui.el)) { t.seen = now; liveTermRead(id); }
    else if (now - t.seen > LIVE_TERM_KEEP) { t.ui.setTyping(false); liveTerms.delete(id); }
    else if (t.ui.typing()) t.ui.setTyping(false);  // nothing is typed into a screen nobody sees
  }
}
if (typeof window === 'object' && typeof document === 'object' && !(typeof module === 'object' && module.exports)) {
  setInterval(liveTermTick, LIVE_TERM_EVERY);
}
if (typeof module === 'object' && module.exports) module.exports = {liveTermWanted, liveTermApply, liveTermTick, liveTerms};
