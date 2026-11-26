'use strict';
// Settings, add-on pages and add-on actions.
let settingsTab = 'general', settingsAddon = null;
const settingsBusy = new Set();
// ORCH-227: a choice shows at once, with "Saving…", while it is saved; a click while one saves is sent after it (the
// last click wins). settingsPending holds the picked value per key, settingsQueued the next send.
const settingsPending = new Map(), settingsQueued = new Map();
async function settingsChoose(key, value, send) {
  settingsPending.set(key, value);
  if (settingsBusy.has(key)) { settingsQueued.set(key, send); render(); return null; }
  let result = await send();
  while (settingsQueued.has(key)) {
    const next = settingsQueued.get(key);
    settingsQueued.delete(key);
    result = await next();
  }
  settingsPending.delete(key);
  render();
  return result;
}
const settingsSaving = key => settingsPending.has(key) ? settingsText('span', {className:'meta', role:'status', 'data-key':'settings-saving-' + key}, 'Saving…') : null;
// The add-on's name, the same whether it is on or off (never the lower-case package name, never a tab label).
const rowLabel = a => capitalise(a?.label || a?.dashboard?.label || a?.name || 'add-on');
// "Turning on…" next to a switch while the change runs (it can take half a minute: the services restart).
// While the dashboard restarts after the change: "Waiting for orch to restart…" (ORCH-1046).
const switchBusy = a => settingsBusy.has('addon-' + a.name) ? h('span', {className:'meta', 'data-key':'addon-busy-' + a.name, role:'status'}, addonWaiting.has(a.name) ? ADDON_WAIT_TEXT : a.active ? 'Turning off…' : 'Turning on…') : null;
// A change of the add-ons restarts this page's server: nothing asks it (or an add-on's page) until it is back.
const addonChanging = () => [...settingsBusy].some(k => String(k).startsWith('addon-'));
const asList = value => Array.isArray(value) ? value : [value];
const folderName = path => String(path || '').replace(/[\\/]+$/, '').split(/[\\/]/).pop();
const settingsText = (tag, attrs, value) => {
  const node = h(tag, attrs);
  node.textContent = String(value ?? '');
  return node;
};
const addonOpen = new Set(), agentTests = Object.create(null);
const short = text => { const first = String(text || '').split(/(?<=[.!?])\s/)[0]; return first.length > 70 ? first.slice(0, 67).replace(/\s+\S*$/, '') + '…' : first; };
function addonSummary(addon) {
  if (addon.name === 'dashboard') return 'This page';
  const d = addon.detail;
  if (!addon.active || !d) return short(addon.description);
  if (!d.connected) return 'Not connected yet';
  const n = array(d.workspaces).length;
  return h('span', {className:'on-dot'}, 'Connected' + (n ? ' · ' + n + (n === 1 ? ' workspace' : ' workspaces') : ''));
}
function addonFacts(addon) {
  const d = addon.detail, rows = [];
  const row = (label, value) => h('div', {}, h('dt', {}, label), h('dd', {}, value));
  rows.push(row('Address', [settingsText('span', {className:'mono'}, d.address), h('button', {type:'button', className:'ad-more', 'data-copy':d.address}, 'Copy')]));
  rows.push(row('Status', h('span', {className:'on-dot'}, 'Connected')));
  const ws = array(d.workspaces);
  if (ws.length) rows.push(row('Can talk to', ws.map(w => h('span', {className:w.online ? 'on-dot' : 'off-dot'}, settingsText('span', {}, w.name), settingsText('span', {className:'meta'}, ' · ' + (w.online ? 'Reachable from your phone' : 'Not reachable from your phone'))))));
  return h('dl', {}, rows);
}
const FULL_WARNING = 'Never asks: a helper can change or delete anything in this folder and run any command without asking.';
const PERMISSION_CHOICES = [['ask', 'Asks first', 'Before it changes anything. Example: it asks before editing a file.'], ['auto', 'Asks for risky things', 'It works on its own and asks only when something is risky. Example: it asks before deleting.'], ['full', 'Never asks', 'It changes things without asking. Example: it deletes a file straight away. Only use this if you trust it.']];
function permissionsCard(settings) {
  const saved = PERMISSION_CHOICES.some(([value]) => value === settings.permissions) ? settings.permissions : 'auto';
  const current = settingsPending.has('permissions') ? settingsPending.get('permissions') : saved;
  const rows = PERMISSION_CHOICES.map(([value, label, hint]) => {
    const radio = h('input', {type:'radio', name:'settings-permissions', value, 'data-key':'settings-permissions-' + value, 'data-settings-permissions':value, disabled:snapshot});
    radio.checked = value === current;
    return h('label', {className:'card-row agent-opt' + (value === current ? ' sel' : ''), 'data-key':'settings-permissions-row-' + value}, radio,
      h('div', {className:'grow'}, settingsText('h3', {}, label), settingsText('p', {className:'meta'}, hint)));
  });
  return h('div', {className:'stack', 'data-key':'settings-permissions'}, h('h2', {className:'set-sub'}, 'What a helper may do', ' ', settingsSaving('permissions')),
    h('div', {className:'card'}, h('div', {className:'permission-choices', role:'radiogroup', 'aria-label':'What a helper may do'}, rows),
      current === 'full' ? h('p', {className:'card-row bad', role:'note'}, FULL_WARNING) : null));
}
// What helpers need (ORCH-45, drawn and chosen on ORCH-43): every tool login, connection and key a helper needs here,
// with whether it works, when it runs out and how many tickets it stops. The buttons are Home's (loginAction): Renew
// from the renew step when it is there, else Check again / Try again. Never checked yet or nothing set: no card.
function helperNeedsCard() {
  const D = window.DashHelpers, items = D.needItems(snapshot ? null : state.logins);
  if (!items.length) return null;
  const at = state.logins.checked_at, when = typeof age === 'function' ? age(at) : '';
  const rows = items.map(item => {
    const key = 'settings-need-' + item.name, st = D.needState(item), stops = D.needStopsWord(item.state === 'works' ? 0 : item.stops.length);
    const action = typeof loginAction === 'function' ? loginAction(item, key, item.state === 'works') : null;
    return h('div', {className:'setting-row', 'data-key':key, 'data-state':item.state},
      h('div', {className:'row-label'}, settingsText('span', {}, D.needListName(item)), settingsText('p', {className:'meta'}, D.needKindWord(item))),
      h('div', {className:'row-value'}, h('span', {className:'badge ' + st.tone}, st.word), stops ? settingsText('p', {className:'meta'}, stops) : null,
        typeof loginHow === 'function' ? loginHow(item, key + '-how') : D.needHow(item) ? settingsText('p', {className:'meta', 'data-key':key + '-how'}, D.needHow(item)) : null),
      h('div', {className:'row-action'}, action));
  });
  return h('section', {className:'card', id:'needs', 'data-key':'settings-needs'},
    h('header', {className:'card-h row between'}, h('h3', {}, 'What helpers need'), when ? settingsText('span', {className:'meta', 'data-key':'settings-needs-when'}, 'Checked ' + when) : null),
    rows);
}
// Share with team: off by default; on writes one short entry into the team's AGENTS.md (the orch files stay local).
// Helpers at once (ORCH-16): no limit by default; a number makes the next helper wait in line until one is
// finished. Saved on change, like the copies cap (a select, no typed words).
const LIVE_MAX_CHOICES = [2, 3, 4, 5, 6, 7, 8, 9, 10];
function helpersAtOnceCard(settings) {
  const want = settingsPending.has('live') ? settingsPending.get('live') : settings.live_max;
  const n = LIVE_MAX_CHOICES.includes(want) ? want : null;
  const pick = h('select', {className:'input copies-max', 'aria-label':'Helpers at once', 'data-key':'settings-live-max', disabled:snapshot},
    h('option', {value:'none'}, 'No limit'), LIVE_MAX_CHOICES.map(v => h('option', {value:String(v)}, String(v))));
  pick.value = n ? String(n) : 'none';
  return h('div', {className:'stack', 'data-key':'settings-live'}, h('div', {className:'card'}, h('div', {className:'card-row'},
    h('div', {className:'grow'}, h('h3', {}, 'Helpers at once', ' ', settingsSaving('live')),
      settingsText('p', {}, n ? 'When ' + n + ' helpers are working, the next one waits in line and starts when one is finished.' : 'Any number of helpers can work at the same time.'),
      settingsText('p', {className:'meta'}, 'Pick a number if your computer gets slow with many helpers.')),
    pick)));
}
// "More settings": the technical switches shown plainly at the end of a tab under their own heading, no fold
// (ORCH-1693; owner rule: detail lower down, never a "More" / "Show more" toggle).
function moreSettings(tab, ...cards) {
  return h('div', {className:'stack', 'data-key':'settings-more-' + tab}, h('h2', {className:'set-sub'}, 'More settings'), ...cards.filter(Boolean));
}
function shareCard(settings) {
  const on = settings.share === true;
  return h('div', {className:'stack', 'data-key':'settings-share'},
    h('div', {className:'card'}, h('div', {className:'card-row'},
      h('div', {className:'grow'}, settingsText('h3', {}, 'Tell teammates about orch'),
        settingsText('p', {}, 'Adds a short note to your project’s guide file so your teammates’ helpers know orch is used here.'),
        settingsText('p', {className:'meta'}, 'Example: a colleague’s helper learns how to open your tickets.')),
      h('span', {className:'switch-text', 'aria-hidden':'true'}, on ? 'On' : 'Off'), h('button', {type:'button', className:'switch', role:'switch', 'aria-checked':on, 'aria-label':'Tell teammates about orch', 'data-key':'settings-switch-share', 'data-action':'settings-share', disabled:snapshot || settingsBusy.has('share')})),
      reviewPanel('share', settings)));
}
// The CLI hint stays out of the page: a missing sign-in is said in plain words.
const plainTest = reason => /not logged in|\/login/i.test(String(reason || '')) ? 'The helper is not signed in yet.' : reason;
// Every field the approval covers, in full (name, adapter, command, interactive, prompt).
const pendingText = p => [['Helper', p.name], ['Adapter', p.adapter], ['Command', p.command], ['Live command', p.interactive], ['Prompt', p.prompt]].filter(r => r[1]).map(r => r[0] + ': ' + r[1]).join('\n');
function privateCard(settings) {
  const info = settings.git_private;
  const pending = array(info?.pending);
  const hidden = pending.filter(p => !p.showable).length;
  if (!info || !(info.count > 0 || pending.length)) return null;
  const lines = array(info.lines);
  return h('div', {className:'stack', 'data-key':'settings-private'},
    info.count > 0 ? h('div', {className:'card'}, h('div', {className:'card-row'}, h('div', {className:'grow'},
      settingsText('h3', {}, 'Private files are in your team repo'), settingsText('p', {className:'meta'}, lines[0])),
      snapshot ? null : settingsText('button', {type:'button', className:'btn', 'data-action':'private-move', 'data-key':'settings-private-move', disabled:settingsBusy.has('private')}, 'Move to private'))) : null,
    ...pending.filter(p => p.showable).map(p => h('div', {className:'card', 'data-key':'settings-private-pending-' + p.name}, h('div', {className:'card-row'}, h('div', {className:'grow'},
      settingsText('h3', {}, 'This workspace asks to run a command'), settingsText('pre', {className:'meta mono preserve-lines'}, pendingText(p))),
      snapshot ? null : settingsText('button', {type:'button', className:'btn', 'data-action':'private-allow', 'data-name':p.name, 'data-key':'settings-private-allow-' + p.name, disabled:settingsBusy.has('private')}, 'Allow on this computer')))),
    /* Requests orch cannot show safely cannot be allowed: one card for all of them, not N identical ones. */
    hidden ? h('div', {className:'card', 'data-key':'settings-private-pending-hidden'}, h('div', {className:'card-row'}, h('div', {className:'grow'},
      settingsText('h3', {}, 'This workspace asks to run a command'),
      settingsText('p', {className:'meta'}, hidden + (hidden === 1 ? " request" : " requests") + " orch can't show safely. Not allowed.")))) : null);
}
// Report a problem (diagnostics, D3): the debug log switch (one click) and the saved reports.
function diagCard(settings) {
  const on = settings.diag_enabled !== false, reports = settings.diag?.reports || {};
  const off = snapshot || settingsBusy.has('diag');
  const n = Number(reports.count) || 0;
  return h('div', {className:'stack', 'data-key':'settings-diag'}, h('h2', {className:'set-sub'}, 'Report a problem'), h('div', {className:'card'},
    h('div', {className:'card-row'}, h('div', {className:'grow'}, settingsText('h3', {}, 'Problem log'),
      settingsText('p', {}, 'orch notes steps, errors and timings in the background, so a helper can find out what went wrong. It stays on this computer.'),
      settingsText('p', {className:'meta'}, 'On by default. Keeps the last 7 days. Off stops new notes.')),
      h('span', {className:'switch-text', 'aria-hidden':'true'}, on ? 'On' : 'Off'), h('button', {type:'button', className:'switch', role:'switch', 'aria-label':'Problem log', 'aria-checked':on, 'data-key':'settings-switch-diag', 'data-action':'diag-set', disabled:off})),
    h('div', {className:'card-row name-row'}, h('span', {className:'set-label'}, 'Saved reports'),
      h('p', {className:'grow set-ctl', 'data-key':'settings-diag-reports'}, n === 1 ? '1 report' : n + ' reports', reports.last ? h('span', {className:'meta'}, ' · last ' + time(reports.last)) : null),
      snapshot ? null : h('button', {type:'button', className:'btn ghost sm', 'data-action':'diag-delete-reports', 'data-key':'settings-diag-delete-reports', disabled:off || !n}, 'Delete all')),
    settingsText('p', {className:'card-row meta', 'data-key':'settings-diag-delete-help'}, 'Deletes the saved problem reports on this computer. Your tickets and files stay.')));
}
async function diagSwitch() {
  const on = state.settings?.diag_enabled === false;
  const result = await settingsSend('diag.set', {on}, 'diag');
  if (result.ok) window.orch.toast(on ? 'Problem log is on.' : 'Problem log is off.', 'ok');
}
async function diagDelete() {
  const result = await settingsSend('diag.delete_reports', {}, 'diag');
  if (result.ok) window.orch.toast('Reports deleted.', 'ok');
}
function workflowCard(settings) {
  return h('div', {className:'stack', 'data-key':'settings-workflow'},
    h('div', {className:'card'}, h('div', {className:'card-row'},
      h('div', {className:'grow'}, settingsText('h3', {}, 'Let helpers finish tickets'),
        settingsText('p', {}, 'A helper may mark its own ticket Done. When this is off it asks you to check first.'),
        settingsText('p', {className:'meta'}, 'Example: the helper fixes a typo and closes the ticket; you find it under Done.')),
      h('span', {className:'switch-text', 'aria-hidden':'true'}, settings.agents_may_finish ? 'On' : 'Off'), h('button', {type:'button', className:'switch', role:'switch', 'aria-label':'Let helpers finish tickets', 'aria-checked':!!settings.agents_may_finish, 'data-key':'settings-switch-workflow', 'data-action':'workflow-set', disabled:snapshot || settingsBusy.has('workflow')})),
      reviewPanel('workflow', settings)));
}
// Auto Reviewer (ORCH-1798, owner 24 Nov): turned on here (off by default); the Review page shows its card only while
// a switch is on. The rows are the Review page's own (review.js), so both places say and do the same.
function autoReviewerCard() {
  if (typeof reviewAutoRows !== 'function') return null;
  return h('section', {className:'card', 'data-key':'settings-auto-reviewer'},
    h('header', {className:'card-h'}, h('h3', {}, 'Auto Reviewer')), ...reviewAutoRows('settings'));
}
// Accept small finished work for me (ORCH-77): one switch that saves at once; the Reviewer's work shows on Review.
function reviewerCard(settings) {
  return h('div', {className:'stack', 'data-key':'settings-reviewer'},
    h('div', {className:'card'}, h('div', {className:'card-row'},
      h('div', {className:'grow'}, settingsText('h3', {}, 'Accept small finished work for me'),
        settingsText('p', {className:'meta'}, 'Merged work where all tests passed and no change to looks, words or rules is marked Done for you. You see it on Review and can send any back.')),
      h('span', {className:'switch-text', 'aria-hidden':'true'}, settings.reviewer_on ? 'On' : 'Off'), h('button', {type:'button', className:'switch', role:'switch', 'aria-label':'Accept small finished work for me', 'aria-checked':!!settings.reviewer_on, 'data-key':'settings-switch-reviewer', 'data-action':'reviewer-set', disabled:snapshot || settingsBusy.has('reviewer')})),
      reviewerKindsRow(settings)));
}
// ORCH-645: which kinds of tickets it accepts by itself (the helper sets a ticket's kind). Draft or design is shown
// and never on: drafts, mockups and designs are only accepted by a person.
const REVIEWER_KINDS = [['bug', 'Bug'], ['small_bug', 'Small bug'], ['feature', 'New feature'], ['small_feature', 'Small feature'], ['other', 'Other']];
function reviewerKindsRow(settings) {
  const on = new Set(Array.isArray(settings.reviewer_kinds) ? settings.reviewer_kinds : []);
  const busy = snapshot || settingsBusy.has('reviewer_kinds');
  return h('div', {className:'card-row', 'data-key':'settings-reviewer-kinds'},
    h('div', {className:'grow stack'}, settingsText('p', {}, 'Which kinds of tickets'),
      h('div', {className:'grid-2', role:'group', 'aria-label':'Kinds accepted for me'},
        REVIEWER_KINDS.map(([k, label]) => h('label', {className:'check-label'},
          h('input', {type:'checkbox', value:k, checked:on.has(k) || null, disabled:busy, 'data-action':'reviewer-kind', 'data-kind':k}), label)),
        h('label', {className:'check-label'}, h('input', {type:'checkbox', disabled:true}), 'Draft or design')),
      settingsText('p', {className:'meta'}, 'Drafts, mockups and designs always wait for you.')));
}
// h() writes every value but null as an attribute, so an unticked box gets no checked at all.
// From the saved list, never from the box: the click handler reads the box after the browser may have put it back.
async function reviewerKindToggle(box) {
  const now = new Set(state.settings?.reviewer_kinds || []), k = box.dataset.kind;
  if (now.has(k)) now.delete(k); else now.add(k);
  await settingsSend('reviewer.kinds', {kinds:REVIEWER_KINDS.map(([x]) => x).filter(x => now.has(x))}, 'reviewer_kinds');
}
async function reviewerSwitch() {
  await settingsSend('reviewer.set', {on:state.settings?.reviewer_on !== true}, 'reviewer');
}
// People (ORCH-1161, owner 21 Nov: its own tab, a bit nicer): the workspace's person list. Only here, only at this
// computer (core refuses helpers). Off: the master empty state with Turn on. On: add a person first (the tab's one
// main action), then one row per person: name, what they may do in plain words, the three rights as checkboxes
// (saved on click), Rename and Remove (Remove asks once in the row; the owner has none). Below: what each right
// means, and who was removed (their names stay in the history). A new person starts with Write.
// The words People / Write / Decide / Start work wait for the owner's pick (R4.2, ORCH-1159).
const PEOPLE_RIGHTS = [['write', 'Write', 'Chat, add steps and files.'], ['decide', 'Decide', 'Answer questions and accept drafts.'], ['start', 'Start work', 'Start a helper, which spends your budget, and merge finished work.']];
let peopleRenaming = null, peopleRemoving = null, peopleCutting = null;
function peopleCan(p) {
  if (p.owner) return 'Owner: may do everything and manages the people.';
  const words = {write:'write', decide:'decide', start:'start work'};
  const can = PEOPLE_RIGHTS.map(([id]) => id).filter(id => p.rights.includes(id)).map(id => words[id]);
  if (!can.length) return 'May only read.';
  return 'May ' + (can.length > 1 ? can.slice(0, -1).join(', ') + ' and ' + can[can.length - 1] : can[0]) + '.';
}
const RIGHTS_CARD = () => h('div', {className:'card', 'data-key':'settings-people-rights'}, PEOPLE_RIGHTS.map(([id, label, what]) => h('div', {className:'card-row name-row'}, h('span', {className:'set-label'}, label), settingsText('p', {className:'grow meta'}, what))));
// The plain terminal's typing switch (ORCH-1684): a plain terminal is a shell with the owner's logins and keys, so its
// switch sits in People, the owner's own tab, not on an add-on's page; the server refuses it from anyone else too.
// Shown when an add-on with live sessions is on and the core has the setting.
function terminalTypingCard(settings) {
  const on = settings?.terminal_typing_on;
  if (typeof on !== 'boolean' || !addons().some(a => a.active !== false && a.page?.live_session === true)) return null;
  return h('div', {className:'stack', 'data-key':'settings-terminal-typing'}, h('h2', {className:'set-sub'}, 'Plain terminal'),
    h('div', {className:'card'}, h('div', {className:'card-row name-row', 'data-key':'settings-terminal-typing-row'},
      h('div', {className:'grow'}, settingsText('p', {}, 'Let me type into the plain terminal'), settingsText('p', {className:'meta'}, 'A plain terminal is a shell on this computer. When on, anyone signed in to this dashboard can type commands into it. Only the owner can change this.')),
      h('button', {type:'button', className:'switch', role:'switch', 'aria-checked':on, 'aria-label':'Let me type into the plain terminal', 'data-action':'terminal-typing', 'data-key':'settings-terminal-typing-switch', disabled:snapshot || settingsBusy.has('terminal-typing')}, on ? 'On' : 'Off'))));
}
function peoplePanel(settings) {
  const list = settings.people_list || {state:'off', people:[]};
  const busy = settingsBusy.has('people');
  const intro = h('p', {className:'meta'}, 'Who works in ' + clean(state.workspace || 'this workspace') + ' and what each one may do. Only you can change this.');
  if (list.state === 'broken') return [intro, h('div', {className:'card'}, h('div', {className:'card-row', 'data-key':'settings-people'},
    h('div', {className:'grow'}, settingsText('h3', {}, 'The people list can’t be read'), settingsText('p', {className:'meta'}, 'Nobody but you can do anything until it is set up again. Move the file .orch/local/people.json away, then turn People on here.'))))];
  if (list.state !== 'on') return [intro, h('div', {className:'empty', 'data-key':'settings-people'},
    h('span', {className:'empty-mark', 'aria-hidden':'true'}, '+'), h('h3', {}, 'Only you work here'),
    h('p', {}, 'Turn on People to add the people who work with you and choose what each one may do. You stay the owner.'),
    snapshot ? null : h('button', {type:'button', className:'btn outline sm', 'data-action':'people-on', 'data-key':'settings-people-on', disabled:busy}, 'Turn on'))];
  const active = array(list.people).filter(p => !p.removed), removed = array(list.people).filter(p => p.removed);
  const row = p => {
    const key = 'settings-people-row-' + p.id;
    if (peopleRenaming === p.id) return h('div', {className:'card-row', 'data-key':key},
      h('input', {type:'text', className:'input grow', maxLength:40, value:p.name, 'aria-label':'New name for ' + p.name, 'data-key':'settings-people-rename-name', 'data-people-enter':'people-rename-save', 'data-id':p.id, disabled:busy}),
      h('button', {type:'button', className:'btn primary sm', 'data-action':'people-rename-save', 'data-id':p.id, 'data-key':'settings-people-rename-save', disabled:busy}, 'Save'),
      h('button', {type:'button', className:'btn ghost sm', 'data-action':'people-rename-cancel', 'data-key':'settings-people-rename-cancel'}, 'Cancel'));
    if (peopleRemoving === p.id) return h('div', {className:'card-row', 'data-key':key, role:'alert'},
      h('div', {className:'grow'}, settingsText('h3', {}, 'Remove ' + p.name + '?'), settingsText('p', {className:'meta'}, 'They can’t write, decide or start work here any more. What they did stays in the history with their name.')),
      h('button', {type:'button', className:'btn danger sm', 'data-action':'people-remove-yes', 'data-id':p.id, 'data-key':'settings-people-remove-yes', disabled:busy}, 'Remove'),
      h('button', {type:'button', className:'btn ghost sm', 'data-action':'people-remove-cancel', 'data-key':'settings-people-remove-cancel'}, 'Cancel'));
    const rights = h('div', {className:'row', role:'group', 'aria-label':'Rights of ' + p.name}, PEOPLE_RIGHTS.map(([id, label]) =>
      h('label', {className:'check-label'}, h('input', {type:'checkbox', 'data-people-right':id, 'data-id':p.id, 'data-key':'settings-people-' + p.id + '-' + id, ...(p.owner || p.rights.includes(id) ? {checked:''} : {}), disabled:snapshot || busy || p.owner}), label)));
    // the actions sit under the rights, so the rights keep the whole width at phone size
    const actions = snapshot ? null : h('div', {className:'row'},
      h('button', {type:'button', className:'btn ghost sm', 'data-action':'people-rename', 'data-id':p.id, 'data-key':'settings-people-rename-' + p.id, 'aria-label':'Rename ' + p.name, disabled:busy}, 'Rename'),
      p.owner ? null : h('button', {type:'button', className:'btn ghost sm', 'data-action':'people-remove', 'data-id':p.id, 'data-key':'settings-people-remove-' + p.id, 'aria-label':'Remove ' + p.name, disabled:busy}, 'Remove'));
    return h('div', {className:'card-row', 'data-key':key},
      h('span', {className:'avatar', 'aria-hidden':'true'}, (String(p.name).trim()[0] || '?').toUpperCase()),
      h('div', {className:'grow'}, h('div', {}, h('h3', {}, String(p.name), p.owner ? ' ' : null, p.owner ? h('span', {className:'badge'}, 'Owner') : null), settingsText('p', {className:'meta'}, peopleCan(p))), rights, actions));
  };
  const add = snapshot ? null : h('div', {className:'card'}, h('div', {className:'card-row', 'data-key':'settings-people-add'},
    h('input', {type:'text', className:'input grow', maxLength:40, placeholder:'Name', 'aria-label':'Name of the new person', autocomplete:'off', 'data-key':'settings-people-name', 'data-people-enter':'people-add', disabled:busy}),
    h('button', {type:'button', className:'btn primary sm', 'data-action':'people-add', 'data-key':'settings-people-add-btn', disabled:busy}, 'Add person')));
  const count = active.length === 1 ? '1 person' : active.length + ' people';
  return [intro,
    h('div', {className:'stack', 'data-key':'settings-people'},
      h('h2', {className:'set-sub'}, 'Add a person'), h('p', {className:'meta'}, 'A new person starts with Write. Tick more below.'), add,
      h('h2', {className:'set-sub'}, 'What the rights mean'), RIGHTS_CARD(),
      h('h2', {className:'set-sub'}, count), h('div', {className:'card', 'data-key':'settings-people-list'}, active.map(row))),
    peoplePhones(list, active, busy),
    removed.length ? h('div', {className:'stack', 'data-key':'settings-people-removed'}, h('h2', {className:'set-sub'}, 'Removed'),
      h('div', {className:'card'}, h('div', {className:'card-row'}, settingsText('p', {className:'grow'}, removed.map(p => p.name).join(', ')), settingsText('p', {className:'meta'}, 'Their names stay in the history.')))) : null];
}
// Phones and browsers (step 4, ORCH-1197): every device paired on the relay, and whose it is. A device does nothing
// until it is tied to a person; Cut stops one lost device at once (the relay admin page still lists it until it is
// removed there). A browser signs in on the relay's own page and is tied, cut and checked exactly like a phone.
function peoplePhones(list, active, busy) {
  const phones = array(list.phones);
  if (!phones.length) return null;
  const nameOf = id => (array(list.people).find(p => p.id === id) || {}).name;
  const row = ph => {
    const key = 'settings-people-phone-' + ph.id, owner = nameOf(ph.person), kind = ph.kind === 'browser' ? 'browser' : 'phone';
    if (peopleCutting === ph.id) return h('div', {className:'card-row', 'data-key':key, role:'alert'},
      h('div', {className:'grow'}, settingsText('h3', {}, 'Cut off ' + ph.name + '?'), settingsText('p', {className:'meta'}, 'It can’t write, decide or start work here any more. What it already shows can’t be taken back. Also remove it on the relay admin page.')),
      h('button', {type:'button', className:'btn danger sm', 'data-action':'people-cut-yes', 'data-phone':ph.id, 'data-key':'settings-people-cut-yes', disabled:busy}, 'Cut off'),
      h('button', {type:'button', className:'btn ghost sm', 'data-action':'people-cut-cancel', 'data-key':'settings-people-cut-cancel'}, 'Cancel'));
    const status = ph.cut ? 'Cut off. Also remove it on the relay admin page.'
      : !ph.paired ? 'Not paired with this workspace any more.'
      : owner ? owner + '’s ' + kind + '.' : 'Not tied to anyone yet, so it can’t do anything here.';
    const pick = snapshot ? null : h('select', {'aria-label':'Whose ' + kind + ' is ' + ph.name, 'data-people-phone':ph.id, 'data-key':key + '-who', disabled:busy || !ph.paired},
      h('option', {value:'', ...(owner && !ph.cut ? {} : {selected:''})}, 'Whose?'),
      active.map(p => h('option', {value:p.id, ...(p.id === ph.person && !ph.cut ? {selected:''} : {})}, String(p.name))));
    return h('div', {className:'card-row', 'data-key':key},
      h('div', {className:'grow'}, h('h3', {}, String(ph.name), !ph.person && ph.paired ? ' ' : null, !ph.person && ph.paired ? h('span', {className:'badge'}, 'New') : null), settingsText('p', {className:'meta'}, status)),
      pick,
      snapshot || !ph.person || ph.cut ? null : h('button', {type:'button', className:'btn ghost sm', 'data-action':'people-cut', 'data-phone':ph.id, 'data-key':key + '-cut', 'aria-label':'Cut off ' + ph.name, disabled:busy}, 'Cut off'));
  };
  return h('div', {className:'stack', 'data-key':'settings-people-phones'}, h('h2', {className:'set-sub'}, 'Phones and browsers'),
    h('p', {className:'meta'}, 'Phones and browsers are connected on the relay admin page. Choose whose each one is: only then can it write, decide or start work, as that person may.'),
    h('div', {className:'card'}, phones.map(row)));
}
async function peopleTie(select) {
  const list = state.settings?.people_list || {};
  if (snapshot || !select.value) return;
  const r = await settingsSend('people.tie', {phone:select.dataset.peoplePhone, id:select.value, revision:list.revision}, 'people');
  const ph = array(list.phones).find(x => x.id === select.dataset.peoplePhone) || {};
  if (r.ok) window.orch.toast('Saved. That ' + (ph.kind === 'browser' ? 'browser' : 'phone') + ' now acts as ' + (array(list.people).find(p => p.id === select.value) || {}).name + '.', 'ok');
}
async function peopleAction(action, control) {
  const list = state.settings?.people_list || {}, revision = list.revision;
  const person = array(list.people).find(p => p.id === control?.dataset.id);
  const value = key => (document.querySelector('[data-key="' + key + '"]')?.value || '').trim();
  if (action === 'people-on') {
    const me = state.people?.me;
    const r = await settingsSend('people.on', me ? {name:me} : {}, 'people');
    if (r.ok) window.orch.toast('People is on. You are the owner.', 'ok');
  } else if (action === 'people-add') {
    const name = value('settings-people-name');
    if (!name) { document.querySelector('[data-key="settings-people-name"]')?.focus(); return; }
    const r = await settingsSend('people.add', {name, rights:['write'], revision}, 'people');
    if (r.ok) { window.orch.toast('Added ' + name + '.', 'ok'); document.querySelector('[data-key="settings-people-name"]')?.focus(); }
  } else if (action === 'people-rename' && person) { peopleRenaming = person.id; peopleRemoving = null; render(); document.querySelector('[data-key="settings-people-rename-name"]')?.select();
  } else if (action === 'people-rename-cancel') { peopleRenaming = null; render();
  } else if (action === 'people-rename-save' && person) {
    const name = value('settings-people-rename-name');
    if (!name || name === person.name) { peopleRenaming = null; render(); return; }
    const r = await settingsSend('people.rename', {id:person.id, name, revision}, 'people');
    if (r.ok) { peopleRenaming = null; render(); }
  } else if (action === 'people-remove' && person) { peopleRemoving = person.id; peopleRenaming = null; render(); document.querySelector('[data-key="settings-people-remove-cancel"]')?.focus();
  } else if (action === 'people-cut') { peopleCutting = control.dataset.phone; render(); document.querySelector('[data-key="settings-people-cut-cancel"]')?.focus();
  } else if (action === 'people-cut-cancel') { peopleCutting = null; render();
  } else if (action === 'people-cut-yes') {
    const r = await settingsSend('people.cut', {phone:control.dataset.phone, revision}, 'people');
    if (r.ok) { peopleCutting = null; window.orch.toast('Cut off. Also remove it on the relay admin page.', 'ok'); render(); }
  } else if (action === 'people-remove-cancel') { peopleRemoving = null; render();
  } else if (action === 'people-remove-yes' && person) {
    const r = await settingsSend('people.remove', {id:person.id, revision}, 'people');
    if (r.ok) { peopleRemoving = null; window.orch.toast('Removed ' + person.name + '.', 'ok'); render(); }
  }
}
async function peopleRight(box) {
  const list = state.settings?.people_list || {};
  const person = array(list.people).find(p => p.id === box.dataset.id);
  if (!person || person.owner || snapshot) return;
  const rights = PEOPLE_RIGHTS.map(([id]) => id).filter(id => id === box.dataset.peopleRight ? box.checked : person.rights.includes(id));
  await settingsSend('people.rights', {id:person.id, rights, revision:list.revision}, 'people');
}
// ORCH-971: both switches are about merged pull requests, so a plain folder (no GitHub remote, no pull-requests
// add-on) does not see them. A switch that is already on still shows, so the person can turn it off. #1228: with the
// pull-requests add-on on, the release switch lives on its own settings page instead (releaseMergeRow).
const releaseInAddon = settings => array(settings?.addons).some(a => a.name === 'pull-requests' && a.active);
function prSwitchCards(settings) {
  const has = settings.pull_requests === true;
  return [has || settings.reviewer_on ? reviewerCard(settings) : null, !releaseInAddon(settings) && (has || settings.release_merge_on) ? releaseMergeCard(settings) : null];
}
// Put new versions live without my click (ORCH-79): off = the owner clicks Merge on the release card; on = a release
// with every check green merges by itself (orch review tend-releases). Only a person can turn it on.
function releaseMergeCard(settings) {
  return h('div', {className:'stack', 'data-key':'settings-release-merge'},
    h('div', {className:'card'}, h('div', {className:'card-row'},
      h('div', {className:'grow'}, settingsText('h3', {}, 'Put new versions live without my click'),
        settingsText('p', {className:'meta'}, RELEASE_MERGE_WORDS)),
      h('span', {className:'switch-text', 'aria-hidden':'true'}, settings.release_merge_on ? 'On' : 'Off'), releaseMergeButton(settings))));
}
const RELEASE_MERGE_WORDS = 'A release where all tests passed goes live by itself with your GitHub login. You get the short highlights afterwards. Off: you decide on the card.';
function releaseMergeButton(settings, key = 'settings-switch-release-merge') {
  return h('button', {type:'button', className:'switch', role:'switch', 'aria-label':'Put new versions live without my click', 'aria-checked':!!settings?.release_merge_on, 'data-key':key, 'data-action':'release-merge-set', disabled:snapshot || settingsBusy.has('release_merge')});
}
// The same switch as a row of the pull-requests add-on's own settings page (#1228), same words, same release_merge.set.
function releaseMergeRow(row, settings) {
  return row('Releases', h('div', {}, settingsText('p', {}, 'Put new versions live without my click'), settingsText('p', {className:'meta'}, RELEASE_MERGE_WORDS)),
    releaseMergeButton(settings, 'addon-detail-release-merge'), 'addon-detail-release-merge-row');
}
// Prepare tickets when I save (ORCH-741, draft ORCH-730 section 4): on by default; off = Save without starting
// keeps the ticket as written until Start. Only a person turns it on (it starts helpers).
function prepareCard(settings) {
  return h('div', {className:'stack', 'data-key':'settings-prepare'},
    h('div', {className:'card'}, h('div', {className:'card-row'},
      h('div', {className:'grow'}, settingsText('h3', {}, 'Prepare tickets when I save'),
        settingsText('p', {className:'meta'}, 'When you save a ticket without starting it, a helper writes the title, description, done-when, estimate and first steps. It does no work until you press Start. At most ' + (settings.prepare_daily_limit ?? 30) + ' tickets a day.')),
      h('span', {className:'switch-text', 'aria-hidden':'true'}, settings.prepare_on_save !== false ? 'On' : 'Off'), h('button', {type:'button', className:'switch', role:'switch', 'aria-label':'Prepare tickets when I save', 'aria-checked':settings.prepare_on_save !== false, 'data-key':'settings-switch-prepare', 'data-action':'prepare-set', disabled:snapshot || settingsBusy.has('prepare')}))));
}
async function prepareSwitch() {
  await settingsSend('prepare.set', {on:state.settings?.prepare_on_save === false}, 'prepare');
}
async function releaseMergeSwitch() {
  await settingsSend('release_merge.set', {on:state.settings?.release_merge_on !== true}, 'release_merge');
}
// Separate copies (draft 1f, owner pass 11 Nov): one plain row with a switch; when, how many, what is on this
// computer, how a copy is prepared and what it needs sit behind Details.
const COPY_CHOICES = [['together', 'When helpers work at the same time'], ['always', 'Every time, even for one helper']];
// Text fields on this page: Edit, then the field with Save / Cancel (like Description); switches save at once.
let copySetupEditing = false;
// Review step (owner rule): a change here is one plain click after a shown review: what will happen and what it
// touches, then [Verb] [Cancel]; never a typed word. It opens in place, in the same look as the command review of
// "+ Add your own helper" (.cmd-preview with its .acts row). Only its first button makes the change.
let settingsReview = null, settingsReviewFrom = null;
const SETTINGS_REVIEW_BUSY = {share:'share', workflow:'workflow', 'copies-switch':'copies', 'copies-clean':'copies-clean'};
const copiesModeOf = settings => ['off', 'together', 'always'].includes(settings.copies) ? settings.copies : 'together';
function settingsReviewText(id, settings) {
  if (id === 'share') return settings.share === true
    ? {verb:'Stop sharing', what:'Your team will no longer see that this workspace uses orch.', affects:'The short orch entry is taken out of AGENTS.md. Nothing else in your files changes.'}
    : {verb:'Share', what:'Your team will see that this workspace uses orch.', affects:'A short orch entry is added to AGENTS.md in your team’s files. Everything else from orch stays on this computer.'};
  if (id === 'workflow') return settings.agents_may_finish
    ? {verb:'Turn off', what:'Helpers will ask you to check finished work, and you decide when it is Done.', affects:'Only new finished work. Tickets that are already Done stay Done.'}
    : {verb:'Turn on', what:'Helpers will mark their finished work Done themselves.', affects:'You will not be asked to look at it first. Tickets already waiting for your check stay there.'};
  if (id === 'copies-switch') return copiesModeOf(settings) !== 'off'
    ? {verb:'Turn off', what:'Helpers will all work in your own folder, also when they work at the same time.', affects:'Copies that already exist stay until their ticket is done. Your own files are not touched.'}
    : {verb:'Turn on', what:'When helpers work at the same time, each one gets its own copy of your files.', affects:'At most ' + (settings.copies_max || 3) + ' copies at the same time. They take space on this computer and are removed when their ticket is done. Your own files are not touched.'};
  const n = settings.copies_disk?.copies;
  return {verb:'Clean up', what:'Copies of your files that no helper needs any more will be removed now.',
    affects:(n === 0 ? 'There are no copies right now, so nothing will be removed.'
      : typeof n === 'number' ? 'Up to ' + n + (n === 1 ? ' copy' : ' copies') + ' will be removed, only the ones no ticket needs any more. Saved changes stay in the saved earlier versions.'
      : 'Only copies no ticket needs any more are removed. Saved changes stay in the saved earlier versions.') + ' Your own files are not touched.'};
}
function reviewPanel(id, settings) {
  if (settingsReview !== id || snapshot) return null;
  const r = settingsReviewText(id, settings);
  return h('div', {className:'cmd-preview settings-review', role:'group', tabindex:'-1', 'aria-labelledby':'settings-review-what', 'aria-describedby':'settings-review-affects', 'data-key':'settings-review-' + id},
    settingsText('p', {id:'settings-review-what', className:'settings-review-what'}, r.what),
    settingsText('p', {id:'settings-review-affects', className:'meta'}, r.affects),
    h('div', {className:'acts'},
      settingsText('button', {type:'button', className:'btn sm primary', 'data-key':'settings-review-ok', 'data-action':'settings-review-ok', disabled:settingsBusy.has(SETTINGS_REVIEW_BUSY[id])}, r.verb),
      settingsText('button', {type:'button', className:'btn sm ghost', 'data-key':'settings-review-cancel', 'data-action':'settings-review-cancel'}, 'Cancel')));
}
function copiesDiskText(d) {
  if (!d || typeof d.copies !== 'number') return 'Counting…';
  const n = d.copies, b = Number(d.bytes) || 0;
  const size = b >= 1e9 ? (b / 1e9).toFixed(1) + ' GB' : b >= 1e6 ? Math.round(b / 1e6) + ' MB' : b > 0 ? 'under 1 MB' : '0 MB';
  const gone = array(d.orphaned).reduce((sum, o) => sum + (Number(o.copies) || 0), 0);
  return (n ? n + (n === 1 ? ' copy' : ' copies') + ' · ' + (d.partial ? 'more than ' : '') + size + ' · removed by themselves when a ticket is done' : 'None right now · a copy is removed by itself when its ticket is done')
    + (gone ? ' · ' + gone + (gone === 1 ? ' copy' : ' copies') + ' from a moved or deleted project' : '')
    + (d.changed ? ' · ' + d.changed + (d.changed === 1 ? ' removed copy' : ' removed copies') + ' changed after being saved, kept for you to look at' : '')
    + array(d.stuck).map(() => ' · a copy could not be cleaned up').join('');
}
function copiesCard(settings) {
  const mode = copiesModeOf(settings), on = mode !== 'off', busy = settingsBusy.has('copies');
  const disk = settings.copies_disk, off = snapshot || busy;
  const cap = h('select', {className:'input copies-max', 'aria-label':'Most copies at the same time', 'data-key':'settings-copies-max', disabled:off},
    [1, 2, 3, 4, 5, 6, 8, 10, 20].map(n => h('option', {value:String(n)}, String(n))));
  cap.value = String(settings.copies_max || 3);
  const setup = copySetupEditing && !snapshot
    ? h('div', {className:'copies-setup-edit'}, h('input', {type:'text', className:'input copies-setup', maxLength:500, value:settings.copy_setup || '', placeholder:'For example: install the packages', 'aria-label':'Get each working copy ready with', 'data-key':'settings-copy-setup', disabled:busy}),
      h('div', {className:'row'}, h('button', {type:'button', className:'btn sm primary', 'data-key':'settings-copy-setup-save', 'data-action':'copies-setup', disabled:busy}, 'Save'),
        h('button', {type:'button', className:'btn sm ghost', 'data-key':'settings-copy-setup-cancel', 'data-action':'copies-setup-cancel'}, 'Cancel')))
    : h('div', {className:'row copies-setup-view'}, settingsText('p', {className:settings.copy_setup ? 'grow mono' : 'grow meta'}, settings.copy_setup || 'Nothing'),
      snapshot ? null : h('button', {type:'button', className:'btn sm', 'data-key':'settings-copy-setup-edit', 'data-action':'copies-setup-edit'}, 'Edit'));
  const row = (title, hint, ...rest) => h('div', {className:'copies-sub'}, settingsText('h3', {}, title), hint ? settingsText('p', {className:'meta'}, hint) : null, ...rest);
  return h('div', {className:'stack', 'data-key':'settings-copies'},
    h('div', {className:'card'},
      h('div', {className:'card-row'}, h('div', {className:'grow'}, settingsText('h3', {}, 'Several helpers at once'),
        settingsText('p', {}, 'Each helper works in its own copy of your folder, so two helpers never change the same file.'),
        settingsText('p', {className:'meta'}, 'Example: one helper writes the newsletter while another fixes the website.')),
        h('span', {className:'switch-text', 'aria-hidden':'true'}, on ? 'On' : 'Off'), h('button', {type:'button', className:'switch', role:'switch', 'aria-checked':on, 'aria-label':'Several helpers at once', 'data-key':'settings-switch-copies', 'data-action':'copies-switch', 'data-mode':on ? 'off' : 'together', disabled:off})),
      reviewPanel('copies-switch', settings),
      !on ? null : h('div', {className:'copies-details', 'data-key':'settings-copies-details'},
        h('div', {className:'stack copies-more'},
          row('When', '', h('div', {className:'row copies-choices', role:'radiogroup', 'aria-label':'When each helper gets its own copy'}, COPY_CHOICES.map(([id, label]) =>
            h('button', {type:'button', className:'btn sm ' + (mode === id ? 'primary' : 'ghost'), role:'radio', 'aria-checked':mode === id, 'data-key':'settings-copies-' + id, 'data-action':'copies-mode', 'data-mode':id, disabled:off || !on}, label)))),
          row('Most copies at the same time', 'When this many exist, the next helper works in your own folder.', cap),
          h('div', {className:'copies-sub', 'data-key':'settings-copies-disk'}, settingsText('h3', {}, 'Copies on this computer'), settingsText('p', {className:'meta'}, copiesDiskText(disk)),
            h('div', {className:'row'},
              array(disk?.stuck).length ? h('button', {type:'button', className:'btn sm ghost', 'data-key':'settings-copies-retry', 'data-action':'copies-retry', disabled:off || settingsBusy.has('copies-clean')}, 'Try again') : null,
              array(disk?.orphaned).length ? h('button', {type:'button', className:'btn sm ghost', 'data-key':'settings-copies-orphaned', 'data-action':'copies-orphaned', disabled:off || settingsBusy.has('copies-clean')}, 'Remove the moved ones') : null,
              h('button', {type:'button', className:'btn sm outline', 'data-key':'settings-copies-clean', 'data-action':'copies-clean', disabled:off || settingsBusy.has('copies-clean')}, 'Clean up now')),
            reviewPanel('copies-clean', settings)),
          row('Get each working copy ready with', 'Runs once in each new copy, for example to install what the project needs.', setup),
          settingsText('p', {className:'meta'}, 'Needs saved earlier versions in this folder. When a copy is removed, its saved changes stay in the saved earlier versions.')))));
}
// Sync (draft sync-card.html, Variant A): Settings › General, below Workspace. Every fact and change goes through
// the sync add-on's own verbs on the ONE generic op: `orch sync act status|check|set|now|use-public -- <target>`.
// The address and the choice come only from the person's clicks here; choices that decide for the person are signed.
const SYNC = 'sync';
// Each choice says what it does in one line below it (bug hunt 17 Nov: three bare choices).
const SYNC_WHERE = [['off', 'Off', 'No copy is kept.'],
  ['local', 'On this computer only', 'Saves earlier versions in the workspace folder every 5 minutes. Nothing is sent to another device.'],
  ['remote', 'Another computer or your own storage', 'A copy in a private place you own, such as a GitHub repository. You give its address next.']];
