/* Same-origin scoreboard transport. This does not create or grade predictions. */
(function(root){
  'use strict';
  var api=root.GPHomepageFeed;if(!api)return;
  function list(v){return Array.isArray(v)?v:[];}
  async function get(url){
    var controller=new AbortController(),timer=setTimeout(function(){controller.abort();},15000);
    try{
      var response=await root.fetch(url+(url.indexOf('?')<0?'?':'&')+'_gp='+Date.now(),{cache:'no-store',headers:{Accept:'application/json'},signal:controller.signal});
      if(!response.ok)throw Error('HTTP '+response.status);
      return await response.json();
    }finally{clearTimeout(timer);}
  }
  api.load=async function(agent){
    var values=await Promise.allSettled([get(agent+'/latest'),get('./data/homepage-snapshot.json'),get('./data/homepage-scoreboard.json'),get('./data/homepage-result-archive.json')]);
    function value(i){return values[i].status==='fulfilled'?values[i].value:null;}
    var now=Date.now(),mirror=value(2),board=null,previous=null,scoreStamp=Date.parse(mirror&&mirror.fetchedAt||'');
    if(mirror&&mirror.ok===true&&Number.isFinite(scoreStamp)&&now-scoreStamp<=api.MAX_AGE&&scoreStamp-now<=300000){
      var raw=mirror.scoreboard;
      if(raw&&raw.season&&(raw.week||{}).number&&Array.isArray(raw.events)){
        board=raw;previous=mirror.previousScoreboard||null;
      }
    }
    var candidates=[value(0),value(1)].filter(function(p){return p&&p.ok===true&&p.snapshot;}).map(function(p){return p.snapshot;});
    var result=api.compose(board,candidates,previous,value(3),now);
    var valid=candidates.filter(function(s){return api.current(s,board,now);}).sort(function(a,b){return Date.parse(b.generatedAt)-Date.parse(a.generatedAt);})[0];
    // Newer analysis snapshots can carry newer live scores than the hourly
    // fallback. Never replace those scores with an older scoreboard mirror.
    if(valid&&(!board||Date.parse(valid.generatedAt)>=scoreStamp)){
      result.games=list(valid.games);
      result.scoreStrip=list(valid.scoreStrip).length?valid.scoreStrip:result.games.map(function(g){return {gameId:g.id,kickoff:g.date,state:g.status.state,status:g.status.shortDetail,away:g.teams.away.abbreviation,home:g.teams.home.abbreviation,awayScore:g.teams.away.score,homeScore:g.teams.home.score};});
      result.generatedAt=valid.generatedAt;
      result.feedStatus.gamesCheckedAt=valid.generatedAt;
      result.feedStatus.scoreSource='analysis-agent';
    }else if(board){
      result.generatedAt=valid?valid.generatedAt:mirror.fetchedAt;
      result.feedStatus.gamesCheckedAt=mirror.fetchedAt;
      result.feedStatus.scoreSource='timestamped-scoreboard-snapshot';
    }
    result.mode=result.games.some(function(g){return (g.status||{}).state==='in';})?'live':'pregame';
    return result;
  };
  var oldPaint=api.paint;
  api.paint=function(snapshot){
    oldPaint(snapshot);
    if(!root.document)return;
    var doc=root.document,status=(snapshot||{}).feedStatus||{};
    if(!status.available){var label=doc.getElementById('connection-label');if(label)label.textContent='Current game feed unavailable';}
    if(!status.analysisCurrent){
      doc.querySelectorAll('.spotlight-summary strong').forEach(function(el){el.textContent='\u2014';});
      var availability=doc.getElementById('availability-grid');if(availability)availability.innerHTML='<div class="empty" style="grid-column:1/-1">Current availability analysis is awaiting refresh. No reports shown does not mean there are no injuries.</div>';
    }
  };
  // Existing projection refreshes can repaint individual sections without
  // renderAll. Preserve the stale-analysis labels after those repaints too.
  function hook(){
    ['renderSpotlight','renderEdges','renderAvailability','renderHeader'].forEach(function(key){
      var fn=root[key];if(typeof fn!=='function'||fn.gpFeedHook)return;
      var wrapped=function(){var result=fn.apply(this,arguments);api.paint(root.state&&root.state.snapshot);return result;};
      wrapped.gpFeedHook=true;root[key]=wrapped;
    });
  }
  if(root.document){if(root.document.readyState==='loading')root.document.addEventListener('DOMContentLoaded',hook,{once:true});else hook();}
})(typeof window!=='undefined'?window:globalThis);
