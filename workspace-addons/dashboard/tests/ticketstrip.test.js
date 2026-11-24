'use strict';
// Owner feedback 14 Nov (sweep d-ticket-states, f-ticket-check): one header strip in every state, one word for the
// review state, "What the helper did", compact Done properties.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/ticket.js'), 'utf8');
const startSource = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/start.js'), 'utf8');  // the one Start button (ORCH-475)
const helpers = require('../src/orch_dashboard/web/helpers.js');
const kit = {}; vm.runInContext(fs.readFileSync(path.join(__dirname, '../../../workspace/src/orch_ui/static/date.js'), 'utf8'), vm.createContext({window:kit}));
const h = (tag, attrs = {}, ...children) => { const n = {tag, attrs, children:children.flat(Infinity).filter(x => x != null && x !== false)}; n.append = (...c) => n.children.push(...c); n.dataset = {}; n.setAttribute = () => {}; n.addEventListener = () => {}; n.classList = {add(){}, remove(){}}; return n; };
const nodes = n => n && typeof n === 'object' ? [n, ...(n.children || []).flatMap(nodes)] : [];
const text = n => !n ? '' : typeof n === 'string' ? n : (n.children || []).map(text).join('');
function ctx(extra = {}) {
  const c = {window:{DashHelpers:helpers, orch:{}, UI:{...kit.UI, ...require('./kit_state.js'), statusIcon:name => h('svg', {className:'st ' + name})}}, document:{addEventListener(){}}, addEventListener(){}, h, locks:new Set(),
    array:v => Array.isArray(v) ? v : [], iconEl:n => n, clean:v => String(v ?? ''), name:v => String(v || '').replace(/^(human|agent):/, ''),
    el:(tag, cls, t) => h(tag, {className:cls}, t), fragment:(...children) => h('fragment', {}, children),
    card:(key, title, suffix, children) => h('section', {'data-key':key}, title, suffix, children), emptyRow:t => h('p', {}, t),
    questions:t => (t.questions || []).filter(q => q.answer == null), capitalise:v => v, date:v => String(v || ''), dueText:t => String(t.due || ''), time:v => kit.UI.stamp(v), ticketTabs:new Map(), addons:() => [], tickets:() => [], ticketOf:() => null,
    statusChip:() => h('span', {}, 'x'), chip:t => h('span', {}, t), href:id => '#ticket/' + id, MOVE_CHOICES:[], moveTicket(){}, button:label => h('button', {}, label), loadArtifacts(){}, ticketArtifactPreview:() => null, agentBar:() => null,
    surface:v => v, inlineField:(t, f) => h('span', {}, String(t[f] ?? '')), ticketHistoryPanel:() => null, artifactsPanel:() => null, ticketParts:() => null, taskRows:() => null, addTaskRow:() => null, artifactCount:() => 0,
    linksCard:() => null, fieldSections:() => null, selectTicketTab(){}, ticketLinks:() => null, addonRows:() => null, mountQuestion(){}, state:{runs:{}}, snapshot:false, repeatsAddon:() => null, act:async () => ({ok:true}),
    fetch:() => new Promise(() => {}), ...extra};
  vm.createContext(c); vm.runInContext(source, c); vm.runInContext(startSource, c); return c;
}
const base = {id:'t_one', title:'Update the opening hours', owner:'human:Anna', created_at:'2026-11-02T08:15:00Z', updated_at:'2026-11-14T10:32:00Z', questions:[]};
const STATES = [
  ['todo', {status:'open'}, {}, /Not started/],
  ['working', {status:'active', sessions:[{id:'s'}]}, {runs:{t_one:{running:true}}}, /Working/],
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
  assert.doesNotMatch(text(props), /What happens next|Updated/);
  // ORCH-581: created and finished are one quiet line at the foot of the rail
  const stamp = nodes(tree).find(n => /^ticket-stamp-/.test(n.attrs?.['data-key'] || ''));
  assert.match(text(stamp), /finished/);
  assert.doesNotMatch(text(stamp), /updated/);
});

test('G2: a quiet ticket shows one line, "Quiet since" replaces "Updated"', () => {
  const c = ctx({state:{runs:{}}, now:() => new Date('2026-11-14T18:00:00Z')});
  const tree = c.detail({...base, status:'active', quiet_since:'2026-11-14T10:32:00Z'});
  const sentence = nodes(tree).find(n => n.attrs?.['data-key'] === 'ticket-sentence');
  assert.match(text(sentence), /^Quiet since .+\.$/);
  assert.doesNotMatch(text(sentence), /Updated/);
});

