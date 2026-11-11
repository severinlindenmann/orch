/* Read-only overview and lists. Workspace text is always inserted as text nodes. */
'use strict';
const prefix = document.documentElement.dataset.prefix || '';
const byId = id => document.getElementById(id);
const labels = {skills: 'Skills', connections: 'Connections', keys: 'Keys'};
const kinds = {skill: 'skills', connection: 'connections', key: 'keys'};
const tiles = {skills: '◇', connections: '↗', keys: '⚿'};
let overview, list = null, active = 'skills', selected = null, filter = 'all', loading = false;

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

function usageCell(row) {
  const usage = node('div', undefined, 'usage');
  if (active === 'connections') {
    usage.append(node('span', row.allowed));
    return usage;
  }
  if (row.uses === null) usage.append(node('b', '-'));
  else usage.append(node('b', String(row.uses)), document.createTextNode(' this month'));
  return usage;
}

function rowFacts(row) {
  const facts = [row.last_used, row.health === 'unknown' ? '' : row.numbers, row.unseen];
  if (active === 'keys') facts.unshift(row.type);
  return facts.filter(Boolean).join(' · ');
}

function renderRow(row) {
  const item = node('li', undefined, 'row');
  item.tabIndex = 0;
  item.setAttribute('role', 'button');
  item.setAttribute('aria-haspopup', 'dialog');
  item.dataset.key = row.key;
  if (row.key === selected) item.classList.add('selected');
  const tile = node('span', tiles[active], 'tile');
  tile.setAttribute('aria-hidden', 'true');
  const description = node('div', undefined, 'what');
  description.append(node('div', row.name, 'name'), node('div', rowFacts(row), 'numbers'));
  for (const line of [row.versions, row.also]) if (line) description.append(node('div', line, 'numbers'));
  const state = node('div', undefined, 'state');
  state.append(node('span', row.state.text, `chip ${row.state.tone}`.trim()));
  item.append(tile, description, node('div', row.source, 'source'), usageCell(row), state);
  item.addEventListener('click', () => openPanel(row.key));
  item.addEventListener('keydown', event => {
    if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); openPanel(row.key); }
  });
  return item;
}

function renderFilters() {
  const filters = byId('filters');
  filters.replaceChildren();
  for (const choice of list.filters) {
    const button = node('button', `${choice.label} ${choice.count}`, 'chip');
    button.setAttribute('aria-pressed', String(choice.id === filter));
    if (choice.id === filter) button.classList.add('active');
    button.addEventListener('click', () => { filter = choice.id; renderList(); });
    filters.append(button);
  }
}

function renderList() {
  const rows = byId('rows');
  rows.replaceChildren();
  byId('panel').setAttribute('aria-labelledby', `tab-${active}`);
  if (!list) { rows.append(node('li', 'Reading the workspace record…', 'empty')); return; }
  renderFilters();
  const head = node('li', undefined, 'row head');
  head.setAttribute('aria-hidden', 'true');
  head.append(node('span'), ...list.columns.map(column => node('span', column)));
  rows.append(head);
  for (const row of list.rows) {
    if (filter === 'all' || row.filter === filter) rows.append(renderRow(row));
  }
  if (rows.children.length === 1) rows.append(node('li', 'No items here.', 'empty'));
  renderPanel();
}

function fold(details) {
  const block = node('details', undefined, 'fold');
  block.append(node('summary', 'Details'));
  const terms = node('dl');
  for (const entry of details) terms.append(node('dt', entry.term), node('dd', entry.value));
  block.append(terms);
  return block;
}

function renderPanel() {
  const aside = byId('detail');
  const row = list && list.rows.find(entry => entry.key === selected);
  if (!row) { aside.hidden = true; aside.replaceChildren(); return; }
  const panel = row.panel;
  const top = node('div', undefined, 'panel-top');
  const close = node('button', '×', 'close');
  close.setAttribute('aria-label', 'Close');
  close.addEventListener('click', closePanel);
  top.append(node('h2', row.name), close);
  const facts = node('dl', undefined, 'facts');
  const pairs = [['From', row.source], ['Last used', row.last_used], ['First seen', panel.first_seen],
    ['Last seen', panel.last_seen]];
  if (active === 'keys') pairs.splice(1, 0, ['Type', row.type]);
  if (active === 'connections') pairs.splice(1, 0, ['Allowed actions', row.allowed]);
  for (const [term, value] of pairs) facts.append(node('dt', term), node('dd', value));
  const numbers = node('ul', undefined, 'figures');
  for (const line of panel.numbers) numbers.append(node('li', line));
  aside.replaceChildren(top, node('div', row.state.text, `health ${row.health}`));
  for (const line of [row.versions, row.also]) if (line) aside.append(node('p', line));
  aside.append(node('h3', 'Numbers'), numbers, facts);
  if (panel.tickets) {
    aside.append(node('h3', 'Tickets'), node('p', panel.tickets), node('p', panel.note, 'note'));
  }
  aside.append(fold(panel.details));
  aside.hidden = false;
}

