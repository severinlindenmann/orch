'use strict';
// The helper's browser, live (ORCH-1493, watch only): the master view (kit browser.js, UI.browserView) on the browser
// add-on's stream, GET /api/browse/stream?ticket=<id> (server-sent events): hello {generation}, tabs {tabs},
// frame {jpeg, w, h, at}, clear, event {text, site_text?, allow?}, beat, end {why, final}. Stop is POST /api/browse/stop
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
// Take over and give back (ORCH-1495): the stream's hello carries this page's id (the broker mints it), `control`
// {state, epoch, mine, asking?} says who drives. Take over, Stop its step now, Give back and the person's input are
// POST /api/browse/take {ticket, generation, page, epoch, action}, /api/browse/give and /api/browse/input {..., w, h,
// events}; "Forms may go to" (owner pick A) is POST /api/browse/send {..., site}; while this page holds control it renews its lease every 20 s. A helper that asks for a person (orch
// browse ask-person) is "Waiting for you" on its preview and one line on Home (browseAskBanner).
const LIVE_BROWSE_BACKOFF = [1000, 2000, 4000, 8000, 15000];
const BROWSE_LIST_EVERY = 5000;
const MAX_BROWSE_STREAMS = 4;  // the browser allows six connections per address; the rest of the page keeps two
const BROWSE_RENEW_EVERY = 20000;
const liveBrowses = new Map();  // ticket id -> {ui, peeks: Map place -> peek, es, tries, timer, final, gen, last}
const browseList = {doc:null, sig:'', timer:0, busy:false, tried:false, failed:false};  // the newest GET /api/browse/list

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
    if (!r.ok) window.orch?.toast?.(window.DashHelpers.answerText(r.status, await r.text(), 'The browser did not stop. Try again.').slice(0, 160), 'error');
    return {ok:r.ok};
  } catch (e) { return {ok:false}; }
}
function liveBrowseFor(ticket) {
  let b = liveBrowses.get(ticket);
  if (b) return b;
  b = {ui:null, peeks:new Map(), es:null, tries:0, timer:0, final:false, gen:'', last:{}, page:'', ctl:null, renew:0};
  liveBrowses.set(ticket, b);
  return b;
}
// One take-over call: {ok, text}; a refusal is said in the view (and as a toast when it is not about input).
async function liveBrowsePost(ticket, b, what, extra) {
  if (!b.page || !b.ctl) return {ok:false, text:'Wait a moment: the browser is still connecting.'};
  try {
    const r = await fetch('/api/browse/' + what, {method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({ticket, generation:b.gen, page:b.page, epoch:b.ctl.epoch, ...extra})});
    const text = await r.text();
    if (!r.ok) return {ok:false, text:text.slice(0, 200) || 'That did not work. Try again.'};
    const doc = liveBrowseJSON(text) || {};
    if (Number.isInteger(doc.epoch) && b.ctl && doc.epoch >= b.ctl.epoch) b.ctl = {...b.ctl, epoch:doc.epoch};
    return {ok:true, text:doc.text || ''};
  } catch (e) { return {ok:false, text:'The dashboard could not be reached. Try again.'}; }
}
function liveBrowseControl(ticket, b) {
  const say = r => { if (r && r.ok && r.text) window.orch?.toast?.(r.text); return r; };
  return {
    take:() => liveBrowsePost(ticket, b, 'take', {action:'take'}),
    cancel:() => liveBrowsePost(ticket, b, 'take', {action:'cancel'}),
    give:async () => say(await liveBrowsePost(ticket, b, 'give', {})),
    send:(events, size) => liveBrowsePost(ticket, b, 'input', {w:size.w, h:size.h, events}),
    allowSends:site => liveBrowsePost(ticket, b, 'send', {site:String(site || '')}),
  };
}
// The page that holds control renews its lease while the stream says it is its own (else the broker pauses).
function liveBrowseLease(ticket, b) {
  const mine = b.ctl && b.ctl.mine && (b.ctl.state === 'person' || b.ctl.state === 'finishing');
  if (mine && !b.renew) b.renew = setInterval(() => liveBrowsePost(ticket, b, 'take', {action:'renew'}), BROWSE_RENEW_EVERY);
  if (!mine && b.renew) { clearInterval(b.renew); b.renew = 0; }
}
function liveBrowseView(ticket, b, own = false) {
  if (b.ui) return b.ui;
  // the person's own browser (O-20) sits on the Browser page: nothing to hide into, and its Close is on the page
  b.ui = window.UI.browserView({label:own ? 'Your browser' : 'The helper’s browser', onStop:gen => liveBrowseStop(ticket, gen),
    onHide:own ? null : () => browseSetOpen(ticket, false), control:liveBrowseControl(ticket, b)});
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
  if (l.control && typeof to.control === 'function') to.control(l.control);
}
function liveBrowseFan(b, kind, data) {
  if (kind === 'hello') b.last = {hello:data};
  else if (kind === 'tabs' || kind === 'frame' || kind === 'control') b.last[kind] = data;
  else if (kind === 'clear') delete b.last.frame;
  if (b.ui && typeof b.ui[kind] === 'function') b.ui[kind](data);
  for (const p of b.peeks.values()) if (kind !== 'event' && typeof p[kind] === 'function') p[kind](data);
}
function liveBrowseOpen(ticket, b) {
  if (b.es || b.final || typeof EventSource !== 'function') return;
  const es = new EventSource('/api/browse/stream?ticket=' + encodeURIComponent(ticket));
  b.es = es;
  es.addEventListener('hello', e => { b.tries = 0; const d = liveBrowseJSON(e.data) || {}; b.gen = d.generation || ''; b.page = d.page || ''; b.ctl = null; liveBrowseFan(b, 'hello', d); });
  es.addEventListener('control', e => { const d = liveBrowseJSON(e.data); if (!d) return; b.ctl = d; liveBrowseLease(ticket, b); liveBrowseFan(b, 'control', d); });
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
function liveBrowseClose(b) { if (b.es) { b.es.close(); b.es = null; } b.page = ''; b.ctl = null; if (b.renew) { clearInterval(b.renew); b.renew = 0; } }
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
    const ticket = host.dataset.liveBrowse, b = liveBrowseFor(ticket), ui = liveBrowseView(ticket, b, host.dataset.own === 'yes');
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
const browseShown = () => !!document.querySelector('[data-browse-peek],[data-live-browse],[data-browse-page],[data-browse-asks]');
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
    const sig = JSON.stringify(doc), was = browseList.failed;
    browseList.doc = doc; browseList.failed = false;
    if (sig !== browseList.sig || was) { browseList.sig = sig; render(); return; }  // the paint mounts and polls again
  } else if (!browseList.doc && !browseList.failed) {  // nothing to show yet: the page says so instead of loading on
    browseList.failed = true; render(); return;
  }
  browsePoll();
}

