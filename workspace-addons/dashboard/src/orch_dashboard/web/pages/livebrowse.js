'use strict';
// The helper's browser, live (ORCH-1493, watch only): the master view (kit browser.js, UI.browserView) on the browser
// add-on's stream, GET /api/browse/stream?ticket=<id> (server-sent events): hello {generation}, tabs {tabs},
// frame {jpeg, w, h, at}, clear, event {text, site_text?}, beat, end {why, final}. Stop is POST /api/browse/stop
// {ticket, generation} (the person's session; it ends that browser only). A stream that drops opens again after
// 1, 2, 4, 8, then every 15 s; an end that is final (the browser closed) does not, until the page asks again.
// One view per ticket, kept across repaints (a host gets the same element back). The page #browser/<ticket> shows
// it on its own.
// Places (ORCH-1494, the owner's pick on ORCH-1341: "Use A"): the small live preview (UI.browserPeek) is the ONE way
// in. It sits in the ticket's Activity, in Focus, in the ticket chat and on the Browser page (the add-on's tab, panel
// "browser": every helper's browser in one list, ended today as links). A click opens the live view in the ticket,
// next to the steps (#ticket/<id>?browser=open); on the ticket itself it opens in place. Only while the browser add-on
// is on, and only while GET /api/browse/list says the ticket's browser is open (or ended in the last day: then one
// quiet "ended" line). The list is read every 5 s while a place is on screen; a stream opens only for an open
// browser that a place shows, and one stream feeds the view and every preview of that ticket.
const LIVE_BROWSE_BACKOFF = [1000, 2000, 4000, 8000, 15000];
const BROWSE_LIST_EVERY = 5000;
const MAX_BROWSE_STREAMS = 4;  // the browser allows six connections per address; the rest of the page keeps two
const liveBrowses = new Map();  // ticket id -> {ui, peeks: Map place -> peek, es, tries, timer, final, gen, last}
const browseList = {doc:null, sig:'', timer:0, busy:false, tried:false};  // the newest GET /api/browse/list

function liveBrowseJSON(s) { try { return JSON.parse(s); } catch (e) { return null; } }
// The add-on is on: its tab is the native Browser page (the dashboard never names an add-on).
const browseOn = () => !(typeof snapshot !== 'undefined' && snapshot) && typeof addons === 'function' && addons().some(a => a.dashboard?.panel === 'browser');
const browseRow = id => (browseList.doc?.browsers || []).find(r => r && r.ticket === id) || null;
const browseHref = id => '#ticket/' + encodeURIComponent(id) + '?browser=open';
// The ticket page shows the live view next to the steps when its address asks for it.
function browseViewIn(id) {
  if (!browseOn() || typeof location !== 'object') return false;
  const full = String(location.hash || ''), at = full.indexOf('?');
  return at >= 0 && full.slice(0, at) === '#ticket/' + encodeURIComponent(id) && new URLSearchParams(full.slice(at + 1)).get('browser') === 'open';
}
function browseSetOpen(id, on) {
  const base = '#ticket/' + encodeURIComponent(id);
  if (String(location.hash || '').split('?')[0] !== base) { if (on) location.hash = browseHref(id); else location.hash = base; return; }
  if (on) history.pushState(null, '', browseHref(id)); else history.replaceState(null, '', base);
  render();
  const host = on ? main.querySelector('[data-live-browse="' + id.replace(/[^a-z0-9_]/g, '') + '"]') : null;
  if (host && host.scrollIntoView) host.scrollIntoView({block:'nearest'});
}
// A preview's place in a page: filled by mountLiveBrowse after each paint.
function browsePeekHost(id, place) {
  if (!browseOn() || !id) return null;
  return h('div', {className:'bpeek-host' + (place === 'chat' ? ' inset' : ''), 'data-browse-peek':id, 'data-place':place, 'data-key':'bpeek-' + place + '-' + id});
}

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
  b = {ui:null, peeks:new Map(), es:null, tries:0, timer:0, final:false, gen:'', last:{}};
  liveBrowses.set(ticket, b);
  return b;
}
function liveBrowseView(ticket, b) {
  if (b.ui) return b.ui;
  b.ui = window.UI.browserView({label:'The helper’s browser', onStop:gen => liveBrowseStop(ticket, gen),
    onHide:() => browseSetOpen(ticket, false)});
  liveBrowseReplay(b, b.ui);
  return b.ui;
}
// A view or preview that comes after the stream began gets what the stream already said.
function liveBrowseReplay(b, to) {
  const l = b.last;
  if (l.end) { if (to === b.ui) to.end(l.end); return; }
  if (l.hello) to.hello(l.hello);
  if (l.tabs) to.tabs(l.tabs);
  if (l.frame) to.frame(l.frame);
}
function liveBrowseFan(b, kind, data) {
  if (kind === 'hello') b.last = {hello:data};
  else if (kind === 'tabs' || kind === 'frame') b.last[kind] = data;
  else if (kind === 'clear') delete b.last.frame;
  if (b.ui && typeof b.ui[kind] === 'function') b.ui[kind](data);
  for (const p of b.peeks.values()) if (kind !== 'event' && typeof p[kind] === 'function') p[kind](data);
}
function liveBrowseOpen(ticket, b) {
  if (b.es || b.final || typeof EventSource !== 'function') return;
  const es = new EventSource('/api/browse/stream?ticket=' + encodeURIComponent(ticket));
  b.es = es;
  es.addEventListener('hello', e => { b.tries = 0; const d = liveBrowseJSON(e.data) || {}; b.gen = d.generation || ''; liveBrowseFan(b, 'hello', d); });
  es.addEventListener('tabs', e => liveBrowseFan(b, 'tabs', (liveBrowseJSON(e.data) || {}).tabs));
  es.addEventListener('frame', e => liveBrowseFan(b, 'frame', liveBrowseJSON(e.data)));
  es.addEventListener('clear', () => liveBrowseFan(b, 'clear'));
  es.addEventListener('event', e => liveBrowseFan(b, 'event', liveBrowseJSON(e.data)));
  es.addEventListener('end', e => {
    const d = liveBrowseJSON(e.data) || {};
    if (b.ui) b.ui.end(d);
    liveBrowseClose(b);
    if (d.final) {  // the browser closed: the previews say so with its time from the list
      b.final = true; b.last = {end:d};
      for (const p of b.peeks.values()) p.end(d, Date.now() / 1000);
      browseListLoad();
    } else liveBrowseLater(ticket, b);  // no browser yet: look again later
  });
  es.onerror = () => { if (b.final) return; liveBrowseClose(b); if (b.ui) b.ui.show('lost'); liveBrowseLater(ticket, b); };
}
function liveBrowseClose(b) { if (b.es) { b.es.close(); b.es = null; } }
function liveBrowseLater(ticket, b) {
  clearTimeout(b.timer);
  const wait = LIVE_BROWSE_BACKOFF[Math.min(b.tries, LIVE_BROWSE_BACKOFF.length - 1)];
  b.tries += 1;
  b.timer = setTimeout(() => liveBrowseOpen(ticket, b), wait);
}
// A new browser for the same ticket (another generation) is watched afresh.
function liveBrowseFresh(b, row) {
  if (row?.open && row.generation && b.final && row.generation !== b.gen) { b.final = false; b.tries = 0; b.last = {}; }
}