const SYNC_EVERY = [['5', '5 min'], ['15', '15 min'], ['60', '1 hour']];
const SYNC_PUBLIC = 'This sync address is public. Anyone can read your tickets.';
const SYNC_STATUS = {synced:['ok', 'Last synced'], never:['', 'Not synced yet'], offline:['', 'Offline, will sync when connected'], syncing:['live', 'Syncing…'], paused:['you', 'Paused, review below']};
// card = the add-on's last status answer; draft = the person's unsaved choice (the review line shows while it differs)
const syncUi = {card:null, loading:false, failed:false, draft:null, check:null, note:'', busy:false, nowBusy:false, details:false, wasOff:false, timer:null};
const syncSaved = card => ({where:card?.mode === 'remote' ? 'remote' : card?.mode === 'local' ? 'local' : 'off', addr:card?.mode === 'remote' ? card.remote || '' : '', every:String(card?.interval && card.mode === 'remote' ? card.interval : 15)});
const syncNow = () => syncUi.draft || syncSaved(syncUi.card);
const syncSame = (a, b) => a.where === b.where && (a.where !== 'remote' || (a.addr === b.addr && a.every === b.every));
const syncHost = addr => { const text = String(addr || '').trim(); const scp = /^[^@\s/]+@([^:\s/]+):/.exec(text); if (scp) return scp[1]; try { return new URL(text).host || text; } catch (_) { return text; } };
const syncEveryLabel = every => (SYNC_EVERY.find(([v]) => v === String(every)) || SYNC_EVERY[1])[1];
// The shapes sync takes (https, ssh, git@host:path; a plain path or file: only for a test install): anything else is wrong before Save
const syncAddrOk = addr => { const t = String(addr || '').trim(); return !/\s/.test(t) && (/^(https|ssh):\/\/[^/\s:@]+/i.test(t) || /^git@[A-Za-z0-9.-]+:\S+$/.test(t) || /^(\/|file:)/.test(t)); };
const SYNC_BAD_ADDR = 'This is not a valid sync address. Use one that starts with https:// or ssh://, or looks like git@host:name.';
function syncReviewText(s) {
  if (s.where === 'off') return 'Sync will stop. Your tickets stay on this computer as they are.';
  if (s.where === 'local') return 'Sync will keep a copy on this computer only.';
  if (!s.addr.trim()) return 'Enter a sync address first.';
  if (!syncAddrOk(s.addr)) return SYNC_BAD_ADDR;
  return 'Sync will copy tickets to ' + syncHost(s.addr) + ' every ' + syncEveryLabel(s.every) + '.';
}
// One click on the sync add-on's own verb; its answer comes back as state.act_answer.
async function syncAct(verb, target, extra = {}) {
  const result = await act('addon.act', {addon:SYNC, verb, target, ...extra});
  if (verb !== 'status' && verb !== 'check' && typeof addonViews === 'object') delete addonViews[SYNC];  // the Sync page's saved view is old now: it asks again, so Settings and the page agree (ORCH-184)
  const answer = result.ok && result.state?.act_answer?.addon === SYNC ? result.state.act_answer.answer : null;
  return {...result, answer};
}
// The card's status is a read, not a click (ORCH-413): GET with the rights of /api/state, so a page opened without a
// signed-in session shows the setting and sends no click that is refused (no 'Sign in to do this' banner).
async function syncRead() {
  try {
    const res = await fetch('/api/addon-read?addon=' + SYNC + '&verb=status', {cache:'no-store'});
    const answer = res.ok ? await res.json() : null;
    return {ok:res.ok, answer:answer && typeof answer === 'object' && !Array.isArray(answer) ? answer : null};
  } catch (_) { return {ok:false, answer:null}; }
}
// The Sync card lives in Settings › General and on the Sync page itself (#addon/sync): both change settings in place.
// The settings say Sync is installed but off (ORCH-960): the 15 s look stops instead of reading a status that is refused.
const syncTurnedOff = () => array(state.settings?.addons).find(a => a.name === SYNC)?.active === false;
const syncPageOpen = () => { const r = route(); return r.kind === 'settings' || (r.kind === 'addon' && r.id === SYNC); };
async function syncLoad() {
  if (syncUi.loading || snapshot) return;
  clearTimeout(syncUi.timer); syncUi.timer = null;
  if (addonChanging()) { syncUi.timer = setTimeout(syncLoad, 3000); return; }  // the server is restarting: look again soon
  if (!syncPageOpen()) return;  // the page was left: it loads again when Settings or the Sync page opens
  if (syncTurnedOff()) return;  // Sync was turned off: no status read (it would be refused); it loads again once it is on
  syncUi.loading = true;
  try {
    const result = await syncRead();
    syncUi.failed = !(result.answer && typeof result.answer.shown === 'string');
    if (!syncUi.failed) {
      syncUi.card = result.answer;
      // just turned on here: "On this computer only" is offered, the person saves it in the review line
      if (syncUi.wasOff && result.answer.mode === 'off' && !syncUi.draft) syncUi.draft = {where:'local', addr:'', every:'15'};
      syncUi.wasOff = false;
    }
  } finally {
    syncUi.loading = false;
    syncUi.timer = setTimeout(syncLoad, 15000);  // before render: a render never starts a second load
    render();
  }
}
const syncStatusText = card => card.shown === 'synced' ? 'Last synced ' + (time(card.last_ok) || '') : (SYNC_STATUS[card.shown] || SYNC_STATUS.never)[1];
function syncStatusLine(card) {
  const shown = syncUi.nowBusy ? 'syncing' : card.shown, [dot] = SYNC_STATUS[shown] || SYNC_STATUS.never;
  const text = syncUi.nowBusy ? 'Syncing…' : syncStatusText(card);
  let label = text;
  if (shown === 'paused') {
    label = h('a', {href:'#home', 'data-key':'sync-paused-link'}, text);
    label.addEventListener('click', event => { event.preventDefault(); location.hash = '#home'; requestAnimationFrame(() => { const n = document.getElementById('needs-you'); if (n) { n.scrollIntoView({block:'start'}); n.focus({preventScroll:true}); } }); });
  }
  const n = array(card.not_synced).length;
  const skipped = n ? h('button', {type:'button', className:'sync-skipped', 'aria-controls':'sync-details', 'data-key':'sync-skipped'}, n + (n === 1 ? ' file not synced' : ' files not synced')) : null;
  skipped?.addEventListener('click', () => { syncUi.details = true; render(); });
  return h('span', {className:'sync-status-line', 'data-key':'sync-status-line'},
    h('span', {className:'sync-status' + (shown === 'paused' ? ' you' : ''), role:'status', 'data-key':'sync-status'}, h('span', {className:'dot ' + dot, 'aria-hidden':'true'}), label), skipped);
}
// "Not synced: tickets/t_x.json: secret" in the words a person reads; other texts stay as the add-on wrote them.
const SYNC_WHY = {secret:'it may contain a password or access key', path:'its name or folder is never synced', 'cannot-check':'it could not be checked'};
const SYNC_STOP = {secret:'a ticket or file may contain a password or access key', path:'a file name or folder is never synced', 'cannot-check':'a file could not be checked'};
function syncPlainError(text) {
  const m = /^Not synced: (.+): (secret|path|cannot-check)$/.exec(String(text));
  if (!m) return String(text);
  const file = m[1].split('/').pop();
  return 'Not synced: ' + file + ' (' + SYNC_WHY[m[2]] + ').';
}
function syncLastError(card) {
  if (!card.last_error) return 'Last error: none';
  const when = time(card.last_try);
  return 'Last error' + (when ? ' ' + when : '') + ': ' + (card.last_error === 'offline' ? 'could not reach the sync address.' : syncPlainError(card.last_error));
}
// Paused: what is wrong in one plain line, and the one button that goes to the place where the person decides.
function syncPausedHelp(card) {
  const m = /^Not synced: .+: (secret|path|cannot-check)$/.exec(String(card.last_error || ''));
  const what = m ? 'Sync stopped: ' + SYNC_STOP[m[1]] + '.' : 'Sync stopped: something needs your decision.';
  const go = h('a', {className:'btn primary sm', href:'#home', 'data-key':'sync-paused-button'}, 'Review it now');
  go.addEventListener('click', event => { event.preventDefault(); location.hash = '#home'; requestAnimationFrame(() => { const n = document.getElementById('needs-you'); if (n) { n.scrollIntoView({block:'start'}); n.focus({preventScroll:true}); } }); });
  return h('div', {className:'sync-warn sync-paused', 'data-key':'sync-paused-help'}, h('p', {}, what), h('div', {className:'row'}, go));
}
// ---- The Sync page (fb18): where, what and when, the last 5 syncs, one plain error with one button. ----
const syncSize = n => n >= 1e6 ? Math.round(n / 1e6) + ' MB' : n > 0 ? Math.max(1, Math.round(n / 1e3)) + ' KB' : '0 KB';
const syncWhen = value => time(value);
function syncInfo(card) {
  if (!card || card.mode === 'off') return null;
  const c = card.counts || {tickets:0, files:0, bytes:0}, remote = card.mode === 'remote' && card.remote;
  const box = (key, title, ...body) => h('section', {className:'card', 'data-key':key}, h('header', {className:'card-h'}, h('h3', {}, title)), h('div', {className:'card-row sync-info-body'}, h('div', {className:'stack'}, ...body)));
  const failed = card.shown === 'offline' || (card.last_error && card.shown !== 'paused' && card.shown !== 'syncing');
  const banner = failed ? h('div', {className:'banner error', role:'alert', 'data-key':'sync-error'},
    h('div', {className:'grow'}, h('strong', {}, 'The last sync did not finish.'),
      h('p', {}, card.shown === 'offline' || card.last_error === 'offline' ? 'orch could not reach your storage. Check the address or your internet connection.' : 'orch will try again by itself, or you can try now.')),
    (() => { const b = button('Try again', 'primary sm', syncNowClick); b.dataset.key = 'sync-error-retry'; return b; })()) : null;
  const history = array(card.history).slice(0, 5);
  return h('div', {className:'stack', 'data-key':'sync-info'}, banner,
    h('div', {className:'grid-3'},
      box('sync-where-info', 'Backup destination',
        h('strong', {}, remote ? 'Your storage repository' : card.mode === 'remote' ? 'Choose a storage address below' : 'Workspace folder only'),
        remote ? h('div', {className:'more-text'}, h('p', {className:'meta'}, card.remote)) : null,
        h('div', {className:'more-text'}, h('p', {className:'meta'}, 'Local history: ' + (card.folder_path || (card.folder ? card.folder + '/.orch' : 'the workspace’s .orch folder')))),
        !remote ? h('p', {className:'meta'}, 'No backup on another device.') : null),
      box('sync-what-info', 'What is backed up', h('strong', {}, 'Tickets and their attached files'),
        h('p', {className:'meta'}, 'Saved locally: ' + c.tickets + (c.tickets === 1 ? ' ticket · ' : ' tickets · ') + c.files + (c.files === 1 ? ' file · ' : ' files · ') + syncSize(c.bytes)),
        h('p', {className:'meta'}, 'Other workspace files, settings, passwords and keys are not included.' + (array(card.not_synced).length ? ' Skipped files are listed below.' : ''))),
      box('sync-when-info', 'When', h('strong', {}, 'Every ' + (card.interval || (card.mode === 'local' ? 5 : 15)) + ' minutes while running'),
        h('p', {className:'meta'}, 'Last successful sync: ' + (syncWhen(card.last_ok) || 'not yet')),
        h('p', {className:'meta', 'data-key':'sync-service'}, card.shown === 'paused' ? 'Paused. Review what needs you below.' : !card.running ? 'Sync is stopped. Turn backup off and on to restart.' : card.shown === 'offline' ? 'Waiting for a connection. Sync retries automatically.' : 'Next: ' + (syncWhen(card.next_run) || 'waiting for the first run')))),
    history.length ? h('section', {className:'card', 'data-key':'sync-history'}, h('header', {className:'card-h'}, h('h3', {}, 'Last ' + history.length + (history.length === 1 ? ' sync' : ' syncs'))),
      history.map(e => h('div', {className:'card-row', 'data-key':'sync-history-row'}, h('span', {className:'dot ' + (e.ok ? 'ok' : 'bad'), 'aria-hidden':'true'}), h('span', {className:'meta'}, syncWhen(e.at)), h('span', {className:'grow'}, capitalise(e.text || ''))))) : null);
}
function syncCard(settings) {
  const addon = array(settings.addons).find(a => a.name === SYNC);
  if (!addon || snapshot) return null;
  // aria-busy until the setting is read: orch shot waits for it instead of picturing the placeholder (ORCH-2021)
  const wrap = (body, busy = false) => h('div', {className:'stack sync-wrap', 'data-key':'settings-sync'}, h('div', {className:'card sync-card', id:'sync-card', 'aria-busy':busy ? 'true' : 'false'}, body));
  if (!addon.active) {
    syncUi.wasOff = true; syncUi.card = null; syncUi.draft = null;
    clearTimeout(syncUi.timer); syncUi.timer = null;  // turned off: the 15 s status look stops (ORCH-960)
    return wrap(h('div', {className:'card-row'}, h('span', {className:'grow sync-lbl'}, 'Keep a copy of my tickets'),
      h('span', {className:'switch-text', 'aria-hidden':'true'}, 'Off'), h('button', {type:'button', className:'switch', role:'switch', 'aria-checked':false, 'aria-label':'Keep a copy of my tickets', 'data-key':'settings-switch-sync-off', 'data-action':'settings-addon', 'data-name':addon.name, disabled:settingsBusy.has('addon-' + addon.name)})));
  }
  const card = syncUi.card;
  if (!syncUi.loading && !syncUi.timer) queueMicrotask(syncLoad);  // then every 15 s while Settings is open
  const cur = syncNow(), saved = syncSaved(card), changed = !!card && !syncSame(cur, saved), off = !card || syncUi.busy;
  const paused = card?.shown === 'paused', blocked = paused || !!card?.public;
  const radios = SYNC_WHERE.map(([value, label, says]) => {
    const radio = h('input', {type:'radio', name:'sync-where', value, 'data-sync-where':value, 'data-key':'sync-where-' + value, disabled:off});
    radio.checked = !!card && cur.where === value;  // no choice is shown before the real status is read (ORCH-287)
    radio.addEventListener('change', () => { syncUi.draft = {...syncNow(), where:value}; render(); });
    return h('label', {className:'card-row radio-row', 'data-key':'sync-where-row-' + value}, radio,
      h('span', {className:'radio-text'}, h('span', {}, label), h('span', {className:'meta', 'data-key':'sync-where-says-' + value}, says)));
  });
  const addr = h('input', {type:'text', className:'input mono', id:'sync-addr', 'data-key':'sync-addr', 'data-settings-field':'sync-addr', value:cur.addr, placeholder:'https://github.com/your-name/orch-copy', spellcheck:'false', autocomplete:'off', disabled:off});
  addr.addEventListener('input', () => { syncUi.draft = {...syncNow(), addr:addr.value}; syncUi.check = null; render(); });
  const check = button('Check connection', '', async () => {
    const target = (syncNow().addr || '').trim();
    if (!target) { syncUi.check = {state:'bad'}; render(); return; }
    syncUi.check = {state:'checking'}; render();
    const result = await syncAct('check', target);
    syncUi.check = {state:result.answer?.ok === true ? 'ok' : 'bad'};
    render();
  });
  check.dataset.key = 'sync-check';
  const res = syncUi.check ? h('span', {className:'check-res' + (syncUi.check.state === 'ok' ? ' ok' : syncUi.check.state === 'bad' ? ' bad' : ''), role:'status', 'data-key':'sync-check-res'},
    syncUi.check.state === 'checking' ? null : iconEl(syncUi.check.state === 'ok' ? 'check' : 'x'),
    syncUi.check.state === 'checking' ? 'Checking…' : syncUi.check.state === 'ok' ? 'Connection works' : 'Can’t reach this address') : null;
  const chips = SYNC_EVERY.map(([value, label]) => {
    const chip = h('button', {type:'button', className:'sync-chip', 'aria-pressed':cur.every === value, 'data-key':'sync-every-' + value, disabled:off}, label);
    chip.addEventListener('click', () => { syncUi.draft = {...syncNow(), every:value}; render(); });
    return chip;
  });
  const now = h('button', {type:'button', className:'btn ' + (blocked ? 'ghost' : 'primary'), 'data-key':'sync-now', disabled:off || syncUi.nowBusy || saved.where === 'off'}, iconEl('refresh'), 'Sync now');
  now.addEventListener('click', syncNowClick);
  const remoteBox = cur.where === 'remote' ? h('div', {className:'sync-sub', 'data-key':'sync-remote'},
    h('div', {className:'sync-field'}, h('label', {className:'meta', for:'sync-addr'}, 'Sync address'), h('div', {className:'sync-field-line'}, addr, check), res,
      h('span', {className:'meta', 'data-key':'sync-addr-example'}, 'For example: github.com/your-name/orch-copy, a private repository you own.')),
    h('div', {className:'sync-every'}, h('span', {className:'meta', id:'sync-every-lbl'}, 'Sync every'), h('div', {className:'sync-chips', role:'group', 'aria-labelledby':'sync-every-lbl'}, chips)),
    h('div', {className:'sync-act'}, now, syncUi.note ? h('span', {className:'sync-note', role:'status', 'data-key':'sync-note'}, syncUi.note) : null)) : null;
  const review = changed ? h('div', {className:'sync-review', role:'group', 'aria-label':'Review before saving', 'data-key':'sync-review'},
    h('p', {'data-key':'sync-review-text'}, syncReviewText(cur)),
    h('div', {className:'row'}, button('Undo', 'quiet', () => { syncUi.draft = null; syncUi.check = null; render(); }), (() => {
      const save = button('Save', 'primary', syncSave);
      save.dataset.key = 'sync-review-save';
      save.disabled = syncUi.busy || (cur.where === 'remote' && (!cur.addr.trim() || !syncAddrOk(cur.addr)));
      return save;
    })())) : null;
  const warn = card?.public ? h('div', {className:'sync-warn', role:'alert', 'data-key':'sync-public'}, h('p', {}, SYNC_PUBLIC),
    h('div', {className:'row'}, button('Use public location', '', () => signedAct({addon:SYNC, verb:'use-public', target:'pending'}, 'Using the public location.', syncLoad)),
    button('Keep on this computer', '', async () => {
      syncUi.busy = true; render();
      const r = await syncAct('set', 'local');
      syncUi.busy = false; syncUi.draft = null;
      window.orch.toast(r.ok ? 'Your tickets stay on this computer only.' : r.text, r.ok ? 'ok' : 'error');
      await syncLoad();
    }))) : null;
  const notSynced = array(card?.not_synced);
  const details = card && card.mode !== 'off' && (card.last_error || notSynced.length) ? h('div', {className:'sync-details', id:'sync-details', 'data-key':'sync-details'},
    h('ul', {}, card.last_error ? h('li', {'data-key':'sync-last-error'}, syncLastError(card)) : null, notSynced.map((f, i) => h('li', {'data-key':'sync-not-synced-' + i}, 'Not synced: ' + f.name + (f.why ? ' (' + f.why + ')' : ''))))) : null;
  // The Sync page's When card already says "Last: …": its own card shows the status line only when it adds something.
  const page = route().kind === 'addon';
  const status = card && card.mode !== 'off' && (!page || syncUi.nowBusy || card.shown !== 'synced' || notSynced.length) ? syncStatusLine(card) : null;
  const retry = () => { const b = button('Try again', 'outline sm', () => { syncUi.failed = false; render(); return syncLoad(); }); b.dataset.key = 'sync-unread-retry'; return b; };
  const unread = card ? null : syncUi.failed
    ? h('div', {className:'sync-warn', role:'alert', 'data-key':'sync-unread'}, h('p', {}, 'Can’t read the sync setting right now. Nothing was changed.'), retry())
    : h('p', {className:'meta sync-unread', role:'status', 'data-key':'sync-unread'}, 'Reading the sync setting…');
  return wrap([
    // On the Sync page its heading already says Sync: the card heading names the choice instead, like the cards above it.
    page ? h('header', {className:'card-h', 'data-key':'sync-where-head'}, h('h3', {id:'sync-where-title'}, 'Where to keep a copy'), status)
      : h('div', {className:'sync-head'}, h('h3', {}, 'Backup'), status),
    paused && card.mode !== 'off' ? syncPausedHelp(card) : null,
    warn,
    page ? h('fieldset', {className:'sync-where', 'aria-labelledby':'sync-where-title'}, radios)
      : h('fieldset', {className:'sync-where'}, h('legend', {className:'meta'}, 'Where to keep a copy'), radios),
    unread,
    remoteBox, review, details], !card);
}
async function syncSave() {
  const s = syncNow();
  if (syncUi.busy || (s.where === 'remote' && (!s.addr.trim() || !syncAddrOk(s.addr)))) return;
  const saved = syncSaved(syncUi.card), sameAddr = s.where === 'remote' && saved.where === 'remote' && syncUi.card?.confirmed === true && s.addr.trim() === saved.addr;  // an unconfirmed address is never a 'same address' shortcut
  if (s.where === 'remote' && !sameAddr) {
    // choosing the sync address is the person's signed choice: the sign step shows the address the add-on returns
    await signedAct({addon:SYNC, verb:'set', target:s.addr.trim(), value:s.every}, 'Sync address chosen.', async result => {
      if (result.ok) { syncUi.draft = null; syncUi.note = ''; }
      await syncLoad();
    });
    return;
  }
  syncUi.busy = true; render();
  const result = sameAddr ? await syncAct('set', s.addr.trim(), {value:s.every}) : await syncAct('set', s.where);  // how often: unsigned
  syncUi.busy = false;
  if (!result.ok) { window.orch.toast(result.text || 'That did not work.', 'error'); render(); return; }
  syncUi.draft = null; syncUi.note = '';
  if (!result.answer?.public) window.orch.toast('Saved.', 'ok');
  await syncLoad();
}
// Sync now never clears a pause or a public address that waits: the add-on says what still needs the person.
async function syncNowClick() {
  if (syncUi.nowBusy) return;
  syncUi.nowBusy = true; syncUi.note = ''; render();
  const result = await syncAct('now', SYNC);
  syncUi.nowBusy = false;
  if (!result.ok) window.orch.toast(result.text || 'That did not work.', 'error');
  else if (result.answer?.still_paused || result.answer?.choose_first) syncUi.note = String(result.answer.text || '');
  await syncLoad();
}
// A signed add-on click in two phases: the add-on says what it signs ({target, review}, worked out from the same bytes
// the target hashes), the sign step shows exactly that review (never the row's or the page's own text), and Sign
// echoes the target it showed (`seen`): the server mints only while the add-on still names that same target.
async function signedAct(args, done, after) {
  const asked = await act('addon.act', {...args, review:true});
  const got = asked.ok && asked.state?.act_answer?.addon === args.addon ? asked.state.act_answer.answer : null;
  if (!got || !got.review || typeof got.review.title !== 'string') {
    window.orch.toast(asked.text || 'This can’t be confirmed right now. Nothing was changed.', 'error');
    return null;
  }
  const {title, body, here, there, value} = got.review;
  return signStep({title, body, here, there, value, done, run:async () => {
    const result = await act('addon.act', {...args, sign:true, seen:typeof got.target === 'string' ? got.target : null});
    if (after) await after(result);
    return result;
  }});
}
// The person's sign step (the draft's modal): what will happen, the exact value signed (an address, a file, a peer's
// value), both versions when there are two, "You confirm this as <name>", then Confirm. No typed word.
function signStep({title, body, here, there, value, done, run}) {
  const {d, actions} = dialog(String(title || ''), 'dialog confirm-step');
  const sides = here || there ? h('ul', {className:'confirm-sides'}, h('li', {}, h('b', {}, 'Here:'), ' ', String(here || '')), h('li', {}, h('b', {}, 'Other computer:'), ' ', String(there || ''))) : null;
  const shown = value ? settingsText('p', {className:'mono confirm-value', 'data-key':'confirm-value'}, String(value)) : null;
  const who = name(state?.who) || 'you';
  const sign = h('button', {type:'button', className:'btn primary', 'data-key':'confirm-ok'}, iconEl('shield'), 'Confirm');
  let pending = false;
  d.addEventListener('cancel', event => { if (pending) event.preventDefault(); });
  sign.addEventListener('click', async () => {
    if (pending) return;
    pending = true;
    actions.querySelectorAll('button').forEach(b => { b.disabled = true; });
    const result = await run();
    await window.orch.close(d);
    window.orch.toast(result?.ok ? 'Confirmed. ' + (done || '') : result?.text || 'That did not work.', result?.ok ? 'ok' : 'error');
  });
  actions.append(sign);
  d.append(...[shown, sides, body ? settingsText('p', {className:'meta'}, body) : null, settingsText('p', {className:'meta'}, 'You confirm this as ' + who + '.'), actions].filter(Boolean));
  window.orch.open(d);
  return d;
}
// Short summaries with a direct way to the place that changes them (draft: Everyday settings).
function everydayCard(settings, phoneAddon) {
  const chosen = array(settings.agents).find(a => a.chosen);
  const go = (tab, label, key) => h('button', {type:'button', className:'btn ghost sm', 'data-action':'settings-tab', 'data-tab':tab, 'data-key':key}, label + ' →');
  const row = (label, value, action, key) => h('div', {className:'card-row name-row', 'data-key':key}, h('span', {className:'set-label'}, label), settingsText('p', {className:'grow set-ctl'}, value), snapshot ? null : action);
  return h('div', {className:'stack', 'data-key':'settings-everyday'}, h('h2', {className:'set-sub'}, 'Everyday settings'), h('div', {className:'card'},
    row('Helper', chosen ? chosen.label : 'No helper chosen yet', go('agent', 'Manage', 'settings-everyday-helper'), 'settings-everyday-helper-row'),
    phoneAddon ? row('Phone questions', state.mobile_mode ? (window.DashHelpers.mobileOn(state.mobile_mode) ? 'On' + (window.mobileEndWords && state.mobile_mode.ends_at ? ' · until ' + window.mobileEndWords(state.mobile_mode.ends_at) : '') : 'Off · switches off by itself after ' + state.mobile_mode.default_hours + ' h') : 'Phones are paired on your phone link’s admin page.', go('phone', 'Change', 'settings-everyday-phone'), 'settings-everyday-phone-row') : null));
}
// Phone & workspaces (draft settings-phone): 1. the relay connection, 2. phones (paired on the relay admin page) + delivery,
// then the workspaces this one may talk to. Everything comes from the relay add-on's saved connection (no network).
function relayInfo(phoneAddon) {
  const row = array(state.settings?.addons).find(a => a.name === phoneAddon.name), d = row?.detail;
  return {connected:!!(row?.active && d?.connected), address:d?.address || '', workspaces:array(d?.workspaces)};
}
function phonePanel(phoneAddon, settings) {
  const {connected, address, workspaces} = relayInfo(phoneAddon);
  const mm = snapshot ? null : window.OrchMobileMode?.settingsSection(h);
  const rowOf = (label, value, action, key) => h('div', {className:'card-row name-row', 'data-key':key}, h('span', {className:'set-label'}, label), h('div', {className:'grow set-ctl'}, ...asList(value)), action);
  const btn = (label, cls, name, extra = {}) => snapshot ? null : h('button', {type:'button', className:'btn sm ' + cls, 'data-action':name, 'data-key':'phone-' + name, ...extra}, label);
  const relay = h('div', {className:'stack', 'data-key':'phone-relay'}, h('h2', {className:'set-sub'}, '1. Phone link'), h('div', {className:'card'},
    rowOf('Status', [connected ? h('strong', {className:'on-dot', 'data-key':'phone-relay-status'}, 'Connected') : h('strong', {className:'muted', 'data-key':'phone-relay-status'}, 'Not set up'),
      settingsText('p', {className:'meta', 'data-key':'phone-relay-address'}, connected && address ? address : 'No phone link connected')],
      h('div', {className:'row'}, btn(connected ? 'Check connection' : 'Check again', 'outline', 'relay-reconnect')), 'phone-relay-row'),
    // Not connected: the next step is written here, no dead end (a relay is connected from its own admin page + one line)
    connected ? null : h('div', {className:'card-row', 'data-key':'phone-relay-steps'}, h('ol', {className:'meta relay-steps'},
      h('li', {}, 'Open the admin page of your phone link and add this workspace. It gives you one line to copy.'),
      h('li', {}, 'Paste that line below and press Connect.'))),
    connected || snapshot ? null : relayPaste(),
    settingsText('p', {className:'card-row meta'}, 'Your phone talks to this workspace through your phone link.')));
  // Phones are paired on the relay's own admin page (owner 15 Nov, prototype): no pairing from the workspace.
  const adminHref = connected && /^https?:\/\//.test(address) ? address.replace(/\/+$/, '') + '/admin' : '';
  const pair = h('div', {className:'stack', 'data-key':'phone-phones'}, h('h2', {className:'set-sub'}, '2. Phones'), h('div', {className:'card'},
    rowOf('Pairing', [settingsText('p', {'data-key':'phone-pair-line'}, 'Phones are paired on your phone link’s admin page.')],
      adminHref && !snapshot ? h('a', {className:'btn sm outline', href:adminHref, target:'_blank', rel:'noopener', 'data-key':'phone-relay-admin'}, 'Open the phone link admin page') : null, 'phone-pairing-row'),
    mm));
  const allowed = h('div', {className:'stack', 'data-key':'phone-allowed'}, h('div', {className:'row between'}, h('h2', {className:'set-sub'}, 'Allowed workspaces'),
    settingsText('span', {className:'meta'}, (connected ? workspaces.length : 0) + ' allowed')),
    connected && workspaces.length ? h('div', {className:'card'}, workspaces.map(w => h('div', {className:'card-row', 'data-key':'phone-ws-' + w.name}, h('span', {className:w.online ? 'on-dot' : 'off-dot', title:w.online ? 'online' : 'offline'}, settingsText('span', {}, w.name)))))
      : h('div', {className:'card pad empty-note', 'data-key':'phone-allowed-empty'}, settingsText('h3', {}, 'No other workspaces yet'), settingsText('p', {className:'meta'}, 'Allow a workspace to send it messages and files.')));
  return h('div', {className:'stack', 'data-key':'settings-phone'}, relay, pair, allowed,
    h('div', {className:'row'}, h('a', {className:'btn ghost sm', href:'#addon/' + encodeURIComponent(phoneAddon.name), 'data-key':'phone-open-messages'}, 'Open messages →')));
}
// Not connected: the line from the phone link's admin page is pasted here and Connect runs it (ORCH-1693).
const relayUi = {line:'', busy:false};
function relayPaste() {
  const input = h('input', {type:'text', className:'input grow', 'data-key':'phone-relay-line', 'aria-label':'Line from your phone link', placeholder:'Paste the line here', autocomplete:'off', spellcheck:'false', disabled:relayUi.busy});
  input.value = relayUi.line;
  input.oninput = () => { relayUi.line = input.value; };
  input.onkeydown = e => { if (e.key === 'Enter') relayConnect(); };
  return h('div', {className:'card-row row'}, input,
    h('button', {type:'button', className:'btn sm', 'data-action':'relay-connect', 'data-key':'phone-relay-connect', disabled:relayUi.busy}, relayUi.busy ? 'Connecting…' : 'Connect'));
}
async function relayConnect() {
  const line = relayUi.line.trim();
  if (relayUi.busy) return;
  if (!line) { window.orch.toast('Paste the line from your phone link’s admin page first.', 'error'); return; }
  relayUi.busy = true; render();
  const result = await act('relay.connect', {line});
  relayUi.busy = false;
  if (!result.ok) { window.orch.toast(result.text, 'error'); render(); return; }
  relayUi.line = '';
  await refresh();
  window.orch.toast('Connected. Your phone link is set up.', 'ok');
}
async function relayReconnect(control) {
  if (control.disabled) return;
  control.disabled = true;
  await refresh();
  const phoneAddon = addons().find(a => a.dashboard?.panel === 'phone');
  const ok = phoneAddon && relayInfo(phoneAddon).connected;
  window.orch.toast(ok ? 'Checked. Your phone link is connected.' : 'Your phone link is not connected.', ok ? 'ok' : 'error');
  control.disabled = false;
}
// One add-on's own settings page (draft addon-detail): the switch, the connection, what it holds, and a quiet
// always-visible "About this add-on" at the bottom. Reached from a row of the Add-ons tab (#settings/addons/<name>).
function addonDetailPage(addon) {
  const d = addon.detail, live = addons().find(a => a.name === addon.name), label = rowLabel(addon);
  const connected = addon.active && d?.connected;
  const row = (title, value, action, key) => h('div', {className:'card-row name-row', 'data-key':key}, h('span', {className:'set-label'}, title), h('div', {className:'grow set-ctl'}, ...asList(value)), action);
  const links = live?.dashboard?.panel === 'links';
  const shown = state.look ? state.look.shared_pages !== false : null;
  const settingsRows = [
    row('Add-on', settingsText('p', {}, addon.description || label),
      fragment(switchBusy(addon), h('button', {type:'button', className:'switch', role:'switch', 'aria-checked':!!addon.active, 'aria-label':label + ' on or off', 'data-key':'settings-switch-' + addon.name, 'data-action':'settings-addon', 'data-name':addon.name, disabled:snapshot || settingsBusy.has('addon-' + addon.name)}, addon.active ? 'On' : 'Off')), 'addon-detail-switch'),
    addon.page?.live_session === true && addon.active && typeof state.settings?.typing_on === 'boolean' ? row('Typing', h('div', {}, settingsText('p', {}, 'Let me type into the helper\u2019s screen'), settingsText('p', {className:'meta'}, 'When on, you can click the helper\u2019s live screen and type into it.')),
      h('button', {type:'button', className:'switch', role:'switch', 'aria-checked':state.settings.typing_on, 'aria-label':'Let me type into the helper\u2019s screen', 'data-action':'session-typing', 'data-key':'addon-detail-typing', disabled:snapshot || settingsBusy.has('session-typing')}, state.settings.typing_on ? 'On' : 'Off'), 'addon-detail-typing-row') : null,
    addon.active && d ? row('Connection', connected ? h('span', {className:'on-dot', 'data-key':'addon-detail-status'}, 'Connected') : h('span', {className:'off-dot', 'data-key':'addon-detail-status'}, 'Not connected yet'), null, 'addon-detail-connection') : null,
    links && shown !== null ? row(label, settingsText('p', {}, 'Show workspace name and icon'),
      h('button', {type:'button', className:'switch', role:'switch', 'aria-checked':shown, 'aria-label':'Show workspace name and icon on published pages', 'data-action':'addon-shared', 'data-on':String(!shown), 'data-key':'addon-detail-shared', disabled:snapshot || settingsBusy.has('shared')}, shown ? 'On' : 'Off'), 'addon-detail-shared-row') : null,
    addon.name === 'pull-requests' && addon.active && state.settings ? releaseMergeRow(row, state.settings) : null,
  ];
  // Typing is technical: behind "More" (ORCH-300 item 14). Connection stays in view.
  const technical = settingsRows.splice(1, 1).filter(Boolean);
  if (technical.length) settingsRows.push(moreSettings('addon-' + addon.name, ...technical));
  const where = live && (live.dashboard || live.page)
    ? h('div', {className:'card'}, row('Open', settingsText('p', {}, 'See what ' + label + ' holds.'), h('a', {className:'btn ghost sm', href:'#addon/' + encodeURIComponent(addon.name), 'data-key':'addon-detail-open'}, 'Open ' + label + ' →'), 'addon-detail-open-row')) : null;
  return fragment(h('div', {className:'settings stack', 'data-key':'settings-addon-detail'},
    heading(label, 'Add-on settings', {back:{label:'Add-ons', href:'#settings/addons'}}),
    h('div', {className:'card'}, settingsRows),
    where,
    snapshot || addon.name === 'dashboard' ? null : addon.removable === false ? settingsText('p', {className:'meta', 'data-key':'addon-detail-core'}, rowLabel(addon) + ' is part of orch. You can turn it off, but not remove it.') : h('div', {className:'row'}, h('button', {type:'button', className:'btn outline sm', 'data-action':'addon-remove', 'data-name':addon.name, 'data-key':'addon-detail-remove', disabled:settingsBusy.has('addon-' + addon.name)}, 'Uninstall')),
    // the description is the Add-on row's text already: About shows only what is not said above (ORCH-1684)
    connected && d.address ? h('section', {className:'addon-about', 'data-key':'addon-about'}, h('h3', {}, 'About this add-on'),
      settingsText('p', {className:'meta'}, 'Connection address: ' + d.address)) : null));
}
function settingsPage() {
  const settings = state.settings;
  const phoneAddon = addons().find(a => a.dashboard?.panel === 'phone');
  if (settingsTab === 'phone' && !phoneAddon) settingsTab = 'general';
  const agents = array(settings.agents).map(agent => {
    const radio = h('input', {type:'radio', 'aria-label':agent.label, name:'settings-agent', value:agent.name, 'data-key':'settings-agent-' + agent.name, 'data-settings-agent':agent.name, disabled:settingsBusy.has('agent') || (!agent.found && agent.status !== 'your command')});
    radio.checked = !!agent.chosen;
    const missing = !agent.found && agent.status !== 'your command';
    const status = agent.status === 'your command' ? 'Your own helper' : agent.found ? 'Found' : 'Not found on this computer. Install it, then it shows up here.';
    return h('div', {className:'card card-row agent-opt agent-card' + (missing ? ' off' : '') + (agent.chosen ? ' sel' : ''), 'data-key':'settings-agent-row-' + agent.name}, h('label', {className:'tap-box'}, radio),
      h('div', {className:'grow'}, settingsText('h3', {}, agent.label), settingsText('p', {className:'meta'}, status)),
      agent.chosen ? h('span', {className:'chip active def'}, 'Default') : null);
  }).map(row => row);
  array(settings.agents).forEach((agent, i) => {
    // An unavailable helper has nothing to test: its row already says how to get it.
    if (snapshot || (!agent.found && agent.status !== 'your command')) return;
    const test = h('button', {type:'button', className:'btn ghost sm', 'data-action':'agent-test', 'data-name':agent.name, 'data-key':'settings-test-' + agent.name, disabled:settingsBusy.has('test-' + agent.name)}, 'Test');
    const note = agentTests[agent.name] ? h('p', {role:'status', className:'meta test-note'}, plainTest(agentTests[agent.name].reason)) : null;
    agents[i].append(test);
    if (note) agents[i].append(note);
  });
  const panel = (id, body) => h('section', {className:'set-sec', id:'settings-panel-' + id, 'data-key':'settings-panel-' + id, role:'tabpanel', 'aria-labelledby':'settings-tab-' + id, hidden:settingsTab !== id, tabindex:'0'}, body);
  // One tidy aligned list: the same name as the sidebar, one plain line, the connection status, the switch.
  const addonRow = addon => {
    const d = addon.detail, connected = addon.active && d?.connected;
    const status = !addon.active || !d ? null : connected ? h('span', {className:'on-dot ad-status'}, 'Connected') : h('span', {className:'off-dot ad-status'}, 'Not connected yet');
    const about = connected && d.address ? settingsText('p', {className:'meta ad-about', 'data-key':'settings-addon-about-' + addon.name}, 'Connection address: ' + d.address) : null;
    return h('div', {className:'card-row ad-row', 'data-key':'settings-addon-' + addon.name},
      h('div', {className:'grow'}, addon.dashboard?.stage === 'preview' ? h('h3', {}, rowLabel(addon) + ' ', h('span', {className:'badge'}, 'Preview')) : settingsText('h3', {}, rowLabel(addon)), settingsText('p', {className:'meta'}, addon.description), status, about),
      h('a', {className:'btn ghost sm', href:'#settings/addons/' + encodeURIComponent(addon.name), 'data-key':'settings-addon-open-' + addon.name, 'aria-label':rowLabel(addon) + ' settings'}, 'Settings →'),
      switchBusy(addon), h('span', {className:'switch-text', 'aria-hidden':'true'}, addon.active ? 'On' : 'Off'),
      h('button', {type:'button', className:'switch', role:'switch', 'aria-checked':!!addon.active, 'aria-label':rowLabel(addon) + ' on or off', 'data-key':'settings-switch-' + addon.name, 'data-action':'settings-addon', 'data-name':addon.name, disabled:snapshot || settingsBusy.has('addon-' + addon.name) || !!window.addonJobLive?.()}, addon.active ? 'On' : 'Off'));
  };
  const optional = array(settings.addons).filter(a => a.name !== 'dashboard');
  const jobLive = !!window.addonJobLive?.();  // ORCH-1739: one add-on run at a time; the switches wait for it too
  const addonsPanel = h('div', {className:'stack', 'data-key':'settings-addon-list'},
    h('div', {className:'row between ad-head'}, h('h2', {className:'set-sub'}, 'Installed add-ons'),
      snapshot ? null : h('div', {className:'action-note'}, h('button', {type:'button', className:'btn primary sm', 'data-action':'addon-catalog', 'data-key':'settings-addon-catalog', disabled:jobLive}, 'Add add-ons'),
        jobLive ? settingsText('p', {className:'meta', 'data-key':'settings-addon-busy'}, 'You can add more when this is done.') : null)),
    typeof addonJobBanner === 'function' ? addonJobBanner() : null,
    optional.length ? h('div', {className:'card'}, optional.map(addonRow))
      : h('div', {className:'card pad empty-note', 'data-key':'settings-addons-empty'}, settingsText('h3', {}, 'No optional add-ons installed'), settingsText('p', {className:'meta'}, 'Add tools for schedules, shared links and more.')),
    null);
  const detailAddon = settingsTab === 'addons' && settingsAddon ? array(settings.addons).find(a => a.name === settingsAddon && a.name !== 'dashboard') : null;
  if (detailAddon) return addonDetailPage(detailAddon);
  return fragment(h('div', {className:'settings stack form-width', 'data-key':'settings-root'}, heading('Settings', 'Make ' + clean(state.workspace || 'this workspace') + ' work your way.'),
    h('div', {className:'settings-layout'}, h('nav', {className:'tabs settings-nav', role:'tablist', 'aria-label':'Settings'}, [['general', 'General'], ['people', 'People'], ['agent', 'Helper'], ...(phoneAddon ? [['phone', phoneAddon.dashboard.label]] : []), ['addons', 'Add-ons'], ['about', 'About & updates']].map(([id, label]) => h('button', {type:'button', id:'settings-tab-' + id, role:'tab', 'aria-selected':settingsTab === id, 'aria-controls':'settings-panel-' + id, tabindex:settingsTab === id ? '0' : '-1', 'data-action':'settings-tab', 'data-tab':id}, label))), h('div', {className:'settings-content'},
    panel('general', [snapshot ? null : window.OrchLook?.profileCard(), privateCard(settings), h('div', {className:'stack', 'data-key':'settings-workspace'}, h('h2', {className:'set-sub'}, 'Workspace'), h('div', {className:'card'},
      // Folder: its name plainly and Copy path; the full path only on hover (ORCH-1693: no raw path at first level).
      h('div', {className:'card-row name-row folder-row'}, h('span', {className:'set-label'}, 'Folder'), h('div', {className:'grow set-ctl'},
        settingsText('strong', {title:String(settings.folder || ''), 'data-key':'settings-folder-name'}, folderName(settings.folder) || state.workspace)),
        snapshot || !settings.folder ? null : settingsText('button', {type:'button', className:'btn outline sm', 'data-copy':String(settings.folder), 'data-key':'settings-copy-path'}, 'Copy path')))),
      // Shared pages are files shared with a link: only once sharing is on (R1.1, ORCH-2112).
      snapshot || !sharingOn() ? null : window.OrchLook?.settingsSection(),
      syncCard(settings),
      everydayCard(settings, phoneAddon),
      h('div', {className:'stack', 'data-key':'settings-sharing'}, h('h2', {className:'set-sub'}, 'Sharing and finished work'), workflowCard(settings), autoReviewerCard()),
      // Technical settings behind one fold (ORCH-300, owner's word list item 14; DESIGN.md: one disclosure per section).
      moreSettings('general', shareCard(settings), ...prSwitchCards(settings), copiesCard(settings), diagCard(settings))]),
    panel('people', [...peoplePanel(settings), terminalTypingCard(settings)]),
    panel('agent', [h('p', {className:'meta'}, 'Pick the helper tool to use. It is saved right away.'), h('div', {className:'stack'}, h('div', {className:'agent-cards', role:'radiogroup', 'aria-label':'Helper tool'}, agents),
      snapshot ? null : h('div', {className:'agent-foot', 'data-key':'settings-add-slot'}, h('button', {type:'button', className:'btn ghost sm', 'data-key':'settings-add-agent', 'data-action':'agent-add'}, '+ Add your own helper'))),
      helperNeedsCard(), permissionsCard(settings), moreSettings('agent', helpersAtOnceCard(settings)), prepareCard(settings)]),
    phoneAddon ? panel('phone', phonePanel(phoneAddon, settings)) : null,
    panel('addons', addonsPanel),
    panel('about', aboutPanel())))
  ));
}
// ---- About & updates (Settings): the installed release, the newest one, what changed, one Update button, the steps.
// Data: GET /api/update-info (orch asks its install source; nothing is sent). The click runs a detached `orch update`.
// The phase comes from update.js ("orch-update-state" events).
const updUi = {info:null, loading:false, phase:'idle', from:null, to:null, reason:''};
const UPD_STEPS = ['Downloading', 'Installing', 'Restarting', 'Done'];
function updLoad(force = false) {
  if (updUi.loading || (updUi.info && !force)) return;
  updUi.loading = true;
  fetch('/api/update-info', {cache:'no-store'}).then(r => r.ok ? r.json() : {}).catch(() => ({})).then(info => {
    updUi.info = info && typeof info === 'object' ? info : {}; updUi.loading = false;
    if (updUi.phase === 'restarting' || updUi.phase === 'running') return;
    if (updUi.phase === 'done' && updUi.info.installed) updUi.to = updUi.info.installed.release || updUi.info.installed.label;
    if (route().kind === 'settings') render();
  });
}
async function updStart(to) {
  const was = updUi.info?.installed;
  updUi.from = was?.release || was?.label || null; updUi.phase = 'running'; updUi.reason = ''; render();
  try { sessionStorage.setItem('orch-update-from', JSON.stringify(updUi.from)); } catch (e) {}
  let res = null;
  try { res = await fetch('/api/act', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({op:'update.start', args:to === 'release' || to === 'development' || /^[1-9][0-9]{0,5}(\.[1-9][0-9]{0,3})?$/.test(String(to || '')) ? {to:String(to)} : {}})}); } catch (e) { /* the server may already be restarting */ }
  if (res && res.status !== 202) { updUi.phase = 'failed'; updUi.reason = window.DashHelpers.answerText(res.status, await res.text(), 'It did not start.').slice(0, 200); render(); return; }
  try { sessionStorage.setItem('orch-update-started', String(Date.now())); } catch (e) {}
}
if (typeof window !== 'undefined' && window.addEventListener) window.addEventListener('orch-update-state', event => {
  const d = event.detail || {};
  if (d.state === 'running' && updUi.phase === 'idle') updUi.phase = 'running';
  else if (d.state === 'unreachable' && updUi.phase === 'running') updUi.phase = 'restarting';
  else if (d.state === 'finished') {
    if (updUi.from == null) { try { updUi.from = JSON.parse(sessionStorage.getItem('orch-update-from')); } catch (e) {} }
    updUi.phase = 'done'; updUi.info = null; updUi.loading = false;
  } else if (d.state === 'failed') { updUi.phase = 'failed'; updUi.reason = String(d.reason || 'It did not finish.'); }
  if (route().kind === 'settings') render();
  if (d.state === 'finished') updLoad(true);
});
function updButton(text, key, fn) { const b = button(text, 'primary', fn); b.dataset.key = key; return b; }
// Where this orch came from (issue 957): "Release" or "Development build" on the Installed line, and one click to switch.
// The switch is the same detached `orch update` as the Update button, with --to (the official source at that branch).
function buildLine(info, phase) {
  const dev = info?.build === 'development';
  if (info?.build !== 'release' && !dev) return null;
  const idle = phase === 'idle' || phase === 'failed';
  return [
    h('span', {className:dev ? 'badge needs' : 'badge', 'data-key':'update-build'}, dev ? 'Test version' : 'Release'),
    // What the build is sits under its name; what the button does sits beside the button (manager, 17 Nov).
    dev ? settingsText('p', {className:'meta', 'data-key':'update-build-note'}, 'The newest changes, not yet tested as a release.') : null,
    idle && !snapshot ? h('div', {className:'row'}, (() => { const b = button(dev ? 'Switch to release' : 'Switch to test version', 'outline sm', () => updStart(dev ? 'release' : 'development')); b.dataset.key = 'update-switch'; return b; })(),
      settingsText('span', {className:'meta', 'data-key':'update-switch-note'}, (dev ? 'Installs the newest release' : 'Installs the newest changes, not yet tested as a release,') + ' and restarts. Your helpers keep their work.')) : null];
}
// The installed version in plain words: a release number, else just "orch" (a test build's commit only on hover).
function installedName(have, info) { return have?.release != null ? updNum(have.release) : have || info ? 'orch' : '…'; }
function updNum(v) { return typeof v === 'number' ? 'orch ' + v : String(v || ''); }
function aboutPanel() {
  if (settingsTab === 'about') updLoad();  // the check runs when the tab is open, not on every Settings page
  const info = updUi.info, have = info?.installed, newest = info?.newest, phase = updUi.phase;
  const line = (label, body) => h('div', {className:'card-row name-row'}, h('span', {className:'set-label'}, label), h('div', {className:'grow set-ctl'}, body));
  const steps = h('ol', {className:'upd-steps', 'data-key':'update-steps', 'aria-label':'Update steps'}, UPD_STEPS.map((name, i) => {
    const at = phase === 'done' ? 4 : phase === 'restarting' ? 2 : phase === 'running' ? 0 : -1;  // Downloading + Installing run as one step
    const state = i < at ? 'done' : (i === at || (at === 0 && i === 1)) && phase !== 'failed' ? 'now' : 'next';
    return h('li', {className:'upd-step ' + state, 'aria-current':state === 'now' ? 'step' : null}, (state === 'done' ? '✓ ' : '') + name);
  }));
  let body;
  if (phase === 'running' || phase === 'restarting') {
    body = [steps, settingsText('p', {className:'meta', role:'status', 'data-key':'update-note'}, 'Your helpers keep their work and carry on after the restart.')];
  } else if (phase === 'done') {
    const to = updUi.to ?? have?.release ?? have?.label;
    const text = updUi.from != null && to != null && updUi.from !== to ? 'Updated ' + (typeof updUi.from === 'number' ? updUi.from : String(updUi.from).replace(/^orch /, '')) + ' → ' + (typeof to === 'number' ? to : String(to).replace(/^orch /, '')) : 'Updated';
    body = [steps, settingsText('p', {className:'upd-done', role:'status', 'data-key':'update-done'}, text),
      array(info?.changes).length ? h('ul', {className:'upd-changes', 'data-key':'update-changes'}, array(info.changes).map(c => settingsText('li', {}, c))) : null];
  } else if (phase === 'failed') {
    body = [settingsText('p', {className:'bad', role:'alert', 'data-key':'update-failed'}, 'The update did not finish: ' + clean(updUi.reason).replace(/[.\s]+$/, '') + '. orch is still the old version.'),
      snapshot ? null : updButton('Try again', 'update-retry', () => { updUi.phase = 'idle'; render(); })];
  } else if (!info) {
    body = settingsText('p', {className:'meta', 'data-key':'update-loading'}, 'Checking for a newer version…');
  } else {
    const ready = info.update_available === true && newest;
    body = [
      // A build from a branch (no release number, a commit) is a normal case, not an error: say what it is, skip the check.
      !newest && have?.sha && !have.release && info.ref ? settingsText('p', {className:'meta', 'data-key':'update-branch'}, 'This is a test version, so there is no release to compare it with. Update checks are skipped.')
        : !newest ? h('div', {className:'row'}, settingsText('p', {className:'meta', 'data-key':'update-unknown'}, 'Could not check for a newer version right now.'),
          snapshot ? null : updButton('Check again', 'update-check-again', () => { updUi.info = null; updLoad(true); render(); }))
        : ready ? h('div', {className:'upd-ready'}, settingsText('strong', {}, updNum(newest.release) || newest.label), settingsText('span', {className:'meta'}, ' is ready to install'))
        : settingsText('p', {className:'meta', 'data-key':'update-current'}, 'You have the newest version.'),
      ready && array(info.changes).length ? h('div', {className:'stack', 'data-key':'update-changes'}, h('h3', {}, 'What changed'), h('ul', {className:'upd-changes'}, array(info.changes).map(c => settingsText('li', {}, c)))) : null,
      ready && !snapshot ? h('div', {className:'row'}, updButton('Update to ' + String(newest.release || newest.label).replace(/^orch /, ''), 'update-start', updStart),
        info.source ? settingsText('span', {className:'meta'}, 'From ' + info.source) : null) : null];
  }
  return h('div', {className:'stack', 'data-key':'settings-about'}, h('h2', {className:'set-sub'}, 'Version'), h('div', {className:'card'},
    line('Installed', h('div', {className:'stack'}, h('div', {className:'row'}, settingsText('strong', {'data-key':'update-installed', title:have?.label || null}, installedName(have, info)), buildLine(info, phase)?.[0]), ...(buildLine(info, phase) || []).slice(1))),
    line(phase === 'idle' || phase === 'failed' ? 'Newest' : 'Update', h('div', {className:'stack'}, body))),
    autoUpdateCard(info),
    toolsCard(),
    snapshot ? null : companionCard(),
    // About sits with the version (ORCH-89: it was under General)
    snapshot ? null : h('div', {className:'stack', 'data-key':'settings-about-orch'}, h('h2', {className:'set-sub'}, 'About'), h('div', {className:'card'},
      h('div', {className:'card-row name-row'}, h('span', {className:'set-label'}, 'Style guide'), h('div', {className:'grow set-ctl'}, h('a', {className:'btn outline sm', href:'/styleguide', target:'_blank', rel:'noopener', 'data-key':'settings-style-guide'}, 'Open the style guide'))))));
}
// ---- Tools (ORCH-589): the helper tools and the other tools this workspace uses, newest version, what's new and
// one Update button each. Data: GET /api/tool-updates (orch keeps the answers 6 hours; Check now asks again).
// Update runs `orch tools update <name>` in the background; while it runs the card asks again every 3 seconds.
const toolUi = {data:null, loading:false, starting:null, reason:'', timer:null, clicked:new Set()};
function toolLoad(refresh = false) {
  if (toolUi.loading || (toolUi.data && !refresh)) return;
  toolUi.loading = true;
  fetch('/api/tool-updates' + (refresh === true ? '?refresh=1' : ''), {cache:'no-store'}).then(r => r.ok ? r.json() : null).catch(() => null).then(data => {
    toolUi.loading = false;
    if (data && typeof data === 'object' && Array.isArray(data.tools)) toolUi.data = data;
    else if (!toolUi.data || toolUi.data.failed) toolUi.data = {tools:[], failed:true};  // keep what was shown; else say it failed
    const running = toolUi.data.job?.status === 'running';
    // while an update runs, ask again every 3 s from orch's kept answers (no outside question each time)
    if (running || toolUi.starting) { clearTimeout(toolUi.timer); toolUi.timer = setTimeout(() => toolLoad('poll'), 3000); }
    if (!running && toolUi.data.job?.name === toolUi.starting) toolUi.starting = null;
    if (route().kind === 'settings') render();
  });
}
async function toolStart(name) {
  toolUi.starting = name; toolUi.clicked.add(name); toolUi.reason = ''; render();
  let res = null;
  try { res = await fetch('/api/act', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({op:'tools.update', args:{name}})}); } catch (e) { /* shown below */ }
  if (!res || res.status !== 202) { toolUi.starting = null; toolUi.reason = res ? window.DashHelpers.answerText(res.status, await res.text(), 'It did not start.').slice(0, 200) : 'It did not start.'; render(); return; }
  setTimeout(() => toolLoad('poll'), 1500);
}
function toolRow(t, job) {
  const running = (job?.status === 'running' && job.name === t.name) || toolUi.starting === t.name;
  const busy = job?.status === 'running' || !!toolUi.starting;  // one update at a time: the other buttons wait
  // the result of an update started from this page (an older one from another day is not news)
  const finished = job && job.name === t.name && toolUi.clicked.has(t.name) && (job.status === 'done' || job.status === 'failed') ? job : null;
  const notes = array(t.notes);
  const body = [
    h('div', {className:'row'}, t.update ? h('span', {className:'badge', 'data-key':'tool-ready'}, 'Update available')
        : settingsText('strong', {}, t.compare === 'current' ? 'Up to date' : t.installed ? 'Installed' : 'Version unknown'),
      settingsText('span', {className:'meta', 'data-key':'tool-installed'}, t.installed ? (t.update ? t.installed + ' \u2192 ' + t.newest : t.installed) : '')),
    t.update && notes.length ? h('div', {className:'stack', 'data-key':'tool-notes'}, notes.map(n => h('div', {className:'stack'},
      settingsText('h3', {}, 'What\u2019s new in ' + n.version),
      h('ul', {className:'upd-changes'}, array(n.lines).map(x => settingsText('li', {}, x))))),
      t.more || t.notes_url ? h('p', {className:'meta'}, t.more ? 'And ' + t.more + ' more. ' : '', t.notes_url ? h('a', {href:t.notes_url, target:'_blank', rel:'noopener noreferrer'}, 'All notes') : null) : null) : null,
    running ? settingsText('p', {className:'meta', role:'status', 'data-key':'tool-updating'}, 'Updating\u2026 You can leave this page.')
      : t.can_update && !snapshot && !busy ? h('div', {className:'row'}, (() => { const b = button('Update to ' + t.newest, 'outline sm', () => toolStart(t.name)); b.dataset.key = 'tool-update'; return b; })(),
        t.helper ? settingsText('span', {className:'meta'}, 'Helpers working now keep going; they use the new version from their next start.') : null)
      : t.update && t.manual ? settingsText('p', {className:'meta', 'data-key':'tool-manual'}, t.manual) : null,
    finished && !running ? settingsText('p', {className:finished.status === 'failed' ? 'bad' : 'upd-done', role:'status', 'data-key':'tool-result'}, finished.say || '') : null,
    t.error ? settingsText('p', {className:'meta', 'data-key':'tool-error'}, t.last_good_at && t.newest ? 'Could not check right now. This is from ' + fmtAgo(t.last_good_at) + '.' : 'Could not check for a newer version right now.') : null];
  return h('div', {className:'card-row name-row', 'data-key':'tool-' + t.name}, h('span', {className:'set-label'}, t.label), h('div', {className:'grow set-ctl'}, h('div', {className:'stack'}, body)));
}
function fmtAgo(at) { const ago = window.DashHelpers?.ago; const d = new Date(at); return ago && !isNaN(d) ? ago(at, Date.now()) : isNaN(d) ? String(at) : d.toLocaleString([], {dateStyle:'medium', timeStyle:'short'}); }
function toolsCard() {
  if (settingsTab === 'about') toolLoad();
  const data = toolUi.data, tools = array(data?.tools);
  if (data && !tools.length && !data.failed) return null;  // no tool orch can check here: nothing to show
  const checked = tools.map(t => t.checked_at).filter(Boolean).sort()[0];
  return h('div', {className:'stack', 'data-key':'settings-tools'}, h('h2', {className:'set-sub'}, 'Tools'),
    h('div', {className:'card'},
      !data ? h('div', {className:'card-row'}, settingsText('p', {className:'meta', 'data-key':'tools-loading'}, 'Checking your tools for newer versions\u2026'))
        : data.failed ? h('div', {className:'card-row'}, settingsText('p', {className:'meta', 'data-key':'tools-unknown'}, 'Could not check your tools right now.'))
        : tools.map(t => toolRow(t, data.job)),
      toolUi.reason ? h('div', {className:'card-row'}, settingsText('p', {className:'bad', role:'alert', 'data-key':'tools-failed'}, 'The update did not start: ' + clean(toolUi.reason))) : null,
      data && !snapshot ? h('div', {className:'card-row'}, h('div', {className:'row'},
        checked ? settingsText('span', {className:'meta', 'data-key':'tools-checked'}, 'Checked ' + fmtAgo(checked)) : null,
        (() => { const b = button(toolUi.loading ? 'Checking\u2026' : 'Check now', 'outline sm', () => { toolLoad(true); render(); }); b.dataset.key = 'tools-check'; b.disabled = toolUi.loading; return b; })())) : null));
}
// orch Companion (ORCH-1721): the Mac app that records calls for Meetings. Newest release and its download from
// GET /api/companion (orch asks GitHub at most every 6 hours); without an answer the button opens the release list.
const compUi = {data:null, loading:false, at:0};
function companionLoad() {
  if (compUi.loading || (compUi.data && Date.now() - compUi.at < 600000)) return;  // asks again after 10 minutes
  compUi.loading = true; compUi.at = Date.now();
  fetch('/api/companion', {cache:'no-store'}).then(r => r.ok ? r.json() : null).catch(() => null).then(data => {
    compUi.loading = false;
    compUi.data = data && typeof data === 'object' ? data : {};
    if (route().kind === 'settings') render();
  });
}
function companionCard() {
  if (settingsTab === 'about') companionLoad();
  const d = compUi.data, ok = typeof d?.url === 'string' && /^https:\/\/github\.com\//.test(d.url) && typeof d.version === 'string';
  const page = typeof d?.page === 'string' && /^https:\/\/github\.com\//.test(d.page) ? d.page : 'https://github.com/severinlindenmann/orch/releases?q=companion';
  return h('div', {className:'stack', 'data-key':'settings-companion'}, h('h2', {className:'set-sub'}, 'orch Companion'),
    h('div', {className:'card'}, h('div', {className:'card-row'},
      h('div', {className:'grow'}, settingsText('p', {'data-key':'companion-what'}, 'Records your calls and adds them to Meetings. Opens when your Mac starts.'),
        settingsText('p', {className:'meta', 'data-key':'companion-version'}, !d ? 'Looking for the newest version\u2026' : ok ? 'Version ' + d.version + ' \u00b7 Mac only for now' : 'Mac only for now')),
      d ? h('a', {className:'btn outline sm', href:ok ? d.url : page, target:ok ? null : '_blank', rel:'noopener', 'data-key':'companion-download'}, ok ? 'Download for Mac' : 'See downloads') : null)));
}
// Update automatically (off until the person turns it on): one switch. A development build follows its own branch, said plainly.
function autoUpdateCard(info) {
  const auto = info?.auto;
  if (!auto || typeof auto.on !== 'boolean') return null;
  return h('div', {className:'card', 'data-key':'settings-auto-update'}, h('div', {className:'card-row'},
    h('div', {className:'grow'}, settingsText('h3', {}, 'Update automatically when a new release is out'),
      settingsText('p', {}, 'orch installs it by itself at a quiet moment, never while a helper is working, and shows on Home what changed.'),
      auto.branch ? settingsText('p', {className:'meta', 'data-key':'settings-auto-update-branch'}, 'This is a test version: it gets every new change as soon as it is ready, not only releases.') : null),
    h('span', {className:'switch-text', 'aria-hidden':'true'}, auto.on ? 'On' : 'Off'), h('button', {type:'button', className:'switch', role:'switch', 'aria-checked':auto.on, 'aria-label':'Update automatically when a new release is out', 'data-key':'settings-switch-auto-update', 'data-action':'auto-update-set', disabled:snapshot || settingsBusy.has('auto-update')})));
}
async function autoUpdateSwitch() {
  if (settingsBusy.has('auto-update')) return;
  const on = updUi.info?.auto?.on !== true;
  const result = await settingsSend('update.auto', {on}, 'auto-update');
  if (result.ok) { if (updUi.info?.auto) updUi.info.auto.on = on; window.orch.toast(on ? 'orch now updates by itself.' : 'Automatic updates are off.', 'ok'); render(); }
}
// An agent that is started with a command: a small form that opens in the list; the command is shown before it is added.
function openAgentForm(control) {
  const slot = control.closest('[data-key="settings-add-slot"]');
  if (!slot || locks.has('settings-add-slot')) return;
  locks.add('settings-add-slot');
  const input = (tag, attrs = {}) => Object.assign(el(tag, 'input'), attrs);
  const nameIn = input('input', {type:'text', placeholder:'Name, e.g. report-tool', maxLength:32});
  const cmdIn = input('input', {type:'text', placeholder:'report-tool --task {task}'});
  const via = input('select');
  via.append(new Option('The task goes in as an argument', 'arg'), new Option('The task goes in on stdin', 'stdin'));
  const err = el('p', 'bad'); err.setAttribute('role', 'alert');
  const row = (label, control, hint) => { const l = el('label', '', label); l.append(control); if (hint) { const t = el('span', 'hint', hint); t.setAttribute('aria-hidden', 'true'); t.id = 'hint-' + label.toLowerCase().replace(/\W+/g, '-'); control.setAttribute('aria-describedby', t.id); l.append(t); } return l; };
  const form = el('div', 'add-form');
  const preview = el('div', 'cmd-preview');
  preview.hidden = true;
  const cancel = () => { locks.delete('settings-add-slot'); render(); };
  const back = button('Back', 'ghost sm', () => { preview.hidden = true; fields.hidden = false; });
  const fields = el('div', 'add-form');
  fields.append(row('Name', nameIn, '2–32 characters: lowercase letters, numbers or hyphens, a letter first.'), row('Command', cmdIn, 'Type the command you use to start your tool. {prompt} is where the ticket text goes.'), row('How the task goes in', via), err);
  const next = button('Save', 'primary sm', () => {
    const draft = {name:nameIn.value.trim(), command:cmdIn.value, prompt_via:via.value};
    err.textContent = !/^[a-z][a-z0-9-]{1,31}$/.test(draft.name) ? 'Name: 2–32 characters, a lowercase letter first, then lowercase letters, numbers or hyphens.'
      : !draft.command.trim() || /[\r\n\u2028\u2029]/.test(draft.command) || Array.from(draft.command).length > 500 ? 'Enter a command on one line, up to 500 characters.' : '';
    if (err.textContent) return;
    fields.hidden = true;
    preview.hidden = false;
    preview.replaceChildren(el('p', 'meta', 'orch will run this for each ticket:'), settingsText('pre', {className:'cmd-preview mono preserve-lines'}, draft.command),
      (() => { const a = el('div', 'acts'); a.append(back, button('Add helper', 'primary sm', async () => {
        const args = {name:draft.name, command:draft.command};
        if (draft.prompt_via === 'stdin') args.prompt_via = 'stdin';
        const result = await settingsSend('config.agent.add', args, 'add');
        if (!result.ok) { preview.hidden = true; fields.hidden = false; err.textContent = result.text; return; }
        await settingsSend('config.agent', {name:draft.name}, 'agent');
        window.orch.toast(draft.name + ' added and set as the default.', 'ok');
        cancel();
      })); return a; })());
  });
  const acts = el('div', 'acts');
  acts.append(button('Cancel', 'ghost sm', cancel), next);
  fields.append(acts);
  form.append(fields, preview);
  slot.replaceChildren(form);
  nameIn.focus();
}
// The catalogue ("Add add-ons": pick several, one run) is pages/addon-add.js (ORCH-1739).
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
  const [lead, ...rest] = String(text).split('\n');
  if (rest.length && cls === 'preserve-lines') {
    // one plain sentence first; the technical lines (version, command, where data is kept) behind a small click
    d.append(settingsText('p', {}, lead), h('details', {className:'meta'}, settingsText('summary', {}, 'Details'), settingsText('pre', {className:cls + ' consent-details'}, rest.join('\n'))), actions);
  } else d.append(settingsText('pre', {className:cls}, text), actions);
  window.orch.open(d);
}
async function settingsSend(op, args, key, run) {
  settingsBusy.add(key);
  render();
  const result = await (run ? run(op, args) : act(op, args));
  settingsBusy.delete(key);
  if (!result.ok) window.orch.toast(result.text, 'error');
  else if (op === 'addon.set') window.orch.toast(args.on ? 'Turned on.' : 'Turned off.', 'ok');
  render();
  return result;
}
// The review step: the control opens the panel and the keyboard moves into it; Cancel or Escape closes it and the
// keyboard goes back to the control; the panel's first button runs the same action the control ran before.
const settingsReviewFocus = key => { if (key) document.querySelector('[data-key="' + key + '"]')?.focus(); };
function settingsReviewOpen(id, control) {
  if (snapshot || control.disabled || !SETTINGS_REVIEW_BUSY[id]) return;
  settingsReview = id;
  settingsReviewFrom = control.dataset.key || null;
  render();
  settingsReviewFocus('settings-review-' + id);
}
function settingsReviewClose() {
  const from = settingsReviewFrom;
  settingsReview = null; settingsReviewFrom = null;
  render();
  settingsReviewFocus(from);
}
async function settingsReviewRun() {
  const id = settingsReview, from = settingsReviewFrom, settings = state.settings || {};
  if (!id || snapshot || settingsBusy.has(SETTINGS_REVIEW_BUSY[id])) return;
  settingsReview = null; settingsReviewFrom = null;
  if (id === 'share') {
    const on = settings.share !== true;
    const result = await settingsSend('share.set', {on}, 'share');
    if (result.ok) window.orch.toast(on ? 'Shared. Your team can now see this workspace.' : 'Not shared any more.', 'ok');
  } else if (id === 'workflow') await settingsSend('workflow.set', {on:!settings.agents_may_finish}, 'workflow');
  else if (id === 'copies-switch') await settingsSend('copies.set', {mode:copiesModeOf(settings) === 'off' ? 'together' : 'off'}, 'copies');
  else await settingsSend('copies.clean', {}, 'copies-clean');
  settingsReviewFocus(from);
}

