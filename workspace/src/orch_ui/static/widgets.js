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
/* A terminal command to copy (ORCH-218): the exact step a person runs when orch cannot do it (a tool's sign-in such as
   'az login'). UI.commandCopy(command, o) -> <div class="cmd-copy"> with an optional lead line (o.lead), the command as
   <code> and one Copy button (UI.copyText; falls back to selecting the text). o.dataKey keys the box; o.scroll gives a command that scrolls sideways a Tab stop. Text only. */
UI.commandCopy=(command,o)=>{o=o||{};command=String(command||'');const box=el('div','cmd-copy');if(o.dataKey)box.dataset.key=o.dataKey;
 if(o.lead)box.append(el('p','meta',o.lead));const row=el('div','cmd-copy-row');const code=el('code','cmd-copy-text',command);if(o.scroll)code.tabIndex=0;/* a command that scrolls sideways is reachable by keyboard (ORCH-1360) */
 const b=el('button','btn outline sm','Copy');b.type='button';b.setAttribute('aria-label','Copy '+command);if(o.dataKey)b.dataset.key=o.dataKey+'-copy';
 b.onclick=async()=>{const ok=UI.copyText?await UI.copyText(command):false;if(ok){b.textContent='Copied';if(UI.toast)UI.toast('Copied');setTimeout(()=>{b.textContent='Copy'},2000)}
  else{const r=document.createRange&&document.createRange();const sel=window.getSelection&&window.getSelection();if(r&&sel){r.selectNodeContents(code);sel.removeAllRanges();sel.addRange(r)}if(UI.toast)UI.toast('Could not copy. The command is selected: press Ctrl+C (Cmd+C on a Mac).',null,'error')}};
 row.append(code,b);box.append(row);return box};
/* Run it now card (ORCH-848, owner picked draft A, 19 Nov): the question's own command, run with one click.
   UI.runCard(item, o) -> <div class="run-card" data-state="...">. item: a run card, {no_label, run:{command, cwd, class:'orch'|'other'|'login',
   changes, undo}} (a review row's mapped item has noLabel and the same run). The question stays the title: the host draws it.
   o: {run({confirmed}) -> Promise<{ok, exit, output, error}>, no({}) -> Promise, primary (the filled Run it now: Review),
       phone (a phone screen) and phoneRun (the phone may run it), last {at, by, exit, output, error} (a failed try shown again),
       onDone(result) (it ran), onNo() (the other answer was saved), now (Date, tests),
       terminal (a sign-in whose Run it now opens the Focus terminal, ORCH-865), underway {at} (its sign-in is under way there),
       show(terminalId) (Show sign-in: opens that session), typing {on() -> bool, set() -> Promise<{ok, error}>, watch(fn, cardElement)}
       (a sign-in's terminal: "Turn on typing to sign in here" with a switch while the person cannot type there yet;
       only the person's click turns it on)}.
   States (data-state): waiting, confirm (a command that is not orch's own: one way out, Cancel), running, done, failed,
   left, login (copy only: orch cannot sign in for you), terminal (the sign-in runs in the Focus terminal; the card answers itself once
   it ended and its login check is green), copy (copy only: run it in your own terminal), phone (copy only). Text only (textContent), never innerHTML. */
UI.runCard=(item,o)=>{o=o||{};item=item||{};const r=item.run||{},cmd=String(r.command||''),cwd=String(r.cwd||''),cls=r.class==='other'||r.class==='login'||r.class==='copy'?r.class:'orch',
 noLabel=String(item.no_label||item.noLabel||'Leave it off for now'),okLabel=String(item.ok_label||item.okLabel||'I ran it'),
 inTerm=cls==='login'&&!!o.terminal,copyOnly=(cls==='login'&&!inTerm)||cls==='copy',phoneOnly=!!o.phone&&!o.phoneRun&&!copyOnly,root=el('div','run-card');
 let st=copyOnly?cls:phoneOnly?'phone':inTerm&&o.underway?'terminal':'waiting',res=null,at=null,pending=false,termId=o.underway&&o.underway.terminal||'',typingBusy=false;
 const typingOn=()=>{try{return !!(o.typing&&o.typing.on())}catch(e){return false}};
 if(o.typing&&typeof o.typing.watch==='function')o.typing.watch(()=>{if(!typingBusy)draw()},root);
 const hm=d=>{d=d||(o.now?new Date(o.now):new Date());return String(d.getHours()).padStart(2,'0')+':'+String(d.getMinutes()).padStart(2,'0')};
 if(o.last&&!copyOnly&&st!=='terminal'){st='failed';res={ok:false,exit:o.last.exit,output:o.last.output,error:o.last.error}}
 const lines=t=>{t=String(t==null?'':t).replace(/\s+$/,'');return t?t.split('\n').slice(0,200):[]};
 const btn=(c,label,on)=>{const b=el('button','btn '+c,label);b.type='button';if(on)b.onclick=on;return b};
 const copyOf=(command,c)=>{const b=btn(c||'outline sm','Copy');b.setAttribute('aria-label','Copy '+command);
  b.onclick=async()=>{const ok=UI.copyText?await UI.copyText(command):false;if(ok){b.textContent='Copied';if(UI.toast)UI.toast('Copied');setTimeout(()=>{b.textContent='Copy'},2000)}else if(UI.toast)UI.toast('Could not copy. Select the command and copy it by hand.',null,'error')};return b};
 const fact=(dl,name,text,command)=>{const row=el('div','run-fact'),dd=el('dd');row.append(el('dt','',name));if(command)dd.append(el('code','run-code',command),copyOf(command,'ghost sm'));else dd.textContent=text;row.append(dd);dl.append(row)};
 const setSt=(s,focus)=>{st=s;draw();if(focus){const f=root.querySelector&&root.querySelector(focus);if(f&&f.focus)f.focus()}};
 const hadFocus=()=>typeof document.activeElement!=='undefined'&&!!document.activeElement&&root.contains&&root.contains(document.activeElement);
 const run=confirmed=>{if(st==='running'||pending)return;const back=hadFocus();
  if(cls==='other'&&!confirmed){return setSt('confirm',back?'[data-act="cancel"]':null)}
  setSt('running');let p;try{p=Promise.resolve(o.run?o.run({confirmed:!!confirmed}):{ok:false,error:'This page cannot run it.'})}catch(e){p=Promise.reject(e)}
  p.then(x=>{res=x&&typeof x==='object'?x:{ok:false};if(res.ok&&inTerm){termId=String(res.terminal||'');setSt('terminal',back?'[data-act="show"]':null)}else if(res.ok){at=hm();setSt('done');if(o.onDone)o.onDone(res)}else setSt('failed',back?'[data-act="run"]':null)},()=>{res={ok:false,error:'Could not reach orch.'};setSt('failed',back?'[data-act="run"]':null)})};
 const leave=()=>{if(st==='running'||pending)return;pending=true;draw();let p;try{p=Promise.resolve(o.no?o.no({}):{ok:true})}catch(e){p=Promise.reject(e)}
  p.then(x=>{pending=false;if(x&&x.ok===false){draw();if(UI.toast)UI.toast((x.error&&x.error.message)||x.error||x.text||'Could not save your answer.',null,'error');return}at=hm();setSt('left');if(o.onNo)o.onNo()},()=>{pending=false;draw();if(UI.toast)UI.toast('Could not reach orch.',null,'error')})};
 const term=()=>{const t=el('div','term run-out'),h=el('div','term-h'),b=el('div','term-b');h.append(el('span','','In '+cwd));
  const right=el('span','run-right');if(st==='running'){right.setAttribute('role','status');right.append(el('span','spinner'),el('span','','Running'))}else right.textContent=st==='done'?'Exit '+(res&&res.exit!=null?res.exit:0):'It did not work';h.append(right);
  b.append(el('div','c','$ '+cmd));
  if(st==='done'){const l=lines(res&&res.output);if(l.length)l.forEach(x=>b.append(el('div','ok',x)));else b.append(el('div','','(it printed nothing)'))}
  if(st==='failed')lines(res&&res.output).forEach(x=>b.append(el('div','run-err',x)));
  t.append(h,b);return t};
 function draw(){root.dataset.state=st;const body=[],busy=st==='running'||pending,box=UI.commandCopy(cmd,{scroll:true}),row=box.lastChild;
  const word=st==='failed'?'Run it again':'Run it now',runBtn=()=>{const b=btn((o.primary?'primary':'outline')+' sm','',()=>run(false));b.dataset.act='run';
   if(st==='running'){b.disabled=true;b.setAttribute('aria-busy','true');b.append(el('span','spinner'),el('span','',inTerm?'Opening…':'Running…'))}else{b.textContent=word;if(pending)b.disabled=true}return b};
  if(st==='done'){const p=el('span','pill done');p.append(UI.statusIcon?UI.statusIcon('done'):'',el('span','',okLabel));row.append(p)}

  else if(st==='waiting'||st==='failed'||st==='running')row.append(runBtn());
  body.push(box);
  if(st==='waiting')body.push(el('p','meta run-where',inTerm?'Opens the terminal in Focus and starts the sign-in there, in '+cwd:'Runs in '+cwd));
  if(st==='terminal'){const s=el('p','run-help','Finish the sign-in on the right: press Enter and follow the steps. This card closes by itself when you are done.');s.setAttribute('role','status');
   const d=el('div','run-row'),b=btn('outline sm','Show sign-in',()=>{if(o.show)o.show(termId)});b.dataset.act='show';if(!o.show)b.disabled=true;d.append(b);body.push(s,d)}
  if(inTerm&&(st==='waiting'||st==='terminal')&&o.typing&&!typingOn()){const d=el('div','run-row run-typing'),sw=el('button','switch');sw.type='button';sw.setAttribute('role','switch');
   sw.setAttribute('aria-checked','false');sw.setAttribute('aria-label','Turn on typing to sign in here');sw.dataset.act='typing';if(typingBusy){sw.disabled=true;sw.setAttribute('aria-busy','true')}
   sw.onclick=()=>{if(typingBusy)return;typingBusy=true;draw();let p;try{p=Promise.resolve(o.typing.set())}catch(e){p=Promise.reject(e)}
    p.then(x=>{typingBusy=false;draw();if(x&&x.ok===false&&UI.toast)UI.toast(String((x.error&&x.error.message)||x.error||'Typing did not turn on.'),null,'error')},()=>{typingBusy=false;draw();if(UI.toast)UI.toast('Could not reach orch.',null,'error')})};
   d.append(sw,el('span','','Turn on typing to sign in here'));body.push(d)}
  if(st==='phone')body.push(el('p','run-help','The phone runs only orch’s own commands. Run this one at your computer.'));
  if(st==='login')body.push(el('p','run-help','This is a sign-in: run it in your terminal.'));
  if(st==='copy')body.push(el('p','meta run-unchecked','orch did not check this command. Read it before you run it in your terminal.'));
  if(st==='confirm'){const k=el('div','banner attn run-confirm'),g=el('div','grow'),p=el('p','','It runs exactly this, in '+cwd+': '),code=el('code','run-code',cmd);p.append(code);
   g.append(el('strong','','This is not an orch command'),p);const a=el('div','run-row'),c=btn('outline sm','Cancel',()=>setSt('waiting','[data-act="run"]')),g2=btn('primary sm','Run it now',()=>run(true));c.dataset.act='cancel';g2.dataset.act='confirmed';a.append(c,g2);k.append(g,a);body.push(k)}
  if((st==='running'&&!inTerm)||st==='done'||st==='failed')body.push(term());
  if(st==='done'){const l=el('p','meta run-result');l.append(el('strong','',okLabel),' · You ran it at '+at);body.push(l)}
  if(st==='failed'){const e=el('p','run-help run-error',String((res&&res.error)||'It did not work.'));e.setAttribute('role','alert');body.push(e);}
  if(st==='left'){const d=el('div','run-row'),p=el('span','pill done');p.append(UI.statusIcon?UI.statusIcon('done'):'',el('span','',noLabel));d.append(p,el('span','meta','You answered at '+at));body.push(d)}
  if(cls!=='copy'&&!inTerm&&(r.changes||r.undo)){const dl=el('dl','run-facts');if(r.changes)fact(dl,'Changes',r.changes);if(r.undo)fact(dl,'Undo',null,r.undo);body.push(dl)}
  if(st!=='done'&&st!=='left'&&st!=='confirm'){const n=btn('outline sm run-leave',noLabel,leave);n.dataset.act='no';if(busy)n.disabled=true;body.push(n)}
  root.replaceChildren(...body)}
 draw();return root};
