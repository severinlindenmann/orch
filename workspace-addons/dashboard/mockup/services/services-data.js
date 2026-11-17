/* Services mockup (ORCH-268): the demo snapshot and the preview actions of services.html (layout C, picked by the owner 17 Nov). */
   Mockup only. Nothing here talks to a computer; every click changes this snapshot and shows the shared toast. */
(()=>{'use strict';
const ticket='../ticket/ticket.html';
const services=[
 {id:'budget-guard',name:'Budget guard',what:'Stops helpers when the weekly budget is used up',state:'failing',
  since:'stopped 3 times in the last 10 minutes, last at 16:41',sinceShort:'last stop 16:41',auto:false,madeBy:{text:'ORCH-7',href:ticket,kind:'ticket'},
  health:{ok:false,how:'process alive',text:'Not alive: it stops about 40 seconds after every start'},depends:['Every helper run that has a budget'],
  question:{title:'Budget guard keeps stopping',text:'Restart, Stop or Look into it?',from:'ORCH-7'},
  log:['16:39:02 started','16:39:40 could not read the budget file, stopping','16:40:11 started','16:40:13 key loaded: ••••••',
       '16:40:52 could not read the budget file, stopping','16:41:20 started','16:41:58 could not read the budget file, stopping']},
 {id:'forwarder',name:'Private-network forwarder',what:'Makes your shared pages reachable on the private network',state:'running',
  since:'since Mon 16 Nov, 09:12',auto:true,madeBy:{text:'Found, now managed',kind:'outside'},
  health:{ok:true,how:'answers on its address',text:'Answers on its address'},depends:['The dashboard link','The demo'],
  log:['09:12:03 started','09:12:04 key loaded: ••••••','09:12:04 listening on the private network','12:30:41 shared page opened: weekly report',
       '16:44:10 answered on its address']},
 {id:'report-watcher',name:'Problem-report watcher',what:'Turns new problem reports into tickets',state:'running',
  since:'since Sun 15 Nov, 22:40',auto:true,madeBy:{text:'ORCH-20',href:ticket,kind:'ticket'},
  health:{ok:true,how:'process alive',text:'Process alive'},depends:['Nothing else'],
  log:['22:40:15 started, watching for new problem reports','08:03:27 new report, ticket made','11:52:09 new report, ticket made',
       '16:20:44 login to the tracker ok (token ••••••)','16:43:00 nothing new']},
 {id:'demo-update',name:'Demo auto-update',what:'Keeps the demo workspace on the newest version',state:'running',
  since:'since today 07:58',auto:true,madeBy:{text:'ORCH-22',href:ticket,kind:'ticket'},
  health:{ok:true,how:'process alive',text:'Process alive'},depends:['The demo workspace'],
  log:['07:58:10 started','07:58:31 demo is on the newest version','12:14:02 new version found, updating the demo',
       '12:15:40 demo updated (download key ••••••)','16:30:00 demo is on the newest version']},
 {id:'dashboard-front',name:'Dashboard front',what:'Shows this dashboard at its short address',state:'stopped',
  since:'since this computer restarted, today 06:30',auto:false,madeBy:{text:'Dashboard add-on',href:'../settings/settings.html',kind:'addon'},
  health:{ok:false,how:'answers on its address',text:'Does not answer on its address'},depends:['The short dashboard address'],
  log:['Mon 21:02:11 started','Mon 21:02:12 session key loaded: ••••••','Mon 21:02:12 answering on its address','today 06:30:02 this computer restarted, not started again']}
];
const found=[
 {id:'old-test-page',name:'Old test page on port 8794',what:'A page somebody started by hand',since:'running since 12 Nov',
  health:{ok:true,how:'answers on its address',text:'Answers on its address'},depends:['Nothing we know of'],log:['12 Nov 14:02:55 started by hand','today 16:12:30 page opened']},
 {id:'test-network-helper',name:'Test network helper',what:'3 parts that belong together',since:'running since 10 Nov',
  health:{ok:true,how:'process alive',text:'Process alive, all 3 parts'},depends:['Nothing we know of'],log:['10 Nov 09:40:00 part 1 of 3 started','10 Nov 09:40:02 part 2 of 3 started','10 Nov 09:40:05 part 3 of 3 started (key ••••••)']}
];
const data={today:'Tue 17 Nov',services,found};
const WORD={running:'Running',stopped:'Stopped',failing:'Failing'};
const listeners=[];
const changed=()=>listeners.forEach(f=>f());
const get=id=>data.services.find(s=>s.id===id)||data.found.find(s=>s.id===id);
const snap=()=>JSON.stringify(data);
const back=json=>{const old=JSON.parse(json);data.services=old.services;data.found=old.found;changed()};
const toast=(text,before)=>window.UI?.toast?.(text,before?()=>back(before):undefined);
const healthFor=(s,up)=>{s.health.ok=up;s.health.text=up?(s.health.how==='process alive'?'Process alive':'Answers on its address'):(s.health.how==='process alive'?'Not alive':'Does not answer on its address')};

/* tiny DOM builder: h('button',{class:'btn',onclick:f},'Start'); text always through textContent */
const h=(tag,attrs,...kids)=>{const n=document.createElement(tag);for(const [k,v] of Object.entries(attrs||{})){if(v==null||v===false)continue;
 if(k.startsWith('on'))n.addEventListener(k.slice(2),v);else if(k==='class')n.className=v;else if(v===true)n.setAttribute(k,'');else n.setAttribute(k,v)}
 kids.flat(Infinity).forEach(c=>{if(c!=null&&c!==false)n.append(c.nodeType?c:document.createTextNode(String(c)))});return n};

const act={
 start(id){const s=get(id),b=snap();s.state='running';s.since='since just now';delete s.question;healthFor(s,true);s.log=[...s.log,'just now: started'];changed();toast(s.name+' started',b)},
 stop(id){const s=get(id),b=snap();s.state='stopped';s.since='since just now';delete s.question;healthFor(s,false);s.log=[...s.log,'just now: stopped'];changed();toast(s.name+' stopped',b)},
 restart(id){const s=get(id),b=snap();s.state='running';s.since='since just now';delete s.question;healthFor(s,true);s.log=[...s.log,'just now: restarted'];changed();toast(s.name+' restarted',b)},
 auto(id,on){const s=get(id);s.auto=on;changed();toast(s.name+(on?' now starts by itself':' no longer starts by itself'))},
 manage(id){const i=data.found.findIndex(s=>s.id===id);if(i<0)return;const b=snap(),f=data.found.splice(i,1)[0];
  data.services.push({...f,state:'running',since:f.since.replace('running ',''),auto:false,madeBy:{text:'Found, now managed',kind:'outside'}});changed();toast(f.name+' is now managed with orch',b)},
 remove(id,after){const s=get(id);if(!s)return;const things=s.depends.filter(d=>!/^Nothing/.test(d));
  const d=h('dialog',{class:'dialog ui-bottom-close','aria-label':'Remove '+s.name},
   h('div',{class:'stack'},
    h('h2',null,'Remove '+s.name+'?'),
    h('p',null,'This is what happens:'),
    h('ul',null,
     h('li',null,s.state==='stopped'?'It stays stopped and leaves this list.':'It stops now and leaves this list.'),
     h('li',null,'It will not start by itself again.'),
     things.length?h('li',null,'These stop working: '+things.join(', ').toLowerCase()+'.'):null,
     h('li',null,s.madeBy.kind==='ticket'?'Ticket '+s.madeBy.text+' and its files stay as they are.':'Its files on this computer stay as they are.')),
    h('div',{class:'dlg-f'},
     h('button',{class:'btn outline',type:'button',onclick:()=>d.close()},'Keep it'),
     h('button',{class:'btn danger',type:'button','data-remove-yes':true,onclick:()=>{const b=snap();d.close();data.services=data.services.filter(x=>x.id!==id);after?.();changed();toast(s.name+' removed',b)}},'Remove'))));
  d.addEventListener('close',()=>d.remove());document.body.append(d);d.showModal()},
 answer(id,choice){choice==='stop'?act.stop(id):act.restart(id)}
};

/* shared pieces: state pill, question, log lines, Remove window */
const pill=s=>{const state=s.state||'found';
 if(state==='running')return h('span',{class:'pill done'},h('span',{class:'dot-ok','aria-hidden':'true'}),'Running');
 if(state==='failing')return h('span',{class:'pill failed'},window.UI.statusIcon('needs'),'Failing');
 if(state==='stopped')return h('span',{class:'pill'},window.UI.statusIcon('todo'),'Stopped');
 return h('span',{class:'pill'},h('span',{class:'dot-ok','aria-hidden':'true'}),'Running, not managed')};
const madeBy=s=>!s.madeBy?document.createTextNode('Not made by orch'):s.madeBy.href?h('a',{href:s.madeBy.href},s.madeBy.text):document.createTextNode(s.madeBy.text);
const logBox=s=>h('div',{class:'term',role:'group','aria-label':'Last log lines of '+s.name,tabindex:'-1','data-log':s.id},
 h('div',{class:'term-h'},'Last log lines'),h('div',{class:'term-b'},s.log.slice(-6).map(l=>h('span',null,l))));
const facts=s=>h('dl',null,
 h('div',null,h('dt',null,'Health check'),h('dd',null,h('span',{class:s.health.ok?'dot-ok':'dot-err','aria-hidden':'true'}),' '+s.health.text)),
 h('div',null,h('dt',null,'Depends on it'),h('dd',null,s.depends.join(', '))));
const autoSwitch=s=>h('input',{class:'switch',type:'checkbox',role:'switch',checked:s.auto,'aria-label':'Starts by itself: '+s.name,'data-k':s.id+':auto',onchange:e=>act.auto(s.id,e.target.checked)});
const autoWords=s=>s.auto?'Yes, after this computer restarts':'No, you start it by hand';
const btn=(s,what,label,cls)=>h('button',{class:'btn sm '+(cls||'outline'),type:'button','data-k':s.id+':'+what,'aria-label':label+' '+s.name,onclick:()=>act[what](s.id)},label);
/* one order everywhere: Start or Stop first, then Restart (then Open log, added by the page) */
const mainButton=s=>s.state==='stopped'?btn(s,'start','Start'):btn(s,'stop','Stop');
const stateButtons=s=>s.state==='stopped'?[mainButton(s)]:[mainButton(s),btn(s,'restart','Restart')];
const logBtn=(s,show)=>h('button',{class:'btn ghost sm',type:'button','data-k':s.id+':log','aria-label':'Open log of '+s.name,onclick:()=>show()},'Open log');
const removeRow=(s,after)=>h('div',{class:'row between quiet-note'},h('span',{class:'meta'},'Remove takes it off this list for good.'),h('button',{class:'btn danger sm',type:'button','data-k':s.id+':remove','aria-label':'Remove '+s.name,onclick:()=>act.remove(s.id,after)},'Remove'));
/* everything about one service, plainly, top to bottom: state, starts by itself, made by, health check, depends on it, last log lines, Remove.
   A found service shows what was found and only Manage with orch. */
const about=(s,o)=>{o=o||{};
 if(!s.state)return h('div',{class:'stack-lg','data-about':s.id},
  h('dl',null,h('div',null,h('dt',null,'Found'),h('dd',null,s.since.replace(/^r/,'R')+', not made by orch')),h('div',null,h('dt',null,'What it is'),h('dd',null,s.what))),
  h('p',{class:'muted'},'orch leaves it alone until you say so.'),
  h('div',{class:'row'},h('button',{class:'btn outline sm',type:'button','data-k':s.id+':manage','aria-label':'Manage '+s.name+' with orch',onclick:()=>act.manage(s.id)},'Manage with orch')));
 return h('div',{class:'stack-lg','data-about':s.id},
  h('dl',null,
   h('div',null,h('dt',null,'State'),h('dd',null,stateLine(s))),
   h('div',null,h('dt',null,'Starts by itself'),h('dd',null,h('label',{class:'row'},autoSwitch(s),h('span',null,autoWords(s))))),
   h('div',null,h('dt',null,'Made by'),h('dd',null,madeBy(s))),
   h('div',null,h('dt',null,'Health check'),h('dd',null,h('span',{class:s.health.ok?'dot-ok':'dot-err','aria-hidden':'true'}),' '+s.health.text)),
   h('div',null,h('dt',null,'Depends on it'),h('dd',null,s.depends.join(', ')))),
  logBox(s),
  removeRow(s,o.afterRemove))};
const toLog=(root,id)=>{const l=(root||document).querySelector('[data-log="'+id+'"]');if(!l)return;const dlg=l.closest('dialog');if(dlg)dlg.scrollTop=l.getBoundingClientRect().top-dlg.getBoundingClientRect().top+dlg.scrollTop-16;else l.scrollIntoView({block:'nearest'});l.focus({preventScroll:true})};
const stateLine=s=>WORD[s.state]+(s.state==='failing'?': ':' ')+s.since;
const question=s=>h('div',{class:'grow stack',role:'group','aria-label':'Question about '+s.name},
 h('div',null,h('strong',null,s.question.title),h('p',{class:'muted'},'It '+s.since+'. '+s.question.text)),
 h('div',{class:'row'},
  h('button',{class:'btn primary sm',type:'button','data-k':s.id+':q-restart',onclick:()=>act.answer(s.id,'restart')},'Restart'),
  h('button',{class:'btn outline sm',type:'button','data-k':s.id+':q-stop',onclick:()=>act.answer(s.id,'stop')},'Stop'),
  h('a',{class:'btn ghost sm',href:ticket},'Look into it')));
const counts=()=>{const c={running:0,stopped:0,failing:0};data.services.forEach(s=>c[s.state]++);return c};
const summary=()=>{const c=counts(),n=data.services.length;return [n+(n===1?' service':' services'),c.running+' running',c.stopped?c.stopped+' stopped':null,c.failing?c.failing+' failing':null].filter(Boolean).join(' · ')};
const order=()=>[...data.services.filter(s=>s.state==='failing'),...data.services.filter(s=>s.state!=='failing')];
/* re-draw and keep the keyboard focus on the same control */
const keep=draw=>{const k=document.activeElement?.dataset?.k;draw();if(k){const n=[...(window.UI?.overlay?.top()||document).querySelectorAll('[data-k]')].find(e=>e.dataset.k===k&&!e.closest('[inert]'));(n||(window.UI?.overlay?.top()?null:document.querySelector('[data-k^="'+k.split(':')[0]+':"]')))?.focus({preventScroll:true})}};
const param=(k,v)=>{const u=new URL(location.href);if(v==null)u.searchParams.delete(k);else u.searchParams.set(k,v);history.replaceState(null,'',u)};
/* the Empty and Error views, from the master state component */
const fillStates=()=>{const e=document.querySelector('[data-view="empty"]'),x=document.querySelector('[data-view="error"]');
 if(e){const a=h('a',{class:'btn outline sm',href:'../chat/chat.html'},'Ask the helper');const box=window.UI.state({kind:'empty',title:'No services yet',text:'When a ticket needs something to keep running on this computer, it shows up here.'});box.append(a);e.replaceChildren(box)}
 if(x)x.replaceChildren(window.UI.state({kind:'error',title:'Could not read the services on this computer',text:'Nothing was changed. Your services keep running as they were.',action:{label:'Try again',onClick:()=>{const u=new URL(location.href);u.searchParams.set('state','loaded');location.href=u.href}}}))};
window.servicesDemo={data,WORD,stateLine,question,get,act,h,pill,madeBy,logBox,facts,autoSwitch,autoWords,btn,mainButton,stateButtons,logBtn,removeRow,about,toLog,counts,summary,order,keep,param,fillStates,on:f=>listeners.push(f)};
})();