test('ORCH-415: In progress with no helper says so in the pill and the line; the start is outlined with its cost; one start button (ORCH-1466)', () => {
  const c = ctx({state:{runs:{}}});
  const tree = c.detail({...base, status:'active', model:{name:'opus', by:'orch'}, estimate:{minutes:30, cost:1.2}});
  const all = nodes(tree), sentence = all.find(n => n.attrs?.['data-key'] === 'ticket-sentence');
  assert.equal(text(sentence), 'No helper is working on it right now.');
  assert.match(text(all.find(n => /^status-/.test(n.attrs?.['data-key'] || ''))), /In progress/);
  const go = nodes(all.find(n => n.attrs?.['data-key'] === 'ticket-start')).find(n => n.attrs?.['data-start'] === 'main');
  assert.match(go.attrs.className, /\boutline\b/);
  // the cheaper model is picked in the Start choice behind the caret, never a second start button beside it
  assert.ok(!all.find(n => n.attrs?.['data-key'] === 'ticket-start-cheaper'));
  const again = nodes(c.detail({...base, status:'active', sessions:[{id:'s1'}], model:{name:'opus', by:'orch'}}));
  assert.ok(!again.some(n => n.tag === 'button' && /on Sonnet/.test(text(n))), 'no Continue on Sonnet');
  assert.equal(text(all.find(n => n.attrs?.['data-key'] === 'ticket-start-cost')), 'On Opus · estimate about $1.20');
  assert.ok(!all.some(n => n.tag === 'button' && /\bprimary\b/.test(n.attrs?.className || '') && /Continue|Start|Resume/.test(text(n))), 'no filled start');
});

test('ORCH-415: a helper that may be stuck never reads "No helper"; no plain start beside Start anyway', () => {
  const c = ctx({state:{runs:{t_one:{running:false, state:'maybe-stale', claim:{agent:'claude'}}}}});
  const all = nodes(c.detail({...base, status:'active', model:{name:'opus', by:'orch'}}));
  assert.doesNotMatch(text(all.find(n => n.attrs?.['data-key'] === 'ticket-sentence')), /No helper/);
  assert.ok(!all.find(n => n.attrs?.['data-key'] === 'ticket-start'), 'no plain Continue while it may be stuck');
});

test('ORCH-415: next to Reopen the Continue is plain, with no cost line or cheaper choice; Sonnet has no cheaper choice', () => {
  const c = ctx({state:{runs:{}}});
  const done = nodes(c.detail({...base, status:'done', model:{name:'opus', by:'orch'}}));
  assert.ok(done.find(n => n.attrs?.['data-key'] === 'ticket-start'));
  assert.ok(!done.find(n => n.attrs?.['data-key'] === 'ticket-start-cheaper'));
  assert.ok(!done.find(n => n.attrs?.['data-key'] === 'ticket-start-cost'));
  const sonnet = nodes(c.detail({...base, status:'active', model:{name:'sonnet', by:'orch'}}));
  assert.ok(sonnet.find(n => n.attrs?.['data-key'] === 'ticket-start-cost'));
  assert.ok(!sonnet.find(n => n.attrs?.['data-key'] === 'ticket-start-cheaper'));
});

test('ORCH-415: the cost line is read with the start choice for screen readers', () => {
  const c = ctx({state:{runs:{}}});
  const all = nodes(c.detail({...base, status:'active', model:{name:'opus', by:'orch'}}));
  const cost = all.find(n => n.attrs?.['data-key'] === 'ticket-start-cost');
  const pick = all.find(n => n.attrs?.['data-key'] === 'ticket-start-pick');
  assert.equal(pick.attrs.role, 'group');
  assert.equal(pick.children[0], cost, 'the cost line comes first in the group');
});

