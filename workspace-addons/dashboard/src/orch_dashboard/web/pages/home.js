'use strict';
// Home page and the General (phone conversation) page.
function ticketRow(t) {
  const meta = [typeof t.key === 'string' ? t.key : '', statusWord(shown(t)), name(t.owner), t.due ? 'Due ' + date(t.due) : '', snapshot ? '' : activityNote(t)].filter(Boolean);
  const parent = ticketOf(t.parent);
  let late = '';
  if (overdue(t)) {
    const days = Math.round((Date.parse(today()) - Date.parse(t.due)) / 86400000);
    late = chip('Overdue ' + days + (days === 1 ? ' day' : ' days'), 'error');
  }
  return h('div', {className:'card-row ticket-row', 'data-key':'ticket-' + t.id}, h('div', {className:'grow'}, h('h3', {}, h('a', {href:href(t.id)}, clean(t.title))), h('p', {className:'meta'}, meta.join(' · ')), questionLine(t), parent ? h('p', {className:'meta'}, 'Part of ', clean(parent.title)) : null), h('div', {className:'row'}, late, activity(t, 'row'), statusControl(t, 'row')));
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
  return h('div', {className:'card-row', 'data-key':'need-' + row.id, 'data-need-row':row.id, 'data-newest':row.id === newest ? '' : null}, h('span', {className:'need-icon ' + (row.tone === 'bad' ? 'bad' : row.tone === 'warn' ? 'warn' : 'muted')}, iconEl(row.tone === 'bad' ? 'stop' : row.tone === 'warn' ? 'shield' : 'note')), h('div', {className:'grow'}, h('h3', {}, clean(window.DashHelpers.plainWhy(row.text, by || 'The agent') || window.DashHelpers.plainNames(row.text))), h('p', {className:'meta'}, meta)), h('time', {datetime:row.since || ''}, age(row.since)), action);
}
function home() {
  const needs = needsList();
  const rows = window.DashHelpers.agentRows(state.tickets, state.runs, Date.now());
  const working = rows.filter(row => ['working', 'needs', 'stuck'].includes(row.state));
  // a ticket whose agent is still starting (the click is answered, the session is not up yet) counts as starting
  const gettingStarted = new Set([...starting, ...rows.filter(row => row.state === 'starting').map(row => row.ticket)]);
  const startingText = gettingStarted.size ? gettingStarted.size + (gettingStarted.size === 1 ? ' agent starting' : ' agents starting') : '';
  const current = sorted(tickets().filter(activeTicket));
  const oldest = needs.map(n => parse(n.since)).filter(Boolean).sort((a, b) => a - b)[0];
  const newest = needs.slice().sort((a, b) => (Date.parse(b.since) || 0) - (Date.parse(a.since) || 0))[0]?.id;
  const history = tickets().flatMap(t => window.DashHelpers.dedupeHistory(array(t.history), t.checklist).map(entry => ({entry, title:t.title, checklist:t.checklist}))).sort((a, b) => (Date.parse(b.entry.at) || 0) - (Date.parse(a.entry.at) || 0)).slice(0, 5);
  const stopped = array(state.services).some(s => s.running === false);
  const banner = stopped ? h('div', {className:'banner attn', 'data-key':'background'}, h('p', {className:'grow'}, 'Background work is not running. Start it so repeating work and checks can run.'), snapshot ? null : h('button', {type:'button', className:'btn outline sm', 'data-action':'start'}, 'Start')) : null;
  const agents = rows.slice(0, 5).map(row => h('div', {className:'card-row', 'data-key':'agent-' + row.agent + '-' + row.ticket}, h('span', {className:'dot ' + (row.state === 'stuck' ? 'needs' : row.state)}), h('div', {className:'grow'}, h('h3', {}, capitalise(name(row.agent) || 'Agent') + ' · ' + ({working:'working', starting:'getting started', needs:'needs you', stuck:'may be stuck', idle:'idle'}[row.state])), h('p', {className:'meta'}, row.state === 'idle' ? 'Last worked ' + window.DashHelpers.ago(row.since, Date.now()) : [clean(ticketOf(row.ticket)?.title), age(row.since)].filter(Boolean).join(' · ')))));
  const links = pageLinks();
  const recent = history.map(({entry, title, checklist}) => {
    const line = clean(window.DashHelpers.historyLine(entry, checklist));
    return h('div', {className:'card-row'}, h('div', {className:'grow'}, h('h3', {}, line.length > 80 ? line.slice(0, 79) + '…' : line), h('p', {className:'meta'}, [name(entry.by), clean(title), age(entry.at)].filter(Boolean).join(' · '))));
  });
  return fragment(heading('Today', now().toLocaleDateString('en-GB', {weekday:'long', day:'numeric', month:'long'}) + ' · ' + [window.DashHelpers.needsYou(needs.length), working.length + (working.length === 1 ? ' agent working' : ' agents working'), startingText].filter(Boolean).join(' · ')), banner,
    h('div', {className:'columns', 'data-key':'columns'}, h('div', {className:'stack', 'data-key':'left'},
      card('needs-you', 'Needs you', needs.length + (oldest ? ' · oldest ' + age(oldest) : ''), needs.length ? needs.map(n => needRow(n, newest)) : emptyRow('Nothing needs you right now.'), true),
      card('your-tickets', 'Your tickets', current.length + (current.some(overdue) ? ' · ' + current.filter(overdue).length + ' overdue' : ''), current.length ? current.map(ticketRow) : tickets().length ? h('div', {className:'card-row'}, h('p', {className:'grow muted'}, 'Nothing open. Finished tickets are under Tickets.'), newButton()) : firstTicket(), true)),
    h('aside', {className:'stack', 'data-key':'right'},
      card('agents', 'Agents', working.length + ' working' + (gettingStarted.size ? ' · ' + gettingStarted.size + ' starting' : ''), [agents.length ? agents : emptyRow('No one is working on your tickets. Open a ticket and press Start.'), links.length ? h('div', {className:'card-row'}, links.map(link => h('a', {className:'meta', href:link.url}, 'Watch live in ' + capitalise(link.label) + ' →'))) : null]),
      card('recently', 'Recently', '', recent.length ? recent : emptyRow('No recent activity.')))));
}
// The General conversation with the phone: every text both ways, newest last. Read only.
function generalPage() {
  const g = state.general, list = array(g?.history).slice().sort((a, b) => (Date.parse(a.at) || 0) - (Date.parse(b.at) || 0));
  const rows = list.map((entry, i) => {
    const rich = g && entry.via === 'phone' ? phoneEntry(g.id, entry) : null;
    const mine = entry.via !== 'phone';
    return h('div', {className:'card-row chat-row' + (mine ? ' chat-out' : ''), 'data-key':'general-' + i + '-' + (entry.at || '')},
      h('div', {className:'grow'}, rich || h('p', {}, clean(window.DashHelpers.historyLine(entry, []))), h('p', {className:'meta'}, [name(entry.by), surface(entry.via)].filter(Boolean).join(' · '))),
      h('time', {datetime:entry.at || ''}, age(entry.at)));
  });
  return fragment(heading('General', 'Texts from the phone that belong to no ticket.'),
    h('section', {className:'card', 'data-key':'general-card'}, rows.length ? rows : emptyRow('No messages yet. Texts from the phone that are not about a ticket show up here.')));
}
