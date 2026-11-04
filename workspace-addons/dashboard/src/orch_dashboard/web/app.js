'use strict';
(() => {
  document.title = 'orch · Dashboard';
  const snapshot = typeof window.ORCH_SNAPSHOT !== 'undefined';
  const content = document.getElementById('content');
  const statuses = ['active', 'waiting', 'open', 'done', 'dropped'];
  const array = value => Array.isArray(value) ? value : [];
  const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const label = value => { const text = String(value ?? ''); return text.charAt(0).toUpperCase() + text.slice(1); };
  const plural = (count, word) => `${count} ${word}${count === 1 ? '' : 's'}`;
  const parse = value => { const d = new Date(value); return value == null || value === '' || Number.isNaN(d.getTime()) ? null : d; };
  const fmt = (d, opts) => d.toLocaleString('en-GB', opts);
  const date = value => { const d = parse(value); return d ? fmt(d, {day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit'}) : '—'; };
  const day = value => { const d = parse(value); return d ? fmt(d, {weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit'}) : ''; };
  function ago(value) {
    const d = parse(value);
    if (!d) return '';
    const min = Math.round((Date.now() - d.getTime()) / 60000);
    if (min < 1) return 'just now';
    if (min < 60) return `${min} min ago`;
    if (min < 1440) return `${Math.round(min / 60)} h ago`;
    return date(value);
  }
  const ticketHref = id => '#ticket/' + encodeURIComponent(String(id));
  const openQuestions = ticket => array(ticket.questions).filter(q => q.answer == null);
  const doneCount = ticket => array(ticket.checklist).filter(c => c.done).length;
  // Never show internal ids: drop "message m_..." phrases and any ws_/t_/q_ style token.
  const noIds = text => String(text ?? '').replace(/,?\s*message\s+m_\w+/gi, '').replace(/\b(?:ws|ph|m|t|q|wh|b|f)_[A-Za-z0-9]{4,}\b/g, '').replace(/\s+/g, ' ').trim();
  const base = path => String(path).replace(/[?#].*$/, '').split(/[\\/]/).filter(Boolean).pop() || String(path);
  const dayWord = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
  function cronText(cron) {
    const m = /^(\d{1,2}) (\d{1,2}) \* \* (\*|\d)$/.exec(String(cron || '').trim());
    if (!m) return '';
    const at = `${m[2].padStart(2, '0')}:${m[1].padStart(2, '0')}`;
    return m[3] === '*' ? `Every day, ${at}` : `Every ${dayWord[Number(m[3]) % 7]}, ${at}`;
  }
  const names = () => state.names || {};
  function waitingText(ticket) {
    const w = ticket.waiting_on;
    if (!w) return ticket.status === 'waiting' && ticket.wake_at ? `a set time (${day(ticket.wake_at)})` : '';
    if (w.kind === 'question') {
      const qs = openQuestions(ticket);
      const q = qs.find(x => x.id === w.ref) || (qs.length === 1 ? qs[0] : null);
      if (qs.length > 1) return `your answers (${qs.length})`;
      return q ? `your answer to “${q.text}”` : 'your answer';
    }
    if (w.kind === 'workspace') return `a reply from ${names()[w.ref] || 'another workspace'}`;
    if (w.kind === 'webhook') return 'an outside event';
    return noIds(w.ref) || 'something outside the workspace';
  }
  const waitingLine = ticket => { const t = ticket.status === 'waiting' ? waitingText(ticket) : ''; return t ? `Waiting on: ${t}` : ''; };
  function evidenceLabel(e) {
    const ref = String(e.ref ?? ''), text = String(e.text ?? '');
    if (e.type === 'pr') { const n = /\/pull\/(\d+)|#(\d+)/.exec(ref); return n ? `PR #${n[1] || n[2]}` : 'Pull request'; }
    if (e.type === 'commit') return `commit ${ref.slice(0, 7)}`;
    if (e.type === 'file') return base(ref);
    if (e.type === 'url') { try { return new URL(ref).hostname; } catch (_) { return 'Link'; } }
    if (e.type === 'command') {
      const tool = ref.split(/\s+/).find(w => w && !['uv', 'run', 'npx', 'python', 'python3', '-m', 'sudo'].includes(w)) || 'Command';
      return text ? `${base(tool)}: ${text}` : `Ran ${base(tool)}`;
    }
    return noIds(text || ref) || 'Note';
  }
  let state;
  let renderedRoute = '';
  const heading = (title, subtitle) => `<div class="heading"><div><h1>${esc(title)}</h1>${subtitle ? `<p class="intro">${subtitle}</p>` : ''}</div></div>`;
  const pill = status => `<span class="pill ${status === 'waiting' ? 'amber' : status === 'active' ? 'teal' : ''}">${esc(label(status))}</span>`;
  const disclosure = (key, title, body) => `<details data-key="${esc(key)}"><summary>${esc(title)}</summary>${body}</details>`;
  function link(item) {
    const url = String(item.url ?? '');
    let safe = false, host = '';
    try { const u = new URL(url); safe = ['http:', 'https:'].includes(u.protocol); host = u.hostname; } catch (_) { /* shown as text */ }
    const title = item.title || (safe ? host : base(url)) || 'Link';
    return safe ? `<a class="chip" href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(title)} ↗</a>` : `<span class="chip">${esc(title)}</span>`;
  }
  function row(ticket) {
    const count = openQuestions(ticket).length, total = array(ticket.checklist).length;
    const wait = waitingLine(ticket);
    const meta = [wait ? `<span class="attention">${esc(wait)}</span>` : (count ? `<span class="attention">${esc(plural(count, 'question'))} waiting for you</span>` : ''),
      total ? `<span>${doneCount(ticket)} of ${plural(total, 'step')}</span>` : ''].filter(Boolean).join('');
    return `<a class="ticket" href="${esc(ticketHref(ticket.id))}"><div><div class="ticket-title">${esc(ticket.title)}</div>${meta ? `<div class="ticket-sub">${meta}</div>` : ''}</div><span class="chevron" aria-hidden="true">›</span></a>`;
  }
  function list() {
    const tickets = array(state.tickets);
    if (!tickets.length) return heading('Tickets', '') + '<section class="panel empty"><h2>Your first ticket starts here.</h2><p>Ask your agent: “Prepare my weekly summary.” Your ticket will appear here.</p></section>';
    const count = tickets.reduce((sum, ticket) => sum + openQuestions(ticket).length, 0);
    const first = tickets.find(ticket => openQuestions(ticket).length);
    const notice = !count ? '' : snapshot
      ? `<div class="notice"><strong>${esc(plural(count, 'unanswered question'))}</strong></div>`
      : `<div class="notice"><strong>${esc(plural(count, 'question'))} ${count === 1 ? 'needs' : 'need'} your answer</strong><a href="${esc(state.inbox != null ? '#inbox' : ticketHref(first.id))}">View ${count === 1 ? 'question' : 'questions'} →</a></div>`;
    return heading('Tickets', '') + notice + statuses.map(status => {
      const group = tickets.filter(ticket => ticket.status === status);
      if (!group.length) return '';
      const body = `<div class="panel">${group.map(row).join('')}</div>`;
      return status === 'dropped' ? `<details class="group" data-key="dropped"><summary>Dropped · ${group.length}</summary>${body}</details>` : `<section class="group"><h2 class="group-title"><span class="status-dot ${status}"></span>${label(status)} <span class="number">${group.length}</span></h2>${body}</section>`;
    }).join('');
  }
  function questionCard(ticket) {
    const qs = array(ticket.questions);
    if (!qs.length) return '';
    const open = qs.filter(q => q.answer == null);
    const body = qs.map(q => `<div class="question-item"><h3>${esc(q.text)}</h3>${q.answer == null ? (array(q.options).length ? `<ul class="options">${q.options.map(o => `<li>${esc(o)}${o === q.recommended ? ' <span class="recommended-label">(recommended)</span>' : ''}</li>`).join('')}</ul>` : '') : `<p class="question-text">Answer: ${esc(q.answer)}</p>${q.answered_by ? `<p class="hint">${esc(String(q.answered_by).replace(/^(agent|human):/, ''))}${q.via ? ` · via ${esc(q.via)}` : ''}</p>` : ''}`}</div>`).join('');
    const title = open.length ? `${plural(open.length, 'question')} waiting for you` : `${plural(qs.length, 'question')} answered`;
    return `<section class="panel question">${disclosure('questions', title, body + (open.length && !snapshot ? '<p class="hint">Answer in your agent or on your phone.</p>' : ''))}</section>`;
  }
  function detail(ticket) {
    const checks = array(ticket.checklist).map((item, index) => {
      const evidence = array(item.evidence);
      return `<div class="check"><span class="${item.done ? 'checkmark' : 'unchecked'}" aria-label="${item.done ? 'Done' : 'Not done'}">${item.done ? '✓' : '○'}</span><div><span class="check-text">${esc(item.text)}</span>${item.done ? (evidence.length ? `<div class="chips">${evidence.map(e => `<span class="chip" title="">${esc(evidenceLabel(e))}</span>`).join('')}</div>` : '<div class="missing">No proof yet</div>') : ''}</div></div>`;
    }).join('');
    const history = array(ticket.history).slice().sort((a, b) => (Date.parse(b.at) || 0) - (Date.parse(a.at) || 0));
    const wait = waitingLine(ticket);
    const cron = cronText(ticket.ext?.scheduler?.cron);
    const more = `<dl><dt>Type</dt><dd>${esc(label(ticket.type))}</dd><dt>Created</dt><dd>${esc(date(ticket.created_at))}</dd></dl>`;
    const sub = `${pill(ticket.status)} <span class="updated">Updated ${esc(ago(ticket.updated_at))}</span>`;
    return '<a class="back" href="#tickets">← All tickets</a>' + `<div class="heading"><div><h1>${esc(ticket.title)}</h1><div class="statusline">${sub}</div>${wait ? `<p class="waiting-line">${esc(wait)}</p>` : ''}</div></div>`
      + questionCard(ticket)
      + `<div class="detail-grid"><div>${checks ? `<section class="panel"><div class="section-title"><h2>Checklist</h2><small>${doneCount(ticket)} of ${array(ticket.checklist).length} done</small></div>${checks}</section>` : ''}${history.length ? `<section class="history">${disclosure('history', `History · ${plural(history.length, 'update')}`, `<ol class="timeline">${history.map(h => `<li>${esc(noIds(h.text))}<small>${esc(date(h.at))} · ${esc(String(h.by).replace(/^(agent|human):/, ''))}</small></li>`).join('')}</ol>`)}</section>` : ''}</div>`
      + `<section class="panel context">${ticket.wake_at ? `<h2>Resumes</h2><p>${esc(day(ticket.wake_at))}</p>` : ''}${cron ? `<h2>Repeats</h2><p>${esc(cron)}</p>` : ''}${array(ticket.links).length ? `<h2>Links</h2><div class="chips">${ticket.links.map(link).join('')}</div>` : ''}${disclosure('more', 'More details', more)}</section></div>`;
  }
  function scheduler() {
    const rows = array(state.scheduler);
    if (!rows.length) return heading('Scheduler', '') + '<section class="panel empty"><h2>Nothing scheduled yet.</h2><p>Ask your agent: “Run this every Monday morning.”</p></section>';
    return heading('Scheduler', '') + `<section class="panel">${rows.map((item, index) => {
      const when = item.next_run || item.wake_at;
      const every = cronText(item.cron);
      return `<article class="schedule-row"><div><h2><a href="${esc(ticketHref(item.ticket))}">${esc(item.title)}</a></h2><p class="next">${when ? `Next run: ${esc(day(when))}` : 'No next run scheduled'}</p>${every ? `<p>${esc(every)}</p>` : ''}</div>${disclosure(`schedule-${item.ticket}-${index}`, 'Details', `<dl><dt>Last run</dt><dd>${item.last_run ? esc(date(item.last_run)) : 'Not yet'}</dd></dl>`)}</article>`;
    }).join('')}</section>`;
  }
  const msgKind = {text: 'Message', file: 'File', question: 'Question', answer: 'Answer'};
  function inbox() {
    const messages = array(state.inbox);
    const titleOf = id => (array(state.tickets).find(t => String(t.id) === String(id)) || {}).title;
    const pending = array(state.tickets).filter(t => openQuestions(t).length);
    const waiting = pending.length ? `<h2 class="section-label">Waiting for your answer</h2><section class="panel">${pending.map(t => openQuestions(t).map(q => `<a class="ticket" href="${esc(ticketHref(t.id))}"><div><div class="ticket-title">${esc(q.text)}</div><div class="ticket-sub"><span>${esc(t.title)}</span></div></div><span class="chevron" aria-hidden="true">›</span></a>`).join('')).join('')}</section>` : '';
    const items = messages.filter(m => m.type !== 'refresh-hint').map(message => {
      const about = message.ticket != null ? titleOf(message.ticket) : '';
      return `<article class="message${message.seen ? '' : ' unseen'}"><div class="message-head"><strong>${esc(message.from)}</strong><span class="pill">${esc(msgKind[message.type] || 'Update')}</span>${message.seen ? '' : '<span class="pill teal">New</span>'}<time>${esc(date(message.created_at))}</time></div>${about ? `<h2><a href="${esc(ticketHref(message.ticket))}">${esc(about)}</a></h2>` : ''}<p class="message-text">${esc(noIds(message.text || message.title))}</p></article>`;
    });
    const msgPanel = items.length ? `<h2 class="section-label">Messages</h2><section class="panel">${items.join('')}</section>` : '';
    const empty = !waiting && !msgPanel ? '<section class="panel empty"><h2>No messages yet.</h2><p>Messages from your agent and other workspaces will appear here.</p></section>' : '';
    return heading('Inbox', '') + waiting + msgPanel + empty;
  }
  function render() {
    if (!state) return;
    const currentRoute = location.hash || '#tickets';
    const sameRoute = currentRoute === renderedRoute;
    const openKeys = new Set(sameRoute ? [...content.querySelectorAll('details[open]')].map(el => el.dataset.key) : []);
    const scroll = [window.scrollX, window.scrollY];
    const active = document.activeElement;
    const focusedKey = sameRoute && active?.tagName === 'SUMMARY' ? active.parentElement.dataset.key : null;
    let route = currentRoute.slice(1), ticket;
    if (route.startsWith('ticket/')) {
      let id;
      try { id = decodeURIComponent(route.slice(7)); } catch (_) { id = ''; }
      ticket = array(state.tickets).find(item => String(item.id) === id);
      route = ticket ? 'ticket' : 'tickets';
    }
    if (!['tickets', 'ticket', 'scheduler', 'inbox'].includes(route) || (route === 'inbox' && (snapshot || state.inbox == null)) || (snapshot && route === 'scheduler')) route = 'tickets';
    if (route === 'tickets' && currentRoute !== '#tickets') history.replaceState(null, '', '#tickets');
    const banner = snapshot ? `<div class="snapshot-banner">Shared copy · ${esc(date(state.now))}</div>` : '';
    content.classList.remove('fade'); content.innerHTML = banner + (route === 'ticket' ? detail(ticket) : route === 'scheduler' ? scheduler() : route === 'inbox' ? inbox() : list());
    content.querySelectorAll('details').forEach(el => { el.open = openKeys.has(el.dataset.key); if (focusedKey === el.dataset.key) el.querySelector('summary').focus({preventScroll: true}); });
    for (const id of ['workspace-name', 'top-workspace']) document.getElementById(id).textContent = state.workspace ?? 'Workspace';
    const count = (id, n) => { document.getElementById(id).textContent = n > 0 ? n : ''; };
    count('ticket-count', array(state.tickets).length);
    count('schedule-count', array(state.scheduler).length);
    count('inbox-count', array(state.inbox).filter(m => !m.seen).length + array(state.tickets).reduce((s, t) => s + openQuestions(t).length, 0));
    document.getElementById('inbox-nav').hidden = snapshot || state.inbox == null;
    document.getElementById('side-nav').hidden = snapshot;
    document.getElementById('workspace-mode').textContent = snapshot ? 'Shared copy' : 'Local workspace';
    document.getElementById('crumb').textContent = route === 'ticket' ? 'Ticket' : label(route);
    document.querySelectorAll('nav.side-nav a').forEach(a => {
      const selected = a.hash === '#' + (route === 'ticket' ? 'tickets' : route);
      a.classList.toggle('active', selected);
      if (selected) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
    });
    if (!sameRoute) { void content.offsetWidth; content.classList.add('fade'); }
    renderedRoute = location.hash || '#tickets';
    window.scrollTo(...(sameRoute ? scroll : [0, 0]));
  }
  let fetching = false;
  async function refresh() {
    if (fetching) return;
    fetching = true;
    const connection = document.getElementById('connection');
    try {
      const response = await fetch('/api/state', {cache: 'no-store'});
      if (!response.ok) throw new Error('State request failed');
      const next = await response.json();
      if (!next || typeof next !== 'object' || Array.isArray(next)) throw new Error('Invalid state');
      connection.hidden = true;
      if (!state || next.rev !== state.rev) { state = next; render(); }
    } catch (_) {
      document.getElementById('connection-text').textContent = state ? 'Can’t refresh right now. Showing the last update; trying again shortly.' : 'Can’t load your workspace right now. Trying again shortly.';
      connection.hidden = false;
    } finally { fetching = false; }
  }
  document.getElementById('retry').addEventListener('click', refresh);
  window.addEventListener('hashchange', render);
  if (snapshot) { state = window.ORCH_SNAPSHOT || {}; render(); }
  else { refresh(); window.setInterval(refresh, 3000); }
})();