/* Helpers list (ORCH-61): one row per live helper, the same on dashboard Home and in Focus. The state comes from the core
   (orch run status "helper": working | starting | you | waiting | idle | stuck | limit); the page never words it itself.
   UI.helperPill(state, word) -> the worded pill; UI.helperSummary(rows) -> "4 working · 1 needs you · 1 idle";
   UI.helperList(rows, o) -> <section class="card helper-list"> with rows {key, title, href, state, word, meta, actions:[{label, run, key}]},
   o.title (default "Helpers"), o.empty (shown when there are no rows), o.dataKey. */
const HELPER_LOOK={working:['working','working'],starting:['working','working'],you:['needs','needs'],waiting:['','check'],idle:['','todo'],stuck:['failed','needs'],limit:['','check']};
UI.helperPill=(state,word)=>{const [cls,icon]=HELPER_LOOK[state]||['','todo'];const p=el('span','pill helper-pill'+(cls?' '+cls:''));p.dataset.state=state||'';p.append(UI.statusIcon(icon),document.createTextNode(word||''));return p};
const HELPER_COUNT=[['working','working'],['starting','starting'],['you','needs you','need you'],['waiting','on hold'],['idle','idle'],['stuck','stuck'],['limit','stopped on the usage limit']];
UI.helperSummary=rows=>{const n={};(rows||[]).forEach(r=>{n[r.state]=(n[r.state]||0)+1});return HELPER_COUNT.filter(([k])=>n[k]).map(([k,one,many])=>n[k]+' '+(n[k]>1&&many?many:one)).join(' · ')};
/* The meta line under a helper's title, the same words everywhere: "Step 3 of 4 · 52 min", "Since 3 h · your answer",
   "Nothing running for 18 min". row: {state, detail, step:{n,of}, minutes, idle, finished} (minutes: since start, idle: quiet). */
const helperSpan=m=>m==null?'':m<1?'just now':m<60?m+' min':m<1440?Math.round(m/60)+' h':(d=>d+(d===1?' day':' days'))(Math.round(m/1440));
UI.helperMeta=r=>{r=r||{};const d=r.detail||'';
 if(r.finished&&(r.state==='idle'||r.state==='stuck'))return 'Finished · '+(d||'session still open');
 if(r.state==='you')return [r.idle!=null?'Since '+helperSpan(r.idle):'',d.toLowerCase()].filter(Boolean).join(' · ');
 if(r.state==='waiting'||r.state==='idle'||r.state==='stuck'||r.state==='limit')return d;
 return [r.step?'Step '+r.step.n+' of '+r.step.of:'',helperSpan(r.minutes),d].filter(Boolean).join(' · ')};
/* The ticket's one state (ORCH-71): the ticket page strip and Focus show the same pill and word for the same ticket.
   t: {status, questions, bring_back, waiting_on}; helper: the core's helper state {state, word, detail} while a helper runs, else null.
   UI.ticketState(t, helper) -> {pill, word, helper}; pill is a status icon name (todo, working, needs, check, done).
   UI.ticketPill(s) -> the pill for that state: the helper pill while a helper runs, else the status pill. */
/* active with no helper is In progress: Working is said only while a helper runs, so the pill never contradicts
   the ticket's "No helper is working" line (ORCH-415) */
const TICKET_WORD={open:'Backlog',ready:'To do',active:'In progress',waiting:'Needs you',review:'Check',done:'Done',dropped:"Won't do"};
const HELPER_WORD={working:'Working',starting:'Starting',you:'Needs you',waiting:'On hold',idle:'Idle',stuck:'Stuck',limit:'Stopped: usage limit'};
const HELPER_PILL={working:'working',starting:'working',you:'needs',waiting:'check',idle:'todo',stuck:'needs',limit:'check'};
UI.ticketState=(t,helper)=>{t=t||{};
 if(t.status==='done')return {pill:'done',word:'Done',helper:null};
 if((t.questions||[]).some(q=>q&&q.answer==null))return {pill:'needs',word:'Needs you',helper:null};
 if(t.status==='review')return {pill:'check',word:'Check',helper:null};
 if(t.bring_back&&t.bring_back.state==='waiting')return {pill:'needs',word:'Needs you',helper:null};
 // a wait for a date, another ticket or the outside (no open question) is Waiting, as the board's lane says (ORCH-235)
 if(t.status==='waiting'&&!(t.waiting_on&&t.waiting_on.kind==='question'))return {pill:'todo',word:'Waiting',helper:null};
 if(helper&&HELPER_WORD[helper.state])return helper.state==='working'?{pill:'working',word:'Working',helper:null}:{pill:HELPER_PILL[helper.state],word:HELPER_WORD[helper.state],helper};
 if(helper)return {pill:'working',word:'Working',helper:null};
 return {pill:'todo',word:TICKET_WORD[t.status]||'To do',helper:null}};
UI.ticketPill=s=>{s=s||{};if(s.helper)return UI.helperPill(s.helper.state,s.word);const p=el('span','pill'+(['working','needs','done'].includes(s.pill)?' '+s.pill:''));p.dataset.state=s.pill||'';p.append(UI.statusIcon(s.pill),document.createTextNode(s.word||''));return p};
UI.helperList=(rows,o)=>{o=o||{};rows=rows||[];const box=el('section','card helper-list');if(o.dataKey)box.dataset.key=o.dataKey;
 const head=el('header','card-h');head.append(el('h2','',o.title||'Helpers'));/* ORCH-1616: no need-you count in the head (the number lives on the Review badge); each row still says Needs you */const sum=UI.helperSummary((rows||[]).filter(r=>r.state!=='you'));if(sum)head.append(el('span','meta helper-sum',sum));box.append(head);
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
 else{n.setAttribute('aria-expanded',String(!!it.expanded));if(it.current)n.dataset.current='page';else delete n.dataset.current}};
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
/* Launch (ORCH-1037): the short "starting" moment between pressing Start in a form and landing on what it made.
   UI.launch({title, sub, steps:['Creating the ticket','Starting your helper','Opening it']}) -> {el, step(i), warn(i, text), finish(title), fail()}.
   step(i) marks the steps before i done and step i working; warn(i, text) marks step i as needing you, with new words; finish() marks all done and fades the box out. role=status, so a
   screen reader hears each step. Text only (textContent). Reduced motion: no spin, no fade (motion.css). */
UI.launch=o=>{o=o||{};const box=el('div','launch');box.setAttribute('role','status');box.setAttribute('aria-live','polite');
 const mark=el('div','launch-mark');mark.setAttribute('aria-hidden','true');mark.append(el('span','launch-ring'),el('span','launch-core'));
 const title=el('h2','launch-title',o.title||'Starting');box.append(mark,title);if(o.sub)box.append(el('p','launch-sub meta',o.sub));
 const list=el('ol','launch-steps'),rows=(o.steps||[]).map(t=>{const li=el('li');li.dataset.state='todo';li.append(UI.statusIcon('todo'),el('span','',t));list.append(li);return li});
 if(rows.length)box.append(list);
 const mark_=(li,st)=>{if(li.dataset.state===st||li.dataset.state==='needs')return;li.dataset.state=st;li.firstChild.replaceWith(UI.statusIcon(st==='active'?'working':st))};
 const api={el:box,step(i){rows.forEach((li,n)=>mark_(li,n<i?'done':n===i?'active':'todo'))},
  warn(i,t){const li=rows[i];if(!li)return;mark_(li,'needs');if(t)li.lastChild.textContent=t},
  finish(t){rows.forEach(li=>mark_(li,'done'));box.dataset.done='true';if(t)title.textContent=t;box.classList.add('launch-out')},
  fail(){box.remove()}};
 api.step(0);return api};
