/* Demo items for the swipe review draft (15 Nov). Everything that waits on the owner, one card each. */
window.SWIPE_KIT='../../../../../workspace/src/orch_ui/static/';
window.SWIPE_ITEMS=[
 {id:'d1',kind:'draft',kindLabel:'Draft',icon:'page',ticket:'DT-41',when:'today 09:12',title:'Home: “What changed today” block',
  why:'The helper drew a new block for the top of Home. Approve and it builds it.',
  preview:{type:'page',src:'../fb23-home-what-changed.html'},open:'../fb23-home-what-changed.html'},
 {id:'d2',kind:'check',kindLabel:'Check result',icon:'text',ticket:'DT-38',when:'today 08:40',title:'Customer survey summary',
  why:'Finished. Does this summary say what you need?',
  preview:{type:'doc',heading:'Survey: what customers said',paras:['48 answers from 1–12 Nov. Most liked: the friendly team (84 %). Most asked for: opening on Sunday (61 %).','Proposal: try Sunday 9–13 for four weeks, then look at the numbers again.','Three people asked for oat milk; one complaint about the waiting time on Saturday.']}},
 {id:'d3',kind:'link',kindLabel:'Link',icon:'link',ticket:'DT-35',when:'yesterday 17:05',title:'Opening hours page for the café',
  why:'Public page, goes live at cafe.example when you approve.',signs:true,
  preview:{type:'page',src:window.SWIPE_KIT+'samples/sample-page.html'},open:window.SWIPE_KIT+'samples/sample-page.html'},
 {id:'d4',kind:'question',kindLabel:'Plan',icon:'note',ticket:'DT-44',when:'today 10:02',title:'Send invoice reminders every Monday',
  why:'The helper wants to start a schedule. Nothing is sent before you say yes.',signs:true,
  preview:{type:'doc',heading:'Plan',steps:['Every Monday 08:00, find invoices older than 30 days.','Write one friendly reminder per customer (your usual wording).','Send from billing@, copy to you.','Stop after 3 reminders; then ask you.']}},
 {id:'d5',kind:'check',kindLabel:'Check result',icon:'table',ticket:'DT-38',when:'today 08:41',title:'Survey answers, cleaned (48 rows)',
  why:'Duplicates removed, topics grouped.',
  preview:{type:'table',cols:['Topic','Answers','Share'],rows:[['Friendly team','84','35 %'],['Sunday opening','61','25 %'],['Oat milk','29','12 %'],['Waiting time','22','9 %'],['Prices','18','8 %'],['Music','14','6 %'],['Parking','12','5 %']]}},
 {id:'d6',kind:'draft',kindLabel:'Draft',icon:'image',ticket:'DT-29',when:'Thu 16:20',title:'Invoice export screen',
  why:'New screen for the October export. Approve the look before it is built.',
  preview:{type:'img',src:window.SWIPE_KIT+'demo-image.svg',alt:'Invoice export screen draft'}}
];
