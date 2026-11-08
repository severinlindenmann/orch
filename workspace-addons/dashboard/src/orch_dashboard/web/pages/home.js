'use strict';
// Page controls use direct listeners; h() only sets attributes.
function changeUnavailable() {
  if (document.getElementById('connection')?.hidden !== false) return false;
  window.orch.toast("Can't reach orch. Your change was not sent.", 'error');
  return true;
}
function changeError(result) {
  return result.status === 0 ? "Can't reach orch. Your change was not sent." : result.text;
}
function ticketTitle(t) {
  return h('div', {className:'row ticket-title'}, h('h3', {className:'grow'}, h('a', {href:href(t.id)}, typeof t.key === 'string' ? h('span', {className:'meta mono'}, t.key + ' ') : null, clean(t.title))), statusChip(t));
}
function parentLine(t) {
  const parent = ticketOf(t.parent || tickets().find(p => array(p.children).includes(t.id))?.id);
  return parent ? h('p', {className:'meta'}, 'Part of ', h('a', {href:href(parent.id)}, clean(parent.title))) : null;
}
function ticketRow(t) {
  return h('div', {className:'card-row home-ticket', 'data-key':'ticket-' + t.id}, ticketTitle(t));
}
function needRow(row, newest) {
  const t = ticketOf(row.ticket), choice = window.DashHelpers.needAction(row);
  const options = array(row.answer?.options), key = 'need-' + row.id;
  let actions = null;
  if (!snapshot && options.length) {
    actions = h('div', {className:'row answer-options'}, options.map(option => {
      const control = button(option + (option === row.answer.recommended ? ' · Suggested' : ''), 'outline sm', async event => {
        if (changeUnavailable() || locks.has(key)) return;
        const host = event.currentTarget.closest('[data-need-row]');
        locks.add(key);
        host.querySelectorAll('button').forEach(b => { b.disabled = true; });
        try {
          const result = await act('answer', {ticket:row.ticket, question:row.answer.question, answer:option});
          window.orch.toast(result.ok ? 'Answered' : changeError(result), result.ok ? 'ok' : 'error');
        } finally {
          locks.delete(key);
          host.querySelectorAll('button').forEach(b => { b.disabled = false; });
          render();
        }
      });
      control.dataset.key = key + '-option-' + option;
      return control;
    }));
  } else if (!snapshot) {
    actions = h('button', {type:'button', className:'btn outline sm', 'data-action':'need', 'data-need':row.id}, choice.label);
  }
  const question = array(t?.questions).find(q => q.id === row.answer?.question)?.text || row.title || row.text;
  return h('div', {className:'card-row home-need', 'data-key':key, 'data-need-row':row.id, 'data-newest':row.id === newest ? '' : null},
    t ? ticketTitle(t) : h('h3', {}, clean(row.title)), h('p', {}, clean(window.DashHelpers.plainWhy(question, 'The agent'))),
    h('p', {className:'meta'}, 'Next step · ', options.length ? 'Choose an answer' : choice.label), actions, t ? parentLine(t) : null);
}
function workingRow(t) {
  const tasks = array(t.checklist), done = tasks.filter(task => task.done).length;
  const claim = state.runs?.[t.id]?.claim, task = tasks.find(task => !task.done);
  return h('div', {className:'card-row home-work', 'data-key':'ticket-' + t.id}, ticketTitle(t),
    task ? h('p', {}, clean(task.text || task.title)) : null,
    h('p', {className:'meta'}, [capitalise(name(claim?.label || claim?.agent || t.owner)), age(claim?.started_at)].filter(Boolean).join(' · ')),
    tasks.length ? h('div', {className:'segments', role:'progressbar', 'aria-label':'Tasks done', 'aria-valuemin':0, 'aria-valuemax':tasks.length, 'aria-valuenow':done}, tasks.map(task => h('span', {className:task.done ? 'complete' : ''}))) : null,
    h('div', {className:'row'}, h('span', {className:'meta grow'}, done + ' of ' + tasks.length + ' tasks done'), h('a', {className:'btn ghost sm', href:href(t.id)}, 'Watch →')));
}
function resultRow(t) {
  return h('div', {className:'card-row home-result', 'data-key':'ticket-' + t.id}, ticketTitle(t),
    h('p', {className:'meta'}, 'Next step · Read the result, then mark done'),
    h('div', {className:'row'}, h('a', {className:'btn outline sm', href:href(t.id)}, 'Open result'), snapshot ? null : button('Mark done', 'outline sm', () => moveTicket(t.id, 'done'))));
}
function messageTicket(text) {
  if (snapshot) return;
  const {d, actions} = dialog('Make a ticket');
  const title = h('input', {className:'input', 'aria-label':'Title', required:true, maxlength:200, value:text.split('\n')[0].slice(0, 200)});
  const note = h('textarea', {className:'input', 'aria-label':'Note (optional)', rows:5}, text);
  const create = button('Create', 'primary', async () => {
    if (!title.value.trim()) { title.reportValidity(); return; }
    if (changeUnavailable()) return;
    create.disabled = true;
    const result = await act('ticket.new', {title:title.value.trim(), note:note.value});
    create.disabled = false;
    if (result.ok) { await window.orch.close(d); window.orch.toast('Ticket created', 'ok'); }
    else window.orch.toast(changeError(result), 'error');
  });
  actions.append(create);
  d.append(h('label', {className:'message-field'}, 'Title', title), h('label', {className:'message-field'}, 'Note (optional)', note), actions);
  window.orch.open(d);
}
function homeSection(key, title, body) {
  return h('section', {className:'home-section', 'data-key':key, id:key === 'needs-you' ? key : null}, h('h2', {}, title), h('div', {className:'card'}, body));
}
function home() {
  const needs = needsList(), all = tickets();
  const working = sorted(all.filter(t => shown(t).status === 'active' && !needs.some(n => n.ticket === t.id)));
  const review = sorted(all.filter(t => t.status === 'review' && !needs.some(n => n.ticket === t.id)));
  const used = new Set([...needs.map(n => n.ticket), ...working.map(t => t.id), ...review.map(t => t.id)]);
  const finished = all.filter(t => t.status === 'done' && (() => {
    const at = parse(t.done_at || t.completed_at || t.updated_at);
    return at && at.toDateString() === now().toDateString();
  })());
  const message = array(state.general?.history).filter(e => e.via === 'phone' && e.text).sort((a,b) => (Date.parse(b.at) || 0) - (Date.parse(a.at) || 0))[0];
  const text = message && String(message.text).replace(/^From [^:]{1,100}: /, '');
  const newest = needs.slice().sort((a,b) => (Date.parse(b.since) || 0) - (Date.parse(a.since) || 0))[0]?.id;
  const agent = capitalise(name(state.runs?.[working[0]?.id]?.claim?.label || state.runs?.[working[0]?.id]?.claim?.agent || array(state.settings?.agents).find(a => a.chosen)?.label || 'Agent'));
  const hour = now().getHours();
  const stopped = array(state.services).some(s => s.running === false);
  const banner = stopped ? h('div', {className:'banner attn', 'data-key':'background'}, h('p', {className:'grow'}, 'Background work is not running. Start it so repeating work and checks can run.'), snapshot ? null : h('button', {type:'button', className:'btn outline sm', 'data-action':'start'}, 'Start')) : null;
  return fragment(heading('Good ' + (hour < 12 ? 'morning' : hour < 18 ? 'afternoon' : 'evening'), now().toLocaleDateString('en-GB', {weekday:'long', day:'numeric', month:'long'}) + ' · ' + needs.length + (needs.length === 1 ? ' question for you · ' : ' questions for you · ') + agent + ' is working on ' + working.length + (working.length === 1 ? ' ticket' : ' tickets')), banner,
    h('div', {className:'columns home-columns', 'data-key':'columns'}, h('div', {className:'stack', 'data-key':'left'},
      homeSection('needs-you', 'Needs you (' + needs.length + ')', needs.length ? needs.map(n => needRow(n, newest)) : emptyRow('Nothing needs you right now.')),
      homeSection('working-now', 'Working now', working.length ? working.map(workingRow) : emptyRow('No tickets are being worked on.')),
      homeSection('check-result', 'Check result (' + review.length + ')', review.length ? review.map(resultRow) : emptyRow('No results to check.')),
      h('div', {className:'card card-row', 'data-key':'everything-else'}, h('span', {className:'grow muted'}, 'Everything else (' + all.filter(t => activeTicket(t) && !used.has(t.id)).length + ')'), h('a', {className:'btn ghost sm', href:'#tickets'}, 'View Tickets →'))),
    h('aside', {className:'stack', 'data-key':'right'}, message ? card('messages', 'Messages', '', h('div', {className:'card-row home-message', 'data-key':'message-' + (message.at || text)}, h('p', {}, clean(text)), snapshot ? null : button('Make a ticket', 'outline sm', () => messageTicket(text)))) : null,
      card('finished-today', 'Finished today', '', finished.length ? finished.map(ticketRow) : emptyRow('Nothing finished today yet.')))));
}
function loadingView() {
  const shape = kind => h('div', {className:'card skeleton-card ' + kind, 'aria-hidden':'true'}, h('div', {className:'skeleton-line'}), h('div', {className:'skeleton-line short'}), h('div', {className:'skeleton-line'}));
  return h('div', {className:'loading-home', 'data-key':'loading', 'aria-busy':'true'}, h('p', {role:'status'}, 'Loading your workspace…'),
    h('div', {className:'skeleton-heading', 'aria-hidden':'true'}), h('div', {className:'columns'}, h('div', {className:'stack'}, shape('question'), shape('work'), shape('result')), h('aside', {className:'stack'}, shape('message'), shape('finished'))));
}
function connectionNotice(connectionEl, hadState) {
  connectionEl.replaceChildren(h('p', {className:'grow'}, hadState ? "Can't reach orch. Showing the last update, trying again every few seconds." : "Can't reach orch yet. Trying again shortly."),
    button('Try now', 'outline sm', () => refresh()), h('details', {}, h('summary', {}, 'Details'), h('p', {}, 'Is the computer asleep? orch runs on the computer that owns this workspace. Wake it up and check that it is connected. This page will try again shortly.')));
  connectionEl.hidden = false;
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
