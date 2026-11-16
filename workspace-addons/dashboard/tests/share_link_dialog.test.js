const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const web = path.join(__dirname, '../src/orch_dashboard/web/pages/');
const settings = fs.readFileSync(path.join(web, 'settings.js'), 'utf8');
const ticket = fs.readFileSync(path.join(web, 'ticket.js'), 'utf8');
const viewer = fs.readFileSync(path.join(__dirname, '../../../workspace/src/orch_ui/static/fileviewer.js'), 'utf8');
const dialog = () => { const i = settings.indexOf('function shareDialog'); return settings.slice(i, settings.indexOf('async function sharedLinkAction', i)); };

// e2e 15 Nov (item 36): the dialog stays open on success, shows the link, copies it and says "Copied"
test('Share a file keeps the dialog open, shows the link and copies it', () => {
  const body = dialog();
  const ok = body.indexOf('if (!out.ok)'), copy = body.indexOf('window.UI.copyText(row.link)');
  assert.ok(ok > 0 && copy > ok, 'the link is copied after a successful share');
  assert.match(body, /'Copied'/);
  assert.match(body, /h\('input', \{className:'input', type:'text', readOnly:true, value:row\.link/);
  assert.match(body, /button\('Copy'/);
  assert.ok(body.indexOf('window.orch.close(d)') > body.indexOf('if (!row)') , 'it only closes by itself when no link is known');
});

// "Share by link…" in the file viewer: same flow for a ticket file, only when sharing is on
test('the viewer shows "Share by link…" only when the caller can share, and it opens the same dialog', () => {
  assert.match(viewer, /typeof opts\.share === 'function'[^\n]*'Share by link…'/);
  assert.match(ticket, /addons\(\)\.some\(a => a\.active !== false && isPublish\(a\.name\)\) \? f => shareDialog\(\{name:/);
  assert.match(ticket, /FileViewer\.open\(\{files, index, context:[^\n]*share\}\)/);
  assert.match(dialog(), /function shareDialog\(start = null\)/);
  assert.match(dialog(), /act\('link\.share'/);
});
