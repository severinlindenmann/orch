/* The Start button and the Start choice (ORCH-485, look: mockup ticket/ticket-start.html, gallery #start-button).
   UI.startButton(host, o) fills host with .start-split: the main button starts the usual way in one click (Continue
   when an earlier session can be reopened, else Start); the caret opens the Start choice (.start-pop around .live-start):
   continue, fresh start with tool and model, an earlier session; helper places in use. While it starts both halves are
   disabled and the main half says Starting… until the page reports the helper runs. A greyed choice says why.
   Logic in start-choice-state.js (StartChoiceState, tested without a browser). Plain DOM, textContent only.

   o: {ticket (id), name (key or title, for labels), label ('Start helper'), continueLabel ('Continue'), style ('outline' by default: a start costs, so it is never filled, UX D2 and ORCH-415; 'primary' only where a page has no other main action),
       align ('start' opens the choice to the right), send(op, args) -> Promise<{ok, text}> (the page's act()),
       sessions (GET /api/sessions/<ticket> answer, null while it loads), runs, settings, line (state.start_line),
       agents (settings.agents), model (the ticket's model), running (a helper works on it now),
       before() -> ops to send first (Send and start: the message) or null to stop, toast(text, kind)}
   Returns {el, update(changes), open(), close()}. Pages call update({running, sessions, runs, ...}) on every refresh;
   update({running:true}) also ends Starting. */
