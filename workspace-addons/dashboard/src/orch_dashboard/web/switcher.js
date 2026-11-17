'use strict';
// The workspace switcher: the workspace box at the top of the sidebar shows this workspace's badge; a click lists the
// workspaces orch knows on this computer (state.look.workspaces) and opens another one in this tab.
// Needs look.js (window.OrchLook.badge). No workspace string is put into markup.
(() => {
  const box = document.querySelector('.workspace');
  if (!box) return;
  let look = null, slot = null, menu = null, wired = false;
  const n = (tag, attrs = {}, ...kids) => {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (v == null || v === false) continue;
      if (k === 'className') node.className = v; else node.setAttribute(k, v === true ? '' : String(v));
    }
    node.append(...kids.flat().filter(x => x != null && x !== false));
    return node;
  };
  const chevron = () => {
    const s = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    for (const [k, v] of [['viewBox', '0 0 24 24'], ['width', '14'], ['height', '14'], ['fill', 'none'], ['stroke', 'currentColor'], ['stroke-width', '2'], ['aria-hidden', 'true'], ['class', 'ws-chev']]) s.setAttribute(k, v);
    const p = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    p.setAttribute('d', 'm7 15 5 5 5-5M7 9l5-5 5 5');
    s.append(p);
    return s;
  };

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
    box.replaceChildren(slot, text, chevron());
    box.addEventListener('click', toggle);
    box.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(); } else if (e.key === 'Escape') close(); });
  }

  function close() {
    if (menu) { menu.remove(); menu = null; }
    box.setAttribute('aria-expanded', 'false');
  }

  function item(w) {
    const L = window.OrchLook;
    // The row follows the gallery (.sw-item): the name gets the whole row width and wraps to a second line when long
    // (manager review 17 Nov: a cut name cannot tell two workspaces apart). Under it one grey line holds the state
    // ("Current", "Not running" or the type) and who waits ("1 needs you"); the right side only has the tick on the current one.
    // The current row shows the same name as the box above it (the display name), not the folder name.
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

  function toggle() {
    if (!look) return;
    if (menu) { close(); return; }
    // Only workspaces on this computer (owner 8 Nov): a workspace in another network is never listed.
    const list = (look.workspaces || []).filter(w => w.here || !w.url || /^http:\/\/(127\.0\.0\.1|localhost)[:/]/.test(w.url)).sort((a, b) => (Number(!!b.here) - Number(!!a.here)) || a.name.localeCompare(b.name));
    menu = n('div', {className: 'sw-menu', role: 'menu', 'aria-label': 'Workspaces on this computer', 'data-testid': 'ws-menu'},
      n('p', {className: 'eyebrow'}, 'On this computer'), list.map(item),
      list.length === 0 ? n('p', {className: 'meta sw-hint'}, 'No local workspaces available.') : null);
    box.insertAdjacentElement('afterend', menu);
    menu.style.top = box.offsetTop + box.offsetHeight + 4 + 'px';
    box.setAttribute('aria-expanded', 'true');
    menu.querySelector('[role=menuitem]')?.focus();
    menu.onkeydown = e => {
      const rows = [...menu.querySelectorAll('[role=menuitem]')];
      const index = rows.indexOf(document.activeElement);
      const next = {ArrowDown: (index + 1) % rows.length, ArrowUp: (index - 1 + rows.length) % rows.length, Home: 0, End: rows.length - 1};
      if (e.key in next) { e.preventDefault(); rows[next[e.key]]?.focus(); }
      if (e.key === 'Tab') close();
    };
  }

  document.addEventListener('click', e => { if (menu && !menu.contains(e.target) && !box.contains(e.target)) close(); });
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && menu) { close(); box.focus(); } });

  function paint() {
    if (!look || !window.OrchLook) { if (menu) close(); return; }
    wire();
    const me = (look.workspaces || []).find(w => w.here);
    slot.replaceChildren(window.OrchLook.badge(look, window.OrchLook.name(), 32));
    if (menu && !me) close();
    void me;
  }

  window.addEventListener('orch:state', e => { look = e.detail && e.detail.look ? e.detail.look : null; paint(); });
  window.addEventListener('orch:look-saved', paint);
})();
