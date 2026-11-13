/* Insights settings view. Workspace text (ticket titles) is always inserted as text nodes. */
'use strict';
(() => {
  const prefix = document.documentElement.dataset.prefix || '';
  const byId = id => document.getElementById(id);
  const UNLINKED = 'This page could not be linked to your session. Open Insights again from the dashboard on this computer.';
  // The page secret of this server (H2): memory only, never storage, cookie or URL.
  let view = null, busy = false, pendingTicket = null, pageSecret = '';

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
      const response = await fetch(`${prefix}/session`, {method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({token: match[1]})});
      if (response.status !== 200) throw new Error('not linked');
      const secret = (await response.json()).secret;
      if (typeof secret !== 'string' || !secret) throw new Error('not linked');
      pageSecret = secret;
    } catch {
      const note = byId('session-note');
      note.textContent = UNLINKED;
      note.hidden = false;
    }
  }

  function headers(extra) {
    return pageSecret ? {...extra, 'X-Orch-Page': pageSecret} : {...extra};
  }

  async function act(op, args) {
    const response = await fetch(`${prefix}/api/act`, {method: 'POST', signal: AbortSignal.timeout(70000),
      headers: headers({'Content-Type': 'application/json'}), body: JSON.stringify({op, args})});
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
      say('Saved.');
      if (window.UI && UI.toast) UI.toast('Saved');
    } catch (error) {
      await load();  // after any refusal or timeout, show what the record says now
      say(error.message);
    } finally { busy = false; }
  }

  function selectControl(row) {
    const label = node('label');
    label.append(node('span', row.label, 'sr-only'));
    const select = node('select');
    select.id = row.key.replace(/\./g, '-');
    for (const option of row.options) {
      const entry = node('option', option.label);
      entry.value = option.value;
      entry.selected = option.selected;
      entry.disabled = option.disabled && !option.selected;
      select.append(entry);
    }
    select.addEventListener('change', () => {
      const option = row.options.find(entry => entry.value === select.value);
      if (option) change(row, option);
    });
    label.append(select);
    return label;
  }

  function switchControl(row) {
    const on = row.options.find(option => option.value === 'on');
    const off = row.options.find(option => option.value === 'off');
    const box = node('input', undefined, 'switch');
    box.type = 'checkbox';
    box.setAttribute('role', 'switch');
    box.setAttribute('aria-label', row.label);
    box.checked = row.current === 'on';
    box.disabled = !on || !off || (box.checked ? off.disabled : on.disabled);
    box.addEventListener('change', () => change(row, box.checked ? on : off));
    return box;
  }

  function settingRow(row, title, help, kind) {
    const block = node('div', undefined, 'settings-row');
    const text = node('div');
    text.append(node('h3', title || row.label));
    if (help) text.append(node('p', help, 'muted'));
    if (row.locked) text.append(node('p', row.reason, 'locked'));
    for (const line of [row.note, row.person_note]) if (line) text.append(node('p', line, 'note'));
    block.append(text);
    if (!row.locked) block.append(kind === 'switch' ? switchControl(row) : selectControl(row));
    return block;
  }

  function card(title) {
    const section = node('section', undefined, 'card');
    if (title) { const head = node('div', undefined, 'card-h'); head.append(node('h2', title)); section.append(head); }
    return section;
  }

  function sharingCard() {
    const section = card('Activity & sharing');
    section.append(
      settingRow(view.keep, 'Keep full details for', 'Older details are removed automatically. Usage counts stay available.'),
      settingRow(view.share_counts, 'Share counts with your organisation',
        'Share how often skills and connected services are used, without the full activity details.', 'switch'),
      settingRow(view.share_names, null, null, 'switch'));
    return section;
  }

  function storageCard() {
    const section = node('section', undefined, 'card pad');
    section.append(node('p', 'Storage limits', 'meta'));
    const body = node('div', undefined, 'stack space-top');
    const field = node('div', undefined, 'field');
    field.append(node('span', 'Largest size'), selectControl(view.size));
    body.append(field);
    for (const line of [view.size.note, view.size.person_note, view.usage, view.narrow_note]) {
      if (line) body.append(node('p', line, 'meta'));
    }
    section.append(body);
    return section;
  }

  function contextCard() {
    const aside = node('aside', undefined, 'card context-card');
    aside.append(node('h2', 'Your activity stays useful'),
      node('p', 'Counts help you see what your helpers use. Full details let you look more closely at individual runs.', 'muted'),
      node('hr'), node('h3', 'What is recorded'), node('p', view.recorded.what, 'muted'),
      node('p', view.recorded.where, 'muted'));
    if (view.recorded.since) {
      const since = new Date(view.recorded.since);
      const day = since.toLocaleDateString(undefined, {day: 'numeric', month: 'short', year: 'numeric'});
      aside.append(node('p', `Recording since ${day}`, 'meta'));
    }
    const back = node('button', 'Back to Insights →', 'btn ghost sm');
    back.type = 'button';
    back.addEventListener('click', () => show(false));
    aside.append(back);
    return aside;
  }

  function ticketItem(entry) {
    const item = node('div', undefined, 'ticket-line');
    const button = node('button', 'Delete detail', 'btn outline sm');
    button.type = 'button';
    button.disabled = !view.can_act;
    button.addEventListener('click', () => confirmDelete(entry));
    item.append(node('span', entry.title, 'name'), button);
    return item;
  }

  function deleteCard() {
    const section = card('Delete detail for a ticket');
    if (view.tickets.error) { section.append(node('p', view.tickets.error, 'note set-block')); return section; }
    if (!view.can_act) section.append(node('p', 'Open Insights from the dashboard on this computer to do this.', 'note set-block'));
    for (const entry of view.tickets.rows) section.append(ticketItem(entry));
    if (!view.tickets.rows.length) section.append(node('p', 'No tickets.', 'muted set-block'));
    return section;
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
      const left = (Number(result.kept) || 0) + (Number(result.unreadable) || 0) + (Number(result.skipped) || 0);
      say(`Deleted detail of ${n} ${n === 1 ? 'run' : 'runs'}.` + (left ? ' Some files could not be deleted and were left.' : ''));
    } catch (error) {
      await load();
      say(error.message);
    } finally { busy = false; }
  }

  function render() {
    const body = byId('settings-body');
    if (view.error) { body.replaceChildren(node('p', view.error)); return; }
    const grid = node('div', undefined, 'settings-grid');
    const left = node('div', undefined, 'stack');
    left.append(sharingCard(), storageCard(), deleteCard());
    grid.append(left, contextCard());
    body.replaceChildren(grid);
    if (window.UI && UI.select) UI.select.sync();
  }

  async function load() {
    try {
      const response = await fetch(`${prefix}/api/settings`, {signal: AbortSignal.timeout(20000), headers: headers({})});
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
    byId('range').hidden = on;
    byId('settings-link').hidden = on;
    byId('health').hidden = on || byId('overview').hidden;
    byId('page-title').textContent = on ? 'Insights settings' : 'Insights';
    byId('page-sub').textContent = on ? 'Choose what to keep and share.' : 'What your helpers used, at a glance.';
    byId('settings-link').setAttribute('aria-pressed', String(on));
    if (on) { say(''); load(); }
  }

  byId('settings-link').addEventListener('click', () => show(true));
  window.addEventListener('keydown', event => { if (event.key === 'Escape' && !byId('settings').hidden && !byId('confirm').open) show(false); });
  byId('confirm-cancel').addEventListener('click', () => { pendingTicket = null; byId('confirm').close(); });
  byId('confirm-delete').addEventListener('click', deleteDetail);
  startSession();
})();
