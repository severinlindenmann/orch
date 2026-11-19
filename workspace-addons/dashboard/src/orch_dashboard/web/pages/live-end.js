'use strict';
// ORCH-817: Stop and End session for every session of the new live page: a ticket's helper, the Manager, the empty
// helper, the chat helper and the plain terminal. The same two sit in the pane header (pages/live-layer.js), in the
// More menu of a wall tile (pages/livewall.js) and on the bar (pages/livebar.js: a list row's More, a right-click on a
// chip). Stop ends only the current step and the session stays (`run.interrupt` = `orch run interrupt`). End session
// asks once, then ends the process: a ticket's helper through `run.stop` (= `orch run stop`), a session without a
// ticket through `session.end` (= `orch session end <kind>`); a helper's conversation stays in History, the plain
// terminal just closes. A hung helper (nothing running, or its login changed) offers Start again: end, then start.

// --- the model (plain data, tested in tests/live_end.test.js) ---
const LIVE_END_KINDS = ['empty', 'chat', 'terminal', 'manager'];
// A helper whose screen says its login changed or ran out: it stopped and waits for a new sign-in.
const LIVE_END_LOGIN = /\/login\b|login (?:has )?(?:changed|expired)|not logged in|invalid api key|please (?:log|sign) in/i;
function liveEndLogin(lines) {
  return (Array.isArray(lines) ? lines : []).slice(-8).some(l => LIVE_END_LOGIN.test(String(l || '')));
}
// What Stop and End do for one session. s: a session of GET /api/sessions ({id, kind, status, lines}); kind '' is a
// ticket's helper. on: there is something to stop or end; stop: a helper (a plain terminal has no step); busy: a step
// runs now (Stop is greyed otherwise); hung: idle or the login changed, so the pane offers Start again.
function liveEndModel(s) {
  if (!s || typeof s.id !== 'string') return {on:false, stop:false, busy:false, hung:false, login:false, kind:''};
  const kind = LIVE_END_KINDS.includes(s.kind) ? s.kind : '', st = String(s.status || 'closed');
  const terminal = kind === 'terminal', on = terminal ? st !== 'closed' : ['working', 'needs-you', 'idle'].includes(st);
  const login = on && !terminal && liveEndLogin(s.lines);
  return {on, kind, stop:on && !terminal, busy:on && !terminal && !login && (st === 'working' || st === 'needs-you'),
    hung:on && !terminal && (st === 'idle' || login), login,
    stopOp:['run.interrupt', {ticket:s.id}],
    endOp:kind ? ['session.end', {kind}] : ['run.stop', {ticket:s.id}],
    startOp:kind ? ['session.new', {kind}] : ['run.start', {ticket:s.id}]};
}
// The words of the one question before End, and what a person reads after it.
function liveEndWords(name, kind) {
  const who = String(name || '').trim() || (kind === 'terminal' ? 'the plain terminal' : 'this session');
  return kind === 'terminal'
    ? {ask:'End ' + who + '?', why:'The terminal closes.', done:'Plain terminal closed.'}
    : {ask:'End ' + who + '?', why:'The helper stops for good. Its conversation is kept in History, where you can reopen it.',
      done:who.charAt(0).toUpperCase() + who.slice(1) + ' ended. Its conversation is in History.'};
}
// The note an idle helper's pane shows instead of an empty box: what is going on, what to type, a way out.
function liveEndIdleText(m, now) {
  if (m.login) return {head:'The helper stopped: its login changed.', tail:'Start it again to use the new login. The conversation is kept.'};
  const said = String(now || '').trim().replace(/\.$/, '');
  return {head:said ? said + '.' : 'Idle. Nothing is running.', tail:'Type a message below to give it work. If it hangs, start it again.'};
}

