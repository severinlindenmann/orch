'use strict';
// Contacts with fingerprint and state (ORCH-1203, look B picked by the owner): the contacts that need an Accept come
// first with the check line, the fingerprint in two rows of four and one Accept; "New key without the old one" gets
// the careful Accept (outline, empty name, one warning line); the rest sit in a table with Stop trusting. Only checked
// ids and fingerprints reach the DOM; the words are orch's own.
const test = require('node:test');
const assert = require('node:assert/strict');

class El {
  constructor(tag) { this.tagName = tag.toUpperCase(); this.className = ''; this.dataset = {}; this.attrs = {}; this.kids = []; this.text = ''; this.style = {}; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  set textContent(v) { this.text = String(v); this.kids = []; }
  get textContent() { return this.text + this.kids.map(k => k.textContent).join(''); }
  set type(v) { this.attrs.type = v; } set scope(v) { this.attrs.scope = v; }
  append(...c) { for (const x of c) this.kids.push(typeof x === 'string' ? Object.assign(new El('#text'), {text: x}) : x); }
  all() { return this.kids.flatMap(k => [k, ...k.all()]); }
  find(f) { return this.all().filter(f); }
}
global.document = {createElement: t => new El(t), createElementNS: (_, t) => new El(t), createDocumentFragment: () => new El('#frag')};
const B = require('../src/orch_dashboard/web/blocks.js');

const FP = 'P9CE 2WXK 6MHB T4RN J0QD 8VA3 Y5GS F7Z1', OLD = 'T6HQ 1NWB K9XD 3ZPC R8ME 4JVA Y0G5 S2F7';
const block = {type: 'contacts', title: 'Contacts', own: {name: 'ORCH Development', fingerprint: 'D4WP 8N2K XQ7H 3RTA 9C5M B6YE 0GJS V1ZF'}, items: [
  {id: 'ws_homemac001', name: 'Home Mac', kind: 'workspace', state: 'new_key', fingerprint: FP, old_fingerprint: OLD, held: 1},
  {id: 'ws_fernscout1', name: 'fernscout', kind: 'workspace', state: 'not_accepted', fingerprint: OLD, held: 2},
  {id: 'ws_severin001', name: 'Workspace Severin', relay_name: 'severin-main', kind: 'workspace', state: 'accepted', fingerprint: FP, held: 0, accepted_at: '2026-11-12T08:00:00Z'},
  {id: 'ws_market0001', name: 'Marketing', kind: 'workspace', state: 'not_valid', fingerprint: FP, held: 0, refused: 3},
  {id: 'ws_swapped001', name: 'Sales', kind: 'workspace', state: 'withdrawn', fingerprint: FP, old_fingerprint: OLD, held: 0},
  {id: 'ws_bad', name: 'Wrong id', kind: 'workspace', state: 'accepted', fingerprint: FP, held: 0},
  {id: 'ws_badfp00001', name: 'Wrong fp', kind: 'workspace', state: 'accepted', fingerprint: '<img src=x>', held: 0},
  {id: 'ws_badstate01', name: 'Wrong state', kind: 'workspace', state: 'trusted', fingerprint: FP, held: 0},
]};
const draw = () => B.render([block]).kids[0];

test('the contacts that need an Accept come first, each with the check line, the fingerprint and one Accept', () => {
  const s = draw();
  const asks = s.find(n => n.dataset.contact && n.tagName === 'ARTICLE');
  assert.deepEqual(asks.map(a => a.dataset.contact), ['ws_homemac001', 'ws_fernscout1']);
  const fern = asks[1];
  assert.match(fern.textContent, /Not accepted yet/);
  assert.match(fern.textContent, /Check that it matches the fingerprint fernscout shows on its own Settings page\./);
  const fp = fern.find(n => n.className === 'fingerprint lg')[0];
  assert.deepEqual(fp.kids.map(k => k.text), OLD.split(' '));   // 8 groups, drawn as two rows of four by the kit
  const acc = fern.find(n => n.dataset.contactAccept)[0];
  assert.equal(acc.text, 'Accept'); assert.match(acc.className, /primary/);
  assert.equal(acc.dataset.fingerprint, OLD);
  const name = fern.find(n => n.tagName === 'INPUT')[0];   // empty keeps the relay's name; it is never saved as your own
  assert.equal(name.value, ''); assert.equal(name.placeholder, 'fernscout');
  assert.match(fern.textContent, /2 messages wait for your Accept/);
});

test('a new key without the old one gets the careful Accept: outline, empty name, one warning line', () => {
  const home = draw().find(n => n.dataset.contact === 'ws_homemac001' && n.tagName === 'ARTICLE')[0];
  assert.match(home.textContent, /New key without the old one/);
  assert.match(home.textContent, /Only accept if they set up a new computer\./);
  assert.match(home.textContent, /Old key, no longer used: /);
  const acc = home.find(n => n.dataset.contactAccept)[0];
  assert.equal(acc.text, 'Accept as new contact'); assert.match(acc.className, /outline/); assert.doesNotMatch(acc.className, /primary/);
  assert.equal(home.find(n => n.tagName === 'INPUT')[0].value, '');
  assert.equal(home.dataset.tone, 'bad');
});

test('every other contact is a table row: Accepted with Stop trusting, Not valid with Check and accept again', () => {
  const s = draw();
  const rows = s.find(n => n.tagName === 'TR' && n.dataset.contact);
  assert.deepEqual(rows.map(r => r.dataset.contact), ['ws_severin001', 'ws_market0001', 'ws_swapped001']);
  assert.match(rows[0].textContent, /Accepted/); assert.match(rows[0].textContent, /Name on the relay: severin-main/);
  assert.equal(rows[0].find(n => n.dataset.contactWithdraw)[0].text, 'Stop trusting');
  assert.match(rows[1].textContent, /Not valid/); assert.match(rows[1].textContent, /3 messages refused as forged or changed\./);
  assert.equal(rows[1].find(n => n.dataset.contactAccept)[0].text, 'Accept again');
});

test('this workspace shows its own fingerprint with Copy; a wrong id, fingerprint or state is never drawn', () => {
  const s = draw();
  const own = s.find(n => n.tagName === 'ASIDE')[0];
  assert.match(own.textContent, /This workspace/); assert.match(own.textContent, /ORCH Development/);
  assert.equal(own.find(n => n.dataset.copy)[0].dataset.copy, block.own.fingerprint);
  assert.doesNotMatch(s.textContent, /Wrong id|Wrong fp|Wrong state|img/);
});

test('a key swapped on a Withdrawn or Not valid contact shows the old key and the careful Accept', () => {
  const r = draw().find(n => n.tagName === 'TR' && n.dataset.contact === 'ws_swapped001')[0];
  assert.match(r.textContent, /Old key, no longer used: /);
  assert.match(r.textContent, /Only accept if they set up a new computer\./);
  const acc = r.find(n => n.dataset.contactAccept)[0];
  assert.equal(acc.text, 'Accept as new contact'); assert.match(acc.className, /outline/);
  assert.equal(r.find(n => n.tagName === 'INPUT')[0].value, '');
  const plain = draw().find(n => n.tagName === 'TR' && n.dataset.contact === 'ws_market0001')[0];
  assert.doesNotMatch(plain.textContent, /Old key|Only accept/);
});

test('your own earlier name for a contact is kept in the field', () => {
  const sev = {...block.items[2], state: 'not_accepted'};
  const c = B.render([{...block, items: [sev]}]).kids[0].find(n => n.tagName === 'INPUT')[0];
  assert.equal(c.value, 'Workspace Severin');
});