// ---- the Browser page (the add-on's tab, panel "browser"): every helper's browser in one list ----
const browseTitle = r => { const t = typeof ticketOf === 'function' ? ticketOf(r.ticket) : null; return clean(t?.title || r.title || 'A ticket'); };
const browseToday = sec => new Date(sec * 1000).toDateString() === new Date().toDateString();
const browseClock = sec => (window.UI?.clock ? window.UI.clock(new Date(sec * 1000)) : '');

// ---- Allowed sites and your own browser (O-20, O-21: owner, 28 Nov) ----
// GET /api/browse/sites {on, workspace:[site], tickets:[{ticket, title, sites}]}: the workspace's permanent list (it
// holds for every ticket) and each open ticket's own extra sites. POST /api/browse/sites {scope, ticket, add, remove,
// check} reads a typed or pasted list as it would be stored (check) and saves it; POST /api/browse/open {address}
// opens a browser for the person on those same sites. Only a person's own session reaches the two POSTs.
// The page is repainted in place, so every control only names what it does (data-browse-act / data-browse-field)
// and one listener for the whole document acts on it.
const BROWSE_SITE_ROWS = 20;     // rows drawn at once: a list of 1,000 sites is a count and a search, not 1,000 rows
const BROWSE_SEARCH_FROM = 9;    // the search field appears once the list is longer than a glance
const browseSites = {doc:null, busy:false, tried:false, failed:false, query:'', draft:'', check:null, saving:false, said:'', error:'',
  address:'', opening:false, openError:''};
