// "Send questions to my phone" is hidden entirely while no phone is paired (owner 14 Nov); no relay at all hides it too.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function load() {
  const el = () => ({hidden:true, disabled:false, title:'', attrs:{}, children:[], className:'', setAttribute(k, v) { this.attrs[k] = v; }, replaceChildren() { this.children = []; },
    append(...n) { this.children.push(...n); }, querySelector: sel => sel === '.mm-label' ? label : null, classList:{toggle(){}}});
  const label = {textContent:'Send questions to my phone'}, toggle = el(), bar = el();
  const doc = {getElementById:id => id === 'mm-toggle' ? toggle : bar, createElement:() => el(), addEventListener(){}, body:{classList:{toggle(){}}}};
  const win = {listeners:{}, addEventListener(name, fn) { this.listeners[name] = fn; }};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/mobile-mode.js'), 'utf8'), {document:doc, window:win, localStorage:{getItem(){}, setItem(){}, removeItem(){}}});
  return {toggle, label, win, state:mobile_mode => win.listeners['orch:state']({detail:{mobile_mode}})};
}
const base = {on:false, default_hours:12, hours_choices:[4, 8, 12, 24]};
test('no phone paired: the switch is hidden, not just disabled', () => {
  const c = load();
  c.state({...base, phones:0});
  assert.equal(c.toggle.hidden, true);
  assert.notEqual(c.label.textContent, 'Pair a phone first');
});
test('no relay set up: the switch is hidden', () => {
  const c = load();
  c.state(null);
  assert.equal(c.toggle.hidden, true);
});
test('a paired phone, or an unknown count, leaves the switch usable; an On switch can always be turned off', () => {
  for (const mm of [{...base, phones:1}, {...base, phones:null}, {...base, on:true, phones:0}]) {
    const c = load();
    c.state(mm);
    assert.equal(c.toggle.hidden, false);
    assert.equal(c.toggle.disabled, false);
    assert.equal(c.label.textContent, 'Send questions to my phone');
  }
});