const addonViews = Object.create(null), addonBusy = new Set();
let addonTimer, activeAddon = null;
// The label comes from the add-on's own manifest; `panel` is a capability the manifest declares (repeats | links | phone).
const panelOf = id => addons().find(a => a.name === id)?.dashboard?.panel || null;
const addonLabel = a => a?.dashboard?.label || a?.label || a?.name || 'Add-on';
// A page served by the add-on's background service: while that service is stopped the page shows why and a Start
// button (addon.start, like Start now in the catalogue) instead of the proxy's bare "not found".
function pageStopped(r) {
  const svc = array(state?.services).filter(s => s && s.addon === r.id);
  if (snapshot || !svc.length || svc.some(s => s.running === true)) return null;
  const label = addonLabel(addons().find(a => a.name === r.id));
  return fragment(h('section', {className:'card pad stack', 'data-key':'page-stopped'},
    h('div', {className:'row'}, h('p', {className:'grow'}, label + ' isn’t running.'),
      h('button', {type:'button', className:'btn primary sm', 'data-action':'start', 'data-key':'page-start'}, 'Start'))));
}
// Every add-on page runs sandboxed: its own origin is opaque, so a script in it can never read this page's
// secret or reach into this page (ORCH-186). One orch ships acts with a pass for that add-on only, handed over in
// the frame address's fragment (kit/frame.js takes it out at once); one orch did not ship gets no pass.
const SHIPPED_SANDBOX = 'allow-scripts allow-forms allow-popups allow-popups-to-escape-sandbox allow-downloads';
const framePasses = new Map(), framePassAsks = new Map(), framePassFailed = new Map(), frameFresh = new Map();
let frameGen = 0;  // a dashboard restart (framesForget) ends every pass ask still under way: its answer is the old run's
// The server ends a pass after its life (`life` seconds, framepass.py LIFE): one kept longer is asked for again
// before a page opens with it, so its first call never answers 401 (ORCH-1004). The frame on screen keeps its pass
// (a new one would load it again); when that one ends, its next call answers 401 and the frame asks for new ones.
function framePass(name) {
  const kept = framePasses.get(name);
  if (kept && (Date.now() < kept.until || frameShown()?.getAttribute('src')?.includes('#orch-frame=' + kept.pass + '&'))) return kept;
  if (kept) framePasses.delete(name);
  if (framePassAsks.has(name) || Date.now() - (framePassFailed.get(name) || 0) < 10000) return null;
  const asked = Date.now(), gen = frameGen;  // the server's clock for the pass starts before its answer arrives
  const ask = fetch('/api/frame-pass', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({addon:name})})
    .then(r => r.ok ? r.json() : null)
    .then(j => {
      if (gen !== frameGen) return;
      // used up to 60 s before the server ends it (half its life when that is short)
      const life = Number.isFinite(j?.life) && j.life > 0 ? j.life : 900, keep = Math.max(life / 2, life - 60);
      if (j && typeof j.pass === 'string' && typeof j.file === 'string') framePasses.set(name, {pass:j.pass, file:j.file, chan:frameChanNew(), until:asked + keep * 1000});
      else framePassFailed.set(name, Date.now());
    })
    .catch(() => { if (gen === frameGen) framePassFailed.set(name, Date.now()); })
    .finally(() => { if (framePassAsks.get(name) === ask) framePassAsks.delete(name); if (gen === frameGen && framePasses.has(name)) render(); });
  framePassAsks.set(name, ask);
  return null;
}
// A per-frame code the page's messages must carry: a document that is navigated into the frame (not the add-on's
// own page, which got it in its address) cannot drive the dashboard (ORCH-186 review M1).
function frameChanNew() { const b = new Uint8Array(16); crypto.getRandomValues(b); return Array.from(b, x => x.toString(16).padStart(2, '0')).join(''); }
globalThis.orchFrameChan = () => { const r = route(); return r.kind === 'page' ? framePasses.get(r.id)?.chan || null : null; };
// Passes go only to the add-on's own page (its start page and its own places such as t/<id>), never to one of
// its files, pictures, answers or ticket pages (api/, page/, kit/, web/, or any name with a dot): those can carry
// content an agent made (ORCH-186 review H1).
const frameEntry = path => /^[A-Za-z0-9_\/-]{0,300}$/.test(path) && !/^(api|page|kit|web)(\/|$)/i.test(path) && !path.includes('//');
// The shown page moved inside itself (frame-at, ORCH-241): while the address is the one it moved to, the frame keeps
// the address it was opened with, so drawing the page again never reloads it. {id, hash, pass, src}
// Only while that same frame is still on screen: a new frame (back from another page) opens at the address's place.
let frameKeep = null;
const frameShown = () => document.querySelector('iframe.embed[data-key="embed"]');
// The shown add-on page takes the keyboard once it has loaded, so its own keys (such as 1 to 4) work without a click
// first (ORCH-465); never while the person types in a field of the dashboard or a dialog is open.
function frameTakesKeys(frame, doc = document) {
  const a = doc.activeElement;
  if (!frame.isConnected || doc.querySelector('dialog[open]')) return false;
  if (a && a !== doc.body && a !== frame && a.matches?.('input,textarea,select,[contenteditable],[contenteditable] *')) return false;
  frame.focus({preventScroll:true});
  return true;
}
function pageFrame(r) {
  const stopped = pageStopped(r);
  if (stopped) return stopped;
  const shipped = !!addons().find(a => a.name === r.id)?.shipped, base = '/addon/' + r.id + '/' + r.path;
  const entry = shipped && frameEntry(r.path), p = entry ? framePass(r.id) : null;
  if (entry && !p) { const wait = skeletonFor('page'); wait.dataset.key = 'embed-skeleton'; return wait; }
  const kept = entry && frameKeep && frameKeep.id === r.id && frameKeep.hash === r.hash && frameKeep.pass === p.pass && frameShown()?.getAttribute('src') === frameKeep.src ? frameKeep.src : null;
  if (!kept) frameKeep = null;
  const src = kept || (entry ? base + '#orch-frame=' + p.pass + '&orch-file=' + p.file + '&orch-chan=' + p.chan + (r.inner ? '&' + r.inner : '') : base + (r.inner ? '#' + r.inner : ''));
  const frame = h('iframe', {className:'embed' + (shellAddons.has(r.id) ? ' embed-shell' : ''), 'data-key':'embed', src, title:addonLabel(addons().find(a => a.name === r.id)), allow:'fullscreen', sandbox:shipped ? SHIPPED_SANDBOX : 'allow-scripts'});  // allow alone: both log a warning (ORCH-186)
  frame.addEventListener('load', () => frameTakesKeys(frame));
  // A skeleton shows until the add-on page has painted, then goes (no blank frame on add-on switch).
  const skeleton = framesLoaded.has(src) ? null : skeletonFor('page'), done = () => { framesLoaded.add(src); document.querySelectorAll('[data-key="embed-skeleton"]').forEach(n => n.remove()); };
  if (skeleton) { skeleton.dataset.key = 'embed-skeleton'; frame.addEventListener('load', done, {once:true}); frame.classList.add('embed-loading'); frame.addEventListener('load', () => frame.classList.remove('embed-loading'), {once:true}); }
  return fragment(skeleton, frame);
}
// The shown shipped add-on page asks to open another of its places (a link, or a fresh pass after a reload or an
// expired one): the dashboard opens it, so the new page gets a pass. A link to the dashboard's own page moves it.
// A move inside the page itself (frame-at) only changes the address: the frame is not loaded again.
globalThis.addEventListener?.('message', e => {
  const d = e.data, r = route();
  if (snapshot || e.origin !== 'null' || !d || !['frame-go', 'frame-top', 'frame-at'].includes(d.orch) || r.kind !== 'page') return;
  const frame = document.querySelector('iframe.embed[data-key="embed"]');
  if (!frame || e.source !== frame.contentWindow || !addons().find(a => a.name === r.id)?.shipped) return;
  const hash = typeof d.hash === 'string' && /^[A-Za-z0-9_\/-]{0,200}$/.test(d.hash) ? d.hash : null;
  if (hash === null) return;
  if (d.orch === 'frame-top') { if (hash && d.chan && d.chan === globalThis.orchFrameChan()) location.hash = '#' + hash; return; }
  const prefix = '/addon/' + r.id + '/', rel = typeof d.path === 'string' && d.path.startsWith(prefix) ? d.path.slice(prefix.length) : null;
  if (rel === null || rel.startsWith('/') || !frameEntry(rel)) return;  // only the add-on's own page gets opened with a pass
  if (d.orch === 'frame-at') {  // only the page that had the code, and only a place on the page that is shown
    if (!d.chan || d.chan !== globalThis.orchFrameChan() || rel !== r.path) return;
    const at = '#addon/' + r.id + (rel ? '/' + rel : '') + (hash ? '#' + hash : '');
    if (location.hash === at) return;
    const src = frame.getAttribute('src') || '';
    try { followAddress(at); } catch (_) { return; }  // the browser may refuse many address changes in a row
    frameKeep = {id:r.id, hash:at, pass:/#orch-frame=([A-Za-z0-9_-]+)&/.exec(src)?.[1] || null, src};  // the pass the frame really has
    return;
  }
  if (d.fresh && d.chan && d.chan === globalThis.orchFrameChan()) {  // new passes only for the page that had the code
    if (Date.now() - (frameFresh.get(r.id) || 0) < 5000) return;
    frameFresh.set(r.id, Date.now()); framePasses.delete(r.id);
  }
  const next = '#addon/' + r.id + (rel ? '/' + rel : '') + (hash ? '#' + hash : '');
  if (location.hash !== next) location.hash = next;
  else render();
});
const framesLoaded = new Set();
// The shown frame got the dashboard's starting page (its add-on's service is restarting after an add-on was added or
// removed, ORCH-1055): open a new frame in a moment. Only this page can: a reload from inside the sandboxed frame is
// cross-site and refused. A new element, as the same address with its #pass would not load again. Meanwhile the
// page's skeleton shows (the starting page itself is empty). At most FRAME_RETRIES times per address within 5
// minutes; after that the skeleton stays until the person opens the page again.
const FRAME_RETRY_MS = 2000, FRAME_RETRIES = 30, frameRetries = new Map(), frameRetrying = new WeakSet();
globalThis.addEventListener?.('message', e => {
  const frame = frameShown(), r = route();
  if (snapshot || e.origin !== 'null' || e.data?.orch !== 'frame-starting' || r.kind !== 'page' || !frame || e.source !== frame.contentWindow) return;
  if (frameRetrying.has(frame)) return;  // already opening it again
  const was = frameRetries.get(r.hash), fresh = !was || Date.now() - was.since > 5 * 60000;  // a later restart counts anew
  const n = fresh ? 1 : was.n + 1;
  if (n > FRAME_RETRIES) return;
  frameRetries.set(r.hash, {n, since:fresh ? Date.now() : was.since});
  const src = frame.getAttribute('src') || '';
  framesLoaded.delete(src);  // the starting page was no load of the add-on page: the new frame gets its skeleton
  if (!document.querySelector('[data-key="embed-skeleton"]')) {
    const wait = skeletonFor('page'); wait.dataset.key = 'embed-skeleton'; frame.before(wait);
  }
  frame.classList.add('embed-loading');
  frameRetrying.add(frame);
  setTimeout(() => {
    if (!frame.isConnected || frameShown() !== frame || route().hash !== r.hash) return;  // the person moved on
    document.querySelectorAll('[data-key="embed-skeleton"]').forEach(n => n.remove());
    frame.replaceWith(pageFrame(route()));
  }, FRAME_RETRY_MS);
});
// The dashboard restarted (app.js noteBoot): its passes are gone. Forget ours and the shown frame itself, so the
// next drawing asks for a new pass and loads the add-on page anew: also one that failed while the dashboard was down
// (its calls refused), which would wait for its own next refresh. A new element: a new #pass alone loads nothing.
function framesForget() {
  frameGen++; framePassAsks.clear();
  framePasses.clear(); framePassFailed.clear(); frameFresh.clear(); frameRetries.clear(); frameKeep = null;
  frameShown()?.remove();
}
// A page that is the dashboard's own shell (three columns, no header) says so once; its frame then fills the page.
const shellAddons = new Set();
globalThis.addEventListener?.('message', event => {
  const ours = event.origin === location.origin || (event.origin === 'null' && !!event.data?.chan && event.data.chan === globalThis.orchFrameChan() && [...document.querySelectorAll('iframe.embed')].some(f => f.contentWindow === event.source));
  const name = ours && event.data?.orch === 'embed-shell' && /^\/addon\/([a-z][a-z0-9-]{1,31})\//.exec(String(event.data.path || ''))?.[1];
  if (!name || shellAddons.has(name)) return;
  shellAddons.add(name);
  document.querySelectorAll('iframe.embed').forEach(f => { if ((f.getAttribute('src') || '').startsWith('/addon/' + name + '/')) f.classList.add('embed-shell'); });
});
const addonHost = id => h('div', {id:'addon-body', className:'stack', 'data-name':id});
// Sharing not connected yet (ORCH-2170, RP2): the admin's whole text is pasted on the add-on's own page and Connect
// runs its connect from that text (the core finds the connect line). The view asks for it with its Connect button.
const linkUi = {text:'', busy:false, error:''};
const linkNeedsConnect = id => isPublish(id) && !snapshot && addonViews[id]?.view?.header?.button?.action?.op === 'link.connect';
function linkPaste(id) {
  const a = addons().find(a => a.name === id);
  const input = h('textarea', {rows:4, className:'input', 'data-native':'link-text', 'data-key':'link-connect-text', 'aria-label':'Text from your admin', placeholder:'Paste the whole text here. It starts with “Connect this workspace…”', autocomplete:'off', spellcheck:'false', disabled:linkUi.busy});
  input.value = linkUi.text;
  return h('section', {className:'card pad stack-sm', 'data-key':'link-connect'},
    settingsText('h2', {}, 'Connect ' + addonTitle(a)),
    settingsText('p', {className:'meta'}, 'Your admin gives you a short text. Paste all of it here, then share a file.'),
    input,
    linkUi.error ? settingsText('p', {className:'meta', role:'alert', 'data-key':'link-connect-error'}, linkUi.error) : null,
    h('div', {className:'row'}, h('button', {type:'button', className:'btn sm primary', 'data-native':'link-connect', 'data-key':'link-connect-button', disabled:linkUi.busy}, linkUi.busy ? 'Connecting…' : 'Connect')));
}
async function linkConnect(id) {
  const text = linkUi.text.trim();
  if (linkUi.busy || !id) return;
  linkUi.error = text ? '' : 'Paste the text from your admin first.';
  linkUi.busy = !!text;
  paintAddon(id);
  if (!text) return;
  const result = await act('link.connect', {text});
  linkUi.busy = false;
  if (!result.ok) { linkUi.error = result.text || 'That did not work. Copy the whole text from your admin again and paste it here.'; paintAddon(id); return; }
  linkUi.text = '';
  window.orch.toast('Connected. You can share a file now.', 'ok');
  await loadAddon(id);
}
// Shared-link controls belong to the built-in sharing add-on only: a `panel` in some other add-on's manifest never earns them.
const isPublish = id => { const a = addons().find(a => a.name === id); return !!a && a.name === 'publish' && a.shipped === true; };
const sharingOn = () => addons().some(a => a.active !== false && isPublish(a.name));
const addonTitle = a => a?.dashboard?.title || addonLabel(a);
// The add-on's part of Settings (the Settings button in its page top), or null where this browser has no Settings.
const addonSettingsHref = id => snapshot || !state?.settings || !array(state.settings.addons).some(a => a && a.name === id) ? null : '#settings/addons/' + encodeURIComponent(id);
// The add-on's own page heading (manifest `title`/`subtitle`) with what its view puts at the right: a status pill, a
// quiet link and/or one primary button (view `header`). Redrawn when the view arrives.
function addonHeaderNodes(id) {
  const header = addonViews[id]?.view?.header;
  if (!header || snapshot) return [];
  const out = [];
  if (header.status) out.push(h('span', {className:'badge ' + (header.status.tone === 'good' ? 'done' : header.status.tone && header.status.tone !== 'neutral' ? 'paused' : ''), role:'status'}, (header.status.tone === 'good' ? '● ' : '') + clean(header.status.label)));
  const to = header.link ? OrchBlocks.appHash(header.link.to) : null;
  if (to) out.push(h('a', {className:'btn ghost sm', href:to}, clean(header.link.label)));
  const op = header.button?.action?.op;
  if (op === 'link.share' && isPublish(id)) out.push(h('button', {type:'button', className:'btn primary sm', 'data-native':'link-share'}, 'Share a file'));
  else if (op === 'addon.refresh') out.push(h('button', {type:'button', className:'btn outline sm', 'data-action':'retry-addon'}, clean(header.button.label)));
  return out;
}
const syncNative = () => !snapshot && array(state.settings?.addons).some(a => a.name === SYNC && a.active);
function addonTab(id) {
  // Sync is changed on its own page: the same card as in Settings, no trip to another page.
  if (id === SYNC && syncNative()) {
    const a = addons().find(a => a.name === id);
    return fragment(heading(addonTitle(a), a?.dashboard?.subtitle || '', {settings:addonSettingsHref(id)}), h('div', {className:'settings stack', 'data-key':'sync-page'}, h('div', {className:'stack'}, syncInfo(syncUi.card), syncCard(state.settings))));
  }
  // The Browser page (panel "browser", ORCH-1494): every helper's browser, drawn here (pages/livebrowse.js).
  if (panelOf(id) === 'browser' && typeof browserListPage === 'function') return browserListPage(addons().find(a => a.name === id));
  // The add-on that repeats tickets has a page of its own (its heading is its menu name): its main button sits in the heading.
  // One top for every page (D1, ORCH-2282): Settings first on the right (this add-on's part of Settings), then the
  // view's own status and link, the one filled button last.
  const a = addons().find(a => a.name === id), slot = h('div', {id:'addon-header', className:'row'}, addonHeaderNodes(id));
  const settings = addonSettingsHref(id);
  if (panelOf(id) === 'repeats') {
    const add = snapshot ? null : h('button', {type:'button', className:'btn primary sm', 'data-native':'repeat'}, iconEl('plus'), 'New repeat');
    if (add) add.onclick = () => repeatsDialog(null, id);
    return fragment(heading(addonTitle(a), a?.dashboard?.subtitle || 'Repeat work on a plan you choose.', {settings, actions:h('div', {className:'row'}, slot, add)}), addonHost(id));
  }
  return fragment(heading(addonTitle(a), a?.dashboard?.subtitle || '', {settings, actions:slot}), addonHost(id));
}
// The add-on whose blocks view is on screen: its own tab.
function shownAddon() {
  const r = route();
  return r.kind === 'addon' && !(r.id === SYNC && syncNative()) && panelOf(r.id) !== 'browser' ? r.id : null;
}
// The address names a tab like its label: Helper is #settings/helper, Contacts is #settings/contacts.
const SETTINGS_TAB_ADDRESS = {agent:'helper', phone:'contacts'};
// Choosing a Settings tab stays on Settings: the address becomes #settings/<tab> (one history entry, so Back returns to the tab before).
function settingsGo(tab) {
  settingsTab = tab;
  settingsAddon = null;
  settingsReview = null;
  if (location.hash !== '#settings/' + (SETTINGS_TAB_ADDRESS[tab] || tab)) history.pushState(null, '', '#settings/' + (SETTINGS_TAB_ADDRESS[tab] || tab));
  render();
}
function addonBody(a, res) {
  if (!res) return fragment(skeletonFor('section'));
  const retry = snapshot ? null : h('button', {type:'button', className:'btn outline sm', 'data-action':'retry-addon'}, 'Try again');
  if (res.state === 'error' || !res.view) return fragment(h('section', {className:'card pad stack'}, h('h2', {}, 'Can’t show ', addonLabel(a), ' right now.'), h('p', {}, res.message || 'It did not answer.', ' Nothing here was changed.'), retry));
  return fragment(res.state === 'stale' ? h('p', {className:'meta'}, 'As of ', time(res.as_of)) : null,
    res.state === 'stale' ? h('div', {className:'banner attn', role:'status'}, h('p', {className:'grow'}, 'Not up to date. Showing the last answer from ', time(res.as_of), '.', res.message ? ' ' + clean(res.message) + ' Newer items may be missing.' : ''), retry) : null,
    addonNotice(res.view), h('div', {id:'addon-blocks'}));
}
function addonNotice(view) {
  if (!view.notice) return null;
  if (view.header?.status && view.notice_tone === 'good') return null;   // the heading's status pill already says it
  const tone = 'banner ' + (view.notice_tone === 'bad' ? 'error' : ['warn', 'needs-you'].includes(view.notice_tone) ? 'attn' : '');
  const b = view.button;
  // "Running. Next run in 2 days." -> a small state badge and the rest of the line
  const split = view.notice_tone === 'good' && /^([^.]{1,24})\. (.+)$/.exec(String(view.notice));
  if (split) return h('p', {className:'status-line'}, h('span', {className:'badge done'}, '● ' + clean(split[1])), h('span', {}, clean(split[2])));
  const op = b?.action?.op;
  if (snapshot || (op !== 'addon.start' && op !== 'addon.refresh')) return h('p', {className:tone}, clean(view.notice));
  return h('div', {className:tone}, h('p', {className:'grow'}, clean(view.notice)), h('button', {type:'button', className:'btn outline sm', 'data-action':op === 'addon.start' ? 'start' : 'retry-addon'}, clean(b.label)));
}
let pendingRepeat = null;  // {addon, tid, title, plan, removing, savedAt}: the repeat being saved or removed, shown as a row
// The cells of that row: "DEM-9 · Weekly report · Saving…" first, the new plan in the second cell (one line when one cell).
// ORCH-1006: once stored (savedAt) the row drops the Saving word at once, with the toast, and stays until the list has it.
function pendingCells(n, p) {
  const head = p.title + (p.savedAt ? '' : p.removing ? ' · Removing…' : ' · Saving…');
  if (n < 2) return [head + (p.plan && !p.removing ? ' · ' + p.plan : '')];
  return Array.from({length:n}, (_, i) => i === 0 ? head : i === 1 && !p.removing ? p.plan || '' : '');
}
function paintAddon(id) {
  const host = document.getElementById('addon-body'), a = addons().find(a => a.name === id);
  if (!host || host.dataset.name !== id || !a) return;
  const scroll = [window.scrollX, window.scrollY];
  const template = addonBody(a, addonViews[id]);
  const blocks = template.querySelector('#addon-blocks');
  if (blocks) {
    if (linkNeedsConnect(id)) blocks.append(linkPaste(id));   // not connected yet: the paste box is the page (RP2)
    else blocks.append(OrchBlocks.render(addonViews[id].view.blocks, {addonUrl, self:id, links:isPublish(id), inApp:name => addons().some(a => a.name === name && a.page) ? path => pageHash(name, path) : null}));
    if (!blocks.childNodes.length) blocks.append(stateNote('Nothing to show yet', 'It fills in as work happens.'));
    blocks.querySelectorAll('.blk:not(.blk-above)').forEach(n => n.classList.add('card'));
    // Block text is supplied by add-ons; keep internal keys out of visible copy.
    const walker = document.createTreeWalker(blocks, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) walker.currentNode.data = clean(walker.currentNode.data);
  }
  // A repeat that is being saved or removed shows at once, with its number and plan, until the list has the change:
  // in place of the ticket's own row when it has one, else as a new row on top.
  // A removed repeat simply leaves. With no table yet (the first repeat) the line takes the place of the empty card,
  // never above a "No schedules yet" (ORCH-1006).
  if (pendingRepeat && pendingRepeat.addon === id && blocks) {
    const body = blocks.querySelector('table tbody'), first = body?.querySelector('tr');
    const own = body ? [...body.querySelectorAll('[data-addon-edit]')].find(n => n.dataset.addonEdit === pendingRepeat.tid)?.closest('tr') : null;
    if (pendingRepeat.removing && pendingRepeat.savedAt) own?.remove();
    else if (body && first) {
      const row = h('tr', {'data-key':'repeat-saving', role:'status'}, pendingCells((own || first).children.length, pendingRepeat).map(text => h('td', {}, text)));
      if (own) own.replaceWith(row); else body.prepend(row);
    } else if (!pendingRepeat.removing) {
      const empty = blocks.querySelector('.blk-empty');
      if (empty) {   // drawn as the list's own row: the name, the plan below it
        const [head, plan] = pendingCells(2, pendingRepeat);
        empty.replaceWith(h('ul', {className:'blk-list'}, h('li', {'data-key':'repeat-saving', role:'status'},
          h('span', {className:'li-row'}, h('span', {className:'li-main'}, h('span', {className:'li-title'}, head), plan ? h('small', {className:'li-sub'}, plan) : null)))));
      } else blocks.prepend(h('p', {className:'status-line', 'data-key':'repeat-saving', role:'status'}, pendingCells(1, pendingRepeat)[0]));
    }
  }
  reconcile(host, template);
  const slot = document.getElementById('addon-header');
  if (slot) { slot.replaceChildren(...addonHeaderNodes(id)); bindAddonControls(slot); }
  bindAddonControls(host);
  host.querySelectorAll('[data-action="retry-addon"]').forEach(n => { n.disabled = false; });
  window.scrollTo(...scroll);
}
const addonAgain = new Set();
async function loadAddon(id, manual = false) {
  if (addonBusy.has(id)) { addonAgain.add(id); return; }  // a load is under way: it may predate this change, so one more follows it
  if (addonChanging()) return;
  if (!snapshot && state && !addons().some(a => a.name === id)) return;  // turned off or removed: nothing to ask
  addonBusy.add(id);
  const asked = Date.now();  // a load asked after a repeat was stored has it: the waiting row can go (ORCH-1006)
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
    addonViews[id] = addonViews[id]?.view ? {...addonViews[id], state:'stale'} : {state:'error', message:'It did not answer.'};
  } finally { addonBusy.delete(id); }
  if (pendingRepeat?.savedAt && pendingRepeat.addon === id && asked >= pendingRepeat.savedAt) pendingRepeat = null;
  if (isPublish(id) && !snapshot) await loadSharedLinks();
  if (shownAddon() === id) paintAddon(id);
  if (addonAgain.delete(id)) await loadAddon(id);
}
// The view of an add-on tab costs the server about half a second the first time. Fetch each once in the background
// (a quiet start after the first screen, one at a time) so the first click has something to show; a menu entry that
// is hovered is fetched at once. The page add-ons (own web page) and the native Sync card have no view to fetch.
let addonsWarmed = false;
const warmable = id => { const a = addons().find(a => a.name === id); return !!a && !!a.dashboard && !a.page && a.dashboard.panel !== 'browser' && !(id === SYNC && syncNative()); };
async function warmAddonView(id) {
  if (snapshot || addonViews[id] || addonBusy.has(id) || !warmable(id)) return;
  await loadAddon(id);
}
function warmAddons() {
  if (addonsWarmed || snapshot || !state) return;
  const queue = addons().map(a => a.name).filter(warmable);
  if (!addons().length) return;  // the add-ons are not known yet: look again at the next render
  addonsWarmed = true;
  const step = async () => {
    const id = queue.shift();
    if (id === undefined) return;
    await warmAddonView(id);
    setTimeout(step, 400);
  };
  setTimeout(step, 1500);
}
function startAddon(id) {
  clearInterval(addonTimer);
  activeAddon = id;
  paintAddon(id);
  loadAddon(id);
  if (!snapshot) addonTimer = setInterval(() => { if (document.visibilityState !== 'hidden') loadAddon(id); }, 15000);
}

