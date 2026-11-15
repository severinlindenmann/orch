'use strict';
// "Report a problem": the button in the top bar of every page, its dialog (what happened, what you expected, a picture
// of the page, ticket text) and the "Report ready" answer with the checks. Nothing leaves this computer. The hand-off
// to a helper puts one line into the helper chat's message box; it never sends it by itself.
const reportUi = {busy:false};
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
  return ('<!doctype html>\n' + clone.outerHTML).slice(0, 1500000);
}
// The checks' own names are ids; the good news line reads them as plain words.
const REPORT_NAMES = {clock_skew:'Clock', dead_lock_holder:'Locks', diag_dropped:'Debug log', disk_low:'Disk space', hook_lines_missing:'Helper reminders',
  no_heartbeat:'Helper heartbeat', relay_unreachable:'Relay', run_gone_ticket_working:'Running helper', ticket_op_refused:'Ticket changes', waiting_for_permission:'Permissions'};
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
  const field = (label, input) => h('label', {className:'field'}, h('span', {}, label, ' ', h('span', {className:'meta'}, '(optional)')), input);
  body.append(
    h('p', {className:'muted'}, 'orch saves what happened around ', h('strong', {}, scope.label), ' since the helper started, on this computer. Nothing is sent.'),
    field('What happened?', happened), field('What did you expect?', expected),
    h('label', {className:'check-label'}, picture, ' Add a picture of this page'),
    h('p', {className:'meta'}, 'The picture can show ticket text. You see everything before anything is shared.'),
    h('label', {className:'check-label'}, content, ' Include ticket text and helper conversation'));
  const create = button('Create report', 'primary', async () => {
    reportUi.busy = true;
    create.disabled = true; actions.querySelectorAll('button').forEach(b => { b.disabled = true; });
    const bar = h('div', {className:'progress', role:'progressbar', 'aria-label':'Collecting'}, h('span', {}));
    bar.firstChild.style.setProperty('--value', '60%');
    body.replaceChildren(h('p', {role:'status'}, 'Collecting…'), bar, h('p', {className:'meta'}, 'This page, the ticket, the helper, add-ons, the relay'));
    const payload = {ticket:scope.ticket, addon:scope.addon, note:happened.value.trim() || undefined, expected:expected.value.trim() || undefined,
      content:content.checked, page:picture.checked && content.checked ? reportPageSnapshot() : undefined};
    let result = null, failure = 'The report could not be made. Please try again.';
    try {
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
  body.replaceChildren(h('p', {}, h('strong', {}, 'Checks')), reportChecks(array(result.checks)),
    h('p', {className:'report-sub'}, h('strong', {}, 'Give it to a helper')), h('p', {className:'muted'}, 'Paste this into Claude or a helper chat:'),
    h('div', {className:'row'}, h('input', {type:'text', className:'input grow', readOnly:true, value:line, 'aria-label':'Line for a helper', 'data-key':'report-line'}), copy),
    h('p', {className:'meta'}, folder));
  actions.replaceChildren(button('Close', 'outline', () => window.orch.close(d)),
    button('Ask a helper to investigate', 'primary', async () => { await window.orch.close(d); chatPrefill(line); }));
  actions.querySelector('.btn.primary')?.focus();
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
