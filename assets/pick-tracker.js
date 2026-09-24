/* Read-only view of the cumulative exact-stat ledger. Does not create picks or grades. */
(function (root) {
  'use strict';
  var POSITIONS = ['QB', 'RB', 'WR', 'TE'];
  var POSITION_NAMES = {QB:'Quarterbacks', RB:'Running backs', WR:'Wide receivers', TE:'Tight ends', OTHER:'Other positions'};
  var MODELS = ['v2.1-tracked-1', 'workload-trial-1'];
  var MODEL_NAMES = {'v2.1-tracked-1':'v2.1 original', 'workload-trial-1':'Workload trial'};
  var LABELS = {passing_yards:'Passing yards', passing_tds:'Passing TD', rushing_yards:'Rushing yards', rushing_tds:'Rushing TD', receiving_yards:'Receiving yards', receiving_tds:'Receiving TD', scrimmage_yards:'Rush + receiving yards', scrimmage_tds:'Rush + receiving TD', receptions:'Receptions', targets:'Targets', carries:'Carries'};
  var STATUS_NAMES = {graded:'Fully graded', pending:'Pending kickoff', awaiting:'Awaiting final stats', live:'Live', partial:'Partial results', 'no-data':'Stats unavailable', excluded:'Excluded capture', conflict:'Check stat sources'};
  var MAX_SCORE_AGE = 90 * 60 * 1000;
  function list(v) { return Array.isArray(v) ? v : []; }
  function number(v) { return !['number','string'].includes(typeof v) || String(v).trim()==='' ? null : Number.isFinite(Number(v)) ? Number(v) : null; }
  function esc(v) { return String(v == null ? '' : v).replace(/[&<>"']/g, function(c) { return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]; }); }
  function fmt(v) { var n=number(v); return n==null ? '\u2014' : n.toLocaleString(undefined,{maximumFractionDigits:2}); }
  function date(v) { var t=Date.parse(v); return Number.isFinite(t) ? new Date(t).toLocaleString(undefined,{month:'short',day:'numeric',hour:'numeric',minute:'2-digit'}) : 'Date unavailable'; }
  function normalized(v) { return String(v||'').toLowerCase().replace(/[^a-z0-9]/g,''); }
  function label(k) { return LABELS[k] || String(k).replace(/_/g,' '); }
  function modelName(k) { return MODEL_NAMES[k] || k; }
  function groupKey(r) { return String(r.season)+'|'+String(r.gameId)+'|'+String(r.athleteId); }
  function metricKeys(g) { return Array.from(new Set(g.records.flatMap(function(r) { return Object.keys(r.predictions||{}); }))); }
  function outcome(r, outcomes) { return outcomes[r.id] || {}; }
  function validCapture(r, outcomes) {
    return outcome(r,outcomes).status!=='INVALID_CAPTURE' && Number.isFinite(Date.parse(r.recordedAt)) && Date.parse(r.recordedAt)<Date.parse(r.kickoff);
  }
  function metricGrade(r, k, outcomes) {
    if (!r || !validCapture(r,outcomes)) return null;
    var o=outcome(r,outcomes), m=(o.metrics||{})[k];
    if (o.status!=='FINAL' || !m || m.status!=='GRADED' || number(m.actual)==null || number(m.absoluteError)==null || number(m.prediction)!==number(r.predictions[k])) return null;
    return m;
  }
  function actualFor(g, k, outcomes) {
    var values=g.records.map(function(r) { var m=metricGrade(r,k,outcomes); return m ? number(m.actual) : null; }).filter(function(v) { return v!=null; });
    var unique=Array.from(new Set(values));
    return {value:unique.length===1 ? unique[0] : null, conflict:unique.length>1};
  }
  function groupStatus(g, outcomes, games, now) {
    var usable=g.records.filter(function(r) { return validCapture(r,outcomes); });
    if (!usable.length) return 'excluded';
    if (metricKeys(g).some(function(k) { return actualFor(g,k,outcomes).conflict; })) return 'conflict';
    var total=0, graded=0, noData=0;
    usable.forEach(function(r) {
      Object.keys(r.predictions||{}).forEach(function(k) {
        if (number(r.predictions[k])==null) return;
        total++;
        if (metricGrade(r,k,outcomes)) graded++;
        else if (outcome(r,outcomes).status==='FINAL' && ((outcome(r,outcomes).metrics||{})[k]||{}).status==='NO_DATA') noData++;
      });
    });
    if (graded && graded===total && usable.length===g.records.length) return 'graded';
    if (graded) return 'partial';
    if (total && noData===total) return 'no-data';
    var game=games[String(g.gameId)];
    if (game && game.state==='in') return 'live';
    if (game && game.completed) return 'awaiting';
    return Date.parse(g.kickoff)>now ? 'pending' : 'awaiting';
  }
  function groupsFrom(data, games, now) {
    var map=new Map(), ids=new Set();
    list(data.forecasts).forEach(function(r) {
      if (!r.id || !r.athleteId || !r.gameId || !r.playerName || !r.model || !r.predictions || typeof r.predictions!=='object') throw Error('Incomplete saved forecast');
      if (ids.has(r.id)) throw Error('Duplicate forecast ID');
      ids.add(r.id);
      var key=groupKey(r), g=map.get(key);
      if (!g) {
        g={key:key, playerName:r.playerName, athleteId:r.athleteId, player_id:r.player_id, team:r.team, opponent:r.opponent, season:r.season, week:r.week, kickoff:r.kickoff, gameId:r.gameId, position:POSITIONS.includes(r.position)?r.position:'OTHER', records:[]};
        map.set(key,g);
      }
      if (g.records.some(function(x) { return x.model===r.model; })) throw Error('Duplicate model in a player-game pick');
      if (g.team!==r.team || g.opponent!==r.opponent || (POSITIONS.includes(r.position)?r.position:'OTHER')!==g.position) throw Error('Conflicting saved player identity');
      g.records.push(r);
    });
    return Array.from(map.values()).map(function(g) {
      g.status=groupStatus(g,data.outcomes||{},games||{},now||Date.now());
      return g;
    }).sort(function(a,b) { return Date.parse(a.kickoff)-Date.parse(b.kickoff) || a.playerName.localeCompare(b.playerName); });
  }
  function filtered(groups, f, isFollowed, ignorePosition) {
    return groups.filter(function(g) {
      var s=g.status;
      return (ignorePosition || f.position==='all' || g.position===f.position) &&
        (f.week==='all' || String(g.season)+'|'+String(g.week)===f.week) &&
        (f.team==='all' || g.team===f.team) &&
        (!f.query || normalized(g.playerName+' '+g.team+' '+g.opponent).includes(normalized(f.query))) &&
        (!f.favorites || isFollowed(g)) &&
        (f.status==='all' || f.status===s || (f.status==='awaiting' && ['pending','awaiting'].includes(s)) || (f.status==='unavailable' && ['no-data','excluded','conflict'].includes(s)));
    });
  }
  function counts(groups) {
    return {total:groups.length, graded:groups.filter(function(g) { return g.status==='graded'; }).length, awaiting:groups.filter(function(g) { return ['pending','awaiting','live'].includes(g.status); }).length, review:groups.filter(function(g) { return ['partial','no-data','excluded','conflict'].includes(g.status); }).length};
  }
  function gamesFrom(mirror, snapshot, now) {
    var result={};
    function fresh(v) { var t=Date.parse(v); return Number.isFinite(t) && now-t<=MAX_SCORE_AGE && t-now<=300000; }
    if (mirror && mirror.ok && fresh(mirror.fetchedAt)) {
      [mirror.scoreboard,mirror.previousScoreboard].filter(Boolean).forEach(function(b) {
        list(b.events).forEach(function(e) { var t=(e.status||{}).type||{}; result[String(e.id)]={state:t.state,completed:t.completed===true,at:Date.parse(mirror.fetchedAt)}; });
      });
    }
    var s=snapshot && snapshot.ok && snapshot.snapshot;
    if (s && fresh(s.generatedAt)) list(s.games).forEach(function(g) {
      if (!result[String(g.id)] || Date.parse(s.generatedAt)>=result[String(g.id)].at) result[String(g.id)]={state:(g.status||{}).state,completed:(g.status||{}).completed===true,at:Date.parse(s.generatedAt)};
    });
    return result;
  }
  var api={number:number, groupsFrom:groupsFrom, filtered:filtered, counts:counts, actualFor:actualFor, metricGrade:metricGrade, gamesFrom:gamesFrom};
  if (typeof module!=='undefined' && module.exports) module.exports=api;
  root.GPPickTracker=api;
  if (!root.document) return;

  var doc=root.document, data=null, all=[], games={}, loading=false, timer=null, position='all', expanded=new Set(), expandAll=false, lastGood=null;
  function el(id) { return doc.getElementById(id); }
  function readFavorites() { try { var f=JSON.parse(root.localStorage.getItem('gridironPulseFavoritesV1')||'{}'); return f && typeof f==='object' ? f : {}; } catch(e) { return {}; } }
  function followed(g) { return list(readFavorites().players).some(function(p) { return String(p.athleteId||p.key)===String(g.athleteId); }); }
  function toggleFollow(g) {
    var f=readFavorites(), players=list(f.players).slice(), i=players.findIndex(function(p) { return String(p.athleteId||p.key)===String(g.athleteId); });
    if (i>=0) players.splice(i,1);
    else players.push({key:String(g.athleteId),athleteId:String(g.athleteId),name:g.playerName,team:g.team,position:g.position});
    f.players=players;
    try { root.localStorage.setItem('gridironPulseFavoritesV1',JSON.stringify(f)); render(); }
    catch(e) { showWarning('This browser could not save favorites. Your saved forecasts are unchanged.'); }
  }
  function filters() { return {position:position, query:el('pt-search').value, week:el('pt-week').value, team:el('pt-team').value, status:el('pt-status').value, favorites:el('pt-favorites').checked}; }
  function showWarning(message) { el('pt-warning').textContent=message; el('pt-warning').hidden=!message; }
  function nameLink(g) { return root.GPPlayerStats ? root.GPPlayerStats.link({name:g.playerName,athleteId:g.athleteId,player_id:g.player_id,position:g.position,team:g.team},g.playerName) : esc(g.playerName); }
  function primaryMetric(g) {
    var wanted={QB:'passing_yards',RB:'scrimmage_yards',WR:'receiving_yards',TE:'receiving_yards'}[g.position];
    return metricKeys(g).includes(wanted) ? wanted : metricKeys(g)[0];
  }
  function primaryActual(g, k) {
    var a=actualFor(g,k,data.outcomes||{});
    return a.conflict ? 'Conflict' : fmt(a.value);
  }
  function prediction(r,k) { return r ? number(r.predictions[k]) : null; }
  function errorCell(r,k) {
    if (!r || prediction(r,k)==null) return '<td>\u2014</td>';
    if (!validCapture(r,data.outcomes||{})) return '<td>\u2014<small>Excluded</small></td>';
    var m=metricGrade(r,k,data.outcomes||{});
    if (!m) return '<td>\u2014<small>'+(((outcome(r,data.outcomes||{}).metrics||{})[k]||{}).status==='NO_DATA'?'No data':'Not graded')+'</small></td>';
    var signed=number(m.error), direction=signed===0?'Exact':signed>0?'Above forecast':'Below forecast';
    return '<td>'+fmt(m.absoluteError)+'<small>'+esc(direction)+'</small></td>';
  }
  function detailsHTML(g) {
    var baseline=g.records.find(function(r) { return r.model===MODELS[0]; }), trial=g.records.find(function(r) { return r.model===MODELS[1]; });
    var rows=metricKeys(g).map(function(k) {
      var a=actualFor(g,k,data.outcomes||{});
      return '<tr data-stat="'+esc(k)+'"><th scope="row">'+esc(label(k))+'</th><td data-model="'+MODELS[0]+'">'+fmt(prediction(baseline,k))+'</td><td data-model="'+MODELS[1]+'">'+fmt(prediction(trial,k))+'</td><td class="pt-stat-actual">'+(a.conflict?'Check sources':fmt(a.value))+'</td>'+errorCell(baseline,k)+errorCell(trial,k)+'</tr>';
    }).join('');
    var stamps=g.records.map(function(r) {
      return '<div class="pt-capture"><b>'+esc(modelName(r.model))+'</b>Saved: '+esc(date(r.recordedAt))+'<br>Input timestamp: '+esc(date(r.sourceGeneratedAt))+'<br>Fingerprint: '+esc(r.forecastHash||'Unavailable')+(number(r.historyGames)!=null?'<br>History: '+esc(r.historyGames)+' same-team appearances.':'')+'</div>';
    }).join('');
    return '<div class="pt-detail-body"><div class="pt-table-scroll" tabindex="0" role="region" aria-label="Saved forecasts and actual stats for '+esc(g.playerName)+'"><table><caption>Saved numbers for this game only. Scroll sideways on small screens for error columns.</caption><thead><tr><th scope="col">Statistic</th><th scope="col">v2.1 saved</th><th scope="col">Trial saved</th><th scope="col">Actual</th><th scope="col">v2.1 error</th><th scope="col">Trial error</th></tr></thead><tbody>'+rows+'</tbody></table></div><p class="pt-detail-note">A dash means not projected, not yet graded, or unavailable; it never means zero. Error columns use the saved grader, not a new grading rule.</p>'+(!baseline||!trial?'<p class="pt-detail-note">'+(!baseline?'No eligible v2.1':'No eligible workload trial')+' forecast was captured for this player and game.</p>':'')+'<div class="pt-captures">'+stamps+'</div></div>';
  }
  function pickHTML(g) {
    var k=primaryMetric(g), b=g.records.find(function(r) { return r.model===MODELS[0]; }), t=g.records.find(function(r) { return r.model===MODELS[1]; });
    var initials=String(g.playerName).split(/\s+/).filter(Boolean).map(function(x) { return x[0]; }).slice(0,2).join('');
    return '<article class="pt-pick" data-pick-key="'+esc(g.key)+'" data-position="'+esc(g.position)+'"><div class="pt-pick-main"><div class="pt-player"><span class="pt-avatar" aria-hidden="true">'+esc(initials)+'</span><div><h3>'+nameLink(g)+'</h3><small>'+esc(g.team+' / '+g.position)+'</small></div></div><div class="pt-game"><b>'+esc(g.team+' vs '+g.opponent)+'</b><small>'+esc(g.season+' / Week '+g.week)+'</small><small>'+esc(date(g.kickoff))+'</small></div><div class="pt-save"><small>'+esc(label(k))+' / saved</small><div><span>v2.1<strong>'+fmt(prediction(b,k))+'</strong></span><span>WORKLOAD<strong>'+fmt(prediction(t,k))+'</strong></span></div></div><div class="pt-actual"><small>Actual '+esc(label(k))+'</small><strong>'+primaryActual(g,k)+'</strong></div><div class="pt-status-cell"><span class="pt-badge '+esc(g.status)+'">'+esc(STATUS_NAMES[g.status])+'</span><button type="button" class="pt-follow" data-pt-follow="'+esc(g.key)+'" aria-label="'+esc((followed(g)?'Unfollow ':'Follow ')+g.playerName)+'" aria-pressed="'+followed(g)+'">'+(followed(g)?'\u2605 Following':'\u2606 Follow')+'</button></div></div><details class="pt-detail" data-detail-key="'+esc(g.key)+'"'+(expandAll||expanded.has(g.key)?' open':'')+'><summary>All stats &amp; saved forecast details</summary>'+detailsHTML(g)+'</details></article>';
  }
  function optionHTML(value,title) { return '<option value="'+esc(value)+'">'+esc(title)+'</option>'; }
  function setOptions() {
    var w=el('pt-week').value, t=el('pt-team').value;
    var weeks=Array.from(new Set(all.map(function(g) { return String(g.season)+'|'+String(g.week); }))).sort(function(a,b) { var x=a.split('|').map(Number),y=b.split('|').map(Number); return y[0]-x[0]||y[1]-x[1]; });
    el('pt-week').innerHTML=optionHTML('all','All saved weeks')+weeks.map(function(x) { var p=x.split('|'); return optionHTML(x,p[0]+' / Week '+p[1]); }).join('');
    el('pt-week').value=weeks.includes(w)?w:'all';
    var teams=Array.from(new Set(all.map(function(g) { return g.team; }))).sort();
    el('pt-team').innerHTML=optionHTML('all','All teams')+teams.map(function(x) { return optionHTML(x,x); }).join('');
    el('pt-team').value=teams.includes(t)?t:'all';
  }
  function render() {
    if (!data) return;
    all=groupsFrom(data,games,Date.now());
    var f=filters(), shown=filtered(all,f,followed,false), base=filtered(all,f,followed,true), n=counts(shown);
    ['total','graded','awaiting','review'].forEach(function(k) { el('pt-'+k).textContent=n[k]; });
    var positions=POSITIONS.concat(all.some(function(g) { return g.position==='OTHER'; })?['OTHER']:[]);
    el('pt-positions').style.gridTemplateColumns='repeat('+(positions.length+1)+',minmax(0,1fr))';
    el('pt-positions').innerHTML=['all'].concat(positions).map(function(p) {
      var count=p==='all'?base.length:base.filter(function(g) { return g.position===p; }).length;
      return '<button type="button" data-pt-position="'+p+'" aria-pressed="'+(position===p)+'"><span><b>'+esc(p==='all'?'ALL':p)+'</b><small>'+esc(POSITION_NAMES[p]||'Every position')+'</small></span><span class="pt-position-count">'+count+'</span></button>';
    }).join('');
    el('pt-count').textContent=shown.length+' player-game picks shown / '+all.length+' saved. Local kickoff times. Expand a pick for all statistics.';
    el('pt-groups').innerHTML=shown.length?positions.map(function(p) {
      var group=shown.filter(function(g) { return g.position===p; });
      if (!group.length) return '';
      var complete=group.filter(function(g) { return g.status==='graded'; }).length;
      return '<section class="pt-position-group" data-group-position="'+p+'" aria-labelledby="pt-heading-'+p+'"><header class="pt-group-head"><span>'+p+'</span><div><h2 id="pt-heading-'+p+'">'+esc(POSITION_NAMES[p])+'</h2><p>'+group.length+' picks / '+complete+' fully graded</p></div><small>NAME / MATCHUP / PROJECTION / RESULT</small></header>'+group.map(pickHTML).join('')+'</section>';
    }).join(''):'<div class="pt-empty">No saved picks match these filters. Clear filters to see all captured player-game picks.</div>';
    el('pt-groups').setAttribute('aria-busy','false');
    el('pt-groups').querySelectorAll('details[data-detail-key]').forEach(function(d) { d.addEventListener('toggle',function() { if (d.open) expanded.add(d.dataset.detailKey); else expanded.delete(d.dataset.detailKey); }); });
    api.data=data; api.groups=all;
  }
  async function get(url) {
    var c=new AbortController(), timeout=setTimeout(function() { c.abort(); },20000);
    try { var r=await root.fetch(url+'?pt='+Date.now(),{cache:'no-store',signal:c.signal}); if (!r.ok) throw Error('Feed HTTP '+r.status); return await r.json(); }
    finally { clearTimeout(timeout); }
  }
  async function load() {
    if (loading) return;
    loading=true; el('pt-refresh').disabled=true;
    try {
      var results=await Promise.allSettled([get('./data/projection-trial.json'),get('./data/homepage-scoreboard.json'),get('./data/homepage-snapshot.json')]);
      if (results[0].status!=='fulfilled') throw Error('Saved forecast feed is unavailable');
      var next=results[0].value;
      if (!next || next.trialOnly!==true || !Array.isArray(next.forecasts) || !next.outcomes || !Number.isFinite(Date.parse(next.generatedAt))) throw Error('Saved forecast feed failed validation');
      var nextGames=gamesFrom(results[1].status==='fulfilled'?results[1].value:null,results[2].status==='fulfilled'?results[2].value:null,Date.now());
      var nextGroups=groupsFrom(next,nextGames,Date.now());
      data=next; games=nextGames; all=nextGroups; lastGood=next.generatedAt;
      setOptions(); render();
      el('pt-feed-status').textContent='Results feed updated '+date(data.generatedAt)+' / '+all.length+' saved player-game picks / checks every 5 minutes while open.';
      var messages=list(data.warnings).slice();
      if (Date.now()-Date.parse(data.generatedAt)>MAX_SCORE_AGE) messages.unshift('Results feed is older than 90 minutes. Saved forecasts remain valid; grades and game status may lag.');
      if (!Object.keys(games).length) messages.push('No fresh game-status feed is available. Kickoff time alone is not treated as proof a game is live.');
      showWarning(messages.join(' '));
    } catch(error) {
      el('pt-feed-status').textContent=lastGood?'Update unavailable / showing saved data from '+date(lastGood):'Saved picks could not be loaded.';
      showWarning('No results were invented. Use Refresh results to retry.');
      if (!data) { el('pt-groups').innerHTML='<div class="pt-empty">The saved forecast feed is temporarily unavailable.</div>'; el('pt-groups').setAttribute('aria-busy','false'); }
    } finally { loading=false; el('pt-refresh').disabled=false; clearTimeout(timer); timer=setTimeout(load,300000); }
  }
  function init() {
    ['pt-search','pt-week','pt-team','pt-status','pt-favorites'].forEach(function(id) { el(id).addEventListener(id==='pt-search'?'input':'change',render); });
    el('pt-filters').addEventListener('submit',function(e) { e.preventDefault(); });
    el('pt-filters').addEventListener('reset',function() { position='all'; setTimeout(render,0); });
    el('pt-refresh').addEventListener('click',load);
    el('pt-expand').addEventListener('change',function() { expandAll=this.checked; expanded.clear(); render(); });
    el('pt-positions').addEventListener('click',function(e) {
      var b=e.target.closest('[data-pt-position]'); if (!b) return; position=b.dataset.ptPosition; render();
      el('pt-positions').querySelector('[data-pt-position="'+position+'"]').focus();
    });
    el('pt-groups').addEventListener('click',function(e) {
      var b=e.target.closest('[data-pt-follow]'); if (!b) return; var g=all.find(function(x) { return x.key===b.dataset.ptFollow; }); if (g) toggleFollow(g);
    });
    root.addEventListener('storage',function(e) { if (e.key==='gridironPulseFavoritesV1') render(); });
    load();
  }
  if (doc.readyState==='loading') doc.addEventListener('DOMContentLoaded',init,{once:true}); else init();
})(typeof window==='undefined'?globalThis:window);