if (typeof module === 'object' && module.exports) {
  module.exports = {LIVE_END_KINDS, liveEndLogin, liveEndModel, liveEndWords, liveEndIdleText};
} else {
  // --- the page ---
  // One menu at a time, wherever it is: 'pane:<id>', 'tile:<id>' or 'bar:<id>'; ask = the End question shows.
  const liveEnd = {open:'', ask:false, busy:''};
  const liveEndSession = id => (Array.isArray(window.LiveSessions?.list) ? window.LiveSessions.list : []).find(x => x && x.id === id) || null;
  // A session of the API, else what the layer knows (a ticket's pane before the first answer of the sessions API).
  const liveEndOf = id => liveEndSession(id) || (typeof liveLayerSession === 'function' ? (x => x && x.running ? {id:x.id, kind:x.kind || '', status:'working', lines:[]} : null)(liveLayerSession(id)) : null);
  const liveEndName = id => { const s = liveEndSession(id); return s ? (typeof liveName === 'function' ? liveName(s) : s.title) || s.key || '' : ''; };
  window.liveEndKey = () => [liveEnd.open, liveEnd.ask, liveEnd.busy];
  function liveEndRepaint(focus) {
    if (typeof liveLayerPaint === 'function') liveLayerPaint();
    if (typeof liveWallRepaint === 'function') liveWallRepaint();
    window.dispatchEvent(new CustomEvent('orch:live-end'));  // the bar paints itself again
    if (focus) document.querySelector(focus)?.focus({preventScroll:true});
  }
  const ic = name => { const s = h('span', {className:'ic-wrap', 'aria-hidden':'true'}); s.innerHTML = icon(name, 18); return s; };
  // The pane header's two buttons: Stop (one click, greyed when nothing runs) and End session (opens the question).
  window.liveEndButtons = function liveEndButtons(id, label) {
    const m = liveEndModel(liveEndOf(id));
    if (!m.on) return [];
    const where = 'pane:' + id;
    return [
      m.stop ? h('button', {type:'button', className:'btn icon sm ghost', 'data-live-end':'stop', 'data-id':id, 'data-key':'live-stop',
        disabled:!m.busy || liveEnd.busy === id, 'aria-label':'Stop the current step of ' + label,
        title:m.busy ? 'Stop: ends the current step, the session stays' : 'Nothing is running right now'}, ic('stop')) : null,
      h('button', {type:'button', className:'btn icon sm ghost', 'data-live-end':'ask', 'data-where':where, 'data-id':id, 'data-key':'live-end',
        'aria-expanded':String(liveEnd.open === where), 'aria-label':'End session of ' + label, title:'End session'}, ic('power')),
      liveEnd.open === where ? liveEndMenu(id, where) : null];
  };
  // The More button of a tile or a bar row, and the menu it opens.
  window.liveEndMore = function liveEndMore(id, where, label) {
    if (!liveEndModel(liveEndOf(id)).on) return null;
    const w = where + ':' + id;
    return h('button', {type:'button', className:'btn icon sm ghost', 'data-live-end':'menu', 'data-where':w, 'data-id':id, 'data-key':where + '-end-' + id,
      'aria-expanded':String(liveEnd.open === w), 'aria-haspopup':'true', 'aria-label':'Stop or end ' + label, title:'Stop or end this session'}, ic('more'));
  };
  // Opens the Stop and End menu of a session that has one ('bar:<id>' from a chip's right-click); false when it has none.
  window.liveEndShow = where => {
    const id = where.slice(where.indexOf(':') + 1);
    if (!liveEndModel(liveEndOf(id)).on) return false;
    liveEnd.open = where; liveEnd.ask = false;
    liveEndRepaint('[data-key="live-end-menu"] button:not([disabled])');
    return true;
  };
  window.liveEndOpenAt = where => liveEnd.open.startsWith(where + ':') ? liveEnd.open.slice(where.length + 1) : '';
  // The menu: Stop and End session, or, once End was chosen, the one question (also the pane's End button).
  function liveEndMenu(id, where) {
    const s = liveEndOf(id), m = liveEndModel(s), name = liveEndName(id), words = liveEndWords(name, m.kind);
    const ask = liveEnd.ask || where.startsWith('pane:');
    if (!m.on) return null;
    const busy = liveEnd.busy === id;
    if (ask) return h('div', {className:'live-pop live-end-ask', role:'group', 'aria-label':words.ask, 'data-key':'live-end-ask'},
      h('p', {className:'live-pop-h'}, words.ask),
      h('p', {className:'meta'}, words.why),
      h('div', {className:'row live-end-row'},
        h('button', {type:'button', className:'btn danger sm', 'data-live-end':'yes', 'data-id':id, 'data-key':'live-end-yes', disabled:busy, 'aria-busy':busy ? 'true' : null}, 'End session'),
        h('button', {type:'button', className:'btn ghost sm', 'data-live-end':'no', 'data-id':id, 'data-key':'live-end-no'}, 'Keep it')));
    const item = (act, glyph, words2, sub, extra = {}) => h('button', {type:'button', className:'live-opt live-end-opt', 'data-live-end':act, 'data-id':id, 'data-where':where, ...extra},
      ic(glyph), h('span', {className:'live-opt-t'}, h('span', {}, words2), h('span', {className:'meta'}, sub)));
    return h('div', {className:'live-pop live-end-menu', role:'group', 'aria-label':'Stop or end ' + (name || 'this session'), 'data-key':'live-end-menu'},
      name ? h('p', {className:'live-pop-h'}, name) : null,
      m.stop ? item('stop', 'stop', 'Stop', m.busy ? 'Ends the current step. The session stays.' : 'Nothing is running right now.', {disabled:!m.busy || busy, 'data-key':'live-end-stop'}) : null,
      item('ask', 'power', 'End session', m.kind === 'terminal' ? 'Closes the terminal.' : 'Ends the helper. It moves to History.', {'data-key':'live-end-end'}));
  }
  window.liveEndMenu = liveEndMenu;
  // The idle note of a helper's pane: filled on every answer of the sessions API (pages/live-layer.js liveLayerFill).
  window.liveEndIdleFill = function liveEndIdleFill(box, id, now) {
    const m = liveEndModel(liveEndSession(id));
    box.hidden = !m.hung;
    if (!m.hung) return;
    const t = liveEndIdleText(m, now), sig = t.head + '\u0001' + t.tail;
    if (box.dataset.sig === sig) return;
    box.dataset.sig = sig; box.textContent = '';
    box.append(h('p', {}, h('strong', {}, t.head), ' ' + t.tail),
      h('div', {className:'row live-end-row'},
        h('button', {type:'button', className:'btn outline sm', 'data-live-end':'restart', 'data-id':id, 'data-key':'live-restart'}, 'Start again'),
        h('button', {type:'button', className:'btn ghost sm', 'data-live-end':'ask', 'data-where':'pane:' + id, 'data-id':id, 'data-key':'live-idle-end'}, 'End session')));
  };
  async function liveEndRun(id, op) {
    liveEnd.busy = id; liveEndRepaint();
    const r = await act(op[0], op[1], {quiet:true});
    liveEnd.busy = '';
    if (r.ok) await window.LiveSessions?.refresh?.();  // the pane, the wall and the bar show the new state at once
    return r;
  }
  const toast = (text, kind) => window.orch?.toast?.(text, kind);
  document.addEventListener('click', async e => {
    const b = e.target.closest?.('[data-live-end]');
    if (!b) {
      if (liveEnd.open && !e.target.closest?.('.live-end-menu, .live-end-ask')) { liveEnd.open = ''; liveEnd.ask = false; liveEndRepaint(); }
      return;
    }
    if (b.disabled) return;
    e.preventDefault(); e.stopPropagation();
    const id = b.dataset.id, s = liveEndOf(id), m = liveEndModel(s), what = b.dataset.liveEnd;
    if (what === 'menu' || what === 'ask') {
      const where = b.dataset.where || 'pane:' + id;
      const again = liveEnd.open === where && (what === 'menu' ? !liveEnd.ask : liveEnd.ask || where.startsWith('pane:'));
      liveEnd.open = again ? '' : where; liveEnd.ask = !again && what === 'ask';
      liveEndRepaint(liveEnd.open ? (liveEnd.ask || where.startsWith('pane:') ? '[data-key="live-end-yes"]' : '[data-key="live-end-menu"] button:not([disabled])') : null);
      return;
    }
    if (what === 'no') { liveEnd.open = ''; liveEnd.ask = false; liveEndRepaint(); toast('The session stays.', 'ok'); return; }
    liveEnd.open = ''; liveEnd.ask = false;
    if (what === 'stop') {
      const r = await liveEndRun(id, m.stopOp);
      toast(r.ok ? 'Stopped the current step. The session stays; type to go on.' : r.text || 'Could not stop the step.', r.ok ? 'ok' : 'error');
    } else if (what === 'yes') {
      const r = await liveEndRun(id, m.endOp), words = liveEndWords(liveEndName(id), m.kind);
      toast(r.ok ? words.done : r.text || 'Could not end the session.', r.ok ? 'ok' : 'error');
      if (r.ok && m.kind === 'terminal' && typeof liveLayerDo === 'function') liveLayerDo({type:'close', key:id});
    } else if (what === 'restart') {
      const r = await liveEndRun(id, m.endOp), r2 = r.ok ? await liveEndRun(id, m.startOp) : r;
      toast(r2.ok ? 'Started again. It goes on with the same conversation.' : r2.text || 'Could not start it again.', r2.ok ? 'ok' : 'error');
    }
    liveEndRepaint();
  }, true);
  document.addEventListener('keydown', e => {
    if (e.key !== 'Escape' || !liveEnd.open) return;
    const where = liveEnd.open.replace(/["\\]/g, '');
    e.stopPropagation(); liveEnd.open = ''; liveEnd.ask = false;
    liveEndRepaint('[data-live-end="' + (where.startsWith('pane:') ? 'ask' : 'menu') + '"][data-where="' + where + '"]');
  }, true);
}
