'use strict';
/* Record a call (ORCH-1104): opened from Meetings in Personal (/record.html#for=<add-on>). A page of its own because a
   browser lets only a page with a real address share a screen's sound or use the microphone, never the sandboxed
   frame an add-on page runs in. The person says everyone agreed (one click), shares the call (a browser tab's sound or
   the whole system's) and talks; UI.meetingRecorder (the master kit) hands over a piece every 100 s, each piece goes
   through the dashboard's speech path (POST /api/voice/words: the relay, then our own service or Deepgram) and its
   words go to the add-on (op meet_record), so the transcript grows on the meeting while the call runs. The sound is
   never kept: a piece is dropped once its words arrived. */
(function (root) {
  const ADDON = /^[a-z][a-z0-9-]{1,31}$/;
  const PIECE_SECS = 100, TRIES = 3, WAITS = [2000, 5000, 10000], MAX_TEXT = 1800;
  const WORDS = {
    signIn: 'Sign in to the dashboard first, then open Record again from Meetings.',
    offline: 'The dashboard does not answer. Check that orch is running, then try again.',
    failed: 'The words could not be written down right now.',
  };

  // --- the model (no page needed: tests run it with a fake fetch) ------------------------------------------
  function target(hash) {
    const m = /(?:^#|&)for=([^&]*)/.exec(hash || '');
    return m && ADDON.test(m[1]) ? m[1] : null;
  }
  function newRef(now, rnd) {
    const d = new Date(now), p = n => String(n).padStart(2, '0');
    return 'browser-' + d.getFullYear() + p(d.getMonth() + 1) + p(d.getDate()) + '-' + p(d.getHours()) + p(d.getMinutes()) + p(d.getSeconds()) + '-' + rnd;
  }
  // The time on this computer's clock with its offset (2026-11-25T11:15:00+01:00): the meeting's title reads it as is.
  function localIso(ms) {
    const d = new Date(ms), p = n => String(Math.floor(Math.abs(n))).padStart(2, '0'), off = -d.getTimezoneOffset();
    return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate()) + 'T' + p(d.getHours()) + ':' + p(d.getMinutes()) + ':' + p(d.getSeconds())
      + (off < 0 ? '-' : '+') + p(off / 60) + ':' + p(off % 60);
  }
  function clock(iso) {
    const d = new Date(iso);
    return isNaN(d) ? '' : String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
  }
  // Long words go in parts the add-on takes in one request each (its limit is a few kilobytes), split at a space.
  function splitText(text, max) {
    max = max || MAX_TEXT;
    const out = [];
    let rest = String(text || '').trim();
    while (rest.length > max) {
      let cut = rest.lastIndexOf(' ', max);
      if (cut < max / 2) cut = max;
      out.push(rest.slice(0, cut).trim());
      rest = rest.slice(cut).trim();
    }
    if (rest) out.push(rest);
    return out;
  }
  // What an answer of /api/voice/words means: words, nothing heard, try again later, or stop (no sense to go on).
  function wordsAnswer(status, body) {
    if (status === 200) {
      let text = '';
      try { text = String(JSON.parse(body).text || ''); } catch (e) { text = ''; }
      return {kind: 'words', text: text.trim()};
    }
    if (status === 422) return {kind: 'words', text: ''};
    const said = String(body || '').trim();
    const plain = said && !/^</.test(said) && said.length < 300 ? said : '';
    if (status === 401 || status === 403) return {kind: 'stop', text: WORDS.signIn};
    if (status === 409 || status === 413 || status === 415) return {kind: 'stop', text: plain || WORDS.failed};
    return {kind: 'again', text: plain || WORDS.failed};
  }

  /* One recording: begin() makes the meeting, piece() writes one piece down (in order), finish() closes it.
     io: {fetch, sleep, addon, rec, started, consentAt, meetingAudio, onChange}. */
  function session(io) {
    const sleep = io.sleep || (ms => new Promise(r => setTimeout(r, ms)));
    const failed = new Map();   // n -> {blob, info, text}: kept in memory for Try again
    let chain = Promise.resolve(), written = 0, stopped = null;
    const changed = () => io.onChange && io.onChange(view());
    const view = () => ({written, failed: failed.size, stopped, why: [...failed.values()].map(f => f.text)[0] || ''});
    async function act(args) {
      let r;
      try {
        r = await io.fetch('/addon/' + io.addon + '/api/act', {method: 'POST', credentials: 'same-origin',
          headers: {'Content-Type': 'application/json'}, body: JSON.stringify({op: 'meet_record', args: {rec: io.rec, ...args}})});
      } catch (e) { return {kind: 'again', text: WORDS.offline}; }
      const text = await r.text().catch(() => '');
      let body = null;
      try { body = JSON.parse(text); } catch (e) { body = null; }
      if (r.ok && body && !body.error) return {kind: 'ok', result: body.result};
      if (r.status === 401 || r.status === 403) return {kind: 'stop', text: WORDS.signIn};
      if (body && body.error) return {kind: 'stop', text: String(body.error)};
      return {kind: 'again', text: WORDS.offline};
    }
    async function tryHard(step) {
      let got;
      for (let i = 0; i < TRIES; i++) {
        got = await step();
        if (got.kind !== 'again') return got;
        if (i < TRIES - 1) await sleep(WAITS[i]);
      }
      return got;
    }
    async function begin() {
      const got = await tryHard(() => act({started: io.started, consent_at: io.consentAt, meeting_audio: !!io.meetingAudio}));
      if (got.kind !== 'ok') { stopped = got.text; changed(); }
      return got;
    }
    async function write(blob, info) {
      const heard = await tryHard(async () => {
        let r;
        try {
          r = await io.fetch('/api/voice/words', {method: 'POST', credentials: 'same-origin',
            headers: {'Content-Type': (blob.type || 'audio/webm').split(';')[0]}, body: blob});
        } catch (e) { return {kind: 'again', text: WORDS.offline}; }
        return wordsAnswer(r.status, await r.text().catch(() => ''));
      });
      if (heard.kind !== 'words') return heard;
      const parts = splitText(heard.text);
      for (let k = 0; k < Math.max(1, parts.length); k++) {
        const got = await tryHard(() => act({n: info.n, k, at: clock(info.at), text: parts[k] || '', secs: info.secs}));
        if (got.kind !== 'ok') return got;
      }
      return {kind: 'ok'};
    }
    function piece(blob, info) {
      chain = chain.then(async () => {
        if (stopped) { failed.set(info.n, {blob, info, text: stopped}); return changed(); }
        const got = await write(blob, info);
        if (got.kind === 'ok') { written++; failed.delete(info.n); }
        else {
          failed.set(info.n, {blob, info, text: got.text});
          if (got.kind === 'stop') stopped = got.text;
        }
        changed();
      });
      return chain;
    }
    function again() {
      stopped = null;
      const todo = [...failed.values()].sort((a, b) => a.info.n - b.info.n);
      todo.forEach(f => piece(f.blob, f.info));
      return chain;
    }
    async function finish(secs, missing) {
      await chain;
      const got = await tryHard(() => act({done: true, minutes: Math.max(1, Math.round((secs || 0) / 60)), missing: missing ? failed.size : 0}));
      return got;
    }
    return {begin, piece, again, finish, view, idle: () => chain};
  }

  root.RecordModel = {target, newRef, localIso, clock, splitText, wordsAnswer, session, PIECE_SECS};
  if (typeof document === 'undefined' || !document.getElementById('rec')) return;

  // --- the page --------------------------------------------------------------------------------------------
  const box = document.getElementById('rec');
  const el = (tag, cls, ...kids) => { const e = document.createElement(tag); if (cls) e.className = cls; kids.flat().forEach(k => k != null && e.append(k)); return e; };
  const btn = (label, cls, onClick) => { const b = el('button', cls, label); b.type = 'button'; b.addEventListener('click', onClick); return b; };
  const say = t => { document.getElementById('announcement').textContent = t; };
  const show = (...kids) => { box.replaceChildren(...kids.filter(Boolean)); };
  const addon = target(location.hash);
  const UIK = window.UI || {};
  let rec = null, run = null, tickT = null, levels = {mic: null, meeting: null}, heard = {mic: false, meeting: false}, consentAt = '';
  let meetingAudio = false, started = '';

  function unavailable(title, text) { show(UIK.state({kind: 'empty', title, text})); }
  function fatal(text) {
    show(UIK.state({kind: 'error', title: 'The recording stopped', text, action: {label: 'Start again', onClick: () => location.reload()}}));
  }
  function consent() {
    const go = btn('Everyone agreed, record', 'btn primary', share);
    show(el('div', 'card pad stack-sm',
      el('p', null, el('strong', null, 'Ask everyone on the call first. Record only when all of them agreed.')),
      el('div', 'row', go),
      el('p', 'meta', 'Next your browser asks what to share: pick the call’s tab or your whole screen, and turn on its sound. Only the sound is recorded.')));
    go.focus();
  }
  async function share(tab) {
    if (!consentAt) consentAt = localIso(Date.now());
    show(el('div', 'card pad stack-sm', el('p', null, el('strong', null, 'Pick the call in your browser’s window')),
      el('p', 'meta', 'Choose the tab with the call, or your whole screen, and turn on “Share audio”.')));
    let got;
    try { got = await rec.share({tab: tab === true}); }
    catch (e) { return e.code === 'cancelled' ? missing(true) : fatal(e.message); }
    if (got.meeting === 'missing') return missing(false);
    begin(false);
  }
  function missing(cancelled) {
    const tab = btn('Use the Teams web tab', 'btn primary', () => share(true));
    const teams = el('a', null, 'Open Teams in the browser'); teams.href = 'https://teams.microsoft.com/'; teams.target = '_blank'; teams.rel = 'noopener';
    show(el('div', 'banner attn', el('div', 'grow stack-sm',
      el('strong', null, cancelled ? 'Nothing was shared' : 'The call’s sound is not shared'),
      el('p', null, cancelled ? 'Without the call’s sound only your own voice would be recorded.'
        : 'Your browser gave no sound with what you picked, so only your own voice would be recorded. A browser tab’s sound always works.'),
      el('p', 'meta', 'Join the call in Teams on the web, then pick its tab and turn on “Also share tab audio”. ', teams, '.'),
      el('div', 'row', tab, btn('Record only my microphone', 'btn outline', () => begin(true)), btn('Cancel', 'btn ghost', () => window.close())))));
    tab.focus();
  }
  async function begin(micOnly) {
    show(el('div', 'card pad', el('p', 'meta', 'Starting…')));
    let src;
    try { src = await rec.start({micOnly}); }
    catch (e) { return fatal(e.message); }
    meetingAudio = src.meeting === 'captured';
    started = localIso(Date.now());
    run = session({fetch: (u, o) => fetch(u, o), addon, rec: newRef(Date.now(), Math.random().toString(36).slice(2, 8)), started, consentAt, meetingAudio,
      onChange: paint});
    const ok = await run.begin();
    if (ok.kind !== 'ok') { rec.cancel(); return fatal(ok.text); }
    say('Recording.');
    recording(src);
  }
  let live = null;
  function recording(src) {
    const t = el('span', 'live-voice-t', '0:00');
    const wave = el('span', 'live-voice-wave'); wave.setAttribute('aria-hidden', 'true');
    for (let i = 0; i < 12; i++) wave.append(el('i'));
    const stop = btn('Stop', 'btn primary sm', finish);
    const bar = el('div', 'live-voice', wave, el('span', null, 'Recording ', t), el('span', 'grow'), stop);
    bar.setAttribute('role', 'status'); bar.dataset.rec = '';
    const row = (name, label) => { const dot = el('span', 'dot'), note = el('span', 'meta'); return {dot, note, el: el('div', 'list-row', dot, el('span', 'grow', label), note), name}; };
    const mic = row('mic', 'Your microphone'), call = row('meeting', 'The call’s sound');
    const count = el('p', 'meta');
    live = {t, mic, call, count, src};
    show(bar, el('div', 'card', mic.el, call.el), count,
      el('p', 'meta', 'Keep this window open while the call runs. The words land on the meeting in Personal every two minutes.'));
    paint(run.view());
    tickT = setInterval(paint, 500);
    stop.focus();
  }
  function paint(v) {
    if (!live) return;
    v = v && typeof v === 'object' ? v : run.view();
    const s = rec.secs();
    live.t.textContent = Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0');
    for (const [r, on] of [[live.mic, live.src.mic === 'on'], [live.call, live.src.meeting === 'captured']]) {
      const lv = levels[r.name];
      if (lv > 0.02) heard[r.name] = true;
      r.dot.className = 'dot ' + (!on ? 'bad' : heard[r.name] ? 'ok' : 'idle');
      r.note.textContent = !on ? (r.name === 'mic' ? 'Not recorded: the microphone is off' : 'Not recorded: only your microphone')
        : lv > 0.02 ? 'Heard now' : heard[r.name] ? 'Recorded' : 'Quiet so far';
    }
    live.count.textContent = (v.written ? 'Written down so far: ' + v.written + (v.written === 1 ? ' part' : ' parts') : 'The first words arrive after two minutes.')
      + (v.failed ? ' · ' + v.failed + ' waiting to be written down' : '');
    if (v.stopped && rec.recording) finish();
  }
  async function finish() {
    if (!live) return;
    clearInterval(tickT); live = null;
    show(el('div', 'card pad stack-sm', el('p', null, el('strong', null, 'Writing down the last part…')), el('div', 'progress indeterminate', el('span'))));
    const secs = rec.secs();
    await rec.stop();
    await run.idle();
    const v = run.view();
    if (v.failed) return failedParts(secs, v);
    close(await run.finish(secs, false));
  }
  function failedParts(secs, v) {
    show(el('div', 'banner error', el('div', 'grow stack-sm',
      el('strong', null, v.failed === 1 ? '1 part could not be written down' : v.failed + ' parts could not be written down'),
      el('p', null, v.why || WORDS.failed),
      el('div', 'row', btn('Try again', 'btn primary', async () => { show(el('div', 'card pad', el('p', 'meta', 'Writing down…'))); await run.again(); const w = run.view(); return w.failed ? failedParts(secs, w) : close(await run.finish(secs, false)); }),
        btn('Finish without them', 'btn outline', async () => close(await run.finish(secs, true)))))));
  }
  function close(got) {
    if (got.kind !== 'ok') return fatal(got.text);
    say('The transcript is on the meeting.');
    show(el('div', 'banner success', el('div', 'grow stack-sm',
      el('strong', null, 'The transcript is on the meeting in Personal'),
      el('p', null, 'Open Meetings in Personal to read it and make tickets from it. The sound was not kept.'),
      el('div', 'row', btn('Close this window', 'btn primary', () => window.close())))));
  }

  addEventListener('beforeunload', e => { if (rec && rec.recording) { e.preventDefault(); e.returnValue = ''; } });
  if (!addon) unavailable('Open Record from Meetings', 'Go to Meetings in Personal and click Record.');
  else if (!window.isSecureContext) unavailable('This address can’t record a call', 'Browsers record only on a secure address. Open the dashboard with its https:// address, then Record again.');
  else if (!(rec = UIK.meetingRecorder && UIK.meetingRecorder({pieceSecs: PIECE_SECS, onPiece: (b, i) => run && run.piece(b, i),
    onLevel: l => { levels = l; }, onEnd: () => { say('Sharing stopped, so the recording stopped.'); finish(); }}))) {
    unavailable('This browser can’t record a call', 'Open the dashboard in Chrome or Edge on a computer, then Record again from Meetings.');
  } else consent();
})(typeof window !== 'undefined' ? window : globalThis);
