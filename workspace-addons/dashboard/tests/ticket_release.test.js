// ORCH-87: a finished ticket with a merged pull request says whether the change is in the orch installed here.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../src/orch_dashboard/web/pages/ticket.js'), 'utf8');

function context(answer) {
  const asked = [], renders = [];
  const ctx = {
    h:(tag, attrs, ...children) => ({tag, attrs, children}), clean:s => String(s), snapshot:false,
    route:() => ({kind:'ticket', id:'t_abc123'}), ticketOf:id => ({id}), render:() => renders.push(1),
    fetch:url => { asked.push(url); return Promise.resolve({ok:true, json:() => Promise.resolve(answer)}); },
  };
  vm.createContext(ctx);
  vm.runInContext(source.slice(source.indexOf('// A finished ticket with a merged pull request'), source.indexOf('const proofRows')), ctx);
  return {ctx, asked, renders};
}
const text = n => n == null ? '' : typeof n === 'string' ? n : Array.isArray(n) ? n.map(text).join('') : text(n.children);
const tick = () => new Promise(r => setImmediate(r));

test('a done ticket asks orch once and shows the line it gets', async () => {
  const {ctx, asked, renders} = context({state:'installed', release:30, text:'In release 30 (installed here)'});
  const t = {id:'t_abc123', status:'done'};
  assert.equal(ctx.ticketReleaseLine(t), null, 'nothing before the answer');
  ctx.loadRelease(t); ctx.loadRelease(t);
  await tick();
  assert.deepEqual(asked, ['/api/release?ticket=t_abc123'], 'one request while it is busy');
  assert.equal(renders.length, 1);
  const line = ctx.ticketReleaseLine(t);
  assert.equal(text(line), '✓ In release 30 (installed here)');
  assert.match(line.attrs.className, /ticket-proof-line/);
  ctx.loadRelease(t);
  assert.equal(asked.length, 1, 'asked again only after a minute');
});

test('merged but not released reads plainly; open tickets, odd answers and no answer show nothing', async () => {
  const {ctx, asked} = context({state:'merged', release:null, text:'Merged, not released yet'});
  ctx.loadRelease({id:'t_abc123', status:'review'});
  ctx.loadRelease({id:'t_open01', status:'active'});
  await tick();
  assert.deepEqual(asked, ['/api/release?ticket=t_abc123']);
  assert.equal(text(ctx.ticketReleaseLine({id:'t_abc123', status:'review'})), '– Merged, not released yet');
  assert.equal(ctx.ticketReleaseLine({id:'t_abc123', status:'active'}), null);
  for (const answer of [null, {state:'other', text:'x'}, {state:'merged'}]) {
    const c = context(answer);
    c.ctx.loadRelease({id:'t_abc123', status:'done'});
    await tick();
    assert.equal(c.ctx.ticketReleaseLine({id:'t_abc123', status:'done'}), null);
  }
});
