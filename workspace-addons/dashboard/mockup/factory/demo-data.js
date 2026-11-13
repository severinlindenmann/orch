/* Fixed demo fixtures. No services, keys, or network calls. */
window.FactoryData = {
  booking: {title:'Online booking page', time:'~2 h', cost:12, eta:'today 18:30–19:30', done:['Customers can choose a service and available time.','A booking shows a clear confirmation.','The page works on a phone and with a keyboard.','Anna can change opening hours without changing code.'], wont:'No payments, customer accounts, or changes to other workspaces.', ship:'Add the reviewed page to the Demo website’s main branch. Only your final Ship approves this.'},
  campaign: {title:'Spring campaign',time:'~45 min',cost:6,eta:'today 18:45',done:['One email and two social posts are ready.','Every link points to the spring collection.','The launch date is 31 March.','Anna approves the copy before anything is sent.'],wont:'No paid ads, new mailing connections, or automatic sending.',ship:'Save the approved email and two social posts in Demo, ready for the 31 March launch. Nothing is sent.'},
  decisions:[
    {title:'Split slow test file into 3',why:'Independent tests can run together. The same 38 checks pass.',result:'−40 s per test run · 09:12'},
    {title:'Archived 4 stale tickets',why:'No activity for 90 days; all four were already finished.',result:'Board is easier to scan · 10:08'},
    {title:'Renamed board column “Doing” → “Working”',why:'Matches the words Anna and Ben use elsewhere in Demo.',result:'House rule: use plain English · 10:42'},
    {title:'Removed duplicate test setup',why:'Two identical fixtures were safe to share.',result:'No acceptance points changed · 11:10'},
    {title:'Grouped finished campaign tickets',why:'Approved board rule keeps finished work together.',result:'One reversible board move · 12:02'},
    {title:'Started a small order to tidy test names',why:'Within the approved test cleanup goal and $3 order limit.',result:'1 of 2 orders active · 13:20'},
    {title:'Shortened the daily report',why:'Anna asked for decisions first and details below.',result:'Taste decision within the reporting house rule · 14:15'}
  ],
  rules:[['House rules','Keep changes small and reversible. Use plain English.'],['Your time','Ask Anna or Ben together at 18:30; aim for 10 minutes a day.'],['Notifications','Send one daily digest. Interrupt only for a blocked stop.'],['Default line','Draft → Build → Check → Ship it? Always ask before shipping.'],['Crew per role','Helper manages with Claude API · Codex builds · Claude API reviews.']]
};
