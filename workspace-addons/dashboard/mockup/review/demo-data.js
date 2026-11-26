/* Demo items for the swipe review draft (15 Nov, revised after the design challenge).
   Every card says what happens when you approve (then), the approve button names the action (okLabel), and the card
   shows why it waits on you (need). Order: most urgent first. */
window.SWIPE_KIT='../../../../workspace/src/orch_ui/static/';
window.SWIPE_ITEMS=[
 /* Stuck work (ORCH-1108): Home's rows of work that stopped, as cards first in line, with Home's own buttons and Open
    (the ticket, same tab). No Looks good / Don't do: there is nothing to approve. A row with no button (a helper waiting
    for an OK on its screen) shows Open alone. */
 {id:'s1',kind:'stuck',kindLabel:'Stuck',icon:'pause',ticket:'DT-53',ticketId:'DT-53',ticketTitle:'Booking form',when:'today 11:12',title:'Booking form',text:'The checks of the step "Send the booking mail" failed 3 times in a row.',
  about:'Guests book a table on the website and get a confirmation mail.',why:'Stopped at: Send the booking mail · 3 of 6 steps done.',hint:'Nudge asks the helper to go on with the next step. Start fresh stops it and starts a new helper on this ticket.',
  href:'../ticket/ticket.html',preview:{type:'doc'},answers:[{label:'Nudge',picked:'nudge'},{label:'Start fresh',picked:'fresh'}]},
 {id:'s2',kind:'stuck',kindLabel:'Stuck',icon:'pause',ticket:'DT-54',ticketId:'DT-54',ticketTitle:'Menu page',when:'today 10:55',title:'Menu page',text:'The helper has waited 6 min for your OK on its screen.',
  about:'Put this week\'s menu on the website as a page with prices.',why:'Stopped at: Upload the menu photos · 2 of 4 steps done.',hint:'Open the ticket to see what the helper asks and answer it there.',
  href:'../ticket/ticket.html',preview:{type:'doc'}},
 /* Run it now (ORCH-848, owner picked draft A 19 Nov): the question is the title, the command box is the card, its two buttons are the answers. */
 {id:'r1',kind:'run',kindLabel:'Run',icon:'code',ticket:'DT-56',ticketId:'DT-56',ticketTitle:'Turn on the second look',when:'today 14:20',title:'Turn on the Reviewer\'s second look?',
  text:'Turn on the Reviewer\'s second look?',ifWait:'Bigger finished work is accepted after one look only.',facts:['Only bigger finished work gets the second look','One command turns it on, one turns it off again'],said:{who:'you',src:'chat',day:'on 21 Nov',words:'Bigger changes should get a second look before they are accepted.',stale:''},okLabel:'I ran it',noLabel:'Leave it off for now',then:'The Reviewer gives bigger finished work a second look.',phoneRun:true,
  run:{v:1,command:'orch config set workflow.reviewer_look on',cwd:'~/workspace-orch',class:'orch',exe:'orch',changes:'The Reviewer gives bigger finished work a second look',undo:'orch config set workflow.reviewer_look off'}},
 /* A sign-in (ORCH-865): Run it now opens the plain terminal with the sign-in started there; the card answers itself once
    the sign-in ended and its login check is green (here it only shows the waiting state). */
 {id:'r1b',kind:'run',kindLabel:'Run',icon:'code',ticket:'DT-57',ticketId:'DT-57',ticketTitle:'Read the Azure reports',when:'today 14:24',title:'Sign in to Azure so I can read the reports?',
  text:'Sign in to Azure so I can read the reports?',okLabel:'I ran it',noLabel:'Not now',then:'The helper goes on once it ran.',runTerminal:true,
  run:{v:1,command:'az login',cwd:'~/workspace-orch',class:'login',exe:null,changes:'Sign in again'}},
 /* A CI workflow change the owner merges (ORCH-305, ORCH-429): the changed lines with the risky ones red, the check's words
    first, and "Safe to merge" only when a script check found nothing. The click approves and merges this exact version. */
 {id:'m1',kind:'link',kindLabel:'Merge',icon:'link',ticket:'ORCH-512',ticketId:'ORCH-512',ticketTitle:'Release builds upload the app',when:'today 11:40',title:'Merge the CI workflow change of ORCH-512?',
  why:'It changes a CI workflow, so GitHub waits for you to approve it: your click approves this exact version and merges it with your own GitHub login.',okLabel:'Merge',
  links:[{label:'Workflow changes',url:'https://github.com/'}],
  then:'It is merged on GitHub with your own login.',
  preview:{type:'doc',heading:'What goes out · 1 change',status:{tone:'done',text:'All 14 checks passed · checked 11:40'},chips:[{text:'Look at the red lines',tone:'bad'}],
   paras:['Workflow check, look at this: reads a secret (DEPLOY_KEY); runs a download straight in a shell.'],
   diff:[{op:'-',file:'.github/workflows/release.yml',text:'      - run: make dist'},{op:'+',file:'.github/workflows/release.yml',text:'      - run: make dist upload'},
    {op:'+',file:'.github/workflows/release.yml',text:'          DEPLOY_KEY: ${{ secrets.DEPLOY_KEY }}',risk:'secret'},
    {op:'+',file:'.github/workflows/release.yml',text:'      - run: curl -fsSL https://get.example.dev/install.sh | bash',risk:'download run in a shell'}],
   rows:[{title:'.github/workflows/release.yml (+3 −1)'},{title:'Release builds upload the app',key:'ORCH-512',n:1842}],foot:'Exact version: 3f9c2a1'}},
 /* ORCH-477 (owner pick B, 18 Nov): a result with its files (pictures and a PDF that open large in the page), a second
    result to put beside it, a choice whose options have pictures (tick two options to compare them) and a short yes/no
    card that is as tall as its words. */
 {id:'s1',kind:'check',kindLabel:'Check result',icon:'check',ticket:'DT-53',ticketId:'DT-53',ticketTitle:'Spring sale',when:'today 09:40',need:'Sends Friday 08:00',title:'Spring sale email',
  why:'The helper says this is ready for your check.',okLabel:'Looks good',
  then:'The ticket is done. The email goes out on Friday 08:00 to 312 people.',
  files:[{label:'Email on a computer',type:'img',src:'assets/email-desktop.png'},{label:'Email on a phone',type:'img',src:'assets/email-phone.png'},{label:'Website banner',type:'img',src:'assets/sale-banner.png'},{label:'Flyer for the counter.pdf',type:'pdf',src:'assets/spring-flyer.pdf'}],
  preview:{type:'doc',heading:'What was done',paras:['In short: the spring sale email is written, with a version for phones, a banner for the website and a flyer for the counter.','The offer is 20% off all beans from 20 to 27 March with the code SPRING20, as you wrote in the ticket.','The list has 312 people: regulars, online shop customers and people who only get the newsletter.']}},
 {id:'s2',kind:'check',kindLabel:'Check result',icon:'check',ticket:'DT-51',ticketId:'DT-51',ticketTitle:'Weekly report for the café',when:'today 08:15',title:'Weekly report for the café',
  why:'The helper says this is ready for your check.',okLabel:'Looks good',
  then:'The ticket is done. The report goes to the team.',
  files:[{label:'Weekly report.pdf',type:'pdf',src:'assets/weekly-report.pdf'}],
  preview:{type:'doc',heading:'What was done',paras:['In short: the report for 10 to 16 November is written, two pages, with sales per day and the survey.','Sales were 8,420, 6% above last week. The first Sunday opening brought 900 in four hours.','One thing to check: the report proposes a second person on the till on Saturday.']}},
 {id:'s3',kind:'choice',kindLabel:'Choose',icon:'cards',ticket:'DT-46',ticketId:'DT-46',ticketTitle:'New start page',when:'today 10:20',need:'Blocks the new start page',title:'Start page: which layout?',
  why:'Three ways to show the start page. Pick the one you want.',
  then:'The helper builds the one you pick. You check it before it goes live.',
  preview:{type:'options',options:[
   {id:'A',title:'As today',preview:{type:'img',src:'assets/layout-a.png',alt:'Layout A'},text:'Three cards: questions, results and work.'},
   {id:'B',title:'Recent changes first',suggested:true,preview:{type:'img',src:'assets/layout-b.png',alt:'Layout B'},text:'Adds a list of what changed since yesterday.'},
   {id:'C',title:'Questions first',preview:{type:'img',src:'assets/layout-c.png',alt:'Layout C'},text:'One list, most urgent first.'}]}},
 {id:'s4',kind:'question',kindLabel:'Question',icon:'comment',ticket:'DT-47',ticketId:'DT-47',ticketTitle:'Friday newsletter',when:'today 10:31',need:'Sends Friday 08:00',title:'Send the newsletter on Friday?',
  text:'The text was checked yesterday. It goes to 312 people at 08:00.',preview:{type:'doc'},
  answers:[{label:'No',picked:'No'},{label:'Yes',picked:'Yes'}]},
 /* ORCH-477 round 2 (owner sent it back, 18 Nov): cards that stress sizes and text lengths, so the owner sees they fit:
    a 2-word title with a one-line summary and no files, a 114-character title, an unbroken web address in a title and a
    summary, 15 paragraphs, 1, 2 and 12 files (a very wide banner, a very tall phone screenshot, a tiny icon, a PDF), a
    choice with 2 and one with 6 options, a question with no detail text. dueAt within a day shows the deadline amber. */
 {id:'x1',kind:'check',kindLabel:'Check result',icon:'check',ticket:'DT-60',ticketId:'DT-60',ticketTitle:'Menu prices',title:'Menu prices',
  why:'The helper says this is ready for your check.',okLabel:'Looks good',then:'The ticket is done. The new prices show on the website tomorrow.',
  preview:{type:'doc',heading:'What was done',paras:['In short: every price on the website menu now matches the board at the counter.']}},
 {id:'x8',kind:'question',kindLabel:'Question',icon:'comment',ticket:'DT-61',ticketId:'DT-61',ticketTitle:'Christmas hours',title:'Open the café on 24 December?',
  okLabel:'Open',then:'The helper puts 8 to 12 on the website and on the door.',preview:{type:'doc'}},
 {id:'x6',kind:'choice',kindLabel:'Choose',icon:'cards',ticket:'DT-62',ticketId:'DT-62',ticketTitle:'Autumn flyer',need:'Prints tomorrow 09:00',dueAt:Date.now()+16*36e5,title:'Which picture for the autumn flyer?',
  why:'Two pictures fit the flyer. Pick one.',then:'The print shop gets the one you pick tomorrow at 09:00.',
  preview:{type:'options',options:[
   {id:'A',title:'Wide banner',suggested:true,preview:{type:'img',src:'assets/wide-banner.png',alt:'Wide autumn banner'},text:'Fits the top of the flyer.'},
   {id:'B',title:'Menu on a phone',preview:{type:'img',src:'assets/tall-phone.png',alt:'The menu on a phone'},text:'Shows the whole menu, but needs the full page.'}]}},
 {id:'x2',kind:'check',kindLabel:'Check result',icon:'check',ticket:'DT-63',ticketId:'DT-63',ticketTitle:'Autumn newsletter',need:'Sends Friday 08:00',
  title:'Autumn newsletter for regulars, online shop customers and everyone who only comes in on Sunday mornings for brunch',
  why:'The helper says this is ready for your check.',okLabel:'Looks good',then:'The ticket is done. The newsletter goes out on Friday 08:00 to 312 people.',
  files:[{label:'Website banner, autumn',type:'img',src:'assets/wide-banner.png'},{label:'Shop icon',type:'img',src:'assets/tiny-icon.png'}],
  preview:{type:'doc',heading:'What was done',paras:['In short: one newsletter for all three lists, with the oat milk latte on top and the Sunday hours below.','The banner is the same as on the website; the small icon is for the online shop.']}},
 {id:'x3',kind:'check',kindLabel:'Check result',icon:'link',ticket:'DT-63',ticketId:'DT-63',ticketTitle:'Autumn newsletter',
  title:'Check the offer link https://cafe-linde.example/angebote/herbst-2026/hafermilch-latte-gratis-fuer-stammkunden?quelle=newsletter',
  why:'The link is long because the shop adds where a visitor came from.',okLabel:'Looks good',then:'The link goes into the newsletter.',
  files:[{label:'Offer page on a phone',type:'img',src:'assets/tall-phone.png'}],
  preview:{type:'doc',heading:'What was done',paras:['The button in the newsletter opens https://cafe-linde.example/angebote/herbst-2026/hafermilch-latte-gratis-fuer-stammkunden?quelle=newsletter&kampagne=herbstnewsletter2026','The voucher page shows the rule word Hafermilchlattegratisgutscheinbedingungen, as the shop system names it.']}},
 {id:'x4',kind:'check',kindLabel:'Check result',icon:'text',ticket:'DT-64',ticketId:'DT-64',ticketTitle:'Year review',title:'Year review 2026 for the café',
  why:'The helper says this is ready for your check.',okLabel:'Looks good',then:'The ticket is done. The review goes to the team before the Christmas meeting.',
  files:[{label:'Weekly report.pdf',type:'pdf',src:'assets/weekly-report.pdf'}],
  preview:{type:'doc',heading:'What was done',paras:['In short: 2026 was our best year so far. Sales rose 11%, mostly from the new Sunday opening and the online shop.', 'January was quiet, as every year. We used it to repaint the back room and train Lena on the new coffee machine.', 'February brought the first oat milk complaints. We switched supplier in March, and the complaints stopped.', 'March: the spring sale with the code SPRING20 brought 214 orders in one week, 60 of them from new customers.', 'April and May were steady. The terrace opened on 2 May, two weeks earlier than last year, thanks to the warm weather.', 'June: the summer menu with iced coffee and lemonade sold better than planned. Iced coffee alone was 9% of drinks.', 'July had the two-week closure for the holidays. The online shop stayed open and shipped 180 orders.', 'August: we started the loyalty card. 312 regulars have one now; about a third come in every week.', 'September: the new opening hours on Sunday (9 to 13) started. The first Sunday brought 900 in four hours.', 'October: the customer survey. 48 people answered; 40 praised the friendly team, 29 asked for more Sunday hours.', 'November: the autumn newsletter went out to 312 people. 41% opened it, which is twice the usual number.', 'Costs: coffee beans went up 8% this year. We kept prices the same until September, then raised a cappuccino by 20 cents.', 'Team: two new people on the till on Saturdays. Waiting time on Saturday mornings dropped from 9 to 5 minutes.', 'What did not work: the soup of the day. It sold fewer than five a day and we stopped it in October.', 'Proposal for 2027: keep Sunday 9 to 13, try a small brunch plate, and open the terrace again in early May.']}},
 {id:'x5',kind:'check',kindLabel:'Check result',icon:'image',ticket:'DT-65',ticketId:'DT-65',ticketTitle:'Menu board',title:'Pictures for the new menu board',
  why:'The helper says this is ready for your check.',okLabel:'Looks good',then:'The ticket is done. The print shop gets all twelve files.',
  files:[{label:'Autumn banner',type:'img',src:'assets/wide-banner.png'},{label:'Menu on a phone',type:'img',src:'assets/tall-phone.png'},{label:'Shop icon',type:'img',src:'assets/tiny-icon.png'},
   {label:'Email on a computer',type:'img',src:'assets/email-desktop.png'},{label:'Email on a phone',type:'img',src:'assets/email-phone.png'},{label:'Website banner',type:'img',src:'assets/sale-banner.png'},
   {label:'Board layout A',type:'img',src:'assets/layout-a.png'},{label:'Board layout B',type:'img',src:'assets/layout-b.png'},{label:'Board layout C',type:'img',src:'assets/layout-c.png'},
   {label:'Flyer for the counter.pdf',type:'pdf',src:'assets/spring-flyer.pdf'},{label:'Home today',type:'img',src:'assets/home-today.jpg'},{label:'Home proposal',type:'img',src:'assets/home-proposal.jpg'}],
  preview:{type:'doc',heading:'What was done',paras:['In short: twelve pictures for the board behind the counter, each in the size the print shop asked for.']}},
 {id:'x7',kind:'choice',kindLabel:'Choose',icon:'cards',ticket:'DT-66',ticketId:'DT-66',ticketTitle:'Sunday cake',title:'Sunday cake: which one goes on the board?',
  why:'Six cakes the baker can make on Saturday evening.',then:'The baker gets the order on Friday.',
  preview:{type:'options',options:[
   {id:'A',title:'Apple cake',preview:{type:'doc',heading:'Apple cake',paras:['Our classic. 4.50 a slice.']}},
   {id:'B',title:'Carrot cake',suggested:true,preview:{type:'doc',heading:'Carrot cake',paras:['Asked for 12 times in the survey. 4.80 a slice.']}},
   {id:'C',title:'Cheesecake',preview:{type:'doc',heading:'Cheesecake',paras:['Needs the cold shelf. 5.20 a slice.']}},
   {id:'D',title:'Plum cake',preview:{type:'doc',heading:'Plum cake',paras:['Only until the end of October. 4.60 a slice.']}},
   {id:'E',title:'Lemon tart',preview:{type:'doc',heading:'Lemon tart',paras:['Small, sells out fast. 4.90 a piece.']}},
   {id:'F',title:'Chocolate cake without flour',preview:{type:'doc',heading:'Chocolate cake without flour',paras:['For people who eat no gluten. 5.40 a slice.']}}]}},
 /* A design review as one set of cards (16 Nov, ORCH-65): the question text on the card, full-page pictures that fit the
    pane on a dark ground with a zoom per side, a marked suggestion, a choice with how it is today. */
 {id:'g1',kind:'draft',kindLabel:'Draft',icon:'page',group:'Home look',ticket:'DT-50',ticketId:'DT-50',ticketTitle:'Home look',when:'today 11:02',title:'Home: one list of what needs you',
  text:'Now: Home shows questions, results to check and a factory start in three places, and the count on top does not match the list. Proposal: one list, most urgent first, each row with its picture and one button. The count on top is the length of this list.',
  why:'Found in the dashboard look review.',okLabel:'Build it',suggest:'ok',
  links:[{label:'Mockup',url:'../proposals/fb23-home-what-changed.html'},{label:'Issue 1290',url:'https://github.com/'}],
  then:'The helper builds it. You check it again before anyone sees it.',
  preview:{type:'compare',before:{type:'img',src:'assets/home-today.jpg',alt:'Home today'},after:{type:'img',src:'assets/home-proposal.jpg',alt:'Home as proposed'}}},
 {id:'g2',kind:'choice',kindLabel:'Choose',icon:'cards',group:'Home look',ticket:'DT-50',ticketId:'DT-50',ticketTitle:'Home look',when:'today 11:03',title:'Home: where the review sets go',
  text:'Several cards that belong together should show as one row on Home with their pictures. Which place?',
  then:'The helper builds the one you pick.',
  preview:{type:'options',before:{type:'img',src:'assets/home-today.jpg',alt:'Home today'},options:[
   {id:'A',title:'Top of Home',suggested:true,preview:{type:'img',src:'assets/home-proposal.jpg',alt:'Sets on top'},text:'One row per set, above everything else.'},
   {id:'B',title:'Inside Needs you',preview:{type:'page',src:'../home/home.html'},text:'The set is one row in the list.'}]}},
 {id:'g3',kind:'plan',kindLabel:'Plan',icon:'note',group:'Home look',ticket:'DT-50',ticketId:'DT-50',ticketTitle:'Home look',when:'today 11:04',title:'Drop the old “Review all” button',
  text:'With sets on Home, the separate “Review all” button repeats the same thing. Proposal: remove it; the menu keeps Review.',
  okLabel:'Remove it',suggest:'no',
  then:'The button goes; Review stays in the menu.',
  preview:{type:'doc',heading:'What changes',paras:['Home: the “Review all” button is removed.','Menu: Review stays, with its count.']}},
 {id:'d1',kind:'draft',kindLabel:'Draft',icon:'page',ticket:'DT-41',ticketId:'DT-41',ticketTitle:'Home update',task:'d1',about:'Draw the “What changed today” block',when:'today 09:12',need:'Blocks the Home update',title:'Home: “What changed today” block',
  why:'The helper drew a new block for the top of Home.',okLabel:'Build it',
  then:'The helper builds it. You check it again before anyone sees it.',
  preview:{type:'compare',before:{type:'page',src:'../home/home.html'},after:{type:'page',src:'../proposals/fb23-home-what-changed.html'}},open:'../proposals/fb23-home-what-changed.html'},
 {id:'o1',kind:'choice',kindLabel:'Choose',icon:'cards',ticket:'DT-45',ticketId:'DT-45',ticketTitle:'New start page',task:'o1',about:'Pick the Home layout',when:'today 10:20',need:'Blocks the new start page',title:'Home: which layout?',
  why:'Three ways to show the start page. Tap the one you want.',
  then:'The helper builds the one you pick. You check it before it goes live.',
  preview:{type:'options',options:[
   {id:'A',title:'As today',preview:{type:'page',src:'../home/home.html'},text:'Cards for questions and work.'},
   {id:'B',title:'Recent changes first',suggested:true,preview:{type:'page',src:'../proposals/fb23-home-what-changed.html'},text:'Adds a “what changed” list.'},
   {id:'C',title:'Questions first',preview:{type:'page',src:'../proposals/f-home.html'},text:'One list, most urgent first.'}]}},
 {id:'d3',kind:'link',kindLabel:'Publish',icon:'link',ticket:'DT-35',ticketId:'DT-35',ticketTitle:'Opening hours page',when:'yesterday 17:05',need:'Needed before Friday',title:'Opening hours page for the café',
  why:'New Sunday hours 9–13.',okLabel:'Publish',signs:true,
  then:'Goes live for everyone at cafe.example. You can take it down again.',
  preview:{type:'page',src:window.SWIPE_KIT+'samples/sample-page.html'},open:window.SWIPE_KIT+'samples/sample-page.html'},
 {id:'o2',kind:'choice',kindLabel:'Choose',icon:'cards',ticket:'DT-47',ticketId:'DT-47',ticketTitle:'Friday newsletter',task:'o2',about:'Choose the subject line',when:'today 10:31',need:'Sends Friday 08:00',title:'Newsletter subject line',
  why:'Only the subject line. The newsletter text was checked yesterday.',
  then:'Used for Friday’s newsletter to 312 people.',
  preview:{type:'options',options:[
   {id:'A',title:'Plain',preview:{type:'doc',heading:'November news from the café',paras:['Short and safe.']}},
   {id:'B',title:'Question',suggested:true,preview:{type:'doc',heading:'Sunday coffee? You asked, we listened',paras:['Picks up the survey result.']}},
   {id:'C',title:'Offer',preview:{type:'doc',heading:'Free oat milk all November ☕',paras:['Promises an offer. Picking C asks you about the offer itself first.']}}]}},
 /* a Factory start: Home's short form and Home's buttons, none filled (ORCH-183, owner choice B) */
 {id:'f1',kind:'choice',kindLabel:'Choose',icon:'cards',ticket:'DT-49',ticketId:'DT-49',ticketTitle:'Loyalty card',when:'today 10:00',title:"Start 'Loyalty card for regular customers'?",
  text:'Regular customers collect stamps and get a free coffee after ten visits.\nRuns about 1 h 30 min · needs you for about 10 min · up to 2 h of helper time',preview:{type:'doc'},
  answers:[{label:'Not now',picked:'Not now'},{label:'Change it',picked:'Edit'},{label:'Start',picked:'Start'}]},
 /* a plain question with no pictures (orch ask --option ...): plain rows, whole titles (ORCH-110) */
 {id:'o3',kind:'choice',kindLabel:'Choose',icon:'cards',ticket:'DT-48',ticketId:'DT-48',ticketTitle:'Export button',task:'o3',when:'today 10:40',title:'Which name for the export button?',
  then:'The helper uses the name you pick.',
  preview:{type:'options',options:[{id:'Export',title:'Export',suggested:true},{id:'Download',title:'Download',text:'Says what happens on a phone.'}]}},
 {id:'d4',kind:'question',kindLabel:'Plan',icon:'note',ticket:'DT-44',ticketId:'DT-44',ticketTitle:'Invoice reminders',when:'today 10:02',need:'7 invoices are overdue',title:'Send invoice reminders every Monday',
  why:'The helper wants to start a schedule.',okLabel:'Start reminders',signs:true,
  then:'Every Monday 08:00 to customers with invoices older than 30 days (7 today). First one Mon 17 Nov. Nothing is sent before.',
  preview:{type:'doc',heading:'Plan',steps:['Every Monday 08:00, find invoices older than 30 days.','Write one friendly reminder per customer (your usual wording).','Send from billing@, copy to you.','Stop after 3 reminders; then ask you.']}},
 {id:'d2',kind:'check',kindLabel:'Check result',icon:'text',ticket:'DT-38',ticketId:'DT-38',ticketTitle:'Customer survey',when:'today 08:40',title:'Customer survey summary',
  why:'Round 2, after your comment “shorter, and say what we should do”.',
  then:'The ticket is done and the summary goes to Anna. Nothing else starts. To change something, press Send back and say what; a helper then works on it in this ticket.',
  preview:{type:'compare',note:'Round 2',
   before:{type:'doc',heading:'Survey results (round 1)',paras:['We received 48 answers between 1 and 12 November. Respondents mentioned the team, opening hours, products, prices, music and parking. 40 of 48 people (83 %) praised the team. 29 (60 %) asked for Sunday opening.','Other topics: waiting time (6), prices (5), oat milk (3), music (2).']},
   after:{type:'doc',heading:'Survey: what customers said',paras:['48 people answered (1–12 Nov). 40 praised the friendly team. 29 asked for Sunday opening.','Proposal: try Sunday 9–13 for four weeks, then look at the numbers again.','Smaller points: 6 about waiting time on Saturday, 3 asked for oat milk.']}}},
 {id:'d5',kind:'check',kindLabel:'Check result',icon:'table',ticket:'DT-38',ticketId:'DT-38',ticketTitle:'Customer survey',when:'today 08:41',title:'Survey answers, cleaned',
  why:'48 people. One person can mention several topics.',
  then:'The summary above uses these numbers.',
  preview:{type:'table',cols:['Topic','People','Of 48'],rows:[['Friendly team','40','83 %'],['Sunday opening','29','60 %'],['Waiting time','6','13 %'],['Prices','5','10 %'],['Oat milk','3','6 %'],['Music','2','4 %']]}},
 {id:'d7',kind:'check',kindLabel:'Check result',icon:'check',ticket:'DT-47',ticketId:'DT-47',ticketTitle:'Opening hours page',when:'today 09:15',need:'Done when is not fully covered',title:'New opening hours on the website',
  why:'The helper says this is ready for your check.',okLabel:'Looks good',open:'https://example.com/pull/12',
  then:'The ticket is done as it is, although pull request #12 is not merged yet. The missing part is dropped: no new ticket is made for it. To get it done, press Send back and say what is missing; a helper then works on it in this ticket.',
  files:[{label:'Opening hours page',type:'page',src:window.SWIPE_KIT+'samples/sample-page.html'},{label:'Door poster',type:'img',src:window.SWIPE_KIT+'demo-image.svg'},{label:'Shop window photo 1',type:'img',src:window.SWIPE_KIT+'demo-image.svg'},{label:'Shop window photo 2',type:'img',src:window.SWIPE_KIT+'demo-image.svg'},{label:'Shop window photo 3',type:'img',src:window.SWIPE_KIT+'demo-image.svg'},{label:'Shop window photo 4',type:'img',src:window.SWIPE_KIT+'demo-image.svg'},{label:'Shop window photo 5',type:'img',src:window.SWIPE_KIT+'demo-image.svg'},{label:'Shop window photo 6',type:'img',src:window.SWIPE_KIT+'demo-image.svg'}],/* the result's own files (ORCH-183); eight: 5 tiles and "+3 more" (ORCH-421) */
  preview:{type:'doc',heading:'What was done',paras:['In short: Sunday 9–13 is on the website and the Google entry.','No task covers: “the poster at the door shows it”','What to do: send it back and say which part is missing, or approve it if that part does not matter.'],
   steps:['Done: Change the hours on the website — Page now says Sunday 9:00 – 13:00 · Ran: page check (all links fine) · PR #12','Done: Update the Google entry — Saved; Google shows the new hours']}},
 {id:'d8',kind:'check',kindLabel:'Check result',icon:'check',ticket:'DT-48',ticketId:'DT-48',ticketTitle:'Supplier call',when:'today 09:20',title:'Call the supplier about oat milk',
  why:'The helper says this is ready for your check.',okLabel:'Looks good',
  then:'The ticket is done. Nothing else starts: no new ticket, no more work. To change something, press Send back and say what; a helper then works on it in this ticket.',
  preview:{type:'doc',heading:'What was done',paras:['In short: The supplier delivers oat milk from Monday, 12 cartons a week.','Done when: The supplier confirmed a weekly oat milk order','Part of: DT-38 Customer survey']}},
 {id:'d9',kind:'check',kindLabel:'Check result',icon:'check',ticket:'DT-49',ticketId:'DT-49',ticketTitle:'Lunch plan',when:'today 09:24',need:'Looks good is off',title:'Lunch plan for Friday',
  why:'The helper says this is ready for your check.',okLabel:'Looks good',
  then:'The ticket is done. Nothing else starts: no new ticket, no more work. To change something, press Send back and say what; a helper then works on it in this ticket.',blocked:'1 step is not finished. Send it back to get it done.',/* ORCH-548: Looks good is off and says why */
  preview:{type:'doc',progress:{done:1,total:2},steps:['Done: Ask the team what they want','Open: Book the table']}},
 {id:'d6',kind:'draft',kindLabel:'Draft',icon:'image',ticket:'DT-29',ticketId:'DT-29',ticketTitle:'Invoice export',task:'d6',about:'Design the export screen',when:'Thu 16:20',title:'Invoice export screen',
  why:'New screen for the October export.',okLabel:'Build it',
  then:'The helper builds the screen. You check it before it is used.',
  preview:{type:'img',src:window.SWIPE_KIT+'demo-image.svg',alt:'Invoice export screen draft'}}
];
/* ORCH-1847: a plain, reversible question with short named answers (orch marks it one_tap): each answer records the
   ticket answer in one tap, Undo while it is held. Shown alone with review.html?one=1. */
