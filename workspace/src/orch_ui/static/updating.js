/* "orch is updating" page (ORCH-1794, option A: the steps with their times, the step list of "Add several at once").
   The Windows update finisher serves updating.html on the dashboard address while the dashboard is off, and
   /orch-updating/state from its step file (finish.step). This script asks for that state every second; once
   something else answers there (the dashboard is back), it opens the dashboard by loading the same address.
   The mockup renders a sample through window.ORCH_UPDATING_SAMPLE ({state, lost, back}) and asks nothing. */
(function () {
  'use strict';
  var STATE = '/orch-updating/state';
  var last = null, skew = 0, lost = false, back = false, timer = 0;

  function $(k) { return document.querySelector('[data-u="' + k + '"]'); }
  function took(s) { s = Math.max(0, Math.round(Number(s) || 0)); return s < 90 ? s + ' s' : Math.round(s / 60) + ' min'; }
  function clock(s) {
    s = Math.max(0, Math.floor(Number(s) || 0));
    var m = Math.floor(s / 60), r = s % 60;
    return m + ':' + (r < 10 ? '0' : '') + r;
  }
  function now() { return Date.now() / 1000 + skew; }
  function node(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }
  function icon(look) {
    var e = node('span', 'run-ic' + (look === 'now' ? '' : ' is-' + look));
    e.setAttribute('aria-hidden', 'true');
    if (look === 'now') e.appendChild(node('span', 'spinner'));
    else e.textContent = look === 'done' ? '✓' : look === 'bad' ? '×' : look === 'skip' ? '–' : '';
    return e;
  }
  function show(k, on) { var e = $(k); if (e) e.hidden = !on; }
  function text(k, t) { var e = $(k); if (e) e.textContent = t; }

  // The steps with their look: done, now, todo, bad (the step that failed), skip (not run after it).
  function looks(st) {
    var names = Array.isArray(st.names) ? st.names : [], total = names.length;
    var n = Math.min(Math.max(1, Number(st.n) || 1), total || 1);
    var bad = st.result === 'fail' ? Number(st.bad) || 0 : 0;
    if (lost || st.result) n = total; // the page server stops only when the services start again
    return names.map(function (name, i) {
      var k = i + 1, look = k < n ? 'done' : k === n ? 'now' : 'todo';
      if (bad && k < total) look = k < bad ? 'done' : k === bad ? 'bad' : 'skip';
      if (back && k === total) look = 'done';
      return {name: String(name), look: look, k: k};
    });
  }

  function render(st) {
    if (!st) return;
    var steps = looks(st), total = steps.length, failed = st.result === 'fail', ok = st.result === 'ok' && !failed;
    var nowStep = steps.filter(function (s) { return s.look === 'now'; })[0];
    var took_ = Array.isArray(st.took) ? st.took : [], usual = Array.isArray(st.usual) ? st.usual : [];
    text('title', failed ? 'The update did not finish' : ok ? 'orch is updated' : 'orch is updating');
    text('lead', failed ? 'Your tickets are safe. The dashboard is starting again.'
      : 'The dashboard is back in a few minutes. This page opens it by itself.');
    show('lead', !ok);
    text('foot', failed ? 'Try the update again later.' : 'Your tickets are safe. Helpers that are working keep going.');
    show('foot', !ok);
    var card = $('card');
    if (card) card.setAttribute('role', failed ? 'alert' : 'status');
    show('head', !ok && !failed);
    text('count', nowStep ? 'Step ' + nowStep.k + ' of ' + total : 'Updating');
    text('all', st.began ? clock(now() - Number(st.began)) + ' in all' : '');
    var list = $('steps');
    if (list) {
      list.textContent = '';
      list.hidden = ok;
      steps.forEach(function (s) {
        var li = node('li', 'run-step is-' + s.look);
        if (s.look === 'now') li.setAttribute('aria-current', 'step');
        var body = node('span', null, s.name), sub = '';
        if (s.look === 'done' && typeof took_[s.k - 1] === 'number') sub = took(took_[s.k - 1]);
        if (s.look === 'now' && s.k === Number(st.n) && !lost && st.since) {
          sub = took(now() - Number(st.since)) + ' so far';
          if (typeof usual[s.k - 1] === 'number') sub += ' · last time ' + took(usual[s.k - 1]);
        }
        if (sub) body.appendChild(node('span', 'meta run-sub', sub));
        if (s.look === 'bad' && st.reason) body.appendChild(node('span', 'meta run-sub run-reason', String(st.reason)));
        li.appendChild(icon(s.look));
        li.appendChild(body);
        list.appendChild(li);
      });
    }
    show('bar', !ok && !failed);
    show('opening', ok);
    var open = $('open');
    if (open) {
      open.href = location.href;
      open.textContent = failed ? 'Open the dashboard' : 'Open it now';
      open.className = failed ? 'btn primary' : 'btn';
      open.hidden = !(ok || (failed && back));
    }
  }

  function ask() {
    fetch(STATE, {cache: 'no-store', credentials: 'omit'}).then(function (r) {
      var ours = r.ok && /json/.test(r.headers.get('Content-Type') || '');
      return ours ? r.json().catch(function () { return null; }) : null;
    }).then(function (st) {
      if (st && st.orch_updating === true) {
        if (typeof st.now === 'number') skew = st.now - Date.now() / 1000;
        last = st;
        lost = false;
        return render(st);
      }
      back = true; // something else answers on this address now: the dashboard
      if (last && last.result === 'fail') { clearInterval(timer); return render(last); }
      clearInterval(timer);
      render(last || {result: 'ok', names: []});
      location.replace(location.href);
    }, function () {
      lost = true; // nothing answers: the dashboard is starting
      render(last);
    });
  }

  function boot() {
    var sample = window.ORCH_UPDATING_SAMPLE;
    if (sample && sample.state) {
      lost = !!sample.lost;
      back = !!sample.back;
      skew = Number(sample.state.now || 0) - Date.now() / 1000;
      return render(sample.state);
    }
    ask();
    timer = setInterval(ask, 1000);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
