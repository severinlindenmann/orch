'use strict';
// ORCH-1104: the kit's call recorder (UI.meetingRecorder in composer.js). The call's sound only through the browser's
// share picker; never a silent fall back to the microphone; pieces in order; stop() hands over the last piece.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const SRC = fs.readFileSync(path.join(__dirname, '../../../workspace/src/orch_ui/static/composer.js'), 'utf8');
const tick = () => new Promise(r => setTimeout(r, 0));
function track(kind) {
  const t = {kind, label:kind === 'audio' ? 'Meeting tab' : 'screen', stopped:false, on:{}, stop() { this.stopped = true; }, addEventListener(e, f) { this.on[e] = f; }};
  return t;
}
function stream(tracks) {
  return {tracks, getTracks:() => tracks.slice(), getAudioTracks:() => tracks.filter(t => t.kind === 'audio'), getVideoTracks:() => tracks.filter(t => t.kind === 'video'), removeTrack(t) { tracks.splice(tracks.indexOf(t), 1); }};
}
function load({display = 'audio', mic = 'ok'} = {}) {
  let now = 0;
  const made = [], timers = [], asked = [], got = {};
  class FakeRec {
    constructor(s, o) { this.state = 'inactive'; this.mimeType = o.mimeType; made.push(this); }
    static isTypeSupported(t) { return t === 'audio/webm;codecs=opus'; }
    start() { this.state = 'recording'; }
    stop() { this.state = 'inactive'; this.ondataavailable({data:{size:3}}); setTimeout(() => this.onstop(), 0); }
  }
  class FakeAC {
    async resume() {} close() {}
    createMediaStreamDestination() { return {stream:'mixed'}; }
    createMediaStreamSource() { return {connect() {}}; }
    createAnalyser() { return {getFloatTimeDomainData(b) { b.fill(0.1); }}; }
  }
  const md = {
    async getDisplayMedia(o) {
      asked.push(o);
      if (display === 'cancel') { const e = new Error('no'); e.name = 'NotAllowedError'; throw e; }
      got.display = stream(display === 'audio' ? [track('video'), track('audio')] : [track('video')]);
      return got.display;
    },
    async getUserMedia() {
      if (mic === 'blocked') { const e = new Error('no'); e.name = 'NotAllowedError'; throw e; }
      got.mic = stream([track('audio')]); return got.mic;
    },
  };
  const win = {UI:{}, MediaRecorder:FakeRec, AudioContext:FakeAC};
  const ctx = {window:win, navigator:{language:'en', mediaDevices:md}, document:{createElement:() => ({}), addEventListener() {}},
    Blob:class { constructor(parts, o) { this.type = o.type; } }, File:class {}, Event:class {}, setTimeout,
    setInterval:f => { timers.push(f); return timers.length; }, clearInterval:id => { if (id) timers[id - 1] = null; },
    Float32Array, Math, Promise, Object, Error,
    Date:Object.assign(function () { return new Date(now); }, {now:() => now})};
  ctx.UI = win.UI;
  vm.createContext(ctx); vm.runInContext(SRC, ctx);
  return {UI:win.UI, made, asked, got, timers, at:t => { now = t; }, run:() => timers.forEach(f => f && f())};
}

test('without screen sharing in the browser there is no recorder', () => {
  const ctx = {window:{UI:{}, MediaRecorder:class {}}, navigator:{mediaDevices:{getUserMedia() {}}}, document:{addEventListener() {}}, setTimeout};
  ctx.UI = ctx.window.UI; vm.createContext(ctx); vm.runInContext(SRC, ctx);
  assert.equal(ctx.UI.meetingRecorder({}), null);
});

test('the call’s sound is shared, the picture dropped, and both sounds recorded in pieces in order', async () => {
  const k = load();
  const pieces = [];
  const r = k.UI.meetingRecorder({pieceSecs:100, onPiece:(b, p) => pieces.push([p.n, p.secs, b.type])});
  assert.equal((await r.share()).meeting, 'captured');
  assert.equal(k.asked[0].audio.suppressLocalAudioPlayback, false, 'the person still hears the call');
  assert.equal(k.got.display.getVideoTracks().length, 0, 'the picture is never kept');
  assert.deepEqual(JSON.parse(JSON.stringify(await r.start())), {mic:'on', meeting:'captured'});
  assert.equal(r.recording, true);
  k.at(100000); k.run(); await tick();
  assert.equal(k.made.length, 2, 'a new piece starts before the old one ends');
  k.at(130000);
  await r.stop();
  assert.deepEqual(pieces, [[1, 100, 'audio/webm'], [2, 30, 'audio/webm']]);
  assert.equal(k.got.mic.tracks[0].stopped, true, 'the microphone is released');
  assert.equal(r.recording, false);
});

test('no sound in what was shared: says missing and never starts on the microphone alone by itself', async () => {
  const k = load({display:'video'});
  const r = k.UI.meetingRecorder({});
  assert.equal((await r.share()).meeting, 'missing');
  await assert.rejects(r.start(), e => e.code === 'none');
  assert.equal(k.made.length, 0);
  await r.share({tab:true});
  assert.equal(k.asked[1].video.displaySurface, 'browser', 'the second try offers a browser tab');
  assert.equal(JSON.parse(JSON.stringify(await r.start({micOnly:true}))).meeting, 'missing', 'only when the person chose it');
  r.cancel();
});

test('closing the share picker or a blocked microphone comes back as a code', async () => {
  await assert.rejects(load({display:'cancel'}).UI.meetingRecorder({}).share(), e => e.code === 'cancelled');
  const r = load({mic:'blocked'}).UI.meetingRecorder({});
  await assert.rejects(r.start({micOnly:true}), e => e.code === 'blocked');
});

test('the browser’s own Stop sharing ends the recording and hands over the last piece', async () => {
  const k = load();
  const pieces = [], ends = [];
  const r = k.UI.meetingRecorder({onPiece:(b, p) => pieces.push(p.n), onEnd:w => ends.push(w)});
  await r.share(); await r.start();
  k.got.display.getAudioTracks()[0].on.ended();
  await tick(); await tick();
  assert.deepEqual(ends, ['shared']);
  assert.deepEqual(pieces, [1]);
  assert.equal(r.recording, false);
});

test('levels for both sounds four times a second', async () => {
  const k = load();
  const seen = [];
  const r = k.UI.meetingRecorder({onLevel:l => seen.push(l)});
  await r.share(); await r.start();
  k.run();
  assert.ok(seen[0].mic > 0 && seen[0].meeting > 0);
  r.cancel();
});
