'use strict';
// ORCH-687: the chat view of a ticket's session in Focus (pages/livechat.js). The model turns the ticket the page
// already has into one conversation: step events, the helper's summaries and questions, your answers and messages.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const web = path.join(__dirname, '../src/orch_dashboard/web');
const source = fs.readFileSync(path.join(web, 'pages/livechat.js'), 'utf8');
const model = source.slice(0, source.indexOf('// --- the page ---'));
const ctx = {};
vm.createContext(ctx);
vm.runInContext(model + '\nthis.api = {liveChatModel, liveTalkReal, liveChatSplit, liveChatMine, liveViewRead, liveViewWrite, liveChatParts, liveCmdTyped, LIVE_CHAT_MAX, LIVE_CHAT_TEXT, LIVE_VIEW_KEY};', ctx);
const C = ctx.api;
const plain = x => JSON.parse(JSON.stringify(x));

const ticket = () => ({
  id: 't_1',
  checklist: [
    {id: 'c1', text: 'Files can be dropped on a ticket', done: true, evidence: [
      {type: 'note', ref: 'ran tests', summary: 'Uploading works for pictures, pages and tables.', by: 'agent:claude', at: '2026-11-19T14:21:00Z'},
      {type: 'pr', ref: 'https://github.com/o/r/pull/12', by: 'agent:claude', at: '2026-11-19T14:21:00Z'}]},
    {id: 'c2', text: 'Notes below the files', done: false, evidence: []},
  ],
  questions: [
    {id: 'q1', text: 'Keep the old file name?', options: ['Keep', 'New'], answer: 'Keep', answered_by: 'human:lume', asked_at: '2026-11-19T14:52:00Z', answered_at: '2026-11-19T14:55:00Z'},
    {id: 'q2', text: 'Send it now?', options: ['Yes', 'No'], answer: null, asked_at: '2026-11-19T15:10:00Z'},
  ],
  history: [
    {at: '2026-11-19T14:00:00Z', by: 'agent:factory', text: 'Claude started', chat_message: false},
    {at: '2026-11-19T14:05:00Z', by: 'agent:claude', text: 'Added check c1', chat_message: false},
    {at: '2026-11-19T14:30:00Z', by: 'human:anna', text: 'Please also try a PDF.', chat_message: true},
    {at: '2026-11-19T15:20:00Z', by: 'human:lume', text: 'Status active -> review', chat_message: false},
  ],
});

test('a ticket reads as one conversation, oldest first: events, helper messages and your words', () => {
  const rows = plain(C.liveChatModel(ticket(), 'human:lume'));
  assert.deepEqual(rows.map(r => [r.w, r.text]), [
    ['e', 'The helper started'],
    ['e', 'Step 1 done: Files can be dropped on a ticket'],
    ['h', 'Uploading works for pictures, pages and tables.'],
    ['y', 'Please also try a PDF.'],
    ['h', 'Keep the old file name?'],
    ['y', 'Keep'],
    ['e', 'Moved to Review by Lume'],
  ]);
  assert.deepEqual(rows[2].links, [{href: 'https://github.com/o/r/pull/12', label: 'Pull request 12'}], 'the step\'s pull request sits in its message');
  assert.equal(rows[3].who, 'Anna', 'another person is named');
  assert.equal(rows[5].who, '', 'your own answer says You');
});

test('the open question is not a message: the pane shows it as its card', () => {
  const rows = C.liveChatModel(ticket(), 'human:lume');
  assert.ok(!rows.some(r => r.text === 'Send it now?'));
});

test('an answer given for you by a program is an event, not your message', () => {
  const t = ticket();
  t.questions[0].answered_by = 'agent:reviewer';
  const rows = plain(C.liveChatModel(t, 'human:lume'));
  assert.deepEqual(rows.find(r => r.text.startsWith('Answered')), {w: 'e', text: 'Answered for you: Keep', at: '2026-11-19T14:55:00Z'});
});

test('technical history lines stay on the ticket; a step without a time is left out', () => {
  const t = ticket();
  t.history.push({at: '2026-11-19T15:30:00Z', by: 'agent:claude', text: 'pull-requests refresh: github.com/o/r/pull/12 title', chat_message: false});
  t.checklist[1] = {id: 'c2', text: 'No time', done: true, evidence: [{type: 'note', ref: 'x'}]};
  const rows = C.liveChatModel(t, 'human:lume');
  assert.ok(!rows.some(r => /refresh|No time/.test(r.text)));
});

test('a message sent from this page shows as yours at once', () => {
  const rows = plain(C.liveChatModel(ticket(), 'human:lume', [{text: 'Try a PDF too', at: '2026-11-19T15:40:00Z'}]));
  assert.deepEqual(rows.at(-1), {w: 'y', text: 'Try a PDF too', at: '2026-11-19T15:40:00Z', sent: true});
});

