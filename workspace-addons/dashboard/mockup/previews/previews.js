(()=>{
'use strict';
const $=(s,r=document)=>r.querySelector(s),$$=(s,r=document)=>[...r.querySelectorAll(s)];
const params=new URLSearchParams(location.search),main=$('#content'),dialog=$('#file-viewer');
const files=window.previewFiles,samples=window.previewSamples,all=[...files,...samples];
const reduced=matchMedia('(prefers-reduced-motion: reduce)').matches;
const notice=text=>UI.toast(text);
function urlSet(key,value){const u=new URL(location.href);value?u.searchParams.set(key,value):u.searchParams.delete(key);try{history.replaceState(null,'',u)}catch{}}
function replay(el){el.classList.remove('state-change','page-enter','replay');void el.offsetWidth;el.classList.add(el===dialog?'replay':'state-change');}
async function copy(text){try{await navigator.clipboard.writeText(text);notice('Copied')}catch{notice('Copy unavailable here. Select and copy the address from your browser.')}}
let state=params.get('state')||main.dataset.defaultState||'loaded';
if(!['loaded','loading','empty','error'].includes(state))state='loaded';
function showState(){const scope=dialog||main;main.dataset.state=state;scope.setAttribute('aria-busy',String(state==='loading'));$$('[data-loaded]',scope).forEach(x=>{x.hidden=state==='empty'||state==='error'||(!!dialog&&state==='loading');x.inert=state==='loading';if(state==='loading')x.setAttribute('aria-hidden','true');else x.removeAttribute('aria-hidden');});$$('[data-empty]',scope).forEach(x=>x.hidden=state!=='empty');$$('[data-loading]',scope).forEach(x=>x.hidden=state!=='loading');$$('[data-error]',scope).forEach(x=>x.hidden=state!=='error');if(!dialog&&state==='loading'){main.setAttribute('aria-label','Loading ticket files');$('.review-verdict')?.setAttribute('inert','');}if(state==='empty'){$('#accept-result')?.setAttribute('disabled','');$('#ask-changes')?.setAttribute('disabled','');} }
// A saved file key routes ticket thumbnail links into a type-specific viewer.
if(main.dataset.viewerIndex){const requested=params.get('file')||params.get('name')||params.get('n')||params.get('type');let f=all.find(f=>f.name===requested||f.viewer===requested||f.kind.toLowerCase()===requested?.toLowerCase());if(!f&&requested)f=files.find(f=>requested.endsWith('.'+f.name.split('.').pop()));if(f){const u=new URL(f.url,location.href);for(const k of ['state','from'])if(params.has(k))u.searchParams.set(k,params.get(k));location.replace(u.href);}}
const collection=$('.files-collection');
if(collection&&!dialog){
 const search=$('#file-search'),filter=$('#type-filter');
 // Viewer backdrops keep their existing collection; only the two collection pages have these controls.
 const sort=$('#file-sort'),grouping=$('#file-grouping');
 if(sort && grouping){
 const originalGroups=$$('.file-group',collection),items=[];
 originalGroups.forEach(group=>$$('.file-tile',group).forEach(tile=>{
   const f=all.find(f=>new URL(tile.href).searchParams.get('file')===f.name);
   if(!f)return;
   const card=document.createElement('article');card.className='file-tile';card.dataset.name=(f.title+' '+f.step+' '+f.role).toLowerCase();card.dataset.category=f.category;
   const open=tile.cloneNode(true);open.className='file-preview-link';open.querySelector('.tile-time')?.remove();open.querySelector('.list-actor')?.remove();open.querySelector('.list-open')?.remove();
   if(f.viewer==='html'){open.querySelector('.tile-copy .meta').textContent='Website · 26.6 KB · 4 files';open.setAttribute('aria-label','Preview Catalogue web page · Website');}
   const context=document.createElement('div');context.className='file-context';
   const chip=document.createElement('span');chip.className='role-chip';chip.dataset.role=f.role;chip.textContent=f.role==='Evidence'?'Evidence for: '+f.step:f.role;
   const task=document.createElement('a');task.className='task-link';task.href=f.taskUrl;task.textContent='Task: '+f.step;
   const time=document.createElement('time');time.className='created-time meta';time.dateTime=f.createdAt;time.textContent='Created 13 Nov 2026 · 13:38';
   context.append(chip,task,time);card.append(open,context);items.push({card,f,index:items.length});
   open.addEventListener('click',()=>{try{sessionStorage.setItem('preview-return',location.href);sessionStorage.setItem('preview-scroll',String(scrollY));sessionStorage.setItem('preview-focus',open.getAttribute('href'));}catch{}});
 }));
 originalGroups.forEach(g=>g.remove());
 search.value=params.get('q')||'';filter.value=params.get('type')||'All';if(!filter.value)filter.value='All';
 sort.value=params.get('sort')||'important';if(!sort.value)sort.value='important';grouping.value=params.get('group')||'task';if(!grouping.value)grouping.value='task';
 let expanded=params.get('expanded')==='1',view=params.get('view')==='list'?'list':'grid';
 const ranks={Result:0,Evidence:1,Reference:2,Other:2};
 function compare(a,b){const dates=Date.parse(a.f.createdAt)-Date.parse(b.f.createdAt);return (sort.value==='important'?ranks[a.f.role]-ranks[b.f.role]:sort.value==='oldest'?dates:-dates)||a.index-b.index;}
 function render(animate=true){
   $$('.file-group,.ungrouped-files',collection).forEach(g=>g.remove());
   const q=search.value.trim().toLowerCase(),visible=items.filter(({card,f})=>card.dataset.name.includes(q)&&(filter.value==='All'||filter.value===f.category)).sort(compare);
   const groups=new Map();visible.forEach(item=>{const key=grouping.value==='task'?item.f.step:grouping.value==='role'?item.f.role:'All files';if(!groups.has(key))groups.set(key,[]);groups.get(key).push(item);});
   let hiddenCount=0;
   [...groups].forEach(([name,rows],index)=>{
     const flat=grouping.value==='none',g=document.createElement(flat?'section':'details');g.className=flat?'ungrouped-files':'file-group';
     if(!flat){g.open=expanded||view==='list'||!!q||filter.value!=='All'||index<2;const summary=document.createElement('summary');const title=document.createElement('strong');title.textContent=name;const count=document.createElement('span');count.className='meta group-count';count.textContent=rows.length+' '+(rows.length===1?'file':'files');summary.append(title,count);g.append(summary);}
     const grid=document.createElement('div');grid.className='file-grid';rows.forEach(({card},i)=>{card.hidden=false;card.classList.toggle('overflow-file',!expanded&&view==='grid'&&!q&&filter.value==='All'&&i>=5);grid.append(card);});
     const overflow=rows.filter(({card})=>card.classList.contains('overflow-file')).length;
     if(overflow){const more=document.createElement('button');more.className='more-tile';more.textContent='+'+overflow+' more files';more.onclick=()=>{expanded=true;urlSet('expanded','1');render();};grid.append(more);}
     if(!flat&&!g.open)hiddenCount+=rows.length;else hiddenCount+=overflow;
     g.append(grid);collection.append(g);
   });
   collection.dataset.viewMode=view;collection.classList.toggle('expanded',expanded);
   $$('[data-view]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.view===view)));
   $('#no-matches').hidden=visible.length>0||state==='empty';$('#expand-all').textContent=hiddenCount?'Show all files':'Collapse groups';
   $('#expand-all').hidden=grouping.value==='none'&&!hiddenCount;
   for(const [key,value] of Object.entries({q:search.value,type:filter.value==='All'?'':filter.value,sort:sort.value,group:grouping.value,view}))urlSet(key,value);
   if(animate)replay(collection);
 }
 search.oninput=()=>render();filter.onchange=()=>render();sort.onchange=()=>render();grouping.onchange=()=>render();
 $('#clear-filter').onclick=()=>{search.value='';filter.value='All';render();};
 $$('[data-view]').forEach(b=>b.onclick=()=>{view=b.dataset.view;render();});
 $('#expand-all').onclick=()=>{expanded=$('#expand-all').textContent==='Show all files';urlSet('expanded',expanded?'1':'');render();if(!expanded)$$('.file-group',collection).forEach(g=>g.open=false);};
 render(false);
 try{if(sessionStorage.getItem('preview-return')===location.href)requestAnimationFrame(()=>{const href=sessionStorage.getItem('preview-focus');$$('.file-preview-link',collection).find(a=>a.getAttribute('href')===href)?.focus({preventScroll:true});scrollTo(0,Number(sessionStorage.getItem('preview-scroll')||0));});}catch{}
 }
}

let selected;
if(dialog){
 selected=all.find(x=>x.name===params.get('file'))||files.find(x=>x.name===main.dataset.defaultFile);const list=selected.name.startsWith('sample-')?samples:files,index=list.indexOf(selected);
 // A direct wrong-type query is resolved to its correct renderer.
 if(!$('.file-variant[data-file="'+CSS.escape(selected.name)+'"]',dialog)){location.replace(selected.url);return;}
 $$('.file-variant',dialog).forEach(v=>v.hidden=v.dataset.file!==selected.name);
 $('#viewer-title').textContent=selected.title;$('#viewer-meta').textContent=`${selected.kind} · ${selected.size} · Created 13 Nov 2026, 13:38 · Task: ${selected.step} · ${selected.role}`;$('#viewer-position').textContent=`${index+1} of ${list.length} files`;
 $('#open-original').href=$('#download-file').href='assets/'+selected.name;
 if(selected.viewer==='html'){
   $('#open-original').href='assets/site/index.html';
   $('#download-file').href='assets/site.zip';$('#download-file').textContent='Download website';
   $('#viewer-meta').textContent='Website · 26.6 KB · Created 13 Nov 2026, 13:38 · Task: Web page and PDF · '+selected.role;
   const frame=$('.page-frame',dialog);
   function device(size){frame.style.width=size==='tablet'?'768px':size==='phone'?'390px':'100%';$$('[data-device]',dialog).forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.device===size)));urlSet('device',size);}
   $$('[data-device]',dialog).forEach(b=>b.onclick=()=>device(b.dataset.device));
   device(['desktop','tablet','phone'].includes(params.get('device'))?params.get('device'):'desktop');
 }
 for(const [id,offset] of [['prev-file',-1],['next-file',1]]){const next=list[(index+offset+list.length)%list.length];const a=$('#'+id);a.href=next.url+(params.get('from')==='review'?'&from=review':'');a.title=next.title;}
 function closeViewer(){let dest=params.get('from')==='review'?'review-card.html':selected.name.startsWith('sample-')?'many.html':'files.html';try{const saved=sessionStorage.getItem('preview-return');if(saved&&!params.has('from')&&new URL(saved).pathname.startsWith(new URL('.',location.href).pathname))dest=saved;}catch{}location.href=dest;}
 $('#close-viewer').onclick=closeViewer;
 $('.shell').inert=true;
 document.documentElement.style.overflow='hidden';
 $('#close-viewer').focus();
 document.addEventListener('DOMContentLoaded',()=>{
   let expand=$('.ui-expand',dialog);if(!expand){expand=document.createElement('button');expand.className='btn outline sm ui-expand';expand.textContent='Full screen';dialog.prepend(expand)}
   $('.viewer-actions .row',dialog).append(expand);
   expand.onclick=()=>{
     UI.fullscreen(dialog,expand);
     const fullscreen=dialog.closest('dialog');
     fullscreen.classList.add('file-fullscreen');
     fullscreen.setAttribute('role','dialog');
     fullscreen.setAttribute('aria-label',selected.title+' — Full screen');
     expand.hidden=true;
     $('#close-viewer').hidden=true;
     fullscreen.addEventListener('close',()=>{
       expand.hidden=false;
       $('#close-viewer').hidden=false;
       expand.focus({preventScroll:true});
     },{once:true});
   };
 });
 document.addEventListener('keydown',e=>{
   if(e.key==='Escape'&&!dialog.closest('dialog')){e.preventDefault();closeViewer();}
 });
 $('[data-replay]',dialog).onclick=()=>replay(dialog);
 dialog.addEventListener('keydown',e=>{if(['INPUT','TEXTAREA','SELECT','AUDIO','VIDEO'].includes(e.target.tagName)||e.target.closest('[role=tablist]'))return;if(e.key==='ArrowLeft'||e.key==='ArrowRight'){e.preventDefault();location.href=$('#'+(e.key==='ArrowLeft'?'prev-file':'next-file')).href;}});
 $('[data-copy-link]').onclick=()=>copy(location.href);
 const active=$('.file-variant:not([hidden])',dialog);
 $('[data-copy-code]',active)?.addEventListener('click',()=>copy($$('.code-lines li',active).map(l=>l.textContent).join('\n')));
 $('#source-toggle',active)?.addEventListener('click',e=>{const source=$('#markdown-source',active),rendered=$('#rendered-note',active);source.hidden=!source.hidden;rendered.hidden=!source.hidden;e.target.textContent=source.hidden?'View source':'Rendered view';e.target.setAttribute('aria-pressed',String(!source.hidden));replay(active);});
 const text=$('[data-ui="text-content"]',active),search=$('[data-ui="text-search"]',active);if(text){const original=text.textContent;search.oninput=()=>{const query=search.value; text.replaceChildren();let start=0,count=0;if(query){const lower=original.toLowerCase(),q=query.toLowerCase();let i;while((i=lower.indexOf(q,start))>=0){text.append(document.createTextNode(original.slice(start,i)));const mark=document.createElement('mark');mark.textContent=original.slice(i,i+query.length);text.append(mark);start=i+query.length;count++;}}text.append(document.createTextNode(original.slice(start)));$('[data-ui="search-status"]',active).textContent=query?`${count} matches`:'Text file';$('mark',text)?.scrollIntoView({block:'nearest'});};$('[data-ui="wrap-toggle"]',active).onclick=e=>{text.classList.toggle('no-wrap');const wrap=!text.classList.contains('no-wrap');e.target.textContent=wrap?'Wrap on':'Wrap off';e.target.setAttribute('aria-pressed',String(wrap));};}
 $('[data-ui="image-zoom"]',active)?.addEventListener('click',e=>{const stage=$('.image-stage',active);stage.classList.toggle('zoomed');e.target.textContent=stage.classList.contains('zoomed')?'Fit to window':'View at full size';$('[data-ui="image-dimensions"]',active).textContent=stage.classList.contains('zoomed')?'Original size':'Fit to window';});
 const table=$('.data-table',active);if(table){const tbody=$('tbody',table);$('[data-table-search]',active)?.addEventListener('input',e=>{$$('tr',tbody).forEach(r=>r.hidden=!r.textContent.toLowerCase().includes(e.target.value.toLowerCase()));});$$('[data-sort]',table).forEach(b=>b.onclick=()=>{const col=Number(b.dataset.sort),ascending=b.dataset.order!=='asc';$$('th',table).forEach(th=>th.removeAttribute('aria-sort'));b.closest('th').setAttribute('aria-sort',ascending?'ascending':'descending');b.dataset.order=ascending?'asc':'desc';$$('tr',tbody).sort((a,c)=>a.cells[col].textContent.localeCompare(c.cells[col].textContent,undefined,{numeric:true})*(ascending?1:-1)).forEach(r=>tbody.append(r));});}
 // Navigation between variants in the same image set keeps review origin.
 if(params.get('from')==='review')$$('.image-strip a',active).forEach(a=>a.href+='&from=review');
}
const reviewExpand=$('.review-result .card-h a');
if(reviewExpand)reviewExpand.addEventListener('click',e=>{
 e.preventDefault();
 UI.fullscreen($('.review-result'),reviewExpand);
 const full=$('.review-result').closest('dialog');
 full.classList.add('file-fullscreen');
 full.setAttribute('role','dialog');
 full.setAttribute('aria-label','Spring catalogue — Full screen');
});
$('#accept-result')?.addEventListener('click',e=>{const accepted=e.target.dataset.accepted==='true';e.target.dataset.accepted=String(!accepted);e.target.textContent=accepted?'Looks good':'Undo acceptance';$('#verdict-status').textContent=accepted?'Returned to review.':'Accepted in this preview.';replay($('.review-verdict'));});
$('#ask-changes')?.addEventListener('click',()=>{$('#change-form').hidden=!$('#change-form').hidden;if(!$('#change-form').hidden)$('textarea',$('#change-form')).focus();});
$('#change-form')?.addEventListener('submit',e=>{e.preventDefault();$('#verdict-status').textContent='Changes requested in this preview.';e.target.hidden=true;});
showState();
})();