test('Needs you: the strip names the agent that asked (as Home does), not always "Helper" (ORCH-65)', () => {
  const c = ctx({state:{runs:{t_one:{claim:{agent:'manager', label:'Manager'}}}}});
  const tree = c.detail({...base, status:'waiting', questions:[{id:'q1', text:'Build the new card look?'}]});
  const strip = nodes(tree).find(n => /(^| )strip( |$)/.test(n.attrs.className || ''));
  assert.match(text(strip), /Manager asks: Build the new card look\?/);
  assert.doesNotMatch(text(strip), /Helper asks/);
});
// ORCH-235 (bug hunt 17 Nov): one word per state, a move by a person never says a helper ran, an epic offers Done.
const stripOf = (c, t) => nodes(c.detail({...base, ...t})).find(n => /(^| )strip( |$)/.test(n.attrs.className || ''));
test('a wait for a date reads Waiting with its date and reason, never Needs you', () => {
  const c = ctx();
  const strip = stripOf(c, {status:'waiting', waiting_on:{kind:'time', until:'2030-01-07T08:00:00Z', ref:'The price list'}});
  assert.ok(nodes(strip).some(n => /(^| )pill (.* )?todo( |$)/.test(n.attrs.className || '')));
  assert.match(text(strip), /Waiting/);
  assert.match(text(strip), /Waits until .*2030.* · The price list\./);
  assert.doesNotMatch(text(strip), /Needs you/);
  const none = stripOf(c, {status:'waiting', waiting_on:null});
  assert.match(text(none), /Waiting, with no date or reason given\./);
  const asks = stripOf(c, {status:'waiting', waiting_on:{kind:'question', ref:'q1'}, questions:[{id:'q1', text:'Which day?'}]});
  assert.match(text(asks), /Needs you/);
});
test('a ticket a person moved to Check says who moved it, not that a helper finished', () => {
  const c = ctx();
  const byHand = stripOf(c, {status:'review', history:[{at:'2026-11-17T12:59:00Z', by:'human:Anna', text:'Patched status (status ready -> review)'}]});
  assert.match(text(byHand), /Moved to Check by Anna/);
  assert.doesNotMatch(text(byHand), /Helper finished/);
  const byHelper = stripOf(c, {status:'review', history:[{at:'2026-11-17T12:59:00Z', by:'agent:claude', text:'Status active -> review'}]});
  assert.match(text(byHelper), /Helper finished/);
});
test('an epic whose sub-tickets are all done offers Mark Done; with one open it does not', () => {
  const kids = s => [{id:'t_k1', parent:'t_one', status:'done', title:'A'}, {id:'t_k2', parent:'t_one', status:s, title:'B'}];
  let moved = null;
  const c = ctx({tickets:() => kids('done'), moveTicket:(id, status) => { moved = [id, status]; }});
  const strip = stripOf(c, {status:'ready', epic:true, sessions:[{id:'s'}]});
  assert.match(text(strip), /All 2 sub-tickets are done/);
  const mark = nodes(strip).find(n => n.tag === 'button' && text(n) === 'Mark Done');
  assert.ok(mark, 'a Mark Done button'); mark.onclick();
  assert.deepEqual(moved, ['t_one', 'done']);
  const open = stripOf(ctx({tickets:() => kids('active')}), {status:'ready', epic:true, sessions:[{id:'s'}]});
  assert.ok(!nodes(open).some(n => n.tag === 'button' && text(n) === 'Mark Done'));
});
test('Reopen puts a Done ticket back in To do, not Working', () => {
  let moved = null;
  const c = ctx({moveTicket:(id, status) => { moved = status; }});
  nodes(stripOf(c, {status:'done'})).find(n => n.tag === 'button' && text(n) === 'Reopen').onclick();
  assert.equal(moved, 'ready');
});
test('the ticket page menu offers Waiting and Superseded and leaves out the lane it is in', () => {
  const c = ctx({MOVE_CHOICES:helpers.MOVE_CHOICES});
  const keys = nodes(c.detail({...base, status:'ready'})).map(n => n.attrs['data-key']).filter(k => /^ticket-move-/.test(k || ''));
  assert.deepEqual(keys, ['open', 'active', 'blocked', 'review', 'done', 'dropped', 'superseded'].map(l => 'ticket-move-' + l));
});
test('waitWords: a date with a reason, another ticket, the outside, nothing', () => {
  const w = (waiting_on, all) => helpers.waitWords({waiting_on}, all || [], v => 'at ' + v);
  assert.equal(w({kind:'time', until:'X', ref:'The price list'}), 'Waits until at X · The price list');
  assert.equal(w({kind:'time', until:'X'}), 'Waits until at X');
  assert.equal(w({kind:'ticket', ref:'t_abc123'}, [{id:'t_abc123', key:'DM-4'}]), 'Waits for DM-4');
  assert.equal(w({kind:'external', ref:'the supplier'}), 'Waits: the supplier');
  assert.equal(w(null), '');
});
test('ORCH-255/475: a start (Continue, or Start helper with no earlier session) is on the ticket page in every state while no helper runs', () => {
  const label = (patch, st) => { const cc = st ? ctx({state:st}) : ctx(); const strip = nodes(cc.detail({...base, ...patch})).find(n => /(^| )strip( |$)/.test(n.attrs.className || '')); return nodes(strip).filter(n => n.tag === 'button').map(text); };
  // ORCH-483 (owner): with no earlier session there is nothing to continue, so the one Start button says Start helper
  assert.ok(label({status:'waiting', questions:[{id:'q', text:'?'}]}).includes('Start helper'), 'Needs you');
  assert.ok(label({status:'review', sessions:[{id:'s'}]}).includes('Continue'), 'Check');
  assert.ok(label({status:'done', sessions:[{id:'s'}]}).includes('Continue'), 'Done');
  assert.ok(label({status:'waiting', sessions:[{id:'s'}], waiting_on:{kind:'time', until:'2030-01-07T08:00:00Z'}}).includes('Continue'), 'Waiting on a time (ORCH-435)');
  assert.ok(label({status:'waiting', sessions:[{id:'s'}], waiting_on:null}).includes('Continue'), 'Waiting on nothing (ORCH-435)');
  assert.ok(label({status:'active', sessions:[{id:'s'}]}).includes('Continue'), 'active, helper not running');
  const todo = label({status:'open'});
  assert.ok(todo.includes('Start helper') && !todo.includes('Continue'), 'To do keeps Start helper only');
  assert.ok(!label({status:'active', sessions:[{id:'s'}]}, {runs:{t_one:{running:true}}}).includes('Continue'), 'no Continue while a helper runs');
});
test('ORCH-255: a passed wake time on Home has a Continue button, not a command', () => {
  assert.deepEqual(helpers.needAction({kind:'overdue-wait', ticket:'t_one', tone:'warn'}), {label:'Continue', kind:'run'});
  assert.equal(helpers.needAction({kind:'overdue-wait'}).label, 'Open');
});
// ORCH-742 (look B): Prepare on a saved ticket: the sentence, the Prepared word, What I found folded, Could not open.
const sentenceOf = tree => nodes(tree).find(n => n.attrs['data-key'] === 'ticket-sentence');
test('Prepare: Preparing line with Start still there, not the live Working header', () => {
  const c = ctx({state:{runs:{t_one:{running:true, alive:true, claim:{mode:'live', prepare:true}}}}});
  const tree = c.detail({...base, status:'open', sessions:[{id:'s'}], prepare:{state:'preparing', at:'2026-11-19T09:40:00Z'}});
  const s = sentenceOf(tree);
  assert.equal(text(s), 'Preparing: reading the links and filling in the ticket.');
  assert.ok(nodes(s).some(n => n.attrs.className === 'spinner'));
  assert.ok(!nodes(nodes(tree).find(n => /(^| )strip( |$)/.test(n.attrs.className || ""))).some(n => n.attrs['data-key'] === 'ticket-kicker'), 'no Working header while it prepares');
  assert.ok(nodes(tree).some(n => n.attrs['data-key'] === 'ticket-start'), 'Start stays');
});
test('Prepare: Prepared mark, Not prepared yet, In line; none of it once the ticket left Backlog', () => {
  const c = ctx();
  const prepared = sentenceOf(c.detail({...base, status:'open', sessions:[{id:'s'}], prepare:{state:'prepared', at:'2026-11-19T09:41:00Z'}}));
  assert.match(text(prepared), /^☰ Prepared .+\. Press Continue to begin\.$/, 'the sentence names the button: Continue after an earlier session (ORCH-1696)');
  assert.equal(nodes(prepared).find(n => n.attrs['data-key'] === 'prepared-mark').attrs.title, 'Described by the helper, not checked');
  assert.equal(text(sentenceOf(c.detail({...base, status:'open', prepare:{state:'not_prepared', at:'x'}}))), 'Not prepared yet. Start still works.');
  assert.equal(text(sentenceOf(c.detail({...base, status:'open', prepare:{state:'waiting', at:'x'}}))), 'In line to be prepared. Start still works.');
  assert.doesNotMatch(text(sentenceOf(c.detail({...base, status:'review', prepare:{state:'prepared', at:'x'}}))), /Prepared/);
  assert.match(text(sentenceOf(c.detail({...base, status:'open', prepare:{state:'odd'}}))), /Not started/);
});
test('What I found: folded line with counts, sources with web links only, Could not open in sight with one action', () => {
  const c = ctx();
  const found = {sources:[{name:'MKT-214 Spring newsletter', link:'https://acme.example/browse/MKT-214', opened:true, lines:'One mail with the garden range.'},
    {name:'Old notes', link:'javascript:alert(1)', opened:true, lines:'Same list.'},
    {name:'Email from Anna', opened:false, why:'No mail connection is set up.'}], facts:['For 1,400 shop customers'], at:'2026-11-19T09:41:00Z'};
  const tree = c.detail({...base, status:'open', description:'Spring newsletter', found});
  const fold = nodes(tree).find(n => n.attrs['data-key'] === 'found');
  assert.equal(fold.tag, 'details');
  assert.equal(fold.attrs.open, undefined, 'folded at first');
  const summary = text(fold.children[0]);
  assert.match(summary, /What I found2 sources read! 1 could not be opened/);
  const links = nodes(fold).filter(n => n.tag === 'a').map(n => n.attrs.href);
  assert.deepEqual(links, ['https://acme.example/browse/MKT-214']);
  const closed = nodes(tree).find(n => n.attrs['data-key'] === 'found-closed');
  assert.match(text(closed), /Email from Anna.*Attach it.*No mail connection/);
  assert.ok(!nodes(fold).some(n => n.attrs['data-key'] === 'found-closed'), 'Could not open is outside the fold');
  assert.equal(nodes(c.detail({...base, status:'open', found:{sources:[], facts:[]}})).find(n => n.attrs['data-key'] === 'found'), undefined);
});

