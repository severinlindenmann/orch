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
/* Helpers list (ORCH-61): one row per live helper, the same on dashboard Home and in Focus. The state comes from the core
   (orch run status "helper": working | starting | you | waiting | idle | stuck); the page never words it itself.
   UI.helperPill(state, word) -> the worded pill; UI.helperSummary(rows) -> "4 working · 1 waits for you · 1 idle";
   UI.helperList(rows, o) -> <section class="card helper-list"> with rows {key, title, href, state, word, meta, actions:[{label, run, key}]},
   o.title (default "Helpers"), o.empty (shown when there are no rows), o.dataKey. */
const HELPER_LOOK={working:['working','working'],starting:['working','working'],you:['needs','needs'],waiting:['','check'],idle:['','todo'],stuck:['failed','needs']};
UI.helperPill=(state,word)=>{const [cls,icon]=HELPER_LOOK[state]||['','todo'];const p=el('span','pill helper-pill'+(cls?' '+cls:''));p.dataset.state=state||'';p.append(UI.statusIcon(icon),document.createTextNode(word||''));return p};
const HELPER_COUNT=[['working','working'],['starting','starting'],['you','waits for you','wait for you'],['waiting','on hold'],['idle','idle'],['stuck','stuck']];
UI.helperSummary=rows=>{const n={};(rows||[]).forEach(r=>{n[r.state]=(n[r.state]||0)+1});return HELPER_COUNT.filter(([k])=>n[k]).map(([k,one,many])=>n[k]+' '+(n[k]>1&&many?many:one)).join(' · ')};
/* The meta line under a helper's title, the same words everywhere: "Step 3 of 4 · 52 min", "Since 3 h · your answer",
   "Nothing running for 18 min". row: {state, detail, step:{n,of}, minutes, idle, finished} (minutes: since start, idle: quiet). */
const helperSpan=m=>m==null?'':m<1?'just now':m<60?m+' min':m<1440?Math.round(m/60)+' h':Math.round(m/1440)+' days';
UI.helperMeta=r=>{r=r||{};const d=r.detail||'';
 if(r.finished&&(r.state==='idle'||r.state==='stuck'))return 'Finished · '+(d||'session still open');
 if(r.state==='you')return [r.idle!=null?'Since '+helperSpan(r.idle):'',d.toLowerCase()].filter(Boolean).join(' · ');
 if(r.state==='waiting'||r.state==='idle'||r.state==='stuck')return d;
 return [r.step?'Step '+r.step.n+' of '+r.step.of:'',helperSpan(r.minutes),d].filter(Boolean).join(' · ')};
/* The ticket's one state (ORCH-71): the ticket page strip and Focus show the same pill and word for the same ticket.
   t: {status, questions, bring_back}; helper: the core's helper state {state, word, detail} while a helper runs, else null.
   UI.ticketState(t, helper) -> {pill, word, helper}; pill is a status icon name (todo, working, needs, check, done).
   UI.ticketPill(s) -> the pill for that state: the helper pill while a helper runs, else the status pill. */
const TICKET_WORD={open:'To do',ready:'To do',active:'Working',waiting:'Needs you',review:'Check',done:'Done',dropped:'Dropped'};
const HELPER_WORD={working:'Working',starting:'Starting',you:'Waits for you',waiting:'On hold',idle:'Idle',stuck:'Stuck'};
const HELPER_PILL={working:'working',starting:'working',you:'needs',waiting:'check',idle:'todo',stuck:'needs'};
UI.ticketState=(t,helper)=>{t=t||{};
 if(t.status==='done')return {pill:'done',word:'Done',helper:null};
 if((t.questions||[]).some(q=>q&&q.answer==null))return {pill:'needs',word:'Needs you',helper:null};
 if(t.status==='review')return {pill:'check',word:'Check',helper:null};
 if(t.bring_back&&t.bring_back.state==='waiting')return {pill:'needs',word:'Needs you',helper:null};
 if(helper&&HELPER_WORD[helper.state])return helper.state==='working'?{pill:'working',word:'Working',helper:null}:{pill:HELPER_PILL[helper.state],word:HELPER_WORD[helper.state],helper};
 if(helper)return {pill:'working',word:'Working',helper:null};
 return {pill:'todo',word:TICKET_WORD[t.status]||'To do',helper:null}};
UI.ticketPill=s=>{s=s||{};if(s.helper)return UI.helperPill(s.helper.state,s.word);const p=el('span','pill'+(['working','needs','done'].includes(s.pill)?' '+s.pill:''));p.dataset.state=s.pill||'';p.append(UI.statusIcon(s.pill),document.createTextNode(s.word||''));return p};
UI.helperList=(rows,o)=>{o=o||{};rows=rows||[];const box=el('section','card helper-list');if(o.dataKey)box.dataset.key=o.dataKey;
 const head=el('header','card-h');head.append(el('h2','',o.title||'Helpers'));const sum=UI.helperSummary(rows);if(sum)head.append(el('span','meta helper-sum',sum));box.append(head);
 if(!rows.length){box.append(el('p','card-row meta',o.empty||'No helper is running.'));return box}
 rows.forEach(r=>{const row=el('div','card-row helper-row');row.dataset.state=r.state||'';if(r.dataKey)row.dataset.key=r.dataKey;
  const main=el('div','grow helper-main'),title=el(r.href?'a':'span','helper-title');if(r.href)title.href=r.href;title.title=(r.key?r.key+' ':'')+(r.title||'');
  if(r.key)title.append(el('span','helper-key',r.key),document.createTextNode(' '));title.append(document.createTextNode(r.title||''));main.append(title);
  const meta=r.meta!=null?r.meta:UI.helperMeta(r);if(meta)main.append(el('p','meta',meta));
  const side=el('div','helper-side');side.append(UI.helperPill(r.state,r.word));
  (r.actions||[]).forEach(a=>{const b=el('button','btn outline sm',a.label);b.type='button';if(a.key)b.dataset.key=a.key;b.onclick=()=>a.run&&a.run(b);side.append(b)});
  row.append(main,side);box.append(row)});
 return box};
/* Status icon: UI.statusIcon('needs') -> <svg class="st needs"> (todo | working | needs | check | done) */
UI.statusIcon=name=>svg('st '+(ST[name]?name:'todo'),ST[name]||ST.todo);
/* Phone bottom bar (ORCH-73): UI.tabbar(items) -> <nav class="tabbar">. items: {label, href | onClick, current, count,
   countLabel, icon (an svg node or markup from icon()), testid}. A count shows only when it is above 0. A button item (no href) is a toggle:
   o.expanded sets aria-expanded, o.controls its aria-controls. Same item keys update in place via UI.tabbar.update(nav, items). */