/* Stat tile: UI.stat('Done this week', '12', {delta:'+3 vs last week', dir:'up'}) */
UI.stat=(label,value,o)=>{o=o||{};const t=el('div','stat-tile');t.append(el('span','stat-label',label),el('span','stat-value',String(value)));if(o.delta)t.append(el('span','stat-delta'+(o.dir?' '+o.dir:''),o.delta));return t};
/* 7-day line: UI.spark([3,5,4,0,2,6,4], {label:'Last 7 days: …', tone:1..7}); an svg with one line, highest value at the top */
UI.spark=(values,o)=>{o=o||{};const NS='http://www.w3.org/2000/svg',w=72,h=24,v=(values||[]).map(n=>Math.max(0,Number(n)||0)),max=Math.max(1,...v),last=Math.max(1,v.length-1);const svg=document.createElementNS(NS,'svg');svg.setAttribute('viewBox','0 0 '+w+' '+h);svg.setAttribute('class','spark');svg.setAttribute('preserveAspectRatio','none');svg.setAttribute('role','img');svg.setAttribute('aria-label',o.label||('Last '+v.length+' days: '+v.join(', ')));if(o.tone)svg.dataset.tone=String((Number(o.tone)-1)%7+1);const line=document.createElementNS(NS,'polyline');line.setAttribute('points',v.map((n,i)=>(i*w/last).toFixed(1)+','+(h-2-n*(h-4)/max).toFixed(1)).join(' '));line.setAttribute('vector-effect','non-scaling-stroke');svg.append(line);return svg};
/* Progress with a label: UI.progress(3, 5, 'steps'[, 'Name read out', default Progress]) */
UI.progress=(value,max,unit,label)=>{const w=el('div','progress-labeled'),bar=el('div','progress');bar.setAttribute('role','progressbar');bar.setAttribute('aria-label',label||'Progress');bar.setAttribute('aria-valuetext',value+' of '+max+(unit?' '+unit:''));bar.setAttribute('aria-valuemin','0');bar.setAttribute('aria-valuemax',String(max));bar.setAttribute('aria-valuenow',String(value));const f=el('span');f.style.width=Math.max(0,Math.min(100,max?value/max*100:0))+'%';bar.append(f);const t=el('div','progress-text');t.append(el('span','',value+' of '+max+(unit?' '+unit:'')));w.append(bar,t);return w};
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
   o: {mode:'phone'|'desk', start, picked:{itemId:'C'}, voice (false: text only, no mic or clips), answered:{itemId:{verdict,note}}, later:[ids], pins:{itemId:[pin]}, quiet, transcript, onDecide(item, verdict, note), attach (UI.composer options: accept, maxFiles, maxBytes, voice; the comment sheet takes screenshots, files and a voice note, note.changes.files), onNote(item, text, files)->Promise<{ok,error?}> (adds "Add note" to the Comment sheet: words saved, card stays, no verdict), onUndo(item), onChange(),
       canUndo(item) (false once the answer is saved for good: Undo is then not offered, ORCH-183)}
   item.files: [{label, type:'img'|'page'|'file', src}] the result's own files (a Check card), as tiles that open them
   item.answers: [{label, picked}] the card's own answer buttons in place of the three (a Factory start: Not now, Change it,
       Start); all outlined, so the costly one is never the easiest click; each answers ok with that pick
   item.kind 'stuck' (ORCH-1108): work that stopped; never Looks good / Don't do / Comment, only its own buttons (Nudge,
       Start fresh, Merge) or none; item.href (a link in this page, '#ticket/<id>') is its Open button, same tab
   item.hint: one plain line in the foot saying what the card's own buttons do
   Answers are buttons and keys only, no swipe (owner 16 Nov: "we already have the arrows or buttons to click"):
   → approve (the button names the action: it.okLabel, "Use C"), ← Don't do / Send back / None of these,
   ↓ comment sheet whose buttons name the outcome ("Send back for changes" / "Use C with these changes"),
   ↑ Later (stays unanswered, goes to the end); Space bigger, B before/after, O all, Z undo. A tap on an option picks
   it, a tap on the picture opens it bigger. The answered card fades; nothing flies. Every card says what happens
   when you approve (it.then). Item extras: text (the question), group, suggest ('ok'|'no'), links [{label,url}].
   verdicts: ok | no | talk | later. note: {picked, changes:{text, clips, pins:[{n,on,x,y,text}]}, about}
   ORCH-477 (owner pick B, 18 Nov): a card is as tall as what it holds (no fixed frame); the answers sit in one bar pinned
   to the bottom of the screen with the "If you approve" line in it, so nothing hides under the bar. A result's files
   open large in the page (UI.reviewViewer, review.js), a PDF tile shows its first page (FileViewer.thumb). Compare:
   tick two cards, or two options of one choice, and they stand side by side, each with its own answers; Close goes
   back to one card. deck.tick(ref), deck.compare([ref, ref]), deck.ticked, deck.tickBox(ref, label) (the checkbox the
   "All cards" lists use), deck.optionRefs(item) ([{ref, label}] for a choice with two or more option pictures).
   A phone shows "All cards · 1 of N" with ← → above the card; the list (with its ticks) is one tap away. */
/* The words box of a card (UI.docBox(preview, headingTag)): heading, paras, numbered steps, and the little structure
   a merge card carries (ORCH-183): a status line with a tone (done | working | failed, a pill with its icon), rows
   (title, a ticket key chip, the number on the right) and a small footer. Text only via textContent. */
UI.docBox=(p,hTag)=>{p=p||{};const d=el('div','doc');const st=p.status;
 if(st&&st.text){const tone=st.tone==='failed'?'failed':st.tone==='working'?'working':'done',s=el('p','pill doc-status '+tone);s.append(UI.statusIcon(tone==='failed'?'needs':tone),el('span','',st.text));d.append(s)}
 if(p.headline)d.append(el('p','doc-headline',p.headline));
 if(p.progress&&p.progress.total>0){const g=el('div','doc-progress'),b=el('div','progress'),f=el('span');f.style.width=Math.round(p.progress.done/p.progress.total*100)+'%';b.append(f);g.append(b,el('span','meta',p.progress.done+' of '+p.progress.total+' steps done'));d.append(g)}
 if(Array.isArray(p.chips)&&p.chips.length){const r=el('div','doc-chips');const T={ok:'success',warn:'warning',bad:'danger',info:'info'};p.chips.forEach(c=>r.append(el('span','chip '+(T[c.tone]||'info'),c.text)));d.append(r)}
 if(Array.isArray(p.flow)&&p.flow.length){const r=el('div','doc-flow');p.flow.forEach((t,i)=>{if(i)r.append(el('span','doc-arrow','→'));r.append(el('span','doc-box',t))});d.append(r)}
 if(p.chart&&Array.isArray(p.chart.bars)){const max=Math.max(...p.chart.bars.map(b=>Math.abs(b.value)),1),r=el('div','doc-chart');r.setAttribute('role','img');r.setAttribute('aria-label',p.chart.bars.map(b=>b.label+' '+b.value+(p.chart.unit||'')).join(', '));
   p.chart.bars.forEach(b=>{const row=el('div','doc-bar'),t=el('div','progress'),f=el('span');f.style.width=Math.round(Math.abs(b.value)/max*100)+'%';t.append(f);row.append(el('span','',b.label),t,el('b','',b.value+(p.chart.unit||'')));r.append(row)});d.append(r)}
/* diff lines (ORCH-429): a file's name above its lines, a risky line marked red with why (l.risk) */
 if(Array.isArray(p.diff)&&p.diff.length){const r=el('div','doc-diff');let last=null;p.diff.forEach(l=>{if(l.file&&l.file!==last)r.append(el('div','doc-diff-file',l.file));last=l.file||last;
   const row=el('div','doc-line '+(l.op==='+'?'add':'del')+(l.risk?' risk':''),l.op+' '+l.text);if(l.risk)row.append(el('span','doc-risk',l.risk));r.append(row)});d.append(r)}
 if(p.heading)d.append(el(hTag||'h4','',p.heading));(p.paras||[]).forEach(x=>d.append(el('p','',x)));
 if(Array.isArray(p.rows)&&p.rows.length){const ul=el('ul','doc-rows');p.rows.forEach(r=>{if(!r||!r.title)return;const li=el('li','doc-row');li.append(el('span','doc-row-title',r.title));
   if(r.key)li.append(el('span','chip doc-row-key',r.key));if(r.n)li.append(el('span','doc-row-n','#'+r.n));ul.append(li)});d.append(ul)}
 if(p.steps){const ol=el('ol');p.steps.forEach(x=>ol.append(el('li','',x)));d.append(ol)}
 if(p.foot)d.append(el('p','doc-foot',p.foot));
 if(Array.isArray(p.details)&&p.details.length){const dt=el('div','doc-details');p.details.forEach(x=>dt.append(el('p','meta',x)));d.append(dt)}
 return d};
