/* Draft A "Home of tiles" (ORCH-605): click-through only, nothing is saved or sent. */
(() => {
  const $$ = (s, r) => [...(r || document).querySelectorAll(s)];
  const say = (text, undo) => {
    const a = document.getElementById('announcement');
    if (a) a.textContent = text;
    if (window.UI && UI.toast) UI.toast(text, undo);
  };

  // phone: the menu button opens the side menu
  $$('[data-menu]').forEach(b => b.addEventListener('click', () => {
    const side = b.closest('.sidebar');
    const open = side.dataset.open !== 'true';
    side.dataset.open = String(open);
    b.setAttribute('aria-expanded', String(open));
  }));

  // buttons that only tell what would happen
  $$('[data-say]').forEach(b => b.addEventListener('click', ev => {
    if (b.tagName === 'A') ev.preventDefault();
    say(b.dataset.say);
  }));
  $$('[data-rule]').forEach(i => i.addEventListener('change', () => say('Rule saved')));
  $$('[data-sub-switch]').forEach(i => i.addEventListener('change', () => {
    const name = i.dataset.subSwitch;
    const label = i.closest('label').querySelector('.switch-text');
    if (label) label.textContent = i.checked ? 'On' : 'Off';
    say(name + (i.checked ? ' turned on' : ' turned off. Helpers can no longer use it.'), () => {
      i.checked = !i.checked;
      if (label) label.textContent = i.checked ? 'On' : 'Off';
    });
  }));

  // sources: a switch opens or closes one source to helpers
  $$('[data-src-switch]').forEach(i => i.addEventListener('change', () => {
    const row = i.closest('.p-src');
    const use = row.querySelector('[data-src-use]');
    const label = row.querySelector('.switch-text');
    const paint = () => {
      use.textContent = i.checked ? use.dataset.onText : 'Nothing';
      label.textContent = i.checked ? 'On' : 'Off';
    };
    paint();
    say(i.checked ? 'Helpers can now use this source, by the rules below' : 'Closed to helpers', () => { i.checked = !i.checked; paint(); });
  }));

  // use in a ticket: pick an open ticket or a new one, then the ticket side shows it attached
  const dlg = document.getElementById('use-dialog');
  if (dlg) {
    let from = null;
    $$('[data-use]').forEach(b => b.addEventListener('click', () => {
      from = b;
      dlg.querySelector('[data-use-what]').textContent = b.dataset.kind + ': ' + b.dataset.name;
      dlg.querySelector('[data-use-allow]').textContent = b.dataset.allow;
      dlg.showModal();
    }));
    dlg.querySelector('[data-use-cancel]').addEventListener('click', () => dlg.close());
    dlg.querySelector('[data-use-ok]').addEventListener('click', () => {
      const [key, title] = dlg.querySelector('input[name=use-ticket]:checked').value.split('|');
      dlg.close();
      const panel = from && from.closest('[data-panel]');
      const box = panel && panel.querySelector('[data-used]');
      if (!box) { say('Attached to ' + key + ' ' + title); return; }
      const none = box.querySelector('[data-none]');
      if (none) none.hidden = true;
      const row = document.createElement('div');
      row.className = 'list-row';
      const chip = document.createElement('a');
      chip.className = 'chip success';
      chip.href = '../../board/board.html';
      chip.textContent = key;
      const mid = document.createElement('span');
      mid.className = 'grow';
      const t = document.createElement('strong');
      t.textContent = title;
      const sub = document.createElement('span');
      sub.className = 'meta p-sub';
      sub.textContent = 'Attached from Personal just now: ' + from.dataset.kind.toLowerCase() + ' “' + from.dataset.name + '”';
      mid.append(t, sub);
      row.append(chip, mid);
      box.append(row);
      say('Attached to ' + key + ' ' + title, () => { row.hidden = true; });
    });
  }

  // meetings: next steps become tickets
  $$('[data-make]').forEach(b => {
    const list = document.querySelector('[data-steps="' + b.dataset.make + '"]');
    const boxes = () => $$('input[type=checkbox]', list);
    const count = () => boxes().filter(x => x.checked).length;
    const label = () => {
      const n = count();
      b.textContent = n === 1 ? 'Make 1 ticket' : 'Make ' + n + ' tickets';
      b.disabled = n === 0;
    };
    boxes().forEach(x => x.addEventListener('change', label));
    b.addEventListener('click', () => {
      let key = 29;
      const n = count();
      boxes().forEach(x => {
        const row = x.closest('li');
        if (x.checked) {
          const chip = document.createElement('a');
          chip.className = 'chip success';
          chip.href = '../../board/board.html';
          chip.textContent = 'Ticket DT-' + key++;
          row.append(chip);
        }
        x.disabled = true;
      });
      b.disabled = true;
      b.textContent = n === 1 ? '1 ticket made' : n + ' tickets made';
      say(n === 1 ? '1 ticket made from this meeting' : n + ' tickets made from this meeting');
    });
  });

  // calendar: tick a calendar off to hide it
  $$('[data-cal-toggle]').forEach(i => i.addEventListener('change', () => {
    $$('[data-cal="' + i.dataset.calToggle + '"]').forEach(el => { el.hidden = !i.checked; });
  }));

  // list on the left, one open thing on the right; every open thing has its own address (#name)
  $$('[data-split]').forEach(split => {
    const panels = $$('[data-panel]', split);
    const links = $$('.split-list a[data-pick]', split);
    const show = (id, picked) => {
      const target = panels.find(p => p.id === id) || panels[0];
      panels.forEach(p => { p.hidden = p !== target; });
      links.forEach(a => {
        const cur = a.getAttribute('href') === '#' + target.id;
        if (cur) a.setAttribute('aria-current', 'true'); else a.removeAttribute('aria-current');
        a.closest('.list-row').classList.toggle('cur', cur);
      });
      if (picked) split.dataset.picked = target.id; else delete split.dataset.picked;
    };
    const route = () => {
      const id = decodeURIComponent(location.hash.slice(1));
      if (panels.some(p => p.id === id)) show(id, true);
      else if (!id || id === 'list') show(panels[0].id, false);
    };
    window.addEventListener('hashchange', route);
    route();
  });
})();