const tabItem=it=>{const n=it.href!=null?el('a'):el('button');if(it.href!=null)n.href=it.href;else{n.type='button';if(it.controls)n.setAttribute('aria-controls',it.controls)}
 n.dataset.tab=it.key||it.label;if(it.testid)n.dataset.testid=it.testid;fillTab(n,it);if(it.onClick)n.addEventListener('click',it.onClick);return n};
const fillTab=(n,it)=>{const kids=[];if(it.icon){const i=el('span','tab-ic');i.setAttribute('aria-hidden','true');if(typeof it.icon==='string')i.innerHTML=it.icon;else i.append(it.icon);kids.push(i)}
 kids.push(el('span','tab-label',it.label));const c=Number(it.count)||0;
 if(c>0){const b=el('span','count',String(c));kids.push(b)}
 n.replaceChildren(...kids);n.setAttribute('aria-label',c>0?it.label+', '+(it.countLabel||String(c)):it.label);
 if(it.href!=null){if(it.current)n.setAttribute('aria-current','page');else n.removeAttribute('aria-current')}
 else n.setAttribute('aria-expanded',String(!!it.expanded))};
UI.tabbar=(items,o)=>{o=o||{};const nav=el('nav','tabbar'+(o.sample?' tabbar-sample':''));nav.setAttribute('aria-label',o.label||'Main');if(o.id)nav.id=o.id;
 (items||[]).forEach(it=>nav.append(tabItem(it)));return nav};
UI.tabbar.update=(nav,items)=>{(items||[]).forEach(it=>{const n=[...nav.children].find(x=>x.dataset.tab===(it.key||it.label));if(n)fillTab(n,it)})};
/* Short rows (ORCH-73): UI.shortGroup({title, icon:'needs'|'working'|..., count, folded, onToggle, rows, more, key}) -> <section class="card short-group">.
   rows: {key (the ticket number), title, href, fact, side (a node: pill, chip or button), child}. more: {label, onClick}. */
UI.shortRow=r=>{const row=el('div','short-row'+(r.child?' child':''));const g=el('span','grow');const t=r.href?el('a','short-title'):el('span','short-title');
 if(r.href)t.href=r.href;if(r.key){const k=el('span','key',r.key);t.append(k,document.createTextNode(' '))}t.append(document.createTextNode(r.title||''));g.append(t);
 if(r.fact)g.append(el('span','short-fact',r.fact));row.append(g);if(r.side){const s=el('span','short-side');s.append(r.side);row.append(s)}
 if(r.dataKey)row.dataset.key=r.dataKey;return row};
UI.shortGroup=o=>{o=o||{};const sec=el('section','card short-group');if(o.key)sec.dataset.key=o.key;const h=el('header','card-h');const b=el('button');b.type='button';
 b.setAttribute('aria-expanded',String(!o.folded));if(o.icon)b.append(UI.statusIcon(o.icon));b.append(el('span','',o.title||''));
 if(o.count!=null)b.append(el('span','count',String(o.count)));b.append(UI.chevron());if(o.onToggle)b.addEventListener('click',o.onToggle);h.append(b);sec.append(h);
 if(!o.folded){(o.rows||[]).forEach(r=>sec.append(UI.shortRow(r)));if(o.more){const m=el('div','short-more');const mb=el('button','btn ghost sm',o.more.label);mb.type='button';if(o.more.onClick)mb.addEventListener('click',o.more.onClick);m.append(mb);sec.append(m)}}
 return sec};
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
/* Swipe review deck (draft 15 Nov, revised after the Codex challenge): UI.swipeDeck(host, items, o)
   o: {mode:'phone'|'desk', start, picked:{itemId:'C'}, voice (false: text only, no mic or clips), answered:{itemId:{verdict,note}}, later:[ids], pins:{itemId:[pin]}, quiet, transcript, onDecide(item, verdict, note), onUndo(item), onChange()}
   Answers are buttons and keys only, no swipe (owner 16 Nov: "we already have the arrows or buttons to click"):
   → approve (the button names the action: it.okLabel, "Use C"), ← Don't do / Send back / None of these,
   ↓ comment sheet whose buttons name the outcome ("Send back for changes" / "Use C with these changes"),
   ↑ Later (stays unanswered, goes to the end); Space bigger, B before/after, O all, Z undo. A tap on an option picks
   it, a tap on the picture opens it bigger. The answered card fades; nothing flies. Every card says what happens
   when you approve (it.then). Item extras: text (the question), group, suggest ('ok'|'no'), links [{label,url}].
   verdicts: ok | no | talk | later. note: {picked, changes:{text, clips, pins:[{n,on,x,y,text}]}, about} */
