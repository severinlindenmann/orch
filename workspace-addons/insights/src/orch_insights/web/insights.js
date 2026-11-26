/* Insights overview: numbers first, then what helpers use. Workspace text is always inserted as text nodes. */
'use strict';
const prefix = document.documentElement.dataset.prefix || '';
const byId = id => document.getElementById(id);
const TABS = [
  {id: 'skills', label: 'What helpers use', help: 'Skills are things your helpers know how to do. Orch is built in; marketplace skills are added from the catalogue.',
    caption: 'Skills used by helpers', columns: ['Skill', 'From', 'Last used', 'Uses this month', 'State']},
  {id: 'connections', label: 'Connected services', help: 'Connected services are outside tools your helpers can reach.',
    caption: 'Connected services', columns: ['Service', 'From', 'Allowed actions', 'Uses this month', 'State']},
  {id: 'keys', label: 'Keys', help: 'Key values are never shown or recorded.',
    caption: 'Keys used by helpers', columns: ['Key', 'Type', 'From', 'Last used', 'Uses this month', 'State']},
];
const kinds = {skill: 'skills', connection: 'connections', key: 'keys'};
const MARKS = {working: '✓ ', look: '▲ ', new: '◇ ', idle: '', unknown: ''};
const CANT_TELL = "Can't tell yet";
const BADGE = {success: 'done', warning: 'attn', info: 'working', '': ''};
let overview = null, lists = {}, active = 'skills', loading = false;
let stuckNow = 0;  // ORCH-476: the core's Stuck count (Stuck now): the health line never says All good beside it
// ORCH-1860: a failed read keeps the last good reading. readAt: when each part was last read well; failed: the parts
// whose last read failed (the error text). Only in memory: a lost sign-in or another workspace forgets them all.
let readAt = {}, failed = {}, workspace = null, era = 0, again = false;
const asked = {};  // per list: the number of its newest read; an older answer arriving later is dropped
const NAMES = {overview: 'the numbers', skills: 'the skills', connections: 'the connected services', keys: 'the keys'};
const READ_ERROR = 'Insights could not read the workspace record.';

function node(tag, text, className) {
  const element = document.createElement(tag);
  if (text !== undefined && text !== null) element.textContent = text;
  if (className) element.className = className;
  return element;
}

// An answer read before the page forgot everything (sign-in lost, another workspace) is dropped: `late`. A lost
// sign-in and a workspace change are said by read() itself, so its callers only stop (`said`).
const late = () => Object.assign(new Error('late'), {late: true});
const said = error => Boolean(error && (error.late || error.signin || error.moved));
async function read(path) {
  const mine = era;
  const response = await fetch(`${prefix}${path}`, {signal: AbortSignal.timeout(15000)});
  if (mine !== era) throw late();
  if (response.status === 401) {  // not signed in: say how to sign in (every read needs it, ORCH-481)
    const signin = new Error(await response.text());
    signin.signin = true;
    if (mine !== era) throw late();
    forget();
    showMessage(signin.message, false);
    throw signin;
  }
  if (!response.ok) throw new Error('read failed');
  const answer = await response.json();
  if (mine !== era) throw late();
  if (answer && typeof answer.ws === 'string') {
    if (workspace && answer.ws !== workspace) {  // another workspace answers here now: nothing read before is its
      forget();
      workspace = answer.ws;
      startOver();
      throw Object.assign(new Error('moved'), {moved: true});
    }
    workspace = answer.ws;
  }
  return answer;
}

