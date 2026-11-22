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

function mountDocs(main, r) {
  main.querySelectorAll('[data-docs-host]').forEach(host => {
    if (mounts.has(host) || !window.UI?.docs) return;
    const holder = {destroy() { if (holder.shown) holder.shown.destroy(); holder.gone = true; }};
    mounts.set(host, holder);
    const draw = data => {
      if (holder.gone) return;
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