UI.swipeDeck=(host,items,o)=>{o=o||{};const mode=o.mode||'desk',ic=(n,z)=>{const t=document.createElement('template');t.innerHTML=window.icon?window.icon(n,z||20):'';return t.content};
 let idx=o.start||0,overlay=null,overlayBack=null,cur=null,busy=false,ticked=(o.ticked||[]).slice(0,2),pairSide=0,picking=!!o.picking,showing=false;const done=[],ans={},pins={},drafts={},later=new Set(o.later||[]),picked=Object.assign({},o.picked);
 Object.assign(pins,o.pins);Object.entries(o.answered||{}).forEach(([id,a])=>{const it=items.find(x=>x.id===id);if(it)ans[id]={verdict:a.verdict,note:a.note||null,item:it}});
 host.classList.add('swipe','swipe-'+mode);host.tabIndex=0;host.addEventListener('blur',()=>host.classList.remove('quiet-focus'));
 const focusHost=()=>{host.classList.add('quiet-focus');host.focus({preventScroll:true})};host.setAttribute('role','region');host.setAttribute('aria-label','Review, one item at a time');
 const btn=(cls,children,label)=>{const b=el('button',cls);b.type='button';children.forEach(c=>b.append(c));if(label)b.setAttribute('aria-label',label);return b};
 /* top: progress words, All, Undo */
 const top=el('div','swipe-top'),count=el('span'),bar=el('div','progress'),fill=el('span');bar.append(fill);
 const allBtn=btn('btn ghost sm swipe-all',[ic('cards',16),'All'],'All cards');allBtn.onclick=()=>openOverview();
 const undoBtn=btn('btn ghost sm',[ic('undo',16),'Undo']);undoBtn.onclick=()=>undo();
 /* Undo only while the last move can still be taken back (a Later always; an answer while o.canUndo says so) */
 const undoable=()=>{const l=done[done.length-1];return !!l&&(l.laterOnly||!o.canUndo||!!o.canUndo(l.item))};
 /* what just happened ("Later", "Looks good") shows here, next to its Undo, for a few seconds: no floating box over the
    card, the answers or the page header (ORCH-421, owner review 18 Nov) */
 const note=el('span','swipe-note');note.hidden=true;note.setAttribute('aria-hidden','true');let noteT=0;
 const say=msg=>{note.textContent=msg;note.hidden=false;clearTimeout(noteT);noteT=setTimeout(()=>{note.hidden=true},6000)};
 /* a phone: "All cards · 1 of N" and ← → above the card (the whole list with its ticks is one tap away) */
 const jumpRow=el('div','swipe-jump phone-only'),jPos=el('span','meta'),jAll=btn('btn outline swipe-jump-all',[ic('cards',16),el('span','','All cards'),jPos]),jPrev=btn('btn outline',['←'],'Previous card'),jNext=btn('btn outline',['→'],'Next card');
 jAll.onclick=()=>openOverview();jPrev.onclick=()=>step(-1);jNext.onclick=()=>step(1);jumpRow.append(jAll,jPrev,jNext);
 top.append(count,note,bar,allBtn,undoBtn,jumpRow);
 const stage=el('div','swipe-stage'),live=el('div','sr-only');live.setAttribute('aria-live','polite');
 /* bottom: the three answers + Later */
 const acts=el('div','swipe-actions');
 const mk=(cls,icon,label,key,fn)=>{const r=el('span','ring');if(icon)r.append(ic(icon,18));const l=el('span','act-label'),w=el('span','act-word',label);l.append(w);if(key)l.append(el('kbd','',key));const b=btn('swipe-act '+cls,icon?[r,l]:[l]);b.onclick=fn;return b};
 const noBtn=mk('no','x',"Don't do",'←',()=>fly('no')),talkBtn=mk('talk',o.voice?'mic':'comment','Comment','↓',()=>fly('talk')),okBtn=mk('ok','check','Looks good','→',()=>fly('ok'));
 const laterBtn=btn('btn ghost sm swipe-later',['Later']);laterBtn.append(el('kbd','','↑'));laterBtn.onclick=()=>fly('later');
 const ownRow=el('div','swipe-own');ownRow.hidden=true;
 /* the line that says what an answer does is part of the pinned bar, so the bar never hides it (ORCH-477) */
 const thenEl=el('p','swipe-then swipe-bar-then');thenEl.hidden=true;
 const laterRow=el('div','swipe-later-row swipe-acts-row'),answersEl=el('div','swipe-answers');answersEl.append(talkBtn,noBtn,okBtn,ownRow);laterRow.append(laterBtn,answersEl);acts.append(thenEl,laterRow);
 host.replaceChildren(top,stage,acts,live);
 /* words */
 const isOpt=it=>!!(it&&it.preview&&it.preview.type==='options');
 const isRun=it=>!!(it&&it.kind==='run'&&it.run&&UI.runCard);/* Run it now: the card's own buttons, never the arrow keys */
 const ownAnswers=it=>{const a=it&&Array.isArray(it.answers)?it.answers.filter(x=>x&&x.label&&x.picked):[];return a.length?a:null};
 const ownOnly=it=>!!ownAnswers(it)||!!it&&it.kind==='stuck';/* a stuck card (ORCH-1108) has no Looks good / Don't do: its own buttons, or Open alone */
 const answerOwn=a=>{if(!cur||overlay||busy)return;const c=cur;busy=true;c.classList.add('leaving');setTimeout(()=>{busy=false;commit('ok',{picked:a.picked})},120)};
 const sendsBack=it=>!!it&&(it.kind==='check'||it.noWords===true);/* its "no" is Send back, which needs words: the comment sheet, and no second Comment button */
 const noWord=it=>it.noLabel||(isOpt(it)?'None of these':it.kind==='check'?'Send back':"Don't do");
 const okWord=it=>{if(!isOpt(it))return it.okLabel||'Looks good';const p=picked[it.id];return p?'Use '+p:'Pick one'};
 const ansWord=a=>!a?'':a.verdict==='ok'&&ownAnswers(a.item)&&a.note?((ownAnswers(a.item).find(x=>x.picked===a.note.picked)||{}).label||a.note.picked):a.verdict==='ok'?(a.note&&a.note.picked?'Use '+a.note.picked+(a.note.changes?' with changes':''):(a.item.okLabel||'Looks good')):a.verdict==='no'?noWord(a.item):a.verdict==='talk'?(a.item.kind==='choice'?'Answered in your words':'Sent back for changes'):'Later';
 /* previews */
 const hasPreview=it=>{const p=it&&it.preview;if(!p||typeof p!=='object'||!p.type)return false;if(p.type==='doc')return !!(p.heading||p.headline||p.chart||p.flow||p.diff||(p.chips||[]).length||p.progress||(p.paras||[]).length||(p.steps||[]).length);return true};
 const frame=(src,title)=>{const fr=el('iframe');fr.src=src;fr.title=title;fr.setAttribute('sandbox','');fr.tabIndex=-1;fr.loading='lazy';fr.classList.add('loading');fr.addEventListener('load',()=>fr.classList.remove('loading'),{once:true});return fr};
 const buildPreview=(it,big)=>{const p=it.preview||{},f=document.createDocumentFragment();
  if(p.type==='compare'){f.append(buildCompare(it,big));return f}
  if(p.type==='options'){f.append(buildOptions(it,big));return f}
  if(p.type==='img'){const i=el('img');i.src=p.src;i.alt=p.alt||it.title;i.draggable=false;f.append(i)}
  else if(p.type==='page')f.append(el('span','preview-wait','Loading the preview…'),frame(p.src,it.title));
  else if(p.type==='table'){const t=el('table','mini-table'),h=el('tr');(p.cols||[]).forEach(c=>h.append(el('th','',c)));const th=el('thead');th.append(h);const tb=el('tbody');(p.rows||[]).slice(0,big?50:7).forEach(r=>{const tr=el('tr');r.forEach(c=>tr.append(el('td','',c)));tb.append(tr)});t.append(th,tb);f.append(t)}
  else f.append(UI.docBox(p,'h4'));
  return f};
 /* Before / after. Card: Before · After · Both. Viewer: Slide (drag the handle, or the slider keys) · Side by side · Before · After. */
 const buildCompare=(it,big)=>{const p=it.preview,w=el('div','swipe-compare');const views=big?[['slide','Slide'],['both','Side by side'],['before','Before'],['after','After']]:[['before','Before'],['after','After'],['both','Both']];
  const ctl=el('div','segmented swipe-cmp-ctl');ctl.setAttribute('role','group');ctl.setAttribute('aria-label','Before and after');
  const set=v=>{w.dataset.view=v;ctl.querySelectorAll('button').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.v===v)))};
  const pane=side=>{const d=el('div','cmp-pane '+side);d.dataset.on=side;d.dataset.type=(p[side]||{}).type||'doc';d.append(buildPreview({title:it.title+' '+side,preview:p[side]},big),el('span','cmp-tag',side==='before'?'Before':'After'));
   if(!big){const z=btn('btn icon sm cmp-zoom',[ic('expand',16)],side==='before'?'Make before bigger':'Make after bigger');z.dataset.side=side;z.addEventListener('pointerdown',e=>e.stopPropagation());z.onclick=e=>{e.stopPropagation();openViewer(side,it)};d.append(z)}return d};
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
   b.append(h);if(op.preview){const th=el('span','opt-thumb');th.dataset.type=op.preview.type||'doc';th.append(buildPreview({title:op.title,preview:op.preview},big));b.append(th)}/* no picture: no empty box */
   if(op.text)b.append(el('span','opt-text',op.text));const pk=el('span','opt-picked');pk.append(ic('check',14),'Picked');b.append(pk);
   b.onclick=e=>{e.stopPropagation();const c=b.closest('.swipe-card');if(c&&c===cur&&e.detail!==0)return;/* the card's tap handler picks on pointer taps */pick(it,picked[it.id]===op.id?null:op.id)};
   w.append(b)});
  return w};
 const pick=(it,id)=>{if(!it)return;if(id)picked[it.id]=id;else delete picked[it.id];
  host.querySelectorAll('.swipe-opt').forEach(b=>{const c=b.closest('.swipe-card,.swipe-viewer');if(c&&c.dataset.item===it.id)b.setAttribute('aria-pressed',String(b.dataset.opt===picked[it.id]))});
  host.querySelectorAll('.swipe-pair-ok').forEach(b=>{if(b.dataset.item===it.id)drawOk(b,it)});
  syncWords();live.textContent=id?'Picked '+id:'Nothing picked'};
 const sugOf=it=>it&&it.suggest&&!isOpt(it)?it.suggest:null;
 const syncWords=()=>{const it=items[idx];if(!it)return;[[okBtn,'ok'],[noBtn,'no']].forEach(([b,v])=>{b.classList.toggle('suggested',sugOf(it)===v);b.querySelector('.act-sug')?.remove();if(sugOf(it)===v)b.append(el('span','opt-sug act-sug','Suggested'))});okBtn.querySelector('.act-word').textContent=okWord(it);noBtn.querySelector('.act-word').textContent=noWord(it);
  okBtn.classList.toggle('wait',okWord(it)==='Pick one'||!!it.blocked);okBtn.setAttribute('aria-disabled',String(!!it.blocked));talkBtn.hidden=sendsBack(it);thenLine(thenEl,it);
  const own=ownAnswers(it),rn=isRun(it),only=ownOnly(it)||rn;[noBtn,okBtn].forEach(b=>{b.hidden=only});if(only)talkBtn.hidden=true;ownRow.hidden=!own;/* a run card (ORCH-848) and a stuck card (ORCH-1108) answer with their own buttons */
  ownRow.replaceChildren(...(own||[]).map(a=>{const b=mk('own',null,a.label,null,()=>answerOwn(a));b.dataset.picked=a.picked;return b}));
  const st=cur&&cur.querySelector('.swipe-stamp.right');if(st)st.textContent=okWord(it)==='Pick one'?'Pick one first':okWord(it)};
 /* card */
 const pinEl=(pn,i)=>{const p=el('span','swipe-pin');p.style.left=pn.x+'%';p.style.top=pn.y+'%';p.append(el('span','',String(i+1)));p.title=pn.text;return p};
 /* ORCH-848: a Run it now card shows UI.runCard under the question; its two buttons are the answers. o.onRun(item, {confirmed}) runs the
    command (it answers the card itself), so after "I ran it" the card only leaves; the other answer goes the usual way (hold + Undo). */
 const settle=(it,verdict,note,wait)=>setTimeout(()=>{if(items[idx]!==it||ans[it.id]||!cur)return;busy=true;cur.classList.add('leaving');setTimeout(()=>{busy=false;if(items[idx]===it&&!ans[it.id])commit(verdict,note)},120)},wait);
 const runBox=it=>{const b=el('div','swipe-run');b.addEventListener('pointerdown',e=>e.stopPropagation());
  b.append(UI.runCard(it,{primary:true,phone:mode==='phone',phoneRun:it.phoneRun,last:it.runLast,terminal:it.runTerminal&&mode!=='phone',underway:it.runLogin,
   show:o.onShowTerminal?id=>o.onShowTerminal(id):undefined,typing:it.runTerminal&&mode!=='phone'&&o.runTyping?o.runTyping(it):undefined,
   run:x=>o.onRun?o.onRun(it,x):Promise.resolve({ok:false,error:'This page cannot run it.'}),
   no:()=>{settle(it,'no',null,0);return Promise.resolve({ok:true})},onDone:()=>settle(it,'ok',{ran:true},1800)}));return b};
 /* due within a day (it.dueAt) shows amber; any other deadline stays quiet */
 const soon=it=>{const t=it&&it.dueAt!=null?+new Date(it.dueAt):NaN;return isFinite(t)&&t-Date.now()<864e5};
 const metaLine=it=>{const m=el('div','swipe-meta'),k=el('span','swipe-kind');k.append(ic(it.icon||'file',14),el('span','',it.kindLabel||it.kind||''));m.append(k);
  if(it.need)m.append(el('span','swipe-need'+(soon(it)?' soon':''),it.need));if(it.ticket)m.append(el('span','swipe-key',it.ticket));return m};
 const card=(it,layer)=>{const c=el('article','swipe-card'+(layer?' '+layer:'')+(!hasPreview(it)||plainOpts(it)?' short':''));/* no picture: as tall as its words (ORCH-421) */c.setAttribute('aria-label',it.title);c.dataset.item=it.id;if(layer){c.setAttribute('aria-hidden','true');c.inert=true}/* the cards behind are only a backdrop: no Tab stop, nothing read (ORCH-1360) */
  /* title first, then ONE quiet line: type · deadline · ticket key (ORCH-477 round 2: no routine time stamp, no group, no
     "Suggested" here; the one filled answer button is the suggestion) */
  const h=el('header','swipe-head'),m=metaLine(it);
  const t0=String(it.title||'').replace(/[\s….]+$/,''),cut=!!(it.text&&t0&&it.text.startsWith(t0));/* the title is only a cut copy of the question: show the question once, in the title's place */
  if(!cut){const t3=el('h3','',it.title);t3.title=it.title;h.append(t3,m);if(it.text&&it.text!==it.title)h.append(el('p','swipe-text',it.text))}
  else h.append(el('p','swipe-text swipe-lead',it.text),m);
  if(it.about)h.append(el('p','swipe-about','About: '+it.about));
  if(it.why)h.append(el('p','swipe-why',it.why));
  const pv=hasPreview(it)?el('div','swipe-preview'+(plainOpts(it)?' plain':'')):null;/* nothing to preview: no empty box */
  if(pv){pv.dataset.type=it.preview.type;pv.append(buildPreview(it,false));
  if(!plainOpts(it)){const ex=btn('btn icon sm swipe-expand',[ic('expand',16)],'Make bigger');ex.onclick=e=>{e.stopPropagation();openViewer(null,it)};pv.append(ex)}
  (pins[it.id]||[]).forEach((pn,i)=>pv.append(pinEl(pn,i)));}
  const fl=filesRow(it);
  const rb=isRun(it)&&!layer?runBox(it):null;
  const ft=el('footer','swipe-foot');/* "If you approve" is in the pinned answers bar (ORCH-477); why Looks good is off stays on the card (ORCH-548) */
  if(it.blocked){const t=el('span','swipe-then');t.append(el('b','','Looks good is off: '),it.blocked);ft.append(t)}
  else if(it.hint)ft.append(el('span','swipe-then',it.hint));/* what the card's own buttons do (a stuck card) */
  const row=el('div','swipe-foot-row');
  row.append(el('span','grow'));const pc=(pins[it.id]||[]).length;if(pc){const s=el('span','swipe-pins');s.append(ic('pin',14),pc+(pc===1?' spot marked':' spots marked'));row.append(s)}
  (it.links||[]).forEach(l=>{const a=el('a','btn ghost sm swipe-link');a.href=l.url;a.target='_blank';a.rel='noopener';a.append(ic('link',14),l.label);a.addEventListener('pointerdown',e=>e.stopPropagation());row.append(a)});/* the helper's links: a mockup, a reference */
  if(it.open){const a=el('a','btn ghost sm');a.href=it.open;a.target='_blank';a.rel='noopener';a.append(ic('external',14),'Open');a.addEventListener('pointerdown',e=>e.stopPropagation());row.append(a)}
  if(it.href&&!it.open){const a=el('a','btn outline sm swipe-here');a.href=it.href;a.append(ic('ticket',14),'Open');a.addEventListener('pointerdown',e=>e.stopPropagation());row.append(a)}/* a page of this site (the ticket): same tab */
  ft.append(row);if(row.children.length<2&&!it.blocked&&!it.hint)ft.classList.add('empty');/* nothing in it: no empty strip under a short card */
  c.append(...[h,pv,rb,fl,ft].filter(Boolean));return c};
 /* The result's own files (a picture, a page, a PDF): tiles that open the file large inside the page, ← → to the card's
    other files, with "Open in new tab" in the viewer (UI.reviewViewer, ORCH-477). A PDF tile shows its first page through
    the browser's own PDF view, small and without its toolbar (FileViewer.thumb); without a PDF view the icon stays. */
 const openFile=(fs,i,it,opener)=>{const f=fs[i];if(!f)return;
  if(UI.reviewViewer)return UI.reviewViewer(fs.map(x=>({label:x.label,src:x.src,open:x.src,preview:{type:x.type==='img'||x.type==='page'||x.type==='pdf'?x.type:'file'}})),i,{title:it.title,opener});
  if(typeof window.open==='function')window.open(f.src,'_blank','noopener')};
 /* a tile with no picture is never an empty box (ORCH-1686): the icon and the file's type (PDF) under the
    small picture, which covers them once the browser draws it */
 const fileFace=(th,f)=>{const m=/\.([a-z0-9]{1,8})$/i.exec(f.label||'')||/\.([a-z0-9]{1,8})(?:[?#&]|$)/i.exec(f.src||'');th.append(el('span','swipe-file-ext',m?m[1].toUpperCase():'File'))};
 const filesRow=it=>{const fs=(Array.isArray(it.files)?it.files:[]).filter(f=>f&&f.src&&f.label);if(!fs.length)return null;
  const r=el('div','swipe-files');r.setAttribute('role','list');r.setAttribute('aria-label','Files');
  const one=f=>{const a=btn('swipe-file'+(f.type==='pdf'?' pdf':''),[]);a.dataset.src=f.src;a.setAttribute('role','listitem');a.setAttribute('aria-label','Open '+f.label+' large');a.addEventListener('pointerdown',e=>e.stopPropagation());a.onclick=e=>{e.stopPropagation();openFile(fs,fs.indexOf(f),it,a)};
   const th=el('span','swipe-file-thumb');if(f.type==='img'){const i=el('img');i.src=f.src;i.alt='';i.draggable=false;i.loading='lazy';th.append(i)}else if(f.type==='page')th.append(frame(f.src,f.label));
   else{th.append(ic('file',24));const FV=window.FileViewer,nm=/\.pdf$/i.test(f.label)?f.label:f.label+'.pdf',pt=f.type==='pdf'&&FV&&FV.thumb?FV.thumb({src:f.src,name:nm,tid:'',kind:'review'}):null;fileFace(th,f);if(pt)th.append(pt)}
   a.append(th,el('span','swipe-file-name',f.label));return a};
  /* more than 6 files: 5 tiles and one "+N more" tile that shows the rest in place, never a silent cut (ORCH-421) */
  const tile=fs.length>6?fs.slice(0,5):fs;tile.forEach(f=>r.append(one(f)));
  if(fs.length>6){const m=btn('swipe-file swipe-file-more',[el('span','swipe-file-thumb','+'+(fs.length-5)),el('span','swipe-file-name',(fs.length-5)+' more files')]);m.setAttribute('role','listitem');
   m.addEventListener('pointerdown',e=>e.stopPropagation());m.onclick=e=>{e.stopPropagation();m.remove();fs.slice(5).forEach(f=>r.append(one(f)));r.classList.add('all')};r.append(m)}
  return r};
 /* order: waiting cards first (Later ones at the end), then answered */
 const waiting=()=>{const w=items.map((_,i)=>i).filter(i=>!ans[items[i].id]);return w.filter(i=>!later.has(items[i].id)).concat(w.filter(i=>later.has(items[i].id)))};
 const nextIdx=from=>{const w=waiting();const pos=w.indexOf(from);return w.length?(pos>=0?w[pos]:w.find(i=>i>from&&!later.has(items[i].id))??w[0]):items.length};
 let ready=false;const change=()=>{if(ready&&o.onChange)o.onChange()};/* the first onChange comes after the constructor returns, so a handler may use the deck */
 const render=()=>{stage.replaceChildren();cur=null;const n=items.length,k=Object.keys(ans).length;
  count.textContent=k+' answered · '+(n-k)+' waiting';fill.style.width=(k/n*100)+'%';undoBtn.disabled=!undoable();
  ticked=ticked.filter(r=>parseRef(r));if(!pairRefs())showing=false;const pr=pairNow();host.classList.toggle('pairing',!!pr);syncJump(pr);
  if(idx>=n&&!pr){acts.hidden=true;stage.append(summary());change();return}
  /* two side by side: each side has its own answers, the shared bar steps aside (ORCH-477) */
  if(pr){acts.hidden=true;stage.append(pairView(pr));change();return}acts.hidden=false;
  cur=card(items[idx]);const a=ans[items[idx].id];
  if(a){const t=el('div','swipe-was');t.append(ic('check',14),'You answered: '+ansWord(a)+'. A new answer is added, the old one stays on the ticket.');const sf=cur.querySelector('.swipe-foot');sf.classList.remove('empty');sf.prepend(t)}
  stage.append(cur);syncWords();wire(cur);change()};
 const thenLine=(t,it)=>{t.replaceChildren();t.hidden=!(it&&it.then&&!it.blocked);if(t.hidden)return;t.append(el('b','',isRun(it)?'After it runs: ':isOpt(it)?'If you pick one: ':'If you approve: '),it.then)};
 /* ---- compare (ORCH-477): a side is a card ("<id>") or one option of a choice ("<id>\n<option id>") */
 const SEP='\n',optsWithPreview=it=>isOpt(it)?(it.preview.options||[]).filter(op=>op&&op.preview):[];
 const optionRefs=it=>{const ops=optsWithPreview(it);return ops.length>1?ops.map(op=>({ref:it.id+SEP+op.id,label:(optLetter(op)?optLetter(op)+': ':'')+(op.title||op.id)})):[]};
 const parseRef=r=>{const s=String(r||''),k=s.indexOf(SEP),id=k<0?s:s.slice(0,k),it=items.find(x=>x.id===id);if(!it||ans[it.id])return null;if(k<0)return {ref:s,it,op:null};
  const op=optsWithPreview(it).find(x=>String(x.id)===s.slice(k+1));return op?{ref:s,it,op}:null};
 const refName=r=>r.op?(optLetter(r.op)?optLetter(r.op)+': ':'')+(r.op.title||r.op.id):r.it.title;
 /* round 2 (owner sent back, 18 Nov): ticks only in Compare mode (picking); two ticked wait for the Compare button
    (showing); Close, Esc or Cancel ends it. A third tick is refused calmly: its box stays disabled. */
 const pairRefs=()=>{const p=ticked.map(parseRef).filter(Boolean);return p.length===2?p:null};
 const pairNow=()=>showing?pairRefs():null;
 const syncOverview=headOnly=>{if(overlay&&overlay.draw)overlay.draw(headOnly)};
 const tick=ref=>{if(overlay&&!overlay.classList.contains('swipe-overview'))return;const on=ticked.includes(ref);if(!on&&(ticked.length>=2||!parseRef(ref)))return;ticked=on?ticked.filter(x=>x!==ref):ticked.concat(ref);picking=true;pairSide=0;
  if(showing&&!pairRefs()){showing=false;render()}else change();syncBoxes();syncOverview(true)};
 const compare=refs=>{ticked=(refs||[]).filter(r=>parseRef(r)).slice(0,2);showing=ticked.length===2;picking=ticked.length>0;pairSide=0;closeOverlay(true);render();syncBoxes()};
 const showPair=()=>{if(!pairRefs())return;showing=true;pairSide=0;closeOverlay(true);render()};
 const setPicking=on=>{picking=!!on;if(!picking){ticked=[];if(showing){showing=false;render();syncOverview();return}}change();syncOverview()};
 const syncBox=cb=>{const on=ticked.includes(cb.dataset.ref);cb.checked=on;cb.disabled=!on&&ticked.length>=2};
 const syncBoxes=()=>{if(overlay)overlay.querySelectorAll('.review-tick-box').forEach(syncBox)};
 /* the checkbox both "All cards" lists use (the page's list beside the deck and the deck's own overview) */
 const tickBox=(ref,label)=>{const l=el('label','review-tick'),cb=el('input','review-tick-box');cb.type='checkbox';cb.dataset.ref=ref;cb.setAttribute('aria-label','Compare '+label);syncBox(cb);cb.addEventListener('change',()=>tick(ref));l.append(cb);return l};
 /* the filled button is the suggested answer only, and only one on screen: two suggested sides keep both outlined */
 const sugSide=r=>r.op?!!r.op.suggested:sugOf(r.it)==='ok';
 const drawOk=(b,it)=>{const w=okWord(it),wait=w==='Pick one';b.className='btn '+(b.dataset.fill==='1'&&!wait?'primary':'outline')+' swipe-pair-ok';b.replaceChildren(...(wait?[]:[ic('check',16)]),el('span','',w))};
 const sideBar=(it,fill,op)=>{const bar=el('div','swipe-pair-bar'),t=el('p','swipe-then');thenLine(t,it);if(!t.hidden)bar.append(t);
  const row=el('div','swipe-pair-acts'),own=ownAnswers(it);
  if(op){const u=btn('btn '+(fill?'primary':'outline'),[ic('check',16),el('span','','Use '+(optLetter(op)||op.title||op.id))]);u.onclick=()=>answerIn(it,'ok',op.id);row.append(u)}
  else{const lt=btn('btn ghost swipe-pair-later',['Later']),ans=el('div','swipe-pair-answers');lt.onclick=()=>answerIn(it,'later');row.append(lt,ans);
   if(own)own.forEach(a=>{const b=btn('btn outline',[a.label]);b.onclick=()=>answerIn(it,'ok',a.picked);ans.append(b)});
   else{if(!sendsBack(it)){const c=btn('btn ghost',[ic('comment',16),el('span','','Comment')]);c.onclick=()=>answerIn(it,'talk');ans.append(c)}
    const no=btn('btn outline',[ic('x',16),el('span','',noWord(it))]);no.onclick=()=>answerIn(it,'no');
    const ok=btn('btn outline swipe-pair-ok',[]);ok.dataset.item=it.id;ok.dataset.fill=fill?'1':'';ok.onclick=()=>answerIn(it,'ok');drawOk(ok,it);ans.append(no,ok)}}
  bar.append(row);return bar};
 /* one option of a choice as its own card, so two options stand side by side at full size */
 const optionCard=(it,op,fill)=>{const c=el('article','swipe-card in-pair swipe-optcard');c.dataset.item=it.id;c.setAttribute('aria-label',refName({it,op}));
  const h=el('header','swipe-head'),m=metaLine({icon:it.icon||'cards',kindLabel:it.kindLabel,kind:it.kind,ticket:it.ticket});
  h.append(el('h3','',refName({it,op})),m,el('p','swipe-why','One of '+(it.preview.options||[]).length+' options of “'+it.title+'”'));c.append(h);
  const pv=el('div','swipe-preview');pv.dataset.type=op.preview.type||'doc';pv.append(buildPreview({title:op.title||op.id,preview:op.preview},false));c.append(pv);
  if(op.text){const d=el('div','doc swipe-optcard-text');d.append(el('p','',op.text));c.append(d)}
  c.append(sideBar(it,fill,op));return c};
 const pairView=pr=>{const box=el('section','swipe-pair');box.setAttribute('aria-label','Compare');
  const head=el('div','swipe-pair-head');head.append(el('h2','','Compare'));
  if(pr[0].it===pr[1].it)head.append(el('p','meta swipe-pair-of',(pr[0].it.preview.options||[]).length+' options of “'+pr[0].it.title+'”'));
  /* a phone shows one side at a time; the switch names both in full */
  const sw=el('div','segmented phone-only swipe-pair-switch'),panes=el('div','swipe-pair-panes');sw.setAttribute('role','group');sw.setAttribute('aria-label','Which one to show');panes.dataset.side=String(pairSide);
  pr.forEach((r,i)=>{const b=btn('btn sm',[el('span','',refName(r))]);b.setAttribute('aria-pressed',String(i===pairSide));b.onclick=()=>{pairSide=i;panes.dataset.side=String(i);sw.querySelectorAll('button').forEach((x,k)=>x.setAttribute('aria-pressed',String(k===i)))};sw.append(b)});
  const close=btn('btn outline sm swipe-pair-close',[ic('x',16),el('span','','Close')]);close.onclick=()=>{const back=pr[pairSide]||pr[0];compare([]);const at=items.indexOf(back.it);if(at>=0)jump(at)};
  head.append(sw,el('span','grow'),close);
  const sug=pr.map(sugSide),fillAt=sug.filter(Boolean).length===1?sug.indexOf(true):-1;
  pr.forEach((r,i)=>{const pane=el('div','swipe-pair-pane');
   if(r.op)pane.append(optionCard(r.it,r.op,i===fillAt));
   else{const c=card(r.it,'in-pair');c.append(sideBar(r.it,i===fillAt,null));pane.append(c)}
   panes.append(pane)});
  box.append(head,panes);return box};
 const step=d=>{const w=waiting(),at=w.indexOf(idx),to=w[at+d];if(to!=null)jump(to)};
 const syncJump=pr=>{const w=waiting(),at=w.indexOf(idx);jPos.textContent=pr?'2 side by side':w.length?(Math.max(at,0)+1)+' of '+w.length:'';jPrev.hidden=jNext.hidden=!!pr||w.length<2;jPrev.disabled=at<=0;jNext.disabled=at<0||at>=w.length-1};
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
 /* a card's name in that line: its whole title when short; a long one goes by its ticket (PIL-8), never cut mid-word */
 const shortName=it=>{const t=String(it.title||'').trim();if(t.length<=48)return t;if(it.ticket)return it.ticket;const c=t.slice(0,48),sp=c.lastIndexOf(' ');return (sp>20?c.slice(0,sp):c).replace(/[\s,;:.-]+$/,'')+'…'};
 const nudge=(c,msg)=>{reset(c);c.classList.remove('nudge');void c.offsetWidth;c.classList.add('nudge');live.textContent=msg;if(!o.quiet)say(msg)};
 const fly=(verdict,dx,dy)=>{if(!cur||overlay||busy)return;const c=cur,it=items[idx],w=stage.clientWidth,h=stage.clientHeight;
  if((ownOnly(it)||isRun(it))&&verdict!=='later')return;/* its own buttons answer it */
  if(verdict==='talk'||(verdict==='no'&&sendsBack(it)))return openComment();/* a Check sent back always says what should change */
  if(verdict==='ok'&&isOpt(it)&&!picked[it.id])return nudge(c,'Tap the option you want first.');
  if(verdict==='ok'&&it.blocked)return nudge(c,it.blocked);/* ORCH-548: Looks good is off; the card says why and what to press */
  busy=true;c.classList.add('leaving');/* a short fade, no swipe */
  setTimeout(()=>{busy=false;verdict==='later'?defer(it):commit(verdict,isOpt(it)&&verdict==='ok'?{picked:picked[it.id]}:null)},120)};
 /* an answer on one side of Compare: the same words and the same rules as the shared bar (ORCH-477) */
 const answerIn=(it,verdict,pick)=>{if(!it||overlay||busy)return;
  if(verdict==='later')return defer(it);
  if(verdict==='talk'||(verdict==='no'&&sendsBack(it)))return openComment(it);
  if(verdict==='ok'&&!pick&&isOpt(it)){if(!picked[it.id]){live.textContent='Tap the option you want first.';if(!o.quiet)say('Tap the option you want first.');return}pick=picked[it.id]}
  commit(verdict,pick?{picked:pick}:null,it)};
 const defer=it=>{const at=items.indexOf(it);later.add(it.id);done.push({item:it,verdict:'later',idx:at,laterOnly:true});if(!pairNow()){const w=waiting();idx=w.find(i=>!later.has(items[i].id))??w[0]??items.length}
  live.textContent='Later: '+it.title;render();if(!o.quiet)say('Moved to the end: '+shortName(it))};
 const commit=(verdict,note,item)=>{const it=item||items[idx],at=items.indexOf(it);done.push({item:it,verdict,note,idx:at,prev:ans[it.id],prevPick:ans[it.id]&&ans[it.id].note?ans[it.id].note.picked:undefined});ans[it.id]={verdict,note,item:it};later.delete(it.id);
  /* answered on one side of Compare: the other side stays ticked and shows as the card */
  ticked=ticked.filter(r=>parseRef(r));const rest=ticked.length?parseRef(ticked[0]):null;
  if(rest)idx=items.indexOf(rest.it);else{const from=at;idx=nextIdx(from)===from?items.length:nextIdx(from);if(idx===from)idx=items.length}
  const word=ansWord(ans[it.id]);live.textContent=word+': '+it.title;o.onDecide&&o.onDecide(it,verdict,note);render();
  if(!o.quiet)say(word+': '+shortName(it))};
 const undo=()=>{if(!undoable())return;const last=done.pop();if(last.laterOnly)later.delete(last.item.id);else if(last.prev){ans[last.item.id]=last.prev;if(last.prevPick)picked[last.item.id]=last.prevPick}else delete ans[last.item.id];
  idx=last.idx;closeOverlay();render();live.textContent='Back: '+last.item.title;if(!o.quiet)say('Back: '+shortName(last.item));o.onUndo&&o.onUndo(last.item);focusHost()};
 const jump=i=>{if(i<0||i>=items.length)return;closeOverlay(true);idx=i;showing=false;render();focusHost()};
 /* overlays: inside the deck (a phone frame keeps them); the rest of the deck is inert; Tab stays inside; Esc closes */
 const openOverlay=(node,focusEl)=>{overlay=node;[top,stage,acts,laterRow].forEach(n=>n.inert=true);host.append(node);(focusEl||node.querySelector('button,[href],input,textarea'))?.focus()};
 /* closing gives focus back to what opened it (the list's opener on a phone), else to the deck */
 const closeOverlay=quiet=>{if(!overlay)return;overlay.remove();overlay=null;[top,stage,acts,laterRow].forEach(n=>n.inert=false);const back=overlayBack;overlayBack=null;if(!quiet&&back&&back.isConnected!==false&&typeof back.focus==='function')back.focus();else focusHost()};
 host.addEventListener('keydown',e=>{if(e.key!=='Tab'||!overlay)return;const f=[...overlay.querySelectorAll('button:not([disabled]),[href],input,textarea,[tabindex="0"]')].filter(x=>x.offsetParent!==null);if(!f.length)return;
  const a=f[0],z=f[f.length-1];if(e.shiftKey&&document.activeElement===a){e.preventDefault();z.focus()}else if(!e.shiftKey&&document.activeElement===z){e.preventDefault();a.focus()}});
 /* ---- the "All cards" list (ORCH-477 round 2): a row goes to its card (title up to two lines, the deadline under it);
    "Compare" turns on picking: ticks beside the cards and beside the options of a choice with pictures, at most two;
    then "Compare" (filled once two are ticked) opens them side by side and "Cancel" ends picking. A group header is the
    ticket's name, with the count only when more than one waits; a lone card named like its ticket has no header. The
    page's list beside the deck (deck.drawList) and the phone's full list (the overview) draw the same rows. */
 const groupOf=it=>it.group||it.ticketTitle||it.ticket||'';
 const sameName=(a,b)=>String(a||'').trim().toLowerCase()===String(b||'').trim().toLowerCase();
 const listHead=()=>{const hd=el('div','review-list-head'),acts=el('div','review-list-acts');hd.append(el('h2','review-list-title','All cards'),acts);
  if(!picking){const c=btn('btn outline sm review-list-compare',[ic('compare',16),el('span','','Compare')]);c.setAttribute('aria-pressed','false');c.onclick=()=>setPicking(true);acts.append(c);return hd}
  const two=!!pairRefs(),go=btn('btn sm review-list-compare '+(two?'primary':'outline'),[el('span','','Compare')]),no=btn('btn ghost sm review-list-cancel',[el('span','','Cancel')]);
  go.disabled=!two;go.onclick=()=>showPair();no.onclick=()=>setPicking(false);acts.append(no,go);
  hd.append(el('p','meta review-list-hint','Tick two to see them side by side.'));return hd};
 const listRow=i=>{const it=items[i],a=ans[it.id],now=i===idx&&!pairNow()&&idx<items.length,r=btn('review-row'+(now?' is-current':'')+(a?' is-done':''),[]);
  r.dataset.item=it.id;r.title=it.title;if(now)r.setAttribute('aria-current','true');
  const ico=el('span','review-row-icon');ico.append(ic(it.icon||'file',16));const txt=el('span','review-row-text');txt.append(el('span','review-row-title',it.title));
  if(a)txt.append(el('span','review-row-sub',ansWord(a)));else if(it.need)txt.append(el('span','review-row-sub'+(soon(it)?' soon':''),it.need));
  r.append(ico,txt);r.onclick=()=>jump(i);
  const li=el('div','review-li');li.setAttribute('role','listitem');
  if(!picking||a){li.append(r);return li}
  const w=el('div','review-row-pick');w.append(tickBox(it.id,it.title),r);li.append(w);
  optionRefs(it).forEach(x=>{const l=tickBox(x.ref,x.label);l.classList.add('review-row-opt');l.append(el('span','review-row-title',x.label));li.append(l)});
  return li};
 const listGroups=()=>{const g=new Map();items.forEach((it,i)=>{const k=groupOf(it);if(!g.has(k))g.set(k,[]);g.get(k).push(i)});const wrap=el('div','review-list-groups');
  g.forEach((rows,name)=>{const sec=el('div','review-group');sec.setAttribute('role','list');sec.setAttribute('aria-label',name||'Cards');
   if(name&&!(rows.length===1&&sameName(name,items[rows[0]].title))){sec.classList.add('has-head');const left=rows.filter(i=>!ans[items[i].id]).length,hh=el('h3','review-group-head');hh.append(el('span','review-group-name',name));if(left>1)hh.append(el('span','review-group-count',left+' waiting'));sec.append(hh)}
   rows.forEach(i=>sec.append(listRow(i)));wrap.append(sec)});
  return wrap};
 /* keeps the focused tick or row focused across a redraw, and brings the current row into view once per change of card */
 let shownRow=null;
 const drawList=target=>{if(!target)return;const ae=document.activeElement,inside=ae&&target.contains&&target.contains(ae)?ae:null,ref=inside&&inside.dataset?inside.dataset.ref||'':'',row=inside&&inside.dataset?inside.dataset.item||'':'';
  target.replaceChildren(listHead(),listGroups());
  if(ref)[...target.querySelectorAll('.review-tick-box')].find(b=>b.dataset.ref===ref)?.focus();else if(row)[...target.querySelectorAll('.review-row')].find(b=>b.dataset.item===row)?.focus();
  else if(inside&&inside.classList&&inside.classList.contains('review-list-compare'))target.querySelector('.review-list-compare')?.focus();
  const c=target.querySelector('.review-row.is-current'),key=c?c.dataset.item:null;if(c&&key!==shownRow)showRow(target,c);shownRow=key};
 /* scrolls only the list itself (never the page) so the current row is in sight below the list's sticky header */
 const showRow=(target,c)=>{const sc=target.closest&&target.closest('.review-side,.swipe-viewer-body');if(!sc||!c.getBoundingClientRect)return;
  const r=c.getBoundingClientRect(),b=sc.getBoundingClientRect(),hd=sc.querySelector('.review-list-head'),top=b.top+(hd?hd.offsetHeight:0),bottom=Math.min(b.bottom,window.innerHeight||b.bottom);
  if(r.top<top)sc.scrollTop-=top-r.top+8;else if(r.bottom>bottom)sc.scrollTop+=r.bottom-bottom+8};
 /* a phone: the full list, one tap away; Close or Esc gives focus back to its opener */
 const openOverview=()=>{const back=document.activeElement;if(overlay)closeOverlay(true);const v=el('div','swipe-viewer swipe-overview');v.setAttribute('role','dialog');v.setAttribute('aria-label','All cards');
  const b=el('div','swipe-viewer-bar'),x=btn('btn ghost icon sm',[ic('x',18)],'Close');x.onclick=()=>{closeOverlay();render()};
  const body=el('div','swipe-viewer-body review-list');
  v.draw=headOnly=>{b.replaceChildren(x,listHead());if(!headOnly)body.replaceChildren(listGroups())};
  v.draw();v.append(b,body);overlayBack=back&&back!==document.body&&back!==host?back:null;openOverlay(v,x);return v};
 const openComment=item=>{const it=item||items[idx];if(!it)return null;const dr=drafts[it.id]=drafts[it.id]||{text:'',clips:[]};
  const scr=el('div','swipe-scrim'),sh=el('div','swipe-sheet');sh.setAttribute('role','dialog');sh.setAttribute('aria-label','Comment on '+it.title);
  const grab=el('div','grab');grab.title='Pull down to close; your words are kept';
  const ttl=el('h2','','What should change?'),sub=el('p','meta',it.title);sub.style.margin='0';
  /* o.attach (composer options, ORCH-422): the text field is the shared box, so a screenshot pastes, files drop or pick and
     a voice note records into the same tray; Send back and Add note carry them (note.changes.files). */
  let box=null,ta;if(o.attach&&UI.composer){box=el('div');box.id='swipe-box-'+String(it.id).replace(/[^A-Za-z0-9_-]/g,'_');
   const comp=UI.composer(box,{hint:'',...o.attach,send:false,interrupt:false,label:'What should change',placeholder:o.attach.placeholder||'Write, paste a picture or record',draft:dr.text,dropTarget:sh,onFiles:f=>{dr.files=f.slice();sync&&sync()}});
   box.comp=comp;ta=comp.field;if(dr.files&&dr.files.length)comp.restore({text:dr.text,files:dr.files})}
  else{ta=el('textarea');ta.placeholder=o.voice?'Type, or hold the mic and talk':'Type what should change';ta.setAttribute('aria-label','What should change');ta.value=dr.text}
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
  const foot=el('div','swipe-sheet-foot'),cancel=btn('btn',['Cancel']),back=btn('btn',[it.kind==='choice'?'Send my answer':'Send back for changes']),use=btn('btn primary',['']),note=o.onNote&&it.kind!=='choice'?btn('btn',['Add note'],'Add note, the card stays and the work goes on'):null;
  const setAbout=v=>{about.v=v;about.querySelectorAll('button').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.v===v)));sync()};
  const ready=()=>!box||box.comp.files().every(f=>f.progress===100&&!f.failed);
  var sync=()=>{const has=(!!ta.value.trim()||(o.voice&&dr.clips.length)||!!(box&&box.comp.files().length))&&ready();dr.text=ta.value;back.disabled=use.disabled=!has;if(note)note.disabled=!has;
   const opt=about&&about.v!=='all'?about.v:null;use.hidden=!opt;if(opt)use.textContent='Use '+opt+' with these changes';
   back.className=opt?'btn':'btn primary';
   hint.textContent=opt?('“Send back” asks for new versions. “Use '+opt+'” builds '+opt+' with your changes.'):it.kind==='choice'?'The helper gets your words as the answer.':'The helper gets your words and makes a new version. Nothing is approved.'+(note?' “Add note” only saves your words: the card stays and the work goes on.':'')};
  ta.addEventListener('input',sync);
  const close=()=>{box&&box.comp.recorder&&box.comp.recorder.stop();closeOverlay();reset(cur)};cancel.onclick=close;
  const leave=(verdict,note)=>{box&&box.comp.recorder&&box.comp.recorder.destroy();closeOverlay();const c=cur;busy=true;if(c&&c.dataset.item===it.id)c.classList.add('leaving');
   setTimeout(()=>{busy=false;delete drafts[it.id];commit(verdict,note,it)},220)};
  const sent=()=>box?box.comp.files().map(({name,size,type,url})=>({name,size,type,url})):[];
  const words=()=>({text:ta.value.trim(),clips:o.voice?dr.clips.slice():[],pins:(pins[it.id]||[]).slice(),...(box?{files:sent()}:{})});
  back.onclick=()=>leave('talk',{changes:words(),about:about?about.v:null});
  use.onclick=()=>{picked[it.id]=about.v;leave('ok',{picked:about.v,changes:words()})};
  if(note)note.onclick=async()=>{const text=ta.value.trim(),files=sent();if((!text&&!files.length)||note.disabled)return;note.disabled=back.disabled=use.disabled=true;
   let r;try{r=await o.onNote(it,text,files)}catch(e){r={ok:false}}
   if(r&&r.ok){delete drafts[it.id];closeOverlay();reset(cur);if(!o.quiet)say('Note added. The card stays; the work goes on.')}
   else{hint.textContent=(r&&r.error&&r.error.message)||'Could not save the note. Your words are kept.';sync()}};
  foot.append(cancel,...(note?[note]:[]),back,use);
  /* pull the handle down to close (the words stay) */
  grab.addEventListener('pointerdown',e=>{const y0=e.clientY;grab.setPointerCapture(e.pointerId);const mv=ev=>{sh.style.transform=`translateY(${Math.max(0,ev.clientY-y0)}px)`};
   grab.addEventListener('pointermove',mv);grab.addEventListener('pointerup',ev=>{grab.removeEventListener('pointermove',mv);if(ev.clientY-y0>80)close();else sh.style.transform=''},{once:true})});
  sh.append(grab,ttl,sub);if(about)sh.append(about);sh.append(hint);if(o.voice&&!box)sh.append(voice,clips);sh.append(box||ta,foot);scr.append(sh);
  scr.addEventListener('pointerdown',e=>{if(e.target===scr)close()});
  if(about)setAbout(picked[it.id]||'all');drawClips();sync();openOverlay(scr,o.state?null:ta);return {mic,start,stop,ta,send:back,use,setAbout,sync}};
 /* Viewer: bigger, zoom, Open, and spots (tap “Spot”, tap the place, say or type what to change; the spot remembers
    which option or side it is on). */
 const openViewer=(side,item)=>{const it=item||items[idx];if(!it)return null;side=side==='before'||side==='after'?side:null;const v=el('div','swipe-viewer');v.dataset.item=it.id;v.setAttribute('role','dialog');v.setAttribute('aria-label',it.title);
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
  const k=e.key;/* side by side: the arrows do not answer (which side?); Esc goes back to one card */
  if(pairNow()){if(k==='Escape'){e.preventDefault();compare([])}else if(k==='z'||k==='Z'){e.preventDefault();undo()}else if(k==='o'||k==='O'){e.preventDefault();openOverview()}return}
  if(k==='ArrowRight'){e.preventDefault();fly('ok')}else if(k==='ArrowLeft'){e.preventDefault();fly('no')}else if(k==='ArrowDown'){e.preventDefault();fly('talk')}else if(k==='ArrowUp'){e.preventDefault();fly('later')}
  else if(k===' '){e.preventDefault();cur&&hasPreview(items[idx])&&openViewer()}else if(k==='z'||k==='Z'){e.preventDefault();undo()}else if(k==='o'||k==='O'){e.preventDefault();openOverview()}
  else if((k==='b'||k==='B')&&cur){const w=cur.querySelector('.swipe-compare');if(w){e.preventDefault();w.cycle()}}});
 if(!o.start&&items[idx]&&ans[items[idx].id]){const w=waiting();idx=w.find(i=>!later.has(items[i].id))??w[0]??items.length}
 render();ready=true;Promise.resolve().then(()=>o.onChange&&o.onChange());
 return {jump,openOverview,answers:ans,items,fly,undo,syncUndo:()=>{undoBtn.disabled=!undoable()},pick:id=>pick(items[idx],id),openComment,openViewer,show:(dx,dy)=>cur&&show(cur,dx,dy),pins,later,get busy(){return !!overlay||busy},get index(){return idx},
  tick,compare,showPair,setPicking,drawList,tickBox,optionRefs,openFile,get ticked(){return ticked.slice()},get comparing(){return !!pairNow()},get picking(){return picking}}};
})();
/* Login door and profile picker (ORCH-1035). UI.doorLogin({onLogin, commands, error, notice}) is the full-page login card
   ("Welcome", one token field, Log in) plus the way in for someone without a token (ORCH-1851): ask the person who
   sent the address for a private sign-in link or a token, and how to use each. commands: [{command, text}] for the
   person who runs the workspace, shown last and small. notice: a line above the card (a sign-in link that no longer
   works). onLogin(token) returns a promise of an error line or null. UI.profilePicker(
   {people, current, onPick, onAdd, onLogout}) is the full-page "Who is using orch?" picker; onPick(name) and
   onAdd(name) return a promise of an error line or null. Both return the .door element (the caller adds it to the page
   and removes it when done). Text only through textContent. */
