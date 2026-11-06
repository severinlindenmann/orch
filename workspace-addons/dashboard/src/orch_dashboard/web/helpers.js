'use strict';
// Pure helpers of the dashboard page (no DOM), so node can test them.
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.DashHelpers = api;
})(typeof self !== 'undefined' ? self : this, function () {
  const arr = v => Array.isArray(v) ? v : [];
  const STATUS_WORD = {open: 'To do', active: 'Doing', waiting: 'Waiting', done: 'Done', dropped: 'Dropped'};
  const FIELD_WORD = {title: 'the title', owner: 'the owner', due: 'the due day', note: 'the note', summary: 'the summary',
    status: 'the status'};

  /* One plain line for a history entry. The common words the CLI writes become sentences; anything else is shown as
     written (the caller still strips ids). */
  function historyLine(entry, checklist) {
    const text = String((entry && entry.text) ?? '').trim();
    let m;
    // the lines orch writes itself (same words as the CLI): a task line names the task, add-on settings their add-on
    const task = id => { const c = (Array.isArray(checklist) ? checklist : []).find(x => x && x.id === id); return c && c.text ? ': ' + c.text : ''; };
    const addon = key => key.replace(/-/g, ' ').replace(/^./, c => c.toUpperCase());
    if ((m = /^Added check (c\d+)$/.exec(text))) return 'Added a task' + task(m[1]);
    if ((m = /^Check (c\d+) done$/.exec(text))) return 'Finished a task' + task(m[1]);
    if ((m = /^Set ext\.([a-z][a-z0-9-]*)$/.exec(text))) return 'Updated ' + addon(m[1]) + ' settings';
    if ((m = /^Removed ext\.([a-z][a-z0-9-]*)(\.[\w-]+)?$/.exec(text))) return 'Removed ' + addon(m[1]) + ' settings';
    if (/^Created/.test(text)) return /under /.test(text) ? 'Created as a sub-ticket' : 'Ticket created';
    if ((m = /^Edited (.+)$/.exec(text))) {
      const parts = m[1].split(/,\s*/).map(f => FIELD_WORD[f.trim()] || f.trim());
      return 'Changed ' + (parts.length > 1 ? parts.slice(0, -1).join(', ') + ' and ' + parts[parts.length - 1] : parts[0]);
    }
    if (/^Asked\b/.test(text)) return 'Asked a question';
    if (/^Answered\b/.test(text)) return 'Answered a question';
    if ((m = /^Status \w+ -> (\w+)/.exec(text))) return 'Moved to ' + (STATUS_WORD[m[1]] || m[1]);
    if (/^Summary/.test(text)) return 'Updated the summary';
    if ((m = /^Added (?:task|check)[:\s]+(.+)$/i.exec(text))) return 'Added a task: ' + m[1];
    if ((m = /^Finished a task[:\s]+(.+)$/i.exec(text))) return 'Finished a task: ' + m[1];
    if (/^(Updated|Removed) .+ settings$/.test(text)) return text;
    if (/^Check c\d+ done/i.test(text) || /^(Checked|Done)\b.*\bc\d+/.test(text) || /^Task .* done/i.test(text)) return 'Finished a task';
    if (/^Added task|^Added check/i.test(text)) return 'Added a task';
    if (/^Linked|^Link added/i.test(text)) return 'Added a link';
    return text;
  }

  /* The answer that is already there for a question (someone else was first). Null when it is still open. */
  function winningAnswer(tickets, ticketId, questionId) {
    const t = arr(tickets).find(x => x && x.id === ticketId);
    const q = arr(t && t.questions).find(x => x && x.id === questionId);
    if (!q || q.answer == null) return null;
    return {text: String(q.answer), who: q.answered_by || '', via: q.via || ''};
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
      out.push({agent: String(agent).replace(/^(agent|human):/, ''), state: run.state === 'maybe-stale' ? 'stuck' : asks ? 'needs' : 'working',
        ticket: tid, since: run.claim && run.claim.started_at});
    }
    const last = new Map();
    for (const t of arr(tickets)) for (const s of arr(t.sessions)) {
      const at = Date.parse(s && s.last_used);
      if (!s || !s.agent || Number.isNaN(at) || busy.has(s.agent)) continue;
      if (!last.has(s.agent) || at > last.get(s.agent).at) last.set(s.agent, {at, ticket: t.id});
    }
    for (const [agent, v] of last) if (nowMs - v.at >= 0) out.push({agent, state: 'idle', ticket: v.ticket, since: new Date(v.at).toISOString()});
    const rank = {needs: 0, stuck: 1, working: 2, idle: 3};
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

  /* The ONE agent line under the ticket title. state: working | starting | background | stuck | needs | failed | resume | new.
     primary = the main action {label, op, args} (op is a dashboard op, or "open" with a url); items = the rest, under "...". */
  function agentLine(ticket, run, nowMs, liveLink) {
    const t = ticket || {}, r = run || null, id = t.id;
    const sessions = arr(t.sessions).slice().sort((a, b) => Date.parse(b.last_used || 0) - Date.parse(a.last_used || 0));
    const claim = (r && r.claim) || {};
    const agent = capital(noPrefix(claim.agent || (sessions[0] && sessions[0].agent) || '')) || 'Agent';
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
      if (asks) return {state: 'needs', agent, status: 'waiting for your answer' + since, primary: {label: 'Answer', op: 'answer'}, items: [stop, fresh]};
      const waits = claim.live && claim.live.state === 'attention' ? String(claim.live.why || 'waiting for your OK in the live session') : '';
      if (waits) return {state: 'needs', agent, status: waits, primary: liveLink ? {label: 'Open ' + liveLink.label, op: 'open', url: liveLink.url} : stop,
        items: liveLink ? [stop] : []};
      const live = liveLink ? {label: 'Open ' + liveLink.label, op: 'open', url: liveLink.url} : null;
      if (claim.live && claim.live.state === 'starting') return {state: 'starting', agent, status: 'Starting…', primary: live || stop, items: live ? [stop] : []};
      if (claim.mode === 'oneshot') return {state: 'background', agent, status: 'works in the background (no live view)' + since,
        primary: live ? {...live, label: 'Watch in ' + liveLink.label} : stop, items: live ? [stop] : []};
      return {state: 'working', agent, status: 'working' + by + since, primary: live || stop, items: live ? [stop] : []};
    }
    if (r && r.state === 'dead') return {state: 'failed', agent, status: 'the last run ended without finishing',
      primary: start('Try again'), items: [fresh]};
    if (asks) return {state: 'needs', agent, status: 'waiting for your answer', primary: {label: 'Answer', op: 'answer'}, items: [fresh]};
    if (sessions[0]) {
      const when = Date.parse(sessions[0].last_used);
      return {state: 'resume', agent, status: 'last worked ' + (Number.isNaN(when) ? 'earlier' : span(nowMs - when) === 'just now' ? 'just now' : span(nowMs - when) + ' ago'),
        primary: start('Continue'), items: [fresh]};
    }
    return {state: 'new', agent, status: 'not started yet', primary: start('Start'), items: []};
  }

  /* Tickets tab tree: parents with their children (N of M done), children beyond 3 collapsed, a child whose parent is
     missing is shown as a top-level ticket. Input order is kept. */
  function treeRows(tickets) {
    const all = arr(tickets), byId = new Map(all.map(t => [t.id, t]));
    const kids = new Map();
    for (const t of all) if (t.parent && byId.has(t.parent) && t.parent !== t.id) {
      if (!kids.has(t.parent)) kids.set(t.parent, []);
      kids.get(t.parent).push(t);
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
      out.push({ticket: t, depth, children: ch.length, done, parentMissing: !!t.parent && !byId.has(t.parent), late: depth > 0 && idx >= 3});
      ch.forEach((c, i) => walk(c, depth + 1, i));
    };
    for (const t of all) if (!t.parent || !byId.has(t.parent) || t.parent === t.id) walk(t, 0, 0);
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
  /* A file proof: its title or file name, then the size core saved in `text` ("hello.txt · 1 KB"). */
  function fileProofLabel(ev) {
    const e = ev || {}, base = String(e.ref || '').split(/[\\/]/).pop();
    return [e.title || base || 'File', e.text].filter(Boolean).join(' · ');
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
  return {flushPending, historyLine, winningAnswer, needAction, agentRows, serviceLinks, agentLine, treeRows, proofMark, fileProofLabel, ago};
});
