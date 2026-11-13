'use strict';
// Settings, add-on pages and add-on actions.
let settingsTab = 'general', settingsAddon = null;
const settingsBusy = new Set();
// A long path keeps its start and its end: "/Users/me/…/team/pilatus". The full path is in the row's title.
const middleShort = (value, max = 48) => {
  const text = String(value ?? '');
  if (text.length <= max) return text;
  const tail = Math.ceil((max - 1) / 2), head = max - 1 - tail;
  return text.slice(0, head) + '…' + text.slice(-tail);
};
// The add-on's name as the sidebar shows it (its manifest label), from the live add-on list.
const rowLabel = a => addonLabel(addons().find(x => x.name === a.name) || a);
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
  if (ws.length) rows.push(row('Can talk to', ws.map(w => h('span', {className:w.online ? 'on-dot' : 'off-dot', title:w.online ? 'online' : 'offline'}, settingsText('span', {}, w.name)))));
  return h('dl', {}, rows);
}
const FULL_WARNING = 'Full: a helper can change or delete anything in this folder and run any command without asking.';
const PERMISSION_CHOICES = [['ask', 'Ask', 'A helper asks before it changes anything.'], ['auto', 'Auto', 'A helper works on its own and asks only for risky things.'], ['full', 'Full', 'A helper never asks. It changes things without asking. Only use this if you trust it.']];
function permissionsCard(settings) {
  const current = PERMISSION_CHOICES.some(([value]) => value === settings.permissions) ? settings.permissions : 'auto';
  const rows = PERMISSION_CHOICES.map(([value, label, hint]) => {
    const radio = h('input', {type:'radio', name:'settings-permissions', value, 'data-key':'settings-permissions-' + value, 'data-settings-permissions':value, disabled:snapshot || settingsBusy.has('permissions')});
    radio.checked = value === current;
    return h('label', {className:'card-row agent-opt' + (value === current ? ' sel' : ''), 'data-key':'settings-permissions-row-' + value}, radio,
      h('div', {className:'grow'}, settingsText('h3', {}, label), settingsText('p', {className:'meta'}, hint)));
  });
  return h('div', {className:'stack', 'data-key':'settings-permissions'}, h('h2', {className:'set-sub'}, 'What a helper may do'),
    h('div', {className:'card'}, h('div', {className:'permission-choices', role:'radiogroup', 'aria-label':'What a helper may do'}, rows),
      current === 'full' ? h('p', {className:'card-row bad', role:'note'}, FULL_WARNING) : null));
}
// Share with team: off by default; on writes one short entry into the team's AGENTS.md (the orch files stay local).
function shareCard(settings) {
  const on = settings.share === true;
  return h('div', {className:'stack', 'data-key':'settings-share'},
    h('div', {className:'card'}, h('div', {className:'card-row'},
      h('div', {className:'grow'}, settingsText('h3', {}, 'Share with team'),
        settingsText('p', {className:'meta'}, on ? 'AGENTS.md has a short orch entry. Turn off to remove it.' : 'Off: orch files stay on this computer and your team sees nothing.')),
      h('button', {type:'button', className:'switch', role:'switch', 'aria-checked':on, 'aria-label':'Share with team', 'data-key':'settings-switch-share', 'data-action':'settings-share', disabled:snapshot || settingsBusy.has('share')})),
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
function workflowCard(settings) {
  return h('div', {className:'stack', 'data-key':'settings-workflow'},
    h('div', {className:'card'}, h('div', {className:'card-row'},
      h('div', {className:'grow'}, settingsText('h3', {}, 'Helpers may mark tickets Done'),
        settingsText('p', {className:'meta'}, 'On: a helper marks its finished work Done. Off: helpers send finished work to Review and you decide when it is Done.')),
      h('button', {type:'button', className:'switch', role:'switch', 'aria-label':'Helpers may mark tickets Done', 'aria-checked':!!settings.agents_may_finish, 'data-key':'settings-switch-workflow', 'data-action':'workflow-set', disabled:snapshot || settingsBusy.has('workflow')})),
      reviewPanel('workflow', settings)));
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
    ? {verb:'Turn off', what:'Helpers will send finished work to Review, and you decide when it is Done.', affects:'Only new finished work. Tickets that are already Done stay Done.'}
    : {verb:'Turn on', what:'Helpers will mark their finished work Done themselves.', affects:'You will not be asked to look at it first. Tickets already waiting in Review stay there.'};
  if (id === 'copies-switch') return copiesModeOf(settings) !== 'off'
    ? {verb:'Turn off', what:'Helpers will all work in your own folder, also when they work at the same time.', affects:'Copies that already exist stay until their ticket is done. Your own files are not touched.'}
    : {verb:'Turn on', what:'When helpers work at the same time, each one gets its own copy of your files.', affects:'At most ' + (settings.copies_max || 3) + ' copies at the same time. They take space on this computer and are removed when their ticket is done. Your own files are not touched.'};
  const n = settings.copies_disk?.copies;
  return {verb:'Clean up', what:'Copies of your files that no helper needs any more will be removed now.',
    affects:(n === 0 ? 'There are no copies right now, so nothing will be removed.'
      : typeof n === 'number' ? 'Up to ' + n + (n === 1 ? ' copy' : ' copies') + ' will be removed, only the ones no ticket needs any more. Saved changes stay in the version history.'
      : 'Only copies no ticket needs any more are removed. Saved changes stay in the version history.') + ' Your own files are not touched.'};
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
    ? h('div', {className:'copies-setup-edit'}, h('input', {type:'text', className:'input copies-setup', maxLength:500, value:settings.copy_setup || '', placeholder:'For example: install the packages', 'aria-label':'Prepare a copy with', 'data-key':'settings-copy-setup', disabled:busy}),
      h('div', {className:'row'}, h('button', {type:'button', className:'btn sm primary', 'data-key':'settings-copy-setup-save', 'data-action':'copies-setup', disabled:busy}, 'Save'),
        h('button', {type:'button', className:'btn sm ghost', 'data-key':'settings-copy-setup-cancel', 'data-action':'copies-setup-cancel'}, 'Cancel')))
    : h('div', {className:'row copies-setup-view'}, settingsText('p', {className:settings.copy_setup ? 'grow mono' : 'grow meta'}, settings.copy_setup || 'Nothing'),
      snapshot ? null : h('button', {type:'button', className:'btn sm', 'data-key':'settings-copy-setup-edit', 'data-action':'copies-setup-edit'}, 'Edit'));
  const row = (title, hint, ...rest) => h('div', {className:'copies-sub'}, settingsText('h3', {}, title), hint ? settingsText('p', {className:'meta'}, hint) : null, ...rest);
  return h('div', {className:'stack', 'data-key':'settings-copies'},
    h('div', {className:'card'},
      h('div', {className:'card-row'}, h('div', {className:'grow'}, settingsText('h3', {}, 'Helpers working at the same time: each gets its own copy of your files')),
        h('button', {type:'button', className:'switch', role:'switch', 'aria-checked':on, 'aria-label':'Each helper gets its own copy of your files', 'data-key':'settings-switch-copies', 'data-action':'copies-switch', 'data-mode':on ? 'off' : 'together', disabled:off})),
      reviewPanel('copies-switch', settings),
      h('div', {className:'copies-details', 'data-key':'settings-copies-details'},
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
          row('Prepare a copy with', 'Runs once in each new copy, for example to install what the project needs.', setup),
          settingsText('p', {className:'meta'}, 'Needs version history in this folder. When a copy is removed, its saved changes stay in the version history.')))));
}
// Sync (draft sync-card.html, Variant A): Settings › General, below Workspace. Every fact and change goes through
// the sync add-on's own verbs on the ONE generic op: `orch sync act status|check|set|now|use-public -- <target>`.
// The address and the choice come only from the person's clicks here; choices that decide for the person are signed.
const SYNC = 'sync';
const SYNC_WHERE = [['off', 'Off'], ['local', 'On this computer only'], ['remote', 'Also on another computer or server']];
const SYNC_EVERY = [['5', '5 min'], ['15', '15 min'], ['60', '1 hour']];
const SYNC_PUBLIC = 'This sync address is public. Anyone can read your tickets.';
const SYNC_STATUS = {synced:['ok', 'Last synced'], never:['', 'Not synced yet'], offline:['', 'Offline, will sync when connected'], syncing:['live', 'Syncing…'], paused:['you', 'Paused, review below']};
// card = the add-on's last status answer; draft = the person's unsaved choice (the review line shows while it differs)
const syncUi = {card:null, loading:false, draft:null, check:null, note:'', busy:false, nowBusy:false, details:false, wasOff:false, timer:null};
const syncSaved = card => ({where:card?.mode === 'remote' ? 'remote' : card?.mode === 'local' ? 'local' : 'off', addr:card?.mode === 'remote' ? card.remote || '' : '', every:String(card?.interval && card.mode === 'remote' ? card.interval : 15)});
const syncNow = () => syncUi.draft || syncSaved(syncUi.card);
const syncSame = (a, b) => a.where === b.where && (a.where !== 'remote' || (a.addr === b.addr && a.every === b.every));
const syncHost = addr => { const text = String(addr || '').trim(); const scp = /^[^@\s/]+@([^:\s/]+):/.exec(text); if (scp) return scp[1]; try { return new URL(text).host || text; } catch (_) { return text; } };
const syncEveryLabel = every => (SYNC_EVERY.find(([v]) => v === String(every)) || SYNC_EVERY[1])[1];
function syncReviewText(s) {
  if (s.where === 'off') return 'Sync will stop. Your tickets stay on this computer as they are.';
  if (s.where === 'local') return 'Sync will keep a copy on this computer only.';
  if (!s.addr.trim()) return 'Enter a sync address first.';
  return 'Sync will copy tickets to ' + syncHost(s.addr) + ' every ' + syncEveryLabel(s.every) + '.';
}
// One click on the sync add-on's own verb; its answer comes back as state.act_answer.
async function syncAct(verb, target, extra = {}) {
  const result = await act('addon.act', {addon:SYNC, verb, target, ...extra});
  const answer = result.ok && result.state?.act_answer?.addon === SYNC ? result.state.act_answer.answer : null;
  return {...result, answer};
}
async function syncLoad() {
  if (syncUi.loading || snapshot) return;
  clearTimeout(syncUi.timer); syncUi.timer = null;
  if (route().kind !== 'settings') return;  // the page was left: it loads again when Settings opens
  syncUi.loading = true;
  try {
    const result = await syncAct('status', SYNC);
    if (result.answer && typeof result.answer.shown === 'string') {
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
function syncLastError(card) {
  if (!card.last_error) return 'Last error: none';
  const when = time(card.last_try);
  return 'Last error' + (when ? ' ' + when : '') + ': ' + (card.last_error === 'offline' ? 'could not reach the sync address.' : String(card.last_error));
}
function syncCard(settings) {
  const addon = array(settings.addons).find(a => a.name === SYNC);
  if (!addon || snapshot) return null;
  const wrap = body => h('div', {className:'stack sync-wrap', 'data-key':'settings-sync'}, h('div', {className:'card sync-card', id:'sync-card'}, body));
  if (!addon.active) {
    syncUi.wasOff = true; syncUi.card = null; syncUi.draft = null;
    return wrap(h('div', {className:'card-row'}, h('span', {className:'grow sync-lbl'}, 'Keep a copy of my tickets'),
      h('button', {type:'button', className:'switch', role:'switch', 'aria-checked':false, 'aria-label':'Keep a copy of my tickets', 'data-key':'settings-switch-sync-off', 'data-action':'settings-addon', 'data-name':addon.name, disabled:settingsBusy.has('addon-' + addon.name)})));
  }
  const card = syncUi.card;
  if (!syncUi.loading && !syncUi.timer) queueMicrotask(syncLoad);  // then every 15 s while Settings is open
  const cur = syncNow(), saved = syncSaved(card), changed = !!card && !syncSame(cur, saved), off = !card || syncUi.busy;
  const paused = card?.shown === 'paused', blocked = paused || !!card?.public;
  const radios = SYNC_WHERE.map(([value, label]) => {
    const radio = h('input', {type:'radio', name:'sync-where', value, 'data-sync-where':value, 'data-key':'sync-where-' + value, disabled:off});
    radio.checked = cur.where === value;
    radio.addEventListener('change', () => { syncUi.draft = {...syncNow(), where:value}; render(); });
    return h('label', {className:'card-row radio-row', 'data-key':'sync-where-row-' + value}, radio, h('span', {}, label));
  });
  const addr = h('input', {type:'text', className:'input mono', id:'sync-addr', 'data-key':'sync-addr', 'data-settings-field':'sync-addr', value:cur.addr, placeholder:'https://…', spellcheck:'false', autocomplete:'off', disabled:off});
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
  const now = h('button', {type:'button', className:'btn ' + (blocked ? 'ghost' : 'primary'), 'data-key':'sync-now', disabled:off || syncUi.nowBusy}, iconEl('refresh'), 'Sync now');
  now.addEventListener('click', syncNowClick);
  const remoteBox = cur.where === 'remote' ? h('div', {className:'sync-sub', 'data-key':'sync-remote'},
    h('div', {className:'sync-field'}, h('label', {className:'meta', for:'sync-addr'}, 'Sync address'), h('div', {className:'sync-field-line'}, addr, check), res),
    h('div', {className:'sync-every'}, h('span', {className:'meta', id:'sync-every-lbl'}, 'Sync every'), h('div', {className:'sync-chips', role:'group', 'aria-labelledby':'sync-every-lbl'}, chips)),
    h('div', {className:'sync-act'}, now, syncUi.note ? h('span', {className:'sync-note', role:'status', 'data-key':'sync-note'}, syncUi.note) : null)) : null;
  const review = changed ? h('div', {className:'sync-review', role:'group', 'aria-label':'Review before saving', 'data-key':'sync-review'},
    h('p', {'data-key':'sync-review-text'}, syncReviewText(cur)),
    h('div', {className:'row'}, button('Undo', 'quiet', () => { syncUi.draft = null; syncUi.check = null; render(); }), (() => {
      const save = button('Save', 'primary', syncSave);
      save.dataset.key = 'sync-review-save';
      save.disabled = syncUi.busy || (cur.where === 'remote' && !cur.addr.trim());
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
  const details = card && card.mode !== 'off' ? h('div', {className:'sync-details', id:'sync-details', 'data-key':'sync-details'},
    h('ul', {}, h('li', {'data-key':'sync-last-error'}, syncLastError(card)), notSynced.map((f, i) => h('li', {'data-key':'sync-not-synced-' + i}, 'Not synced: ' + f.name + (f.why ? ' (' + f.why + ')' : ''))))) : null;
  return wrap([
    h('div', {className:'sync-head'}, h('h3', {}, 'Sync'), card && card.mode !== 'off' ? syncStatusLine(card) : null),
    warn,
    h('fieldset', {className:'sync-where'}, h('legend', {className:'meta'}, 'Where to keep a copy'), radios),
    remoteBox, review, details]);
}
async function syncSave() {
  const s = syncNow();
  if (syncUi.busy || (s.where === 'remote' && !s.addr.trim())) return;
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
    window.orch.toast(asked.text || 'This can’t be signed right now. Nothing was changed.', 'error');
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
// value), both versions when there are two, "You sign this as <name>", then Sign. No typed word.
function signStep({title, body, here, there, value, done, run}) {
  const {d, actions} = dialog(String(title || ''), 'dialog sign-step');
  const sides = here || there ? h('ul', {className:'sign-sides'}, h('li', {}, h('b', {}, 'Here:'), ' ', String(here || '')), h('li', {}, h('b', {}, 'Other computer:'), ' ', String(there || ''))) : null;
  const shown = value ? settingsText('p', {className:'mono sign-value', 'data-key':'sign-value'}, String(value)) : null;
  const who = name(state?.who) || 'you';
  const sign = h('button', {type:'button', className:'btn primary', 'data-key':'sign-ok'}, iconEl('shield'), 'Sign');
  let pending = false;
  d.addEventListener('cancel', event => { if (pending) event.preventDefault(); });
  sign.addEventListener('click', async () => {
    if (pending) return;
    pending = true;
    actions.querySelectorAll('button').forEach(b => { b.disabled = true; });
    const result = await run();
    await window.orch.close(d);
    window.orch.toast(result?.ok ? 'Signed. ' + (done || '') : result?.text || 'That did not work.', result?.ok ? 'ok' : 'error');
  });
  actions.append(sign);
  d.append(...[shown, sides, body ? settingsText('p', {className:'meta'}, body) : null, settingsText('p', {className:'meta'}, 'You sign this as ' + who + '.'), actions].filter(Boolean));
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
    phoneAddon ? row('Phone questions', state.mobile_mode ? (state.mobile_mode.on ? 'On' : 'Off') + ' · switch off after ' + state.mobile_mode.default_hours + ' h' : 'Pair a phone and choose which workspaces may reach this one.', go('phone', 'Change', 'settings-everyday-phone'), 'settings-everyday-phone-row') : null));
}
// Phone & workspaces (drafts settings-phone / settings-phone-pair): 1. the relay connection, 2. pairing + delivery,
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
  const relay = h('div', {className:'stack', 'data-key':'phone-relay'}, h('h2', {className:'set-sub'}, '1. Relay connection'), h('div', {className:'card'},
    rowOf('Status', [connected ? h('strong', {className:'on-dot', 'data-key':'phone-relay-status'}, 'Connected') : h('strong', {className:'muted', 'data-key':'phone-relay-status'}, 'Not set up'),
      settingsText('p', {className:'meta', 'data-key':'phone-relay-address'}, connected && address ? address : 'No relay connected')],
      h('div', {className:'row'}, connected ? btn('Reconnect', 'outline', 'relay-reconnect') : null, btn('Set up relay', connected ? 'ghost' : 'primary', 'relay-setup')), 'phone-relay-row'),
    settingsText('p', {className:'card-row meta'}, 'Your phone talks to this workspace through your relay.')));
  const pair = h('div', {className:'stack', 'data-key':'phone-pair'}, h('h2', {className:'set-sub'}, '2. Pair a phone'), h('div', {className:'card'},
    rowOf('Pairing', [settingsText('p', {}, 'Link a phone to this workspace'), connected ? null : settingsText('p', {className:'meta', 'data-key':'phone-relay-hint'}, 'Connect to your relay first')],
      btn('Pair a phone', 'primary', 'phone-pair', connected ? {} : {disabled:true}), 'phone-pairing-row'),
    mm));
  const allowed = h('div', {className:'stack', 'data-key':'phone-allowed'}, h('div', {className:'row between'}, h('h2', {className:'set-sub'}, 'Allowed workspaces'),
    settingsText('span', {className:'meta'}, (connected ? workspaces.length : 0) + ' allowed')),
    connected && workspaces.length ? h('div', {className:'card'}, workspaces.map(w => h('div', {className:'card-row', 'data-key':'phone-ws-' + w.name}, h('span', {className:w.online ? 'on-dot' : 'off-dot', title:w.online ? 'online' : 'offline'}, settingsText('span', {}, w.name)))))
      : h('div', {className:'card pad empty-note', 'data-key':'phone-allowed-empty'}, settingsText('h3', {}, 'No other workspaces yet'), settingsText('p', {className:'meta'}, 'Allow a workspace to send it messages and files.')));
  return h('div', {className:'stack', 'data-key':'settings-phone'}, relay, pair, allowed,
    h('div', {className:'row between'}, settingsText('p', {className:'meta'}, 'Messages have their own page.'), h('a', {className:'btn ghost sm', href:'#addon/' + encodeURIComponent(phoneAddon.name), 'data-key':'phone-open-messages'}, 'Open messages →')));
}
// The pairing dialog stays inside Settings. A pairing code comes from the relay and this page has no way to ask
// for one yet, so it shows no code (never a made-up QR), only the relay the phone would go through.
function phonePairDialog() {
  const phoneAddon = addons().find(a => a.dashboard?.panel === 'phone');
  const info = phoneAddon ? relayInfo(phoneAddon) : null;
  if (!info?.connected) return;
  const {d, actions} = dialog('Pair a phone', 'dialog', 'settings-other');
  actions.firstChild.textContent = 'Close';
  d.append(settingsText('p', {className:'meta', 'data-key':'phone-pair-relay'}, 'Through your relay: ' + (info.address || 'your relay')),
    settingsText('p', {className:'meta'}, 'A phone is paired with a one-time code from your relay. This page cannot create that code yet, so no code is shown.'),
    settingsText('p', {className:'meta'}, 'Your phone talks to this workspace through your relay.'), actions);
  window.orch.open(d);
}
function relaySetupDialog() {
  const {d, actions} = dialog('Set up relay', 'dialog', 'settings-other');
  actions.firstChild.textContent = 'Close';
  d.append(settingsText('p', {className:'meta'}, 'Connecting a relay needs its address, a setup code from its administrator and your signature. This page cannot do that yet.'),
    settingsText('p', {className:'meta'}, 'Once a relay is connected, its address and status show here.'), actions);
  window.orch.open(d);
}
async function relayReconnect(control) {
  if (control.disabled) return;
  control.disabled = true;
  await refresh();
  const phoneAddon = addons().find(a => a.dashboard?.panel === 'phone');
  const ok = phoneAddon && relayInfo(phoneAddon).connected;
  window.orch.toast(ok ? 'Checked. Your relay is connected.' : 'Your relay is not connected.', ok ? 'ok' : 'error');
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
      h('button', {type:'button', className:'switch', role:'switch', 'aria-checked':!!addon.active, 'aria-label':label + ' on or off', 'data-key':'settings-switch-' + addon.name, 'data-action':'settings-addon', 'data-name':addon.name, disabled:snapshot || settingsBusy.has('addon-' + addon.name)}, addon.active ? 'On' : 'Off'), 'addon-detail-switch'),
    addon.active && d ? row('Connection', connected ? h('span', {className:'on-dot', 'data-key':'addon-detail-status'}, 'Connected') : h('span', {className:'off-dot', 'data-key':'addon-detail-status'}, 'Not connected yet'), null, 'addon-detail-connection') : null,
    links && shown !== null ? row('Shared pages', settingsText('p', {}, 'Show workspace name and icon'),
      h('button', {type:'button', className:'switch', role:'switch', 'aria-checked':shown, 'aria-label':'Show workspace name and icon on shared pages', 'data-action':'addon-shared', 'data-on':String(!shown), 'data-key':'addon-detail-shared', disabled:snapshot || settingsBusy.has('shared')}, shown ? 'On' : 'Off'), 'addon-detail-shared-row') : null,
  ];
  const where = live && (live.dashboard || live.page)
    ? h('div', {className:'card'}, row('Open', settingsText('p', {}, 'See what ' + label + ' holds.'), h('a', {className:'btn ghost sm', href:'#addon/' + encodeURIComponent(addon.name), 'data-key':'addon-detail-open'}, 'Open ' + label + ' →'), 'addon-detail-open-row')) : null;
  return fragment(h('div', {className:'settings stack', 'data-key':'settings-addon-detail'},
    heading(label, 'Add-on settings', {actions:h('a', {className:'btn ghost sm', href:'#settings/addons', 'data-key':'addon-detail-back'}, '← Installed add-ons')}),
    h('div', {className:'card'}, settingsRows),
    where,
    h('section', {className:'addon-about', 'data-key':'addon-about'}, h('h3', {}, 'About this add-on'),
      settingsText('p', {className:'meta'}, connected && d.address ? 'Connection address: ' + d.address : addon.description || 'No connection address.'))));
}
function settingsPage() {
  const settings = state.settings;
  const phoneAddon = addons().find(a => a.dashboard?.panel === 'phone');
  if (settingsTab === 'phone' && !phoneAddon) settingsTab = 'general';
  const agents = array(settings.agents).map(agent => {
    const radio = h('input', {type:'radio', 'aria-label':agent.label, name:'settings-agent', value:agent.name, 'data-key':'settings-agent-' + agent.name, 'data-settings-agent':agent.name, disabled:settingsBusy.has('agent') || (!agent.found && agent.status !== 'your command')});
    radio.checked = !!agent.chosen;
    const missing = !agent.found && agent.status !== 'your command';
    const status = agent.status === 'your command' ? 'Your own helper' : agent.found ? 'Found' + (agent.version ? ' · version ' + agent.version : '') : 'Not found on this computer. Install it, then it shows up here.';
    return h('div', {className:'card card-row agent-opt agent-card' + (missing ? ' off' : '') + (agent.chosen ? ' sel' : ''), 'data-key':'settings-agent-row-' + agent.name}, radio,
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
      h('div', {className:'grow'}, settingsText('h3', {}, rowLabel(addon)), settingsText('p', {className:'meta'}, addon.description), status, about),
      h('a', {className:'btn ghost sm', href:'#settings/addons/' + encodeURIComponent(addon.name), 'data-key':'settings-addon-open-' + addon.name, 'aria-label':rowLabel(addon) + ' settings'}, 'Settings →'),
      h('button', {type:'button', className:'switch', role:'switch', 'aria-checked':!!addon.active, 'aria-label':rowLabel(addon) + ' on or off', 'data-key':'settings-switch-' + addon.name, 'data-action':'settings-addon', 'data-name':addon.name, disabled:snapshot || settingsBusy.has('addon-' + addon.name)}, addon.active ? 'On' : 'Off'));
  };
  const optional = array(settings.addons).filter(a => a.name !== 'dashboard');
  const addonsPanel = h('div', {className:'stack', 'data-key':'settings-addon-list'},
    h('div', {className:'row between ad-head'}, h('h2', {className:'set-sub'}, 'Installed add-ons'),
      snapshot ? null : h('button', {type:'button', className:'btn primary sm', 'data-action':'addon-catalog', 'data-key':'settings-addon-catalog'}, 'Add an add-on')),
    optional.length ? h('div', {className:'card'}, optional.map(addonRow))
      : h('div', {className:'card pad empty-note', 'data-key':'settings-addons-empty'}, settingsText('h3', {}, 'No optional add-ons installed'), settingsText('p', {className:'meta'}, 'Add tools for schedules, shared links and more.')),
    settingsText('p', {className:'meta', 'data-key':'settings-addon-foot'}, 'The dashboard is always on. Turn an add-on off without removing its settings.'));
  const detailAddon = settingsTab === 'addons' && settingsAddon ? array(settings.addons).find(a => a.name === settingsAddon && a.name !== 'dashboard') : null;
  if (detailAddon) return addonDetailPage(detailAddon);
  return fragment(h('div', {className:'settings stack', 'data-key':'settings-root'}, heading('Settings', 'Make ' + clean(state.workspace || 'this workspace') + ' work your way.'),
    h('div', {className:'settings-layout'}, h('nav', {className:'tabs settings-nav', role:'tablist', 'aria-label':'Settings'}, [['general', 'General'], ['agent', 'Helper'], ...(phoneAddon ? [['phone', phoneAddon.dashboard.label]] : []), ['addons', 'Add-ons']].map(([id, label]) => h('button', {type:'button', id:'settings-tab-' + id, role:'tab', 'aria-selected':settingsTab === id, 'aria-controls':'settings-panel-' + id, tabindex:settingsTab === id ? '0' : '-1', 'data-action':'settings-tab', 'data-tab':id}, label))), h('div', {className:'settings-content'},
    panel('general', [privateCard(settings), h('div', {className:'stack', 'data-key':'settings-workspace'}, h('h2', {className:'set-sub'}, 'Workspace'), h('div', {className:'card'},
      h('div', {className:'card-row name-row'}, h('span', {className:'set-label'}, 'Name'), settingsText('p', {className:'grow set-ctl'}, state.workspace)),
      // Folder: its name plainly, Copy path, and the full path as quiet text beside it (no Details toggle).
      h('div', {className:'card-row name-row folder-row'}, h('span', {className:'set-label'}, 'Folder'), h('div', {className:'grow set-ctl'},
        settingsText('strong', {'data-key':'settings-folder-name'}, folderName(settings.folder) || state.workspace),
        settingsText('p', {className:'mono meta folder-path', title:String(settings.folder || ''), 'data-key':'settings-folder'}, middleShort(settings.folder))),
        snapshot || !settings.folder ? null : settingsText('button', {type:'button', className:'btn outline sm', 'data-copy':String(settings.folder), 'data-key':'settings-copy-path'}, 'Copy path')))),
      snapshot ? null : window.OrchLook?.settingsSection(),
      syncCard(settings),
      everydayCard(settings, phoneAddon),
      h('div', {className:'stack', 'data-key':'settings-sharing'}, h('h2', {className:'set-sub'}, 'Sharing and finished work'), shareCard(settings), workflowCard(settings), copiesCard(settings))]),
    panel('agent', [h('p', {className:'meta'}, 'Pick the helper tool to use. It is saved right away.'), h('div', {className:'stack'}, h('div', {className:'agent-cards', role:'radiogroup', 'aria-label':'Helper tool'}, agents),
      snapshot ? null : h('div', {className:'agent-foot', 'data-key':'settings-add-slot'}, h('button', {type:'button', className:'btn ghost sm', 'data-key':'settings-add-agent', 'data-action':'agent-add'}, '+ Add your own helper'))),
      permissionsCard(settings)]),
    phoneAddon ? panel('phone', phonePanel(phoneAddon, settings)) : null,
    panel('addons', addonsPanel)))
  ));
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
// The catalogue is not connected yet: say so plainly and list what is installed (nothing invented).
function addonCatalog() {
  const {d, actions} = dialog('Add an add-on', 'dialog', 'settings-other');
  const names = array(state.settings?.addons).filter(a => a.name !== 'dashboard').map(rowLabel);
  d.append(settingsText('p', {className:'meta'}, names.length ? names.join(', ') + ' are already installed.' : 'No add-ons are installed yet.'),
    settingsText('p', {className:'meta'}, 'The add-on catalogue is not connected yet. Available add-ons will appear here.'), actions);
  window.orch.open(d);
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
  const [lead, ...rest] = String(text).split('\n');
  if (rest.length && cls === 'preserve-lines') {
    d.append(settingsText('p', {}, lead), settingsText('pre', {className:cls + ' consent-details'}, rest.join('\n')), actions);
  } else d.append(settingsText('pre', {className:cls}, text), actions);
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
function pageFrame(r) {
  const src = '/addon/' + r.id + '/' + r.path;
  const frame = h('iframe', {className:'embed', 'data-key':'embed', src, title:addonLabel(addons().find(a => a.name === r.id)), allow:'fullscreen', allowfullscreen:''});
  // an add-on that orch did not ship gets an opaque origin: it cannot use the dashboard's session
  if (!addons().find(a => a.name === r.id)?.shipped) frame.setAttribute('sandbox', 'allow-scripts');
  return fragment(frame);
}
const addonHost = id => h('div', {id:'addon-body', className:'stack', 'data-name':id});
const addonTitle = a => a?.dashboard?.title || addonLabel(a);
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
  if (op === 'link.share') out.push(h('button', {type:'button', className:'btn primary sm', 'data-native':'link-share'}, clean(header.button.label)));
  else if (op === 'addon.refresh') out.push(h('button', {type:'button', className:'btn outline sm', 'data-action':'retry-addon'}, clean(header.button.label)));
  return out;
}
function addonTab(id) {
  // The add-on that repeats tickets is the Schedules page: its main button sits in the heading.
  const a = addons().find(a => a.name === id), slot = h('div', {id:'addon-header', className:'row'}, addonHeaderNodes(id));
  if (panelOf(id) === 'repeats') {
    const add = snapshot ? null : h('button', {type:'button', className:'btn primary', 'data-native':'repeat'}, '+ New schedule');
    if (add) add.onclick = () => repeatsDialog(null, id);
    return fragment(heading('Schedules', 'Repeat work on a plan you choose.', {actions:h('div', {className:'row'}, slot, add)}), addonHost(id));
  }
  return fragment(heading(addonTitle(a), a?.dashboard?.subtitle || '', {actions:slot}), addonHost(id));
}
// The add-on whose blocks view is on screen: its own tab.
function shownAddon() {
  const r = route();
  return r.kind === 'addon' ? r.id : null;
}
// Choosing a Settings tab stays on Settings: the address becomes #settings/<tab> without a navigation.
function settingsGo(tab) {
  settingsTab = tab;
  settingsAddon = null;
  settingsReview = null;
  history.replaceState(null, '', '#settings/' + tab);
  render();
}
function addonBody(a, res) {
  if (!res) return fragment(skeletonFor('section'));
  const retry = snapshot ? null : h('button', {type:'button', className:'btn outline sm', 'data-action':'retry-addon'}, 'Try again');
  if (res.state === 'error' || !res.view) return fragment(h('section', {className:'card pad stack'}, h('h2', {}, 'Can’t show ', addonLabel(a), ' right now.'), h('p', {}, res.message || 'No answer.', ' Nothing here was changed.'), retry));
  return fragment(res.state === 'stale' ? h('p', {className:'meta'}, 'As of ', time(res.as_of)) : null,
    res.state === 'stale' ? h('div', {className:'banner attn', role:'status'}, h('p', {className:'grow'}, 'Not up to date. Showing the last answer from ', time(res.as_of), '.', res.message ? ' ' + clean(res.message) + ' Newer items may be missing.' : ''), retry) : null,
    addonNotice(res.view), h('div', {id:'addon-blocks'}));
}
function addonNotice(view) {
  if (!view.notice) return null;
  const tone = 'banner ' + (view.notice_tone === 'bad' ? 'error' : ['warn', 'needs-you'].includes(view.notice_tone) ? 'attn' : '');
  const b = view.button;
  // "Running. Next run in 2 days." -> a small state badge and the rest of the line
  const split = view.notice_tone === 'good' && /^([^.]{1,24})\. (.+)$/.exec(String(view.notice));
  if (split) return h('p', {className:'status-line'}, h('span', {className:'badge done'}, '● ' + clean(split[1])), h('span', {}, clean(split[2])));
  const op = b?.action?.op;
  if (snapshot || (op !== 'addon.start' && op !== 'addon.refresh')) return h('p', {className:tone}, clean(view.notice));
  return h('div', {className:tone}, h('p', {className:'grow'}, clean(view.notice)), h('button', {type:'button', className:'btn outline sm', 'data-action':op === 'addon.start' ? 'start' : 'retry-addon'}, clean(b.label)));
}
function paintAddon(id) {
  const host = document.getElementById('addon-body'), a = addons().find(a => a.name === id);
  if (!host || host.dataset.name !== id || !a) return;
  const scroll = [window.scrollX, window.scrollY];
  const template = addonBody(a, addonViews[id]);
  const blocks = template.querySelector('#addon-blocks');
  if (blocks) {
    blocks.append(OrchBlocks.render(addonViews[id].view.blocks, {addonUrl, self:id, inApp:name => addons().some(a => a.name === name && a.page) ? path => pageHash(name, path) : null}));
    if (!blocks.childNodes.length) blocks.append(h('section', {className:'card pad muted'}, 'Nothing to show yet.'));
    blocks.querySelectorAll('.blk:not(.blk-above)').forEach(n => n.classList.add('card'));
    blocks.querySelectorAll('svg').forEach(n => {
      n.replaceWith(iconEl('external'));
    });
    // Block text is supplied by add-ons; keep internal keys out of visible copy.
    const walker = document.createTreeWalker(blocks, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) walker.currentNode.data = clean(walker.currentNode.data);
  }
  reconcile(host, template);
  const slot = document.getElementById('addon-header');
  if (slot) { slot.replaceChildren(...addonHeaderNodes(id)); bindAddonControls(slot); }
  bindAddonControls(host);
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
  if (panelOf(id) === 'links' && !snapshot) await loadSharedLinks();
  if (shownAddon() === id) paintAddon(id);
}
function startAddon(id) {
  clearInterval(addonTimer);
  activeAddon = id;
  paintAddon(id);
  loadAddon(id);
  if (!snapshot) addonTimer = setInterval(() => loadAddon(id), 15000);
}

// An add-on row's switch or button: the DOM only carries verb + ticket (blocks.js checked them); the page adds
// the add-on of the open tab, so a view can never address another add-on.
async function addonAct(control) {
  const id = shownAddon();
  if (!id || control.disabled || locks.has('addon-act')) return;
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
// Workspace messages are composed in their persistent Chat thread.
function messageSend(control) {
  if (snapshot) return;
  const peer = control.dataset.sendTo;
  if (/^ws_[a-z0-9]{10}$/.test(peer)) location.hash = '#chat/' + peer;
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
  const [hh, mm] = String(c.time || '').split(':').map(Number);
  if (!Number.isInteger(hh) || !Number.isInteger(mm) || hh < 0 || hh > 23 || mm < 0 || mm > 59) return {phrase:null, summary:'Choose a time.', hint:''};
  const at = String(hh).padStart(2, '0') + ':' + String(mm).padStart(2, '0');
  if (c.freq === 'daily') return {phrase:'daily ' + at, summary:'Runs every day at ' + at, hint:''};
  if (c.freq === 'weekly') {
    const picked = REPEAT_DAYS.filter(d => c.days.includes(d[2]));
    if (!picked.length) return {phrase:null, summary:'Choose at least one day.', hint:''};
    const phrase = picked.length === 1 ? 'every ' + picked[0][1].toLowerCase() + ' ' + at : mm + ' ' + hh + ' * * ' + picked.map(d => d[2]).join(',');
    return {phrase, summary:'Runs every ' + andList(picked.map(d => d[1])) + ' at ' + at, hint:''};
  }
  if (c.freq === 'monthly') {
    const day = Number(c.monthday);
    if (!Number.isInteger(day) || day < 1 || day > 28) return {phrase:null, summary:'Choose a day from 1 to 28.', hint:''};
    return {phrase:'monthly ' + day + ' ' + at, summary:'Runs on day ' + day + ' of every month at ' + at, hint:'Days go up to 28 so every month has them.'};
  }
  const n = Number(c.every);
  if (!Number.isInteger(n) || n < 1 || n > 30) return {phrase:null, summary:'Choose between 1 and 30 days.', hint:''};
  if (n === 1) return {phrase:'daily ' + at, summary:'Runs every day at ' + at, hint:''};
  return {phrase:mm + ' ' + hh + ' */' + n + ' * *', summary:'Runs every ' + n + ' days at ' + at, hint:'Counted from the 1st of each month.'};
}
// The reverse of repeatPlan for the plans it writes: a saved 5-field cron -> the dialog's choices (null when it is some other plan).
function cronToChoice(cron) {
  const f = String(cron || '').trim().split(/\s+/);
  if (f.length !== 5 || !/^\d+$/.test(f[0]) || !/^\d+$/.test(f[1]) || f[3] !== '*') return null;
  const time = String(f[1]).padStart(2, '0') + ':' + String(f[0]).padStart(2, '0'), base = {freq:'weekly', days:[1], monthday:1, every:2, time};
  if (f[2] === '*' && f[4] === '*') return {...base, freq:'daily'};
  if (f[2] === '*' && /^[0-6](,[0-6])*$/.test(f[4])) return {...base, freq:'weekly', days:f[4].split(',').map(Number)};
  if (/^\d+$/.test(f[2]) && f[4] === '*') return {...base, freq:'monthly', monthday:Math.min(28, Number(f[2]))};
  if (/^\*\/\d+$/.test(f[2]) && f[4] === '*') return {...base, freq:'custom', every:Number(f[2].slice(2))};
  return null;
}
const REPEAT_FREQ = [['daily', 'Every day'], ['weekly', 'Every week'], ['monthly', 'Every month'], ['custom', 'Custom']];
// The ticket is chosen in the window, or fixed when it is opened from a ticket's menu (`only`).
function repeatsDialog(only = null, addonName = null) {
  if (snapshot) return;
  const saved = only ? tickets().find(t => t.id === only)?.ext?.[addonName || repeatsAddon()] : null;
  const had = saved?.recurring === true ? cronToChoice(saved.cron) : null;
  const {d, actions} = dialog(had ? 'Edit schedule' : 'New schedule', 'dialog repeat-dialog');
  const ticket = h('select', {className:'input', name:'ticket', id:'repeat-ticket'});
  tickets().filter(t => only ? t.id === only : !['done', 'dropped'].includes(t.status)).forEach(t => ticket.append(new Option(t.title || t.id, t.id)));
  const choice = had || {freq:'weekly', days:[1], monthday:1, every:2, time:'08:00'};
  const summary = h('p', {className:'repeat-summary', role:'status'}), hint = h('span', {className:'meta'});
  const rowsHost = h('div', {className:'schedule-fields'});
  const row = (label, ...kids) => h('div', {className:'schedule-row'}, h('span', {}, label), ...kids);
  const save = button('Save schedule', 'primary', async () => {
    const plan = repeatPlan(choice);
    if (save.disabled || !ticket.value || !plan.phrase) return;
    save.disabled = true;
    const result = await act('addon.act', {addon:addonName || route().id, verb:'repeat', target:ticket.value, value:plan.phrase});
    window.orch.toast(result.ok ? 'Schedule saved.' : result.text || 'That did not work.', result.ok ? 'ok' : 'error');
    save.disabled = false;
    if (result.ok) await window.orch.close(d);
    if (route().kind === 'addon') await loadAddon(route().id);
  });
  const refreshSummary = () => {
    const plan = repeatPlan(choice);
    summary.textContent = plan.summary; hint.textContent = plan.hint;
    hint.hidden = !plan.hint; save.disabled = !plan.phrase || !ticket.options.length;
  };
  const draw = () => {
    const plan = repeatPlan(choice), kids = [];
    if (choice.freq === 'custom') {
      const n = h('input', {className:'input', type:'number', min:'1', max:'30', value:String(choice.every), 'aria-label':'Number of days'});
      n.oninput = () => { choice.every = n.value; refreshSummary(); };
      kids.push(row('Repeat every', h('div', {className:'custom-interval'}, n, h('span', {}, 'days'))));
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
      for (let i = 1; i <= 28; i++) day.append(new Option(String(i), String(i)));
      day.value = String(choice.monthday);
      day.onchange = () => { choice.monthday = Number(day.value); refreshSummary(); };
      kids.push(row('Day of month', h('div', {className:'schedule-value'}, day, plan.hint ? hint : null)));
    }
    const time = h('input', {className:'input', type:'time', value:choice.time, required:'', 'aria-label':'Time'});
    time.oninput = () => { choice.time = time.value; refreshSummary(); };
    kids.push(row('Time', h('div', {className:'schedule-value'}, time, h('span', {className:'meta'}, 'Uses the workspace’s time zone.'))));
    rowsHost.replaceChildren(...kids);
    refreshSummary();
  };
  const freq = h('div', {className:'segmented frequency-control', role:'radiogroup', 'aria-label':'How often'},
    REPEAT_FREQ.map(([value, label]) => {
      const input = h('input', {type:'radio', name:'frequency', value});
      input.checked = value === choice.freq;
      input.onchange = () => { choice.freq = value; draw(); };
      return h('label', {}, input, h('span', {}, label));
    }));
  const fields = h('div', {className:'form-fields'}, h('label', {className:'field'}, 'Ticket', ticket),
    h('fieldset', {className:'repeat-block'}, h('legend', {}, 'How often'), freq, rowsHost, summary));
  if (!ticket.options.length) fields.append(h('p', {className:'meta'}, 'No open tickets yet.'));
  const copy = button('Copy ticket now', 'ghost', async () => {
    if (!ticket.value) return;
    const result = await act('addon.act', {addon:addonName || route().id, verb:'copy', target:ticket.value});
    window.orch.toast(result.ok ? 'Ticket copied.' : result.text || 'That did not work.', result.ok ? 'ok' : 'error');
    if (result.ok) await window.orch.close(d);
    if (route().kind === 'addon') await loadAddon(route().id);
  });
  draw();
  // An existing schedule: Save changes, or remove it (its tickets stay); a new one may also copy the ticket.
  const remove = button('Delete schedule', 'outline danger', async () => {
    if (remove.disabled) return;
    remove.disabled = true;
    const result = await act('addon.act', {addon:addonName || route().id, verb:'delete', target:only});
    window.orch.toast(result.ok ? 'Schedule removed. Its tickets stay.' : result.text || 'That did not work.', result.ok ? 'ok' : 'error');
    remove.disabled = false;
    if (result.ok) await window.orch.close(d);
    if (route().kind === 'addon') await loadAddon(route().id);
  });
  if (had) actions.append(remove, save); else actions.append(copy, save);
  d.append(fields, actions); window.orch.open(d);
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
// "Share a file": pick a file here; the dashboard hands it to the sharing server (encrypted on this computer) and the
// new row shows up in the list. The link, which holds the key, is only ever copied from its row.
function shareDialog() {
  if (snapshot) return;
  const {d, actions} = dialog('Share a file', 'dialog share-dialog');
  const picker = h('input', {type:'file', className:'input', id:'share-file', 'aria-label':'File'});
  const note = h('p', {className:'meta', role:'status'});
  const create = button('Create link', 'primary', async () => {
    const file = picker.files[0];
    if (!file || create.disabled) { note.textContent = 'Choose a file first.'; return; }
    if (file.size > SHARE_MAX) { note.textContent = 'That file is over 3 MB.'; return; }
    create.disabled = true; note.textContent = 'Uploading…';
    let data = '';
    try {
      const bytes = new Uint8Array(await file.arrayBuffer());
      for (let i = 0; i < bytes.length; i += 32768) data += String.fromCharCode(...bytes.subarray(i, i + 32768));
    } catch (_) { note.textContent = 'That file could not be read.'; create.disabled = false; return; }
    const result = await act('link.share', {name:file.name, data:btoa(data), days:7});
    create.disabled = false;
    if (!result.ok) { note.textContent = result.text || 'That did not work.'; return; }
    window.orch.toast('Link created. Copy it from the list.', 'ok');
    await window.orch.close(d);
    await loadSharedLinks();
    if (shownAddon()) await loadAddon(shownAddon());
  });
  actions.append(create);
  d.append(h('p', {className:'muted'}, 'Choose a file to share by private link. It works for 7 days; you can extend it or stop sharing any time.'),
    h('label', {className:'field'}, 'File', picker), note, actions);
  window.orch.open(d);
}
async function sharedLinkAction(control) {
  if (snapshot || control.disabled) return;
  if (control.dataset.native === 'link-share') { shareDialog(); return; }
  const link = sharedLinks?.find(link => String(link.id) === control.dataset.linkId);
  if (!link) return;
  if (control.dataset.native === 'link-copy') {
    if (!link.copy) return;
    try { await navigator.clipboard.writeText(link.link); window.orch.toast('Link copied.', 'ok'); }
    catch (_) { window.orch.toast('Could not copy the link.', 'error'); }
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
  host.querySelectorAll('[data-native]').forEach(control => {
    control.onclick = () => control.dataset.native === 'repeat' ? repeatsDialog() : sharedLinkAction(control);
  });
}

