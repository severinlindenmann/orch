// ORCH-238: "Add to this ticket" on the ticket page. The files go on the ticket first (ticket.attach), then the helper is
// told (run.send; run.start when nothing is on the ticket; ticket.changes in Review). Everything the code touches is faked.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/ticket.js'), 'utf8');
const start = source.indexOf('// ORCH-238 (owner, 17 Nov)'), end = source.indexOf('async function ticketSendChanges');
const part = source.slice(start, end);
const plain = v => JSON.parse(JSON.stringify(v));

function setup({status = 'active', alive = true, snapshot = false, results = {}} = {}) {
  const acts = [];
  const tickets = [{id:'t_talk0001', title:'Fix the toolbar', status}];
  const ctx = {snapshot, mounts:new Map(), artifactData:new Map(), state:{runs:{t_talk0001:{running:alive}}}, array:v => Array.isArray(v) ? v : [],
    ticketOf:id => tickets.find(t => t.id === id), render(){},
    h:(tag, attrs, ...kids) => ({tag, attrs, kids}),
    act:async (op, args) => {
      acts.push([op, args]);
      if (results[op]) return results[op];
      return {ok:true, status:200, state:op === 'run.send' ? {send_result:alive ? {id:'p_1', delivered:1, state:'idle'} : {id:'p_1', delivered:0, state:'none'}} : {}};
    },
    window:{DashHelpers:{helperAlive:(t, run) => !!run?.running, scrubText:s => s}}};
  vm.createContext(ctx); vm.runInContext(part, ctx);
  return {ctx, acts};
}
const shot = {name:'Screenshot 14-02.png', size:10, type:'image/png', url:'data:image/png;base64,iVBORw0KGgo='};
const log = {name:'feedback.md', size:5, type:'text/markdown', url:'data:text/markdown;base64,aGVsbG8='};

test('the helper is told the words and the files by name', () => {
  const {ctx} = setup();
  assert.equal(ctx.ticketTalkText('The save button is cut off', []), 'The save button is cut off');
  assert.equal(ctx.ticketTalkText('  See these  ', ['a.png', 'b.md']), 'See these\n\nI added 2 files to this ticket: a.png, b.md. Read them first.');
  assert.equal(ctx.ticketTalkText('', ['a.png']), 'I added a file to this ticket: a.png. Read it and carry on.');
  // long names never push the message over run.send's limit
  const long = ctx.ticketTalkText('x'.repeat(1500), Array.from({length:10}, (_, i) => 'n'.repeat(200) + i + '.png'));
  assert.ok(long.length <= 2000, long.length);
  assert.match(long, /I added 10 files to this ticket\. Read them first\.$/);
});

test('files land on the ticket first, then a working helper gets the message', async () => {
  const {ctx, acts} = setup();
  const result = await ctx.ticketTalkSend('t_talk0001', {text:'User feedback, round 2', files:[shot, log]});
  assert.deepEqual(plain(acts), [
    ['ticket.attach', {ticket:'t_talk0001', files:[{name:'Screenshot 14-02.png', data:'iVBORw0KGgo='}, {name:'feedback.md', data:'aGVsbG8='}]}],
    ['run.send', {ticket:'t_talk0001', text:'User feedback, round 2\n\nI added 2 files to this ticket: Screenshot 14-02.png, feedback.md. Read them first.'}]]);
  assert.deepEqual(plain(result), {ok:true, text:'Sent. The helper reads it now.'});
});

test('with no helper on the ticket the message is queued and a helper starts', async () => {
  const {ctx, acts} = setup({status:'ready', alive:false});
  const result = await ctx.ticketTalkSend('t_talk0001', {text:'Go on', files:[]});
  assert.deepEqual(plain(acts).map(a => a[0]), ['run.send', 'run.start']);
  assert.equal(result.ok, true);
  assert.equal(result.text, 'Sent. A helper starts and reads it first.');
});

