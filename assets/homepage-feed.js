/* Current game data and historical model results have separate provenance. */
(function(root){
  'use strict';
  var ESPN='https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard';
  var MAX_AGE=90*60*1000, previousCache=null;
  function list(v){return Array.isArray(v)?v:[];}
  function num(v){if(v==null||typeof v==='boolean'||!['string','number'].includes(typeof v)||String(v).trim()==='')return null;var n=Number(v);return Number.isFinite(n)?n:null;}
  function esc(v){return String(v==null?'':v).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});}
  function stamp(v){return Date.parse(v||'');}
  function fresh(s,now){var t=stamp(s&&s.generatedAt);return Number.isFinite(t)&&now-t<=MAX_AGE&&t-now<=300000;}
  function seasonOf(board){var s=board.season||{},w=(board.week||{}).number;return {year:s.year,type:s.type,week:w,typeName:s.type===3?'Postseason':s.type===1?'Preseason':'Regular Season',label:String(s.year)+' '+(s.type===3?'Postseason':s.type===1?'Preseason':'Regular Season')+' - Week '+String(w)};}
  function current(s,board,now){
    if(!s||!fresh(s,now)||!list(s.games).length)return false;
    if(list(s.games).some(function(g){return (g.status||{}).state==='pre'&&stamp(g.date)<now-6*3600000;}))return false;
    if(!board)return true;
    var expected=seasonOf(board),actual=s.season||{};
    if(['year','type','week'].some(function(k){return String(expected[k])!==String(actual[k]);}))return false;
    var ids=new Set(list(s.games).map(function(g){return String(g.id);}));
    return list(board.events).every(function(e){return ids.has(String(e.id));});
  }
  function team(c){c=c||{};var t=c.team||{};return {id:String(t.id||c.id||''),abbreviation:t.abbreviation||'',displayName:t.displayName||t.name||'',shortName:t.shortDisplayName||t.name||'',logo:t.logo||'',color:t.color||'',alternateColor:t.alternateColor||'',score:num(c.score),record:(list(c.records).find(function(r){return r.type==='total';})||list(c.records)[0]||{}).summary||null};}
  function game(e,old){
    var c=list(e.competitions)[0]||{},s=(e.status||c.status||{}),t=s.type||{},cs=list(c.competitors),venue=c.venue||{};
    return Object.assign({},old||{},{id:String(e.id),date:e.date,name:e.name,shortName:e.shortName,
      week:(e.week||{}).number||null,
      status:{state:t.state||'pre',completed:t.completed===true,detail:t.detail||t.description||'',shortDetail:t.shortDetail||t.description||'',period:s.period||0,clock:s.displayClock||null},
      teams:{away:team(cs.find(function(x){return x.homeAway==='away';})),home:team(cs.find(function(x){return x.homeAway==='home';}))},
      venue:{name:venue.fullName||'',city:(venue.address||{}).city||'',indoor:venue.indoor==null?null:venue.indoor},
      broadcasts:list(c.broadcasts).flatMap(function(b){return list(b.names);}),
      possession:(c.situation||{}).possession||null,situation:{downDistance:(c.situation||{}).downDistanceText||null,yardLine:(c.situation||{}).possessionText||null,isRedZone:(c.situation||{}).isRedZone===true},
      comparisonStats:list(old&&old.comparisonStats),injuries:list(old&&old.injuries),leaders:list(old&&old.leaders),drives:list(old&&old.drives),weather:(old&&old.weather)||{},teamStats:(old&&old.teamStats)||{}});
  }
  function mergeResults(snapshots,archived){
    var map=new Map();
    list(archived).forEach(function(r){if(r&&r.gameId)map.set([r.gameId,r.player,r.team].join('|'),r);});
    snapshots.slice().reverse().forEach(function(s){
      if(!s)return;var games=new Map(list(s.games).map(function(g){return [String(g.id),g];}));
      list(s.results).forEach(function(r){var g=games.get(String(r.gameId))||{};map.set([r.gameId,r.player,r.team].join('|'),Object.assign({},r,{gameDate:r.gameDate||g.date||null,sourceGeneratedAt:r.sourceGeneratedAt||s.generatedAt||null}));});
    });
    return Array.from(map.values()).sort(function(a,b){return (stamp(b.gameDate)||0)-(stamp(a.gameDate)||0);});
  }
  function compose(board,candidates,previous,archive,now){
    now=now||Date.now();candidates=list(candidates).filter(Boolean).sort(function(a,b){return (stamp(b.generatedAt)||0)-(stamp(a.generatedAt)||0);});
    var valid=candidates.find(function(s){return current(s,board,now);}), latest=candidates[0]||null;
    var oldGames=new Map(list(valid&&valid.games).map(function(g){return [String(g.id),g];}));
    var games=board?list(board.events).map(function(e){return game(e,oldGames.get(String(e.id)));}):list(valid&&valid.games);
    var ids=new Set(games.map(function(g){return String(g.id);}));
    var boards=list(valid&&valid.playerEdge).filter(function(b){return ids.has(String(b.gameId));});
    var season=board?seasonOf(board):(valid&&valid.season)||null;
    var recent=list(previous&&previous.events).map(function(e){return game(e);}).filter(function(g){return g.status.completed;});
    var results=mergeResults(candidates,list(archive&&archive.results));
    return {
      id:'homepage-current-'+now,version:'homepage-current-1',generatedAt:valid?valid.generatedAt:board?new Date(now).toISOString():null,
      mode:games.some(function(g){return g.status.state==='in';})?'live':'pregame',season:season,
      games:games,recentGames:recent,playerEdge:boards,
      scoreStrip:games.map(function(g){return {gameId:g.id,kickoff:g.date,state:g.status.state,status:g.status.shortDetail,away:g.teams.away.abbreviation,home:g.teams.home.abbreviation,awayScore:g.teams.away.score,homeScore:g.teams.home.score};}),
      results:results,modelPerformance:(latest&&latest.modelPerformance)||null,
      powerRankings:(valid&&valid.powerRankings)||{teams:[],players:[],message:'Current form rankings are unavailable while the analysis feed is awaiting refresh.'},
      availability:(valid&&valid.availability)||{items:[],message:'Current availability analysis is awaiting an agent refresh. Missing reports do not mean everyone is healthy.'},
      refresh:{recommendedBrowserSeconds:games.some(function(g){return g.status.state==='in';})?30:120},
      summary:{gameCount:games.length,edgePickCount:valid?boards.reduce(function(n,b){return n+list(b.picks).length;},0):null,availabilityConcernCount:valid?(valid.summary||{}).availabilityConcernCount:null},
      feedStatus:{available:!!board||!!valid,analysisCurrent:!!valid,mode:valid?'agent':board?'scores-only':'unavailable',gamesCheckedAt:board?new Date(now).toISOString():null,analysisGeneratedAt:valid?valid.generatedAt:latest?latest.generatedAt:null,modelRecordAsOf:latest?latest.generatedAt:null}
    };
  }
  async function get(url){
    var ctl=new AbortController(),timer=setTimeout(function(){ctl.abort();},20000);
    try{var r=await root.fetch(url+(url.includes('?')?'&':'?')+'_gp='+Date.now(),{cache:'no-store',headers:{Accept:'application/json'},signal:ctl.signal});if(!r.ok)throw Error('HTTP '+r.status);var v=await r.json();return v;}finally{clearTimeout(timer);}
  }
  async function load(agent){
    var values=await Promise.allSettled([get(agent+'/latest'),get('./data/homepage-snapshot.json'),get(ESPN),get('./data/homepage-result-archive.json')]);
    function value(i){return values[i].status==='fulfilled'?values[i].value:null;}
    var board=value(2),now=Date.now(),prior=null;
    if(!board||!board.season||!(board.week||{}).number||!Array.isArray(board.events))board=null;
    if(board&&num(board.week.number)>1&&list(board.events).filter(function(e){return ((e.status||{}).type||{}).completed;}).length<5){
      var s=seasonOf(board),key=[s.year,s.type,s.week-1].join('-');
      if(previousCache&&previousCache.key===key&&now-previousCache.at<900000)prior=previousCache.data;
      else try{prior=await get(ESPN+'?dates='+encodeURIComponent(s.year)+'&seasontype='+encodeURIComponent(s.type)+'&week='+encodeURIComponent(s.week-1));previousCache={key:key,at:Date.now(),data:prior};}catch(e){prior=null;}
    }
    var candidates=[value(0),value(1)].filter(function(p){return p&&p.ok===true&&p.snapshot;}).map(function(p){return p.snapshot;});
    return compose(board,candidates,prior,value(3),Date.now());
  }
  function pickSpotlight(games,score,now){
    now=now||Date.now();games=list(games);
    var live=games.filter(function(g){return (g.status||{}).state==='in'&&stamp(g.date)<=now+300000&&stamp(g.date)>now-12*3600000;});
    var upcoming=games.filter(function(g){return (g.status||{}).state==='pre'&&stamp(g.date)>now;});
    var pool=live.length?live:upcoming;
    if(pool.length)return pool.slice().sort(function(a,b){var delta=typeof score==='function'?score(b)-score(a):0;return delta||stamp(a.date)-stamp(b.date);})[0];
    return games.filter(function(g){return (g.status||{}).completed&&stamp(g.date)>now-36*3600000;}).sort(function(a,b){return stamp(b.date)-stamp(a.date);})[0]||null;
  }
  function date(v){var t=stamp(v);return Number.isFinite(t)?new Date(t).toLocaleString(undefined,{month:'short',day:'numeric',hour:'numeric',minute:'2-digit'}):'date unavailable';}
  function paint(snapshot){
    if(!root.document)return;var doc=root.document,fs=(snapshot||{}).feedStatus||{},box=doc.getElementById('homepage-feed-status');
    if(box){box.dataset.mode=fs.mode||'unavailable';box.textContent=(snapshot&&snapshot.season?snapshot.season.label+' | ':'')+(fs.gamesCheckedAt?'Game data checked '+date(fs.gamesCheckedAt):'Game schedule source unavailable')+' | '+(fs.analysisCurrent?'Analysis generated '+date(fs.analysisGeneratedAt):'Player Edge awaiting refresh; last analysis '+date(fs.analysisGeneratedAt));}
    if(!fs.analysisCurrent){
      ['meta-edges','meta-concerns'].forEach(function(id){var e=doc.getElementById(id);if(e)e.textContent='\u2014';});
      var head=doc.querySelector('.spotlight-card-head b');if(head)head.textContent='Current matchup - analysis awaiting refresh';
      var read=doc.querySelector('.spotlight-read p');if(read)read.textContent='The schedule is current. Model game signals are withheld until the analysis agent publishes a fresh forecast.';
      var edges=doc.getElementById('edge-grid');if(edges)edges.innerHTML='<div class="empty" style="grid-column:1/-1">Current Player Edge signals are awaiting a fresh agent snapshot. Old signals are not reused for new opponents. Player profiles, favorites and the separate 2026 projections page remain available.</div>';
    }
    var record=doc.getElementById('model-feed-status');if(record)record.textContent='Saved model record as of '+date(fs.modelRecordAsOf)+'. Only originally locked picks are graded; missing weeks are not backfilled with invented predictions.';
  }
  function renderResults(snapshot){
    if(!root.document)return;var box=root.document.getElementById('results-list');if(!box)return;
    snapshot=snapshot||{};
    var map=new Map();list(snapshot.games).concat(list(snapshot.recentGames)).forEach(function(g){map.set(String(g.id),g);});
    var finals=Array.from(map.values()).filter(function(g){return (g.status||{}).completed&&num(g.teams.away.score)!==null&&num(g.teams.home.score)!==null;}).sort(function(a,b){return stamp(b.date)-stamp(a.date);}).slice(0,16);
    var ids=new Set(Array.from(map.keys())),rows=list(snapshot.results),recent=rows.filter(function(r){return ids.has(String(r.gameId));}),older=rows.filter(function(r){return !ids.has(String(r.gameId));});
    function resultRow(r){var p={name:r.player,playerName:r.player,team:r.team,position:r.position,athleteId:r.athleteId};var name=root.GPPlayerStats&&root.GPPlayerStats.link?root.GPPlayerStats.link(p,r.player):esc(r.player);return '<article class="result-row"><div><h3>'+name+' - '+esc(r.team)+'</h3><p>'+esc(r.matchup)+' | '+(r.gameDate?'Game '+esc(date(r.gameDate)):'Recorded '+esc(date(r.sourceGeneratedAt)))+'</p></div><div class="actual">'+esc(r.actual||'Player line unavailable')+'</div><strong>'+esc(num(r.edgeScore)==null?'\u2014':r.edgeScore)+'</strong><span class="outcome">'+esc(r.outcome||'NO DATA')+'</span></article>';}
    box.innerHTML='<h3>Latest final scores</h3><p>Actual game scores, separate from the model\'s locked-pick record.</p>'+(finals.length?finals.map(function(g){return '<article class="result-row"><div><h3><button type="button" class="text-button" data-game="'+esc(g.id)+'">'+esc(g.shortName||g.name)+'</button></h3><p>'+esc(date(g.date))+(g.week?' | Week '+esc(g.week):'')+'</p></div><div class="actual">'+esc(g.teams.away.abbreviation)+' '+esc(g.teams.away.score)+' - '+esc(g.teams.home.abbreviation)+' '+esc(g.teams.home.score)+'</div><strong>FINAL</strong></article>';}).join(''):'<div class="empty">No recent verified final scores are available from the current schedule source.</div>')+'<h3 style="margin-top:28px">Recent locked-pick results</h3>'+(recent.length?recent.map(resultRow).join(''):'<div class="empty">No locked-pick results for these games were supplied by the agent. Old results are retained below, not shown as this week\'s picks.</div>')+(older.length?'<details style="margin-top:20px"><summary style="cursor:pointer;font-weight:800">Earlier locked-pick results ('+older.length+')</summary>'+older.slice(0,100).map(resultRow).join('')+'</details>':'');
  }
  var api={number:num,current:current,compose:compose,load:load,pickSpotlight:pickSpotlight,paint:paint,renderResults:renderResults,MAX_AGE:MAX_AGE};
  root.GPHomepageFeed=api;if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
