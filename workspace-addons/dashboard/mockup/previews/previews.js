(()=>{
'use strict';
const $=(s,r=document)=>r.querySelector(s),$$=(s,r=document)=>[...r.querySelectorAll(s)];
const params=new URLSearchParams(location.search),main=$('#content'),dialog=$('#file-viewer');
const files=window.previewFiles,samples=window.previewSamples,all=[...files,...samples];
const reduced=matchMedia('(prefers-reduced-motion: reduce)').matches;
const notice=(text)=>{const n=dialog?$('#viewer-message'):$('#notice');n.textContent=text;n.hidden=false;};
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
 const search=$('#file-search'),filter=$('#type-filter');search.value=params.get('q')||'';filter.value=params.get('type')||'All';if(!filter.value)filter.value='All';
 function setView(mode){collection.dataset.viewMode=mode;$$('[data-view]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.view===mode)));if(mode==='list')$$('.file-group').forEach(d=>d.open=true);urlSet('view',mode);replay(collection);}
 $$('[data-view]').forEach(b=>b.onclick=()=>setView(b.dataset.view));
 function filterFiles(){let count=0;const q=search.value.toLowerCase();$$('.file-tile',collection).forEach(t=>{t.hidden=!(t.dataset.name.includes(q)&&(filter.value==='All'||filter.value===t.dataset.category));if(!t.hidden)count++;});$$('.file-group',collection).forEach(g=>{g.hidden=!$$('.file-tile',g).some(t=>!t.hidden);if(q||filter.value!=='All')g.open=true;});$('#no-matches').hidden=count>0||state==='empty';if(q||filter.value!=='All')collection.classList.add('expanded');urlSet('q',search.value);urlSet('type',filter.value==='All'?'':filter.value);replay(collection);}
 search.oninput=filterFiles;filter.onchange=filterFiles;$('#clear-filter').onclick=()=>{search.value='';filter.value='All';filterFiles();};
 $('#expand-all').onclick=e=>{const expanded=e.target.textContent==='Collapse groups';$$('.file-group',collection).forEach(d=>d.open=!expanded);collection.classList.toggle('expanded',!expanded);e.target.textContent=expanded?'Show all files':'Collapse groups';urlSet('expanded',expanded?'':'1');replay(collection);};
 $('#show-more')?.addEventListener('click',()=>{collection.classList.add('expanded');urlSet('expanded','1');replay(collection);$('.overflow-file',collection)?.focus();});
 if(params.get('expanded')){collection.classList.add('expanded');$$('.file-group',collection).forEach(d=>d.open=true);$('#expand-all').textContent='Collapse groups';}
 function updateMoreCount(){const remaining=$$('.file-tile',collection).filter(t=>!t.hidden&&(!t.closest('details').open||(t.classList.contains('overflow-file')&&!collection.classList.contains('expanded')))).length;$('#expand-all').textContent=remaining?'+'+remaining+' more files':'Collapse groups';}
 $$('.file-group',collection).forEach(g=>g.addEventListener('toggle',updateMoreCount));
 $('#show-more')?.addEventListener('click',updateMoreCount);
 if(params.get('view')==='list')setView('list');if(search.value||filter.value!=='All')filterFiles();
 $$('.file-tile',collection).forEach(t=>t.addEventListener('click',()=>{try{sessionStorage.setItem('preview-return',location.href);sessionStorage.setItem('preview-scroll',String(scrollY));sessionStorage.setItem('preview-focus',t.getAttribute('href'));}catch{}}));
 try{if(sessionStorage.getItem('preview-return')===location.href){requestAnimationFrame(()=>{const href=sessionStorage.getItem('preview-focus');$$('.file-tile').find(t=>t.getAttribute('href')===href)?.focus({preventScroll:true});scrollTo(0,Number(sessionStorage.getItem('preview-scroll')||0));});}}catch{}
}
let selected;
if(dialog){
 selected=all.find(x=>x.name===params.get('file'))||files.find(x=>x.name===main.dataset.defaultFile);const list=selected.name.startsWith('sample-')?samples:files,index=list.indexOf(selected);
 // A direct wrong-type query is resolved to its correct renderer.
 if(!$('.file-variant[data-file="'+CSS.escape(selected.name)+'"]',dialog)){location.replace(selected.url);return;}
 $$('.file-variant',dialog).forEach(v=>v.hidden=v.dataset.file!==selected.name);
 $('#viewer-title').textContent=selected.title;$('#viewer-meta').textContent=`${selected.kind} · ${selected.size} · Helper · today 13:38 · ${selected.step}`;$('#full-filename').textContent=selected.name;$('#viewer-position').textContent=`${index+1} of ${list.length} files`;
 $('#open-original').href=$('#download-file').href='assets/'+selected.name;
 for(const [id,offset] of [['prev-file',-1],['next-file',1]]){const next=list[(index+offset+list.length)%list.length];const a=$('#'+id);a.href=next.url+(params.get('from')==='review'?'&from=review':'');a.title=next.title;}
 function close(){dialog.classList.add('is-closing');setTimeout(()=>{dialog.close();let dest=params.get('from')==='review'?'review-card.html':selected.name.startsWith('sample-')?'many.html':'files.html';try{const saved=sessionStorage.getItem('preview-return');if(saved&&!params.has('from')&&new URL(saved).pathname.startsWith(new URL('.',location.href).pathname))dest=saved;}catch{}location.href=dest;},reduced?0:150);}
 $('#close-viewer').onclick=close;dialog.addEventListener('cancel',e=>{e.preventDefault();close();});dialog.showModal();
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
$('#accept-result')?.addEventListener('click',e=>{const accepted=e.target.dataset.accepted==='true';e.target.dataset.accepted=String(!accepted);e.target.textContent=accepted?'Looks good':'Undo acceptance';$('#verdict-status').textContent=accepted?'Returned to review.':'Accepted in this preview.';replay($('.review-verdict'));});
$('#ask-changes')?.addEventListener('click',()=>{$('#change-form').hidden=!$('#change-form').hidden;if(!$('#change-form').hidden)$('textarea',$('#change-form')).focus();});
$('#change-form')?.addEventListener('submit',e=>{e.preventDefault();$('#verdict-status').textContent='Changes requested in this preview.';e.target.hidden=true;});
showState();
})();
