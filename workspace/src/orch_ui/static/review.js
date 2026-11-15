/* Review stack page module (15 Nov 2026). Built on UI.swipeDeck (widgets.js). Plain DOM, text only via textContent.
   Needs: components.js (UI.toast), icons.js, widgets.js, and widgets.css / components.css for the look.

   UI.reviewPage(host, api, o)   the page body: Waiting deck + Answered list. Returns {reload, destroy, show}.
       o: {nav (element that receives the Waiting / Answered buttons, else they sit above the deck),
           meta (element whose text becomes "Review · <workspace>" once api.workspace is known),
           poll (ms, default 5000, 0 = off), now (Date, tests)}
   UI.decisionRecord(entry, o)   one Decision card (Decisions tab and the Answered list). o: {fileUrl, now}
   UI.decisionsNow(entries, o)   the "What applies now" block (null when nothing was answered yet)
   UI.reviewFetchApi(base, f)    the api for pages served by orch itself: same-origin /api/stack, /api/answered,
                                 /api/answer, /api/file (f = fetch, for tests)
   UI.review                     pure helpers (mapCard, verdictWord, fmtTime) for tests

   api (what the page needs; the dashboard passes its own):
     stack()    -> Promise<[card]>      card = one row of `orch review list --json`:
                  {id, ticket, key, card:{kind,title,why,need,then,ok_label,signs,open,preview}, digest, since}
                  preview refs are "reviewed/<sha12>/<name>" files; the page asks api.fileUrl for them
     answered() -> Promise<[entry]>     entry = {id, ticket, key, card, shown:{digest,copy,files}, at, by, via,
                  decision:{action:approve|use|use_with_changes|send_back|dont|none_of_these, picked, allows,
                  changes:[str], words:{text, voice:[{text,secs}]}, pins:[{n,on,x,y,text}], summary, replaces, replaced_by}}
     answer({id, digest, verdict:'ok'|'no'|'talk', picked, note}) -> Promise<{ok, error?:{code,message}}>
                  note = {text, pins:[{n,on,x,y,text}]} when the person wrote words or marked spots
     fileUrl(card, ref) -> string       URL of one reviewed file of that card or entry
   A rejected stack()/answered() with error.code 'needs_person' (or 401/403) shows the plain sign-in state. */
(()=>{'use strict';const UI=window.UI=window.UI||{};
const el=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!=null)n.textContent=text;return n};
const KIND={draft:['Draft','page'],check:['Check','check'],link:['Publish','link'],choice:['Choose','cards'],plan:['Plan','note']};