// An add-on row's switch or button: the DOM only carries verb + ticket (blocks.js checked them); the page adds
// the add-on of the open tab, so a view can never address another add-on.
// One add-on action runs at a time: a click during another one waits its turn, its button busy meanwhile (ORCH-1806).
const addonTurn = () => new Promise(done => { const look = () => locks.has('addon-act') ? setTimeout(look, 150) : done(); look(); });
async function addonAct(control) {
  const id = shownAddon();
  if (!id || control.disabled) return;
  if (locks.has('addon-act')) {
    control.disabled = true; control.setAttribute('aria-busy', 'true');
    await addonTurn();
    control.disabled = false; control.removeAttribute('aria-busy');
    if (shownAddon() !== id) return;   // the person left this add-on meanwhile
  }
  if (control.dataset.review) return addonReview(id, control);
  const send = async () => {
    locks.add('addon-act'); control.disabled = true;
    const result = await act('addon.act', {addon:id, verb:control.dataset.verb, target:control.dataset.target});
    locks.delete('addon-act'); if (control.isConnected) control.disabled = false;
    if (!result.ok && /^No helper is set yet/.test(result.text || '')) {   // one click to the place that fixes it
      const {d, actions} = dialog('No helper is set yet', 'dialog');
      d.append(el('p', '', 'Choose a helper first, then start again.'));
      actions.append(button('Open Helper settings', 'primary', async () => { await window.orch.close(d); location.hash = '#settings/helper'; }));
      d.append(actions); window.orch.open(d);
    } else if (!result.ok) window.orch.toast(result.text || 'That did not work.', 'error');
    else if (control.closest('.blk-split')) {   // list and panel: say what happened, in the add-on's own words
      const said = result.state?.act_answer?.addon === id ? result.state.act_answer.answer?.next : null;
      if (typeof said === 'string' && said) window.orch.toast(clean(said.split(/(?<=\.)\s/)[0]).slice(0, 160), 'ok');   // the first sentence: no path, no command
    }
    await loadAddon(id);
  };
  if (!control.dataset.confirm) return send();
  const {d, actions} = dialog(control.dataset.confirm, 'dialog');
  if (control.dataset.confirmLines) {
    // What will happen, in plain lines; Keep it and the action's own word (danger look), never a typed word.
    const list = el('ul');
    control.dataset.confirmLines.split('\n').filter(Boolean).forEach(line => list.append(el('li', '', line)));
    d.append(el('p', '', 'This is what happens:'), list);
    actions.firstChild.textContent = control.dataset.keep || 'Keep it';
    actions.append(button(control.dataset.label || 'Yes', 'danger', async () => { await window.orch.close(d); send(); }));
  } else actions.append(button('Yes', 'primary', async () => { await window.orch.close(d); send(); }));
  d.append(actions);
  window.orch.open(d);
}
// "Allow this script" on a repeat whose script is not allowed here yet: the add-on answers what the person reads
// (the command in full, never behind Details) and a target that ends in the entry's key; the click sends that key back,
// so only what was shown is allowed (as Settings > Allow this command).
async function addonReview(id, control) {
  if (snapshot) return;
  const args = {addon:id, verb:control.dataset.verb, target:control.dataset.target};
  // reading what the add-on would allow takes a few seconds: say so on the button, so the click is seen at once
  const label = control.textContent;
  locks.add('addon-act'); control.disabled = true; control.setAttribute('aria-busy', 'true'); control.textContent = 'Checking\u2026';
  const asked = await act('addon.act', {...args, review:true});
  locks.delete('addon-act'); control.disabled = false; control.removeAttribute('aria-busy'); control.textContent = label;
  const got = asked.ok && asked.state?.act_answer?.addon === id ? asked.state.act_answer.answer : null;
  const key = typeof got?.target === 'string' ? (/:([0-9a-f]{64})$/.exec(got.target) || [])[1] : null;
  if (!got?.review || typeof got.review.title !== 'string' || !key) {
    window.orch.toast(asked.text || 'This can\u2019t be allowed right now. Nothing was changed.', 'error');
    return;
  }
  const text = [got.review.value, got.review.body].filter(x => typeof x === 'string' && x).join('\n\n');
  settingsConfirm(String(got.review.title), text, 'scroll-all', 'Allow', async () => {
    locks.add('addon-act');
    const result = await act('addon.act', {...args, value:key});
    locks.delete('addon-act');
    window.orch.toast(result.ok ? 'Script allowed.' : result.text || 'That did not work.', result.ok ? 'ok' : 'error');
    await loadAddon(id);
  });
}
// "Allow on this computer" on a schedule that came by sync: the person signs sync's own Allow for that ticket's
// block (the sign step shows exactly the block); afterwards the page reads the add-on again.
async function syncAllow(tid) {
  const id = shownAddon();
  if (!id || !/^t_[a-z0-9]{6,16}$/.test(String(tid)) || locks.has('addon-act')) return;
  await signedAct({addon:SYNC, verb:'allow', target:tid + ':' + id}, 'Allowed on this computer.', () => loadAddon(id));
}
async function addonRadio(input) {
  const id = shownAddon();
  if (snapshot || !id) return;
  if (input.dataset.radioGo) { location.hash = '#' + input.dataset.radioGo; return; }
  if (locks.has('addon-act')) return;
  const group = [...input.closest('.sync-options').querySelectorAll('input')];
  locks.add('addon-act'); group.forEach(n => { n.disabled = true; });
  const result = await act('addon.act', {addon:id, verb:input.dataset.radioVerb, target:input.dataset.radioTarget});
  locks.delete('addon-act');
  window.orch.toast(result.ok ? 'Saved.' : result.text || 'That did not work.', result.ok ? 'ok' : 'error');
  await loadAddon(id);
}
// Contacts (message keys, ORCH-1203): Accept sends the fingerprint the person saw (the core refuses it when the
// key changed meanwhile) and their own name for the contact; Stop trusting asks once, with the action's own word.
const CONTACT_ID = /^(ws|ph)_[a-z0-9]{10}$/;
async function contactAccept(control) {
  const id = shownAddon();
  if (snapshot || !id || locks.has('addon-act') || !CONTACT_ID.test(control.dataset.contactAccept || '')) return;
  const name = (control.closest('form')?.querySelector('input[name=name]')?.value || '').trim().slice(0, 60);
  locks.add('addon-act'); control.disabled = true;
  const result = await act('contact.accept', {peer:control.dataset.contactAccept, fingerprint:control.dataset.fingerprint, name});
  locks.delete('addon-act'); if (control.isConnected) control.disabled = false;
  window.orch.toast(result.ok ? 'Accepted ' + clean(name || control.dataset.who || '').slice(0, 60) + '.' : result.text || 'That did not work.', result.ok ? 'ok' : 'error');
  await loadAddon(id);
}
function contactWithdraw(control) {
  const id = shownAddon(), peer = control.dataset.contactWithdraw;
  if (snapshot || !id || locks.has('addon-act') || !CONTACT_ID.test(peer || '')) return;
  const who = clean(control.dataset.who || '').slice(0, 60);
  const {d, actions} = dialog('Stop trusting ' + who + '?', 'dialog');
  const list = el('ul');
  ['Its messages wait and nothing from it runs.', 'You can accept it again here at any time.'].forEach(line => list.append(el('li', '', line)));
  d.append(el('p', '', 'This is what happens:'), list);
  actions.firstChild.textContent = 'Keep trusting';
  actions.append(button('Stop trusting', 'danger', async () => {
    await window.orch.close(d);
    locks.add('addon-act');
    const result = await act('contact.withdraw', {peer});
    locks.delete('addon-act');
    window.orch.toast(result.ok ? 'Stopped trusting ' + who + '.' : result.text || 'That did not work.', result.ok ? 'ok' : 'error');
    await loadAddon(id);
  }));
  d.append(actions); window.orch.open(d);
}
// Workspace messages are composed in their persistent Chat thread.
function messageSend(control) {
  if (snapshot) return;
  const peer = control.dataset.sendTo;
  if (/^ws_[a-z0-9]{10}$/.test(peer)) { if (typeof chatDmHint === 'function') chatDmHint(peer, control.dataset.who); location.hash = '#chat/' + peer; }
  else if (/^ph_[a-z0-9]{10}$/.test(peer) || peer === 'phones') location.hash = '#chat';
}
async function copyText(control) {
  try { await navigator.clipboard.writeText(control.dataset.copy); window.orch.toast('Copied', 'ok'); }
  catch (_) { window.orch.toast('Could not copy. Select the text and copy it.', 'error'); }
}

