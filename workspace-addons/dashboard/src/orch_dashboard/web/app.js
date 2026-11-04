'use strict';
(() => {
  document.title = 'orch · Dashboard';
  const snapshot = typeof window.ORCH_SNAPSHOT !== 'undefined';
  const content = document.getElementById('content');
  const statuses = ['active', 'waiting', 'open', 'done', 'dropped'];
  const array = value => Array.isArray(value) ? value : [];
  const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const label = value => { const text = String(value ?? ''); return text.charAt(0).toUpperCase() + text.slice(1); };
  const date = value => {
    if (value == null || value === '') return '—';
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? String(value) : parsed.toLocaleString();
  };
  const time = value => `<time>${esc(date(value))}</time>`;
  const ticketHref = id => '#ticket/' + encodeURIComponent(String(id));
  const questions = ticket => array(ticket.questions).filter(q => q.answer == null);
  const metric = ticket => { const items = array(ticket.checklist); return `${items.filter(c => c.done).length}/${items.length}`; };
  const plural = (count, word) => `${count} ${word}${count === 1 ? '' : 's'}`;
  const footer = () => '<footer class="footer"><span>A step counts as done once it has proof.</span><span>Read only</span></footer>';
  let state;
  let renderedRoute = '';
  const heading = (title, subtitle) => `<div class="heading"><div><h1>${esc(title)}</h1><p class="intro">${esc(subtitle)}</p></div><span class="readonly">${esc(date(state.now))}</span></div>`;
  const pill = status => `<span class="pill ${status === 'waiting' ? 'amber' : status === 'active' ? 'teal' : ''}">${esc(label(status))}</span>`;
  const disclosure = (key, title, body) => `<details data-key="${esc(key)}"><summary>${esc(title)}</summary>${body}</details>`;
  function link(item) {
    const url = String(item.url ?? '');
    const title = item.title || url || item.type;
    let safe = false;
    try { safe = /^https?:\/\//i.test(url) && ['http:', 'https:'].includes(new URL(url).protocol); } catch (_) { /* Display malformed URLs as text. */ }
    return safe ? `<a class="chip" href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(title)} ↗</a>` : `<span class="chip">${esc(title)}${item.title && url ? ` · ${esc(url)}` : ''}</span>`;
  }
  function row(ticket) {
    const count = questions(ticket).length;
    return `<a class="ticket" href="${esc(ticketHref(ticket.id))}"><div><div class="ticket-title">${esc(ticket.title)}</div><div class="ticket-sub"><span>${esc(label(ticket.status))}</span>${count ? `<span class="attention">${esc(plural(count, 'question'))} for you</span>` : ''}</div></div><div class="metrics"><span class="metric" aria-label="Checklist completion">✓ ${esc(metric(ticket))}</span><span class="chevron" aria-hidden="true">›</span></div></a>`;
  }
  function list() {
    const tickets = array(state.tickets);
    if (!tickets.length) return heading('Tickets', 'A fresh workspace.') + '<section class="panel empty"><h2>Your first ticket starts here.</h2><p>Give your agent a small piece of work.</p><code>orch ticket new "Rename field X in ingestion job"</code></section>';
    const count = tickets.reduce((sum, ticket) => sum + questions(ticket).length, 0);
    const first = tickets.find(ticket => questions(ticket).length);
    return heading('Tickets', state.workspace) + (count ? `<div class="notice"><strong>${esc(plural(count, 'question'))} ${count === 1 ? 'needs' : 'need'} your input</strong><a href="${esc(ticketHref(first.id))}">View question ↗</a></div>` : '') + statuses.map(status => {
      const group = tickets.filter(ticket => ticket.status === status);
      if (!group.length) return '';
      const body = `<div class="panel">${group.map(row).join('')}</div>`;
      return status === 'dropped' ? `<details class="group" data-key="dropped"><summary>Dropped · ${group.length}</summary>${body}</details>` : `<section class="group"><h2 class="group-title"><span class="status-dot ${status}"></span>${label(status)} <span class="number">${group.length}</span></h2>${body}</section>`;
    }).join('');
  }
  function detail(ticket) {
    const checks = array(ticket.checklist).map((item, index) => {
      const evidence = array(item.evidence);
      return `<div class="check"><span class="${item.done ? 'checkmark' : 'unchecked'}" aria-label="${item.done ? 'Done' : 'Not done'}">${item.done ? '✓' : '○'}</span><div><span class="check-text">${esc(item.text)}</span>${item.done ? evidence.length ? disclosure(`evidence-${item.id ?? index}`, 'Evidence', evidence.map(e => `<p class="evidence">${esc(e.type)} · <code>${esc(e.ref)}</code>${e.text ? ` · ${esc(e.text)}` : ''}</p>`).join('')) : '<div class="missing">No evidence yet</div>' : ''}</div></div>`;
    }).join('');
    const questionSections = array(ticket.questions).map(q => `<section class="panel question"><span class="pill ${q.answer == null ? 'amber' : ''}">${q.answer == null ? 'Open question' : 'Answered'}</span><h2>${esc(q.text)}</h2>${q.answer == null ? array(q.options).map(option => `<div class="option${option === q.recommended ? ' recommended' : ''}">${esc(option)}${option === q.recommended ? ' <span class="recommended-label">(Recommended)</span>' : ''}</div>`).join('') + '<p class="hint">Answer in your agent or on the phone.</p>' : `<p class="question-text">${esc(q.answer)}</p><p class="hint">${esc([q.answered_by, q.via].filter(Boolean).join(' · '))}</p>`}</section>`).join('');
    const history = array(ticket.history).slice().sort((a, b) => (Date.parse(b.at) || 0) - (Date.parse(a.at) || 0));
    return '<a class="back" href="#tickets">← All tickets</a>' + heading(ticket.title, ticket.id) + `<div class="detail-grid"><div><section class="panel"><div class="section-title"><h2>Checklist</h2><small>${esc(metric(ticket))} complete</small></div>${checks || '<p class="panel-body">No checklist items yet.</p>'}</section>${questionSections}<section class="history">${disclosure('history', `History · ${plural(history.length, 'update')}`, `<ol class="timeline">${history.map(h => `<li>${esc(h.text)}<small>${time(h.at)} · ${esc(h.by)}</small></li>`).join('')}</ol>`)}</section></div><section class="panel context"><h2>At a glance</h2><dl><dt>Workspace</dt><dd>${esc(state.workspace)}</dd><dt>Status</dt><dd>${pill(ticket.status)}</dd><dt>Type</dt><dd>${esc(label(ticket.type))}</dd><dt>Created</dt><dd>${time(ticket.created_at)}</dd><dt>Updated</dt><dd>${time(ticket.updated_at)}</dd>${ticket.waiting_on ? `<dt>Waiting on</dt><dd>${esc(ticket.waiting_on.kind)} · ${esc(ticket.waiting_on.ref)}</dd>` : ''}${ticket.wake_at ? `<dt>Wake at</dt><dd>${time(ticket.wake_at)}</dd>` : ''}</dl>${ticket.ext?.scheduler?.cron ? disclosure('ticket-schedule', 'Schedule details', `<code>${esc(ticket.ext.scheduler.cron)}</code>`) : ''}${array(ticket.links).length ? `<h2>Links</h2><div class="chips">${ticket.links.map(link).join('')}</div>` : ''}</section></div>`;
  }
  function scheduler() {
    const rows = array(state.scheduler);
    return heading('Scheduler', state.workspace) + `<section class="panel">${rows.length ? rows.map((item, index) => `<article class="schedule-row"><div><h2><a href="${esc(ticketHref(item.ticket))}">${esc(item.title || item.ticket)}</a></h2><p>${esc(label(item.kind))}${item.wake_at ? ` · Wake at ${esc(date(item.wake_at))}` : ''}</p></div>${pill(item.status)}${disclosure(`schedule-${item.ticket}-${index}`, 'Schedule details', `${item.cron ? `<code>${esc(item.cron)}</code>` : '<p>One-time schedule</p>'}<dl><dt>Next run</dt><dd>${time(item.next_run)}</dd><dt>Last run</dt><dd>${time(item.last_run)}</dd></dl>`)}</article>`).join('') : '<p class="panel-body">Nothing scheduled yet. Your upcoming work will appear here.</p>'}</section>`;
  }
  function inbox() {
    const messages = array(state.inbox);
    return heading('Inbox', `${state.workspace ?? ''} · Relay`) + `<section class="panel">${messages.length ? messages.map(message => `<article class="message${message.seen ? '' : ' unseen'}"><div class="message-head"><strong>${esc(message.from)}</strong><span class="pill">${esc(message.type)}</span>${message.seen ? '' : '<span class="pill teal">Unseen</span>'}${time(message.created_at)}</div>${message.title ? `<h2>${message.ticket != null ? `<a href="${esc(ticketHref(message.ticket))}">${esc(message.title)}</a>` : esc(message.title)}</h2>` : ''}<p class="message-text">${esc(message.text)}</p></article>`).join('') : '<p class="panel-body">You’re all caught up. New messages will appear here.</p>'}</section>`;
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
    if (!['tickets', 'ticket', 'scheduler', 'inbox'].includes(route) || (route === 'inbox' && (snapshot || state.inbox == null))) route = 'tickets';
    if (route === 'tickets' && currentRoute !== '#tickets') history.replaceState(null, '', '#tickets');
    const counts = statuses.map(status => `${array(state.tickets).filter(t => t.status === status).length} ${status}`).join(' · ');
    const banner = snapshot ? `<div class="snapshot-banner">Snapshot from ${esc(date(state.now))}<small>Read-only copy · ${esc(counts)}</small></div>` : '';
    content.innerHTML = banner + (route === 'ticket' ? detail(ticket) : route === 'scheduler' ? scheduler() : route === 'inbox' ? inbox() : list()) + footer();
    content.querySelectorAll('details').forEach(el => { el.open = openKeys.has(el.dataset.key); if (focusedKey === el.dataset.key) el.querySelector('summary').focus({preventScroll: true}); });
    for (const id of ['workspace-name', 'top-workspace']) document.getElementById(id).textContent = state.workspace ?? 'Workspace';
    document.getElementById('ticket-count').textContent = array(state.tickets).length;
    document.getElementById('schedule-count').textContent = array(state.scheduler).length;
    document.getElementById('inbox-count').textContent = array(state.inbox).filter(m => !m.seen).length || '';
    document.getElementById('inbox-nav').hidden = snapshot || state.inbox == null;
    document.getElementById('workspace-mode').textContent = snapshot ? 'Published snapshot' : 'Local workspace';
    document.getElementById('crumb').textContent = route === 'ticket' ? 'Ticket detail' : label(route);
    document.querySelectorAll('nav.side-nav a').forEach(a => {
      const selected = a.hash === '#' + (route === 'ticket' ? 'tickets' : route);
      a.classList.toggle('active', selected);
      if (selected) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
    });
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
      connection.textContent = state ? 'Unable to refresh. Showing the last available state; retrying shortly.' : 'Unable to load the workspace. Retrying shortly.';
      connection.hidden = false;
    } finally { fetching = false; }
  }
  window.addEventListener('hashchange', render);
  if (snapshot) { state = window.ORCH_SNAPSHOT || {}; render(); }
  else { refresh(); window.setInterval(refresh, 3000); }
})();
