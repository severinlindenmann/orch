// Mockup only (W-051, O-25, owner 28 Nov): the product's rows in a page area under 900 px, beside the right panel or in
// a small window. A compact table with buttons or a switch becomes the kit's short rows (the name, one quiet line, the
// buttons and the switch always in view); a row marked data-narrow-below puts its buttons on a line of their own.
// A phone-width window (up to 720 px) keeps the table's card form. Narrow the window, or open
// ?room=617 / ?room=785, to see it.
(function () {
  const asked = Number(new URLSearchParams(location.search).get('room')) || 0;
  const main = document.querySelector('main');
  if (asked && main) main.style.maxWidth = asked + 'px';
  const room = () => (main && main.clientWidth ? main.clientWidth : innerWidth);
  const narrow = () => innerWidth > 720 && (innerWidth < 900 || room() < 900);
  const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
  const copy = n => { const c = n.cloneNode(true); c.removeAttribute('id'); return c; };

  function shortRows(table) {
    const heads = [...table.querySelectorAll('thead th')].map(th => th.textContent.trim());
    const list = el('div', 'blk-short');
    list.hidden = true;
    for (const tr of table.querySelectorAll('tbody tr')) {
      const tds = [...tr.children], first = tds[0], row = el('div', 'short-row'), grow = el('span', 'grow');
      const link = first.querySelector('a'), title = link ? el('a', 'short-title', link.textContent) : el('span', 'short-title', first.firstChild ? first.firstChild.textContent : '');
      if (link) title.href = link.getAttribute('href');
      const facts = [];
      tds.forEach((td, i) => {
        if (!i || td.classList.contains('cell-actions') || td.classList.contains('cell-toggle')) return;
        const t = td.textContent.trim();
        if (t) facts.push(facts.length ? heads[i] + ': ' + t : t);
      });
      const sub = first.querySelector('.subline');
      if (sub) facts.push(sub.textContent.trim());
      grow.append(title, el('span', 'short-fact', facts.join(' · ')));
      const side = el('span', 'short-side');
      tr.querySelectorAll('.cell-actions .btn, .cell-toggle .switch').forEach(n => side.append(copy(n)));
      row.append(grow, side);
      list.append(row);
    }
    return list;
  }
  const tables = [...document.querySelectorAll('[data-view="loaded"] table.blk-table.compact')].filter(t => t.querySelector('.cell-actions, .cell-toggle'))
    .map(t => { const wrap = t.closest('.table-wrap') || t, list = shortRows(t); wrap.after(list); return [wrap, list]; });
  const below = [...document.querySelectorAll('[data-narrow-below]')].map(row => [row, row.querySelector('.grow'), row.querySelector('.actions')]);

  function paint() {
    const n = narrow();
    for (const [wrap, list] of tables) { wrap.hidden = n; list.hidden = !n; }
    for (const [row, grow, acts] of below) { if (!grow || !acts) continue; if (n) grow.append(acts); else row.append(acts); }
  }
  paint();
  addEventListener('resize', paint);
})();
