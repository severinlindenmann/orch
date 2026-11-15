/* Demo items for the swipe review draft (15 Nov, revised after the design challenge).
   Every card says what happens when you approve (then), the approve button names the action (okLabel), and the card
   shows why it waits on you (need). Order: most urgent first. */
window.SWIPE_KIT='../../../../workspace/src/orch_ui/static/';
window.SWIPE_ITEMS=[
 {id:'d1',kind:'draft',kindLabel:'Draft',icon:'page',ticket:'DT-41',when:'today 09:12',need:'Blocks the Home update',title:'Home: “What changed today” block',
  why:'The helper drew a new block for the top of Home.',okLabel:'Build it',
  then:'The helper builds it. You check it again before anyone sees it.',
  preview:{type:'compare',before:{type:'page',src:'../home/home.html'},after:{type:'page',src:'../proposals/fb23-home-what-changed.html'}},open:'../proposals/fb23-home-what-changed.html'},
 {id:'o1',kind:'choice',kindLabel:'Choose',icon:'cards',ticket:'DT-45',when:'today 10:20',need:'Blocks the new start page',title:'Home: which layout?',
  why:'Three ways to show the start page. Tap the one you want.',
  then:'The helper builds the one you pick. You check it before it goes live.',
  preview:{type:'options',options:[
   {id:'A',title:'As today',preview:{type:'page',src:'../home/home.html'},text:'Cards for questions and work.'},
   {id:'B',title:'Recent changes first',suggested:true,preview:{type:'page',src:'../proposals/fb23-home-what-changed.html'},text:'Adds a “what changed” list.'},
   {id:'C',title:'Questions first',preview:{type:'page',src:'../proposals/f-home.html'},text:'One list, most urgent first.'}]}},
 {id:'d3',kind:'link',kindLabel:'Publish',icon:'link',ticket:'DT-35',when:'yesterday 17:05',need:'Needed before Friday',title:'Opening hours page for the café',
  why:'New Sunday hours 9–13.',okLabel:'Publish',signs:true,
  then:'Goes live for everyone at cafe.example. You can take it down again.',
  preview:{type:'page',src:window.SWIPE_KIT+'samples/sample-page.html'},open:window.SWIPE_KIT+'samples/sample-page.html'},
 {id:'o2',kind:'choice',kindLabel:'Choose',icon:'cards',ticket:'DT-47',when:'today 10:31',need:'Sends Friday 08:00',title:'Newsletter subject line',
  why:'Only the subject line. The newsletter text was checked yesterday.',
  then:'Used for Friday’s newsletter to 312 people.',
  preview:{type:'options',options:[
   {id:'A',title:'Plain',preview:{type:'doc',heading:'November news from the café',paras:['Short and safe.']}},
   {id:'B',title:'Question',suggested:true,preview:{type:'doc',heading:'Sunday coffee? You asked, we listened',paras:['Picks up the survey result.']}},
   {id:'C',title:'Offer',preview:{type:'doc',heading:'Free oat milk all November ☕',paras:['Promises an offer. Picking C asks you about the offer itself first.']}}]}},
 {id:'d4',kind:'question',kindLabel:'Plan',icon:'note',ticket:'DT-44',when:'today 10:02',need:'7 invoices are overdue',title:'Send invoice reminders every Monday',
  why:'The helper wants to start a schedule.',okLabel:'Start reminders',signs:true,
  then:'Every Monday 08:00 to customers with invoices older than 30 days (7 today). First one Mon 17 Nov. Nothing is sent before.',
  preview:{type:'doc',heading:'Plan',steps:['Every Monday 08:00, find invoices older than 30 days.','Write one friendly reminder per customer (your usual wording).','Send from billing@, copy to you.','Stop after 3 reminders; then ask you.']}},
 {id:'d2',kind:'check',kindLabel:'Check result',icon:'text',ticket:'DT-38',when:'today 08:40',title:'Customer survey summary',
  why:'Round 2, after your comment “shorter, and say what we should do”.',
  then:'The ticket is done; the summary goes to Anna.',
  preview:{type:'compare',note:'Round 2',
   before:{type:'doc',heading:'Survey results (round 1)',paras:['We received 48 answers between 1 and 12 November. Respondents mentioned the team, opening hours, products, prices, music and parking. 40 of 48 people (83 %) praised the team. 29 (60 %) asked for Sunday opening.','Other topics: waiting time (6), prices (5), oat milk (3), music (2).']},
   after:{type:'doc',heading:'Survey: what customers said',paras:['48 people answered (1–12 Nov). 40 praised the friendly team. 29 asked for Sunday opening.','Proposal: try Sunday 9–13 for four weeks, then look at the numbers again.','Smaller points: 6 about waiting time on Saturday, 3 asked for oat milk.']}}},
 {id:'d5',kind:'check',kindLabel:'Check result',icon:'table',ticket:'DT-38',when:'today 08:41',title:'Survey answers, cleaned',
  why:'48 people. One person can mention several topics.',
  then:'The summary above uses these numbers.',
  preview:{type:'table',cols:['Topic','People','Of 48'],rows:[['Friendly team','40','83 %'],['Sunday opening','29','60 %'],['Waiting time','6','13 %'],['Prices','5','10 %'],['Oat milk','3','6 %'],['Music','2','4 %']]}},
 {id:'d6',kind:'draft',kindLabel:'Draft',icon:'image',ticket:'DT-29',when:'Thu 16:20',title:'Invoice export screen',
  why:'New screen for the October export.',okLabel:'Build it',
  then:'The helper builds the screen. You check it before it is used.',
  preview:{type:'img',src:window.SWIPE_KIT+'demo-image.svg',alt:'Invoice export screen draft'}}
];
