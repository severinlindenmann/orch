// "Where work is happening" on the start screen: accepted areas and who works in them. Agents only suggest areas; a person accepts them here.
(function () {
  'use strict';
  const S = window.FocusStore;
  const {h, P, toast} = S;
  const text = value => String(value ?? '').replace(/\bVPN\b/gi, 'network').replace(/\bMCP\b/gi, 'connection').replace(/\bt_[a-z0-9]{6,16}\b/g, '');
  const STATE = {suggested: 'Suggested', accepted: 'Accepted'};

  function mount(box) {
    if (!box || box.querySelector('.fx-areas')) return;
    const section = h('section', {class: 'fx-areas', hidden: true, 'aria-label': 'Where work is happening'});
    box.insertBefore(section, box.querySelector('.fx-pick-group, .fx-procs'));
    let last = '', loading = false, sending = 0, generation = 0, areas = [], dialog = null, list = null;

    async function load() {
      if (document.hidden || loading || sending || !box.isConnected) return;
      loading = true;
      const version = generation;
      try {
        const response = await fetch(P + '/api/areas');
        if (!response.ok) return;
        const data = await response.json(), json = JSON.stringify(data);
        if (version !== generation || sending || document.hidden || !box.isConnected || json === last) return;
        areas = data.areas || [];
        paint();
        last = json;
      } catch (e) { /* Keep the last snapshot until the next poll. */ }
      finally {
        loading = false;
        if (version !== generation && !sending) load();
      }
    }

    function tile(area) {
      const who = (area.who || []).map(text).filter(Boolean);
      const people = h('div', {class: 'fx-area-who'});
      if (who.length) people.append(...who.map(name => h('span', {class: 'fx-area-av', title: name, 'aria-label': name, role: 'img', text: name.charAt(0).toUpperCase()})));
      else if (area.quiet) people.append(h('span', {class: 'chip', text: 'quiet'}));
      return h('div', {class: 'fx-area' + (who.length ? ' busy' : '')},
        h('strong', {class: 'fx-area-name', text: text(area.name)}),
        h('span', {class: 'fx-area-path', text: text(area.path)}),
        people);
    }

    function paint() {
      const accepted = areas.filter(a => a.state === 'accepted'), suggested = areas.filter(a => a.state === 'suggested');
      section.hidden = !accepted.length && !suggested.length;
      if (accepted.length) {
        section.replaceChildren(
          h('div', {class: 'row fx-areas-h'},
            h('h2', {class: 'grow', text: 'Where work is happening '},
              h('span', {class: 'meta', text: '(' + accepted.length + (suggested.length ? ', ' + suggested.length + ' suggested' : '') + ')'})),
            h('button', {type: 'button', class: 'btn ghost sm', 'aria-haspopup': 'dialog', text: 'Areas…', onclick: open})),
          h('div', {class: 'fx-areas-grid'}, accepted.map(tile)));
      } else if (suggested.length) {
        section.replaceChildren(h('div', {class: 'row fx-areas-note'},
          h('span', {class: 'grow meta', text: suggested.length + (suggested.length === 1 ? ' area suggested' : ' areas suggested')}),
          h('button', {type: 'button', class: 'btn ghost sm', 'aria-haspopup': 'dialog', text: 'Review', onclick: open})));
      } else section.replaceChildren();
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
      if (area.state === 'suggested') buttons.push(h('button', {type: 'button', class: 'btn primary sm', text: 'Accept', 'aria-label': 'Accept ' + text(area.name), onclick: () => send('area.accept', area, all())}));
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
        h('p', {class: 'meta', text: 'Agents suggest areas. You decide which ones count.'}),
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
