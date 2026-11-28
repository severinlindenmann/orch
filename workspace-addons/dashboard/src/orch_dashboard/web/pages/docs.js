// The Documentation page (ORCH-735): the book icon next to Settings opens #docs; #docs/<page> is one page and
// #docs/g-<group> the overview at that group. The pages and this workspace's live facts come from GET /api/docs
// (docspage.py); the master's UI.docs (kit/docs.js, docs.css) draws them. Classic script: shares app.js's scope.
let docsData = null, docsAt = 0;
const DOCS_KEEP = 30000;  // ms the pages are kept between two moves inside the Documentation page

function docsTitle(at) {
  const p = docsData && Array.isArray(docsData.pages) ? docsData.pages.find(x => x.id === at) : null;
  return p ? String(p.title) : '';
}

function docsPage() {
  return fragment(h('div', {className:'docs-host', 'data-docs-host':'', 'data-key':'docs-host'}));
}

function docsLink(x) {
  return x ? '#docs/' + encodeURIComponent(x) : '#docs';
}

// O-22 (owner 28 Nov): in a page area under 900 px (beside the right panel, or a small window) the overview is a plain
// list of topics, one part under the other: Start here, then each group, every topic one full-width row with its name
// and "Related n". The map with its lines is for a wide page only. Drawn from the kit's short rows (UI.shortRow).
const DOCS_NARROW = 900, DOCS_START = 'new-ticket', DOCS_PARTS = ['orch', 'builtin', 'addon'];
const docsOverview = at => !at || /^g-/.test(at);
const docsNarrow = () => !!window.UI?.pageRoom?.under && !!window.UI?.shortRow && window.UI.pageRoom.under(DOCS_NARROW);
function docsList(data, at) {
  const pages = array(data?.pages), by = Object.fromEntries(pages.map(p => [p.id, p]));
  // topics that name each other, either way, counted once (the same pairs as the map's "Related")
  const near = id => new Set(pages.flatMap(p => p.id === id ? array(p.related).filter(x => by[x] && x !== id) : array(p.related).includes(id) ? [p.id] : [])).size;
  const row = p => {
    const n = near(p.id), fact = [p.id === DOCS_START ? clean(p.one || '') : '', n ? 'Related ' + n : '', p.on === false ? 'Off' : ''].filter(Boolean).join(' · ');
    return window.UI.shortRow({title:clean(p.title), href:docsLink(p.id), fact, dataKey:'docs-topic-' + p.id});
  };
  const part = (key, label, list) => list.length ? h('section', {className:'stack', id:'docs-part-' + key, 'data-key':'docs-part-' + key, 'aria-label':label},
    h('h2', {className:'blk-title'}, label), h('div', {className:'card cal-list', role:'list'}, list.map(p => { const r = row(p); r.setAttribute('role', 'listitem'); return r; }))) : null;
  const groups = array(data?.groups), label = id => clean(groups.find(g => g.id === id)?.label || id);
  const rest = groups.map(g => g.id).filter(id => !DOCS_PARTS.includes(id));
  return h('div', {className:'stack', 'data-key':'docs-list', 'data-at':at || ''},
    heading('Documentation', 'How orch works, in pictures. Pick a part.'),
    part('start', 'Start here', pages.filter(p => p.id === DOCS_START)),
    [...DOCS_PARTS, ...rest].map(id => part(id, label(id), pages.filter(p => p.group === id && p.id !== DOCS_START))));
}
// The overview is drawn again when the room crosses 900 px (one paint per crossing, from the pages already read).
let docsShownNarrow = null;
function docsRoomChanged() {
  if (route().kind !== 'docs' || !docsOverview(route().at || '') || docsShownNarrow === null || docsNarrow() === docsShownNarrow) return;
  const host = main.querySelector('[data-docs-host]');
  if (!host) return;
  mounts.get(host)?.destroy(); mounts.delete(host); host.replaceChildren();
  mountDocs(main, route());
}
if (typeof window !== 'undefined' && typeof window.addEventListener === 'function') {
  window.addEventListener('orch:page-room', docsRoomChanged);
  window.addEventListener('resize', docsRoomChanged);
}

function mountDocs(main, r) {
  main.querySelectorAll('[data-docs-host]').forEach(host => {
    if (mounts.has(host) || !window.UI?.docs) return;
    const holder = {destroy() { if (holder.shown) holder.shown.destroy(); holder.gone = true; }};
    mounts.set(host, holder);
    const draw = data => {
      if (holder.gone) return;
      docsShownNarrow = docsOverview(r.at || '') ? docsNarrow() : null;
      if (docsShownNarrow) {
        host.classList.remove('ui-docs');
        host.replaceChildren(docsList(data, r.at || ''));
        // #docs/g-<group>: the list opens at that part
        const part = r.at ? host.querySelector('#docs-part-' + CSS.escape(r.at.slice(2))) : null;
        if (part) part.scrollIntoView({block:'start'});
        return;
      }
      holder.shown = window.UI.docs(host, data, {at:r.at || '', link:docsLink, settings:'#settings/addons'});
      // the crumb names the page once its title is known (after this paint, never inside it)
      if (r.at) setTimeout(() => { if (!holder.gone && typeof render === 'function') render(); }, 0);
    };
    if (docsData && Date.now() - docsAt < DOCS_KEEP) { draw(docsData); return; }
    if (window.UI?.state) host.replaceChildren(window.UI.state({kind:'loading'}));
    fetch('/api/docs', {credentials:'same-origin'}).then(res => {
      if (!res.ok) throw new Error(String(res.status));
      return res.json();
    }).then(data => { docsData = data; docsAt = Date.now(); draw(data); }).catch(() => {
      if (holder.gone) return;
      const again = () => { mounts.delete(host); host.replaceChildren(); mountDocs(main, r); };
      host.replaceChildren(window.UI?.state ? window.UI.state({kind:'error', title:'The documentation did not load', text:'The dashboard could not read it just now.', action:{label:'Try again', onClick:again}})
        : h('p', {className:'meta'}, 'The documentation did not load. Reload the page to try again.'));
    });
  });
}