/* ---------- time: "today 09:12", "yesterday 17:05", "Thu 16:05", "12 Nov" ---------- */
const pad=n=>String(n).padStart(2,'0');
const toDate=v=>{if(v==null||v==='')return null;const d=typeof v==='number'?new Date(v<1e12?v*1000:v):new Date(v);return isNaN(d)?null:d};
const fmtTime=(v,now)=>{const d=toDate(v);if(!d)return '';now=now||new Date();const day=x=>new Date(x.getFullYear(),x.getMonth(),x.getDate()).getTime();
 const diff=Math.round((day(now)-day(d))/864e5),hm=pad(d.getHours())+':'+pad(d.getMinutes());
 if(diff===0)return 'today '+hm;if(diff===1)return 'yesterday '+hm;
 if(diff>1&&diff<7)return ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'][d.getDay()]+' '+hm;
 return d.getDate()+' '+['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][d.getMonth()]};

/* ---------- card JSON -> the widget's item ---------- */
const refOf=p=>p&&(p.src||p.ref||p.file);
const mapPreview=(p,c,api)=>{if(!p||typeof p!=='object')return {type:'doc'};const q=Object.assign({},p);
 if(q.type==='page'||q.type==='img'){const r=refOf(p);q.src=r?api.fileUrl(c,r):'';delete q.ref;delete q.file}
 if(q.type==='compare'){q.before=mapPreview(p.before,c,api);q.after=mapPreview(p.after,c,api)}
 if(q.type==='options')q.options=(p.options||[]).map(op=>Object.assign({},op,{preview:op.preview?mapPreview(op.preview,c,api):undefined}));
 return q};
const safeOpen=u=>typeof u==='string'&&/^https?:\/\//i.test(u)?u:undefined;
const mapCard=(c,api,now)=>{const k=c.card||{},kd=KIND[k.kind]||[k.kind||'Review','file'];
 return {id:c.id,kind:k.kind,kindLabel:kd[0],icon:kd[1],ticket:c.key||c.ticket,when:fmtTime(c.since,now),need:k.need,title:k.title||'Review',
  why:k.why,okLabel:k.ok_label,then:k.then,signs:!!k.signs,open:safeOpen(k.open),preview:mapPreview(k.preview,c,api),digest:c.digest,raw:c}};

/* ---------- Decisions: words, pill, record ---------- */
const verdictWord=e=>{const d=e.decision||{},k=e.card||{},n=(d.changes||[]).length;
 switch(d.action){
  case 'use':return 'Use '+d.picked;
  case 'use_with_changes':return 'Use '+d.picked+' with '+n+(n===1?' change':' changes');
  case 'send_back':return 'Sent back for changes';
  case 'none_of_these':return 'None of these';
  case 'dont':return k.kind==='check'?'Sent back':"Don't do";
  case 'approve':return d.allows||k.ok_label||'Looks good';
  default:return d.summary||'Answered'}};
const verdictClass=e=>{const a=(e.decision||{}).action;return a==='dont'||a==='none_of_these'?'no':a==='send_back'?'talk':'ok'};

const thumbs=(e,o)=>{const k=e.card||{},p=k.preview||{},d=e.decision||{},out=[];
 const content=pv=>{const w=el('span','opt-thumb');
  if(!pv)return w;
  if(pv.type==='img'||pv.type==='page'){const r=refOf(pv),u=r&&o.fileUrl?o.fileUrl(e,r):'';
   if(pv.type==='img'){const i=el('img');i.src=u;i.alt=pv.alt||'';i.draggable=false;w.append(i)}
   else{const f=el('iframe');f.src=u;f.title=pv.title||k.title||'Reviewed page';f.setAttribute('sandbox','');f.tabIndex=-1;f.loading='lazy';w.append(f)}}
  else if(pv.type==='table'){const t=el('div','doc');t.append(el('h4','',(pv.cols||[]).join(' · ')));(pv.rows||[]).slice(0,3).forEach(r=>t.append(el('p','',r.join(' · '))));w.append(t)}
  else{const t=el('div','doc');if(pv.heading)t.append(el('h4','',pv.heading));(pv.paras||[]).slice(0,2).forEach(x=>t.append(el('p','',x)));w.append(t)}
  return w};
 const shot=(label,pv,on,taken,dim)=>{const b=el('button','decision-shot'+(taken?' taken':'')+(dim?' dim':''));b.type='button';b.dataset.on=on;
  const w=content(pv),cap=el('span');cap.append(el('b','',label));b.append(w,cap);out.push({b,w,on,taken:!!taken});return b};
 if(p.type==='options')(p.options||[]).forEach(op=>shot(op.id+' · '+op.title+(op.suggested?' (suggested)':''),op.preview,'option '+op.id,d.picked===op.id,d.picked&&d.picked!==op.id));
 else if(p.type==='compare'){shot('Before',p.before,'before');shot('After',p.after,'after')}
 else shot(k.title||'Reviewed',p,'');
 /* pins sit on the thumbnail they were set on (else the taken one, else the first) */
 (d.pins||[]).forEach((pn,i)=>{const t=out.find(x=>x.on&&(x.on===pn.on||x.on==='option '+pn.on))||out.find(x=>x.taken)||out[0];
  if(!t)return;const s=el('span','swipe-pin');s.style.left=pn.x+'%';s.style.top=pn.y+'%';s.title=pn.text||'';s.append(el('span','',String(pn.n||i+1)));t.w.append(s)});
 return out.map(x=>x.b)};

UI.decisionRecord=(e,o)=>{o=o||{};const d=e.decision||{},k=e.card||{},c=el('article','decision');c.dataset.id=e.id||'';
 const h=el('div','decision-h'),v=el('span','decision-verdict '+verdictClass(e),verdictWord(e));
 h.append(el('h3','',k.title||'Answered'),v);
 const by=[e.by,e.via,fmtTime(e.at,o.now)].filter(Boolean).join(' · ');
 c.append(h,el('div','decision-by',by));
 const th=thumbs(e,o);if(th.length){const g=el('div','decision-shown');th.forEach(x=>g.append(x));c.append(g)}
 const w=d.words||{},lines=[];if(w.text)lines.push(w.text);(w.voice||[]).forEach(x=>x&&x.text&&lines.push('Voice: '+x.text));
 (d.pins||[]).forEach((pn,i)=>lines.push('Spot '+(pn.n||i+1)+(pn.on?' on '+pn.on:'')+': '+pn.text));
 if(lines.length){const b=el('div','decision-words');lines.forEach(x=>b.append(el('p','',x)));c.append(b)}
 const f=el('div','decision-foot'),first=Object.keys((e.shown||{}).files||{})[0];
 if(o.fileUrl&&first){const a=el('a','btn ghost sm','View reviewed version');a.href=o.fileUrl(e,'reviewed/'+(((e.shown||{}).copy||'').replace(/^reviewed\//,'').replace(/\/$/,''))+'/'+first);a.target='_blank';a.rel='noopener';f.append(a)}
 f.append(el('span','',d.replaced_by?'Replaced by a later answer.':d.replaces?'Replaces your earlier answer.':'Kept exactly as you saw it.'));
 if(d.replaced_by)c.classList.add('replaced');
 c.append(f);return c};

/* "What applies now": the newest answer that no later one replaced, with its changes. */
UI.decisionsNow=(entries,o)=>{o=o||{};const live=(entries||[]).filter(e=>e.decision&&!e.decision.replaced_by);if(!live.length)return null;
 const e=live.slice().sort((a,b)=>(toDate(b.at)||0)-(toDate(a.at)||0))[0],d=e.decision,k=e.card||{},s=el('section','decision now');
 s.setAttribute('aria-label','What applies now');s.append(el('p','eyebrow','What applies now'));
 const h=el('h2','',d.summary||verdictWord(e));h.style.cssText='margin:0;font-size:20px;line-height:28px';s.append(h);
 if((d.changes||[]).length){const ol=el('ol');ol.style.cssText='margin:0;padding-left:20px;display:grid;gap:4px';d.changes.forEach(x=>ol.append(el('li','',x)));s.append(ol)}
 const next=d.next||(verdictClass(e)==='ok'?k.then:'');if(next){const p=el('p','decision-by');p.style.margin='0';p.append(el('strong','','Next: '),next);s.append(p)}
 return s};

/* ---------- api for pages served by orch itself ---------- */
UI.reviewFetchApi=(base,f)=>{base=base||'';f=f||((...a)=>window.fetch(...a));
 const fail=(r,msg)=>{const e=new Error(msg||'request failed');e.status=r.status;e.code=r.status===401||r.status===403?'needs_person':'error';return e};
 const get=async p=>{const r=await f(base+p,{headers:{accept:'application/json'},cache:'no-store'});if(!r.ok)throw fail(r);return r.json()};
 const api={workspace:'',
  stack:async()=>{const j=await get('/api/stack');if(j&&!Array.isArray(j)){api.workspace=j.workspace||api.workspace;return j.cards||[]}return j},
  answered:async()=>{const j=await get('/api/answered');return Array.isArray(j)?j:(j&&j.entries)||[]},
  answer:async body=>{try{const r=await f(base+'/api/answer',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(body)});
    let j=null;try{j=await r.json()}catch{}
    if(j&&typeof j==='object'&&('ok' in j))return j;
    if(r.status===401||r.status===403)return {ok:false,error:{code:'needs_person',message:'Sign in first.'}};
    return r.ok?{ok:true}:{ok:false,error:{code:'error',message:'Could not save your answer.'}}}
   catch{return {ok:false,error:{code:'error',message:'Could not reach orch.'}}}},
  fileUrl:(c,ref)=>{const m=/^reviewed\/([^/]+)\/(.+)$/.exec(ref||'');if(!m)return '';
   return base+'/api/file?t='+encodeURIComponent(c.ticket)+'&c='+encodeURIComponent(m[1])+'&n='+encodeURIComponent(m[2])}};
 return api};

/* ---------- the page ---------- */
UI.reviewPage=(host,api,o)=>{o=o||{};const pollMs=o.poll==null?5000:o.poll;
 const deckEl=el('section'),ansEl=el('section');deckEl.id='deck';deckEl.setAttribute('aria-label','Review deck');ansEl.id='answered';ansEl.hidden=true;ansEl.setAttribute('aria-label','Answered');
 const mkBtn=(label,view)=>{const b=el('button','btn sm');b.type='button';b.dataset.show=view;b.append(label,' ',el('span','meta',''));return b};
 const bWait=mkBtn('Waiting','deck'),bAns=mkBtn('Answered','answered'),nav=el('nav','segmented');nav.setAttribute('aria-label','Show');nav.append(bWait,bAns);
 if(o.nav)o.nav.append(nav);else host.append(nav);host.append(deckEl,ansEl);
 let deck=null,view='deck',timer=null,alive=true,dirty=false,loading=false;const gone=new Set();/* id@digest answered here */
 const sig=it=>it.id+'@'+it.digest;
 const waitCount=n=>{bWait.lastChild.textContent=n?String(n):'';bWait.setAttribute('aria-pressed',String(view==='deck'))};
 const setView=v=>{view=v;bWait.setAttribute('aria-pressed',String(v==='deck'));bAns.setAttribute('aria-pressed',String(v==='answered'));deckEl.hidden=v!=='deck';ansEl.hidden=v!=='answered';if(v==='answered')drawAnswered();else if(deck)deckEl.focus()};
 const signIn=()=>{deck=null;deckEl.replaceChildren(UI.state({kind:'empty',title:'Sign in',text:'Run orch review in your terminal. It opens this page signed in.'}));waitCount(0)};
 const isAuth=e=>e&&(e.code==='needs_person'||e.status===401||e.status===403);
 const err=e=>{if(isAuth(e))return signIn();deck=null;deckEl.replaceChildren(UI.state({kind:'error',title:"Can't reach orch",text:'Is the review page still running in your terminal?',action:{label:'Try again',onClick:()=>load(true)}}));waitCount(0)};
 const touchMeta=()=>{if(o.meta&&api.workspace)o.meta.textContent='Review · '+api.workspace};
 /* answers go to orch; a failed one brings the card back */
 const send=(it,verdict,note)=>{const body={id:it.id,digest:it.digest,verdict,picked:null,note:null};
  if(note&&note.picked)body.picked=note.picked;else if(note&&note.about&&note.about!=='all')body.picked=note.about;
  const w=note&&note.changes;if(w&&(w.text||(w.pins||[]).length))body.note={text:w.text||'',pins:(w.pins||[]).map((p,i)=>({n:p.n||i+1,on:p.on||'',x:p.x,y:p.y,text:p.text}))};
  gone.add(sig(it));
  Promise.resolve().then(()=>api.answer(body)).catch(()=>({ok:false,error:{code:'error',message:'Could not reach orch.'}})).then(res=>{
   if(res&&res.ok){if(view==='answered')drawAnswered();return}
   gone.delete(sig(it));const code=res&&res.error&&res.error.code;
   if(code==='changed')UI.toast('This card changed. Showing the new version.');
   else if(code==='needs_person')UI.toast('Sign in to answer: run orch review in your terminal.',null,'error');
   else UI.toast((res&&res.error&&res.error.message)||'Could not save your answer. It is waiting again.',null,'error');
   dirty=true;load(true)})};
 const build=(items,start,later,pins)=>{deckEl.replaceChildren();
  deck=UI.swipeDeck(deckEl,items,{mode:'desk',voice:false,start,later,pins,onDecide:send,onChange:()=>{if(deck)waitCount(deck.items.length-Object.keys(deck.answers).length)}});
  waitCount(items.length-Object.keys(deck.answers).length)};
 const apply=(cards,force)=>{const items=cards.map(c=>mapCard(c,api,o.now)).filter(it=>!gone.has(sig(it)));
  if(!items.length&&!(deck&&Object.keys(deck.answers).length)){deck=null;deckEl.replaceChildren(UI.state({kind:'empty',title:'Nothing waits for you',text:'New cards appear here when a helper needs you.'}));waitCount(0);return}
  if(!items.length)return;/* everything answered here: keep the summary */
  if(deck){const have=deck.items.filter(i=>!deck.answers[i.id]).map(sig).sort().join('|');if(!force&&have===items.map(sig).sort().join('|'))return;
   if(deck.busy){dirty=true;return}/* a sheet or a move is open: try again on the next poll */}
  dirty=false;const cur=deck&&deck.items[deck.index],at=cur?items.findIndex(i=>i.id===cur.id):-1;
  const keep=new Set(deck?deck.items.map(sig):[]),pins={};if(deck)Object.keys(deck.pins).forEach(id=>{const n=items.find(i=>i.id===id);if(n&&keep.has(sig(n)))pins[id]=deck.pins[id]});
  const later=deck?[...deck.later].filter(id=>items.some(i=>i.id===id)):[];
  build(items,at>0?at:0,later,pins)};
 const load=async force=>{if(loading||!alive)return;loading=true;try{const cards=await api.stack();touchMeta();apply(cards,!!force)}catch(e){if(!deck||isAuth(e))err(e)}finally{loading=false}};
 const drawAnswered=async()=>{try{const list=await api.answered();if(!alive)return;ansEl.replaceChildren();
   if(!list.length){ansEl.append(UI.state({kind:'empty',title:'No answers yet',text:'Your answers appear here and on each ticket.'}));return}
   list.forEach(e=>ansEl.append(UI.decisionRecord(e,{fileUrl:api.fileUrl,now:o.now})))}
  catch(e){ansEl.replaceChildren(isAuth(e)?UI.state({kind:'empty',title:'Sign in',text:'Run orch review in your terminal. It opens this page signed in.'}):UI.state({kind:'error',title:"Can't reach orch",text:'Is the review page still running in your terminal?',action:{label:'Try again',onClick:drawAnswered}}))}};
 bWait.onclick=()=>setView('deck');bAns.onclick=()=>setView('answered');
 deckEl.replaceChildren(UI.state({kind:'loading'}));waitCount(0);setView('deck');
 const tick=()=>{if(typeof document!=='undefined'&&document.visibilityState==='hidden')return;load(dirty);if(view==='answered')drawAnswered()};
 load(false);if(pollMs>0)timer=setInterval(tick,pollMs);
 return {reload:()=>load(true),show:setView,destroy:()=>{alive=false;clearInterval(timer)},get deck(){return deck},tick};
};
UI.review={mapCard,verdictWord,fmtTime,mapPreview};
})();