// Drop every private value the page holds or shows: a lost sign-in or a workspace change (ORCH-1860).
function forget() {
  era++;
  overview = null; lists = {}; readAt = {}; failed = {}; stuckNow = 0;
  for (const id of ['metrics', 'bars', 'rows', 'thead', 'services', 'needs', 'models-bars', 'models-rows',
    'team-stats', 'people-rows', 'empty', 'overview-error', 'list-error']) byId(id).replaceChildren();
  for (const id of ['skill-text', 'trend-text', 'models-text', 'week-label', 'services-title', 'foot-note', 'lost-note',
    'health']) byId(id).textContent = '';
  for (const id of ['team', 'week', 'models', 'lost-note', 'overview-error', 'list-error', 'checkup']) byId(id).hidden = true;
  // the health check card is drawn by checkup.js; its proposals go too (its note element stays for checkup.js)
  for (const child of [...byId('checkup').children]) if (child.id !== 'checkup-note') child.remove();
}

const when = at => (window.UI && window.UI.stamp ? window.UI.stamp(at) : at.toLocaleTimeString());

// The master error banner (gallery: States) by the part that failed: what failed, the last good reading (or that
// nothing is shown), Try again and the error itself. Focus stays where it was: on Try again when it was there.
function paintFailure(host, part, onRetry) {
  const why = failed[part];
  const had = host.contains(document.activeElement);
  host.hidden = !why;
  if (!why) { host.replaceChildren(); if (had) byId('content').focus({preventScroll: true}); return; }
  const banner = node('div', undefined, 'banner error');
  banner.dataset.part = part;
  const text = node('div', undefined, 'grow');
  const at = readAt[part];
  text.append(node('h3', `${at ? 'Couldn’t refresh' : 'Couldn’t read'} ${NAMES[part]}`),
    node('p', at ? `Showing what was read ${when(at)}.` : 'Nothing is shown here until it can be read.'));
  const row = node('div', undefined, 'row space-top');
  const button = node('button', 'Try again', 'btn outline sm');
  button.type = 'button';
  button.addEventListener('click', async () => {
    if (button.getAttribute('aria-disabled') === 'true') return;
    button.setAttribute('aria-disabled', 'true');  // stays focusable (disabled would drop the focus)
    button.textContent = 'Trying again…';
    await onRetry();
  });
  row.append(button, node('p', why, 'meta'));
  text.append(row);
  const mark = node('span', '!', 'bad');
  mark.setAttribute('aria-hidden', 'true');
  banner.append(mark, text);
  host.replaceChildren(banner);
  if (had) button.focus({preventScroll: true});
}

function plural(n, word) { return `${n} ${word}${n === 1 ? '' : 's'}`; }

function lastUsed(row) {
  const text = row.last_used || '';
  if (text.startsWith('Last used ')) return text.charAt(10).toUpperCase() + text.slice(11);
  if (text.startsWith('Never used')) return 'Never';
  return text;
}

function showView(which) {
  byId('message').hidden = which !== 'message';
  byId('overview').hidden = which !== 'overview';
  byId('empty').hidden = which !== 'empty';
  byId('loading').hidden = which !== 'loading';
  byId('health').hidden = which !== 'overview';
  byId('view-region').setAttribute('aria-busy', String(which === 'loading'));
}

// The one master empty / error state (UI.state) in a host element; a plain line if the kit is missing.
function paintState(host, kind, title, text) {
  if (window.UI && window.UI.state) host.replaceChildren(window.UI.state({kind, title, text}));
  else host.textContent = title + (text ? ' ' + text : '');
}
// Nothing read yet (or the sign-in is gone): the error alone, never zeros or the first-day tiles. Try again shows
// the first loading shape again; a sign-in message has no Try again (a fresh sign-in link is the way on).
function showMessage(text, retry = true) {
  showView('message');
  const host = byId('message');
  if (window.UI && window.UI.state) {
    const action = retry ? {label: 'Try again', onClick: () => {
      const had = host.contains(document.activeElement);
      showView('loading');
      if (had) byId('content').focus({preventScroll: true});
      refresh();
    }} : undefined;
    host.replaceChildren(window.UI.state({kind: 'error', title: 'Insights can’t show this right now', text, action}));
  } else paintState(host, 'error', 'Insights can’t show this right now', text);
  overview = null;
}

