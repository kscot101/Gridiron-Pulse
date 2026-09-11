/* Projection reliability guardrails. No prediction coefficients live here. */
(function(root){
  'use strict';
  var MAX_AGE_MS=3*60*60*1000;
  function number(value){
    if(value===null || value===undefined || typeof value==='boolean') return null;
    if(typeof value!=='number' && typeof value!=='string') return null;
    if(typeof value==='string' && !value.trim()) return null;
    var n=Number(value);
    return Number.isFinite(n)?n:null;
  }
  function stamp(data){
    data=data||{};
    return data.generatedAt || (data.seasonOutlook||{}).generatedAt || null;
  }
  function fresh(data,now){
    now=now===undefined?Date.now():now;
    var t=Date.parse(stamp(data)||'');
    if(!Number.isFinite(t) || now-t>MAX_AGE_MS || t-now>5*60*1000) return false;
    var source=(data||{}).sourceGeneratedAt;
    if(source){var s=Date.parse(source);if(!Number.isFinite(s)||now-s>MAX_AGE_MS||s-now>5*60*1000)return false;}
    return true;
  }
  function team(value){
    if(value && typeof value==='object') value=value.abbreviation||value.team||value.teamAbbreviation||value.code;
    value=String(value||'').toUpperCase();
    return {LA:'LAR',STL:'LAR',JAC:'JAX',OAK:'LV',SD:'LAC',WSH:'WAS'}[value]||value;
  }
  function name(value){return String(value||'').toLowerCase().replace(/\b(jr|sr|ii|iii|iv|v)\b/g,'').replace(/[^a-z0-9]/g,'');}
  function forGame(row,pick,games,boards,now){
    if(!row||!pick||!row.nextGameId||!row.nextOpponent) return false;
    now=now===undefined?Date.now():now;
    var tm=team(pick.team), id=pick.gameId||pick.eventId||pick.game_id;
    games=Array.isArray(games)?games:[]; boards=Array.isArray(boards)?boards:[];
    if(!id){
      var related=boards.filter(function(b){return (b.picks||[]).some(function(p){return name(p.name||p.playerName)===name(pick.name||pick.playerName)&&team(p.team)===tm;});});
      var ids=Array.from(new Set(related.map(function(b){return String(b.gameId||b.id||'');}).filter(Boolean)));
      if(ids.length===1) id=ids[0];
    }
    var candidates=games.filter(function(g){var ts=g.teams||{};return team(ts.away)===tm||team(ts.home)===tm;});
    var game=id?games.find(function(g){return String(g.id)===String(id);}):candidates.filter(function(g){return (g.status||{}).state==='pre'&&Date.parse(g.date)>now;}).sort(function(a,b){return Date.parse(a.date)-Date.parse(b.date);})[0];
    if(!game || String(game.id)!==String(row.nextGameId) || (game.status||{}).state!=='pre') return false;
    var kickoff=Date.parse(game.date), expected=Date.parse(row.nextGameKickoff);
    if(!Number.isFinite(kickoff)||kickoff<=now||!Number.isFinite(expected)||Math.abs(kickoff-expected)>60000)return false;
    var sides=game.teams||{}, opponent=team(sides.away)===tm?team(sides.home):team(sides.away);
    return opponent===team(row.nextOpponent);
  }
  function paint(data){
    if(!root.document)return;
    var box=root.document.getElementById('projection-feed-status');if(!box)return;
    var raw=stamp(data),t=Date.parse(raw||''),ok=fresh(data);
    box.textContent=Number.isFinite(t)?'Projections generated '+new Date(t).toLocaleString()+(ok?'':' - stale; current estimates withheld'):'Projection timestamp unavailable';
    box.style.color=ok?'inherit':'#ffb375';
    box.dataset.fresh=String(ok);
  }
  var api={number:number,fresh:fresh,stamp:stamp,team:team,forGame:forGame,paint:paint,MAX_AGE_MS:MAX_AGE_MS};
  root.GPProjectionSafety=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
