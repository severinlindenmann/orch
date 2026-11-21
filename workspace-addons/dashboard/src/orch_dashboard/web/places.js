'use strict';
// Saved places (ORCH-1273, owner picked option A on ORCH-1036): the person's own list of dashboards, relay and publish
// pages, kept in this browser (localStorage of this address). Pure logic, no page markup: switcher.js draws it.
// - Each place has its own id and a time of last change; a removed place is kept as a removed mark for 90 days so it
//   does not come back from another dashboard's list.
// - The same workspace under two addresses is one row (joined by its workspace id); the address that last worked wins,
//   but an https address is never replaced by its http copy.
// - Local addresses (127.0.0.1, localhost) stay in this browser: they are never put into a link, because on another
//   device they mean that device.
// - Places that arrive in a link are never added by themselves: they come back as "new" for the keep question, and
//   only places the person kept are passed on. A link can never change the address of a place already saved.
// - Checks on everything that arrives: only http/https addresses, no sign-in data in the address, names up to 40
//   characters, colours from the badge palette, at most 50 places.
(() => {
  const KEY = 'orch.places.v1';
  const MAX = 50, NAME_MAX = 40, URL_MAX = 300, LINK_MAX = 8000;
  const KEEP_REMOVED = 90 * 24 * 3600 * 1000;
  const KINDS = ['workspace', 'relay', 'publish'];
  const COLORS = ['teal', 'green', 'lime', 'amber', 'orange', 'red', 'pink', 'violet', 'indigo', 'blue', 'cyan', 'slate'];
  const ID = /^[a-z0-9]{8,32}$/, WSID = /^[A-Za-z0-9_-]{4,64}$/, ICON = /^[a-z0-9-]{1,32}$/;

  const num = v => (Number.isFinite(v) && v >= 0 ? Math.floor(v) : 0);
  const cleanName = s => String(s == null ? '' : s).replace(/[\u0000-\u001f\u007f-\u009f​-‏‪-‮⁦-⁩]/g, '').replace(/\s+/g, ' ').trim().slice(0, NAME_MAX);

  // An address the person pasted or that arrived in a link: { ok: true, url } with the address in one form
  // (scheme, host, port, path; no query, no #part), or { ok: false, why } in plain words.
  function address(raw) {
    let s = String(raw == null ? '' : raw).trim();
    if (!s) return {ok: false, why: 'Paste the address of the page.'};
    if (s.length > URL_MAX) return {ok: false, why: 'This address is too long.'};
    if (!/^[a-z][a-z0-9+.-]*:/i.test(s)) s = (/^(127\.|localhost\b|\[::1\])/i.test(s) ? 'http://' : 'https://') + s;
    let u;
    try { u = new URL(s); } catch (_) { return {ok: false, why: 'This is not a web address.'}; }
    if (u.protocol !== 'https:' && u.protocol !== 'http:') return {ok: false, why: 'Only web addresses (https:// or http://) can be saved.'};
    if (u.username || u.password) return {ok: false, why: 'Remove the name and password from the address.'};
    if (!u.hostname) return {ok: false, why: 'This is not a web address.'};
    const path = u.pathname.replace(/\/+$/, '');
    return {ok: true, url: u.protocol + '//' + u.host + path};
  }
  const hostOf = url => { try { return new URL(url).hostname.toLowerCase(); } catch (_) { return ''; } };
  function isLocal(url) {
    const h = hostOf(url);
    return h === 'localhost' || h.endsWith('.localhost') || /^127\.\d+\.\d+\.\d+$/.test(h) || h === '[::1]' || h === '::1';
  }
  const isSecure = url => /^https:/i.test(url) || isLocal(url);

  // One place in its checked form, or null when something does not fit. A removed mark keeps only id, url and times.
  function check(p) {
    if (!p || typeof p !== 'object' || !ID.test(String(p.id || ''))) return null;
    const a = address(p.url);
    if (!a.ok) return null;
    const out = {id: p.id, url: a.url, changed: num(p.changed)};
    if (num(p.removed)) { out.removed = num(p.removed); return out; }
    out.kind = KINDS.includes(p.kind) ? p.kind : 'workspace';
    out.name = cleanName(p.name) || hostOf(a.url);
    if (COLORS.includes(p.color)) out.color = p.color;
    if (typeof p.icon === 'string' && ICON.test(p.icon)) out.icon = p.icon;
    if (typeof p.wsid === 'string' && WSID.test(p.wsid)) out.wsid = p.wsid;
    if (num(p.opened)) out.opened = num(p.opened);
    if (p.signed === true) out.signed = true;
    return out;
  }
  const live = list => list.filter(p => !p.removed);

  function newId(rand) {
    const c = typeof crypto !== 'undefined' && crypto.getRandomValues ? crypto : null;
    const r = typeof rand === 'function' ? rand : c ? () => c.getRandomValues(new Uint32Array(1))[0] / 4294967296 : Math.random;
    let s = '';
    while (s.length < 12) s += Math.floor(r() * 36).toString(36);
    return s.slice(0, 12);
  }

  // Tidy a list: checked places only, removed marks older than 90 days dropped, one row per id (latest change wins,
  // a removed mark wins on a tie), one row per workspace id and per address, at most 50 live places.
  function tidy(list, now) {
    const byId = new Map();
    for (const raw of Array.isArray(list) ? list : []) {
      const p = check(raw);
      if (!p) continue;
      if (p.removed && now - p.removed > KEEP_REMOVED) continue;
      const old = byId.get(p.id);
      if (!old || p.changed > old.changed || (p.changed === old.changed && p.removed && !old.removed)) byId.set(p.id, p);
    }
    const out = [...byId.values()];
    const keepers = new Map();
    const better = (a, b) => {  // the row to keep when a and b are the same place
      if (isSecure(a.url) !== isSecure(b.url)) return isSecure(a.url) ? a : b;
      return (a.opened || 0) !== (b.opened || 0) ? ((a.opened || 0) > (b.opened || 0) ? a : b) : (a.changed >= b.changed ? a : b);
    };
    for (const p of live(out)) {
      for (const k of [p.wsid && 'w:' + p.wsid, 'u:' + p.url].filter(Boolean)) {
        const other = keepers.get(k);
        if (other && other !== p) { const win = better(other, p); const lose = win === p ? other : p; lose.dupe = true; keepers.set(k, win); }
        else keepers.set(k, p);
      }
    }
    const result = out.filter(p => !p.dupe);
    let count = 0;
    return result.sort((a, b) => b.changed - a.changed).filter(p => p.removed || ++count <= MAX)
      .sort((a, b) => (Number(!!a.removed) - Number(!!b.removed)) || (a.removed ? a.id.localeCompare(b.id) : a.name.localeCompare(b.name)));
  }

  // Add a place the person typed: { ok, list, place } or { ok: false, why }.
  function add(list, input, now, rand) {
    const a = address(input && input.url);
    if (!a.ok) return a;
    const cur = tidy(list, now);
    const same = live(cur).find(p => p.url === a.url);
    if (same) return {ok: false, why: 'This place is already saved as "' + same.name + '".', place: same};
    if (live(cur).length >= MAX) return {ok: false, why: 'You can keep up to ' + MAX + ' places. Remove one first.'};
    const place = check({id: newId(rand), url: a.url, kind: input.kind, name: input.name, changed: now});
    return {ok: true, list: tidy(cur.concat(place), now), place};
  }
  function change(list, id, fields, now) {
    return tidy(tidy(list, now).map(p => (p.id === id && !p.removed ? Object.assign({}, p, fields, {changed: now}) : p)), now);
  }
  const rename = (list, id, name, now) => change(list, id, {name: cleanName(name)}, now);
  const remove = (list, id, now) => tidy(tidy(list, now).map(p => (p.id === id ? {id: p.id, url: p.url, changed: now, removed: now} : p)), now);
  // Undo of a remove: the place comes back as a new change.
  const restore = (list, place, now) => tidy(tidy(list, now).filter(p => p.id !== place.id).concat(Object.assign({}, place, {changed: now, removed: 0})), now);

  // What this page says about itself (its own workspace id, name, colour, icon) updates the saved row of this address
  // or of this workspace: this is the only way a place's name and colour change apart from the person renaming it.
  function describe(list, url, self, now) {
    const a = address(url);
    if (!a.ok || !self) return tidy(list, now);
    const wsid = typeof self.wsid === 'string' && WSID.test(self.wsid) ? self.wsid : null;
    return tidy(tidy(list, now).map(p => {
      if (p.removed || (p.url !== a.url && !(wsid && p.wsid === wsid))) return p;
      const q = Object.assign({}, p, {opened: now, signed: true, changed: now});
      if (wsid) q.wsid = wsid;
      if (p.url !== a.url && (isSecure(a.url) || !isSecure(p.url))) q.url = a.url;  // the address that last worked
      const name = cleanName(self.name);
      if (name) q.name = name;
      if (COLORS.includes(self.color)) q.color = self.color;
      if (typeof self.icon === 'string' && ICON.test(self.icon)) q.icon = self.icon; else delete q.icon;
      return q;
    }), now);
  }

  // ---- the list inside a link (the part after #, which never reaches a server)
  const b64 = s => (typeof btoa === 'function' ? btoa(unescape(encodeURIComponent(s))) : Buffer.from(s, 'utf8').toString('base64')).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  const unb64 = s => { const t = s.replace(/-/g, '+').replace(/_/g, '/'); return typeof atob === 'function' ? decodeURIComponent(escape(atob(t))) : Buffer.from(t, 'base64').toString('utf8'); };

  // The places to pass on: kept, not local, plus removed marks so a removal reaches the other dashboards.
  function pack(list, now) {
    const out = tidy(list, now).filter(p => !isLocal(p.url)).map(p => (p.removed
      ? {id: p.id, url: p.url, changed: p.changed, removed: p.removed}
      : {id: p.id, url: p.url, kind: p.kind, name: p.name, color: p.color, icon: p.icon, wsid: p.wsid, changed: p.changed}));
    return out.length ? b64(JSON.stringify(out)) : '';
  }
  // Read a list from a link: checked places only, never more than 50, nothing local. [] when it does not fit.
  function unpack(text, now) {
    if (typeof text !== 'string' || !text || text.length > LINK_MAX || !/^[A-Za-z0-9_-]+$/.test(text)) return [];
    let data;
    try { data = JSON.parse(unb64(text)); } catch (_) { return []; }
    if (!Array.isArray(data)) return [];
    return data.slice(0, MAX * 2).map(check).filter(p => p && !isLocal(p.url) && (!p.removed || now - p.removed <= KEEP_REMOVED));
  }
  // Split what arrived: removed marks newer than our copy apply at once (removing works everywhere); updates of a place
  // we keep may change its name and colour but never its address; anything new waits for the keep question.
  function arrive(list, incoming, now) {
    const cur = tidy(list, now), byId = new Map(cur.map(p => [p.id, p]));
    const fresh = [];
    let next = cur;
    for (const p of incoming) {
      const old = byId.get(p.id);
      if (!old) { if (!p.removed && !live(cur).some(q => q.url === p.url || (p.wsid && q.wsid === p.wsid))) fresh.push(p); continue; }
      if (p.changed <= old.changed) continue;
      if (p.removed) next = next.map(q => (q.id === p.id ? {id: q.id, url: q.url, changed: p.changed, removed: p.removed} : q));
      else if (!old.removed && p.url === old.url) next = next.map(q => (q.id === p.id ? Object.assign({}, q, {name: p.name, color: p.color, icon: p.icon, changed: p.changed}) : q));
    }
    return {list: tidy(next, now), fresh: fresh.slice(0, MAX)};
  }
  const keep = (list, places, now) => tidy(tidy(list, now).concat(places.map(p => Object.assign({}, p, {changed: Math.max(p.changed, now)}))), now);

  // Take the list out of the address bar (#…&places=… or #places=…) so it does not stay in history or copied links.
  // Returns { hash, packed }: the hash without it and the packed list ('' when none).
  function takeFromHash(hash) {
    const h = String(hash || '');
    const m = /([#&?])places=([A-Za-z0-9_-]*)/.exec(h);
    if (!m) return {hash: h, packed: ''};
    let rest = h.slice(0, m.index) + (m[1] === '#' ? '#' : '') + h.slice(m.index + m[0].length);
    rest = rest.replace(/^#&/, '#').replace(/[?&]$/, '').replace(/\?&/, '?');
    return {hash: rest === '#' ? '' : rest, packed: m[2]};
  }
  // The address to open a place with: a dashboard place gets the kept list after #; relay and publish never do.
  function openUrl(place, list, now) {
    if (place.kind !== 'workspace') return place.url;
    const packed = pack(list, now);
    return packed ? place.url + '/#home&places=' + packed : place.url;
  }
  const shareUrl = (here, list, now) => { const packed = pack(list, now); return packed ? here.replace(/\/+$/, '') + '/#home&places=' + packed : ''; };

  // ---- this browser's storage (it can be missing or refuse: then the list is just empty)
  function load(store, now) {
    try { return tidy(JSON.parse((store || localStorage).getItem(KEY) || '[]'), now); } catch (_) { return []; }
  }
  function save(store, list, now) {
    try { (store || localStorage).setItem(KEY, JSON.stringify(tidy(list, now))); return true; } catch (_) { return false; }
  }

  // ---- arrival: the list is taken out of the address bar at once (before the router reads it) and kept for this
  // tab (sessionStorage), so it survives the sign-in step; the keep question reads it after sign-in.
  const INCOMING = 'orch.places.incoming';
  function stash(win, now) {
    const loc = win.location, got = takeFromHash(loc.hash);
    if (!got.packed) return false;
    try { win.history.replaceState(null, '', loc.pathname + loc.search + got.hash); } catch (_) { /* the list just stays */ }
    try {
      const store = win.sessionStorage, before = unpack(store.getItem(INCOMING) || '', now);
      const all = before.concat(unpack(got.packed, now));
      store.setItem(INCOMING, all.length ? b64(JSON.stringify(all.slice(-MAX))) : '');
    } catch (_) { return false; }
    return true;
  }
  // What arrived in this tab and is not handled yet ([] when nothing); clear() after the keep question.
  const incoming = (store, now) => { try { return unpack((store || sessionStorage).getItem(INCOMING) || '', now); } catch (_) { return []; } };
  const clearIncoming = store => { try { (store || sessionStorage).removeItem(INCOMING); } catch (_) { /* nothing kept */ } };

  const api = {KEY, INCOMING, MAX, NAME_MAX, KINDS, COLORS, address, isLocal, isSecure, check, tidy, live, add, rename, remove,
    restore, describe, pack, unpack, arrive, keep, takeFromHash, openUrl, shareUrl, load, save, newId, stash, incoming, clearIncoming};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (typeof window !== 'undefined' && window.location) {
    window.OrchPlaces = api;
    // This listener is added before the app's (places.js loads before app.js): a pasted share link in an open tab is
    // cleaned before the router sees it.
    const take = () => { if (stash(window, Date.now())) window.dispatchEvent(new Event('orch:places-arrived')); };
    take();
    window.addEventListener('hashchange', take);
  }
})();
