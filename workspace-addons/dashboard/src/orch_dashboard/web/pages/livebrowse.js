'use strict';
// The helper's browser, live (ORCH-1493, watch only): the master view (kit browser.js, UI.browserView) on the browser
// add-on's stream, GET /api/browse/stream?ticket=<id> (server-sent events): hello {generation}, tabs {tabs},
// frame {jpeg, w, h, at}, clear, event {text, site_text?}, beat, end {why, final}. Stop is POST /api/browse/stop
// {ticket, generation} (the person's session; it ends that browser only). A stream that drops opens again after
// 1, 2, 4, 8, then every 15 s; an end that is final (the browser closed) does not, until the page asks again.
// One view per ticket, kept across repaints (a host gets the same element back). The page #browser/<ticket> shows
// it on its own; ORCH-1494 puts it in the ticket, Activity, Focus and chat.
const LIVE_BROWSE_BACKOFF = [1000, 2000, 4000, 8000, 15000];
const liveBrowses = new Map();  // ticket id -> {ui, es, tries, timer, final}

function liveBrowseJSON(s) { try { return JSON.parse(s); } catch (e) { return null; } }
async function liveBrowseStop(ticket, generation) {
  try {
    const r = await fetch('/api/browse/stop', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ticket, generation})});
    if (!r.ok) window.orch?.toast?.((await r.text()).slice(0, 160) || 'The browser did not stop. Try again.', 'error');
    return {ok:r.ok};
  } catch (e) { return {ok:false}; }
}
function liveBrowseFor(ticket) {
  let b = liveBrowses.get(ticket);
  if (b) return b;
  const ui = window.UI.browserView({label:'The helper’s browser', onStop:gen => liveBrowseStop(ticket, gen)});
  b = {ui, es:null, tries:0, timer:0, final:false};
  liveBrowses.set(ticket, b);
  return b;
}
function liveBrowseOpen(ticket, b) {
  if (b.es || b.final || typeof EventSource !== 'function') return;
  const es = new EventSource('/api/browse/stream?ticket=' + encodeURIComponent(ticket));
  b.es = es;
  es.addEventListener('hello', e => { b.tries = 0; b.ui.hello(liveBrowseJSON(e.data) || {}); });
  es.addEventListener('tabs', e => b.ui.tabs((liveBrowseJSON(e.data) || {}).tabs));
  es.addEventListener('frame', e => b.ui.frame(liveBrowseJSON(e.data)));
  es.addEventListener('clear', () => b.ui.clear());
  es.addEventListener('event', e => b.ui.event(liveBrowseJSON(e.data)));
  es.addEventListener('end', e => {
    const d = liveBrowseJSON(e.data) || {};
    b.ui.end(d);
    liveBrowseClose(b);
    if (d.final) b.final = true; else liveBrowseLater(ticket, b);  // no browser yet: look again later
  });
  es.onerror = () => { if (b.final) return; liveBrowseClose(b); b.ui.show('lost'); liveBrowseLater(ticket, b); };
}
function liveBrowseClose(b) { if (b.es) { b.es.close(); b.es = null; } }
function liveBrowseLater(ticket, b) {
  clearTimeout(b.timer);
  const wait = LIVE_BROWSE_BACKOFF[Math.min(b.tries, LIVE_BROWSE_BACKOFF.length - 1)];
  b.tries += 1;
  b.timer = setTimeout(() => liveBrowseOpen(ticket, b), wait);
}
// Called after each paint: every [data-live-browse] host shows its ticket's view (and opens its stream).
function mountLiveBrowse(main) {
  if (!window.UI?.browserView) return;
  main.querySelectorAll('[data-live-browse]').forEach(host => {
    const ticket = host.dataset.liveBrowse, b = liveBrowseFor(ticket);
    if (b.ui.el.parentNode !== host) host.replaceChildren(b.ui.el);
    liveBrowseOpen(ticket, b);
  });
  // a view no page shows any more closes its stream
  for (const [ticket, b] of liveBrowses) {
    if (!b.ui.el.isConnected) { liveBrowseClose(b); clearTimeout(b.timer); b.ui.dispose(); liveBrowses.delete(ticket); }
  }
}
function liveBrowsePage(id) {
  return fragment(heading('The helper’s browser', ''), h('div', {className:'stack', 'data-key':'live-browse'},
    h('div', {'data-live-browse':id})));
}
if (typeof module === 'object' && module.exports) module.exports = {LIVE_BROWSE_BACKOFF, liveBrowseFor, liveBrowseOpen, mountLiveBrowse, liveBrowses};
