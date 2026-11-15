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
/* Swipe review deck (draft 15 Nov): UI.swipeDeck(host, items, {mode:'phone'|'desk', onDecide(item, verdict, note), start})
   verdict = 'ok' (right, Looks good) | 'no' (left, Don't do / Send back) | 'talk' (down, Comment: voice or text).
   Every swipe has a button and a key (→ ← ↓, Space opens the viewer, Z undoes). Overlays stay inside host. */
UI.swipeDeck=(host,items,o)=>{o=o||{};const mode=o.mode||'desk',ic=(n,z)=>{const t=document.createElement('template');t.innerHTML=window.icon?window.icon(n,z||20):'';return t.content};
 let idx=o.start||0;const done=[],pins={};let overlay=null;
 host.classList.add('swipe','swipe-'+mode);host.tabIndex=0;host.setAttribute('role','region');host.setAttribute('aria-label','Review, one item at a time');
 const top=el('div','swipe-top'),count=el('span'),bar=el('div','progress'),fill=el('span');bar.append(fill);
 const undoBtn=el('button','btn ghost sm');undoBtn.type='button';undoBtn.append(ic('undo',16),'Undo');undoBtn.onclick=()=>undo();
 top.append(count,bar,undoBtn);
 const stage=el('div','swipe-stage'),live=el('div','sr-only');live.setAttribute('aria-live','polite');
 const acts=el('div','swipe-actions');
 const mk=(cls,icon,label,key,fn)=>{const b=el('button','swipe-act '+cls);b.type='button';const r=el('span','ring');r.append(ic(icon,cls==='ok'?28:24));const l=el('span','',label);if(key){const k=el('kbd','',key);l.append(k)}b.append(r,l);b.onclick=fn;return b};
 const noBtn=mk('no','x',"Don't do",'←',()=>fly('no')),talkBtn=mk('talk','mic','Comment','↓',()=>fly('talk')),okBtn=mk('ok','check','Looks good','→',()=>fly('ok'));
 acts.append(noBtn,talkBtn,okBtn);host.replaceChildren(top,stage,acts,live);
 const noWord=it=>it.noLabel||(it.kind==='check'?'Send back':"Don't do");
 const buildPreview=(it,big)=>{const p=it.preview||{},f=document.createDocumentFragment();
  if(p.type==='img'){const i=el('img');i.src=p.src;i.alt=p.alt||it.title;i.draggable=false;f.append(i)}
  else if(p.type==='page'){const fr=el('iframe');fr.src=p.src;fr.title=it.title;fr.setAttribute('sandbox','');fr.tabIndex=-1;f.append(fr)}
  else if(p.type==='table'){const t=el('table','mini-table'),h=el('tr');(p.cols||[]).forEach(c=>h.append(el('th','',c)));const th=el('thead');th.append(h);const tb=el('tbody');(p.rows||[]).slice(0,big?50:7).forEach(r=>{const tr=el('tr');r.forEach(c=>tr.append(el('td','',c)));tb.append(tr)});t.append(th,tb);f.append(t)}
  else{const d=el('div','doc');if(p.heading)d.append(el('h4','',p.heading));(p.paras||[]).forEach(x=>d.append(el('p','',x)));if(p.steps){const ol=el('ol');p.steps.forEach(x=>ol.append(el('li','',x)));d.append(ol)}f.append(d)}
  return f};
 const card=(it,layer)=>{const c=el('article','swipe-card'+(layer?' '+layer:''));c.setAttribute('aria-label',it.title);
  const h=el('header','swipe-head'),m=el('div','swipe-meta'),k=el('span','swipe-kind');k.append(ic(it.icon||'file',14),it.kindLabel||it.kind);m.append(k);if(it.ticket)m.append(el('span','',it.ticket));if(it.when)m.append(el('span','',it.when));
  h.append(m,el('h3','',it.title));if(it.why)h.append(el('p','',it.why));
  const pv=el('div','swipe-preview');pv.append(buildPreview(it,false));
  const ex=el('button','btn icon sm swipe-expand');ex.type='button';ex.setAttribute('aria-label','Make bigger');ex.append(ic('expand',16));ex.onclick=e=>{e.stopPropagation();openViewer()};pv.append(ex);
  (pins[it.id]||[]).forEach((pn,i)=>pv.append(pinEl(pn,i)));
  const ft=el('footer','swipe-foot');
  if(it.signs){const s=el('span','swipe-signs');s.append(ic('shield',14),mode==='phone'?'Face ID when you approve':'Signs when you approve');ft.append(s)}
  ft.append(el('span','grow'));const pc=(pins[it.id]||[]).length;if(pc){const s=el('span','swipe-pins');s.append(ic('pin',14),pc+(pc===1?' comment':' comments'));ft.append(s)}
  if(it.open){const a=el('a','btn ghost sm');a.href=it.open;a.target='_blank';a.rel='noopener';a.append(ic('external',14),'Open');a.onpointerdown=e=>e.stopPropagation();ft.append(a)}
  ['right','left','down'].forEach(d=>{c.append(el('div','swipe-edge '+d));const st=el('div','swipe-stamp '+d,d==='right'?'Looks good':d==='left'?noWord(it):'Comment');c.append(st)});
  c.append(h,pv,ft);return c};
 const pinEl=(pn,i)=>{const p=el('span','swipe-pin');p.style.left=pn.x+'%';p.style.top=pn.y+'%';p.append(el('span','',String(i+1)));p.title=pn.text;return p};
 let cur=null;
 const render=()=>{stage.replaceChildren();cur=null;const n=items.length;count.textContent=Math.min(idx+1,n)+' of '+n;fill.style.width=(idx/n*100)+'%';undoBtn.disabled=!done.length;
  if(idx>=n){acts.hidden=true;stage.append(summary());return}acts.hidden=false;
  if(items[idx+2])stage.append(card(items[idx+2],'under2'));if(items[idx+1])stage.append(card(items[idx+1],'under'));
  cur=card(items[idx]);stage.append(cur);noBtn.querySelector('span:not(.ring)').firstChild.textContent=noWord(items[idx]);wire(cur)};
 const summary=()=>{const d=el('div','swipe-done');d.append(UI.statusIcon('done'));d.append(el('h3','',"All done. Nothing else waits on you."));
  const t=el('div','tally'),c=v=>done.filter(x=>x.verdict===v).length;[['ok','check','Looks good'],['no','x',"Don't do"],['talk','mic','Comment']].forEach(([v,i,l])=>{const s=el('span');s.append(ic(i,16),c(v)+' '+l);t.append(s)});
  d.append(t,el('p','',"The helper picks up each answer now. Undo works for 5 seconds."));return d};
 const show=(c,dx,dy)=>{const w=stage.clientWidth||1,hgt=stage.clientHeight||1;c.style.transform=`translate(${dx}px,${dy}px) rotate(${dx/w*14}deg)`;
  const dir=dirOf(dx,dy),amt=dir==='down'?dy/(hgt*.22):Math.abs(dx)/(w*.3);
  c.querySelectorAll('.swipe-stamp,.swipe-edge').forEach(s=>{s.style.opacity=s.classList.contains(dir)?Math.min(1,Math.max(0,amt)):0})};
 const dirOf=(dx,dy)=>dy>0&&dy>Math.abs(dx)*1.1?'down':dx>0?'right':'left';
 const wire=c=>{let sx=0,sy=0,t0=0,id=null,dx=0,dy=0;
  c.addEventListener('pointerdown',e=>{if(overlay||e.button>0)return;id=e.pointerId;sx=e.clientX;sy=e.clientY;t0=performance.now();dx=dy=0;c.setPointerCapture(id);c.classList.add('dragging')});
  c.addEventListener('pointermove',e=>{if(e.pointerId!==id)return;dx=e.clientX-sx;dy=Math.max(-40,e.clientY-sy);show(c,dx,dy)});
  const end=e=>{if(e.pointerId!==id)return;id=null;c.classList.remove('dragging');const dt=performance.now()-t0,dist=Math.hypot(dx,dy);
   if(dist<6&&dt<350){reset(c);if(e.target.closest('.swipe-preview'))openViewer();return}
   const w=stage.clientWidth,h=stage.clientHeight,dir=dirOf(dx,dy),v=dist/dt;
   const go=dir==='down'?(dy>h*.22||v>.6&&dy>40):(Math.abs(dx)>w*.3||v>.6&&Math.abs(dx)>40);
   if(!go)return reset(c);fly(dir==='right'?'ok':dir==='left'?'no':'talk',dx,dy)};
  c.addEventListener('pointerup',end);c.addEventListener('pointercancel',e=>{if(e.pointerId===id){id=null;c.classList.remove('dragging');reset(c)}})};
 const reset=c=>{c.style.transform='';c.querySelectorAll('.swipe-stamp,.swipe-edge').forEach(s=>s.style.opacity=0)};
 const fly=(verdict,dx,dy)=>{if(!cur||overlay)return;const c=cur,w=stage.clientWidth,h=stage.clientHeight;
  if(verdict==='talk'){show(c,dx||0,Math.max(dy||0,h*.18));return openComment()}
  const tx=(verdict==='ok'?1:-1)*w*1.4;show(c,dx||tx*.1,dy||0);requestAnimationFrame(()=>{c.classList.add('leaving');show(c,tx,(dy||0)+40)});
  setTimeout(()=>commit(verdict,null),200)};
 const commit=(verdict,note)=>{const it=items[idx];done.push({item:it,verdict,note,idx});idx++;
  const word=verdict==='ok'?'Looks good':verdict==='no'?noWord(it):'Comment sent';live.textContent=word+': '+it.title;
  if(o.onDecide)o.onDecide(it,verdict,note);render();if(UI.toast&&!o.quiet)UI.toast(word+': '+it.title,()=>undo())};
 const undo=()=>{const last=done.pop();if(!last)return;idx=last.idx;render();live.textContent='Back: '+last.item.title;host.focus()};
 const closeOverlay=()=>{if(overlay){overlay.remove();overlay=null;host.focus()}};
 /* Comment sheet: hold the mic to talk (or tap to start/stop), or type. Send = the card leaves downwards. */
 const openComment=()=>{const it=items[idx];if(!it)return null;const scr=el('div','swipe-scrim'),sh=el('div','swipe-sheet');sh.setAttribute('role','dialog');sh.setAttribute('aria-label','Comment on '+it.title);
  const ta=el('textarea');ta.placeholder='Or type what should change';ta.setAttribute('aria-label','Comment');
  const voice=el('div','swipe-voice'),mic=el('button','swipe-mic');mic.type='button';mic.append(ic('mic',18),el('span','','Hold to talk'));const wave=el('div','swipe-wave');for(let i=0;i<18;i++){const b=el('i');b.style.animationDelay=(i%6)*0.09+'s';wave.append(b)}
  voice.append(mic,wave);const clips=el('div');clips.style.display='grid';clips.style.gap='8px';let t0=0,timer=null,clip=0;
  const start=()=>{if(mic.classList.contains('rec'))return;mic.classList.add('rec');mic.lastChild.textContent='Recording… let go to stop';t0=Date.now()};
  const stop=()=>{if(!mic.classList.contains('rec'))return;mic.classList.remove('rec');mic.lastChild.textContent='Hold to talk';const secs=Math.max(1,Math.round((Date.now()-t0)/1000));clip++;
   const c=el('div','swipe-clip');c.append(ic('play',14),el('span','','0:'+String(secs).padStart(2,'0')),el('q','',o.transcript||'Make the button bigger and put it above the fold.'));clips.append(c);send.disabled=false};
  mic.addEventListener('pointerdown',e=>{e.preventDefault();start()});['pointerup','pointerleave','pointercancel'].forEach(t=>mic.addEventListener(t,stop));
  mic.addEventListener('keydown',e=>{if(e.key===' '||e.key==='Enter'){e.preventDefault();mic.classList.contains('rec')?stop():start()}});
  const foot=el('div','swipe-sheet-foot'),cancel=el('button','btn','Cancel'),send=el('button','btn primary','Send');cancel.type=send.type='button';send.disabled=true;
  ta.addEventListener('input',()=>send.disabled=!ta.value.trim()&&!clip);
  cancel.onclick=()=>{closeOverlay();reset(cur)};
  send.onclick=()=>{const note={text:ta.value.trim(),voiceClips:clip,pins:(pins[it.id]||[]).length};closeOverlay();const c=cur;c.classList.add('leaving');show(c,0,stage.clientHeight*1.2);setTimeout(()=>commit('talk',note),200)};
  foot.append(cancel,send);const ttl=el('h2','','Comment');const sub=el('p','meta',it.title);sub.style.margin='0';
  sh.append(el('div','grab'),ttl,sub,voice,clips,ta,foot);scr.append(sh);scr.addEventListener('pointerdown',e=>{if(e.target===scr)cancel.onclick()});
  overlay=scr;host.append(scr);if(!o.state)mic.focus();return {mic,start,stop,ta,send}};
 /* Viewer: bigger preview, zoom, open, and pins (tap a spot, say or type what to change there). */
 const openViewer=()=>{const it=items[idx];if(!it)return null;const v=el('div','swipe-viewer');v.setAttribute('role','dialog');v.setAttribute('aria-label',it.title);
  const barEl=el('div','swipe-viewer-bar'),close=el('button','btn ghost icon sm');close.type='button';close.setAttribute('aria-label','Close');close.append(ic('x',18));close.onclick=()=>{closeOverlay();render()};
  let z=1;const zo=el('button','btn icon sm'),zi=el('button','btn icon sm');zo.type=zi.type='button';zo.setAttribute('aria-label','Zoom out');zi.setAttribute('aria-label','Zoom in');zo.append(ic('minus',16));zi.append(ic('plus',16));
  const pinBtn=el('button','btn sm');pinBtn.type='button';pinBtn.setAttribute('aria-pressed','false');pinBtn.append(ic('pin',16),'Comment on a spot');
  barEl.append(close,el('strong','',it.title),zo,zi,pinBtn);
  if(it.open){const a=el('a','btn sm');a.href=it.open;a.target='_blank';a.rel='noopener';a.append(ic('external',16),'Open');barEl.append(a)}
  const body=el('div','swipe-viewer-body'),zm=el('div','swipe-zoomed');zm.append(buildPreview(it,true));body.append(zm);
  const setZ=n=>{z=Math.max(1,Math.min(4,n));zm.style.transform=`scale(${z})`;zm.style.width=`calc(${100/z}% - 32px)`};zo.onclick=()=>setZ(z-.5);zi.onclick=()=>setZ(z+.5);
  body.addEventListener('wheel',e=>{if(e.ctrlKey){e.preventDefault();setZ(z-e.deltaY*.01)}},{passive:false});
  const pts=new Map();let d0=0,z0=1;body.addEventListener('pointerdown',e=>{pts.set(e.pointerId,[e.clientX,e.clientY]);if(pts.size===2){const [a,b]=[...pts.values()];d0=Math.hypot(a[0]-b[0],a[1]-b[1]);z0=z}});
  body.addEventListener('pointermove',e=>{if(!pts.has(e.pointerId))return;pts.set(e.pointerId,[e.clientX,e.clientY]);if(pts.size===2&&d0){const [a,b]=[...pts.values()];setZ(z0*Math.hypot(a[0]-b[0],a[1]-b[1])/d0)}});
  ['pointerup','pointercancel'].forEach(t=>body.addEventListener(t,e=>{pts.delete(e.pointerId);if(pts.size<2)d0=0}));
  const foot=el('div','swipe-viewer-foot'),list=el('div');list.style.display='grid';list.style.gap='8px';
  const hint=el('div','row');const drawList=()=>{list.replaceChildren();(pins[it.id]||[]).forEach((pn,i)=>{const r=el('div','swipe-pin-note'),b=el('b','',String(i+1));r.append(b,el('span','',pn.text));list.append(r)});
   hint.replaceChildren(ic('pin',14),el('span','',(pins[it.id]||[]).length?'Your comments go with your answer. Close, then swipe.':'Tap “Comment on a spot”, then tap the place you mean.'))};
  const pinning=on=>{pinBtn.setAttribute('aria-pressed',String(on));body.classList.toggle('pinning',on)};pinBtn.onclick=()=>pinning(pinBtn.getAttribute('aria-pressed')!=='true');
  zm.addEventListener('click',e=>{if(!body.classList.contains('pinning'))return;const r=zm.getBoundingClientRect(),x=(e.clientX-r.left)/r.width*100,y=(e.clientY-r.top)/r.height*100;askPin(x,y)});
  const askPin=(x,y,text)=>{zm.querySelector('.swipe-pin-pop')?.remove();const pop=el('div','swipe-pin-pop');pop.style.left=`min(${x}%, calc(100% - 268px))`;pop.style.top=`calc(${y}% + 8px)`;
   const inp=el('input');inp.placeholder='What should change here?';inp.setAttribute('aria-label','Comment on this spot');if(text)inp.value=text;
   const row=el('div','row'),m=el('button','btn sm');m.type='button';m.append(ic('mic',14),'Talk');m.onclick=()=>{inp.value=o.transcript||'Make this bigger.'};const add=el('button','btn primary sm','Add');add.type='button';
   const tmp=pinEl({x,y,text:''},(pins[it.id]||[]).length);zm.append(tmp);
   add.onclick=()=>{if(!inp.value.trim())return;(pins[it.id]=pins[it.id]||[]).push({x,y,text:inp.value.trim()});pop.remove();tmp.title=inp.value.trim();pinning(false);drawList()};
   row.append(m,el('span','grow'),add);pop.append(inp,row);zm.append(pop);if(!o.state)inp.focus();return pop};
  (pins[it.id]||[]).forEach((pn,i)=>zm.append(pinEl(pn,i)));
  foot.append(hint,list);drawList();v.append(barEl,body,foot);overlay=v;host.append(v);close.focus();return {askPin,pinning,setZ}};
 host.addEventListener('keydown',e=>{if(e.target.closest('textarea,input'))return;
  if(e.key==='Escape'&&overlay){e.preventDefault();overlay.classList.contains('swipe-viewer')?(closeOverlay(),render()):(closeOverlay(),cur&&reset(cur));return}
  if(overlay)return;if(e.key==='ArrowRight'){e.preventDefault();fly('ok')}else if(e.key==='ArrowLeft'){e.preventDefault();fly('no')}else if(e.key==='ArrowDown'){e.preventDefault();fly('talk')}
  else if(e.key===' '){e.preventDefault();cur&&openViewer()}else if(e.key==='z'||e.key==='Z'){e.preventDefault();undo()}});
 render();
 return {fly,undo,openComment,openViewer,show:(dx,dy)=>cur&&show(cur,dx,dy),pins,get index(){return idx}}};
})();
