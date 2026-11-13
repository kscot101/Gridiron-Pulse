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
  async function mountPlayer(section,d,result) {
    if(!section||!section.isConnected||!result||!playerOptions[d.position])return;
    var pref=settings.get(section)||{metric:playerOptions[d.position][0],post:false,defenseMetric:''};
    if(!playerOptions[d.position].includes(pref.metric))pref.metric=playerOptions[d.position][0];
    settings.set(section,pref);
    var host=document.createElement('section');
    host.className='gp-compare gc-player';
    host.innerHTML='<p class="gc-note" role="status">Building player and defensive comparison charts…</p>';
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
      var teamData=defense.teams&&defense.teams[code];

      function paint() {
        if(!host.isConnected)return;
        var metric=pref.metric;
        var records=(result.rows||[]).filter(function(game){
          return pref.post||String(game.seasonType||'REG').toUpperCase()==='REG';
        });
        var h2hValues=records.map(function(game){return historicalValue(game,metric);}).filter(function(value){return value!==null;});
        var h2hAvg=h2hValues.length?h2hValues.reduce(function(a,b){return a+b;},0)/h2hValues.length:null;
        var season=player&&player.averages&&player.averages.season&&player.averages.season[metric];
        var last5=player&&player.averages&&player.averages.last5&&player.averages.last5[metric];
        var comparison=[
          {key:'h2h',label:'Head-to-head'+(code?' vs '+code:''),value:h2hAvg,
            note:h2hValues.length+' recorded meeting'+(h2hValues.length===1?'':'s')+
              (pref.post?' · including playoffs':' · regular season')+
              (result.loadingExtended?' · checking older meetings':result.failed&&result.failed.length?' · partial history':'')},
          {key:'season',label:data.season+' season average',value:stat(season),
            note:sample(season)+' recorded appearances'},
          {key:'last5',label:'Last 5 average',value:stat(last5),
            note:sample(last5)+' most recent recorded appearances'}
        ];
        var recent=playerWeeklyRows(player,metric);
        var rowSamples=recent.filter(function(row){return num(row.value)!==null;}).length;
        var playerLabel=labels[metric]||metric;
        var options=playerOptions[position].map(function(key){
          return '<option value="'+esc(key)+'"'+(key===metric?' selected':'')+'>'+esc(labels[key]||key)+'</option>';
        }).join('');
        var metricButtons=playerOptions[position].map(function(key){
          return '<button type="button" data-gc-metric="'+esc(key)+'" aria-pressed="'+(key===metric)+'">'+esc(labels[key]||key)+'</button>';
        }).join('');
        var markup=
          '<div class="gc-player-intro"><div><p class="gc-kicker">PERFORMANCE SNAPSHOT</p>'+
          '<h4>Compare the numbers</h4><p>One statistic across matchup history, season form, and the last five games.</p></div>'+
          '<label class="gc-metric-picker">Statistic <select data-gc-player-stat aria-label="Player comparison statistic">'+options+'</select></label></div>'+ 
          '<div class="gc-stat-pills" role="group" aria-label="Select player performance statistic">'+metricButtons+'</div>'+
          '<div class="gc-matchup-layout"><div class="gc-player-side"><div class="gc-player-chart-grid">'+
          chartSection('H2H vs season vs last 5',playerLabel+' per recorded appearance',comparison,playerLabel)+
          chartSection('Last 5 individual games',recent.length?rowSamples+' of '+recent.length+' with published '+playerLabel.toLowerCase():'No current-season games',recent,playerLabel,true)+
          '</div>'+
          '<label class="gc-playoff-toggle"><input type="checkbox" data-gc-playoffs'+(pref.post?' checked':'')+'> Include playoff games in H2H</label>'+
          '<p class="gc-note">H2H covers available verified meetings across seasons; the other averages and weekly bars use '+
             esc(data.season)+' regular-season appearances. Missing games or statistics are not displayed as zero.</p>';

        var saved=null;
        if(root.GPExactTracker&&opponent)saved=root.GPExactTracker.find({
          name:d.name,athleteId:d.espnId||player&&player.espnId,team:d.team,gameId:opponent.gameId
        });
        if(saved&&Date.parse(saved.kickoff)>Date.now()&&team(saved.opponent)===code&&
          Date.parse(saved.recordedAt)<=Date.parse(saved.kickoff)-300000&&num(saved.predictions[predKeys[metric]])!==null){
          markup+='<p class="gc-forecast-note">Saved pregame forecast: <strong>'+
            esc(fmt(saved.predictions[predKeys[metric]]))+'</strong> '+esc(playerLabel.toLowerCase())+
            ' · model estimate, not a game result</p>';
        }
        if(Number(data.season)!==currentSeason())markup+='<p class="gc-warning">The latest available player averages are for '+
          esc(data.season)+', not the current season.</p>';
        markup+='<p class="gc-source">Player data: nflverse · through '+esc(date(data.through))+'</p>';

        // Place weekly defensive allowances beside the player's results.
        // Counts are for the whole opposing position group, never one player.
        markup+='</div><section class="gc-defense-weeks"><div class="gc-defense-weeks-head">'+
          '<div><p class="gc-kicker">OPPONENT DEFENSE / LAST FIVE GAMES</p>'+
          '<h4>'+(code?esc(code)+' vs '+esc(position):'Upcoming defensive matchup')+'</h4>'+
          '<p>What the defense allowed to the entire opposing '+esc(position)+' group each week, before this matchup.</p></div>'+
          (code?'<a class="gc-page-link" href="team.html?team='+encodeURIComponent(code)+'">Full defense profile ↗</a>':'')+'</div>';

        var candidates=(positionDefenseMetrics[position]||[]).filter(function(key){return !!(defense.metrics&&defense.metrics[key]);});
        var aligned=position+'_'+metric;
        var suggested=candidates.includes(aligned)?aligned:defaultDefenseMetrics[position];
        var chosen=candidates.includes(pref.defenseMetric)?pref.defenseMetric:
          candidates.includes(suggested)?suggested:candidates[0];
        var defenseRead='No verified opponent trend available';
        if(teamData&&chosen){
          var optionsDefense=candidates.map(function(key){
            return '<option value="'+esc(key)+'"'+(key===chosen?' selected':'')+'>'+esc(defense.metrics[key].label)+'</option>';
          }).join('');
          var weeks=defensiveWeeklyRows(teamData,chosen,opponent);
          var weekMean=mean(weeks);
          var valuesCount=weeks.filter(function(row){return num(row.value)!==null;}).length;
          var league=defense.league&&defense.league[chosen];
          var alignedMetric=(chosen===aligned);
          var defensiveLabel=defense.metrics[chosen].label;
          if(weekMean!==null)defenseRead=esc(fmt(weekMean))+' '+esc(defensiveLabel.toLowerCase())+' allowed per game (last '+weeks.length+')';
          markup+='<label class="gc-metric-picker gc-defense-picker">Defense allowed statistic '+
            '<select data-gc-defense-stat aria-label="Defense allowed statistic">'+optionsDefense+'</select></label>'+
            (!alignedMetric?'<p class="gc-defense-disclosure">Position-specific '+esc(playerLabel.toLowerCase())+
              ' data is not published for this view. Showing <strong>'+esc(defensiveLabel.toLowerCase())+'</strong> instead.</p>':'')+
            '<div class="gc-defense-summary">'+
            '<div><small>Last '+weeks.length+' games avg</small><strong>'+esc(fmt(weekMean))+'</strong></div>'+
            '<div><small>League / team-game avg</small><strong>'+esc(fmt(stat(league)))+'</strong></div>'+
            '</div>'+
            (weeks.length?weeklyColumns(weeks,defensiveLabel,'defense'):
              '<p class="gc-visual-empty">No completed defensive games precede this matchup in the available feed.</p>')+
            '<p class="gc-note">Last '+weeks.length+' completed regular-season team-games; '+valuesCount+
            ' have a recorded value. All opposing '+esc(position)+' players combined — <strong>not</strong> the average for one player. '+
            'More yards, catches, or touchdowns allowed does not guarantee an individual result.</p>'+
            (Number(defense.season)!==currentSeason()?'<p class="gc-warning">Defensive data is from '+esc(defense.season)+', not the current season.</p>':'')+
            '<p class="gc-source">Defense data: nflverse · through '+esc(date(defense.through))+'</p>';
        }else{
          markup+='<p class="gc-visual-empty">Verified weekly position-specific defensive statistics are unavailable'+
            (code?' for '+esc(code):' until the next opponent is known')+'. No placeholder values have been inserted.</p>';
        }
        markup+='</section></div>';
        var seasonValue=stat(season),last5Value=stat(last5);
        var recentRead=last5Value===null?'No recent player average recorded':
          esc(fmt(last5Value))+' '+esc(playerLabel.toLowerCase())+' per game (last '+esc(sample(last5))+')';
        var h2hRead=h2hValues.length?esc(fmt(h2hAvg))+' '+esc(playerLabel.toLowerCase())+
          ' per meeting ('+h2hValues.length+' recorded)':'No verified meetings available';
        markup+='<div class="gc-read-strip" aria-label="Performance summary"><div class="gc-read-title">'+
          '<span class="gc-kicker">THE READ</span><strong>At a glance</strong></div>'+
          '<div><b>Head to head</b><span>'+h2hRead+'</span></div>'+
          '<div><b>Recent form</b><span>'+recentRead+'</span></div>'+
          '<div><b>Defense trend</b><span>'+defenseRead+'</span></div></div>';
        host.innerHTML=markup;

        host.querySelectorAll('[data-gc-metric]').forEach(function(button){
          button.addEventListener('click',function(){
            pref.metric=button.getAttribute('data-gc-metric');pref.defenseMetric='';paint();
            var next=Array.from(host.querySelectorAll('[data-gc-metric]')).find(function(b){
              return b.getAttribute('data-gc-metric')===pref.metric;
            });
            if(next)next.focus({preventScroll:true});
          });
        });
        var playerSelect=host.querySelector('[data-gc-player-stat]');
        if(playerSelect)playerSelect.addEventListener('change',function(e){
          pref.metric=e.target.value;pref.defenseMetric='';paint();
          var again=host.querySelector('[data-gc-player-stat]');if(again)again.focus({preventScroll:true});
        });
        var postToggle=host.querySelector('[data-gc-playoffs]');
        if(postToggle)postToggle.addEventListener('change',function(e){
          pref.post=e.target.checked;paint();
          var again=host.querySelector('[data-gc-playoffs]');if(again)again.focus({preventScroll:true});
        });
        var defenseSelect=host.querySelector('[data-gc-defense-stat]');
        if(defenseSelect)defenseSelect.addEventListener('change',function(e){
          pref.defenseMetric=e.target.value;paint();
          var again=host.querySelector('[data-gc-defense-stat]');if(again)again.focus({preventScroll:true});
        });
      }
      paint();
    }catch(error){
      if(host.isConnected)host.innerHTML='<p class="gc-warning">Comparison charts are temporarily unavailable. Verified H2H box scores and recent game logs remain accessible below. Missing values are never represented as zero.</p>';
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