// The stat tiles. A number is shown only when it is measured; an unmeasured one says "Not measured yet" (ORCH-72).
function metric(label, value, small) {
  const card = node('article', undefined, 'card metric');
  card.append(node('p', label, 'meta'), value === null ? node('p', 'Not measured yet') : node('strong', value), node('small', small));
  return card;
}

function servicesTile(view, small) {
  const {count, known} = view.tabs.connections;
  if (known) return metric('Connected services', String(count), small || (count ? 'Used by your helpers' : 'None connected'));
  // The full list is unknown: the services seen in use are still a true count (one number, ORCH-232); never a false 0.
  if (count) return metric('Connected services', String(count), 'Used by your helpers · there may be more');
  return metric('Connected services', null, 'orch can’t see this list yet');
}

// First day, nothing recorded yet: the same tiles as the overview, each saying when it fills.
function emptyTiles(view, team) {
  const note = 'Fills after a helper’s first work';
  // services already set up are ready now: "fills after the first work" beside a 3 contradicts the number
  const services = view.tabs.connections.count ? 'Ready for your helpers' : note;
  // No run is recorded: say so, never a 0 (the record can be empty although helpers worked, ORCH-139). When the
  // tickets show helper time, say where that comes from, so the page does not contradict itself (ORCH-410).
  const worked = team && team.time && team.time !== '–';
  // orch started runs but the helper wrote no record lines (a custom helper): say so, not "no runs" (ORCH-966).
  const started = view.started || 0;
  if (started) return [metric('Times helpers worked', null, `orch started ${plural(started, 'run')}; this helper does not report them, so they are not measured`), servicesTile(view, services)];
  return [metric('Times helpers worked', null, worked ? 'Not counted here; the helper time above comes from the tickets' : 'No work by helpers is recorded here yet'), servicesTile(view, services)];
}

function fillMetrics() {
  const first = overview.since && (Date.now() - Date.parse(overview.since)) < 31 * 86400000;
  byId('metrics').replaceChildren(
    metric('Times helpers worked', String(overview.runs), first ? 'First month of data' : 'In the last 30 days'),
    servicesTile(overview));
}

function fillTrend() {
  const runs = overview.runs;
  byId('trend-text').textContent =
    `Helpers worked ${plural(runs, 'time')}. Not enough days of work yet to draw a chart.`;
}

function fillBars() {
  const rows = (((lists.skills && lists.skills.rows) || []).filter(row => row.runs_of));
  const bars = byId('bars');
  bars.replaceChildren();
  // a failed skills read is not "no skill use": say it can't be shown yet; a kept reading says when it was read
  byId('skill-period').textContent = lists.skills && failed.skills ? `Read ${when(readAt.skills)}` : 'Last 30 days';
  if (!lists.skills && failed.skills) { byId('skill-text').textContent = 'Skill use can’t be shown until the skills are read.'; return; }
  if (!rows.length) { byId('skill-text').textContent = 'No skill use is recorded yet.'; return; }
  const top = rows[0];
  byId('skill-text').textContent = `${top.name} was used ${top.runs_used} of the ${top.runs_of} times helpers worked in the last 30 days.`;
  rows.slice(0, 5).forEach((row, index) => {
    const bar = node('div', undefined, index ? 'bar-row secondary' : 'bar-row');
    const head = node('div', undefined, 'row between');
    head.append(node('span', row.name), node('strong', `${row.runs_used} / ${row.runs_of}`));
    const meter = node('div', undefined, 'progress');
    meter.setAttribute('aria-label', `${row.name} used ${row.runs_used} of the ${row.runs_of} times helpers worked`);
    const fill = node('span');
    fill.style.setProperty('--value', `${Math.round(100 * row.runs_used / row.runs_of)}%`);
    meter.append(fill);
    bar.append(head, meter);
    bars.append(bar);
  });
}

