// The Helpers list on the start screen (ORCH-61): one row per running helper with ORCH-n, step, minutes and the
// core's state word, drawn by the same kit widget as the Helpers panel on dashboard Home (UI.helperList).
(function () {
  'use strict';
  const S = window.FocusStore;
  const {h, P, toast} = S;
  const text = value => String(value ?? '').replace(/\bVPN\b/gi, 'network').replace(/\bMCP\b/gi, 'connection').replace(/\bt_[a-z0-9]{6,16}\b/g, '');
  const NUDGE = 'You have been idle for a while with open tasks on this ticket. Carry on with the next open task, or ask if something blocks you.';

  let current = null;
  /* settles once the first answer is drawn (or failed): the start page waits for it so the lists and the list of
     helpers appear together, instead of the tickets moving into it a few seconds later */
  let firstDone = null, first = Promise.resolve();
  function mount(box) {
    if (!box || box.querySelector('.fx-livenow')) return;
    first = new Promise(done => { firstDone = done; });
    const settle = () => { if (firstDone) { firstDone(); firstDone = null; } };
    const section = h('section', {class: 'fx-livenow', hidden: true, 'aria-label': 'Helpers'});
    box.insertBefore(section, box.querySelector('.fx-pick-group, .fx-procs'));
    let last = '', loading = false, sending = 0, generation = 0;

    async function load() {
      if (document.hidden || loading || sending || !box.isConnected) return settle();
      loading = true;
      const version = generation;
      try {
        const response = await fetch(P + '/api/live');
        if (!response.ok) return;
        const data = await response.json(), json = JSON.stringify(data);
        if (version !== generation || sending || document.hidden || !box.isConnected || json === last) return;
        paint(data.cards || []);
        last = json;
      } catch (e) { /* Keep the last snapshot until the next poll. */ }
      finally {
        loading = false;
        settle();
        if (version !== generation && !sending) load();
      }
    }

    /* Nudge an idle or stuck helper; Stop one whose ticket is finished (its session is still open). */
    function action(card, label, op, args, done) {
      return {label, key: 'helper-' + card.ticket + '-' + label.toLowerCase(), run: async button => {
        if (sending) return;
        sending++; generation++; button.disabled = true;
        try {
          const r = await S.act(op, args);
          toast(r.ok ? done : text(r.message), r.ok ? 'ok' : 'error');
        } catch (e) { toast('That did not go through. Try again.', 'error'); }
        finally { sending--; button.disabled = false; load(); }
      }};
    }
    function row(card) {
      const idle = card.state === 'idle' || card.state === 'stuck';
      return {
        key: text(card.key), title: text(card.title), href: P + '/t/' + encodeURIComponent(card.ticket),
        state: card.state, word: card.word, detail: text(card.detail), step: card.step, finished: card.finished,
        minutes: card.age_minutes, idle: card.idle_minutes, dataKey: 'helper-' + card.ticket,
        actions: !idle ? [] : card.finished ? [action(card, 'Stop', 'run.stop', {ticket: card.ticket}, 'Helper stopped')]
          : [action(card, 'Nudge', 'run.send', {ticket: card.ticket, text: NUDGE}, 'Message sent')],
      };
    }

    /* A ticket shown in the Helpers list is not listed again under "Working". */
    let shown = new Set();
    function hideListed() {
      for (const group of box.querySelectorAll('.fx-group-active, .fx-group-waiting')) {
        let left = 0;
        for (const a of group.querySelectorAll('.card > a')) {
          const id = (a.getAttribute('href') || '').split('/').pop();
          a.hidden = shown.has(id); if (!a.hidden) left++;
        }
        group.hidden = !left;
      }
    }
    current = hideListed;

    function paint(cards) {
      shown = new Set(cards.map(c => c.ticket));
      hideListed();
      section.hidden = !cards.length;
      // keep the keyboard where it was: the list is drawn again
      const at = section.contains(document.activeElement) ? document.activeElement.dataset.key || '' : '';
      section.replaceChildren(...(cards.length && window.UI && window.UI.helperList ? [window.UI.helperList(cards.map(row))] : []));
      if (at) section.querySelector('[data-key="' + at.replace(/"/g, '') + '"]')?.focus();
      S.state.pickAgents = cards.filter(c => c.state === 'working' || c.state === 'starting').length;  // "2 helpers are working.": only those that really work
      if (S.views.ticket && S.views.ticket.pickerSub) S.views.ticket.pickerSub();
    }

    const visible = () => { if (!document.hidden) load(); };
    const timer = setInterval(() => {
      if (!box.isConnected) {
        clearInterval(timer);
        document.removeEventListener('visibilitychange', visible);
        return;
      }
      load();
    }, 3000);
    document.addEventListener('visibilitychange', visible);
    load();
  }

  /* the first answer, at most `ms` long: a slow or broken answer never keeps the tickets hidden */
  const ready = ms => Promise.race([first, new Promise(done => setTimeout(done, ms))]);
  S.register('livenow', {mount, ready, hideListed: () => { if (current) current(); }});
})();
