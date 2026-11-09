// Owns the live feed, questions, status lines, and run actions.
(function () {
  'use strict';
  const S = window.FocusStore;
  const {h, TID, toast, els, act, STATUS_WORD, plainNames, keyOf, hhmm, evText} = S;

  // The ticket lines orch writes itself, in the same plain words as the CLI and the dashboard.
  function plainLine(text, checklist) {
    const task = id => { const c = (checklist || []).find(x => x.id === id); return c && c.text ? ': ' + c.text : ''; };
    const addon = k => k.replace(/-/g, ' ').replace(/^./, c => c.toUpperCase());
    let m;
    if ((m = /^Added check (c\d+)$/.exec(text))) return 'Added a task' + task(m[1]);
    if ((m = /^Check (c\d+) done$/.exec(text))) return 'Finished a task' + task(m[1]);
    if ((m = /^Marked (c\d+) as won't do$/.exec(text))) return "Marked as won't do" + task(m[1]);
    if (/^Asked q\d+, waiting$/.test(text)) return 'Asked a question';
    if ((m = /^Answered q\d+: ([\s\S]*)$/.exec(text))) return 'Answered a question: ' + m[1];
    if ((m = /^(?:Patched status \(status|Status) \w+ -> (\w+)/.exec(text))) return 'Moved to ' + (STATUS_WORD[m[1]] || m[1]);
    if ((m = /^Set ext\.([a-z][a-z0-9-]*)$/.exec(text))) return 'Updated ' + addon(m[1]) + ' settings';
    return plainNames(text);
  }

  function feedItems(v) {
    const items = [];
    for (const e of v.ticket.history || []) items.push({at: e.at, icon: /Asked|waiting/.test(e.text) ? 'note' : (/done/.test(e.text) ? 'check' : 'text'), ok: /done/.test(e.text), text: plainLine(String(e.text || ''), v.ticket.checklist), who: e.by, you: /^human:/.test(e.by || '') && e.via !== 'cli'});
    for (const e of v.events) {
      if (e.kind === 'tool.start') items.push({at: e.at, icon: 'text', text: plainNames(e.text)});
      else if (e.kind === 'tool.end') items.push({at: e.at, icon: e.data.ok === false ? 'x' : 'check', ok: e.data.ok !== false, text: e.text});
      else if (e.kind === 'helper.start') items.push({at: e.at, icon: 'user', text: 'Helper: ' + e.text});
      else if (e.kind === 'helper.end') items.push({at: e.at, icon: 'check', ok: true, text: 'Helper done: ' + e.text});
    }
    items.sort((a, b) => String(a.at).localeCompare(String(b.at)));
    return items.slice(-80);
  }

  function renderFeed(v) {
    const key = keyOf([v.ticket.checklist, v.state, v.run.running, v.run.run, v.ticket.started, v.board.step, v.events, v.ticket.history]);
    if (key === S.state.lastFeedKey) return;
    S.state.lastFeedKey = key;
    const asking = v.ticket.questions.some(q => q.answer == null);
    const checks = v.ticket.checklist;
    if (!v.run.running && !v.run.run && !v.ticket.started && v.state !== 'done' && !asking && !checks.length) {
      els.feed.replaceChildren(h('div', {class: 'fx-start'}, h('span', {class: 'empty-symbol', text: '◌'}),
        h('h2', {text: 'Give ' + els.agent.textContent + ' the first step'}),
        h('p', {text: els.agent.textContent + ' hasn’t started yet. Start it and watch it plan the tasks here.'}),
        h('p', {class: 'meta', text: 'Next step · Start ' + els.agent.textContent}), h('button', {class: 'btn primary', 'data-act': 'stop', text: 'Start ' + els.agent.textContent})));
      return;
    }
    const story = checks.filter(c => !c.wont_do && (c.done || c.state === 'doing'));
    const heading = asking ? 'Before the question' : v.state === 'done' ? 'Work completed' : v.run.running ? 'The work is taking shape' : 'Work so far';
    const nodes = [h('h2', {text: heading})];
    if (!asking) nodes.push(h('p', {class: 'meta', text: v.done + ' of ' + v.total + ' tasks finished.'}));
    for (const c of story) nodes.push(h('article', {class: 'fx-story' + (!c.done && v.run.running ? ' now' : '')},
      h('h3', {text: (c.done ? '✓ ' : v.run.running ? 'Now: ' : '') + c.text}),
      h('p', {text: evText(c) || (!c.done && v.run.running ? v.board.step || 'Working on this task.' : '')})));
    if (v.run.running && !story.some(c => !c.done)) nodes.push(h('article', {class: 'fx-story now'}, h('h3', {text: v.board.step || 'Waiting for the first step…'})));
    if (!v.run.running && !asking && v.state !== 'done' && v.ticket.status !== 'review' && !v.ticket.started && !v.run.run) nodes.push(h('button', {class: 'btn primary', 'data-act': 'stop', text: 'Start ' + els.agent.textContent}));
    const details = h('details', {class: 'fx-history'}, h('summary', {text: 'Details'}));
    for (const it of feedItems(v)) details.append(h('div', {class: 'fx-step'}, h('time', {text: hhmm(it.at)}), h('span', {icon: it.icon}), h('span', {text: it.text})));
    nodes.push(details);
    els.feed.replaceChildren(...nodes);
  }

  function renderQuestions(v) {
    const open = v.ticket.questions.filter(q => q.answer == null);
    if (S.state.prevQuestionLabel !== v.run.label) { for (const card of S.state.shownQs.values()) card.node.remove(); S.state.shownQs.clear(); S.state.prevQuestionLabel = v.run.label; }
    const ids = new Set(open.map(q => q.id));
    for (const [id, card] of S.state.shownQs) if (!ids.has(id)) { card.node.remove(); S.state.shownQs.delete(id); }
    for (const q of open) {
      // m1-api question fields: sent_to_phone or delivered, strict booleans only.
      const delivered = q.sent_to_phone === true;
      if (S.state.shownQs.has(q.id)) { S.state.shownQs.get(q.id).receipt.hidden = !delivered; continue; }
      const node = h('div', {'data-row': '', class: 'fx-ask-wrap'});
      els.qs.append(node);
      const options = (q.options || []).map(o => ({text: o, suggested: o === q.recommended}));
      const question = {ticket: TID, key: typeof v.ticket.key === 'string' ? v.ticket.key : undefined, id: q.id, title: q.text, oneTap: true, kind: q.kind, text: els.agent.textContent + ' waits for you. After you answer it continues in the same conversation.', options};
      if (window.QuestionCard) {
        window.QuestionCard.mount(node, question, {send: async (answer) => {
          const r = await act('answer', {ticket: TID, question: q.id, answer});
          return r.ok ? {status: 200, who: 'you', via: 'focus'} : {status: r.status === 409 ? 409 : (r.status || 0), message: r.message};
        }});
      }
      const own = node.querySelector('.qoptions .quiet');
      if (own) own.textContent = 'Write your own…';
      const card = node.querySelector('.qcard');
      if (card) card.prepend(h('p', {class: 'meta', text: 'Next step · Answer ' + els.agent.textContent}));
      const receipt = h('span', {class: 'fx-receipt', hidden: !delivered, title: 'Also sent to your phone', 'aria-label': 'Also sent to your phone', role: 'img'});
      receipt.innerHTML = '<svg width=16 height=16 viewBox="0 0 24 24" fill=none stroke=currentColor stroke-width=1.5 aria-hidden=true><rect x=7 y=2 width=10 height=20 rx=2 /><path d="M10 18h4" /></svg>';
      (card || node).append(receipt);
      S.state.shownQs.set(q.id, {node, receipt});
      if (!S.state.firstRender && window.orch) window.orch.needsIn(node);
    }
  }

  function renderLine(v) {
    const u = v.board.usage, d = v.board.denials;
    const lines = [];
    if (u) lines.push(h('p', {class: 'fx-line ' + (u.status === 'limited' ? 'bad' : 'warn'), text: u.text}));
    if (v.attention) lines.push(h('p', {class: 'fx-line warn'}, (v.why || 'Waiting for your OK in the live session.') + ' ', h('button', {class: 'btn ghost xs', 'data-act': 'attach', text: 'Open live session'})));
    if (v.retry_error) lines.push(h('p', {class: 'fx-line bad', text: 'Could not run it again: ' + v.retry_error}));
    if (d.length) lines.push(h('p', {class: 'fx-line warn', text: d[d.length - 1].text + '. It waits for your OK.'}));
    els.line.replaceChildren(...lines);
  }

  function focusQuestion() {
    const host = els.qs.querySelector('button,input,textarea') || els.qs;
    els.qs.scrollIntoView({block: 'center'});
    if (host === els.qs) els.qs.tabIndex = -1;
    host.focus();
  }
  async function stopToggle() {
    if (!S.state.view) return;
    if (!S.state.view.run.running && S.state.view.ticket.questions.some(q => q.answer == null)) { focusQuestion(); return; }
    const r = S.state.view.run.running ? await act('run.stop', {ticket: TID}) : await act('run.start', {ticket: TID});
    if (!r.ok) toast(r.message, 'error'); else toast(S.state.view.run.running ? 'Started. Same conversation.' : 'Stopped. The work done so far is kept.', 'ok');
  }
  async function startFresh() { const r = await act('run.start', {ticket: TID, fresh: true}); if (!r.ok) toast(r.message, 'error'); else toast('Started fresh from the ticket.', 'ok'); }
  function renderWorking(v) {
    const running = v.run.running;
    els.working.hidden = true;
    els.working.replaceChildren(...(running && v.board.step ? [h('span', {class: 'fx-dot'}), h('span', {text: v.board.step})] : []));
  }

  S.register('live', {plainLine, feedItems, renderFeed, renderQuestions, renderLine, focusQuestion, stopToggle, startFresh, renderWorking});
})();
