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
  function answer(id) {
    return group('stack', group('actions', ticket(id)), meta("You answer on the order's ticket, where orch confirms it's you."));
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
  function home(data) {
    const orders = array(data.orders), auto = data.autopilot;
    const needing = orders.filter(o => o.open);
    const minutes = needing.reduce((sum, o) => sum + (Number.isFinite(Number(o.owner_min)) && o.owner_min !== null ? Number(o.owner_min) : 0), 0);
    view.append(heading('Factory', needing.length
      ? plural(needing.length, 'thing needs you', 'things need you') + (minutes ? ' · about ' + minutes + ' min of your time' : '')
      : 'Nothing needs you right now. Your ideas and planned runs are below.'));
    let autoCard;
    if (auto?.on) {
      const days = Math.max(0, Math.ceil((Date.parse(auto.until) - Date.now()) / 864e5));
      autoCard = card('Autopilot on · ' + (days > 1 ? days + ' days left' : days === 1 ? '1 day left' : 'ends today'),
        meta('Ends ' + when(auto.until) + ' · ' + plural(Number(auto.decided_today) || 0, 'decision', 'decisions') + ' today'),
        meta('Your agent answers routine stops. Ship still asks you.'),
        tail(link('What it decided', '#/autopilot')));
    } else {
      autoCard = card('Autopilot off', meta('Your agent asks you at every planned stop.'), ...(auto ? [tail(link('What it decided', '#/autopilot'))] : []));
    }
    autoCard.classList.add('f-autopilot'); view.append(autoCard);
    if (!orders.length) {
      view.append(card('Start with an idea', p('Tell your agent an idea in Chat — it plans the run here.'), tail(link('Open Chat', '/#chat', true)))); return;
    }
    const primary = group('stack'), secondary = group('stack');
    const section = (parent, title, rows, render, empty) => {
      const el = node('section', null, 'f-section'); el.append(node('h2', title));
      el.append(...(rows.length ? rows.map(render) : [meta(empty)])); parent.append(el);
    };
    section(primary, 'Proposals waiting for Start', orders.filter(o => o.phase === 'proposed'), o => {
      const need = yourTime(o.owner_min);
      const c = card(o.title, ...(need ? [meta(capital(need))] : []), tail(orderLink(o, 'Read proposal', '/proposal')));
      c.classList.add('f-attention'); return c;
    }, 'No proposals waiting for Start.');
    section(primary, 'Needs you · stops', orders.filter(o => o.open && o.phase !== 'proposed'), o => {
      const c = card(o.title, node('h3', openTitle(o, o.open)), ...openBody(o, o.open, false), rawDetails(o.open),
        tail(ticket(o.id, 'Answer in the ticket', true), orderLink(o, 'Review order')));
      c.classList.add('f-attention'); return c;
    }, 'No stops waiting for you.');
    section(primary, 'Running', orders.filter(o => o.phase === 'started'), o => o.kind === 'autopilot'
      ? card(o.title, meta('Autopilot order'), p('Routine stops answered by your agent · Ship still asks you'), tail(link('What it decided', '#/autopilot')))
      : card(o.title, stages(o), budget(o), meta('ETA ' + when(o.eta)), tail(orderLink(o))), 'No running orders.');
    // The summary contract has no shipped timestamp. Do not infer a week from due dates.
    section(secondary, 'Shipped', orders.filter(o => o.phase === 'shipped'), o => card('✓ ' + text(o.title), badge('Shipped'), tail(orderLink(o))), 'No shipped work recorded.');
    secondary.append(meta('Shipped orders are listed from the workspace record; shipment dates are not available yet.'));
    section(secondary, 'Saved ideas', orders.filter(o => ['draft','edit','parked','cancelled','broken'].includes(o.phase)), o => card(o.title, badge(capital(o.phase)), tail(orderLink(o))), 'No saved ideas.');
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
    if (data.active_min_per_day != null) rows.push('Target: ' + duration(data.active_min_per_day) + ' of active work a day · not enforced yet');
    if (data.api_usd_per_day != null) rows.push('Target: $' + text(data.api_usd_per_day) + ' of API spend a day · not enforced yet');
    return list(rows);
  }
  const mayDecide = {routine: 'Routine improvements', taste: 'Taste decisions within your house rules'};
  const alwaysAsks = ['Shipping: the final Ship stop.', 'Anything that cannot be undone.', 'Scope changes and budget beyond the limits.', 'New connections or credentials.', 'Anything touching another workspace.', 'Creating, renewing or widening Autopilot.'];
  function proposal(order) {
    const data = order.proposal;
    view.append(heading(data?.title || order.title, data?.kind === 'autopilot' ? 'Autopilot proposal · ' + text(data.goal) : 'Run proposal · review the whole run before answering', orderLink(order)));
    if (!data) { view.append(card('No frozen proposal yet', p('Your agent is still planning this order.'), answer(order.id))); return; }
    if (data.kind === 'autopilot') {
      const l = data.limits || {};
      const parts = [];
      if (l.days != null) parts.push(plural(Number(l.days), 'day', 'days'));
      if (l.max_orders != null) parts.push('at most ' + plural(Number(l.max_orders), 'order', 'orders') + ' at once');
      if (data.report_at) parts.push('daily report at ' + data.report_at);
      view.append(node('p', parts.join(' · '), 'f-summary'),
        group('grid-2', card('May decide', list(array(data.may_decide).map(x => mayDecide[x] || capital(x))), ...(array(data.examples).length ? [meta('Examples: ' + array(data.examples).join('; '))] : [])),
          card('Always asks you', list(alwaysAsks))),
        card('Limits & duration', limits(data.limits)), card('Done means', list(data.done_means)), answer(order.id)); return;
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
    view.append(group('grid-2', card('Done means', list(data.done_means)), card('Won’t do', list(data.wont_do), node('h3','What Ship does'), p(data.ship?.does), meta('Undo: ' + text(data.ship?.undo)))));
    const assumptions = card('Assumptions');
    for (const a of array(data.assumptions)) assumptions.append(group('row', ...(a.uncertain ? [badge('Unsure')] : []), p(a.text)));
    if (!array(data.assumptions).length) assumptions.append(meta('No assumptions recorded.'));
    assumptions.append(meta('Resolve unsure assumptions on the ticket before Start.'));
    view.append(assumptions, answer(order.id));
    const details = node('details', null, 'f-details');
    details.append(node('summary', 'Details · full line, crew, plan & tasks'), group('stack', line(data.line), node('h3','Crew'), crewPlan(data.crew),
      node('h3','Tasks'), list(array(data.tasks).map(t => text(t.title) + ' · ' + text(t.slug) + ' · ' + roleName(t.role) + ' · ' + capital(t.stage) + (array(t.proves).length ? ' · proves: ' + t.proves.map(i => array(data.done_means)[i] || i).join('; ') : ''))),
      node('h3','Skipped stages'), list(array(data.skipped).map(s => capital(s.stage) + ' — ' + text(s.why))),
      node('h3','Handovers'), list(array(data.handovers).map(h => text(h.task) + ' → ' + text(h.workspace) + ' — ' + text(h.why)))));
    view.append(details);
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
    const lineCard = card('The line', stages(order), ...(order.kind === 'run' && order.phase === 'started' ? [nextStop(order)].filter(Boolean) : []));
    const main = group('stack', lineCard, card('Time + budget', budget(order), meta('Due ' + when(order.due))));
    const crew = card('Crew now');
    for (const c of array(order.crew)) {
      const label = [roleName(c.role), c.agent, statusWord[c.status] || c.status].filter(Boolean).join(' · ');
      const row = group('f-record f-crew');
      if (validId(c.ticket)) { const a = link(label + ' ↗', '/#ticket/' + c.ticket); a.className = 'f-crewlink'; a.title = c.title || ''; row.append(a); } else row.append(node('span', label));
      row.append(meta(c.title));
      crew.append(row);
    }
    if (!array(order.crew).length) crew.append(meta('No crew assigned yet.'));
    main.append(crew, tiny(order));
    const timeline = node('ol', null, 'f-timeline');
    for (const a of array(order.activity)) { const li = node('li'); li.append(meta(when(a.at)), p(noIso(a.text))); timeline.append(li); }
    main.append(card('Activity', timeline.children.length ? timeline : meta('No activity recorded.')));
    const aside = group('stack');
    if (order.open) {
      const question = card('Needs you', node('h3', openTitle(order, order.open)), ...openBody(order, order.open, true), rawDetails(order.open), answer(order.id));
      question.classList.add('f-attention'); aside.append(question);
    }
    if (order.problem) aside.append(card('Record needs attention', p(order.problem), group('actions', ticket(order.id, 'Open order ticket', false))));
    const changes = card('Changes');
    for (const c of array(order.changes)) changes.append(group('f-record', badge(capital(c.state)), node('h3', c.title), meta('+' + text(c.adds_min) + ' min'), ...(c.state === 'open' ? [group('actions', ticket(order.id))] : [])));
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
  function stopPage(order, round) {
    const stop = array(order.stops).find(s => String(s.n) === round);
    if (!stop) throw new Error('Stop not found');
    const data = stop.data || {};
    view.append(heading(stageName(order, stop.stage) + ' · stop review', order.title, orderLink(order)), meta([({open: 'Waiting for you', decided: 'Decided by your agent', answered: 'Answered', ignored: 'Not counted'})[stop.state] || stop.state, stop.answer].filter(Boolean).join(' · ')));
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
    view.append(group('grid-2', card('Checked', list(data.checked)), card('Not checked', list(data.not_checked))),
      card('Changed during the run', list(data.changed_during_run)), answer(order.id));
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
    view.replaceChildren(group('f-loading', node('p', 'Reading the Factory record…'), ...['title','thumb','thumb'].map(c => { const el = node('div', null, 'skeleton ' + c); el.setAttribute('aria-hidden','true'); return el; })));
    try {
      // Always begin with home, including deep links, to get watcher/stale status.
      const homeData = await read('/api/home', signal);
      if (serial !== request) return;
      showNotices(homeData);
      const hash = location.hash || '#/';
      let draw;
      if (hash === '#/' || hash === '#content') draw = () => home(homeData);
      else if (hash === '#/autopilot') {
        const data = await read('/api/autopilot', signal);
        if (serial !== request) return;
        showNotices(homeData, data); draw = () => autopilot(data);
      } else {
        const match = /^#\/order\/(t_[a-z0-9]{6,16})(?:\/(proposal)|\/(stop|draft)\/([1-9][0-9]*))?$/.exec(hash);
        if (!match || !validId(match[1]) || (match[4] && !validVersion(match[4]))) throw new Error('Unknown route');
        const order = await read('/api/order/' + match[1], signal);
        if (serial !== request) return;
        if (order.id !== match[1]) throw new Error('Order reference mismatch');
        showNotices(homeData, order);
        if (match[2]) draw = () => proposal(order);
        else if (match[3] === 'stop') draw = () => stopPage(order, match[4]);
        else if (match[3] === 'draft') {
          const draft = await read('/api/order/' + match[1] + '/draft/' + match[4], signal);
          if (serial !== request) return;
          showNotices(homeData, order, draft);
          draw = () => view.append(heading(order.title, 'Draft · version ' + match[4], orderLink(order)), draftTabs(order, match[4]), node('pre', draft.text, 'card f-draft'), ...(draft.truncated ? [meta('This draft is too large to display in full. The text shown is truncated.')] : []));
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
  render();
})();
