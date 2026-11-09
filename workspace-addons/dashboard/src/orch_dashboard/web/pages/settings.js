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
const FULL_WARNING = 'Full: the agent can change or delete anything in this folder and run any command without asking.';
const PERMISSION_CHOICES = [['ask', 'Ask', 'The agent asks before it changes anything.'], ['auto', 'Auto', 'The agent works on its own and asks only for risky things.'], ['full', 'Full', 'The agent never asks. It changes things without asking. Only use this if you trust it.']];
function permissionsCard(settings) {
  const current = PERMISSION_CHOICES.some(([value]) => value === settings.permissions) ? settings.permissions : 'auto';
  const rows = PERMISSION_CHOICES.map(([value, label, hint]) => {
    const radio = h('input', {type:'radio', name:'settings-permissions', value, 'data-key':'settings-permissions-' + value, 'data-settings-permissions':value, disabled:snapshot || settingsBusy.has('permissions')});
    radio.checked = value === current;
    return h('label', {className:'card-row agent-opt' + (value === current ? ' sel' : ''), 'data-key':'settings-permissions-row-' + value}, radio,
      h('div', {className:'grow'}, settingsText('h3', {}, label), settingsText('p', {className:'meta'}, hint)));
  });
  return h('div', {className:'stack', 'data-key':'settings-permissions'}, h('h2', {className:'set-sub'}, 'What the agent may do'),
    h('div', {className:'card'}, h('div', {className:'permission-choices', role:'radiogroup', 'aria-label':'What the agent may do'}, rows),
      current === 'full' ? h('p', {className:'card-row bad', role:'note'}, FULL_WARNING) : null));
}
// Share with team: off by default; on writes one short entry into the team's AGENTS.md (the orch files stay local).
function shareCard(settings) {
  const on = settings.share === true;
  return h('div', {className:'stack', 'data-key':'settings-share'}, h('h2', {className:'set-sub'}, 'Team'),
    h('div', {className:'card'}, h('div', {className:'card-row'},
      h('div', {className:'grow'}, settingsText('h3', {}, 'Share with team'),
        settingsText('p', {className:'meta'}, on ? 'AGENTS.md has a short orch entry. Turn off to remove it.' : 'Off: orch files stay on this computer and your team sees nothing.')),
      h('button', {type:'button', className:'switch', role:'switch', 'aria-checked':on, 'aria-label':'Share with team', 'data-key':'settings-switch-share', 'data-action':'settings-share', disabled:snapshot || settingsBusy.has('share')}))));
}
// The CLI hint stays out of the page: a missing sign-in is said in plain words.
const plainTest = reason => /not logged in|\/login/i.test(String(reason || '')) ? 'The agent is not signed in yet.' : reason;
function workflowCard(settings) {
  return h('div', {className:'stack', 'data-key':'settings-workflow'}, h('h2', {className:'set-sub'}, 'Workflow'),
    h('div', {className:'card'}, h('div', {className:'card-row'},
      h('div', {className:'grow'}, settingsText('h3', {}, 'Agents may mark tickets Done'),
        settingsText('p', {className:'meta'}, 'Off: agents send finished work to Review and you decide when it is Done.')),
      h('button', {type:'button', className:'switch', role:'switch', 'aria-label':'Agents may mark tickets Done', 'aria-checked':!!settings.agents_may_finish, 'data-action':'workflow-set', disabled:snapshot || settingsBusy.has('workflow')}))));
}
function settingsPage() {
  const settings = state.settings;
  const phoneAddon = addons().find(a => a.dashboard?.panel === 'phone');
  const agents = array(settings.agents).map(agent => {
    const radio = h('input', {type:'radio', 'aria-label':agent.label, name:'settings-agent', value:agent.name, 'data-key':'settings-agent-' + agent.name, 'data-settings-agent':agent.name, disabled:settingsBusy.has('agent') || (!agent.found && agent.status !== 'your command')});
    radio.checked = !!agent.chosen;
    const missing = !agent.found && agent.status !== 'your command';
    const status = agent.status === 'your command' ? 'Your own agent' : agent.found ? 'Found' + (agent.version ? ' · version ' + agent.version : '') : 'Not found on this computer';
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
    h('div', {className:'settings-layout'}, h('nav', {className:'tabs settings-nav', role:'tablist', 'aria-label':'Settings'}, [['general', 'General'], ['agent', 'Agent'], ...(phoneAddon ? [['phone', phoneAddon.dashboard.label]] : []), ['addons', 'Add-ons']].map(([id, label]) => id === 'phone' ? h('a', {href:'#addon/' + phoneAddon.name, 'data-key':'settings-phone'}, label) : h('button', {type:'button', id:'settings-tab-' + id, role:'tab', 'aria-selected':settingsTab === id, 'aria-controls':'settings-panel-' + id, tabindex:settingsTab === id ? '0' : '-1', 'data-action':'settings-tab', 'data-tab':id}, label))), h('div', {className:'settings-content'},
    panel('general', [snapshot ? null : window.OrchMobileMode?.settingsSection(h), snapshot ? null : window.OrchLook?.settingsSection(), h('div', {className:'stack', 'data-key':'settings-workspace'}, h('h2', {className:'set-sub'}, 'Workspace'), h('div', {className:'card'},
      h('div', {className:'card-row name-row'}, h('span', {className:'set-label'}, 'Name'), settingsText('p', {className:'grow set-ctl'}, state.workspace)),
      h('details', {className:'settings-details'}, h('summary', {}, 'Details'), h('div', {className:'card-row'}, h('span', {className:'set-label'}, 'Folder'), h('div', {className:'grow set-ctl'}, settingsText('p', {className:'mono'}, settings.folder), h('p', {className:'meta'}, 'Stored on this computer')))))),
      shareCard(settings), workflowCard(settings)]),
    panel('agent', [h('p', {className:'meta'}, 'Pick the default. It is saved right away.'), h('div', {className:'stack'}, h('div', {className:'agent-cards', role:'radiogroup', 'aria-label':'Default agent'}, agents),
      snapshot ? null : h('div', {className:'agent-foot', 'data-key':'settings-add-slot'}, h('button', {type:'button', className:'btn ghost sm', 'data-key':'settings-add-agent', 'data-action':'agent-add'}, '+ Add your own agent'))),
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
      (() => { const a = el('div', 'acts'); a.append(back, button('Add agent', 'primary sm', async () => {
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

const addonViews = Object.create(null), addonBusy = new Set();
let addonTimer, activeAddon = null;
// The label comes from the add-on's own manifest; `panel` is a capability the manifest declares (repeats | links | phone).
const panelOf = id => addons().find(a => a.name === id)?.dashboard?.panel || null;
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
// An add-on row's "Send a message" opens a small box; Send passes the text on for that workspace or phone.
function messageSend(control) {
  if (snapshot || route().kind !== 'addon') return;
  const peer = control.dataset.sendTo, who = control.dataset.who || 'this workspace';
  const {d, actions} = dialog('Send a message to ' + who, 'dialog');
  const area = el('textarea', 'input');
  Object.assign(area, {rows:4, maxLength:2000, name:'message', placeholder:'Write your message'});
  area.setAttribute('aria-label', 'Message to ' + who);
  const go = button('Send', 'primary', async () => {
    const text = area.value.trim();
    if (!text || go.disabled) return;
    go.disabled = true;
    const args = {workspace:peer, text};
    if (control.dataset.replyTo !== undefined) args.reply_to = control.dataset.replyTo;
    const result = await act('message.send', args);
    go.disabled = false;
    if (!result.ok) { window.orch.toast(result.text || 'That did not work.', 'error'); return; }
    await window.orch.close(d);
    window.orch.toast('Sent to ' + who, 'ok');
    loadAddon(route().id);
  });
  actions.append(go);
  d.append(area, actions);
  window.orch.open(d);
  area.focus();
}
async function copyText(control) {
  try { await navigator.clipboard.writeText(control.dataset.copy); window.orch.toast('Copied', 'ok'); }
  catch (_) { window.orch.toast('Could not copy. Select the text and copy it.', 'error'); }
}

const repeatPresets = ['every day at 9', 'every weekday at 9', 'every monday at 9', 'every hour'];
function repeatsCard() {
  return h('section', {className:'card pad stack addon-native', 'data-key':'repeats-card'},
    h('h2', {}, 'Repeats'), h('div', {className:'actions'},
      h('button', {type:'button', className:'btn primary', 'data-native':'repeat'}, '+ Repeat a ticket'),
      h('button', {type:'button', className:'btn outline', 'data-native':'copy'}, 'Copy a ticket')));
}
// The add-on that declares the `repeats` panel (state.addons lists only active add-ons, with no `active` field); null when off (then no Copy/Repeat shows on a ticket).
const repeatsAddon = () => addons().find(a => a.dashboard?.panel === 'repeats')?.name || null;
function repeatsDialog(verb, only = null, addonName = null) {
  if (snapshot) return;
  const {d, actions} = dialog(verb === 'repeat' ? 'Repeat a ticket' : 'Copy a ticket', 'dialog');
  const ticket = h('select', {className:'input', name:'ticket'});
  tickets().filter(t => only ? t.id === only : !['done', 'dropped'].includes(t.status)).forEach(t => ticket.append(new Option(t.title || t.id, t.id)));
  const preset = h('select', {className:'input', name:'repeat'});
  repeatPresets.forEach(value => preset.append(new Option(capitalise(value).replace('monday', 'Monday'), value)));
  const fields = h('div', {className:'form-fields'}, h('label', {}, 'Ticket', ticket),
    verb === 'repeat' ? h('label', {}, 'Repeat', preset) : null);
  if (!ticket.options.length) fields.append(h('p', {className:'meta'}, 'No open tickets yet.'));
  const save = button(verb === 'repeat' ? 'Save' : 'Copy ticket', 'primary', async () => {
    if (save.disabled || !ticket.value) return;
    save.disabled = true;
    const args = {addon:addonName || route().id, verb, target:ticket.value};
    if (verb === 'repeat') args.value = preset.value;
    const result = await act('addon.act', args);
    window.orch.toast(result.ok ? (verb === 'repeat' ? 'Repeat saved.' : 'Ticket copied.') : result.text || 'That did not work.', result.ok ? 'ok' : 'error');
    save.disabled = false;
    if (result.ok) await window.orch.close(d);
    if (route().kind === 'addon') await loadAddon(route().id);
  });
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
    control.onclick = () => ['repeat', 'copy'].includes(control.dataset.native) ? repeatsDialog(control.dataset.native) : sharedLinkAction(control);
  });
}

// Copy a ticket in one click and open the copy; the copy is the ticket that was not there before.
async function copyTicket(t) {
  const addon = repeatsAddon(), known = new Set(tickets().map(x => x.id));
  if (!addon || snapshot) return;
  const result = await act('addon.act', {addon, verb:'copy', target:t.id});
  const made = result.ok ? tickets().find(x => !known.has(x.id)) : null;
  window.orch.toast(result.ok ? 'Ticket copied.' : changeError(result), result.ok ? 'ok' : 'error');
  if (made) location.hash = href(made.id);
}
