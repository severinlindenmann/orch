// Live activity cards on the start screen.
(function () {
  'use strict';
  const S = window.FocusStore;
  const {h, P, hhmm, toast} = S;
  const text = value => String(value ?? '').replace(/\bVPN\b/gi, 'network').replace(/\bMCP\b/gi, 'connection').replace(/\bt_[a-z0-9]{6,16}\b/g, '');

  let current = null;
  function mount(box) {
    if (!box || box.querySelector('.fx-livenow')) return;
    const section = h('section', {class: 'fx-livenow', hidden: true, 'aria-label': 'Live now'});
    box.insertBefore(section, box.querySelector('.fx-pick-group, .fx-procs'));
    let last = '', loading = false, sending = 0, generation = 0;

    async function load() {
      if (document.hidden || loading || sending || !box.isConnected) return;
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
        if (version !== generation && !sending) load();
      }
    }

    /* The same-file line lives in "Where work is happening" (areas.js), above the area tiles. */

    function cardView(card) {
      const href = P + '/t/' + encodeURIComponent(card.ticket), question = card.question;
      const label = h('div', {class: 'fx-ln-label', text: question ? 'Waits for your answer' : 'Now'});
      if (!question) label.append(h('span', {class: 'fx-ln-dot' + (card.working ? ' working' : ''), 'aria-hidden': 'true'}));
      const now = h('div', {class: 'fx-ln-now'}, label,
        h('div', {class: 'fx-ln-current', text: text(question ? question.text : card.now)}));
      if (card.why) now.append(h('div', {class: 'fx-ln-why', text: text(card.why)}));
      if (card.progress && card.progress.total > 0) {
        const total = card.progress.total, done = Math.max(0, Math.min(total, card.progress.done));
        now.append(h('div', {class: 'fx-ln-progress', role: 'progressbar', 'aria-label': 'Task progress', 'aria-valuemin': 0, 'aria-valuemax': total, 'aria-valuenow': done},
          h('span', {style: 'width:' + (done / total * 100) + '%'})));
      }
      if (question) {
        let busy = false;
        const options = h('div', {class: 'fx-ln-options'});
        const buttons = question.options.map(option => h('button', {
          type: 'button', class: 'btn sm ' + (option === question.recommended ? 'primary' : 'outline'),
          text: text(option) + (option === question.recommended ? ' (recommended)' : ''),
          onclick: async () => {
            if (busy) return;
            busy = true; sending++; generation++;
            buttons.forEach(button => { button.disabled = true; });
            options.setAttribute('aria-busy', 'true');
            try {
              const r = await S.act('answer', {ticket: card.ticket, question: question.id, answer: option});
              if (!r.ok) toast(text(r.message), 'error');
            } catch (e) { toast('Could not send your answer. Try again.', 'error'); }
            finally {
              busy = false; sending--;
              buttons.forEach(button => { button.disabled = false; });
              options.removeAttribute('aria-busy');
              load();
            }
          }
        }));
        options.append(...buttons, h('a', {href, text: 'Reply…'}));
        now.append(options);
      }
      const steps = h('ul', {class: 'fx-ln-steps'}, (card.steps || []).slice(0, 3).map(step =>
        h('li', {}, h('time', {datetime: step.at, text: hhmm(step.at)}),
          h('span', {class: 'fx-ln-icon' + (step.ok ? ' ok' : ''), 'aria-hidden': 'true', text: ({step: '·', done: '✓', ask: '?', helper: '↳'})[step.kind] || '·'}),
          h('span', {text: text(step.text)}))));
      return h('article', {class: 'fx-ln-card' + (question ? ' asking' : '')},
        h('header', {class: 'fx-ln-head'}, h('div', {class: 'fx-ln-title'},
          card.key ? h('div', {class: 'fx-ln-key', text: text(card.key)}) : null,
          h('a', {href, text: text(card.title)})),
        h('span', {class: 'fx-ln-agent', text: text(card.agent) + (card.minutes == null ? '' : ' · ' + card.minutes + ' min') + (card.area ? ' · ' + text(card.area) : '')})),
        now, steps, h('footer', {class: 'fx-ln-foot'}, h('a', {href, text: 'Open →'})));
    }

    /* A ticket shown as a live card is not listed again under "Working". */
    let shown = new Set();
    function hideListed() {
      for (const group of box.querySelectorAll('.fx-group-active')) {
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
      box.classList.toggle('fx-pick-live', !!cards.length);
      // keep the keyboard where it was: the cards are drawn again
      const at = section.contains(document.activeElement) ? [...section.querySelectorAll('a,button')].indexOf(document.activeElement) : -1;
      section.replaceChildren(...(cards.length ? [
        h('h2', {text: 'Live now '}, h('span', {class: 'meta', text: '(' + cards.length + ')'})),
        h('div', {class: 'fx-ln-grid' + (cards.length > 4 ? ' compact' : '')}, cards.map(cardView))
      ] : []));
      if (at >= 0) section.querySelectorAll('a,button')[at]?.focus();
      S.state.pickAgents = cards.length;  // "2 agents are working." in the line under the title
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

  S.register('livenow', {mount, hideListed: () => { if (current) current(); }});
})();
