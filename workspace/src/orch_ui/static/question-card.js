/* DOM adapter for the shared, clock-injectable question state. */
(function (root) {
  'use strict';
  let serial = 0;
  function mount(el, question, opts) {
    opts = opts || {};
    const doc = el.ownerDocument;
    const make = (tag, cls, text) => {
      const node = doc.createElement(tag);
      if (cls) node.className = cls;
      if (text !== undefined) node.textContent = text;
      return node;
    };
    const button = (text, cls, click) => {
      const node = make('button', cls, text);
      node.type = 'button';
      node.addEventListener('click', click);
      return node;
    };
    let storage = opts.storage;
    if (!storage) { try { storage = root.localStorage; } catch (_) { /* Optional storage. */ } }
    const state = root.QuestionCardState.create({key: 'orch.q.' + question.ticket + '.' + question.id,
      send: (answer, actionId) => {
        // The state timer may fire before its final countdown tick.
        // Once sending begins the undo window is closed.
        undoButton.disabled = true;
        undoButton.textContent = 'Undo 0';
        return opts.send(answer, actionId);
      }, storage, clock: opts.clock});
    const card = make('article', 'qcard');
    const meta = make('div', 'row qmeta');
    const badge = make('span', 'badge attn', 'Needs you');
    meta.append(badge, make('span', 'muted', 'Ticket ' + question.ticket));
    if (question.since) meta.append(make('span', 'faint', question.since));
    const title = make('h3', '', question.title);
    title.id = 'qcard-title-' + (++serial);
    card.setAttribute('aria-labelledby', title.id);
    const status = make('div', 'qstatus');
    status.setAttribute('aria-live', 'polite');
    const controls = make('div', 'qcontrols');
    card.append(meta, title, make('p', 'muted', question.text), status, controls);
    el.replaceChildren(card);
    let phase, undoButton, draft = '';
    function choices() {
      const options = make('div', 'qoptions');
      [...(question.options || [])].sort((a, b) => Number(!!b.suggested) - Number(!!a.suggested)).forEach(option => {
        const node = button('', 'btn qoption' + (option.suggested ? ' suggested' : ''), () => choose(option.text));
        node.append(make('span', '', option.text));
        if (option.suggested) node.append(make('span', 'suggested-label', 'Suggested'));
        options.append(node);
      });
      const editor = make('form', 'qeditor');
      editor.hidden = true;
      const label = make('label', '', 'Your answer');
      const input = make('textarea', 'input');
      input.id = title.id + '-answer';
      label.htmlFor = input.id;
      input.maxLength = 2000;
      input.rows = 3;
      input.value = draft;
      const counter = make('span', 'faint', draft.length + ' / 2000');
      counter.id = input.id + '-count';
      const err = make('div', 'err');
      err.id = input.id + '-error';
      err.setAttribute('aria-live', 'polite');
      input.setAttribute('aria-describedby', counter.id + ' ' + err.id);
      input.addEventListener('input', () => { draft = input.value; counter.textContent = draft.length + ' / 2000'; });
      const send = make('button', 'btn primary', 'Send');
      send.type = 'submit';
      const footer = make('div', 'row');
      footer.append(counter, send);
      editor.append(label, input, footer);
      editor.addEventListener('submit', event => { event.preventDefault(); choose(input.value); });
      const other = button('Something else...', 'btn quiet', () => {
        editor.hidden = !editor.hidden;
        other.setAttribute('aria-expanded', String(!editor.hidden));
        if (!editor.hidden) input.focus();
      });
      editor.id = input.id + '-editor';
      other.setAttribute('aria-controls', editor.id);
      other.setAttribute('aria-expanded', 'false');
      options.append(other);
      controls.append(options, editor, err);
      function choose(answer) {
        const result = state.choose(answer);
        if (!result.ok) { err.textContent = result.error; input.setAttribute('aria-invalid', 'true'); }
      }
    }
    function render(s) {
      const previous = phase;
      phase = s.phase;
      card.dataset.phase = phase;
      if (phase === 'pending' && previous === phase) {
        undoButton.textContent = 'Undo ' + s.secondsLeft;
        undoButton.disabled = s.secondsLeft <= 0;
        return;
      }
      const hadFocus = card.contains(doc.activeElement);
      controls.replaceChildren();
      status.className = 'qstatus ' + phase;
      status.textContent = '';
      badge.textContent = phase === 'sent' ? 'Answered' : phase === 'conflict' ? 'Answered elsewhere' : 'Needs you';
      badge.className = 'badge ' + (phase === 'sent' ? 'success' : 'attn');
      if (phase === 'pending') {
        status.textContent = "Answering '" + s.answer + "'...";
        undoButton = button('Undo ' + s.secondsLeft, 'btn', () => state.undo());
        controls.append(undoButton);
      } else if (phase === 'sent') {
        status.textContent = ["Answered '" + s.answer + "'", s.who, s.via].filter(Boolean).join(' · ');
      } else if (phase === 'conflict') {
        status.textContent = 'Someone answered first: ' + root.QuestionCardState.otherLine(s.other);
      } else {
        if (phase === 'undone') status.textContent = 'Not sent.';
        if (phase === 'notsent') status.textContent = "This answer was not sent: '" + s.answer + "'. Answer again.";
        if (phase === 'error') status.textContent = s.message;
        choices();
      }
      if (hadFocus) {
        const next = controls.querySelector('button');
        if (next) next.focus();
        else { status.tabIndex = -1; status.focus(); }
      }
    }
    state.init();
    const unsubscribe = state.subscribe(render);
    render(state.getState());
    return {state, reset() { draft = ''; state.reset(); }, destroy() { unsubscribe(); state.reset(); card.remove(); }};
  }
  root.QuestionCard = {mount};
})(window);
