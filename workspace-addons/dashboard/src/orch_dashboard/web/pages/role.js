// ORCH-827: the page of a ticket that runs by itself (a role: a ticket with a repeat), as the owner picked draft A2
// on ORCH-812. Header: "Runs by itself", Run now and Pause (Turn on while paused). Tabs Overview · Runs · Schedule ·
// Chat · Files instead of a task list that grows with every run; Tasks and Activity stay one click away from Overview.
// The runs, results, findings and totals come from the automation add-on (GET /api/role/<ticket>), the same totals
// the Automation page shows. Chat is the Focus chat view (livechat.js) with each run as a run card.

const ROLE_TABS = ['overview', 'runs', 'schedule', 'chat', 'files', 'tasks', 'activity'];
const ROLE_SHOWN = ['overview', 'runs', 'schedule', 'chat', 'files'];
const ROLE_NOTE = 'For the next run: ';
const ROLE_LIMITS = [30, 45, 60, 75, 90, 120, 180];
const ROLE_REPEATS = [['every hour', 'Every hour'], ['every 3 hours', 'Every 3 hours'], ['every 6 hours', 'Every 6 hours'], ['every day at 03:00', 'Every day at 03:00'], ['every monday at 08:00', 'Every week, Monday 08:00']];
const roleData = new Map();  // ticket id -> {at, busy, rev, data}

function roleOf(t) {
  const a = t && t.ext && typeof t.ext === 'object' ? t.ext.automation : null;
  return !!a && a.recurring === true && typeof a.cron === 'string' && a.cron.length > 0 && !!repeatsAddon();
}
function loadRole(t, force = false) {
  if (snapshot) return;
  const hit = roleData.get(t.id), age = hit ? Date.now() - hit.at : Infinity;
  if (hit?.busy || (!force && hit && hit.rev === t.revision && age < 30000)) return;
  roleData.set(t.id, {...hit, busy:true});
  fetch('/api/role/' + encodeURIComponent(t.id), {cache:'no-store'}).then(r => r.ok ? r.json() : null).catch(() => null).then(data => {
    const before = JSON.stringify(roleData.get(t.id)?.data);
    roleData.set(t.id, {at:Date.now(), rev:t.revision, data});
    if (JSON.stringify(data) !== before && route().kind === 'ticket' && ticketOf(route().id)?.id === t.id) render();
  });
}
function roleSelectedTab(t) {
  const raw = ticketTabs.get(t.id), tab = raw === 'artifacts' ? 'files' : raw === 'history' ? 'activity' : raw;
  return ROLE_TABS.includes(tab) ? tab : 'overview';
}

// ---- words
function roleTook(s) {
  if (!Number.isFinite(s)) return '';
  if (s < 60) return 'a few seconds';
  const m = Math.round(s / 60);
  return m < 60 ? m + ' min' : Math.floor(m / 60) + ' h' + (m % 60 ? ' ' + (m % 60) + ' min' : '');
}
const roleCost = r => r.outcome === 'skipped' ? 'no cost' : Number.isFinite(r.cost) ? '$' + r.cost.toFixed(2) : '';
const roleWhen = r => [r.at ? time(r.at) : '', r.outcome === 'running' ? '' : roleTook(r.took), roleCost(r)].filter(Boolean).join(' · ');
const ROLE_DOT = {ok:'ok', warn:'needs', bad:'bad', none:'idle', working:'working'};
const roleDot = r => h('span', {className:'dot ' + (ROLE_DOT[r.tone] || 'idle'), 'aria-hidden':'true'});
function roleRunTitle(r) {
  const n = r.findings.length;
  const words = r.outcome === 'problems' && n ? n + (n === 1 ? ' problem reported' : ' problems reported') : r.words;
  return 'Run ' + r.run + (r.script ? ' · ' + clean(r.script) : '') + ' · ' + words;
}
function roleIn(at) {
  const ms = Date.parse(at || '') - now().getTime();
  if (!Number.isFinite(ms) || ms <= 0) return '';
  const m = Math.round(ms / 60000), d = Math.round(m / 1440);
  if (m >= 2880) return 'in ' + d + ' days';
  return 'in ' + (m < 60 ? m + ' min' : Math.floor(m / 60) + ' h' + (m % 60 ? ' ' + (m % 60) + ' min' : ''));
}
function roleFilesWords(tot) {
  const f = tot.files || {}, all = (f.opened || 0) + (f.unopened || 0) + (f.unknown || 0);
  if (!all) return 'None yet';
  const parts = [f.unopened ? f.unopened + ' not opened' : '', f.unknown ? f.unknown + ' unknown' : ''].filter(Boolean);
  return parts.length ? parts.join(', ') : 'All opened';
}