window.SWIPE_ONE={id:'one1',kind:'choice',kindLabel:'Choose',icon:'cards',ticket:'DT-70',ticketId:'DT-70',ticketTitle:'Answer the supplier about the delivery date',oneTap:true,when:'today 11:20',
 title:'The supplier can deliver on Tuesday or Thursday. Which day?',preview:{type:'options',options:[{id:'Tuesday',title:'Tuesday',suggested:true},{id:'Thursday',title:'Thursday'}]}};

/* Review overhaul (owner's picks 25 Nov 2026): every card carries the name orch gives its kind and its lane (as
   orch/cardkinds.py and UI.review.mapCard do), and the list shows what holds up work first, then by what you do. */
(()=>{const LANE={holds_up:'Holds up work now',click:'Only you can press it',help:'Needs you in person',look:'Look at the result'},ORDER=Object.keys(LANE);
 const of=it=>{const p=it.preview||{},files=it.files||[];
  if(it.kind==='stuck')return ['Stuck','pause','holds_up'];
  if(it.kind==='link')return ['Put it live','link','click'];
  if(it.kind==='run')return it.run&&it.run.class==='orch'?['Run it','code','click']:['Try it yourself','user','help'];
  if(p.type==='options')return p.before||(p.options||[]).some(o=>o.preview)?['Choice','cards','holds_up']:['Question','comment','holds_up'];
  if(it.kind==='question')return ['Question','comment','holds_up'];
  if(p.type==='compare')return ['Before and after','compare','look'];
  if(p.type==='img'||p.type==='page'||files.some(f=>f.type==='img'||f.type==='page'))return ['Pictures','image','look'];
  if(p.type==='table'||p.chart)return ['Numbers','chart','look'];
  if(p.diff)return ['Changed words','diff','look'];
  if(p.status||(p.chips||[]).length)return ['Test results','check','look'];
  return ['Document','file','look']};
 const put=list=>list.forEach(it=>{const [n,i,l]=of(it);it.kindLabel=n;it.icon=i;it.lane=l;it.laneName=LANE[l];
  if(it.kind==='check'&&it.preview&&it.preview.headline){it.title=it.preview.headline;delete it.preview.headline}});
 put(window.SWIPE_ITEMS);if(window.SWIPE_ONE)put([window.SWIPE_ONE]);
 window.SWIPE_ITEMS=window.SWIPE_ITEMS.map((it,i)=>[it,i]).sort((a,b)=>ORDER.indexOf(a[0].lane)-ORDER.indexOf(b[0].lane)||a[1]-b[1]).map(x=>x[0])})();

