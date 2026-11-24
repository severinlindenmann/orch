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
  assert.match(c.reviewSubtitle(), /^2 things wait on you, most urgent first\.$/);
  const api = c.reviewApi();
  return Promise.all([api.stack(), api.answered()]).then(([s, a]) => { assert.equal(s.length, 2); assert.equal(a.length, 1); assert.equal(api.workspace, 'Demo'); });
});
test('one card and none: plain words', () => {
  assert.match(ctx({review:{cards:[CARD]}}).reviewSubtitle(), /^1 thing waits on you/);
  assert.equal(ctx({}).reviewSubtitle(), 'Nothing waits for you.');
  assert.equal(ctx({}).reviewCount(), 0);
});
test('fileUrl serves only reviewed/<sha12>/<name> through /api/file', () => {
  const f = ctx({}).reviewApi().fileUrl;
  assert.equal(f(CARD, 'reviewed/0123456789ab/after.png'), '/api/file?t=t_abcdef&k=reviewed&n=0123456789ab%2Fafter.png');
  for (const bad of ['reviewed/0123456789ab/../x.png', 'reviewed/0123456789ab/a/b.png', 'reviewed/XYZ/x.png', '', null, 'https://evil/x.png', 'artifacts/../x.png', 'evidence/a/../../x.png', 'evidence/.orch/x.png', 'secrets/x.png', 'evidence/a\\b.png']) assert.equal(f(CARD, bad), '', String(bad));
  assert.equal(f({}, 'reviewed/0123456789ab/after.png'), '');
});
test('a Check result opens its own files: pictures and PDFs through /api/file, a page only in its /view frame (ORCH-183)', () => {
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
// ORCH-477 round 2 (owner sent back): the list is the kit's (deck.drawList: rows, groups, Compare mode); the page only
// hands it the queue and keeps it on the left. The kit's swipe-deck tests cover the rows and Compare mode.
test('the All cards list is drawn by the kit into the queue, on the left of the deck (ORCH-477)', () => {
  const c = ctx({});
  const drawn = [], queue = h('div'), deck = {drawList:q => drawn.push(q)};
  c.reviewDrawSide(queue, deck);
  assert.deepEqual(drawn, [queue]);
  assert.doesNotThrow(() => c.reviewDrawSide(null, deck));
  assert.doesNotThrow(() => c.reviewDrawSide(queue, {}), 'an old deck without the list draws nothing');
  const page = nodes(c.reviewPage()), layout = page.find(n => n.attrs?.['data-key'] === 'review-layout');
  assert.equal(layout.children[0].attrs['data-key'], 'review-rail', 'the list is on the left');
  const side = page.find(n => n.attrs?.['data-review-side'] !== undefined);
  assert.equal(side.attrs['aria-label'], 'All cards');
  assert.deepEqual(side.children.map(n => n.attrs['data-review-queue']), [''], 'no tick hint and no heading of its own: the kit draws them');
});
test('the page keeps its host and side list out of the reconcile (mounted once), and leaving destroys the page', () => {
  const calls = [];
  const c = ctx({}, {window:{DashHelpers:helpers, UI:{reviewPage:(host, api, o) => { calls.push(o); return {destroy() { calls.push('destroy'); }, tick() {}}; }}}});
  const host = h('div'), side = h('aside'), queue = h('div');
  const main = {querySelectorAll: sel => sel === '[data-review-host]' ? [host] : sel === '[data-review-side]' ? [side] : [], querySelector: () => queue};
  c.mountReview(main); c.mountReview(main);
  assert.equal(calls.length, 1, 'mounted once'); assert.equal(calls[0].poll, 3000); assert.equal(typeof calls[0].onChange, 'function');
  assert.ok(c.mounts.has(host) && c.mounts.has(side));
  c.mounts.get(host).destroy(); assert.equal(calls.at(-1), 'destroy');
});
// ---- Home and ticket ----
function home(state, tickets = [], rows = []) {
  const c = ctx(state, {tickets:() => tickets, ticketOf:id => tickets.find(t => t.id === id), href:id => '#ticket/' + id, needsList:() => rows});
  vm.runInContext(read('pages/ticket.js'), c); vm.runInContext(read('pages/home.js'), c);
  return c;
}
test('"Review all" is a link to #review with the card count, and never changes the Home total', () => {
  const rows = [{id:'n1', ticket:'t_abcdef', since:'2026-11-15T09:00:00Z', title:'Home block', answer:{question:'q3', digest:ID, options:[]}}];
  const base = {settings:{}, runs:{}, services:[]};
  const tickets = [{id:'t_abcdef', title:'Newsletter', status:'waiting', questions:[{id:'q3', text:'Home block'}]}];
  const withCards = home({...base, review:{cards:[CARD], answered:[]}}, tickets, rows), without = home({...base}, tickets, rows);
  const a = withCards.reviewAllButton();
  assert.equal(a.tag, 'a'); assert.equal(a.attrs.href, '#review'); assert.match(text(a), /^Review all$/);  // no number: only the Review badge shows it (ORCH-1616)
  assert.equal(without.reviewAllButton(), null, 'no cards, no button');
  assert.equal(withCards.reviewCount(), 1);
  assert.equal(withCards.needsToday().count, without.needsToday().count, 'cards are the questions and results Home already counts');
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
  assert.equal(c.reviewSubtitle(), '2 things wait on you, most urgent first.');
  // owner 16 Nov: the number is open questions plus results to check, so it equals the cards here. A helper idle at its
  // prompt, or a ticket that only waits for another ticket, has no card and is not counted.
  const idle = {id:'core:stuck:t_ccccdd', source:'core', kind:'stuck:idle', ticket:'t_ccccdd', since:'2026-11-15T11:00:00Z', title:'Docs', text:'The helper waits at its prompt', tone:'warn'};
  const waits = {id:'t_ddddee', title:'Later', status:'waiting', waiting_on:{kind:'ticket', ref:'t_abcdef'}, questions:[]};
  const check = {...CARD, id:'core:review:t_eeeeff', ticket:'t_eeeeff', key:'review', kind:'check', card:{kind:'check', title:'Report'}};
  const cards = [CARD, factory, check];
  const more = home({...base, review:{cards, answered:[]}}, [t1, t2, {id:'t_ccccdd', title:'Docs', status:'active', questions:[]}, waits, {id:'t_eeeeff', title:'Report', status:'review', questions:[]}], [...rows, idle]);
  assert.equal(more.needsToday().count, 3); assert.equal(more.needsToday().count, more.reviewCount());
  assert.equal(more.reviewSubtitle(), '3 things wait on you, most urgent first.');
  assert.equal(home({...base, review:{cards:[], answered:[]}}, [], []).reviewSubtitle(), 'Nothing waits for you.');
});
test('ORCH-63: the dashboard sends the one count to the shown add-on page of its own (Focus), and on request', () => {
  const src = read('app.js');
  assert.match(src, /postMessage\(\{type:'orch\.needs\.count', count:n\}, '\*'\)/);  // to the sandboxed frame only
  assert.match(src, /const needCount = needsYouTotal\(\)[^\n]*\n[\s\S]{0,400}postNeedsCount\(needCount\);/);
  assert.match(src, /e\.data\?\.orch !== 'needs-count'/);
  assert.match(src, /\.shipped\) return null;/, 'only an add-on orch ships gets the number');
});
test('"Review all" is not shown in a shared copy', () => {
  assert.ok(home({review:{cards:[CARD]}}).reviewAllButton());
  const c = home({review:{cards:[CARD]}}); c.snapshot = true; assert.equal(c.reviewAllButton(), null);
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
  assert.match(c.reviewSubtitle(), /^1 thing waits on you/);
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
  // the page keeps the card beside the "All cards" aside, not inside it (the aside hides on a phone)
  const page = nodes(c.reviewPage());
  const side = page.find(n => n.attrs?.['data-review-side'] !== undefined), rail = page.find(n => n.attrs?.['data-key'] === 'review-rail');
  assert.ok(rail && !nodes(side).some(n => n.attrs?.['data-key'] === 'review-accepted') && nodes(rail).some(n => n.attrs?.['data-key'] === 'review-accepted'));
  // the send: ticket.changes with the note, then the row reads "Sent back"
  assert.equal(await c.reviewSendBack(row('t_aaaa11'), '   '), false, 'an empty note sends nothing');
  assert.equal(c.acts.length, 0);
  assert.equal(await c.reviewSendBack(row('t_aaaa11'), ' Keep the old name '), true);
  assert.deepEqual(JSON.parse(JSON.stringify(c.acts[0])), ['ticket.changes', {ticket:'t_aaaa11', text:'Keep the old name'}]);
  assert.equal(nodes(c.reviewAcceptedCard()).filter(n => n.tag === 'button').length, 0);
});
test('ORCH-288: Review all, the Home title, the Needs you pill and the subtitle say one number', () => {
  const base = {settings:{}, runs:{}, services:[], review:{cards:[CARD, CARD], answered:[]}};
  const rows = [{id:'n1', ticket:'t_abcdef', since:'2026-11-15T09:00:00Z', title:'A', answer:{question:'q1', digest:ID, options:[]}}];
  const tickets = [{id:'t_abcdef', title:'News', status:'waiting', questions:[{id:'q1', text:'A'}]}, {id:'t_ghijkl', title:'Done work', status:'review'}];
  const c = home(base, tickets, rows), total = c.needsYouTotal();
  assert.equal(total, 2);  // one question + one result to check, not the two cards
  assert.equal(text(c.reviewAllButton()), 'Review all');  // the number only on the Review badge (ORCH-1616)
  assert.equal(c.attentionSummary(c.needsToday().groups, [], 1, 0), '1 question · 1 result to check');
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
  assert.deepEqual(sw.map(n => [n.attrs['data-action'], n.attrs['aria-checked']]), [['auto-reviewer-set', false], ['away-set', true]]);
  const rail = nodes(c.reviewPage()).find(n => n.attrs?.['data-key'] === 'review-rail');
  assert.ok(nodes(rail).some(n => n.attrs?.['data-key'] === 'review-auto'));
  await c.reviewSwitch('auto');
  await c.reviewSwitch('away');
  assert.deepEqual(JSON.parse(JSON.stringify(c.acts)), [['auto_reviewer.set', {on:true}], ['away.set', {on:false}]]);
  assert.equal(ctx({review:{cards:[]}}).reviewAutoCard(), null, 'no settings (a read-only copy): no switches');
  const snap = ctx({settings:{}}, {snapshot:true});
  assert.ok(nodes(snap.reviewAutoCard()).filter(n => n.attrs?.role === 'switch').every(n => n.attrs.disabled));
  assert.equal(await snap.reviewSwitch('auto'), null);
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
  assert.equal(c.reviewSubtitle(), n.count + ' things wait on you, most urgent first.');
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
  assert.equal(JSON.stringify(rows.map(r => [r.t.id, r.what, r.text])), JSON.stringify([['t_abcdef', 'question', 'Which logo?'], ['t_ghijkl', 'result', 'A result to check.']]));
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
