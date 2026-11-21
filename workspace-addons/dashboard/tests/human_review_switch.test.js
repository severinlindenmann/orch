'use strict';
// ORCH-424: every ticket page shows a Human review needed switch in Properties. It is on unless the person turned it
// off (no field = on, also for tickets made before the switch), and one click changes it.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const ticketSrc = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/ticket.js'), 'utf8');

function load(snapshot) {
  const body = ticketSrc.match(/function humanReviewField\(t\) \{[\s\S]*?\n\}/)[0];
  const calls = [], toasts = [];
  const h = (tag, attrs = {}, ...kids) => ({tag, attrs, children:kids.flat(), disabled:false, setAttribute(k, v) { this.attrs[k] = v; }});
  const ctx = {
    snapshot, calls, toasts, h,
    el: (tag, cls, text) => ({tag, className:cls, textContent:text}),
    ticketOf: () => ({revision:7}),
    changeError: r => r.text,
    act: async (op, args) => { calls.push({op, args}); return ctx.answer; },
    answer: {ok:true},
    window: {orch: {toast: (text, kind) => toasts.push([text, kind])}},
  };
  vm.createContext(ctx);
  vm.runInContext(body + '\nthis.humanReviewField = humanReviewField;', ctx);
  return ctx;
}

test('Properties lists the switch right after Release', () => {
  // ORCH-581: Properties shows only what is set, but this safety switch always shows, right after Release
  assert.match(ticketSrc, /field\('Release', releaseField\(t\), 'release'\) : null,\s+field\('Human review needed', humanReviewField\(t\)\),/);
});

test('on by default, also for an older ticket without the field', () => {
  const ctx = load(false);
  const sw = ctx.humanReviewField({id:'t_abcdef'});
  assert.equal(sw.attrs.role, 'switch');
  assert.equal(sw.attrs['aria-checked'], 'true');
  assert.equal(sw.attrs['aria-label'], 'Human review needed');
  assert.equal(ctx.humanReviewField({id:'t_abcdef', human_review:false}).attrs['aria-checked'], 'false');
});

test('a click turns it off with the latest revision; a refusal puts it back', async () => {
  const ctx = load(false);
  const sw = ctx.humanReviewField({id:'t_abcdef'});
  await sw.onclick();
  assert.deepEqual(JSON.parse(JSON.stringify(ctx.calls)), [{op:'ticket.edit', args:{ticket:'t_abcdef', human_review:false, if_revision:7}}]);
  assert.equal(sw.attrs['aria-checked'], 'false');
  ctx.answer = {ok:false, text:'Only a person turns Human review needed off'};
  const again = ctx.humanReviewField({id:'t_abcdef'});
  await again.onclick();
  assert.equal(again.attrs['aria-checked'], 'true');
  assert.equal(ctx.toasts[0][1], 'error');
});

test('a read-only copy shows the words, no switch', () => {
  const ctx = load(true);
  assert.equal(ctx.humanReviewField({id:'t_abcdef'}).textContent, 'Yes, nothing is accepted without you');
  assert.equal(ctx.humanReviewField({id:'t_abcdef', human_review:false}).textContent, 'No');
});