(()=>{'use strict';const UI=window.UI=window.UI||{};
const el=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!=null)n.textContent=text;return n};
const COLORS=['blue','green','violet','amber','teal','pink','indigo','orange','cyan','red','lime','slate'];
UI.profileColor=name=>{let h=0;for(const c of String(name||''))h=(h*31+c.codePointAt(0))>>>0;return COLORS[h%COLORS.length]};
UI.doorLogo=UI.doorLogo||'logo.svg';  // the page's orch mark (a mockup sets its own path)
const mark=()=>{const m=el('img','door-mark');m.src=UI.doorLogo;m.alt='';return m};
const shell=(title,text)=>{const g=el('div','door');g.setAttribute('role','dialog');g.setAttribute('aria-modal','true');
 const inner=el('div','door-inner'),h=el('h1','door-title',title);h.id='door-title-'+Math.random().toString(36).slice(2,8);g.setAttribute('aria-labelledby',h.id);
 inner.append(mark(),h);if(text)inner.append(el('p','door-text',text));g.append(inner);return [g,inner]};
UI.doorLogin=o=>{o=o||{};const [g,inner]=shell('Welcome','Log in with your token.');
 const form=el('form','door-card'),field=el('div','field'),label=el('label','',  'Token'),inp=el('input','input');
 inp.type='password';inp.name='token';inp.autocomplete='current-password';inp.spellcheck=false;inp.id='door-token';label.htmlFor=inp.id;inp.required=true;
 const err=el('p','door-error');err.id='door-token-err';err.setAttribute('role','alert');err.hidden=!o.error;if(o.error){err.textContent=o.error;inp.setAttribute('aria-invalid','true');inp.setAttribute('aria-describedby',err.id)}
 const go=el('button','btn primary','Log in');go.type='submit';
 field.append(label,inp,err);form.append(field,go);
 if(o.notice){const n=el('div','banner error door-notice',o.notice);n.setAttribute('role','alert');inner.append(n)}
 inner.append(form);
 const help=el('section','door-help'),ht=el('h2','door-help-title');ht.id=inp.id+'-help';help.setAttribute('aria-labelledby',ht.id);
 const again=()=>{ht.textContent='Need a new link or token?'};ht.textContent='No token yet?';if(o.error||o.notice)again();
 const ask=el('p');ask.append(el('strong','','Ask the person who sent you this address'),' for a private sign-in link or a token, just for you.');
 const steps=el('ol','door-steps');steps.append(el('li','','Sign-in link: open it in this browser.'),el('li','','Token: paste it above, then Log in.'));
 help.append(ht,ask,steps);
 if(o.commands&&o.commands.length){const c=el('div','door-hint');c.append(el('p','','For the person who runs this workspace, in their terminal:'));
  o.commands.forEach(x=>{const p=el('p');p.append(el('code','',x.command),' '+x.text);c.append(p)});help.append(c)}
 inner.append(help);
 form.addEventListener('submit',async e=>{e.preventDefault();const v=inp.value.trim();if(!v){inp.focus();return}
  go.disabled=true;go.setAttribute('aria-busy','true');go.textContent='Logging in…';
  let why=null;try{why=o.onLogin?await o.onLogin(v):null}catch(_){why='That did not work. Try again.'}
  go.disabled=false;go.removeAttribute('aria-busy');go.textContent='Log in';
  if(why){err.textContent=why;err.hidden=false;inp.setAttribute('aria-invalid','true');inp.setAttribute('aria-describedby',err.id);again();inp.select()}});
 setTimeout(()=>inp.focus(),0);return g};