// The add-on that declares the `repeats` panel (state.addons lists only active add-ons, with no `active` field); null when off (then no Copy/Repeat shows on a ticket).
const repeatsAddon = () => addons().find(a => a.dashboard?.panel === 'repeats')?.name || null;
// ---- "How often": plain choices that become one of the phrases (or a five-field cron) the repeating add-on accepts. ----
const REPEAT_DAYS = [['Mon', 'Monday', 1], ['Tue', 'Tuesday', 2], ['Wed', 'Wednesday', 3], ['Thu', 'Thursday', 4], ['Fri', 'Friday', 5], ['Sat', 'Saturday', 6], ['Sun', 'Sunday', 0]];
const andList = list => list.length < 2 ? list.join('') : list.slice(0, -1).join(', ') + ' and ' + list[list.length - 1];
// {freq: daily|weekly|monthly|custom, days: [cron weekday numbers], monthday, every, time: 'HH:MM'} -> {phrase, summary, hint}
function repeatPlan(c) {
  if (c.freq === 'custom' && (c.unit === 'minutes' || c.unit === 'hours')) {  // a steady rhythm: no time of day
    const n = Number(c.every), mins = c.unit === 'minutes', word = mins ? 'minutes' : n === 1 ? 'hour' : 'hours';
    if (!Number.isInteger(n) || n < (mins ? 5 : 1) || n > (mins ? 59 : 23)) return {phrase:null, summary:mins ? 'Choose between 5 and 59 minutes.' : 'Choose between 1 and 23 hours.', hint:''};
    return {phrase:'every ' + n + ' ' + word, summary:'Repeats every ' + n + ' ' + word, hint:''};
  }
  const [hh, mm] = String(c.time || '').split(':').map(Number);
  if (!Number.isInteger(hh) || !Number.isInteger(mm) || hh < 0 || hh > 23 || mm < 0 || mm > 59) return {phrase:null, summary:'Choose a time.', hint:''};
  const at = String(hh).padStart(2, '0') + ':' + String(mm).padStart(2, '0');
  if (c.freq === 'daily') return {phrase:'daily ' + at, summary:'Repeats every day at ' + at, hint:''};
  if (c.freq === 'weekly') {
    const picked = REPEAT_DAYS.filter(d => c.days.includes(d[2]));
    if (!picked.length) return {phrase:null, summary:'Choose at least one day.', hint:''};
    const phrase = picked.length === 1 ? 'every ' + picked[0][1].toLowerCase() + ' ' + at : mm + ' ' + hh + ' * * ' + picked.map(d => d[2]).join(',');
    return {phrase, summary:'Repeats every ' + andList(picked.map(d => d[1])) + ' at ' + at, hint:''};
  }
  if (c.freq === 'monthly') {
    const day = Number(c.monthday);
    if (!Number.isInteger(day) || day < 1 || day > 31) return {phrase:null, summary:'Choose a day from 1 to 31.', hint:''};
    return {phrase:'monthly ' + day + ' ' + at, summary:'Repeats on day ' + day + ' of every month at ' + at, hint:day > 28 ? 'In shorter months it happens on the last day.' : ''};
  }
  const n = Number(c.every);
  if (!Number.isInteger(n) || n < 1 || n > 30) return {phrase:null, summary:'Choose between 1 and 30 days.', hint:''};
  if (n === 1) return {phrase:'daily ' + at, summary:'Repeats every day at ' + at, hint:''};
  return {phrase:mm + ' ' + hh + ' */' + n + ' * *', summary:'Repeats every ' + n + ' days at ' + at, hint:'Counted from the 1st of each month.'};
}
// The reverse of repeatPlan for the plans it writes: a saved 5-field cron -> the dialog's choices (null when it is some other plan).
function cronToChoice(cron) {
  const f = String(cron || '').trim().split(/\s+/);
  const base0 = {freq:'custom', days:[1], monthday:1, time:'08:00'};
  if (f.length === 5 && /^\*\/\d+$/.test(f[0]) && f.slice(1).every(x => x === '*') && Number(f[0].slice(2)) >= 5 && Number(f[0].slice(2)) <= 59) return {...base0, unit:'minutes', every:Number(f[0].slice(2))};
  if (f.length === 5 && f[0] === '0' && /^\*\/\d+$/.test(f[1]) && f.slice(2).every(x => x === '*') && Number(f[1].slice(2)) >= 1 && Number(f[1].slice(2)) <= 23) return {...base0, unit:'hours', every:Number(f[1].slice(2))};
  if (f.length !== 5 || !/^\d+$/.test(f[0]) || !/^\d+$/.test(f[1]) || f[3] !== '*') return null;
  const time = String(f[1]).padStart(2, '0') + ':' + String(f[0]).padStart(2, '0'), base = {freq:'weekly', days:[1], monthday:1, every:2, time};
  if (f[2] === '*' && f[4] === '*') return {...base, freq:'daily'};
  if (f[2] === '*' && /^[0-6](,[0-6])*$/.test(f[4])) return {...base, freq:'weekly', days:f[4].split(',').map(Number)};
  if (/^\d+$/.test(f[2]) && f[4] === '*') return {...base, freq:'monthly', monthday:Math.min(31, Number(f[2]))};
  if (/^\*\/\d+$/.test(f[2]) && f[4] === '*') return {...base, freq:'custom', unit:'days', every:Number(f[2].slice(2))};
  return null;
}
// A saved rule the choices below cannot show (set by the helper): its plain words, read-only. null when it is one of ours.
function cronWords(cron) {
  const f = String(cron || '').trim().split(/\s+/);
  if (f.length === 5 && /^\*\/\d+$/.test(f[0]) && f.slice(1).every(x => x === '*')) return 'every ' + f[0].slice(2) + ' minutes';
  if (f.length === 5 && f[0] === '0' && /^\*\/\d+$/.test(f[1]) && f.slice(2).every(x => x === '*')) return 'every ' + f[1].slice(2) + ' hours';
  return 'a custom plan';
}
// A saved repeat in plain words ("Repeats every Monday at 08:00"); a plan set by the helper in its own words.
function savedRepeatWords(cron) {
  const c = cronToChoice(cron), plan = c ? repeatPlan(c) : null;
  if (plan?.phrase) return plan.summary;
  const w = cronWords(cron);
  return w === 'a custom plan' ? 'Repeats on a custom plan' : 'Repeats ' + w;
}
// A ticket as the repeat list names it: its number first ("DEM-9 · Weekly sales report").
function repeatTicketName(t) { return (t.key ? t.key + ' · ' : '') + (t.title || t.id); }
const REPEAT_UNITS = [['minutes', 'minutes'], ['hours', 'hours'], ['days', 'days']];
const REPEAT_FREQ = [['daily', 'Every day'], ['weekly', 'Every week'], ['monthly', 'Every month'], ['custom', 'Custom']];
// The zone the repeat window's time is read in (ORCH-1861), from the add-on's `zones`: a ticket that already repeats
// its own (an old one without a zone reads in the zone it runs in), a new repeat the default `repeat` saves. Save
// keeps a repeat's own zone (the add-on does, ORCH-1969), so what the window names is what is saved.
function repeatZone(zones, tid, saved) {
  const isSaved = !!(tid && saved?.recurring === true && saved.cron);
  return (isSaved ? zones?.repeats?.[tid] || saved.tz : zones?.new) || 'Uses the workspace’s time zone.';
}

