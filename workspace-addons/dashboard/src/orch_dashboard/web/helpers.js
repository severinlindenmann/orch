'use strict';
// Pure helpers of the dashboard page (no DOM), so node can test them.
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.DashHelpers = api;
})(typeof self !== 'undefined' ? self : this, function () {
  const arr = v => Array.isArray(v) ? v : [];
  const STATUS_WORD = {open: 'Not started', ready: 'Not started', active: 'Working', waiting: 'Needs you', review: 'Ready for review', done: 'Done', dropped: 'Dropped'};
  /* The ONE source of status words and order (board columns, Home, ticket page, Move to, history, lists).
     Lifecycle order. "ready" is the same place as "open" (no separate word); "waiting" shows as "Needs you". */
  const STATUS_ORDER = ['open', 'active', 'waiting', 'review', 'done'];
  const statusWord = (status, started) => (status === 'open' || status === 'ready') && started === true ? 'Paused' : STATUS_WORD[status] || 'Not started';
  const columnOf = status => status === 'ready' ? 'open' : status;
  const STATUS_CHOICES = STATUS_ORDER.map(s => [s, STATUS_WORD[s]]);
  // "Move to" offers four places; Waiting is decided by the agent.
  const MOVE_CHOICES = STATUS_CHOICES.filter(([s]) => s !== 'waiting');
  const FIELD_WORD = {title: 'the title', owner: 'the owner', due: 'the due day', note: 'the note', summary: 'the summary',
    status: 'the status'};

  /* One plain line for a history entry. The common words the CLI writes become sentences; anything else is shown as
     written (the caller still strips ids). */
  /* The one place a raw actor id inside a line ("agent:<name>", "human:<name>") becomes the name a person reads. */
  function plainNames(text) {
    return String(text ?? '').replace(/\b(?:agent|human):([A-Za-z0-9_.@-]+)/g, (_, n) => n.charAt(0).toUpperCase() + n.slice(1));
  }

  /* A task finished by the agent is written twice (orch's own "Check c1 done" and the agent's own note): both read
     "Finished a task: ...". Within two minutes the longer of two equal-or-prefix lines stays, once. Original order kept. */
  function dedupeHistory(entries, checklist) {
    const list = Array.isArray(entries) ? entries : [], drop = new Set(), last = [];
    const order = list.map((e, i) => [e, i]).sort((a, b) => (Date.parse(a[0] && a[0].at) || 0) - (Date.parse(b[0] && b[0].at) || 0) || a[1] - b[1]);
    for (const [e] of order) {
      const line = historyLine(e, checklist), at = Date.parse(e && e.at) || 0;
      const dup = last.find(p => Math.abs(at - p.at) <= 120000 && (p.line === line || line.startsWith(p.line + ':') || p.line.startsWith(line + ':')));
      if (!dup) { last.push({e, line, at}); continue; }
      if (line.length > dup.line.length) { drop.add(dup.e); Object.assign(dup, {e, line, at}); } else drop.add(e);
    }
    return list.filter(e => !drop.has(e));
  }

  /* The sidebar footer: the relay add-on's saved connection (the same fact Settings shows as "Connected"). */
  function footerState(state, snapshot) {
    if (snapshot) return 'Shared copy';
    const relay = ((state && state.settings && state.settings.addons) || []).find(a => a && a.name === 'relay' && a.active && a.detail);
    if (!relay) return 'Local workspace';
    return relay.detail.connected ? 'Connected' : 'Not connected yet';
  }

  function historyLine(entry, checklist) {
    const text = String((entry && entry.text) ?? '').trim();
    let m;
    // the lines orch writes itself (same words as the CLI): a task line names the task, add-on settings their add-on
    const task = id => { const c = (Array.isArray(checklist) ? checklist : []).find(x => x && x.id === id); return c && c.text ? ': ' + c.text : ''; };
    const addon = key => key.replace(/-/g, ' ').replace(/^./, c => c.toUpperCase());
    if ((m = /^Added check (c\d+)$/.exec(text))) return 'Added a task' + task(m[1]);
    if ((m = /^Marked (c\d+) as won't do$/.exec(text))) return "Marked as won't do" + task(m[1]);
    if ((m = /^Check (c\d+) done$/.exec(text))) return 'Finished a task' + task(m[1]);
    if ((m = /^Set ext\.([a-z][a-z0-9-]*)$/.exec(text))) return 'Updated ' + addon(m[1]) + ' settings';
    if ((m = /^Removed ext\.([a-z][a-z0-9-]*)(\.[\w-]+)?$/.exec(text))) return 'Removed ' + addon(m[1]) + ' settings';
    if (/^Created/.test(text)) return /under /.test(text) ? 'Created as a sub-ticket' : 'Ticket created';
    if ((m = /^Edited (.+)$/.exec(text))) {
      const parts = m[1].split(/,\s*/).map(f => FIELD_WORD[f.trim()] || f.trim());
      return 'Changed ' + (parts.length > 1 ? parts.slice(0, -1).join(', ') + ' and ' + parts[parts.length - 1] : parts[0]);
    }
    if (/^Asked\b/.test(text)) return 'Asked a question';
    if (/^Answered q\d+/.test(text)) return 'Answered a question';
    if ((m = /^(?:Patched status \(status|Status) \w+ -> (\w+)/.exec(text))) return 'Moved to ' + (STATUS_WORD[m[1]] || m[1]);
    if (/^Summary/.test(text)) return 'Updated the summary';
    if ((m = /^Added (?:task|check)[:\s]+(.+)$/i.exec(text))) return 'Added a task: ' + m[1];
    if ((m = /^Finished a task[:\s]+(.+)$/i.exec(text))) return 'Finished a task: ' + m[1];
    if (/^(Updated|Removed) .+ settings$/.test(text)) return text;
    if (/^Check c\d+ done/i.test(text) || /^(Checked|Done)\b.*\bc\d+/.test(text) || /^Task .* done/i.test(text)) return 'Finished a task';
    if (/^Added task|^Added check/i.test(text)) return 'Added a task';
    if (/^Linked|^Link added/i.test(text)) return 'Added a reference';
    return plainNames(text);
  }

  /* Plain words for a failure or notice: never a raw ticket id, an internal actor name (agent:/human:) or a UTC time.
     A conflict ("was changed by agent:<name> at 12:08") becomes "<Name> just changed this ticket - updated." */
  function titleCase(n) { return String(n || '').replace(/[_.-]+/g, ' ').trim().replace(/^./, c => c.toUpperCase()); }
  function scrubText(text) {
    const raw = String(text ?? '');
    const m = /\bchanged by (?:(agent|human):)?([A-Za-z0-9_.@ -]*?)(?: at \d{1,2}:\d{2})?\s*\.?(?:\s|$)/.exec(raw);
    if (/\bwas changed by\b/.test(raw) && m) return (m[2] && m[1] !== 'human' ? titleCase(m[2]) : 'Someone') + ' just changed this ticket — updated.';
    return plainNames(raw)
      .replace(/\s+(?:at|since|on)\s+\d{1,2}:\d{2}(?::\d{2})?(?:\s*(?:UTC|Z))?/g, '')
      .replace(/\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?Z?/g, '')
      .replace(/\bt_[A-Za-z0-9]+\b/g, 'this ticket')
      .replace(/\s*Reload the page and try again\./g, '')
      .replace(/\s{2,}/g, ' ').trim();
  }

  /* Who a history line is about: "You" for the current person, the display name otherwise. */
  function historyWho(by, me) {
    const b = String(by || '');
    if (me && b === me) return 'You';
    return titleCase(b.replace(/^(?:agent|human):/, '')) || 'Someone';
  }
  /* The history of a ticket as plain rows {entry, who, line, sentence}. Person actions on the status or fields become one
     sentence ("You asked for changes: <note>"); the "Change: <note>" task that went with it is folded into that sentence. */
  function historyView(entries, checklist, me) {
    const list = dedupeHistory(entries, checklist), out = [];
    const noteFor = (entry) => {
      const at = Date.parse(entry && entry.at) || 0;
      for (const e of list) {
        const m = /^Added check (c\d+)$/.exec(String((e && e.text) || '').trim());
        const c = m && (Array.isArray(checklist) ? checklist : []).find(x => x && x.id === m[1]);
        if (c && /^Change: /.test(c.text || '') && Math.abs((Date.parse(e.at) || 0) - at) <= 120000) return {entry: e, note: c.text.slice(8)};
      }
      return null;
    };
    const hidden = new Set();
    for (const e of list) {
      const text = String((e && e.text) || '').trim(), by = String((e && e.by) || '');
      const who = historyWho(by, me);
      let sentence = null, m;
      if (by.startsWith('human:')) {
        if ((m = /^Asked for changes(?:: ([\s\S]*))?$/.exec(text))) {
          const n = noteFor(e);
          if (n) hidden.add(n.entry);
          const note = m[1] || (n && n.note) || '';
          sentence = who + ' asked for changes' + (note ? ': ' + note : '');
        } else
        if ((m = /^(?:Patched status \(status|Status) (\w+) -> (\w+)\)?$/.exec(text))) {
          if (m[1] === 'review' && m[2] === 'active') {
            const n = noteFor(e);
            if (n) hidden.add(n.entry);
            sentence = who + ' asked for changes' + (n && n.note ? ': ' + n.note : '');
          } else if (m[2] === 'done') sentence = who + ' marked it Done';
          else sentence = who + ' moved it to ' + (STATUS_WORD[m[2]] || m[2]);
        } else if ((m = /^Patched ([a-z_, ]+?)(?: \(status \w+ -> (\w+)\))?$/.exec(text))) {
          const parts = m[1].split(/,\s*/).map(f => FIELD_WORD[f.trim()] || f.trim());
          sentence = who + ' changed ' + (parts.length > 1 ? parts.slice(0, -1).join(', ') + ' and ' + parts[parts.length - 1] : parts[0]) + (m[2] ? ' and moved it to ' + (STATUS_WORD[m[2]] || m[2]) : '');
        }
      }
      out.push({entry: e, who, line: historyLine(e, checklist), sentence});
    }
    return out.filter(r => !hidden.has(r.entry));
  }

  /* The answer that is already there for a question (someone else was first). Null when it is still open. */
  function winningAnswer(tickets, ticketId, questionId) {
    const t = arr(tickets).find(x => x && x.id === ticketId);
    const q = arr(t && t.questions).find(x => x && x.id === questionId);
    if (!q || q.answer == null) return null;
    return {text: String(q.answer), who: q.answered_by || '', via: q.via || ''};
  }

  /* The rows of "Needs you", each thing that needs the person exactly once: the same row id, or the same question of
     the same ticket (a core row and an add-on row for it), counts once. The Home badge and the list use this one list. */
  function uniqueNeeds(rows) {
    const seen = new Set(), out = [];
    for (const r of arr(rows)) {
      if (!r) continue;
      const q = r.answer && r.answer.question;
      const key = r.ticket && q ? 'q:' + r.ticket + ':' + q : 'id:' + r.id;
      if (seen.has(key)) continue;
      seen.add(key); out.push(r);
    }
    return out;
  }

  /* True when "Needs you" already lists a question of this ticket (the question text is shown there only). */
  function inNeeds(rows, ticketId) {
    return arr(rows).some(r => r && r.ticket === ticketId && r.answer && r.answer.question);
  }

  /* The one button of a "Needs you" row. kind: answer (opens the question card), review (an add-on's own question),
     run (start the work again) or open (the ticket). */
  function needAction(row) {
    const r = row || {};
    const answerable = !!r.answer && r.kind !== 'overdue-wait';
    if (answerable && /^[a-z][a-z0-9-]*:/.test(String(r.kind || ''))) return {label: 'Review', kind: 'review'};
    if (answerable) return {label: 'Answer', kind: 'answer'};
    if (r.tone === 'bad' && r.ticket) return {label: 'Run again', kind: 'run'};
    return {label: 'Open', kind: 'open'};
  }

  /* Agents card: who works, who waits for the person, who is idle. Working comes from `runs`, idle from the
     tickets' sessions (newest session per agent that is not working now). */
  function agentRows(tickets, runs, nowMs) {
    const out = [], busy = new Set();
    for (const [tid, run] of Object.entries(runs || {})) {
      if (!run || (run.running !== true && run.state !== 'maybe-stale')) continue;
      const t = arr(tickets).find(x => x.id === tid);
      const agent = (run.claim && (run.claim.agent || run.claim.by)) || 'agent';
      const asks = arr(t && t.questions).some(q => q && q.answer == null);
      busy.add(String(agent).replace(/^(agent|human):/, ''));
      const idle = !asks && run.state !== 'maybe-stale' && run.claim && run.claim.live && run.claim.live.state === 'idle';  // a live session waiting for a message
      out.push({agent: String(agent).replace(/^(agent|human):/, ''), state: run.state === 'maybe-stale' ? 'stuck' : asks ? 'needs' : idle ? 'idle' : run.claim && run.claim.live && run.claim.live.state === 'starting' ? 'starting' : 'working',
        ticket: tid, since: idle ? run.claim.live.since : run.claim && run.claim.started_at});
    }
    const last = new Map();
    for (const t of arr(tickets)) for (const s of arr(t.sessions)) {
      const at = Date.parse(s && s.last_used);
      if (!s || !s.agent || Number.isNaN(at) || busy.has(s.agent)) continue;
      if (!last.has(s.agent) || at > last.get(s.agent).at) last.set(s.agent, {at, ticket: t.id});
    }
    for (const [agent, v] of last) if (nowMs - v.at >= 0) out.push({agent, state: 'idle', ticket: v.ticket, since: new Date(v.at).toISOString()});
    const rank = {needs: 0, stuck: 1, working: 2, starting: 2, idle: 3};
    return out.sort((a, b) => rank[a.state] - rank[b.state]);
  }

  /* Links to other running pages of this workspace (label and address come from the services data). */
  function serviceLinks(services, ownOrigin) {
    return arr(services).filter(s => s && s.running === true && typeof s.url === 'string' && /^http:\/\/(127\.0\.0\.1|localhost):\d{1,5}\/?$/.test(s.url)
      && !s.url.startsWith(ownOrigin) && /^[a-z][a-z0-9-]{1,31}$/.test(String(s.addon || s.name)))
      .map(s => ({label: String(s.addon || s.name), url: s.url}));
  }

  const noPrefix = v => String(v || '').replace(/^(agent|human):/, '');
  const capital = v => String(v || '').charAt(0).toUpperCase() + String(v || '').slice(1);
  const minutes = ms => Math.max(0, Math.round(ms / 60000));
  const span = ms => { const m = minutes(ms); return m < 1 ? 'just now' : m < 60 ? m + ' min' : m < 1440 ? Math.round(m / 60) + ' h' : Math.round(m / 1440) + ' days'; };

  function agentLabel(settings, claim = {}) {
    claim = claim || {};
    const agents = arr(settings && settings.agents).filter(Boolean);
    const match = agents.find(a => a.name === claim.agent);
    const chosen = agents.find(a => a.chosen);
    return capital(noPrefix(claim.label || match?.label || claim.agent || chosen?.label || chosen?.name || agents[0]?.label || agents[0]?.name || 'Agent'));
  }
  const matchesTicket = (ref, t) => !!ref && (ref === t.id || (!!t.key && String(ref).toLowerCase() === String(t.key).toLowerCase()));
  function childrenOf(all, t) {
    const seen = new Set();
    return arr(all).filter(c => c && c.id !== t.id && (matchesTicket(c.parent, t) || arr(t.children).includes(c.id)) && !seen.has(c.id) && seen.add(c.id));
  }
  function parentOf(all, t) {
    return arr(all).find(p => p && p.id !== t.id && matchesTicket(t.parent, p)) ||
      arr(all).find(p => p && p.id !== t.id && arr(p.children).includes(t.id)) || null;
  }
  const plainFileName = value => String(value || '').split(/[\\/]/).pop().replace(/\.[^.]+$/, '').replace(/[-_]+/g, ' ').replace(/^./, c => c.toUpperCase());
  const cleanOutcome = value => String(value || '').replace(/\b\d+(?:\.\d+)?\s*(?:[KMGT]?i?B|bytes?)\b/gi, '').replace(/(?:[\w-]+\/)*[\w-]+\.(?:md|txt|html?|csv|json|pdf|png|jpe?g|webp)\b/gi, name => plainFileName(name)).replace(/^[\s✓✔·—,:;-]+|[\s·—,:;-]+$/g, '').replace(/\s+/g, ' ').trim();
  const resolved = task => !!(task.done || task.wont_do);
  function outcome(task) {
    if (task.wont_do) return "";
    const said = arr(task.evidence).slice().reverse().map(ev => cleanOutcome(ev.summary) || cleanOutcome(ev.text) || (ev.type === 'note' ? cleanOutcome(ev.ref) : '')).find(Boolean);
    return said || (task.done ? 'Completed.' : task.state === 'doing' ? 'Working on this task.' : 'Not started yet.');
  }

  /* The cause of a failed agent start in plain words ("the agent program was not found"), from waiting_on.ref. */
  function plainStartReason(ref) {
    const s = String(ref || '');
    const missing = /No such file or directory:?\s*'([^']+)'/i.exec(s) || /\[Errno 2\][^']*'([^']+)'/.exec(s);
    const program = missing && missing[1].split(/[\\/]/).pop();
    if (program && /^[A-Za-z0-9._-]{1,40}$/.test(program)) return 'the ' + program + ' program was not found';
    if (/Errno 13|Permission denied/i.test(s)) return 'it is not allowed to run';
    return 'it did not start';  // anything else (paths, commands, tokens) is never shown
  }

  /* {agent, reason, text} when the ticket waits because the agent could not be started (waiting_on.start), else null. */
  function startFailure(ticket, run, settings) {
    const t = ticket || {}, w = t.waiting_on;
    if (t.status !== 'waiting' || !w || w.start !== true || (run && run.running === true)) return null;
    const agent = agentLabel(settings, (run && run.claim) || {}), reason = plainStartReason(w.ref);
    return {agent, reason, text: agent + ' could not start: ' + reason};
  }

  /* The ONE agent line under the ticket title. state: working | starting | background | stuck | needs | failed | resume | new.
     primary = the main action {label, op, args} (op is a dashboard op, or "open" with a url); items = the rest, under "...". */
  function agentLine(ticket, run, nowMs, liveLink, settings) {
    const t = ticket || {}, r = run || null, id = t.id;
    const sessions = arr(t.sessions).slice().sort((a, b) => Date.parse(b.last_used || 0) - Date.parse(a.last_used || 0));
    const claim = (r && r.claim) || {};
    const agent = agentLabel(settings, claim);
    const asks = arr(t.questions).some(q => q && q.answer == null);
    const start = (label, extra) => ({label, op: 'run.start', args: {ticket: id, ...(extra || {})}});
    const stop = {label: 'Stop', op: 'run.stop', args: {ticket: id}};
    const fresh = {label: 'Start fresh', op: 'run.start', args: {ticket: id, fresh: true}};
    const since = claim.started_at ? ' · ' + span(nowMs - Date.parse(claim.started_at)) : '';
    // core: running is state == "alive"; a claim nobody renewed for a while is state "maybe-stale" with running false
    if (r && r.state === 'maybe-stale') return {state: 'stuck', agent, status: 'may be stuck · quiet for a while' + since,
      primary: start('Start anyway', {take_over: true}), items: [stop]};
    if (r && r.running === true) {
      const by = claim.by ? ' · started by ' + noPrefix(claim.by) : '';
      if (asks) return {state: 'needs', agent, status: 'needs your answer' + since, primary: {label: 'Answer', op: 'answer'}, items: [stop, fresh]};
      const waits = claim.live && claim.live.state === 'attention' ? (plainWhy(claim.live.why, agent) || 'waiting for your OK in the live session') : '';
      if (waits) return {state: 'needs', agent, status: waits, primary: liveLink ? {label: 'Open ' + liveLink.label, op: 'open', url: liveLink.url} : stop,
        items: liveLink ? [stop] : []};
      const live = liveLink ? {label: 'Open ' + liveLink.label, op: 'open', url: liveLink.url} : null;
      const hold = typeof r.hold === 'string' ? r.hold.replace(/\s+/g, ' ').trim().slice(0, 200) : '';
      if (hold) return {state: 'working', agent, status: hold, hold, primary: live || stop, items: live ? [stop] : []};  /* the core's words, as is */
      if (claim.live && claim.live.state === 'starting') return {state: 'starting', agent, status: 'Starting…', primary: live || stop, items: live ? [stop] : []};
      if (claim.mode === 'oneshot') return {state: 'background', agent, status: 'works in the background (no live view)' + since,
        primary: live ? {...live, label: 'Watch in ' + liveLink.label} : stop, items: live ? [stop] : []};
      if (claim.live && claim.live.state === 'idle') return {state: 'idle', agent, status: 'live session open, waiting for a message' + by, primary: live || stop, items: live ? [stop] : []};
      return {state: 'working', agent, status: 'working' + by + since, primary: live || stop, items: live ? [stop] : []};
    }
    const sf = startFailure(t, r, settings);
    if (sf) return {state: 'failed', agent, status: sf.text, startFailed: true, primary: start('Retry'), items: []};
    if (r && r.state === 'dead') return {state: 'failed', agent, status: 'the last run ended without finishing',
      primary: start('Try again'), items: [fresh]};
    if (asks) return {state: 'needs', agent, status: 'needs your answer', primary: {label: 'Answer', op: 'answer'}, items: [fresh]};
    if (sessions[0]) {
      const when = Date.parse(sessions[0].last_used);
      return {state: 'resume', agent, status: 'last worked ' + (Number.isNaN(when) ? 'earlier' : span(nowMs - when) === 'just now' ? 'just now' : span(nowMs - when) + ' ago'),
        primary: start('Continue'), items: [fresh]};
    }
    // a ticket already waiting for the person's check has no run to start: no Start button
    if (t.status === 'review') return {state: 'new', agent, status: 'ready for you to check', primary: null, items: []};
    return {state: 'new', agent, status: 'not started yet', primary: start('Start'), items: []};
  }

  /* The line under an agent's "waiting" chip, in plain words: no command text, a login named as signing in. */
  function plainWhy(why, label) {
    const w = String(why || '');
    if (/wants a login|log in to|login method/i.test(w)) return (label || 'The agent') + ' needs you to sign in';
    return plainNames(w).replace(/\s*(Open the live session[^:]*:\s*)?orch run attach\s+\S+/gi, '').replace(/\s+/g, ' ').trim().replace(/[.:]$/, '');
  }

  /* One line of the question a ticket waits on (the first open one), for under its title; '' when none. */
  function questionPreview(ticket) {
    const q = arr(ticket && ticket.questions).find(x => x && x.answer == null && x.text);
    const text = q ? String(q.text).replace(/\s+/g, ' ').trim() : '';
    return text.length > 90 ? text.slice(0, 89) + '…' : text;
  }

  /* One state per ticket: a ticket the agent cannot go on with (live state attention) is Waiting, never Working. */
  function shownStatus(ticket, run) {
    const t = ticket || {}, live = run && run.claim && run.claim.live;
    return t.status === 'active' && live && live.state === 'attention' ? 'waiting' : t.status;
  }

  /* True while the yellow "Needs you" chip shows (an open question, or the agent needs you): the plain
     Waiting status chip is then left out, so the ticket shows one chip. */
  function showsAnswerChip(ticket, run) {
    const t = ticket || {}, live = run && run.claim && run.claim.live;
    return arr(t.questions).some(q => q && q.answer == null) || !!(live && live.state === 'attention');
  }

  /* Tickets tab tree: parents with their children (N of M done), children beyond 3 collapsed, a child whose parent is
     missing is shown as a top-level ticket. Input order is kept. */
  function treeRows(tickets) {
    const all = arr(tickets), byId = new Map(all.map(t => [t.id, t]));
    const byKey = new Map(all.filter(t => t.key).map(t => [String(t.key).toLowerCase(), t.id]));
    // `parent` is a ticket id, but real data may carry the key ("PIL-2"): both name the same parent
    const pid = t => t.parent && (byId.has(t.parent) ? t.parent : byKey.get(String(t.parent).toLowerCase())) || null;
    const kids = new Map();
    for (const t of all) if (pid(t) && pid(t) !== t.id) {
      if (!kids.has(pid(t))) kids.set(pid(t), []);
      kids.get(pid(t)).push(t);
    }
    // Children in the order they were made (the order of the work), not the order the page lists tickets.
    const made = t => Date.parse(t.created_at) || 0;
    for (const list of kids.values()) list.sort((a, b) => made(a) - made(b) || String(a.id).localeCompare(String(b.id)));
    const seen = new Set(), out = [];
    const walk = (t, depth, idx) => {
      if (seen.has(t.id)) return;
      seen.add(t.id);
      const ch = kids.get(t.id) || [];
      const done = ch.filter(c => c.status === 'done').length;
      out.push({ticket: t, depth, children: ch.length, done, parentMissing: !!t.parent && !pid(t), late: depth > 0 && idx >= 3});
      ch.forEach((c, i) => walk(c, depth + 1, i));
    };
    for (const t of all) if (!pid(t) || pid(t) === t.id) walk(t, 0, 0);
    for (const t of all) walk(t, 0, 0);  // a parent cycle still shows its tickets
    return out;
  }

  /* "just now" under a minute, else "5 min ago" / "2 h ago" / "3 days ago"; "" for no date. */
  function ago(iso, nowMs) {
    const when = Date.parse(iso);
    if (Number.isNaN(when)) return '';
    const s = span(nowMs - when);
    return s === 'just now' ? s : s + ' ago';
  }
  /* When something was added, in the person's own time: "today 16:05", "yesterday 09:12", "5 Nov 09:12". */
  function stamp(iso, nowMs) {
    const d = new Date(iso), now = new Date(nowMs);
    if (!iso || Number.isNaN(d.getTime()) || Number.isNaN(now.getTime())) return '';
    const day = x => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
    const diff = Math.round((day(now) - day(d)) / 86400000);
    const two = n => String(n).padStart(2, '0'), time = two(d.getHours()) + ':' + two(d.getMinutes());
    if (diff === 0) return 'today ' + time;
    if (diff === 1) return 'yesterday ' + time;
    const month = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][d.getMonth()];
    return d.getDate() + ' ' + month + (d.getFullYear() !== now.getFullYear() ? ' ' + d.getFullYear() : '') + ' ' + time;
  }
  /* A file proof: its title or file name, the size core saved in `text`, and when it was added ("hello.txt · 1 KB · today 16:05"). */
  function fileProofLabel(ev, nowMs) {
    const e = ev || {}, base = String(e.ref || '').split(/[\\/]/).pop();
    return [e.title || base || 'File', e.text, e.at && nowMs != null ? stamp(e.at, nowMs) : ''].filter(Boolean).join(' · ');
  }
  /* FO-14: who stands behind a proof. */
  function proofMark(ev) {
    return String((ev && ev.by) || '').startsWith('human:') ? {mark: '●', label: 'You'} : {mark: '○', label: 'Agent says'};
  }
  /* Leaving the page: every answer still in its Undo window is sent now. entries: [{state, send}]. Returns how many. */
  function flushPending(entries) {
    let n = 0;
    for (const e of arr(entries)) {
      const st = e && e.state && e.state.getState ? e.state.getState() : null;
      if (!st || st.phase !== 'pending' || typeof e.send !== 'function') continue;
      const answer = st.answer;
      e.state.reset();
      e.send(answer);
      n++;
    }
    return n;
  }

  /* A cron line in plain words for the common shapes (else the line itself): "30 7 * * *" -> "Every day at 07:30". */
  function cronHuman(value) {
    const raw = String(value == null ? '' : value).trim(), f = raw.split(/\s+/);
    if (f.length !== 5) return raw;
    const [mi, hr, dom, mon, dow] = f, num = x => /^\d{1,2}$/.test(x);
    const at = () => String(hr).padStart(2, '0') + ':' + String(mi).padStart(2, '0');
    const days = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
    const every = /^\*\/(\d{1,2})$/.exec(mi);
    if (every && hr === '*' && dom === '*' && mon === '*' && dow === '*') return 'Every ' + every[1] + ' minutes';
    if (num(mi) && hr === '*' && dom === '*' && mon === '*' && dow === '*') return 'Every hour at :' + String(mi).padStart(2, '0');
    if (!num(mi) || !num(hr) || mon !== '*') return raw;
    if (dom === '*' && dow === '*') return 'Every day at ' + at();
    if (dom === '*' && dow === '1-5') return 'Weekdays at ' + at();
    if (dom === '*' && /^[0-7]$/.test(dow)) return 'Every ' + days[+dow] + ' at ' + at();
    if (num(dom) && dow === '*') return 'Every month on day ' + dom + ' at ' + at();
    return raw;
  }

  /* A text from the phone, as the workspace wrote it into the history (relay `_describe`), split into parts the page can
     show: {head, text, parts:[{type:'voice'|'photo'|'sound'|'file'|'location'|'feedback'|'pin'|'note', ...}]}.
     Files are only trusted when they sit in this ticket's files folder. */
  function phoneParts(text, tid) {
    const lines = String(text ?? '').split('\n');
    const first = /^From ([^:]{1,100}): (.*)$/.exec(lines[0] || '');
    if (!first) return null;
    const folder = '.orch/tickets/' + tid + '/files/';
    const out = {who: first[1], text: '', parts: []};
    const fileOf = rel => rel.startsWith(folder) && !rel.slice(folder.length).includes('..') && rel.length < 300 ? rel.slice(folder.length) : null;
    let m;
    for (const [i, raw] of [first[2], ...lines.slice(1)].entries()) {
      const line = raw.trimEnd();
      if (!line.trim()) continue;
      if ((m = /^Voice message \(([^)]*)\): "([\s\S]*)"$/.exec(line))) out.parts.push({type:'voice', lang:m[1], transcript:m[2]});
      else if (/^Voice message \(nothing could be understood\)$/.test(line)) out.parts.push({type:'voice', lang:'', transcript:''});
      else if ((m = /^(Photo|Voice recording|File): (\.orch\/\S.*)$/.exec(line)) && fileOf(m[2])) {
        const name = fileOf(m[2]);
        out.parts.push({type:m[1] === 'Photo' ? 'photo' : m[1] === 'Voice recording' ? 'sound' : 'file', name});
      } else if ((m = /^(Photo|Voice recording|File)(?: .*)?: could not be downloaded\.$/.exec(line)) || line === 'A file could not be saved.') out.parts.push({type:'note', text:'A file could not be loaded.'});
      else if ((m = /^Location: (-?[\d.]+), (-?[\d.]+)(?: \((.*)\))? - (https:\/\/maps\.apple\.com\/\?\S+)$/.exec(line))) out.parts.push({type:'location', lat:m[1], lon:m[2], label:m[3] || '', url:m[4]});
      else if ((m = /^Feedback on (.*?)(?: \(([A-Za-z0-9._:-]{1,12})\))?: (?:(\u{1F44D}) Looks good|changes wanted)$/u.exec(line))) out.parts.push({type:'feedback', title:m[1], rev:m[2] || '', approve:!!m[3]});
      else if ((m = /^ {2}(\d+|-)\. (.*)$/.exec(line))) {
        const w = /^(".*?"(?=: |$)|the page|page \d+|a page|the picture[^:]*)(?:: (.*))?$/.exec(m[2]);
        out.parts.push({type:'pin', n:m[1], where:w ? w[1] : '', said:w ? w[2] || '' : m[2]});
      } else if (/^ {2}\(\+\d+ more .* not shown\)$/.test(line) || /^\(Phone message /.test(line) || /^ {2}\(the rest is not shown\)$/.test(line)) continue;
      else if (i === 0) out.text = line === '(empty)' ? '' : line;  // the words the person typed
      else out.parts.push({type:'note', text:line.trim()});
    }
    return out;
  }

  // Narrow board: which column opens first, and the quiet label of a column chip.
  function firstColumnWithTickets(counts) {
    const keys = Object.keys(counts || {});
    return keys.find(k => counts[k] > 0) || keys[0] || '';
  }
  const needsYou = n => n + (n === 1 ? ' needs you' : ' need you');  // same words as the phone
  const columnChipLabel = (label, n) => n > 0 ? label + ' ' + n : label;

  return {resolved, agentLabel, childrenOf, parentOf, plainFileName, cleanOutcome, outcome, plainNames, scrubText, historyWho, historyView, dedupeHistory, footerState, STATUS_WORD, STATUS_ORDER, STATUS_CHOICES, MOVE_CHOICES, statusWord, columnOf, needsYou, uniqueNeeds, inNeeds, firstColumnWithTickets, columnChipLabel, phoneParts, cronHuman, flushPending, historyLine, winningAnswer, needAction, agentRows, serviceLinks, agentLine, startFailure, plainStartReason, plainWhy, questionPreview, shownStatus, showsAnswerChip, treeRows, proofMark, fileProofLabel, stamp, ago};
});