const short = (n, d, unit) => `${(n / d).toFixed(1).replace(/\.0$/, "")}${unit}`;
const fmt = n => n >= 1e6 ? short(n, 1e6, "M") : n >= 1e3 ? short(n, 1e3, "k") : String(n);

// Work and tokens come from two records: work without recorded tokens is not "no helper work" (ORCH-232).
function modelsEmptyText(view, runs) {
  return runs > 0 ? 'Token use isn’t recorded for this work yet.' : view.text;
}

function renderModels(view) {
  const host = byId('models');
  if (!view || view.error) { host.hidden = true; return; }
  host.hidden = false;
  const bars = byId('models-bars'), rows = byId('models-rows');
  bars.replaceChildren();
  rows.replaceChildren();
  rows.hidden = view.empty;
  byId('models-more').hidden = view.empty;
  if (view.empty) { byId('models-text').textContent = modelsEmptyText(view, overview && overview.runs); return; }
  byId('models-text').textContent = view.moved_text + '.';
  const most = Math.max(...view.models.map(m => m.tokens));
  view.models.forEach((m, index) => {
    const bar = node('div', undefined, index ? 'bar-row secondary' : 'bar-row');
    const head = node('div', undefined, 'row between');
    head.append(node('span', m.label), node('strong', `${fmt(m.tokens)} tokens`));
    const meter = node('div', undefined, 'progress');
    meter.setAttribute('aria-label', `${m.label}: ${m.tokens} tokens`);
    const fill = node('span');
    fill.style.setProperty('--value', `${Math.round(100 * m.tokens / most)}%`);
    meter.append(fill);
    bar.append(head, meter);
    bars.append(bar);
  });
  for (const t of view.tickets) {
    // one line per ticket: the title is cut with an ellipsis, the tokens stay right-aligned on the same row
    const item = node('div', undefined, 'list-row');
    item.setAttribute('role', 'listitem');
    const name = node('div', undefined, 'grow');
    name.append(node('strong', t.key), node('div', t.title, 'meta truncate'));
    const tokens = node('div', undefined, 'numeric');  // one short line per model, right-aligned
    const parts = t.parts.length ? t.parts : [{ label: '', tokens: t.tokens }];
    tokens.append(...parts.map(p => node('div', `${p.label} ${fmt(p.tokens)}`.trim(), 'meta truncate')));
    item.append(name, tokens);
    rows.append(item);
  }
}

// ORCH-189 manager view: four numbers and one row per person, from the helpers' conversations (not the record,
// so it shows on a first day too). Cost is at list price.
function statTile(label, value, small) {
  const tile = node('article', undefined, 'stat-tile');
  tile.append(node('span', label, 'stat-label'), node('span', value, 'stat-value'), node('span', small, 'stat-delta'));
  return tile;
}
function renderTeam(team) {
  if (team) stuckNow = Number(team.stuck) > 0 ? Number(team.stuck) : 0;  // a team that failed to load keeps the last count
  if (overview) renderNeeds();
  const host = byId('team');
  if (!team) { host.hidden = true; return; }
  host.hidden = false;
  byId('team-stats').replaceChildren(
    statTile('Helper time', team.time, 'Last 30 days'),
    statTile('Cost', team.cost, team.note || 'at list price'),
    statTile('Tickets finished', String(team.finished), team.each || 'Last 30 days'),
    statTile('Stuck now', String(team.stuck), team.stuck ? 'See Stuck on the Tickets page' : 'Nothing is stuck'));
  const rows = byId('people-rows');
  rows.replaceChildren(...team.people.map(p => {
    const tr = node('tr');
    tr.append(node('td', p.name), node('td', String(p.finished), 'numeric'), node('td', String(p.open), 'numeric'),
      node('td', p.time, 'numeric'), node('td', p.cost, 'numeric'));
    return tr;
  }));
  byId('people').hidden = !team.people.length;
}
// ORCH-297: one bar for this week against the weekly budget set in Usage; no bar when there is none.
function renderWeek(week) {
  const host = byId('week');
  if (!week) { host.hidden = true; return; }
  host.hidden = false;
  byId('week-label').textContent = week.label;
  const bar = byId('week-bar');
  bar.setAttribute('aria-valuenow', String(week.percent));
  bar.setAttribute('aria-valuetext', week.label);
  bar.firstElementChild.style.setProperty('--value', `${week.percent}%`);
}
function renderLost(view) {
  const note = byId('lost-note');
  note.hidden = !(view && view.lost);
  note.textContent = view && view.lost ? view.lost.text : '';
}
// The models and the week are asked for at once, side by side with the overview (ORCH-1621: one after the
// other, the page waited for each answer in turn).
function askModels() {
  return {models: read('/api/models').catch(() => null), week: read('/api/week').then(a => a.week).catch(() => null)};
}
async function loadModels(asked = askModels()) {
  const mine = era;
  const view = await asked.models;
  if (mine !== era) return null;  // asked before the page forgot everything
  renderTeam(view && !view.error ? view.team : null);
  const week = await asked.week;
  if (mine !== era) return null;
  renderWeek(view && !view.error && view.team ? week : null);
  renderModels(view);
  return view && !view.error ? view.team : null;
}

