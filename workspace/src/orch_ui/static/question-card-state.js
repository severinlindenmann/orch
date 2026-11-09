/* Question card logic, no DOM. Plain-question options (oneTap, no kind) send immediately; everything else waits 5 seconds (Undo); exactly one send.
   idle -> pending -> sending -> sent | undone | conflict | error ;  a reload with an unsent pending answer -> notsent.
   Clock, send function, storage and id source are injected so tests need no browser and no real time. */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.QuestionCardState = api;
})(typeof self !== 'undefined' ? self : this, function () {
  const MAX_LEN = 2000;
  const UNDO_MS = 5000;

  /* opts: {key, send(answer, actionId) -> Promise<{status, who?, via?, other?:{text, who, via}, message?}>,
            clock:{setTimeout, clearTimeout, now}, storage:{getItem,setItem,removeItem}, newId(), undoMs} */
  function create(opts) {
    const clock = opts.clock || {setTimeout: (f, ms) => setTimeout(f, ms), clearTimeout: id => clearTimeout(id), now: () => Date.now()};
    const storage = opts.storage || {getItem() { return null; }, setItem() {}, removeItem() {}};
    const undoMs = opts.undoMs || UNDO_MS;
    const newId = opts.newId || (() => 'a_' + Math.random().toString(36).slice(2, 10));
    const subs = [];
    let timer = null, tick = null, deadline = 0;
    let state = {phase: 'idle'};

    const set = next => { state = next; subs.forEach(f => f(state)); };
    const save = rec => { try { storage.setItem(opts.key, JSON.stringify(rec)); } catch (e) { /* storage may be blocked */ } };
    const clear = () => { try { storage.removeItem(opts.key); } catch (e) { /* ignore */ } };
    const stopTimers = () => {
      if (timer !== null) clock.clearTimeout(timer);
      if (tick !== null) clock.clearTimeout(tick);
      timer = tick = null;
    };

    /* A pending answer left in storage means the tab closed before the send: tell the person it was not sent. */
    function init() {
      let rec = null;
      try { rec = JSON.parse(storage.getItem(opts.key) || 'null'); } catch (e) { rec = null; }
      if (rec && typeof rec.answer === 'string') {
        clear();
        set({phase: 'notsent', answer: rec.answer});
      }
      return state;
    }

    function countdown() {
      const left = Math.max(0, Math.ceil((deadline - clock.now()) / 1000));
      if (state.phase === 'pending') set({phase: 'pending', answer: state.answer, actionId: state.actionId, secondsLeft: left});
      tick = clock.setTimeout(countdown, 1000);
    }

    function validate(text) {
      if (typeof text !== 'string' || !text.trim()) return 'Write an answer first.';
      if (text.length > MAX_LEN) return `Please keep the answer under ${MAX_LEN} characters.`;
      return '';
    }

    function choose(text, {immediate = false} = {}) {
      if (state.phase === 'pending' || state.phase === 'sending') return {ok: false, error: 'Already answering.'};
      const error = validate(text);
      if (error) return {ok: false, error};
      const actionId = newId();
      deadline = clock.now() + undoMs;
      save({answer: text, actionId, at: clock.now()});
      set({phase: 'pending', answer: text, actionId, secondsLeft: Math.ceil(undoMs / 1000)});
      if (immediate) { clear(); fire(); }
      else {
        tick = clock.setTimeout(countdown, 1000);
        timer = clock.setTimeout(fire, undoMs);
      }
      return {ok: true};
    }

    function undo() {
      if (state.phase !== 'pending') return false;
      stopTimers();
      clear();
      set({phase: 'undone', answer: state.answer});
      return true;
    }

    async function fire() {
      if (state.phase !== 'pending') return;
      stopTimers();
      const {answer, actionId} = state;
      set({phase: 'sending', answer, actionId});
      let res;
      try { res = await opts.send(answer, actionId); } catch (e) { res = {status: 0, message: 'Could not reach orch.'}; }
      clear();
      if (res && res.status >= 200 && res.status < 300) set({phase: 'sent', answer, who: res.who, via: res.via});
      else if (res && res.status === 409) set({phase: 'conflict', answer, other: res.other || {}});
      else set({phase: 'error', answer, message: (res && res.message) || 'Not sent. Try again.'});
    }

    function reset() { stopTimers(); clear(); set({phase: 'idle'}); }

    return {init, choose, undo, reset, getState: () => state, subscribe: f => { subs.push(f); return () => subs.splice(subs.indexOf(f), 1); }};
  }

  /* "Yes · Marco · dashboard" */
  function otherLine(other) {
    return [other && other.text, other && other.who, other && other.via].filter(Boolean).join(' · ');
  }

  return {create, otherLine, MAX_LEN, UNDO_MS};
});