const browseCount = (n, one, many) => Number(n).toLocaleString('en-US') + ' ' + (n === 1 ? one : many);
async function browseSitesLoad() {
  if (browseSites.busy || !browseOn()) return;
  browseSites.busy = true; browseSites.tried = true;
  let doc = null;
  try { const r = await fetch('/api/browse/sites', {cache:'no-store'}); if (r.ok) doc = await r.json(); } catch (e) { /* said on the page */ }
  browseSites.busy = false;
  if (doc && Array.isArray(doc.workspace)) { browseSites.doc = doc; browseSites.failed = false; } else browseSites.failed = true;
  render();
}
// Every allowed site with where it comes from: the workspace's first (by name), then each ticket's own.
function browseSiteRows(doc) {
  const rows = (doc?.workspace || []).filter(s => typeof s === 'string').map(site => ({site, scope:'workspace', ticket:null, source:'Workspace'}));
  for (const t of Array.isArray(doc?.tickets) ? doc.tickets : []) {
    for (const site of Array.isArray(t?.sites) ? t.sites : []) if (typeof site === 'string') rows.push({site, scope:'ticket', ticket:String(t.ticket), source:'Ticket: ' + browseTitle(t)});
  }
  return rows;
}
async function browseSitesPost(body) {
  try {
    const r = await fetch('/api/browse/sites', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({scope:'workspace', ticket:null, add:'', remove:[], check:false, ...body})});
    const text = await r.text();
    if (!r.ok) return {ok:false, text:window.DashHelpers?.answerText ? window.DashHelpers.answerText(r.status, text, 'The list was not changed. Try again.').slice(0, 200) : text.slice(0, 200) || 'The list was not changed. Try again.'};
    return {ok:true, doc:liveBrowseJSON(text) || {}};
  } catch (e) { return {ok:false, text:'The dashboard could not be reached. Try again.'}; }
}
// Add: what was typed or pasted is read first as it would be stored. A clean list is saved at once (one click); when
// an entry is stored under another name ("*.20min.ch" is 20min.ch) or cannot be a site, the page shows that first.
async function browseSitesAdd(confirmed) {
  const typed = String(browseSites.draft || '').trim();
  if (browseSites.saving || (!typed && !confirmed)) return;
  browseSites.saving = true; browseSites.error = ''; browseSites.said = ''; render();
  let r;
  if (confirmed && browseSites.check) r = await browseSitesPost({add:browseSites.check.new});
  else {
    r = await browseSitesPost({add:typed, check:true});
    const c = r.ok ? r.doc : null;
    if (c && !c.refused_count && !(c.changed || []).length && (c.new || []).length) r = await browseSitesPost({add:c.new});
    else if (c) { browseSites.saving = false; browseSites.check = c; render(); return; }
  }
  browseSites.saving = false;
  if (!r.ok) { browseSites.error = r.text; render(); return; }
  const n = (r.doc.new || []).length;
  browseSites.said = n ? 'Added ' + browseCount(n, 'site', 'sites') + '.' : 'Nothing new: already on the list.';
  browseSites.check = null; browseSites.draft = '';
  const box = document.querySelector('[data-browse-field="draft"]'); if (box) box.value = '';
  await browseSitesLoad();
}
async function browseSitesRemove(site, scope, ticket) {
  if (browseSites.saving) return;
  browseSites.saving = true; browseSites.error = ''; browseSites.said = ''; render();
  const r = await browseSitesPost(scope === 'ticket' ? {scope, ticket, remove:[site]} : {remove:[site]});
  browseSites.saving = false;
  if (!r.ok) { browseSites.error = r.text; render(); return; }
  // undo is one click: the removed site goes back on the list it came from
  window.orch?.toast?.('Removed ' + site + '.', 'ok', async () => { await browseSitesPost(scope === 'ticket' ? {scope, ticket, add:[site]} : {add:[site]}); browseSitesLoad(); });
  await browseSitesLoad();
}
// What the reading of a pasted list says, before anything is saved.
function browseCheckNote(c) {
  const fresh = (c.new || []).length, changed = (c.changed || []).filter(x => (c.new || []).includes(x.site));
  const lines = [h('p', {'data-key':'browse-check-sum'}, [fresh ? browseCount(fresh, 'site', 'sites') + ' to add' : 'Nothing new to add',
    c.known ? browseCount(c.known, 'is', 'are') + ' on the list already' : '', c.repeats ? browseCount(c.repeats, 'was', 'were') + ' in the list twice' : ''].filter(Boolean).join(' · ') + '.')];
  if (changed.length) lines.push(h('p', {className:'meta', 'data-key':'browse-check-changed'}, 'Stored as: ' + changed.slice(0, 5).map(x => clean(x.entry) + ' → ' + clean(x.site)).join(', ')
    + (changed.length > 5 ? ' and ' + (changed.length - 5) + ' more' : '') + '. A site covers every part of it (www, news, …).'));
  if (c.refused_count) lines.push(h('p', {className:'meta bad', role:'alert', 'data-key':'browse-check-refused'}, browseCount(c.refused_count, 'entry cannot', 'entries cannot') + ' be a site: '
    + (c.refused || []).slice(0, 3).map(x => clean(x.entry) + ' (' + clean(x.why) + ')').join('; ') + (c.refused_count > 3 ? '; and ' + (c.refused_count - 3) + ' more' : '') + '. They are left out.'));
  return h('div', {className:'banner', role:'status', 'data-key':'browse-check'}, h('div', {className:'grow stack-sm'}, lines),
    h('div', {className:'row'}, fresh ? h('button', {type:'button', className:'btn primary sm', 'data-browse-act':'confirm', 'data-key':'browse-check-add', disabled:browseSites.saving}, 'Add ' + browseCount(fresh, 'site', 'sites')) : null,
      h('button', {type:'button', className:'btn ghost sm', 'data-browse-act':'cancel-check', 'data-key':'browse-check-cancel'}, fresh ? 'Cancel' : 'OK')));
}
function browseSitesCard() {
  const st = browseSites, doc = st.doc;
  if (!st.tried && !st.busy && typeof fetch === 'function') setTimeout(() => { if (!browseSites.tried) browseSitesLoad(); }, 0);
  const card = (...body) => h('section', {className:'card pad stack', 'data-key':'browse-sites', 'aria-labelledby':'browse-sites-title'}, ...body);
  const title = count => h('h2', {id:'browse-sites-title'}, 'Allowed sites', count == null ? null : h('span', {className:'muted', 'data-key':'browse-sites-count'}, ' · ' + browseCount(count, 'site', 'sites')));
  if (!doc && st.failed) return card(title(null), stateNote('The allowed sites did not load', 'The dashboard could not read them just now.', 'error',
    {label:'Try again', onClick:() => { browseSites.failed = false; browseSites.tried = false; render(); }}));
  if (!doc) return card(title(null), typeof skeletonFor === 'function' ? skeletonFor('section') : h('p', {className:'meta'}, 'Loading…'));
  const all = browseSiteRows(doc), query = st.query.trim().toLowerCase().replace(/^\*\./, '');
  const found = query ? all.filter(r => r.site.includes(query) || r.source.toLowerCase().includes(query)) : all;
  const shown = found.slice(0, BROWSE_SITE_ROWS), more = found.length - shown.length;
  const list = !all.length ? stateNote('No site is allowed yet', 'Add the sites your helpers and you may open. Nothing else opens.')
    : !found.length ? h('p', {className:'meta', role:'status', 'data-key':'browse-sites-none'}, 'No site matches “' + clean(st.query.trim()).slice(0, 60) + '”.')
    : h('div', {className:'stack-sm', role:'list', 'aria-label':'Allowed sites', 'data-key':'browse-sites-list'}, shown.map(r =>
      h('div', {className:'list-row', role:'listitem', 'data-key':'browse-site-' + r.scope + '-' + (r.ticket || '') + '-' + r.site},
        h('span', {className:'grow', title:r.site}, r.site), chip(r.source, r.scope === 'workspace' ? '' : 'info'),
        h('button', {type:'button', className:'btn ghost sm', 'data-browse-act':'remove', 'data-site':r.site, 'data-scope':r.scope, 'data-ticket':r.ticket || '',
          'aria-label':'Remove ' + r.site, disabled:st.saving}, 'Remove'))));
  return card(title(all.length),
    h('p', {className:'meta'}, 'Sites on this list may open for every ticket; a ticket can have extra sites of its own. A site covers every part of it: “*.20min.ch” is stored as 20min.ch. Only a person changes the list.'),
    doc.error ? h('p', {className:'meta bad', role:'alert', 'data-key':'browse-sites-damaged'}, clean(doc.error)) : null,
    h('label', {className:'field', 'data-key':'browse-sites-add'}, 'Add sites',
      h('textarea', {className:'input', rows:2, 'data-browse-field':'draft', 'data-key':'browse-sites-draft', autocomplete:'off', spellcheck:'false',
        placeholder:'20min.ch, sbb.ch … or paste a whole list', 'aria-describedby':'browse-sites-hint'}, st.draft),
      h('span', {className:'meta', id:'browse-sites-hint'}, 'One or many, separated by commas, spaces or lines. Web addresses are fine: only the site name is kept.')),
    h('div', {className:'row'}, h('button', {type:'button', className:'btn outline sm', 'data-browse-act':'add', 'data-key':'browse-sites-add-btn', disabled:st.saving, 'aria-busy':st.saving ? 'true' : null},
      st.saving ? h('span', {className:'spinner', 'aria-hidden':'true'}) : null, st.saving ? 'Saving…' : 'Add to the list')),
    st.check ? browseCheckNote(st.check) : null,
    st.error ? h('p', {className:'meta bad', role:'alert', 'data-key':'browse-sites-error'}, clean(st.error)) : null,
    st.said ? h('p', {className:'meta', role:'status', 'data-key':'browse-sites-said'}, clean(st.said)) : null,
    all.length >= BROWSE_SEARCH_FROM || st.query ? h('label', {className:'field', 'data-key':'browse-sites-search'}, 'Search the list',
      h('input', {className:'input', type:'search', 'data-browse-field':'query', 'data-key':'browse-sites-query', autocomplete:'off', placeholder:'Find a site', value:st.query})) : null,
    list,
    more > 0 ? h('p', {className:'meta', 'data-key':'browse-sites-more'}, 'And ' + browseCount(more, 'more site', 'more sites') + '. Search to find one.') : null);
}

