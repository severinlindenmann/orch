'use strict';
// The Review page of the dashboard: state.review in, one signed click out (review.answer), files through /api/file,
// the "All cards" list, "Review all" on Home and the card answers on a ticket. The kit's UI.reviewPage has its own tests.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const WEB = path.join(__dirname, '../src/orch_dashboard/web');
const read = f => fs.readFileSync(path.join(WEB, f), 'utf8');
const helpers = require(path.join(WEB, 'helpers.js'));
const kit = {}; vm.runInContext(fs.readFileSync(path.join(__dirname, '../../../workspace/src/orch_ui/static/date.js'), 'utf8'), vm.createContext({window:kit}));
const h = (tag, attrs = {}, ...children) => { const n = {tag, attrs, children:children.flat(Infinity).filter(x => x != null && x !== false), dataset:{}, classList:{add(){}, remove(){}}}; n.append = (...c) => n.children.push(...c); n.setAttribute = (k, v) => { n.attrs[k] = v; }; n.addEventListener = () => {}; return n; };
const nodes = n => n && typeof n === 'object' ? [n, ...(n.children || []).flatMap(nodes)] : [];
const text = n => !n ? '' : typeof n === 'string' ? n : (n.children || []).map(text).join('');
const ID = 'a'.repeat(64);
const CARD = {id:'core:q:t_abcdef:q3', ticket:'t_abcdef', ticket_key:'DT-41', key:'q3', kind:'draft', card:{kind:'draft', title:'Home block'}, digest:ID, since:'2026-11-15T09:00:00Z'};
function ctx(state, extra = {}) {
  const acts = [];
  const c = {h, window:{DashHelpers:helpers, UI:kit.UI, orch:{toast(){}}}, document:{addEventListener(){}, getElementById:() => null}, addEventListener(){}, locks:new Set(), localStorage:{getItem:() => null, setItem(){}}, setTimeout, clearTimeout,
    name:v => String(v || '').replace(/^(human|agent):/, ''), capitalise:v => v, iconEl:n => n, card:(key, title, suffix, kids) => h('section', {'data-key':key}, title, suffix, kids), emptyRow:t => h('p', {}, t), button:(label, cls, fn) => h('button', {className:'btn ' + cls}, label), render(){}, time:v => kit.UI.stamp(v), parse:v => new Date(v), now:() => new Date('2026-11-15T12:00:00Z'), array:v => Array.isArray(v) ? v : [], clean:String, state, mounts:new Map(), snapshot:false,
    fragment:(...k) => h('fragment', {}, k), heading:(t, s) => h('header', {}, t, s), el:(tag, cls, t) => h(tag, {className:cls}, t),
    act:async (op, args) => { acts.push([op, args]); return {ok:true, status:200}; }, ...extra};
  c.acts = acts; vm.createContext(c); vm.runInContext(read('pages/review.js'), c); return c;
}
test('the page reads cards and decisions from state.review and counts the cards', () => {
  const c = ctx({workspace:'Demo', review:{cards:[CARD, {...CARD, id:'core:review:t_abcdef', key:'review'}], answered:[{id:'x'}]}});
  assert.equal(c.reviewCount(), 2);
  assert.match(c.reviewSubtitle(), /^2 things need you\.( .*)?$/);
  const api = c.reviewApi();
  return Promise.all([api.stack(), api.answered()]).then(([s, a]) => { assert.equal(s.length, 2); assert.equal(a.length, 1); assert.equal(api.workspace, 'Demo'); });
});
test('one card and none: plain words', () => {
  assert.match(ctx({review:{cards:[CARD]}}).reviewSubtitle(), /^1 thing needs you\./);
  assert.equal(ctx({}).reviewSubtitle(), 'Nothing waits for you.');
  assert.equal(ctx({}).reviewCount(), 0);
});
test('fileUrl serves only reviewed/<sha12>/<name> through /api/file', () => {
  const f = ctx({}).reviewApi().fileUrl;
  assert.equal(f(CARD, 'reviewed/0123456789ab/after.png'), '/api/file?t=t_abcdef&k=reviewed&n=0123456789ab%2Fafter.png');
  for (const bad of ['reviewed/0123456789ab/../x.png', 'reviewed/0123456789ab/a/b.png', 'reviewed/XYZ/x.png', '', null, 'https://evil/x.png', 'artifacts/../x.png', 'evidence/a/../../x.png', 'evidence/.orch/x.png', 'secrets/x.png', 'evidence/a\\b.png']) assert.equal(f(CARD, bad), '', String(bad));
  assert.equal(f({}, 'reviewed/0123456789ab/after.png'), '');
});
test('a Test results card opens its own files: pictures and PDFs through /api/file, a page only in its /view frame (ORCH-183)', () => {
  const f = ctx({}).reviewApi().fileUrl;
  assert.equal(f(CARD, 'evidence/shop photo.png'), '/api/file?t=t_abcdef&k=evidence&n=shop%20photo.png');
  assert.equal(f(CARD, 'artifacts/out/poster.pdf'), '/api/file?t=t_abcdef&k=artifacts&n=out%2Fposter.pdf');
  assert.equal(f(CARD, 'evidence/result.html'), '/view/t_abcdef/evidence/result.html');
  assert.equal(f(CARD, 'artifacts/site/index.HTM'), '/view/t_abcdef/artifacts/site/index.HTM');
});
test('a Factory proposal on Review reads like Home: its title as the question, goal and time in short lines (ORCH-183)', async () => {
  const text = "Start 'Loyalty card for regular customers'? ~1 h 30 min · you're needed for ~10 min. Goal: Regular customers collect stamps. Done means: The card design is ready. Stops: ship. Cap: 2 h active. Crew: manager claude.";
  const plain = {...CARD, id:'core:q:t_abcdef:q4', key:'q4', text, options:['Start', 'Edit', 'Not now'], card:{kind:'choice', title:text, preview:{type:'options', options:[{id:'Start', title:'Start'}]}}};
  const [fac, other] = await ctx({review:{cards:[plain, CARD]}}).reviewApi().stack();
  assert.equal(fac.card.title, "Start 'Loyalty card for regular customers'?");
  assert.equal(fac.text, 'Regular customers collect stamps.\n' + helpers.factoryStart(text).meta, 'the goal, then the same time line as Home');
  assert.doesNotMatch(fac.text, /Crew|Stops/);
  assert.equal(JSON.stringify(fac.answers), JSON.stringify([{label:'Not now', picked:'Not now'}, {label:'Change it', picked:'Edit'}, {label:'Start', picked:'Start'}]), "Home's buttons, Start last (owner choice B)");
  assert.equal(fac.card.preview, undefined, 'no second list of the same answers on the card');
  assert.equal(plain.card.preview.type, 'options', 'the state itself is not changed');
  assert.equal(fac.digest, plain.digest, 'the answer still names what was asked');
  assert.equal(other, CARD, 'any other card as it is');
});
test('an answer is one review.answer click: question card, check card, picked and note', async () => {
  const c = ctx({});
  const api = c.reviewApi();
  assert.deepEqual({...await api.answer({id:'core:q:t_abcdef:q3', digest:ID, verdict:'talk', picked:'C', note:{text:'x', pins:[]}})}, {ok:true});
  assert.deepEqual(JSON.parse(JSON.stringify(c.acts[0])), ['review.answer', {ticket:'t_abcdef', key:'q3', verdict:'talk', digest:ID, picked:'C', note:{text:'x', pins:[]}}]);
  await api.answer({id:'core:review:t_abcdef', digest:ID, verdict:'ok', picked:null, note:null});
  assert.deepEqual(JSON.parse(JSON.stringify(c.acts[1])), ['review.answer', {ticket:'t_abcdef', key:'review', verdict:'ok', digest:ID}]);
  const bad = await api.answer({id:'core:q:../x:q1', digest:ID, verdict:'ok'});
  assert.equal(bad.ok, false); assert.equal(c.acts.length, 2, 'a malformed id never reaches the server');
});
test('refusals become the codes the page understands', async () => {
  const reply = r => ctx({}, {act:async () => r}).reviewApi().answer({id:CARD.id, digest:ID, verdict:'ok'});
  assert.equal((await reply({ok:false, status:403, text:'Sign in to do this: run orch dashboard open in your terminal.'})).error.code, 'needs_person');
  assert.deepEqual({...(await reply({ok:false, status:422, text:JSON.stringify({ok:false, error:{code:'changed', message:'It changed.'}})})).error}, {code:'changed', message:'It changed.'});
  assert.equal((await reply({ok:false, status:400, text:'That is not a card.'})).error.code, 'refused');
  assert.equal((await reply({ok:false, status:0, text:'Could not reach orch.'})).error.code, 'error');
});
// Owner's walk of 28 Nov (O-05 D, O-06 D, W-036): the page draws the waiting list itself: five compact rows and the
// count, Next five / All, cards with one cause folded into a row with Open, no Compare and no ticks; under it the
// merge line and the Reviewer's line.
const listDeck = (n, extra = {}) => { const jumps = []; return {jumps, items:Array.from({length:n}, (_, i) => ({id:'c' + i, title:'Card ' + i, ticket:'DT-' + i, raw:{}})), answers:{}, index:0, jump:i => jumps.push(i), drawList() { throw new Error('the kit list is not used'); }, ...extra}; };
const buttons = n => nodes(n).filter(x => x.tag === 'button');
test('O-05: the list shows five compact rows and the count; Next five shows the next five, All every one, First five the start again', () => {
  const c = ctx({}), deck = listDeck(13), queue = h('div');
  c.reviewDrawSide(queue, deck);
  const rows = () => nodes(queue).filter(n => n.attrs?.['data-review-row']).map(n => n.attrs['data-review-row']);
  const steps = () => buttons(queue).filter(b => b.attrs['data-review-more']).map(text);
  const where = () => text(nodes(queue).find(n => n.attrs?.['data-review-where'] !== undefined));
  assert.deepEqual(rows(), ['c0', 'c1', 'c2', 'c3', 'c4']);
  assert.match(text(queue), /^Needs you13 waiting/);
  const first = nodes(queue).find(n => n.attrs?.['data-review-row'] === 'c0');
  assert.equal(first.attrs['aria-current'], 'true'); assert.match(first.attrs.className, /review-queue-row is-now/);
  assert.deepEqual(steps(), ['Next five', 'All 13']); assert.equal(where(), 'Rows 1 to 5 of 13');
  nodes(queue).find(n => n.attrs?.['data-review-row'] === 'c3').onclick(); assert.deepEqual(deck.jumps, [3], 'a row opens its card');
  const more = key => buttons(queue).find(b => b.attrs['data-review-more'] === key);
  // the buttons redraw the list in its place on the page; here the place is handed in again
  c.document.querySelector = () => queue;
  more('next').onclick(); assert.deepEqual(rows(), ['c5', 'c6', 'c7', 'c8', 'c9'], 'the next five, never a longer list');
  assert.deepEqual(steps(), ['Next five', 'First five', 'All 13']); assert.equal(where(), 'Rows 6 to 10 of 13');
  more('next').onclick(); assert.deepEqual(rows(), ['c10', 'c11', 'c12']); assert.deepEqual(steps(), ['First five', 'All 13']);
  more('all').onclick(); assert.equal(rows().length, 13); assert.deepEqual(steps(), ['First five']);
  more('five').onclick(); assert.deepEqual(rows(), ['c0', 'c1', 'c2', 'c3', 'c4']);
  // the list follows the card on screen: a card further down (opened from a ticket, or the next after an answer) shows its five
  deck.index = 7; c.reviewDrawSide(queue, deck);
  assert.deepEqual(rows(), ['c5', 'c6', 'c7', 'c8', 'c9']);
  more('five').onclick(); assert.deepEqual(rows(), ['c0', 'c1', 'c2', 'c3', 'c4'], 'First five stays where the person put it');
  c.reviewDrawSide(queue, deck); assert.deepEqual(rows(), ['c0', 'c1', 'c2', 'c3', 'c4'], 'the same card: no jump back');
  deck.answers.c0 = {verdict:'ok'}; c.reviewDrawSide(queue, deck);
  assert.match(text(queue), /^Needs you12 waiting/, 'an answered card leaves the list and the count at once');
  assert.deepEqual(rows(), ['c1', 'c2', 'c3', 'c4', 'c5']);
  // five or fewer: no steps at all
  const few = h('div'); ctx({}).reviewDrawSide(few, listDeck(4));
  assert.deepEqual(buttons(few).filter(b => b.attrs['data-review-more']).length, 0);
});
test('O-05: cards that wait for one cause are one row with Open (their cards under it), never a button that answers them all', () => {
  const c = ctx({}), queue = h('div');
  const items = [{id:'s1', title:'Export', ticket:'DT-1', raw:{cause:'helper:unmerged'}}, {id:'q', title:'Which colour?', ticket:'DT-2', raw:{}},
    {id:'s2', title:'Import', ticket:'DT-3', raw:{cause:'helper:unmerged'}}, {id:'r1', kind:'check', title:'Recorded as passed for release 53', raw:{}}, {id:'r2', kind:'check', title:'Recorded as passed for release 53', raw:{}},
    {id:'n1', kind:'draft', title:'Review', raw:{}}, {id:'n2', kind:'draft', title:'Review', raw:{}}, {id:'d1', kind:'draft', title:'Recorded as passed for release 53', raw:{}}];
  const deck = listDeck(0, {items, index:2});
  c.document.querySelector = () => queue;
  c.reviewDrawSide(queue, deck);
  const group = key => buttons(queue).find(b => b.attrs['data-review-group'] === key);
  assert.equal(text(group('cause:helper:unmerged')), '2 · Pull request not mergedOpen');
  assert.equal(text(group('title:check:recorded as passed for release 53')), '2 · Recorded as passed for release 53Open');
  assert.match(group('cause:helper:unmerged').attrs.className, /is-now/, 'the card on screen is in this group');
  assert.deepEqual(nodes(queue).filter(n => n.attrs?.['data-review-row']).map(n => n.attrs['data-review-row']), ['q', 'n1', 'n2'], 'a lone cause stays its own row (rows 1 to 5: two groups, then three single rows)');
  assert.equal(c.reviewListModel(deck).all, 6, 'two groups and four single rows for eight cards');
  vm.runInContext('reviewListAll = true', c); c.reviewDrawSide(queue, deck);
  assert.deepEqual(nodes(queue).filter(n => n.attrs?.['data-review-row']).map(n => n.attrs['data-review-row']), ['q', 'n1', 'n2', 'd1'], 'cards without words of their own, or of another kind, are never folded');
  vm.runInContext('reviewListAll = false', c); c.reviewDrawSide(queue, deck);
  group('cause:helper:unmerged').onclick();
  assert.deepEqual(nodes(queue).filter(n => n.attrs?.['data-review-row']).map(n => n.attrs['data-review-row']).slice(0, 3), ['s1', 's2', 'q']);
  assert.equal(text(group('cause:helper:unmerged')), '2 · Pull request not mergedClose'); assert.equal(group('cause:helper:unmerged').attrs['aria-expanded'], 'true');
  assert.deepEqual(buttons(queue).map(text).filter(t => /merge all|answer all/i.test(t)), [], 'every decision stays its own');
});
test('O-06: no Compare button and no ticks in the list, and the kit is told to leave them out of its own lists', () => {
  const calls = [];
  const c = ctx({}, {window:{DashHelpers:helpers, UI:{reviewPage:(host, api, o) => { calls.push(o); return {destroy() {}, tick() {}}; }}}});
  const queue = h('div');
  c.reviewDrawSide(queue, listDeck(8));
  assert.doesNotMatch(text(queue), /Compare|Tick two/);
  assert.equal(nodes(queue).filter(n => n.tag === 'input').length, 0);
  const host = h('div');
  c.mountReview({querySelectorAll: sel => sel === '[data-review-host]' ? [host] : [], querySelector: () => null});
  assert.equal(calls[0].compare, false);
  assert.doesNotMatch(read('pages/review.js'), /deck\.drawList\(|setPicking|showPair/, 'the page starts no Compare mode');
});
test('W-036: the same order in every layout: the card, the list, then the Reviewer\'s one line that opens Answered', () => {
  const acc = (ticket, extra = {}) => ({ticket, key:'DT-1', title:'Fix', why:'merged.', sent_back:false, ...extra});
  const c = ctx({review:{cards:[], accepted:[acc('t_aaaa11'), acc('t_bbbb22'), acc('t_cccc33', {back:true}), acc('t_dddd44', {answer:true, question:'q1'}), acc('t_eeee55', {earlier:true})]}}, {iconEl:n => n});
  const queue = h('div');
  c.reviewDrawSide(queue, listDeck(1));
  const line = nodes(queue).find(n => n.attrs?.['data-review-reviewer'] !== undefined);
  assert.equal(text(line), 'The Reviewer accepted 2, sent back 1, answered 1 for you today.Look');
  assert.equal(nodes(queue).filter(n => n.attrs?.['data-review-row']).length, 0, 'one card alone has no rows; the line still shows');
  // wide: the list beside the card; the Reviewer's history is not on the Waiting page at all
  const page = nodes(c.reviewPage()), keys = page.map(n => n.attrs?.['data-key']).filter(Boolean);
  assert.ok(!keys.includes('review-accepted'), 'no log on Waiting');
  const main = page.find(n => n.attrs?.['data-key'] === 'review-main');
  assert.deepEqual(main.children.map(n => n.attrs['data-key']), ['review-nav', 'review-host'], 'the switch, then the card: nothing above the decision');
  const wide = page.find(n => n.attrs?.['data-key'] === 'review-layout');
  assert.deepEqual(wide.children.map(x => x.attrs['data-key']), ['review-main', 'review-rail'], 'wide too: the card before the list in the page, so Tab reaches the decision first');
  assert.equal(wide.attrs['data-narrow'], null, 'wide: no narrow mark, so the master stands the list on the left');
  assert.match(fs.readFileSync(path.join(__dirname, '../../../workspace/src/orch_ui/static/widgets.css'), 'utf8'), /\.review-layout:not\(\[data-narrow\]\)>\.review-rail\{order:-1\}/, 'the master rule that keeps the list on the left');
  // narrow (a phone, or beside the Focus panel): one column, the card first, the list after it in the same scroll
  const n = ctx({review:{cards:[], accepted:[]}}, {document:{addEventListener(){}, getElementById:() => null, body:{dataset:{liveNarrow:''}}}});
  const layout = nodes(n.reviewPage()).find(x => x.attrs?.['data-key'] === 'review-layout');
  assert.deepEqual(layout.children.map(x => x.attrs['data-key']), ['review-main', 'review-rail']);
  assert.deepEqual(layout.children[0].children.map(x => x.attrs['data-key']), ['review-nav', 'review-host', 'review-next']);
  assert.equal(nodes(layout).filter(x => x.attrs?.['data-review-queue'] !== undefined).length, 1, 'one list, never two');
  assert.ok(!nodes(layout).some(x => x.attrs?.className === 'card review-side'), 'the aside the narrow styles hide is not used');
  // Answered: the Reviewer's block first, each entry with its reason and Undo
  const a = ctx({review:{cards:[], accepted:[acc('t_aaaa11', {undo:'accept'})]}, tickets:[{id:'t_x', key:'DT-9', title:'Lunch', questions:[{id:'q1', text:'The helper could not start: Automation is paused.', taken_back:{at:'2026-11-15T10:00:00Z', by:'agent:automation', reason:'Automation runs again, so this needs no answer.'}}, {id:'q2', text:'old', taken_back:{at:'2026-11-01T10:00:00Z', reason:'x'}}]}]},
    {iconEl:x => x, document:{addEventListener(){}, getElementById:id => id === 'answered' ? {hidden:false} : null}});
  const am = nodes(a.reviewPage()).find(x => x.attrs?.['data-key'] === 'review-main');
  assert.deepEqual(am.children.map(x => x.attrs['data-key']), ['review-nav', 'review-accepted', 'review-closed', 'review-host']);
  assert.match(text(am.children[1]), /What the Reviewer did.*merged\./); assert.deepEqual(buttons(am.children[1]).map(text), ['Send back', 'Undo']);
  // W-043: what closed by itself today says so in one line; an older one is history
  assert.match(text(am.children[2]), /^Closed without youDT-9 · Lunch.*Closed by itself · Automation runs again, so this needs no answer\.$/);
  assert.doesNotMatch(text(am.children[2]), /old/);
});
test('W-043: a paused automation is one line on top with Turn on (one click, orch resume); running, there is no line', async () => {
  const c = ctx({paused:{reason:'Disk almost full: 8 GB free'}, tickets:[{id:'t_a', status:'ready'}, {id:'t_b', status:'ready'}, {id:'t_c', status:'active'}], review:{cards:[]}});
  const page = c.reviewPage(), line = nodes(page).find(n => n.attrs?.['data-key'] === 'review-paused');
  assert.equal(text(line), 'Automation is paused: Disk almost full: 8 GB free. Nothing starts by itself. 2 tickets wait for a helper.Turn on');
  assert.equal(page.children[1], line, 'right under the heading, above every card');
  assert.doesNotMatch(text(line), /orch resume/, 'no command to type');
  await buttons(line)[0].onclick();
  assert.deepEqual(JSON.parse(JSON.stringify(c.acts)), [['automation.resume', {}]]);
  assert.equal(nodes(c.reviewPage()).find(n => n.attrs?.['data-key'] === 'review-paused'), undefined, 'gone at once');
  assert.equal(ctx({review:{cards:[]}}).reviewPausedLine(), null);
  assert.equal(ctx({paused:{reason:''}, review:{cards:[]}}, {snapshot:true}).reviewPausedLine(), null, 'never in a shared copy');
});
test('the page keeps its host and side list out of the reconcile (mounted once), and leaving destroys the page', () => {
  const calls = [];
  const c = ctx({}, {window:{DashHelpers:helpers, UI:{reviewPage:(host, api, o) => { calls.push(o); return {destroy() { calls.push('destroy'); }, tick() {}}; }}}});
  const host = h('div'), side = h('aside'), queue = h('div');
  const main = {querySelectorAll: sel => sel === '[data-review-host]' ? [host] : sel === '[data-review-side],[data-review-nav]' ? [side] : [], querySelector: () => queue};
  c.mountReview(main); c.mountReview(main);
  assert.equal(calls.length, 1, 'mounted once'); assert.equal(calls[0].poll, 3000); assert.equal(typeof calls[0].onChange, 'function');
  assert.ok(c.mounts.has(host) && c.mounts.has(side));
  c.mounts.get(host).destroy(); assert.equal(calls.at(-1), 'destroy');
});
test('ORCH-2182: the page passes the decision-first switch to the deck, read from the settings at each draw', () => {
  const calls = [];
  const c = ctx({settings:{decision_first_on:false}}, {window:{DashHelpers:helpers, UI:{reviewPage:(host, api, o) => { calls.push(o); return {destroy() {}, tick() {}}; }}}});
  const host = h('div'), side = h('aside'), queue = h('div');
  c.mountReview({querySelectorAll: sel => sel === '[data-review-host]' ? [host] : sel === '[data-review-side]' ? [side] : [], querySelector: () => queue});
  assert.equal(calls[0].decisionFirst(), false);
  c.state.settings.decision_first_on = true;
  assert.equal(calls[0].decisionFirst(), true);
});
// ---- Home and ticket ----
function home(state, tickets = [], rows = []) {
  const c = ctx(state, {tickets:() => tickets, ticketOf:id => tickets.find(t => t.id === id), href:id => '#ticket/' + id, needsList:() => rows});
  vm.runInContext(read('pages/ticket.js'), c); vm.runInContext(read('pages/home.js'), c);
  return c;
}
// O-01 D (28 Nov): Home has no review cards; what waits is one line with "Open Review".
const homePage = c => { Object.assign(c, {titleTag:() => null, shown:t => t, parse:v => new Date(v), now:() => new Date('2026-11-15T12:00:00Z'), heading:(t, s) => h('header', {}, t, s),
  card:(key, title, suffix, kids) => h('section', {'data-key':key}, title, kids), emptyRow:t => h('p', {}, t), fragment:(...k) => h('fragment', {}, k)}); return c.home(); };
test('"Open Review" on Home is a link to #review beside the count, and the cards never change the Home total', () => {
  const rows = [{id:'n1', ticket:'t_abcdef', since:'2026-11-15T09:00:00Z', title:'Home block', answer:{question:'q3', digest:ID, options:[]}}];
  const base = {settings:{}, runs:{}, services:[]};
  const tickets = [{id:'t_abcdef', title:'Newsletter', status:'waiting', questions:[{id:'q3', text:'Home block'}]}];
  const withCards = home({...base, review:{cards:[CARD], answered:[]}}, tickets, rows), without = home({...base}, tickets, rows);
  const line = nodes(homePage(withCards)).find(n => n.attrs?.['data-key'] === 'review-line');
  assert.match(text(line), /^1 question waits in Review/);
  const a = nodes(line).find(n => n.attrs?.['data-key'] === 'review-all');
  assert.equal(a.tag, 'a'); assert.equal(a.attrs.href, '#review'); assert.match(text(a), /^Open Review$/);
  assert.doesNotMatch(text(homePage(withCards)), /Home block/, 'the question itself is on Review, never a card on Home');
  assert.equal(withCards.reviewCount(), 1);
  assert.equal(withCards.needsToday().count, without.needsToday().count, 'cards are the questions and results Home already counts');
  // a shared read-only copy keeps the line and the way to Review
  const copy = home({...base, review:{cards:[CARD], answered:[]}}, tickets, rows); copy.snapshot = true;
  assert.ok(nodes(homePage(copy)).some(n => n.attrs?.['data-key'] === 'review-all'));
});
test('ORCH-63: the Review subtitle, the top bar and the Review menu entry say one number: the cards (questions + results)', () => {
  const base = {settings:{}, runs:{}, services:[]};
  const t1 = {id:'t_abcdef', title:'Newsletter', status:'waiting', questions:[{id:'q3', text:'Home block'}]};
  const t2 = {id:'t_fffaaa', title:'Services', status:'waiting', questions:[{id:'q1', text:"Start 'Services'?", kind:'factory:start'}]};
  const rows = [
    {id:'core:q:t_abcdef:q3', source:'core', ticket:'t_abcdef', since:'2026-11-15T09:00:00Z', title:'Newsletter', answer:{question:'q3', digest:ID, options:['A', 'B']}},
    {id:'core:q:t_fffaaa:q1', source:'core', kind:'factory:start', ticket:'t_fffaaa', since:'2026-11-15T10:00:00Z', title:'Services', answer:{question:'q1', digest:ID, options:['Start', 'Edit', 'Not now']}}];
  const factory = {...CARD, id:'core:q:t_fffaaa:q1', ticket:'t_fffaaa', key:'q1', kind:'choice', card:{kind:'choice', title:"Start 'Services'?"}};
  const c = home({...base, review:{cards:[CARD, factory], answered:[]}}, [t1, t2], rows);
  assert.equal(c.needsToday().count, 2);
  assert.equal(c.reviewSubtitle(), '2 things need you.');
  // owner 16 Nov: the number is open questions plus results to check, so it equals the cards here. A helper idle at its
  // prompt, or a ticket that only waits for another ticket, has no card and is not counted.
  const idle = {id:'core:stuck:t_ccccdd', source:'core', kind:'stuck:idle', ticket:'t_ccccdd', since:'2026-11-15T11:00:00Z', title:'Docs', text:'The helper waits at its prompt', tone:'warn'};
  const waits = {id:'t_ddddee', title:'Later', status:'waiting', waiting_on:{kind:'ticket', ref:'t_abcdef'}, questions:[]};
  const check = {...CARD, id:'core:review:t_eeeeff', ticket:'t_eeeeff', key:'review', kind:'check', card:{kind:'check', title:'Report'}};
  const cards = [CARD, factory, check];
  const more = home({...base, review:{cards, answered:[]}}, [t1, t2, {id:'t_ccccdd', title:'Docs', status:'active', questions:[]}, waits, {id:'t_eeeeff', title:'Report', status:'review', questions:[]}], [...rows, idle]);
  assert.equal(more.needsToday().count, 3); assert.equal(more.needsToday().count, more.reviewCount());
  assert.equal(more.reviewSubtitle(), '3 things need you.');
  assert.equal(home({...base, review:{cards:[], answered:[]}}, [], []).reviewSubtitle(), 'Nothing waits for you.');
});
test('ORCH-63: the dashboard sends the one count to the shown add-on page of its own (Focus), and on request', () => {
  const src = read('app.js');
  assert.match(src, /postMessage\(\{type:'orch\.needs\.count', count:n\}, '\*'\)/);  // to the sandboxed frame only
  assert.match(src, /const needCount = needsYouTotal\(\)[^\n]*\n[\s\S]{0,400}postNeedsCount\(needCount\);/);
  assert.match(src, /e\.data\?\.orch !== 'needs-count'/);
  assert.match(src, /\.shipped\) return null;/, 'only an add-on orch ships gets the number');
});
test('Review answers on a ticket: only those with a card answer, newest first', () => {
  const answered = (id, at, extra = {}) => ({id, text:'Q ' + id, answer:'Looks good', answered_by:'human:sev', via:'dashboard', at, card:{kind:'draft', title:'Card ' + id}, decision:{action:'approve', summary:'Looks good'}, ...extra});
  const t = {id:'t_abcdef', questions:[answered('q1', '2026-11-14T09:00:00Z'), {id:'q2', text:'open'}, answered('q3', '2026-11-15T09:00:00Z'), {id:'q4', answer:'x', at:'2026-11-15T10:00:00Z'}]};
  const c = home({review:{cards:[]}}, [t]);
  const list = vm.runInContext('ticketReviewAnswers', c)(t);
  assert.deepEqual(list.map(e => e.id), ['core:q:t_abcdef:q3', 'core:q:t_abcdef:q1'], 'an answer without a decision is not one');
  assert.equal(vm.runInContext('ticketReviewAnswers', c)({id:'t_abcdef', questions:[{id:'q4', answer:'x'}]}).length, 0);
});