// What a preview says now: live (stream), ended in the last day (one quiet line), or nothing. True = live.
function browsePeekSay(b, row, peek) {
  if (!row) { peek.hide(); return false; }
  liveBrowseFresh(b, row);
  if (!row.open) { peek.end(row, row.ended || 0); return false; }
  if (b.final) return false;  // ended a moment ago; the list says so at its next look
  if (b.last.hello) liveBrowseReplay(b, peek);
  return true;
}
function browsePeekOpen(ticket, place) {
  if (place === 'ticket') browseSetOpen(ticket, !browseViewIn(ticket));
  else location.hash = browseHref(ticket);
}
// Called after each paint (and after Focus paints its layer): every [data-live-browse] host shows its ticket's view,
// every [data-browse-peek] host its preview; streams open for what is shown, close for what is not.
function mountLiveBrowse() {
  if (!window.UI?.browserView || typeof document !== 'object') return;
  const want = new Set();
  document.querySelectorAll('[data-live-browse]').forEach(host => {
    const ticket = host.dataset.liveBrowse, b = liveBrowseFor(ticket), ui = liveBrowseView(ticket, b);
    if (ui.el.parentNode !== host) host.replaceChildren(ui.el);
    if (typeof mounts === 'object' && !mounts.has(host)) mounts.set(host, {destroy() {}});
    liveBrowseFresh(b, browseRow(ticket));
    want.add(ticket);
  });
  if (window.UI.browserPeek) document.querySelectorAll('[data-browse-peek]').forEach(host => {
    const ticket = host.dataset.browsePeek, place = host.dataset.place || 'ticket', b = liveBrowseFor(ticket);
    let peek = b.peeks.get(place);
    if (!peek) { peek = window.UI.browserPeek({onOpen:() => browsePeekOpen(ticket, place), wide:place === 'list', compact:place === 'pane' || place === 'chat'}); b.peeks.set(place, peek); }
    if (peek.el.parentNode !== host) host.replaceChildren(peek.el);
    if (typeof mounts === 'object' && !mounts.has(host)) mounts.set(host, {destroy() {}});
    peek.open(place === 'ticket' && browseViewIn(ticket));
    if (browsePeekSay(b, browseRow(ticket), peek)) want.add(ticket);
  });
  let streams = 0;  // the open live view first, then the previews; at most MAX_BROWSE_STREAMS keep a connection
  const order = [...liveBrowses].sort(([, x], [, y]) => (y.ui ? 1 : 0) - (x.ui ? 1 : 0));
  for (const [ticket, b] of order) {
    for (const [place, p] of b.peeks) if (!p.el.isConnected) { p.dispose(); b.peeks.delete(place); }
    if (b.ui && !b.ui.el.isConnected) { b.ui.dispose(); b.ui = null; }
    if (want.has(ticket) && streams < MAX_BROWSE_STREAMS) { streams += 1; liveBrowseOpen(ticket, b); }
    else { liveBrowseClose(b); clearTimeout(b.timer); }
    if (!b.ui && !b.peeks.size) liveBrowses.delete(ticket);
  }
  browsePoll();
}