test('long words are cut and the newest rows are kept', () => {
  const t = {checklist: [], questions: [], history: []};
  for (let i = 0; i < C.LIVE_CHAT_MAX + 5; i++) t.history.push({at: new Date(Date.UTC(2026, 10, 19, 10, i)).toISOString(), by: 'agent:claude', text: 'line ' + i, chat_message: true});
  t.history[t.history.length - 1].text = 'x'.repeat(C.LIVE_CHAT_TEXT + 50);
  const rows = C.liveChatModel(t, '');
  assert.equal(rows.length, C.LIVE_CHAT_MAX);
  assert.equal(rows[0].text, 'line 5');
  assert.equal(rows.at(-1).text.length, C.LIVE_CHAT_TEXT);
  assert.ok(rows.at(-1).text.endsWith('…'));
});

test('no ticket, no rows; broken entries are skipped', () => {
  assert.equal(C.liveChatModel(null).length, 0);
  assert.equal(C.liveChatModel({checklist: [null, 3], questions: ['x'], history: [null, {at: 'never', text: 'Claude started'}]}).length, 0);
});

test('only an address opens as a link; other evidence refs are not links', () => {
  const t = ticket();
  t.checklist[0].evidence.push({type: 'url', ref: 'javascript:alert(1)', at: '2026-11-19T14:21:00Z'});
  const links = C.liveChatModel(t, '').find(r => r.links)?.links;
  assert.equal(links.length, 1);
});

test('Chat or Terminal is kept per browser; chat is the default and broken data reads as nothing', () => {
  const m = new Map(), store = {getItem: k => m.get(k) ?? null, setItem: (k, v) => m.set(k, v)};
  assert.deepEqual(plain(C.liveViewRead(store)), {});
  C.liveViewWrite(store, {t_1: 'term'});
  assert.deepEqual(plain(C.liveViewRead(store)), {t_1: 'term'});
  m.set(C.LIVE_VIEW_KEY, '{"t_2":"chat","t_3":"term","":"term"}');
  assert.deepEqual(plain(C.liveViewRead(store)), {t_3: 'term'});
  m.set(C.LIVE_VIEW_KEY, 'not json');
  assert.deepEqual(plain(C.liveViewRead(store)), {});
  assert.deepEqual(plain(C.liveViewRead(null)), {});
});