UI.profilePicker=o=>{o=o||{};const [g,inner]=shell('Who is using orch?',null);
 const list=el('ul','profiles'),err=el('p','door-error');err.setAttribute('role','alert');err.hidden=true;
 const fail=why=>{err.textContent=why||'';err.hidden=!why};
 const tile=(name,add)=>{const li=el('li'),b=el('button','profile'+(add?' add':''));b.type='button';
  const face=el('span','profile-face',add?'+':(String(name).trim()[0]||'?').toUpperCase());face.setAttribute('aria-hidden','true');
  if(!add){b.dataset.c=UI.profileColor(name);b.dataset.profile=name;if(name===o.current)b.setAttribute('aria-current','true')}
  b.append(face,el('span','profile-name',add?'Add profile':name));li.append(b);return [li,b]};
 (o.people||[]).forEach(n=>{const [li,b]=tile(n,false);b.onclick=async()=>{fail(null);b.disabled=true;let why=null;try{why=o.onPick?await o.onPick(n):null}catch(_){why='That did not work. Try again.'}finally{b.disabled=false}fail(why)};list.append(li)});
 const addForm=el('form','profiles-add'),inp=el('input','input');inp.name='name';inp.maxLength=40;inp.setAttribute('aria-label','Name of the new profile');inp.placeholder='Name';
 const save=el('button','btn primary','Add');save.type='submit';addForm.append(inp,save);addForm.hidden=true;
 if(o.onAdd&&(o.people||[]).length<(o.max||20)){const [li,b]=tile('',true);b.onclick=()=>{addForm.hidden=false;inp.focus()};list.append(li)}
 addForm.addEventListener('submit',async e=>{e.preventDefault();const v=inp.value.trim();if(!v){inp.focus();return}save.disabled=true;let why=null;try{why=await o.onAdd(v)}catch(_){why='That did not work. Try again.'}finally{save.disabled=false}fail(why)});
 inner.append(list,addForm,err);
 if(!(o.people||[]).length){addForm.hidden=false;setTimeout(()=>inp.focus(),0)}
 if(o.onLogout){const out=el('button','btn ghost sm','Log out');out.type='button';out.onclick=()=>o.onLogout();inner.append(out)}
 setTimeout(()=>{const f=list.querySelector('[aria-current=true]');f&&f.focus()},0);  // only the current profile: a focused first tile looks picked
 return g};
})();
