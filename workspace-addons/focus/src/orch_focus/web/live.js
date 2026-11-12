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

  // agent: only the steps of that agent ('main' or a helper); the ticket's own lines belong to no agent.
  function feedItems(v, agent) {
    const items = [];
    if (!agent) for (const e of v.ticket.history || []) items.push({at: e.at, icon: /Asked|waiting/.test(e.text) ? 'note' : (/done/.test(e.text) ? 'check' : 'text'), ok: /done/.test(e.text), text: plainLine(String(e.text || ''), v.ticket.checklist), who: e.by, you: /^human:/.test(e.by || '') && e.via !== 'cli'});
    for (const e of v.events) {
      if (agent && (e.agent || 'main') !== agent) continue;
      const used = (e.data && e.data.used) || null, by = e.agent || 'main';
      if (e.kind === 'tool.start') items.push({at: e.at, icon: 'text', text: plainNames(e.text), used, agent: by});
      else if (e.kind === 'tool.end') items.push({at: e.at, icon: e.data.ok === false ? 'x' : 'check', ok: e.data.ok !== false, text: e.text, used, agent: by});
      else if (e.kind === 'helper.start') items.push({at: e.at, icon: 'user', text: 'Helper: ' + e.text, agent: by});
      else if (e.kind === 'helper.end') items.push({at: e.at, icon: 'check', ok: true, text: 'Helper done: ' + e.text, agent: by});
    }
    items.sort((a, b) => String(a.at).localeCompare(String(b.at)));
    return items.slice(-80);
  }
  const usedChip = used => (used && S.views.used ? S.views.used.chip(used) : null);

  /* The plain step list right under the task: the newest first and marked, each with what it used (never raw names). */
  function stepList(v, agent, max) {
    const items = feedItems(v, agent).slice(-max).reverse();
    if (!items.length) return null;
    return h('ol', {class: 'fx-now-steps', 'aria-label': 'Latest steps'}, items.map((it, i) => h('li', {class: 'fx-now-step' + (i === 0 ? ' newest' : '') + (it.ok === false ? ' bad' : '')},
      h('time', {datetime: it.at, text: hhmm(it.at)}), h('span', {class: 'fx-step-t'}, h('span', {text: it.text}), usedChip(it.used)))));
  }

  /* A helper picked in "Working on this": its own header, what it does now, and only its steps. */
  function helperView(v, agent) {
    const tree = (v.board && v.board.helper_tree) || [];
    const at = tree.findIndex(x => x.agent === agent), x = tree[at];
    const now = (v.board.agent_now || {})[agent];
    const nodes = [h('div', {class: 'fx-worker-h'},
      h('div', {class: 'fx-worker-name'}, h('h2', {text: 'Helper ' + (at + 1)}), h('span', {class: 'fx-role helper', text: 'HELPER'})),
      h('button', {type: 'button', class: 'btn ghost sm', 'data-act': 'all-work', text: '← All work'})),
    h('p', {class: 'fx-worker-task', text: plainNames(x.text) || 'A helper of ' + els.agent.textContent}),
    x.at ? h('p', {class: 'meta', text: 'Started ' + hhmm(x.at)}) : null];
    if (x.open && now) nodes.push(h('div', {class: 'fx-worker-now'}, h('span', {class: 'fx-worker-l', text: 'NOW'}), h('span', {text: plainNames(now)})));
    else nodes.push(h('div', {class: 'fx-worker-now done'}, h('span', {class: 'fx-worker-l', text: x.ok === false ? 'STOPPED' : 'DONE'}), h('span', {text: plainNames(x.result || now || 'Finished.')})));
    nodes.push(stepList(v, agent, 30) || h('p', {class: 'meta', text: 'No steps from this helper yet.'}));
    return nodes;
  }

  function renderFeed(v) {
    const key = keyOf([v.ticket.checklist, v.state, v.run.running, v.run.run, v.ticket.started, v.board.step, v.events, v.ticket.history, S.state.agentFilter || null, S.state.agentFilter ? [v.board.helper_tree, v.board.agent_now] : null]);
    if (key === S.state.lastFeedKey) return;
    S.state.lastFeedKey = key;
    const helper = S.state.agentFilter && S.state.agentFilter !== 'main' && ((v.board && v.board.helper_tree) || []).some(x => x.agent === S.state.agentFilter);
    els.feed.classList.toggle('fx-worker', !!helper);
    if (helper) {
      keepFocus(els.feed, () => els.feed.replaceChildren(...helperView(v, S.state.agentFilter).filter(Boolean)));
      return;
    }
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
    let now = null;
    for (const c of story) {
      const node = h('article', {class: 'fx-story' + (!c.done && v.run.running ? ' now' : '')},
        h('h3', {}, h('span', {text: (c.done ? '✓ ' : v.run.running ? 'Now: ' : '') + c.text})),
        h('p', {text: evText(c) || (!c.done && v.run.running ? v.board.step || 'Working on this task.' : '')}));
      if (!c.done && v.run.running && !now) now = node;
      nodes.push(node);
    }
    if (v.run.running && !now) nodes.push(now = h('article', {class: 'fx-story now'}, h('h3', {}, h('span', {text: v.board.step || 'Waiting for the first step…'}))));
    /* the step lines sit right under the task they belong to; while the agent rests, after the last task */
    const steps = stepList(v, 'main', 6);
    if (steps && now) now.append(steps);
    else if (steps) nodes.push(h('section', {class: 'fx-latest'}, h('h3', {text: 'Latest steps'}), steps));
    if (!v.run.running && !asking && v.state !== 'done' && v.ticket.status !== 'review' && !v.ticket.started && !v.run.run) nodes.push(h('button', {class: 'btn primary', 'data-act': 'stop', text: 'Start ' + els.agent.textContent}));
    /* Details: the full history, the ticket's own lines included */
    const details = h('details', {class: 'fx-history', open: !!S.state.detailsOpen}, h('summary', {text: 'Details'}));
    details.addEventListener('toggle', () => { S.state.detailsOpen = details.open; });  // a poll draws it again; it stays as the person left it
    for (const it of feedItems(v, null)) details.append(h('div', {class: 'fx-step'}, h('time', {text: hhmm(it.at)}), h('span', {icon: it.icon}), h('span', {class: 'fx-step-t'}, h('span', {text: it.text}), usedChip(it.used))));
    nodes.push(details);
    keepFocus(els.feed, () => els.feed.replaceChildren(...nodes));
  }

  // A poll draws the feed again; the keyboard stays on the same control (by its place among the controls).
  function keepFocus(box, draw) {
    const pick = () => [...box.querySelectorAll('button,summary,a[href]')];
    const at = box.contains(document.activeElement) ? pick().indexOf(document.activeElement) : -1;
    draw();
    if (at >= 0) pick()[at]?.focus();
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
          const r = await act('answer', {ticket: TID, question: q.id, digest: q.digest, answer});
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
