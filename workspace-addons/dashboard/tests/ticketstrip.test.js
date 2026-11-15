'use strict';
// Owner feedback 14 Nov (sweep d-ticket-states, f-ticket-check): one header strip in every state, one word for the
// review state, "What the helper did", compact Done properties.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/ticket.js'), 'utf8');
const helpers = require('../src/orch_dashboard/web/helpers.js');
const kit = {}; vm.runInContext(fs.readFileSync(path.join(__dirname, '../../../workspace/src/orch_ui/static/date.js'), 'utf8'), vm.createContext({window:kit}));
const h = (tag, attrs = {}, ...children) => { const n = {tag, attrs, children:children.flat(Infinity).filter(x => x != null && x !== false)}; n.append = (...c) => n.children.push(...c); n.dataset = {}; n.setAttribute = () => {}; n.addEventListener = () => {}; n.classList = {add(){}, remove(){}}; return n; };
const nodes = n => n && typeof n === 'object' ? [n, ...(n.children || []).flatMap(nodes)] : [];
const text = n => !n ? '' : typeof n === 'string' ? n : (n.children || []).map(text).join('');
function ctx(extra = {}) {
  const c = {window:{DashHelpers:helpers, orch:{}, UI:{...kit.UI, statusIcon:name => h('svg', {className:'st ' + name})}}, document:{addEventListener(){}}, addEventListener(){}, h, locks:new Set(),
    array:v => Array.isArray(v) ? v : [], iconEl:n => n, clean:v => String(v ?? ''), name:v => String(v || '').replace(/^(human|agent):/, ''),
    el:(tag, cls, t) => h(tag, {className:cls}, t), fragment:(...children) => h('fragment', {}, children),
    card:(key, title, suffix, children) => h('section', {'data-key':key}, title, suffix, children), emptyRow:t => h('p', {}, t),
    questions:t => (t.questions || []).filter(q => q.answer == null), capitalise:v => v, date:v => String(v || ''), dueText:t => String(t.due || ''), time:v => kit.UI.stamp(v), ticketTabs:new Map(), addons:() => [], tickets:() => [], ticketOf:() => null,
    statusChip:() => h('span', {}, 'x'), chip:t => h('span', {}, t), href:id => '#ticket/' + id, MOVE_CHOICES:[], moveTicket(){}, button:label => h('button', {}, label), loadArtifacts(){}, ticketArtifactPreview:() => null, agentBar:() => null,
    surface:v => v, inlineField:(t, f) => h('span', {}, String(t[f] ?? '')), ticketHistoryPanel:() => null, artifactsPanel:() => null, ticketParts:() => null, taskRows:() => null, addTaskRow:() => null, artifactCount:() => 0,
    linksCard:() => null, fieldSections:() => null, selectTicketTab(){}, ticketLinks:() => null, addonRows:() => null, mountQuestion(){}, state:{runs:{}}, snapshot:false, repeatsAddon:() => null, act:async () => ({ok:true}),
    fetch:() => new Promise(() => {}), ...extra};
  vm.createContext(c); vm.runInContext(source, c); return c;
}
const base = {id:'t_one', title:'Update the opening hours', owner:'human:Anna', created_at:'2026-11-02T08:15:00Z', updated_at:'2026-11-14T10:32:00Z', questions:[]};
const STATES = [
  ['todo', {status:'open'}, {}, /Not started/],
  ['working', {status:'active', sessions:[{id:'s'}]}, {runs:{t_one:{running:true}}}, /Helper is working/],
  ['needs', {status:'waiting', questions:[{id:'q1', text:'Which opening time on Saturday?'}]}, {}, /Helper asks: Which opening time on Saturday\?/],
  ['check', {status:'review'}, {}, /Helper finished/],
  ['done', {status:'done', done_at:'2026-11-14T11:05:00Z', history:[{at:'2026-11-14T11:05:00Z', by:'human:Severin', text:'Status review -> done'}], checklist:[{id:'c1', text:'Read the page', done:true}, {id:'c2', text:'Changed 3 lines', done:true}, {id:'c3', text:'Skipped bit', wont_do:true}]}, {}, /Done .*checked by Severin/],
];
for (const [pill, patch, run, sentence] of STATES) {
  test('header strip, state ' + pill + ': one pill, one sentence, no stepper', () => {
    const c = ctx({state:{runs:run.runs || {}}});
    const tree = c.detail({...base, ...patch});
    const strip = nodes(tree).find(n => /(^| )strip( |$)/.test(n.attrs.className || ''));
    assert.ok(strip, 'a header strip');
    assert.equal(nodes(strip).filter(n => /(^| )pill( |$)/.test(n.attrs.className || '')).length, 1);
    assert.ok(nodes(strip).some(n => new RegExp('(^| )pill (.* )?' + pill + '( |$)').test(n.attrs.className || '')), 'pill ' + pill);
    assert.match(text(strip), sentence);
    const all = JSON.stringify(tree);
    assert.doesNotMatch(all, /stepper|Ticket progress/);
    assert.doesNotMatch(all, /Your helper (is|asks|finished|paused)/, 'the actor is just "Helper"');
    assert.ok(nodes(strip).filter(n => n.tag === 'button' && /(^| )primary( |$)/.test(n.attrs.className || '')).length <= 1, 'one main action');
  });
}
test('Check: Looks good + Send back in the strip, no "Ask for changes" anywhere; Result card has the preview', () => {
  const c = ctx();
  const tree = c.detail({...base, status:'review', summary:'Hours now read 08:00-18:00.'});
  const strip = nodes(tree).find(n => /(^| )strip( |$)/.test(n.attrs.className || ''));
  const labels = nodes(strip).filter(n => n.tag === 'button').map(text);
  assert.ok(labels.includes('Looks good') && labels.includes('Send back'));
  assert.doesNotMatch(JSON.stringify(tree), /Ask for changes|Your review/);
  const result = nodes(tree).find(n => /review-card/.test(n.attrs.className || ''));
  assert.match(text(result), /Result/);
  assert.match(text(result), /In short/);
  assert.equal(nodes(result).filter(n => n.tag === 'button' && /Looks good|Send back/.test(text(n))).length, 0, 'verdict buttons live in the strip only');
});
test('Start, Answer, Stop and Reopen are the main actions of their states', () => {
  const c = ctx({state:{runs:{t_one:{running:true}}}});
  const label = (patch, st) => { const cc = st ? ctx({state:st}) : ctx(); const strip = nodes(cc.detail({...base, ...patch})).find(n => /(^| )strip( |$)/.test(n.attrs.className || '')); return nodes(strip).filter(n => n.tag === 'button').map(text); };
  assert.ok(label({status:'open'}).includes('Start helper'));
  assert.ok(label({status:'waiting', questions:[{id:'q', text:'?'}]}).includes('Answer'));
  assert.ok(label({status:'done'}).includes('Reopen'));
  assert.ok(c.detail);
});
test('Done: "What the helper did" lists the finished tasks; Properties are compact', () => {
  const c = ctx();
  const done = STATES[4][1];
  const tree = c.detail({...base, ...done, done_when:'The website shows the new hours.'});
  const did = nodes(tree).find(n => /helper-did/.test(n.attrs.className || ''));
  assert.ok(did, 'a "What the helper did" card');
  assert.match(text(did), /What the helper did/);
  assert.match(text(did), /Read the page/);
  assert.match(text(did), /Changed 3 lines/);
  assert.doesNotMatch(text(did), /Skipped bit/);
  const props = nodes(tree).find(n => n.tag === 'aside' && /properties/.test(n.attrs.className || ''));
  assert.match(text(props), /Finished/);
  assert.doesNotMatch(text(props), /What happens next|Updated/);
});

test('G2: a quiet ticket shows one line, "No news since" replaces "Updated"', () => {
  const c = ctx({state:{runs:{}}, now:() => new Date('2026-11-14T18:00:00Z')});
  const tree = c.detail({...base, status:'active', quiet_since:'2026-11-14T10:32:00Z'});
  const sentence = nodes(tree).find(n => n.attrs?.['data-key'] === 'ticket-sentence');
  assert.match(text(sentence), /^No news since .+\.$/);
  assert.doesNotMatch(text(sentence), /Updated/);
});