function openPanel(key) {
  selected = key;
  renderList();
  byId('detail').querySelector('.close').focus();
}

function closePanel() {
  const key = selected;
  selected = null;
  renderList();
  const back = [...byId('rows').querySelectorAll('.row:not(.head)')].find(row => row.dataset.key === key);
  if (back) back.focus();
}

async function loadList(tab, target) {
  try {
    const answer = await read(`/api/list/${tab}`);
    if (tab !== active) return;
    if (answer.error) { showMessage(answer.error); return; }
    list = answer;
    if (target) {
      const row = list.rows.find(entry => entry.name === target);
      selected = row ? row.key : null;
    }
    renderList();
  } catch {
    showMessage('Insights could not read the workspace record.');
  }
}

function selectTab(tab, target) {
  if (tab !== active) { list = null; filter = 'all'; }
  active = tab;
  selected = null;
  for (const button of byId('tabs').children) {
    const on = button.dataset.tab === tab;
    button.setAttribute('aria-selected', String(on));
    button.tabIndex = on ? 0 : -1;
  }
  renderList();
  return loadList(tab, target);
}

function renderTabs() {
  byId('tabs').replaceChildren();
  for (const [tab, label] of Object.entries(labels)) {
    const button = node('button', `${label} ${overview.tabs[tab].count}`);
    button.id = `tab-${tab}`;
    button.dataset.tab = tab;
    button.setAttribute('role', 'tab');
    button.setAttribute('aria-controls', 'panel');
    button.setAttribute('aria-selected', String(tab === active));
    button.tabIndex = tab === active ? 0 : -1;
    button.addEventListener('click', () => selectTab(tab));
    button.addEventListener('keydown', event => {
      const tabs = Object.keys(labels);
      let index = tabs.indexOf(tab);
      if (event.key === 'ArrowRight') index = (index + 1) % tabs.length;
      else if (event.key === 'ArrowLeft') index = (index + tabs.length - 1) % tabs.length;
      else if (event.key === 'Home') index = 0;
      else if (event.key === 'End') index = tabs.length - 1;
      else return;
      event.preventDefault();
      selectTab(tabs[index]);
      byId(`tab-${tabs[index]}`).focus();
    });
    byId('tabs').append(button);
  }
}

function renderNeeds() {
  const needs = byId('needs');
  needs.replaceChildren();
  if (!overview.needs.length) needs.append(node('p', overview.empty_needs));
  for (const card of overview.needs) {
    const article = node('article', undefined, `card ${card.tone}`);
    const button = node('button', card.button, card.tone === 'warn' ? 'primary' : '');
    button.addEventListener('click', async () => {
      await selectTab(kinds[card.kind], card.target);
      const close = byId('detail').querySelector('.close');
      if (close) close.focus();
    });
    article.append(node('small', card.kind), node('h2', card.title), node('p', card.text), button);
    needs.append(article);
  }
}

function showMessage(text) {
  byId('overview').hidden = true;
  byId('sharing').hidden = true;
  byId('message').textContent = text;
  byId('message').hidden = false;
  byId('rows').replaceChildren();
  byId('filters').replaceChildren();
  byId('needs').replaceChildren();
  byId('tabs').replaceChildren();
  byId('detail').replaceChildren();
  byId('detail').hidden = true;
  list = null;
}

async function refresh() {
  if (document.hidden || loading) return;
  loading = true;
  try {
    overview = await read('/api/overview');
    if (overview.error) { showMessage(overview.error); return; }
    if (overview.first_day) {
      showMessage('Nothing recorded yet. Counts appear after the first agent run.');
    } else {
      renderNeeds();
      renderTabs();
      byId('message').hidden = true;
      byId('overview').hidden = false;
      await loadList(active);
    }
    byId('sharing').textContent = overview.sharing.chip || '';
    byId('sharing').hidden = !overview.sharing.on;
  } catch {
    showMessage('Insights could not read the workspace record.');
  } finally { loading = false; }
}
document.addEventListener('keydown', event => { if (event.key === 'Escape' && selected) closePanel(); });
setInterval(refresh, 30000);
document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
refresh();
