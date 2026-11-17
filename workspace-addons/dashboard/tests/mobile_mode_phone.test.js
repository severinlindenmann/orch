// "Send questions to my phone" is hidden entirely while no phone is paired (owner 14 Nov); no relay at all hides it too.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

// The page runs on a fixed clock, local noon today: "in 3 hours" stays today and "in 26 hours" is tomorrow, whatever the
// hour the test runs (late in the evening they used to cross midnight, #1366).
const NOON = (() => { const d = new Date(); d.setHours(12, 0, 0, 0); return d.getTime(); })();
class NoonDate extends Date {
  constructor(...a) { if (a.length) super(...a); else super(NOON); }
  static now() { return NOON; }
}
function load() {
  const el = () => ({hidden:true, disabled:false, title:'', attrs:{}, children:[], className:'', setAttribute(k, v) { this.attrs[k] = v; }, replaceChildren(...n) { this.children = n.flat().filter(x => x != null); },
    append(...n) { this.children.push(...n); }, querySelector: sel => sel === '.mm-label' ? label : null, classList:{toggle(){}}});
  const label = {textContent:'Send questions to my phone'}, toggle = el(), bar = el(), chip = el(), clicks = [];
  const doc = {getElementById:id => id === 'mm-toggle' ? toggle : id === 'mm-chip' ? chip : bar, createElement:() => el(), addEventListener(type, fn) { if (type === 'click') clicks.push(fn); }, body:{classList:{toggle(){}}}};
  const win = {listeners:{}, addEventListener(name, fn) { this.listeners[name] = fn; }};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/mobile-mode.js'), 'utf8'), {document:doc, window:win, Date:NoonDate, localStorage:{getItem(){}, setItem(){}, removeItem(){}}});
  return {toggle, label, win, bar, chip, clicks, state:mobile_mode => win.listeners['orch:state']({detail:{mobile_mode}})};
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
    assert.equal(c.label.textContent, 'Phone');
  }
});

// UX round 15 Nov (item 3): while it is on, a chip in the top bar and no banner; the banner is for the ask, the ended notice and the last 5 minutes.
const text = n => typeof n === 'string' ? n : (n.children || []).map(text).join('');
const find = (n, f) => typeof n === 'string' ? [] : [...(f(n) ? [n] : []), ...(n.children || []).flatMap(k => find(k, f))];
const soon = ms => new Date(NOON + ms).toISOString();  // on the page's clock
const fromNow = ms => new Date(Date.now() + ms).toISOString();  // on the real clock (helpers.js below runs on it)
test('on: the chip shows "Phone until HH:MM" with the menu, and the banner stays hidden', () => {
  const c = load();
  c.state({...base, phones:1, on:true, ends_at:soon(3 * 3600000), awake:'awake'});
  assert.equal(c.chip.hidden, false);
  assert.equal(c.bar.hidden, true);
  assert.match(text(c.chip.children[0]), /^Phone until \d\d:\d\d$/);
  const menu = text(c.chip.children[1]);
  assert.match(menu, /Questions go to your phone until \d\d:\d\d/);
  assert.match(menu, /This computer stays awake meanwhile\./);
  assert.match(menu, /Keep on for \d+ hours/);
  assert.match(menu, /Turn off/);
  assert.ok(find(c.chip, n => n.attrs?.['data-testid'] === 'mobile-mode-bar-off').length === 1);
  assert.match(c.label.textContent, /^Phone · until \d\d:\d\d$/);
});
test('on but could not keep the computer awake: the chip uses the warning tone and the menu says why', () => {
  const c = load();
  c.state({...base, phones:1, on:true, ends_at:soon(3 * 3600000), awake:'could_not_keep_awake'});
  assert.match(c.chip.children[0].className, /attn/);
  assert.match(text(c.chip.children[1]), /Could not keep this computer awake/);
});
test('off: no chip, label is just Phone', () => {
  const c = load();
  c.state({...base, phones:1});
  assert.equal(c.chip.hidden, true);
  assert.equal(c.label.textContent, 'Phone');
});
test('the banner shows for the first-click ask, and for the last 5 minutes only', () => {
  const ask = load();
  ask.state({...base, phones:1});
  ask.clicks[0]({target:{closest:() => ({id:'mm-toggle', dataset:{}})}});
  assert.equal(ask.bar.hidden, false);
  assert.equal(ask.bar.attrs['data-testid'], 'mobile-mode-ask');
  const last = load();
  last.state({...base, phones:1, on:true, ends_at:soon(2 * 60000)});
  assert.equal(last.bar.hidden, false);
  assert.equal(last.bar.attrs['data-testid'], 'mobile-mode-soon');
  assert.match(text(last.bar), /ends in 5 minutes/);
  assert.equal(last.chip.hidden, false);
});
test('New ticket in the top bar is the quiet (outlined) button, not the filled one', () => {
  const html = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/index.html'), 'utf8');
  const tag = html.match(/<button[^>]*id="new-ticket"[^>]*>/)[0];
  assert.match(tag, /class="btn outline sm"/);
  assert.doesNotMatch(tag, /primary/);
  assert.match(html, /id="mm-chip"/);
});
test('the ended notice is one toast, marked seen, never a banner that stays', () => {
  const toasts = [], acts = [];
  const c = load();
  c.win.orch = {toast:(text, kind) => toasts.push([text, kind])};
  c.win.orchAct = async (op) => { acts.push(op); return {ok:true}; };
  const ended = {...base, phones:1, ended:{text:'Mobile mode ended after its time ran out.'}};
  c.state(ended);
  c.state(ended);
  assert.equal(c.bar.hidden, true);
  assert.deepEqual(toasts, [['Mobile mode ended after its time ran out.', 'ok']]);
  assert.deepEqual(acts, ['mobile.ack']);
});
test('ORCH-184: a mode whose end time has passed is shown as ended, not "Phone until HH:MM"', () => {
  const c = load();
  c.state({...base, phones:1, on:true, ends_at:soon(-60000), awake:'ok'});
  assert.equal(c.chip.hidden, true);
  assert.equal(c.bar.hidden, true);
  assert.equal(c.label.textContent, 'Phone');
  const helpers = require('../src/orch_dashboard/web/helpers.js');
  assert.equal(helpers.mobileOn({on:true, ends_at:fromNow(-1000)}), false);
  assert.equal(helpers.mobileOn({on:true, ends_at:fromNow(60000)}), true);
  assert.equal(helpers.mobileOn({on:true}), true);
});
test('ORCH-286: an end time on another day says the day, in the chip, the menu and the sidebar label', () => {
  const c = load();
  c.state({...base, phones:1, on:true, ends_at:soon(26 * 3600 * 1000), awake:'ok'});
  assert.match(text(c.chip.children[0]), /^Phone until tomorrow \d\d:\d\d$/);
  assert.match(c.label.textContent, /^Phone · until tomorrow \d\d:\d\d$/);
  assert.match(text(c.chip.children[1]), /Questions go to your phone until tomorrow \d\d:\d\d/);
  const c2 = load();
  c2.state({...base, phones:1, on:true, ends_at:soon(4 * 24 * 3600 * 1000), awake:'ok'});
  assert.match(text(c2.chip.children[0]), /^Phone until (Mon|Tue|Wed|Thu|Fri|Sat|Sun) \d\d:\d\d$/);
});
