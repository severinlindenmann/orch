'use strict';
// Soft page changes (ORCH-336), wherever the live page runs (liveFocusOn, pages/live.js). The dashboard already
// draws every page from its #address without loading the document again; it also:
// - keeps what sits in the keep place (<div id="keep"> in index.html, right after <main> in .shell-body, outside it) across every page change:
//   nothing here or in render() redraws it, and a page change does not close a dialog that sits in it. The bar and
//   the layer of the new live page mount there (window.orchKeep.mount(node)),
// - turns a click on a link to this same dashboard page that the browser would load again ("/", "/index.html#...")
//   into an address change, so the keep place stays. New tab, download and modifier clicks stay the browser's,
// - takes Back and Forward to the place on the page where the person was,
// - says every page change once (window event 'orch:page', detail {from, to, kind}),
// - moves the keyboard place to the new page's heading and says its title in a polite status line (arrive),
// - falls back to a normal load once when a page cannot be drawn softly.
// Off, the dashboard behaves exactly as before. Pure helpers take their inputs, so tests run them without a browser.
const SoftNav = (() => {
  const on = () => typeof liveFocusOn === 'function' && liveFocusOn();
  const keepEl = (doc = document) => doc.getElementById('keep');
  // The dashboard address a click should go to softly ('#tickets'), or null when the browser handles the click.
  function softHash(event, anchor, loc) {
    if (!anchor || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return null;
    if (anchor.hasAttribute('download')) return null;
    const target = (anchor.getAttribute('target') || '').toLowerCase();
    if (target && target !== '_self') return null;
    const raw = anchor.getAttribute('href');
    if (!raw || raw.startsWith('#')) return null;  // a plain #address is soft already
    let u;
    try { u = new URL(raw, loc.href); } catch (_) { return null; }
    if (u.origin !== loc.origin || u.search !== loc.search) return null;
    const page = p => (p === '/index.html' ? '/' : p);
    if (page(u.pathname) !== page(loc.pathname)) return null;  // another page of this server (style guide, a file)
    return u.hash && u.hash !== '#' ? u.hash : '#home';
  }
  // A page change closes the open dialogs, except the ones in the keep place.
  function dialogsToClose(doc = document, preview = on()) {
    const keep = preview ? keepEl(doc) : null;
    return [...doc.querySelectorAll('dialog[open]')].filter(d => !(keep && keep.contains(d)));
  }
  // Where each history entry was scrolled to, so Back and Forward land there again (in memory: a reload starts fresh).
  const scrolls = new Map();
  let serial = 0, moving = false;
  const hold = yes => { moving = !!yes; };  // while a page changes, scrolls belong to no entry
  function entryId(hist = history) {
    const id = hist.state && typeof hist.state === 'object' ? hist.state.softNav : null;
    if (id) return id;
    const fresh = 'p' + Date.now().toString(36) + '-' + (++serial);
    try { hist.replaceState({...(hist.state && typeof hist.state === 'object' ? hist.state : {}), softNav:fresh}, ''); } catch (_) { return null; }
    return fresh;
  }
  const KEEP_SCROLLS = 100;  // the last places only: a long session of page changes must not grow without end (ORCH-340)
  function remember(win = window) {
    if (!on() || moving) return;
    const id = entryId(win.history);
    if (!id) return;
    scrolls.delete(id);  // the newest goes last, so the oldest is dropped first
    scrolls.set(id, [win.scrollX, win.scrollY]);
    while (scrolls.size > KEEP_SCROLLS) scrolls.delete(scrolls.keys().next().value);
  }
  // The scroll to show after a page change: where this entry was left, or the top for a new one.
  function scrollAfterChange(hist = history, preview = on()) {
    if (!preview) return [0, 0];
    const id = hist.state && typeof hist.state === 'object' ? hist.state.softNav : null;
    return (id && scrolls.get(id)) || [0, 0];
  }
  // A page that could not be drawn: one normal load per address within a minute (never a reload loop).
  const HARD = 'orch-soft-fallback';
  function fallBack(hash, store = sessionStorage, loc = location, now = Date.now()) {
    if (!on()) return false;
    let last = null;
    try { last = JSON.parse(store.getItem(HARD) || 'null'); } catch (_) { last = null; }
    if (last && last.hash === hash && now - last.at < 60000) return false;
    try { store.setItem(HARD, JSON.stringify({hash, at:now})); } catch (_) { return false; }  // no storage: no loop guard, no reload
    loc.reload();
    return true;
  }
  // A new page takes the keyboard place and says its name once (#1350): the keyboard place moves to the page's heading (or <main>)
  // and the polite status line #page-said gets the page title, so a screen reader follows the change. Not gated on on().
  function arrive(main, words, doc = document) {
    if (!main) return null;
    const head = main.querySelector('h1') || main;
    if (head !== main && !head.hasAttribute('tabindex')) head.setAttribute('tabindex', '-1');
    try { head.focus({preventScroll:true}); } catch (_) { /* detached */ }
    const live = doc.getElementById('page-said');
    if (live) { live.textContent = ''; live.textContent = String(words || ''); }
    return head;
  }
  function said(from, to, kind, win = window) {
    try { win.dispatchEvent(new CustomEvent('orch:page', {detail:{from, to, kind}})); } catch (_) { /* old browser */ }
  }
  return {on, keepEl, softHash, dialogsToClose, entryId, remember, hold, scrollAfterChange, fallBack, arrive, said, scrolls, KEEP_SCROLLS};
})();
// The one mount place for content that survives a page change (the bar, the layer). It is empty until a later task
// mounts something; in a shared copy nothing mounts.
window.orchKeep = {
  el: () => SoftNav.keepEl(),
  mount(node) { const k = SoftNav.keepEl(); if (k && node && node.parentNode !== k) k.append(node); return node; },
};
document.addEventListener('click', event => {
  if (!SoftNav.on()) return;
  const hash = SoftNav.softHash(event, event.target.closest?.('a[href]'), location);
  if (!hash) return;
  event.preventDefault();
  if (location.hash !== hash) location.hash = hash;
});
{
  let queued = false;
  window.addEventListener('scroll', () => {
    if (queued) return;
    queued = true;
    requestAnimationFrame(() => { queued = false; SoftNav.remember(); });
  }, {passive:true});
}