test('one start button (ORCH-1466): with Focus on, Open in Focus is in the ⋯ menu, never a second start in the header', () => {
  const focus = t => h('button', {'data-key':'live-session-btn'}, 'Start in Focus');
  const all = nodes(ctx({state:{runs:{}}, liveFocusButton:focus, liveLayerName:() => 'Focus'}).detail({...base, status:'active', model:{name:'opus', by:'orch'}}));
  const actions = all.find(n => /ticket-strip-actions/.test(n.attrs?.className || ''));
  assert.ok(!nodes(actions).some(n => n.attrs?.['data-key'] === 'live-session-btn'), 'no Start in Focus beside the start');
  assert.equal(nodes(actions).filter(n => n.attrs?.['data-start'] === 'main').length, 1, 'one start button');
  const menu = all.find(n => n.attrs?.['data-key'] === 'ticket-menu-t_one');
  assert.equal(text(nodes(menu).find(n => n.attrs?.['data-key'] === 'ticket-open-layer')), 'Open in Focus');
  const off = nodes(ctx({state:{runs:{}}}).detail({...base, status:'active'}));
  assert.ok(!off.find(n => n.attrs?.['data-key'] === 'ticket-open-layer'), 'no Focus item while Focus is off');
});

// ORCH-1696: the sentence names the Start button it means, and one status word per state (as the tickets list says)
test('Sent back and paused: the sentence says the button\'s word, the pill says Changes asked / Paused', () => {
  const c = ctx();
  const stripOf = patch => nodes(c.detail({...base, ...patch})).find(n => /(^| )strip( |$)/.test(n.attrs.className || ''));
  const pillOf = strip => text(nodes(strip).find(n => /^status-/.test(n.attrs?.['data-key'] || '')));
  const back = stripOf({status:'ready', sessions:[{id:'s'}], checklist:[{id:'c1', text:'Use the new logo', origin:'change_request'}]});
  assert.match(text(nodes(back).find(n => n.attrs?.['data-key'] === 'ticket-sentence')), /press Continue to begin now\.$/);
  assert.ok(nodes(back).some(n => n.tag === 'button' && text(n) === 'Continue'));
  assert.equal(pillOf(back), 'Changes asked');
  const paused = stripOf({status:'ready', sessions:[{id:'s'}]});
  assert.equal(pillOf(paused), 'Paused');
  const fresh = stripOf({status:'open'});
  assert.equal(text(nodes(fresh).find(n => n.attrs?.['data-key'] === 'ticket-sentence')), 'Not started. Your helper begins when you press Start helper.');
  assert.equal(pillOf(fresh), 'Backlog');
});
test('Done when: a long one is cut to three lines with Show more, and stays editable (ORCH-1696)', () => {
  const seen = [];
  const c = ctx();
  c.window.UI.moreText = (t, o) => { seen.push(t); return h('div', {className:'more-text clamped'}, o.node, h('button', {}, 'Show more')); };
  const long = Array.from({length:20}, (_, i) => 'Line ' + (i + 1)).join('\n');
  const row = nodes(c.detail({...base, status:'open', done_when:long})).find(n => n.attrs?.['data-key'] === 'prop-done-when-t_one');
  assert.deepEqual(seen, [long]);
  assert.ok(nodes(row).some(n => /more-text/.test(n.attrs?.className || '')));
  assert.ok(nodes(row).some(n => n.attrs?.['data-key'] === 'inline-done_when-t_one' || /inline/.test(n.attrs?.className || '')), 'the editable field is inside');
});