/* Focused review C (ORCH-2184, owner's words of 26 Nov): each card's attention group as orch/attention.py gives it
   (Take your time: puts something live, you try it yourself, or its words name money, deleting, sending out, logins;
   Quick look: only a passed test result, the Reviewer's proposed accept or a one-tap question; Short decision: the
   rest, and anything unknown). One card has a deadline (orch ask --due) for the tile's "Next deadline". */
(()=>{const G={quick:'Quick look',short:'Short decision',time:'Take your time'};
 const RISK=/(€|\$|\bprice|\bpay|\bbuy|\bcost|delet|remov|publish|send\b|\bmail\b|customers|everyone|\blive\b|sign in|login|password|\bkey\b)/i;
 const PROPOSED=['d5','x5','x4','d2'],NAMES=['o2','o3'];/* the Reviewer checked these (Reviewer mode propose); two are about words */
 const of=it=>{const words=[it.title,it.text,it.ifWait].concat(it.facts||[]).filter(Boolean).join(' ');
  if(NAMES.includes(it.id))return ['time','it is about words or names'];
  if(PROPOSED.includes(it.id)&&it.kind==='check')return ['quick','the Reviewer proposes to accept'];
  if(it.kindLabel==='Put it live')return ['time','it puts something live'];
  if(it.kindLabel==='Try it yourself')return ['time','you try it yourself'];
  if(RISK.test(words))return ['time','goes live or out to others'];
  if(it.kindLabel==='Test results'&&!(it.preview&&it.preview.status&&it.preview.status.tone==='failed'))return ['quick','small and tested'];
  if(it.proposal&&it.proposal.verdict==='accept')return ['quick','the Reviewer proposes to accept'];
  if(it.oneTap)return ['quick','one tap, and you can undo it'];
  if(it.kindLabel==='Document'&&!it.files)return ['quick','small and tested'];
  return ['short',it.kindLabel==='Question'||it.kindLabel==='Choice'?'one clear question':'needs a look']};
 const put=list=>list.forEach(it=>{const [g,why]=of(it);it.attention={group:g,name:G[g],why}});
 put(window.SWIPE_ITEMS);if(window.SWIPE_ONE)put([window.SWIPE_ONE]);
 const t=new Date();t.setDate(t.getDate()+1);t.setHours(9,0,0,0);const d8=window.SWIPE_ITEMS.find(it=>it.id==='d8');if(d8)d8.due=t.toISOString()})();

