/* ORCH-576 board mockup data (status rows): the owner board snapshot of 18 Nov plus helper, add-on and family facts. Data only. */
/* ORCH-576 board drafts: one realistic snapshot (from the owner's screenshot, 18 Nov). Data only. */
window.D576 = {
  lanes: [
    {id:'needs',   name:'Needs you', total:0,   tone:'needs-you', empty:'Nothing waits on you'},
    {id:'check',   name:'Check',     total:1,   tone:'review',    empty:'Nothing to check'},
    {id:'working', name:'Working',   total:4,   tone:'working',   empty:'No helper is working'},
    {id:'waiting', name:'Waiting',   total:31,  tone:'paused',    empty:'Nothing is waiting'},
    {id:'todo',    name:'To do',     total:9,   tone:'text-muted',empty:'Nothing picked to do next'},
    {id:'backlog', name:'Backlog',   total:33,  tone:'text-faint',empty:'New tickets land here'},
    {id:'done',    name:'Done',      total:468, tone:'done',      empty:'Nothing finished yet', today:14, folded:true},
    {id:'wontdo',  name:"Won't do",  total:29,  tone:'text-faint',empty:'', folded:true}
  ],
  boardOrder: ['backlog','todo','working','needs','waiting','check','done','wontdo'],
  t: [
    {k:'ORCH-428',lane:'check',title:'Away mode: answer cards and accept merged tickets while the owner is away',tasks:[2,2],age:'just now',act:'Check result'},

    {k:'ORCH-518',lane:'working',title:'Stress test: orch and the dashboard stay fast with 10,000 tickets',tasks:[1,6],age:'3 min ago',subs:[
      {k:'ORCH-519',title:'Seed script for big test workspaces (500, 2,000, 10,000, 50,000 tickets)',s:'done',when:'today'},
      {k:'ORCH-520',title:'Measure the baseline at every size and write the table',s:'done',when:'today'},
      {k:'ORCH-521',title:'Ticket list loads in under a second at 10,000',s:'working'},
      {k:'ORCH-522',title:'Board draws only what is on screen',s:'todo'},
      {k:'ORCH-523',title:'Search stays fast with 50,000 tickets',s:'todo'},
      {k:'ORCH-524',title:'Phone list pages through big workspaces',s:'todo'},
      {k:'ORCH-525',title:'Sync copes with 10,000 changed tickets',s:'todo'},
      {k:'ORCH-526',title:'Write the result into the docs',s:'todo'}]},
    {k:'ORCH-444',lane:'working',title:'Phone: voice, pictures and files as review feedback',tasks:[0,4],age:'11 min ago',parent:'Review page polish, right side'},
    {k:'ORCH-547',lane:'working',title:'Record truthfully who answered: the person, the manager or a script',tasks:[0,6],age:'11 min ago'},
    {k:'ORCH-507',lane:'working',title:'Dispatcher: start Ready and Backlog tickets up to a target from the queue',tasks:[2,5],age:'14 min ago'},

    {k:'ORCH-552',lane:'waiting',title:'Fix lane: a fix for release N ships as N.1 on its own',tasks:[4,5],age:'2 min ago',wait:'Until today 21:00',ws:'Until 21:00',parent:'Fast fix path when a release breaks'},
    {k:'ORCH-545',lane:'waiting',title:'Dev workspace: light checks per pull request, full suite per merge queue group',tasks:[1,7],age:'6 min ago',wait:'On pull request #1611',ws:'PR #1611',subs:[
      {k:'ORCH-556',title:'Light check set on each pull request',s:'backlog'},{k:'ORCH-557',title:'Full suite once per merge queue group of up to 10',s:'backlog'},{k:'ORCH-559',title:'No extra develop run after a proven group',s:'backlog'}]},
    {k:'ORCH-261',lane:'waiting',title:'The new Focus: wall, bar and layer (draft D)',tasks:[15,17],age:'1 h ago',wait:'Until today 18:30',ws:'Until 18:30',subs:[
      {k:'ORCH-262',title:'Make draft D the one Focus mockup and merge it',s:'done',when:'yesterday'},{k:'ORCH-263',title:'Result widgets and big overlay in the style guide',s:'done',when:'yesterday'},{k:'ORCH-264',title:'Preview switch for the new Focus',s:'done',when:'yesterday'}]},
    {k:'ORCH-571',lane:'waiting',title:'Release 27: walk it like a person before it goes out',tasks:[3,6],age:'20 min ago',wait:'On the release walk',ws:'Release walk'},
    {k:'ORCH-533',lane:'waiting',title:'Usage switches back to the main account after the reset',tasks:[2,3],age:'1 h ago',wait:'Until Fri 09:00',ws:'Until Fri 09:00'},
    {k:'ORCH-490',lane:'waiting',title:'Merge queue groups pull requests that are ready at the same time',tasks:[5,6],age:'2 h ago',wait:'On pull request #1598',ws:'PR #1598'},
    {k:'ORCH-472',lane:'waiting',title:'Windows: install without admin rights',tasks:[4,7],age:'yesterday',wait:'On ORCH-470',ws:'After ORCH-470'},

    {k:'ORCH-10',lane:'todo',title:'Notice by itself when a tool, connection or key stops working or needs renewing, and renew it from the workspace',tasks:[1,4],age:'2 days ago',paused:true,subs:[
      {k:'ORCH-43',title:'Design how a tool, connection or key that stopped working shows and is renewed',s:'done',when:'Mon'},
      {k:'ORCH-44',title:'orch checks by itself whether each tool, connection and key still works',s:'done',when:'Mon'},
      {k:'ORCH-45',title:'Dashboard shows what stopped working or runs out soon',s:'done',when:'yesterday'},
      {k:'ORCH-46',title:'Renew from the workspace in a few clicks',s:'done',when:'yesterday'},
      {k:'ORCH-47',title:'The phone warns when something stopped working or runs out soon',s:'done',when:'yesterday'},
      {k:'ORCH-48',title:'Checks for the other tools and outside connections',s:'done',when:'yesterday'},
      {k:'ORCH-164',title:'Renew and phone alert: security leftovers',s:'done',when:'yesterday'}]},
    {k:'ORCH-560',lane:'todo',title:'Ticket page: the task list folds finished tasks',tasks:[0,3],age:'1 h ago'},
    {k:'ORCH-561',lane:'todo',title:'Home: one line per helper that is idle',tasks:[0,2],age:'2 h ago'},
    {k:'ORCH-563',lane:'todo',title:'Board cards: due date in the warning colour once late',tasks:[0,2],age:'3 h ago',due:'Late since 09:00'},
    {k:'ORCH-565',lane:'todo',title:'Settings: plain words for the budget switch',tasks:[0,1],age:'yesterday'},

    {k:'ORCH-425',lane:'backlog',title:'Auto Reviewer: accepts or sends back work on tickets without the switch',tasks:[0,5],age:'just now',parent:'Review page polish, right side'},
    {k:'ORCH-559',lane:'backlog',title:'No extra develop run after a proven group',tasks:[1,2],age:'8 min ago',parent:'Dev workspace: light checks'},
    {k:'ORCH-556',lane:'backlog',title:'Light check set on each pull request',tasks:[1,2],age:'8 min ago',parent:'Dev workspace: light checks'},
    {k:'ORCH-557',lane:'backlog',title:'Full suite once per merge queue group of up to 10',tasks:[1,3],age:'8 min ago',parent:'Dev workspace: light checks'},
    {k:'ORCH-527',lane:'backlog',title:'Repeat a ticket every working day at 08:00',tasks:[0,0],age:'1 h ago'},
    {k:'ORCH-530',lane:'backlog',title:'Insights: cost per person this month',tasks:[0,0],age:'yesterday'},
    {k:'ORCH-531',lane:'backlog',title:'Chat answers with a picture of the board',tasks:[0,0],age:'yesterday'},
    {k:'ORCH-538',lane:'backlog',title:'Publish: a link that runs out after one week',tasks:[0,0],age:'Mon'},
    {k:'ORCH-541',lane:'backlog',title:'Phone: answer two questions in a row without going back',tasks:[0,0],age:'Mon'},

    {k:'ORCH-568',lane:'done',title:'Helper watcher nudges tickets waiting on a queued PR',tasks:[6,6],age:'just now',when:'today'},
    {k:'ORCH-520',lane:'done',title:'Measure the baseline at every size and write the table',tasks:[1,1],age:'1 min ago',when:'today',parent:'Stress test'},
    {k:'ORCH-546',lane:'done',title:'Fast fix path when a release breaks the workspace: fix release in 30 minutes, go back one release',tasks:[4,4],age:'today',when:'today'},
    {k:'ORCH-550',lane:'done',title:'Go back to an earlier release in one command',tasks:[3,3],age:'today',when:'today'},
    {k:'ORCH-551',lane:'done',title:'Self-check after every update, with one card to go back',tasks:[5,5],age:'today',when:'today'},

    {k:'ORCH-208',lane:'wontdo',title:'Invoice export',tasks:[0,0],age:'1 day ago'},
    {k:'ORCH-205',lane:'wontdo',title:'Invoice export',tasks:[0,0],age:'1 day ago'},
    {k:'ORCH-204',lane:'wontdo',title:'Invoice export',tasks:[0,0],age:'1 day ago'}
  ]
};
/* ORCH-576 draft C2: the same snapshot as data.js plus what the helper and the add-ons know per ticket. Data only. */
(() => {
  const D = window.D576, by = k => D.t.find(t => t.k === k);
  // One ticket waits on the owner, so the Answer signal and the Needs you row can be seen.
  D.t.unshift({k:'ORCH-580', lane:'needs', title:'Phone: which sound for a new question?', tasks:[1,3], age:'4 min ago', q:'Which sound?', due:'Late since 12:00'});
  D.lanes.find(l => l.id === 'needs').total = 1;
  // Helper state (core).
  by('ORCH-547').helper = {kind:'quiet', text:'Quiet for 25 min'};
  by('ORCH-507').helper = {kind:'stuck', text:'Stuck for 40 min'};
  // Add-on facts. tone: bad (failed), active (running now), watch (someone watching), info (scheduled or context), good.
  const A = (k, list) => { by(k).addons = list; };
  A('ORCH-545', [{a:'pull-requests', icon:'pull', tone:'bad', text:'Code checks failed on pull request #1611. A helper needs to fix them.', link:'Open pull request'}]);
  A('ORCH-490', [{a:'pull-requests', icon:'pull', tone:'active', text:'Code checks are running on pull request #1598.', link:'Open pull request'}]);
  A('ORCH-428', [{a:'pull-requests', icon:'pull', tone:'good', text:'Pull request #1622: every check passed. It is in the merge queue.', link:'Open pull request'}]);
  A('ORCH-518', [
    {a:'focus', icon:'focus', tone:'watch', text:'Someone is watching this ticket live now.', link:'Watch live'},
    {a:'services', icon:'play', tone:'active', text:'Its preview is running.', link:'Open preview'}]);
  A('ORCH-490', [{a:'pull-requests', icon:'pull', tone:'active', text:'Code checks are running on pull request #1598.', link:'Open pull request'}, {a:'automation', icon:'refresh', tone:'info', text:'Checks again every hour until it is merged.'}]);
  A('ORCH-444', [{a:'factory', icon:'hammer', tone:'info', text:'Step 2 of 5 of the Factory run "Review page polish".', link:'Open the run'}]);
  A('ORCH-527', [{a:'automation', icon:'refresh', tone:'info', text:'Repeats every working day at 08:00.', link:'Change when'}]);
  // Waits until a time: the core wait line already says it, so the automation icon stays away (no double fact).
  A('ORCH-533', [{a:'automation', icon:'clock', tone:'info', text:'Wakes on Fri at 09:00.', same:'wait'}]);
  A('ORCH-261', [{a:'sync', icon:'cloud', tone:'info', text:'A change on this ticket is not backed up yet.'}]);
  // How tickets belong together (core). kind: epic or release; pk: the ticket it is part of; dep: waits for that
  // ticket; replacedBy: Won't do because another ticket replaces it. Release 27 > epic ORCH-546 > ORCH-552 is 3 deep.
  const put = (t, beforeK) => { const i = beforeK ? D.t.findIndex(x => x.k === beforeK) : -1; if (i >= 0) D.t.splice(i, 0, t); else D.t.push(t); D.lanes.find(l => l.id === t.lane).total++; };
  put({k:'ORCH-575', lane:'working', kind:'release', title:'Release 27', tasks:[2,5], age:'5 min ago'}, 'ORCH-518');
  put({k:'ORCH-521', lane:'working', title:'Ticket list loads in under a second at 10,000', tasks:[2,4], age:'9 min ago', pk:'ORCH-518'}, 'ORCH-444');
  put({k:'ORCH-522', lane:'todo', title:'Board draws only what is on screen', tasks:[0,3], age:'1 h ago', pk:'ORCH-518'}, 'ORCH-560');
  put({k:'ORCH-420', lane:'todo', kind:'epic', title:'Review page polish, right side', tasks:[0,0], age:'yesterday'}, 'ORCH-10');
  put({k:'ORCH-470', lane:'todo', title:'Windows: installer for every computer', tasks:[1,4], age:'2 h ago'}, 'ORCH-561');
  const rel = (pk, keys) => keys.forEach(k => { const t = by(k); t.pk = pk; delete t.parent; });
  rel('ORCH-575', ['ORCH-546', 'ORCH-571', 'ORCH-568', 'ORCH-552']);
  by('ORCH-546').kind = 'epic'; by('ORCH-546').subs = [{k:'ORCH-553', title:'Prove the fast fix path end to end', s:'done'}];
  rel('ORCH-546', ['ORCH-552', 'ORCH-550', 'ORCH-551']);
  rel('ORCH-518', ['ORCH-520']);
  by('ORCH-545').kind = 'epic'; delete by('ORCH-545').subs; rel('ORCH-545', ['ORCH-556', 'ORCH-557', 'ORCH-559']);
  rel('ORCH-420', ['ORCH-425', 'ORCH-444']);
  by('ORCH-472').dep = 'ORCH-470';
  by('ORCH-205').replacedBy = 'ORCH-208'; by('ORCH-204').replacedBy = 'ORCH-208';
  D.t.forEach(t => delete t.parent);
  // Changed-at line for the hover title.
  D.t.forEach(t => { if (!t.ws && t.wait) t.ws = t.wait; });
})();
