/* Completed-game rankings load independently from live games and next-game picks. */
(function(root){
  'use strict';
  if(root.GPPowerPulse)return;
  var HOUR=3600000, MAX_AGE=7*24*HOUR, saved=null, retry=null, pending=null;
  function arr(v){return Array.isArray(v)?v:[];}
  function stamp(v){return Date.parse(v||'');}
  function numeric(v){return typeof v==='number'&&Number.isFinite(v)?v:null;}
  function year(now){var d=new Date(now);return d.getUTCFullYear()-(d.getUTCMonth()<2?1:0);}
  function usable(power,now){
    if(!power||power.available!==true||!Number.isFinite(stamp(power.generatedAt)))return false;
    var age=now-stamp(power.generatedAt);
    if(age < -300000||age>MAX_AGE||Number(power.seasonYear)!==year(now))return false;
    if(![2,3].includes(Number(power.seasonType))||!Number.isInteger(Number(power.seasonWeek))||Number(power.seasonWeek)<1)return false;
    if(!Array.isArray(power.teams)||!Array.isArray(power.players)||!power.teams.length||!power.players.length)return false;
    return ['teams','players'].every(function(kind){
      var seen=new Set();return power[kind].every(function(r){
        var id=String(kind==='teams'?(r.teamId||r.abbreviation||''):(r.athleteId||r.key||''));
        var games=arr(r.recentGames),score=numeric(r.heatScore),sample=numeric(r.sampleSize);
        if(!id||seen.has(id)||score===null||score<0||score>100||sample===null||sample<1||!games.length)return false;
        seen.add(id);
        return games.every(function(g){var t=stamp(g.date);return g.gameId&&Number.isFinite(t)&&t<=stamp(power.generatedAt)+300000;});
      });
    });
  }
  function choose(candidates,now){
    now=now||Date.now();return arr(candidates).filter(function(p){return usable(p,now);})
      .sort(function(a,b){return stamp(b.generatedAt)-stamp(a.generatedAt);})[0]||null;
  }
  function current(snapshot,now){
    now=now||Date.now();return choose([snapshot&&snapshot.powerRankings,saved&&saved.rankings],now);
  }
  function unitSource(history,now){
    if(!history||!Number.isFinite(stamp(history.generatedAt)))return false;
    var age=now-stamp(history.generatedAt);
    return age>=-300000&&age<=MAX_AGE&&Array.isArray(history.teams);
  }
  function unitRow(id,history,now){
    if(!unitSource(history,now))return null;
    return history.teams.find(function(t){return String(t.teamId||t.id||'')===String(id)||String(t.abbreviation||t.team||'')===String(id);})||null;
  }
  function units(id,history,now){
    now=now||Date.now();var choices=[history,saved&&saved.units].filter(function(h){return unitSource(h,now);})
      .sort(function(a,b){return stamp(b.generatedAt)-stamp(a.generatedAt);});
    for(var i=0;i<choices.length;i++){
      var t=unitRow(id,choices[i],now),m=t&&t.metrics;
      if(t&&t.historical&&t.historical.active&&m&&['offensePulse','defensePulse','tandemPulse'].some(function(k){return numeric(m[k])!==null;}))return t;
    }
    return null;
  }
  function metric(item,key,history){var row=units(item&&item.teamId,history);return row?numeric((row.metrics||{})[key]):null;}
  function formatDate(v){return new Date(v).toLocaleString(undefined,{month:'short',day:'numeric',hour:'numeric',minute:'2-digit'});}
  function status(snapshot){
    if(!root.document)return;
    var box=document.getElementById('power-feed-status');if(!box)return;
    var power=current(snapshot),now=Date.now();
    if(power){
      var delayed=now-stamp(power.generatedAt)>72*HOUR;
      box.dataset.mode=delayed?'last-available':'saved';
      box.textContent=(delayed?'Last available rankings':'Rankings')+' - Week '+power.seasonWeek+' / '+power.seasonYear+' - Updated '+formatDate(power.generatedAt)+'. Based on completed games, not next-game predictions.';
    }else{
      box.dataset.mode=pending?'loading':'unavailable';
      box.textContent=pending?'Loading saved team and player rankings...':'Rankings are awaiting an update. No scores have been invented; current picks remain available above.';
    }
  }
  function repaint(){
    if(typeof root.renderPower==='function')root.renderPower();
    status(root.state&&root.state.snapshot);
  }
  async function load(){
    if(pending)return pending;
    var ctl=new AbortController(),timeout=setTimeout(function(){ctl.abort();},8000);
    pending=(async function(){
      try{
        var res=await root.fetch('./data/power-pulse.json?t='+Math.floor(Date.now()/60000),{cache:'no-cache',signal:ctl.signal});
        if(!res.ok)throw Error('Saved rankings unavailable');
        var next=await res.json();
        if(next.ok!==true||next.schemaVersion!==1||!usable(next.rankings,Date.now()))throw Error('Invalid or expired rankings');
        if(!saved||stamp(next.rankings.generatedAt)>=stamp(saved.rankings.generatedAt))saved=next;
      }catch(e){ /* Keep the last usable rankings; never clear them on a failed refresh. */ }
      finally{clearTimeout(timeout);pending=null;repaint();clearTimeout(retry);retry=setTimeout(load,60000);}
    })();
    return pending;
  }
  root.GPPowerPulse={usable:usable,choose:choose,current:current,units:units,metric:metric,status:status,load:load,MAX_AGE:MAX_AGE};
  if(typeof module!=='undefined'&&module.exports)module.exports=root.GPPowerPulse;
  if(root.document){
    function init(){if(!document.getElementById('power-grid'))return;load();repaint();document.addEventListener('visibilitychange',function(){if(!document.hidden){repaint();load();}});setInterval(repaint,60000);}
    if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
  }
})(typeof window!=='undefined'?window:globalThis);
