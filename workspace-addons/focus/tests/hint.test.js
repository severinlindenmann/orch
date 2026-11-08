const test = require('node:test'), assert = require('node:assert'), fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
const src = fs.readFileSync(path.join(__dirname, '..', 'src', 'orch_focus', 'web', 'focus.js'), 'utf8');
const m = /function hintText[\s\S]*?\n}\n/.exec(src);
const ctx = {}; vm.createContext(ctx); vm.runInContext(m[0], ctx);
test('the message hint points to the answer while a question waits', () => {
  assert.match(ctx.hintText({generic:false, live:true}, true, true), /Answer the question/);
  assert.doesNotMatch(ctx.hintText({generic:false, live:true}, true, true), /after this step/);
  assert.equal(ctx.hintText({generic:false, live:true}, true, false), 'Goes in after this step.');
  assert.equal(ctx.hintText({generic:true, live:false}, false, false), 'Saved for the next run.');
});
