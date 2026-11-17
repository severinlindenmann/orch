// The frame side of an add-on page orch ships, shown inside the dashboard (ORCH-186). The page runs sandboxed (an
// opaque origin): it can never read the dashboard's page secret or reach into the dashboard page. The dashboard
// hands it a pass for this add-on in the address fragment (#orch-frame=<pass>[&<the page's own hash>]); this
// script takes it out of the address at once and sends it as X-Orch-Frame on every call to this server.
// Load it FIRST (before any other script reads location.hash or calls fetch). Opened on its own (not framed, or
// not sandboxed) it does nothing.
(function () {
  var framed = false;
  try { framed = window.top !== window; } catch (e) { framed = true; }
  var off = {on: false, url: function (u) { return u; }, EventSource: window.EventSource};
  if (!framed || self.origin !== 'null') { window.OrchFrame = off; return; }

  var HEADER = 'X-Orch-Frame', PARAM = 'orch-frame';
  var here = location.protocol + '//' + location.host;  // the dashboard's origin (the frame's own is opaque)
  var m = /^#orch-frame=([A-Za-z0-9_-]{20,64})(?:&(.*))?$/.exec(location.hash || '');
  var pass = m ? m[1] : '';
  if (m) {
    try { history.replaceState(null, '', location.pathname + location.search + (m[2] ? '#' + m[2] : '')); }
    catch (e) { location.replace('#' + (m[2] || '')); }
  }
  function same(u) {
    try { var x = new URL(u, location.href); return x.protocol + '//' + x.host === here; } catch (e) { return false; }
  }
  function tell(msg) { try { window.parent.postMessage(msg, here); } catch (e) { /* not in the dashboard */ } }
  // No pass (a reload inside the frame, an expired pass, a restarted dashboard): ask the dashboard to show this
  // place again with a fresh one. At most once every 5 seconds.
  var asked = 0;
  function renew() {
    var now = Date.now();
    if (now - asked < 5000) return;
    asked = now;
    tell({orch: 'frame-go', path: location.pathname, hash: (location.hash || '').slice(1), fresh: true});
  }
  if (!pass) renew();

  var realFetch = window.fetch;
  window.fetch = function (input, init) {
    var url = (typeof Request !== 'undefined' && input instanceof Request) ? input.url : String(input);
    if (pass && same(url)) {
      init = Object.assign({}, init || {});
      var h = new Headers(init.headers || (typeof input !== 'string' && input ? input.headers : undefined) || {});
      h.set(HEADER, pass);
      init.headers = h;
    }
    return realFetch.call(this, input, init).then(function (r) {
      if (r.status === 401 && same(url)) renew();
      return r;
    });
  };

  // A picture, file or download address of this server: the pass rides along as a query value (an <img> or a
  // link cannot send a header). The dashboard takes it off before the add-on sees the request.
  function withPass(u) {
    if (!pass || typeof u !== 'string' || !same(u)) return u;
    var x = new URL(u, location.href);
    x.searchParams.set(PARAM, pass);
    return u.charAt(0) === '/' && u.charAt(1) !== '/' ? x.pathname + x.search + x.hash : x.href;
  }

  // EventSource cannot send a header: the same stream read with fetch (only what the pages use: named events,
  // onopen, onerror, close).
  function FrameEvents(url) {
    var self_ = this, ctl = new AbortController(), handlers = {};
    this.onopen = null; this.onerror = null; this.onmessage = null;
    this.addEventListener = function (name, fn) { (handlers[name] = handlers[name] || []).push(fn); };
    this.close = function () { ctl.abort(); };
    function emit(name, data) {
      var ev = {type: name, data: data};
      (handlers[name] || []).forEach(function (fn) { try { fn(ev); } catch (e) { /* the page's own */ } });
      if (name === 'message' && self_.onmessage) self_.onmessage(ev);
    }
    window.fetch(url, {signal: ctl.signal, headers: {Accept: 'text/event-stream'}}).then(function (r) {
      if (!r.ok || !r.body) throw new Error('no stream');
      if (self_.onopen) self_.onopen({type: 'open'});
      var reader = r.body.getReader(), dec = new TextDecoder(), buf = '';
      function pump() {
        return reader.read().then(function (part) {
          if (part.done) throw new Error('closed');
          buf += dec.decode(part.value, {stream: true});
          var at;
          while ((at = buf.indexOf('\n\n')) >= 0) {
            var block = buf.slice(0, at); buf = buf.slice(at + 2);
            var name = 'message', data = [];
            block.split('\n').forEach(function (line) {
              if (line.indexOf('event:') === 0) name = line.slice(6).trim();
              else if (line.indexOf('data:') === 0) data.push(line.slice(5).replace(/^ /, ''));
            });
            if (data.length) emit(name, data.join('\n'));
          }
          return pump();
        });
      }
      return pump();
    }).catch(function () { if (!ctl.signal.aborted && self_.onerror) self_.onerror({type: 'error'}); });
  }

  // Links: a place of this add-on is opened by the dashboard (so the new page gets a pass), a link to the
  // dashboard's own page (target _top, "/#...") moves the dashboard. Nothing else leaves the frame on its own.
  document.addEventListener('click', function (e) {
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    var a = e.target && e.target.closest ? e.target.closest('a[href]') : null;
    if (!a || a.hasAttribute('download')) return;
    var target = (a.getAttribute('target') || '').toLowerCase(), u;
    try { u = new URL(a.getAttribute('href'), location.href); } catch (err) { return; }
    if (!same(u.href)) return;
    if (target === '_top' || target === '_parent') {
      if (u.pathname === '/' && !u.search) { e.preventDefault(); tell({orch: 'frame-top', hash: u.hash.slice(1)}); }
      return;
    }
    if ((target && target !== '_self') || u.search) return;
    if (u.pathname === location.pathname && u.hash) return;  // a place on this page: the browser scrolls
    e.preventDefault();
    tell({orch: 'frame-go', path: u.pathname, hash: u.hash.slice(1)});
  });

  window.OrchFrame = {on: true, url: withPass, EventSource: FrameEvents};
})();
