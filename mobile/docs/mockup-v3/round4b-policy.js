function reducedMotion(){return matchMedia('(prefers-reduced-motion: reduce)').matches||document.getElementById('phone').classList.contains('reduce-motion');}
let lastListInteraction=0,listTouch=false,settledRows;
function chatListBusy(){return listTouch||Date.now()-lastListInteraction<240;}
