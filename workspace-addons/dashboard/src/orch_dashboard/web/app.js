'use strict';
(() => {
  const snapshot = typeof window.ORCH_SNAPSHOT !== 'undefined';
  const main = document.getElementById('content');
  const nav = document.getElementById('side-nav');
  const array = value => Array.isArray(value) ? value : [];
  const clean = value => String(value ?? '').replace(/\b(?:ws|t|q|m|ph|wh|b|f)_[a-zA-Z0-9]{4,}\b/g, '').replace(/\s+·\s+·/g, ' · ').trim();
  const name = value => clean(String(value ?? '').replace(/^(human|agent):/, ''));
  const icon = value => {
    const svg = window.icon(String(value || 'page'));
    return /<(path|rect|circle|polyline|line|ellipse)\b/.test(svg) ? svg : window.icon('page');
  };
  function iconEl(name) {
    const node = document.createElement('span');
    node.className = 'ic-wrap';
    node.innerHTML = icon(name); // ic-wrap: only trusted kit icons use markup.
    return node;
  }
  function append(node, children) {
    for (const child of children.flat(Infinity)) {
      if (child == null || child === false) continue;
      node.appendChild(child instanceof Node ? child : document.createTextNode(String(child)));
    }
    return node;
  }
  function h(tag, attrs = {}, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs)) {
      if (value == null) continue;
      if (key === 'href' && !/^(#|https?:)/i.test(String(value))) continue;
      if (key.startsWith('data-')) node.dataset[key.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = String(value);
      else if (['className', 'hidden', 'disabled'].includes(key)) node[key] = value;
      else node.setAttribute(key, String(value));
    }
    return append(node, children);
  }
  const fragment = (...children) => append(document.createDocumentFragment(), children);
  const capitalise = value => String(value).replace(/^./, c => c.toUpperCase());
  const el = (tag, cls, text) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  };
  const button = (text, cls, click) => {
    const node = el('button', 'btn ' + cls, text);
    node.type = 'button';
    node.addEventListener('click', click);
    return node;
  };
  const parse = value => {
    if (!value) return null;
    const d = new Date(/^\d{4}-\d{2}-\d{2}$/.test(String(value)) ? value + 'T00:00:00' : value);
    return Number.isNaN(d.getTime()) ? null : d;
  };
  const date = value => parse(value)?.toLocaleDateString('en-GB', {weekday:'short', day:'numeric', month:'short'}) || '';
  const time = value => parse(value)?.toLocaleTimeString('en-GB', {hour:'2-digit', minute:'2-digit'}) || '';
  let state, renderedRoute = '', fetching = false, writing = 0, serial = 0, mutation = 0;
  const now = () => parse(state?.now) || new Date();
  const today = () => {
    const d = now();
    return [d.getFullYear(), String(d.getMonth() + 1).padStart(2, '0'), String(d.getDate()).padStart(2, '0')].join('-');
  };
  const age = value => {
    const d = parse(value);
    if (!d) return '';
    const mins = Math.max(0, Math.floor((now() - d) / 60000));
    return mins < 60 ? Math.max(1, mins) + ' min' : mins < 1440 ? Math.floor(mins / 60) + ' h' : Math.floor(mins / 1440) + (mins < 2880 ? ' day' : ' days');
  };
  const tickets = () => array(state?.tickets);
  const addons = () => array(state?.addons);
  const ticketOf = id => tickets().find(t => String(t.id) === String(id));
  const href = id => '#ticket/' + encodeURIComponent(id);
  const questions = t => array(t.questions).filter(q => q.answer == null);
  const activeTicket = t => !['done', 'dropped'].includes(t.status);
  const overdue = t => activeTicket(t) && t.due && t.due < today();
  const newer = (a, b) => (Date.parse(b.updated_at) || 0) - (Date.parse(a.updated_at) || 0);
  const sorted = list => list.slice().sort((a, b) => Number(!!overdue(b)) - Number(!!overdue(a)) || Number(questions(b).length > 0) - Number(questions(a).length > 0) || newer(a, b));
  const statusWord = t => questions(t).length ? 'Waiting for an answer' : ({active:'Doing', waiting:'Waiting', open:'Open', done:'Done', dropped:'Dropped'}[t.status] || 'Open');
  const chip = (text, cls = '') => h('span', {className:'chip ' + cls}, text);
  // Only waiting for the person's answer is "Waiting for you", not a fault; "Blocked" is a ticket waiting on something else.
  const statusChip = t => {
    if (!activeTicket(t)) return chip(statusWord(t));
    if (questions(t).length) return chip('Waiting for you', 'attn');
    return t.status === 'waiting' ? chip('Blocked', 'attn') : chip(statusWord(t), t.status === 'active' ? 'active' : '');
  };
  const heading = (title, sub = '') => h('header', {className:'page-heading', 'data-key':'heading'}, h('h1', {}, clean(title)), sub ? h('p', {className:'muted'}, sub) : null);
  const card = (key, title, suffix, body, chevron = false) => h('section', {className:'card', 'data-key':key, id:key === 'needs-you' ? key : null}, h('div', {className:'card-h'}, chevron ? iconEl('down') : null, h('h2', {}, title, suffix ? h('span', {className:'muted'}, ' · ', suffix) : null)), body);
  const emptyRow = text => h('div', {className:'card-row muted'}, text);
  const newButton = () => snapshot ? null : h('button', {type:'button', className:'btn primary sm', 'data-action':'new'}, 'New ticket');
  const firstTicket = () => h('div', {className:'card-row'}, h('p', {className:'grow muted'}, 'Your first ticket starts here.'), newButton());
  function ticketRow(t) {
    const meta = [name(t.owner), t.due ? 'Due ' + date(t.due) : '', statusWord(t)].filter(Boolean);
    const parent = ticketOf(t.parent);
    let late = '';
    if (overdue(t)) {
      const days = Math.round((Date.parse(today()) - Date.parse(t.due)) / 86400000);
      late = chip('Overdue ' + days + (days === 1 ? ' day' : ' days'), 'error');
    }
    return h('div', {className:'card-row ticket-row', 'data-key':'ticket-' + t.id}, h('div', {className:'grow'}, h('h3', {}, h('a', {href:href(t.id)}, clean(t.title))), h('p', {className:'meta'}, meta.join(' · ')), parent ? h('p', {className:'meta'}, 'Part of ', clean(parent.title)) : null), h('div', {className:'row'}, late, statusChip(t)));
  }
  function needRow(row, newest) {
    const t = ticketOf(row.ticket);
    const claim = state.runs?.[row.ticket]?.claim;
    const by = name(row.agent || row.by || claim?.agent || claim?.by);
    const meta = [typeof t?.key === 'string' ? clean(t.key) : '', by, t && clean(t.title)].filter(Boolean).join(' · ');
    const choice = window.DashHelpers.needAction(row);
    const action = snapshot
      ? (t ? h('a', {className:'btn outline sm', href:href(t.id)}, 'Open') : null)
      : h('button', {type:'button', className:'btn outline sm', 'data-action':'need', 'data-need':row.id}, choice.label);
    return h('div', {className:'card-row', 'data-key':'need-' + row.id, 'data-need-row':row.id, 'data-newest':row.id === newest ? '' : null}, h('span', {className:'need-icon ' + (row.tone === 'bad' ? 'bad' : row.tone === 'warn' ? 'warn' : 'muted')}, iconEl(row.tone === 'bad' ? 'stop' : row.tone === 'warn' ? 'shield' : 'note')), h('div', {className:'grow'}, h('h3', {}, clean(row.text)), h('p', {className:'meta'}, meta)), h('time', {datetime:row.since || ''}, age(row.since)), action);
  }
  function home() {
    const needs = array(state.needs);
    const rows = window.DashHelpers.agentRows(state.tickets, state.runs, Date.now());
    const working = rows.filter(row => ['working', 'needs', 'stuck'].includes(row.state));
    const current = sorted(tickets().filter(activeTicket));
    const oldest = needs.map(n => parse(n.since)).filter(Boolean).sort((a, b) => a - b)[0];
    const newest = needs.slice().sort((a, b) => (Date.parse(b.since) || 0) - (Date.parse(a.since) || 0))[0]?.id;
    const history = tickets().flatMap(t => array(t.history).map(entry => ({entry, title:t.title}))).sort((a, b) => (Date.parse(b.entry.at) || 0) - (Date.parse(a.entry.at) || 0)).slice(0, 5);
    const stopped = array(state.services).some(s => s.running === false);
    const banner = stopped ? h('div', {className:'banner attn', 'data-key':'background'}, h('p', {className:'grow'}, 'Background work is not running. Start it so repeating work and checks can run.'), snapshot ? null : h('button', {type:'button', className:'btn outline sm', 'data-action':'start'}, 'Start')) : null;
    const agents = rows.slice(0, 5).map(row => h('div', {className:'card-row', 'data-key':'agent-' + row.agent + '-' + row.ticket}, h('span', {className:'dot ' + (row.state === 'stuck' ? 'needs' : row.state)}), h('div', {className:'grow'}, h('h3', {}, capitalise(name(row.agent) || 'Agent') + ' · ' + ({working:'working', needs:'needs you', stuck:'may be stuck', idle:'idle'}[row.state])), h('p', {className:'meta'}, row.state === 'idle' ? 'Last worked ' + age(row.since) + ' ago' : [clean(ticketOf(row.ticket)?.title), age(row.since)].filter(Boolean).join(' · ')))));
    const links = pageLinks();
    const recent = history.map(({entry, title}) => {
      const line = clean(window.DashHelpers.historyLine(entry));
      return h('div', {className:'card-row'}, h('div', {className:'grow'}, h('h3', {}, line.length > 80 ? line.slice(0, 79) + '…' : line), h('p', {className:'meta'}, [name(entry.by), clean(title), age(entry.at)].filter(Boolean).join(' · '))));
    });
    return fragment(heading('Today', now().toLocaleDateString('en-GB', {weekday:'long', day:'numeric', month:'long'}) + ' · ' + needs.length + ' need you · ' + working.length + (working.length === 1 ? ' agent working' : ' agents working')), banner,
      h('div', {className:'columns', 'data-key':'columns'}, h('div', {className:'stack', 'data-key':'left'},
        card('needs-you', 'Needs you', needs.length + (oldest ? ' · oldest ' + age(oldest) : ''), needs.length ? needs.map(n => needRow(n, newest)) : emptyRow('Nothing needs you right now.'), true),
        card('your-tickets', 'Your tickets', current.length + ' · ' + current.filter(overdue).length + ' overdue', current.length ? current.map(ticketRow) : firstTicket(), true)),
      h('aside', {className:'stack', 'data-key':'right'},
        card('agents', 'Agents', working.length + ' working', [agents.length ? agents : emptyRow('No agent is working right now.'), links.length ? h('div', {className:'card-row'}, links.map(link => h('a', {className:'meta', href:link.url}, 'Open ' + capitalise(link.label) + ' →'))) : null]),
        card('recently', 'Recently', '', recent.length ? recent : emptyRow('No recent activity.')))));
  }
  const expanded = new Set();
  const treeExpanded = new Set(), treeSeen = new Set(), treeAll = new Set(), ticketTabs = new Map();
  function treeBranch(rows, index) {
    const row = rows[index], t = row.ticket;
    if (!treeSeen.has(t.id)) { treeSeen.add(t.id); treeExpanded.add(t.id); }
    const open = treeExpanded.has(t.id);
    const children = [];
    for (let i = index + 1; i < rows.length && rows[i].depth > row.depth; i++) {
      if (rows[i].depth === row.depth + 1) children.push(i);
    }
    const late = children.filter(i => rows[i].late);
    return fragment(h('div', {className:'card-row ticket-row' + (row.depth ? ' child' : ''), 'data-key':'tree-' + t.id},
      row.children ? h('button', {type:'button', className:'btn ghost icon sm', 'data-action':'tree', 'data-ticket':t.id, 'aria-expanded':open, 'aria-label':(open ? 'Collapse ' : 'Expand ') + clean(t.title)}, h('span', {className:'chevron ' + (open ? '' : 'closed')}, iconEl('down'))) : null,
      h('div', {className:'grow'}, h('h3', {}, h('a', {href:href(t.id)}, clean(t.title))), h('p', {className:'meta'}, [name(t.owner), t.due ? 'Due ' + date(t.due) : '', row.children ? row.done + ' of ' + row.children + ' done' : ''].filter(Boolean).join(' · ')),
        !row.depth && row.parentMissing ? h('p', {className:'meta'}, 'Part of a ticket that is not here') : null), statusChip(t)),
      open ? children.filter(i => !rows[i].late || treeAll.has(t.id)).map(i => treeBranch(rows, i)) : null,
      open && late.length && !treeAll.has(t.id) ? h('div', {className:'card-row child', 'data-key':'tree-all-' + t.id}, h('button', {type:'button', className:'btn ghost sm', 'data-action':'tree-all', 'data-ticket':t.id}, 'Show all ' + children.length)) : null);
  }
  function list() {
    const rows = window.DashHelpers.treeRows(tickets());
    return fragment(heading('Tickets'), !tickets().length ? card('empty', 'Tickets', '', firstTicket()) : ['active', 'waiting', 'open', 'done', 'dropped'].map(status => {
      const group = rows.map((row, i) => ({row, i})).filter(({row}) => row.depth === 0 && row.ticket.status === status);
      if (!group.length) return null;
      const title = {active:'Doing', waiting:'Waiting', open:'Open', done:'Done', dropped:'Dropped'}[status];
      const body = group.map(({i}) => treeBranch(rows, i));
      if (!['done', 'dropped'].includes(status)) return card('group-' + status, title, group.length, body);
      const open = expanded.has(status);
      return h('section', {className:'card', 'data-key':'group-' + status}, h('button', {type:'button', className:'card-h card-toggle', 'data-action':'group', 'data-group':status, 'aria-expanded':open, 'aria-controls':'group-' + status}, h('span', {className:'chevron ' + (open ? '' : 'closed')}, iconEl('down')), h('span', {}, title + ' · ' + group.length)), h('div', {id:'group-' + status, hidden:!open}, body));
    }));
  }
  function localUrl(value) {
    if (typeof value !== 'string' || !/^http:\/\/(127\.0\.0\.1|localhost):\d{1,5}\/?$/.test(value)) return null;
    try { return new URL(value).href; } catch (_) { return null; }
  }
  // An add-on that declares a [page] opens inside this app at #open/<add-on>/<path>; the server shows it under /addon/<add-on>/.
  const pageHash = (addon, path) => '#open/' + encodeURIComponent(addon) + '/' + String(path).replace(/^\/+/, '');
  function pageLinks() {
    return addons().filter(a => a.page && array(state.services).some(s => s.addon === a.name && s.running === true))
      .map(a => ({label:addonLabel(a), url:pageHash(a.name, a.page.path)}));
  }
  function addonUrl(addon) {
    return array(state.services).filter(s => s.addon === addon && s.running === true).map(s => localUrl(s.url)).find(Boolean) || null;
  }
  function addonLink(addon, path, label, startLabel = addon) {
    if (!/^[a-z][a-z0-9-]{1,31}$/.test(addon) || typeof path !== 'string' || !/^[A-Za-z0-9_./-]*$/.test(path) || path.includes('..')) return null;
    const base = addonUrl(addon);
    return base ? h('a', {className:'chip outline', href: pageHash(addon, path)}, label)
      : snapshot ? null : h('button', {type:'button', className:'btn outline sm', 'data-action':'start'}, 'Start ' + startLabel);
  }
  function ticketLinks(t) {
    const links = array(t.links).map(link => {
      const url = link.url;
      if (typeof url !== 'string') return null;
      const addon = /^addon:([a-z][a-z0-9-]{1,31})\/([A-Za-z0-9_./-]*)$/.exec(url);
      if (addon) return addonLink(addon[1], addon[2], clean(link.title) || addon[1]);
      if (/^t_[A-Za-z0-9]+$/.test(url)) {
        const target = ticketOf(url);
        return target ? h('a', {className:'chip outline', href:href(url)}, clean(target.title)) : null;
      }
      if (!/^https:\/\/[^\s<>"'`]+$/.test(url)) return null;
      try { const parsed = new URL(url); return h('a', {className:'chip outline', href:parsed.href, target:'_blank', rel:'noopener noreferrer'}, clean(link.title) || parsed.host); } catch (_) { return null; }
    }).filter(Boolean);
    return links.length ? h('div', {className:'chips', 'data-key':'ticket-links'}, links) : null;
  }
  function addonValue(row, value) {
    if (value == null || value === '' || (Array.isArray(value) && !value.length)) return '';
    if (row.format === 'time') return [date(value), time(value)].filter(Boolean).join(' ');
    if (row.format === 'cron-human') return String(value);
    if (row.format === 'yes-no') return value === true ? 'Yes' : value === false ? 'No' : '';
    if (row.format === 'chips') return h('div', {className:'chips'}, array(value).map(v => chip(clean(v))));
    return typeof value === 'object' ? '' : clean(value);
  }
  function addonRows(ticket) {
    const rows = addons().flatMap(a => array(a.ticket_view).map(r => [r, (ticket.ext || {})[a.name], a.name]))
      .map(([r, ext, addon]) => [r, ext && typeof ext === 'object' ? (r.format === 'open-page' ? addonLink(addon, ext[r.field], r.label, r.label) : addonValue(r, ext[r.field])) : '']).filter(([, v]) => v);
    return rows.length ? h('dl', {className:'addon-rows'}, rows.map(([r, v]) => [h('dt', {}, r.label), h('dd', {}, v)])) : null;
  }
  function liveLinkFor(t) {
    const a = addons().find(a => a.page && array(state.services).some(s => s.addon === a.name && s.running === true));
    if (!a) return null;
    const own = (t.ext || {})[a.name]?.page;
    return {label:addonLabel(a), url:pageHash(a.name, typeof own === 'string' && /^[A-Za-z0-9_./-]+$/.test(own) && !own.includes('..') ? own : a.page.path)};
  }
  function agentBar(t) {
    const line = window.DashHelpers.agentLine(t, state.runs?.[t.id], Date.now(), liveLinkFor(t));
    const action = (item, primary) => {
      const attrs = {className:primary ? 'btn sm ' + (line.state === 'working' ? 'outline' : 'primary') : 'menu-item', role:primary ? null : 'menuitem', 'data-key':primary ? 'agent-primary' : 'agent-' + item.label};
      if (item.op === 'open') return /^#open\//.test(item.url) ? h('a', {...attrs, href:item.url}, item.label) : null;
      return h('button', {...attrs, type:'button', 'data-action':'agent', 'data-op':item.op, 'data-args':JSON.stringify(item.args || {}), 'data-ticket':t.id}, item.label);
    };
    return h('div', {className:'agent-bar', 'data-state':line.state, 'data-key':'agent-bar'}, h('span', {className:'dot ' + ({working:'working', needs:'needs', stuck:'needs', failed:'error'}[line.state] || 'idle')}),
      h('span', {className:'ab-text grow'}, h('strong', {}, name(line.agent)), h('span', {className:'muted'}, ' · ' + clean(line.status))),
      h('span', {className:'ab-actions'}, action(line.primary, true), line.items.length ? h('details', {className:'menu', 'data-key':'agent-menu'}, h('summary', {className:'btn ghost icon sm', 'aria-label':'More agent actions'}, iconEl('more')), h('div', {className:'menu-pop', role:'menu'}, line.items.map(item => action(item, false)))) : null));
  }
  const surface = via => clean(via === 'cli' ? 'terminal' : via);
  function proofChip(ev) {
    const kind = ev.type || ev.kind;
    let label = ev.title || ev.text || String(ev.ref || '').split(/[\\/]/).pop() || 'Proof';
    if (kind === 'pr') {
      const number = ev.number || /(?:pull\/|#|^)(\d+)\b/.exec(String(ev.ref || ev.text || ''))?.[1];
      label = number ? 'PR #' + number : 'PR';
    } else if (kind === 'commit') label = 'Code updated';
    else if (kind === 'command') {
      const passed = /(\d+) passed/.exec([ev.text, ev.summary, ev.ref].filter(Boolean).join(' '));
      if (passed) label = passed[1] + ' checks OK';
    }
    if (kind === 'note') label = ev.text || ev.title || ev.summary || ev.ref || 'Note';
    label = clean(label);
    if (kind === 'note' && label.length > 100) label = label.slice(0, 99) + '…';
    const mark = window.DashHelpers.proofMark(ev);
    return h('span', {className:'chip proof-chip'}, h('small', {className:'muted'}, mark.mark + ' ' + mark.label), ' ', label, ev.missing === true ? ' · on another computer' : null);
  }
  function taskRows(t) {
    return array(t.checklist).map((task, i) => {
      const meta = [name(task.owner || task.by), clean(task.summary)].filter(Boolean).join(' · ');
      return h('div', {className:'card-row', 'data-key':'task-' + (task.id || i)}, task.done ? h('span', {className:'good'}, iconEl('check')) : h('span', {className:'dot idle'}),
        h('div', {className:'grow'}, h('h3', {}, clean(task.text)), meta ? h('p', {className:'meta'}, meta) : null,
          array(task.evidence).length ? h('div', {className:'chips task-proofs'}, array(task.evidence).map(proofChip)) : null), chip(task.done ? 'Done' : 'To do', task.done ? 'success' : ''));
    });
  }
  function selectTicketTab(id, tab, focusQuestion = false) {
    ticketTabs.set(id, tab);
    render();
    if (focusQuestion) {
      const host = main.querySelector('[data-question]');
      if (host) { host.setAttribute('tabindex', '-1'); (host.querySelector('button,input,textarea') || host).focus(); }
    }
  }
  function detail(t) {
    if (!t) return fragment(heading('Ticket not found'), h('a', {href:'#tickets'}, 'All tickets'));
    const qs = questions(t).map(q => snapshot
      ? card('question-' + q.id, clean(q.text), '', h('div', {className:'card-row'}, h('div', {className:'grow'}, h('p', {className:'muted'}, 'Waiting for an answer'), h('div', {className:'row'}, array(q.options).map(o => chip(clean(o), o === q.recommended ? 'attn' : ''))))))
      : h('div', {'data-key':'question-' + q.id, 'data-question':q.id, 'data-ticket':t.id}));
    const history = array(t.history).slice().sort((a, b) => (Date.parse(b.at) || 0) - (Date.parse(a.at) || 0)).map(entry => h('div', {className:'card-row'}, h('p', {className:'grow'}, [clean(window.DashHelpers.historyLine(entry)), name(entry.by), surface(entry.via)].filter(Boolean).join(' · ')), h('time', {datetime:entry.at || ''}, age(entry.at))));
    const field = (label, value, cls = '') => h('div', {}, h('dt', {}, label), h('dd', {className:cls}, value));
    const total = array(t.checklist).length, done = array(t.checklist).filter(task => task.done).length;
    const tasksCard = key => card(key, total && done === total ? 'All done' : 'Tasks', done + ' of ' + total + (total && done === total ? '' : ' done'), total ? taskRows(t) : emptyRow('No tasks yet.'));
    const parent = ticketOf(t.parent), children = tickets().filter(child => child.parent === t.id);
    const selected = ticketTabs.get(t.id) || 'overview';
    const tabs = [['overview', 'Overview'], ['tasks', 'Tasks ' + done + '/' + total], ['questions', 'Questions' + (qs.length ? ' (' + qs.length + ')' : '')], ['history', 'History']];
    const panel = (id, body) => h('section', {id:'ticket-panel-' + id, role:snapshot ? null : 'tabpanel', 'aria-labelledby':snapshot ? null : 'ticket-tab-' + id, className:'stack', hidden:!snapshot && selected !== id, tabindex:'0'}, snapshot ? h('h2', {}, capitalise(id)) : null, body);
    const sessions = array(t.sessions).slice().sort((a, b) => (Date.parse(b.last_used) || 0) - (Date.parse(a.last_used) || 0));
    const agent = sessions.length ? capitalise(name(sessions[0].agent) || 'Agent') + ' · continues its session' : capitalise(name(state.runs?.[t.id]?.claim?.agent)) || 'Not chosen yet';
    const answered = array(t.questions).filter(q => q.answer != null).map(q => {
      const answer = window.DashHelpers.winningAnswer(tickets(), t.id, q.id);
      return h('div', {className:'card-row', 'data-key':'answered-' + q.id}, h('div', {className:'grow'}, h('h3', {}, clean(q.text)), h('p', {className:'meta preserve-lines'}, ['Answered', name(answer?.who), surface(answer?.via)].filter(Boolean).join(' · ') + ': ' + clean(answer?.text))));
    });
    return fragment(h('header', {className:'stack', 'data-key':'ticket-heading'},
      parent ? h('a', {href:href(parent.id), className:'muted'}, 'Part of ' + clean(parent.title)) : null,
      h('div', {className:'row'}, typeof t.key === 'string' ? h('span', {className:'mono'}, t.key) : null, chip('Ticket', 'outline'), statusChip(t)),
      h('div', {className:'row', 'data-key':'ticket-meta'}, h('h1', {className:'grow'}, inlineField(t, 'title')), snapshot ? null : agentBar(t)),
      h('div', {className:'columns ticket-columns', 'data-key':'ticket-columns'}, h('div', {className:'stack'},
        snapshot ? null : h('div', {className:'tabs', role:'tablist', 'aria-label':'Ticket'}, tabs.map(([id, label]) => h('button', {type:'button', id:'ticket-tab-' + id, role:'tab', 'aria-selected':selected === id, 'aria-controls':'ticket-panel-' + id, tabindex:selected === id ? '0' : '-1', 'data-action':'ticket-tab', 'data-tab':id, 'data-ticket':t.id}, label))),
        panel('overview', [t.summary ? h('p', {className:'muted preserve-lines', 'data-key':'summary'}, clean(t.summary)) : null,
          qs.length ? h('div', {className:'banner attn'}, h('p', {className:'grow'}, qs.length + (qs.length === 1 ? ' question needs you' : ' questions need you')), snapshot ? null : h('button', {type:'button', className:'btn outline sm', 'data-action':'answer-tab', 'data-ticket':t.id}, 'Answer')) : null,
          tasksCard('overview-tasks'), addonRows(t), ticketLinks(t), children.length ? card('sub-tickets', 'Sub-tickets', children.filter(child => child.status === 'done').length + ' of ' + children.length + ' done', children.map(child => h('div', {className:'card-row'}, h('a', {className:'grow', href:href(child.id)}, clean(child.title)), statusChip(child)))) : null]),
        panel('tasks', tasksCard('tasks')), panel('questions', [qs.length ? qs : emptyRow('No open questions'), answered]),
        panel('history', card('history', 'History', '', history.length ? history : emptyRow('No history yet.')))),
      h('aside', {className:'card ticket-aside'}, h('div', {className:'card-h'}, h('h2', {}, 'Details')),
        h('dl', {className:'ticket-details'}, field('Owner', inlineField(t, 'owner')), field('Due', inlineField(t, 'due')), field('Note', inlineField(t, 'note')), field('Agent', agent), field('Created', date(t.created_at)), field('Updated', age(t.updated_at)), field('Ticket', t.id, 'mono'))))));
  }

  const FIELD_HINT = {title:'Untitled', owner:'Not chosen yet', due:'Not set', note:'Add a note'};
  // A value on the ticket page: a plain click turns it into a field; Enter or leaving it saves, Esc cancels.
  function inlineField(t, field) {
    const raw = t[field] == null ? '' : String(t[field]);
    const shown = field === 'due' ? date(raw) : field === 'owner' ? name(raw) : clean(raw);
    if (snapshot) return el('span', field === 'note' ? 'preserve-lines' : '', shown || (field === 'title' ? '' : FIELD_HINT[field]));
    const host = el('span', 'inline-host');
    host.dataset.key = 'inline-' + field + '-' + t.id;
    const node = el('button', 'inline-edit' + (shown ? '' : ' empty') + (field === 'note' ? ' preserve-lines' : ''), shown || FIELD_HINT[field]);
    Object.assign(node, {type:'button', title:'Click to change'});
    Object.assign(node.dataset, {action:'inline', field, ticket:t.id});
    host.append(node);
    return host;
  }
  function startInline(control) {
    const t = ticketOf(control.dataset.ticket), field = control.dataset.field, host = control.parentElement;
    if (!t || !host || locks.has(host.dataset.key)) return;
    const key = host.dataset.key;
    const input = el(field === 'note' ? 'textarea' : 'input', 'input inline-input');
    if (field === 'note') input.rows = 3; else input.type = field === 'due' ? 'date' : 'text';
    if (field === 'title') input.maxLength = 200;
    const before = field === 'owner' ? name(t.owner) : t[field] == null ? '' : String(t[field]);
    input.value = before;
    input.setAttribute('aria-label', capitalise(field));
    locks.add(key);
    host.replaceChildren(input);
    input.focus();
    let done = false;
    const finish = async save => {
      if (done) return;
      done = true;
      const value = input.value.trim();
      if (save && value !== before && !(field === 'title' && !value)) {
        const result = await act('ticket.edit', {ticket:t.id, [field]:value, if_revision:t.revision});
        if (!result.ok) window.orch.toast(result.text + (result.status === 409 ? ' Reload the page and try again.' : ''), 'error');
      }
      locks.delete(key);
      render();
    };
    input.addEventListener('keydown', event => {
      if (event.key === 'Enter' && !(field === 'note' && event.shiftKey)) { event.preventDefault(); finish(true); }
      else if (event.key === 'Escape') { event.preventDefault(); finish(false); }
    });
    input.addEventListener('blur', () => finish(true));
  }

  let settingsTab = 'general';
  const settingsBusy = new Set();
  const settingsText = (tag, attrs, value) => {
    const node = h(tag, attrs);
    node.textContent = String(value ?? '');
    return node;
  };
  function addonDetail(addon) {
    const d = addon.detail;
    if (addon.name === 'dashboard') return 'This page';
    if (!addon.active) return addon.description;
    if (!d) return addon.description;
    if (!d.connected) return 'Not connected yet';
    const list = array(d.workspaces);
    return 'Connected to ' + d.address + (list.length ? ' · can talk to ' + list.length + (list.length === 1 ? ' workspace: ' : ' workspaces: ') + list.map(w => w.name).join(', ') : '');
  }
  function settingsPage() {
    const settings = state.settings;
    const agents = array(settings.agents).map(agent => {
      const radio = h('input', {type:'radio', name:'settings-agent', value:agent.name, 'data-key':'settings-agent-' + agent.name, 'data-settings-agent':agent.name, disabled:settingsBusy.has('agent')});
      radio.checked = !!agent.chosen;
      const status = agent.status === 'your command' ? 'Your own agent' : agent.found ? 'Found' + (agent.version ? ' · version ' + agent.version : '') : 'Not found on this computer';
      return h('label', {className:'card-row agent-opt' + (agent.chosen ? ' sel' : ''), 'data-key':'settings-agent-row-' + agent.name}, radio,
        h('div', {className:'grow'}, settingsText('h3', {}, agent.label), settingsText('p', {className:'meta'}, status)),
        agent.chosen ? h('span', {className:'chip active def'}, 'Default') : null);
    });
    const panel = (id, body) => h('section', {className:'set-sec', id:'settings-panel-' + id, 'data-key':'settings-panel-' + id, role:'tabpanel', 'aria-labelledby':'settings-tab-' + id, hidden:settingsTab !== id, tabindex:'0'}, body);
    return h('div', {className:'settings stack'}, heading('Settings'),
      h('div', {className:'tabs', role:'tablist', 'aria-label':'Settings'}, [['general', 'General'], ['agent', 'Agent'], ['addons', 'Add-ons']].map(([id, label]) => h('button', {type:'button', id:'settings-tab-' + id, role:'tab', 'aria-selected':settingsTab === id, 'aria-controls':'settings-panel-' + id, tabindex:settingsTab === id ? '0' : '-1', 'data-action':'settings-tab', 'data-tab':id}, label))),
      panel('general', h('div', {className:'card'},
        h('div', {className:'card-row name-row'}, h('span', {className:'set-label'}, 'Name'), settingsText('p', {className:'grow set-ctl'}, state.workspace)),
        h('div', {className:'card-row'}, h('span', {className:'set-label'}, 'Folder'), settingsText('p', {className:'grow set-ctl mono'}, settings.folder)))),
      panel('agent', [h('p', {className:'meta'}, 'The default agent works on new tickets. A ticket keeps its own agent session.'), h('div', {className:'card'}, h('div', {role:'radiogroup', 'aria-label':'Default agent'}, agents)),
        snapshot ? null : h('div', {}, h('button', {type:'button', className:'btn outline sm', 'data-key':'settings-add-agent', 'data-action':'agent-add'}, 'Add your own agent'))]),
      panel('addons', h('div', {className:'card'}, array(settings.addons).map(addon => h('div', {className:'card-row addon-row', 'data-key':'settings-addon-' + addon.name},
        h('div', {className:'grow'}, settingsText('h3', {}, capitalise(addon.name)), settingsText('p', {className:'meta'}, addonDetail(addon))),
        addon.name === 'dashboard' ? null : h('button', {type:'button', className:'switch', role:'switch', 'aria-checked':!!addon.active, 'aria-label':addon.name + ' on or off', 'data-key':'settings-switch-' + addon.name, 'data-action':'settings-addon', 'data-name':addon.name, disabled:settingsBusy.has('addon-' + addon.name)}))))));
  }
  // A small form for an agent that is started with a command. Save shows the command once more before adding it.
  function openAgentForm() {
    const {d, actions} = dialog('Add your own agent', 'dialog', 'settings-other');
    const input = (tag, attrs = {}) => Object.assign(el(tag, 'input'), attrs);
    const nameIn = input('input', {type:'text', placeholder:'my-agent', maxLength:32});
    const cmdIn = input('input', {type:'text', placeholder:'mytool --yes {prompt}'});
    const via = input('select');
    via.append(new Option('As an argument', 'arg'), new Option('On stdin', 'stdin'));
    const use = Object.assign(el('input'), {type:'checkbox', checked:true});
    const err = el('p', 'bad'); err.setAttribute('role', 'alert');
    const row = (label, control, hint) => { const l = el('label', 'stack', label); l.append(control); if (hint) l.append(el('span', 'meta', hint)); return l; };
    const form = el('div', 'other-cmd');
    form.append(row('Name', nameIn), row('Command', cmdIn, '{prompt} is replaced with the ticket and its tasks.'), row('The task goes in', via), row('', use), err);
    use.parentElement.append(' Use it as the default agent');
    const save = button('Save', 'primary', async () => {
      const draft = {name:nameIn.value.trim(), command:cmdIn.value, prompt_via:via.value, use:use.checked};
      err.textContent = !/^[a-z][a-z0-9-]{1,31}$/.test(draft.name) ? 'Use 2–32 characters: start with a lowercase letter, then use lowercase letters, numbers or hyphens.'
        : !draft.command.trim() || /[\r\n\u2028\u2029]/.test(draft.command) || Array.from(draft.command).length > 500 ? 'Enter a command on one line, up to 500 characters.' : '';
      if (err.textContent) return;
      await window.orch.close(d);
      settingsConfirm('Add ' + draft.name + '?', draft.command, 'mono preserve-lines', 'Yes, add it', async () => {
        const args = {name:draft.name, command:draft.command};
        if (draft.prompt_via === 'stdin') args.prompt_via = 'stdin';
        const result = await settingsSend('config.agent.add', args, 'add');
        if (!result.ok) return;
        if (draft.use) await settingsSend('config.agent', {name:draft.name}, 'agent');
        window.orch.toast(draft.name + ' added.', 'ok');
      });
    });
    d.append(form, actions);
    actions.append(save);
    window.orch.open(d);
    nameIn.focus();
  }
  function settingsConfirm(title, text, cls, label, send) {
    const {d, actions} = dialog(title, 'dialog', 'settings-other');
    d.querySelector('h2').textContent = title;
    const confirm = h('button', {type:'button', className:'btn primary'}, label);
    let pending = false;
    d.addEventListener('cancel', event => { if (pending) event.preventDefault(); });
    confirm.addEventListener('click', async () => {
      if (pending) return;
      pending = true;
      actions.querySelectorAll('button').forEach(control => { control.disabled = true; });
      await send();
      await window.orch.close(d);
    });
    actions.append(confirm);
    d.append(settingsText('pre', {className:cls}, text), actions);
    window.orch.open(d);
  }
  async function settingsSend(op, args, key) {
    settingsBusy.add(key);
    render();
    const result = await act(op, args);
    settingsBusy.delete(key);
    if (!result.ok) window.orch.toast(result.text, 'error');
    render();
    return result;
  }

  // Reconcile matching DOM nodes so polling cannot replace a focused control or a draft.
  const locks = new Set();
  const mounts = new Map();
  const nodeKey = node => node?.nodeType === 1 ? node.dataset.key || node.id || (node.dataset.action ? [node.dataset.action, node.dataset.need, node.dataset.ticket, node.dataset.group].join(':') : '') || (node.tagName === 'A' ? node.getAttribute('href') : '') : '';
  function sync(target, source) {
    if (target.nodeType === 3) { if (target.data !== source.data) target.data = source.data; return; }
    if (target.nodeType !== 1) return;
    if (locks.has(target.dataset.key) || mounts.has(target) || target.id === 'addon-body') return;
    for (const attr of [...target.attributes]) {
      if (attr.name === 'open' && target.tagName === 'DETAILS') continue;
      if (!source.hasAttribute(attr.name)) target.removeAttribute(attr.name);
    }
    for (const attr of [...source.attributes]) {
      if (target.getAttribute(attr.name) !== attr.value) target.setAttribute(attr.name, attr.value);
    }
    reconcile(target, source);
    if (target.matches('[data-settings-agent]')) target.checked = source.checked;
    if (target.matches('[data-settings-field]')) {
      if (target.type === 'checkbox') target.checked = source.checked;
      else if (target.value !== source.value) target.value = source.value;
    }
  }
  function reconcile(target, source) {
    const old = [...target.childNodes], used = new Set();
    for (const fresh of [...source.childNodes]) {
      const key = nodeKey(fresh);
      const existing = old.find(n => !used.has(n) && n.nodeType === fresh.nodeType && n.nodeName === fresh.nodeName && (key ? nodeKey(n) === key : !nodeKey(n)));
      const node = existing || fresh;
      const at = target.childNodes[used.size];
      if (node !== at) target.insertBefore(node, at || null);
      if (existing) sync(existing, fresh);
      used.add(node);
    }
    for (const node of old) if (!used.has(node) && !locks.has(node.dataset?.key)) node.remove();
  }
  const seenNeeds = new Set();
  function accept(next) {
    const first = !state;
    const arrived = new Set(array(next.needs).filter(n => !seenNeeds.has(n.id)).map(n => n.id));
    array(next.needs).forEach(n => seenNeeds.add(n.id));
    state = next;
    render(first ? new Set() : arrived);
  }
  function route() {
    const hash = location.hash || '#home';
    if (hash === '#settings' && !snapshot && state?.settings) return {kind:'settings', hash};
    try {
      if (hash.startsWith('#ticket/')) return {kind:'ticket', id:decodeURIComponent(hash.slice(8)), hash};
      const open = /^#open\/([a-z][a-z0-9-]{1,31})\/([A-Za-z0-9_./-]*)$/.exec(hash);
      if (open && !open[2].includes('..') && addons().some(a => a.name === open[1] && a.page)) return {kind:'page', id:open[1], path:open[2], hash};
      if (hash.startsWith('#addon/')) {
        const id = decodeURIComponent(hash.slice(7));
        if (addons().some(a => a.name === id && a.dashboard)) return {kind:'addon', id, hash};
      }
    } catch (_) { /* Malformed links fall back to Home. */ }
    return {kind:hash === '#tickets' ? 'tickets' : 'home', hash};
  }
  function render(arrived = new Set()) {
    if (!state) return;
    const r = route(), changed = !!renderedRoute && renderedRoute !== r.hash;
    const scroll = [window.scrollX, window.scrollY];
    const active = document.activeElement;
    const activeKey = nodeKey(active);
    const pageName = r.kind === 'settings' ? 'Settings' : (r.kind === 'addon' || r.kind === 'page') ? addonLabel(addons().find(a => a.name === r.id)) : r.kind === 'ticket' ? 'Ticket' : r.kind === 'tickets' ? 'Tickets' : 'Home';
    document.getElementById('workspace-name').textContent = clean(state.workspace || 'Workspace');
    document.getElementById('workspace-mode').textContent = snapshot ? 'Shared copy' : 'Local workspace';
    const crumb = document.getElementById('crumb');
    if (r.kind === 'ticket') {
      const tk = ticketOf(r.id);
      crumb.replaceChildren(h('a', {href:'#tickets'}, 'Tickets'), ' / ', typeof tk?.key === 'string' ? tk.key : clean(tk?.title) || 'Ticket');
    } else crumb.textContent = pageName;
    const navLink = (url, text, glyph, tail = null) => h('a', {className:'nav-item', href:url, 'aria-current':(r.kind === 'ticket' ? '#tickets' : r.kind === 'home' ? '#home' : r.kind === 'page' ? '#addon/' + encodeURIComponent(r.id) : r.hash) === url ? 'page' : null}, iconEl(glyph), text, tail);
    reconcile(nav, fragment(navLink('#home', 'Home', 'page', array(state.needs).length ? h('span', {className:'count'}, array(state.needs).length) : null), navLink('#tickets', 'Tickets', 'table'),
      !snapshot && state.settings ? navLink('#settings', 'Settings', 'user') : null,
      h('p', {className:'eyebrow'}, 'Add-ons'), addons().filter(a => a.dashboard).map(a => navLink('#addon/' + encodeURIComponent(a.name), addonLabel(a), a.dashboard.icon || a.icon))));
    if (changed) {
      for (const [host, mounted] of mounts) { if (main.contains(host)) { mounted.destroy(); mounts.delete(host); } }
      main.replaceChildren();
    }
    reconcile(main, r.kind === 'settings' ? settingsPage() : r.kind === 'home' ? home() : r.kind === 'tickets' ? list() : r.kind === 'ticket' ? detail(ticketOf(r.id)) : r.kind === 'page' ? pageFrame(r) : addonTab(r.id));
    for (const [host, mounted] of mounts) if (!host.isConnected) { mounted.destroy(); mounts.delete(host); }
    main.querySelectorAll('[data-question]').forEach(host => {
      if (!mounts.has(host)) {
        const t = ticketOf(host.dataset.ticket), q = array(t?.questions).find(q => q.id === host.dataset.question);
        if (q) mountQuestion(host, {ticket:t.id, id:q.id, title:q.text, text:'', options:array(q.options).map(o => ({text:o, suggested:o === q.recommended}))});
      }
    });
    if (r.kind === 'addon') {
      if (activeAddon !== r.id) startAddon(r.id);
      else if (!document.getElementById('addon-body').childNodes.length) paintAddon(r.id);
    } else {
      clearInterval(addonTimer); activeAddon = null;
    }
    if (!changed && renderedRoute === r.hash && r.kind === 'home') {
      main.querySelectorAll('[data-need-row]').forEach(row => { if (arrived.has(row.dataset.needRow)) window.orch.needsIn(row); });
    }
    if (changed) window.orch.enter(main);
    renderedRoute = r.hash;
    if (!active?.isConnected && activeKey && !document.querySelector('dialog[open]')) {
      [...document.querySelectorAll('a,button,summary')].find(n => nodeKey(n) === activeKey)?.focus({preventScroll:true});
    }
    window.scrollTo(...(changed ? [0, 0] : scroll));
  }

  const addonViews = Object.create(null), addonBusy = new Set();
  let addonTimer, activeAddon = null;
  const addonLabel = a => a?.dashboard?.label || a?.label || a?.name || 'Add-on';
  function pageFrame(r) {
    const src = '/addon/' + r.id + '/' + r.path;
    const frame = h('iframe', {className:'embed', 'data-key':'embed', src, title:addonLabel(addons().find(a => a.name === r.id)), allow:'fullscreen', allowfullscreen:''});
    return fragment(frame);
  }
  function addonTab(id) {
    return fragment(heading(addonLabel(addons().find(a => a.name === id))), h('div', {id:'addon-body', className:'stack', 'data-name':id}));
  }
  function addonBody(a, res) {
    if (!res) return fragment(h('div', {className:'skeleton addon-loading', role:'status', 'aria-label':'Loading'}));
    const retry = snapshot ? null : h('button', {type:'button', className:'btn outline sm', 'data-action':'retry-addon'}, 'Try again');
    if (res.state === 'error' || !res.view) return fragment(h('section', {className:'card pad stack'}, h('h2', {}, 'Can’t show ', addonLabel(a), ' right now.'), h('p', {}, res.message || 'No answer.', ' Nothing here was changed.'), retry));
    return fragment(h('p', {className:'meta'}, 'As of ', time(res.as_of)),
      res.state === 'stale' ? h('div', {className:'banner attn', role:'status'}, h('p', {className:'grow'}, 'Not up to date. Showing the last answer from ', time(res.as_of), '.'), retry) : null,
      res.view.notice ? h('p', {className:'banner ' + (res.view.notice_tone === 'bad' ? 'error' : ['warn', 'needs-you'].includes(res.view.notice_tone) ? 'attn' : '')}, clean(res.view.notice)) : null, h('div', {id:'addon-blocks'}));
  }
  function paintAddon(id) {
    const host = document.getElementById('addon-body'), a = addons().find(a => a.name === id);
    if (!host || host.dataset.name !== id || !a) return;
    const scroll = [window.scrollX, window.scrollY];
    const template = addonBody(a, addonViews[id]);
    const blocks = template.querySelector('#addon-blocks');
    if (blocks) {
      blocks.append(OrchBlocks.render(addonViews[id].view.blocks, {addonUrl, self:id}));
      if (!blocks.childNodes.length) blocks.append(h('section', {className:'card pad muted'}, 'Nothing to show yet.'));
      blocks.querySelectorAll('.blk').forEach(n => n.classList.add('card'));
      blocks.querySelectorAll('svg').forEach(n => {
        n.replaceWith(iconEl('external'));
      });
      // Block text is supplied by add-ons; keep internal keys out of visible copy.
      const walker = document.createTreeWalker(blocks, NodeFilter.SHOW_TEXT);
      while (walker.nextNode()) walker.currentNode.data = clean(walker.currentNode.data);
    }
    reconcile(host, template);
    host.querySelectorAll('[data-action="retry-addon"]').forEach(n => { n.disabled = false; });
    window.scrollTo(...scroll);
  }
  async function loadAddon(id, manual = false) {
    if (addonBusy.has(id)) return;
    addonBusy.add(id);
    const retry = main.querySelector('[data-action="retry-addon"]');
    if (manual && retry) { retry.disabled = true; retry.textContent = 'Trying…'; }
    try {
      if (snapshot) addonViews[id] = state.views?.[id] || {state:'error', message:'This shared copy has no view.'};
      else {
        const res = await fetch('/api/addon/' + encodeURIComponent(id), {cache:'no-store'});
        if (!res.ok) throw new Error('No answer.');
        addonViews[id] = await res.json();
      }
    } catch (_) {
      addonViews[id] = addonViews[id]?.view ? {...addonViews[id], state:'stale'} : {state:'error', message:'No answer.'};
    } finally { addonBusy.delete(id); }
    if (route().kind === 'addon' && route().id === id) paintAddon(id);
  }
  function startAddon(id) {
    clearInterval(addonTimer);
    activeAddon = id;
    paintAddon(id);
    loadAddon(id);
    if (!snapshot) addonTimer = setInterval(() => loadAddon(id), 15000);
  }

  async function act(op, args) {
    if (snapshot) return {ok:false, status:0, text:'This is a shared copy.'};
    writing++;
    mutation++;
    try {
      const res = await fetch('/api/act', {method:'POST', keepalive:true, headers:{'Content-Type':'application/json'}, body:JSON.stringify({op, args})});
      if (res.status !== 200) return {ok:false, status:res.status, text:await res.text()};
      const next = await res.json();
      accept(next);
      return {ok:true, status:200, state:next};
    } catch (err) { return {ok:false, status:0, text:err.message || 'Could not reach orch.'}; }
    finally { writing--; }
  }
  async function refresh() {
    if (snapshot || fetching || writing) return;
    fetching = true;
    const version = mutation;
    const connection = document.getElementById('connection');
    try {
      const res = await fetch('/api/state', {cache:'no-store'});
      if (!res.ok) throw new Error('Could not load the workspace.');
      const next = await res.json();
      if (writing || version !== mutation) return;
      connection.hidden = true;
      if (!state || next.rev !== state.rev) accept(next);
    } catch (_) {
      connection.textContent = state ? 'Can’t refresh right now. Showing the last update; trying again shortly.' : 'Can’t load your workspace right now. Trying again shortly.';
      connection.hidden = false;
    } finally { fetching = false; }
  }
  function dialog(title, cls = 'dialog', lock = '') {
    const d = el('dialog', cls);
    const id = 'dialog-title-' + (++serial);
    const h = el('h2', '', clean(title)); h.id = id;
    d.setAttribute('aria-labelledby', id); d.append(h);
    const trigger = document.activeElement;
    const triggerKey = nodeKey(trigger);
    const actions = el('div', 'actions');
    actions.append(button('Cancel', 'ghost', () => window.orch.close(d)));
    if (lock) locks.add(lock);
    d.addEventListener('close', () => {
      const resolving = d.dataset.resolving === 'true';
      if (lock && !resolving) locks.delete(lock);
      for (const [host, mounted] of mounts) if (d.contains(host)) { mounted.destroy(); mounts.delete(host); }
      d.remove();
      if (!resolving) render();
      if (trigger?.isConnected) trigger.focus({preventScroll:true});
      else if (triggerKey) [...document.querySelectorAll('a,button')].find(n => nodeKey(n) === triggerKey)?.focus({preventScroll:true});
    });
    document.body.append(d);
    return {d, actions};
  }
  // An answer still in its Undo window is sent at once when the page is left, so it is not lost.
  const sends = new WeakMap();
  function flushPending() {
    window.DashHelpers.flushPending([...mounts.values()].map(m => ({state:m.state, send:sends.get(m)})));
  }
  addEventListener('pagehide', flushPending);
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'hidden') flushPending(); });
  function mountQuestion(host, q, context = {}) {
    let sendAnswer;
    const mounted = window.QuestionCard.mount(host, {...q, title:clean(q.title), text:clean(q.text)}, {
      send: sendAnswer = async answer => {
        const lock = context.lock || host.dataset.key;
        if (lock) locks.add(lock);
        const result = await act('answer', {ticket:q.ticket, question:q.id, answer});
        if (!result.ok) {
          let fresh = result.state;
          try {
            if (!fresh) {
              const res = await fetch('/api/state', {cache:'no-store'});
              if (res.ok) fresh = await res.json();
            }
          } catch (_) { /* Keep the original send error if the refresh also fails. */ }
          const win = window.DashHelpers.winningAnswer(fresh?.tickets, q.ticket, q.id);
          // Keep the mounted card and any open dialog intact while accepting the refresh.
          if (fresh) { mutation++; accept(fresh); }
          if (lock && !context.dialog) locks.delete(lock);
          if (win !== null) return {status:409, other:{text:win.text, who:name(win.who), via:win.via}};
          return {status:0, message:result.text};
        }
        const answered = array(ticketOf(q.ticket)?.questions).find(x => x.id === q.id);
        const who = name(answered?.answered_by || result.state.who) || 'You';
        // Let the shared card finish its send transition before releasing its host.
        setTimeout(async () => {
          window.orch.toast('Answered · ' + who + ' · dashboard', 'ok');
          if (context.dialog) {
            context.dialog.dataset.resolving = 'true';
            await window.orch.close(context.dialog);
          }
          if (context.row?.isConnected) await window.orch.resolve(context.row);
          if (lock) locks.delete(lock);
          if (host.isConnected && mounts.has(host)) { mounts.get(host).destroy(); mounts.delete(host); }
          render();
          if (!document.querySelector('dialog[open]') && !document.activeElement?.closest('button,a,input,textarea')) {
            main.querySelector('h1')?.setAttribute('tabindex', '-1');
            main.querySelector('h1')?.focus({preventScroll:true});
          }
          refresh();
        }, 0);
        return {status:200, who, via:'dashboard'};
      }
    });
    // The shared component uses the real key for persistence; only its visible label changes.
    const label = host.querySelector('.qmeta .muted');
    if (label) label.textContent = clean(ticketOf(q.ticket)?.title) || 'Ticket';
    mounts.set(host, mounted);
    sends.set(mounted, sendAnswer);
  }
  async function openNeed(row, trigger) {
    if (!row) return;
    const action = window.DashHelpers.needAction(row);
    if (action.kind === 'run') {
      if (trigger.disabled) return;
      trigger.disabled = true;
      const result = await act('run.start', {ticket:row.ticket});
      trigger.disabled = false;
      window.orch.toast(result.ok ? 'Started again' : result.text, result.ok ? 'ok' : 'error');
      return;
    }
    if (action.kind === 'answer' || action.kind === 'review') {
      const {d, actions} = dialog(row.title, 'dialog', 'needs-you');
      const host = el('div');
      d.append(host, actions);
      mountQuestion(host, {ticket:row.ticket, id:row.answer.question, title:row.title, text:row.text, options:array(row.answer.options).map(o => ({text:o, suggested:o === row.answer.recommended}))}, {dialog:d, row:trigger.closest('[data-need-row]'), lock:'needs-you'});
      window.orch.open(d);
    } else if (row.ticket) location.hash = href(row.ticket);
    else {
      const a = addons().find(a => a.dashboard && (a.name === row.source || String(row.kind).startsWith(a.name + ':')));
      if (a) location.hash = '#addon/' + encodeURIComponent(a.name);
      else {
        const {d, actions} = dialog(row.title);
        d.append(el('p', 'preserve-lines', clean(row.text || 'No further details.')), actions);
        window.orch.open(d);
      }
    }
  }
  function ticketForm(t) {
    const {d, actions} = dialog(t ? 'Edit ticket' : 'New ticket', t ? 'sheet' : 'dialog', t ? 'ticket-meta' : '');
    const form = el('form'), fields = el('div', 'form-fields'), inputs = {};
    for (const field of (t ? ['owner', 'due', 'note'] : ['title', 'owner', 'due', 'note'])) {
      const label = el('label', '', field.charAt(0).toUpperCase() + field.slice(1) + (field === 'title' ? '' : ' (optional)'));
      const input = el(field === 'note' ? 'textarea' : 'input', 'input');
      input.name = field; input.id = 'field-' + serial + '-' + field;
      if (field !== 'note') input.type = field === 'due' ? 'date' : 'text';
      if (field === 'title') { input.required = true; input.maxLength = 200; }
      input.value = t?.[field] || '';
      label.htmlFor = input.id; label.append(input); fields.append(label); inputs[field] = input;
    }
    const error = el('p', 'bad'); error.setAttribute('role', 'alert');
    const reload = button('Reload ticket', 'outline sm', async () => { await refresh(); await window.orch.close(d); const latest = ticketOf(t?.id); if (latest) ticketForm(latest); });
    reload.hidden = true;
    const submit = el('button', 'btn primary', t ? 'Save changes' : 'Create ticket'); submit.type = 'submit';
    actions.append(submit);
    form.append(fields, error, reload, actions); d.append(form);
    let created = null, creationUnresolved = false;
    form.addEventListener('submit', async event => {
      event.preventDefault();
      if (!form.reportValidity() || submit.disabled || creationUnresolved) return;
      submit.disabled = true; error.textContent = ''; reload.hidden = true;
      const values = Object.fromEntries(Object.entries(inputs).map(([key, input]) => [key, input.value.trim()]));
      let result;
      if (t) result = await act('ticket.edit', {ticket:t.id, owner:values.owner, due:values.due, note:values.note, if_revision:t.revision});
      else {
        if (!created) {
          const previous = new Set(tickets().map(t => t.id));
          result = await act('ticket.new', {title:values.title});
          if (result.ok) {
            created = tickets().filter(t => t.title === values.title && !previous.has(t.id)).sort((a, b) => (Date.parse(b.created_at) || 0) - (Date.parse(a.created_at) || 0))[0];
            if (!created) {
              creationUnresolved = true;
              result = {ok:false, status:0, text:'The ticket was created, but could not be found in the reply. Close this dialog and reload before trying again.'};
            }
          }
        } else result = {ok:true};
        if (result.ok && created && (values.owner || values.due || values.note)) {
          // The ticket exists: close now, save the optional details behind the scenes.
          window.orch.toast('Ticket created', 'ok');
          window.orch.close(d);
          const details = await act('ticket.edit', {ticket:created.id, owner:values.owner, due:values.due, note:values.note});
          if (!details.ok) window.orch.toast('The ticket was created, but its details were not saved: ' + details.text, 'error');
          return;
        }
      }
      submit.disabled = creationUnresolved;
      if (!result.ok) {
        error.textContent = result.text + (result.status === 409 ? ' Reload the ticket before trying again.' : '');
        reload.hidden = !(t && result.status === 409);
        if (created) { inputs.title.disabled = true; submit.textContent = 'Save details'; }
        return;
      }
      window.orch.toast(t ? 'Ticket updated' : 'Ticket created', 'ok');
      await window.orch.close(d);
    });
    window.orch.open(d);
  }
  document.getElementById('new-ticket').hidden = snapshot;
  document.getElementById('new-ticket').addEventListener('click', () => ticketForm());
  const toggle = document.getElementById('menu-toggle');
  toggle.addEventListener('click', () => {
    const open = toggle.getAttribute('aria-expanded') !== 'true';
    toggle.setAttribute('aria-expanded', String(open));
    document.querySelector('.sidebar').dataset.open = String(open);
  });
  nav.addEventListener('click', event => {
    if (!event.target.closest('a')) return;
    toggle.setAttribute('aria-expanded', 'false');
    document.querySelector('.sidebar').dataset.open = 'false';
  });
  // An add-on row's switch or button: the DOM only carries verb + ticket (blocks.js checked them); the page adds
  // the add-on of the open tab, so a view can never address another add-on.
  async function addonAct(control) {
    const id = route().id;
    if (route().kind !== 'addon' || control.disabled || locks.has('addon-act')) return;
    const send = async () => {
      locks.add('addon-act'); control.disabled = true;
      const result = await act('addon.act', {addon:id, verb:control.dataset.verb, target:control.dataset.target});
      locks.delete('addon-act'); control.disabled = false;
      if (!result.ok) window.orch.toast(result.text || 'That did not work.', 'error');
      await loadAddon(id);
    };
    if (!control.dataset.confirm) return send();
    const {d, actions} = dialog(control.dataset.confirm, 'dialog');
    actions.append(button('Yes', 'primary', async () => { await window.orch.close(d); send(); }));
    d.append(actions);
    window.orch.open(d);
  }
  async function copyText(control) {
    try { await navigator.clipboard.writeText(control.dataset.copy); window.orch.toast('Copied', 'ok'); }
    catch (_) { window.orch.toast('Could not copy. Select the text and copy it.', 'error'); }
  }
  main.addEventListener('change', async event => {
    const control = event.target.closest('[data-settings-agent]');
    if (!control || snapshot || settingsBusy.has('agent')) return;
    const agent = array(state.settings?.agents).find(agent => agent.name === control.dataset.settingsAgent);
    if (!agent) return;
    const result = await settingsSend('config.agent', {name:agent.name}, 'agent');
    if (result.ok) window.orch.toast(agent.label + ' is now the default agent.', 'ok');
  });
  main.addEventListener('keydown', event => {
    const settingsTabControl = event.target.closest('[data-action="settings-tab"]');
    if (settingsTabControl && ['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) {
      event.preventDefault();
      const tabs = [...settingsTabControl.parentElement.querySelectorAll('[role="tab"]')];
      const index = tabs.indexOf(settingsTabControl);
      const next = event.key === 'Home' ? tabs[0] : event.key === 'End' ? tabs[tabs.length - 1] : tabs[(index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length];
      settingsTab = next.dataset.tab;
      render();
      document.getElementById(next.id)?.focus();
      return;
    }
    const tab = event.target.closest('[data-action="ticket-tab"]');
    if (!tab || !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const tabs = [...tab.parentElement.querySelectorAll('[role="tab"]')];
    const index = tabs.indexOf(tab);
    const next = event.key === 'Home' ? tabs[0] : event.key === 'End' ? tabs[tabs.length - 1] : tabs[(index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length];
    selectTicketTab(tab.dataset.ticket, next.dataset.tab);
    document.getElementById(next.id)?.focus();
  });
  main.addEventListener('click', async event => {
    const menu = event.target.closest('details.menu');
    if (menu && event.target.closest('button,a')) menu.open = false;
    const row = event.target.closest('[data-addon-act]');
    if (row) { if (!snapshot) addonAct(row); return; }
    const copy = event.target.closest('[data-copy]');
    if (copy) { copyText(copy); return; }
    const control = event.target.closest('[data-action]');
    if (!control) return;
    const action = control.dataset.action;
    if (action === 'tree' || action === 'tree-all') {
      const id = control.dataset.ticket;
      if (action === 'tree-all') treeAll.add(id);
      else if (treeExpanded.has(id)) treeExpanded.delete(id); else treeExpanded.add(id);
      render(); return;
    }
    if (action === 'ticket-tab' || action === 'answer-tab') {
      selectTicketTab(control.dataset.ticket, action === 'answer-tab' ? 'questions' : control.dataset.tab, action === 'answer-tab');
      return;
    }
    if (action === 'group') {
      const group = control.dataset.group;
      if (expanded.has(group)) expanded.delete(group); else expanded.add(group);
      render(); return;
    }
    if (snapshot) return;
    if (action === 'settings-tab') {
      settingsTab = control.dataset.tab;
      render(); return;
    }
    if (action === 'settings-addon') {
      const addon = array(state.settings?.addons).find(addon => addon.name === control.dataset.name);
      if (!addon || addon.name === 'dashboard' || settingsBusy.has('addon-' + addon.name)) return;
      const send = () => settingsSend('addon.set', {name:addon.name, on:!addon.active}, 'addon-' + addon.name);
      if (addon.active) await send();
      else settingsConfirm('Turn on ' + capitalise(addon.name) + '?', addon.consent, 'preserve-lines', 'Turn on', send);
      return;
    }
    if (action === 'agent') {
      if (control.dataset.op === 'answer') { selectTicketTab(control.dataset.ticket, 'questions', true); return; }
      const op = control.dataset.op;
      if (!['run.start', 'run.stop'].includes(op) || locks.has('agent-bar')) return;
      locks.add('agent-bar'); control.disabled = true;
      const result = await act(op, JSON.parse(control.dataset.args));
      locks.delete('agent-bar'); control.disabled = false;
      render();
      window.orch.toast(result.ok ? (op === 'run.start' ? 'Started' : 'Stopped') : result.text, result.ok ? 'ok' : 'error');
      return;
    }
    if (action === 'new') ticketForm();
    if (action === 'inline') startInline(control);
    if (action === 'agent-add') openAgentForm();
    if (action === 'need') openNeed(array(state.needs).find(n => n.id === control.dataset.need), control);
    if (action === 'retry-addon') loadAddon(route().id, true);
    if (action === 'start') {
      if (locks.has('background')) return;
      locks.add('background');
      control.disabled = true;
      const result = await act('addon.start', {});
      if (!result.ok) window.orch.toast(result.text, 'error');
      locks.delete('background');
      control.disabled = false;
      render();
    }
  });
  window.addEventListener('hashchange', async () => {
    for (const d of document.querySelectorAll('dialog[open]')) await window.orch.close(d);
    render();
  });
  if (snapshot) accept(window.ORCH_SNAPSHOT || {});
  else { refresh(); setInterval(refresh, 3000); }
})();

