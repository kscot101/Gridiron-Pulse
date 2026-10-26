/* Descriptive comparisons only. No changes to forecasts, favorites or grading. */
(function (root) {
  'use strict';
  if (root.GPMatchupComparisons) return;
  var src = document.currentScript.src, requests = {}, settings = new WeakMap(), serial = 0;
  var A = {LA:'LAR',STL:'LAR',WSH:'WAS',JAC:'JAX',SD:'LAC',OAK:'LV'};
  function team(v) { v=String(v||'').toUpperCase(); return A[v]||v; }
  function esc(v) {return String(v==null?'':v).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});}
  function num(v) {if(v==null||v===''||typeof v==='boolean')return null;var n=Number(v);return Number.isFinite(n)?n:null;}
  function fmt(v) {return num(v)==null?'Unavailable':Number(v).toLocaleString(undefined,{maximumFractionDigits:1});}
  function norm(v) {return String(v||'').toLowerCase().replace(/\b(jr|sr|ii|iii|iv|v)\b/g,'').replace(/[^a-z0-9]/g,'');}
  function date(v) {var d=new Date(String(v).length===10?v+'T12:00:00Z':v);return Number.isFinite(d.getTime())?d.toLocaleDateString(undefined,{month:'short',day:'numeric',year:'numeric'}):'Unavailable';}
  function currentSeason() {var d=new Date();return d.getUTCFullYear()-(d.getUTCMonth()<2?1:0);}
  function read(name) {
    if(requests[name])return requests[name];
    var controller=new AbortController(),timer=setTimeout(function(){controller.abort();},18000);
    requests[name]=fetch(new URL('../data/'+name+'.json',src).href+'?v='+Math.floor(Date.now()/900000),{signal:controller.signal,cache:'no-cache'})
      .then(function(r){if(!r.ok)throw Error('Statistics feed unavailable');return r.json();})
      .then(function(d){if(!d.ok||d.schemaVersion!==1)throw Error('Unrecognized statistics feed');return d;})
      .catch(function(e){delete requests[name];throw e;}).finally(function(){clearTimeout(timer);});
    return requests[name];
  }
  function sample(s) {return s&&s.n!=null?s.n+' / '+s.expected+' games':'No sample';}
  function stat(s) {return s&&num(s.value)!=null?s.value:null;}
  function bars(rows, label, unit) {
    var values=rows.map(function(r){return num(r.value);}).filter(function(n){return n!==null;});
    var low=Math.min.apply(null,[0].concat(values)),high=Math.max.apply(null,[0].concat(values));
    if(high===low)high=low+1;
    var span=high-low,zero=(0-low)/span*100;
    return '<div class="gc-bars" role="group" aria-label="'+esc(label)+'">'+rows.map(function(r,i){
      var v=num(r.value),left=v==null?zero:(Math.min(0,v)-low)/span*100,width=v==null?0:Math.abs(v)/span*100;
      return '<div class="gc-bar-row" data-series="'+esc(r.key||i)+'"><div class="gc-bar-label"><span>'+esc(r.label)+'</span><strong data-value="'+(v==null?'':v)+'">'+esc(fmt(v))+(v==null?'':unit==='%'?'%':'')+'</strong></div><div class="gc-track" aria-hidden="true"><i class="gc-zero" style="left:'+zero+'%"></i><i class="gc-fill gc-tone-'+i+'" style="left:'+left+'%;width:'+width+'%"></i></div><small>'+esc(r.note||'')+'</small></div>';
    }).join('')+'</div>';
  }
  function rowsFor(d,t,key) {
    return [['season','Season'],['last3','Last 3'],['last5','Last 5']].map(function(a){var s=t.averages[a[0]][key];return {key:a[0],label:a[1],value:stat(s),note:sample(s)};})
      .concat([{key:'league',label:'NFL season average',value:stat(d.league[key]),note:sample(d.league[key])+' team-games'}]);
  }
  function card(d,t,key) {
    var m=d.metrics[key],rank=(t.ranks||{})[key];
    return '<article class="gc-metric" data-defense-metric="'+esc(key)+'"><header><h4>'+esc(m.label)+'</h4><span>'+esc(m.unit)+'</span></header>'+bars(rowsFor(d,t,key),m.label,m.unit)+
      '<p class="gc-rank">'+(rank?'Season rank '+rank.rank+' / '+rank.of+' (1 = '+(m.higherBetter?'most':'fewest')+')':'Rank unavailable for an incomplete sample')+'</p></article>';
  }
  var tabs = [
    ['overview','Overview',['passYards','rushYards','points','takeaways']],
    ['pass','Vs Pass',['passYards','netPassYards','passTD','completionPct','yardsPerAttempt','completions','attempts','explosivePass']],
    ['run','Vs Run',['rushYards','yardsPerCarry','rushTD','carries','explosiveRun']],
    ['qb','Vs QB',['QB_fantasy','QB_passingYards','QB_passingTD','QB_rushingYards']],
    ['rb','Vs RB',['RB_fantasy','RB_rushingYards','RB_scrimmageYards','RB_receptions','RB_receivingYards','RB_rushingTD','RB_receivingTD']],
    ['wr','Vs WR',['WR_fantasy','WR_receivingYards','WR_receptions','WR_receivingTD']],
    ['te','Vs TE',['TE_fantasy','TE_receivingYards','TE_receptions','TE_receivingTD']],
    ['disruption','Sacks & takeaways',['sacks','interceptions','takeaways','qbHits','explosivePass','explosiveRun']],
    ['recent','Recent games',[]]
  ];
  function trend(d,t,key) {
    var m=d.metrics[key],gs=t.games.slice(-5),rows=gs.map(function(g){return {label:'W'+g.week+' '+(g.home?'vs ':'@ ')+g.opponent,value:g.values[key],note:date(g.date),key:g.id};});
    return '<article class="gc-metric"><header><h4>'+esc(m.label)+'</h4><span>Last '+gs.length+' completed games</span></header>'+bars(rows,m.label,m.unit)+'</article>';
  }
  function context(d,t) {
    return '<div class="gc-position-read">'+['QB','RB','WR','TE'].map(function(p){
      var key=p+'_fantasy',s=t.averages.season[key],league=stat(d.league[key]),value=stat(s);
      var difference=value!=null&&league>0?(value/league-1)*100:null;
      return '<div><b>'+p+' group</b><strong>'+fmt(value)+' <small>PPR / game</small></strong><span>'+esc(difference==null?'No verified comparison':Math.abs(difference).toFixed(0)+'% '+(difference>=0?'more':'less')+' allowed than NFL average')+'</span></div>';
    }).join('')+'</div><p class="gc-note">Position totals cover every opposing player at that position combined. These are descriptive matchup numbers, not individual forecasts or guarantees.</p>';
  }
  function methods(d) {return '<details class="gc-methods"><summary>Definitions, scoring & sources</summary>'+Object.keys(d.definitions).map(function(k){return '<p>'+esc(d.definitions[k])+'</p>';}).join('')+d.sources.map(function(s){return '<p><a href="'+esc(s.url)+'" target="_blank" rel="noopener">'+esc(s.name)+'</a></p>';}).join('')+'</details>';}
  function gameLog(t) {
    return '<details class="gc-methods"><summary>Game-by-game defensive numbers</summary><div class="gc-table-wrap"><table><thead><tr><th>Game</th><th>Pass allowed</th><th>Rush allowed</th><th>Sacks</th><th>Takeaways</th></tr></thead><tbody>'+t.games.slice().reverse().map(function(g){return '<tr><th>W'+g.week+' '+esc(g.opponent)+'<small>'+esc(date(g.date))+'</small></th>'+['passYards','rushYards','sacks','takeaways'].map(function(k){return '<td>'+fmt(g.values[k])+'</td>';}).join('')+'</tr>';}).join('')+'</tbody></table></div></details>';
  }
  function renderTeam(host,d,code,full) {
    var t=d.teams[team(code)];if(!t){host.innerHTML='<p class="gc-note">Choose a team with published defensive statistics.</p>';return;}
    var id='gc-team-'+(++serial),view='overview';
    var old=Date.now()-Date.parse(d.generatedAt)>48*3600000||Number(d.season)!==currentSeason();
    host.classList.add('gp-compare','gc-defense');host.dataset.team=t.abbreviation;
    host.innerHTML='<div class="gc-heading"><div><p class="gc-kicker">DEFENSIVE PROFILE</p><h3>'+esc(t.name)+'</h3></div>'+
      (full?'':'<a class="gc-page-link" href="team.html?team='+encodeURIComponent(t.abbreviation)+'">Full team page &rarr;</a>')+'</div>'+
      '<p class="gc-note">'+d.season+' regular season &middot; '+t.completedGames+' completed games &middot; statistics through '+esc(date(d.through))+'</p>'+
      (old?'<p class="gc-warning">This is a saved statistical snapshot, not a live feed. Last refreshed '+esc(date(d.generatedAt))+'.</p>':'')+
      '<p class="gc-note">Bar length = amount, not a quality score. Lower allowed is usually better; higher sacks and takeaways is better.</p>'+
      '<div class="gc-tabs" role="tablist" aria-label="Defensive statistics">'+tabs.map(function(x,i){return '<button type="button" role="tab" id="'+id+'-'+x[0]+'" aria-controls="'+id+'-panel" aria-selected="'+(i===0)+'" tabindex="'+(i===0?'0':'-1')+'" data-defense-tab="'+x[0]+'">'+x[1]+'</button>';}).join('')+'</div>'+
      '<div id="'+id+'-panel" role="tabpanel" aria-labelledby="'+id+'-overview" tabindex="0"></div>'+gameLog(t)+methods(d);
    var panel=host.querySelector('[role="tabpanel"]');
    function paint(key) {
      view=key;var tab=tabs.find(function(x){return x[0]===key;})||tabs[0];
      host.querySelectorAll('[role="tab"]').forEach(function(b){var active=b.dataset.defenseTab===key;b.setAttribute('aria-selected',String(active));b.tabIndex=active?0:-1;});
      panel.setAttribute('aria-labelledby',id+'-'+key);
      var content=key==='recent'?['passYards','rushYards','passTD','rushTD'].map(function(k){return trend(d,t,k);}).join(''):tab[2].map(function(k){return card(d,t,k);}).join('');
      panel.innerHTML=(['qb','rb','wr','te'].includes(key)?'<p class="gc-note gc-group-notice">Entire opposing '+key.toUpperCase()+' group combined per game. Not the allowance for a single player.</p>':'')+
        '<div class="gc-metric-grid">'+content+'</div>'+(key==='overview'?'<h4 class="gc-subheading">Fantasy allowance by position</h4>'+context(d,t):'');
    }
    host.querySelector('.gc-tabs').addEventListener('click',function(e){var b=e.target.closest('[data-defense-tab]');if(b)paint(b.dataset.defenseTab);});
    host.querySelector('.gc-tabs').addEventListener('keydown',function(e){
      var list=Array.from(host.querySelectorAll('[role="tab"]')),i=list.indexOf(document.activeElement);if(i<0)return;
      var next=e.key==='ArrowRight'?(i+1)%list.length:e.key==='ArrowLeft'?(i+list.length-1)%list.length:e.key==='Home'?0:e.key==='End'?list.length-1:-1;
      if(next>=0){e.preventDefault();paint(list[next].dataset.defenseTab);list[next].focus();}
    });
    paint(view);
  }
  async function mountTeam(entity,container) {
    if(!container)return;var code=team(entity.abbreviation||entity.team||entity.teamAbbreviation||entity.key);
    container.querySelectorAll('.gc-defense').forEach(function(n){n.remove();});
    var host=document.createElement('section');host.className='gp-compare gc-defense';host.innerHTML='<p class="gc-note" role="status">Loading defensive comparisons...</p>';
    var first=container.querySelector('.modal-section');if(first)first.before(host);else container.appendChild(host);
    try{var d=await read('team-defense');if(host.isConnected)renderTeam(host,d,code,false);}catch(e){if(host.isConnected)host.innerHTML='<p class="gc-warning">Defensive statistics are unavailable. Missing values are not shown as zero.</p>';}
  }
  var playerOptions={QB:['passingYards','passingTD','interceptions','rushingYards'],RB:['scrimmageYards','rushingYards','receivingYards','receptions','scrimmageTD'],WR:['receivingYards','receptions','targets','receivingTD'],TE:['receivingYards','receptions','targets','receivingTD']};
  var labels={passingYards:'Passing yards',passingTD:'Passing TDs',interceptions:'Interceptions',rushingYards:'Rushing yards',rushingTD:'Rushing TDs',receivingYards:'Receiving yards',receivingTD:'Receiving TDs',receptions:'Receptions',targets:'Targets',scrimmageYards:'Rushing + receiving yards',scrimmageTD:'Rushing + receiving TDs'};
  var oldKeys={passingTD:'passingTouchdowns',rushingTD:'rushingTouchdowns',receivingTD:'receivingTouchdowns'};
  var predKeys={passingYards:'passing_yards',passingTD:'passing_tds',rushingYards:'rushing_yards',rushingTD:'rushing_tds',receivingYards:'receiving_yards',receivingTD:'receiving_tds',receptions:'receptions',targets:'targets',scrimmageYards:'scrimmage_yards',scrimmageTD:'scrimmage_tds'};
  function historicalValue(g,k){var s=g.stats||{};if(k==='scrimmageYards'||k==='scrimmageTD'){var a=num(s[k==='scrimmageYards'?'rushingYards':'rushingTouchdowns']),b=num(s[k==='scrimmageYards'?'receivingYards':'receivingTouchdowns']);return a==null||b==null?null:a+b;}return num(s[oldKeys[k]||k]);}
  function resolvePlayer(data,d) {
    var players=Object.values(data.players),id=String(d.id||d.player_id||''),eid=String(d.espnId||d.athleteId||'');
    if(data.players[id])return data.players[id];
    if(eid){var exact=players.filter(function(p){return p.espnId&&String(p.espnId)===eid;});if(exact.length===1)return exact[0];}
    var matches=players.filter(function(p){return norm(p.name)===norm(d.name)&&(!d.position||p.position===d.position);});
    return matches.length===1?matches[0]:null;
  }
  async function mountPlayer(section,d,result) {
    if(!section||!section.isConnected||!result||!playerOptions[d.position])return;
    var pref=settings.get(section)||{metric:playerOptions[d.position][0],post:false};settings.set(section,pref);
    var host=document.createElement('section');host.className='gp-compare gc-player';host.innerHTML='<p class="gc-note">Loading comparison bars...</p>';
    section.querySelectorAll('.gc-player').forEach(function(n){n.remove();});
    var head=section.querySelector('.gp-h2h-head');if(head)head.after(host);else section.prepend(host);
    var table=section.querySelector('.gp-h2h-scroll'),summary=section.querySelector('.gp-h2h-summary');
    if(table&&!table.closest('details')){var raw=document.createElement('details');raw.className='gc-methods';raw.innerHTML='<summary>Individual H2H games and totals</summary>';table.before(raw);if(summary)raw.appendChild(summary);raw.appendChild(table);}
    try {
      var feeds=await Promise.all([read('defense-players'),read('team-defense')]);if(!host.isConnected)return;
      var data=feeds[0],defense=feeds[1],p=resolvePlayer(data,d),opp=result.opponent||null,code=team(opp&&opp.team);
      function paint() {
        var k=pref.metric,records=(result.rows||[]).filter(function(g){return pref.post||String(g.seasonType).toUpperCase()==='REG';});
        var values=records.map(function(g){return historicalValue(g,k);}).filter(function(v){return v!==null;});
        var h2h=values.length?values.reduce(function(a,b){return a+b;},0)/values.length:null;
        var season=p&&p.averages.season[k],recent=p&&p.averages.last5[k];
        var rows=[{label:data.season+' season average',value:stat(season),note:sample(season)+' recorded appearances',key:'season'},
          {label:'Last 5 this season',value:stat(recent),note:sample(recent)+' recorded appearances',key:'recent'},
          {label:'Available H2H'+(code?' vs '+code:''),value:h2h,note:values.length+' verified games'+(pref.post?' (regular + playoffs)':' (regular season)')+(result.loadingExtended?' - older history loading':result.failed&&result.failed.length?' - partial history':''),key:'h2h'}];
        var saved=null;
        if(root.GPExactTracker&&opp) saved=root.GPExactTracker.find({name:d.name,athleteId:d.espnId||p&&p.espnId,team:d.team,gameId:opp.gameId});
        if(saved&&Date.parse(saved.kickoff)>Date.now()&&team(saved.opponent)===code&&Date.parse(saved.recordedAt)<=Date.parse(saved.kickoff)-300000&&num(saved.predictions[predKeys[k]])!==null)
          rows.push({label:'Saved '+(saved.model==='workload-trial-1'?'trial':'v2.1')+' forecast',value:saved.predictions[predKeys[k]],note:'Frozen before kickoff; estimate, not a result',key:'forecast'});
        host.innerHTML='<div class="gc-chart-tools"><label>Compare <select aria-label="Player comparison statistic">'+playerOptions[d.position].map(function(x){return '<option value="'+x+'"'+(x===k?' selected':'')+'>'+labels[x]+'</option>';}).join('')+'</select></label><label class="gc-check"><input type="checkbox"'+(pref.post?' checked':'')+'> Include playoff H2H</label></div>'+
          bars(rows,labels[k]+' per recorded appearance','per game')+
          '<p class="gc-note">Same player, same statistic. Season and recent averages use published appearances in '+data.season+'; H2H spans available seasons, not necessarily every career meeting. Zero is shown only when recorded.</p>'+
          (Number(data.season)!==currentSeason()?'<p class="gc-warning">Current-season data is unavailable; season bars above are explicitly for '+data.season+'.</p>':'')+
          '<p class="gc-source">Source: nflverse &middot; through '+esc(date(data.through))+'</p>';
        var t=defense.teams[code],key=d.position+'_'+k;
        if(t&&defense.metrics[key]){
          host.insertAdjacentHTML('beforeend','<details class="gc-opponent"><summary>'+esc(code)+' defensive context &middot; full '+esc(d.position)+' group</summary><p class="gc-note gc-group-notice">These are totals for every opposing '+esc(d.position)+' combined, not a target for '+esc(d.name)+'.</p>'+bars(rowsFor(defense,t,key),defense.metrics[key].label,defense.metrics[key].unit)+'<a class="gc-page-link" href="team.html?team='+encodeURIComponent(code)+'">Explore '+esc(code)+' defense &rarr;</a></details>');
        }else if(code){host.insertAdjacentHTML('beforeend','<a class="gc-page-link" href="team.html?team='+encodeURIComponent(code)+'">Explore '+esc(code)+' defense &rarr;</a>');}
        host.querySelector('select').addEventListener('change',function(e){pref.metric=e.target.value;paint();host.querySelector('select').focus({preventScroll:true});});
        host.querySelector('input').addEventListener('change',function(e){pref.post=e.target.checked;paint();host.querySelector('input').focus({preventScroll:true});});
      }
      paint();
    }catch(e){if(host.isConnected)host.innerHTML='<p class="gc-warning">Comparison data is unavailable. Verified H2H game details remain below.</p>';}
  }
  async function resolveOpponent(d) {
    var data=await read('team-defense');if(Number(data.season)!==currentSeason())return null;
    var t=data.teams[team(d.team)];if(!t)return null;
    var schedule=t.schedule||[],selected=d.gameId&&schedule.find(function(g){return String(g.id)===String(d.gameId)||String(g.espnId)===String(d.gameId);});
    var g=selected||schedule.find(function(g){return !g.completed&&Date.parse(g.date)>Date.now()-12*3600000;});
    return g?{team:g.opponent,name:data.teams[g.opponent]?data.teams[g.opponent].name:g.opponent,gameId:g.espnId||g.id,date:g.date}:null;
  }
  async function initPage() {
    var host=document.getElementById('team-defense-dashboard');if(!host)return;
    var select=document.getElementById('team-select'),overview=document.getElementById('team-overview');
    try {
      var d=await read('team-defense');select.innerHTML=Object.keys(d.teams).sort().map(function(k){return '<option value="'+k+'">'+esc(d.teams[k].name)+'</option>';}).join('');
      var chosen=team(new URLSearchParams(location.search).get('team'));select.value=d.teams[chosen]?chosen:'ARI';
      function update() {
        var t=d.teams[select.value];document.title=t.name+' Defense | Gridiron Pulse';document.getElementById('team-title').textContent=t.name;
        var next=t.schedule.find(function(g){return !g.completed&&Date.parse(g.date)>Date.now()-12*3600000;});
        overview.innerHTML='<div><small>Record</small><strong>'+esc(t.record)+'</strong></div><div><small>Completed games</small><strong>'+t.completedGames+'</strong></div><div><small>Next scheduled matchup</small><strong>'+(next?esc((next.home?'vs ':'@ ')+next.opponent):'No upcoming game')+'</strong><span>'+(next?esc(date(next.date)):'')+'</span></div><div><small>Stats through</small><strong>'+esc(date(d.through))+'</strong></div>';
        history.replaceState(null,'','team.html?team='+encodeURIComponent(t.abbreviation));renderTeam(host,d,t.abbreviation,true);
      }
      select.addEventListener('change',update);update();
    }catch(e){host.innerHTML='<p class="gc-warning">Team defensive data is temporarily unavailable. No sample statistics have been substituted.</p>';}
  }
  root.GPMatchupComparisons={mountTeam:mountTeam,mountPlayer:mountPlayer,resolveOpponent:resolveOpponent,bars:bars};
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',initPage,{once:true});else initPage();
})(window);