test('ORCH-420: the subtitle never says nothing waits above cards (a card put off on Home is still a card here)', () => {
  const c = ctx({review:{cards:[CARD]}}, {needsYouTotal:() => 0});
  assert.equal(c.reviewSubtitle(), 'Nothing new needs you. 1 card you put off is still here.', 'W-003: never another number than the badge; the part is named');
});

test('Review opens at the card the ticket page asked for (#review?card=...)', () => {
  const calls = [];
  const c = ctx({}, {location:{hash:'#review?card=' + encodeURIComponent('core:q:t_abcdef:q2')}, window:{DashHelpers:helpers, UI:{reviewPage:(host, api, o) => { calls.push(o); return {destroy() {}, tick() {}}; }}}});
  const host = h('div'), main = {querySelectorAll: sel => sel === '[data-review-host]' ? [host] : [], querySelector: () => h('div')};
  c.mountReview(main);
  assert.equal(calls[0].startId, 'core:q:t_abcdef:q2');
});

test('"What the Reviewer did": hidden when empty, a link and the why line per row, one tap sends back with a note (ORCH-77)', async () => {
  const row = (ticket, extra = {}) => ({ticket, key:'ORCH-' + ticket.slice(-2), title:'Fix ' + ticket, why:'pull request #12 merged, 17 checks green.', sent_back:false, ...extra});
  const c = ctx({review:{cards:[], accepted:[]}}, {iconEl:n => n});
  assert.equal(c.reviewAcceptedCard(), null, 'nothing accepted: no section');
  c.state.review.accepted = [row('t_aaaa11'), row('t_bbbb22', {sent_back:true})];
  const card = c.reviewAcceptedCard();
  assert.match(text(card), /^What the Reviewer did/);
  const links = nodes(card).filter(n => n.tag === 'a');
  assert.deepEqual(links.map(a => a.attrs.href), ['#ticket/t_aaaa11', '#ticket/t_bbbb22']);
  assert.match(text(card), /pull request #12 merged, 17 checks green\./);
  const buttons = nodes(card).filter(n => n.tag === 'button');
  assert.equal(buttons.length, 1, 'only the row that is not sent back has the button');
  assert.equal(text(buttons[0]), 'Send back');
  assert.match(text(card), /Sent back/);
  // W-036: the block is on Answered, not in the rail under the list
  assert.ok(!nodes(c.reviewPage()).some(n => n.attrs?.['data-key'] === 'review-accepted'));
  // the send: ticket.changes with the note, then the row reads "Sent back"
  assert.equal(await c.reviewSendBack(row('t_aaaa11'), '   '), false, 'an empty note sends nothing');
  assert.equal(c.acts.length, 0);
  assert.equal(await c.reviewSendBack(row('t_aaaa11'), ' Keep the old name '), true);
  assert.deepEqual(JSON.parse(JSON.stringify(c.acts[0])), ['ticket.changes', {ticket:'t_aaaa11', text:'Keep the old name'}]);
  assert.equal(nodes(c.reviewAcceptedCard()).filter(n => n.tag === 'button').length, 0);
});
test('ORCH-288: Home’s Review line, the Needs you pill and the subtitle say one number', () => {
  const base = {settings:{}, runs:{}, services:[], review:{cards:[CARD, CARD], answered:[]}};
  const rows = [{id:'n1', ticket:'t_abcdef', since:'2026-11-15T09:00:00Z', title:'A', answer:{question:'q1', digest:ID, options:[]}}];
  const tickets = [{id:'t_abcdef', title:'News', status:'waiting', questions:[{id:'q1', text:'A'}]}, {id:'t_ghijkl', title:'Done work', status:'review'}];
  const c = home(base, tickets, rows), total = c.needsYouTotal();
  assert.equal(total, 2);  // one question + one result to check, not the two cards
  assert.equal(text(nodes(homePage(c)).find(n => n.attrs?.['data-key'] === 'review-line')), '1 question and 1 result wait in ReviewOpen Review');
});
test('ORCH-422: Add note and Send back on Review carry screenshots, files and voice notes onto the ticket', async () => {
  const attached = [];
  const extra = {FEEDBACK_BOX:{accept:['png', 'webm'], voice:true, maxBytes:1},
    ticketAttachFiles:async (tid, files) => { attached.push([tid, files.map(f => f.name)]); return files.some(f => f.name.endsWith('.pdf')) ? {ok:false, text:'x.pdf: no'} : {ok:true, names:files.map(f => 'kept-' + f.name)}; },
    ticketTalkText:(text, names) => [text, names.length ? 'FILES ' + names.join(',') : ''].filter(Boolean).join(' | ')};
  const c = ctx({review:{cards:[CARD]}}, extra);
  const api = c.reviewApi();
  assert.equal(api.box.voice, true, 'the comment sheet gets the feedback box with Record');
  assert.equal(ctx({}, {...extra, snapshot:true}).reviewApi().box, null, 'a shared copy has no box');
  assert.equal(ctx({}).reviewApi().box, null, 'no ticket page code, no box');
  // Add note with only a voice note: files first, then the helper is told their names
  const r = await api.note({ticket:'t_abcdef', text:'', files:[{name:'voice-note-0931.webm', url:'data:audio/webm;base64,GkXf'}]});
  assert.equal(r.ok, true);
  assert.deepEqual(JSON.parse(JSON.stringify(attached)), [['t_abcdef', ['voice-note-0931.webm']]]);
  assert.deepEqual(JSON.parse(JSON.stringify(c.acts)), [['run.send', {ticket:'t_abcdef', text:'FILES kept-voice-note-0931.webm'}]]);
  // a refused file: nothing is told to the helper, the words stay
  c.acts.length = 0;
  const bad = await api.note({ticket:'t_abcdef', text:'see this', files:[{name:'x.pdf', url:'data:,x'}]});
  assert.equal(bad.ok, false);
  assert.equal(c.acts.length, 0);
  // Send back on a card: the kit calls attach, then the answer (see the kit test); attach returns the kept names
  const up = await api.attach({ticket:'t_abcdef', files:[{name:'shot.png', url:'data:image/png;base64,iVBO'}]});
  assert.deepEqual(JSON.parse(JSON.stringify(up)), {ok:true, names:['kept-shot.png']});
  // empty: no words and no files is refused before anything is sent
  assert.equal((await api.note({ticket:'t_abcdef', text:' ', files:[]})).ok, false);
});
test('Auto Reviewer card: two switches on the rail that save at once (ORCH-425)', async () => {
  const c = ctx({review:{cards:[], accepted:[]}, settings:{auto_reviewer_on:false, away_on:true}});
  const cardNode = c.reviewAutoCard();
  assert.match(text(cardNode), /^Auto Reviewer/);
  const sw = nodes(cardNode).filter(n => n.attrs?.role === 'switch');
  assert.deepEqual(sw.map(n => [n.attrs['data-action'], n.attrs['aria-checked']]), [['auto-reviewer-set', false], ['away-set', true], ['reviewer-mode-set', false]]);
  const rail = nodes(c.reviewPage()).find(n => n.attrs?.['data-key'] === 'review-rail');
  assert.ok(nodes(rail).some(n => n.attrs?.['data-key'] === 'review-auto'));
  await c.reviewSwitch('auto');
  await c.reviewSwitch('away');
  await c.reviewSwitch('propose');
  assert.deepEqual(JSON.parse(JSON.stringify(c.acts)), [['auto_reviewer.set', {on:true}], ['away.set', {on:false}], ['reviewer_mode.set', {on:true}]]);
  assert.equal(ctx({review:{cards:[]}}).reviewAutoCard(), null, 'no settings (a read-only copy): no switches');
  const snap = ctx({settings:{away_on:true}}, {snapshot:true});
  assert.ok(nodes(snap.reviewAutoCard()).filter(n => n.attrs?.role === 'switch').every(n => n.attrs.disabled));
  assert.equal(await snap.reviewSwitch('auto'), null);
});
test('Auto Reviewer: hidden on Review until a switch is on in Settings; plain words; verdicts in the history (ORCH-1798)', () => {
  const off = ctx({review:{cards:[], accepted:[]}, settings:{auto_reviewer_on:false, away_on:false}});
  assert.equal(off.reviewAutoCard(), null, 'both off: no card on Review');
  const rail = nodes(off.reviewPage()).find(n => n.attrs?.['data-key'] === 'review-rail');
  assert.ok(!nodes(rail).some(n => n.attrs?.['data-key'] === 'review-auto'));
  // Settings > General draws the same rows (its own keys), with both switches off
  const src = read('pages/settings.js');
  vm.runInContext(src.slice(src.indexOf('function autoReviewerCard'), src.indexOf('// Accept small finished work for me')), off);
  const set = off.autoReviewerCard();
  assert.equal(set.attrs['data-key'], 'settings-auto-reviewer');
  assert.deepEqual(nodes(set).filter(n => n.attrs?.role === 'switch').map(n => [n.attrs['data-key'], n.attrs['data-action'], n.attrs['aria-checked']]),
    [['settings-switch-auto', 'auto-reviewer-set', false], ['settings-switch-away', 'away-set', false], ['settings-switch-propose', 'reviewer-mode-set', false]]);
  const words = text(set);
  assert.match(words, /shows in the ticket\u2019s history, and you can undo it/);
  for (const w of ['Words, names', 'deploy', 'recommendation']) assert.ok(!words.includes(w), 'no orch-only word: ' + w);
  // turned on: the card shows on Review, with the same note
  const on = ctx({review:{cards:[], accepted:[]}, settings:{auto_reviewer_on:true, away_on:false}});
  assert.match(text(on.reviewAutoCard()), /ticket\u2019s history/);
});
test('What the Reviewer did: each decision says who and what, and Undo takes it back in one click (ORCH-425)', async () => {
  const rows = [
    {ticket:'t_aaaa11', key:'O-1', title:'Speed', why:'code work, all 2 points shown.', auto:true, undo:'accept'},
    {ticket:'t_bbbb22', key:'O-2', title:'Sort', why:'answered q2 = A', auto:true, answer:true, question:'q2', undo:'answer'},
    {ticket:'t_cccc33', key:'O-3', title:'Home', why:'pictures missing', auto:true, back:true, undo:null},
    {ticket:'t_dddd44', key:'O-4', title:'Old', why:'small', auto:false, undo:null, undone:true},
  ];
  const c = ctx({review:{cards:[], accepted:rows}});
  const card = c.reviewAcceptedCard();
  const t = text(card);
  // ORCH-1835: the card holds send-backs and answers too, so its name is not "Accepted for you"
  assert.match(t, /^What the Reviewer did/);
  assert.doesNotMatch(t, /Accepted for you/);
  assert.match(t, /Auto Reviewer · Accepted/);
  assert.match(t, /Away mode · Answered/);
  assert.match(t, /Auto Reviewer · Sent back to the helper/);
  assert.match(t, /Reviewer · AcceptedsmallUndone/);
  const undos = nodes(card).filter(n => n.tag === 'button' && text(n) === 'Undo');
  assert.equal(undos.length, 2);
  const sends = nodes(card).filter(n => n.tag === 'button' && text(n) === 'Send back');
  assert.equal(sends.length, 1, 'Send back only on an accept that is not undone');
  await undos[1].onclick();
  await undos[0].onclick();
  assert.deepEqual(JSON.parse(JSON.stringify(c.acts)), [['review.undo', {ticket:'t_bbbb22', question:'q2'}], ['review.undo', {ticket:'t_aaaa11'}]]);
  assert.match(text(c.reviewAcceptedCard()), /AnsweredUndone|Undone/);
  const keys = nodes(c.reviewAcceptedCard()).map(n => n.attrs?.['data-key']).filter(k => /^review-accepted-t_/.test(k || '') && !/-(send|undo)$/.test(k));
  assert.equal(new Set(keys).size, keys.length, 'one key per row');
});
test('ORCH-420 follow-up: files of an answer go in the ticket\'s feedback folder, so the Check card does not change under the answer', async () => {
  const calls = [];
  const c = ctx({review:{cards:[CARD]}}, {FEEDBACK_BOX:{accept:['png'], voice:true, maxBytes:1}, ticketTalkText:t => t,
    ticketAttachFiles:async (tid, files, feedback) => { calls.push([tid, feedback === true]); return {ok:true, names:files.map(f => f.name)}; }});
  await c.reviewApi().attach({ticket:'t_abcdef', files:[{name:'shot.png', url:'data:image/png;base64,iVBO'}]});
  assert.deepEqual(JSON.parse(JSON.stringify(calls)), [['t_abcdef', true]]);
});

// ORCH-1108 (owner's pick on ORCH-1102: "4 things wait" over 1 card): work that stopped is a card on Review too, with
// Home's buttons, so the number and the Waiting cards are the same count.
const STUCK = (kind, tid, extra = {}) => ({id:'core:' + kind.split(':')[1] + ':' + tid, source:'core', kind, ticket:tid, title:'T ' + tid, since:'2026-11-15T10:00:00Z', text:'Stopped: ' + kind, ...extra});
function stuckHome(runs = {}) {
  const tickets = [
    {id:'t_abcdef', key:'DT-41', title:'Newsletter', status:'waiting', questions:[{id:'q3', text:'Home block'}]},
    {id:'t_aaaa01', key:'DT-1', title:'Invoice export', status:'review', questions:[]},
    {id:'t_aaaa02', key:'DT-2', title:'Docs', status:'active', questions:[], description:'Write the setup guide for new staff.\nMore lines.',
      checklist:[{id:'c1', text:'Collect the steps', done:true}, {id:'c2', text:'Write the guide'}, {id:'c3', text:'Skip', wont_do:true}]},
    {id:'t_aaaa03', key:'DT-3', title:'Booking', status:'active', questions:[]},
    {id:'t_aaaa04', key:'DT-4', title:'Menu', status:'active', questions:[]},
    {id:'t_aaaa05', key:'DT-5', title:'Report', status:'review', questions:[]},
    {id:'t_aaaa06', key:'DT-6', title:'Survey', status:'active', questions:[]}];
  const rows = [
    {id:'core:q:t_abcdef:q3', source:'core', ticket:'t_abcdef', since:'2026-11-15T09:00:00Z', title:'Newsletter', answer:{question:'q3', digest:ID, options:['A', 'B']}},
    STUCK('helper:unmerged', 't_aaaa01', {pull:{url:'https://github.com/acme/app/pull/12', head:'a'.repeat(40)}}),
    STUCK('helper:idle', 't_aaaa02'), STUCK('helper:failing', 't_aaaa03'), STUCK('helper:permission', 't_aaaa04'),
    STUCK('reviewer:unsure', 't_aaaa05'),   // waits in Check: its Check card is the card, counted once
    STUCK('reviewer:unsure', 't_aaaa06')];  // not in Check (any more): a stuck card of its own
  const check = id => ({...CARD, id:'core:review:' + id, ticket:id, key:'review', kind:'check', card:{kind:'check', title:'Result'}});
  return home({settings:{}, runs, services:[], review:{cards:[CARD, check('t_aaaa01'), check('t_aaaa05')], answered:[]}}, tickets, rows);
}
test('ORCH-1108: Review\'s number and its Waiting cards are the same count, stuck work included', async () => {
  const c = stuckHome();
  const n = c.needsToday();
  assert.equal(n.stuck.length, 6, 'Home lists six rows of stopped work');
  assert.equal(n.count, 1 + 2 + 6 - 1, 'one question, two results, six stopped, the unsure one in Check once');
  const stack = await c.reviewApi().stack();
  assert.equal(stack.length, n.count, 'one card per thing counted');
  assert.equal(c.reviewCount(), n.count);
  assert.equal(c.reviewSubtitle(), n.count + ' things need you.');
  const stuck = stack.filter(x => x.card.kind === 'stuck');
  assert.deepEqual([...stuck.map(x => x.ticket)], ['t_aaaa01', 't_aaaa02', 't_aaaa03', 't_aaaa04', 't_aaaa06'], 'first in line, as on Home; the unsure ticket in Check has only its Check card');
  assert.equal(stack.indexOf(stuck[0]), 0);
  const by = id => stuck.find(x => x.ticket === id);
  assert.equal(JSON.stringify(by('t_aaaa01').answers), JSON.stringify([{label:'Merge', picked:'merge'}, {label:'Start helper', picked:'nudge'}]), 'no helper running: Start helper, as on Home');
  assert.equal(JSON.stringify(by('t_aaaa02').answers), JSON.stringify([{label:'Nudge', picked:'nudge'}, {label:'Start fresh', picked:'fresh'}]));
  assert.equal(by('t_aaaa04').answers.length, 0, 'a helper waiting for an OK on its screen: Open only');
  assert.equal(by('t_aaaa02').href, '#ticket/t_aaaa02'); assert.equal(by('t_aaaa02').ticket_key, 'DT-2');
  // the context the owner asked for (q1 sent back: "not enough context what it is about"): the ticket's name, what was
  // asked, where it stopped, what the buttons do
  assert.equal(by('t_aaaa02').card.title, 'Docs'); assert.equal(by('t_aaaa02').text, 'Stopped: helper:idle');
  assert.equal(by('t_aaaa02').about, 'Write the setup guide for new staff.');
  assert.equal(by('t_aaaa02').card.why, 'Stopped at: Write the guide · 1 of 2 steps done.');
  assert.match(by('t_aaaa02').card.hint, /^Nudge asks the helper .* Start fresh stops it/);
  assert.match(by('t_aaaa04').card.hint, /^Open the ticket/);
  assert.equal(by('t_aaaa03').about, undefined, 'no description: no About line');
  assert.equal(stuckHome({t_aaaa01:{running:true}}).reviewStuckCards()[0].answers[1].label, 'Nudge', 'a helper running: Nudge');
  // the shared kit draws it as a Stuck card with those buttons and the Open link
  const reviewKit = {}; vm.runInContext(fs.readFileSync(path.join(__dirname, '../../../workspace/src/orch_ui/static/review.js'), 'utf8'), vm.createContext({window:reviewKit}));
  const item = reviewKit.UI.review.mapCard(by('t_aaaa01'), {fileUrl:() => ''}, new Date('2026-11-15T12:00:00Z'));
  assert.equal(item.kindLabel, 'Stuck'); assert.equal(item.ticket, 'DT-1'); assert.equal(item.href, '#ticket/t_aaaa01');
  assert.equal(item.title, 'Invoice export'); assert.equal(item.text, 'Stopped: helper:unmerged'); assert.match(item.hint, /^Merge puts the pull request in\. Start helper/);
});
test('#2385: with the core counting the stopped work, Home adds nothing of its own and says the same number', () => {
  const row = (kind, tid) => ({ticket:tid, question:null, stopped:kind, row:'core:' + kind.split(':')[1] + ':' + tid});
  // what orch/counts.py makes of the same tickets and rows: the unsure ticket in Check is its row only
  const items = [{ticket:'t_abcdef', question:'q3'}, row('helper:unmerged', 't_aaaa01'), {ticket:'t_aaaa01', question:null},
    row('helper:idle', 't_aaaa02'), row('helper:failing', 't_aaaa03'), row('helper:permission', 't_aaaa04'),
    row('reviewer:unsure', 't_aaaa05'), row('reviewer:unsure', 't_aaaa06')];
  const c = stuckHome(), old = c.needsToday().count;
  c.state.counts = {needs_you:{count:items.length, questions:1, results:1, failed:0, stopped:6, items}};
  const n = c.needsToday();
  assert.equal(n.count, items.length, 'the core number, not the core number plus the rows again');
  assert.equal(n.count, old, 'the same as Home counted it on its own');
  assert.deepEqual(n.review.map(t => t.id), ['t_aaaa01'], 'a stopped item is never a result to check');
  assert.ok(!c.reviewExtraRows().some(r => r.what === 'result'), 'Review lists no stopped item as "A result to check"');
});
test('ORCH-1108: a stuck card\'s buttons do what Home\'s do; a row that is gone, changed or without that button does nothing', async () => {
  const c = stuckHome(), api = c.reviewApi(), stuck = (await api.stack()).filter(x => x.card.kind === 'stuck');
  const card = t => stuck.find(x => x.ticket === t), press = (t, picked, extra = {}) => api.answer({id:card(t).id, digest:card(t).digest, verdict:'ok', picked, ...extra});
  assert.deepEqual({...await press('t_aaaa01', 'merge')}, {ok:true});
  assert.deepEqual(JSON.parse(JSON.stringify(c.acts.at(-1))), ['pull.merge', {ticket:'t_aaaa01', url:'https://github.com/acme/app/pull/12', head:'a'.repeat(40)}]);
  await press('t_aaaa02', 'nudge');
  assert.deepEqual(c.acts.slice(-2).map(a => a[0]), ['run.send', 'run.start'], 'Nudge: the words, then a start when no helper runs');
  assert.match(c.acts.at(-2)[1].text, /idle for a while/);
  await press('t_aaaa03', 'fresh');
  assert.deepEqual(JSON.parse(JSON.stringify(c.acts.at(-1))), ['run.start', {ticket:'t_aaaa03', fresh:true}]);
  // the work is still stopped: the card stays in Waiting (a new digest, so the deck shows it again) and says what was done
  const after = (await api.stack()).filter(x => x.card.kind === 'stuck');
  assert.equal(after.length, stuck.length, 'still one card per thing counted');
  const idle = after.find(x => x.ticket === 't_aaaa02');
  assert.notEqual(idle.digest, card('t_aaaa02').digest);
  assert.match(idle.card.why, /^Helper started /, 'no helper was running, so Nudge started one');
  assert.equal(after.find(x => x.ticket === 't_aaaa04').card.why, undefined);
  const before = c.acts.length;
  assert.equal((await press('t_aaaa02', 'nudge')).error.code, 'changed', 'the old card (shown before the press) is not pressed twice');
  assert.equal((await press('t_aaaa04', 'nudge')).error.code, 'refused', 'no Nudge on a helper waiting for an OK on its screen');
  assert.equal((await press('t_aaaa01', 'fresh', {digest:after[0].digest})).error.code, 'refused', 'Start fresh is not on a pull request card');
  assert.equal((await api.answer({id:'stuck:core:idle:t_zzzzzz', verdict:'ok', picked:'nudge'})).error.code, 'decided', 'gone: the page says so and reloads');
  assert.equal(c.acts.length, before, 'nothing was sent');
  const shared = stuckHome(); shared.snapshot = true;
  assert.equal(shared.reviewStuckCards().length, 0, 'a shared copy shows no buttons that change things');
});
// Outside review (OpenAI credit): what was done belongs to one stop; two quick presses run one action.
test('ORCH-1108: "Helper started" stays with the stop it was pressed on; a later stop of the same ticket starts clean', async () => {
  const row = STUCK('helper:idle', 't_aaaa02');
  const c = home({settings:{}, runs:{}, services:[], review:{cards:[], answered:[]}}, [{id:'t_aaaa02', key:'DT-2', title:'Docs', status:'active', questions:[]}], [row]);
  const api = c.reviewApi(), [card] = await api.stack();
  assert.deepEqual({...await api.answer({id:card.id, digest:card.digest, verdict:'ok', picked:'fresh'})}, {ok:true});
  assert.match((await api.stack())[0].card.why, /^Helper started fresh /);
  row.since = '2026-11-16T08:00:00Z';  // it went idle again later: the same row id, a new stop
  const later = (await api.stack())[0];
  assert.equal(later.card.why, undefined, 'the earlier press is not shown on the new stop');
  assert.notEqual(later.digest, card.digest);
});
test('ORCH-1108: two presses at once on a stuck card run its action once', async () => {
  let release; const hold = new Promise(r => { release = r; });
  const c = home({settings:{}, runs:{t_aaaa03:{running:true}}, services:[], review:{cards:[], answered:[]}}, [{id:'t_aaaa03', key:'DT-3', title:'Booking', status:'active', questions:[]}], [STUCK('helper:failing', 't_aaaa03')]);
  const calls = []; c.act = async (op, args) => { calls.push(op); await hold; return {ok:true, status:200}; };
  const api = c.reviewApi(), [card] = await api.stack(), press = () => api.answer({id:card.id, digest:card.digest, verdict:'ok', picked:'fresh'});
  const first = press(), second = await press();
  assert.equal(second.error.code, 'busy', 'the second press does nothing while the first runs');
  release(); assert.deepEqual({...await first}, {ok:true});
  assert.deepEqual(calls, ['run.stop', 'run.start'], 'one stop, one fresh start');
});
test('ORCH-1108: Merge on a card shown before a newer commit arrived merges nothing', async () => {
  const c = stuckHome(), api = c.reviewApi();
  const shown = (await api.stack())[0];
  c.needsList().find(r => r.kind === 'helper:unmerged').pull.head = 'b'.repeat(40);
  assert.equal((await api.answer({id:shown.id, digest:shown.digest, verdict:'ok', picked:'merge'})).error.code, 'changed');
  assert.equal(c.acts.length, 0);
});
test('ORCH-1616: what the number counts but has no card is listed above the cards, so badge, heading and page agree', () => {
  const base = {settings:{}, runs:{}, services:[], counts:{needs_you:{count:2, questions:1, results:1, items:[{ticket:'t_abcdef', question:'q1'}, {ticket:'t_ghijkl'}]}}};
  const tickets = [{id:'t_abcdef', key:'ORCH-7', title:'News', status:'waiting', questions:[{id:'q1', text:'Which logo?'}]},
    {id:'t_ghijkl', key:'ORCH-8', title:'Done work', status:'review'}];
  const none = home({...base, review:{cards:[], answered:[]}}, tickets, []);
  const rows = none.reviewExtraRows();
  assert.equal(JSON.stringify(rows.map(r => [r.t.id, r.what, r.text])), JSON.stringify([['t_abcdef', 'question', 'Which logo?'], ['t_ghijkl', 'result', 'A result to review.']]));
  assert.equal(rows.length, none.needsYouTotal(), 'everything the badge counts is listed');
  assert.match(JSON.stringify(none.reviewExtraCard()), /Also waiting for you/);
  // with a card for each, nothing extra: the cards list them
  const carded = home({...base, review:{cards:[{id:'core:q:t_abcdef:q1', ticket:'t_abcdef'}, {id:'r', ticket:'t_ghijkl'}], answered:[]}}, tickets, []);
  assert.equal(carded.reviewExtraRows().length, 0);
  assert.equal(carded.reviewExtraCard(), null);
});
test('ORCH-1687: a helper that could not start is counted and listed on the Review page, with Open', () => {
  const base = {settings:{}, runs:{}, services:[], counts:{needs_you:{count:1, questions:0, results:1, items:[{ticket:'t_ghijkl'}]}}};
  const tickets = [{id:'t_abcdef', key:'ORCH-7', title:'Notes', status:'waiting', waiting_on:{kind:'external', ref:'Not logged in', start:true}},
    {id:'t_ghijkl', key:'ORCH-8', title:'Done work', status:'review'}];
  const c = home({...base, review:{cards:[], answered:[]}}, tickets, []);
  const rows = c.reviewExtraRows();
  assert.equal(JSON.stringify(rows.map(r => [r.t.id, r.what]).sort()), JSON.stringify([['t_abcdef', 'failed'], ['t_ghijkl', 'result']]));
  assert.equal(rows.length, c.needsYouTotal(), 'the badge counts what the page lists');
  assert.match(rows.find(r => r.what === 'failed').text, /could not start/);
  assert.match(JSON.stringify(c.reviewExtraCard()), /"Open"/);
});

test('What the Reviewer did: an earlier verdict of a ticket says so and has no buttons (ORCH-1719)', () => {
  const rows = [
    {ticket:'t_aaaa11', key:'O-1', title:'Speed', why:'Pictures at 1920 and 390 px are missing.', auto:true, back:true, undo:null},
    {ticket:'t_aaaa11', key:'O-1', title:'Speed', why:'All 2 points of this code work are shown.', auto:true, earlier:true, undo:null, sent_back:false},
  ];
  const card = ctx({review:{cards:[], accepted:rows}}).reviewAcceptedCard();
  assert.match(text(card), /Earlier verdict: a newer one counts/);
  assert.equal(nodes(card).filter(n => n.tag === 'button' && text(n) === 'Send back').length, 0);
});
test('ORCH-1804: "Open ticket" shows the card\'s ticket beside the deck (#review?ticket=), the ticket page itself, in place of All cards', () => {
  const at = hash => ({location:{hash}, snapshot:false, array:v => Array.isArray(v) ? v : [], history:{state:null, replaceState(){}},
    ticketOf:id => id === 't_abcdef' ? {id, key:'DT-41'} : null, detail:t => h('div', {className:'ticket-page'}, 'ticket ' + t.key), missingTicket:id => h('p', {}, 'gone ' + id)});
  const closed = ctx({}, at('#review?card=x'));
  assert.equal(closed.reviewTicketId(), '');
  assert.equal(closed.reviewTicketHref('t_abcdef'), '#review?card=x&ticket=t_abcdef', 'the card the page opened on stays');
  const layout0 = nodes(closed.reviewPage()).find(n => n.attrs?.['data-key'] === 'review-layout');
  assert.equal(layout0.attrs.className, 'review-layout');
  assert.deepEqual(layout0.children.map(n => n.attrs['data-key']), ['review-main', 'review-rail'], 'closed: the card before the list in the page (W-036); the master stands the list on the left');
  const c = ctx({}, at('#review?ticket=t_abcdef'));
  assert.equal(c.reviewTicketId(), 't_abcdef');
  assert.equal(c.reviewTicketHref(''), '#review', 'Close drops only the ticket');
  const layout = nodes(c.reviewPage()).find(n => n.attrs?.['data-key'] === 'review-layout');
  assert.equal(layout.attrs.className, 'review-layout with-ticket');
  const panel = layout.children[0];
  assert.equal(panel.attrs['data-key'], 'review-ticket', 'the ticket on the left');
  assert.match(text(panel), /ticket DT-41/, 'drawn by the ticket page\'s own detail()');
  const links = nodes(panel).filter(n => n.tag === 'a');
  assert.deepEqual(links.map(a => a.attrs.href), ['#ticket/t_abcdef', '#review']);
  assert.ok(nodes(layout).some(n => n.attrs?.['data-key'] === 'review-host'), 'the deck stays on the page');
  assert.match(text(nodes(ctx({}, at('#review?ticket=t_zzzzzz')).reviewPage()).find(n => n.attrs?.['data-key'] === 'review-ticket')), /gone t_zzzzzz/);
  assert.equal(ctx({}, at('#review?ticket=../x')).reviewTicketId(), '', 'only a ticket id');
  assert.equal(ctx({}, {...at('#review?ticket=t_abcdef'), snapshot:true}).reviewPage().children.flat().some(n => nodes(n).some(m => m.attrs?.['data-key'] === 'review-ticket')), false, 'not in a shared copy');
});
test('ORCH-1804: the deck gets the "Open ticket" address, and an open panel follows the card on screen', () => {
  const calls = [], moved = [];
  const c = ctx({}, {location:{hash:'#review?ticket=t_abcdef'}, snapshot:false, array:v => Array.isArray(v) ? v : [], setTimeout(){}, render(){},
    history:{state:null, replaceState:(s, t, url) => moved.push(url)}, window:{DashHelpers:helpers, UI:{reviewPage:(host, api, o) => { calls.push(o); return {destroy() {}, tick() {}}; }}}});
  const host = h('div'), main = {querySelectorAll: sel => sel === '[data-review-host]' ? [host] : [], querySelector: () => h('div')};
  c.mountReview(main);
  assert.equal(calls[0].ticketPanel('t_abc999'), '#review?ticket=t_abc999');
  calls[0].onChange({items:[{id:'a', ticketId:'t_abcdef'}, {id:'b', ticketId:'t_abc999'}], index:0, answers:{}});
  assert.deepEqual(moved, [], 'same ticket: nothing moves');
  calls[0].onChange({items:[{id:'a', ticketId:'t_abcdef'}, {id:'b', ticketId:'t_abc999'}], index:1, answers:{}});
  assert.deepEqual(moved, ['#review?ticket=t_abc999']);
  c.location.hash = '#review';
  calls[0].onChange({items:[{id:'a', ticketId:'t_abcdef'}], index:0, answers:{}});
  assert.equal(moved.length, 1, 'closed: the card never opens it');
});

// ORCH-2185 (Focused review D, behind workflow.decision_first): the panel beside the card has Ticket, Chat and
// "What the helper does" ("Terminal" with the plain terminal's typing on); it keeps its tab when it follows the card,
// "Ask about this" opens Chat with "About: <the decision>" and Run it on a sign-in shows the terminal in the panel.
const jeq = (a, b, m) => assert.equal(JSON.stringify(a), JSON.stringify(b), m);
const panelCtx = (hash, settings = {decision_first_on:true}, more = {}) => ctx({settings, runs:more.runs || {}}, {location:{hash}, snapshot:false, array:v => Array.isArray(v) ? v : [], history:{state:null, replaceState(){}},
  ticketOf:id => id === 't_abcdef' ? {id, key:'DT-41', status:more.status || 'open', history:[]} : null, detail:t => h('div', {className:'ticket-page'}, 'ticket ' + t.key), missingTicket:id => h('p', {}, 'gone ' + id),
  tcItems:() => more.items || [], tcGroupOf:() => null, tcLine:item => h('article', {}, 'line ' + item.e.text), tcAnswer:item => h('article', {}, 'answer ' + item.q.answer),
  tcLineShell:(item, prev, g, ...b) => h('article', {}, ...b), ...more.extra});
const panelOf = c => nodes(c.reviewPage()).find(n => n.attrs?.['data-key'] === 'review-ticket');
test('ORCH-2185: off, the panel is as before; on, three tabs and the address keeps the tab', () => {
  assert.match(text(panelOf(panelCtx('#review?ticket=t_abcdef&tab=chat', {}))), /^Ticket/, 'switch off: the heading, the ticket page, no tabs');
  assert.equal(panelCtx('#review?ticket=t_abcdef&tab=chat', {}).reviewPanelTab(), 'ticket');
  const c = panelCtx('#review?card=x&ticket=t_abcdef');
  const tabs = nodes(panelOf(c)).find(n => n.attrs?.['data-key'] === 'review-ticket-tabs');
  const links = nodes(tabs).filter(n => n.tag === 'a');
  jeq(links.map(text), ['Ticket', 'Chat', 'What the helper does']);
  jeq(links.map(a => a.attrs.href), ['#review?card=x&ticket=t_abcdef', '#review?card=x&ticket=t_abcdef&tab=chat', '#review?card=x&ticket=t_abcdef&tab=helper']);
  assert.equal(links[0].attrs['aria-current'], 'true');
  assert.match(text(panelOf(c)), /ticket DT-41/, 'the Ticket tab is the ticket page');
  jeq(nodes(panelOf(panelCtx('#review?ticket=t_abcdef', {decision_first_on:true, terminal_typing_on:true}))).filter(n => n.attrs?.['data-key'] === 'review-tab-helper').map(text), ['Terminal'], 'Terminal only with the plain terminal setting on');
  assert.equal(c.reviewTicketHref('t_abcdef', 'helper', 't_term01'), '#review?card=x&ticket=t_abcdef&tab=helper&term=t_term01');
  assert.equal(c.reviewTicketHref('t_abcdef', 'chat', 't_term01'), '#review?card=x&ticket=t_abcdef&tab=chat', 'a terminal only on the helper tab');
  assert.equal(panelCtx('#review?ticket=t_abcdef&tab=helper&term=t_term01').reviewTicketHref(''), '#review', 'Close drops the ticket, its tab and terminal');
  assert.equal(panelCtx('#review?ticket=t_abcdef&tab=evil').reviewPanelTab(), 'ticket', 'only the three tabs');
});
test('ORCH-2185: the Chat tab shows the chat lines, open questions as plain lines and the message box; closed: no box', () => {
  const items = [{kind:'line', key:'h1', at:'2026-11-26T09:00:00Z', e:{by:'human:me', text:'Keep it short'}}, {kind:'question', key:'q-q1', at:'2026-11-26T10:00:00Z', q:{id:'q1', text:'Send it today?'}}];
  const p = panelOf(panelCtx('#review?ticket=t_abcdef&tab=chat', undefined, {items}));
  assert.match(text(p), /line Keep it short/);
  assert.match(text(p), /Send it today\?/);
  assert.ok(nodes(p).some(n => n.attrs?.['data-review-chat-box'] === 't_abcdef'), 'the message box host');
  const closed = panelOf(panelCtx('#review?ticket=t_abcdef&tab=chat', undefined, {status:'done'}));
  assert.ok(!nodes(closed).some(n => n.attrs?.['data-review-chat-box']), 'a closed ticket takes no reply');
  assert.match(text(closed), /No messages yet/);
});
test('ORCH-2185: the helper tab: the live screen, the plain terminal Run it started, or a plain empty state', () => {
  const live = panelOf(panelCtx('#review?ticket=t_abcdef&tab=helper', undefined, {runs:{t_abcdef:{running:true, claim:{mode:'tmux'}}}}));
  assert.ok(nodes(live).some(n => n.attrs?.['data-review-term'] === 't_abcdef'));
  const oneshot = panelOf(panelCtx('#review?ticket=t_abcdef&tab=helper', undefined, {runs:{t_abcdef:{running:true, claim:{mode:'oneshot'}}}}));
  assert.match(text(oneshot), /No helper works on this now/, 'a one-step helper has no live screen');
  const term = panelOf(panelCtx('#review?ticket=t_abcdef&tab=helper&term=t_term01'));
  const host = nodes(term).find(n => n.attrs?.['data-review-term']);
  assert.equal(host.attrs['data-review-term'], 't_term01'); assert.equal(host.attrs['data-review-plain'], 'yes');
  assert.doesNotMatch(text(term), /session/i, 'never "session" on screen');
});
test('ORCH-2185: More gets Ask about this (and Watch the helper with a live helper); Ask prefills the box once', () => {
  const off = panelCtx('#review', {});
  jeq(off.reviewMoreItems({ticketId:'t_abcdef'}), [], 'switch off: nothing');
  const c = panelCtx('#review', undefined, {runs:{t_abcdef:{running:true, claim:{}}}});
  const items = c.reviewMoreItems({id:'core:q:t_abcdef:q1', ticketId:'t_abcdef', text:'Send the newsletter today?'});
  jeq(items.map(i => i.label), ['Ask about this', 'Watch the helper']);
  jeq(items.map(i => i.href), ['#review?ticket=t_abcdef&tab=chat', '#review?ticket=t_abcdef&tab=helper']);
  jeq(panelCtx('#review').reviewMoreItems({ticketId:'t_abcdef'}).map(i => i.label), ['Ask about this'], 'no live helper: no Watch');
  items[0].onClick();
  assert.equal(vm.runInContext('reviewChatDrafts', c).get('t_abcdef'), 'About: Send the newsletter today?\n');
  vm.runInContext('reviewChatDrafts', c).set('t_abcdef', 'my own words');
  items[0].onClick();
  assert.equal(vm.runInContext('reviewChatDrafts', c).get('t_abcdef'), 'my own words', 'never over words already typed');
});
test('ORCH-2185: the panel keeps its tab when it follows the card; Run it opens the terminal in the panel', () => {
  const moved = [];
  const c = panelCtx('#review?ticket=t_abcdef&tab=chat', undefined, {extra:{setTimeout(){}, history:{state:null, replaceState:(s, t, u) => moved.push(u)}, route:() => ({kind:'review'})}});
  c.reviewTicketFollow({items:[{id:'b', ticketId:'t_abc999'}], index:0, answers:{}});
  jeq(moved, ['#review?ticket=t_abc999&tab=chat']);
  assert.equal(c.reviewPanelRun('t_term01', 't_abcdef'), true);
  assert.equal(c.location.hash, '#review?ticket=t_abcdef&tab=helper&term=t_term01');
  assert.equal(panelCtx('#review', {}, {extra:{route:() => ({kind:'review'})}}).reviewPanelRun('t_term01', 't_abcdef'), false, 'switch off: the live layer as before');
  assert.equal(panelCtx('#review', undefined, {extra:{route:() => ({kind:'review'}), liveLayerPhone:() => true}}).reviewPanelRun('t_term01', 't_abcdef'), false, 'a phone keeps the live layer');
  assert.equal(panelCtx('#home', undefined, {extra:{route:() => ({kind:'home'})}}).reviewPanelRun('t_term01', 't_abcdef'), false, 'Home keeps the live layer');
});
test('ORCH-2316 (R2 A, draft r2-a): the subtitle says how many need you and how many hold up work now', () => {
  const ask = {...CARD, card_kind:{family:'answer', kind:'question', name:'Question', lane:'holds_up'}};
  const look = {...CARD, id:'core:review:t_abcdef', key:'review', card:{kind:'check', title:'Done'}, card_kind:{family:'look', kind:'document', name:'Document', lane:'look'}};
  assert.equal(ctx({review:{cards:[ask, look]}}).reviewSubtitle(), '2 things need you. 1 holds up work now.');
  assert.equal(ctx({review:{cards:[ask, {...ask, id:'core:q:t_abcdef:q4'}, look]}}).reviewSubtitle(), '3 things need you. 2 hold up work now.');
  assert.equal(ctx({review:{cards:[look]}}).reviewSubtitle(), '1 thing needs you.');
});
// ORCH-2339: the heading says cards + listed rows, the Waiting tab the cards, the badge needsToday().count. Whatever the
// core counts must be on the page as a card or as a row of "Also waiting for you", so the three can never drift apart.
test('ORCH-2339: every item the core counts is a card or a listed row (stopped work with no Home row too)', async () => {
  const c = stuckHome();
  const items = [{ticket:'t_abcdef', question:'q3'}, {ticket:'t_aaaa01', question:null},
    {ticket:'t_aaaa02', question:null, stopped:'helper:idle', row:'core:idle:t_aaaa02'},
    // counted by the core, but no row on Home's list (so no stuck card is made for it)
    {ticket:'t_aaaa03', question:null, stopped:'helper:failing', row:'core:failing:t_aaaa03'}];
  c.state.counts = {needs_you:{count:items.length, questions:1, results:1, failed:0, stopped:2, items}};
  c.state.review.cards = c.state.review.cards.slice(0, 2);  // the question and the result of t_aaaa01
  c.needsList = () => [];  // Home lists nothing of the stopped work
  const n = c.needsToday(), cards = (await c.reviewApi().stack()).length;
  assert.equal(n.count, items.length);
  assert.equal(cards + c.reviewExtraRows().length, n.count, 'the heading adds up to the badge');
  assert.equal(c.reviewExtraRows().map(r => r.what).join(), 'stopped,stopped');
});

// ---- Owner's walk of 28 Nov: evidence and cost on the card, the one number, the ticket beside the card ----
test('W-040: a pull request card shows one evidence line (which one, check and merge state, how fresh) with Open, and says what Start helper costs', async () => {
  const c = stuckHome();
  c.needsList().find(r => r.kind === 'helper:unmerged').pull.checked_at = '2026-11-15T11:55:00Z';
  const card = (await c.reviewApi().stack()).find(x => x.ticket === 't_aaaa01' && x.card.kind === 'stuck');
  assert.equal(card.card.why, 'Pull request #12 · checks passed, not merged · passed ' + kit.UI.stamp('2026-11-15T10:00:00Z') + ' · looked at ' + kit.UI.stamp('2026-11-15T11:55:00Z'));
  assert.equal(JSON.stringify(card.links), JSON.stringify([{label:'Open pull request #12', url:'https://github.com/acme/app/pull/12'}]));
  assert.equal(card.card.hint, 'Merge puts the pull request in. Start helper starts paid helper work (cost not known) that asks it to merge or say why it stays open.');
  assert.equal(card.cause, 'helper:unmerged', 'the list folds cards with one cause');
  // a real estimate when the helper gave one, never an invented one
  c.tickets().find(t => t.id === 't_aaaa02').estimate = {minutes:20, cost:1.2};
  const idle = (await c.reviewApi().stack()).find(x => x.ticket === 't_aaaa02');
  assert.match(idle.card.hint, /starts a new helper on this ticket \(this ticket's estimate: about 20 min · \$1\.20\)\.$/);
  assert.doesNotMatch(read('pages/review.js'), /\$1\b|10 min/, 'no fixed estimate in the page');
  // the card reads: what happened, the evidence, what the buttons do and cost (W-042); other stuck cards keep their step line
  assert.equal(idle.card.why, 'Stopped at: Write the guide · 1 of 2 steps done.');
});
test('W-040 / CX-02: a result to review links its pull request with its state, and says that Send back is paid helper work', async () => {
  const check = {...CARD, id:'core:review:t_abcdef', key:'review', card:{kind:'check', title:'Result'}, links:[{label:'Preview', url:'https://example.com/p'}]};
  const t = {id:'t_abcdef', refs:[{url:'https://github.com/acme/app/pull/7', kind:'github-pr', status:'ready to merge'}, {url:'https://example.com/doc'}]};
  const c = ctx({review:{cards:[check, CARD]}}, {ticketOf:id => id === t.id ? t : null});
  const [got, other] = await c.reviewApi().stack();
  assert.equal(JSON.stringify(got.links), JSON.stringify([{label:'Preview', url:'https://example.com/p'}, {label:'Pull request #7 · ready to merge', url:'https://github.com/acme/app/pull/7'}]));
  assert.equal(got.card.hint, 'Send back: sends your changes for a helper to work on · cost not known.');
  assert.equal(other, CARD, 'a question is left as it is');
  t.estimate = {minutes:45, cost:2};
  assert.equal((await c.reviewApi().stack())[0].card.hint, "Send back: sends your changes for a helper to work on · this ticket's estimate: about 45 min · $2.00.");
  assert.equal(check.card.hint, undefined, 'the state itself is not changed');
  // the Reviewer's own row: the Send back box says it above its button
  const row = {ticket:'t_abcdef', key:'DT-41', title:'Fix', why:'merged.', sent_back:false};
  const a = ctx({review:{cards:[], accepted:[row]}}, {ticketOf:() => t, FEEDBACK_BOX:{}, window:{DashHelpers:helpers, UI:{...kit.UI, composer:() => ({field:{focus() {}}, destroy() {}})}, orch:{toast() {}}}});
  const node = a.reviewAcceptedRow(row);
  node.replaceChildren = (...kids) => { node.children = kids; };
  nodes(node).find(n => n.tag === 'button' && text(n) === 'Send back').onclick();
  const kids = node.children.map(text);
  assert.equal(kids[1], "Sends your changes for a helper to work on · this ticket's estimate: about 45 min · $2.00.");
  assert.ok(kids.indexOf(kids[1]) < node.children.findIndex(n => String(n.attrs?.id || '').endsWith('-box')), 'above the box with its button');
});
test('W-003: the subtitle reads the menu badge\'s number, whatever the deck holds at that moment', () => {
  let total = 31;
  const c = ctx({review:{cards:[CARD, {...CARD, id:'core:review:t_abcdef', key:'review'}]}}, {needsYouTotal:() => total});
  assert.match(c.reviewSubtitle(), /^31 things need you\./);
  const sub = {textContent:''}, main = {querySelector:() => sub};
  c.reviewSetWaiting(main, {items:[{id:'a'}, {id:'b'}], answers:{a:{}}});  // the deck says 1 waiting: the heading keeps THE number
  assert.match(sub.textContent, /^31 things need you\./);
  total = 30; c.reviewSetWaiting(main, {items:[{id:'a'}, {id:'b'}], answers:{a:{}}});
  assert.match(sub.textContent, /^30 things need you\./, 'it changes when the badge does');
  total = 0; c.reviewSetWaiting(main, null);
  assert.equal(c.reviewSubtitle(), 'Nothing new needs you. 2 cards you put off are still here.');
  assert.doesNotMatch(read('pages/review.js').slice(read('pages/review.js').indexOf('function reviewSubtitle'), read('pages/review.js').indexOf('// The words the "All cards" list')), /reviewWaiting \+/, 'never the deck count as the heading number');
});
test('W-039: with a ticket open beside the card nothing is pushed in above the decision; what has no card is listed after it', () => {
  const c = ctx({review:{cards:[CARD]}, tickets:[]}, {reviewExtraCard:undefined});
  vm.runInContext("reviewExtraCard = () => h('section', {'data-key':'review-extra'}, 'Also waiting for you')", c);
  const main = nodes(c.reviewPage()).find(n => n.attrs?.['data-key'] === 'review-main');
  assert.deepEqual(main.children.map(n => n.attrs['data-key']), ['review-nav', 'review-host', 'review-extra']);
  const src = read('pages/review.js');
  assert.match(src, /e\.key !== 'Escape'[^\n]*reviewTicketId\(\)/, 'Esc closes the ticket beside the card');
  assert.match(src, /reviewKeepY = .*scrollY/, 'the page stays where it was');
});
test('FX-04: the quiet line under the list says how many wait to be merged', () => {
  const one = ctx({counts:{needs_you:{queue:['t_a']}}, review:{cards:[]}}), two = ctx({counts:{needs_you:{queue:['t_a', 't_b']}}, review:{cards:[]}});
  assert.equal(text(one.reviewQueueLine()), '1 waits to be merged, nothing to do');
  assert.equal(text(two.reviewQueueLine()), '2 wait to be merged, nothing to do');
  assert.equal(ctx({review:{cards:[]}}).reviewQueueLine(), null);
});
test('W-003: a card answered on Review leaves the one count at once (badge, heading, Home), and Undo brings it back', async () => {
  const c = stuckHome();
  let refreshed = 0;
  vm.runInContext('var wantFull = false;', c); c.refresh = () => { refreshed++; };
  c.state.counts = {needs_you:{count:3, questions:1, results:2, failed:0, stopped:0, tickets:[], queue:[],
    items:[{ticket:'t_abcdef', question:'q3'}, {ticket:'t_aaaa01', question:null}, {ticket:'t_aaaa05', question:null}, {ticket:'t_aaaa02', question:null, stopped:'helper:idle', row:'core:idle:t_aaaa02'}]}};
  const before = c.needsYouTotal(), api = c.reviewApi();
  assert.match(c.reviewSubtitle(), new RegExp('^' + before + ' things need you'));
  api.hold({id:'core:q:t_abcdef:q3'}, 'ok');
  assert.equal(c.needsYouTotal(), before - 1, 'the question is out of the number while its answer waits for Undo');
  assert.match(c.reviewSubtitle(), new RegExp('^' + (before - 1) + ' things need you'));
  api.hold({id:'core:review:t_aaaa01'}, 'no');
  assert.equal(c.needsYouTotal(), before - 2, 'a result sent back too');
  api.hold({id:'stuck:core:idle:t_aaaa02'}, 'ok');
  assert.equal(c.needsYouTotal(), before - 2, 'work that stopped is not answered by a button: it stays counted');
  // a new state from the server while the answers wait: still left out
  const next = c.acceptOverlay({...c.state, counts:{needs_you:{...c.state.counts.needs_you, items:[{ticket:'t_abcdef', question:'q3'}, {ticket:'t_aaaa01', question:null}, {ticket:'t_aaaa05', question:null}]}}});
  assert.deepEqual(next.counts.needs_you.items.map(i => i.ticket), ['t_aaaa05']);
  // Undo: the whole state is read again, so every place shows the card again
  api.release({id:'core:q:t_abcdef:q3'});
  assert.ok(refreshed >= 1); assert.equal(c.state.rev, '');
  assert.deepEqual(c.acceptOverlay({counts:{needs_you:{items:[{ticket:'t_abcdef', question:'q3'}, {ticket:'t_aaaa01', question:null}]}}}).counts.needs_you.items.map(i => i.ticket), ['t_abcdef']);
  // saved: nothing more to hide
  await api.answer({id:'core:review:t_aaaa01', digest:ID, verdict:'no'});
  assert.equal(c.acceptOverlay({counts:{needs_you:{items:[{ticket:'t_aaaa01', question:null}]}}}).counts.needs_you.items.length, 1);
});
test('O-04: the layout watcher draws the page again only when the layout really changed (the shell writes its marks at every paint)', () => {
  let renders = 0;
  const body = {dataset:{}};
  const c = ctx({review:{cards:[]}}, {document:{addEventListener(){}, getElementById:() => null, body}, route:() => ({kind:'review'}), render:() => { renders++; c.reviewPage(); }});
  assert.equal(c.reviewLayoutChanged(), false, 'before the first paint there is nothing to redo');
  c.reviewPage();
  assert.equal(c.reviewLayoutChanged(), false); assert.equal(renders, 0, 'the same layout: no paint');
  body.dataset.liveNarrow = '';
  assert.equal(c.reviewLayoutChanged(), true); assert.equal(renders, 1, 'the Focus panel took the room: one paint');
  for (let i = 0; i < 5; i++) c.reviewLayoutChanged();  // the shell writes the same mark again at every paint
  assert.equal(renders, 1, 'a mark written again starts no paint');
  delete body.dataset.liveNarrow; body.dataset.liveStack = '';
  assert.equal(c.reviewLayoutChanged(), false, 'still one column');
  delete body.dataset.liveStack;
  assert.equal(c.reviewLayoutChanged(), true); assert.equal(renders, 2);
  const other = ctx({review:{cards:[]}}, {document:{addEventListener(){}, getElementById:() => null, body:{dataset:{liveNarrow:''}}}, route:() => ({kind:'home'}), render:() => { renders++; }});
  other.reviewPage(); delete other.document.body.dataset.liveNarrow;
  assert.equal(other.reviewLayoutChanged(), false, 'another page is on screen');
});
test('W-039: the keyboard moves only when the ticket panel opens or closes, and a scroll kept for a click is used once and soon', () => {
  const focused = [], timers = [];
  const at = hash => ({location:{hash, origin:'', pathname:'/'}});
  const c = ctx({review:{cards:[]}}, {...at('#review'), setTimeout:fn => timers.push(fn), window:{DashHelpers:helpers, UI:kit.UI, orch:{toast(){}}, scrollTo:(x, y) => focused.push('scroll:' + y), scrollY:0}});
  const main = {querySelector:sel => ({focus:() => focused.push(sel)})};
  const run = () => { while (timers.length) timers.shift()(); };
  c.reviewKeepPlace(main); run();
  assert.deepEqual(focused, [], 'the page just opened: nothing moves');
  c.location.hash = '#review?ticket=t_abcdef'; c.reviewKeepPlace(main); run();
  assert.deepEqual(focused, ['[data-key="review-ticket-close"]'], 'opened: to the panel');
  c.location.hash = '#review?ticket=t_aaaa01'; c.reviewKeepPlace(main); run();
  assert.equal(focused.length, 1, 'the panel followed the next card: the keyboard stays on the deck');
  c.location.hash = '#review'; c.reviewKeepPlace(main); run();
  assert.equal(focused[1], '[data-review-host] .swipe-more summary', 'closed: back to the card');
  vm.runInContext('reviewKeepY = {y:240, at:Date.now()}', c); c.reviewKeepPlace(main); run();
  assert.equal(focused[2], 'scroll:240');
  c.reviewKeepPlace(main); run(); assert.equal(focused.length, 3, 'used once');
  vm.runInContext('reviewKeepY = {y:99, at:Date.now() - 5000}', c); c.reviewKeepPlace(main); run();
  assert.equal(focused.length, 3, 'an old one is dropped');
});
