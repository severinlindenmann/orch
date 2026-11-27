'use strict';
// The terminal view of a session in the layer (ORCH-744, draft D feature 5): the helper's real screen in the master
// terminal (kit term.js, UI.term) where the pane shows Terminal. No switch (ORCH-2199, owner pick B a): a click into the
// screen types there, Esc twice or a click outside stops; the server checks again (the typing setting and the
// sign-in). The screen's tools (keyboard icon, Copy) sit in the pane header, so the screen gets the pane's height.
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
// terminal always (the bridge streams it under its session id). The Manager shows its terminal like a helper's
// (ORCH-1756: its plain last lines were cut off in the panel). Other sessions without a ticket keep their own view.
function liveTermWanted(body) {
  if (!body) return false;
  if (body.dataset.liveKind) return body.dataset.liveKind === 'terminal' || body.dataset.liveKind === 'manager';
  return body.dataset.liveView === 'term';
}
// The answer of a POST in the shape UI.term wants: {ok, status, text}.
async function liveTermPost(path, payload) {
  try {
    const r = await fetch(path, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
    return {ok:r.ok, status:r.status, text:r.ok ? '' : window.DashHelpers.answerText(r.status, await r.text()).slice(0, 300)};
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
    label, plain, toolsOut:true,
    // ORCH-1600: the typing switch is there; the plain terminal's is the owner's, in People (ORCH-1684)
    settingsHref: page ? (plain ? '#settings/people' : '#settings/addons/' + encodeURIComponent(page)) : null,
    onInput: async data => { const r = await liveTermPost('/api/term/input', {ticket:id, data, page:t.page}); if (!r.ok) liveTermSay(r); return r; },
    onSize: size => liveTermPost('/api/term/size', {ticket:id, cols:size.cols, rows:size.rows, page:t.page}),
    onTyping: async (on, byOther) => {
      liveTermTold();
      if (!t.page || byOther) return;  // no stream yet, or another page took it (nothing to give back)
      const r = await liveTermPost('/api/term/typing', {ticket:id, page:t.page, on});
      if (on && !r.ok) { ui.setTyping(false); liveTermSay(r); }
    },
  });
  t = {ui, es:null, seen:Date.now(), ended:false, retry:0, page:'', allowed:false, want:false};
  liveTerms.set(id, t);
  liveTermTold();  // a sign-in card asks again whether the person can type here (ORCH-865)
  return t;
}
// A sign-in card shows "Turn on typing to sign in here" while the person cannot type into its terminal (ORCH-865):
// it hears every change of typing here, and its switch (the person's own click) asks for typing with want(id).
const liveTermTold = () => { if (typeof window === 'object' && typeof CustomEvent === 'function') window.dispatchEvent(new CustomEvent('orch:term-typing')); };
if (typeof window === 'object') window.LiveTerm = {
  has: id => liveTerms.has(id),
  typing: id => !!liveTerms.get(id)?.ui.typing(),
  send: liveTermSend,
  mount: (host, id, label, plain) => liveTermMount(host, id, label, plain),
  // typing for this session as soon as its stream allows it: now, or after a new hello (the setting was just turned on)
  want(id) {
    const t = liveTerms.get(id);
    if (!t) return;
    t.want = true;
    if (t.allowed && t.es) { t.ui.setTyping(true); if (t.ui.typing()) { t.want = false; return; } }
    liveTermClose(t, 0);  // the stream opens again on the next tick and says hello with the new setting
  },
};
// Types text (never Enter) into a session's terminal for "Run in terminal" (ORCH-2203): the session's pane shows its
// terminal (opened or switched to Terminal), and once its stream says hello the text goes the way a key does
// (/api/term/input: the sign-in and the typing setting are checked there). Resolves {ok, text}.
async function liveTermSend(id, text, {wait = 6000, plain = false} = {}) {
  if (!plain && typeof liveViewSet === 'function' && liveViewOf(id) !== 'term') liveViewSet(id, 'term');
  if (plain && typeof window === 'object') window.LiveLayer?.open?.(id);
  if (typeof liveLayerFill === 'function') liveLayerFill();
  const until = Date.now() + wait;
  let t = liveTerms.get(id);
  while (!(t && t.es && t.page) && Date.now() < until) { await new Promise(r => setTimeout(r, 100)); t = liveTerms.get(id); }
  if (!(t && t.es && t.page)) return {ok:false, text:'That terminal is not open yet. Open it and try again.'};
  const r = await liveTermPost('/api/term/input', {ticket:id, data:text, page:t.page});
  if (!r.ok) liveTermSay(r);
  return r;
}
// Review's side panel (ORCH-2185, Focused review D): the session's terminal in a host of its own, watching until the
// person turns on "Let me type". It is the same one terminal and stream per session as a live pane's: a terminal a
// pane shows now stays there (false: the panel says where it is). liveTermTick closes it once no page shows it.
function liveTermMount(host, id, label, plain = false) {
  if (!host || typeof window !== 'object' || !window.UI?.term || !/^t_[a-z0-9]{6,16}$/.test(String(id || ''))) return false;
  const t = liveTermFor(id, label || 'the helper', plain);
  if (t.ui.el.parentNode !== host && document.contains(t.ui.el)) return false;
  t.seen = Date.now();
  if (t.ui.el.parentNode !== host) { host.append(t.ui.el); t.ui.back(); }
  liveTermOpen(id, t);
  return true;
}
// Opens the session's stream (once; again after it closed and LIVE_TERM_RETRY passed).
function liveTermOpen(id, t) {
  if (t.es || typeof EventSource !== 'function' || Date.now() < t.retry) return;
  const es = new EventSource('/api/term/stream?ticket=' + encodeURIComponent(id));
  t.es = es; t.ended = false;
  es.addEventListener('hello', e => {
    const h = liveTermJSON(e.data); t.page = (h && typeof h.page === 'string') ? h.page : ''; t.ui.hello(h);
    t.allowed = !!(h && h.typing_allowed === true);
  });
  es.addEventListener('typing', e => { t.ui.typingBy((liveTermJSON(e.data) || {}).by || 'none'); liveTermTold(); });
  es.addEventListener('screen', e => {
    const s = liveTermJSON(e.data); if (s) t.ui.screen(s);
    if (t.want && t.allowed) { t.ui.setTyping(true); t.want = !t.ui.typing(); }  // a sign-in card's switch (ORCH-865)
    liveTermTold();
  });
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
// The line above a one-step helper's log in the Terminal view (ORCH-1797): no live screen exists for it.
const LIVE_LOG_WINDOWS = 'On Windows helpers run in one step; the live screen is not there yet. This is the helper’s log.';
const LIVE_LOG_ONESTEP = 'This helper runs in one step, so it has no live screen. This is the helper’s log.';
const LIVE_LOG_EMPTY = ' Nothing is in it yet.';
function liveLogNote(live, windows) {
  return (windows ? LIVE_LOG_WINDOWS : LIVE_LOG_ONESTEP) + (Array.isArray(live?.lines) && live.lines.length ? '' : LIVE_LOG_EMPTY);
}
// Called by liveLayerFill for every pane body with its live session (null: no helper, then the pane says so itself):
// puts the session's terminal in the body when it shows Terminal, and hides the plain last lines there. The same
// element moves into a body the layer drew again. A helper that runs in one step has no screen to stream: the
// Terminal view shows its log (the plain last lines) under one plain line instead of an empty terminal (ORCH-1797).
function liveTermApply(body, live) {
  const id = body.dataset.liveBody, plain = body.dataset.liveKind === 'terminal';
  const log = !plain && live?.mode === 'oneshot' && liveTermWanted(body);
  const pre = body.querySelector('[data-live-lines]'), note = body.querySelector('[data-live-log-note]');
  if (note) {
    const text = log ? liveLogNote(live, typeof window === 'object' && window.LiveSessions?.windows === true) : '';
    if (note.textContent !== text) note.textContent = text;
    note.hidden = !log;
  }
  if (log && pre) pre.hidden = !(Array.isArray(live.lines) && live.lines.length);
  if (typeof window !== 'object' || !window.UI?.term) return;
  const on = (plain || !!live) && !log && liveTermWanted(body);
  if (!on) {
    const t = liveTerms.get(id);
    // this body showed it, or the layer drew the pane again and it sits in the old one: out, typing off, stream closed
    if (t && (t.ui.el.parentNode === body || !document.contains(t.ui.el))) { t.ui.setTyping(false); t.ui.el.remove(); t.ui.tools?.remove(); liveTermClose(t); }
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
  const slot = body.closest('.live-pane')?.querySelector('[data-live-term-tools]');
  if (slot && t.ui.tools && t.ui.tools.parentNode !== slot) slot.append(t.ui.tools);
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
if (typeof module === 'object' && module.exports) module.exports = {liveTermSend, liveTermMount, liveTermWanted, liveTermApply, liveTermTick, liveTerms, liveLogNote};
