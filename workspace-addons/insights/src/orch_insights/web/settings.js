/* Insights settings view. Workspace text (ticket titles) is always inserted as text nodes. */
'use strict';
(() => {
  const prefix = document.documentElement.dataset.prefix || '';
  const byId = id => document.getElementById(id);
  let view = null, busy = false, pendingTicket = null;

  function node(tag, text, className) {
    const element = document.createElement(tag);
    if (text !== undefined && text !== null) element.textContent = text;
    if (className) element.className = className;
    return element;
  }

  async function startSession() {
    const match = /[#&]launch=([A-Za-z0-9_-]{20,64})/.exec(location.hash || '');
    if (!match) return;
    history.replaceState(null, '', location.pathname + location.search);
    try {
      await fetch(`${prefix}/session`, {method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({token: match[1]})});
    } catch { /* watch-only */ }
  }

  async function act(op, args) {
    const response = await fetch(`${prefix}/api/act`, {method: 'POST', signal: AbortSignal.timeout(70000),
      headers: {'Content-Type': 'application/json'}, body: JSON.stringify({op, args})});
    if (!response.ok) throw new Error((await response.text()) || 'That did not work.');
    return (await response.json()).result || {};
  }

  function say(text) { byId('settings-status').textContent = text || ''; }

  async function change(row, option) {
    if (busy || option.disabled || option.selected) return;
    busy = true;
    say('Saving…');
    try {
      await act('settings.set', {key: row.key, value: option.value});
      await load();
      say(option.needs_person ? 'Saved.' : `Saved. ${view && view.narrow_note ? view.narrow_note : ''}`.trim());
    } catch (error) { say(error.message); } finally { busy = false; }
  }

  function segmented(row) {
    const group = node('div', undefined, 'seg');
    group.setAttribute('role', 'group');
    group.setAttribute('aria-label', row.label);
    for (const option of row.options) {
      const button = node('button', option.label, option.selected ? 'chip active' : 'chip');
      button.setAttribute('aria-pressed', String(option.selected));
      button.disabled = option.disabled;
      button.addEventListener('click', () => change(row, option));
      group.append(button);
    }
    return group;
  }

  function settingRow(row, title) {
    const block = node('div', undefined, 'set-row');
    if (title !== null) block.append(node('h3', title || row.label));
    if (row.locked) block.append(node('p', row.reason, 'locked'));
    else block.append(segmented(row));
    for (const line of [row.note, row.person_note]) if (line) block.append(node('p', line, 'note'));
    return block;
  }

  function recordedCard() {
    const card = node('section', undefined, 'set-card');
    card.append(node('h2', 'What is recorded'), node('p', view.recorded.what), node('h3', 'Where'),
      node('p', view.recorded.where));
    if (view.recorded.since) {
      const since = new Date(view.recorded.since);
      const day = since.toLocaleDateString(undefined, {day: 'numeric', month: 'short', year: 'numeric'});
      card.append(node('h3', 'Recording since'), node('p', day));
    }
    return card;
  }

  function keepCard() {
    const card = node('section', undefined, 'set-card');
    card.append(node('h2', 'Keep full detail for'), settingRow(view.keep, null), settingRow(view.size));
    if (view.usage) card.append(node('p', view.usage, 'note'));
    card.append(node('p', view.narrow_note, 'note'));
    return card;
  }

  function shareCard() {
    const card = node('section', undefined, 'set-card');
    card.append(node('h2', 'Share counts with your admin'), settingRow(view.share_counts, null),
      settingRow(view.share_names));
    return card;
  }

  function ticketItem(entry) {
    const item = node('li', undefined, 'row');
    const button = node('button', 'Delete detail');
    button.disabled = !view.can_act;
    button.addEventListener('click', () => confirmDelete(entry));
    item.append(node('span', entry.title, 'name'), button);
    return item;
  }

  function deleteCard() {
    const card = node('section', undefined, 'set-card');
    card.append(node('h2', 'Delete detail for a ticket'));
    if (view.tickets.error) { card.append(node('p', view.tickets.error, 'note')); return card; }
    if (!view.can_act) card.append(node('p', 'Open Insights from the dashboard on this computer to do this.', 'note'));
    const list = node('ul', undefined, 'rows');
    for (const entry of view.tickets.rows) list.append(ticketItem(entry));
    if (!view.tickets.rows.length) list.append(node('li', 'No tickets.', 'empty'));
    card.append(list);
    return card;
  }

  function confirmDelete(entry) {
    pendingTicket = entry.ticket;
    byId('confirm-title').textContent = entry.title;
    byId('confirm').showModal();
  }

  async function deleteDetail() {
    const ticket = pendingTicket;
    pendingTicket = null;
    byId('confirm').close();
    if (!ticket || busy) return;
    busy = true;
    say('Deleting…');
    try {
      const result = await act('record.delete_detail', {ticket});
      const n = Number(result.deleted) || 0;
      say(`Deleted detail of ${n} ${n === 1 ? 'run' : 'runs'}`);
    } catch (error) { say(error.message); } finally { busy = false; }
  }

  function render() {
    const body = byId('settings-body');
    if (view.error) { body.replaceChildren(node('p', view.error)); return; }
    body.replaceChildren(recordedCard(), keepCard(), shareCard(), deleteCard());
  }

  async function load() {
    try {
      const response = await fetch(`${prefix}/api/settings`, {signal: AbortSignal.timeout(20000)});
      if (!response.ok) throw new Error('read failed');
      view = await response.json();
    } catch {
      view = {error: 'Insights could not read the settings.'};
    }
    render();
  }

  function show(on) {
    byId('settings').hidden = !on;
    byId('main-view').hidden = on;
    byId('settings-link').setAttribute('aria-pressed', String(on));
    byId('settings-link').textContent = on ? 'Back to overview' : 'Settings';
    if (on) { say(''); load(); }
  }

  byId('settings-link').addEventListener('click', () => show(byId('settings').hidden));
  byId('confirm-cancel').addEventListener('click', () => { pendingTicket = null; byId('confirm').close(); });
  byId('confirm-delete').addEventListener('click', deleteDetail);
  startSession();
})();
