(()=>{
 const beans=document.querySelector('#beans'),gifts=document.querySelector('#gifts'),total=document.querySelector('#total'),error=document.querySelector('#quantity-error');
 function calculate(){
   const valid=[beans,gifts].every(input=>input.value!==''&&input.checkValidity());
   error.textContent=valid?'':'Choose a whole number from 0 to 99 for each item.';
   total.textContent=valid?'CHF '+((Number(beans.value)*950+Number(gifts.value)*2400)/100).toFixed(2):'—';
 }
 [beans,gifts].forEach(input=>input.addEventListener('input',calculate));
 document.querySelector('form').addEventListener('submit',event=>event.preventDefault());
 calculate();
})();
