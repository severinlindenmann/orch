/* Insights check-up card: last check-up, Run a check-up, the Monday switch and the suggestions.
   Agent text (titles, plain, files) is data: always inserted as text nodes. A click goes through the page's one
   act() (settings.js, window.insightsAct); the core asks for the person's proof, never this page. */
'use strict';
(() => {
  const prefix = document.documentElement.dataset.prefix || '';
  const byId = id => document.getElementById(id);
  const STATE = {
    proposed: ['Not tested', ''], tested: ['Tested', 'working'], accepted: ['Accepted', 'done'],
    rolled_back: ['Rolled back', 'paused'], stale: ['Out of date', 'attn'], sent_to_admin: ['Sent to your admin', ''],
  };
  let view = null, busy = false, timer = 0;
  const note = byId('checkup-note');  // lives inside #checkup; render() keeps it after the card

  function node(tag, text, className) {
    const element = document.createElement(tag);
    if (text !== undefined && text !== null) element.textContent = text;
    if (className) element.className = className;
    return element;
  }

  function when(iso) {
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return '';
    return date.toLocaleString(undefined, {weekday: 'short', hour: '2-digit', minute: '2-digit'});
  }
  const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;

  function say(text) { note.textContent = text || ''; note.hidden = !text; }
  function fail(error) {
    say(error.message);
    if (window.UI && UI.toast) UI.toast(error.message, undefined, 'error');
  }

  async function read(path) {
    const response = await fetch(`${prefix}${path}`, {signal: AbortSignal.timeout(20000)});
    if (!response.ok) throw new Error('That could not be read.');
    return response.json();
  }

  // One click: `run` does the act() call; the card is read again afterwards whatever happened.
  async function click(label, run, done) {
    if (busy) return;
    busy = true;
    say(label);
    render();
    try {
      const result = await run();
      say('');
      if (done) done(result);
    } catch (error) { fail(error); }
    busy = false;
    await load();
  }

  const act = (op, args) => window.insightsAct(op, args);
  const ticketHref = ticket => (prefix ? `/#ticket/${encodeURIComponent(ticket)}` : null);

  function ticketLink(ticket) {
    const href = ticket && ticketHref(ticket);
    if (!href) return null;
    const link = node('a', 'See the ticket', 'btn ghost sm');
    link.href = href;
    link.target = '_top';
    return link;
  }

  function lastLine() {
    const last = view.last;
    if (!last) return 'No check-up yet';
    const bits = [];
    if (last.runs !== null) bits.push(plural(last.runs, 'run'));
    if (last.tickets !== null) bits.push(plural(last.tickets, 'ticket'));
    if (last.found !== null) bits.push(plural(last.found, 'suggestion'));
    return [`Last check-up: ${when(last.at)}`, ...bits].join(' · ');
  }

  function weeklySwitch() {
    const row = node('label', undefined, 'row checkup-weekly');
    const box = node('input', undefined, 'switch');
    box.type = 'checkbox';
    box.setAttribute('role', 'switch');
    box.checked = view.weekly === 'on';
    box.disabled = view.weekly === 'unavailable' || busy;
    box.addEventListener('change', () => click('Saving…', () => act('checkup.weekly', {value: box.checked ? 'on' : 'off'})));
    row.append(box, node('span', 'Every Monday 07:00'));
    if (view.weekly === 'unavailable') row.append(node('span', 'Needs the Automation add-on', 'meta'));
    return row;
  }

  function head() {
    const section = node('div', undefined, 'card-h checkup-head');
    const title = node('div', undefined, 'grow');
    title.append(node('h2', 'Check-up'), node('p', lastLine(), 'meta'));
    const run = node('button', view.running ? 'Checking…' : 'Run a check-up', 'btn primary');
    run.type = 'button';
    run.disabled = busy || view.running;
    run.addEventListener('click', () => click('Starting…', () => act('checkup.start', {}), result => {
      if (result.result === 'busy') say('A check-up is already running.');
    }));
    section.append(title, weeklySwitch());
    const link = view.running ? ticketLink(view.last && view.last.ticket) : null;
    if (link) section.append(link);
    section.append(run);
    return section;
  }

  function chips(proposal) {
    const box = node('span', undefined, 'row');
    if (proposal.likely) box.append(node('span', 'likely', 'chip outline'));
    if (proposal.status === 'proposed' && !canTest(proposal)) return box;  // nothing to test: no state to show
    const tests = proposal.tests;
    if (proposal.status === 'proposed' && (tests.state === 'failed' || tests.state === 'error')) {
      box.append(node('span', 'Did not pass', 'badge failed'));
    } else {
      const [text, kind] = STATE[proposal.status] || STATE.proposed;
      box.append(node('span', text, `badge ${kind}`.trim()));
    }
    return box;
  }

  function canTest(proposal) {
    const ask = proposal.target.source === 'admin' || proposal.kind === 'key.ask_admin';
    return !ask && proposal.kind !== 'note' && proposal.kind !== 'connection.fix';
  }

  function mainButton(proposal) {
    if (!canTest(proposal)) return null;
    const make = (text, cls, fn) => {
      const button = node('button', text, `btn ${cls}`);
      button.type = 'button';
      button.disabled = busy;
      button.addEventListener('click', fn);
      return button;
    };
    const id = proposal.id;
    if (proposal.status === 'proposed') {
      const again = proposal.tests.state === 'failed' || proposal.tests.state === 'error';
      return make(again ? 'Test again' : 'Test it', 'outline', () =>
        click('Testing in a copy…', () => act('checkup.test', {id}), () => UI.toast && UI.toast('Tested')));
    }
    if (proposal.status === 'tested') return make('Accept', 'primary', () => openAccept(proposal));
    if (proposal.status === 'accepted') {
      return make('Roll back', 'outline', () =>
        click('Rolling back…', () => act('checkup.rollback', {id}), () => UI.toast && UI.toast('Rolled back')));
    }
    return null;
  }

  function dismissButton(proposal) {
    if (proposal.status !== 'proposed' && proposal.status !== 'tested') return null;
    const button = node('button', 'Dismiss', 'btn ghost sm');
    button.type = 'button';
    button.disabled = busy;
    button.addEventListener('click', () => click('Dismissing…', () => act('checkup.reject', {id: proposal.id})));
    return button;
  }

  function suggestion(proposal) {
    const row = node('div', undefined, 'card-row checkup-row');
    row.dataset.state = proposal.status;
    const text = node('div', undefined, 'grow');
    text.append(node('h3', proposal.title));
    if (proposal.target.source === 'admin' || proposal.kind === 'key.ask_admin') {
      text.append(node('p', 'Ask your admin', 'meta'));
    } else if (proposal.status === 'stale') {
      text.append(node('p', 'The skill changed since this was suggested. Run a new check-up.', 'meta'));
    }
    row.append(text, chips(proposal));
    const dismiss = dismissButton(proposal), main = mainButton(proposal);
    if (dismiss) row.append(dismiss);
    if (main) row.append(main);
    return row;
  }

  function diffBlock(file) {
    const box = node('div', undefined, 'stack');
    box.append(node('p', file.path, 'meta'));
    if (file.before_text !== null) box.append(node('pre', file.before_text, 'checkup-code before'));
    box.append(node('pre', file.after === null ? '(file removed)' : file.after, 'checkup-code after'));
    return box;
  }

  async function openAccept(proposal) {
    if (busy) return;
    let shown;
    try { shown = await read(`/api/checkup/${encodeURIComponent(proposal.id)}`); } catch (error) { return fail(error); }
    const content = node('div', undefined, 'stack checkup-sheet');
    content.append(node('p', shown.plain));
    if (shown.diff.length) {
      const fold = node('details', undefined, 'checkup-change');
      fold.append(node('summary', 'Show the change'));
      for (const file of shown.diff) fold.append(diffBlock(file));
      content.append(fold);
    }
    const buttons = node('div', undefined, 'row checkup-buttons');
    const cancel = node('button', 'Cancel', 'btn ghost');
    const accept = node('button', 'Accept', 'btn primary');
    cancel.type = accept.type = 'button';
    buttons.append(cancel, accept);
    content.append(buttons);
    const sheet = UI.sheet(proposal.title, content);
    cancel.addEventListener('click', () => sheet.close());
    accept.addEventListener('click', () => {
      sheet.close();
      click('Accepting…', () => act('checkup.accept', {id: proposal.id}), () => UI.toast && UI.toast('Accepted. You can roll it back.'));
    });
  }

  function render() {
    const host = byId('checkup');
    if (!view || !view.available) { host.hidden = true; return; }
    host.hidden = false;
    const card = node('div', undefined, 'card');
    card.append(head());
    if (view.proposals.length) {
      for (const proposal of view.proposals) card.append(suggestion(proposal));
    } else {
      card.append(node('p', view.last ? 'Nothing to suggest right now.' : 'Run a check-up to look for things to improve.',
        'muted pad'));
    }
    host.replaceChildren(card, note);
  }

  async function load() {
    clearTimeout(timer);
    try { view = await read('/api/checkup'); } catch { view = {available: false}; }
    render();
    if (view.available && view.running) timer = setTimeout(load, 5000);
  }

  load();
})();