// ---- pieces
function roleFileButtons(t, r, primary = false) {
  const files = r.files || [];
  if (!files.length) return [];
  const open = () => previewFile(t.id, files[0].kind === 'evidence' ? 'evidence' : 'artifacts', files[0].name);
  return [ticketButton(files.length === 1 ? '1 file' : files.length + ' files', primary ? 'outline sm' : 'ghost sm', open, {'data-key':'role-run-files-' + r.run})];
}
function roleFindingLinks(r) {
  const seen = new Set();
  return r.findings.filter(f => !seen.has(f.ticket) && seen.add(f.ticket)).map(f => {
    const ft = ticketOf(f.ticket);
    return h('a', {className:'btn ghost sm', href:href(f.ticket), 'data-key':'role-finding-' + f.ticket}, (ft && window.DashHelpers.ticketKey(ft)) || 'Its ticket');
  });
}
function roleRunCard(t, r, opts = {}) {
  return h('article', {className:'card pad stack role-run', 'data-key':(opts.chat ? 'role-chat-run-' : 'role-run-card-') + r.run},
    h('div', {className:'row between'},
      h('span', {className:'status-line'}, roleDot(r), h('strong', {}, roleRunTitle(r))),
      h('span', {className:'meta muted'}, roleWhen(r))),
    r.text ? h('p', {}, clean(r.text)) : null,
    opts.next ? h('p', {className:'muted'}, opts.next) : null,
    h('div', {className:'row'}, roleFileButtons(t, r, opts.primary), roleFindingLinks(r), opts.extra || null));
}
function roleRunRow(t, r, open) {
  const detailBits = [
    h('p', {className:'meta'}, r.outcome === 'running' ? 'What it checks' : 'What it checked'),
    r.checked.length ? h('ul', {}, r.checked.map(c => h('li', {}, clean(c))))
      : h('p', {className:'muted'}, r.outcome === 'skipped' ? 'Quick check: nothing changed since the run before. No helper started.' : r.text ? clean(r.text) : 'The helper wrote no result for this run.'),
    r.findings.length ? h('p', {className:'meta'}, r.findings.length === 1 ? '1 finding' : r.findings.length + ' findings') : null,
    r.findings.length ? h('ul', {}, r.findings.map(f => h('li', {}, clean(f.title || ''), ' · ', h('a', {href:href(f.ticket)}, (ticketOf(f.ticket) && window.DashHelpers.ticketKey(ticketOf(f.ticket))) || 'its ticket')))) : null,
    r.files.length || r.outcome === 'running' ? h('div', {className:'row'}, roleFileButtons(t, r, true),
      r.outcome === 'running' && typeof liveFocusButton === 'function' ? liveFocusButton(t, true) : null) : null];
  return h('details', {className:'role-run-row', open:open || null, 'data-key':'role-run-' + r.run},
    h('summary', {className:'card-row'}, roleDot(r),
      h('div', {className:'grow'}, h('p', {className:'title'}, roleRunTitle(r)), h('p', {className:'meta'}, roleWhen(r) || (r.at ? time(r.at) : ''))),
      h('span', {className:'meta role-open', 'aria-hidden':'true'}, 'Details')),
    h('div', {className:'pad stack role-run-detail'}, detailBits));
}
function roleTotalsRows(tot) {
  if (!tot) return [];
  const row = (label, value, key) => h('div', {'data-key':'role-total-' + key}, h('dt', {}, label), h('dd', {}, value));
  const skipped = tot.by_outcome?.skipped || 0;
  return [
    row('Runs', tot.runs + (skipped ? ' (' + skipped + ' skipped)' : ''), 'runs'),
    row('Findings', String(tot.findings), 'findings'),
    row('Their tickets', tot.tickets ? tot.fixed + ' fixed · ' + tot.open + ' open · ' + tot.dropped + ' dropped' : 'None yet', 'tickets'),
    row('Result files', roleFilesWords(tot), 'files'),
    Number.isFinite(tot.cost) ? row('Cost so far', '$' + tot.cost.toFixed(2) + ' in ' + tot.runs + (tot.runs === 1 ? ' run' : ' runs'), 'cost') : null];
}
function roleAbout(t, data) {
  return h('aside', {className:'side-panel properties', 'data-key':'role-about'}, h('h2', {}, 'About this role'),
    h('dl', {}, roleTotalsRows(data?.totals),
      h('div', {}, h('dt', {}, 'Created'), h('dd', {}, t.created_at ? time(t.created_at) : '–'))),
    data && !data.totals?.files_measured && (data.totals?.files?.unknown || 0) ? h('p', {className:'meta'}, 'Files from before this page counted opens show as unknown.') : null);
}
function roleJob(t) {
  const text = clean(t.description || t.note || '');
  const parts = text.split(/(?<=[.!?])\s+/).filter(Boolean);
  const short = parts.slice(0, 2).join(' ');
  const full = t.note && clean(t.note) !== short ? clean(t.note) : parts.length > 2 ? text : '';
  return h('section', {className:'story-section', 'data-key':'role-job'},
    h('div', {className:'section-head'}, h('h2', {}, 'Its job')),
    short ? h('p', {className:'t-row'}, short) : h('p', {className:'muted'}, 'No job written yet.'),
    full ? h('details', {className:'disclosure'}, h('summary', {}, 'Full instructions'), h('p', {className:'muted preserve-lines'}, full)) : null);
}
// One plain line under the last run: what it means for the person (the draft's "Nothing for you to do").
function roleNextStep(r) {
  const n = new Set(r.findings.map(f => f.ticket)).size;
  if (n) return n === 1 ? 'What it found is a ticket now.' : 'What it found is in ' + n + ' tickets now.';
  if (r.outcome === 'running') return '';
  if (['failed', 'stopped'].includes(r.outcome)) return 'The next run tries again.';
  return 'Nothing for you to do.';
}
function roleNextStrip(t, sc) {
  const paused = sc?.paused || t.ext?.automation?.paused === true;
  const next = sc?.next?.[0];
  return h('section', {className:'strip role-strip', 'aria-label':'Next run', 'data-key':'role-next'}, h('div', {className:'strip-h'},
    h('div', {className:'role-fact'}, h('span', {className:'meta'}, 'Next run'),
      paused ? h('strong', {className:'muted'}, 'None while paused') : next ? h('strong', {}, time(next), ' ', h('span', {className:'muted'}, roleIn(next) ? '· ' + roleIn(next) : '')) : h('strong', {className:'muted'}, 'Not planned')),
    h('div', {className:'role-fact grow'}, h('span', {className:'meta'}, 'Repeats'), h('strong', {}, clean(sc?.repeats || 'On a plan')),
      sc?.quick === 'on' ? h('span', {className:'meta muted'}, 'Quick check first. Skips when nothing changed.') : null),
    ticketButton('Change the schedule', 'ghost sm', () => selectTicketTab(t.id, 'schedule'), {'data-key':'role-to-schedule'})));
}
function roleOverview(t, data, openQs) {
  const runs = data?.runs || [], last = runs.find(r => r.outcome !== 'running') || runs[0];
  return [
    openQs.length ? h('div', {className:'banner attn', 'data-key':'role-question-banner'}, h('div', {className:'grow'}, h('strong', {}, 'It has a question for you'), h('p', {}, clean(openQs[0].text))),
      ticketButton('Answer', 'primary sm', () => selectTicketTab(t.id, 'chat'), {'data-key':'role-answer'})) : null,
    roleJob(t),
    h('section', {className:'story-section', 'data-key':'role-last'},
      h('div', {className:'section-head'}, h('h2', {}, 'Last run'), runs.length ? h('button', {type:'button', className:'btn ghost sm', 'data-action':'ticket-tab', 'data-ticket':t.id, 'data-tab':'runs'}, runs.length === 1 ? 'See it in Runs' : 'All ' + runs.length + ' runs') : null),
      last ? roleRunCard(t, last, {primary:true, next:roleNextStep(last), extra:ticketButton('Open the chat', 'ghost sm', () => selectTicketTab(t.id, 'chat'), {'data-key':'role-open-chat'})})
        : h('p', {className:'muted'}, data ? 'It has not run yet.' : data === null ? 'The runs can’t be shown right now.' : 'Loading the runs…')),
    roleNextStrip(t, data?.schedule),
    h('p', {className:'meta role-more'}, h('button', {type:'button', className:'btn ghost sm', 'data-action':'ticket-tab', 'data-ticket':t.id, 'data-tab':'tasks', 'data-key':'role-to-tasks'}, 'All tasks'), ' · ',
      h('button', {type:'button', className:'btn ghost sm', 'data-action':'ticket-tab', 'data-ticket':t.id, 'data-tab':'activity', 'data-key':'role-to-activity'}, 'Everything that happened'))];
}
function roleRunsPanel(t, data) {
  const runs = data?.runs || [], tot = data?.totals;
  const cost = Number.isFinite(tot?.cost) ? ' · $' + tot.cost.toFixed(2) + ' in all' : '';
  return [h('h2', {}, 'Runs'),
    h('p', {className:'muted'}, 'Every time it woke up, newest first. Click a run to see what it checked.' + (runs.length ? ' ' + runs.length + (runs.length === 1 ? ' run' : ' runs') + cost + '.' : '')),
    runs.length ? h('section', {className:'card', 'data-key':'role-runs'}, runs.slice(0, 100).map((r, i) => roleRunRow(t, r, i === 0 && r.outcome !== 'skipped')))
      : h('p', {className:'muted'}, data ? 'No runs yet.' : 'Loading the runs…')];
}
async function roleAct(t, verb, value, done) {
  const result = await act('addon.act', {addon:repeatsAddon(), verb, target:t.id, ...(value != null ? {value} : {})});
  if (result.ok) { window.orch.toast(clean(result.data?.text || result.text || 'Saved.'), 'ok'); loadRole(t, true); }
  else window.orch.toast(typeof changeError === 'function' ? changeError(result) : 'That did not work. Try again.', 'error');
  if (done) done(result.ok);
}
function roleSettingRow(label, value, action, key) {
  return h('div', {className:'setting-row', 'data-key':'role-setting-' + key}, h('span', {className:'row-label'}, label), h('div', {className:'row-value'}, value), h('div', {className:'row-action'}, action));
}
function roleSchedulePanel(t, data) {
  const sc = data?.schedule || {}, paused = sc.paused || t.ext?.automation?.paused === true;
  // the page keeps a drawn control and its handler across redraws (the keyed morph), so a handler reads the newest
  // state when it is clicked, never what was true when it was drawn
  const sw = (on, label, key, click, disabled = false) => { const b = h('button', {type:'button', className:'switch', role:'switch', 'aria-checked':String(on), 'aria-label':label, 'data-key':key, disabled:disabled || null}); b.onclick = click; return b; };
  const fresh = () => roleData.get(t.id)?.data?.schedule || {};
  // keyed by what they show: the kit's select draws its own label, so a new value draws a new control
  const repeats = h('select', {'aria-label':'Repeats', 'data-key':'role-repeats-' + (sc.cron || 'none')},
    h('option', {value:''}, clean(sc.repeats || 'On a plan')), ROLE_REPEATS.filter(([, label]) => label.toLowerCase() !== (sc.repeats || '').toLowerCase()).map(([v, label]) => h('option', {value:v}, label)), h('option', {value:'custom'}, 'Other plan…'));
  repeats.value = '';
  repeats.onchange = e => {
    const sel = e.currentTarget, v = sel.value; sel.value = '';
    if (v === 'custom') return repeatsDialog(t.id, repeatsAddon());
    if (v) roleAct(t, 'repeat', v);
  };
  const limit = h('select', {'aria-label':'Time limit', 'data-key':'role-limit-' + (sc.time_limit || 'none')}, h('option', {value:'none'}, 'No time limit'), ROLE_LIMITS.map(m => h('option', {value:String(m)}, 'Stops after ' + m + ' minutes')));
  limit.value = sc.time_limit ? String(sc.time_limit) : 'none';
  limit.onchange = e => { const sel = e.currentTarget; roleAct(t, 'limit', sel.value, ok => { if (!ok) sel.value = fresh().time_limit ? String(fresh().time_limit) : 'none'; }); };
  const next = paused ? h('strong', {className:'muted'}, 'None while paused') : sc.next?.length ? h('strong', {}, sc.next.map(x => time(x)).join(' · ')) : h('strong', {className:'muted'}, 'Not planned');
  return [h('h2', {}, 'Schedule'), h('p', {className:'muted'}, 'When it runs and how. A change counts from the next run.'),
    h('section', {className:'card', 'data-key':'role-schedule'},
      roleSettingRow('Runs by itself', [h('strong', {}, paused ? 'Paused' : 'On'), h('p', {className:'meta'}, paused ? 'It will not run until you turn it on.' : 'Nobody has to start it.')],
        sw(!paused, clean(t.title) + ' on or paused', 'role-switch', () => roleAct(t, 'toggle')), 'on'),
      roleSettingRow('Repeats', repeats, null, 'repeats'),
      roleSettingRow('Next runs', next, paused ? null : ticketButton('Run now', 'outline sm', () => roleAct(t, 'run'), {'data-key':'role-schedule-run'}), 'next'),
      roleSettingRow('Quick check first', [h('strong', {}, sc.quick === 'on' ? 'On' : 'Off'),
        h('p', {className:'meta'}, sc.quick === 'none' ? 'Nothing to check is set up for this role yet.' : 'It looks whether anything changed. If not, the run is skipped and costs nothing.')],
        sw(sc.quick === 'on', 'Quick check first', 'role-quick', () => roleAct(t, 'quick', fresh().quick === 'on' ? 'off' : 'on'), sc.quick === 'none'), 'quick'),
      sc.script ? null : roleSettingRow('Time limit', limit, null, 'limit'),  // a script ends by itself
      roleSettingRow('Helper strength', modelField(t), null, 'model'))];
}
// The chat: the Focus chat rows (steps, answers, the person's lines), each run as a run card, the person's notes for
// the next run as their messages, the open question answered inside, and the box for the next run.
function roleChatRows(t, data) {
  const st = typeof state === 'object' && state ? state : {};
  const rows = liveChatModel(t, st.me || '', liveChatMine(st.runs?.[t.id], liveChatSent.get(t.id)))
    .filter(r => !(r.w === 'e' && r.text === 'The helper started'));  // the run card says it
  for (const e of array(t.history)) {
    const text = String(e?.text || '');
    if (/^human:/.test(String(e?.by || '')) && text.startsWith(ROLE_NOTE)) {
      rows.push({w:'y', text:text.slice(ROLE_NOTE.length), at:e.at, who:e.by === st.me ? '' : liveChatWho(e.by)});
      rows.push({w:'e', text:'Saved for the next run', at:e.at});
    }
  }
  for (const r of data?.runs || []) if (r.at) rows.push({w:'run', run:r, at:r.at});
  return rows.map((r, n) => [r, n]).sort((a, b) => (liveChatTime(a[0].at) - liveChatTime(b[0].at)) || (a[1] - b[1])).map(x => x[0]);
}
function roleChatPanel(t, data, openQs) {
  const rows = roleChatRows(t, data), out = [];
  for (let i = 0; i < rows.length; i++) {
    const r = rows[i];
    if (r.w === 'run' && r.run.outcome === 'skipped') {  // skipped runs in a row fold into one quiet line
      let j = i; while (j + 1 < rows.length && rows[j + 1].w === 'run' && rows[j + 1].run.outcome === 'skipped') j++;
      const n = j - i + 1, list = rows.slice(i, j + 1);
      out.push(h('details', {className:'disclosure', 'data-key':'role-skipped-' + r.run.run}, h('summary', {}, n === 1 ? '1 run skipped, nothing changed' : n + ' runs skipped, nothing changed'),
        list.map(x => h('p', {className:'live-ev meta'}, 'Run ' + x.run.run + ' · ' + time(x.at) + ' · quick check only · no cost'))));
      i = j; continue;
    }
    out.push(r.w === 'run' ? roleRunCard(t, r.run, {chat:true}) : liveChatRow(r, t.id));
  }
  const thread = h('div', {className:'live-chat', role:'log', 'aria-label':'Runs and messages of ' + clean(t.title), tabindex:'0', 'data-key':'role-thread', 'data-role-thread':t.id},
    out.length ? out : h('p', {className:'meta live-chat-empty'}, 'No runs or messages yet.'),
    openQs.map(q => ticketQuestion(t, q)));
  const input = h('input', {className:'input', type:'text', maxlength:'1500', 'aria-label':'Tell it something for the next run', placeholder:'Tell it something for the next run', 'data-key':'role-say-' + t.id});
  const form = h('form', {className:'role-say', 'data-key':'role-say'}, input, h('button', {type:'submit', className:'btn primary sm'}, 'Send'));
  form.onsubmit = async e => {
    e.preventDefault();
    const input = e.currentTarget.querySelector('input'), text = input.value.trim(); if (!text) return;
    const result = await act('log', {ticket:t.id, text:ROLE_NOTE + text});
    if (result.ok) { input.value = ''; window.orch.toast('Saved. It reads this when the next run starts.', 'ok'); }
    else window.orch.toast(typeof changeError === 'function' ? changeError(result) : 'Not saved. Try again.', 'error');
  };
  const next = data?.schedule?.next?.[0];
  requestAnimationFrame(() => { const box = main.querySelector('[data-role-thread="' + t.id + '"]'); if (box && !box.dataset.scrolled) { box.scrollTop = box.scrollHeight; box.dataset.scrolled = '1'; } });
  return [thread, form, h('p', {className:'meta role-say-hint'}, next && !data?.schedule?.paused ? 'It reads this when it starts at ' + time(next) + '.' : 'It reads this when the next run starts.')];
}
function roleHeader(t, run, data, openQs, menu, tabs) {
  const paused = data?.schedule?.paused || t.ext?.automation?.paused === true, running = !!run?.running;
  const key = window.DashHelpers.ticketKey(t), dot = () => h('span', {'aria-hidden':'true'}, '·');
  const kicker = [key ? h('span', {className:'key'}, key) : null, h('span', {className:'chip active', 'data-key':'role-chip'}, '↻ Runs by itself'),
    running ? h('span', {className:'pill working', 'data-key':'role-running'}, h('span', {className:'live-dot', 'aria-hidden':'true'}), 'Running now') : null,
    openQs.length ? h('span', {className:'pill needs', 'data-key':'role-has-question'}, 'Has a question for you') : null,
    paused ? h('span', {className:'badge paused', 'data-key':'role-paused'}, 'Paused') : null].filter(Boolean);
  const every = clean(data?.schedule?.repeats || '').toLowerCase();
  const sentence = 'A role. Nobody has to start it' + (every ? ': it wakes up ' + every.replace(/^repeats /, '') + ' and does its job.' : '.');
  const actions = snapshot ? [] : [
    running ? (typeof liveFocusButton === 'function' ? liveFocusButton(t, true) : null) : null,
    running ? ticketButton('Stop this run', 'ghost sm', () => act('run.stop', {ticket:t.id}), {'data-key':'role-stop'}) : null,
    !running && !paused ? ticketButton('Run now', 'outline sm', () => roleAct(t, 'run'), {'data-key':'role-run-now'}) : null,
    paused ? ticketButton('Turn on', 'primary sm', () => roleAct(t, 'on'), {'data-key':'role-turn-on'}) : !running ? ticketButton('Pause', 'ghost sm', () => roleAct(t, 'off'), {'data-key':'role-pause'}) : null,
    railButton(t), menu].filter(Boolean);
  return h('section', {className:'strip strip-plain ticket-strip ticket-heading', 'data-key':'ticket-strip-' + t.id},
    h('div', {className:'strip-h'},
      h('div', {className:'grow ticket-strip-text'}, h('p', {className:'t-meta strip-kicker', 'data-key':'ticket-kicker'}, kicker.flatMap((x, i) => i ? [dot(), x] : [x])),
        h('h1', {className:'t-title'}, inlineField(t, 'title')), h('p', {className:'t-meta muted', 'data-key':'ticket-sentence'}, sentence), railFacts(t)),
      actions.length ? h('div', {className:'row ticket-strip-actions'}, actions) : null),
    tabs);
}
function roleDetail(t, run, parent, menu) {
  const hit = roleData.get(t.id), data = hit && 'data' in hit ? hit.data : undefined;
  const selected = roleSelectedTab(t), openQs = t.status === 'done' ? [] : questions(t);
  loadRole(t);
  loadArtifacts(t, selected === 'files');
  const runsN = data?.runs?.length, filesN = ticketFileCount(t);
  const tabs = snapshot ? null : h('div', {className:'tabs ticket-tabs', role:'tablist', 'aria-label':'Role'},
    [['overview', 'Overview', null], ['runs', 'Runs', runsN ?? null], ['schedule', 'Schedule', null], ['chat', 'Chat', null], ['files', 'Files', filesN]].map(([id, label, count]) =>
      ticketButton([label, count != null ? ' ' : null, count != null ? h('span', {className:'tab-count'}, String(count)) : null], 'ghost', null,
        {id:'ticket-tab-' + id, role:'tab', 'aria-selected':String(selected === id), 'aria-controls':'ticket-panel-' + id, tabindex:selected === id ? '0' : '-1', 'data-action':'ticket-tab', 'data-ticket':t.id, 'data-tab':id, 'data-key':'ticket-tab-' + id})));
  const panel = (id, label, body, cls = '') => h('section', {id:'ticket-panel-' + id, role:snapshot ? null : 'tabpanel', 'aria-labelledby':snapshot || !ROLE_SHOWN.includes(id) ? null : 'ticket-tab-' + id, 'aria-label':ROLE_SHOWN.includes(id) ? null : label, className:'stack ticket-panel ' + cls, hidden:!snapshot && selected !== id, tabindex:'0'}, snapshot || !ROLE_SHOWN.includes(id) ? h('h2', {}, label) : null, body);
  const total = array(t.checklist).length, done = array(t.checklist).filter(window.DashHelpers.resolved).length;
  return fragment(h('div', {className:'ticket-page role-page', 'data-key':'ticket-page-' + t.id},
    parent ? h('a', {href:href(parent.id), className:'muted ticket-parent'}, 'Sub-ticket of ' + partName(parent)) : null,
    roleHeader(t, run, data, openQs, menu, tabs),
    h('div', {className:'columns ticket-layout' + (selected === 'files' ? ' wide' : '')},
      h('div', {className:'stack story'},
        panel('overview', 'Overview', roleOverview(t, data, openQs)),
        panel('runs', 'Runs', roleRunsPanel(t, data)),
        panel('schedule', 'Schedule', roleSchedulePanel(t, data)),
        panel('chat', 'Chat', roleChatPanel(t, data, openQs), 'role-chat'),
        panel('files', 'Files', artifactsPanel(t)),
        panel('tasks', 'All tasks', card('tasks', 'Tasks', total ? done + ' of ' + total + ' done' : '', [total ? taskRows(t) : emptyRow('No tasks yet.')])),
        panel('activity', 'Everything that happened', ticketHistoryPanel(t))),
      h('div', {className:'stack ticket-side' + (snapshot ? '' : ' rail-sheet'), id:'ticket-rail-' + t.id, 'data-open':String(railOpen.id === t.id), 'aria-label':'About this role', 'data-key':'ticket-rail-' + t.id,
        role:railOpen.id === t.id ? 'dialog' : null, 'aria-modal':railOpen.id === t.id ? 'true' : null},
        roleAbout(t, data), ticketProperties(t, parent), railStamp(t)),
      snapshot || railOpen.id !== t.id ? null : railScrim(t))));
}
