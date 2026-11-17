// ORCH-89: the finished "Report a problem" view says Saved with the full reference first, and Settings' About row
// (Style guide) sits in About & updates, not in General.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const WEB = path.join(__dirname, '../src/orch_dashboard/web');
const read = name => fs.readFileSync(path.join(WEB, name), 'utf8');
const between = (src, from, to) => src.slice(src.indexOf(from), src.indexOf(to, src.indexOf(from)));

test('the finished report view starts with Saved and the whole reference, ticket id included', () => {
  const app = read('app.js');
  const ctx = {};
  vm.createContext(ctx);
  // app.js's own clean() strips ticket ids: the Saved line must not run the ref through it
  vm.runInContext(app.slice(app.indexOf('const cleanIds ='), app.indexOf('\n', app.indexOf('const clean ='))).replace(/const /g, 'var ') + ';var showWs=v=>String(v||"");var TAG_HEAD=/^$/;var TAG_TAIL=/^$/;', ctx);
  assert.notEqual(ctx.clean('r-1116-1748-t_8k1847'), 'r-1116-1748-t_8k1847');
  const ready = between(read('pages/report.js'), 'function reportReady', '\n}\n');
  const saved = ready.split('\n').find(l => l.includes("'data-key':'report-saved'"));
  assert.ok(saved && saved.includes('Saved on this computer as') && saved.includes('String(result.ref'), saved);
  assert.ok(!/clean\(result\.ref\)/.test(saved));
  assert.ok(/body\.replaceChildren\(\.\.\.\[saved,/.test(ready), 'the Saved line comes first');
});

test("Settings' Style guide row is in About & updates, not in General", () => {
  const settings = read('pages/settings.js');
  const about = between(settings, 'function aboutPanel()', '\n}\n');
  const general = between(settings, "panel('general',", "panel('agent',");
  assert.ok(about.includes("'data-key':'settings-style-guide'"));
  assert.ok(!general.includes('settings-style-guide') && !general.includes("'About'"));
});
