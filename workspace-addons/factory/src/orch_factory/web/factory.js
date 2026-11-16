/* Read-only Factory. All workspace content is inserted as text, never HTML. */
(() => {
  'use strict';
  const prefix = document.documentElement.dataset.prefix || '';
  const view = document.getElementById('factory-view');
  const notices = document.getElementById('notices');
  const validId = id => typeof id === 'string' && /^t_[a-z0-9]{6,16}$/.test(id);
  const validVersion = value => /^[1-9][0-9]*$/.test(String(value)) && Number.isSafeInteger(Number(value));
  const array = value => Array.isArray(value) ? value : [];
  const text = value => value === null || value === undefined ? '—' : String(value);
  const node = (tag, value, className) => {
    const el = document.createElement(tag);
    if (value !== undefined && value !== null) el.textContent = text(value);
    if (className) el.className = className;
    return el;
  };
  const group = (className, ...children) => { const el = node('div', null, className); el.append(...children); return el; };
  const p = value => node('p', value);
  const meta = value => node('p', value, 'meta');
  const badge = value => node('span', value, 'badge');
  const plural = (n, one, many) => n + ' ' + (n === 1 ? one : many);
  const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const pad = n => String(n).padStart(2, '0');
  function parseWhen(value) {
    if (typeof value !== 'string') return null;
    const day = /^(\d{4})-(\d\d)-(\d\d)$/.exec(value);
    if (day) return {date: new Date(+day[1], +day[2] - 1, +day[3]), dateOnly: true};
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? null : {date, dateOnly: false};
  }
  function dayWord(date) {
    const now = new Date();
    const diff = Math.round((new Date(date.getFullYear(), date.getMonth(), date.getDate()) - new Date(now.getFullYear(), now.getMonth(), now.getDate())) / 864e5);
    if (diff === 0) return 'today';
    if (diff === 1) return 'tomorrow';
    if (diff === -1) return 'yesterday';
    return date.getDate() + ' ' + MONTHS[date.getMonth()] + (date.getFullYear() === now.getFullYear() ? '' : ' ' + date.getFullYear());
  }
  const hhmm = date => pad(date.getHours()) + ':' + pad(date.getMinutes());
  // Local, human time: "today 18:30", "tomorrow 09:00", "16 Nov 19:18". Never a raw ISO string.
  function when(value) {
    const t = parseWhen(value);
    if (!t) return '—';
    return dayWord(t.date) + (t.dateOnly ? '' : ' ' + hhmm(t.date));
  }
  function whenRange(from, to) {
    const a = parseWhen(from), b = parseWhen(to);
    if (!a || !b) return when(from || to);
    if (a.date.toDateString() === b.date.toDateString() && !a.dateOnly && !b.dateOnly) return dayWord(a.date) + ' ' + hhmm(a.date) + '–' + hhmm(b.date);
    return when(from) + ' – ' + when(to);
  }
  const noIso = value => text(value).replace(/agent:factory/g, 'your agent').replace(/\d{4}-\d\d-\d\dT\d\d:\d\d(?::\d\d(?:\.\d+)?)?(?:Z|[+-]\d\d:?\d\d)/g, m => when(m));
  function duration(min) {
    const n = Math.round(Number(min));
    if (!Number.isFinite(n)) return '—';
    const h = Math.floor(n / 60), m = n % 60;
    return [h ? h + ' h' : '', m || !h ? m + ' min' : ''].filter(Boolean).join(' ');
  }
  const capital = value => { const t = text(value).replace(/[-_]/g, ' '); return t.charAt(0).toUpperCase() + t.slice(1); };
  const tagWord = tag => tag === 'cant-undo' ? "can't undo" : text(tag).replace(/[-_]/g, ' ');
  // The proposal's own label when it gave one, else the capitalized stage name; the ship stage is always a question.
  const stageLabel = item => item.label || (item.stage === 'ship' ? 'Ship it?' : capital(item.stage));
  const stageName = (order, stage) => stageLabel(array(order?.line).find(x => x.stage === stage) || {stage});
  const yourTime = min => Number.isFinite(Number(min)) && min !== null ? "you're needed ~" + min + ' min' : '';
  function link(label, href, primary = false) {
    const el = node('a', label, primary ? 'btn primary' : 'btn outline sm');
    el.classList.add('f-btn');
    el.href = href;
    if (href.startsWith('/#')) el.target = '_top';
    return el;
  }
  function ticket(id, label = 'Answer in the ticket', primary = true) {
    return validId(id) ? link(label, '/#ticket/' + id, primary) : meta('Ticket reference unavailable.');
  }
  const validQuestion = q => typeof q === 'string' && /^q[A-Za-z0-9_-]{0,31}$/.test(q);
  const embedded = () => { try { return window.top !== window; } catch (_) { return true; } };
  // Inside the dashboard a decision asks it to open its own question card for this order's open question (the page itself
  // never answers). Outside the dashboard, or with nothing open, it stays a link to the ticket.
  function decide(order, label = 'Answer', primary = true, question = order.open?.q) {
    if (!embedded() || !question || !validId(order.id) || !validQuestion(question)) return ticket(order.id, label, primary);
    const b = node('button', label, primary ? 'btn primary f-btn' : 'btn outline sm f-btn');
    b.type = 'button';
    b.addEventListener('click', () => {
      b.disabled = true;
      window.parent.postMessage({type: 'orch.question', ticket: order.id, question}, location.origin);
      setTimeout(() => { b.disabled = false; }, 1500);
    });
    return b;
  }
  window.addEventListener('message', e => {
    const d = e.data;
    if (e.source !== window.parent || e.origin !== location.origin || !d || d.type !== 'orch.question.done' || !validId(d.ticket) || !validQuestion(d.question)) return;
    render();
  });
  function orderLink(order, label = 'Open order', suffix = '') {
    return validId(order.id) ? link(label, '#/order/' + order.id + suffix) : meta('Order reference unavailable.');
  }
  function card(title, ...children) {
    const el = node('section', null, 'card f-card');
    el.append(node('h2', title), ...children);
    return el;
  }
  function list(values, empty = 'None recorded.') {
    if (!array(values).length) return meta(empty);
    const el = node('ul', null, 'f-list');
    for (const value of values) el.append(node('li', value));
    return el;
  }
  function heading(title, subtitle, ...actions) {
    document.title = text(title) + ' · Factory';
    const h1 = node('h1', title); h1.tabIndex = -1;
    return group('f-heading', group('stack', h1, meta(subtitle)), group('actions', ...actions));
  }
  // The questions your helper asked on the order (the draft's open questions): one card each, its options and its
  // suggestion shown, the answer given in the dashboard's own question card (the page never answers).
  function questionCards(order) {
    const rows = array(order.questions).filter(x => validQuestion(x?.q));
    if (!rows.length) return [];
    return rows.map(x => {
      const c = card(x.text || 'A question for you');
      if (array(x.options).length) c.append(meta('Options: ' + array(x.options).join(' · ')));
      if (x.recommended) c.append(meta('Your agent suggests: ' + x.recommended));
      c.append(tail(decide(order, 'Answer', true, x.q)));
      c.classList.add('f-attention'); return c;
    });
  }
  // The crew's results that wait for your Looks good: one card, one link per result (each opens its own ticket, where
  // the check is your own click). Nothing is checked from here.
  const results = order => array(order.results).filter(r => validId(r?.ticket));
  function resultsCard(order, withOrder) {
    const rows = results(order);
    const c = card(order.title, node('h3', plural(rows.length, 'result', 'results') + ' built, waiting for your Looks good'),
      group('stack', ...rows.map((r, i) => link((rows.length > 1 ? 'Look at ' : 'Look at the result: ') + text(r.title), '/#ticket/' + r.ticket, i === 0))),
      ...(withOrder ? [tail(orderLink(order, 'Review order'))] : []));
    c.classList.add('f-attention'); return c;
  }
  // The run goes on by itself; until its next step has started, say so instead of showing nothing.
  const startingNote = order => order.starting ? [meta('Starting the ' + stageName(order, order.starting) + ' stage…')] : [];
  function answer(order) {
    return group('stack', group('actions', decide(order)), meta(embedded() && order.open ? 'Your answer opens in a card here, where orch confirms it\'s you.' : "You answer on the order's ticket, where orch confirms it's you."));
  }
  function stages(order) {
    const el = node('ol', null, 'f-stage'); el.setAttribute('aria-label', 'Order stages');
    for (const stage of array(order.line)) {
      const done = ['done', 'complete', 'completed', 'passed'].includes(stage.state);
      const li = node('li', (done ? '✓ ' : stage.stop ? '◇ ' : '') + stageLabel(stage), done ? 'complete' : '');
      if (stage.stage === order.stage) li.setAttribute('aria-current', 'step');
      el.append(li);
    }
    return el.children.length ? el : meta('The line is not planned yet.');
  }
  function nextStop(order) {
    const stop = array(order.line).find(x => x.stop && x.state !== 'done');
    if (!stop) return null;
    const need = yourTime(order.owner_min);
    return meta('Next stop: ' + stageLabel(stop) + (need ? ' · ' + need : ''));
  }
  // Plain title for an open question, from the structured stop/change data. The raw core text stays behind Details.
  function openTitle(order, open) {
    const data = open.data || {};
    if (open.kind === 'stop') return data.stage === 'ship' ? 'Ship it?' : 'Check at ' + stageName(order, data.stage);
    if (open.kind === 'change') return 'Add “' + text(data.title) + '”?';
    if (open.kind === 'autopilot') return 'Start autopilot?';
    return 'Start this run?';
  }
  function openBody(order, open, full) {
    const data = open.data || {}, parts = [];
    if (open.kind === 'stop') {
      const items = array(data.items);
      if (items.length) parts.push(list(items.map(i => text(i.title) + ' (' + tagWord(i.tag) + ')')));
      const checked = array(data.checked).length, not = array(data.not_checked).length;
      parts.push(meta('Checked: ' + checked + ' · Not checked: ' + not));
      if (full) {
        if (not) parts.push(meta('Not checked: ' + array(data.not_checked).join(', ')));
      }
    } else if (open.kind === 'change') {
      parts.push(meta('+' + text(data.adds_min) + ' min' + (data.new_eta ? ' · new ETA ' + when(data.new_eta) : '')));
      if (data.what) parts.push(p(data.what));
    } else {
      const need = yourTime(order.owner_min);
      if (need) parts.push(meta(capital(need)));
    }
    return parts;
  }
  function rawDetails(open) {
    const el = node('details', null, 'f-details');
    el.append(node('summary', 'Details'), meta(open.text), ...(array(open.options).length ? [meta('Options: ' + open.options.join(' · '))] : []));
    return el;
  }
  function budget(order) {
    const b = order.budget || {};
    const used = Number(b.used), cap = Number(b.cap);
    if (b.used == null || b.cap == null || !Number.isFinite(used) || !Number.isFinite(cap) || cap <= 0) return meta('Budget health · not available yet.');
    const percent = Math.max(0, Math.round(used / cap * 100));
    const bar = node('progress'); bar.max = 100; bar.value = Math.min(100, percent);
    bar.setAttribute('aria-label', 'Active time budget used');
    bar.setAttribute('aria-valuetext', percent + '% · ' + used + ' of ' + cap + ' minutes');
    return group('f-budget', group('row between', meta('Budget health'), meta(percent + ' % · time is the tightest')), bar,
      meta(used + ' / ' + cap + ' active min · waiting for you never counts'),
      ...(b.warn ? [meta('Budget needs attention · review the order ticket.')] : []));
  }
  const tail = (...nodes) => group('actions', ...nodes);
  // The page never writes by itself. "Ask me at every stop" goes to your helper in Chat as typed text (you press Send
  // there). The idea box asks the dashboard to file the idea as YOUR click (orch.idea): the dashboard checks this frame and
  // runs the person's action with your page session; it answers orch.idea.done {id, order} or orch.idea.failed {id, error}.
  function toChat(message) {
    window.parent.postMessage({type: 'orch.say', text: message}, location.origin);
  }
  const IDEA_MAX = 500, NOTE_MAX = 1000;
  // A request to the dashboard waits for its answer by a random id: orch.idea.* and orch.send.* (see below).
  const asked = new Map();  // request id -> callback
  window.addEventListener('message', e => {
    const d = e.data;
    if (e.source !== window.parent || e.origin !== location.origin || !d || typeof d.id !== 'string' || !asked.has(d.id)) return;
    if (d.type === 'orch.idea.done' && validId(d.order)) asked.get(d.id)({order: d.order});
    else if (d.type === 'orch.send.done' && validId(d.ticket)) {
      // "Sent" only when orch says the words were delivered to the agent or queued for it; anything else is an error
      if (d.delivered === true || d.queued === true) asked.get(d.id)({ticket: d.ticket, delivered: d.delivered === true});
      else asked.get(d.id)({error: 'orch did not confirm that your message was saved.'});
    }
    else if (d.type === 'orch.ask.done' && ['delivered', 'queued', 'partial'].includes(d.state)) asked.get(d.id)({state: d.state, said: typeof d.said === 'string' ? d.said.slice(0, 300) : ''});
    else if (d.type === 'orch.idea.failed' || d.type === 'orch.send.failed' || d.type === 'orch.ask.failed') asked.get(d.id)({error: typeof d.error === 'string' ? d.error.slice(0, 300) : ''});
  });
  function askDashboard(message, wait = 30000) {
    return new Promise(resolve => {
      const id = Array.from(crypto.getRandomValues(new Uint8Array(12)), b => (b % 36).toString(36)).join('');
      const timer = setTimeout(() => finish({error: ''}), wait);  // an older dashboard never answers
      function finish(result) { clearTimeout(timer); asked.delete(id); resolve(result); }
      asked.set(id, finish);
      window.parent.postMessage({...message, id}, location.origin);
    });
  }
  // Ask another workspace at a stop (816 A): one click; the dashboard runs the add-on's ask act as the person.
  const askWorkspace = target => askDashboard({type: 'orch.ask', target}, 120000);
  const fileIdea = textValue => askDashboard({type: 'orch.idea', text: textValue});
  // Plan the run / Ask for changes on a draft: the dashboard sends the words to the agent on the order as YOUR message
  // (its own proven "send to the agent" click, the same as typing on the ticket) and starts the agent when none works.
  const PLAN_TEXT = 'Now plan the run: propose the whole run for this order (orch factory propose).';
  const toAgent = (order, words) => askDashboard({type: 'orch.send', ticket: order, text: words});
  function draftActions(order, onSent) {
    const box = group('stack f-draft-actions');
    if (!validId(order.id)) return box;
    if (!embedded()) { box.append(meta('Open Factory in the dashboard to plan the run or ask for changes with one click.'), tail(ticket(order.id, 'Open the ticket', false))); return box; }
    const plan = node('button', 'Plan the run', 'btn primary'); plan.type = 'button';
    const change = node('button', 'Ask for changes', 'btn outline sm'); change.type = 'button';
    const note = node('textarea', null, 'text-input'); note.rows = 3; note.maxLength = NOTE_MAX; note.style.width = '100%';
    note.setAttribute('aria-label', 'What should change'); note.placeholder = 'For example: shorter, and add a map'; note.hidden = true;
    const send = node('button', 'Send', 'btn primary sm'); send.type = 'button'; send.hidden = true; send.disabled = true;
    const cancel = node('button', 'Cancel', 'btn ghost sm'); cancel.type = 'button'; cancel.hidden = true;
    const status = node('p', null, 'meta'); status.setAttribute('role', 'status'); status.hidden = true;
    const say = value => { status.textContent = value; status.hidden = !value; };
    const writing = on => { note.hidden = send.hidden = cancel.hidden = !on; plan.hidden = change.hidden = on; if (on) note.focus(); };
    const busy = on => { for (const b of [plan, change, send, cancel]) b.disabled = on || (b === send && !note.value.trim()); note.readOnly = on; };
    async function go(words, sent) {
      busy(true); say('Sending…');
      const result = await toAgent(order.id, words);
      busy(false);
      if (result.ticket) { note.value = ''; writing(false); plan.hidden = change.hidden = true; say(result.delivered ? sent : 'Saved. Your agent gets it as soon as it is free.'); if (onSent) setTimeout(onSent, 8000); return; }
      say((result.error ? result.error + ' ' : "That didn't work. ") + 'Nothing was sent.');
    }
    note.addEventListener('input', () => { send.disabled = !note.value.trim(); });
    plan.addEventListener('click', () => go(PLAN_TEXT, 'Sent. Your agent is planning the run; the proposal shows up here.'));
    change.addEventListener('click', () => { say(''); writing(true); });
    cancel.addEventListener('click', () => { writing(false); say(''); });
    send.addEventListener('click', () => { const words = note.value.trim(); if (words) go('Change the draft: ' + words, 'Sent. Your agent is changing the draft.'); });
    box.append(group('actions', plan, change), note, group('actions', send, cancel), status);
    return box;
  }
  // A draft waits for you only once the agent filed its own version (agent_draft) and its turn ended (not working).
  const draftNote = o => meta(o.working ? 'Your agent is working on the draft.' : 'Waiting for your agent to write the first draft.');
  const draftWaiting = o => o.phase === 'draft' && o.agent_draft === true && !o.working;
  function ideaBox() {
    const el = card('Start with an idea', meta('Describe something you want built. Factory plans it and builds it step by step.'));
    const field = node('textarea', null, 'text-input'); field.rows = 3; field.setAttribute('aria-label', 'Your idea');
    field.placeholder = 'For example: a page that shows our opening hours'; field.style.width = '100%'; field.maxLength = IDEA_MAX;
    const go = node('button', 'Start with this idea', 'btn primary'); go.type = 'button'; go.disabled = true;
    const status = node('p', null, 'meta f-idea-status'); status.setAttribute('role', 'status'); status.hidden = true;
    const fallback = node('button', 'Send it to your helper in Chat instead', 'btn outline sm'); fallback.type = 'button'; fallback.hidden = true;
    const say = value => { status.textContent = value; status.hidden = !value; };
    field.addEventListener('input', () => { go.disabled = !field.value.trim(); fallback.hidden = true; say(''); });
    fallback.addEventListener('click', () => { if (field.value.trim()) toChat('Factory: ' + field.value.trim()); });
    go.addEventListener('click', async () => {
      const idea = field.value.trim();
      if (!idea) return;
      if (!embedded()) { say('Open Factory in the dashboard to start an idea with one click.'); return; }
      go.disabled = true; field.readOnly = true; fallback.hidden = true; say('Saving your idea…');
      const result = await fileIdea(idea);
      field.readOnly = false;
      if (result.order) { field.value = ''; say(''); location.hash = '#/order/' + result.order + '/draft'; return; }
      go.disabled = false;
      say((result.error ? result.error + ' ' : "That didn't work. ") + 'Your idea is still here.');
      fallback.hidden = false;
    });
    el.append(field, group('row', go, fallback), status); el.classList.add('f-idea'); return el;
  }
  // One idea box for the whole page: it is on screen before the order list has been read, and what you type in it
  // stays when the list arrives.
  let idea = null;
  const theIdea = () => idea || (idea = ideaBox());
  function askRow(auto) {
    const asks = !auto?.on, row = group('setting-row f-ask');
    const input = node('input', null, 'switch'); input.type = 'checkbox'; input.checked = asks; input.setAttribute('aria-label', 'Ask me at every stop');
    const word = node('span', asks ? 'On' : 'Off', 'meta');
    input.addEventListener('change', () => { input.checked = asks; toChat(asks ? 'Factory: run to the end with Autopilot' : 'Factory: ask me at every stop again'); });
    const label = node('label', null, 'row'); label.append(word, input);
    row.append(node('div', 'Ask me at every stop', 'row-label'),
      group('row-value', document.createTextNode('Factory waits for your OK after each step'), meta('Turn off to let it run to the end.')),
      group('row-action', label));
    return group('card', row);
  }
  function home(data) {
    const orders = array(data.orders), auto = data.autopilot;
    const needing = orders.filter(o => o.open || draftWaiting(o) || results(o).length);
    const minutes = needing.reduce((sum, o) => sum + (o.open && Number.isFinite(Number(o.owner_min)) && o.owner_min !== null ? Number(o.owner_min) : 0), 0);
    view.append(heading('Factory', needing.length
      ? plural(needing.length, 'Factory item waits for you', 'Factory items wait for you') + (minutes ? ' · about ' + minutes + ' min of your time' : '')
      : 'Nothing in Factory waits for you right now. Your ideas and planned runs are below.'));
    view.append(theIdea(), askRow(auto));
    if (auto?.on) {
      const days = Math.max(0, Math.ceil((Date.parse(auto.until) - Date.now()) / 864e5));
      const autoCard = card('Autopilot on · ' + (days > 1 ? days + ' days left' : days === 1 ? '1 day left' : 'ends today'),
        meta('Ends ' + when(auto.until) + ' · ' + plural(Number(auto.decided_today) || 0, 'decision', 'decisions') + ' today'),
        meta('Your agent answers routine stops. Ship still asks you.'),
        tail(link('What it decided', '#/autopilot')));
      autoCard.classList.add('f-autopilot'); view.append(autoCard);
    } else if (auto) view.append(tail(link('What it decided', '#/autopilot')));
    if (!orders.length) return;
    const primary = group('stack'), secondary = group('stack');
    const section = (parent, title, rows, render, empty) => {
      const el = node('section', null, 'f-section'); el.append(node('h2', title));
      el.append(...(rows.length ? rows.map(render) : [meta(empty)])); parent.append(el);
    };
    section(primary, 'Drafts waiting for you', orders.filter(draftWaiting), o => {
      const c = card(o.title, meta('Read the draft, then plan the run or ask for changes.'),
        tail(orderLink(o, 'Read draft', '/draft')), draftActions(o, render));
      c.classList.add('f-attention'); return c;
    }, 'No drafts waiting for you.');
    section(primary, 'Proposals waiting for Start', orders.filter(o => o.phase === 'proposed'), o => {
      const need = yourTime(o.owner_min);
      const c = card(o.title, ...(need ? [meta(capital(need))] : []), tail(orderLink(o, 'Read proposal', '/proposal')));
      c.classList.add('f-attention'); return c;
    }, 'No proposals waiting for Start.');
    section(primary, 'Factory stops waiting for you', orders.filter(o => o.open && o.phase !== 'proposed'), o => {
      const c = card(o.title, node('h3', openTitle(o, o.open)), ...openBody(o, o.open, false), rawDetails(o.open),
        tail(decide(o, 'Answer', true), orderLink(o, 'Review order')));
      c.classList.add('f-attention'); return c;
    }, 'No stops waiting for you.');
    section(primary, 'Results to check', orders.filter(o => results(o).length), o => resultsCard(o, true), 'No results waiting for you.');
    section(primary, 'Running', orders.filter(o => o.phase === 'started'), o => o.kind === 'autopilot'
      ? card(o.title, meta('Autopilot order'), p('Routine stops answered by your agent · Ship still asks you'), tail(link('What it decided', '#/autopilot')))
      : card(o.title, stages(o), ...startingNote(o), budget(o), ...(o.eta ? [meta('ETA ' + when(o.eta))] : []), tail(orderLink(o))), 'No running orders.');
    // The summary contract has no shipped timestamp. Do not infer a week from due dates.
    section(secondary, 'Shipped', orders.filter(o => o.phase === 'shipped'), o => card('✓ ' + text(o.title), badge('Shipped'), tail(orderLink(o))), 'No shipped work recorded.');
    secondary.append(meta('Shipped orders are listed from the workspace record; shipment dates are not available yet.'));
    section(secondary, 'Saved ideas', orders.filter(o => (o.phase === 'draft' && !draftWaiting(o)) || ['edit','parked','cancelled','broken'].includes(o.phase)),
      o => card(o.title, ...(o.phase === 'draft' ? [draftNote(o)] : [badge(capital(o.phase))]), tail(orderLink(o))), 'No saved ideas.');
    view.append(group('f-grid', primary, secondary));
  }
  function line(items) {
    const el = node('ol', null, 'f-line');
    for (const item of array(items)) {
      const li = node('li', (item.stop ? '◇ ' : '') + stageLabel(item), item.stop ? 'stop' : '');
      li.append(node('small', item.why)); el.append(li);
    }
    return el;
  }
  const roles = {manager: 'Manager', builder: 'Builder', reviewer: 'Reviewer'};
  const roleName = role => roles[role] || capital(role);
  function crewPlan(crew) {
    return list(array(crew).map(c => roleName(c.role) + ' · ' + text(c.agent) + ' — ' + text(c.why)));
  }
  function limits(data) {
    data = data || {};
    const rows = [];
    if (data.days != null) rows.push('Runs for ' + plural(Number(data.days), 'day', 'days') + '. Then your agent stops and asks you to renew.');
    if (data.max_orders != null) rows.push('At most ' + plural(Number(data.max_orders), 'order', 'orders') + ' at once.');
    if (data.active_min_per_day != null) rows.push('Target: ' + duration(data.active_min_per_day) + ' of active work a day. You get a heads-up when it is reached; Autopilot keeps going.');
    if (data.api_usd_per_day != null) rows.push('Target: $' + text(data.api_usd_per_day) + ' of API spend a day · not enforced yet');
    return list(rows);
  }
  const mayDecide = {routine: 'Routine improvements', taste: 'Taste decisions within your house rules'};
  const alwaysAsks = ['Shipping: the final Ship stop.', 'Anything that cannot be undone.', 'Scope changes and budget beyond the limits.', 'New connections or credentials.', 'Anything touching another workspace.', 'Creating, renewing or widening Autopilot.'];
  function proposal(order) {
    const data = order.proposal;
    view.append(heading(data?.title || order.title, data?.kind === 'autopilot' ? 'Autopilot proposal · ' + text(data.goal) : 'Run proposal · review the whole run before answering', orderLink(order)));
    if (!data) { view.append(card('No frozen proposal yet', p('Your agent is still planning this order.'), answer(order))); return; }
    if (data.kind === 'autopilot') {
      const l = data.limits || {};
      const parts = [];
      if (l.days != null) parts.push(plural(Number(l.days), 'day', 'days'));
      if (l.max_orders != null) parts.push('at most ' + plural(Number(l.max_orders), 'order', 'orders') + ' at once');
      if (data.report_at) parts.push('daily report at ' + data.report_at);
      view.append(node('p', parts.join(' · '), 'f-summary'),
        group('grid-2', card('May decide', list(array(data.may_decide).map(x => mayDecide[x] || capital(x))), ...(array(data.examples).length ? [meta('Examples: ' + array(data.examples).join('; '))] : [])),
          card('Always asks you', list(alwaysAsks))),
        card('Limits & duration', limits(data.limits)), card('Done means', list(data.done_means)), answer(order)); return;
    }
    const time = data.time || {}, b = data.budget || {};
    view.append(p(data.goal));
    const summary = ['~' + duration(time.active_min)];
    if (b.api_usd_target != null) summary.push('target $' + text(b.api_usd_target));
    if (time.owner_min != null) summary.push("you're needed ~" + time.owner_min + ' min');
    if (time.eta_from || time.eta_to) summary.push('ETA ' + whenRange(time.eta_from, time.eta_to));
    view.append(node('p', summary.join(' · '), 'f-summary'));
    view.append(group('f-three', card('The line', line(data.line)),
      card('Time + budget', p('~' + duration(time.active_min) + ' active · API target $' + text(b.api_usd_target)),
        p('ETA ' + whenRange(time.eta_from, time.eta_to)), meta('Budget preset · ' + capital(b.preset)),
        meta('Active time cap: ' + duration(b.active_min_cap) + '. API spend is a target, not a cap.'), meta('Your time: about ' + text(time.owner_min) + ' min.')),
      card('Crew + what it needs', crewPlan(data.crew), list(array(data.needs).map(n => (n.ready ? '✓ Ready · ' : 'Needs you · ') + text(n.what) + (!n.ready && n.fix ? ' — ' + n.fix : '')), 'No additional needs recorded.'))));
    for (const h of array(order.handover)) {
      const tiles = group('actions', ...array(h.files).map(f => badge(f.split('/').pop())));
      view.append(card(text(h.name) + ' does this', p(text(h.name) + ' makes ' + text(h.title) + (h.minutes ? ' · about ' + h.minutes + ' min' : '')), meta(h.why),
        p('They get: this brief' + (array(h.files).length ? ' and ' + plural(array(h.files).length, 'file', 'files') + ':' : '')), ...(array(h.files).length ? [tiles] : []),
        meta(text(h.name) + '’s time is not counted here. Everything else stays here, and ' + text(h.name) + ' allows it on their side.')));
    }
    view.append(group('grid-2', card('Done means', list(data.done_means)), card('Won’t do', list(data.wont_do), node('h3','What Ship does'), p(data.ship?.does), meta('Undo: ' + text(data.ship?.undo)))));
    const assumptions = card('Assumptions');
    for (const a of array(data.assumptions)) assumptions.append(group('row', ...(a.uncertain ? [badge('Unsure')] : []), p(a.text)));
    if (!array(data.assumptions).length) assumptions.append(meta('No assumptions recorded.'));
    assumptions.append(meta('Resolve unsure assumptions on the ticket before Start.'));
    view.append(assumptions, answer(order));
    const details = node('details', null, 'f-details');
    details.append(node('summary', 'Details · full line, crew, plan & tasks'), group('stack', line(data.line), node('h3','Crew'), crewPlan(data.crew),
      node('h3','Steps'), list(array(data.tasks).map(t => text(t.title) + ' · ' + text(t.slug) + ' · ' + roleName(t.role) + ' · ' + capital(t.stage) + (array(t.proves).length ? ' · proves: ' + t.proves.map(i => array(data.done_means)[i] || i).join('; ') : ''))),
      node('h3','Skipped stages'), list(array(data.skipped).map(s => capital(s.stage) + ' — ' + text(s.why))),
      node('h3','Handovers'), list(array(data.handovers).map(h => text(h.task) + ' → ' + text(h.workspace) + ' — ' + text(h.why)))));
    view.append(details);
  }
  // A task handed to another workspace that nobody has picked up for a day: one click asks your helper to propose "Do it here instead".
  const DAY = 24 * 3600 * 1000, handoverOpen = ['waiting_start', 'waiting_allow', 'queued'];
  const waitedADay = w => handoverOpen.includes(w.state) && w.since && Date.now() - Date.parse(w.since) > DAY;
  function doItHere(order, c) {
    const button = node('button', 'Ask Helper to do it here', 'btn outline sm'); button.type = 'button';
    const status = node('span', null, 'meta'); status.setAttribute('role', 'status');
    button.addEventListener('click', async () => {
      button.disabled = true; status.textContent = ' Sending…';
      const result = await toAgent(order.id, 'Propose a change "Do it here instead" for the task "' + text(c.title) + '": ' + text(c.with.name) + ' has not finished it after a day.');
      status.textContent = result.ticket ? ' Sent. Your helper proposes the change; you decide.' : ' That didn’t work. Nothing was sent.';
      if (!result.ticket) button.disabled = false;
    });
    return group('actions', button, status);
  }
  function tiny(order) { return card('Changed during the run', list(array(order.tiny).map(t => text(t.what) + ' · +' + text(t.minutes) + ' min'), 'No tiny changes recorded.')); }
  const statusWord = {open: 'open', todo: 'not started', doing: 'working', done: 'done', blocked: 'blocked'};
  function orderPage(order) {
    const phase = order.phase === 'started' ? 'Running' : capital(order.phase);
    view.append(heading(order.title, [phase, order.stage ? 'Stage: ' + stageName(order, order.stage) : '', order.eta ? 'ETA ' + when(order.eta) : ''].filter(Boolean).join(' · '), orderLink(order, 'Read proposal', '/proposal')));
    if (order.kind === 'autopilot') {
      view.append(card('Autopilot order', p('Routine stops answered by your agent · Ship still asks you'),
        group('actions', link('What it decided', '#/autopilot'), ticket(order.id, 'Open order ticket', false))));
    }
    const lineCard = card('The line', stages(order), ...startingNote(order), ...(order.kind === 'run' && order.phase === 'started' ? [nextStop(order)].filter(Boolean) : []));
    const main = group('stack', lineCard, card('Time + budget', budget(order), ...(order.due ? [meta('Due ' + when(order.due))] : [])));
    const crew = card('Crew now');
    for (const c of array(order.crew)) {
      const label = c.with ? [roleName(c.role), c.with.name, c.with.words].filter(Boolean).join(' · ') : [roleName(c.role), c.agent, statusWord[c.status] || c.status].filter(Boolean).join(' · ');
      const row = group('f-record f-crew');
      if (validId(c.ticket)) { const a = link(label + ' ↗', '/#ticket/' + c.ticket); a.className = 'f-crewlink'; a.title = c.title || ''; row.append(a); } else row.append(node('span', label));
      row.append(meta(c.title));
      if (c.with && waitedADay(c.with) && embedded() && validId(order.id)) row.append(doItHere(order, c));
      crew.append(row);
    }
    if (!array(order.crew).length) crew.append(meta('No crew assigned yet.'));
    main.append(crew, tiny(order));
    const timeline = node('ol', null, 'f-timeline');
    for (const a of array(order.activity)) { const li = node('li'); li.append(meta(when(a.at)), p(noIso(a.text))); timeline.append(li); }
    main.append(card('Activity', timeline.children.length ? timeline : meta('No activity recorded.')));
    const aside = group('stack');
    if (order.phase === 'draft') {  // the same rule as Factory home and the draft page (draftWaiting)
      const c = draftWaiting(order)
        ? card('Your draft is ready', meta('Read the draft, then plan the run or ask for changes.'),
          tail(orderLink(order, 'Read draft', '/draft')), draftActions(order, render))
        : card('Draft', draftNote(order));
      if (draftWaiting(order)) c.classList.add('f-attention');
      aside.append(c);
    }
    if (order.open) {
      const question = card('Needs you', node('h3', openTitle(order, order.open)), ...openBody(order, order.open, true), rawDetails(order.open), answer(order));
      question.classList.add('f-attention'); aside.append(question);
    }
    if (results(order).length) aside.append(resultsCard(order, false));
    aside.append(...questionCards(order));
    if (order.problem) aside.append(card('Record needs attention', p(order.problem), group('actions', ticket(order.id, 'Open order ticket', false))));
    const changes = card('Changes');
    for (const c of array(order.changes)) changes.append(group('f-record', badge(capital(c.state)), node('h3', c.title), meta('+' + text(c.adds_min) + ' min'), ...(c.state === 'open' ? [group('actions', decide(order))] : [])));
    if (!array(order.changes).length) changes.append(meta('No changes proposed.'));
    aside.append(changes);
    const stops = card('Stops');
    const stateWord = {open: 'waiting for you', decided: 'decided by your agent', answered: 'answered', ignored: 'not counted'};
    for (const s of array(order.stops)) if (validVersion(s.n)) stops.append(group('f-record', orderLink(order, stageName(order, s.stage) + ' · round ' + s.n, '/stop/' + s.n), meta([stateWord[s.state] || s.state, s.answer].filter(Boolean).join(' · '))));
    if (!stops.querySelector('a')) stops.append(meta('No stop reviews yet.'));
    aside.append(stops, card('Drafts', draftTabs(order)));
    view.append(group('f-order', main, aside));
  }
  function imageName(value) {
    // The API also accepts an explicit stop-round folder (for example s1/before.png).
    // No arbitrary directories, URLs, encoded separators or traversal.
    return typeof value === 'string' && /^(?:s[1-9][0-9]{0,3}\/)?[a-zA-Z0-9_-][a-zA-Z0-9_.-]{0,79}\.(png|jpg|jpeg|webp|gif)$/i.test(value) && !value.includes('..');
  }
  function preview(order, label, value) {
    const figure = node('figure'); figure.append(node('figcaption', label));
    if (validId(order.id) && imageName(value)) {
      const img = node('img'); img.alt = label + ' review image'; img.src = prefix + '/api/order/' + order.id + '/file/' + value.split('/').map(encodeURIComponent).join('/');
      img.addEventListener('error', () => img.replaceWith(meta(label + ' image unavailable.')), {once:true}); figure.append(img);
    } else figure.append(p(value || 'No image supplied.'));
    return figure;
  }
  const picturesOf = item => [item.before, item.after].filter(imageName);
  const askState = {queued: 'Queued', delivered: 'Delivered', answered: 'Answered', failed: 'Failed', partial: 'Partly sent', closed: 'Closed'};
  const askPill = state => { const el = node('span', null, 'pill ' + ({answered: 'done', failed: 'needs', partial: 'needs', queued: 'todo'}[state] || 'working')); el.append(node('span', askState[state] || state)); return el; };
  // "Maya says" / "Design's helper says": text from another workspace is data, shown as plain text and cut to a few lines.
  function replyBlock(a, r, retry) {
    const row = group('list-row', askPill('answered'), group('grow', node('strong', r.by === 'helper' ? a.ws_name + "'s helper says: " : a.ws_name + ' says: '), document.createTextNode(text(r.text)), ...(r.more ? [meta(' …more on the ask ticket')] : [])), meta(r.at ? when(r.at) : ''));
    const add = node('button', 'Add to my comments', 'btn ghost sm'); add.type = 'button';
    add.addEventListener('click', async () => {
      const quoted = a.ws_name + ' wrote: "' + text(r.text).replace(/\s+/g, ' ') + '"';
      try { await navigator.clipboard.writeText(quoted); add.textContent = 'Copied · paste it into your comments'; } catch (_) { add.textContent = 'Could not copy'; }
    });
    row.append(add);
    return row;
  }
  function otherViews(order, stop, openAskDialog) {
    const c = card('Other views', meta('They advise. You decide.'));
    for (const a of array(stop.asks)) {
      const replies = array(a.replies);
      if (replies.length) for (const r of replies) c.append(replyBlock(a, r));
      else {
        const note = {queued: a.ws_name + ' is offline. Your question goes out when it is back.', failed: a.note || 'Not delivered to ' + a.ws_name + '.', partial: a.note || 'Only part of it reached ' + a.ws_name + '.', closed: 'Asked ' + a.ws_name + ' · closed when you answered', delivered: 'Asked ' + a.ws_name + ' · no answer yet'}[a.state] || 'Asked ' + a.ws_name;
        const row = group('list-row', askPill(a.state), group('grow', document.createTextNode(note)), meta(a.at ? when(a.at) : ''));
        if ((a.state === 'failed' || a.state === 'partial') && openAskDialog) { const again = node('button', 'Send again', 'btn outline sm'); again.type = 'button'; again.addEventListener('click', () => openAskDialog(a)); row.append(again); }
        c.append(row);
      }
    }
    return c;
  }
  // The dialog: who, exactly what leaves this computer (the line and the items you tick), a check for passwords and keys.
  function askDialog(order, stop, reach) {
    const items = array(stop.data?.items);
    const d = node('dialog', null, 'dialog'); d.setAttribute('aria-labelledby', 'ask-title');
    const select = node('select', null, 'input'); select.setAttribute('aria-label', 'Who');
    for (const w of reach) { const o = node('option', w.name + (w.description ? ' · ' + w.description : '')); o.value = w.ws; select.append(o); }
    const who = node('label', 'Who', 'field'); who.append(select);
    const ticks = items.map((item, i) => {
      const n = picturesOf(item).length;
      const box = node('input'); box.type = 'checkbox'; box.checked = true;
      const label = node('label', null, 'check-label'); label.append(box, document.createTextNode(' ' + text(item.title) + (n ? ' · before and after (' + plural(n, 'picture', 'pictures') + ')' : '')));
      return {box, label, i, text: label.lastChild, suffix: n ? ' · before and after (' + plural(n, 'picture', 'pictures') + ')' : ''};
    });
    const checked = meta('Checking for passwords and keys…');
    const preview = group('stack', meta('Reading what will be sent…'));
    const problem = p(''); problem.hidden = true; problem.setAttribute('role', 'alert');
    const cancel = node('button', 'Cancel', 'btn'); cancel.type = 'button'; cancel.addEventListener('click', () => d.close());
    const send = node('button', 'Send', 'btn primary'); send.type = 'button'; send.disabled = true;
    const close = node('div', null, 'row between'); close.append(node('h2', 'Ask another workspace'));
    close.firstChild.id = 'ask-title';
    d.append(close, who, node('h3', 'What leaves this computer'), preview, ...ticks.map(t => t.label),
      p('Not sent: other orders, crew logs, budget, chat, anything you untick.'), checked, problem, group('actions actions-end', cancel, send));
    // the check runs when the dialog opens, before Send: a file with a hit is shown unticked and disabled with its reason
    read('/api/order/' + order.id + '/stop/' + stop.n + '/scan').then(scan => {
      const hits = [];
      // exactly what the add-on sends, built by the one function that sends it: card title, line, question, item texts
      preview.replaceChildren(node('strong', text(scan.title)), p('“' + text(scan.line) + '”'), meta('Question: ' + text(scan.question)));
      for (const row of array(scan.items)) { const t = ticks[row.i]; if (t) t.text.nodeValue = ' ' + text(row.check) + t.suffix; }
      for (const row of array(scan.items)) {
        const t = ticks[row.i]; const bad = array(row.files).filter(f => f.ok === false);
        if (!t || !bad.length) continue;
        t.box.checked = false; t.box.disabled = true;
        for (const f of bad) { hits.push(f.name); t.label.append(node('strong', ' · not sent: ' + text(f.name) + ' ' + text(f.why || 'could not be checked'))); }
      }
      checked.textContent = hits.length ? 'Found in a picture: untick it or remove the password first.' : 'Checked for passwords and keys: nothing found.';
      send.disabled = false;
    }).catch(() => { checked.textContent = 'Could not check for passwords and keys now. Send checks again before anything leaves.'; send.disabled = false; });
    send.addEventListener('click', async () => {
      send.disabled = true; cancel.disabled = true; problem.hidden = true;
      const picked = ticks.filter(t => t.box.checked).map(t => t.i);
      const result = await askWorkspace(order.id + ':s' + stop.n + ':' + select.value + ':' + (picked.length ? picked.join(',') : '-'));
      if (result.state) { d.close(); render(); return; }  // partial: the row on the stop says what went out
      problem.textContent = result.error || 'It was not sent. Nothing left this computer. Try again.'; problem.hidden = false;
      send.disabled = false; cancel.disabled = false;
    });
    d.addEventListener('close', () => d.remove());
    document.body.append(d);
    d.showModal();
  }
  function stopPage(order, round, reach = []) {
    const stop = array(order.stops).find(s => String(s.n) === round);
    if (!stop) throw new Error('Stop not found');
    const data = stop.data || {};
    const canAsk = stop.state === 'open' && embedded() && reach.length > 0 && validId(order.id);
    const ask = canAsk ? node('button', 'Ask another workspace', 'btn outline sm f-btn') : null;
    if (ask) { ask.type = 'button'; ask.addEventListener('click', () => askDialog(order, stop, reach)); }
    view.append(heading(stageName(order, stop.stage) + ' · stop review', order.title, ...(ask ? [ask] : []), orderLink(order)), meta([({open: 'Waiting for you', decided: 'Decided by your agent', answered: 'Answered', ignored: 'Not counted'})[stop.state] || stop.state, stop.answer].filter(Boolean).join(' · ')));
    for (const [index, item] of array(data.items).entries()) {
      const compare = group('f-compare', preview(order, 'Before', item.before), preview(order, 'After', item.after));
      const c = card(item.title, badge(tagWord(item.tag)), compare);
      if (imageName(item.before) && imageName(item.after)) {
        const label = node('label', 'Compare before / after', 'stack');
        const range = node('input', null, 'f-range'); range.type = 'range'; range.min = '15'; range.max = '85'; range.value = '50';
        range.setAttribute('aria-label', 'Before and after comparison balance · item ' + (index + 1));
        range.addEventListener('input', () => { const split = Number(range.value); compare.style.gridTemplateColumns = 'minmax(0,' + split + 'fr) minmax(0,' + (100 - split) + 'fr)'; });
        label.append(range); c.append(label);
      }
      if (item.recommend) c.append(meta('Your agent suggests: ' + item.recommend));
      c.append(meta('Review images and pins are view-only here. Add feedback on the order ticket.')); view.append(c);
    }
    if (array(stop.asks).length) view.append(otherViews(order, stop, canAsk ? () => askDialog(order, stop, reach) : null));
    if (stop.autopilot_waits) view.append(p('Autopilot waits for you on this stop, because you asked for a view.'));
    view.append(group('grid-2', card('Checked', list(data.checked)), card('Not checked', list(data.not_checked))),
      card('Changed during the run', list(data.changed_during_run)), answer(stop.state === 'open' ? order : {...order, open: null}));
  }
  function autopilot(data) {
    view.append(heading('Autopilot', 'Bounded permission for your agent. Ship still asks you.'));
    const grants = card('Grants');
    for (const grant of array(data.grants)) grants.append(group('f-record', node('h3', (grant.live ? 'Active until ' : 'Ended ') + when(grant.until)),
      node('h3', 'May decide'), list(array(grant.may).map(x => mayDecide[x] || capital(x))), node('h3', 'Limits'), limits(grant.limits), group('actions', ticket(grant.order, 'Open order ticket', false))));
    if (!array(data.grants).length) grants.append(meta('No grants recorded.'));
    const decisions = card('What it decided');
    for (const d of array(data.decisions)) decisions.append(group('f-record', node('h3', d.answer), p('Decided by your agent · ' + noIso(d.why)), meta(when(d.at)), group('actions', ticket(d.order, 'Open order ticket', false))));
    if (!array(data.decisions).length) decisions.append(meta('No agent decisions recorded.'));
    view.append(group('grid-2', grants, card('Always asks you', list(alwaysAsks))), decisions);
  }
  function draftTabs(order, selected) {
    const nav = node('nav', null, 'f-tabs'); nav.setAttribute('aria-label', 'Draft versions');
    for (const d of array(order.drafts)) if (validVersion(d.v)) {
      const a = orderLink(order, 'Version ' + d.v, '/draft/' + d.v);
      if (String(d.v) === selected) a.setAttribute('aria-current','page');
      if (d.at) a.title = when(d.at); nav.append(a);
    }
    if (!nav.children.length) nav.append(meta('No draft versions yet.'));
    return nav;
  }
  async function read(path, signal) {
    const response = await fetch(prefix + path, {signal});
    if (!response.ok) throw new Error('Read failed');
    const data = await response.json();
    if (!data || typeof data !== 'object' || data.error) throw new Error('Read failed');
    return data;
  }
  let request = 0, controller;
  function showNotices(homeData, ...data) {
    notices.replaceChildren();
    if (homeData.day_limit?.warning) notices.append(node('p', homeData.day_limit.warning, 'f-banner'));
    if (homeData.watcher === false) notices.append(node('p', 'Factory watcher is off. Runs will not be picked up automatically until it is restarted.', 'f-banner'));
    if ([homeData, ...data].some(d => d?.stale === true)) notices.append(node('p', 'This record is stale. It may not include the latest changes.', 'f-banner'));
  }
  async function render() {
    const serial = ++request;
    controller?.abort(); controller = new AbortController();
    const signal = controller.signal;
    const controllerForRequest = controller;
    const timeout = setTimeout(() => controllerForRequest.abort(), 15000);
    view.setAttribute('aria-busy', 'true'); notices.replaceChildren();
    const skeletons = names => names.map(c => { const el = node('div', null, 'skeleton ' + c); el.setAttribute('aria-hidden','true'); return el; });
    if (location.hash === '' || location.hash === '#/' || location.hash === '#content') {
      // the page frame and the idea box at once; the order list follows (skeleton) when it has been read
      view.replaceChildren(heading('Factory', 'Reading your orders…'), theIdea(), group('f-loading', ...skeletons(['title', 'thumb'])));
    } else view.replaceChildren(group('f-loading', node('p', 'Reading the Factory record…'), ...skeletons(['title','thumb','thumb'])));
    try {
      // Always begin with home, including deep links, to get watcher/stale status.
      const homeData = await read('/api/home', signal);
      if (serial !== request) return;
      lastHome = JSON.stringify({...homeData, generated_at: null});
      showNotices(homeData);
      const hash = location.hash || '#/';
      let draw;
      if (hash === '#/' || hash === '#content') draw = () => home(homeData);
      else if (hash === '#/autopilot') {
        const data = await read('/api/autopilot', signal);
        if (serial !== request) return;
        showNotices(homeData, data); draw = () => autopilot(data);
      } else {
        const match = /^#\/order\/(t_[a-z0-9]{6,16})(?:\/(proposal)|\/(stop)\/([1-9][0-9]*)|\/(draft)(?:\/([1-9][0-9]*))?)?$/.exec(hash);
        if (!match || !validId(match[1]) || (match[4] && !validVersion(match[4])) || (match[6] && !validVersion(match[6]))) throw new Error('Unknown route');
        const order = await read('/api/order/' + match[1], signal);
        if (serial !== request) return;
        if (order.id !== match[1]) throw new Error('Order reference mismatch');
        showNotices(homeData, order);
        if (match[2]) draw = () => proposal(order);
        else if (match[3] === 'stop') {
          const reach = await read('/api/reach', signal).catch(() => []);  // empty when the relay is off: no button then
          if (serial !== request) return;
          draw = () => stopPage(order, match[4], array(reach));
        }
        else if (match[5] === 'draft') {
          // without a version the newest one opens, and it moves on by itself when your helper files a newer one
          const newest = array(order.drafts).reduce((n, x) => validVersion(x.v) ? Math.max(n, Number(x.v)) : n, 0);
          const version = match[6] || String(newest || 1);
          const draft = await read('/api/order/' + match[1] + '/draft/' + version, signal);
          if (serial !== request) return;
          showNotices(homeData, order, draft);
          draw = () => view.append(heading(order.title, 'Draft · version ' + version, orderLink(order)), draftTabs(order, version), ...questionCards(order), node('pre', draft.text, 'card f-draft'), ...(draft.truncated ? [meta('This draft is too large to display in full. The text shown is truncated.')] : []), ...(draftWaiting(order) ? [draftActions(order)] : order.phase === 'draft' ? [draftNote(order)] : []));
        } else draw = () => orderPage(order);
      }
      if (serial !== request) return;
      view.replaceChildren(); draw(); view.classList.add('page-enter');
      if (serial > 1) view.querySelector('h1')?.focus({preventScroll:true});
    } catch (error) {
      if (serial !== request) return;
      const retry = node('button', 'Try again', 'btn primary'); retry.type = 'button'; retry.addEventListener('click', render);
      const box = card('Factory could not read this page', p('The record may be unavailable, or this page may no longer exist.'), group('actions', retry, link('Back to Factory', '#/'))); box.setAttribute('role','alert');
      view.replaceChildren(box);
    } finally {
      clearTimeout(timeout);
      if (serial === request) view.setAttribute('aria-busy','false');
    }
  }
  document.querySelector('.skip-link').addEventListener('click', event => {
    event.preventDefault(); document.getElementById('content').focus();
  });
  window.addEventListener('hashchange', render);
  // An open page follows the workspace: every 15 s (only while visible) home is read again, and the page is drawn anew
  // only when something changed and you are not in the middle of something (typing, a box with text, a request waiting).
  let lastHome = null;
  const busy = () => asked.size > 0 || ['TEXTAREA', 'INPUT'].includes(document.activeElement?.tagName)
    || [...view.querySelectorAll('textarea')].some(t => t.value.trim()) || !!document.querySelector('dialog[open]');
  async function follow() {
    if (document.visibilityState !== 'visible' || busy() || view.getAttribute('aria-busy') === 'true') return;
    try {
      const data = await read('/api/home');
      if (lastHome !== null && JSON.stringify({...data, generated_at: null}) !== lastHome && !busy()) render();
    } catch (_) { /* the next tick tries again */ }
  }
  setInterval(follow, 15000);
  render();
})();
