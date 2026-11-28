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
       before(ops) -> ops to send first (Send and start: the message) or null to stop; it gets the start the person
       picked, toast(text, kind), fresh (true: the main button is a fresh start on the usual tool and model, Home's Start
       fresh), caretOnly (true: only the caret and the Start choice; the page keeps its own main button, the composer's
       Send and start helper, given as mainEl: it sits left of the caret and is disabled while it starts), caretHidden
       (true: no caret now, e.g. a helper already works), hasSessions (false: the ticket never ran, so no Continue while
       the earlier sessions load), why (ORCH-2201, inline only: {question:{id,text,options}|null, review:{text}|null, href, answer(text)->Promise<{ok,text}>}: a ticket that
       waits for the person; the choice starts with a "Why it waits" box, then Continue and a small Fresh start link), inline (true: the Start choice itself, drawn in place with no
       button or caret: the live page's pane of a ticket with no helper)}
   Returns {el, update(changes), open(), close(), start(how), starting()}: start() is the main button's click from
   elsewhere on the page (a keyboard key, a second Start in the feed); start('fresh') a fresh start on the usual tool
   and model. Pages call update({running, sessions, runs, ...}) on every refresh;
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
  /* The notices of a start come once, from the button that started it, even when the page drew that button again
     (two buttons of one ticket, a notice that closed): ticket -> {name, toast} of the start in progress. */
  const said = new Map();
  const starterFor = send => {
    if (UI.startStarter) return UI.startStarter;
    const st = UI.startStarter = S.starter({send: (op, args) => send(op, args)});
    st.subscribe(e => {
      const w = said.get(e.ticket);
      if (!w) return;
      if (e.state === 'queued') w.toast(w.name + ' waits in line for a free helper place.', 'ok');
      else if (e.state === 'failed' && w.again) {
        /* a failed start says what to do and offers the one button that does it (ORCH-1362, UX checklist E3/L4) */
        const t = String(e.text || 'Could not start the helper.').trim().replace(/([^.!?])$/, '$1.');
        const again = () => w.again(e.rest);
        again.label = 'Try again';
        w.toast(t, 'error', again);  // the button says what to do; the words say what went wrong
      } else if (e.state === 'failed' || e.state === 'slow') w.toast(e.text, 'error');
      if (!['starting', 'started'].includes(e.state)) said.delete(e.ticket);
    });
    return st;
  };

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
    let menuNow = null; /* the drawn caret menu: a redraw reads its open state, as its toggle event comes later */
    const toast = (text, kind, again) => (o.toast || (UI.toast ? (t, k, a) => UI.toast(t, a, k) : () => {}))(text, kind, again);

    const view = () => S.sessions(o.sessions, new Date(), UI.stamp ? (at, now) => UI.stamp(at.toISOString(), {now: now.toISOString()}) : null);
    const pickOf = () => {
      const t = S.tools(o.agents), was = picks.get(o.ticket) || {}, cur = S.model({model: o.model});
      const tool = t.tools.some(x => x.name === was.tool) ? was.tool : t.usual;
      return {tools: t, tool, model: was.model || cur.name, cur};
    };
    const unavailable = (how, row) => {
      const pick = pickOf(), tool = how === 'fresh' ? pick.tool : (row || S.last(view().rows))?.agent || pick.tools.usual;
      return o.unavailable?.[tool] || '';
    };
    const ctx = extra => {
      const p = S.places(o.runs, o.settings, o.line);
      return Object.assign({starting: starter.starting(o.ticket), running: !!o.running, inLine: !!S.inLine(p, o.ticket), tools: pickOf().tools, unavailable:unavailable(extra?.how, extra?.row)}, extra || {});
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
      if (what === 'tool') s.dataset.prefix = label; /* owner, ORCH-488: the tool picker says Tool on its face */
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
      if (p.tools.tools.length > 1) run.append(sel('Tool', p.tools.tools.map(x => [x.name, x.label]), p.tool, 'tool', () => render()));
      else if (tool) run.append(el('span', 'chip', 'Tool: ' + tool.label));
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
      /* while the list loads, Continue shows only when the page does not know the ticket never ran (o.hasSessions) */
      const v = view(), lastRow = S.last(v.rows), hasLast = !!lastRow || (v.state === 'loading' && o.hasSessions !== false), name = o.name || 'this ticket';
      const p = S.places(o.runs, o.settings, o.line), at = S.inLine(p, o.ticket);
      const box = el('div', 'live-start');
      if (starter.starting(o.ticket)) box.setAttribute('aria-busy', 'true');
      const waits = o.inline && o.why && (o.why.question || o.why.review) ? o.why : null;
      const head = el('div', 'start-pop-h');
      if (!waits) head.append(el('h3', 'live-start-h', 'Start a helper'));
      const pl = el('span', 'meta live-places', S.placesShort(p));
      if (p.full) pl.dataset.full = '';
      if (pl.textContent) head.append(pl);
      if (waits) box.append(whyBox(waits));
      if (head.children.length) box.append(head);
      if (at) {
        box.append(el('p', 'meta', name + ' is number ' + at.at + ' of ' + at.of + ' in line. It starts by itself when a place is free.'));
        /* ORCH-2295: a way out of the line, one click (the same path as `orch run stop`; nothing runs, so nothing is lost) */
        const lb = attr(el('button', 'btn outline sm', 'Take out of the line'), {type: 'button', 'aria-label': 'Take ' + name + ' out of the line'});
        lb.dataset.start = 'leave';
        lb.addEventListener('click', async () => {
          lb.disabled = true;
          const r = await sendNow('run.stop', {ticket: o.ticket}).catch(() => null);
          if (r && r.ok) { isOpen = false; toast(name + ' no longer waits in line.', 'ok'); }
          else { lb.disabled = false; toast((r && r.text) || 'Could not take ' + name + ' out of the line. Try again.', 'error'); }
        });
        box.append(lb);
        return box;
      }
      if (waits) { box.append(waitsActions(hasLast, name)); if (freshOpen) box.append(freshList(hasLast)); const e0 = earlier(v); if (e0) box.append(e0); return box; }
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
      list.append(opt('start-fresh', 'Fresh start', hasLast ? 'Starts over without the earlier talk' : 'Reads the ticket and starts on the first step', fb, S.why('fresh', ctx({how:'fresh'})), runRow()));
      box.append(list);
      const e = earlier(v);
      if (e) box.append(e);
      return box;
    }
    /* ORCH-2201 (owner, ORCH-2188 K a): why the ticket waits comes first: the open question with a field to answer it, or the
       review that waits with Open. Starting without that is the person's call, so Continue stays, and Fresh start is a small link. */
    let freshOpen = false;
    function whyBox(w) {
      const box = attr(el('section', 'live-why'), {'aria-label': 'Why it waits'});
      box.dataset.key = 'start-why';
      box.append(el('h4', 'live-why-h', 'Why it waits'));
      if (w.question) {
        const q = w.question, line = el('p', 'live-why-q');
        line.append(document.createTextNode('The helper asked: '), el('b', '', q.text));
        box.append(line);
        const send = async text => {
          const a = String(text || '').trim();
          if (!a || box.dataset.busy || !w.answer) return;
          box.dataset.busy = '1';
          const r = await w.answer(a);
          delete box.dataset.busy;
          if (r && r.ok) toast('Answered: ' + a, 'ok'); else toast((r && r.text) || 'Could not send your answer.', 'error');
        };
        if ((q.options || []).length) {
          const row = el('div', 'live-why-opts');
          q.options.forEach(op => { const b = attr(el('button', 'btn outline sm', op), {type: 'button'}); b.addEventListener('click', () => send(op)); row.append(b); });
          box.append(row);
        }
        const input = attr(el('input', 'input'), {type: 'text', placeholder: 'Your answer', 'aria-label': 'Your answer'});
        input.dataset.key = 'start-why-text';
        const go2 = attr(el('button', 'btn outline sm', 'Send'), {type: 'button'});
        go2.dataset.key = 'start-why-send';
        go2.addEventListener('click', () => send(input.value));
        input.addEventListener('keydown', e => { if (e.key === 'Enter') send(input.value); });
        const f = el('div', 'live-why-line');
        f.append(input, go2);
        box.append(f);
      } else {
        const row = el('div', 'live-why-line');
        row.append(el('p', 'live-why-q', w.review.text));
        const open = attr(el('a', 'btn outline sm', 'Open'), {href: w.href || '#', 'aria-label': 'Open the review of ' + (o.name || 'this ticket')});
        open.dataset.key = 'start-why-open';
        row.append(open);
        box.append(row);
      }
      return box;
    }
    function waitsActions(hasLast, name) {
      const row = el('div', 'live-why-act');
      const main = attr(el('button', 'btn primary', hasLast ? 'Continue' : 'Start'), {type: 'button', 'aria-label': (hasLast ? 'Continue the last conversation on ' : 'Start a helper on ') + name});
      main.dataset.start = hasLast ? 'continue' : 'fresh';
      main.addEventListener('click', () => { if (hasLast) go([['run.start', {ticket: o.ticket}]], 'continue'); else { const pk = pickOf(); go(S.freshOps(o.ticket, pk, pk.tools.usual, pk.cur), 'fresh'); } });
      const reason = hasLast ? S.why('continue', ctx()) : S.why('fresh', ctx({how: 'fresh'}));
      if (reason) { main.disabled = true; row.append(main, el('p', 'start-why', reason)); } else row.append(main);
      if (hasLast) {
        const fl = attr(el('button', 'btn ghost sm live-why-link', 'Fresh start…'), {type: 'button', 'aria-expanded': String(freshOpen)});
        fl.dataset.key = 'start-fresh-link';
        fl.addEventListener('click', () => { freshOpen = !freshOpen; render('[data-key="start-fresh-link"]'); });
        row.append(fl);
      }
      return row;
    }
    function freshList(hasLast) {
      const fb = attr(el('button', 'btn outline sm', 'Start again'), {type: 'button', 'aria-label': 'Fresh start on ' + (o.name || 'this ticket')});
      fb.dataset.start = 'fresh';
      fb.addEventListener('click', () => { const pk = pickOf(); go(S.freshOps(o.ticket, pk, pk.tools.usual, pk.cur), 'fresh'); });
      const list = el('ul', 'start-opts');
      list.append(opt('start-fresh', 'Fresh start', 'Starts over without the earlier talk', fb, S.why('fresh', ctx({how: 'fresh'})), runRow()));
      return list;
    }
    let more = false; /* the earlier sessions folded out (owner, ORCH-484: the newest one shows, the rest behind Show more) */
    function earlier(v) {
      if (v.state === 'empty' || (v.state === 'loading' && o.hasSessions === false)) return null; /* a ticket that never ran has none */
      const w = el('div', 'live-hist');
      w.dataset.key = 'start-earlier';
      const hid = me + '-earlier';
      const head = el('h4', 'live-hist-h', 'Earlier sessions');
      head.id = hid;
      w.append(head);
      if (v.state === 'loading') { w.append(el('p', 'meta', 'Loading the earlier sessions…')); return w; }
      if (v.state === 'error') { w.append(el('p', 'meta', 'The earlier sessions could not be loaded. Try again in a moment.')); return w; }
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
    /* rest: Try again after a failed start sends only the steps that did not go through, without o.before again */
    async function go(ops, how, rest) {
      if (starter.starting(o.ticket)) return;
      const session = ops.find(([op]) => op === 'session.reopen')?.[1]?.session;
      const reason = unavailable(how, view().rows.find(r => r.id === session));
      if (reason) { toast(reason, 'error'); return; }
      const first = rest ? [] : o.before ? await o.before(ops) : [];
      if (first === null) return;
      isOpen = false;
      said.set(o.ticket, {name: o.name || 'The ticket', toast, again: left => go(ops, how, left && left.length ? left : null)});
      starter.start(o.ticket, rest || [...(first || []), ...ops]).then(r => {
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
      if (o.inline) {
        const had = !!document.activeElement && wrap.contains(document.activeElement);
        wrap.replaceChildren(body());
        whyLine.hidden = true;
        if (had || focus) (wrap.querySelector(focus || '[data-start]:not([disabled])') || null)?.focus({preventScroll: true});
        return;
      }
      const v = view(), m = S.main(v, o), reason = S.why('main', ctx(o.fresh ? {how:'fresh'} : {}));
      const mb = attr(el('button', 'btn ' + o.style + ' sm'), {type: 'button'});
      mb.dataset.start = 'main';
      if (busyNow) {
        attr(mb, {disabled: true, 'aria-busy': 'true'});
        mb.append(attr(el('span', 'spinner'), {'aria-hidden': 'true'}), document.createTextNode('Starting…'));
      } else {
        mb.textContent = o.fresh ? o.label : m.label;
        if (reason) attr(mb, {disabled: true});
        mb.addEventListener('click', () => {
          if (!o.fresh) return go([['run.start', {ticket: o.ticket}]], m.what);
          const pk = pickOf();
          go(S.freshOps(o.ticket, pk, pk.tools.usual, pk.cur), 'fresh');
        });
      }
      const menu = menuNow = el('details', 'menu');
      if (isOpen && !busyNow) menu.open = true;
      const sum = attr(el('summary', 'btn ' + o.style + ' sm'), {'aria-label': 'Other ways to start'});
      sum.append(attr(el('span', 'chev'), {'aria-hidden': 'true'}));
      if (busyNow) {
        attr(sum, {'aria-disabled': 'true', tabindex: '-1'});
        sum.addEventListener('click', e => e.preventDefault());
      }
      menu.addEventListener('toggle', () => { isOpen = menu.open; });
      menu.append(sum);
      /* a panel of choices (tool picker, Start buttons), not a menu: its buttons stay buttons however the page draws it (ORCH-555) */
      const pop = attr(el('div', 'menu-pop start-pop'), {role: 'group', 'aria-label': 'Start choice'});
      if (isOpen && !busyNow) pop.append(body());
      menu.addEventListener('toggle', () => { if (menu.open && !pop.firstChild) pop.append(body()); });
      menu.append(pop);
      if (o.caretHidden) menu.hidden = true;
      if (o.mainEl) {
        if (busyNow) { o.mainEl.disabled = true; o.mainEl.setAttribute('aria-busy', 'true'); o.mainEl.dataset.startBusy = ''; }
        else if ('startBusy' in o.mainEl.dataset) { delete o.mainEl.dataset.startBusy; o.mainEl.removeAttribute('aria-busy'); o.mainEl.disabled = false; }
      }
      const kids = o.caretOnly ? [o.mainEl, menu].filter(Boolean) : [mb, menu];
      if (busyNow) kids.push(attr(el('span', 'sr-only', 'Starting the helper on ' + (o.name || 'the ticket') + '.'), {role: 'status'}));
      wrap.replaceChildren(...kids);
      /* the main button greyed (no tool, already in line): the reason as a visible line under it */
      const say = !busyNow && !o.running && !o.caretOnly ? reason : '';
      whyLine.textContent = say;
      whyLine.hidden = !say;
      whyLine.id = me + '-main-why';
      if (say) mb.setAttribute('aria-describedby', whyLine.id);
      else mb.removeAttribute('aria-describedby');
      if (focus) wrap.querySelector(focus)?.focus({preventScroll: true});
    }
    const off = starter.subscribe(e => {
      if (e.ticket !== o.ticket) return;
      if (wrap.isConnected === false) { off(); return; } /* the page painted a new button */
      const hadFocus = !!document.activeElement && wrap.contains(document.activeElement);
      render(hadFocus ? '[data-start="main"]' : null);
    });
    let lastSig = '';
    render();
    return {
      el: wrap,
      starting: () => starter.starting(o.ticket),
      update(changes) {
        Object.assign(o, changes || {});
        if (changes && changes.send) sendNow = changes.send;
        if (o.running) starter.seen(o.ticket, true);
        /* polling calls this often: draw again only when what the button shows changed, so an open picker stays open */
        const sig = JSON.stringify([o.unavailable, o.sessions, !!o.running, S.places(o.runs, o.settings, o.line), o.agents, o.model, o.hasSessions, o.label, o.continueLabel, o.style, !!o.caretHidden, !!o.fresh, o.why ? [o.why.question, o.why.review, o.why.href] : null, starter.starting(o.ticket)]);
        if (sig === lastSig) return;
        lastSig = sig;
        /* a click opens the menu now, its toggle event (isOpen) comes a moment later: a refresh in between kept it shut */
        if (menuNow && !o.inline) isOpen = !!menuNow.open;
        render();
      },
      open() { isOpen = true; render('summary'); },
      start(how) {
        if (how === 'fresh') { const pk = pickOf(); return go(S.freshOps(o.ticket, pk, pk.tools.usual, pk.cur), 'fresh'); }
        if (S.why('main', ctx())) return undefined;
        return go([['run.start', {ticket: o.ticket}]], S.main(view(), o).what);
      },
      close() { isOpen = false; render(); },
    };
  };
})();
