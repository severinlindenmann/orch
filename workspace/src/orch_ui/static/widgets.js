/* Master widgets (14 Nov): builders for the components that need script. Plain DOM, textContent only (never innerHTML for
   text from tickets or people). Every one has a gallery.html entry. Requires components.js (UI.toast) for the toast. */
(()=>{'use strict';const UI=window.UI=window.UI||{};
const NS='http://www.w3.org/2000/svg';
const el=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!=null)n.textContent=text;return n};
const svg=(cls,inner)=>{const s=document.createElementNS(NS,'svg');s.setAttribute('viewBox','0 0 24 24');s.setAttribute('aria-hidden','true');s.setAttribute('class',cls);s.innerHTML=inner;return s};
const ST={
 todo:'<circle cx="12" cy="12" r="8" fill="none" stroke="currentColor" stroke-width="2"/>',
 working:'<circle cx="12" cy="12" r="8" fill="none" stroke="currentColor" stroke-width="2" opacity=".3"/><path class="arc" d="M12 4a8 8 0 0 1 8 8" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
 needs:'<circle cx="12" cy="12" r="8" fill="currentColor"/><path d="M12 8v5" stroke="#101216" stroke-width="2" stroke-linecap="round"/><circle cx="12" cy="16" r="1.2" fill="#101216"/>',
 check:'<circle cx="12" cy="12" r="8" fill="none" stroke="currentColor" stroke-width="2"/><circle cx="12" cy="12" r="3" fill="currentColor"/>',
 done:'<circle cx="12" cy="12" r="8" fill="currentColor"/><path d="m8.5 12 2.5 2.5 4.5-5" fill="none" stroke="#101216" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>'};
/* Status icon: UI.statusIcon('needs') -> <svg class="st needs"> (todo | working | needs | check | done) */
UI.statusIcon=name=>svg('st '+(ST[name]?name:'todo'),ST[name]||ST.todo);
UI.chevron=()=>{const s=el('span','chev');s.setAttribute('aria-hidden','true');return s};
/* Empty / error / loading state: UI.state({kind:'empty'|'error'|'loading', title, text, action:{label, onClick}}) */
UI.state=o=>{o=o||{};const kind=o.kind||'empty';
 if(kind==='loading'){const b=el('div','card pad-card');b.setAttribute('aria-busy','true');['title','line','line short'].forEach(c=>b.append(el('span','skeleton '+c)));return b}
 const b=el('div','empty-state'+(kind==='error'?' err':''));if(kind==='error')b.setAttribute('role','alert');
 const ico=el('span','ico');ico.append(kind==='error'?el('span','dot-err'):UI.statusIcon('todo'));b.append(ico);
 if(o.title)b.append(el('strong','',o.title));if(o.text)b.append(el('p','',o.text));
 if(o.action){const a=el('button','btn '+(kind==='error'?'primary':'outline')+' sm',o.action.label);a.type='button';if(o.action.onClick)a.onclick=o.action.onClick;b.append(a)}
 return b};
/* Stat tile: UI.stat('Done this week', '12', {delta:'+3 vs last week', dir:'up'}) */
UI.stat=(label,value,o)=>{o=o||{};const t=el('div','stat-tile');t.append(el('span','stat-label',label),el('span','stat-value',String(value)));if(o.delta)t.append(el('span','stat-delta'+(o.dir?' '+o.dir:''),o.delta));return t};
/* Progress with a label: UI.progress(3, 5, 'steps') */
UI.progress=(value,max,unit)=>{const w=el('div','progress-labeled'),bar=el('div','progress');bar.setAttribute('role','progressbar');bar.setAttribute('aria-valuemin','0');bar.setAttribute('aria-valuemax',String(max));bar.setAttribute('aria-valuenow',String(value));const f=el('span');f.style.width=Math.max(0,Math.min(100,max?value/max*100:0))+'%';bar.append(f);const t=el('div','progress-text');t.append(el('span','',value+' of '+max+(unit?' '+unit:'')));w.append(bar,t);return w};
/* Sheet: UI.sheet('Title', node) opens the side sheet (native dialog, same lifecycle as every dialog); returns the dialog */
UI.sheet=(title,content)=>{const d=el('dialog','sheet');d.setAttribute('aria-label',title);const h=el('div','sheet-h');h.append(el('h2','',title));const x=el('button','btn ghost icon sm');x.type='button';x.setAttribute('aria-label','Close');x.textContent='×';x.onclick=()=>d.close();h.append(x);d.append(h,content);d.addEventListener('close',()=>d.remove(),{once:true});document.body.append(d);d.showModal();return d};
/* Table: UI.table([{key,label,sort:true}], rows, {empty}) sortable by click or Enter on a header; text goes through textContent */
UI.table=(cols,rows,o)=>{o=o||{};const wrap=el('div','table-wrap'),table=el('table'),thead=el('thead'),tr=el('tr'),tbody=el('tbody');let sortKey=null,dir=1;
 const draw=()=>{tbody.replaceChildren();const list=rows.slice();if(sortKey)list.sort((a,b)=>String(a[sortKey]).localeCompare(String(b[sortKey]),undefined,{numeric:true})*dir);
  if(!list.length){const r=el('tr'),c=el('td','',o.empty||'Nothing here yet.');c.colSpan=cols.length;r.append(c);tbody.append(r)}
  list.forEach(row=>{const r=el('tr');cols.forEach(c=>r.append(el('td','',row[c.key]==null?'':String(row[c.key]))));tbody.append(r)});
  [...tr.children].forEach((th,i)=>{if(cols[i].sort)th.setAttribute('aria-sort',cols[i].key===sortKey?(dir>0?'ascending':'descending'):'none')})};
 cols.forEach(c=>{const th=el('th','',c.label);th.scope='col';if(c.sort){th.setAttribute('aria-sort','none');th.tabIndex=0;th.append(UI.chevron());const go=()=>{dir=sortKey===c.key?-dir:1;sortKey=c.key;draw()};th.onclick=go;th.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();go()}}}tr.append(th)});
 thead.append(tr);table.append(thead,tbody);wrap.append(table);draw();return wrap};
})();