test('a busy helper keeps the message for later, without a second start', async () => {
  const {ctx, acts} = setup({results:{'run.send':{ok:true, status:200, state:{send_result:{id:'p_2', delivered:0, state:'working'}}}}});
  const result = await ctx.ticketTalkSend('t_talk0001', {text:'Also this', files:[]});
  assert.deepEqual(plain(acts).map(a => a[0]), ['run.send']);
  assert.equal(result.text, 'Sent. The helper reads it when it finishes what it is doing.');
});

test('a ticket in Review goes back with the note (Send back), never a plain run.send', async () => {
  const {ctx, acts} = setup({status:'review', alive:false});
  const result = await ctx.ticketTalkSend('t_talk0001', {text:'Two more points', files:[shot]});
  assert.deepEqual(plain(acts).map(a => a[0]), ['ticket.attach', 'ticket.changes']);
  assert.equal(acts[1][1].text, 'Two more points\n\nI added a file to this ticket: Screenshot 14-02.png. Read it first.');
  assert.equal(result.ok, true);
});

test('a refused file sends nothing and keeps the draft', async () => {
  const {ctx, acts} = setup({results:{'ticket.attach':{ok:false, status:422, text:'x.pdf: only text files and pictures can be added.'}}});
  const result = await ctx.ticketTalkSend('t_talk0001', {text:'See file', files:[shot]});
  assert.deepEqual(plain(acts).map(a => a[0]), ['ticket.attach']);
  assert.deepEqual(plain(result), {ok:false, text:'x.pdf: only text files and pictures can be added.'});
});

test('files on the ticket but the message refused: the text stays, the files are not added twice', async () => {
  const {ctx} = setup({results:{'run.send':{ok:false, status:422, text:'That message is too long.'}}});
  const result = await ctx.ticketTalkSend('t_talk0001', {text:'See file', files:[shot]});
  assert.equal(result.ok, false);
  assert.equal(result.dropFiles, true);
  assert.match(result.text, /^The files are on the ticket, but the helper was not told: That message is too long\.$/);
});

test('orch unreachable says so in plain words', async () => {
  const {ctx} = setup({results:{'run.send':{ok:false, status:0, text:''}}});
  const result = await ctx.ticketTalkSend('t_talk0001', {text:'Hi', files:[]});
  assert.deepEqual(plain(result), {ok:false, dropFiles:false, text:"Can't reach orch. Nothing was sent."});
});

test('the card is on open tickets only, never on a shared copy or a done ticket', () => {
  assert.ok(setup().ctx.ticketTalkCard({id:'t_talk0001', status:'active'}));
  assert.ok(setup().ctx.ticketTalkCard({id:'t_talk0001', status:'review'}));
  assert.equal(setup().ctx.ticketTalkCard({id:'t_talk0001', status:'done'}), null);
  assert.equal(setup({snapshot:true}).ctx.ticketTalkCard({id:'t_talk0001', status:'active'}), null);
});

test('the button says what one click does', () => {
  const {ctx} = setup();
  assert.equal(ctx.ticketTalkLabel({status:'active'}, {running:true}), 'Send to helper');
  assert.equal(ctx.ticketTalkLabel({status:'ready'}, {running:false}), 'Send and start helper');
  assert.equal(ctx.ticketTalkLabel({status:'review'}, {running:false}), 'Send back with this');
});

test("the helper's screen is shown as plain text (colour and cursor codes dropped)", () => {
  const {ctx} = setup();
  assert.equal(ctx.talkScreenText('\x1b[1m\x1b[32m●\x1b[0m Reading\x1b[?25l\n  \x1b]0;title\x07done\n\n\n'), '● Reading\n  done');
});

test('without the kit composer the page still renders (mount is a no-op)', () => {
  const {ctx} = setup();
  assert.doesNotThrow(() => ctx.mountTicketTalk({querySelectorAll:() => { throw new Error('must not look'); }}));
});
