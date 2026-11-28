/* Boot for review.html (served by `orch review`): sign in with the one-time #k=<token> fragment (the page posts it
   once to /session and gets an HttpOnly cookie that the browser sends on every same-origin request), then start
   the page. External file on purpose: the page runs under a strict CSP (no inline script). */
(()=>{'use strict';
const host=document.getElementById('review-host');
const api=UI.reviewFetchApi('');
/* ORCH-2187: the decision-first card when the workspace's switch is on (read with every list, so a change shows at the next poll) */
const start=()=>UI.reviewPage(host,api,{decisionFirst:()=>api.decisionFirst===true,nav:document.getElementById('review-nav'),meta:document.getElementById('review-meta'),startId:new URLSearchParams(location.search).get('card')||undefined});
const m=/[#&]k=([^&]+)/.exec(location.hash);
if(!m)return start();
let token='';try{token=decodeURIComponent(m[1])}catch{}
history.replaceState(null,'',location.pathname+location.search);
fetch('/session',{method:'POST',credentials:'same-origin',headers:{'content-type':'application/json'},body:JSON.stringify({token})})
 .catch(()=>{}).then(start);
})();
