/* Saved forecasts are durable until their exact matchup starts.
   This layer never changes model values, live scores, grades or capture times. */
(function(root){
  'use strict';
  if(root.GPSavedPicks)return;
  var HOUR=3600000, saved=null, schedule=null, timer=null, expanded=false, observed=false;
  var metrics={passing_yards:'Passing yards',passing_tds:'Passing TD',rushing_yards:'Rushing yards',rushing_tds:'Rushing TD',receiving_yards:'Receiving yards',receiving_tds:'Receiving TD',scrimmage_yards:'Rush + receiving yards',scrimmage_tds:'Rush + receiving TD',receptions:'Receptions',targets:'Targets',carries:'Carries'};
  function list(v){return Array.isArray(v)?v:[];}
  function tm(v){v=String(v||'').toUpperCase();return {WSH:'WAS',JAC:'JAX',LA:'LAR',OAK:'LV',SD:'LAC'}[v]||v;}
  function esc(v){return String(v==null?'':v).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});}
  function at(v){return Date.parse(v||'');}
  function when(v){return new Date(v).toLocaleString(undefined,{month:'short',day:'numeric',hour:'numeric',minute:'2-digit'});}
  function model(){var box=root.document&&document.getElementById('gp-trial-switch');if(box)return box.checked?'workload-trial-1':'v2.1-tracked-1';try{return localStorage.getItem('gpProjectionView')==='workload-trial-1'?'workload-trial-1':'v2.1-tracked-1';}catch(e){return 'v2.1-tracked-1';}}
  function select(data,mirror,now,selected){
    if(!data||data.trialOnly!==true||!mirror||mirror.ok!==true)return [];
    var checked=at(mirror.fetchedAt),board=mirror.scoreboard;
    // A saved schedule can identify future matchups, but is never a live score.
    if(!Number.isFinite(checked)||checked>now+300000||now-checked>72*HOUR||!board||!board.season)return [];
    var games=new Map(list(board.events).map(function(g){return [String(g.id),g];})),unique=new Map();
    list(data.forecasts).forEach(function(r){
      var g=games.get(String(r.gameId)),c=g&&list(g.competitions)[0],s=g&&((g.status||{}).type||(c&&c.status||{}).type)||{};
      var kick=at(r.kickoff),captured=at(r.recordedAt),source=at(r.sourceGeneratedAt);
      if(!g||!c||s.state!=='pre'||s.completed||/cancel|postpon|suspend/i.test(String(s.name||'')+' '+String(s.description||'')))return;
      if(![kick,captured,source].every(Number.isFinite)||kick<=now||kick-now>8*24*HOUR||captured>now+300000||captured>=kick-300000||source>captured+300000||captured-source>3*HOUR)return;
      if(!Number.isFinite(at(g.date))||Math.abs(at(g.date)-kick)>300000||Number(r.season)!==Number(board.season.year)||Number(r.week)!==Number((board.week||{}).number)||Number(board.season.type)!==2)return;
      var teams=list(c.competitors).map(function(t){return tm((t.team||{}).abbreviation);});
      if(teams.length!==2||!teams.includes(tm(r.team))||!teams.includes(tm(r.opponent))||tm(r.team)===tm(r.opponent))return;
      if(!['QB','RB','WR','TE'].includes(r.position)||!['v2.1-tracked-1','workload-trial-1'].includes(r.model)||!/^\d+$/.test(String(r.athleteId||'')))return;
      if(r.id!==[r.gameId,r.athleteId,r.model].join('|')||!/^[a-f0-9]{64}$/.test(r.forecastHash||''))return;
      if((data.outcomes||{})[r.id]&&data.outcomes[r.id].status==='INVALID_CAPTURE')return;
      var keys=Object.keys(r.predictions||{});
      if(!keys.length||keys.some(function(k){return !metrics[k]||typeof r.predictions[k]!=='number'||!Number.isFinite(r.predictions[k]);}))return;
      var key=[r.gameId,r.athleteId].join('|'),prev=unique.get(key);
      // Prefer the user's selected model. Other-model availability is disclosed.
      if(!prev||r.model===selected)unique.set(key,Object.assign({},r,{scheduleGame:g,modelFallback:r.model!==selected}));
    });
    return Array.from(unique.values()).sort(function(a,b){return at(a.kickoff)-at(b.kickoff)||a.modelFallback-b.modelFallback||String(a.playerName).localeCompare(String(b.playerName));});
  }
  function filtered(rows){
    var selected=root.state&&root.state.edge;
    if(selected==='qb')return rows.filter(function(r){return r.position==='QB';});
    if(selected==='stars')return rows.filter(function(r){return r.position!=='QB';});
    if(selected!=='favorites')return rows;
    var favorites=root.state&&root.state.favorites||{};
    return rows.filter(function(r){
      var comp=list(r.scheduleGame.competitions)[0]||{};
      var side=list(comp.competitors).find(function(c){return tm((c.team||{}).abbreviation)===tm(r.team);});
      var tid=String(side&&side.team&&side.team.id||'');
      return list(favorites.players).some(function(p){return String(p.athleteId||p.key)===String(r.athleteId);})||list(favorites.teams).some(function(t){return tm(t.abbreviation||t.team||t.key)===tm(r.team)||(tid&&String(t.key||t.id||t.teamId)===tid);});
    });
  }
  function card(r){
    var p={name:r.playerName,athleteId:r.athleteId,player_id:r.player_id,position:r.position,team:r.team,gameId:r.gameId,opponent:r.opponent};
    var name=root.GPPlayerStats?root.GPPlayerStats.link(p,r.playerName):esc(r.playerName);
    var reason=root.GPPickReasons?root.GPPickReasons.markup(r):'';
    var details=root.GPPickReasons?root.GPPickReasons.details(r):'<p>Pregame estimate. Saved '+esc(when(r.recordedAt))+'</p>';
    return '<article class="ds-pick" data-saved-record="'+esc(r.id)+'"><small>'+esc(r.team+' vs '+r.opponent+' / '+r.position)+'</small><h3>'+name+'</h3>'+reason+'<div class="ds-values">'+Object.keys(r.predictions).map(function(k){return '<div><strong data-saved-metric="'+esc(k)+'">'+esc(r.predictions[k].toLocaleString(undefined,{maximumFractionDigits:2}))+'</strong><span>'+esc(metrics[k])+'</span></div>';}).join('')+'</div>'+details+'</article>';
  }
  function host(id,before){var e=document.getElementById(id);if(!e&&before){e=document.createElement('section');e.id=id;e.className='ds-panel';e.hidden=true;before.before(e);}return e;}
  function paint(){
    if(!root.document||!document.getElementById('spotlight-game'))return;
    var native=document.getElementById('spotlight-game'),edge=document.getElementById('edge-grid');
    var spot=host('gp-saved-spotlight',native),picks=host('gp-saved-picks',edge);
    var rows=select(saved,schedule,Date.now(),model());root.GPSavedPicks.visible=rows;
    var use=rows.length>0&&!native.querySelector('[data-record-id]');
    native.hidden=use;spot.hidden=!use;
    if(use){
      var first=rows[0],game=first.scheduleGame,gameRows=rows.filter(function(r){return r.gameId===first.gameId;}).slice(0,4);
      spot.innerHTML='<div class="ds-heading"><span>SPOTLIGHT PICKS</span><strong>'+esc(game.shortName||game.name||first.team+' vs '+first.opponent)+'</strong><small>'+esc(when(first.kickoff))+'</small></div><p class="ds-note">Players to watch in this matchup. See their recent production, opponent context and projected stats below.</p><div class="ds-grid">'+gameRows.map(card).join('')+'</div><p class="ds-foot">Pregame estimates, not guarantees. Check player availability before kickoff.</p><a class="ds-link" href="#player-edge">See all upcoming picks</a>';
    }else spot.replaceChildren();
    var shown=filtered(rows);
    var show=rows.length>0&&edge&&!edge.querySelector('[data-record-id]');
    if(picks){
      picks.hidden=!show;if(edge)edge.hidden=show;
      if(show)picks.innerHTML='<div class="ds-heading"><span>PLAYERS TO WATCH</span><strong>'+shown.length+' player matchups</strong></div><p class="ds-note">See the recent usage, production and opponent context behind each featured name. Tap a player for recent games and head-to-head history.</p><div class="ds-grid">'+(shown.length?(expanded?shown:shown.slice(0,6)).map(card).join(''):'<p class="ds-note">No saved picks match this filter.</p>')+'</div>'+(shown.length>6?'<button type="button" class="ds-expand" aria-expanded="'+expanded+'">'+(expanded?'Show fewer':'Show all '+shown.length+' picks')+'</button>':'');
      else picks.replaceChildren();
    }
    if(!rows.length&&!native.querySelector('[data-record-id]')){
      var note=document.getElementById('gp-saved-empty');
      if(!note){note=document.createElement('p');note.id='gp-saved-empty';note.className='ds-empty';native.after(note);}
      note.innerHTML='No verified upcoming saved picks are available yet. Started or completed matchups are kept in the <a href="pick-tracker.html">Pick Tracker</a>, not shown as new picks.';
    }else{var old=document.getElementById('gp-saved-empty');if(old)old.remove();}
  }
  async function read(path){var ctl=new AbortController(),end=setTimeout(function(){ctl.abort();},8000);try{var r=await fetch(path+'?saved='+Math.floor(Date.now()/60000),{cache:'no-cache',signal:ctl.signal});if(!r.ok)throw Error('Saved-pick source unavailable');return await r.json();}finally{clearTimeout(end);}}
  async function load(){
    var result=await Promise.allSettled([read('./data/projection-trial.json'),read('./data/homepage-scoreboard.json')]);
    if(result[0].status==='fulfilled'&&Array.isArray(result[0].value.forecasts)&&(!saved||at(result[0].value.generatedAt)>=at(saved.generatedAt)))saved=result[0].value;
    if(result[1].status==='fulfilled'&&result[1].value.ok===true&&(!schedule||at(result[1].value.fetchedAt)>=at(schedule.fetchedAt)))schedule=result[1].value;
    paint();clearTimeout(timer);timer=setTimeout(load,60000);
  }
  function init(){
    if(!document.getElementById('spotlight-game'))return;
    if(!observed){
      observed=true;var queued=false;
      var ob=new MutationObserver(function(){if(queued)return;queued=true;requestAnimationFrame(function(){queued=false;paint();});});
      ['spotlight-game','edge-grid'].forEach(function(id){var el=document.getElementById(id);if(el)ob.observe(el,{childList:true,subtree:true});});
      document.addEventListener('change',function(e){if(e.target.id==='gp-trial-switch')paint();});
      document.addEventListener('click',function(e){if(e.target.closest('[data-edge]')){expanded=false;requestAnimationFrame(paint);}if(e.target.closest('.ds-expand')){expanded=!expanded;paint();}});
      document.addEventListener('visibilitychange',function(){if(!document.hidden){paint();load();}});
      setInterval(paint,30000);
    }
    load();
  }
  root.GPSavedPicks={select:select,paint:paint,visible:[]};
  if(typeof module!=='undefined'&&module.exports)module.exports=root.GPSavedPicks;
  if(root.document){if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();}
})(typeof window!=='undefined'?window:globalThis);

// PLAIN_PICK_COPY_20261030
