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
  put({k:'ORCH-470', lane:'todo', title:'Windows: signed installer', tasks:[1,4], age:'2 h ago'}, 'ORCH-561');
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
