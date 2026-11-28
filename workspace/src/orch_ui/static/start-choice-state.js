/* The Start choice, no DOM (ORCH-485, owner decision ORCH-483). One click on the main button starts the usual way:
   Continue when an earlier session can be picked up, else Start (fresh, usual tool and model). The caret opens the
   Start choice: continue, fresh start with tool and model, an earlier session; how many helper places are in use.
   While it starts the button says Starting… until the helper runs; a double click (or a second button for the same
   ticket) starts one run; a choice that is greyed says why.
   Everything goes through the dashboard's existing start path: run.start (= orch run start, --fresh, --agent),
   ticket.model (= orch ticket model) and session.reopen (= orch run start --session). The server refuses a second
   start under the ticket lock ("already working on this ticket"); that reply to a second click is quiet.
   The send function and the clock are injected so tests need no browser and no real time. */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.StartChoiceState = api;
})(typeof self !== 'undefined' ? self : this, function () {
  const MODELS = [['sonnet', 'Sonnet'], ['opus', 'Opus'], ['haiku', 'Haiku'], ['fable', 'Fable']];
  const KEEP = 10; /* orch keeps the last 10 sessions of a ticket on this computer */
  const STARTING_MS = 60000; /* no helper seen a minute after the start: stop saying Starting… and say so */
  const plural = (n, one, many) => n + ' ' + (n === 1 ? one : many);

  /* Helper places: how many are in use (live and one-step helpers), the most allowed (null = no limit), who waits in line. */
  function places(runs, settings, line) {
    const rows = runs && typeof runs === 'object' ? Object.values(runs) : [];
    const used = rows.filter(r => r && r.running === true).length; /* one-step helpers hold a place too (ORCH-1677) */
    const max = Number.isInteger(settings && settings.live_max) && settings.live_max > 0 ? settings.live_max : null;
    const waiting = Array.isArray(line && line.waiting) ? line.waiting.filter(x => typeof x === 'string') : [];
    return {used, working: rows.filter(atWork).length, max, waiting, full: max !== null && used >= max};
  }
  /* ORCH-2314: a helper that sits idle at its prompt, is stuck or waits for the person holds a place but is not
     "working": three idle helpers read "3 helpers working". An older core without the helper state counts as before. */
  const atWork = r => !!r && r.running === true && (!r.helper || typeof r.helper.state !== 'string' || ['working', 'starting'].includes(r.helper.state));
  const working = p => Number.isInteger(p.working) ? p.working : p.used;
  /* The places line above the choices, in plain words with the right singular and plural. */
  function placesText(p) {
    const wait = p.waiting.length ? plural(p.waiting.length, 'ticket waits', 'tickets wait') + ' in line.' : '';
    if (p.max === null) {
      // ORCH-1664: "open" was unclear (a closed session's pane said "1 helper open"): what they do, in plain words
      const now = working(p) ? plural(working(p), 'helper is', 'helpers are') + ' working now.' : 'No helper is working now.';
      return [now, wait].filter(Boolean).join(' ');
    }
    if (p.full) return [(p.max === 1 ? 'The one helper place is in use.' : 'All ' + p.max + ' helper places are in use.'), wait,
      'A start waits in line and begins by itself when a place is free.'].filter(Boolean).join(' ');
    return ['A start uses 1 of ' + plural(p.max, 'helper place', 'helper places') + '. Now ' + p.used + ' of ' + p.max + ' ' +
      (p.used === 1 ? 'is' : 'are') + ' in use.', wait].filter(Boolean).join(' ');
  }
  /* The short places line in the Start choice's header (owner, ORCH-484): "4 of 6 places in use"; the full sentence
     when every place is taken (a start then waits in line); '' when there is no limit and no helper works (an idle
     helper is not working, ORCH-2314). */
  function placesShort(p) {
    if (p.full) return placesText(p);
    const wait = p.waiting.length ? ' · ' + plural(p.waiting.length, 'ticket waits', 'tickets wait') : '';
    if (p.max === null) return working(p) ? plural(working(p), 'helper', 'helpers') + ' working' + wait : wait.slice(3);
    return p.used + ' of ' + p.max + ' places in use' + wait;
  }
  /* Where this ticket stands in the line ({at:2, of:3}), or null when it does not wait. */
  function inLine(p, id) {
    const at = p.waiting.indexOf(id);
    return at < 0 ? null : {at: at + 1, of: p.waiting.length};
  }
  /* The tools a fresh start can run on (found on this computer) and the usual one (chosen for this workspace). */
  function tools(agents) {
    const list = (Array.isArray(agents) ? agents : []).filter(a => a && typeof a.name === 'string' && a.found !== false)
      .map(a => ({name: a.name, label: String(a.label || a.name), models: a.models === true, chosen: a.chosen === true}));
    const usual = ((list.find(t => t.chosen) || list[0] || null) || {}).name || '';
    return {tools: list, usual};
  }
  /* The model the ticket runs on now: a person's choice, orch's pick, else Sonnet (orch's small first pick). */
  function model(t) {
    const m = t && t.model, name = m && MODELS.some(x => x[0] === m.name) ? m.name : '';
    return {name: name || 'sonnet', auto: !name || m.by === 'orch'};
  }
  /* What a fresh start sends: the tool only when it is not the usual one, the model only when the person changed it. */
  function freshOps(ticket, pick, usualTool, cur) {
    const ops = [];
    if (pick.model && pick.model !== cur.name) ops.push(['ticket.model', {ticket, model: pick.model}]);
    ops.push(['run.start', {ticket, fresh: true, ...(pick.tool && pick.tool !== usualTool ? {agent: pick.tool} : {})}]);
    return ops;
  }
  /* One earlier session as the list shows it (GET /api/sessions/<ticket> rows); `when` formats the time. */
  function sessionRow(r, now, when) {
    const at = r.last_used ? new Date(r.last_used) : null;
    const day = at && !isNaN(at) ? (when ? when(at, now) : at.toISOString().slice(0, 16).replace('T', ' ')) : 'Earlier';
    const here = !!(r.reopenable || r.current);
    const facts = [r.turns ? plural(r.turns, 'message', 'messages') : (here ? 'No messages' : ''), r.label].filter(Boolean);
    /* the one in use, still on this computer: a plain start continues it (the server never marks it reopenable) */
    const cont = !!(r.current && r.readable !== false);
    return {id: r.id, agent: r.agent, day, title: r.title || 'No first message', facts: facts.join(' · '), current: !!r.current, reopen: !!r.reopenable, cont,
      why: r.current ? '' : r.reopenable ? '' : 'On another computer, so it cannot be reopened here.'};
  }
  /* The earlier sessions: loading, error, empty or list; newest first, at most 10. */
  function sessions(data, now, when) {
    if (!data) return {state: 'loading', rows: []};
    if (data.available === false) return {state: 'error', rows: []};
    const rows = (Array.isArray(data.sessions) ? data.sessions : []).slice(0, KEEP).map(r => sessionRow(r, now, when));
    return {state: rows.some(r => !r.current) ? 'list' : 'empty', rows};
  }
  /* The last conversation Continue picks up, or null: the session in use when it is on this computer (a stopped helper
     keeps it; a plain start continues it), else the newest earlier session that can be reopened here. */
  function last(rows) {
    const list = Array.isArray(rows) ? rows : [];
    return list.find(r => r.cont) || list.find(r => r.reopen) || null;
  }
  /* The main button (owner, ORCH-483): Continue when an earlier session can be reopened, else Start on the usual tool
     and model. Both send run.start without --fresh: orch continues the last conversation when there is one, else it
     starts fresh, so a click while the list still loads does the right thing. `label` is the page's own word for a
     plain start ("Start helper", "Send and start helper"); `continueLabel` the one when it continues. */
  function main(view, o) {
    o = o || {};
    const can = !!last(view && view.rows);
    return {what: can ? 'continue' : 'start', label: can ? (o.continueLabel || 'Continue') : (o.label || 'Start helper')};
  }
  /* Why a choice is greyed, in one plain sentence, or '' when it can be used.
     what: 'main' | 'continue' | 'fresh' | 'reopen' | 'model';  ctx: {starting, running, inLine, tools, tool, row}. */
  function why(what, ctx) {
    ctx = ctx || {};
    if (ctx.starting) return 'The helper is starting.';
    if (ctx.running) return what === 'reopen' ? 'Stop the helper to reopen an earlier session.' : 'A helper is already working on this ticket.';
    if (what !== 'model' && ctx.unavailable) return ctx.unavailable;
    if (ctx.inLine) return 'This ticket already waits in line. It starts by itself when a place is free.';
    if (what === 'fresh' || what === 'main') {
      if (ctx.tools && !ctx.tools.tools.length) return 'No helper tool is set up yet.';
    }
    if (what === 'model' && ctx.tool && !ctx.tool.models) return 'This tool uses its own model.';
    if (what === 'reopen' && ctx.row) return ctx.row.current ? 'This session is in use now.' : (ctx.row.why || '');
    return '';
  }
  /* A start that orch put in line answers with a refusal saying so: that is not a failure. */
  const queued = text => /waits in line/i.test(String(text || ''));
  /* A second start while one runs: the server refuses under the ticket lock. To a double click that is quiet. */
  const busy = text => /already working on this ticket/i.test(String(text || ''));

  /* The starter: one per page. start(ticket, ops) runs the ops in order through send(op, args) -> {ok, text}; a
     second start for a ticket that is starting does nothing (a double click, or another button for the same ticket).
     The ticket stays Starting until seen(ticket, true) says its helper runs, the server refused or STARTING_MS passed.
     Subscribers get every change: f({ticket, state, text}) with state starting | started | queued | quiet | failed | slow. */
  function starter(opts) {
    const send = opts.send;
    /* the slow timer never keeps a process alive (node tests); in a browser unref does not exist */
    const clock = opts.clock || {setTimeout: (f, ms) => { const id = setTimeout(f, ms); if (id && id.unref) id.unref(); return id; }, clearTimeout: id => clearTimeout(id)};
    const ms = opts.startingMs || STARTING_MS;
    const on = new Map(); /* ticket -> {timer, sent} */
    const subs = [];
    const tell = (ticket, state, text, rest) => subs.forEach(f => f(Object.assign({ticket, state, text: text || ''}, rest ? {rest} : {})));
    function end(ticket) {
      const s = on.get(ticket);
      if (!s) return false;
      clock.clearTimeout(s.timer);
      on.delete(ticket);
      return true;
    }
    async function start(ticket, ops) {
      if (!ticket || on.has(ticket)) return {ok: true, again: true};
      const s = {timer: null, sent: false};
      on.set(ticket, s);
      tell(ticket, 'starting');
      let r = {ok: true}, done = 0;
      try {
        for (const [op, args] of ops) {
          r = await send(op, args);
          if (!r || !r.ok) break;
          done++;
        }
      } catch (e) {
        r = {ok: false, text: ''};
      }
      r = r || {ok: false};
      if (on.get(ticket) !== s) return r; /* the helper was seen before the reply came */
      if (r.ok) {
        s.sent = true;
        s.timer = clock.setTimeout(() => { if (end(ticket)) tell(ticket, 'slow', 'The helper did not show up yet. Look again in a moment.'); }, ms);
        tell(ticket, 'started');
        return r;
      }
      end(ticket);
      if (queued(r.text)) tell(ticket, 'queued', r.text);
      else if (busy(r.text)) tell(ticket, 'quiet', r.text);
      else tell(ticket, 'failed', r.text || 'Could not start the helper.', ops.slice(done)); /* rest: what Try again sends (ORCH-1362) */
      return r;
    }
    /* The page saw the ticket's helper (state.runs): it runs, so Starting ends. */
    function seen(ticket, running) {
      if (running && end(ticket)) tell(ticket, 'running');
    }
    return {
      start, seen,
      starting: ticket => on.has(ticket),
      subscribe(f) { subs.push(f); return () => { const i = subs.indexOf(f); if (i >= 0) subs.splice(i, 1); }; },
    };
  }

  return {MODELS, KEEP, STARTING_MS, places, placesText, placesShort, inLine, tools, model, freshOps, sessionRow, sessions, last, main, why,
    queued, busy, starter};
});
