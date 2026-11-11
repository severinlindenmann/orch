// "Where work is happening" on the start screen: areas in the strip and who works in them. Areas are display labels only (they group work on this page; they never give an agent access to anything).
(function () {
  'use strict';
  const S = window.FocusStore;
  const {h, P, toast} = S;
  const text = value => String(value ?? '').replace(/\bVPN\b/gi, 'network').replace(/\bMCP\b/gi, 'connection').replace(/\bt_[a-z0-9]{6,16}\b/g, '');
  const STATE = {suggested: 'Suggested', accepted: 'In the strip'};

  function mount(box) {
    if (!box || box.querySelector('.fx-areas')) return;
    const section = h('section', {class: 'fx-areas', hidden: true, 'aria-label': 'Where work is happening'});
    box.insertBefore(section, box.querySelector('.fx-pick-group, .fx-procs'));
    let last = '', loading = false, sending = 0, generation = 0, areas = [], sameFile = [], dialog = null, list = null;

    async function load() {
      if (document.hidden || loading || sending || !box.isConnected) return;
      loading = true;
      const version = generation;
      try {
        const response = await fetch(P + '/api/areas');
        if (!response.ok) return;
        const data = await response.json();
        // a same-file line says "2 min ago": draw it again once a minute even when nothing else changed
        const json = JSON.stringify(data) + ((data.same_file || []).length ? '|' + Math.floor(Date.now() / 60000) : '');
        if (version !== generation || sending || document.hidden || !box.isConnected || json === last) return;
        areas = data.areas || [];
        sameFile = Array.isArray(data.same_file) ? data.same_file : [];
        paint();
        last = json;
      } catch (e) { /* Keep the last snapshot until the next poll. */ }
      finally {
        loading = false;
        if (version !== generation && !sending) load();
      }
    }

    function tile(area, clash) {
      const who = [...new Set([...(area.who || []), ...(clash ? clashAgents(clash) : [])].map(text).filter(Boolean))];
      const people = h('div', {class: 'fx-area-who'});
      if (who.length) people.append(...who.map(S.avatar));
      else if (area.quiet) people.append(h('span', {class: 'chip', text: 'quiet'}));
      return h('div', {class: 'fx-area' + (clash ? ' clash' : who.length ? ' busy' : '')},
        h('strong', {class: 'fx-area-name', text: text(area.name)}),
        h('span', {class: 'fx-area-path', text: text(area.path)}),
        people);
    }

    /* Same file, two tickets: one amber line (display only; the agents' own record said so). */
    const HOW = {read: 'read it', changed: 'changed it', touched: 'used it'};
    const NUMBER = ['', 'One', 'Two', 'Three', 'Four', 'Five'];
    const clashAgents = c => (c.tickets || []).map(t => t.agent);
    function clashLine(c) {
      const tickets = c.tickets || [];
      const who = tickets.map(t => text(t.key) + ' ' + (HOW[t.how] || 'used it') + (t.how === 'changed' && FH.ago(t.at) ? ' ' + FH.ago(t.at) : '')).join(', ');
      return h('p', {class: 'fx-clash', role: 'status'},
        h('span', {'aria-hidden': 'true', text: '⚠ '}),
        h('b', {text: (NUMBER[tickets.length] || tickets.length) + ' tickets have the same file open:'}), ' ',
        S.docName(text(c.path)), ' (' + who + ')');
    }
    const FH = window.FocusHelpers;
    const folder = p => String(p || '').replace(/\/+$/, '');
    const covers = (area, path) => { const a = folder(area.path); return !!a && (path === a || path.startsWith(a + '/')); };
    const titleName = path => FH.plainFileName(path).replace(/\b\w/g, c => c.toUpperCase());

    function paint() {
      const accepted = areas.filter(a => a.state === 'accepted'), suggested = areas.filter(a => a.state === 'suggested');
      const clashes = sameFile.filter(c => c && typeof c.path === 'string' && (c.tickets || []).length >= 2);
      const had = section.contains(document.activeElement) ? document.activeElement.className : '';
      section.hidden = !accepted.length && !clashes.length && !suggested.length;
      const button = h('button', {type: 'button', class: 'btn ghost sm fx-areas-btn', 'aria-haspopup': 'dialog', text: 'Areas…' + (suggested.length ? ' (' + suggested.length + ' new)' : ''), onclick: open});
      if (accepted.length || clashes.length) {
        const tiles = accepted.map(a => tile(a, clashes.find(c => folder(c.path) === folder(a.path))));
        for (const c of clashes) {
          if (accepted.some(a => covers(a, c.path))) continue;
          tiles.push(tile({name: titleName(c.path) || c.path, path: c.path}, c));
        }
        section.replaceChildren(
          h('div', {class: 'fx-areas-h'}, h('h2', {text: 'Where work is happening'}), button),
          ...clashes.slice(0, 3).map(clashLine),
          h('div', {class: 'fx-areas-grid'}, tiles));
      } else if (suggested.length) {
        section.replaceChildren(h('div', {class: 'row fx-areas-note'},
          h('span', {class: 'grow meta', text: suggested.length + (suggested.length === 1 ? ' area suggested' : ' areas suggested')}),
          h('button', {type: 'button', class: 'btn ghost sm fx-areas-btn', 'aria-haspopup': 'dialog', text: 'Review', onclick: open})));
      } else section.replaceChildren();
      if (had) { const again = section.querySelector('.fx-areas-btn'); if (again) again.focus(); }  // the button is drawn again; keep the keyboard on it
      paintList();
    }

    async function send(op, area, buttons) {
      if (sending) return;
      sending++; generation++;
      buttons.forEach(button => { button.disabled = true; });
      try {
        const r = await S.act(op, {area: area.id});
        if (!r.ok) toast(text(r.message), 'error');
      } catch (e) { toast('Could not reach Focus. Try again.', 'error'); }
      finally {
        sending--;
        buttons.forEach(button => { button.disabled = false; });
        load();
      }
    }

    function row(area) {
      const buttons = [];
      if (area.state === 'suggested') buttons.push(h('button', {type: 'button', class: 'btn primary sm', text: 'Add to strip', 'aria-label': 'Add to strip: ' + text(area.name), onclick: () => send('area.accept', area, all())}));
      buttons.push(h('button', {type: 'button', class: 'btn outline sm', text: 'Remove', 'aria-label': 'Remove ' + text(area.name), onclick: () => send('area.remove', area, all())}));
      return h('li', {class: 'fx-areas-row'},
        h('div', {class: 'grow'}, h('strong', {text: text(area.name)}), h('span', {class: 'fx-area-path', text: text(area.path)})),
        h('span', {class: 'chip' + (area.state === 'suggested' ? ' warning' : ''), text: STATE[area.state] || ''}),
        h('div', {class: 'fx-areas-acts'}, buttons));
    }
    const all = () => (list ? [...list.querySelectorAll('button')] : []);

    function paintList() {
      if (!dialog || !list) return;
      const had = dialog.contains(document.activeElement) && list.contains(document.activeElement);
      list.replaceChildren(...(areas.length ? areas.map(row) : [h('li', {class: 'meta', text: 'No areas yet.'})]));
      if (had || document.activeElement === document.body) focusFirst();
    }
    const focusFirst = () => { const b = dialog && dialog.querySelector('button:not([disabled])'); if (b) b.focus(); };

    function open() {
      if (dialog) return;
      list = h('ul', {class: 'fx-areas-list'});
      dialog = h('dialog', {class: 'dialog fx-areas-dialog', 'aria-labelledby': 'fx-areas-t'},
        h('h2', {id: 'fx-areas-t', text: 'Areas'}),
        h('p', {class: 'meta', text: 'Agents suggest areas. You choose which ones show in the strip. Areas only label and group work here; they change nothing about what an agent may do.'}),
        list,
        h('div', {class: 'actions'}, h('button', {type: 'button', class: 'btn ghost', text: 'Close', onclick: () => dialog.close()})));
      dialog.addEventListener('close', () => { dialog.remove(); dialog = null; list = null; });
      document.body.append(dialog);
      paintList();
      dialog.showModal();
      focusFirst();
    }

    const visible = () => { if (!document.hidden) load(); };
    const timer = setInterval(() => {
      if (!box.isConnected) {
        clearInterval(timer);
        document.removeEventListener('visibilitychange', visible);
        if (dialog) dialog.close();
        return;
      }
      load();
    }, 5000);
    document.addEventListener('visibilitychange', visible);
    load();
  }

  S.register('areas', {mount});
})();
