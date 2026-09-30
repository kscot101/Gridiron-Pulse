/* Gridiron Pulse: recent recorded game stats, shared by the homepage and projections. */
(function () {
  'use strict';
  var script = document.currentScript;
  var dataURL = new URL('../data/player-recent-games.json', script.src).href;
  var feed = null, pending = null, fetchedAt = 0, previousFocus = null;
  var dialog = null, known = new Map(), namesRegex = null, observedRefs = [];
  var timer = null, observer = null;
  var aliases = {LA:'LAR', STL:'LAR', JAC:'JAX', OAK:'LV', SD:'LAC', WSH:'WAS'};
  function arr(v) { return Array.isArray(v) ? v : []; }
  function esc(v) { return String(v == null ? '' : v).replace(/[&<>"']/g, function(c) { return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]; }); }
  function norm(v) { return String(v || '').toLowerCase().replace(/\b(jr|sr|ii|iii|iv|v)\b/g,'').replace(/[^a-z0-9]/g,''); }
  function team(v) { if (v && typeof v === 'object') v = v.abbreviation || v.team || ''; v = String(v || '').toUpperCase(); return aliases[v] || v; }
  function pos(v) { v = String(v || '').toUpperCase(); return ['FB','HB','TB'].includes(v) ? 'RB' : v; }
  function numeric(v) { if (v == null || v === '' || typeof v === 'boolean') return null; var n = Number(v); return Number.isFinite(n) ? n : null; }
  function fmt(v) { var n = numeric(v); return n == null ? '\u2014' : n.toLocaleString(undefined, {maximumFractionDigits:1}); }
  function describe(p) {
    p = p || {};
    return {name:String(p.name || p.playerName || p.player_display_name || p.displayName || p.player_name || p.player || ''),
      id:String(p.player_id || p.gsisId || p.gsis_id || p.id || p.playerKey || ''),
      espnId:String(p.athleteId || p.espnId || p.espn_id || ''),
      team:team(p.team || p.targetTeam || p.target_team || p.toTeam),
      position:pos(p.position || p.positionGroup || p.pos || p.target_position),
      gameId:String(p.gameId || p.eventId || p.game_id || ''),
      headshot:p.headshot || p.headshot_url || ''};
  }
  function link(p, label) {
    var d = describe(p);
    if (!d.name) return esc(label || 'Player');
    return '<button type="button" class="gp-player-name" data-gp-player="' + esc(JSON.stringify(d)) + '" aria-label="' + esc('View recent game stats for ' + d.name) + '">' + esc(label || d.name) + '</button>';
  }
  async function load(force) {
    if (!force && feed && Date.now() - fetchedAt < 15 * 60 * 1000) return feed;
    if (pending) return pending;
    var controller = new AbortController();
    var timeout = setTimeout(function() { controller.abort(); }, 20000);
    pending = fetch(dataURL + '?v=' + Math.floor(Date.now() / 900000), {cache:'no-cache', signal:controller.signal})
      .then(function(r) { if (!r.ok) throw Error('Stats feed unavailable'); return r.json(); })
      .then(function(data) {
        if (!data || data.ok !== true || data.schemaVersion !== 1 || !Array.isArray(data.players)) throw Error('Stats feed unavailable');
        data.byId = new Map(); data.byEspn = new Map(); data.byName = new Map();
        data.players.forEach(function(p) {
          if (p.id) data.byId.set(String(p.id), p);
          if (p.espnId) data.byEspn.set(String(p.espnId), p);
          var key = norm(p.name), group = data.byName.get(key) || [];
          group.push(p); data.byName.set(key, group);
        });
        feed = data; fetchedAt = Date.now(); return data;
      }).finally(function() { clearTimeout(timeout); pending = null; });
    return pending;
  }
  function resolve(d, data) {
    var exact = data.byId.get(d.id) || data.byEspn.get(d.espnId) || data.byEspn.get(d.id);
    if (exact) return exact;
    var matches = arr(data.byName.get(norm(d.name)));
    if (d.position) {
      var positionMatches = matches.filter(function(p) { return pos(p.position) === d.position; });
      if (positionMatches.length) matches = positionMatches;
      else if (['QB','RB','WR','TE','K','P'].includes(d.position)) return null;
    }
    if (matches.length > 1 && d.team) matches = matches.filter(function(p) { return arr(p.teams).map(team).includes(d.team); });
    // Ambiguous names never select someone else's statistics.
    return matches.length === 1 ? matches[0] : null;
  }
  function dateLabel(value) {
    if (!value) return '\u2014';
    var d = new Date(value + 'T12:00:00Z');
    return Number.isNaN(d.getTime()) ? value : d.toLocaleDateString(undefined, {month:'short', day:'numeric', year:'numeric', timeZone:'UTC'});
  }

  /* Current-opponent head-to-head. Kept inside the active player popup so
     search results and clickable names use one player-profile system. */
  var h2hCache = new Map();
  var offensivePositions = new Set(['QB','RB','WR','TE']);
  function seasonYear() {
    var d = new Date();
    return d.getUTCFullYear() - (d.getUTCMonth() < 2 ? 1 : 0);
  }
  function gameSide(game, side) {
    var item = game && game.teams && game.teams[side] || {};
    return {
      team: team(item.abbreviation || item.team || item.teamAbbreviation || item.code),
      name: String(item.displayName || item.teamName || item.name || item.abbreviation || item.team || '')
    };
  }
  function liveGames() {
    try {
      if (typeof window.allGames === 'function') return arr(window.allGames());
      return arr(window.state && window.state.snapshot && window.state.snapshot.games);
    } catch (e) { return []; }
  }
  function h2hOpponent(d) {
    if (!d || !offensivePositions.has(pos(d.position))) return null;
    var games = liveGames(), now = Date.now(), direct = null;
    if (d.gameId) direct = games.find(function(g){ return String(g.id) === String(d.gameId); });
    var pool = direct ? [direct] : games.filter(function(g) {
      var away = gameSide(g,'away').team, home = gameSide(g,'home').team;
      var state = String(g && g.status && g.status.state || '');
      return (away === d.team || home === d.team) && state !== 'post';
    }).sort(function(a,b) {
      var as = String(a && a.status && a.status.state || ''), bs = String(b && b.status && b.status.state || '');
      if (as === 'in' && bs !== 'in') return -1;
      if (bs === 'in' && as !== 'in') return 1;
      var at = Date.parse(a && a.date), bt = Date.parse(b && b.date);
      var av = Number.isFinite(at) ? Math.abs(at-now) : Number.MAX_SAFE_INTEGER;
      var bv = Number.isFinite(bt) ? Math.abs(bt-now) : Number.MAX_SAFE_INTEGER;
      return av-bv;
    });
    var game = pool[0];
    if (!game) return null;
    var away = gameSide(game,'away'), home = gameSide(game,'home'), other = null;
    if (away.team === d.team) other = home;
    else if (home.team === d.team) other = away;
    if (!other || !other.team) return null;
    return {team:other.team,name:other.name || other.team,gameId:String(game.id || ''),date:game.date || null};
  }
  function h2hNumeric(v) {
    if (v == null || v === '' || typeof v === 'boolean') return null;
    var n = Number(String(v).replace(/,/g,''));
    return Number.isFinite(n) ? n : null;
  }
  function h2hStatMap(names, values) {
    var raw = {};
    arr(names).forEach(function(name,i){ raw[name] = values && values[i] != null ? values[i] : null; });
    function get() {
      for (var i=0;i<arguments.length;i++) if (raw[arguments[i]] != null && h2hNumeric(raw[arguments[i]]) != null) return h2hNumeric(raw[arguments[i]]);
      return null;
    }
    return {
      completions:get('completions'),
      attempts:get('passingAttempts','attempts'),
      passingYards:get('passingYards'),
      passingTouchdowns:get('passingTouchdowns'),
      interceptions:get('interceptions','passingInterceptions'),
      carries:get('rushingAttempts','carries'),
      rushingYards:get('rushingYards'),
      rushingTouchdowns:get('rushingTouchdowns'),
      targets:get('receivingTargets','targets'),
      receptions:get('receptions'),
      receivingYards:get('receivingYards'),
      receivingTouchdowns:get('receivingTouchdowns')
    };
  }
  function parseEspnH2H(data, year, opponent) {
    if (!data || !Array.isArray(data.names) || !Array.isArray(data.seasonTypes)) return [];
    var rows = new Map();
    arr(data.seasonTypes).forEach(function(season) {
      var label = String(season.displayName || '');
      if (/preseason|all.star|pro bowl/i.test(label)) return;
      arr(season.categories).forEach(function(category) {
        if (category.type && category.type !== 'event') return;
        var split = String(category.splitType || '');
        if (split && split !== '2' && split !== '3') return;
        arr(category.events).forEach(function(line) {
          var id = String(line.eventId || ''), event = (data.events || {})[id];
          if (!id || !event) return;
          var opp = team(event.opponent);
          if (opp !== opponent) return;
          var result = String(event.gameResult || '');
          if (!/^[WLT]/.test(result)) return;
          var date = event.gameDate || event.date || '';
          var time = Date.parse(date);
          if (!Number.isFinite(time) || time > Date.now()) return;
          var stats = h2hStatMap(data.names,line.stats);
          rows.set(id,{
            gameId:id,date:date,season:Number(year),week:event.week,
            seasonType:/postseason|playoff/i.test(label) || split === '3' ? 'POST' : 'REG',
            team:team(event.team),opponent:opp,homeAway:event.atVs === '@' ? 'away' : 'home',
            result:result.charAt(0),score:String(event.score || ''),stats:stats
          });
        });
      });
    });
    return Array.from(rows.values());
  }
  async function fetchH2HSeason(espnId, year) {
    var key = String(espnId)+'|'+year, cached = h2hCache.get(key);
    if (cached) return cached;
    var promise = (async function() {
      var controller = new AbortController();
      var timeout = setTimeout(function(){controller.abort();},15000);
      try {
        var url='https://site.web.api.espn.com/apis/common/v3/sports/football/nfl/athletes/'+encodeURIComponent(espnId)+'/gamelog?season='+year;
        var response=await fetch(url,{cache:'no-store',headers:{Accept:'application/json'},signal:controller.signal});
        if(!response.ok) throw Error('HTTP '+response.status);
        return await response.json();
      } finally { clearTimeout(timeout); }
    })();
    h2hCache.set(key,promise);
    try { return await promise; } catch (e) { h2hCache.delete(key); throw e; }
  }
  function localH2H(entry, opponent) {
    return arr(entry && entry.games).filter(function(g){return team(g.opponent)===opponent;}).map(function(g){
      return {
        gameId:String(g.gameId||''),date:g.date,season:g.season,week:g.week,seasonType:g.seasonType,
        team:team(g.team),opponent:team(g.opponent),homeAway:g.homeAway,result:g.result,score:g.score,stats:g.stats||{}
      };
    });
  }
  async function loadH2H(d, entry) {
    if (!d || !offensivePositions.has(pos((entry && entry.position) || d.position))) return null;
    var opponent = h2hOpponent(d);
    if (!opponent) return {opponent:null,rows:[],failed:[],message:'Next opponent is not available yet.'};
    var espnId = String(d.espnId || (entry && entry.espnId) || '');
    var year = seasonYear(), oldest = Math.max(2017,year-9), rows = localH2H(entry,opponent.team), failed=[];
    if (espnId) {
      var years=[]; for(var y=year;y>=oldest;y--) years.push(y);
      var remote=await Promise.allSettled(years.map(function(y){return fetchH2HSeason(espnId,y).then(function(data){return parseEspnH2H(data,y,opponent.team);});}));
      remote.forEach(function(result,i){if(result.status==='fulfilled') rows=rows.concat(result.value); else failed.push(years[i]);});
    }
    var unique=new Map();
    rows.forEach(function(row){if(row && row.gameId) unique.set(String(row.gameId),row);});
    rows=Array.from(unique.values()).sort(function(a,b){return String(b.date).localeCompare(String(a.date));});
    return {opponent:opponent,rows:rows,failed:failed,year:year,oldest:oldest,espnId:espnId};
  }
  function h2hYards(row, position) {
    var s=row&&row.stats||{}, p=pos(position);
    if(p==='QB') return numeric(s.passingYards);
    if(p==='RB') {
      var rush=numeric(s.rushingYards), rec=numeric(s.receivingYards);
      return rush==null && rec==null ? null : (rush||0)+(rec||0);
    }
    return numeric(s.receivingYards);
  }
  function h2hTd(row, position) {
    var s=row&&row.stats||{}, p=pos(position);
    if(p==='QB') return (numeric(s.passingTouchdowns)||0)+(numeric(s.rushingTouchdowns)||0);
    if(p==='RB') return (numeric(s.rushingTouchdowns)||0)+(numeric(s.receivingTouchdowns)||0);
    return numeric(s.receivingTouchdowns)||0;
  }
  function renderH2H(section,d,result) {
    if (!section || !section.isConnected) return;
    section.setAttribute('aria-busy','false');
    if (!result || !offensivePositions.has(pos(d.position))) { section.hidden=true; return; }
    section.hidden=false;
    var opponent=result.opponent;
    if(!opponent){
      section.innerHTML='<div class="gp-h2h-head"><div><small>MATCHUP HISTORY</small><h3>Head to head</h3></div></div><p class="gp-h2h-note">'+esc(result.message||'Next opponent is not available yet.')+'</p>';
      return;
    }
    var rows=arr(result.rows), position=pos(d.position), yardLabel=position==='QB'?'Pass yds':position==='RB'?'Scrimmage yds':'Rec yds';
    var yards=rows.map(function(r){return h2hYards(r,position);}).filter(function(v){return v!=null;});
    var avg=yards.length?yards.reduce(function(a,b){return a+b;},0)/yards.length:null;
    var totalTd=rows.reduce(function(sum,row){return sum+h2hTd(row,position);},0);
    var record=rows.reduce(function(out,row){if(row.result==='W')out.w++;else if(row.result==='L')out.l++;else if(row.result==='T')out.t++;return out;},{w:0,l:0,t:0});
    var recordLabel=record.w+'-'+record.l+(record.t?'-'+record.t:'');
    var heading='<div class="gp-h2h-head"><div><small>MATCHUP HISTORY / HEAD TO HEAD</small><h3>vs '+esc(opponent.name||opponent.team)+(opponent.team&&String(opponent.name||'').indexOf(opponent.team)<0?' <span>· '+esc(opponent.team)+'</span>':'')+'</h3></div><b>'+rows.length+' meeting'+(rows.length===1?'':'s')+'</b></div>';
    if(!rows.length){
      var source=result.espnId?'No completed regular-season or playoff meetings were found from '+result.oldest+' through '+result.year+'.':'No prior meeting is available in the verified local history for this player.';
      section.innerHTML=heading+'<p class="gp-h2h-note">'+esc(source)+'</p>';
      return;
    }
    var summary='<div class="gp-h2h-summary"><div><strong>'+rows.length+'</strong><span>Meetings</span></div><div><strong>'+esc(avg==null?'\u2014':avg.toFixed(1))+'</strong><span>Avg '+esc(yardLabel)+'</span></div><div><strong>'+esc(totalTd)+'</strong><span>Total TD</span></div><div><strong>'+esc(recordLabel)+'</strong><span>Team record</span></div></div>';
    var fields=columns(position,rows).slice(0,6);
    var table='<div class="gp-log-scroll gp-h2h-scroll" role="region" aria-label="Head-to-head game statistics for '+esc(d.name)+'" tabindex="0"><table class="gp-log-table gp-h2h-table"><caption class="gp-sr-only">'+esc(d.name)+' head-to-head games versus '+esc(opponent.team)+'</caption><thead><tr><th scope="col">Game</th><th scope="col">Result</th>'+fields.map(function(f){return '<th scope="col">'+esc(f[0])+'</th>';}).join('')+'<th scope="col">Box</th></tr></thead><tbody>'+rows.map(function(row){
      var stats=row.stats||{},box=row.gameId&&/^\d+$/.test(row.gameId)?'<a href="https://www.espn.com/nfl/boxscore/_/gameId/'+encodeURIComponent(row.gameId)+'" target="_blank" rel="noopener noreferrer">View ↗</a>':'—';
      return '<tr><th scope="row">'+esc(dateLabel(String(row.date||'').slice(0,10)))+'<small>'+esc(row.season)+' · '+(row.seasonType==='POST'?'Playoffs':'Week '+esc(row.week))+'</small></th><td><span class="gp-log-result '+(row.result==='W'?'win':row.result==='L'?'loss':'tie')+'">'+esc(row.result||'—')+'</span><small>'+esc(row.score||'')+'</small></td>'+fields.map(function(f){return '<td>'+esc(cell(stats,f[1]))+'</td>';}).join('')+'<td>'+box+'</td></tr>';
    }).join('')+'</tbody></table></div>';
    var partial=result.failed.length?'<p class="gp-h2h-note">Some older seasons could not be loaded. Showing every verified meeting that was available.</p>':'<p class="gp-h2h-note">Completed regular-season and playoff meetings only. Preseason excluded.</p>';
    section.innerHTML=heading+summary+partial+table;
  }
  async function fillH2H(section,d) {
    if(!offensivePositions.has(pos(d.position))){section.hidden=true;return;}
    section.hidden=false; section.setAttribute('aria-busy','true');
    section.innerHTML='<div class="gp-h2h-head"><div><small>MATCHUP HISTORY / HEAD TO HEAD</small><h3>Loading current opponent…</h3></div></div>';
    try{
      var data=await load(false), entry=resolve(d,data), result=await loadH2H(d,entry);
      renderH2H(section,d,result);
    }catch(err){
      if(!section.isConnected)return;
      section.setAttribute('aria-busy','false');
      section.innerHTML='<div class="gp-h2h-head"><div><small>MATCHUP HISTORY / HEAD TO HEAD</small><h3>Current opponent</h3></div></div><p class="gp-h2h-note">Head-to-head history is temporarily unavailable. Recent games are still shown below.</p>';
    }
  }
  function columns(position, games) {
    var qb = [['C/ATT',['completions','attempts']],['Pass Yds','passingYards'],['Pass TD','passingTouchdowns'],['INT','interceptions'],['Rush Yds','rushingYards'],['Rush TD','rushingTouchdowns']];
    var rb = [['CAR','carries'],['Rush Yds','rushingYards'],['Rush TD','rushingTouchdowns'],['REC','receptions'],['Rec Yds','receivingYards'],['Rec TD','receivingTouchdowns']];
    var wr = [['TGT','targets'],['REC','receptions'],['Rec Yds','receivingYards'],['Rec TD','receivingTouchdowns']];
    if (position === 'QB') return qb;
    if (position === 'RB') return rb;
    if (position === 'WR' || position === 'TE') {
      if (games.some(function(g) { return numeric((g.stats || {}).carries) > 0; })) wr.push(['Rush Yds','rushingYards'],['Rush TD','rushingTouchdowns']);
      return wr;
    }
    if (position === 'K') return [['FG',['fieldGoalsMade','fieldGoalsAttempted']],['XP',['extraPointsMade','extraPointsAttempted']]];
    if (position === 'P') return [['Punts','punts'],['Punt Yds','puntYards'],['Inside 20','puntInside20']];
    if (/^(DE|DT|DL|NT|EDGE|LB|ILB|OLB|MLB|CB|DB|S|SS|FS)$/.test(position)) return [['Solo','soloTackles'],['AST','assistedTackles'],['Sacks','sacks'],['INT','defensiveInterceptions'],['PD','passesDefended'],['FF','forcedFumbles']];
    if (games.some(function(g) { return numeric((g.stats || {}).attempts) > 0; })) return qb;
    if (games.some(function(g) { return numeric((g.stats || {}).targets) > 0; })) return wr;
    if (games.some(function(g) { return numeric((g.stats || {}).carries) > 0; })) return rb;
    return [];
  }
  function cell(stats, key) {
    if (Array.isArray(key)) {
      return key.every(function(k) { return numeric(stats[k]) != null; }) ? key.map(function(k) { return fmt(stats[k]); }).join('/') : '\u2014';
    }
    return fmt(stats[key]);
  }
  function render(section, d, entry, data, count) {
    var games = entry ? arr(entry.games).slice().sort(function(a,b) { return String(b.date).localeCompare(String(a.date)) || b.week-a.week; }).slice(0,count) : [];
    var updated = new Date(data.generatedAt);
    var stamp = Number.isNaN(updated.getTime()) ? '' : updated.toLocaleString(undefined, {month:'short',day:'numeric',hour:'numeric',minute:'2-digit'});
    var source = '<p class="gp-log-source">Source: <a href="https://nflreadr.nflverse.com/reference/load_player_stats.html" target="_blank" rel="noopener noreferrer">nflverse game stats</a>' + (stamp ? ' &middot; Feed updated ' + esc(stamp) : '') + '. Not live play-by-play.</p>';
    var head = '<div class="gp-log-heading"><div><h3>Recent games</h3><p>Actual results, not projections.</p></div>' + (entry && entry.games.length > 5 ? '<div class="gp-log-switch" aria-label="Number of recent games"><button type="button" data-gp-count="5" aria-pressed="'+(count===5)+'">Last 5</button><button type="button" data-gp-count="10" aria-pressed="'+(count===10)+'">Last 10</button></div>' : '') + '</div>';
    if (!games.length) {
      section.innerHTML = head + '<div class="gp-log-message">No recent regular-season or playoff game records are available for ' + esc(d.name) + '. New players may not have an NFL game record yet. Missing stats are not shown as zero.</div>' + source;
      return;
    }
    var fields = columns(pos(entry.position || d.position),games);
    var oldSeason = games[0].season < data.season;
    var note = oldSeason ? 'No '+data.season+' season game stats have been published for this player yet. Showing the latest available games from the '+games[0].season+' season or earlier.' : 'Latest '+games.length+' recorded games. Regular season and playoffs; preseason excluded.';
    var table = '<div class="gp-log-scroll" role="region" aria-label="Recent game statistics for '+esc(d.name)+'" tabindex="0"><table class="gp-log-table"><caption class="gp-sr-only">'+esc(d.name)+' recent recorded NFL game statistics</caption><thead><tr><th scope="col">Game</th><th scope="col">Matchup</th><th scope="col">Result</th>' + fields.map(function(c) { return '<th scope="col">'+esc(c[0])+'</th>'; }).join('') + '</tr></thead><tbody>';
    table += games.map(function(g) {
      var stats = g.stats || {};
      return '<tr><th scope="row">'+esc(dateLabel(g.date))+'<small>'+esc(g.season)+' &middot; '+(g.seasonType==='POST' ? 'Playoffs' : 'Week '+esc(g.week))+'</small></th><td>'+esc(g.team)+'<small>'+esc((g.homeAway==='home' ? 'vs ' : '@ ')+g.opponent)+'</small></td><td><span class="gp-log-result '+(g.result==='W'?'win':g.result==='L'?'loss':'tie')+'">'+esc(g.result || '\u2014')+'</span><small>'+esc(g.score || '')+'</small></td>'+fields.map(function(c) { return '<td>'+esc(cell(stats,c[1]))+'</td>'; }).join('')+'</tr>';
    }).join('') + '</tbody></table></div>';
    section.innerHTML = head + '<p class="gp-log-note">'+esc(note)+'</p>' + '<p class="gp-log-swipe">Swipe the table sideways for all stats &rarr;</p>' + table + (!fields.length ? '<p class="gp-log-note">Detailed position-specific counters are not available for these records.</p>' : '') + '<p class="gp-log-key">Yds = yards &middot; TD = touchdowns &middot; CAR = carries &middot; REC = catches &middot; TGT = targets &middot; INT = interceptions. A dash means unavailable.</p>' + source;
    section.querySelectorAll('[data-gp-count]').forEach(function(b) { b.onclick = function() { render(section,d,entry,data,Number(b.dataset.gpCount)); section.querySelector('[data-gp-count="'+b.dataset.gpCount+'"]').focus(); }; });
  }
  async function fill(section, d, force) {
    section.setAttribute('aria-busy','true');
    section.innerHTML = '<div class="gp-log-heading"><div><h3>Recent games</h3><p>Actual results, not projections.</p></div></div><p class="gp-log-message" role="status">Loading recent game stats...</p>';
    try {
      var data = await load(force);
      if (!section.isConnected) return;
      render(section,d,resolve(d,data),data,5);
    } catch (err) {
      if (!section.isConnected) return;
      section.innerHTML = '<div class="gp-log-heading"><h3>Recent games</h3></div><p class="gp-log-message" role="status">Recent stats could not be loaded. Your projections and profile are still available.</p><button type="button" class="gp-log-retry">Retry stats</button>';
      section.querySelector('button').onclick = function() { fill(section,d,true); };
    } finally { section.setAttribute('aria-busy','false'); }
  }
  function attach(player, container) {
    if (typeof container === 'string') container = document.querySelector(container);
    if (!container) return;
    var d=describe(player);
    var old = container.querySelector('.gp-recent-root'); if (old) old.remove();
    var oldH2H = container.querySelector('.gp-h2h-root'); if (oldH2H) oldH2H.remove();
    var h2h = document.createElement('section'); h2h.className='gp-h2h-root';
    var section = document.createElement('section'); section.className = 'gp-recent-root';
    var first = container.querySelector('.modal-section');
    if (first) { first.before(h2h); first.before(section); } else { container.appendChild(h2h); container.appendChild(section); }
    fillH2H(h2h,d);
    fill(section,d);
    var overlay = container.closest('.overlay');
    if (overlay) {
      overlay.setAttribute('aria-label', d.name + ' player profile, head-to-head and recent games');
      requestAnimationFrame(function() { if (section.isConnected && overlay.classList.contains('open')) { overlay.scrollTop = 0; var close = overlay.querySelector('[data-close]'); if(close) close.focus(); } });
    }
  }
  function mainPlayers() {
    try { return typeof window.allPlayers === 'function' ? arr(window.allPlayers()) : []; } catch (e) { return []; }
  }
  function matchingMain(d) {
    var players = mainPlayers();
    var exact = players.find(function(p) { var q=describe(p); return (d.espnId && d.espnId===q.espnId) || (d.id && (d.id===q.id || d.id===q.espnId)); });
    if (exact) return exact;
    var matches=players.filter(function(p) { var q=describe(p); return norm(q.name)===norm(d.name) && (!d.position || !q.position || q.position===d.position); });
    if(matches.length>1 && d.team) matches=matches.filter(function(p) { return describe(p).team===d.team; });
    return matches.length===1 ? matches[0] : null;
  }
  function open(player) {
    var d=describe(player); previousFocus=document.activeElement;
    var entity=matchingMain(d);
    if (entity && typeof window.openProfile==='function' && typeof window.playerKey==='function') {
      window.openProfile('player',window.playerKey(entity)); return;
    }
    if (!dialog) {
      dialog=document.createElement('dialog'); dialog.className='gp-player-dialog'; dialog.setAttribute('aria-labelledby','gp-player-title');
      document.body.appendChild(dialog);
      dialog.addEventListener('click',function(e) { if(e.target===dialog) { var r=dialog.getBoundingClientRect(); if(e.clientX<r.left || e.clientX>r.right || e.clientY<r.top || e.clientY>r.bottom) dialog.close(); } });
      dialog.addEventListener('close',function() { if(previousFocus && previousFocus.isConnected) previousFocus.focus(); });
    }
    dialog.innerHTML='<div class="gp-dialog-head"><div><p>PLAYER GAME LOG</p><h2 id="gp-player-title">'+esc(d.name)+'</h2><small>'+esc([d.team,d.position].filter(Boolean).join(' / '))+'</small></div><button type="button" class="gp-dialog-close" aria-label="Close player stats">&times;</button></div><div class="gp-dialog-body"></div>';
    dialog.querySelector('.gp-dialog-close').onclick=function(){dialog.close();};
    attach(d,dialog.querySelector('.gp-dialog-body'));
    if (!dialog.open) dialog.showModal();
  }
  function refreshNames() {
    var state=window.state || {};
    var refs=[state.snapshot,state.seasonOutlook,state.playerContext];
    if (refs.every(function(x,i){return x===observedRefs[i];}) && namesRegex) return;
    observedRefs=refs;
    var players=mainPlayers().concat(arr(state.playerContext && state.playerContext.players));
    arr(state.snapshot && state.snapshot.results).forEach(function(r) { players.push(Object.assign({},r,{name:r.player || r.name})); });
    arr(state.seasonOutlook && state.seasonOutlook.offseasonMoves && state.seasonOutlook.offseasonMoves.items).forEach(function(r) { players.push(Object.assign({},r,{name:r.player,team:r.toTeam})); });
    var next=new Map();
    players.forEach(function(p) {
      var d=describe(p); if(!d.name || !d.name.trim().includes(' ')) return;
      var key=norm(d.name), old=next.get(key);
      if(!old) next.set(key,d);
      else if(old.position && d.position && old.position!==d.position && !(old.espnId && old.espnId===d.espnId)) old.ambiguous=true;
    });
    known=next;
    var names=Array.from(next.values()).filter(function(d){return !d.ambiguous;}).map(function(d){return d.name;}).sort(function(a,b){return b.length-a.length;});
    namesRegex=names.length ? new RegExp('(^|[^A-Za-z0-9])('+names.map(function(n){return n.replace(/[.*+?^${}()|[\]\\]/g,'\\$&');}).join('|')+')(?=$|[^A-Za-z0-9])','gi') : null;
  }
  function linkKnownNames() {
    refreshNames(); if(!namesRegex) return;
    if(observer) observer.disconnect();
    try {
      document.querySelectorAll('main, #detail-body').forEach(function(root) {
        var walker=document.createTreeWalker(root,NodeFilter.SHOW_TEXT,{acceptNode:function(node){
          var el=node.parentElement;
          return !el || el.closest('a,button,script,style,textarea,input,select,h2.modal-title,.gp-recent-root,[data-gp-no-link]') || !node.nodeValue.trim() ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT;
        }}), nodes=[], node;
        while((node=walker.nextNode())) nodes.push(node);
        nodes.forEach(function(node){
          namesRegex.lastIndex=0; var text=node.nodeValue, match, last=0, fragment=null;
          while((match=namesRegex.exec(text))) {
            var d=known.get(norm(match[2])); if(!d || d.ambiguous) continue;
            if(!fragment) fragment=document.createDocumentFragment();
            var start=match.index+match[1].length;
            fragment.appendChild(document.createTextNode(text.slice(last,start)));
            var template=document.createElement('template'); template.innerHTML=link(d,match[2]);
            fragment.appendChild(template.content); last=start+match[2].length;
          }
          if(fragment) {fragment.appendChild(document.createTextNode(text.slice(last)));node.replaceWith(fragment);}
        });
      });
    } finally { if(observer) observer.observe(document.body,{childList:true,subtree:true}); }
  }
  function init() {
    document.addEventListener('click',function(e) {
      var button=e.target.closest('[data-gp-player]');
      if(button) { e.preventDefault(); e.stopPropagation(); try{open(JSON.parse(button.dataset.gpPlayer));}catch(err){console.error('Player stats:',err);} return; }
      if(e.target.closest('[data-profile-kind="player"], [data-search-open="player"]')) previousFocus=document.activeElement;
      if(e.target.closest('[data-close]') && previousFocus) setTimeout(function(){if(previousFocus.isConnected)previousFocus.focus();},0);
    },true);
    document.addEventListener('keydown',function(e){
      var root=document.querySelector('.overlay.open .gp-recent-root'); if(!root)return;
      var overlay=root.closest('.overlay');
      if(e.key==='Escape' && previousFocus) setTimeout(function(){if(previousFocus.isConnected)previousFocus.focus();},0);
      if(e.key!=='Tab')return;
      var focusable=Array.from(overlay.querySelectorAll('button:not([disabled]),a[href],input,[tabindex="0"]')).filter(function(el){return el.getClientRects().length;});
      var first=focusable[0],last=focusable[focusable.length-1];
      if(e.shiftKey && document.activeElement===first){e.preventDefault();last.focus();}
      else if(!e.shiftKey && document.activeElement===last){e.preventDefault();first.focus();}
    });
    observer=new MutationObserver(function(records){
      var useful=records.some(function(r){return r.addedNodes.length && !(r.target.nodeType===1 && r.target.closest('.gp-recent-root,.gp-player-dialog'));});
      if(useful){clearTimeout(timer);timer=setTimeout(linkKnownNames,120);}
    });
    observer.observe(document.body,{childList:true,subtree:true});
    linkKnownNames();
  }
  window.GPPlayerStats={link:link,open:open,attach:attach,refresh:linkKnownNames};
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
})();
