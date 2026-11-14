/* gallery.html page code: new widgets, then the component and motion demos moved from mockup/system/components.html and motion.html. */
{const q=s=>document.querySelector(s);document.querySelectorAll('[data-st]').forEach(n=>n.replaceWith(UI.statusIcon(n.dataset.st)));
const ws=q('#w-status');['todo','working','needs','check','done'].forEach(k=>{const s=document.createElement('span');s.className='row';s.append(UI.statusIcon(k),document.createTextNode(' '+k));ws.append(s)});
const st=q('#w-stat');st.append(UI.stat('Done this week','12',{delta:'+3 vs last week',dir:'up'}),UI.stat('Needs you','2'),UI.stat('Working now','4'));
q('#w-progress').append(UI.progress(3,5,'steps'),UI.progress(0,4,'steps'));
q('#w-table').append(UI.table([{key:'t',label:'Ticket',sort:true},{key:'o',label:'Owner',sort:true},{key:'s',label:'Status'}],[{t:'Newsletter logo',o:'Anna',s:'Working'},{t:'Customer survey',o:'Ben',s:'Done'},{t:'Opening hours',o:'Anna',s:'Needs you'}]));
q('#w-empty').append(UI.state({kind:'empty',title:'Nothing here yet',text:'Finished work shows up here.',action:{label:'Create a ticket'}}));
q('#w-error').append(UI.state({kind:'error',title:'Could not reach your storage',text:'Check the address or your connection.',action:{label:'Try again'}}));
q('#w-loading').append(UI.state({kind:'loading'}));
q('#w-sheet').onclick=()=>{const p=document.createElement('p');p.textContent='Side sheet over the current page. Escape closes it.';UI.sheet('Summary notes',p)};
q('#w-toast').onclick=()=>UI.toast('Answered: Newsletter logo',()=>UI.toast('Undone'));q('#w-toast-err').onclick=()=>UI.toast('Could not reach your storage',null,'error')}
{
// Reference-only state toggles; no application data or network requests.
let toastTimer;
function toast(message){UI.toast(message);}
document.querySelectorAll('[data-open]').forEach(b=>b.onclick=()=>document.getElementById(b.dataset.open).showModal());
document.querySelectorAll('[data-toast]').forEach(b=>b.onclick=()=>toast(b.dataset.toast));
document.querySelectorAll('[data-copy]').forEach(b=>b.onclick=async()=>{const url=new URL(b.dataset.copy,location.href).href;try{await navigator.clipboard.writeText(url);toast('File link copied');}catch{toast('Copy is unavailable here. Open the file and copy its address.');}});
document.querySelectorAll('[data-preview-state]').forEach(b=>b.onclick=()=>{const state=b.dataset.previewState;document.querySelectorAll('[data-preview-state]').forEach(x=>x.setAttribute('aria-pressed',String(x===b)));const preview=document.getElementById('state-preview');preview.setAttribute('aria-busy',String(state==='loading'));preview.querySelectorAll('[data-state]').forEach(x=>x.hidden=x.dataset.state!==state);document.getElementById('state-announcement').textContent={loaded:'Preview ready',loading:'Loading preview…',empty:'No files yet',error:'Preview unavailable'}[state];});
document.getElementById('type-filter').onchange=e=>document.querySelectorAll('#preview-gallery .preview').forEach(p=>p.hidden=e.target.value!=='all'&&!p.querySelector('.preview-caption .meta').textContent.startsWith(e.target.value+' ·'));
document.querySelector('[data-retry]').onclick=()=>{document.querySelector('[data-retry-status]').textContent='Demo: connection restored. Your work is up to date.';};
document.getElementById('sample-dialog').addEventListener('close',e=>{if(e.target.returnValue==='remove')toast('Demo draft removed');});
document.addEventListener('keydown',e=>{if(e.key==='Escape')document.querySelectorAll('details.dropdown[open],details.workspace[open]').forEach(d=>d.open=false);});
}
{
const reduce=matchMedia('(prefers-reduced-motion: reduce)'), $=id=>document.getElementById(id);let loadTimer, listTimer, toastTimer, toastExit;
function mode(){$('motion-mode').textContent=reduce.matches?'Reduced motion is on · all movement is disabled':'Motion is on · short transitions, no ambient movement';}mode();reduce.addEventListener('change',mode);
function replay(el,cls){el.classList.remove(cls);void el.offsetWidth;el.classList.add(cls);}
function announce(s){$('motion-announcement').textContent=s;}
function tab(name){document.querySelectorAll('[data-demo-tab]').forEach(t=>{const active=t.dataset.demoTab===name;t.setAttribute('aria-selected',active);t.tabIndex=active?0:-1;$('panel-'+t.dataset.demoTab).hidden=!active;});}
function showToast(){UI.toast('Summary accepted',()=>UI.toast('Summary returned to review'));}
const actions={page:()=>replay($('page-sample'),'page-enter'),load:()=>{clearTimeout(loadTimer);const el=$('load-sample');el.setAttribute('aria-busy','true');el.querySelector('[data-load=skeleton]').hidden=false;el.querySelector('[data-load=content]').hidden=true;announce('Loading summary');loadTimer=setTimeout(()=>{el.setAttribute('aria-busy','false');el.querySelector('[data-load=skeleton]').hidden=true;el.querySelector('[data-load=content]').hidden=false;announce('Summary loaded');},1200);},list:()=>{clearTimeout(listTimer);const row=$('changing-row');if(row.hidden){row.hidden=false;row.className='list-row row-new';$('list-label').textContent='Two steps shown';}else{row.className='list-row row-out';listTimer=setTimeout(()=>{row.hidden=true;$('list-label').textContent='One step shown. Replay to add the second.';},reduce.matches?0:100);}},tabs:()=>tab($('tab-overview').getAttribute('aria-selected')==='true'?'files':'overview'),dialog:()=>$('motion-dialog').showModal(),sheet:()=>$('motion-sheet').showModal(),toast:showToast,progress:()=>{const p=$('progress-sample'),n=p.getAttribute('aria-valuenow')==='2'?3:2;p.setAttribute('aria-valuenow',n);p.firstElementChild.style.setProperty('--value',n*25+'%');$('progress-label').textContent=n+' of 4 steps';announce(n+' of 4 steps completed');},press:()=>replay($('press-sample'),'press-demo'),status:()=>replay($('status-sample'),'status-change')};
document.querySelectorAll('[data-replay]').forEach(b=>b.onclick=()=>actions[b.dataset.replay]());
document.querySelectorAll('[data-open]').forEach(b=>b.onclick=()=>$(b.dataset.open).showModal());
document.querySelectorAll('[data-demo-tab]').forEach(t=>{t.onclick=()=>tab(t.dataset.demoTab);t.onkeydown=e=>{if(['ArrowRight','ArrowLeft','Home','End'].includes(e.key)){e.preventDefault();const name=e.key==='Home'?'overview':e.key==='End'?'files':t.dataset.demoTab==='overview'?'files':'overview';tab(name);$('tab-'+name).focus();}};});
document.querySelector('[data-copy]').onclick=async()=>{try{await navigator.clipboard.writeText(new URL('samples/sample-sign.svg',location.href).href);announce('File link copied');}catch{announce('Copy is unavailable here. Open the file and copy its address.');}};
}
document.getElementById('g-density')?.addEventListener('change',e=>{document.documentElement.dataset.density=e.target.value});
