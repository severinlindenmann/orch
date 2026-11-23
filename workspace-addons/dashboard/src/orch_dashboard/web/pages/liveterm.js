'use strict';
// The terminal view of a session in the layer (ORCH-744, draft D feature 5): the helper's real screen in the master
// terminal (kit term.js, UI.term) where the pane shows Terminal. Watching only by default: nothing is typed until the
// person turns on "Let me type", and the server checks again (the typing setting and the sign-in).
// The screen comes from the terminal bridge (ORCH-743) as server-sent events, GET /api/term/stream?ticket=<id>:
// hello {typing_allowed, page}, screen {cols, rows, data}, out (base64 bytes), size {cols, rows}, typing {by}, end
// {state}. One page types at a time (ORCH-883): "Let me type" claims it with POST /api/term/typing {ticket, page, on}
// (page: the id from this stream's hello); the page that typed before hears typing {by:'other'} and goes back to
// watching. Typing goes to POST /api/term/input {ticket, data, page}, the box size to POST /api/term/size
// {ticket, cols, rows, page} (while typing, and while watching when no other page types, ORCH-1758); the helper's
// window gets its own size back when the pages left (the bridge, ORCH-881).
// One terminal and one stream per session while its pane shows it, so a repaint of the layer keeps the screen, the
// typing state and the keyboard. A terminal no pane shows closes its stream at once (the bridge serves few pages).
const LIVE_TERM_EVERY = 1000;      // ms between two looks at which terminals are still shown
const LIVE_TERM_KEEP = 30000;      // ms a terminal no pane shows is kept (a pane closed and opened again)
const LIVE_TERM_RETRY = 5000;      // ms before a stream that closed is opened again
const liveTerms = new Map();       // session id -> {ui, es, seen, ended, retry}