// Your own browser (O-20): one field, one button. It opens only a site that is on the list; "Close" ends it.
async function browseOpenOwn() {
  const st = browseSites, sites = (st.doc?.workspace || []);
  const address = String(st.address || '').trim() || sites[0] || '';
  if (st.opening || !address) return;
  st.opening = true; st.openError = ''; render();
  let text = '', ok = false, status = 0;
  try {
    const r = await fetch('/api/browse/open', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({address})});
    text = await r.text(); ok = r.ok; status = r.status;
  } catch (e) { text = 'The dashboard could not be reached. Try again.'; }
  st.opening = false;
  if (!ok) st.openError = (status && window.DashHelpers?.answerText ? window.DashHelpers.answerText(status, text, 'The browser did not open. Try again.') : text).slice(0, 300) || 'The browser did not open. Try again.';
  else { st.address = ''; const box = document.querySelector('[data-browse-field="address"]'); if (box) box.value = ''; }
  render(); browseListLoad();
}
function browseOwnSection(own) {
  const st = browseSites, sites = (st.doc?.workspace || []), can = sites.length > 0;
  const form = h('div', {className:'stack-sm', 'data-key':'browse-own-form'},
    h('label', {className:'field'}, own ? 'Go to another allowed site' : 'Which site?',
      h('input', {className:'input', type:'text', inputmode:'url', autocomplete:'off', spellcheck:'false', list:'browse-own-sites', 'data-browse-field':'address', 'data-key':'browse-own-address',
        placeholder:can ? sites[0] : 'Add a site below first', value:st.address, disabled:!can || st.opening, 'aria-describedby':'browse-own-hint'})),
    h('datalist', {id:'browse-own-sites', 'data-key':'browse-own-sites'}, sites.slice(0, 200).map(s => h('option', {value:s}))),
    h('div', {className:'row'}, h('button', {type:'button', className:own ? 'btn outline sm' : 'btn primary', 'data-browse-act':'open', 'data-key':'browse-own-open', disabled:!can || st.opening, 'aria-busy':st.opening ? 'true' : null,
        'aria-describedby':'browse-own-hint'}, st.opening ? h('span', {className:'spinner', 'aria-hidden':'true'}) : null, st.opening ? 'Opening…' : own ? 'Go' : 'Open a browser'),
      h('span', {className:'meta', id:'browse-own-hint', 'data-key':'browse-own-hint'}, !st.doc ? '' : can ? (st.opening ? 'Starting can take up to a minute.' : 'Only the allowed sites open. It is private and closed when you close it.')
        : 'No site is allowed yet. Add one under Allowed sites first.')),
    st.openError ? h('p', {className:'meta bad', role:'alert', 'data-key':'browse-own-error'}, clean(st.openError)) : null);
  if (!own) return h('section', {className:'card pad stack', 'data-key':'browse-own', 'aria-labelledby':'browse-own-title'}, h('h2', {id:'browse-own-title'}, 'Your browser'), form);
  return h('section', {className:'stack', 'data-key':'browse-own', 'aria-labelledby':'browse-own-title'},
    h('div', {className:'row between'}, h('h2', {id:'browse-own-title'}, 'Your browser'),
      h('button', {type:'button', className:'btn outline sm', 'data-browse-act':'close', 'data-ticket':own.ticket, 'data-generation':own.generation || '', 'data-key':'browse-own-close'}, 'Close')),
    h('div', {'data-live-browse':own.ticket, 'data-own':'yes', 'data-key':'browse-own-view'}),
    h('div', {className:'card pad'}, form));
}
if (typeof document === 'object' && document.addEventListener) {
  document.addEventListener('click', event => {
    const b = event.target?.closest?.('[data-browse-act]');
    if (!b || b.disabled) return;
    const act = b.dataset.browseAct;
    if (act === 'add') return browseSitesAdd(false);
    if (act === 'confirm') return browseSitesAdd(true);
    if (act === 'cancel-check') { browseSites.check = null; return render(); }
    if (act === 'remove') return browseSitesRemove(b.dataset.site, b.dataset.scope, b.dataset.ticket || null);
    if (act === 'open') return browseOpenOwn();
    if (act === 'close') return liveBrowseStop(b.dataset.ticket, b.dataset.generation).then(() => browseListLoad());
  });
  document.addEventListener('input', event => {
    const f = event.target?.dataset?.browseField;
    if (!f) return;
    browseSites[f] = event.target.value;
    if (f === 'query') render();                       // the list narrows as you type
    else if (f === 'draft' && browseSites.check) { browseSites.check = null; render(); }  // the reading is of the old text
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Enter' && event.target?.dataset?.browseField === 'address') { event.preventDefault(); browseOpenOwn(); }
  });
}

