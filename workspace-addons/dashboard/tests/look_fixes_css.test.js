const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const kit = fs.readFileSync(path.join(__dirname, '../../../workspace/src/orch_ui/static/components.css'), 'utf8');
const style = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/style.css'), 'utf8');

// persona tests F1-F3: look fixes that only CSS can show; the pictures are on the ticket.
test('F1: on a wide screen the top bar stays on one row and the page name gives way first', () => {
  assert.match(kit, /@media\(min-width:900px\)\{\.topbar\{flex-wrap:nowrap\}\.topbar>\*\{flex-shrink:0\}\.topbar>\.breadcrumb\{flex-shrink:1;min-width:0\}\}/);
  // the page name is a line of whole words; "· Updated …" wraps out of sight instead of being cut mid-word
  assert.match(style, /\.breadcrumb>#crumb\{display:block;height:16px;overflow:hidden;white-space:normal/);
  assert.match(style, /\.breadcrumb>#updated\{flex:none;white-space:nowrap/);
});
test('F2: an empty row in a page adds no 24 px gap above the title', () => {
  assert.match(kit, /\.page>\.stack:empty\{display:none\}/);
});
test('F3: a wrapped button is pushed in only after a leading icon, never on a row that starts with its text or the button', () => {
  assert.match(kit, /\.card-row:has\(>:first-child:not\(\.grow,\.btn\)\)>\.btn\{margin-left:24px\}/);
  assert.doesNotMatch(kit, /\n\.card-row>\.btn\{margin-left:24px\}/);
});

// ORCH-902: the ticket page's 44px button height must not stretch the switch (Release, Human review needed).
test('ORCH-902: the ticket page 44px minimum height leaves .switch at its 24px height', () => {
  const ticket = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/ticket.css'), 'utf8');
  const rule = ticket.match(/\.ticket-page :is\(([^)]*\)?[^)]*)\)\{min-height:44px\}/);
  assert.ok(rule, 'the 44px rule exists');
  assert.match(rule[1], /button:not\(\.switch\)/);
  assert.match(kit, /\.switch\{[^}]*height:24px/);
});

// O-28 (owner, 28 Nov): a switch that is On had its knob in the middle. Settings draws its own 44 px target around a
// 36 px track; the knob must keep the same gap to the track's edge when Off and when On, there and in the master.
test('O-28: the switch knob has the same gap at both ends, in the master and in Settings', () => {
  const px = (css, re) => { const m = css.match(re); assert.ok(m, String(re)); return m.slice(1).map(Number); };
  // master: 36 px wide with a 1 px border, knob 16 px at left 3, travel 12
  const [width] = px(kit, /\n\.switch\{[^}]*width:(\d+)px/), [left, knob] = px(kit, /\n\.switch:after\{[^}]*left:(\d+)px;width:(\d+)px/);
  const [travel] = px(kit, /\.switch\[aria-checked=true\]:after\{[^}]*translateX\((\d+)px\)/);
  assert.equal(left, (width - 2) - (left + travel + knob), 'master: Off gap = On gap');
  const settings = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/settings.css'), 'utf8');
  const [trackLeft, trackWidth] = px(settings, /\.settings \.switch::before\{[^}]*left:(\d+)px;top:\d+px;width:(\d+)px/);
  const [knobLeft] = px(settings, /\.settings \.switch::after\{top:\d+px;left:(\d+)px\}/);
  const [go] = px(settings, /\.settings \.switch\[aria-checked=true\]::after\{transform:translateX\((\d+)px\)\}/);
  const off = knobLeft - trackLeft, on = trackLeft + trackWidth - (knobLeft + go + knob);
  assert.ok(off > 0, 'the knob sits inside the track');
  assert.equal(off, on, 'Settings: Off gap = On gap');
});
