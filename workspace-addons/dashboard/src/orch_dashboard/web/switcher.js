'use strict';
// The workspace switcher: the workspace box at the top of the sidebar shows this workspace's badge; a click opens one
// menu with two parts (ORCH-1273, owner picked draft A on 21 Nov):
// - "On this computer": the workspaces orch knows on the computer this dashboard runs on (state.look.workspaces).
// - "Saved places": the person's own list of dashboards, relay and publish pages, kept in this browser (places.js).
//   This lifts the 8 Nov rule that a workspace in another network is never listed: the person adds it themselves.
// The menu shows one thing at a time: the list, or a step (Add place, the keep question for places that came in a
// link, Share my places) with a back arrow. Add place and a rename stay when the menu is closed and opened again, so
// typed text is not lost. Needs look.js (window.OrchLook.badge) and places.js (window.OrchPlaces); qr.js from the kit for the QR.
// No workspace or place string is put into markup: everything is built with createElement and textContent.
(() => {
  const box = document.querySelector('.workspace');
  if (!box) return;
  const P = window.OrchPlaces || null;
  let look = null, slot = null, menu = null, wired = false;
  // what the menu shows: the list, or one step; renaming and the "…" menu belong to the list
  const S = {step: null, form: null, renaming: null, renameText: null, rowMenu: null, arrived: []};
  const n = (tag, attrs = {}, ...kids) => {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (v == null || v === false) continue;
      if (k === 'className') node.className = v;
      else if (k.startsWith('on') && typeof v === 'function') node[k] = v;
      else if (k === 'value') node.value = v;
      else node.setAttribute(k, v === true ? '' : String(v));
    }
    node.append(...kids.flat().filter(x => x != null && x !== false));
    return node;
  };
  const ICONS = {
    chev: 'm7 15 5 5 5-5M7 9l5-5 5 5', back: 'm15 18-6-6 6-6', plus: 'M12 5v14M5 12h14',
    share: 'M4 12v7a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-7M16 6l-4-4-4 4M12 2v13',
    relay: 'M7 7h10M7 7l3-3M7 7l3 3M17 17H7M17 17l-3-3M17 17l-3 3',
    publish: 'M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-1.7 1.7M14 11a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7l1.7-1.7',
  };
  const icon = (name, size = 14, cls) => {
    const s = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    for (const [k, v] of [['viewBox', '0 0 24 24'], ['width', size], ['height', size], ['fill', 'none'], ['stroke', 'currentColor'], ['stroke-width', '2'],
      ['stroke-linecap', 'round'], ['stroke-linejoin', 'round'], ['aria-hidden', 'true']]) s.setAttribute(k, String(v));
    if (cls) s.setAttribute('class', cls);
    const p = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    p.setAttribute('d', ICONS[name]);
    s.append(p);
    return s;
  };
  const KIND = {workspace: 'Workspace', relay: 'Relay', publish: 'Publish'};
  const UI = () => window.UI || {};
  const toast = (text, undo) => (UI().toast ? UI().toast(text, undo) : null);
  const now = () => Date.now();
  const here = () => location.origin + location.pathname.replace(/\/+$/, '');

  // ---- the saved list in this browser
  const load = () => (P ? P.load(null, now()) : []);
  const save = list => { if (P) P.save(null, list, now()); return list; };
  // This dashboard itself, as a place: passed on in a link so the next dashboard can come back here.
  function self() {
    if (!P || !look || P.isLocal(here())) return null;
    const pid = typeof look.place_id === 'string' && /^ws_[0-9a-f]{24}$/.test(look.place_id) ? look.place_id : null;
    if (!pid) return null;
    return P.check({id: pid.slice(3), url: here(), kind: 'workspace', name: (window.OrchLook && window.OrchLook.name()) || '', color: look.color,
      icon: look.icon, wsid: pid, changed: now()});
  }
  const withSelf = list => { const me = self(); return me && !P.live(list).some(p => p.wsid === me.wsid || p.url === me.url) ? list.concat(me) : list; };
  const isHere = p => p.url === here() || !!(look && p.wsid && p.wsid === look.place_id);

  function ago(t) {
    const d = Math.max(0, now() - t), hour = 3600000, day = 24 * hour;
    if (d < hour) return 'last opened just now';
    if (d < day) return 'last opened today';
    if (d < 2 * day) return 'last opened yesterday';
    if (d < 14 * day) return 'last opened ' + Math.floor(d / day) + ' days ago';
    if (d < 60 * day) return 'last opened ' + Math.floor(d / (7 * day)) + ' weeks ago';
    return 'last opened ' + Math.floor(d / (30 * day)) + ' months ago';
  }
  const placeLine = p => {
    const state = P.isLocal(p.url) ? 'Only in this browser' : p.opened ? ago(p.opened) : 'Sign in once';
    return p.kind === 'workspace' ? state : KIND[p.kind] + ' · ' + state;
  };
  function placeBadge(p, size = 32) {
    if (p.kind === 'relay' || p.kind === 'publish') {
      const b = n('span', {className: 'wsb s' + size, 'data-c': p.color || (p.kind === 'relay' ? 'red' : 'blue'), role: 'img', 'aria-label': KIND[p.kind]});
      b.append(icon(p.kind, size > 26 ? 16 : 14));
      return b;
    }
    return window.OrchLook.badge({icon: p.icon || null, color: p.color || null}, p.name, size);
  }

  function wire() {
    if (wired) return;
    wired = true;
    const name = document.getElementById('workspace-name'), meta = box.querySelector('.meta');
    slot = n('span', {className: 'ws-badge-slot'});
    const text = n('span', {className: 'ws-text'});
    text.append(...[name, meta].filter(Boolean));
    box.classList.add('ws-switch');
    box.setAttribute('role', 'button');
    box.setAttribute('tabindex', '0');
    box.setAttribute('aria-haspopup', 'menu');
    box.setAttribute('aria-expanded', 'false');
    box.setAttribute('data-testid', 'ws-switch');
    box.replaceChildren(slot, text, icon('chev', 14, 'ws-chev'));
    box.addEventListener('click', toggle);
    box.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(); } else if (e.key === 'Escape') close(); });
  }

  function dropRowMenu() { document.querySelectorAll('.sw-row-menu').forEach(x => x.remove()); }
  function close() {
    dropRowMenu();
    S.rowMenu = null;
    if (S.step !== 'add') S.step = null;  // only typed text (Add place, a rename) waits for the next open
    if (menu) { menu.remove(); menu = null; }
    box.setAttribute('aria-expanded', 'false');
  }

  // One workspace on this computer (as before: the name on the full row width, one grey line under it).
  function item(w) {
    const L = window.OrchLook;
    // The row follows the gallery (.sw-item): the name gets the whole row width and wraps to a second line when long
    // (manager review 17 Nov: a cut name cannot tell two workspaces apart). Under it one grey line holds the state
    // ("Current", "Not running" or the type) and who waits ("1 needs you"); the right side only has the tick on the current one.
    const label = w.here && typeof L.name === 'function' && L.name() ? L.name() : w.name;
    const state = w.here ? 'Current' : !w.url ? 'Not running' : typeof w.type === 'string' && w.type.trim() ? w.type : null;
    const needs = Number.isInteger(w.needs) && w.needs > 0
      ? n('span', {className: 'sw-needs'}, w.needs + (w.needs === 1 ? ' needs you' : ' need you')) : null;
    const sub = state || needs ? n('span', {className: 'meta'}, state, state && needs ? ' · ' : null, needs) : null;
    const details = n('span', {className: 'grow sw-item-details'}, n('span', {className: 'ws-item-name'}, label), sub);
    const status = w.here ? n('span', {className: 'sw-item-status'}, n('span', {className: 'sw-tick', 'aria-hidden': 'true'}, '✓')) : null;
    // Running workspaces on this computer are links (switching = opening their dashboard); the current one and stopped ones are not.
    const attrs = {className: 'sw-item' + (w.here || w.url ? '' : ' off'), role: 'menuitem', 'data-testid': 'ws-item'};
    if (w.here) Object.assign(attrs, {'aria-current': 'true'});
    else if (w.url) attrs.href = w.url;
    else attrs['aria-disabled'] = 'true';
    const row = n(w.url && !w.here ? 'a' : 'div', attrs, L.badge(w, label, 32), details, status);
    if (!w.url || w.here) row.tabIndex = 0;
    row.onclick = () => { if (w.here) { close(); box.focus(); } };
    return row;
  }

  // One saved place: the place (a link: one click opens it; a dashboard gets the kept list after #) and "…".
  function placeRow(p) {
    if (S.renaming === p.id) return renameRow(p);
    const mark = P.isSecure(p.url) ? null : n('span', {className: 'badge attn'}, 'not secure');
    const details = n('span', {className: 'grow sw-item-details'},
      n('span', {className: 'sw-name'}, n('span', {className: 'ws-item-name'}, p.name), mark), n('span', {className: 'meta'}, placeLine(p)));
    const link = n('a', {className: 'sw-item', role: 'menuitem', href: p.url, title: p.url, 'data-testid': 'ws-place'}, placeBadge(p), details);
    link.onclick = e => {
      if (e.button || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;  // a new tab keeps the plain address
      e.preventDefault();
      const list = save(P.tidy(load().map(q => (q.id === p.id && !q.removed ? Object.assign({}, q, {opened: now(), changed: now()}) : q)), now()));
      location.href = P.openUrl(p, withSelf(list), now());
    };
    const more = n('button', {className: 'btn ghost icon sm sw-more', type: 'button', 'aria-label': 'More for ' + p.name, 'aria-haspopup': 'menu',
      'aria-expanded': String(S.rowMenu === p.id), 'data-more': p.id}, '⋯');
    more.onclick = e => { e.stopPropagation(); S.rowMenu = S.rowMenu === p.id ? null : p.id; draw(); };
    return n('div', {className: 'sw-row', 'data-place': p.id}, link, more);
  }

  // The "…" menu: never over another row. Desktop: beside the menu, level with its row. Phone: one line over its own row.
  function placeRowMenu() {
    dropRowMenu();
    const p = load().find(x => x.id === S.rowMenu && !x.removed);
    const btn = p && menu && menu.querySelector('[data-more="' + p.id + '"]');
    if (!btn) return;
    const phone = matchMedia('(max-width:720px)').matches;
    const rename = n('button', {className: 'menu-item', type: 'button', role: 'menuitem'}, 'Rename');
    rename.onclick = () => { S.rowMenu = null; S.renaming = p.id; S.renameText = null; draw(); };
    const remove = n('button', {className: 'menu-item', type: 'button', role: 'menuitem'}, 'Remove');
    remove.onclick = () => removePlace(p);
    const pop = n('div', {className: 'menu-pop sw-row-menu' + (phone ? ' line' : ''), role: 'menu', 'aria-label': 'More for ' + p.name}, rename, remove);
    pop.onkeydown = e => { if (e.key === 'Escape') { e.stopPropagation(); S.rowMenu = null; draw(); btn.focus(); } };
    document.body.append(pop);
    const line = btn.closest('.sw-row').getBoundingClientRect(), side = menu.getBoundingClientRect();
    const pw = pop.offsetWidth, ph = pop.offsetHeight;
    pop.style.left = (phone ? Math.max(8, btn.getBoundingClientRect().left - pw - 4) : Math.min(side.right + 4, innerWidth - pw - 8)) + 'px';
    pop.style.top = Math.max(8, Math.min(line.top + (line.height - ph) / 2, innerHeight - ph - 8)) + 'px';
    rename.focus({preventScroll: true});
  }

  function removePlace(p) {
    save(P.remove(load(), p.id, now()));
    S.rowMenu = null;
    draw();
    const box2 = toast('Removed ' + p.name, () => { save(P.restore(load(), p, now())); draw(); });
    if (box2) box2.querySelector('.btn.ghost')?.remove();  // Undo only; the toast hides by itself
  }

  function renameRow(p) {
    const input = n('input', {className: 'input', value: S.renameText ?? p.name, maxlength: P.NAME_MAX, 'aria-label': 'Name of ' + p.name});
    input.oninput = () => { S.renameText = input.value; };
    const cancel = n('button', {className: 'btn ghost sm', type: 'button'}, 'Cancel');
    cancel.onclick = () => { S.renaming = null; S.renameText = null; draw(); };
    const form = n('form', {className: 'sw-row sw-rename'}, placeBadge(p), input, n('button', {className: 'btn primary sm', type: 'submit'}, 'Save'), cancel);
    form.onsubmit = e => {
      e.preventDefault();
      if (input.value.trim()) save(P.rename(load(), p.id, input.value, now()));
      S.renaming = null; S.renameText = null; draw();
    };
    setTimeout(() => input.focus(), 0);
    return form;
  }

  // Add place: address, kind, optional name. A bad address is refused in plain words (places.js).
  function hintFor(text) {
    const a = text.trim() ? P.address(text) : null;
    if (!a || !a.ok) return '';
    if (P.isLocal(a.url)) return 'Works only on this computer. It stays in this browser.';
    if (!P.isSecure(a.url)) return 'This address is not secure (http).';
    return '';
  }
  function addForm() {
    const f = S.form;
    const hint = n('p', {className: 'meta sw-hint', id: 'sw-add-hint'}, hintFor(f.address));
    const error = n('p', {className: 'sw-error', id: 'sw-add-error', role: 'alert'}, f.error || '');
    const address = n('input', {className: 'input', id: 'sw-add-address', value: f.address, placeholder: 'https://', autocomplete: 'off', inputmode: 'url',
      autocapitalize: 'off', spellcheck: 'false', 'aria-describedby': 'sw-add-error sw-add-hint', 'aria-invalid': f.error ? 'true' : null});
    address.oninput = () => { f.address = address.value; f.error = ''; error.textContent = ''; address.removeAttribute('aria-invalid'); hint.textContent = hintFor(f.address); };
    const name = n('input', {className: 'input', id: 'sw-add-name', value: f.name, maxlength: P.NAME_MAX, autocomplete: 'off'});
    name.oninput = () => { f.name = name.value; };
    const kinds = n('div', {className: 'segmented', role: 'radiogroup', 'aria-label': 'Kind'}, P.KINDS.map(k => {
      const radio = n('input', {className: 'sr-only', type: 'radio', name: 'sw-add-kind', value: k, checked: f.kind === k});
      radio.onchange = () => { f.kind = k; };
      return n('label', {}, radio, KIND[k]);
    }));
    const cancel = n('button', {className: 'btn ghost', type: 'button'}, 'Cancel');
    cancel.onclick = () => { S.form = null; S.step = null; draw(); };
    const form = n('form', {className: 'sw-form', 'aria-label': 'Add place', novalidate: true},
      n('label', {className: 'field', for: 'sw-add-address'}, 'Address', address), error, hint,
      n('div', {className: 'field'}, n('span', {}, 'Kind'), kinds),
      n('label', {className: 'field', for: 'sw-add-name'}, 'Name (optional)', name),
      n('div', {className: 'row sw-form-actions'}, n('button', {className: 'btn primary', type: 'submit'}, 'Save'), cancel));
    form.onsubmit = e => {
      e.preventDefault();
      const r = P.add(load(), {url: f.address, kind: f.kind, name: f.name}, now());
      if (!r.ok) { f.error = r.why; draw(); return; }
      save(r.list);
      S.form = null; S.step = null;
      draw();
      toast('Saved ' + r.place.name);
    };
    setTimeout(() => address.focus(), 0);
    return form;
  }

  // "New places from a link: keep?": nothing is saved without a tap; every address is shown in full.
  function keepPending() {
    if (!S.arrived.length) { P.clearIncoming(); return; }
    try { sessionStorage.setItem(P.INCOMING, P.pack(S.arrived, now())); } catch (_) { /* only this view */ }
  }
  function keepStep() {
    const keep = list => { save(P.keep(load(), list, now())); S.arrived = S.arrived.filter(p => !list.includes(p)); keepPending(); };
    const rows = S.arrived.map(p => {
      const yes = n('button', {className: 'btn outline sm', type: 'button', 'aria-label': 'Keep ' + p.name}, 'Keep');
      yes.onclick = () => { keep([p]); draw(); toast('Kept ' + p.name); };
      const no = n('button', {className: 'btn ghost sm', type: 'button', 'aria-label': 'Not now for ' + p.name}, 'Not now');
      no.onclick = () => { S.arrived = S.arrived.filter(q => q !== p); keepPending(); draw(); };
      return n('div', {className: 'sw-keep-row'}, placeBadge(p),
        n('span', {className: 'sw-keep-text'}, n('span', {className: 'ws-item-name'}, p.name), n('span', {className: 'meta sw-address'}, p.url)),
        n('span', {className: 'row sw-keep-actions'}, yes, no));
    });
    let all = null;
    if (S.arrived.length > 1) {
      const yes = n('button', {className: 'btn primary sm', type: 'button'}, 'Keep all');
      yes.onclick = () => { const count = S.arrived.length; keep([...S.arrived]); draw(); toast('Kept ' + count + ' places'); };
      const no = n('button', {className: 'btn ghost sm', type: 'button'}, 'Not now');
      no.onclick = () => { S.arrived = []; keepPending(); draw(); };
      all = n('div', {className: 'row sw-keep-all'}, yes, no);
    }
    return n('section', {className: 'sw-keep', 'aria-label': 'New places from a link'}, rows, all, n('p', {className: 'meta'}, 'Only places you keep are saved here.'));
  }

  // Share my places: a link (and its QR code) that opens this dashboard with the kept places; local ones stay here.
  function shareStep() {
    const list = load(), url = P.shareUrl(here(), withSelf(list), now());
    const locals = P.live(list).filter(p => P.isLocal(p.url)).map(p => p.name);
    const field = n('input', {className: 'input', readonly: true, value: url, 'aria-label': 'Link to your places'});
    field.onfocus = () => field.select();
    const copy = n('button', {className: 'btn primary', type: 'button'}, 'Copy');
    copy.onclick = () => { if (UI().copy) UI().copy(url); };
    const picture = window.OrchQR ? window.OrchQR.svg(url, {label: 'QR code with the link to your places'}) : null;
    return n('div', {className: 'sw-share'},
      n('p', {className: 'muted'}, 'Open this link on a new phone or in another browser. It asks there which places to keep.'),
      n('div', {className: 'sw-share-link'}, field, copy),
      picture || n('p', {className: 'meta'}, 'Too many places for a QR code. Copy the link instead.'),
      n('p', {className: 'meta'}, 'Anyone with this link sees these addresses.'),
      n('p', {className: 'meta'}, 'Addresses that only work on this computer are not included' + (locals.length ? ' (' + locals.join(', ') + ').' : '.')));
  }

  function draw() {
    if (!menu) return;
    dropRowMenu();
    const back = title => {
      const b = n('button', {className: 'btn ghost icon sm', type: 'button', 'aria-label': 'Back to all places'}, icon('back', 16));
      b.onclick = () => { S.step = null; S.form = null; draw(); if (menu) menu.querySelector('[role=menuitem]')?.focus(); };
      return n('div', {className: 'sw-head'}, b, n('strong', {}, title));
    };
    if (S.step === 'keep' && !S.arrived.length) S.step = null;
    let kids;
    if (P && S.step === 'add') kids = [back('Add place'), addForm()];
    else if (P && S.step === 'share') kids = [back('Share my places'), shareStep()];
    else if (P && S.step === 'keep') kids = [back('New places from a link: keep?'), keepStep()];
    else {
      const local = (look.workspaces || []).filter(w => w.here || !w.url || /^http:\/\/(127\.0\.0\.1|localhost)[:/]/.test(w.url))
        .sort((a, b) => (Number(!!b.here) - Number(!!a.here)) || a.name.localeCompare(b.name));
      const saved = P ? P.live(load()).filter(p => !isHere(p)) : [];
      let banner = null;
      if (S.arrived.length) {
        const review = n('button', {className: 'btn outline sm', type: 'button'}, 'Review');
        review.onclick = () => { S.step = 'keep'; S.rowMenu = null; draw(); };
        banner = n('div', {className: 'banner attn sw-arrived', role: 'status'},
          n('span', {className: 'grow'}, S.arrived.length === 1 ? '1 new place from a link' : S.arrived.length + ' new places from a link'), review);
      }
      const openAdd = () => { S.form = S.form || {address: '', kind: 'workspace', name: '', error: ''}; S.step = 'add'; S.rowMenu = null; draw(); };
      kids = [banner, n('p', {className: 'eyebrow'}, 'On this computer'), local.map(item),
        local.length === 0 ? n('p', {className: 'meta sw-hint'}, 'No local workspaces available.') : null];
      if (P) {
        kids.push(n('p', {className: 'eyebrow'}, 'Saved places'));
        if (saved.length) {
          const add = n('button', {className: 'btn ghost sm', type: 'button', onclick: openAdd, 'data-testid': 'ws-add'}, icon('plus'), 'Add place');
          const share = n('button', {className: 'btn ghost sm', type: 'button', 'data-testid': 'ws-share'}, icon('share'), 'Share my places');
          share.onclick = () => { S.step = 'share'; S.rowMenu = null; draw(); };
          kids.push(saved.map(placeRow), n('hr', {className: 'sw-rule'}), n('div', {className: 'sw-foot'}, add, saved.some(p => !P.isLocal(p.url)) ? share : null));
        } else {
          kids.push(n('div', {className: 'sw-empty'}, n('p', {className: 'meta'}, 'Nothing saved yet. Add a place to switch to it from here.'),
            n('button', {className: 'btn outline sm', type: 'button', onclick: openAdd, 'data-testid': 'ws-add'}, icon('plus'), 'Add place')));
        }
      }
    }
    menu.replaceChildren(...kids.flat().filter(Boolean));
    menu.style.top = box.offsetTop + box.offsetHeight + 4 + 'px';
    if (S.rowMenu) placeRowMenu();
  }

  function toggle() {
    if (!look) return;
    if (menu) { close(); return; }
    menu = n('div', {className: 'sw-menu sw-places', role: 'menu', 'aria-label': 'Workspaces and saved places', 'data-testid': 'ws-menu'});
    box.insertAdjacentElement('afterend', menu);
    box.setAttribute('aria-expanded', 'true');
    draw();
    if (!S.step && !S.renaming) menu.querySelector('[role=menuitem]')?.focus();
    menu.onkeydown = e => {
      if (e.target.matches('input')) return;
      const rows = [...menu.querySelectorAll('[role=menuitem]')];
      const index = rows.indexOf(document.activeElement);
      const next = {ArrowDown: (index + 1) % rows.length, ArrowUp: (index - 1 + rows.length) % rows.length, Home: 0, End: rows.length - 1};
      if (e.key in next && rows.length) { e.preventDefault(); rows[next[e.key]]?.focus(); }
      if (e.key === 'Tab' && !S.step && !S.renaming) close();
    };
  }

  document.addEventListener('click', e => {
    const t = e.target, pop = document.querySelector('.sw-row-menu');
    if (t && t.isConnected === false) return;  // a button in the menu that the click itself redrew (a step opened) is not outside
    const inside = sel => !!(t && t.closest && t.closest(sel));
    if (pop && !pop.contains(t) && !inside('.sw-more')) { S.rowMenu = null; pop.remove(); }
    if (menu && !menu.contains(t) && !box.contains(t) && !(pop && pop.contains(t)) && !inside('.ui-toasts')) close();
  });
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && menu) { close(); box.focus(); } });

  // After sign-in (the first state): this page describes itself to its own saved row, and what came in a link
  // becomes the keep question (removals and name changes of kept places apply at once).
  function arrive() {
    if (!P || !look) return;
    const list = P.describe(load(), here(), {wsid: look.place_id, name: window.OrchLook && window.OrchLook.name(), color: look.color, icon: look.icon}, now());
    const got = P.arrive(list, P.incoming(null, now()), now());
    save(got.list);
    const me = self();
    S.arrived = got.fresh.filter(p => !isHere(p) && !(me && p.wsid === me.wsid));
    keepPending();
    if (menu) draw();
  }

  function paint() {
    if (!look || !window.OrchLook) { if (menu) close(); return; }
    wire();
    slot.replaceChildren(window.OrchLook.badge(look, window.OrchLook.name(), 32));
    if (menu && !(look.workspaces || []).some(w => w.here)) close();
  }

  let first = true;
  window.addEventListener('orch:state', e => {
    look = e.detail && e.detail.look ? e.detail.look : null;
    paint();
    if (look && first) { first = false; arrive(); }
  });
  window.addEventListener('orch:look-saved', paint);
  window.addEventListener('orch:places-arrived', () => { if (!first) arrive(); });
})();
