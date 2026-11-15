/* Boot for review.html (served by `orch review`): sign in with the one-time #launch=<token> fragment (also #t=),
   keep the page secret for this tab, add it as X-Orch-Page to every same-origin request (pageproof: cookie + secret),
   then start the page. External file on purpose: the page runs under a strict CSP (no inline script). */
(()=>{'use strict';
const host=document.getElementById('review-host');
const KEY='orch_review_secret';
const secret=()=>{try{return sessionStorage.getItem(KEY)||''}catch{return ''}};
const f=window.fetch.bind(window);
window.fetch=(u,o)=>{o=Object.assign({},o||{});const h=new Headers(o.headers||{});const s=secret();
 if(s&&String(u).startsWith('/'))h.set('X-Orch-Page',s);o.headers=h;
 if(String(u).startsWith('/')&&(o.method||'GET')!=='GET'&&o.credentials===undefined)o.credentials='same-origin';return f(u,o)};
const start=()=>UI.reviewPage(host,UI.reviewFetchApi(''),{nav:document.getElementById('review-nav'),meta:document.getElementById('review-meta')});
const m=/[#&](?:t|launch)=([^&]+)/.exec(location.hash);
if(!m)return start();
let token='';try{token=decodeURIComponent(m[1])}catch{}
history.replaceState(null,'',location.pathname+location.search);
f('/session',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({token})})
 .then(r=>r.ok?r.json():null).then(j=>{if(j&&j.secret){try{sessionStorage.setItem(KEY,j.secret)}catch{}}}).catch(()=>{}).then(start);
})();
