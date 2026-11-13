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
  function link(label, href, primary = false) {
    const el = node('a', label, primary ? 'btn primary' : 'btn outline sm');
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
      const li = node('li', (done ? '✓ ' : stage.stop ? '◇ ' : '') + text(stage.label || stage.stage), done ? 'complete' : '');
      if (stage.stage === order.stage) li.setAttribute('aria-current', 'step');
      el.append(li);
    }
    return el.children.length ? el : meta('The line is not planned yet.');
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
  function home(data) {
    const orders = array(data.orders), auto = data.autopilot;
    view.append(heading('Factory', 'Your ideas, planned runs, and the stops that need you.'));
    const autoCard = card('Autopilot', group('row between',
      group('stack', badge(auto?.on ? 'On' : 'Off'), meta(auto?.on ? 'Until ' + text(auto.until) + ' · ' + text(auto.decided_today) + ' decisions today' : 'Your agent asks you at the planned stops.')),
      link('View grants & decisions', '#/autopilot')));
    autoCard.classList.add('f-autopilot'); view.append(autoCard);
    if (!orders.length) {
      view.append(card('Start with an idea', p('Tell your agent an idea in Chat — it plans the run here.'), link('Open Chat', '/#chat', true))); return;
    }
    const primary = group('stack'), secondary = group('stack');
    const section = (parent, title, rows, render, empty) => {
      const el = node('section', null, 'f-section'); el.append(node('h2', title));
      el.append(...(rows.length ? rows.map(render) : [meta(empty)])); parent.append(el);
    };
    section(primary, 'Proposals waiting for Start', orders.filter(o => o.phase === 'proposed'), o => {
      const c = card(o.title, meta(text(o.owner_min) + ' min of your time'), orderLink(o, 'Read proposal', '/proposal'));
      c.classList.add('f-attention'); return c;
    }, 'No proposals waiting for Start.');
    section(primary, 'Needs you · stops', orders.filter(o => o.open && o.phase !== 'proposed'), o => {
      const c = card(o.title, badge(o.stage || o.open.kind), p(o.open.text), orderLink(o, 'Review order'), ticket(o.id));
      c.classList.add('f-attention'); return c;
    }, 'No stops waiting for you.');
    section(primary, 'Running', orders.filter(o => o.phase === 'started'), o => card(o.title, stages(o), budget(o),
      meta('ETA ' + text(o.eta)), orderLink(o)), 'No running orders.');
    // The summary contract has no shipped timestamp. Do not infer a week from due dates.
    section(secondary, 'Shipped this week', orders.filter(o => o.phase === 'shipped'), o => card('✓ ' + text(o.title), badge('Shipped'), orderLink(o)), 'No shipped work recorded.');
    secondary.append(meta('Shipped orders are listed from the workspace record; shipment dates are not available yet.'));
    section(secondary, 'Saved ideas', orders.filter(o => ['draft','edit','parked','cancelled','broken'].includes(o.phase)), o => card(o.title, badge(o.phase), orderLink(o)), 'No saved ideas.');
    view.append(group('f-grid', primary, secondary));
  }
  function line(items) {
    const el = node('ol', null, 'f-line');
    for (const item of array(items)) {
      const li = node('li', (item.stop ? '◇ ' : '') + text(item.label || item.stage), item.stop ? 'stop' : '');
      li.append(node('small', item.why)); el.append(li);
    }
    return el;
  }
  function crewPlan(crew) {
    return list(array(crew).map(c => text(c.role) + ' · ' + text(c.agent) + ' — ' + text(c.why)));
  }
  function limits(data) {
    const labels = {days:'Duration (days)', max_orders:'Maximum orders', active_min_per_day:'Active min / day', api_usd_per_day:'API USD / day'};
    return list(Object.entries(data || {}).map(([key, value]) => (labels[key] || key) + ': ' + text(value) + (key.endsWith('_per_day') ? ' · target, not enforced yet' : '')));
  }
  const alwaysAsks = ['Ship and anything that cannot be undone.', 'Scope changes and budget beyond the limits.', 'Crew outside an approved proposal.', 'New connections or credentials and other workspaces.', 'Starting an order, budget questions, and creating, renewing or widening Autopilot.'];
  function proposal(order) {
    const data = order.proposal;
    view.append(heading(data?.title || order.title, 'Run proposal · review the whole run before answering', orderLink(order)));
    if (!data) { view.append(card('No frozen proposal yet', p('Your agent is still planning this order.'), answer(order.id))); return; }
    view.append(p(data.goal));
    if (data.kind === 'autopilot') {
      view.append(group('grid-2', card('May decide', list(data.may_decide), list(data.examples)), card('Limits', limits(data.limits))), card('What always asks you', list(alwaysAsks)), card('Done means', list(data.done_means)), answer(order.id)); return;
    }
    const time = data.time || {}, b = data.budget || {};
    view.append(group('f-three', card('The line', line(data.line)),
      card('Time + budget', p(text(time.active_min) + ' active min · API target $' + text(b.api_usd_target)),
        p('ETA ' + text(time.eta_from) + ' – ' + text(time.eta_to)), meta('Budget preset · ' + text(b.preset)),
        meta('Active time cap: ' + text(b.active_min_cap) + ' min. API spend is a target, not a cap.'), meta('Your time: about ' + text(time.owner_min) + ' min.')),
      card('Crew + what it needs', crewPlan(data.crew), list(array(data.needs).map(n => (n.ready ? '✓ Ready · ' : 'Needs you · ') + text(n.what) + (!n.ready && n.fix ? ' — ' + n.fix : '')), 'No additional needs recorded.'))));
    view.append(group('grid-2', card('Done means', list(data.done_means)), card('Won’t do', list(data.wont_do), node('h3','What Ship does'), p(data.ship?.does), meta('Undo: ' + text(data.ship?.undo)))));
    const assumptions = card('Assumptions');
    for (const a of array(data.assumptions)) assumptions.append(group('row', ...(a.uncertain ? [badge('Unsure')] : []), p(a.text)));
    if (!array(data.assumptions).length) assumptions.append(meta('No assumptions recorded.'));
    assumptions.append(meta('Resolve unsure assumptions on the ticket before Start.'));
    view.append(assumptions, answer(order.id));
    const details = node('details', null, 'f-details');
    details.append(node('summary', 'Details · full line, crew, plan & tasks'), group('stack', line(data.line), node('h3','Crew'), crewPlan(data.crew),
      node('h3','Tasks'), list(array(data.tasks).map(t => text(t.title) + ' · ' + text(t.slug) + ' · ' + text(t.role) + ' · ' + text(t.stage) + (array(t.proves).length ? ' · proves: ' + t.proves.map(i => array(data.done_means)[i] || i).join('; ') : ''))),
      node('h3','Skipped stages'), list(array(data.skipped).map(s => text(s.stage) + ' — ' + text(s.why))),
      node('h3','Handovers'), list(array(data.handovers).map(h => text(h.task) + ' → ' + text(h.workspace) + ' — ' + text(h.why)))));
    view.append(details);
  }
  function tiny(order) { return card('Changed during the run', list(array(order.tiny).map(t => text(t.what) + ' · +' + text(t.minutes) + ' min'), 'No tiny changes recorded.')); }
  function orderPage(order) {
    view.append(heading(order.title, text(order.phase) + ' · ' + text(order.stage) + ' · ETA ' + text(order.eta), orderLink(order, 'Read proposal', '/proposal')));
    const main = group('stack', card('The line', stages(order)), card('Time + budget', budget(order), meta('Due ' + text(order.due))));
    const crew = card('Crew now');
    for (const c of array(order.crew)) crew.append(group('f-record', ticket(c.ticket, c.title || c.role, false), meta([c.role,c.agent,c.status].filter(Boolean).join(' · '))));
    if (!array(order.crew).length) crew.append(meta('No crew assigned yet.'));
    main.append(crew, tiny(order));
    const timeline = node('ol', null, 'f-timeline');
    for (const a of array(order.activity)) { const li = node('li'); li.append(meta(a.at), p(a.text)); timeline.append(li); }
    main.append(card('Activity', timeline.children.length ? timeline : meta('No activity recorded.')));
    const aside = group('stack');
    if (order.open) { const question = card('Needs you', badge(order.open.kind), p(order.open.text), list(order.open.options), answer(order.id)); question.classList.add('f-attention'); aside.append(question); }
    if (order.problem) aside.append(card('Record needs attention', p(order.problem), ticket(order.id, 'Open order ticket', false)));
    const changes = card('Changes');
    for (const c of array(order.changes)) changes.append(group('f-record', badge(c.state), node('h3', c.title), meta('+' + text(c.adds_min) + ' min'), ...(c.state === 'open' ? [ticket(order.id)] : [])));
    if (!array(order.changes).length) changes.append(meta('No changes proposed.'));
    aside.append(changes);
    const stops = card('Stops');
    for (const s of array(order.stops)) if (validVersion(s.n)) stops.append(group('f-record', orderLink(order, text(s.stage) + ' · round ' + s.n, '/stop/' + s.n), meta([s.state,s.answer,s.by].filter(Boolean).join(' · '))));
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
    view.append(heading(text(stop.stage) + ' · stop review', order.title, orderLink(order)), meta([stop.state,stop.answer,stop.by].filter(Boolean).join(' · ')));
    for (const [index, item] of array(data.items).entries()) {
      const compare = group('f-compare', preview(order, 'Before', item.before), preview(order, 'After', item.after));
      const c = card(item.title, badge(item.tag), compare);
      if (imageName(item.before) && imageName(item.after)) {
        const label = node('label', 'Compare before / after', 'stack');
        const range = node('input', null, 'f-range'); range.type = 'range'; range.min = '15'; range.max = '85'; range.value = '50';
        range.setAttribute('aria-label', 'Before and after comparison balance · item ' + (index + 1));
        range.addEventListener('input', () => { const split = Number(range.value); compare.style.gridTemplateColumns = 'minmax(0,' + split + 'fr) minmax(0,' + (100 - split) + 'fr)'; });
        label.append(range); c.append(label);
      }
      if (item.recommend) c.append(meta('Agent recommends: ' + item.recommend));
      c.append(meta('Review images and pins are view-only here. Add feedback on the order ticket.')); view.append(c);
    }
    view.append(group('grid-2', card('Checked', list(data.checked)), card('Not checked', list(data.not_checked))),
      card('Changed during the run', list(data.changed_during_run)), answer(order.id));
  }
  function autopilot(data) {
    view.append(heading('Autopilot', 'Bounded permission for your agent. Ship still asks you.'));
    const grants = card('Grants');
    for (const grant of array(data.grants)) grants.append(group('f-record', node('h3', 'Until ' + text(grant.until)), node('h3', 'May decide'), list(grant.may), limits(grant.limits), ticket(grant.order, 'Open grant ticket', false)));
    if (!array(data.grants).length) grants.append(meta('No grants recorded.'));
    const decisions = card('Decisions');
    for (const d of array(data.decisions)) decisions.append(group('f-record', node('h3', d.answer), p('Decided by your agent · ' + text(d.why)), meta(text(d.at) + ' · ' + text(d.q)), ticket(d.order, 'Open order ticket', false)));
    if (!array(data.decisions).length) decisions.append(meta('No agent decisions recorded.'));
    view.append(group('grid-2', grants, card('What always asks you', list(alwaysAsks))), decisions);
  }
  function draftTabs(order, selected) {
    const nav = node('nav', null, 'f-tabs'); nav.setAttribute('aria-label', 'Draft versions');
    for (const d of array(order.drafts)) if (validVersion(d.v)) {
      const a = orderLink(order, 'Version ' + d.v, '/draft/' + d.v);
      if (String(d.v) === selected) a.setAttribute('aria-current','page');
      if (d.at) a.title = text(d.at); nav.append(a);
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
