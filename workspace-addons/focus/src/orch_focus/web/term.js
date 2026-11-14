// The live helper session in the dashboard: its real screen, and typing into it (fb17).
// A small renderer for the screen text tmux hands over (colours, bold, reverse, cursor); textContent only.
// Reading is open to the dashboard page; typing is for the person's dashboard session (the server decides).
(function () {
  'use strict';
  const S = window.FocusStore;
  const {h, TID} = S;

  /* the 16 base colours come from the master tokens (classes in focus.css); anything else keeps the default */
  const SGR_FG = {30: 0, 31: 1, 32: 2, 33: 3, 34: 4, 35: 5, 36: 6, 37: 7, 90: 8, 91: 9, 92: 10, 93: 11, 94: 12, 95: 13, 96: 14, 97: 15};
  function paint(text, cx, cy, showCursor) {
    const lines = String(text || '').split('\n');
    while (lines.length > 1 && lines.length - 1 > cy && !lines[lines.length - 1].replace(/\x1b\[[0-9;]*[A-Za-z]/g, '').trim()) lines.pop();  /* the blank rows under the last line are not drawn */
    const out = [];
    let st = {fg: null, bold: false, rev: false, dim: false};
    lines.forEach((line, y) => {
      const row = h('div', {class: 't-row'});
      let col = 0, buf = '';
      const flush = () => {
        if (!buf) return;
        const cls = ['t-seg'].concat(st.fg != null ? ['t-c' + st.fg] : [], st.bold ? ['t-b'] : [], st.dim ? ['t-d'] : [], st.rev ? ['t-r'] : []).join(' ');
        row.append(h('span', {class: cls, text: buf})); buf = '';
      };
      const put = ch => {
        if (showCursor && y === cy && col === cx) { flush(); const cls = ['t-seg', 't-cur'].concat(st.fg != null ? ['t-c' + st.fg] : []).join(' '); row.append(h('span', {class: cls, text: ch})); col++; return; }
        buf += ch; col++;
      };
      for (let i = 0; i < line.length; i++) {
        const c = line[i];
        if (c === '\x1b' && line[i + 1] === '[') {
          const m = /^\x1b\[([0-9;]*)([A-Za-z])/.exec(line.slice(i));
          if (m) {
            i += m[0].length - 1;
            if (m[2] === 'm') {
              flush();
              const codes = (m[1] || '0').split(';').map(Number);
              for (let k = 0; k < codes.length; k++) {
                const n = codes[k];
                if (n === 0) st = {fg: null, bold: false, rev: false, dim: false};
                else if (n === 1) st.bold = true; else if (n === 2) st.dim = true; else if (n === 7) st.rev = true;
                else if (n === 22) { st.bold = false; st.dim = false; } else if (n === 27) st.rev = false;
                else if (n === 39) st.fg = null; else if (n in SGR_FG) st.fg = SGR_FG[n];
                else if (n === 38 || n === 48) k += codes[k + 1] === 5 ? 2 : codes[k + 1] === 2 ? 4 : 0;  /* 256 / true colour: skipped */
              }
            }
            continue;
          }
        }
        put(c);
      }
      if (showCursor && y === cy && col <= cx) { flush(); row.append(h('span', {class: 't-seg', text: ' '.repeat(cx - col)}), h('span', {class: 't-seg t-cur', text: ' '})); }
      flush();
      if (!row.childNodes.length) row.append(h('span', {class: 't-seg', text: ' '}));  /* an empty line keeps its height */
      out.push(row);
    });
    return out;
  }

  const KEYS = {Enter: 'Enter', Backspace: 'BSpace', Tab: 'Tab', Escape: 'Escape', ArrowUp: 'Up', ArrowDown: 'Down', ArrowLeft: 'Left', ArrowRight: 'Right', Home: 'Home', End: 'End', PageUp: 'PageUp', PageDown: 'PageDown'};
  /* a key event becomes one item for the server: literal text, or a name from its list; null = not ours */
  function toItem(e) {
    if (e.metaKey || e.altKey) return null;
    if (e.ctrlKey) return !e.shiftKey && (e.key === 'c' || e.key === 'd') ? {k: 'C-' + e.key} : null;
    if (e.key === 'Tab' && e.shiftKey) return null;  /* Shift+Tab leaves the terminal */
    if (KEYS[e.key]) return {k: KEYS[e.key]};
    return e.key.length === 1 ? {t: e.key} : null;
  }
  const merge = items => items.reduce((acc, it) => { const last = acc[acc.length - 1]; if (it.t && last && last.t && last.t.length + it.t.length <= 2000) last.t += it.t; else acc.push({...it}); return acc; }, []);

  function mount(host) {
    const dot = h('span', {class: 'dot-ok', 'aria-hidden': 'true'});
    const body = h('div', {class: 'term-b fx-term-b', 'aria-hidden': 'true'});
    const hint = h('span', {class: 'meta fx-term-hint', text: 'Click the screen to type into the session · Shift+Tab to leave'});
    const view = h('div', {class: 'fx-term-view', tabindex: '0', role: 'group', 'data-term': '', 'aria-label': 'Live session of the helper. Press a key to type.'}, body);
    const badge = h('span', {class: 'badge fx-term-typing', hidden: true, text: 'Typing into the helper’s session'});
    const IDLE = 'Click the screen to type into the session · Shift+Tab to leave';
    const card = h('div', {class: 'term fx-term', hidden: true}, h('div', {class: 'term-h'}, dot, h('span', {text: 'Live session of Helper (the real session)'}), h('span', {class: 'grow'}), badge), view, h('div', {class: 'fx-term-foot'}, hint));
    const setTyping = () => {
      const on = canType && document.activeElement === view;
      card.dataset.typing = on ? '1' : '';
      badge.hidden = !on;
      hint.textContent = !canType ? 'You can watch here. Open the dashboard from this computer to type.' : on ? 'Your keys go to the helper’s session · Shift+Tab to stop' : IDLE;
    };
    const ask = h('div', {class: 'fx-term-ask row', hidden: true}, h('span', {class: 'grow', text: 'Your helper is waiting for an answer in its session.'}), h('button', {class: 'btn sm primary', type: 'button', text: 'Answer in the session', onclick: () => view.focus()}));
    const note = h('p', {class: 'meta fx-term-note', hidden: true});
    card.insertBefore(ask, card.firstChild); host.prepend(card, note);
    let queue = [], timer = null, canType = true, busy = false, last = '';
    const render = snap => {
      if (snap.state === 'live') {
        card.hidden = false; note.hidden = true;
        const key = JSON.stringify([snap.screen, snap.cx, snap.cy, snap.cursor, document.activeElement === view]);
        if (key !== last) { last = key; body.replaceChildren(...paint(snap.screen, snap.cx, snap.cy, snap.cursor && !snap.scrolled && document.activeElement === view)); }
        view.dataset.readonly = canType ? '' : '1'; setTyping();
        ask.hidden = !snap.waiting_input;
        return;
      }
      card.hidden = true; last = '';
      note.hidden = snap.state === 'none';
      note.textContent = snap.state === 'oneshot' ? 'No live session: the helper works one step at a time. Its steps are below.' : snap.state === 'notmux' ? 'This computer cannot show the live session. The helper’s steps are below.' : '';
    };
    async function poll() {
      if (busy || document.hidden || !TID) return;
      busy = true;
      try { const r = await fetch('/api/term?ticket=' + TID); if (r.ok) render(await r.json()); } catch (e) { /* next poll */ }
      busy = false;
    }
    let chain = Promise.resolve();
    const schedule = () => { if (!timer) timer = setTimeout(() => { timer = null; chain = chain.then(flush, flush); }, 25); };
    async function flush() {
      const all = merge(queue.splice(0, queue.length));
      let secret = ''; try { secret = sessionStorage.getItem('orch_page_secret') || ''; } catch (e) { /* none */ }
      while (all.length) {
        const items = []; let size = 0;
        while (all.length && items.length < 40 && size + (all[0].t || '').length <= 12000) { size += (all[0].t || '').length; items.push(all.shift()); }
        if (!items.length) items.push(all.shift());
        try {
          const r = await fetch('/api/term/keys', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Orch-Page': secret}, body: JSON.stringify({ticket: TID, items})});
          if (r.status === 403) { canType = false; setTyping(); S.toast('Open the dashboard from this computer to type here.', 'error'); return; }
          if (r.status === 409) { S.toast('The live session has ended; those keys were not sent.', 'error'); return; }
          if (!r.ok) { S.toast((await r.text()).slice(0, 120) || 'The session did not take that.', 'error'); return; }
        } catch (e) { return; }
      }
      setTimeout(poll, 120);
    }
    view.addEventListener('keydown', e => {
      const it = canType ? toItem(e) : null;
      if (!it) return;
      e.preventDefault(); e.stopPropagation();
      queue.push(it);
      schedule();
    });
    view.addEventListener('paste', e => {
      const t = (e.clipboardData && e.clipboardData.getData('text')) || '';
      e.preventDefault();
      if (!canType || !t) return;
      for (let i = 0; i < t.length; i += 2000) queue.push({t: t.slice(i, i + 2000).replace(/\r\n?/g, '\n').replace(/[\x00-\x08\x0b-\x1f\x7f-\x9f]/g, '')});
      schedule();
    });
    view.addEventListener('focus', () => { last = ''; setTyping(); poll(); });
    view.addEventListener('blur', () => { last = ''; setTyping(); poll(); });
    body.addEventListener('click', () => view.focus());
    setInterval(() => { if (S.state.view && S.state.view.run.running) poll(); }, 1000);
    poll();
    return {poll};
  }

  S.register('term', {mount, paint, toItem, merge});
})();
