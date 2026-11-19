'use strict';
// ORCH-422: the kit's Record button (UI.voiceRecorder in composer.js). One click starts, one stops; the recording
// comes back as a file; words only from speech recognition that runs on this computer, else none.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const SRC = fs.readFileSync(path.join(__dirname, '../../../workspace/src/orch_ui/static/composer.js'), 'utf8');
const tick = () => new Promise(r => setTimeout(r, 0));
function load({media = true, recorder = true, speech = null, deny = false, type = 'audio/webm;codecs=opus'} = {}) {
  const made = [];
  class FakeRec {
    constructor(stream, o) { this.state = 'inactive'; this.mimeType = (o && o.mimeType) || type; made.push(this); }
    static isTypeSupported(t) { return t === type; }
    start() { this.state = 'recording'; }
    stop() { this.state = 'inactive'; this.ondataavailable({data:{size:3}}); this.onstop(); }
  }
  const tracks = [];
  const button = () => ({classList:{add(){}, remove(){}}, setAttribute(){}, lastChild:{textContent:''}, set innerHTML(v) { this._html = v; this.lastChild = {textContent:''}; }, get innerHTML() { return this._html; }});
  const win = {UI:{}, MediaRecorder:recorder ? FakeRec : undefined, ...(speech || {})};
  const ctx = {window:win, navigator:{language:'en-US', mediaDevices:media ? {getUserMedia:async () => { if (deny) { const e = new Error('no'); e.name = 'NotAllowedError'; throw e; } const t = {stopped:false, stop() { this.stopped = true; }}; tracks.push(t); return {getTracks:() => [t]}; }} : undefined},
    document:{createElement:button, addEventListener(){}}, File:class { constructor(parts, name, o) { this.name = name; this.type = o.type; } }, Event:class {}, setTimeout, setInterval:() => 1, clearInterval(){}, Date};
  ctx.UI = win.UI;  // the browser global UI is window.UI
  vm.createContext(ctx); vm.runInContext(SRC, ctx);
  return {UI:win.UI, made, tracks};
}
test('no microphone access in this browser: no Record button at all', () => {
  assert.equal(load({media:false}).UI.voiceRecorder({}), null);
  assert.equal(load({recorder:false}).UI.voiceRecorder({}), null);
});
test('one click records, one click stops: a voice-note file, the microphone released, no words without local recognition', async () => {
  const {UI, made, tracks} = load();
  const got = [];
  const r = UI.voiceRecorder({onDone:(file, words) => got.push([file.name, file.type, words])});
  assert.match(r.button._html, /Record/);
  r.button.onclick(); await tick();
  assert.equal(r.recording, true);
  assert.equal(made[0].mimeType, 'audio/webm;codecs=opus');
  r.button.onclick(); await tick();
  assert.equal(got.length, 1);
  assert.match(got[0][0], /^voice-note-\d{4}\.webm$/);
  assert.equal(got[0][1], 'audio/webm');
  assert.equal(got[0][2], '', 'no words: the browser has no on-device speech to text');
  assert.equal(tracks[0].stopped, true, 'the microphone is released');
  assert.equal(r.recording, false);
});
test('Safari records mp4: kept as .m4a', async () => {
  const {UI} = load({type:'audio/mp4'});
  const got = [];
  const r = UI.voiceRecorder({onDone:f => got.push(f.name)});
  r.button.onclick(); await tick(); r.button.onclick(); await tick();
  assert.match(got[0], /\.m4a$/);
});
test('a blocked microphone says how to allow it, and nothing is recorded', async () => {
  const {UI} = load({deny:true});
  const errors = [];
  const r = UI.voiceRecorder({onError:m => errors.push(m)});
  r.button.onclick(); await tick();
  assert.match(errors[0], /microphone is blocked/);
  assert.equal(r.recording, false);
});
test('speech recognition that would leave the computer is never used', async () => {
  let started = 0;
  class ServerOnly { start() { started++; } stop() {} }  // no processLocally: Chrome would send the sound to a server
  const {UI} = load({speech:{webkitSpeechRecognition:ServerOnly}});
  const r = UI.voiceRecorder({onDone(){}});
  r.button.onclick(); await tick(); await tick();
  assert.equal(started, 0);
  r.stop();
});
test('on-device recognition: its words come back with the file', async () => {
  let inst = null;
  class Local {
    constructor() { inst = this; } start() { setTimeout(() => this.onresult({resultIndex:0, results:[Object.assign([{transcript:' make the button bigger '}], {isFinal:true})]}), 0); } stop() {}
    static async available(o) { return o.processLocally ? 'available' : 'unavailable'; }
  }
  Local.prototype.processLocally = false;
  const {UI} = load({speech:{SpeechRecognition:Local}});
  const got = [];
  const r = UI.voiceRecorder({onDone:(f, words) => got.push(words)});
  r.button.onclick(); await tick(); await tick(); await tick();
  assert.equal(inst.processLocally, true, 'asked to stay on this computer');
  r.button.onclick(); await new Promise(res => setTimeout(res, 450));
  assert.deepEqual(got, ['make the button bigger']);
});
// ORCH-696: a page that draws its own controls (the new Focus message box) starts, stops and cancels by itself, is
// told when listening starts and ends, and gets the reason of a refusal as a code.
test('start() and stop() from the page: onState says when listening starts and ends, then the file', async () => {
  const {UI} = load();
  const seen = [];
  const r = UI.voiceRecorder({words:false, onState:(on, how) => seen.push([on, how]), onDone:f => seen.push(['file', f.type])});
  r.start(); await tick();
  assert.equal(r.recording, true);
  r.stop(); await tick();
  assert.deepEqual(JSON.parse(JSON.stringify(seen)), [[true, {}], [false, {cancelled:false, empty:false}], ['file', 'audio/webm']]);
});
test('cancel() drops the recording: no file, the microphone released', async () => {
  const {UI, tracks} = load();
  const seen = [];
  const r = UI.voiceRecorder({onState:(on, how) => seen.push([on, how && how.cancelled]), onDone:() => seen.push('file')});
  r.start(); await tick();
  r.cancel(); await tick();
  assert.deepEqual(seen, [[true, undefined], [false, true]]);
  assert.equal(tracks[0].stopped, true);
});
test('cancel() while the browser still asks for the microphone: nothing starts', async () => {
  const {UI, made, tracks} = load();
  const seen = [];
  const r = UI.voiceRecorder({onState:(on, how) => seen.push([on, how && how.cancelled]), onDone:() => seen.push('file')});
  r.start(); r.cancel(); await tick();
  assert.deepEqual(seen, [[false, true]]);
  assert.equal(made.length, 0);
  assert.equal(tracks[0].stopped, true);
});
test('a refusal comes with its code', async () => {
  const codes = [];
  load({deny:true}).UI.voiceRecorder({onError:(m, c) => codes.push(c)}).start(); await tick();
  assert.deepEqual(codes, ['blocked']);
});
