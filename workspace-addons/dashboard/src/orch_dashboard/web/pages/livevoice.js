'use strict';
// Voice into the message box of the new Focus (ORCH-696, draft D feature 13). Speak instead of typing: the browser
// records (UI.voiceRecorder of the design system, composer.js), the server turns the sound into words through the
// relay (POST /api/voice/words; the relay keeps the speech key), and the words land in the box to check and change.
// Nothing is ever sent by itself: the person presses Send.
//   Relay off (or not connected, or a snapshot, or a browser that cannot record): no microphone, no hint (R1.1).
//   Listening: a strip above the box says so with the time, Stop and Cancel; Esc cancels; the microphone is hidden.
//   Then: "Writing down your words…", then the words in the box with draft D's line under it. A refusal (microphone
//   blocked, nothing heard, the relay said no) is one plain sentence in the same place.
const LIVE_VOICE_MAX_SECS = 120;   // the relay's limit for one recording (relay-api.md /v1/transcribe: 2 min)
const LIVE_VOICE_TEXT = 2000;      // the box's own limit (run.send, LIVE_MSG_MAX in livegroups.js)
const LIVE_VOICE_SAY = {
  blocked:'The microphone is blocked for this page; allow it in the browser, then try again.',
  none:'No microphone was found on this computer.',
  empty:'No words were heard; try again a little closer to the microphone.',
  failed:'Your words could not be written down right now; try again or type them.',
};
const LIVE_VOICE_DONE = 'From your voice. Check the words, change what is wrong, then send.';

// --- the model: plain data, no page (tested in tests/live_voice.test.js) ---
// The microphone shows only while the relay add-on is on and this folder is connected to a relay.
function liveVoiceOn(st, isSnapshot) {
  if (isSnapshot || !st || typeof st !== 'object') return false;
  const rows = Array.isArray(st.settings?.addons) ? st.settings.addons : [];
  return rows.some(a => a && a.name === 'relay' && a.active === true && a.detail?.connected === true);
}
// The words go after what is already typed, on the same line, never over the box's limit.
function liveVoiceJoin(typed, words) {
  const a = String(typed || '').replace(/\s+$/, ''), b = String(words || '').trim();
  if (!b) return String(typed || '');
  return (a ? a + ' ' + b : b).slice(0, LIVE_VOICE_TEXT);
}
const liveVoiceClock = n => Math.floor(Math.max(0, n) / 60) + ':' + String(Math.max(0, n) % 60).padStart(2, '0');

