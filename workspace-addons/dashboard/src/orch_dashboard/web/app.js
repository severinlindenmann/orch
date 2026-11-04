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
  const names = () => state.names || {};
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
  // ---- visual helpers (inline SVG, no libraries) ----
  const ic = (id, cls = '') => `<svg class="ic${cls ? ' ' + cls : ''}" aria-hidden="true" focusable="false"><use href="#i-${id}"/></svg>`;
  const SM = {active: {icon: 'half', word: 'In progress'}, waiting: {icon: 'hourglass', word: 'Waiting'}, open: {icon: 'circle', word: 'Open'}, done: {icon: 'check', word: 'Done'}, dropped: {icon: 'x', word: 'Dropped'}};
  const stepKind = item => (item.done ? (array(item.evidence).length ? 'ok' : 'noproof') : 'todo');
  const timeOf = value => { const d = parse(value); return d ? fmt(d, {hour: '2-digit', minute: '2-digit'}) : ''; };
  const sameDay = (a, b) => a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
  function relDay(value) {
    const d = parse(value);
    if (!d) return '';
    const now = new Date(), tomorrow = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1);
    return sameDay(d, now) ? 'Today' : sameDay(d, tomorrow) ? 'Tomorrow' : fmt(d, {weekday: 'short'});
  }
  const shortWhen = value => { const d = parse(value); return d ? `${relDay(value)} ${timeOf(value)}` : ''; };
  function cronShort(cron) {
    const m = /^(\d{1,2}) (\d{1,2}) \* \* (\*|\d)$/.exec(String(cron || '').trim());
    if (!m) return '';
    const at = `${m[2].padStart(2, '0')}:${m[1].padStart(2, '0')}`;
    return m[3] === '*' ? `Daily ${at}` : `${dayWord[Number(m[3]) % 7].slice(0, 3)} ${at}`;
  }
  const tag = (kind, icon, text, title) => `<span class="tag ${kind}"${title ? ` title="${esc(title)}"` : ''}>${icon ? ic(icon) : ''}${esc(text)}</span>`;
  // One arc per checklist step: filled = done, amber = done without proof, grey = still to do.
  function ring(ticket, size, text) {
    const steps = array(ticket.checklist), n = steps.length;
    if (!n) return '';
    const done = doneCount(ticket), stroke = Math.max(4, Math.round(size / 9)), r = (size - stroke) / 2, c = 2 * Math.PI * r, mid = size / 2;
    const gap = n > 1 && n <= 16 ? Math.min(4, c / n / 3) : 0, per = c / n;
    const arcs = steps.map((item, i) => {
      const kind = stepKind(item), len = Math.max(per - gap, 1);
      return `<circle class="arc ${kind}" cx="${mid}" cy="${mid}" r="${r.toFixed(2)}" stroke-width="${stroke}" stroke-dasharray="${len.toFixed(2)} ${(c - len).toFixed(2)}" stroke-dashoffset="${(-i * per).toFixed(2)}"/>`;
    }).join('');
    const label = `${done} of ${plural(n, 'step')} done`;
    return `<span class="ring${done === n ? ' full' : ''}" role="img" aria-label="${esc(label)}" title="${esc(label)}"><svg viewBox="0 0 ${size} ${size}" width="${size}" height="${size}" aria-hidden="true"><g transform="rotate(-90 ${mid} ${mid})">${arcs}</g></svg>${text ? `<b>${done}/${n}</b>` : ''}</span>`;
  }
  const heading = title => `<div class="heading"><h1>${esc(title)}</h1></div>`;
  const statusChip = status => `<span class="chip-status s-${esc(status)}">${ic(SM[status]?.icon || 'circle')}${esc(SM[status]?.word || label(status))}</span>`;
  const disclosure = (key, title, body, icon) => `<details data-key="${esc(key)}"><summary>${icon ? ic(icon) : ''}<span>${esc(title)}</span>${ic('chevron', 'chev')}</summary>${body}</details>`;
  function link(item) {
    const url = String(item.url ?? '');
    let safe = false, host = '';
    try { const u = new URL(url); safe = ['http:', 'https:'].includes(u.protocol); host = u.hostname; } catch (_) { /* shown as text */ }
    const title = item.title || (safe ? host : base(url)) || 'Link';
    return safe ? `<a class="chip" href="${esc(url)}" target="_blank" rel="noopener noreferrer">${ic('link')}${esc(title)}</a>` : `<span class="chip">${ic('link')}${esc(title)}</span>`;
  }
  function evidenceChip(e) {
    const ref = String(e.ref ?? ''), text = String(e.text ?? '');
    let icon = 'note', words = noIds(text || ref) || 'Note';
    if (e.type === 'pr') { icon = 'pr'; words = evidenceLabel(e); }
    else if (e.type === 'commit') { icon = 'commit'; words = 'Code change'; }
    else if (e.type === 'file') { icon = 'file'; words = base(ref); }
    else if (e.type === 'url') { icon = 'link'; words = evidenceLabel(e); }
    else if (e.type === 'command') { icon = 'test'; words = text || 'Check run'; }
    const tip = e.type === 'commit' ? ref.slice(0, 7) : e.type === 'command' ? ref : '';
    return `<span class="chip ev ev-${esc(e.type || 'note')}"${tip ? ` title="${esc(tip)}"` : ''}>${ic(icon)}<span>${esc(words)}</span></span>`;
  }
  function optionPills(q) {
    const opts = array(q.options);
    return opts.length ? `<ul class="pills" aria-label="Options">${opts.map(o => `<li class="opt${o === q.recommended ? ' rec' : ''}">${o === q.recommended ? ic('star') + '<span class="sr">Recommended: </span>' : ''}${esc(o)}</li>`).join('')}</ul>` : '';
  }
  function askCard(ticket, q, as = 'a', compact = false) {
    const open = as === 'a' ? ` href="${esc(ticketHref(ticket.id))}"` : '';
    return `<${as} class="ask${compact ? ' compact' : ''}"${open}><span class="ask-icon">${ic('question')}</span><div class="ask-body"><h2>${esc(q.text)}</h2><div class="ask-ticket">${esc(ticket.title)}</div>${compact ? '' : optionPills(q)}</div>${as === 'a' ? ic('chevron', 'go') : ''}</${as}>`;
  }
  function waitTag(ticket) {
    if (ticket.status !== 'waiting' || ticket.type === 'recurring') return '';
    const w = ticket.waiting_on, wake = ticket.wake_at;
    if (w && w.kind === 'workspace') return tag('wait', 'chat', `Reply from ${names()[w.ref] || 'another workspace'}`);
    if (w && w.kind === 'webhook') return tag('wait', 'clock', 'Outside event');
    if (w && w.kind === 'question') return wake ? tag('wait', 'clock', shortWhen(wake)) : '';
    return wake ? tag('wait', 'clock', shortWhen(wake)) : '';
  }
  function row(ticket) {
    const count = openQuestions(ticket).length, needs = count > 0;
    const chips = [needs ? tag('need', 'question', count > 1 ? `${count} answers` : 'Your answer') : waitTag(ticket),
      ticket.type === 'recurring' || ticket.ext?.scheduler?.cron ? tag('repeat', 'repeat', cronShort(ticket.ext?.scheduler?.cron) || 'Repeats') : ''].filter(Boolean).join('');
    return `<a class="card s-${esc(ticket.status)}${needs ? ' needs' : ''}" href="${esc(ticketHref(ticket.id))}"><div class="card-main"><div class="card-title">${esc(ticket.title)}</div>${chips ? `<div class="tags">${chips}</div>` : ''}</div>${ring(ticket, 44, false)}</a>`;
  }
  const mini = ticket => `<a class="mini s-${esc(ticket.status)}" href="${esc(ticketHref(ticket.id))}">${ic('check')}<span class="mini-title">${esc(ticket.title)}</span><time>${esc(ago(ticket.updated_at))}</time></a>`;
  function weekBars(tickets) {
    const now = new Date(), monday = new Date(now.getFullYear(), now.getMonth(), now.getDate() - ((now.getDay() + 6) % 7));
    const days = Array.from({length: 7}, (_, i) => new Date(monday.getFullYear(), monday.getMonth(), monday.getDate() + i));
    const counts = days.map(d => tickets.reduce((s, t) => s + array(t.history).filter(h => { const x = parse(h.at); return x && sameDay(x, d); }).length, 0));
    const max = Math.max(1, ...counts), total = counts.reduce((a, b) => a + b, 0);
    if (!total) return '';
    const cols = days.map((d, i) => {
      const future = d > now && !sameDay(d, now), today = sameDay(d, now), name = fmt(d, {weekday: 'short'});
      return `<li class="${today ? 'today' : future ? 'future' : ''}" title="${esc(name)}: ${counts[i]}"><span class="val">${future ? '' : counts[i]}</span><span class="bar"><svg width="100%" height="56" aria-hidden="true"><rect x="0" width="100%" y="${100 - Math.max(counts[i] ? 12 : 3, Math.round(counts[i] / max * 100))}%" height="${Math.max(counts[i] ? 12 : 3, Math.round(counts[i] / max * 100))}%" rx="4" ${future ? 'hidden' : ''}/></svg></span><span class="dn"><span class="d-long">${esc(name)}</span><span class="d-short" aria-hidden="true">${esc(name.slice(0, 2))}</span></span></li>`;
    }).join('');
    return `<section class="week panel" aria-label="Activity this week: ${total} updates"><div class="week-head">${ic('spark')}<b>${total}</b><span>updates</span></div><ul class="bars">${cols}</ul></section>`;
  }
  function statusBar(tickets) {
    const counts = statuses.map(s => [s, tickets.filter(t => t.status === s).length]).filter(([s, n]) => n && s !== 'dropped');
    const total = counts.reduce((a, [, n]) => a + n, 0);
    if (!total) return '';
    const text = counts.map(([s, n]) => `${n} ${SM[s].word.toLowerCase()}`).join(', ');
    return `<section class="overview panel" aria-label="${esc(text)}"><svg class="stack" width="100%" height="14" role="img" aria-label="${esc(text)}">${(() => { let x = 0; return counts.map(([s, n]) => { const w = n / total * 100, r = `<rect class="s-${s}" x="${x.toFixed(2)}%" width="${Math.max(w - 1.2, 1).toFixed(2)}%" y="0" height="14" rx="7"/>`; x += w; return r; }).join(''); })()}</svg><ul class="legend">${counts.map(([s, n]) => `<li class="s-${s}">${ic(SM[s].icon)}<b>${n}</b><span>${esc(SM[s].word)}</span></li>`).join('')}</ul></section>`;
  }
  function list() {
    const tickets = array(state.tickets);
    if (!tickets.length) return heading('Tickets') + `<section class="panel empty"><span class="empty-ic">${ic('list')}</span><h2>Your first ticket starts here.</h2><p>Ask your agent: “Prepare my weekly summary.” Your ticket will appear here.</p></section>`;
    const asks = tickets.flatMap(t => openQuestions(t).map(q => askCard(t, q, 'a', true)));
    const body = statuses.map(status => {
      const group = tickets.filter(ticket => ticket.status === status);
      if (!group.length) return '';
      if (status === 'dropped') return `<details class="group" data-key="dropped"><summary>${ic('x')}<span>Dropped</span><span class="num">${group.length}</span>${ic('chevron', 'chev')}</summary><div class="minis">${group.map(t => `<a class="mini s-dropped" href="${esc(ticketHref(t.id))}">${ic('x')}<span class="mini-title">${esc(t.title)}</span></a>`).join('')}</div></details>`;
      return `<section class="group"><h2 class="group-title s-${status}">${ic(SM[status].icon)}<span>${esc(SM[status].word)}</span><span class="num">${group.length}</span></h2>${status === 'done' ? `<div class="minis">${group.map(mini).join('')}</div>` : `<div class="cards">${group.map(row).join('')}</div>`}</section>`;
    }).join('');
    return heading('Tickets') + (asks.length ? `<div class="asks">${asks.join('')}</div>` : '') + `<div class="glance">${statusBar(tickets)}${weekBars(tickets)}</div>` + body;
  }
  function detail(ticket) {
    const steps = array(ticket.checklist), open = openQuestions(ticket), qs = array(ticket.questions);
    const blocker = open.length ? steps.findIndex(s => !s.done) : -1;
    const stepper = steps.length ? `<section class="panel steps-panel"><ol class="steps">${steps.map((item, i) => {
      const kind = stepKind(item), evidence = array(item.evidence);
      const node = item.done ? ic('check') : i === blocker ? ic('question') : '';
      return `<li class="step ${kind}${i === blocker ? ' blocked' : ''}"><span class="node" role="img" aria-label="${item.done ? 'Done' : i === blocker ? 'Needs your answer' : 'Not done'}">${node}</span><div class="step-body"><span class="check-text">${esc(item.text)}</span>${item.done ? `<div class="chips">${evidence.length ? evidence.map(evidenceChip).join('') : `<span class="chip noproof">${ic('question')}No proof yet</span>`}</div>` : ''}</div></li>`;
    }).join('')}</ol></section>` : '';
    const history = array(ticket.history).slice().sort((a, b) => (Date.parse(b.at) || 0) - (Date.parse(a.at) || 0));
    const cron = cronShort(ticket.ext?.scheduler?.cron), wake = parse(ticket.wake_at);
    const more = `<dl><dt>Type</dt><dd>${esc(label(ticket.type))}</dd><dt>Created</dt><dd>${esc(date(ticket.created_at))}</dd></dl>`;
    const asks = qs.map(q => q.answer == null ? askCard(ticket, q, 'div')
      : `<div class="ask done"><span class="ask-icon">${ic('check')}</span><div class="ask-body"><h2>${esc(q.text)}</h2><div class="pills"><span class="opt rec">${esc(q.answer)}</span></div>${q.answered_by ? `<div class="ask-ticket">${esc(String(q.answered_by).replace(/^(agent|human):/, ''))}${q.via ? ` · ${esc(q.via)}` : ''}</div>` : ''}</div></div>`).join('');
    const side = (wake ? `<div class="side-item">${ic('calendar')}<div class="cal"><b>${esc(fmt(wake, {weekday: 'short'}))}</b><span>${wake.getDate()}</span></div><div class="cal-time">${esc(timeOf(ticket.wake_at))}<small>${esc(fmt(wake, {month: 'long'}))}</small></div></div>` : '')
      + (cron ? `<div class="side-item">${tag('repeat', 'repeat', cron)}</div>` : '')
      + (array(ticket.links).length ? `<div class="chips">${ticket.links.map(link).join('')}</div>` : '')
      + disclosure('more', 'More details', more);
    return '<a class="back" href="#tickets">' + ic('chevron', 'flip') + 'All tickets</a>'
      + `<div class="detail-head">${ring(ticket, 72, true)}<div class="detail-title"><h1>${esc(ticket.title)}</h1><div class="statusline">${statusChip(ticket.status)}${ticket.status === 'waiting' ? waitTag(ticket) : ''}<span class="updated">${esc(ago(ticket.updated_at))}</span></div></div></div>`
      + (asks ? `<div class="asks">${asks}</div>` : '') + (open.length && !snapshot ? '<p class="hint">Answer in your agent or on your phone.</p>' : '')
      + `<div class="detail-grid"><div>${stepper}${history.length ? `<section class="history">${disclosure('history', `History · ${history.length}`, `<ol class="timeline">${history.map(h => `<li>${esc(noIds(h.text))}<small>${esc(date(h.at))} · ${esc(String(h.by).replace(/^(agent|human):/, ''))}</small></li>`).join('')}</ol>`, 'clock')}</section>` : ''}</div>`
      + `<aside class="panel context">${side}</aside></div>`;
  }
  function scheduler() {
    const rows = array(state.scheduler);
    if (!rows.length) return heading('Scheduler') + `<section class="panel empty"><span class="empty-ic">${ic('calendar')}</span><h2>Nothing scheduled yet.</h2><p>Ask your agent: “Run this every Monday morning.”</p></section>`;
    const now = new Date(), start = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const whenOf = item => parse(item.next_run || item.wake_at);
    const days = Array.from({length: 7}, (_, i) => new Date(start.getFullYear(), start.getMonth(), start.getDate() + i));
    const any = days.some(d => rows.some(r => { const w = whenOf(r); return w && sameDay(w, d); }));
    const strip = `<ol class="strip${any ? '' : ' none'}">${days.map(d => {
      const runs = rows.filter(r => { const w = whenOf(r); return w && sameDay(w, d); });
      return `<li class="day${sameDay(d, now) ? ' today' : ''}${runs.length ? '' : ' empty'}"><div class="day-head"><span>${esc(fmt(d, {weekday: 'short'}))}</span><b>${d.getDate()}</b></div>${runs.map(r => `<a class="run" href="${esc(ticketHref(r.ticket))}">${ic(r.kind === 'recurring' ? 'repeat' : 'clock')}<time>${esc(timeOf(r.next_run || r.wake_at))}</time><span>${esc(r.title)}</span></a>`).join('')}</li>`;
    }).join('')}</ol>`;
    const cards = rows.map((item, index) => {
      const w = whenOf(item), every = cronShort(item.cron);
      return `<article class="sched"><div class="sched-time">${w ? `<b>${esc(timeOf(item.next_run || item.wake_at))}</b><span class="tag wait">${esc(relDay(item.next_run || item.wake_at))}</span>` : `<span class="tag">No time set</span>`}</div><div class="sched-main"><h2><a href="${esc(ticketHref(item.ticket))}">${esc(item.title)}</a></h2><div class="tags">${every ? tag('repeat', 'repeat', every) : ''}${item.last_run ? `<span class="tag ok" title="Last run">${ic('check')}${esc(shortWhen(item.last_run) || date(item.last_run))}</span>` : ''}</div></div></article>`;
    }).join('');
    return heading('Scheduler') + `<section class="panel strip-panel">${strip}</section><section class="panel sched-list">${cards}</section>`;
  }
  const kindIcon = {text: 'chat', file: 'file', question: 'question', answer: 'test'};
  const hue = name => { let h = 0; for (const ch of String(name)) h = (h * 31 + ch.charCodeAt(0)) % 5; return h + 1; };
  function inbox() {
    const messages = array(state.inbox).filter(m => m.type !== 'refresh-hint');
    const tickets = array(state.tickets);
    const titleOf = id => (tickets.find(t => String(t.id) === String(id)) || {}).title;
    const asks = tickets.flatMap(t => openQuestions(t).map(q => askCard(t, q)));
    const groups = [];
    for (const m of messages) { let g = groups.find(x => x.name === m.from); if (!g) groups.push(g = {name: m.from, items: []}); g.items.push(m); }
    const body = groups.map(g => {
      const unread = g.items.filter(m => !m.seen).length;
      return `<section class="group sender"><h2 class="sender-head"><span class="avatar c${hue(g.name)}" aria-hidden="true">${esc(String(g.name).trim().charAt(0).toUpperCase() || '?')}</span><span>${esc(g.name)}</span>${unread ? `<span class="badge" title="${unread} new" aria-label="${unread} new">${unread}</span>` : ''}</h2><div class="panel">${g.items.map(m => {
        const about = m.ticket != null ? titleOf(m.ticket) : '';
        const text = noIds(m.text || m.title);
        return `<details class="msg${m.seen ? '' : ' unseen'}" data-key="msg-${esc(m.id)}"><summary><span class="dotmark" aria-label="${m.seen ? 'Seen' : 'New'}"></span>${ic(kindIcon[m.type] || 'chat')}<span class="msg-text">${esc(text)}</span><time>${esc(ago(m.created_at))}</time>${ic('chevron', 'chev')}</summary><div class="msg-more"><p class="message-text">${esc(text)}</p>${about ? `<a class="chip" href="${esc(ticketHref(m.ticket))}">${ic('list')}${esc(about)}</a>` : ''}</div></details>`;
      }).join('')}</div></section>`;
    }).join('');
    const empty = !asks.length && !body ? `<section class="panel empty"><span class="empty-ic">${ic('inbox')}</span><h2>No messages yet.</h2><p>Messages from your agent and other workspaces will appear here.</p></section>` : '';
    return heading('Inbox') + (asks.length ? `<div class="asks">${asks.join('')}</div>` : '') + body + empty;
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