/* Focused review E (ORCH-2186): with ?decide=1 one ideas card (orch ask --idea): Keep / Later / No per idea, Save in the
   bar; saving part is fine. In Take your time (you sort the ideas yourself), in the Look at the result lane. */
(()=>{if(!/[?&]decide\b/.test(location.search))return;const L=window.SWIPE_ITEMS,at=L.findIndex(it=>it.lane==='proposed');
 const ideas=['One winter with a heat pump: the Meier family, 3 short posts','Advent calendar with 24 saving tips','Answer the 5 most asked questions, one per week','60-second video with an installer (CHF 900 for the filming)','Live question hour on LinkedIn'];
 L.splice(at<0?L.length:at,0,{id:'i1',kind:'draft',kindLabel:'Document',icon:'file',lane:'look',laneName:'Look at the result',ticket:'NOR-76',ticketId:'t_nor76',ticketTitle:'Content ideas for December',
  title:'Content ideas for December',text:'Which content ideas should the helper work out?',ifWait:'Nothing is held up. December planning starts next week.',
  facts:['Posts with a real customer got 3 times more clicks than product posts in October','Video is missing: 0 of 22 posts last month','Three ideas need no budget'],
  ideas,preview:{type:'doc',steps:ideas},attention:{group:'time',name:'Take your time',why:'you sort the ideas yourself'}})})();
