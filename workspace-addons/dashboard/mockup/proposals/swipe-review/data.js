/* Demo items for the swipe review draft (15 Nov). Everything that waits on the owner, one card each. */
window.SWIPE_KIT='../../../../../workspace/src/orch_ui/static/';
window.SWIPE_ITEMS=[
 {id:'d1',kind:'draft',kindLabel:'Draft',icon:'page',ticket:'DT-41',when:'today 09:12',title:'Home: “What changed today” block',
  why:'The helper drew a new block for the top of Home. Approve and it builds it.',
  preview:{type:'compare',before:{type:'page',src:'../../home/home.html'},after:{type:'page',src:'../fb23-home-what-changed.html'}},open:'../fb23-home-what-changed.html'},
 {id:'o1',kind:'choice',kindLabel:'Choose',icon:'cards',ticket:'DT-45',when:'today 10:20',title:'Home: which layout?',
  why:'Three ways to show the start page. Tap one, then swipe right to take it.',
  preview:{type:'options',options:[
   {id:'A',title:'As today',preview:{type:'page',src:'../../home/home.html'},text:'Cards for questions and work.'},
   {id:'B',title:'What changed',suggested:true,preview:{type:'page',src:'../fb23-home-what-changed.html'},text:'Adds a “what changed” list.'},
   {id:'C',title:'Focus list',preview:{type:'page',src:'../f-home.html'},text:'One list, most urgent first.'}]}},
 {id:'d2',kind:'check',kindLabel:'Check result',icon:'text',ticket:'DT-38',when:'today 08:40',title:'Customer survey summary',
  why:'Round 2, after your comment “shorter, and say what we should do”.',
  preview:{type:'compare',note:'Round 2',
   before:{type:'doc',heading:'Survey results (round 1)',paras:['We received 48 answers between 1 and 12 November. Respondents mentioned the team, opening hours, products, prices, music and parking. The team was mentioned positively by 84 % of respondents. Sunday opening was mentioned by 61 %.','Other topics: oat milk (29), waiting time (22), prices (18), music (14), parking (12).']},
   after:{type:'doc',heading:'Survey: what customers said',paras:['48 answers from 1–12 Nov. Most liked: the friendly team (84 %). Most asked for: opening on Sunday (61 %).','Proposal: try Sunday 9–13 for four weeks, then look at the numbers again.','Three people asked for oat milk; one complaint about the waiting time on Saturday.']}}},
 {id:'d3',kind:'link',kindLabel:'Link',icon:'link',ticket:'DT-35',when:'yesterday 17:05',title:'Opening hours page for the café',
  why:'Public page, goes live at cafe.example when you approve.',signs:true,
  preview:{type:'page',src:window.SWIPE_KIT+'samples/sample-page.html'},open:window.SWIPE_KIT+'samples/sample-page.html'},
 {id:'o2',kind:'choice',kindLabel:'Choose',icon:'cards',ticket:'DT-47',when:'today 10:31',title:'Newsletter subject line',
  why:'Goes out Friday to 312 people.',
  preview:{type:'options',options:[
   {id:'A',title:'Plain',preview:{type:'doc',heading:'November news from the café',paras:['Short and safe. Expected opens: like last month.']}},
   {id:'B',title:'Question',suggested:true,preview:{type:'doc',heading:'Sunday coffee? You asked, we listened',paras:['Picks up the survey result.']}},
   {id:'C',title:'Offer',preview:{type:'doc',heading:'Free oat milk all November ☕',paras:['Needs your OK on the offer itself.']}}]}},
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
