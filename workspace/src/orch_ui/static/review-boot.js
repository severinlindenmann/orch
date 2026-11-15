/* Boot for review.html (served by `orch review`): sign in with the one-time #t=<token> fragment, then start the page.
   External file on purpose: the page runs under a strict CSP (no inline script, no inline handlers). */
(()=>{'use strict';
const host=document.getElementById('review-host');
const start=()=>UI.reviewPage(host,UI.reviewFetchApi(''),{nav:document.getElementById('review-nav'),meta:document.getElementById('review-meta')});
const m=/[#&]t=([^&]+)/.exec(location.hash);
if(!m)return start();
let token='';try{token=decodeURIComponent(m[1])}catch{}
history.replaceState(null,'',location.pathname+location.search);/* the token never stays in the address bar */
fetch('/session',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({token})}).catch(()=>{}).then(start);
})();