test('the page loads the chat before the layer that uses it and the server serves it', () => {
  const html = fs.readFileSync(path.join(web, 'index.html'), 'utf8');
  const chat = html.indexOf('pages/livechat.js'), layer = html.indexOf('pages/live-layer.js');
  assert.ok(chat > 0 && chat < layer);
  assert.match(fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/server.py'), 'utf8'), /\|livechat[|)]/, 'the server serves it');
});

// ORCH-695: what the person sent stays after a reload (orch's run status sent_input), with the files it carried.
test('a sent message comes back from orch after a reload, with its files apart from its words', () => {
  const run = {sent_input: [
    {id: 'p_1', text: 'Please also try a PDF.', at: '2026-11-19T15:00:00Z', by: 'human:lume', read: true},
    {id: 'p_2', text: 'Here are two\n\nI added 2 files to this ticket: shot-1402.png, notes.md. Read them first.', at: '2026-11-19T15:05:00Z', by: 'human:lume', read: false},
    {id: 'p_3', text: 'I added a file to this ticket: only.png. Read it and carry on.', at: '2026-11-19T15:06:00Z', by: 'human:anna'}]};
  const rows = plain(C.liveChatModel({}, 'human:lume', C.liveChatMine(run, [])));
  assert.deepEqual(rows.map(r => [r.w, r.text, r.files || [], r.who || '']), [
    ['y', 'Please also try a PDF.', [], ''],
    ['y', 'Here are two', ['shot-1402.png', 'notes.md'], ''],
    ['y', '', ['only.png'], 'Anna']]);
});

test('what this page just sent shows until orch lists the same words, never twice', () => {
  const local = [{text: 'Please also try a PDF.', at: '2026-11-19T15:00:01Z'}, {text: 'Not listed yet', at: '2026-11-19T15:01:00Z'}];
  assert.equal(C.liveChatMine({}, local).length, 2);
  const both = C.liveChatMine({sent_input: [{id: 'p_1', text: 'Please also try a PDF.', at: '2026-11-19T15:00:00Z', by: 'human:lume'}]}, local);
  assert.deepEqual(plain(both).map(m => m.text), ['Please also try a PDF.', 'Not listed yet']);
  assert.equal(C.liveChatMine({sent_input: 'broken'}, null).length, 0);
});

test('only orch\'s own file line is split off; other words stay as they are', () => {
  assert.deepEqual(plain(C.liveChatSplit('I added a file to this ticket.')), {text: 'I added a file to this ticket.', files: []});
  assert.deepEqual(plain(C.liveChatSplit('Long one\n\nI added 3 files to this ticket. Read them first.')), {text: 'Long one\n\nI added 3 files to this ticket. Read them first.', files: []});
  assert.deepEqual(plain(C.liveChatSplit('Voice\n\nI added a file to this ticket: v.webm. The voice note came without written words. Read it first.')), {text: 'Voice', files: ['v.webm']});
});

test('ORCH-1755: the file line of a helper without a ticket names its folder and is split off the same way', () => {
  assert.deepEqual(plain(C.liveChatSplit('Look\n\nI added a file to .orch/tickets/t_mgr001/artifacts: shot.png. Read it first.')), {text: 'Look', files: ['shot.png']});
  assert.deepEqual(plain(C.liveChatSplit('I added 2 files to .orch/tickets/t_mgr001/artifacts: a.png, b.md. Read them and carry on.')), {text: '', files: ['a.png', 'b.md']});
  assert.equal(C.liveChatSplit('I added a file to some/other/place: x.png. Read it first.').files.length, 0);
});

test('a Chat line a person wrote shows once, though orch also queued it for the helper', () => {
  const msg = {id: 'p_123456', by: 'human:lume', text: 'Please check the draft', at: '2026-11-19T12:00:00Z'};
  const rows = C.liveChatModel({history: [{...msg, chat_message: true}]}, 'human:lume', C.liveChatMine({sent_input: [msg]}, []));
  assert.equal(rows.length, 1);
});

test('ORCH-2203: one-line code blocks, code lines and !commands become commands; several lines stay text', () => {
  const p = x => plain(C.liveChatParts(x));
  assert.deepEqual(p('Start it with:\n```\ndatabricks jobs run-now 5 --profile x\n```\nThen wait.'),
    [{t: 'text', text: 'Start it with:'}, {t: 'cmd', text: 'databricks jobs run-now 5 --profile x'}, {t: 'text', text: 'Then wait.'}]);
  assert.deepEqual(p('Run\n`npm test`'), [{t: 'text', text: 'Run'}, {t: 'cmd', text: 'npm test'}]);
  assert.deepEqual(p('!git status'), [{t: 'cmd', text: '!git status'}]);
  assert.deepEqual(p('Use `npm test` here'), [{t: 'text', text: 'Use `npm test` here'}]);
  assert.deepEqual(p('```\na\nb\n```'), [{t: 'text', text: 'a\nb'}]);
  assert.deepEqual(p('plain words'), [{t: 'text', text: 'plain words'}]);
  assert.deepEqual(p('```\nunclosed'), [{t: 'text', text: '```\nunclosed'}]);
});

test('ORCH-2203: a !command loses its ! in a plain terminal and keeps it for the helper; Enter is never added', () => {
  assert.equal(C.liveCmdTyped('!git status', true), 'git status');
  assert.equal(C.liveCmdTyped('!git status', false), '!git status');
  assert.equal(C.liveCmdTyped('ls -la', true), 'ls -la');
});

// ORCH-2204: the helper's real conversation, where orch can read it, gives the helper's words
test('with the real conversation the helper speaks in its own words; the step summary goes, its links stay', () => {
  const talk = {available: true, turns: [
    {w: 'h', text: 'I read the ticket and start with the upload.', at: '2026-11-19T14:10:00Z'},
    {w: 'y', text: 'Typed in the terminal', at: '2026-11-19T14:12:00Z'},
    {w: 'h', text: 'x'.repeat(2500), at: '2026-11-19T14:20:00Z'},
    {w: 'e', text: 'not a turn', at: '2026-11-19T14:20:00Z'},
    {w: 'h', text: 'no time', at: 'nope'},
  ]};
  const rows = plain(C.liveChatModel(ticket(), 'human:lume', [], talk));
  const talked = rows.filter(r => r.talk);
  assert.deepEqual(talked.map(r => r.w), ['h', 'y', 'h']);
  assert.equal(talked[0].text, 'I read the ticket and start with the upload.');
  assert.equal(talked[2].text.length, 2000);
  assert.ok(talked[2].text.endsWith('…'));
  assert.ok(!rows.some(r => r.text === 'Uploading works for pictures, pages and tables.'), 'the summary is not the helper talking');
  const step = rows.find(r => r.step === 'c1');
  assert.equal(step.text, '');
  assert.equal(step.links[0].href, 'https://github.com/o/r/pull/12');
  assert.ok(rows.some(r => r.question && r.text === 'Keep the old file name?'), 'questions stay');
  assert.ok(rows.some(r => r.w === 'y' && r.text === 'Please also try a PDF.'), 'your Chat lines stay');
});

test('without a readable conversation the chat is the ticket summary', () => {
  for (const talk of [null, {available: false, turns: []}, {available: true, turns: []}, {available: true}]) {
    assert.equal(C.liveTalkReal(talk), false);
    const rows = plain(C.liveChatModel(ticket(), 'human:lume', [], talk));
    assert.ok(rows.some(r => r.text === 'Uploading works for pictures, pages and tables.'));
    assert.ok(!rows.some(r => r.talk));
  }
  assert.equal(C.liveTalkReal({available: true, turns: [{w: 'h', text: 'a', at: '2026-11-19T14:10:00Z'}]}), true);
});