// The ticket is chosen in the window, or fixed when it is opened from a ticket's menu (`only`).
function repeatsDialog(only = null, addonName = null) {
  if (snapshot) return;
  const key = addonName || repeatsAddon();
  const repeatOf = id => { const x = tickets().find(t => t.id === id)?.ext?.[key]; return x?.recurring === true && x.cron ? x : null; };
  const saved = only ? tickets().find(t => t.id === only)?.ext?.[key] : null;
  const had = saved?.recurring === true ? cronToChoice(saved.cron) : null;
  const {d, actions} = dialog(had ? 'Edit repeat' : 'New repeat', 'dialog repeat-dialog');
  const ticket = h('select', {className:'input', name:'ticket', id:'repeat-ticket'});
  tickets().filter(t => only ? t.id === only : !['done', 'dropped'].includes(t.status)).forEach(t => ticket.append(new Option(repeatTicketName(t) + (!only && repeatOf(t.id) ? ' · already repeats' : ''), t.id)));
  const nameOf = id => repeatTicketName(tickets().find(t => t.id === id) || {id});
  const choice = had || {freq:'weekly', days:[1], monthday:1, every:2, time:'08:00', unit:'minutes'};
  const outside = !had && saved?.recurring === true && saved.cron ? cronWords(saved.cron) : null;  // set by the helper: shown, never overwritten silently
  if (outside) Object.assign(choice, {freq:'custom', unit:'minutes', every:5});
  const summary = h('p', {className:'repeat-summary', role:'status'}), hint = h('span', {className:'meta'});
  // The zone the time is read in, from the add-on (never the browser's): the chosen ticket's own repeat zone, a new
  // repeat's default. Saving keeps it (ORCH-1969).
  const zoneTag = h('span', {className:'meta', id:'repeat-zone', 'data-key':'repeat-zone'});
  const showZone = () => { zoneTag.textContent = repeatZone(addonViews[key]?.view?.zones, ticket.value, tickets().find(t => t.id === ticket.value)?.ext?.[key]); };
  showZone();
  const waitZone = n => { showZone(); if (!addonViews[key]?.view?.zones && n > 0) setTimeout(() => waitZone(n - 1), 500); };
  if (!addonViews[key]?.view?.zones && !snapshot) loadAddon(key).then(() => waitZone(6), () => {});
  const rowsHost = h('div', {className:'schedule-fields'});
  const row = (label, ...kids) => h('div', {className:'schedule-row'}, h('span', {}, label), ...kids);
  const save = button('Save repeat', 'primary', async () => {
    const plan = repeatPlan(choice);
    if (save.disabled || !ticket.value || !plan.phrase) return;
    save.disabled = true;
    const target = ticket.value;
    await repeatSend(d, {addon:addonName || route().id, verb:'repeat', target, value:plan.phrase}, {tid:target, title:nameOf(target), plan:plan.summary}, 'Repeat saved.');
  });
  // A new repeat for a ticket that already repeats replaces that plan: the window says so and Save says Replace
  // (bug hunt 17 Nov: the old repeat was gone without a word).
  const replaces = h('p', {className:'banner attn', role:'status', 'data-key':'repeat-replaces', hidden:true});
  const refreshReplace = () => {
    const old = only ? null : repeatOf(ticket.value);
    replaces.hidden = !old;
    replaces.textContent = old ? 'This ticket already repeats ' + savedRepeatWords(old.cron).replace(/^Repeats /, '') + '. Saving replaces that plan.' : '';
    save.textContent = old ? 'Replace repeat' : 'Save repeat';
    showZone();
  };
  ticket.onchange = refreshReplace;
  const refreshSummary = () => {
    const plan = repeatPlan(choice);
    summary.textContent = plan.summary; hint.textContent = plan.hint;
    hint.hidden = !plan.hint; save.disabled = !plan.phrase || !ticket.options.length;
  };
  const draw = () => {
    const plan = repeatPlan(choice), kids = [];
    if (choice.freq === 'custom') {
      const unit = h('select', {className:'input', 'aria-label':'Minutes, hours or days'});
      REPEAT_UNITS.forEach(([v, label]) => unit.append(new Option(label, v)));
      unit.value = choice.unit || 'days';
      const n = h('input', {className:'input', type:'number', min:unit.value === 'minutes' ? '5' : '1', max:unit.value === 'minutes' ? '59' : unit.value === 'hours' ? '23' : '30', value:String(choice.every), 'aria-label':'How many'});
      n.oninput = () => { choice.every = n.value; refreshSummary(); };
      unit.onchange = () => { choice.unit = unit.value; choice.every = unit.value === 'minutes' ? Math.max(5, Number(choice.every) || 5) : Math.min(Number(choice.every) || 1, unit.value === 'hours' ? 23 : 30); draw(); };
      kids.push(row('Every', h('div', {className:'custom-interval'}, n, unit)));
      if (choice.unit !== 'days') kids.push(h('p', {className:'meta'}, 'Pick minutes or hours for a steady rhythm. For fixed times of day choose Every day or Every week.'));
    }
    if (choice.freq === 'weekly') {
      const chips = REPEAT_DAYS.map(([short, long, num]) => {
        const box = h('input', {type:'checkbox', value:String(num), 'aria-label':long});
        box.checked = choice.days.includes(num);
        box.onchange = () => { choice.days = box.checked ? [...choice.days, num] : choice.days.filter(x => x !== num); refreshSummary(); };
        return h('label', {className:'day-chip'}, box, h('span', {'aria-hidden':'true'}, short));
      });
      kids.push(row('Days of week', h('div', {className:'day-chips', role:'group', 'aria-label':'Days of week'}, chips)));
    }
    if (choice.freq === 'monthly') {
      const day = h('select', {className:'input', 'aria-label':'Day of month'});
      for (let i = 1; i <= 31; i++) day.append(new Option(i > 28 ? i + ' \u2014 or the last day in shorter months' : String(i), String(i)));
      day.value = String(choice.monthday);
      day.onchange = () => { choice.monthday = Number(day.value); refreshSummary(); };
      kids.push(row('Day of month', h('div', {className:'schedule-value'}, day, plan.hint ? hint : null)));
    }
    if (choice.freq !== 'custom' || choice.unit === 'days') {
      const time = h('input', {className:'input', type:'time', value:choice.time, required:'', 'aria-label':'Time', 'aria-describedby':'repeat-zone'});
      time.oninput = () => { choice.time = time.value; refreshSummary(); };
      kids.push(row('Time', h('div', {className:'schedule-value'}, h('div', {className:'schedule-time'}, time, zoneTag))));
    }
    rowsHost.replaceChildren(...kids);
    refreshSummary();
  };
  const freq = h('div', {className:'segmented frequency-control', role:'radiogroup', 'aria-label':'How often'},
    REPEAT_FREQ.map(([value, label]) => {
      const input = h('input', {type:'radio', name:'frequency', value});
      input.checked = value === choice.freq;
      input.onchange = () => { choice.freq = value; if (value === 'custom') { choice.unit = choice.unit || 'minutes'; if (choice.unit === 'minutes' && !(Number(choice.every) >= 5)) choice.every = 5; } draw(); };
      return h('label', {}, input, h('span', {}, label));
    }));
  const fields = h('div', {className:'form-fields'}, h('label', {className:'field'}, 'Ticket', ticket), replaces,
    h('fieldset', {className:'repeat-block'}, h('legend', {}, 'How often'), freq, rowsHost, summary,
      outside ? h('p', {className:'meta', 'data-key':'repeat-set-by-helper'}, 'Set by your helper: ' + outside + '. Change it with the options above.') : null));
  if (!ticket.options.length) fields.append(stateNote('No open tickets yet', 'A repeat needs a ticket to start from. Make one first.', 'empty', {label:'New ticket', onClick:async () => { await window.orch.close(d); location.hash = '#new'; }}));
  const copy = button('Run once now', 'ghost', async () => {
    if (!ticket.value) return;
    const result = await act('addon.act', {addon:addonName || route().id, verb:'copy', target:ticket.value});
    window.orch.toast(result.ok ? 'Ticket copied.' : result.text || 'That did not work.', result.ok ? 'ok' : 'error');
    if (result.ok) await window.orch.close(d);
    if (route().kind === 'addon') await loadAddon(route().id);
  });
  draw();
  // An existing schedule: Save changes, or remove it (its tickets stay); a new one may also copy the ticket.
  // Delete asks first, in the window itself, and sits apart from Save (bug hunt 17 Nov: it acted at once, next to Save).
  const sure = h('div', {className:'banner attn', role:'alert', 'data-key':'repeat-delete-confirm', hidden:true});
  const remove = button('Delete repeat', 'outline danger', () => {
    if (remove.disabled) return;
    remove.hidden = true; sure.hidden = false; yes.focus();
  });
  const keep = button('Keep it', 'ghost', () => { sure.hidden = true; remove.hidden = false; remove.focus(); });
  const yes = button('Delete repeat', 'danger', async () => {
    if (yes.disabled) return;
    yes.disabled = true; keep.disabled = true;
    await repeatSend(d, {addon:addonName || route().id, verb:'delete', target:only}, {tid:only, title:nameOf(only), removing:true}, 'Repeat removed. Its tickets stay.');
  });
  sure.append(h('p', {className:'grow'}, 'Delete this repeat? It stops repeating. The ticket and its history stay.'), keep, yes);
  if (had) { actions.prepend(remove, h('span', {className:'grow', 'aria-hidden':'true'})); actions.append(save); d.append(fields, sure, actions); }
  else { actions.append(copy, save); d.append(fields, actions); }
  refreshReplace();
  window.orch.open(d);
}
// Save or Delete in the repeat window: it closes at once and the list shows the change ("Saving…" / "Removing…",
// with the ticket's number) until it is stored. It always ends: the answer, or after 30 s a plain "taking too long"
// (the change may still have been made).
// Stored: the row loses its Saving word together with the toast and stays (plain) until a reload asked after the
// save has painted the list (ORCH-1006: the reload takes seconds, so clearing it later read "Saving…" after "Repeat saved").
async function repeatSend(d, args, pending, okText) {
  await window.orch.close(d);
  const mine = {...pending, addon:args.addon};
  pendingRepeat = mine;
  if (route().kind === 'addon') paintAddon(route().id);
  let timer;
  const late = new Promise(done => { timer = setTimeout(() => done({ok:false, text:'This is taking too long. Check the list, then try again.'}), 30000); });
  let result;
  try { result = await Promise.race([act('addon.act', args), late]); }
  catch (err) { result = {ok:false, text:'That did not work. Try again.'}; }
  finally { clearTimeout(timer); }
  if (pendingRepeat === mine) pendingRepeat = result.ok ? {...mine, savedAt:Date.now()} : null;
  if (route().kind === 'addon') paintAddon(route().id);
  window.orch.toast(result.ok ? okText : result.text || 'That did not work.', result.ok ? 'ok' : 'error');
  if (route().kind === 'addon') await loadAddon(route().id);
}
// `addon.prompt` (a row's Edit in an add-on view): one text line in a small window, prefilled; Save sends the add-on's
// own verb with the new text. 1 to 200 characters; the add-on's refusal is shown here in one sentence.
const PROMPT_MAX = 200;
function promptDialog(control) {
  const id = shownAddon();
  if (snapshot || !id) return;
  const {verb, addonPrompt: target, value = '', promptLabel = 'Edit'} = control.dataset;
  const {d, actions} = dialog(promptLabel, 'dialog');
  const input = h('input', {className:'input', type:'text', maxLength:String(PROMPT_MAX + 50), value, 'aria-label':promptLabel});
  const hint = h('p', {className:'meta', role:'status'}), failed = h('p', {className:'meta', role:'alert', hidden:true});
  const save = button('Save', 'primary', async () => {
    const text = input.value.trim();
    if (save.disabled || !text || text.length > PROMPT_MAX) return;
    save.disabled = true; failed.hidden = true;
    const label = save.textContent; save.textContent = 'Saving…';
    let result;
    try { result = await act('addon.act', {addon:id, verb, target, value:text}); }
    catch (err) { result = {ok:false, text:'That did not work. Try again.'}; }
    save.textContent = label;
    if (!result.ok) { failed.textContent = result.text || 'That did not work. Try again.'; failed.hidden = false; refresh(); return; }
    await window.orch.close(d);
    window.orch.toast('Saved.', 'ok');
    await loadAddon(id);
  });
  const refresh = () => {
    const n = input.value.trim().length;
    save.disabled = n === 0 || n > PROMPT_MAX;
    hint.textContent = n === 0 ? 'Write at least one character.' : n > PROMPT_MAX ? 'Too long: at most ' + PROMPT_MAX + ' characters (now ' + n + ').' : '';
    hint.hidden = !hint.textContent;
  };
  input.addEventListener('input', () => { failed.hidden = true; refresh(); });
  input.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); save.click(); } });
  d.append(h('div', {className:'form-fields'}, h('label', {className:'field'}, input), hint, failed), actions);
  actions.append(save);
  refresh();
  window.orch.open(d);
  input.focus();
}
let sharedLinks = null, sharedLinksDown = false;
async function loadSharedLinks() {
  try {
    const res = await fetch('/api/links', {cache:'no-store'});
    if (res.status !== 200) { sharedLinks = null; sharedLinksDown = false; return; }
    const data = await res.json();
    sharedLinks = Array.isArray(data.links) ? data.links : null;
    sharedLinksDown = data.unreachable === true;
  } catch (_) { sharedLinks = null; sharedLinksDown = false; }
}
const SHARE_MAX = 3 * 1024 * 1024;  // the same limit as the server (actions.share_file)
// "Share a file": pick a file here (or start from a ticket file: `start` = {name, url}); the dashboard hands it to the
// sharing server (encrypted on this computer). The dialog stays open on success and shows the new link, copied once.
// The link is rebuilt from the list row (it holds the key), never sent back by the server in the answer.
function shareDialog(start = null) {
  if (snapshot) return;
  const {d, actions} = dialog('Share a file', 'dialog share-dialog');
  const picker = start ? null : h('input', {type:'file', className:'input', id:'share-file', 'aria-label':'File'});
  const note = h('p', {className:'meta', role:'status'});
  const result = h('div', {className:'stack', hidden:true});
  const create = button('Create link', 'primary', async () => {
    if (create.disabled) return;
    let file = picker ? picker.files[0] : null;
    if (!start && !file) { note.textContent = 'Choose a file first.'; return; }
    create.disabled = true; note.textContent = 'Uploading…';
    if (start) {
      try { const res = await fetch(start.url, {cache:'no-store'}); if (!res.ok) throw new Error('read'); file = new File([await res.blob()], start.name); }
      catch (_) { note.textContent = 'That file could not be read.'; create.disabled = false; return; }
    }
    if (file.size > SHARE_MAX) { note.textContent = 'That file is over 3 MB.'; create.disabled = false; return; }
    let data = '';
    try {
      const bytes = new Uint8Array(await file.arrayBuffer());
      for (let i = 0; i < bytes.length; i += 32768) data += String.fromCharCode(...bytes.subarray(i, i + 32768));
    } catch (_) { note.textContent = 'That file could not be read.'; create.disabled = false; return; }
    const before = new Set((sharedLinks || []).map(l => String(l.id)));
    const out = await act('link.share', {name:file.name, data:btoa(data), days:7});
    create.disabled = false;
    if (!out.ok) { note.textContent = out.text || 'That did not work.'; return; }
    await loadSharedLinks();
    if (shownAddon()) await loadAddon(shownAddon());
    const row = (sharedLinks || []).filter(l => !before.has(String(l.id)) && l.link)[0];
    if (!row) { window.orch.toast('Link created. Copy it from the list.', 'ok'); await window.orch.close(d); return; }
    const copied = await window.UI.copyText(row.link);
    const box = h('input', {className:'input', type:'text', readOnly:true, value:row.link, 'aria-label':'Link'});
    box.addEventListener('focusin', () => box.select());
    const again = button('Copy', 'outline sm', async () => { if (await window.UI.copyText(row.link)) { note.textContent = 'Copied'; } else { box.focus(); box.select(); note.textContent = 'Press Ctrl+C (Cmd+C on a Mac) to copy.'; } });
    result.replaceChildren(h('p', {className:'muted'}, 'Your link is ready. It works for 7 days.'), h('div', {className:'row'}, box, again));
    result.hidden = false;
    if (picker) picker.closest('label').hidden = true;
    intro.hidden = true; create.hidden = true;
    note.textContent = copied ? 'Copied' : 'Press Ctrl+C (Cmd+C on a Mac) to copy.';
    if (!copied) { box.focus(); box.select(); }
  });
  actions.append(create);
  const intro = h('p', {className:'muted'}, start ? 'Share ' + start.name + ' by private link. It works for 7 days; you can extend it or stop sharing any time.' : 'Choose a file to share by private link. It works for 7 days; you can extend it or stop sharing any time.');
  d.append(intro, ...(picker ? [h('label', {className:'field'}, 'File', picker)] : []), result, note, actions);
  window.orch.open(d);
}
async function sharedLinkAction(control) {
  if (snapshot || control.disabled) return;
  if (control.dataset.native === 'link-share') { shareDialog(); return; }
  const link = sharedLinks?.find(link => String(link.id) === control.dataset.linkId);
  if (!link) return;
  if (control.dataset.native === 'link-copy') {
    if (!link.copy) return;
    if (await window.UI.copyText(link.link)) window.orch.toast('Link copied.', 'ok'); else window.UI.showLink(link.link);
    return;
  }
  if (control.dataset.native === 'link-open') {
    if (!link.link) return;
    window.open(link.link, '_blank', 'noopener,noreferrer');
    return;
  }
  const stop = control.dataset.native === 'link-stop';
  const send = async () => {
    control.disabled = true;
    const result = stop ? await act('link.stop', {id:link.id}) : await act('link.extend', {id:link.id, days:7});
    window.orch.toast(result.ok ? (stop ? 'Sharing stopped.' : 'Link extended.') : result.text || 'That did not work.', result.ok ? 'ok' : 'error');
    await loadSharedLinks();
    await loadAddon(shownAddon());
    control.disabled = false;
  };
  if (stop) settingsConfirm('Stop sharing ' + link.name + '?', 'The link stops working.', '', 'Stop sharing', send);
  else await send();
}
// Rebind after reconciliation: retained DOM nodes must use the current link data.
function bindAddonControls(host) {
  const down = isPublish(shownAddon()) && addonViews[shownAddon()]?.view?.notice_tone === 'warn';   // sharing can't be reached: share, extend and stop sharing wait
  host.querySelectorAll('[data-native]').forEach(control => {
    if (down && ['link-share', 'link-extend', 'link-stop'].includes(control.dataset.native)) control.disabled = true;
    if (control.dataset.native === 'link-text') { control.oninput = () => { linkUi.text = control.value; }; return; }
    control.onclick = () => control.dataset.native === 'repeat' ? repeatsDialog() : control.dataset.native === 'link-connect' ? linkConnect(shownAddon()) : sharedLinkAction(control);
  });
}