// ---- the list (GET /api/browse/list), read while a place is on screen ----
const browseShown = () => !!document.querySelector('[data-browse-peek],[data-live-browse],[data-browse-page]');
function browsePoll() {
  if (!browseOn() || !browseShown()) { clearTimeout(browseList.timer); browseList.timer = 0; return; }
  if (!browseList.tried) { browseListLoad(); return; }
  if (browseList.timer) return;  // a look is already planned: a repaint keeps it
  browseList.timer = setTimeout(() => { browseList.timer = 0; if (document.hidden) browsePoll(); else browseListLoad(); }, BROWSE_LIST_EVERY);
}
async function browseListLoad() {
  if (browseList.busy || !browseOn()) return;
  browseList.busy = true; browseList.tried = true;
  let doc = null;
  try {
    const r = await fetch('/api/browse/list', {cache:'no-store'});
    if (r.ok) doc = await r.json();
  } catch (e) { /* the next look tries again */ }
  browseList.busy = false;
  if (doc && Array.isArray(doc.browsers)) {
    const sig = JSON.stringify(doc);
    browseList.doc = doc;
    if (sig !== browseList.sig) { browseList.sig = sig; render(); return; }  // the paint mounts and polls again
  }
  browsePoll();
}

// ---- the Browser page (the add-on's tab, panel "browser"): every helper's browser in one list ----
const browseTitle = r => { const t = typeof ticketOf === 'function' ? ticketOf(r.ticket) : null; return clean(t?.title || r.title || 'A ticket'); };
const browseToday = sec => new Date(sec * 1000).toDateString() === new Date().toDateString();
const browseClock = sec => (window.UI?.clock ? window.UI.clock(new Date(sec * 1000)) : '');
function browserListPage(a) {
  const doc = browseList.doc, head = heading(addonTitle(a), a?.dashboard?.subtitle || '', {});
  const page = (...body) => fragment(head, h('div', {className:'stack', 'data-browse-page':'', 'data-key':'browse-page'}, ...body));
  if (!doc) return page(typeof skeletonFor === 'function' ? skeletonFor('section') : null);
  if (!doc.on) return page(stateNote('The browser add-on is not turned on in this workspace.', '', 'error'));
  const live = doc.browsers.filter(r => r.open), ended = doc.browsers.filter(r => !r.open && r.ended && browseToday(r.ended));
  const body = [];
  if (live.length) body.push(h('section', {className:'stack', 'data-key':'browse-live'}, h('h2', {}, 'Live now', h('span', {className:'muted'}, ' · ' + live.length)),
    live.map(r => h('section', {className:'stack', 'data-key':'browse-row-' + r.ticket},
      h('h3', {}, h('a', {href:'#ticket/' + encodeURIComponent(r.ticket)}, browseTitle(r))),
      browsePeekHost(r.ticket, 'list')))));
  if (ended.length) body.push(h('section', {className:'card pad stack', 'data-key':'browse-ended'}, h('h2', {}, 'Ended today', h('span', {className:'muted'}, ' · ' + ended.length)),
    h('div', {className:'stack'}, ended.map(r => h('p', {'data-key':'browse-ended-' + r.ticket},
      h('a', {href:'#ticket/' + encodeURIComponent(r.ticket)}, browseTitle(r)), h('span', {className:'meta'}, ' · ended at ' + browseClock(r.ended)))))));
  if (!body.length) body.push(stateNote('No helper is using a browser right now', 'When a helper opens a web page for a ticket, you can watch it here.'));
  return page(body);
}

function liveBrowsePage(id) {
  return fragment(heading('The helper’s browser', ''), h('div', {className:'stack', 'data-key':'live-browse'},
    h('div', {'data-live-browse':id})));
}
if (typeof module === 'object' && module.exports) module.exports = {LIVE_BROWSE_BACKOFF, BROWSE_LIST_EVERY, liveBrowseFor, liveBrowseView, liveBrowseOpen, liveBrowseFan, browsePeekSay, mountLiveBrowse, liveBrowses, browseList, browseOn, browseRow, browseViewIn, browsePeekHost, browserListPage, browseListLoad};
