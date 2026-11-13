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
  /* The comparison is the first thing visitors see. Raw box scores remain
     available in the existing expandable H2H table below these graphs. */
  var positionDefenseMetrics = {
    QB:['QB_passingYards','QB_passingTD','QB_rushingYards','QB_fantasy'],
    RB:['RB_scrimmageYards','RB_rushingYards','RB_receivingYards','RB_receptions','RB_rushingTD','RB_receivingTD','RB_fantasy'],
    WR:['WR_receivingYards','WR_receptions','WR_receivingTD','WR_fantasy'],
    TE:['TE_receivingYards','TE_receptions','TE_receivingTD','TE_fantasy']
  };
  var defaultDefenseMetrics = {
    QB:'QB_passingYards', RB:'RB_scrimmageYards',
    WR:'WR_receivingYards', TE:'TE_receivingYards'
  };
  function mean(rows) {
    var values=rows.map(function(row){return num(row.value);}).filter(function(v){return v!==null;});
    return values.length?values.reduce(function(a,b){return a+b;},0)/values.length:null;
  }
  function playerWeeklyRows(player,metric) {
    var games=(player&&Array.isArray(player.games)?player.games:[]).slice().sort(function(a,b){
      return String(a.date||'').localeCompare(String(b.date||''))||String(a.id||'').localeCompare(String(b.id||''));
    }).slice(-5);
    return games.map(function(game){
      return {key:String(game.id||game.date||game.week),label:'W'+esc(game.week)+' · '+String(game.opponent||'Opponent'),
        value:num(game.values&&game.values[metric]),note:date(game.date)};
    });
  }
  function defensiveWeeklyRows(teamData,metric,opponent) {
    // Only completed team-games before the upcoming matchup are eligible.
    // A same-day/finalized matchup must not leak postgame results into its preview.
    var cutoff=String(opponent&&opponent.date||'').slice(0,10);
    var games=(teamData&&Array.isArray(teamData.games)?teamData.games:[])
      .filter(function(game){return game&&game.date&&(!cutoff||String(game.date).slice(0,10)<cutoff);})
      .slice().sort(function(a,b){
        return String(a.date||'').localeCompare(String(b.date||''))||String(a.id||'').localeCompare(String(b.id||''));
      }).slice(-5);
    return games.map(function(game){
      return {key:String(game.id||game.date||game.week),
        label:'W'+esc(game.week)+' '+(game.home?'vs ':'@ ')+String(game.opponent||'Opponent'),
        value:num(game.values&&game.values[metric]),note:date(game.date)};
    });
  }
  /* Weekly game columns use a numeric axis shared by all five bars.
     Negative yardage falls back to the accessible horizontal comparison. */
  function weeklyColumns(rows,label,tone) {
    if(rows.some(function(r){return num(r.value)!==null&&num(r.value)<0;}))return bars(rows,label,'per game');
    var values=rows.map(function(r){return num(r.value);}).filter(function(n){return n!==null;});
    var high=Math.max.apply(null,[1].concat(values));
    return '<div class="gc-weekly-columns" role="group" aria-label="'+esc(label)+'">'+rows.map(function(row,i){
      var value=num(row.value),pct=value===null?0:Math.min(100,Math.max(0,value/high*100));
      var bits=String(row.label||'').split(/\s*·\s*|\s+(?=vs\s|@\s)/);
      var week=bits.shift()||'Game '+(i+1),opponent=bits.join(' ').trim();
      return '<div class="gc-weekly-column" data-series="'+esc(row.key||i)+'">'+
        '<strong data-value="'+(value===null?'':value)+'">'+esc(value===null?'—':fmt(value))+'</strong>'+
        '<div class="gc-weekly-track" aria-hidden="true"><i class="gc-weekly-fill '+(tone==='defense'?'gc-defense-tone':'')+
        '" style="height:'+(value===null?0:value===0?2:pct).toFixed(2)+'%"></i></div>'+
        '<span>'+esc(week)+'</span><small>'+esc(opponent||row.note||'')+'</small></div>';
    }).join('')+'</div>';
  }
  function chartSection(title,subtitle,rows,statLabel,vertical) {
    return '<section class="gc-visual-panel"><div class="gc-visual-head"><h4>'+esc(title)+'</h4><span>'+esc(subtitle)+'</span></div>'+
      (rows.length?(vertical?weeklyColumns(rows,statLabel,'player'):bars(rows,statLabel,'per game')):'<p class="gc-visual-empty">No verified game records for this view.</p>')+'</section>';
  }

  /* Single chart: three observed/baseline levels under each NFL week.
     Each group aligns the player's game and the upcoming opponent defense's
     game by the SAME league week. Current season average is a constant
     baseline, while H2H is a reference marker, not a fourth weekly bar. */
  function availableDefenseStat(position, metric, defense) {
    return !!(defense && defense.metrics && (defense.metrics[position+'_'+metric] ||
      (position==='RB' && metric==='scrimmageTD' &&
       defense.metrics.RB_rushingTD && defense.metrics.RB_receivingTD)));
  }
  function allowedStat(game, position, metric, defense) {
    if(!game || !availableDefenseStat(position,metric,defense))return null;
    var vals=game.values||{};
    if(position==='RB' && metric==='scrimmageTD') {
      var rush=num(vals.RB_rushingTD),receive=num(vals.RB_receivingTD);
      return rush===null || receive===null ? null : rush+receive;
    }
    return num(vals[position+'_'+metric]);
  }
  function weeklyTripleRows(player, opponentTeam, opponent, position, metric, defense) {
    var playerGames=(player && Array.isArray(player.games)?player.games:[]).slice()
      .sort(function(a,b){return String(a.date||'').localeCompare(String(b.date||''))||String(a.id||'').localeCompare(String(b.id||''));});
    var defenseGames=(opponentTeam && Array.isArray(opponentTeam.games)?opponentTeam.games:[])
      .filter(function(game){
        var cutoff=String(opponent&&opponent.date||'').slice(0,10);
        return game&&game.date&&(!cutoff||String(game.date).slice(0,10)<cutoff);
      }).slice().sort(function(a,b){
        return String(a.date||'').localeCompare(String(b.date||''))||String(a.id||'').localeCompare(String(b.id||''));
      });
    // When an opponent is known, align to the defense's five completed games;
    // otherwise show the player's own last five. Never pair games by index.
    var anchors=(defenseGames.length?defenseGames:playerGames).slice(-5);
    return anchors.map(function(anchor){
      var week=Number(anchor.week);
      var defenseGame=defenseGames.find(function(g){return Number(g.week)===week;})||null;
      var playerGame=playerGames.find(function(g){return Number(g.week)===week;})||null;
      return {week:week,playerGame:playerGame,defenseGame:defenseGame,
        playerValue:num(playerGame&&playerGame.values&&playerGame.values[metric]),
        defenseValue:allowedStat(defenseGame,position,metric,defense)};
    });
  }
  function renderTripleChart(rows, seasonValue, h2hValue, metricLabel, code, compatible) {
    var entries=[seasonValue,h2hValue];
    rows.forEach(function(row){entries.push(row.playerValue,row.defenseValue);});
    var present=entries.filter(function(v){return num(v)!==null;});
    var low=Math.min.apply(null,[0].concat(present));
    var high=Math.max.apply(null,[1].concat(present));
    if(high<=low)high=low+1;
    var span=high-low,zero=-low/span*100;
    var h2hPct=num(h2hValue)===null?null:(h2hValue-low)/span*100;
    function strip(which,value,label,week) {
      var v=num(value),left=v===null?zero:(Math.min(0,v)-low)/span*100;
      var width=v===null?0:Math.abs(v)/span*100;
      var zeroMark=low<0?'<i class="gc-combined-zero" style="left:'+zero.toFixed(3)+'%" aria-hidden="true"></i>':'';
      var h2hMark=h2hPct===null?'':'<i class="gc-combined-h2h" style="left:'+h2hPct.toFixed(3)+'%" aria-hidden="true"></i>';
      return '<div class="gc-triple-level gc-triple-'+which+'" data-gc-level="'+which+
        '" data-gc-week="'+esc(week)+'" data-value="'+(v===null?'':v)+'" role="group" aria-label="'+
        esc(label+': '+(v===null?'unavailable':fmt(v)))+'">'+
        '<div class="gc-triple-label"><span><i class="gc-triple-key" aria-hidden="true"></i>'+esc(label)+'</span>'+
        '<strong>'+esc(v===null?'—':fmt(v))+'</strong></div>'+
        '<div class="gc-triple-track">'+
        (v===null?'<span class="gc-triple-empty">No verified value</span>':
          '<i class="gc-triple-bar" style="left:'+left.toFixed(3)+'%;width:'+width.toFixed(3)+'%" aria-hidden="true"></i>')+
        zeroMark+h2hMark+'</div></div>';
    }
    var columns=rows.length?rows.map(function(row,index){
      var week=Number.isFinite(row.week)?'Week '+row.week:'Game '+(index+1);
      var p=row.playerGame,d=row.defenseGame;
      var pLabel=p?'Player '+(p.team||'')+' '+(p.opponent?'vs '+p.opponent:'')+' ('+date(p.date)+')':'No recorded player appearance';
      var dLabel=d?'Defense '+(d.home?'vs ':'@ ')+(d.opponent||'opponent')+' ('+date(d.date)+')':'No recorded defensive game';
      return '<div class="gc-triple-week" data-gc-week-group="'+esc(row.week)+'">'+
        '<div class="gc-triple-week-head"><strong>'+esc(week)+'</strong>'+
        '<span>'+esc(pLabel)+'</span><span>'+esc(dLabel)+'</span></div>'+
        '<div class="gc-triple-stack">'+
          strip('player',row.playerValue,'Player actual',row.week)+
          strip('season',seasonValue,'Season average',row.week)+
          strip('defense',row.defenseValue,code?code+' allowed to position':'Defense allowed',row.week)+
        '</div></div>';
    }).join(''):'<p class="gc-visual-empty">No verified weekly player or opponent-defense data is available for this matchup.</p>';
    return '<section class="gc-unified-graph" aria-label="Five-week player and opponent comparison">'+
      '<div class="gc-unified-head"><div><p class="gc-kicker">ONE GRAPH / THREE LEVELS PER WEEK</p>'+
      '<h4>Week-by-week matchup comparison</h4>'+
      '<p>'+esc(metricLabel)+' · five most recent completed games of the upcoming opponent, matched by NFL week</p></div>'+
      '<div class="gc-axis-range">Shared scale: '+esc(fmt(low))+' to '+esc(fmt(high))+'</div></div>'+
      '<div class="gc-triple-legend" aria-label="Chart legend">'+
      '<span class="gc-legend-player">Player actual</span>'+
      '<span class="gc-legend-season">Season avg</span>'+
      '<span class="gc-legend-defense">Defense allowed (full position group)</span>'+
      (h2hPct!==null?'<span class="gc-legend-h2h">H2H average: <b data-gc-h2h-value="'+h2hValue+'">'+esc(fmt(h2hValue))+'</b></span>':
        '<span>H2H: no verified meetings</span>')+'</div>'+
      '<div class="gc-triple-weeks" role="group" aria-label="Each week has three comparison bars on the same scale">'+columns+'</div>'+
      '<p class="gc-unified-caption">Player actual and defensive allowance refer to <strong>different games in the same NFL week</strong>. '+
      'Season average is the latest published season baseline, repeated for reference. The purple dashed marker shows the H2H average. '+
      'All bars share the same numeric scale. Defense figures include <strong>all opposing '+'players at that position combined</strong>, not one player. Blank values mean unavailable, not zero.</p>'+
      (!compatible?'<p class="gc-defense-disclosure">A position-specific defensive measure for this statistic is not available, so orange bars are left blank instead of comparing different units.</p>':'')+
      '</section>';
  }
  async function mountPlayer(section,d,result) {
    if(!section||!section.isConnected||!result||!playerOptions[d.position])return;
    var pref=settings.get(section)||{metric:playerOptions[d.position][0],post:false};
    if(!playerOptions[d.position].includes(pref.metric))pref.metric=playerOptions[d.position][0];
    settings.set(section,pref);
    var host=document.createElement('section');
    host.className='gp-compare gc-player gc-unified-profile';
    host.innerHTML='<p class="gc-note" role="status">Loading combined weekly comparisons…</p>';
    section.querySelectorAll('.gc-player').forEach(function(node){node.remove();});
    var head=section.querySelector('.gp-h2h-head');
    if(head)head.after(host);else section.prepend(host);

    var table=section.querySelector('.gp-h2h-scroll'),summary=section.querySelector('.gp-h2h-summary');
    if(table&&!table.closest('details')){
      var raw=document.createElement('details');raw.className='gc-methods gc-h2h-details';
      raw.innerHTML='<summary>View individual H2H box scores and totals</summary>';
      table.before(raw);if(summary)raw.appendChild(summary);raw.appendChild(table);
    }
    try {
      var feeds=await Promise.all([read('defense-players'),read('team-defense')]);
      if(!host.isConnected)return;
      var data=feeds[0],defense=feeds[1],player=resolvePlayer(data,d);
      var opponent=result.opponent||null,code=team(opponent&&opponent.team),position=d.position;
      var opponentTeam=defense.teams&&defense.teams[code];
      function paint(){
        if(!host.isConnected)return;
        var metric=pref.metric,label=labels[metric]||metric;
        var history=(result.rows||[]).filter(function(row){
          return pref.post||String(row.seasonType||'REG').toUpperCase()==='REG';
        });
        var h2h=history.map(function(game){return historicalValue(game,metric);}).filter(function(v){return v!==null;});
        var h2hAvg=h2h.length?h2h.reduce(function(sum,v){return sum+v;},0)/h2h.length:null;
        var season=player&&player.averages&&player.averages.season&&player.averages.season[metric];
        var recent=player&&player.averages&&player.averages.last5&&player.averages.last5[metric];
        var seasonAvg=stat(season),last5Avg=stat(recent);
        var aligned=availableDefenseStat(position,metric,defense);
        var slots=weeklyTripleRows(player,opponentTeam,opponent,position,metric,defense);
        var defValues=slots.map(function(row){return row.defenseValue;}).filter(function(v){return v!==null;});
        var defAvg=defValues.length?defValues.reduce(function(a,b){return a+b;},0)/defValues.length:null;
        var selectOptions=playerOptions[position].map(function(key){
          return '<option value="'+esc(key)+'"'+(key===metric?' selected':'')+'>'+esc(labels[key]||key)+'</option>';
        }).join('');
        var pills=playerOptions[position].map(function(key){
          return '<button type="button" data-gc-metric="'+esc(key)+'" aria-pressed="'+(key===metric)+'">'+
            esc(labels[key]||key)+'</button>';
        }).join('');
        var markup='<div class="gc-player-intro"><div><p class="gc-kicker">PLAYER EDGE / UNIFIED VIEW</p>'+
          '<h4>Compare three levels for every week</h4><p>Actual performance, season baseline and opponent positional allowance — together.</p></div>'+
          '<label class="gc-metric-picker">Statistic <select data-gc-player-stat aria-label="Player comparison statistic">'+selectOptions+'</select></label></div>'+
          '<div class="gc-stat-pills" role="group" aria-label="Choose performance statistic">'+pills+'</div>'+
          '<div class="gc-triple-summary" aria-label="Matchup averages">'+
            '<div><small>H2H avg vs '+esc(code||'opponent')+'</small><strong data-gc-summary="h2h">'+esc(fmt(h2hAvg))+'</strong>'+
             '<span>'+h2h.length+' recorded meeting'+(h2h.length===1?'':'s')+(result.loadingExtended?' · checking older games':'')+'</span></div>'+
            '<div><small>Season avg</small><strong data-gc-summary="season">'+esc(fmt(seasonAvg))+'</strong><span>'+esc(sample(season))+'</span></div>'+
            '<div><small>Last 5 avg</small><strong data-gc-summary="last5">'+esc(fmt(last5Avg))+'</strong><span>'+esc(sample(recent))+'</span></div>'+
            '<div><small>Defense last '+slots.length+' avg</small><strong data-gc-summary="defense">'+esc(fmt(defAvg))+'</strong><span>Entire opposing '+esc(position)+' group</span></div>'+
          '</div>'+
          renderTripleChart(slots,seasonAvg,h2hAvg,label,code,aligned)+
          '<label class="gc-playoff-toggle"><input type="checkbox" data-gc-playoffs'+(pref.post?' checked':'')+'> Include playoff games in H2H</label>'+
          '<p class="gc-note">2026 data through '+esc(date(data.through))+' (player) and '+esc(date(defense.through))+' (defense). '+
          'Head-to-head covers available verified meetings across seasons; the weekly graph uses current regular-season records only.</p>';
        if(root.GPExactTracker&&opponent){
          var saved=root.GPExactTracker.find({
            name:d.name,athleteId:d.espnId||(player&&player.espnId),team:d.team,gameId:opponent.gameId
          });
          if(saved&&Date.parse(saved.kickoff)>Date.now()&&team(saved.opponent)===code&&
            Date.parse(saved.recordedAt)<=Date.parse(saved.kickoff)-300000&&
            num(saved.predictions&&saved.predictions[predKeys[metric]])!==null)
            markup+='<p class="gc-forecast-note">Saved pregame projection: <strong>'+
              esc(fmt(saved.predictions[predKeys[metric]]))+'</strong> '+esc(label.toLowerCase())+
              ' · model estimate, not an actual result</p>';
        }
        if(Number(data.season)!==currentSeason()||Number(defense.season)!==currentSeason())
          markup+='<p class="gc-warning">One or more statistics feeds are from a prior NFL season. Verify the data dates before interpreting this comparison.</p>';
        if(result.failed&&result.failed.length)
          markup+='<p class="gc-note">Some older H2H seasons could not be loaded. The H2H sample is partial.</p>';
        if(code)markup+='<a class="gc-page-link" href="team.html?team='+encodeURIComponent(code)+'">View full '+esc(code)+' defense profile ↗</a>';
        host.innerHTML=markup;
        host.querySelectorAll('[data-gc-metric]').forEach(function(button){
          button.addEventListener('click',function(){
            pref.metric=button.dataset.gcMetric;paint();
            var match=Array.from(host.querySelectorAll('[data-gc-metric]')).find(function(b){return b.dataset.gcMetric===pref.metric;});
            if(match)match.focus({preventScroll:true});
          });
        });
        var picker=host.querySelector('[data-gc-player-stat]');
        if(picker)picker.addEventListener('change',function(e){
          pref.metric=e.target.value;paint();
          var again=host.querySelector('[data-gc-player-stat]');if(again)again.focus({preventScroll:true});
        });
        var playoffs=host.querySelector('[data-gc-playoffs]');
        if(playoffs)playoffs.addEventListener('change',function(e){
          pref.post=e.target.checked;paint();
          var again=host.querySelector('[data-gc-playoffs]');if(again)again.focus({preventScroll:true});
        });
      }
      paint();
    }catch(error){
      if(host.isConnected)host.innerHTML='<p class="gc-warning">Combined chart temporarily unavailable. Verified game logs remain below. Missing values are not displayed as zero.</p>';
    }
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