function stateBadge(row) {
  const badge = node('span', `${MARKS[row.health] || ''}${row.state.text}`, `badge ${BADGE[row.state.tone] || ''}`.trim());
  return badge;
}

function nameCell(row) {
  const cell = node('td');
  cell.append(node('strong', row.name));
  const facts = [row.numbers === "Can't tell yet" ? '' : row.numbers, row.unseen, row.versions, row.also].filter(Boolean);
  for (const fact of facts) cell.append(node('span', fact, 'subline'));
  return cell;
}

function rowCells(tab, row) {
  const uses = node('td', row.uses === null || row.uses === undefined ? '–' : String(row.uses), 'numeric');
  if (tab === 'connections') return [nameCell(row), node('td', row.source), node('td', row.allowed), uses];
  if (tab === 'keys') return [nameCell(row), node('td', row.type), node('td', row.source), node('td', lastUsed(row)), uses];
  return [nameCell(row), node('td', row.source), node('td', lastUsed(row)), uses];
}

function renderTable() {
  const tab = TABS.find(entry => entry.id === active);
  const answer = lists[active];
  byId('table-caption').textContent = tab.caption;
  byId('tab-help').textContent = tab.help;
  const head = node('tr');
  tab.columns.forEach((label, index) => {
    const th = node('th', label, label.startsWith('Uses') ? 'numeric' : '');
    th.scope = 'col';
    head.append(th);
  });
  byId('thead').replaceChildren(head);
  const body = byId('rows');
  body.replaceChildren();
  paintFailure(byId('list-error'), active, () => retryList(active));
  byId('panel').hidden = !answer && !!failed[active];  // no reading and a failed read: the banner says it all
  byId('panel').classList.toggle('space-top', !!failed[active]);  // room between the banner and the kept table
  if (!answer) {
    const tr = node('tr'), td = node('td', 'Reading the workspace record…', 'muted');
    td.colSpan = tab.columns.length;
    tr.append(td); body.append(tr);
    return;
  }
  if (!answer.rows.length) {
    const tr = node('tr'), td = node('td', 'Nothing here in the last 30 days.', 'muted');
    td.colSpan = tab.columns.length;
    tr.append(td); body.append(tr);
    return;
  }
  for (const row of answer.rows) {
    const tr = node('tr');
    tr.dataset.name = row.name;
    tr.tabIndex = -1;
    tr.append(...rowCells(active, row), (() => { const td = node('td'); td.append(stateBadge(row)); return td; })());
    body.append(tr);
  }
}

