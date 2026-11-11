'use strict';
// Settings, add-on pages and add-on actions.
let settingsTab = 'general';
const settingsBusy = new Set();
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
  return h('div', {className:'stack', 'data-key':'settings-share'}, h('h2', {className:'set-sub'}, 'Team'),
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
  if (!info || !(info.count > 0 || pending.length)) return null;
  const lines = array(info.lines);
  return h('div', {className:'stack', 'data-key':'settings-private'},
    info.count > 0 ? h('div', {className:'card'}, h('div', {className:'card-row'}, h('div', {className:'grow'},
      settingsText('h3', {}, 'Private files are in your team repo'), settingsText('p', {className:'meta'}, lines[0])),
      snapshot ? null : settingsText('button', {type:'button', className:'btn', 'data-action':'private-move', 'data-key':'settings-private-move', disabled:settingsBusy.has('private')}, 'Move to private'))) : null,
    ...pending.map(p => h('div', {className:'card', 'data-key':'settings-private-pending-' + p.name}, h('div', {className:'card-row'}, h('div', {className:'grow'},
      settingsText('h3', {}, 'This workspace asks to run a command'), p.showable ? settingsText('pre', {className:'meta mono preserve-lines'}, pendingText(p)) : settingsText('p', {className:'meta'}, "This workspace asks to run a command orch can't show safely. Not allowed.")),
      snapshot || !p.showable ? null : settingsText('button', {type:'button', className:'btn', 'data-action':'private-allow', 'data-name':p.name, 'data-key':'settings-private-allow-' + p.name, disabled:settingsBusy.has('private')}, 'Allow on this computer')))));
}
function workflowCard(settings) {
  return h('div', {className:'stack', 'data-key':'settings-workflow'}, h('h2', {className:'set-sub'}, 'Finished work'),
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
  const disk = settings.copies_disk, problems = array(disk?.stuck).length + array(disk?.orphaned).length > 0, off = snapshot || busy;
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
  return h('div', {className:'stack', 'data-key':'settings-copies'}, h('h2', {className:'set-sub'}, 'Copies of your files'),
    h('div', {className:'card'},
      h('div', {className:'card-row'}, h('div', {className:'grow'}, settingsText('h3', {}, 'Helpers working at the same time: each gets its own copy of your files')),
        h('button', {type:'button', className:'switch', role:'switch', 'aria-checked':on, 'aria-label':'Each helper gets its own copy of your files', 'data-key':'settings-switch-copies', 'data-action':'copies-switch', 'data-mode':on ? 'off' : 'together', disabled:off})),
      reviewPanel('copies-switch', settings),
      h('details', {className:'copies-details', 'data-key':'settings-copies-details', open:problems ? '' : null}, h('summary', {}, 'Details'),
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
function settingsPage() {
  const settings = state.settings;
  const phoneAddon = addons().find(a => a.dashboard?.panel === 'phone');
  const agents = array(settings.agents).map(agent => {
    const radio = h('input', {type:'radio', 'aria-label':agent.label, name:'settings-agent', value:agent.name, 'data-key':'settings-agent-' + agent.name, 'data-settings-agent':agent.name, disabled:settingsBusy.has('agent') || (!agent.found && agent.status !== 'your command')});
    radio.checked = !!agent.chosen;
    const missing = !agent.found && agent.status !== 'your command';
    const status = agent.status === 'your command' ? 'Your own helper' : agent.found ? 'Found' + (agent.version ? ' · version ' + agent.version : '') : 'Not found on this computer';
    return h('div', {className:'card card-row agent-opt agent-card' + (missing ? ' off' : '') + (agent.chosen ? ' sel' : ''), 'data-key':'settings-agent-row-' + agent.name}, radio,
      h('div', {className:'grow'}, settingsText('h3', {}, agent.label), settingsText('p', {className:'meta'}, status)),
      agent.chosen ? h('span', {className:'chip active def'}, 'Default') : null);
  }).map(row => row);
  array(settings.agents).forEach((agent, i) => {
    if (snapshot) return;
    const test = h('button', {type:'button', className:'btn ghost sm', 'data-action':'agent-test', 'data-name':agent.name, 'data-key':'settings-test-' + agent.name, disabled:settingsBusy.has('test-' + agent.name)}, 'Test');
    const note = agentTests[agent.name] ? h('p', {role:'status', className:'meta test-note'}, plainTest(agentTests[agent.name].reason)) : null;
    agents[i].append(test);
    if (note) agents[i].append(note);
  });
  const panel = (id, body) => h('section', {className:'set-sec', id:'settings-panel-' + id, 'data-key':'settings-panel-' + id, role:'tabpanel', 'aria-labelledby':'settings-tab-' + id, hidden:settingsTab !== id, tabindex:'0'}, body);
  const addonRow = addon => {
    const more = addon.name !== 'dashboard' && addon.active && addon.detail?.connected, open = addonOpen.has(addon.name);
    return h('div', {className:'card ad-row', 'data-key':'settings-addon-' + addon.name},
      h('div', {className:'ad-h'}, h('div', {className:'grow'}, settingsText('h3', {}, addonLabel(addon)), settingsText('p', {className:'meta'}, addon.description)),
        more ? h('button', {type:'button', className:'ad-more', 'aria-expanded':open, 'data-action':'addon-more', 'data-name':addon.name}, h('span', {className:'chevron'}, iconEl('down')), 'Details') : null,
        addon.name === 'dashboard' ? h('span', {className:'always'}, 'Always on') : h('button', {type:'button', className:'switch', role:'switch', 'aria-checked':!!addon.active, 'aria-label':addonLabel(addon) + ' on or off', 'data-key':'settings-switch-' + addon.name, 'data-action':'settings-addon', 'data-name':addon.name, disabled:snapshot || settingsBusy.has('addon-' + addon.name)}, addon.active ? 'On' : 'Off')),
      more ? h('div', {className:'ad-b', hidden:!open}, addonFacts(addon)) : null);
  };
  return fragment(h('div', {className:'settings stack', 'data-key':'settings-root'}, heading('Settings'),
    h('div', {className:'settings-layout'}, h('nav', {className:'tabs settings-nav', role:'tablist', 'aria-label':'Settings'}, [['general', 'General'], ['agent', 'Helper'], ...(phoneAddon ? [['phone', phoneAddon.dashboard.label]] : []), ['addons', 'Add-ons']].map(([id, label]) => id === 'phone' ? h('a', {href:'#addon/' + phoneAddon.name, 'data-key':'settings-phone'}, label) : h('button', {type:'button', id:'settings-tab-' + id, role:'tab', 'aria-selected':settingsTab === id, 'aria-controls':'settings-panel-' + id, tabindex:settingsTab === id ? '0' : '-1', 'data-action':'settings-tab', 'data-tab':id}, label))), h('div', {className:'settings-content'},
    panel('general', [privateCard(settings), snapshot ? null : window.OrchMobileMode?.settingsSection(h), snapshot ? null : window.OrchLook?.settingsSection(), h('div', {className:'stack', 'data-key':'settings-workspace'}, h('h2', {className:'set-sub'}, 'Workspace'), h('div', {className:'card'},
      h('div', {className:'card-row name-row'}, h('span', {className:'set-label'}, 'Name'), settingsText('p', {className:'grow set-ctl'}, state.workspace)),
      // The folder path is a detail: the row says where in plain words, the path opens under Details.
      h('div', {className:'card-row name-row'}, h('span', {className:'set-label'}, 'Folder'), h('div', {className:'grow set-ctl'}, h('p', {}, 'Stored on this computer'),
        h('details', {className:'folder-details', 'data-key':'settings-folder-details'}, h('summary', {}, 'Details'), settingsText('p', {className:'mono meta'}, settings.folder)))))),
      shareCard(settings), workflowCard(settings), copiesCard(settings)]),
    panel('agent', [h('p', {className:'meta'}, 'Pick the helper tool to use. It is saved right away.'), h('div', {className:'stack'}, h('div', {className:'agent-cards', role:'radiogroup', 'aria-label':'Helper tool'}, agents),
      snapshot ? null : h('div', {className:'agent-foot', 'data-key':'settings-add-slot'}, h('button', {type:'button', className:'btn ghost sm', 'data-key':'settings-add-agent', 'data-action':'agent-add'}, '+ Add your own helper'))),
      permissionsCard(settings)]),
    panel('addons', h('div', {className:'settings-addon-grid'}, array(settings.addons).map(addonRow)))))
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
    d.append(settingsText('p', {}, lead), h('details', {className:'consent-details'}, h('summary', {}, 'Details'), settingsText('pre', {className:cls}, rest.join('\n'))), actions);
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
function addonTab(id) {
  return fragment(heading(addonLabel(addons().find(a => a.name === id))), h('div', {id:'addon-body', className:'stack', 'data-name':id}));
}
function addonBody(a, res) {
  if (!res) return fragment(h('div', {className:'skeleton addon-loading', role:'status', 'aria-label':'Loading'}));
  const retry = snapshot ? null : h('button', {type:'button', className:'btn outline sm', 'data-action':'retry-addon'}, 'Try again');
  if (res.state === 'error' || !res.view) return fragment(h('section', {className:'card pad stack'}, h('h2', {}, 'Can’t show ', addonLabel(a), ' right now.'), h('p', {}, res.message || 'No answer.', ' Nothing here was changed.'), retry));
  return fragment(h('p', {className:'meta'}, 'As of ', time(res.as_of)),
    res.state === 'stale' ? h('div', {className:'banner attn', role:'status'}, h('p', {className:'grow'}, 'Not up to date. Showing the last answer from ', time(res.as_of), '.', res.message ? ' ' + clean(res.message) + ' Newer items may be missing.' : ''), retry) : null,
    res.view.notice ? h('p', {className:'banner ' + (res.view.notice_tone === 'bad' ? 'error' : ['warn', 'needs-you'].includes(res.view.notice_tone) ? 'attn' : '')}, clean(res.view.notice)) : null, h('div', {id:'addon-blocks'}));
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
    blocks.querySelectorAll('.blk').forEach(n => n.classList.add('card'));
    blocks.querySelectorAll('svg').forEach(n => {
      n.replaceWith(iconEl('external'));
    });
    // Block text is supplied by add-ons; keep internal keys out of visible copy.
    const walker = document.createTreeWalker(blocks, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) walker.currentNode.data = clean(walker.currentNode.data);
  }
  if (!snapshot && panelOf(id) === 'repeats') template.append(repeatsCard());
  if (!snapshot && panelOf(id) === 'links' && sharedLinks !== null) template.append(sharedLinksCard());
  reconcile(host, template);
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
  if (route().kind === 'addon' && route().id === id) paintAddon(id);
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

const repeatPresets = ['every day at 9', 'every weekday at 9', 'every monday at 9', 'every hour'];
function repeatsCard() {
  return h('section', {className:'card pad stack addon-native', 'data-key':'repeats-card'},
    h('h2', {}, 'Repeats'), h('div', {className:'actions'},
      h('button', {type:'button', className:'btn primary', 'data-native':'repeat'}, '+ Repeat a ticket')));
}
// The add-on that declares the `repeats` panel (state.addons lists only active add-ons, with no `active` field); null when off (then no Copy/Repeat shows on a ticket).
const repeatsAddon = () => addons().find(a => a.dashboard?.panel === 'repeats')?.name || null;
// From a ticket's menu (`only`) the first schedule is preselected: "Repeat…" must not copy at once.
function repeatsDialog(only = null, addonName = null) {
  if (snapshot) return;
  const {d, actions} = dialog('Repeat a ticket', 'dialog');
  const ticket = h('select', {className:'input', name:'ticket'});
  tickets().filter(t => only ? t.id === only : !['done', 'dropped'].includes(t.status)).forEach(t => ticket.append(new Option(t.title || t.id, t.id)));
  const preset = h('select', {className:'input', name:'repeat'});
  preset.append(new Option('Just once, now', 'once'));
  repeatPresets.forEach(value => preset.append(new Option(capitalise(value).replace('monday', 'Monday'), value)));
  if (only) preset.value = repeatPresets[0];
  const fields = h('div', {className:'form-fields'}, h('label', {}, 'Ticket', ticket), h('label', {}, 'How often', preset));
  if (!ticket.options.length) fields.append(h('p', {className:'meta'}, 'No open tickets yet.'));
  const save = button(only ? 'Save' : 'Copy now', 'primary', async () => {
    if (save.disabled || !ticket.value) return;
    save.disabled = true;
    const once = preset.value === 'once', verb = once ? 'copy' : 'repeat';
    const args = {addon:addonName || route().id, verb, target:ticket.value};
    if (!once) args.value = preset.value;
    const result = await act('addon.act', args);
    window.orch.toast(result.ok ? (once ? 'Ticket copied.' : 'Repeat saved.') : result.text || 'That did not work.', result.ok ? 'ok' : 'error');
    save.disabled = false;
    if (result.ok) await window.orch.close(d);
    if (route().kind === 'addon') await loadAddon(route().id);
  });
  preset.onchange = () => { save.textContent = preset.value === 'once' ? 'Copy now' : 'Save'; };
  save.disabled = !ticket.options.length;
  actions.append(save); d.append(fields, actions); window.orch.open(d);
}
let sharedLinks = null;
async function loadSharedLinks() {
  try {
    const res = await fetch('/api/links', {cache:'no-store'});
    if (res.status !== 200) { sharedLinks = null; return; }
    const data = await res.json();
    sharedLinks = Array.isArray(data.links) ? data.links : null;
  } catch (_) { sharedLinks = null; }
}
function sharedLinksCard() {
  return h('section', {className:'card pad stack addon-native', 'data-key':'shared-links'}, h('h2', {}, 'Links'),
    sharedLinks.length ? sharedLinks.map(link => {
      const expiry = link.expires_at;
      const date = expiry ? new Date(typeof expiry === 'number' ? expiry * 1000 : expiry) : null;
      const expired = link.expired === true || (date && date.getTime() <= Date.now());
      const control = (verb, label) => h('button', {type:'button', className:'btn outline', 'data-native':verb, 'data-link-id':link.id,
        disabled:verb === 'link-copy' && !link.copy, title:verb === 'link-copy' && !link.copy ? 'This link is not available to copy.' : null}, label);
      return h('article', {className:'shared-link stack', 'data-key':'shared-link-' + link.id},
        settingsText('h3', {}, link.name), expired ? h('span', {className:'chip'}, 'Expired') : null,
        settingsText('p', {className:'meta'}, date ? 'Link valid until ' + (Number.isNaN(date.getTime()) ? String(expiry) : date.toLocaleDateString()) : 'No end date'),
        link.size != null ? settingsText('p', {className:'meta'}, typeof link.size === 'number' ? link.size.toLocaleString() + ' bytes' : link.size) : null,
        h('div', {className:'actions'}, control('link-copy', 'Copy link'), control('link-extend', 'Extend'), control('link-stop', 'Stop sharing')),
        h('details', {}, h('summary', {}, 'Details'), settingsText('p', {className:'meta'}, link.id), link.details ? settingsText('p', {}, link.details) : null));
    }) : h('p', {className:'meta'}, 'No shared links yet.'));
}
async function sharedLinkAction(control) {
  if (snapshot || control.disabled) return;
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
    paintAddon(route().id);
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

