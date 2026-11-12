const {test} = require('node:test');
const assert = require('node:assert/strict');
const H = require('../src/orch_focus/web/helpers.js');
test('plain file names and outcomes never use file sizes as labels', () => {
  assert.equal(H.plainFileName('/evidence/offsite-agenda_v2.html'), 'Offsite agenda v2');
  for (const size of ['109 B', '✓ 142 B', '1.2 KB', '193 bytes']) {
    assert.equal(H.outcome({done:true, evidence:[{type:'file', summary:size}]}), 'Completed.');
  }
  assert.equal(H.outcome({done:true, evidence:[{summary:'109 B', text:'Seats assigned.'}]}), 'Seats assigned.');
  assert.equal(H.outcome({done:true, evidence:[{type:'note', ref:'All rows matched.'}]}), 'All rows matched.');
});
test('stage tracks mid-work questions and prioritizes review and done', () => {
  const v = {ticket:{status:'open', questions:[], checklist:[]}, run:{}};
  assert.equal(H.phase(v),0);
  v.ticket.questions.push({answer:null}); assert.equal(H.phase(v),0);
  v.ticket.checklist.push({text:'Task'}); assert.equal(H.phase(v),1);
  v.ticket.status='review'; assert.equal(H.phase(v),2);
  v.ticket.status='done'; assert.equal(H.phase(v),3);
  v.ticket={started:true}; assert.equal(H.phase(v),1);
  v.ticket={}; v.run={running:true}; assert.equal(H.phase(v),1);
});
test('picker counts and done timestamps use real data', () => {
  assert.equal(H.attentionText([]), 'Nothing needs you right now.');
  assert.equal(H.attentionText([{status:'waiting',question_count:2},{status:'review'}]), 'One question and one result need your look.');
  assert.equal(H.completedAt({}),null);
  assert.equal(H.completedAt({history:[{text:'Status review -> done', at:'2026-11-08T09:12:00Z'}]}),'2026-11-08T09:12:00Z');
});
test('the picker line and the Needs you group count the same tickets, one per ticket', () => {
  const list = [{status:'waiting',question_count:2}, {status:'active',question_count:1}, {status:'waiting'}, {status:'done',question_count:1}, {status:'open'}];
  const needs = list.filter(H.needsYou);
  assert.equal(needs.length, 3);
  assert.equal(H.attentionText(list), 'Three questions need you.');
});
test('the hold reason is plain text while the run runs and gone when absent', () => {
  const why = "Waiting: the agent's window is scrolled up.";
  assert.equal(H.holdText({run:{running:true}, hold:why}), why);
  assert.equal(H.holdText({run:{running:true}, hold:''}), '');
  assert.equal(H.holdText({run:{running:true}}), '');
  assert.equal(H.holdText({run:{running:false}, hold:why}), '');
});
test('wont do outcome hides evidence and never describes active work', () => {
  assert.equal(H.outcome({wont_do:true, done:false, state:'doing', reason:'Later', evidence:[{text:'Old proof'}]}), "Won't do");
  assert.equal(H.outcome({wont_do:true, done:false}), "Won't do");
});
