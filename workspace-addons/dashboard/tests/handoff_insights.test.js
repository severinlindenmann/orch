const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const src = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/handoff.js'), 'utf8');
const start = src.indexOf('  function cap('), end = src.indexOf('  function sentence(');
function lines(op, parts) {
  const el = (tag, text) => ({tag, textContent: text || '', kids: [], style: {}, appendChild(k) { this.kids.push(k); }});
  const c = vm.createContext({el, document: {createTextNode: t => ({text: t})}, String, Number});
  vm.runInContext(src.slice(start, end) + '\nthis.T = TEMPLATES;', c);
  const text = n => typeof n === 'string' ? n : (n.textContent || n.text || '') + (n.kids || []).map(text).join('');
  return c.T[op](parts).map(text).join('');
}
test('Insights settings read in plain words, no keys or ids', () => {
  assert.equal(lines('insights.settings', {setting: 'insights.keep_days', value: '365'}), 'Change how long full detail is kept to 365 days?');
  assert.equal(lines('insights.settings', {setting: 'insights.max_mb', value: '2048'}), 'Change the largest size of the record to 2 GB?');
  assert.equal(lines('insights.settings', {setting: 'insights.max_mb', value: '512'}), 'Change the largest size of the record to 512 MB?');
  assert.equal(lines('insights.settings', {setting: 'insights.share_names', value: 'on'}), "Change sharing this workspace's names to on?");
  assert.equal(lines('insights.settings', {setting: 'insights.share_counts', value: 'on'}), 'Change sharing counts with your admin to on?');
});
test('an unknown setting or value is capped text, not an id', () => {
  const t = lines('insights.settings', {setting: 'x.y', value: 'z'.repeat(300)});
  assert.match(t, /^Change an Insights setting to /);
  assert.ok(t.length < 200);
});
test('delete detail names the ticket by title and says counts stay', () => {
  const t = lines('record.delete_detail', {title: 'Close March books'});
  assert.match(t, /Delete the full detail of .Close March books.\? The counts stay\./);
  assert.doesNotMatch(t, /t_[a-z0-9]{6}/);
});
test('an answer request reads as one sentence with the answer, Send answer button, source behind Technical details', () => {
  assert.equal(lines('ticket.answer', {title: 'Weekly report', question: 'Which colour'}), 'Send this answer to Weekly report? Which colour');
  const el = (tag, text) => ({tag, textContent: text || '', kids: [], style: {}, appendChild(k) { this.kids.push(k); }});
  const c = vm.createContext({el, document: {createTextNode: t => ({text: t})}, String, Number});
  vm.runInContext(src.slice(start, end) + '\nthis.T = TEMPLATES;', c);
  const text = n => typeof n === 'string' ? n : (n.textContent || n.text || '') + (n.kids || []).map(text).join('');
  assert.equal(c.T['ticket.answer']({title: 'Weekly report', question: 'Which colour'}, {value: 'Blue'}).map(text).join(''), 'Send this answer to Weekly report? Which colour \u2192 Blue');
  const exact = 'say  "yes"';
  assert.equal(c.T['ticket.answer']({title: 'R'}, {value: exact}).map(text).join(''), 'Send this answer to R?  \u2192 ' + exact, 'the short answer is shown exactly as sent');
  assert.match(src, /"Technical details", "meta"\)[^\n]*\n[^\n]*min-height:44px/);
  assert.match(src, /"ticket.answer": "Send answer"/);
  assert.match(src, /display:inline-flex;gap:8px/);
  assert.match(src, /"Technical details"/);
  assert.doesNotMatch(src, /"Requested by a command"/);
});