(() => {
  'use strict';
  const UI = window.UI = window.UI || {};
  const S = window.StartChoiceState;
  if (!S) return;
  const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };
  const attr = (n, a) => { Object.entries(a).forEach(([k, v]) => { if (v === null || v === undefined || v === false) n.removeAttribute(k); else n.setAttribute(k, v === true ? '' : String(v)); }); return n; };
  let uid = 0;
  const picks = new Map(); /* ticket -> {tool, model} the person picked (this page only) */
  /* One starter per page, so two buttons for the same ticket (strip and composer) share the busy state. */
  UI.startStarter = UI.startStarter || null;
  const starterFor = send => UI.startStarter || (UI.startStarter = S.starter({send: (op, args) => send(op, args)}));

  UI.startButton = function startButton(host, o) {
    o = Object.assign({label: 'Start helper', continueLabel: 'Continue', style: 'outline'}, o || {});
    const me = 'start-' + (++uid);
    let sendNow = o.send;
    const starter = starterFor((op, args) => sendNow(op, args));
    const wrap = el('span', 'start-split');
    if (o.align) wrap.dataset.align = o.align;
    const whyLine = el('p', 'start-why');
    whyLine.hidden = true;
    host.replaceChildren(wrap, whyLine);
    let isOpen = false;
    const toast = (text, kind) => (o.toast || (UI.toast ? t => UI.toast(t) : () => {}))(text, kind);

    const view = () => S.sessions(o.sessions, new Date(), UI.stamp ? (at, now) => UI.stamp(at.toISOString(), {now: now.toISOString()}) : null);
    const pickOf = () => {
      const t = S.tools(o.agents), was = picks.get(o.ticket) || {}, cur = S.model({model: o.model});
      const tool = t.tools.some(x => x.name === was.tool) ? was.tool : t.usual;
      return {tools: t, tool, model: was.model || cur.name, cur};
    };
    const ctx = extra => {
      const p = S.places(o.runs, o.settings, o.line);
      return Object.assign({starting: starter.starting(o.ticket), running: !!o.running, inLine: !!S.inLine(p, o.ticket), tools: pickOf().tools}, extra || {});
    };
    /* A greyed button and its reason: the reason is a visible line, tied to the button with aria-describedby. */
    function greyable(btn, reason, box) {
      if (!reason) return btn;
      btn.disabled = true;
      const w = el('p', 'start-why', reason);
      w.id = me + '-why-' + (box.children.length + 1);
      btn.setAttribute('aria-describedby', w.id);
      box.append(w);
      return btn;
    }
    /* A small picker (owner, ORCH-484: tool and model as two small selects; the kit's select.js dresses them). */
    function sel(label, list, cur, what, onPick) {
      const s = attr(el('select'), {'aria-label': label});
      s.dataset.startPick = what;
      list.forEach(([v, text]) => { const op = el('option', '', text); op.value = v; if (cur === v) op.selected = true; s.append(op); });
      s.value = cur;
      s.addEventListener('change', () => {
        const p = pickOf(), next = {tool: p.tool, model: p.model};
        next[what] = s.value;
        picks.set(o.ticket, next);
        if (onPick) onPick();
      });
      return s;
    }
    /* Runs on: the tool (a picker only when there are two or more) and the model (or why the tool takes none). */
    function runRow() {
      const run = attr(el('span', 'start-run'), {role: 'group', 'aria-label': 'Runs on'});
      const modelBox = el('span');
      const modelPart = () => {
        const p = pickOf(), tool = p.tools.tools.find(x => x.name === p.tool), noModel = S.why('model', {tool});
        modelBox.replaceChildren(noModel ? el('span', 'meta', noModel) : sel('Model', S.MODELS, p.model, 'model'));
      };
      const p = pickOf(), tool = p.tools.tools.find(x => x.name === p.tool);
      if (p.tools.tools.length > 1) run.append(sel('Tool', p.tools.tools.map(x => [x.name, x.label]), p.tool, 'tool', modelPart));
      else if (tool) run.append(el('span', 'chip', tool.label));
      modelPart();
      run.append(modelBox);
      return run;
    }
    /* One way to start: title, one line, (extra), the button on the right; a greyed button says why under the line. */
    function opt(key, title, text, btn, reason, extra) {
      const li = el('li', 'start-opt');
      li.dataset.key = key;
      const t = el('div', 'start-opt-t');
      t.append(el('b', '', title), el('span', 'meta', text));
      if (extra) t.append(extra);
      li.append(t, greyable(btn, reason, t));
      return li;
    }
    function body() {
      const v = view(), lastRow = S.last(v.rows), hasLast = !!lastRow || v.state === 'loading', name = o.name || 'this ticket';
      const p = S.places(o.runs, o.settings, o.line), at = S.inLine(p, o.ticket);
      const box = el('div', 'live-start');
      if (starter.starting(o.ticket)) box.setAttribute('aria-busy', 'true');
      const head = el('div', 'start-pop-h');
      head.append(el('h3', 'live-start-h', 'Start a helper'));
      const pl = el('span', 'meta live-places', S.placesShort(p));
      if (p.full) pl.dataset.full = '';
      if (pl.textContent) head.append(pl);
      box.append(head);
      if (at) {
        box.append(el('p', 'meta', name + ' is number ' + at.at + ' of ' + at.of + ' in line. It starts by itself when a place is free.'));
        return box;
      }
      const list = el('ul', 'start-opts');
      if (hasLast) {
        const b = attr(el('button', 'btn outline sm', 'Continue'), {type: 'button', 'aria-label': 'Continue the last conversation on ' + name});
        b.dataset.start = 'continue';
        b.addEventListener('click', () => go([['run.start', {ticket: o.ticket}]], 'continue'));
        list.append(opt('start-continue', 'Continue where it stopped', lastRow ? 'Keeps the talk from ' + lastRow.day : 'Keeps the last talk', b, S.why('continue', ctx())));
      }
      const fb = attr(el('button', 'btn outline sm', hasLast ? 'Start again' : 'Start'), {type: 'button', 'aria-label': 'Fresh start on ' + name});
      fb.dataset.start = 'fresh';
      fb.addEventListener('click', () => { const pk = pickOf(); go(S.freshOps(o.ticket, pk, pk.tools.usual, pk.cur), 'fresh'); });
      list.append(opt('start-fresh', 'Fresh start', hasLast ? 'Starts over without the earlier talk' : 'Reads the ticket and starts on the first step', fb, S.why('fresh', ctx()), runRow()));
      box.append(list);
      const e = earlier(v);
      if (e) box.append(e);
      return box;
    }
    let more = false; /* the earlier sessions folded out (owner, ORCH-484: the newest one shows, the rest behind Show more) */
    function earlier(v) {
      if (v.state === 'empty') return null;
      const w = el('div', 'live-hist');
      w.dataset.key = 'start-earlier';
      const hid = me + '-earlier';
      const head = el('h4', 'live-hist-h', 'Earlier sessions');
      head.id = hid;
      w.append(head);
      if (v.state === 'loading') { w.append(el('p', 'meta', 'Loading the earlier sessions…')); return w; }
      if (v.state === 'error') { w.append(el('p', 'meta', 'The earlier sessions could not be loaded.')); return w; }
      const ul = attr(el('ul', 'live-hist-list'), {'aria-labelledby': hid});
      const rows = [];
      v.rows.forEach((r, i) => {
        const li = el('li', 'live-hist-row');
        li.hidden = i > 0 && !more;
        rows.push(li);
        if (r.current) li.dataset.current = '';
        const t = el('span', 'live-hist-t', r.title);
        t.title = r.title;
        const facts = el('span', 'meta live-hist-f', r.facts);
        li.append(el('span', 'live-hist-day', r.day), t, facts);
        if (r.current) { li.append(el('span', 'chip', 'In use')); ul.append(li); return; }
        const b = attr(el('button', 'btn outline sm', 'Reopen'), {type: 'button', 'aria-label': 'Reopen the session from ' + r.day});
        b.dataset.start = 'reopen';
        b.dataset.id = r.id;
        b.addEventListener('click', () => go([['session.reopen', {ticket: o.ticket, session: r.id}]], 'reopen'));
        const reason = S.why('reopen', ctx({row: r}));
        if (reason) {
          b.disabled = true;
          const y = el('span', 'start-why', reason);
          y.id = me + '-row-' + i;
          b.setAttribute('aria-describedby', y.id);
          if (facts.textContent) facts.append(document.createTextNode(' · '));
          facts.append(y);
        }
        li.append(b);
        ul.append(li);
      });
      w.append(ul);
      if (rows.length > 1) {
        const tog = attr(el('button', 'btn ghost xs start-more'), {type: 'button', 'aria-expanded': String(more)});
        tog.dataset.startMore = '';
        const say = () => { tog.textContent = more ? 'Show less' : 'Show ' + (rows.length - 1) + ' more'; tog.setAttribute('aria-expanded', String(more)); };
        say();
        tog.addEventListener('click', () => { more = !more; rows.forEach((li, i) => { if (i) li.hidden = !more; }); say(); });
        w.append(tog);
      }
      return w;
    }
    async function go(ops, how) {
      if (starter.starting(o.ticket)) return;
      const first = o.before ? await o.before() : [];
      if (first === null) return;
      isOpen = false;
      starter.start(o.ticket, [...(first || []), ...ops]).then(r => {
        if (r && r.ok && !r.again) {
          picks.delete(o.ticket);
          toast(how === 'fresh' ? 'Fresh start on ' + (o.name || 'the ticket') + ': the helper reads the ticket again.'
            : how === 'reopen' ? 'The helper continues that conversation.'
            : how === 'continue' ? 'The helper continues the last conversation on ' + (o.name || 'the ticket') + '.'
            : 'The helper starts on ' + (o.name || 'the ticket') + '.', 'ok');
        }
      });
    }
    function render(focus) {
      const busyNow = starter.starting(o.ticket);
      const v = view(), m = S.main(v, o), reason = S.why('main', ctx());
      const mb = attr(el('button', 'btn ' + o.style + ' sm'), {type: 'button'});
      mb.dataset.start = 'main';
      if (busyNow) {
        attr(mb, {disabled: true, 'aria-busy': 'true'});
        mb.append(attr(el('span', 'spinner'), {'aria-hidden': 'true'}), document.createTextNode('Starting…'));
      } else {
        mb.textContent = m.label;
        if (reason) attr(mb, {disabled: true});
        mb.addEventListener('click', () => go([['run.start', {ticket: o.ticket}]], m.what));
      }
      const menu = el('details', 'menu');
      if (isOpen && !busyNow) menu.open = true;
      const sum = attr(el('summary', 'btn ' + o.style + ' sm'), {'aria-label': 'Other ways to start'});
      sum.append(attr(el('span', 'chev'), {'aria-hidden': 'true'}));
      if (busyNow) {
        attr(sum, {'aria-disabled': 'true', tabindex: '-1'});
        sum.addEventListener('click', e => e.preventDefault());
      }
      menu.addEventListener('toggle', () => { isOpen = menu.open; });
      menu.append(sum);
      const pop = el('div', 'menu-pop start-pop');
      if (isOpen && !busyNow) pop.append(body());
      menu.addEventListener('toggle', () => { if (menu.open && !pop.firstChild) pop.append(body()); });
      menu.append(pop);
      const kids = [mb, menu];
      if (busyNow) kids.push(attr(el('span', 'sr-only', 'Starting the helper on ' + (o.name || 'the ticket') + '.'), {role: 'status'}));
      wrap.replaceChildren(...kids);
      /* the main button greyed (no tool, already in line): the reason as a visible line under it */
      const say = !busyNow && !o.running ? reason : '';
      whyLine.textContent = say;
      whyLine.hidden = !say;
      whyLine.id = me + '-main-why';
      if (say) mb.setAttribute('aria-describedby', whyLine.id);
      if (focus) wrap.querySelector(focus)?.focus({preventScroll: true});
    }
    const off = starter.subscribe(e => {
      if (e.ticket !== o.ticket) return;
      if (e.state === 'queued') toast((o.name || 'The ticket') + ' waits in line for a free helper place.', 'ok');
      else if (e.state === 'failed') toast(e.text, 'error');
      else if (e.state === 'slow') toast(e.text, 'error');
      if (wrap.isConnected === false) { off(); return; } /* the page painted a new button */
      const hadFocus = !!document.activeElement && wrap.contains(document.activeElement);
      render(hadFocus ? '[data-start="main"]' : null);
    });
    render();
    return {
      el: wrap,
      update(changes) {
        Object.assign(o, changes || {});
        if (changes && changes.send) sendNow = changes.send;
        if (o.running) starter.seen(o.ticket, true);
        render();
      },
      open() { isOpen = true; render('summary'); },
      close() { isOpen = false; render(); },
    };
  };
})();
