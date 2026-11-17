const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const src = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/ticket.js'), 'utf8');
const start = src.indexOf('const PROOF_MARK'), end = src.indexOf('function ticketDoneLine');
function line(t, snapshot = false) {
  const h = (tag, attrs, ...children) => ({tag, attrs, children:children.flat(Infinity).filter(c => c != null)});
  const c = vm.createContext({h, array:v => Array.isArray(v) ? v : [], clean:v => v, snapshot});
  vm.runInContext(src.slice(start, end), c);
  return c.ticketProofLine(t);
}
const text = n => typeof n === 'string' ? n : (n.children || []).map(text).join('');
test('shows the core line, hint and details; nothing without proof data', () => {
  assert.equal(line({id:'t_1', checklist:[]}), null);
  const t = {id:'t_1', checklist:[{id:'c1', text:'Tests pass'}], proof:{line:'1 part of "Done when" has no task', level:'warn', uncovered:['and it works on the phone'], per_item:{c1:'passed'}}};
  const out = text(line(t));
  assert.match(out, /1 part of "Done when" has no task/);
  assert.match(out, /Nothing in the to-do list covers this yet/);
  assert.match(out, /Check passed/);
});
test('a failed check is a bad mark, no checks is neutral', () => {
  const json = JSON.stringify(line({id:'t_1', checklist:[], proof:{line:'1 check failed', level:'fail', uncovered:[], per_item:{}}}));
  assert.match(json, /proof-bad/);
  assert.match(JSON.stringify(line({id:'t_1', checklist:[], proof:{line:'No checks recorded', level:'note', uncovered:[], per_item:{}}})), /proof-none/);
});
test('the colour comes from the core level, not the wording', () => {
  assert.match(JSON.stringify(line({id:'t_1', checklist:[], proof:{line:'Anything new', level:'fail', uncovered:[], per_item:{}}})), /proof-bad/);
});
test('header line: done tickets with tasks only, never with an open coverage warning', () => {
  const c = vm.createContext({h:(tag, attrs, ...ch) => ({tag, attrs, children:ch.flat(Infinity).filter(x => x != null)}), array:v => Array.isArray(v) ? v : [], clean:v => v, snapshot:false});
  vm.runInContext(src.slice(start, end), c);
  const proof = (level, uncovered = []) => ({line:'x', level, uncovered, per_item:{}});
  assert.equal(c.headerProof({id:'t', status:'active', checklist:[{id:'c1'}], proof:proof('ok')}), null);
  assert.equal(c.headerProof({id:'t', status:'done', checklist:[], proof:proof('note')}), null);
  assert.equal(c.headerProof({id:'t', status:'done', checklist:[{id:'c1'}], proof:proof('warn', ['a'])}), null);
  assert.notEqual(c.headerProof({id:'t', status:'done', checklist:[{id:'c1'}], proof:proof('ok')}), null);
});
test('changed since the check: the line and a button that sends one fixed text', () => {
  const sent = [];
  const h = (tag, attrs, ...children) => ({tag, attrs, children:children.flat(Infinity).filter(c => c != null)});
  const ticketButton = (label, cls, fn, attrs) => ({tag:'button', label, fn, attrs, children:[label]});
  const c = vm.createContext({h, array:v => Array.isArray(v) ? v : [], clean:v => v, snapshot:false, ticketButton, ticketSendChanges:(t, text) => sent.push([t.id, text])});
  vm.runInContext(src.slice(start, end), c);
  const proof = {line:"Changes haven't been checked yet", uncovered:[], per_item:{c1:'changed'}};
  const t = {id:'t_1', status:'review', checklist:[{id:'c1', text:'Tests pass', evidence:[{type:'command', ref:'rm -rf /; echo hi'}]}], proof};
  const out = c.ticketProofLine(t);
  assert.match(text(out), /Changes haven't been checked yet/);
  const find = n => n && (n.tag === 'button' ? n : (n.children || []).map(find).find(Boolean));
  const btn = find(out);
  assert.equal(btn.label, 'Ask your helper to check again');
  btn.fn();
  assert.deepEqual(sent, [['t_1', 'Please run the checks again and record them with orch check record.']]); // fixed text, not the stored command
  assert.equal(find(c.ticketProofLine({...t, status:'active'})), undefined);
});
const nodesOf = n => n && typeof n === 'object' ? [n, ...(n.children || []).flatMap(nodesOf)] : [];
test('in Check each step shows its evidence: completion note, what ran, the pull request link', () => {
  const ev = [{type:'command', ref:'pr-green.sh 1012', exit:0}, {type:'note', summary:'Merged on green CI.', ref:'pr-green: GREEN, 4 checks SUCCESS; merged as 0c49e136'},
    {type:'pr', ref:'https://github.com/o/r/pull/1012'}, {type:'command', ref:'pytest', exit:1}];
  const t = {id:'t_1', status:'review', checklist:[{id:'c1', text:'Ship it', done:true, evidence:ev}], proof:{line:'1 check passed', level:'ok', uncovered:[], per_item:{c1:'passed'}}};
  const out = line(t), all = text(out);
  for (const bit of ['Merged on green CI.', 'merged as 0c49e136', 'Ran: pr-green.sh 1012', 'Ran: pytest (failed, exit 1)', 'PR #1012']) assert.ok(all.includes(bit), bit);
  const a = nodesOf(out).find(n => n.tag === 'a');
  assert.equal(a.attrs.href, 'https://github.com/o/r/pull/1012');
  assert.ok(!text(line({...t, status:'done'})).includes('Ran: '), 'a Done ticket keeps its short rows');
});
test('#n mentions link to GitHub through the ticket\'s own links; no GitHub link anywhere keeps plain text', () => {
  const t = {id:'t_1', status:'review', refs:[{url:'https://github.com/o/r/issues/5'}], checklist:[], done_when:'Answers from #681 and #5 are on the issue',
    proof:{line:'1 part of "Done when" has no task', level:'warn', uncovered:['Answers from #681 and #5 are on the issue'], per_item:{}}};
  const links = nodesOf(line(t)).filter(n => n.tag === 'a').map(n => n.attrs.href);
  assert.deepEqual(links, ['https://github.com/o/r/issues/681', 'https://github.com/o/r/issues/5']);
  assert.equal(nodesOf(line({...t, refs:[]})).filter(n => n.tag === 'a').length, 0);
  const c = vm.createContext({h:(tag, attrs, ...ch) => ({tag, attrs, children:ch.flat(Infinity).filter(x => x != null)}), array:v => Array.isArray(v) ? v : [], clean:v => v, snapshot:false,
    tickets:() => [{refs:[{url:'https://github.com/x/y/pull/9'}]}]});
  vm.runInContext(src.slice(start, end), c);
  const other = c.linkRefs({id:'t_2'}, 'see #12, not a&#13; or x#14');
  assert.deepEqual(Array.from(other.filter(n => typeof n !== 'string'), n => n.attrs.href), ['https://github.com/x/y/issues/12'], 'another ticket here names the repository');
});