function browserListPage(a) {
  const doc = browseList.doc, head = heading(addonTitle(a), a?.dashboard?.subtitle || '', {settings:typeof addonSettingsHref === 'function' ? addonSettingsHref(a?.name) : null});
  const page = (...body) => fragment(head, h('div', {className:'stack', 'data-browse-page':'', 'data-key':'browse-page'}, ...body));
  if (!doc && browseList.failed) return page(stateNote('The browsers did not load', 'The dashboard could not read them just now. It tries again on its own.', 'error',
    {label:'Try again', onClick:() => { browseList.failed = false; render(); browseListLoad(); }}));
  if (!doc) return page(typeof skeletonFor === 'function' ? skeletonFor('section') : null);
  if (!doc.on) return page(stateNote('The browser is turned off in this workspace', 'Turn it on again in Settings, under Add-ons.', 'error',
    {label:'Open add-ons', onClick:() => { location.hash = '#settings/addons'; }}));
  const own = doc.browsers.find(r => r.open && r.own) || null;
  const live = doc.browsers.filter(r => r.open && !r.own), ended = doc.browsers.filter(r => !r.open && !r.own && r.ended && browseToday(r.ended));
  const body = [browseOwnSection(own)];
  if (live.length) body.push(h('section', {className:'stack', 'data-key':'browse-live'}, h('h2', {}, 'Live now', h('span', {className:'muted'}, ' · ' + live.length)),
    live.map(r => h('section', {className:'stack', 'data-key':'browse-row-' + r.ticket},
      h('h3', {}, h('a', {href:'#ticket/' + encodeURIComponent(r.ticket)}, browseTitle(r))),
      browsePeekHost(r.ticket, 'list')))));
  if (ended.length) body.push(h('section', {className:'card pad stack', 'data-key':'browse-ended'}, h('h2', {}, 'Ended today', h('span', {className:'muted'}, ' · ' + ended.length)),
    h('div', {className:'stack'}, ended.map(r => h('p', {'data-key':'browse-ended-' + r.ticket},
      h('a', {href:'#ticket/' + encodeURIComponent(r.ticket)}, browseTitle(r)), h('span', {className:'meta'}, ' · ended at ' + browseClock(r.ended)))))));
  if (!live.length && !ended.length) body.push(h('p', {className:'meta', 'data-key':'browse-empty'}, 'No helper is using a browser right now. When one opens a web page for a ticket, you can watch it here.'));
  body.push(browseSitesCard());
  return page(body);
}