function renderTabs() {
  const tabs = byId('tabs');
  const focused = tabs.contains(document.activeElement) ? document.activeElement.dataset.tab : null;
  tabs.replaceChildren();
  const shown = TABS.filter(tab => tab.id === 'skills' || (overview.tabs[tab.id] && overview.tabs[tab.id].count));
  if (!shown.some(tab => tab.id === active)) active = 'skills';
  for (const tab of shown) {
    const count = overview.tabs[tab.id].count;
    const button = node('button', shown.length > 1 ? `${tab.label} · ${count}` : tab.label, 'btn ghost sm');
    button.type = 'button';
    button.id = `tab-${tab.id}`;
    button.dataset.tab = tab.id;
    button.setAttribute('role', 'tab');
    button.setAttribute('aria-controls', 'panel');
    button.setAttribute('aria-selected', String(tab.id === active));
    button.tabIndex = tab.id === active ? 0 : -1;
    button.addEventListener('click', () => selectTab(tab.id));
    tabs.append(button);
  }
  byId('panel').setAttribute('aria-labelledby', `tab-${active}`);
  // a refresh redraws the tabs: the focus stays on the tab it was on, and the page does not scroll
  const back = focused && byId(`tab-${focused}`);
  if (back) back.focus({preventScroll: true});
}

function renderServices() {
  const {count, known} = overview.tabs.connections;
  byId('services-title').textContent = known || count ? `Connected services · ${count}` : 'Connected services';
  const box = byId('services');
  const answer = lists.connections;
  if (!count) { box.textContent = known ? 'No connected services are recorded.' : 'Not measured yet.'; return; }
  if (!answer) { box.textContent = `${plural(count, 'connected service')} recorded.`; return; }
  box.replaceChildren(...answer.rows.map(row => {
    const line = node('p');
    // Only what is known: "Can't tell yet" twice on one line says nothing (ORCH-232).
    const known = [row.state && row.state.text, row.allowed].filter(text => text && text !== CANT_TELL);
    line.append(node('strong', row.name), document.createTextNode(known.map(text => ` · ${text}`).join('')));
    return line;
  }));
}

function renderNeeds() {
  const needs = byId('needs');
  needs.replaceChildren();
  const retry = overview.retries;
  needs.hidden = !overview.needs.length && !retry;
  if (retry) {
    const banner = node('article', undefined, `banner ${retry.tone === 'warn' ? 'attn' : 'info'}`);
    const text = node('div', undefined, 'grow');
    text.append(node('strong', retry.title), node('p', retry.text));
    banner.append(text);
    needs.append(banner);
  }
  for (const card of overview.needs) {
    const banner = node('article', undefined, `banner ${card.tone === 'warn' ? 'attn' : 'info'}`);
    const text = node('div', undefined, 'grow');
    text.append(node('strong', card.title), node('p', card.text));
    const button = node('button', card.button, 'btn outline sm');
    button.type = 'button';
    button.addEventListener('click', () => lookAt(card));
    banner.append(text, button);
    needs.append(banner);
  }
  // a stuck ticket needs a look too: the same count as the Stuck now tile (the core's one Stuck rule)
  const n = overview.needs.length + (retry && retry.tone === 'warn' ? 1 : 0) + stuckNow;
  const health = byId('health');
  health.className = n ? 'badge attn insights-health' : 'badge done insights-health';
  health.textContent = n ? `▲ ${n} ${n === 1 ? 'needs' : 'need'} a look` : 'All good · nothing needs a look';
}

async function lookAt(card) {
  await selectTab(kinds[card.kind]);
  const row = [...byId('rows').children].find(tr => tr.dataset.name === card.target);
  if (row) { row.scrollIntoView({block: 'center'}); row.focus(); row.setAttribute('data-motion', 'new'); }
}