// --- the page ---
if (typeof window === 'object' && typeof document === 'object' && !(typeof module === 'object' && module.exports)) {
  // one recording at a time, in one pane: {id, phase:'ask'|'rec'|'busy', ctl}; notes per pane: {kind:'done'|'err', text}
  let liveVoiceAt = null, liveVoiceRec = null, liveVoiceTimer = null;
  const liveVoiceNote = new Map();
  const liveVoiceCan = () => !!(window.MediaRecorder && navigator.mediaDevices?.getUserMedia && window.UI?.voiceRecorder);
  const liveVoiceShown = () => liveVoiceOn(state, snapshot) && liveVoiceCan();
  const voiceSel = (id, what) => typeof liveSel === 'function' ? liveSel(id, what) : `[data-key="${what}"]`;
  const live = id => liveVoiceAt && liveVoiceAt.id === id ? liveVoiceAt.phase : '';
  const repaint = focus => {
    if (typeof liveLayerPaint === 'function') liveLayerPaint();
    if (focus) requestAnimationFrame(() => document.querySelector(focus)?.focus({preventScroll:true}));
  };
  // Every half second while a try runs: the time in the strip; and when the box of that session is gone (the pane
  // closed, the helper stopped, the panel went to the bar), the try is cancelled and the microphone released.
  const tick = () => {
    if (!liveVoiceAt) return;
    const id = String(liveVoiceAt.id).replace(/["\\]/g, '');
    if (!document.querySelector(`#live-dock [data-live-msg="${id}"]`)) { liveVoiceCancel(); return; }
    const el = document.querySelector(`#live-dock [data-live-voice-t="${id}"]`);
    if (el && liveVoiceRec) el.textContent = liveVoiceClock(liveVoiceRec.secs());
  };
  const stopTimer = () => { clearInterval(liveVoiceTimer); liveVoiceTimer = null; };
  const end = (id, note, focusWhat) => {
    stopTimer();
    liveVoiceAt = null;
    liveVoiceRec = null;
    if (note) liveVoiceNote.set(id, note); else liveVoiceNote.delete(id);
    repaint(voiceSel(id, focusWhat));
  };

  // The parts liveMsgBox (livegroups.js) puts into the box. The key makes the dock paint again when they change.
  // (the line after the words is left out: it goes in place on the first key, so typing never repaints the box)
  window.liveVoiceKey = () => [liveVoiceShown(), liveVoiceAt && [liveVoiceAt.id, liveVoiceAt.phase], [...liveVoiceNote].filter(([, v]) => v.kind === 'err').map(([k, v]) => [k, v.text])];
  window.liveVoiceMic = sess => {
    if (!sess || !liveVoiceShown() || live(sess.id)) return null;
    const busy = !!liveVoiceAt;  // another pane is listening
    const b = h('button', {type:'button', className:'btn icon sm ghost', 'data-live-voice':'start', 'data-session':sess.id, 'data-key':'live-voice',
      'aria-label':'Speak', title:'Speak instead of typing', disabled:busy});
    b.innerHTML = icon('mic', 18);
    return b;
  };
  window.liveVoiceStrip = sess => {
    const phase = sess && liveVoiceShown() ? live(sess.id) : '';
    if (!phase) return null;
    if (phase === 'busy') return h('div', {className:'live-voice', role:'status', 'data-key':'live-voice-strip'}, h('span', {}, 'Writing down your words…'));
    const stop = h('button', {type:'button', className:'btn outline sm', 'data-live-voice':'stop', 'data-session':sess.id, 'data-key':'live-voice-stop', disabled:phase !== 'rec'});
    stop.innerHTML = icon('stop', 16);
    stop.append(h('span', {}, 'Stop'));
    const wave = h('span', {className:'live-voice-wave', 'aria-hidden':'true'}, ...Array.from({length:12}, () => h('i', {})));
    return h('div', {className:'live-voice', role:'status', 'data-key':'live-voice-strip', 'data-rec':phase === 'rec' ? '' : null},
      wave, h('span', {}, phase === 'rec' ? 'Listening ' : 'Asking for the microphone… ',
        phase === 'rec' ? h('span', {className:'live-voice-t', 'data-live-voice-t':sess.id}, liveVoiceClock(liveVoiceRec?.secs() || 0)) : null),
      h('span', {className:'grow'}),
      stop,
      h('button', {type:'button', className:'btn sm ghost', 'data-live-voice':'cancel', 'data-session':sess.id, 'data-key':'live-voice-cancel'}, 'Cancel'));
  };
  window.liveVoiceHint = sess => {
    const n = sess && liveVoiceShown() ? liveVoiceNote.get(sess.id) : null;
    if (!n) return null;
    return n.kind === 'err'
      ? h('p', {className:'meta live-vhint', role:'alert', 'data-key':'live-voice-error'}, n.text)
      : h('p', {className:'meta live-vhint', role:'status', 'data-key':'live-voice-done'}, n.text);
  };

  async function liveVoiceWords(id, file) {
    const ctl = new AbortController();
    liveVoiceAt = {id, phase:'busy', ctl};
    repaint(null);
    let text = '', fail = '';
    try {
      const r = await fetch('/api/voice/words', {method:'POST', body:file, headers:{'Content-Type':file.type || 'audio/webm'}, signal:ctl.signal});
      if (r.ok) text = String((await r.json())?.text || '').trim();
      else fail = (await r.text()).trim().split('\n')[0].slice(0, 200) || LIVE_VOICE_SAY.failed;
    } catch (e) {
      if (e?.name === 'AbortError') return;  // cancelled: end() already ran
      fail = LIVE_VOICE_SAY.failed;
    }
    if (!liveVoiceAt || liveVoiceAt.ctl !== ctl) return;  // cancelled meanwhile
    if (!text) { end(id, {kind:'err', text:fail || LIVE_VOICE_SAY.empty}, 'live-voice'); return; }
    if (typeof liveMsgDraft === 'object') liveMsgDraft.set(id, liveVoiceJoin(liveMsgDraft.get(id), text));
    end(id, {kind:'done', text:LIVE_VOICE_DONE}, null);
    const box = document.querySelector(`#live-dock [data-live-msg-text="${id.replace(/["\\]/g, '')}"]`);
    if (box) {
      box.value = liveMsgDraft.get(id) || box.value;
      requestAnimationFrame(() => { box.focus({preventScroll:true}); box.setSelectionRange(box.value.length, box.value.length); });
    }
   
  }

  function liveVoiceStart(id) {
    if (liveVoiceAt || !liveVoiceShown()) return;
    liveVoiceNote.delete(id);
    const rec = window.UI.voiceRecorder({words:false, maxSecs:LIVE_VOICE_MAX_SECS,
      onState(on, how) {
        if (liveVoiceRec !== rec) return;
        if (on) {
          liveVoiceAt = {id, phase:'rec'};
          repaint(voiceSel(id, 'live-voice-stop'));
         
          return;
        }
        if (how?.cancelled) { end(id, null, 'live-voice'); }
        else if (how?.empty) { end(id, {kind:'err', text:LIVE_VOICE_SAY.empty}, 'live-voice'); }
      },
      onDone(file) { if (liveVoiceRec === rec) liveVoiceWords(id, file); },
      onError(_msg, code) {
        if (liveVoiceRec !== rec) return;
        const text = LIVE_VOICE_SAY[code] || LIVE_VOICE_SAY.none;
        end(id, {kind:'err', text}, 'live-voice');
       
      }});
    if (!rec) return;
    liveVoiceRec = rec;
    liveVoiceAt = {id, phase:'ask'};
    repaint(voiceSel(id, 'live-voice-cancel'));
    liveVoiceTimer = setInterval(tick, 500);
    rec.start();
  }
  function liveVoiceCancel() {
    if (!liveVoiceAt) return;
    const {id, phase, ctl} = liveVoiceAt;
    if (phase === 'busy') { ctl?.abort(); end(id, null, 'live-voice'); return; }
    liveVoiceRec?.cancel();  // onState(false, {cancelled}) ends it
  }

  document.addEventListener('click', e => {
    const b = e.target.closest?.('#live-dock [data-live-voice]');
    if (!b || b.disabled) return;
    const id = b.dataset.session, what = b.dataset.liveVoice;
    if (what === 'start') liveVoiceStart(id);
    else if (what === 'stop' && live(id) === 'rec') liveVoiceRec?.stop();
    else if (what === 'cancel' && liveVoiceAt?.id === id) liveVoiceCancel();
  });
  // Esc while listening cancels the voice only (it runs before the layer's own Esc, which would close the panel)
  document.addEventListener('keydown', e => {
    if (e.key !== 'Escape' || !liveVoiceAt || document.querySelector('dialog[open]')) return;
    e.preventDefault();
    e.stopPropagation();
    liveVoiceCancel();
  }, true);
  // typing in the box after the words landed: the line under it has done its job
  document.addEventListener('input', e => {
    const box = e.target.closest?.('#live-dock [data-live-msg-text]');
    if (box && liveVoiceNote.get(box.dataset.liveMsgText)?.kind === 'done') {
      liveVoiceNote.delete(box.dataset.liveMsgText);
      box.form?.querySelector('[data-key="live-voice-done"]')?.remove();
    }
  });
  // a sent message clears the line too (the box is empty again)
  document.addEventListener('submit', e => {
    const form = e.target.closest?.('#live-dock [data-live-msg]');
    if (form && liveVoiceNote.has(form.dataset.liveMsg)) liveVoiceNote.delete(form.dataset.liveMsg);
  }, true);
}
if (typeof module === 'object' && module.exports) module.exports = {liveVoiceOn, liveVoiceJoin, liveVoiceClock, LIVE_VOICE_SAY, LIVE_VOICE_DONE, LIVE_VOICE_MAX_SECS};