UI.swipeDeck=(host,items,o)=>{o=o||{};const mode=o.mode||'desk',ic=(n,z)=>{const t=document.createElement('template');t.innerHTML=window.icon?window.icon(n,z||20):'';return t.content};
 let idx=o.start||0,overlay=null,cur=null,busy=false;const done=[],ans={},pins={},drafts={},later=new Set(o.later||[]),picked=Object.assign({},o.picked);
 Object.assign(pins,o.pins);Object.entries(o.answered||{}).forEach(([id,a])=>{const it=items.find(x=>x.id===id);if(it)ans[id]={verdict:a.verdict,note:a.note||null,item:it}});
 host.classList.add('swipe','swipe-'+mode);host.tabIndex=0;host.setAttribute('role','region');host.setAttribute('aria-label','Review, one item at a time');
 const btn=(cls,children,label)=>{const b=el('button',cls);b.type='button';children.forEach(c=>b.append(c));if(label)b.setAttribute('aria-label',label);return b};
 /* top: progress words, All, Undo */
 const top=el('div','swipe-top'),count=el('span'),bar=el('div','progress'),fill=el('span');bar.append(fill);
 const allBtn=btn('btn ghost sm',[ic('cards',16),'All'],'All cards');allBtn.onclick=()=>openOverview();
 const undoBtn=btn('btn ghost sm',[ic('undo',16),'Undo']);undoBtn.onclick=()=>undo();
 top.append(count,bar,allBtn,undoBtn);
 const stage=el('div','swipe-stage'),live=el('div','sr-only');live.setAttribute('aria-live','polite');
 /* bottom: the three answers + Later */
 const acts=el('div','swipe-actions');
 const mk=(cls,icon,label,key,fn)=>{const r=el('span','ring');r.append(ic(icon,cls==='ok'?28:24));const l=el('span','act-label'),w=el('span','act-word',label);l.append(w);if(key)l.append(el('kbd','',key));const b=btn('swipe-act '+cls,[r,l]);b.onclick=fn;return b};
 const noBtn=mk('no','x',"Don't do",'←',()=>fly('no')),talkBtn=mk('talk',o.voice?'mic':'comment','Comment','↓',()=>fly('talk')),okBtn=mk('ok','check','Looks good','→',()=>fly('ok'));
 const laterBtn=btn('btn ghost sm swipe-later',['Later']);laterBtn.append(el('kbd','','↑'));laterBtn.onclick=()=>fly('later');
 acts.append(noBtn,talkBtn,okBtn);const laterRow=el('div','swipe-later-row');laterRow.append(laterBtn);
 host.replaceChildren(top,stage,acts,laterRow,live);
 /* words */
 const isOpt=it=>!!(it&&it.preview&&it.preview.type==='options');
 const noWord=it=>it.noLabel||(isOpt(it)?'None of these':it.kind==='check'?'Send back':"Don't do");
 const okWord=it=>{if(!isOpt(it))return it.okLabel||'Looks good';const p=picked[it.id];return p?'Use '+p:'Pick one'};
 const ansWord=a=>!a?'':a.verdict==='ok'?(a.note&&a.note.picked?'Use '+a.note.picked+(a.note.changes?' with changes':''):(a.item.okLabel||'Looks good')):a.verdict==='no'?noWord(a.item):a.verdict==='talk'?'Sent back for changes':'Later';
 /* previews */
 const hasPreview=it=>{const p=it&&it.preview;if(!p||typeof p!=='object'||!p.type)return false;if(p.type==='doc')return !!(p.heading||(p.paras||[]).length||(p.steps||[]).length);return true};
 const frame=(src,title)=>{const fr=el('iframe');fr.src=src;fr.title=title;fr.setAttribute('sandbox','');fr.tabIndex=-1;fr.loading='lazy';fr.classList.add('loading');fr.addEventListener('load',()=>fr.classList.remove('loading'),{once:true});return fr};
 const buildPreview=(it,big)=>{const p=it.preview||{},f=document.createDocumentFragment();
  if(p.type==='compare'){f.append(buildCompare(it,big));return f}
  if(p.type==='options'){f.append(buildOptions(it,big));return f}
  if(p.type==='img'){const i=el('img');i.src=p.src;i.alt=p.alt||it.title;i.draggable=false;f.append(i)}
  else if(p.type==='page')f.append(el('span','preview-wait','Loading the preview…'),frame(p.src,it.title));
  else if(p.type==='table'){const t=el('table','mini-table'),h=el('tr');(p.cols||[]).forEach(c=>h.append(el('th','',c)));const th=el('thead');th.append(h);const tb=el('tbody');(p.rows||[]).slice(0,big?50:7).forEach(r=>{const tr=el('tr');r.forEach(c=>tr.append(el('td','',c)));tb.append(tr)});t.append(th,tb);f.append(t)}
  else{const d=el('div','doc');if(p.heading)d.append(el('h4','',p.heading));(p.paras||[]).forEach(x=>d.append(el('p','',x)));if(p.steps){const ol=el('ol');p.steps.forEach(x=>ol.append(el('li','',x)));d.append(ol)}f.append(d)}
  return f};
 /* Before / after. Card: Before · After · Both. Viewer: Slide (drag the handle, or the slider keys) · Side by side · Before · After. */
 const buildCompare=(it,big)=>{const p=it.preview,w=el('div','swipe-compare');const views=big?[['slide','Slide'],['both','Side by side'],['before','Before'],['after','After']]:[['before','Before'],['after','After'],['both','Both']];
  const ctl=el('div','segmented swipe-cmp-ctl');ctl.setAttribute('role','group');ctl.setAttribute('aria-label','Before and after');
  const set=v=>{w.dataset.view=v;ctl.querySelectorAll('button').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.v===v)))};
  const pane=side=>{const d=el('div','cmp-pane '+side);d.dataset.on=side;d.append(buildPreview({title:it.title+' '+side,preview:p[side]},big),el('span','cmp-tag',side==='before'?'Before':'After'));
   if(!big){const z=btn('btn icon sm cmp-zoom',[ic('expand',16)],side==='before'?'Make before bigger':'Make after bigger');z.dataset.side=side;z.addEventListener('pointerdown',e=>e.stopPropagation());z.onclick=e=>{e.stopPropagation();openViewer(side)};d.append(z)}return d};
  views.forEach(([v,l])=>{const b=btn('btn sm',[l]);b.dataset.v=v;b.onclick=e=>{e.stopPropagation();set(v)};ctl.append(b)});
  ctl.addEventListener('pointerdown',e=>e.stopPropagation());
  w.append(pane('before'),pane('after'),ctl);
  if(big){const line=el('div','cmp-line'),handle=el('span','cmp-handle'),r=el('input','cmp-range');line.append(handle);r.type='range';r.min='0';r.max='100';r.value='50';r.setAttribute('aria-label','Line between before and after');
   const cut=v=>{v=Math.max(0,Math.min(100,v));w.style.setProperty('--cut',v+'%');r.value=String(Math.round(v))};r.oninput=()=>cut(+r.value);cut(50);
   handle.addEventListener('pointerdown',e=>{e.stopPropagation();e.preventDefault();handle.setPointerCapture(e.pointerId);const mv=ev=>{const b=w.getBoundingClientRect();cut((ev.clientX-b.left)/b.width*100)};
    handle.addEventListener('pointermove',mv);handle.addEventListener('pointerup',()=>handle.removeEventListener('pointermove',mv),{once:true})});
   w.append(line,r);w.cut=cut}
  if(p.note)w.append(el('span','cmp-note',p.note));
  w.cycle=()=>{const i=views.findIndex(([v])=>v===w.dataset.view);set(views[(i+1)%views.length][0])};w.view=set;
  set(big?'slide':(mode==='phone'||(host.clientWidth&&host.clientWidth<560)?'after':'both'));return w};
 /* An option's letter chip only for a short id of its own (A, B, 2); a plain question's option has id = its text. */
 const optLetter=op=>{const id=String(op&&op.id||'');return id&&id.length<=2&&id!==op.title?id:''};
 /* Options with no picture at all (a plain orch ask --option question): plain rows, title and description, no frame. */
 const plainOpts=it=>{const p=it&&it.preview;return !!(p&&p.type==='options'&&!p.before&&!(p.options||[]).some(op=>op.preview))};
 /* Options A / B / C: tap to pick (ring + Picked). On the card a drag that starts on a tile still swipes; a tap picks. */
 const buildOptions=(it,big)=>{const p=it.preview,w=el('div','swipe-opts'+(big?' big':'')+(plainOpts(it)?' plain':''));w.style.setProperty('--n',String((p.options||[]).length+(p.before?1:0)));
  if(p.before){const t=el('div','swipe-opt today');t.dataset.on='before';const h=el('span','opt-h');h.append(el('b','opt-letter',''),el('span','opt-title','Today'));h.firstChild.append(ic('clock',14));
   const th=el('span','opt-thumb');th.append(buildPreview({title:'Today',preview:p.before},big));t.append(h,th);if(p.beforeText)t.append(el('span','opt-text',p.beforeText));w.append(t)}
  (p.options||[]).forEach(op=>{const b=btn('swipe-opt',[]),lt=optLetter(op);b.dataset.opt=op.id;b.dataset.on='option '+op.id;b.setAttribute('aria-pressed',String(picked[it.id]===op.id));b.setAttribute('aria-label',(lt?'Option '+lt+': ':'')+(op.title||op.id)+(op.suggested?' (suggested)':''));
   const h=el('span','opt-h');if(lt)h.append(el('b','opt-letter',lt));h.append(el('span','opt-title',op.title||op.id));if(op.suggested)h.append(el('span','opt-sug','Suggested'));
   b.append(h);if(op.preview){const th=el('span','opt-thumb');th.append(buildPreview({title:op.title,preview:op.preview},big));b.append(th)}/* no picture: no empty box */
   if(op.text)b.append(el('span','opt-text',op.text));const pk=el('span','opt-picked');pk.append(ic('check',14),'Picked');b.append(pk);
   b.onclick=e=>{e.stopPropagation();if(b.closest('.swipe-card')&&e.detail!==0)return;/* the card's tap handler picks on pointer taps */pick(it,picked[it.id]===op.id?null:op.id)};
   w.append(b)});
  return w};
 const pick=(it,id)=>{if(!it)return;if(id)picked[it.id]=id;else delete picked[it.id];
  host.querySelectorAll('.swipe-opt').forEach(b=>{if(b.closest('.swipe-card:not(.under):not(.under2),.swipe-viewer'))b.setAttribute('aria-pressed',String(b.dataset.opt===picked[it.id]))});
  syncWords();live.textContent=id?'Picked '+id:'Nothing picked'};
 const sugOf=it=>it&&it.suggest&&!isOpt(it)?it.suggest:null;
 const syncWords=()=>{const it=items[idx];if(!it)return;[[okBtn,'ok'],[noBtn,'no']].forEach(([b,v])=>{b.classList.toggle('suggested',sugOf(it)===v);b.querySelector('.act-sug')?.remove();if(sugOf(it)===v)b.append(el('span','opt-sug act-sug','Suggested'))});okBtn.querySelector('.act-word').textContent=okWord(it);noBtn.querySelector('.act-word').textContent=noWord(it);
  okBtn.classList.toggle('wait',okWord(it)==='Pick one');
  const st=cur&&cur.querySelector('.swipe-stamp.right');if(st)st.textContent=okWord(it)==='Pick one'?'Pick one first':okWord(it)};
 /* card */
 const pinEl=(pn,i)=>{const p=el('span','swipe-pin');p.style.left=pn.x+'%';p.style.top=pn.y+'%';p.append(el('span','',String(i+1)));p.title=pn.text;return p};
 const card=(it,layer)=>{const c=el('article','swipe-card'+(layer?' '+layer:''));c.setAttribute('aria-label',it.title);
  const h=el('header','swipe-head'),m=el('div','swipe-meta'),k=el('span','swipe-kind');k.append(ic(it.icon||'file',14),it.kindLabel||it.kind);m.append(k);if(it.need)m.append(el('span','swipe-need',it.need));if(it.group)m.append(el('span','swipe-group',it.group));if(it.ticket)m.append(el('span','',it.ticket));if(it.when)m.append(el('span','',it.when));
  const sw=it.suggest==='ok'?okWord(it):it.suggest==='no'?noWord(it):isOpt(it)?(((it.preview.options||[]).find(x=>x.suggested)||{}).id):null;if(sw&&sw!=='Pick one')m.append(el('span','swipe-sug','Suggested: '+sw));
  h.append(m);if(it.about)h.append(el('p','swipe-about','About: '+it.about));const t0=String(it.title||'').replace(/[\s….]+$/,''),cut=!!(it.text&&t0&&it.text.startsWith(t0));/* the title is only a cut copy of the question: show the question once */
  if(!cut)h.append(el('h3','',it.title));
  if(it.text&&(cut||it.text!==it.title))h.append(el('p','swipe-text',it.text));/* the whole question; a long one scrolls inside the head */
  if(it.why)h.append(el('p','swipe-why',it.why));
  const pv=hasPreview(it)?el('div','swipe-preview'+(plainOpts(it)?' plain':'')):null;/* nothing to preview: no empty box */
  if(pv){pv.append(buildPreview(it,false));
  if(!plainOpts(it)){const ex=btn('btn icon sm swipe-expand',[ic('expand',16)],'Make bigger');ex.onclick=e=>{e.stopPropagation();openViewer()};pv.append(ex)}
  (pins[it.id]||[]).forEach((pn,i)=>pv.append(pinEl(pn,i)));}
  const ft=el('footer','swipe-foot');
  if(it.then){const t=el('span','swipe-then');t.append(el('b','',(isOpt(it)?'If you pick one: ':'If you approve: ')),it.then);ft.append(t)}
  const row=el('div','swipe-foot-row');
  row.append(el('span','grow'));const pc=(pins[it.id]||[]).length;if(pc){const s=el('span','swipe-pins');s.append(ic('pin',14),pc+(pc===1?' spot marked':' spots marked'));row.append(s)}
  (it.links||[]).forEach(l=>{const a=el('a','btn ghost sm swipe-link');a.href=l.url;a.target='_blank';a.rel='noopener';a.append(ic('link',14),l.label);a.addEventListener('pointerdown',e=>e.stopPropagation());row.append(a)});/* the helper's links: a mockup, a reference */
  if(it.open){const a=el('a','btn ghost sm');a.href=it.open;a.target='_blank';a.rel='noopener';a.append(ic('external',14),'Open');a.addEventListener('pointerdown',e=>e.stopPropagation());row.append(a)}
  ft.append(row);
  c.append(...[h,pv,ft].filter(Boolean));return c};
 /* order: waiting cards first (Later ones at the end), then answered */
 const waiting=()=>{const w=items.map((_,i)=>i).filter(i=>!ans[items[i].id]);return w.filter(i=>!later.has(items[i].id)).concat(w.filter(i=>later.has(items[i].id)))};
 const nextIdx=from=>{const w=waiting();const pos=w.indexOf(from);return w.length?(pos>=0?w[pos]:w.find(i=>i>from&&!later.has(items[i].id))??w[0]):items.length};
 let ready=false;const change=()=>{if(ready&&o.onChange)o.onChange()};/* the first onChange comes after the constructor returns, so a handler may use the deck */
 const render=()=>{stage.replaceChildren();cur=null;const n=items.length,k=Object.keys(ans).length;
  count.textContent=k+' answered · '+(n-k)+' waiting';fill.style.width=(k/n*100)+'%';undoBtn.disabled=!done.length;
  if(idx>=n){acts.hidden=laterRow.hidden=true;stage.append(summary());change();return}acts.hidden=laterRow.hidden=false;
  const behind=waiting().filter(i=>i!==idx);
  if(behind[1]!=null)stage.append(card(items[behind[1]],'under2'));if(behind[0]!=null)stage.append(card(items[behind[0]],'under'));
  cur=card(items[idx]);const a=ans[items[idx].id];
  if(a){const t=el('div','swipe-was');t.append(ic('check',14),'You answered: '+ansWord(a)+'. A new answer is added, the old one stays on the ticket.');cur.querySelector('.swipe-foot').prepend(t)}
  stage.append(cur);syncWords();wire(cur);change()};
 const summary=()=>{const d=el('div','swipe-done');d.append(UI.statusIcon('done'),el('h3','',"You've answered everything in this review."));
  const t=el('div','tally'),c=v=>Object.values(ans).filter(x=>x.verdict===v).length;[['ok','check','approved'],['no','x','not done'],['talk','mic','sent back for changes']].forEach(([v,i,l])=>{const s=el('span');s.append(ic(i,16),c(v)+' '+l);t.append(s)});
  d.append(t,el('p','',"Each ticket shows what happens next. Answers are on the ticket, under its questions."));return d};
 /* drag */
 const dirOf=(dx,dy)=>Math.abs(dy)>Math.abs(dx)*1.1?(dy>0?'down':'up'):dx>0?'right':'left';
 const show=(c,dx,dy)=>{const w=stage.clientWidth||1,hgt=stage.clientHeight||1;c.style.transform=`translate(${dx}px,${dy}px) rotate(${dx/w*12}deg)`;
  const dir=dirOf(dx,dy),amt=(dir==='down'||dir==='up')?Math.abs(dy)/(hgt*.22):Math.abs(dx)/(w*.3);
  c.querySelectorAll('.swipe-stamp,.swipe-edge').forEach(s=>{s.style.opacity=s.classList.contains(dir)?Math.min(1,Math.max(0,amt)):0})};
 const reset=c=>{if(!c)return;c.style.transform='';c.querySelectorAll('.swipe-stamp,.swipe-edge').forEach(s=>s.style.opacity=0)};
 const wire=c=>{let sx=0,sy=0,t0=0,id=null,dx=0,dy=0,start=null;const pts=new Set();
  c.addEventListener('pointerdown',e=>{pts.add(e.pointerId);if(pts.size>1){id=null;c.classList.remove('dragging');reset(c);return}/* a second finger cancels */
   if(overlay||busy||e.button>0)return;const hb=host.getBoundingClientRect();if(mode==='phone'&&e.clientX-hb.left<16)return;/* leave the left edge to the system back gesture */
   id=e.pointerId;sx=e.clientX;sy=e.clientY;t0=performance.now();dx=dy=0;start=e.target;c.setPointerCapture(id)});
  c.addEventListener('pointermove',e=>{if(e.pointerId!==id)return;dx=e.clientX-sx;dy=e.clientY-sy});/* the card does not move: answers are buttons and keys (owner 16 Nov) */
  const end=e=>{pts.delete(e.pointerId);if(e.pointerId!==id)return;id=null;c.classList.remove('dragging');const dt=performance.now()-t0,dist=Math.hypot(dx,dy);
   if(dist<8&&dt<400){reset(c);const opt=start&&start.closest&&start.closest('.swipe-opt');if(opt){pick(items[idx],picked[items[idx].id]===opt.dataset.opt?null:opt.dataset.opt);return}
    if(start&&start.closest&&start.closest('.swipe-preview:not(.plain)')){const pn=start.closest('.cmp-pane');openViewer(pn?pn.dataset.on:null)}return}
   reset(c)};
  c.addEventListener('pointerup',end);c.addEventListener('pointercancel',e=>{pts.delete(e.pointerId);if(e.pointerId===id){id=null;c.classList.remove('dragging');reset(c)}})};
 const nudge=(c,msg)=>{reset(c);c.classList.remove('nudge');void c.offsetWidth;c.classList.add('nudge');live.textContent=msg;if(UI.toast&&!o.quiet)UI.toast(msg)};
 const fly=(verdict,dx,dy)=>{if(!cur||overlay||busy)return;const c=cur,it=items[idx],w=stage.clientWidth,h=stage.clientHeight;
  if(verdict==='talk')return openComment();
  if(verdict==='ok'&&isOpt(it)&&!picked[it.id])return nudge(c,'Tap the option you want first.');
  busy=true;c.classList.add('leaving');/* a short fade, no swipe */
  setTimeout(()=>{busy=false;verdict==='later'?defer(it):commit(verdict,isOpt(it)&&verdict==='ok'?{picked:picked[it.id]}:null)},120)};
 const defer=it=>{later.add(it.id);done.push({item:it,verdict:'later',idx,laterOnly:true});const w=waiting();idx=w.find(i=>!later.has(items[i].id))??w[0]??items.length;
  live.textContent='Later: '+it.title;render();if(UI.toast&&!o.quiet)UI.toast('Later: '+it.title+'. It stays at the end.',()=>undo())};
 const commit=(verdict,note)=>{const it=items[idx];done.push({item:it,verdict,note,idx,prev:ans[it.id],prevPick:ans[it.id]&&ans[it.id].note?ans[it.id].note.picked:undefined});ans[it.id]={verdict,note,item:it};later.delete(it.id);
  const from=idx;idx=nextIdx(from)===from?items.length:nextIdx(from);if(idx===from)idx=items.length;
  const word=ansWord(ans[it.id]);live.textContent=word+': '+it.title;o.onDecide&&o.onDecide(it,verdict,note);render();
  if(UI.toast&&!o.quiet)UI.toast(word+': '+it.title,()=>undo())};
 const undo=()=>{const last=done.pop();if(!last)return;if(last.laterOnly)later.delete(last.item.id);else if(last.prev){ans[last.item.id]=last.prev;if(last.prevPick)picked[last.item.id]=last.prevPick}else delete ans[last.item.id];
  idx=last.idx;closeOverlay();render();live.textContent='Back: '+last.item.title;o.onUndo&&o.onUndo(last.item);host.focus()};
 const jump=i=>{if(i<0||i>=items.length)return;closeOverlay();idx=i;render();host.focus()};
 /* overlays: inside the deck (a phone frame keeps them); the rest of the deck is inert; Tab stays inside; Esc closes */
 const openOverlay=(node,focusEl)=>{overlay=node;[top,stage,acts,laterRow].forEach(n=>n.inert=true);host.append(node);(focusEl||node.querySelector('button,[href],input,textarea'))?.focus()};
 const closeOverlay=()=>{if(!overlay)return;overlay.remove();overlay=null;[top,stage,acts,laterRow].forEach(n=>n.inert=false);host.focus()};
 host.addEventListener('keydown',e=>{if(e.key!=='Tab'||!overlay)return;const f=[...overlay.querySelectorAll('button:not([disabled]),[href],input,textarea,[tabindex="0"]')].filter(x=>x.offsetParent!==null);if(!f.length)return;
  const a=f[0],z=f[f.length-1];if(e.shiftKey&&document.activeElement===a){e.preventDefault();z.focus()}else if(!e.shiftKey&&document.activeElement===z){e.preventDefault();a.focus()}});
 /* Overview: every card with its answer, waiting first; tap one to jump there. */
 const openOverview=()=>{if(overlay)closeOverlay();const v=el('div','swipe-viewer swipe-overview');v.setAttribute('role','dialog');v.setAttribute('aria-label','All cards');
  const b=el('div','swipe-viewer-bar'),x=btn('btn ghost icon sm',[ic('x',18)],'Close');x.onclick=()=>{closeOverlay();render()};
  const k=Object.keys(ans).length;b.append(x,el('strong','','All cards · '+(items.length-k)+' waiting'));
  const tile=i=>{const it=items[i],a=ans[it.id],t=btn('swipe-ov'+(i===idx?' current':'')+(a?' answered':''),[]);
   const th=el('span','swipe-ov-thumb');const p=it.preview||{},pv=p.type==='compare'?p.after:p.type==='options'?(p.options[0]||{}).preview:p;th.append(buildPreview({title:it.title,preview:pv||{}},false));
   const m=el('span','swipe-meta'),kd=el('span','swipe-kind');kd.append(ic(it.icon||'file',12),it.kindLabel||it.kind);m.append(kd);if(it.need&&!a)m.append(el('span','swipe-need',it.need));
   const st=el('span','swipe-ov-state '+(a?a.verdict:later.has(it.id)?'later':'wait'),a?ansWord(a):later.has(it.id)?'Later':i===idx?'Now':'Waiting');
   t.append(th,m,el('span','swipe-ov-title',it.title),st);t.onclick=()=>jump(i);return t};
  const order=waiting().concat(items.map((_,i)=>i).filter(i=>ans[items[i].id]));
  /* grouped by ticket (the round), then by task ("About: ..."); cards without a task come last under their ticket */
  const tk=new Map();order.forEach(i=>{const it=items[i],key=it.group?'g:'+it.group:it.ticketId||it.ticket||'';let t=tk.get(key);if(!t){t={title:it.group||it.ticketTitle,key:it.group?'':it.ticket,tasks:new Map(),plain:[],rows:[]};tk.set(key,t)}t.rows.push(i);
   if(it.about){if(!t.tasks.has(it.task||it.about))t.tasks.set(it.task||it.about,{about:it.about,rows:[]});t.tasks.get(it.task||it.about).rows.push(i)}else t.plain.push(i)});
  const body=el('div','swipe-viewer-body');
  const head=(text,tag,cls)=>{const h=el(tag,cls,text);h.style.cssText='margin:0;padding:var(--s3) var(--s4) 0';body.append(h)};
  const grid=rows=>{const gr=el('div','swipe-ov-grid');rows.forEach(i=>gr.append(tile(i)));body.append(gr)};
  if(![...tk.values()].some(t=>t.title||t.tasks.size))grid(order);
  else tk.forEach(t=>{const left=t.rows.filter(i=>!ans[items[i].id]).length;head((t.title?(t.key&&t.key!==t.title?t.title+' · '+t.key:t.title):t.key)+' · '+(left?left+' of '+t.rows.length+' waiting':'all '+t.rows.length+' answered'),'h3');
   t.tasks.forEach(k=>{head('About: '+k.about,'p','meta');grid(k.rows)});if(t.plain.length)grid(t.plain)});
  v.append(b,body);openOverlay(v,body.querySelector('.current')||x);return v};
 /* Comment sheet. The subject (which option) and the outcome are separate: the buttons say what happens.
    Voice: hold to talk, or tap once to start and once to stop; clips can be removed. The draft is kept per card. */
 const openComment=()=>{const it=items[idx];if(!it)return null;const dr=drafts[it.id]=drafts[it.id]||{text:'',clips:[]};
  const scr=el('div','swipe-scrim'),sh=el('div','swipe-sheet');sh.setAttribute('role','dialog');sh.setAttribute('aria-label','Comment on '+it.title);
  const grab=el('div','grab');grab.title='Pull down to close; your words are kept';
  const ttl=el('h2','','What should change?'),sub=el('p','meta',it.title);sub.style.margin='0';
  const ta=el('textarea');ta.placeholder=o.voice?'Type, or hold the mic and talk':'Type what should change';ta.setAttribute('aria-label','What should change');ta.value=dr.text;
  const voice=el('div','swipe-voice'),mic=btn('swipe-mic',[ic('mic',18),el('span','','Hold or tap to talk')]),wave=el('div','swipe-wave');for(let i=0;i<18;i++){const b=el('i');b.style.animationDelay=(i%6)*0.09+'s';wave.append(b)}
  if(o.voice)voice.append(mic,wave);const clips=el('div','swipe-clips');
  const drawClips=()=>{clips.replaceChildren();dr.clips.forEach((cl,i)=>{const c=el('div','swipe-clip');const rm=btn('btn ghost icon xs',[ic('x',12)],'Remove this recording');rm.onclick=()=>{dr.clips.splice(i,1);drawClips();sync()};
   c.append(ic('play',14),el('span','','0:'+String(cl.secs).padStart(2,'0')),el('q','',cl.text),rm);clips.append(c)})};
  let t0=0,toggled=false;const rec=()=>mic.classList.contains('rec');
  const start=()=>{if(rec())return;mic.classList.add('rec');mic.lastChild.textContent='Listening… tap or let go to stop';t0=Date.now()};
  const stop=()=>{if(!rec())return;mic.classList.remove('rec');mic.lastChild.textContent='Hold or tap to talk';dr.clips.push({secs:Math.max(1,Math.round((Date.now()-t0)/1000)),text:o.transcript||'Make the button bigger and put it above the fold.'});drawClips();sync()};
  mic.addEventListener('pointerdown',e=>{e.preventDefault();if(rec()){toggled=false;stop();return}start();toggled=false});
  mic.addEventListener('pointerup',()=>{if(!rec())return;if(Date.now()-t0<350){toggled=true;return}/* a quick tap keeps listening */stop()});
  mic.addEventListener('keydown',e=>{if(e.key===' '||e.key==='Enter'){e.preventDefault();rec()?stop():start()}});
  /* subject (options only) */
  let about=null;const hint=el('p','meta');hint.style.margin='0';
  if(isOpt(it)){about=el('div','segmented');about.setAttribute('role','group');about.setAttribute('aria-label','About');
   about.append(el('span','meta about-label','About'));[...(it.preview.options||[]).map(x=>[x.id,x.id]),['all','All']].forEach(([v,l])=>{const b=btn('btn sm',[l],v==='all'?'About all options':'About option '+v);b.dataset.v=v;b.onclick=()=>setAbout(v);about.append(b)})}
  const foot=el('div','swipe-sheet-foot'),cancel=btn('btn',['Cancel']),back=btn('btn',['Send back for changes']),use=btn('btn primary',['']);
  const setAbout=v=>{about.v=v;about.querySelectorAll('button').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.v===v)));sync()};
  const sync=()=>{const has=!!ta.value.trim()||(o.voice&&dr.clips.length);dr.text=ta.value;back.disabled=use.disabled=!has;
   const opt=about&&about.v!=='all'?about.v:null;use.hidden=!opt;if(opt)use.textContent='Use '+opt+' with these changes';
   back.className=opt?'btn':'btn primary';
   hint.textContent=opt?('“Send back” asks for new versions. “Use '+opt+'” builds '+opt+' with your changes.'):'The helper gets your words and makes a new version. Nothing is approved.'};
  ta.addEventListener('input',sync);
  const close=()=>{closeOverlay();reset(cur)};cancel.onclick=close;
  const leave=(verdict,note)=>{closeOverlay();const c=cur;busy=true;c.classList.add('leaving');
   setTimeout(()=>{busy=false;delete drafts[it.id];commit(verdict,note)},220)};
  const words=()=>({text:ta.value.trim(),clips:o.voice?dr.clips.slice():[],pins:(pins[it.id]||[]).slice()});
  back.onclick=()=>leave('talk',{changes:words(),about:about?about.v:null});
  use.onclick=()=>{picked[it.id]=about.v;leave('ok',{picked:about.v,changes:words()})};
  foot.append(cancel,back,use);
  /* pull the handle down to close (the words stay) */
  grab.addEventListener('pointerdown',e=>{const y0=e.clientY;grab.setPointerCapture(e.pointerId);const mv=ev=>{sh.style.transform=`translateY(${Math.max(0,ev.clientY-y0)}px)`};
   grab.addEventListener('pointermove',mv);grab.addEventListener('pointerup',ev=>{grab.removeEventListener('pointermove',mv);if(ev.clientY-y0>80)close();else sh.style.transform=''},{once:true})});
  sh.append(grab,ttl,sub);if(about)sh.append(about);sh.append(hint);if(o.voice)sh.append(voice,clips);sh.append(ta,foot);scr.append(sh);
  scr.addEventListener('pointerdown',e=>{if(e.target===scr)close()});
  if(about)setAbout(picked[it.id]||'all');drawClips();sync();openOverlay(scr,o.state?null:ta);return {mic,start,stop,ta,send:back,use,setAbout,sync}};
 /* Viewer: bigger, zoom, Open, and spots (tap “Spot”, tap the place, say or type what to change; the spot remembers
    which option or side it is on). */
 const openViewer=side=>{const it=items[idx];if(!it)return null;side=side==='before'||side==='after'?side:null;const v=el('div','swipe-viewer');v.setAttribute('role','dialog');v.setAttribute('aria-label',it.title);
  const barEl=el('div','swipe-viewer-bar'),close=btn('btn ghost icon sm',[ic('x',18)],'Close');close.onclick=()=>{closeOverlay();render()};
  let z=1;const zo=btn('btn icon sm',[ic('minus',16)],'Zoom out'),zi=btn('btn icon sm',[ic('plus',16)],'Zoom in');
  const pinBtn=btn('btn sm',[ic('pin',16),mode==='phone'?'Spot':'Mark a spot'],'Mark a spot and say what to change');pinBtn.setAttribute('aria-pressed','false');
  barEl.append(close,el('strong','',it.title),zo,zi,pinBtn);
  if(it.open){const a=el('a','btn sm'+(mode==='phone'?' icon':''));a.href=it.open;a.target='_blank';a.rel='noopener';a.setAttribute('aria-label','Open');a.append(ic('external',16));if(mode!=='phone')a.append('Open');barEl.append(a)}
  const body=el('div','swipe-viewer-body'),zm=el('div','swipe-zoomed');zm.append(buildPreview(it,true));body.append(zm);
  const setZ=n=>{z=Math.max(1,Math.min(4,n));zm.style.transform=`scale(${z})`;zm.style.width=`calc(${100/z}% - 32px)`};zo.onclick=()=>setZ(z-.5);zi.onclick=()=>setZ(z+.5);
  body.addEventListener('wheel',e=>{if(e.ctrlKey){e.preventDefault();setZ(z-e.deltaY*.01)}},{passive:false});
  const pts=new Map();let d0=0,z0=1;body.addEventListener('pointerdown',e=>{pts.set(e.pointerId,[e.clientX,e.clientY]);if(pts.size===2){const [a,b]=[...pts.values()];d0=Math.hypot(a[0]-b[0],a[1]-b[1]);z0=z}});
  body.addEventListener('pointermove',e=>{if(!pts.has(e.pointerId))return;pts.set(e.pointerId,[e.clientX,e.clientY]);if(pts.size===2&&d0){const [a,b]=[...pts.values()];setZ(z0*Math.hypot(a[0]-b[0],a[1]-b[1])/d0)}});
  ['pointerup','pointercancel'].forEach(t=>body.addEventListener(t,e=>{pts.delete(e.pointerId);if(pts.size<2)d0=0}));
  const foot=el('div','swipe-viewer-foot'),list=el('div','swipe-pin-list'),hint=el('div','row');
  const drawList=()=>{list.replaceChildren();(pins[it.id]||[]).forEach((pn,i)=>{const r=el('div','swipe-pin-note');const rm=btn('btn ghost icon xs',[ic('x',12)],'Remove spot '+(i+1));rm.onclick=()=>{pins[it.id].splice(i,1);zm.querySelectorAll('.swipe-pin').forEach(p=>p.remove());pins[it.id].forEach((p,j)=>zm.append(pinEl(p,j)));drawList()};
    r.append(el('b','',String(i+1)),el('span','',(pn.on?'On '+pn.on+': ':'')+pn.text),rm);list.append(r)});
   hint.replaceChildren(ic('pin',14),el('span','',(pins[it.id]||[]).length?'Your spots go with your answer. Close, then answer.':'Tap “'+(mode==='phone'?'Spot':'Mark a spot')+'”, then tap the place you mean.'))};
  const pinning=on=>{pinBtn.setAttribute('aria-pressed',String(on));body.classList.toggle('pinning',on)};pinBtn.onclick=()=>pinning(pinBtn.getAttribute('aria-pressed')!=='true');
  zm.addEventListener('click',e=>{if(!body.classList.contains('pinning')||e.target.closest('.swipe-pin-pop'))return;e.preventDefault();e.stopPropagation();const r=zm.getBoundingClientRect(),x=(e.clientX-r.left)/r.width*100,y=(e.clientY-r.top)/r.height*100;
   const tgt=e.target.closest&&e.target.closest('[data-on]');askPin(x,y,'',tgt?tgt.dataset.on:'')},true);
  const askPin=(x,y,text,on)=>{zm.querySelector('.swipe-pin-pop')?.remove();zm.querySelector('.swipe-pin.tmp')?.remove();const pop=el('div','swipe-pin-pop');pop.style.left=`min(${x}%, calc(100% - 268px))`;pop.style.top=`calc(${y}% + 8px)`;
   const inp=el('input');inp.placeholder='What should change here?';inp.setAttribute('aria-label','What should change at this spot');if(text)inp.value=text;
   const row=el('div','row'),m=btn('btn sm',[ic('mic',14),'Talk']);m.onclick=()=>{inp.value=o.transcript||'Make this bigger.'};const add=btn('btn primary sm',['Add']),no=btn('btn ghost sm',['Cancel']);
   const tmp=pinEl({x,y,text:''},(pins[it.id]||[]).length);tmp.classList.add('tmp');zm.append(tmp);
   add.onclick=()=>{if(!inp.value.trim())return;(pins[it.id]=pins[it.id]||[]).push({x,y,on:on||'',text:inp.value.trim()});pop.remove();tmp.classList.remove('tmp');tmp.title=inp.value.trim();pinning(false);drawList()};
   no.onclick=()=>{pop.remove();tmp.remove()};inp.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();add.click()}});
   if(o.voice)row.append(m);row.append(el('span','grow'),no,add);pop.append(inp,row);zm.append(pop);if(!o.state)inp.focus();return pop};
  (pins[it.id]||[]).forEach((pn,i)=>zm.append(pinEl(pn,i)));
  foot.append(hint,list);drawList();v.append(barEl,body,foot);openOverlay(v,close);const cw=zm.querySelector('.swipe-compare');if(side&&cw)cw.view(side);return {askPin,pinning,setZ,compare:zm.querySelector('.swipe-compare')}};
 /* keys: only when the deck itself or the card has focus (a focused button keeps its own Space / Enter) */
 host.addEventListener('keydown',e=>{if(e.key==='Tab')return;const t=e.target;
  if(overlay){if(e.key==='Escape'){e.preventDefault();const wasViewer=overlay.classList.contains('swipe-viewer');closeOverlay();wasViewer?render():reset(cur);return}
   if((e.key==='b'||e.key==='B')&&!t.closest('input,textarea')){const w=overlay.querySelector('.swipe-compare');if(w){e.preventDefault();w.cycle()}}return}
  if(e.repeat)return;if(t!==host&&t.closest('button,a,input,textarea,select'))return;
  const k=e.key;if(k==='ArrowRight'){e.preventDefault();fly('ok')}else if(k==='ArrowLeft'){e.preventDefault();fly('no')}else if(k==='ArrowDown'){e.preventDefault();fly('talk')}else if(k==='ArrowUp'){e.preventDefault();fly('later')}
  else if(k===' '){e.preventDefault();cur&&hasPreview(items[idx])&&openViewer()}else if(k==='z'||k==='Z'){e.preventDefault();undo()}else if(k==='o'||k==='O'){e.preventDefault();openOverview()}
  else if((k==='b'||k==='B')&&cur){const w=cur.querySelector('.swipe-compare');if(w){e.preventDefault();w.cycle()}}});
 if(!o.start&&items[idx]&&ans[items[idx].id]){const w=waiting();idx=w.find(i=>!later.has(items[i].id))??w[0]??items.length}
 render();ready=true;Promise.resolve().then(()=>o.onChange&&o.onChange());
 return {jump,openOverview,answers:ans,items,fly,undo,pick:id=>pick(items[idx],id),openComment,openViewer,show:(dx,dy)=>cur&&show(cur,dx,dy),pins,later,get busy(){return !!overlay||busy},get index(){return idx}}};
})();
