// Focus draft #692 (15 Nov): demo behaviour for the static draft pages. Mockup only, no product code.
// ?state=<name> shows the elements marked data-show="<name> ..." and hides data-hide="<name> ...".
(() => {
  'use strict';
  const $ = (s, r = document) => r.querySelector(s), $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const state = new URLSearchParams(location.search).get('state') || 'loaded';
  document.body.dataset.state = state;
  const words = v => (v || '').split(/\s+/).filter(Boolean);
  $$('[data-show]').forEach(n => { n.hidden = !words(n.dataset.show).includes(state); });
  $$('[data-hide]').forEach(n => { if (words(n.dataset.hide).includes(state)) n.hidden = true; });
  const toast = (t, undo) => (window.UI && UI.toast ? UI.toast(t, undo) : null);

  /* typing switch: watch by default; the switch is where you see the screen */
  const dock = $('.session-dock');
  const setTyping = on => {
    if (!dock) return;
    dock.classList.toggle('typing', on);
    const sw = $('[data-switch-typing]'); if (sw) sw.checked = on;
    const foot = $('[data-dock-foot]');
    if (foot) foot.textContent = on ? 'Your keys go straight to the helper’s screen. Turn “Let me type” off or press Shift+Tab to stop.' : 'Watching. Your messages go through the box below.';
    const body = $('.session-dock-b'); if (on && body) body.focus();
  };
  $$('[data-switch-typing]').forEach(sw => sw.addEventListener('change', () => setTyping(sw.checked)));
  $$('[data-type-answer]').forEach(b => b.addEventListener('click', () => setTyping(true)));
  if (state === 'typing') setTyping(true);
  document.addEventListener('keydown', e => { if (e.key === 'Tab' && e.shiftKey && dock && dock.classList.contains('typing')) { e.preventDefault(); setTyping(false); } });

  /* docked panel: open/peek remembered, maximise */
  const KEY = 'focus-draft-dock';
  const setOpen = open => {
    if (!dock) return;
    dock.classList.toggle('peek', !open);
    $$('[data-dock-toggle]').forEach(b => { b.setAttribute('aria-expanded', String(open)); b.setAttribute('aria-label', open ? 'Hide the session' : 'Show the session'); b.title = open ? 'Hide (Ctrl+`)' : 'Show (Ctrl+`)'; b.querySelector('.dock-chev') && (b.querySelector('.dock-chev').textContent = open ? '⌄' : '⌃'); });
    try { localStorage.setItem(KEY, open ? 'open' : 'peek'); } catch (e) { /* not kept */ }
  };
  if (dock && dock.dataset.dock !== undefined) {
    let saved = null; try { saved = localStorage.getItem(KEY); } catch (e) { /* none */ }
    setOpen(state === 'typing' ? true : saved ? saved === 'open' : dock.dataset.dock !== 'peek');
    $$('[data-dock-toggle]').forEach(b => b.addEventListener('click', e => { e.stopPropagation(); setOpen(dock.classList.contains('peek')); }));
    $('.session-dock-h').addEventListener('click', e => { if (!e.target.closest('button,label,input')) setOpen(dock.classList.contains('peek')); });
    $$('[data-dock-max]').forEach(b => b.addEventListener('click', e => { e.stopPropagation(); const on = document.body.classList.toggle('dock-max'); b.setAttribute('aria-label', on ? 'Back to normal size' : 'Use the whole page'); b.title = b.getAttribute('aria-label'); setOpen(true); }));
  }

  document.addEventListener('keydown', e => { if (e.ctrlKey && e.key === '`' && dock && dock.dataset.dock !== undefined) { e.preventDefault(); setOpen(dock.classList.contains('peek')); } });

  /* tabs in the draft (Live / Session) */
  $$('[data-draft-tab]').forEach(t => t.addEventListener('click', () => {
    $$('[data-draft-tab]').forEach(o => { const on = o === t; o.setAttribute('aria-selected', String(on)); const p = document.getElementById(o.getAttribute('aria-controls')); if (p) p.hidden = !on; });
    try { localStorage.setItem('focus-draft-tab', t.dataset.draftTab); } catch (e) { /* not kept */ }
  }));

  /* run log: find + copy */
  const find = $('[data-log-find]');
  if (find) {
    const count = $('[data-log-count]');
    const blocks = $$('.cmd-block, .fx-row-plain');
    blocks.forEach(b => { b.dataset.raw = b.innerHTML; });
    const run = () => {
      const q = find.value.trim().toLowerCase(); let n = 0;
      blocks.forEach(b => {
        b.innerHTML = b.dataset.raw;
        const hit = !q || b.textContent.toLowerCase().includes(q);
        b.classList.toggle('dim', !!q && !hit);
        if (q && hit) { n++; if (b.tagName === 'DETAILS') b.open = true; mark(b, q); }
      });
      count.textContent = q ? (n ? n + (n === 1 ? ' step matches' : ' steps match') : 'Nothing matches “' + find.value.trim() + '”') : blocks.length + ' steps';
      bindCopy(document);
    };
    find.addEventListener('input', run);
    if (state === 'search') { find.value = 'test mail'; run(); }
  }
  function mark(root, q) {
    const walk = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    const hits = []; let t; while ((t = walk.nextNode())) { if (t.parentElement.closest('button')) continue; if (t.nodeValue.toLowerCase().includes(q)) hits.push(t); }
    hits.forEach(node => {
      const i = node.nodeValue.toLowerCase().indexOf(q), m = document.createElement('mark');
      const after = node.splitText(i); after.splitText(q.length); m.textContent = after.nodeValue; after.replaceWith(m);
    });
  }
  function bindCopy(root) {
    $$('[data-copy]', root).forEach(b => { if (b.dataset.bound) return; b.dataset.bound = '1'; b.addEventListener('click', async e => {
      e.preventDefault(); e.stopPropagation();
      const src = b.dataset.copy ? $(b.dataset.copy, b.closest('.cmd-block') || document) : null;
      try { await navigator.clipboard.writeText(src ? src.textContent : ''); } catch (err) { /* demo */ }
      toast(b.dataset.copied || 'Copied.');
    }); });
  }
  bindCopy(document);

  if (state === 'waiting') { const ta = document.querySelector('[data-wait-placeholder]'); if (ta) ta.placeholder = ta.dataset.waitPlaceholder; }

  /* take back a queued instruction */
  $$('[data-take-back]').forEach(b => b.addEventListener('click', () => {
    const card = b.closest('.queued-msg'); card.classList.add('taken');
    const line = $('[data-q-line]', card); const old = line.innerHTML;
    line.textContent = 'Taken back. The helper never saw it.';
    toast('Taken back. The helper never saw it.', () => { card.classList.remove('taken'); line.innerHTML = old; bindAll(card); });
  }));
  function bindAll(card) { $$('[data-take-back]', card).forEach(x => x.addEventListener('click', () => x.click())); }
  $$('[data-edit-queued]').forEach(b => b.addEventListener('click', () => {
    const card = b.closest('.queued-msg'), ta = document.querySelector('textarea');
    if (ta) { ta.value = card.querySelector('p').textContent; ta.focus(); }
    card.remove(); toast('Taken back. It is in the message box again; the helper never saw it.');
  }));
})();