// Home: a helper that asks for a person in its browser (orch browse ask-person) is one line with one button. The
// empty host keeps the list read while Home shows, so a new question appears within 5 s.
function browseAskBanner() {
  if (!browseOn()) return null;
  const asks = (browseList.doc?.browsers || []).filter(r => r && r.open && r.asking);
  if (!asks.length) return h('div', {hidden:true, 'data-browse-asks':'', 'data-key':'browse-asks'});
  return h('div', {className:'stack', 'data-browse-asks':'', 'data-key':'browse-asks'}, asks.map(r =>
    h('div', {className:'banner attn', role:'status', 'data-key':'browse-ask-' + r.ticket},
      h('p', {className:'grow'}, h('strong', {}, 'The helper needs you in its browser.'), ' ' + clean(r.asking).slice(0, 200),
        h('span', {className:'meta'}, ' · ' + browseTitle(r))),
      h('a', {className:'btn outline sm', href:browseHref(r.ticket)}, 'Open the browser'))));
}

function liveBrowsePage(id) {
  return fragment(heading('The helper’s browser', ''), h('div', {className:'stack', 'data-key':'live-browse'},
    h('div', {'data-live-browse':id})));
}
if (typeof module === 'object' && module.exports) module.exports = {LIVE_BROWSE_BACKOFF, BROWSE_LIST_EVERY, BROWSE_RENEW_EVERY, liveBrowsePost, liveBrowseControl, liveBrowseLease, browseAskBanner, liveBrowseFor, liveBrowseView, liveBrowseOpen, liveBrowseFan, browsePeekSay, mountLiveBrowse, liveBrowses, browseList, browseOn, browseRow, browseViewIn, browsePeekHost, browserListPage, browseListLoad,
  browseSites, browseSiteRows, browseSitesCard, browseSitesAdd, browseSitesRemove, browseCheckNote, browseOwnSection, browseOpenOwn, browseSitesLoad, browseCount, BROWSE_SITE_ROWS};
