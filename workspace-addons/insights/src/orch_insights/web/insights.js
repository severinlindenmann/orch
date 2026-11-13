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
const BADGE = {success: 'done', warning: 'attn', info: 'working', '': ''};
let overview = null, lists = {}, active = 'skills', loading = false;

function node(tag, text, className) {
  const element = document.createElement(tag);
  if (text !== undefined && text !== null) element.textContent = text;
  if (className) element.className = className;
  return element;
}

async function read(path) {
  const response = await fetch(`${prefix}${path}`, {signal: AbortSignal.timeout(15000)});
  if (!response.ok) throw new Error('read failed');
  return response.json();
}

function plural(n, word) { return `${n} ${word}${n === 1 ? '' : 's'}`; }
function list(names) {
  if (names.length <= 2) return names.join(' and ');
  return `${names[0]}, ${names[1]} and ${names.length - 2} more`;
}

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

function showMessage(text) {
  showView('message');
  byId('message').textContent = text;
  overview = null;
}

function fillMetrics() {
  const skills = (lists.skills && lists.skills.rows) || [];
  const used = skills.filter(row => row.uses);
  const first = overview.since && (Date.now() - Date.parse(overview.since)) < 31 * 86400000;
  const cards = [
    ['Runs', String(overview.runs), first ? 'First month of data' : 'In the last 30 days'],
    ['Skills used', String(used.length), used.length ? list(used.map(row => row.name)) : 'None yet'],
    ['Connected services', String(overview.tabs.connections.count),
      overview.tabs.connections.count ? 'Used by your helpers' : 'None connected'],
  ];
  byId('metrics').replaceChildren(...cards.map(([label, value, small]) => {
    const card = node('article', undefined, 'card metric');
    card.append(node('p', label, 'meta'), node('strong', value), node('small', small));
    return card;
  }));
}

function fillTrend() {
  const runs = overview.runs;
  byId('trend').setAttribute('aria-label',
    `Daily run trend unavailable. ${plural(runs, 'run')} recorded; daily totals were not supplied.`);
  byId('trend-text').textContent =
    `${plural(runs, 'run')} ${runs === 1 ? 'is' : 'are'} recorded. There isn’t enough dated activity to draw a reliable trend.`;
}

function fillBars() {
  const rows = (((lists.skills && lists.skills.rows) || []).filter(row => row.runs_of));
  const bars = byId('bars');
  bars.replaceChildren();
  if (!rows.length) { byId('skill-text').textContent = 'No skill use is recorded yet.'; return; }
  const top = rows[0];
  byId('skill-text').textContent = `${top.name} was used in ${top.runs_used} of ${top.runs_of} runs in the last 30 days.`;
  rows.slice(0, 5).forEach((row, index) => {
    const bar = node('div', undefined, index ? 'bar-row secondary' : 'bar-row');
    const head = node('div', undefined, 'row between');
    head.append(node('span', row.name), node('strong', `${row.runs_used} / ${row.runs_of}`));
    const meter = node('div', undefined, 'progress');
    meter.setAttribute('aria-label', `${row.name} used in ${row.runs_used} of ${row.runs_of} runs`);
    const fill = node('span');
    fill.style.setProperty('--value', `${Math.round(100 * row.runs_used / row.runs_of)}%`);
    meter.append(fill);
    bar.append(head, meter);
    bars.append(bar);
  });
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
}

function renderServices() {
  const count = overview.tabs.connections.count;
  byId('services-title').textContent = `Connected services · ${count}`;
  const box = byId('services');
  const answer = lists.connections;
  if (!count) { box.textContent = 'No connected services are recorded.'; return; }
  if (!answer) { box.textContent = `${plural(count, 'connected service')} recorded.`; return; }
  box.replaceChildren(...answer.rows.map(row => {
    const line = node('p');
    line.append(node('strong', row.name), document.createTextNode(` · ${row.state.text} · ${row.allowed}`));
    return line;
  }));
}

function renderNeeds() {
  const needs = byId('needs');
  needs.replaceChildren();
  needs.hidden = !overview.needs.length;
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
  const n = overview.needs.length;
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

async function loadList(tab) {
  try {
    const answer = await read(`/api/list/${tab}`);
    if (answer.error) { showMessage(answer.error); return false; }
    lists[tab] = answer;
    return true;
  } catch {
    showMessage('Insights could not read the workspace record.');
    return false;
  }
}

async function selectTab(tab) {
  active = tab;
  renderTabs();
  renderTable();
  if (!lists[tab]) { await loadList(tab); renderTable(); }
}

async function refresh() {
  if (document.hidden || loading) return;
  loading = true;
  try {
    const answer = await read('/api/overview');
    if (answer.error) { showMessage(answer.error); return; }
    overview = answer;
    if (overview.first_day) {
      showView('empty');
      byId('empty').querySelector('h2').textContent = 'Nothing recorded yet';
      byId('empty').querySelector('p').textContent = 'Counts appear after the first helper run.';
      return;
    }
    if (!await loadList('skills')) return;
    showView('overview');
    renderAll();
    for (const tab of ['connections', 'keys']) {
      if (overview.tabs[tab].count && await loadList(tab)) { renderServices(); if (tab === active) renderTable(); }
    }
  } catch {
    showMessage('Insights could not read the workspace record.');
  } finally { loading = false; }
}
byId('trend-settings').addEventListener('click', () => byId('settings-link').click());
setInterval(refresh, 30000);
document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
refresh();
