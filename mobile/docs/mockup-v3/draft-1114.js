// Draft 14 Nov: owner phone feedback A-E (static data, simulated actions).
(function () {
  const ic = {
    doc: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5M9 13h6M9 17h6M9 9h1"/></svg>',
    people: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="9" cy="8" r="3.5"/><path d="M3 20c0-3.3 2.7-6 6-6s6 2.7 6 6M16 4.5a3.5 3.5 0 0 1 0 7M18 14c2 .8 3 3 3 6"/></svg>',
    home: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"><path d="M4 10.5 12 4l8 6.5V20H4z"/><path d="M10 20v-5h4v5"/></svg>',
    mount: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"><path d="M3 19 8.5 7l3.5 6 2.5-4L21 19z"/></svg>',
    mic: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="9" y="3" width="6" height="12" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/></svg>',
    photo: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"><rect x="3" y="4" width="18" height="16" rx="3"/><circle cx="9" cy="10" r="2"/><path d="m21 16-5-5-9 9"/></svg>',
    cam: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"><path d="M4 8h3l2-3h6l2 3h3v11H4z"/><circle cx="12" cy="13" r="3.5"/></svg>',
    send: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M12 19V5M5 12l7-7 7 7"/></svg>',
    check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="m5 12 5 5L20 7"/></svg>',
    eyeoff: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M3 3l18 18M10.6 6.1A9.8 9.8 0 0 1 12 6c5 0 9 6 9 6a17 17 0 0 1-3 3.4M6.6 6.6C4.4 8.1 3 12 3 12s4 6 9 6a9 9 0 0 0 4.4-1.1"/></svg>',
    bellOff: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M3 3l18 18M17 17H4l2-2v-5a6 6 0 0 1 9.5-4.9M18 10v5"/><path d="M10 20a2 2 0 0 0 4 0"/></svg>',
    gear: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1 7 17M17 7l2.1-2.1"/></svg>'
  };
  const WS = {
    reports: { name: 'Reports', c: 'b-blue', i: ic.doc },
    dev: { name: 'Dev Team', c: 'b-purple', i: ic.people },
    home: { name: 'Home', c: 'b-orange', i: ic.home },
    pilatus: { name: 'Pilatus', c: 'b-cyan', i: ic.mount },
    acme: { name: 'Acme', c: 'b-indigo', i: '<b>A</b>' }
  };
  const badge = (k, cls = '') => `<span class="badge ${WS[k].c} ${cls}">${WS[k].i}</span>`;
  const $ = (id) => document.getElementById(id);
  const sb = '<div class="sb"><span>09:45</span><i></i><span>62%</span></div>';
  const phone = (id, inner) => { const el = $(id); if (el) el.innerHTML = sb + '<div class="scr">' + inner + '</div>'; return el; };

  // ---------- A ----------
  const QS = [
    { id: 'q1', t: 'Weekly numbers check', d: 'Reports · Thu 12 Nov', p: 'Week 45 is 2–8 Nov 2026, but this workspace has no numbers for it.' },
    { id: 'q2', t: 'Weekly numbers check', d: 'Reports · Thu 12 Nov', p: 'There are no numbers for week 45 (2–8 Nov) here: the visitors file only has months.' },
    { id: 'q3', t: 'Pick a lunch place', d: 'Dev Team · 09:12', p: 'Three places have a table for 8 on 20 Nov. Which one should I book?' }
  ];
  let hidden = [];
  function renderA() {
    const shown = QS.filter((q) => !hidden.includes(q.id));
    const rows = shown.map((q, n) => `<div class="qwrap" data-id="${q.id}"><button class="act" data-hide="${q.id}">${ic.eyeoff}Hide</button>
      <div class="qrow" data-id="${q.id}">${badge(q.d.startsWith('Dev') ? 'dev' : 'reports', 'sm')}<div class="m"><b>${q.t}</b><small>${q.d}</small><p>${q.p}</p></div><span class="chev">›</span></div></div>${n < shown.length - 1 ? '<div class="div" style="margin:0"></div>' : ''}`).join('');
    phone('phA', `<div class="navbar"><span class="circ">${ic.gear}</span><h3>Chats</h3><span class="circ" style="font-size:24px">+</span></div>
      ${shown.length ? `<div class="sect warn">Needs your OK · ${shown.length}</div><div class="card">${rows}</div>` : ''}
      <div class="sect">&nbsp;</div><div class="card">
        <div class="wrow">${badge('reports')}<div class="m"><b>Reports</b><small>Tasks: 2 of 2 done</small><small class="q">${QS.filter(q=>q.d.startsWith('Rep')).length} questions</small></div><time>Yesterday</time></div><div class="div"></div>
        <div class="wrow">${badge('dev')}<div class="m"><b>Dev Team</b><small>Made a test HTML page about…</small><small class="q">1 question</small></div><time>09:38</time></div><div class="div"></div>
        <div class="wrow">${badge('home')}<div class="m"><b>Home</b><small>Tasks: 0 of 3 done</small></div><time>Yesterday</time></div></div>
      <p class="hint">Hidden questions stay open in their chat.${hidden.length ? ' <button class="reset" id="aReset">show all again</button>' : ''}</p>`);
    $('phA').insertAdjacentHTML('beforeend', '<div class="toast" id="aToast"><span id="aToastT"></span><button id="aUndo">Undo</button></div>');
    const r = $('aReset'); if (r) r.onclick = () => { hidden = []; renderA(); renderA2(); };
    $('aUndo').onclick = () => { hidden.pop(); renderA(); renderA2(); };
    wireSwipe();
    renderA2();
  }
  let toastTimer;
  function hide(id) {
    const wrap = document.querySelector(`#phA .qwrap[data-id="${id}"]`);
    if (wrap) { wrap.style.height = wrap.offsetHeight + 'px'; wrap.classList.add('gone'); }
    setTimeout(() => {
      hidden.push(id); renderA();
      const q = QS.find((x) => x.id === id);
      $('aToastT').textContent = 'Hidden. It stays open in ' + q.d.split(' · ')[0] + '.';
      const t = $('aToast'); t.classList.add('on'); clearTimeout(toastTimer); toastTimer = setTimeout(() => t.classList.remove('on'), 5000);
    }, 230);
  }
  function wireSwipe() {
    document.querySelectorAll('#phA [data-hide]').forEach((b) => (b.onclick = () => hide(b.dataset.hide)));
    document.querySelectorAll('#phA .qrow').forEach((row) => {
      let x0 = null, dx = 0, open = false;
      row.addEventListener('pointerdown', (e) => { x0 = e.clientX; dx = 0; row.classList.add('drag'); row.setPointerCapture(e.pointerId); });
      row.addEventListener('pointermove', (e) => { if (x0 === null) return; dx = Math.min(0, e.clientX - x0 + (open ? -96 : 0)); row.style.transform = `translateX(${dx}px)`; });
      const end = () => {
        if (x0 === null) return; x0 = null; row.classList.remove('drag');
        const w = row.offsetWidth;
        if (dx < -w * 0.55) { row.style.transform = `translateX(${-w}px)`; hide(row.dataset.id); }
        else if (dx < -40) { row.style.transform = 'translateX(-96px)'; open = true; }
        else { row.style.transform = ''; open = false; }
      };
      row.addEventListener('pointerup', end); row.addEventListener('pointercancel', end);
    });
  }
  function renderA2() {
    const shown = QS.filter((q) => !hidden.includes(q.id)), hid = QS.filter((q) => hidden.includes(q.id));
    const item = (q, dim) => `<div class="qrow" style="cursor:default${dim ? ';opacity:.75' : ''}">${badge(q.d.startsWith('Dev') ? 'dev' : 'reports', 'sm')}<div class="m"><b>${q.t}</b><small>${q.d}</small><p>${q.p}</p></div><span class="chev">›</span></div>`;
    phone('phA2', `<div class="navbar"><span class="circ">${ic.gear}</span><h3>Chats</h3><span class="circ" style="font-size:24px">+</span></div>
      <div class="card" style="display:flex;padding:4px;gap:4px;font-size:14px;text-align:center"><span style="flex:1;padding:8px;color:var(--muted)">All</span><span style="flex:1;padding:8px;color:var(--muted)">Unread</span><span style="flex:1.6;padding:8px;background:var(--s3);border-radius:10px;white-space:nowrap">Needs your OK</span></div>
      <div class="sect warn">Needs your OK · ${shown.length}</div><div class="card">${shown.map((q) => item(q)).join('<div class="div" style="margin:0"></div>') || '<div class="hidden-row">Nothing waiting.</div>'}</div>
      <div class="sect">Hidden (${hid.length})</div><div class="card">${hid.length ? hid.map((q) => item(q, true)).join('<div class="div" style="margin:0"></div>') : '<div class="hidden-row"><span>Swipe a question left on the first phone.</span></div>'}</div>
      <p class="hint">Comes back when the helper writes again.</p>`);
  }
  renderA();

  // ---------- B ----------
  const gstack = (ks) => `<span class="gstack badge-col">${ks.map((k) => `<span class="badge ${WS[k].c}">${k === 'pilatus' ? WS[k].i : WS[k].name[0]}</span>`).join('')}</span>`;
  phone('phB', `<div class="card">
      <div class="wrow">${badge('home')}<div class="m"><b>Home</b><small>Tasks: 0 of 3 done</small></div><time>Yesterday</time><span class="chev">›</span></div><div class="div"></div>
      <div class="wrow">${badge('pilatus')}<div class="m"><b>Pilatus</b><small>Status: done</small></div><time>Yesterday</time><span class="chev">›</span></div></div>
    <div class="sect">Groups</div>
    <div class="gcard"><div class="wrow">${gstack(['pilatus', 'home', 'reports'])}<div class="m"><b>Team lunch 20 Nov</b><small>3 helpers · started 11 Nov</small></div><span class="chev">›</span></div></div>
    <div class="gcard"><div class="wrow">${gstack(['pilatus', 'home', 'reports'])}<div class="m"><b>Pay car tax 2027</b><small>3 helpers · started 9 Nov</small></div><span style="background:var(--brand);color:var(--onbrand);border-radius:999px;font-size:12px;font-weight:700;padding:1px 7px">2</span><span class="chev">›</span></div></div>
    <div class="gcard"><div class="wrow"><span class="badge badge-col" style="background:var(--s3);color:var(--muted);font-size:20px">✓</span><div class="m"><b>Finished groups</b></div><time>3</time><span class="chev">›</span></div></div>`);
  // B alignment line: highlight the 46 pt logo column in every row.
  document.querySelectorAll('#phB .wrow > .badge').forEach((b) => b.classList.add('badge-col'));
  $('guideBtn').onclick = () => { const g = $('phB'); g.classList.toggle('show'); $('guideBtn').textContent = g.classList.contains('show') ? 'hide alignment line' : 'show alignment line'; };

  // ---------- D ----------
  phone('phD0', `<div class="navbar small"><h3>Settings</h3></div>
    <div class="set-sect">Notifications</div><div class="card x"><div class="set-row"><div class="m"><b>Mute all</b><small>Silences notifications inside the app</small></div><span class="tog on"></span></div></div>
    <div class="set-sect">WORKSPACES</div><div class="card"><div class="set-row"><div class="m"><b>Connection</b></div><small style="color:var(--brand)">● Connected</small></div></div>
    <div class="set-sect">PREFERENCES</div><div class="card"><div class="x" style="border-radius:0"><div class="set-row"><div class="m"><b>Notifications</b><small>Questions and finished work</small></div><span class="tog on"></span></div></div><div class="div"></div>
    <div class="set-row"><div class="m"><b>Voice</b><small>Voice and languages</small></div><span class="chev">›</span></div></div>
    <p class="xlabel">Two switches with nearly the same words: which one stops the buzzing?</p>`);
  let muted = null; // null | label
  function renderD() {
    phone('phD', `<div class="navbar small"><h3>Settings</h3></div>
      <div class="set-sect">Notifications</div><div class="card"><div class="set-row"><div class="m"><b>Mute all</b><small>${muted ? 'Muted ' + muted : 'You get a notification for questions and finished work.'}</small></div><button class="tog ${muted ? 'on' : ''}" id="dTog" aria-label="Mute all"></button></div></div>
      <div id="dSheet"></div>
      <div class="set-sect">WORKSPACES</div><div class="card"><div class="set-row"><div class="m"><b>Connection</b></div><small style="color:var(--brand)">● Connected</small></div></div>
      <div class="set-sect">PREFERENCES</div><div class="card"><div class="set-row"><div class="m"><b>Voice</b><small>Voice and languages</small></div><span class="chev">›</span></div></div>`);
    $('dTog').onclick = () => {
      if (muted) { muted = null; renderD(); renderD2(); return; }
      $('dSheet').innerHTML = `<div class="sheetwrap"><div class="sheet"><div class="t">Mute all for how long?</div>${[['1 hour', 'until 10:45'], ['Until tomorrow 08:00', 'until tomorrow 08:00'], ['Until I unmute', 'until you unmute']].map(([a, b]) => `<button data-m="${b}">${a}</button>`).join('')}</div><div class="sheet"><button data-m="" style="font-weight:600;border-top:0">Cancel</button></div></div>`;
      document.querySelectorAll('#dSheet [data-m]').forEach((b) => (b.onclick = () => { muted = b.dataset.m || null; renderD(); renderD2(); }));
    };
  }
  function renderD2() {
    phone('phD2', `<div class="navbar"><span class="circ">${ic.gear}</span><h3>Chats</h3><span class="circ" style="font-size:24px">+</span></div>
      ${muted ? `<div class="banner">${ic.bellOff}<span>Muted ${muted}</span><button id="dUn">Unmute</button></div>` : `<div class="banner" style="opacity:.55">${ic.bellOff}<span>Muted until tomorrow 08:00</span><button>Unmute</button></div><p class="hint">(shown when Mute all is on: switch it on on the middle phone)</p>`}
      <div class="warnrow"><b>Notifications are off in iPhone Settings.</b><br>orch can't tell you about questions.<br><a href="#D">Open iPhone Settings</a></div>
      <p class="hint">Only shown when iPhone permission is off. Then it replaces the mute banner, never both.</p>`);
    const u = $('dUn'); if (u) u.onclick = () => { muted = null; renderD(); renderD2(); };
  }
  renderD(); renderD2();

  // ---------- E ----------
  const order = ['reports', 'dev', 'home', 'pilatus'];
  let eSel = 'reports', eState = 'start', eTimer = null, eSec = 0;
  const waveBars = () => '<div class="wave">' + Array.from({ length: 22 }, (_, i) => `<i style="height:${20 + ((i * 37) % 50)}px;animation-delay:${(i % 7) * 0.12}s"></i>`).join('') + '</div>';
  const fmt = (s) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
  function renderE() {
    clearInterval(eTimer);
    let body;
    if (eState === 'start') {
      body = `<div class="nt"><div class="nt-head"><h3>New topic</h3><button class="xbtn" aria-label="Close">×</button></div>
        <p class="wslabel">To</p><div class="wsrow">${order.slice(0, 3).map((k) => `<button class="wsbtn ${eSel === k ? 'sel' : ''}" data-ws="${k}">${badge(k)}${WS[k].name}</button>`).join('')}<button class="wsbtn" data-more>${'<span class="badge" style="background:var(--s3);color:var(--muted);font-size:20px">···</span>'}More</button></div>
        <button class="mic" id="eMic" aria-label="Talk to ${WS[eSel].name}">${ic.mic}</button>
        <p class="miclabel">Tap and talk</p><p class="micsub">to ${WS[eSel].name}</p>
        <div class="bigpair"><button class="bigbtn">${ic.photo}Photo</button><button class="bigbtn">${ic.cam}Camera</button></div>
        <button class="typeit">Type instead</button></div>`;
    } else if (eState === 'rec') {
      body = `<div class="nt"><div class="rec-top">${badge(eSel)}<div class="m"><b>${WS[eSel].name}</b><small>new topic</small></div></div>
        <div class="timer" id="eT">${fmt(eSec)}</div><div class="recdot">Recording</div>${waveBars()}
        <button class="sendbig" id="eSend">${ic.send}Send</button><button class="cancelbig" id="eCancel" style="margin-top:28px">Cancel</button></div>`;
    } else {
      body = `<div class="nt"><div class="donebox"><div class="ok">${ic.check}</div><b>Sent to ${WS[eSel].name}</b><small>The phone says “Sent to ${WS[eSel].name}” and buzzes once.<br>The answer comes as a voice memo.</small></div><button class="cancelbig" id="eUndo" style="background:#13302a;color:var(--brand)">Undo (5 s)</button><button class="cancelbig" id="eBack">Back to Chats</button></div>`;
    }
    phone('phE', body);
    document.querySelectorAll('#phE [data-ws]').forEach((b) => (b.onclick = () => { eSel = b.dataset.ws; renderE(); }));
    const more = document.querySelector('#phE [data-more]'); if (more) more.onclick = () => $('phEpick').scrollIntoView({ behavior: 'smooth', block: 'center' });
    const m = $('eMic'); if (m) m.onclick = () => { eState = 'rec'; eSec = 0; renderE(); };
    if (eState === 'rec') {
      eTimer = setInterval(() => { eSec++; const t = $('eT'); if (t) t.textContent = fmt(eSec); }, 1000);
      $('eSend').onclick = () => { eState = 'sent'; renderE(); };
      $('eCancel').onclick = () => { eState = 'start'; renderE(); };
    }
    const un = $('eUndo'); if (un) un.onclick = () => { eState = 'start'; renderE(); };
    const bk = $('eBack'); if (bk) bk.onclick = () => { eState = 'start'; renderE(); };
  }
  $('eReset').onclick = () => { eState = 'start'; eSel = 'reports'; renderE(); };
  renderE();
  phone('phEpick', `<div class="nt"><div class="nt-head" style="justify-content:flex-start;gap:10px"><button class="xbtn" aria-label="Back">‹</button><h3>Send to</h3></div>
    <div class="pickgrid">${[...order, 'acme'].map((k) => `<button class="wsbtn ${k === 'reports' ? 'sel' : ''}" data-pick="${k}">${badge(k)}${WS[k].name}</button>`).join('')}</div>
    <p class="hint" style="margin-top:auto">Most used first. One tap picks and goes back.</p></div>`);
  document.querySelectorAll('#phEpick [data-pick]').forEach((b) => (b.onclick = () => { eSel = b.dataset.pick; if (!order.includes(eSel)) order.splice(2, 0, eSel), order.length = 4; eState = 'start'; renderE(); document.querySelectorAll('#phEpick [data-pick]').forEach((x) => x.classList.toggle('sel', x === b)); }));
  phone('phE2', `<div class="nt"><div class="rec-top">${badge('reports')}<div class="m"><b>Reports</b><small>last used</small></div><button class="chg" style="min-height:56px;padding:0 18px;font-size:16px">Change</button></div>
    <div class="timer">0:04</div><div class="recdot">Recording</div>${waveBars()}
    <button class="sendbig">${ic.send}Send</button><button class="cancelbig" style="margin-top:28px">Cancel</button>
    <p class="hint">Opens already recording. Setting: Voice › Start recording right away.</p></div>`);
  phone('phE0', `<div class="navbar small"><h3>New topic</h3></div>
    <div style="display:flex;gap:8px;align-items:center;margin:8px 0 14px"><span style="color:var(--muted)">To:</span><span style="background:var(--s3);border-radius:12px;padding:10px 14px;font-weight:600">Reports ⌄</span></div>
    <div style="display:flex;gap:8px;align-items:center;background:var(--s2);border-radius:26px;padding:6px 6px 6px 14px"><span style="flex:1;color:var(--muted)">Message…</span><span class="circ" style="width:34px;height:34px">${ic.mic.replace('<svg', '<svg width="18" height="18"')}</span></div>
    <p style="color:var(--muted);font-size:13px">Start something with Reports.</p>
    <div style="position:absolute;left:0;right:0;bottom:0;height:290px;background:#1f232a;border-top:1px solid var(--border);display:grid;place-items:center;color:var(--muted);font-size:13px">keyboard</div>`);
})();
