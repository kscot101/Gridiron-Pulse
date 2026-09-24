/* Exact saved numbers, not generic HIT labels. Season projections are unchanged. */
(function(root){
  'use strict';
  var data=null, mode='v2.1-tracked-1', timer=null;
  var labels={passing_yards:'Passing yards',passing_tds:'Passing TD',rushing_yards:'Rushing yards',rushing_tds:'Rushing TD',receiving_yards:'Receiving yards',receiving_tds:'Receiving TD',scrimmage_yards:'Rush + receiving yards',scrimmage_tds:'Rush + receiving TD',receptions:'Receptions',targets:'Targets',carries:'Carries'};
  function arr(v){return Array.isArray(v)?v:[];}
  function esc(v){return String(v==null?'':v).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});}
  function num(v){return v==null||typeof v==='boolean'||String(v).trim()===''?null:Number.isFinite(Number(v))?Number(v):null;}
  function fmt(v){var n=num(v);return n==null?'\u2014':n.toLocaleString(undefined,{maximumFractionDigits:2});}
  function date(v){var t=Date.parse(v);return Number.isFinite(t)?new Date(t).toLocaleString(undefined,{month:'short',day:'numeric',hour:'numeric',minute:'2-digit'}):'Unavailable';}
  function tm(v){return {WSH:'WAS',JAC:'JAX',LA:'LAR'}[v]||v;}
  function player(r){return {name:r.playerName,athleteId:r.athleteId,player_id:r.player_id,position:r.position,team:r.team};}
  function nameLink(r){return root.GPPlayerStats?GPPlayerStats.link(player(r),r.playerName):esc(r.playerName);}
  function favorites(){try{var x=JSON.parse(localStorage.getItem('gridironPulseFavoritesV1')||'{}');return {players:arr(x.players),teams:arr(x.teams)};}catch(e){return {players:[],teams:[]};}}
  function followed(r){return favorites().players.some(function(p){return String(p.athleteId||p.key)===String(r.athleteId);});}
  function follow(r){var f=favorites(),i=f.players.findIndex(function(p){return String(p.athleteId||p.key)===String(r.athleteId);});if(i>=0)f.players.splice(i,1);else f.players.push({key:String(r.athleteId),athleteId:String(r.athleteId),name:r.playerName,team:r.team,position:r.position});localStorage.setItem('gridironPulseFavoritesV1',JSON.stringify(f));renderPage();}
  function find(p, selected){
    if(!data||!p)return null;
    var id=String(p.athleteId||p.espnId||''),gid=p.gameId;
    if(!gid&&typeof root.allBoards==='function'){
      var matches=root.allBoards().filter(function(b){return arr(b.picks).some(function(q){return String(q.athleteId)===id&&tm(q.team)===tm(p.team);});});
      if(matches.length===1)gid=matches[0].gameId;
    }
    return data.forecasts.find(function(r){return r.model===(selected||mode)&&r.athleteId===id&&r.gameId===String(gid)&&tm(r.team)===tm(p.team);})||null;
  }
  function strip(r){
    if(!r)return '<p class="gp-exact-note">No eligible saved forecast for this player/game in this view.</p>';
    return '<div class="gp-exact" data-record-id="'+esc(r.id)+'"><small>'+esc(r.model==='workload-trial-1'?'WORKLOAD TRIAL':'TRACKED v2.1')+' \u00b7 Saved '+esc(date(r.recordedAt))+'</small><div class="gp-exact-strip">'+Object.keys(r.predictions).map(function(k){return '<div><strong data-metric="'+esc(k)+'">'+fmt(r.predictions[k])+'</strong><span>'+esc(labels[k]||k)+'</span></div>';}).join('')+'</div><small>Frozen pregame estimate; TD values are expected counts, not scoring probabilities.</small></div>';
  }
  function bindHomepage(){
    if(typeof root.playerProjectionMarkup!=='function')return;
    root.playerProjectionMarkup=function(p){return strip(find(p));};
    root.spotlightPickedProjections=function(picks){var cards=arr(picks).slice(0,4).map(function(p){var r=find(p);return r?'<article class="gp-exact-spot"><b>'+nameLink(r)+'</b>'+strip(r)+'</article>':'';}).join('');return cards?'<div class="spotlight-player-block"><strong>Saved player projections</strong><div class="gp-exact-spot-grid">'+cards+'</div></div>':'';};
    var actions=document.querySelector('.hero-actions');
    if(actions&&!document.getElementById('gp-trial-switch')){
      var wrap=document.createElement('label');wrap.className='gp-exact-switch';wrap.innerHTML='<input type="checkbox" id="gp-trial-switch"> Show workload trial on cards';actions.after(wrap);
      var input=wrap.querySelector('input');input.checked=mode==='workload-trial-1';input.addEventListener('change',function(){mode=input.checked?'workload-trial-1':'v2.1-tracked-1';try{localStorage.setItem('gpProjectionView',mode);}catch(e){}repaint();});
    }
    repaint();
  }
  function repaint(){if(typeof root.renderSpotlight==='function')root.renderSpotlight();if(typeof root.renderEdges==='function')root.renderEdges();}
  function card(group){
    var r=group[0],baseline=group.find(function(x){return x.model==='v2.1-tracked-1';}),trial=group.find(function(x){return x.model==='workload-trial-1';});
    var metrics=Array.from(new Set(group.flatMap(function(x){return Object.keys(x.predictions);}))),outcomes=data.outcomes||{};
    var rows=metrics.map(function(k){
      var b=baseline&&baseline.predictions[k],t=trial&&trial.predictions[k],bo=baseline&&((outcomes[baseline.id]||{}).metrics||{})[k],to=trial&&((outcomes[trial.id]||{}).metrics||{})[k],actual=to&&to.actual!=null?to.actual:bo&&bo.actual;
      return '<tr><th scope="row">'+esc(labels[k]||k)+'</th><td>'+fmt(b)+'</td><td class="gp-trial-value">'+fmt(t)+'</td><td>'+fmt(actual)+'</td></tr>';
    }).join('');
    var errors=group.map(function(x){var o=outcomes[x.id];if(!o||!o.metrics)return '';return '<p><b>'+esc(x.model==='workload-trial-1'?'Workload trial':'v2.1')+'</b></p>'+Object.keys(o.metrics).map(function(k){var e=o.metrics[k];return '<p>'+esc(labels[k]||k)+': '+(e.status==='GRADED'?'absolute error '+fmt(e.absoluteError)+'; actual minus forecast '+fmt(e.error):'Not graded: statistic unavailable')+'</p>';}).join('');
    return '<article class="gp-trial-card" data-athlete="'+esc(r.athleteId)+'"><header><div><small>'+esc(r.team+' vs '+r.opponent+' / '+r.position)+' \u00b7 '+esc(date(r.kickoff))+'</small><h2>'+nameLink(r)+'</h2></div><button type="button" class="gp-trial-follow" data-follow="'+esc(r.id)+'" aria-pressed="'+followed(r)+'">'+(followed(r)?'Following':'Follow')+'</button></header><div class="gp-trial-table-wrap"><table><thead><tr><th>Stat</th><th>v2.1</th><th>Trial</th><th>Actual</th></tr></thead><tbody>'+rows+'</tbody></table></div><footer><span>'+esc(errors?'Final stats available':'Awaiting final stats')+'</span><details><summary>Saved forecast details</summary>'+group.map(function(x){return '<p>'+esc(x.model)+': captured '+esc(date(x.recordedAt))+'. '+(x.historyGames?esc(x.historyGames+' earlier same-team appearances; '+x.currentSeasonGames+' this season. '):'')+'Forecast fingerprint '+esc(x.forecastHash.slice(0,12))+'.</p>';}).join('')+errors+'<p>Forecasts are conditional on playing and do not update after capture. A missing line is not a zero.</p></details></footer></article>';
  }
  function renderPage(){
    if(!data||!document.getElementById('gp-trial-cards'))return;
    var position=document.getElementById('gp-position').value,query=document.getElementById('gp-search').value.toLowerCase().trim(),favs=document.getElementById('gp-favorites').checked;
    var filtered=data.forecasts.filter(function(r){return (position==='all'||r.position===position)&&(!query||(r.playerName+' '+r.team+' '+r.opponent).toLowerCase().includes(query))&&(!favs||followed(r));});
    var groups=new Map();filtered.forEach(function(r){var k=r.gameId+'|'+r.athleteId;if(!groups.has(k))groups.set(k,[]);groups.get(k).push(r);});
    document.getElementById('gp-trial-cards').innerHTML=Array.from(groups.values()).sort(function(a,b){return Date.parse(a[0].kickoff)-Date.parse(b[0].kickoff)||a[0].playerName.localeCompare(b[0].playerName);}).map(card).join('')||'<p class="gp-trial-empty">No saved forecasts match this filter.</p>';
    document.getElementById('gp-trial-count').textContent=groups.size+' player matchups';
    var graded=arr(data.metrics).reduce(function(n,r){return n+r.graded;},0);
    document.getElementById('gp-trial-status').textContent='Week '+data.week+' / '+data.season+' \u00b7 Updated '+date(data.generatedAt)+' \u00b7 '+graded+' completed forecast-stat grades';
    document.getElementById('gp-trial-warnings').textContent=arr(data.warnings).join(' ');
    var paired=arr(data.pairedComparisons);
    document.getElementById('gp-trial-live-results').innerHTML=paired.length?'<div class="gp-trial-table-wrap"><table><thead><tr><th>Position / stat</th><th>Paired forecasts</th><th>v2.1 error</th><th>Trial error</th></tr></thead><tbody>'+paired.map(function(r){return '<tr><th>'+esc(r.position+' / '+labels[r.metric])+'</th><td>'+r.n+'</td><td>'+fmt(r.baselineMAE)+'</td><td>'+fmt(r.trialMAE)+'</td></tr>';}).join('')+'</tbody></table></div>':'<p>No completed paired forecasts yet. This tracker starts with forecasts saved before kickoff; it does not invent predictions for past games.</p>';
    var c=data.calibration||{};
    document.getElementById('gp-trial-holdout').innerHTML='<div class="gp-trial-table-wrap"><table><thead><tr><th>Position / yardage</th><th>Paired games</th><th>Last 5 error</th><th>Trial error</th></tr></thead><tbody>'+arr(c.holdout).map(function(r){return '<tr><th>'+esc(r.position+' / '+labels[r.metric])+'</th><td>'+r.pairedRows+'</td><td>'+fmt(r.last5.mae)+'</td><td>'+fmt(r.trial.mae)+'</td></tr>';}).join('')+'</tbody></table></div><p>League efficiencies: 2022\u201323. Settings selected on 2024. Test year: 2025. Lower average absolute error is better. These are retrospective individual-game tests against simple baselines, not live wins or a direct comparison with v2.1.</p>';
  }
  async function load(){
    try{
      var response=await fetch('./data/projection-trial.json?t='+Date.now(),{cache:'no-store',signal:AbortSignal.timeout(20000)});if(!response.ok)throw Error('Saved trial data unavailable');
      var next=await response.json();if(!Array.isArray(next.forecasts)||!next.trialOnly)throw Error('Invalid trial feed');data=next;root.GPExactTracker.data=data;
      bindHomepage();renderPage();
    }catch(error){var status=document.getElementById('gp-trial-status');if(status)status.textContent='Trial data is temporarily unavailable. No forecasts have been fabricated.';}
    clearTimeout(timer);timer=setTimeout(load,300000);
  }
  root.GPExactTracker={data:null,find:find,format:fmt,strip:strip};
  function init(){
    try{if(localStorage.getItem('gpProjectionView')==='workload-trial-1')mode='workload-trial-1';}catch(e){}
    ['gp-position','gp-search','gp-favorites'].forEach(function(id){var el=document.getElementById(id);if(el)el.addEventListener(id==='gp-search'?'input':'change',renderPage);});
    document.addEventListener('click',function(e){var b=e.target.closest('[data-follow]');if(!b||!data)return;var r=data.forecasts.find(function(r){return r.id===b.dataset.follow;});if(r)follow(r);});
    root.addEventListener('storage',renderPage);load();
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
})(window);
