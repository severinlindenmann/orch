/* Read-only overview. Workspace text is always inserted as text nodes. */
'use strict';
const prefix = document.documentElement.dataset.prefix || '';
const byId = id => document.getElementById(id);
const labels = {skills: 'Skills', connections: 'Connections', keys: 'Keys'};
const kinds = {skill: 'skills', connection: 'connections', key: 'keys'};
let overview, active = 'skills', selected = null, loading = false;

function node(tag, text, className) {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  if (className) element.className = className;
  return element;
}

function renderRows() {
  const rows = byId('rows');
  rows.replaceChildren();
  for (const row of overview.tabs[active].rows) {
    const item = node('li', undefined, 'row');
    item.tabIndex = -1;
    if (row.name === selected) item.classList.add('selected');
    const tile = node('span', {skills: '◇', connections: '↗', keys: '⚿'}[active], 'tile');
    tile.setAttribute('aria-hidden', 'true');
    const description = node('div');
    description.append(node('div', row.name, 'name'), node('div', row.source, 'source'));
    if (row.detail) description.append(node('div', row.detail, 'detail'));
    const usage = node('div', undefined, 'usage');
    usage.append(node('div', row.uses === null ? '-' : `${row.uses} uses`),
      node('div', row.numbers, 'numbers'));
    if (row.unseen) usage.append(node('div', row.unseen, 'unseen'));
    item.append(tile, description, node('div', row.label, `health ${row.health}`), usage);
    rows.append(item);
  }
  if (!rows.children.length) rows.append(node('li', 'No items recorded here yet.', 'empty'));
  byId('panel').setAttribute('aria-labelledby', `tab-${active}`);
}

function selectTab(tab) {
  active = tab;
  for (const button of byId('tabs').children) {
    const on = button.dataset.tab === tab;
    button.setAttribute('aria-selected', String(on));
    button.tabIndex = on ? 0 : -1;
  }
  renderRows();
}

function renderTabs() {
  byId('tabs').replaceChildren();
  for (const [tab, label] of Object.entries(labels)) {
    const button = node('button', `${label} ${overview.tabs[tab].count}`);
    button.id = `tab-${tab}`;
    button.dataset.tab = tab;
    button.setAttribute('role', 'tab');
    button.setAttribute('aria-controls', 'panel');
    button.addEventListener('click', () => { selected = null; selectTab(tab); });
    button.addEventListener('keydown', event => {
      const tabs = Object.keys(labels);
      let index = tabs.indexOf(tab);
      if (event.key === 'ArrowRight') index = (index + 1) % tabs.length;
      else if (event.key === 'ArrowLeft') index = (index + tabs.length - 1) % tabs.length;
      else if (event.key === 'Home') index = 0;
      else if (event.key === 'End') index = tabs.length - 1;
      else return;
      event.preventDefault();
      selected = null;
      selectTab(tabs[index]);
      byId(`tab-${tabs[index]}`).focus();
    });
    byId('tabs').append(button);
  }
  selectTab(active);
}

function renderNeeds() {
  const needs = byId('needs');
  needs.replaceChildren();
  if (!overview.needs.length) needs.append(node('p', overview.empty_needs));
  for (const card of overview.needs) {
    const article = node('article', undefined, `card ${card.tone}`);
    const button = node('button', card.button);
    button.addEventListener('click', () => {
      selected = card.target;
      selectTab(kinds[card.kind]);
      const row = byId('rows').querySelector('.selected');
      if (row) { row.focus(); row.scrollIntoView({block: 'nearest'}); }
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
  byId('needs').replaceChildren();
  byId('tabs').replaceChildren();
}

async function refresh() {
  if (document.hidden || loading) return;
  loading = true;
  try {
    const response = await fetch(`${prefix}/api/overview`, {signal: AbortSignal.timeout(15000)});
    if (!response.ok) throw new Error('read failed');
    overview = await response.json();
    if (overview.error) { showMessage(overview.error); return; }
    if (overview.first_day) {
      showMessage('Nothing recorded yet. Counts appear after the first agent run.');
    } else {
      renderNeeds();
      renderTabs();
      byId('message').hidden = true;
      byId('overview').hidden = false;
    }
    byId('sharing').textContent = overview.sharing.chip || '';
    byId('sharing').hidden = !overview.sharing.on;
  } catch {
    showMessage('Insights could not read the workspace record.');
  } finally { loading = false; }
}
setInterval(refresh, 30000);
document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
refresh();
