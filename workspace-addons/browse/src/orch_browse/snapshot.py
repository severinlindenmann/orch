"""The page walk behind orch browse look: page text plus numbered elements (from the ORCH-1155 trial)."""

SNAPSHOT_JS = r"""
(gen) => {
  document.querySelectorAll('[data-orch-ref]').forEach(e => e.removeAttribute('data-orch-ref'));
  const out = []; let n = 0; let line = '';
  const flush = () => { const t = line.replace(/\s+/g, ' ').trim(); if (t && t !== '|') out.push(t); line = ''; };
  const vis = e => { try { return e.checkVisibility({checkOpacity: true, visibilityProperty: true}); } catch (_) { return true; } };
  const ROLES = ['button','link','checkbox','radio','tab','menuitem','option','switch','textbox','combobox'];
  const inter = e => {
    const t = e.tagName;
    if (t === 'A') return e.hasAttribute('href');
    if (['BUTTON','SELECT','TEXTAREA','SUMMARY'].includes(t)) return true;
    if (t === 'INPUT') return e.type !== 'hidden';
    const r = e.getAttribute('role'); if (r && ROLES.includes(r)) return true;
    return e.hasAttribute('onclick') || e.getAttribute('contenteditable') === 'true';
  };
  const clean = s => (s || '').replace(/\s+/g, ' ').trim().slice(0, 100);
  const label = e => {
    let s = e.getAttribute('aria-label') || '';
    if (!s && e.labels && e.labels.length) s = [...e.labels].map(l => l.innerText).join(' ');
    if (!s) s = e.getAttribute('placeholder') || '';
    if (!s && !['INPUT','SELECT','TEXTAREA'].includes(e.tagName)) s = e.innerText;
    if (!s) s = e.getAttribute('title') || e.getAttribute('name') || '';
    return clean(s);
  };
  const desc = e => {
    const t = e.tagName, L = JSON.stringify(label(e));
    if (t === 'A') return `link ${L} -> ${e.getAttribute('href')}` + (e.hasAttribute('download') ? ' (download)' : '');
    if (t === 'SUMMARY') return `toggle ${L} (${e.parentElement.open ? 'open' : 'closed'})`;
    if (t === 'SELECT') return `select ${L}: ` + [...e.options].map(o => (o.selected ? '*' : '') + clean(o.text) + (o.value !== o.text ? `=${o.value}` : '')).join(' | ');
    if (t === 'TEXTAREA') return `textbox ${L} = ${JSON.stringify(e.value)}`;
    if (t === 'INPUT') {
      const y = e.type;
      if (y === 'checkbox' || y === 'radio') return `${y} ${L} ${e.checked ? '[x]' : '[ ]'}`;
      if (y === 'submit' || y === 'button') return `button ${JSON.stringify(e.value || label(e))}`;
      if (y === 'file') return `file-upload ${L}` + (e.files.length ? ` (${e.files[0].name})` : '');
      if (y === 'password') return `password ${L}` + (e.value ? ' (filled)' : '');
      return `${y === 'text' ? 'textbox' : y} ${L} = ${JSON.stringify(e.value)}`;
    }
    if (t === 'BUTTON' || e.getAttribute('role') === 'button') return `button ${L}`;
    return `clickable ${L}`;
  };
  const BLOCK = new Set(['P','DIV','LI','TR','H1','H2','H3','H4','H5','H6','SECTION','ARTICLE','HEADER','FOOTER','FORM',
    'FIELDSET','TABLE','UL','OL','DL','DT','DD','BR','DETAILS','MAIN','NAV','BLOCKQUOTE','PRE','LABEL','LEGEND','CAPTION','HR']);
  const walk = (node, skipText) => {
    for (const c of node.childNodes) {
      if (c.nodeType === 3) { if (!skipText) line += c.textContent; continue; }
      if (c.nodeType !== 1) continue;
      const t = c.tagName;
      if (['SCRIPT','STYLE','NOSCRIPT','TEMPLATE','IMG','SVG'].includes(t)) continue;
      if (!vis(c)) continue;
      if (t === 'IFRAME') { flush(); out.push(`(frame ${JSON.stringify(c.title || '')} from ${c.src}: not shown)`); continue; }
      if (inter(c)) {
        flush(); n++; c.setAttribute('data-orch-ref', gen + '-' + n); out.push(`[${n}] ${desc(c)}`);
        if (['A','BUTTON','SELECT','TEXTAREA','INPUT','SUMMARY'].includes(t)) continue;
        walk(c, false); continue;
      }
      const blk = BLOCK.has(t); if (blk) flush();
      if (t === 'TD' || t === 'TH') line += ' | ';
      if (/^H[1-6]$/.test(t)) line += '#'.repeat(+t[1]) + ' ';
      walk(c, t === 'LABEL' && !!c.control);
      if (blk) flush();
    }
  };
  walk(document.body, false); flush();
  return {title: document.title, url: location.href, lines: out, n};
}
"""