function renderAll() {
  paintFailure(byId('overview-error'), 'overview', () => refresh());
  fillMetrics();
  fillTrend();
  fillBars();
  renderNeeds();
  renderTabs();
  renderTable();
  renderServices();
  const foot = [];
  if (overview.sharing.on) foot.push(overview.sharing.chip);
  foot.push('Recorded activity');
  byId('foot-note').textContent = foot.join(' · ');
}

// One list read. A failure keeps the list read before (if any) and marks the list failed; only a lost sign-in or
// another workspace ends the page's view. An answer older than the list's newest read is dropped. Returns true
// when the list may be drawn again.
async function loadList(tab, ask = null) {
  const n = asked[tab] = (asked[tab] || 0) + 1;
  let answer;
  try {
    answer = await (ask || read(`/api/list/${tab}`));
  } catch (error) {
    if (said(error) || n !== asked[tab]) return false;
    failed[tab] = READ_ERROR;
    return true;
  }
  if (n !== asked[tab]) return false;
  if (answer.error) { failed[tab] = answer.error; return true; }
  lists[tab] = answer;
  readAt[tab] = new Date();
  delete failed[tab];
  return true;
}

// Draw again what one list feeds: the table when it is the chosen tab, the services block, the skill bars.
function redrawList(tab) {
  if (!overview || byId('overview').hidden) return;
  if (tab === active) renderTable();
  if (tab === 'connections') renderServices();
  if (tab === 'skills') fillBars();
}

async function retryList(tab) {
  if (await loadList(tab)) redrawList(tab);
}

async function selectTab(tab) {
  active = tab;
  renderTabs();
  renderTable();
  if (!lists[tab] && !failed[tab] && await loadList(tab)) redrawList(tab);
}

// Another workspace answers here now: the first loading shape, then a fresh first read.
function startOver() {
  showView('loading');
  if (loading) again = true; else refresh();
}

// The overview could not be read: keep the numbers read before, with the banner on top; nothing read yet (or only
// the first-day tiles): the error alone, with Try again.
function overviewFailed(text) {
  if (overview && !overview.first_day && !byId('overview').hidden) {
    failed.overview = text;
    paintFailure(byId('overview-error'), 'overview', () => refresh());
  } else showMessage(text);
}

async function refresh() {
  if (document.hidden || loading) return;
  loading = true;
  try {
    const models = askModels(), skills = read('/api/list/skills');
    skills.catch(() => {});  // read again below; an early failure is said there
    let answer;
    try { answer = await read('/api/overview'); } catch (error) {
      if (said(error)) return;
      overviewFailed(READ_ERROR);
      return;
    }
    if (answer.error) { overviewFailed(answer.error); return; }
    overview = answer;
    readAt.overview = new Date();
    delete failed.overview;
    renderLost(overview);
    if (overview.first_day) {
      // The tiles come at once; the models read (`orch tokens`, every ticket of 30 days) can take seconds at 10,000
      // tickets, so the team and the helper-time note follow when it answers (ORCH-2288).
      const mine = era, first = overview;
      const paint = team => {
        const grid = node('div', undefined, 'metric-grid');
        grid.append(...emptyTiles(first, team));
        byId('empty').replaceChildren(grid);
      };
      showView('empty');
      paint(null);
      const team = await loadModels(models);
      if (mine !== era || overview !== first) return;
      if (team) paint(team);
      return;
    }
    const mine = era;
    await loadList('skills', skills);
    if (mine !== era || !overview) return;  // the sign-in was lost or another workspace answered meanwhile
    showView('overview');
    renderAll();
    loadModels(models);
    for (const tab of ['connections', 'keys']) {
      if (overview.tabs[tab].count && await loadList(tab)) redrawList(tab);
      if (mine !== era || !overview) return;
    }
  } catch (error) {
    if (!said(error)) showMessage(READ_ERROR);
  } finally {
    loading = false;
    if (again) { again = false; refresh(); }
  }
}
byId('trend-settings').addEventListener('click', () => byId('settings-link').click());
setInterval(refresh, 30000);
document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
refresh();
