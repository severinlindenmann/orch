'use strict';
// "Report a problem": the button in the top bar of every page, its dialog (what happened, what you expected, a picture
// of the page, ticket text, more details, added pictures and files) and the "Report ready" answer with the checks.
// Nothing leaves this computer unless the workspace is connected to a relay AND the person ticks "Send this report":
// then the same report goes to that relay's admin. The hand-off to a helper puts one line into the helper chat's
// message box; it never sends it by itself.
const reportUi = {busy:false};
const REPORT_FILES = 10, REPORT_FILE_BYTES = 8 * 1024 * 1024, REPORT_FILES_BYTES = 25 * 1024 * 1024;
// The connected relay's host name, or '' (no relay, not turned on, not connected: the dialog then never mentions it).
function reportRelay() {
  const relay = array(state.settings?.addons).find(a => a.name === 'relay');  // the Settings rows carry the connection
  if (!relay?.active || !relay.detail?.connected) return '';
  return clean(String(relay.detail.address || '').replace(/^https?:\/\//, '').split('/')[0]) || 'your relay';
}
const reportBase64 = file => new Promise((resolve, reject) => {
  const reader = new FileReader();
  reader.onload = () => resolve(String(reader.result).slice(String(reader.result).indexOf(',') + 1)); reader.onerror = () => reject(reader.error);
  reader.readAsDataURL(file);
});
const reportSize = n => n >= 1024 * 1024 ? (n / 1024 / 1024).toFixed(1) + ' MB' : Math.max(1, Math.round(n / 1024)) + ' KB';
// The added pictures and files: a button, the list with Remove, paste and drop anywhere in the dialog.
function reportFiles(d) {
  const files = [];
  const list = h('ul', {className:'report-checks stack-sm', 'aria-label':'Added files', 'data-key':'report-files'});
  const error = h('p', {className:'bad', role:'alert', 'data-key':'report-files-error'}); error.hidden = true;
  const picker = h('input', {type:'file', multiple:true, 'data-key':'report-picker'}); picker.hidden = true;
  const draw = () => list.replaceChildren(...files.map(f => h('li', {className:'report-check'},
    h('span', {className:'grow'}, clean(f.name), ' ', h('span', {className:'meta'}, reportSize(f.size))),
    button('Remove', 'ghost xs', () => { files.splice(files.indexOf(f), 1); draw(); }))));
  const add = incoming => {
    const refused = [];
    for (const file of incoming) {
      const total = files.reduce((n, f) => n + f.size, 0);
      if (files.length >= REPORT_FILES) refused.push(file.name + ': a report takes at most ' + REPORT_FILES + ' files');
      else if (file.size > REPORT_FILE_BYTES) refused.push(file.name + ': bigger than 8 MB');
      else if (total + file.size > REPORT_FILES_BYTES) refused.push(file.name + ': the files are bigger than 25 MB together');
      else files.push(file);
    }
    error.textContent = refused.join('\n'); error.hidden = !refused.length;
    draw();
  };
  picker.addEventListener('change', () => { add(Array.from(picker.files)); picker.value = ''; });
  d.addEventListener('paste', event => {
    const pasted = window.UI?.pastedFiles?.(event) || [];  // a pasted screenshot: same path as a picked file
    if (pasted.length) { event.preventDefault(); add(pasted); }
  });
  d.addEventListener('dragover', event => { if (Array.from(event.dataTransfer?.types || []).includes('Files')) event.preventDefault(); });
  d.addEventListener('drop', event => { if (event.dataTransfer?.files.length) { event.preventDefault(); add(Array.from(event.dataTransfer.files)); } });
  const pick = h('button', {type:'button', className:'btn outline sm', 'data-key':'report-add-files'}, 'Add pictures or files');
  pick.addEventListener('click', () => picker.click());
  const nodes = [h('div', {className:'row'}, pick, h('span', {className:'meta'}, 'Pick, drop or paste them. Up to 10.')), picker, list, error];
  return {nodes, read:async () => Promise.all(files.map(async f => ({name:f.name, data:await reportBase64(f)}))), count:() => files.length};
}
function reportScope() {
  const r = route();
  if (r.kind === 'ticket') {
    const t = ticketOf(r.id);
    if (t) return {ticket:t.id, label:clean(t.key || t.title) || 'this ticket'};
  }
  if (r.kind === 'page' || r.kind === 'addon') return {addon:r.id, label:addonLabel(addons().find(a => a.name === r.id))};
  return {label:'this workspace'};
}
// The page as it is now, for the helper: no scripts or styles, every typed value masked, add-on frames and pictures
// left out. (A real screenshot needs a library; this snapshot needs none.)
function reportPageSnapshot() {
  const clone = document.documentElement.cloneNode(true);
  clone.querySelectorAll('script,style,link,dialog,iframe,img,video,audio,canvas').forEach(n => n.remove());
  clone.querySelectorAll('input,textarea,select').forEach(n => {
    n.removeAttribute('value'); n.removeAttribute('placeholder');
    if (n.tagName === 'INPUT') n.setAttribute('value', '[masked]'); else n.textContent = '[masked]';
  });
  clone.querySelectorAll('[contenteditable]').forEach(n => { n.textContent = '[masked]'; });
  // the page's own data-* hooks (data-key="heading") say nothing to a helper and read like "key=value" to the secret check
  clone.querySelectorAll('*').forEach(n => { for (const name of n.getAttributeNames()) if (name.startsWith('data-')) n.removeAttribute(name); });
  return ('<!doctype html>\n' + clone.outerHTML).slice(0, 1500000);
}
// The checks' own names are ids; the good news line reads them as plain words.
const REPORT_NAMES = {clock_skew:'Clock', dead_lock_holder:'Locks', diag_dropped:'Debug log', disk_low:'Disk space', hook_lines_missing:'Helper reminders',
  no_heartbeat:'Helper heartbeat', run_gone_ticket_working:'Running helper', ticket_op_refused:'Ticket changes', waiting_for_permission:'Permissions'};
const reportName = id => REPORT_NAMES[id] || capitalise(String(id || '').replace(/_/g, ' '));
function reportCheckRow(c) {
  const problem = c.verdict === 'problem', ok = c.verdict === 'ok';
  const chip = h('span', {className:'chip' + (problem ? ' warning' : '')}, ok ? h('span', {className:'dot-ok'}) : problem ? h('span', {className:'dot-warn'}) : null, ok ? ' OK' : problem ? ' Problem' : 'Couldn’t check');
  return h('li', {className:'report-check'}, chip, h('span', {}, clean(c.fact || c.name)));
}
// Plain rows: every problem, then what could not be checked, then the good news in one line.
function reportChecks(checks) {
  const by = v => checks.filter(c => c.verdict === v);
  const okNames = by('ok').map(c => reportName(c.name));
  return h('ul', {className:'report-checks stack-sm', 'data-key':'report-checks'}, [...by('problem'), ...by('cannot_check')].map(reportCheckRow),
    okNames.length ? reportCheckRow({verdict:'ok', fact:okNames.join(', ').replace(/^./, c => c) + '.'}) : null);
}
function reportOpen() {
  if (snapshot || reportUi.busy) return;
  const scope = reportScope();
  const {d, actions} = dialog('Report a problem', 'dialog report-dialog', 'report');
  const body = h('div', {className:'stack-sm'});
  const happened = h('input', {type:'text', className:'input', maxLength:600, placeholder:'For example: stuck since 10:00, nothing happens', 'data-key':'report-happened'});
  const expected = h('input', {type:'text', className:'input', maxLength:600, placeholder:'For example: the newsletter is sent', 'data-key':'report-expected'});
  const picture = h('input', {type:'checkbox', 'data-key':'report-picture'}); picture.checked = true;
  const content = h('input', {type:'checkbox', 'data-key':'report-content'}); content.checked = true;
  const more = h('textarea', {className:'input', rows:2, maxLength:4000, placeholder:'For example: it worked yesterday, and what you tried', 'data-key':'report-more'});
  const added = reportFiles(d);
  const relay = reportRelay();
  const share = h('input', {type:'checkbox', 'data-key':'report-share'});
  const field = (label, input) => h('label', {className:'field'}, h('span', {}, label, ' ', h('span', {className:'meta'}, '(optional)')), input);
  body.append(
    h('p', {className:'muted'}, 'orch saves what happened around ', h('strong', {}, scope.label), ' since the helper started, on this computer. ',
      relay ? 'Nothing is sent unless you tick the last box.' : 'Nothing is sent.'),
    field('What happened?', happened), field('What did you expect?', expected), field('Anything else?', more), ...added.nodes,
    h('label', {className:'check-label'}, picture, ' Add a picture of this page'),
    h('p', {className:'meta'}, 'The picture can show ticket text.'),
    h('label', {className:'check-label'}, content, ' Include ticket text and helper conversation'),
    relay ? h('label', {className:'check-label'}, share, ' Send this report to the admin of ', h('strong', {}, relay)) : null,
    relay ? h('p', {className:'meta', 'data-key':'report-share-hint'}, 'Everything in the report goes along, with the files you added. The admin and the workspaces they choose can read it.') : null);
  const create = button('Create report', 'primary', async () => {
    reportUi.busy = true;
    create.disabled = true; actions.querySelectorAll('button').forEach(b => { b.disabled = true; });
    const bar = h('div', {className:'progress', role:'progressbar', 'aria-label':'Collecting'}, h('span', {}));
    bar.firstChild.style.setProperty('--value', '60%');
    const sharing = !!relay && share.checked;
    body.replaceChildren(h('p', {role:'status'}, sharing ? 'Collecting and sending…' : 'Collecting…'), bar, h('p', {className:'meta'}, 'This page, the ticket, the helper and add-ons'));
    let result = null, failure = 'The report could not be made. Please try again.';
    try {
      const payload = {ticket:scope.ticket, addon:scope.addon, note:happened.value.trim() || undefined, expected:expected.value.trim() || undefined,
        more:more.value.trim() || undefined, files:added.count() ? await added.read() : undefined, share:sharing || undefined,
        content:content.checked, page:picture.checked && content.checked ? reportPageSnapshot() : undefined};
      const res = await fetch('/api/diag/report', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
      if (res.ok) result = await res.json(); else failure = window.DashHelpers.scrubText(await res.text()) || failure;
    } catch (_) { /* the plain failure text stands */ }
    reportUi.busy = false;
    if (!d.isConnected) return;
    if (!result) { window.orch.toast(failure, 'error'); await window.orch.close(d); return; }
    reportReady(d, actions, body, result);
  });
  actions.append(create);
  d.append(body, actions);
  window.orch.open(d);
  happened.focus();
}
function reportReady(d, actions, body, result) {
  // Settings counts the reports: read the state again (a new report folder does not change the cached state by itself)
  fetch('/api/state?fresh=1', {cache:'no-store'}).then(r => r.ok ? r.json() : null).then(next => { if (next) accept(next); }).catch(() => {});
  d.querySelector('h2').textContent = 'Report ready';
  const line = 'Investigate orch report ' + result.ref;
  const folder = h('button', {type:'button', className:'btn ghost sm', 'data-key':'report-folder'}, 'Open folder');
  folder.addEventListener('click', async () => {
    let out = null;
    try { const res = await fetch('/api/diag/open', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ref:result.ref})}); if (res.ok) out = await res.json(); } catch (_) { /* below */ }
    if (out && out.opened) return;
    if (out && out.path && window.UI?.copyText && await window.UI.copyText(out.path)) window.orch.toast('Could not open it here. The folder path is copied.');
    else window.orch.toast('Could not open the folder.', 'error');
  });
  const copy = button('Copy', 'outline', async () => {
    const ok = window.UI?.copyText ? await window.UI.copyText(line) : false;
    window.orch.toast(ok ? 'Copied. Paste it to a helper.' : 'Could not copy. Select the line and copy it.', ok ? undefined : 'error');
  });
  // Say plainly that it is saved and under which name, first (ORCH-89: a quick look only saw "Collecting…").
  const saved = h('p', {role:'status', 'data-key':'report-saved'}, h('span', {className:'dot-ok'}), ' Saved on this computer as ', h('strong', {}, String(result.ref || '')), '.');  // not clean(): it drops the ticket id inside a ref
  body.replaceChildren(...[saved, reportChecks(array(result.checks)), reportShared(result),
    h('p', {className:'report-sub'}, h('strong', {}, 'Give it to a helper')), h('p', {className:'muted'}, 'Paste this into a helper chat:'),
    h('div', {className:'row'}, h('input', {type:'text', className:'input grow', readOnly:true, value:line, 'aria-label':'Line for a helper', 'data-key':'report-line'}), copy),
    h('p', {className:'meta'}, folder)].filter(Boolean));  // replaceChildren writes a null as the word
  actions.replaceChildren(button('Close', 'outline', () => window.orch.close(d)),
    button('Ask a helper to investigate', 'primary', async () => { await window.orch.close(d); chatPrefill(line); }));
  actions.querySelector('.btn.primary')?.focus();
}
// What happened to "Send this report": sent, or why not with one button to try again (the report itself is kept).
function reportShared(result) {
  if (result.shared) return h('p', {role:'status', 'data-key':'report-shared'}, h('span', {className:'dot-ok'}), ' Sent to the admin of ', h('strong', {}, clean(result.shared.to)), '.');
  if (!result.share_error) return null;
  const box = h('div', {className:'stack-sm', 'data-key':'report-share-failed'});
  const again = button('Try again', 'outline sm', async () => {
    again.disabled = true;
    let out = null, why = 'The report could not be sent. Please try again.';
    try {
      const res = await fetch('/api/diag/share', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ref:result.ref})});
      if (res.ok) out = await res.json(); else why = window.DashHelpers.scrubText(await res.text()) || why;
    } catch (_) { /* the plain failure text stands */ }
    if (out?.shared) box.replaceWith(reportShared(out));
    else { box.firstChild.textContent = 'Not sent: ' + why; again.disabled = false; }
  });
  box.append(h('p', {className:'bad', role:'alert'}, 'Not sent: ' + clean(result.share_error)), h('div', {className:'row'}, again, h('span', {className:'meta'}, 'The report is saved on this computer.')));
  return box;
}
// The same in-page hand-off as Factory's idea box: the line lands in the helper chat's message box (an empty one; a
// draft you already typed is kept) and the person presses Send. Nothing is read from a URL.
function chatPrefill(text) {
  chatOpenAgent();
  if (!(chatUi.drafts.chat || '').trim()) chatUi.drafts.chat = String(text).slice(0, 500);
  render();
  const field = document.querySelector('.chat-page .chat-draft');
  if (field) { field.value = chatUi.drafts.chat; field.focus(); }
}