// Whether a pane body shows the terminal: a ticket's pane when the person chose Terminal (Chat | Terminal,
// pages/livechat.js; Chat comes first as in draft D, and the bridge serves only a few pages at once), and the plain
// terminal always (the bridge streams it under its session id). Other sessions without a ticket keep their own view.
function liveTermWanted(body) {
  if (!body) return false;
  if (body.dataset.liveKind) return body.dataset.liveKind === 'terminal';
  return body.dataset.liveView === 'term';
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
function liveTermSay(r) {
  if (r.status === 403) window.orch?.toast?.(r.text || 'Sign in to type here: open the dashboard with a sign-in link from orch.', 'error');
  else if (r.status === 409 && /Another page/.test(r.text)) window.orch?.toast?.(r.text, 'error');
  else if (r.status === 409) window.orch?.toast?.('The helper’s screen has closed; that was not sent. Start the helper again from its pane, then type again.', 'error');
  else window.orch?.toast?.(r.text.slice(0, 120) || 'The screen did not take that. Try again.', 'error');
}
const liveTermJSON = s => { try { return JSON.parse(s); } catch (e) { return null; } };
function liveTermFor(id, label, plain) {
  let t = liveTerms.get(id);
  if (t) return t;
  const page = typeof snapshot !== 'undefined' && snapshot ? '' : typeof liveLayerPage === 'function' ? liveLayerPage()?.name || '' : '';
  const ui = window.UI.term({
    label, plain,
    settingsHref: page ? '#settings/addons/' + encodeURIComponent(page) : null,  // ORCH-1600: the typing switch is there
    onInput: async data => { const r = await liveTermPost('/api/term/input', {ticket:id, data, page:t.page}); if (!r.ok) liveTermSay(r); return r; },
    onSize: size => liveTermPost('/api/term/size', {ticket:id, cols:size.cols, rows:size.rows, page:t.page}),
    onTyping: async (on, byOther) => {
      if (!t.page || byOther) return;  // no stream yet, or another page took it (nothing to give back)
      const r = await liveTermPost('/api/term/typing', {ticket:id, page:t.page, on});
      if (on && !r.ok) { ui.setTyping(false); liveTermSay(r); }
    },
  });
  t = {ui, es:null, seen:Date.now(), ended:false, retry:0, page:''};
  liveTerms.set(id, t);
  return t;
}
// Opens the session's stream (once; again after it closed and LIVE_TERM_RETRY passed).
function liveTermOpen(id, t) {
  if (t.es || typeof EventSource !== 'function' || Date.now() < t.retry) return;
  const es = new EventSource('/api/term/stream?ticket=' + encodeURIComponent(id));
  t.es = es; t.ended = false;
  es.addEventListener('hello', e => { const h = liveTermJSON(e.data); t.page = (h && typeof h.page === 'string') ? h.page : ''; t.ui.hello(h); });
  es.addEventListener('typing', e => t.ui.typingBy((liveTermJSON(e.data) || {}).by || 'none'));
  es.addEventListener('screen', e => { const s = liveTermJSON(e.data); if (s) t.ui.screen(s); });
  es.addEventListener('out', e => t.ui.write(e.data));
  es.addEventListener('size', e => t.ui.size(liveTermJSON(e.data)));
  es.addEventListener('end', e => { t.ui.end((liveTermJSON(e.data) || {}).state || 'none'); t.ended = true; liveTermClose(t, LIVE_TERM_RETRY); });
  es.onerror = () => {
    if (t.ended) return;
    // the bridge takes typing only while this page's stream is open: no typing until a new hello and screen arrive
    if (es.readyState === 2) { liveTermClose(t, LIVE_TERM_RETRY); t.ui.show('error'); }  // refused or gone: later again
    else t.ui.show('loading');  // the browser opens it again by itself
  };
}
function liveTermClose(t, wait) {
  if (t.es) { t.es.close(); t.es = null; if (!t.ended) t.ui.show('loading'); }  // a closed stream takes no typing
  t.retry = Date.now() + (wait || 0);
}
// Called by liveLayerFill for every pane body with its live session (null: no helper, then the pane says so itself):
// puts the session's terminal in the body when it shows Terminal, and hides the plain last lines there. The same
// element moves into a body the layer drew again.
function liveTermApply(body, live) {
  if (typeof window !== 'object' || !window.UI?.term) return;
  const id = body.dataset.liveBody, plain = body.dataset.liveKind === 'terminal', on = (plain || !!live) && liveTermWanted(body);
  const pre = body.querySelector('[data-live-lines]');
  if (!on) {
    const t = liveTerms.get(id);
    // this body showed it, or the layer drew the pane again and it sits in the old one: out, typing off, stream closed
    if (t && (t.ui.el.parentNode === body || !document.contains(t.ui.el))) { t.ui.setTyping(false); t.ui.el.remove(); liveTermClose(t); }
    return;
  }
  const label = body.closest('.live-pane')?.querySelector('.live-pt')?.textContent || 'the helper';
  const t = liveTermFor(id, label, plain);
  t.seen = Date.now();
  if (t.ui.el.parentNode !== body) {
    if (pre) pre.after(t.ui.el); else body.append(t.ui.el);
    t.ui.back();
  }
  if (pre) pre.hidden = true;
  liveTermOpen(id, t);
}
// A terminal no pane shows stops typing and closes its stream; after a while it is dropped.
function liveTermTick() {
  const now = Date.now();
  for (const [id, t] of liveTerms) {
    if (document.contains(t.ui.el)) { t.seen = now; continue; }
    if (t.ui.typing()) t.ui.setTyping(false);  // nothing is typed into a screen nobody sees
    if (t.es) liveTermClose(t);
    if (now - t.seen > LIVE_TERM_KEEP) { t.ui.dispose(); liveTerms.delete(id); }
  }
}
if (typeof window === 'object' && typeof document === 'object' && !(typeof module === 'object' && module.exports)) {
  setInterval(liveTermTick, LIVE_TERM_EVERY);
}
if (typeof module === 'object' && module.exports) module.exports = {liveTermWanted, liveTermApply, liveTermTick, liveTerms};
