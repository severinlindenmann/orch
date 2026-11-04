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
    return fmt(d, {weekday: 'short', day: 'numeric', month: 'short'});
  }
  const ticketHref = id => '#ticket/' + encodeURIComponent(String(id));
  const openQuestions = ticket => array(ticket.questions).filter(q => q.answer == null);
  const doneCount = ticket => array(ticket.checklist).filter(c => c.done).length;
  // Never show internal ids: drop "message m_..." phrases and any ws_/t_/q_ style token.
  const noIds = text => String(text ?? '').replace(/,?\s*message\s+m_\w+/gi, '').replace(/\b(?:ws|ph|m|t|q|wh|b|f)_[A-Za-z0-9]{4,}\b/g, '').replace(/\s+via\s+(?:the\s+)?relay\b/gi, '').replace(/\brelay\b/gi, '').replace(/\s+([,.])/g, '$1').replace(/\s+/g, ' ').trim();
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
  const rawKey = t => /^[A-Z][A-Z0-9]*-\d+$/.test(t) || /^PR\s*#?\d+$/i.test(t) || /^[A-Z]{3,5}$/.test(t);
  const linkKind = {jira: 'Issue in tracker', issue: 'Issue in tracker', github: 'Code review', pr: 'Code review', teams: 'Chat thread', publish: 'Shared file', xlsx: 'Excel file'};
  function link(item) {
    const url = String(item.url ?? '');
    let safe = false, host = '';
    try { const u = new URL(url); safe = ['http:', 'https:'].includes(u.protocol); host = u.hostname; } catch (_) { /* shown as text */ }
    const raw = String(item.title || '').replace(/\s*\((?:encrypted|private)\)/i, '').trim();
    const kind = linkKind[String(item.type || '').toLowerCase()] || linkKind[raw.toLowerCase()];
    const title = (!raw || rawKey(raw)) ? (kind || (safe ? host : base(url)) || 'Link') : /^sample rows$/i.test(raw) ? 'Sample data' : raw;
    return safe ? `<a class="chip" href="${esc(url)}" target="_blank" rel="noopener noreferrer">${ic('link')}${esc(title)}</a>` : `<span class="chip">${ic('link')}${esc(title)}</span>`;
  }
  const linkBox = items => items.length > 1 ? disclosure('links', plural(items.length, 'link'), `<div class="chips">${items.map(link).join('')}</div>`, 'link') : `<div class="chips">${items.map(link).join('')}</div>`;
  function evidenceChip(e) {
    const ref = String(e.ref ?? ''), text = String(e.text ?? '');
    let icon = 'note', words = noIds(text || ref) || 'Note';
    if (e.type === 'pr') { icon = 'pr'; words = evidenceLabel(e); }
    else if (e.type === 'commit') { icon = 'commit'; words = 'Code updated'; }
    else if (e.type === 'file') { icon = 'file'; words = base(ref); }
    else if (e.type === 'url') { icon = 'link'; words = evidenceLabel(e); }
    else if (e.type === 'command') { icon = 'test'; const n = /(\d+)\s+passed/i.exec(text); words = n ? `${n[1]} checks OK` : (noIds(text) || 'Check passed'); }
    const tip = e.type === 'commit' ? ref.slice(0, 7) : e.type === 'command' ? ref : '';
    return `<span class="chip ev ev-${esc(e.type || 'note')}"${tip ? ` title="${esc(tip)}"` : ''}>${ic(icon)}<span>${esc(words)}</span></span>`;
  }
  function optionPills(q) {
    const opts = array(q.options);
    return opts.length ? `<ul class="pills" aria-label="Options">${opts.map(o => `<li class="opt${o === q.recommended ? ' rec' : ''}">${o === q.recommended ? ic('star') + esc(o) + '<small>suggested</small>' : esc(o)}</li>`).join('')}</ul>` : '';
  }
  function askCard(ticket, q, as = 'a', compact = false) {
    const open = as === 'a' ? ` href="${esc(ticketHref(ticket.id))}"` : '';
    const hint = compact || snapshot ? '' : `<p class="ask-hint">${ic('chat')}Answer in your agent or on your phone.</p>`;
    return `<${as} class="ask${compact ? ' compact' : ''}"${open}><span class="ask-icon">${ic('question')}</span><div class="ask-body"><h2>${esc(q.text)}</h2><div class="ask-ticket">${esc(ticket.title)}</div>${compact ? '' : optionPills(q) + hint}</div>${as === 'a' && !snapshot ? ic('chevron', 'go') : ''}</${as}>`;
  }
  function waitTag(ticket) {
    if (ticket.status !== 'waiting' || ticket.type === 'recurring') return '';
    const w = ticket.waiting_on, wake = ticket.wake_at;
    if (w && w.kind === 'workspace') return tag('wait', 'chat', `Reply from ${names()[w.ref] || 'another workspace'}`);
    if (w && w.kind === 'webhook') return tag('wait', 'hourglass', 'Outside event');
    if (wake) return tag('wait', 'clock', shortWhen(wake));
    return tag('wait', 'hourglass', w && w.kind === 'question' ? 'Waiting for an answer' : 'Waiting');
  }
  function row(ticket) {
    const count = openQuestions(ticket).length, needs = count > 0;
    const chips = [needs ? tag('need', 'question', count > 1 ? `${count} questions` : 'Your answer') : waitTag(ticket),
      ticket.type === 'recurring' || ticket.ext?.scheduler?.cron ? tag('repeat', 'repeat', cronShort(ticket.ext?.scheduler?.cron) || 'Repeats') : ''].filter(Boolean).join('');
    return `<a class="card s-${esc(ticket.status)}${needs ? ' needs' : ''}" href="${esc(ticketHref(ticket.id))}"><div class="card-main"><div class="card-title">${esc(ticket.title)}</div>${chips ? `<div class="tags">${chips}</div>` : ''}</div>${ring(ticket, 44, true)}</a>`;
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
    return `<section class="week panel" aria-label="Activity this week: ${total} updates"><div class="week-head">${ic('spark')}<b>${total}</b><span>updates this week</span></div><ul class="bars">${cols}</ul></section>`;
  }
  function statusBar(tickets) {
    const counts = statuses.map(s => [s, tickets.filter(t => t.status === s).length]).filter(([s, n]) => n && s !== 'dropped');
    const total = counts.reduce((a, [, n]) => a + n, 0);
    if (!total) return '';
    const text = counts.map(([s, n]) => `${n} ${SM[s].word.toLowerCase()}`).join(', ');
    let x = 0;
    const rects = counts.map(([s, n]) => { const w = n / total * 100, r = `<rect class="s-${s}" x="${x.toFixed(2)}%" width="${w.toFixed(2)}%" y="0" height="100%"/>`; x += w; return r; }).join('');
    return `<section class="overview panel" aria-label="${esc(text)}"><svg class="segbar" width="100%" height="12" aria-hidden="true" preserveAspectRatio="none"><clipPath id="segclip"><rect width="100%" height="100%" rx="6"/></clipPath><g clip-path="url(#segclip)">${rects}</g></svg><ul class="seg">${counts.map(([s, n]) => `<li class="s-${s}"><span class="seg-text">${ic(SM[s].icon)}<b>${n}</b><span>${esc(SM[s].word)}</span></span></li>`).join('')}</ul></section>`;
  }
  function list() {
    const tickets = array(state.tickets);
    if (!tickets.length) return heading('Tickets') + `<section class="panel empty"><span class="empty-ic">${ic('list')}</span><h2>Your first ticket starts here.</h2><p>Ask your agent: “Prepare my weekly summary.” Your ticket will appear here.</p><button type="button" class="copy-req" data-copy="Prepare my weekly summary.">Copy this request</button></section>`;
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
    }).join('')}</ol></section>` : `<section class="panel steps-panel no-steps"><p>No steps yet. Your agent adds them as it plans the work.</p></section>`;
    const history = array(ticket.history).slice().sort((a, b) => (Date.parse(b.at) || 0) - (Date.parse(a.at) || 0));
    const cron = cronShort(ticket.ext?.scheduler?.cron), wake = parse(ticket.wake_at);
    const more = `<dl><dt>Type</dt><dd>${esc(label(ticket.type))}</dd><dt>Created</dt><dd>${esc(date(ticket.created_at))}</dd></dl>`;
    const asks = qs.map(q => q.answer == null ? askCard(ticket, q, 'div')
      : `<div class="ask done"><span class="ask-icon">${ic('check')}</span><div class="ask-body"><h2>${esc(q.text)}</h2><div class="pills"><span class="opt rec">${esc(q.answer)}</span></div>${q.answered_by ? `<div class="ask-ticket">${esc(String(q.answered_by).replace(/^(agent|human):/, ''))}${q.via ? ` · ${esc(q.via)}` : ''}</div>` : ''}</div></div>`).join('');
    const side = (wake ? `<div class="side-item">${ic('calendar')}<div class="cal"><b>${esc(fmt(wake, {weekday: 'short'}))}</b><span>${wake.getDate()}</span></div><div class="cal-time">${esc(timeOf(ticket.wake_at))}<small>${esc(fmt(wake, {month: 'long'}))}</small></div></div>` : '')
      + (cron ? `<div class="side-item">${tag('repeat', 'repeat', cron)}</div>` : '')
      + (array(ticket.links).length ? linkBox(ticket.links) : '')
      + disclosure('more', 'More details', more);
    return '<a class="back" href="#tickets">' + ic('chevron', 'flip') + 'All tickets</a>'
      + `<div class="detail-head">${ring(ticket, 72, true)}<div class="detail-title"><h1>${esc(ticket.title)}</h1><div class="statusline">${ticket.status === 'waiting' && !wake && waitTag(ticket) ? waitTag(ticket) : statusChip(ticket.status)}<span class="updated" title="Last change">${ic('clock')}Updated ${esc(ago(ticket.updated_at))}</span></div></div></div>`
      + (asks ? `<div class="asks">${asks}</div>` : '')
      + `<div class="detail-grid"><div>${stepper}${history.length ? `<section class="history">${disclosure('history', `History · ${history.length}`, `<ol class="timeline">${history.map(h => `<li>${esc(noIds(h.text))}<small>${esc(date(h.at))} · ${esc(String(h.by).replace(/^(agent|human):/, ''))}</small></li>`).join('')}</ol>`, 'clock')}</section>` : ''}</div>`
      + `<aside class="panel context">${side}</aside></div>`;
  }
  function nextCron(cron) {
    const m = /^(\d{1,2}) (\d{1,2}) \* \* (\*|\d)$/.exec(String(cron || '').trim());
    if (!m) return null;
    const now = new Date();
    for (let i = 0; i < 8; i++) {
      const d = new Date(now.getFullYear(), now.getMonth(), now.getDate() + i, Number(m[2]), Number(m[1]));
      if (d > now && (m[3] === '*' || d.getDay() === Number(m[3]) % 7)) return d.toISOString();
    }
    return null;
  }
  function scheduler() {
    const rows = array(state.scheduler).map(r => ({...r, at: r.next_run || r.wake_at || nextCron(r.cron)}));
    if (!rows.length) return heading('Scheduler') + `<section class="panel empty"><span class="empty-ic">${ic('calendar')}</span><h2>Nothing scheduled yet.</h2><p>Ask your agent: “Run this every Monday morning.”</p><button type="button" class="copy-req" data-copy="Run this every Monday morning.">Copy this request</button></section>`;
    const now = new Date(), start = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const days = Array.from({length: 7}, (_, i) => new Date(start.getFullYear(), start.getMonth(), start.getDate() + i));
    const range = `${fmt(days[0], {weekday: 'short', day: 'numeric', month: 'short'})} – ${fmt(days[6], {weekday: 'short', day: 'numeric', month: 'short'})}`;
    const strip = `<ol class="strip">${days.map(d => {
      const runs = rows.filter(r => { const w = parse(r.at); return w && sameDay(w, d); });
      return `<li class="day${sameDay(d, now) ? ' today' : ''}${runs.length ? ' has' : ' empty'}"><div class="day-head"><span>${esc(fmt(d, {weekday: 'short'}))}</span><b>${d.getDate()}</b></div>${runs.length ? runs.map(r => `<a class="run" href="${esc(ticketHref(r.ticket))}" aria-label="${esc(`${r.title}, ${timeOf(r.at)}`)}" title="${esc(r.title)}">${ic(r.kind === 'recurring' ? 'repeat' : 'clock')}<time>${esc(timeOf(r.at))}</time><span>${esc(r.title)}</span></a>`).join('') : '<span class="none-day" aria-hidden="true">–</span>'}</li>`;
    }).join('')}</ol>`;
    const sorted = rows.slice().sort((a, b) => String(a.at || '~').localeCompare(String(b.at || '~')));
    const row = (r, hero) => {
      const every = cronShort(r.cron), w = parse(r.at);
      return `<a class="sched${hero ? ' hero' : ''}" href="${esc(ticketHref(r.ticket))}"><div class="sched-time">${w ? `<b>${esc(timeOf(r.at))}</b><span class="tag wait">${esc(fmt(w, {weekday: 'short', day: 'numeric', month: 'short'}))}</span>` : `<span class="tag">Not scheduled yet</span>`}</div><div class="sched-main"><h2>${esc(r.title)}</h2>${every ? `<div class="tags">${tag('repeat', 'repeat', every)}</div>` : ''}</div>${ic('chevron', 'go')}</a>`;
    };
    const next = sorted[0], rest = sorted.slice(1);
    return heading('Scheduler') + `<section class="panel strip-panel"><div class="range">${esc(range)}</div>${strip}</section>`
      + `<h2 class="sub">Next</h2><section class="panel sched-list">${row(next, true)}</section>`
      + (rest.length ? `<h2 class="sub">Then</h2><section class="panel sched-list then">${rest.map(r => row(r, false)).join('')}</section>` : '');
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
      return `<section class="group sender"><h2 class="sender-head"><span class="avatar c${hue(g.name)}" aria-hidden="true">${g.name === 'Your phone' ? ic('phone') : esc(String(g.name).trim().charAt(0).toUpperCase() || '?')}</span><span>${esc(g.name)}</span></h2><div class="panel">${g.items.map(m => {
        const about = m.ticket != null ? titleOf(m.ticket) : '';
        const text = noIds(m.text || m.title) || (m.type === 'file' ? 'A file' : 'New message');
        return `<details class="msg${m.seen ? '' : ' unseen'}" data-key="msg-${esc(m.id)}"><summary><span class="dotmark" aria-label="${m.seen ? 'Seen' : 'New'}"></span>${m.type === 'file' ? ic('file') : ''}<span class="msg-text">${esc(text)}</span><time>${esc(ago(m.created_at))}</time>${ic('chevron', 'chev')}</summary><div class="msg-more"><p class="message-text">${esc(text)}</p>${about ? `<a class="chip" href="${esc(ticketHref(m.ticket))}">${ic('list')}${esc(about)}</a>` : ''}</div></details>`;
      }).join('')}</div></section>`;
    }).join('');
    const empty = !asks.length && !body ? `<section class="panel empty"><span class="empty-ic">${ic('inbox')}</span><h2>No messages yet.</h2><p>Messages from your agent and other workspaces will appear here.</p><button type="button" class="copy-req" data-copy="Ask me a question about my tickets.">Copy this request</button></section>` : '';
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
    count('inbox-count', array(state.inbox).filter(m => !m.seen && m.type !== 'refresh-hint').length);
    document.getElementById('inbox-nav').hidden = snapshot || state.inbox == null;
    document.getElementById('side-nav').hidden = snapshot;
    document.getElementById('workspace-mode').textContent = snapshot ? 'Shared copy' : 'Local workspace';
    document.getElementById('crumb').textContent = route === 'ticket' ? ticket.title : label(route);
    document.getElementById('updated').textContent = snapshot ? '' : ` · Updated ${timeOf(new Date().toISOString())}`;
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
      if (!state) content.innerHTML = '<section class="panel empty"><span class="empty-ic">'+ic('clock')+'</span><h2>Waiting for your workspace…</h2><p>This page will fill in as soon as it answers.</p></section>';
    } finally { fetching = false; }
  }
  const retry = document.getElementById('retry');
  retry.addEventListener('click', async () => {
    retry.disabled = true; retry.setAttribute('aria-busy', 'true'); retry.textContent = 'Trying…';
    await refresh();
    retry.disabled = false; retry.removeAttribute('aria-busy'); retry.textContent = 'Try again';
  });
  document.addEventListener('keydown', event => {
    if (event.key !== 'Escape') return;
    const open = document.activeElement?.closest?.('details[open]');
    if (open) { open.open = false; open.querySelector('summary').focus(); }
  });
  document.addEventListener('click', async event => {
    const b = event.target.closest?.('.copy-req');
    if (!b) return;
    try { await navigator.clipboard.writeText(b.dataset.copy); b.textContent = 'Copied'; } catch (_) { b.textContent = 'Select and copy the sentence above'; }
    window.setTimeout(() => { b.textContent = 'Copy this request'; }, 2000);
  });
  window.addEventListener('hashchange', render);
  if (snapshot) { state = window.ORCH_SNAPSHOT || {}; render(); }
  else { refresh(); window.setInterval(refresh, 3000); }
})();
