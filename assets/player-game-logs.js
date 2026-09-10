/* Gridiron Pulse: shared, on-demand player box scores. No projection values are used as game results. */
(function () {
  'use strict';
  const arr = v => Array.isArray(v) ? v : [];
  const str = v => v == null ? '' : String(v);
  const norm = v => str(v).normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/\b(jr|sr|ii|iii|iv|v)\b/g, '').replace(/[^a-z0-9]/g, '');
  const esc = v => str(v).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const num = v => {
    if (v == null || typeof v === 'boolean' || !str(v).trim() || /^[-\u2014\u2013]+$/.test(str(v))) return null;
    const n = Number(str(v).replace(/,/g, ''));
    return Number.isFinite(n) ? n : null;
  };
  const team = v => {
    if (v && typeof v === 'object') v = v.abbreviation || v.abbr || v.code;
    const t = str(v).trim().toUpperCase();
    return ({LA:'LAR',STL:'LAR',JAC:'JAX',OAK:'LV',SD:'LAC',WSH:'WAS'})[t] || t;
  };
  const pos = v => {
    if (v && typeof v === 'object') v = v.abbreviation || v.name;
    const p = str(v).toUpperCase();
    return ({FB:'RB',HB:'RB',LWR:'WR',RWR:'WR',SWR:'WR'})[p] || p;
  };
  const nameOf = p => str(p && (p.name || p.playerName || p.player_name || p.displayName || p.fullName || (typeof p.player === 'string' && p.player)));
  function athleteId(p) {
    for (const v of [p && p.athleteId, p && p.espnId, p && p.espn_id, p && p.id, p && p.playerKey]) {
      if (/^[1-9][0-9]{3,9}$/.test(str(v))) return str(v);
    }
    const shot = p && p.headshot;
    const m = str(shot && (shot.href || shot)).match(/espncdn\.com\/i\/headshots\/nfl\/players\/(?:full|small)\/(\d+)\./);
    return m ? m[1] : '';
  }
  function parseGameLog(data, year, now) {
    now = now || Date.now();
    if (!data || !Array.isArray(data.names) || !Array.isArray(data.seasonTypes)) throw Error('Unrecognized box-score format');
    const rows = new Map();
    arr(data.seasonTypes).forEach(season => {
      const label = str(season.displayName);
      if (/preseason|all.star|pro bowl/i.test(label)) return;
      arr(season.categories).forEach(category => {
        if (category.type && category.type !== 'event') return;
        const type = str(category.splitType);
        if (type && type !== '2' && type !== '3') return;
        arr(category.events).forEach(line => {
          const id = str(line.eventId);
          const event = (data.events || {})[id];
          if (!event || !arr(line.stats).some(v => num(v) !== null)) return;
          const date = event.gameDate || event.date;
          const timestamp = Date.parse(date);
          if (!Number.isFinite(timestamp) || timestamp > now || !/^[WLT]$/.test(str(event.gameResult))) return;
          if (event.status && event.status.type && event.status.type.completed === false) return;
          const stats = {};
          data.names.forEach((key, i) => { stats[key] = line.stats[i] == null ? null : line.stats[i]; });
          const previous = rows.get(id);
          rows.set(id, {
            id, date, timestamp, year: Number(year), season: label || str(year),
            phase: /postseason|playoff/i.test(label) || type === '3' ? 'Playoffs' : 'Regular season',
            week: event.week, team: team(event.team) || team(season.displayTeam),
            opponentTeam: team(event.opponent),
            opponentName: str((event.opponent || {}).displayName || (event.opponent || {}).abbreviation || 'Unknown'),
            opponent: (event.atVs === '@' ? '@ ' : 'vs ') + str((event.opponent || {}).abbreviation || (event.opponent || {}).displayName || 'Unknown'),
            result: str(event.gameResult) + (event.score ? ' ' + str(event.score) : ''),
            stats: Object.assign({}, previous && previous.stats, stats)
          });
        });
      });
    });
    return Array.from(rows.values()).sort((a,b) => b.timestamp - a.timestamp);
  }
  const field = (key, label, aliases) => ({ key, label, aliases: aliases || [key] });
  const groups = {
    QB: [field('passingYards','Pass yards'),field('passingTouchdowns','Pass TD'),field('interceptions','INT'),field('rushingYards','Rush yards'),field('rushingTouchdowns','Rush TD')],
    RB: [field('rushingAttempts','Carries'),field('rushingYards','Rush yards'),field('rushingTouchdowns','Rush TD'),field('receptions','Catches'),field('receivingYards','Rec yards'),field('receivingTouchdowns','Rec TD')],
    WR: [field('receivingTargets','Targets',['receivingTargets','targets']),field('receptions','Catches'),field('receivingYards','Rec yards'),field('receivingTouchdowns','Rec TD')],
    DEF: [field('totalTackles','Tackles'),field('sacks','Sacks'),field('interceptions','INT',['interceptions','defensiveInterceptions']),field('passesDefended','Passes defended'),field('fumblesForced','Forced fumbles',['fumblesForced','forcedFumbles'])],
    K: [field('fieldGoalsMade','FG made'),field('fieldGoalAttempts','FG attempts'),field('extraPointsMade','XP made'),field('totalPoints','Points')],
    P: [field('punts','Punts'),field('grossAvgPuntYards','Punt average'),field('puntsInside20','Inside 20')]
  };
  function stat(row, f) {
    for (const k of f.aliases) if (row.stats[k] != null) return row.stats[k];
    return null;
  }
  function columns(position, rows) {
    let fs = groups[position === 'TE' ? 'WR' : position] || groups.DEF;
    const present = fs.filter(f => rows.some(r => stat(r, f) != null));
    if (present.length) return present;
    return Object.keys((rows[0] || {}).stats || {}).slice(0,6).map(k => field(k, k.replace(/([a-z])([A-Z])/g,'$1 $2')));
  }
  const core = { parseGameLog, columns, stat, num, norm, athleteId };
  if (typeof module !== 'undefined' && module.exports) module.exports = core;
  if (typeof window === 'undefined' || !window.document) return;
  if (window.GPGameLogs) return;
  const doc = window.document;
  const registry = new Map();
  const aliases = new Map();
  const requests = new Map();
  let directoryPromise, scanTimer, observer, pattern, aliasCount = 0, standalone, lastTrigger;
  const originalProfile = typeof window.openProfile === 'function' ? window.openProfile : null;
  function register(raw) {
    if (!raw || typeof raw !== 'object') return null;
    const name = nameOf(raw).trim();
    if (name.length < 4 || !/\s/.test(name)) return null;
    const tm = team(raw.team || raw.targetTeam || raw.teamAbbr || raw.teamCode);
    const ps = pos(raw.position || raw.positionGroup || raw.target_position || raw.pos);
    const id = athleteId(raw);
    const key = norm(name) + '|' + tm + '|' + ps;
    const old = registry.get(key);
    const p = Object.assign({}, old || {}, { key, name, team: tm, position: ps, raw, id: id || (old && old.id) || '' });
    registry.set(key,p);
    if (!aliases.has(name)) aliases.set(name, new Set());
    aliases.get(name).add(key);
    return p;
  }
  function refreshRegistry() {
    if (typeof window.allPlayers === 'function') arr(window.allPlayers()).forEach(register);
    const s = window.state || {};
    arr(s.playerContext && s.playerContext.players).forEach(register);
    arr(s.snapshot && s.snapshot.results).forEach(register);
    arr(s.snapshot && s.snapshot.games).forEach(g => arr(g.injuries).forEach(register));
    arr(s.seasonOutlook && s.seasonOutlook.offseasonMoves && s.seasonOutlook.offseasonMoves.items).forEach(p => register(Object.assign({},p,{name:p.player,team:p.toTeam})));
  }
  function candidates(p) {
    let matches = Array.from(registry.values()).filter(x => norm(x.name) === norm(p.name) && x.id);
    if (p.team) matches = matches.filter(x => x.team === p.team);
    if (p.position) matches = matches.filter(x => !x.position || x.position === p.position);
    return Array.from(new Map(matches.map(x => [x.id,x])).values());
  }
  async function json(url, ttl) {
    const now = Date.now(), cached = requests.get(url);
    if (cached && now - cached.time < ttl) return cached.promise;
    const promise = (async () => {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 15000);
      try {
        const res = await fetch(url,{signal:controller.signal,headers:{Accept:'application/json'}});
        if (!res.ok) throw Error('Box-score source returned ' + res.status);
        return await res.json();
      } finally { clearTimeout(timer); }
    })();
    requests.set(url,{time:now,promise});
    if (requests.size > 100) requests.delete(requests.keys().next().value);
    try { return await promise; } catch (e) { requests.delete(url); throw e; }
  }
  async function resolve(p) {
    refreshRegistry();
    if (p.id) return p;
    let found = candidates(p);
    if (found.length === 1) return Object.assign({},p,{id:found[0].id});
    if (!directoryPromise) {
      directoryPromise = json('https://gridiron-pulse-season.kadescott97.workers.dev/season-outlook',300000)
        .then(d => arr((d.seasonOutlook || {}).players).forEach(register))
        .catch(e => { directoryPromise = null; throw e; });
    }
    await directoryPromise;
    found = candidates(p);
    if (found.length !== 1) throw Error('This player could not be matched to a verified NFL game log yet.');
    return Object.assign({},p,{id:found[0].id});
  }
  function seasonYear() {
    const d = new Date();
    return d.getUTCFullYear() - (d.getUTCMonth() < 2 ? 1 : 0);
  }

  /* HEAD-TO-HEAD VS CURRENT OPPONENT */
  const offensivePositions = new Set(['QB','RB','WR','TE']);
  function gameSideTeam(game, side) {
    const item = game && game.teams && game.teams[side] || {};
    return team(item.abbreviation || item.team || item.teamAbbreviation || item.code);
  }
  function gameSideName(game, side) {
    const item = game && game.teams && game.teams[side] || {};
    return str(item.displayName || item.teamName || item.name || item.abbreviation || item.team || 'NFL Team');
  }
  function gameForId(id) {
    if (!id) return null;
    try {
      if (typeof window.findGame === 'function') {
        const found = window.findGame(id);
        if (found) return found;
      }
    } catch (_) {}
    try {
      const games = typeof window.allGames === 'function' ? arr(window.allGames()) : arr((window.state || {}).snapshot && (window.state || {}).snapshot.games);
      return games.find(game => str(game && game.id) === str(id)) || null;
    } catch (_) { return null; }
  }
  function currentOpponent(p) {
    if (!p || !offensivePositions.has(pos(p.position))) return null;
    const raw = p.raw || {};
    let game = gameForId(raw.gameId || raw.eventId || raw.game_id);

    if (!game && typeof window.allBoards === 'function') {
      try {
        const board = arr(window.allBoards()).find(item => arr(item && item.picks).some(pick => {
          return norm(nameOf(pick)) === norm(p.name) && (!p.team || team(pick && pick.team) === p.team);
        }));
        if (board) game = gameForId(board.gameId || board.id);
      } catch (_) {}
    }

    if (!game) {
      try {
        const now = Date.now();
        const games = (typeof window.allGames === 'function' ? arr(window.allGames()) : arr((window.state || {}).snapshot && (window.state || {}).snapshot.games))
          .filter(item => {
            const away = gameSideTeam(item, 'away');
            const home = gameSideTeam(item, 'home');
            const state = str(item && item.status && item.status.state);
            return (away === p.team || home === p.team) && state !== 'post';
          })
          .sort((a,b) => {
            const aLive = str(a && a.status && a.status.state) === 'in' ? 1 : 0;
            const bLive = str(b && b.status && b.status.state) === 'in' ? 1 : 0;
            if (aLive !== bLive) return bLive - aLive;
            const ad = Date.parse(a && a.date), bd = Date.parse(b && b.date);
            const av = Number.isFinite(ad) ? Math.abs(ad - now) : Number.MAX_SAFE_INTEGER;
            const bv = Number.isFinite(bd) ? Math.abs(bd - now) : Number.MAX_SAFE_INTEGER;
            return av - bv;
          });
        game = games[0] || null;
      } catch (_) {}
    }

    if (!game) return null;
    const away = gameSideTeam(game, 'away');
    const home = gameSideTeam(game, 'home');
    let side = '';
    if (p.team && away === p.team) side = 'home';
    else if (p.team && home === p.team) side = 'away';
    if (!side) return null;
    return {
      team: gameSideTeam(game, side),
      name: gameSideName(game, side),
      gameId: str(game.id),
      date: game.date || null
    };
  }
  async function headToHead(p) {
    if (!p || !offensivePositions.has(pos(p.position))) return null;
    const opponent = currentOpponent(p);
    if (!opponent || !opponent.team) return null;
    p = await resolve(p);
    const year = seasonYear();
    const oldest = Math.max(2017, year - 9);
    let rows = [], failed = [];
    for (let y = year; y >= oldest; y--) {
      try {
        const data = await json('https://site.web.api.espn.com/apis/common/v3/sports/football/nfl/athletes/' + p.id + '/gamelog?season=' + y,300000);
        rows = rows.concat(parseGameLog(data,y).filter(row => row.opponentTeam === opponent.team));
      } catch (error) { failed.push(y); }
    }
    rows = Array.from(new Map(rows.map(row => [row.id,row])).values()).sort((a,b)=>b.timestamp-a.timestamp);
    return { opponent, rows, failed, year, oldest };
  }
  function touchdownValue(row, position) {
    const get = key => num(row && row.stats && row.stats[key]) || 0;
    if (position === 'QB') return get('passingTouchdowns') + get('rushingTouchdowns');
    if (position === 'RB') return get('rushingTouchdowns') + get('receivingTouchdowns');
    return get('receivingTouchdowns');
  }
  function primaryYardField(position) {
    if (position === 'QB') return field('passingYards','Pass yards');
    if (position === 'RB') return field('rushingYards','Rush yards');
    return field('receivingYards','Rec yards');
  }
  function renderHeadToHead(data, p) {
    if (!data) return '';
    if (data.error) {
      return '<section class="gp-h2h"><div class="gp-h2h-head"><p>HEAD TO HEAD</p><h4>Vs current opponent</h4></div><p class="gp-note">'+esc(data.error)+'</p></section>';
    }
    const opponent = data.opponent || {};
    const rows = arr(data.rows);
    const label = opponent.name || opponent.team || 'Current opponent';
    const heading = '<div class="gp-h2h-head"><p>HEAD TO HEAD</p><h4>Vs '+esc(label)+(opponent.team && label.indexOf(opponent.team) === -1 ? ' · '+esc(opponent.team) : '')+'</h4></div>';
    if (!rows.length) {
      return '<section class="gp-h2h">'+heading+'<p class="gp-note">No completed regular-season or playoff meetings were found against this opponent from '+esc(data.oldest)+' through '+esc(data.year)+'.</p></section>';
    }
    const fs = columns(p.position,rows);
    const yardField = primaryYardField(p.position);
    const yardValues = rows.map(row => num(stat(row,yardField))).filter(value => value !== null);
    const yardAverage = yardValues.length ? (yardValues.reduce((a,b)=>a+b,0)/yardValues.length).toFixed(1) : '\u2014';
    const tdTotal = rows.reduce((sum,row)=>sum+touchdownValue(row,p.position),0);
    const record = rows.reduce((out,row) => {
      const result = str(row.result).charAt(0);
      if (result === 'W') out.w += 1;
      if (result === 'L') out.l += 1;
      if (result === 'T') out.t += 1;
      return out;
    },{w:0,l:0,t:0});
    const recordLabel = record.w+'-'+record.l+(record.t ? '-'+record.t : '');
    const summaries = '<div class="gp-h2h-summary"><div><strong>'+rows.length+'</strong><small>Meetings</small></div><div><strong>'+esc(yardAverage)+'</strong><small>Avg '+esc(yardField.label)+'</small></div><div><strong>'+esc(tdTotal)+'</strong><small>Total TD</small></div><div><strong>'+esc(recordLabel)+'</strong><small>Team record</small></div></div>';
    const table = '<div class="gp-table-scroll" role="region" aria-label="Head-to-head game box scores; scroll for more stats" tabindex="0"><table class="gp-game-table gp-h2h-table"><caption>'+rows.length+' previous meeting'+(rows.length===1?'':'s')+' vs '+esc(opponent.team || label)+'</caption><thead><tr><th scope="col">Date / season</th><th scope="col">Result</th>'+fs.map(f=>'<th scope="col">'+esc(f.label)+'</th>').join('')+'<th scope="col">Box score</th></tr></thead><tbody>'+rows.map(row=>'<tr><th scope="row">'+esc(new Date(row.date).toLocaleDateString(undefined,{month:'short',day:'numeric',year:'numeric'}))+'<small>'+esc(row.year+' '+row.phase)+(row.team?' \u00b7 '+esc(row.team):'')+'</small></th><td>'+esc(row.result)+'</td>'+fs.map(f=>'<td>'+esc(stat(row,f)==null?'\u2014':stat(row,f))+'</td>').join('')+'<td><a href="https://www.espn.com/nfl/boxscore/_/gameId/'+encodeURIComponent(row.id)+'" target="_blank" rel="noopener noreferrer">View &#8599;</a></td></tr>').join('')+'</tbody></table></div>';
    const note = data.failed.length ? '<p class="gp-note">Some seasons could not be loaded ('+esc(data.failed.join(', '))+'). Showing all verified meetings that were available.</p>' : '<p class="gp-note">Actual completed games only. Preseason is excluded.</p>';
    return '<section class="gp-h2h">'+heading+summaries+note+table+'</section>';
  }

  async function recent(p) {
    p = await resolve(p);
    const year = seasonYear();
    let rows = [], failed = [];
    for (let y = year; y >= year-2 && rows.length < 5; y--) {
      try {
        const data = await json('https://site.web.api.espn.com/apis/common/v3/sports/football/nfl/athletes/' + p.id + '/gamelog?season=' + y,300000);
        rows = rows.concat(parseGameLog(data,y));
      } catch (error) { failed.push(y); }
    }
    rows = Array.from(new Map(rows.map(r => [r.id,r])).values()).sort((a,b)=>b.timestamp-a.timestamp).slice(0,5);
    if (!rows.length && failed.length) throw Error('Recent game stats are temporarily unavailable. Please try again.');
    return {player:p,rows,failed,year};
  }
  function button(p, label) {
    const b = doc.createElement('button');
    b.type = 'button'; b.className = 'gp-player-link'; b.dataset.gpPlayer = p.key;
    b.textContent = label || p.name;
    b.setAttribute('aria-label','View recent game stats for ' + p.name);
    b.setAttribute('aria-haspopup','dialog');
    return b;
  }
  function scan() {
    clearTimeout(scanTimer);
    observer.disconnect();
    try {
      refreshRegistry();
      doc.querySelectorAll('#grid .card .name').forEach(el => {
        if (el.querySelector('button,a')) return;
        const meta = str((el.closest('.card').querySelector('.meta') || {}).textContent).split(/\s[-\u00b7]\s/);
        const p = register({name:el.textContent.trim(),team:meta[0],position:meta[1]});
        if (p) el.replaceChildren(button(p));
      });
      if (aliasCount !== aliases.size) {
        aliasCount = aliases.size;
        const choices = Array.from(aliases.keys()).sort((a,b)=>b.length-a.length).map(n=>n.replace(/[.*+?^${}()|[\]\\]/g,'\\$&'));
        pattern = choices.length ? new RegExp('(^|[^A-Za-z0-9])(' + choices.join('|') + ')(?=$|[^A-Za-z0-9])','gi') : null;
      }
      if (!pattern) return;
      const roots = [doc.querySelector('main'),doc.getElementById('detail-body')].filter(Boolean);
      for (const root of roots) {
        const walker = doc.createTreeWalker(root,NodeFilter.SHOW_TEXT,{acceptNode(node) {
          return !node.nodeValue.trim() || node.parentElement.closest('a,button,script,style,input,textarea,select,option,h1,.modal-title,[data-gp-games],[data-gp-player],[data-profile-kind],[data-search-open]') ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT;
        }});
        const nodes = []; while (walker.nextNode()) nodes.push(walker.currentNode);
        nodes.forEach(node => {
          const value = node.nodeValue; pattern.lastIndex = 0;
          let m, end=0, changed=false; const fragment = doc.createDocumentFragment();
          while ((m = pattern.exec(value))) {
            const name = m[2], keys = aliases.get(Array.from(aliases.keys()).find(n=>n.toLowerCase()===name.toLowerCase()));
            if (!keys || !keys.size) continue;
            const entries = Array.from(keys).map(k=>registry.get(k));
            const ids = new Set(entries.map(p=>p.id).filter(Boolean));
            const p = ids.size <= 1 ? entries.find(p=>p.id) || entries[0] : register({name});
            const start = m.index + m[1].length;
            fragment.append(doc.createTextNode(value.slice(end,start)),button(p,name));
            end = start + name.length; changed = true;
          }
          if (changed) { fragment.append(doc.createTextNode(value.slice(end))); node.replaceWith(fragment); }
        });
      }
    } finally { observer.observe(doc.body,{childList:true,subtree:true}); }
  }
  function renderGames(box, data) {
    const p = data.player, rows = data.rows, fs = columns(p.position,rows);
    const external = '<a class="gp-source" href="https://www.espn.com/nfl/player/gamelog/_/id/' + p.id + '" target="_blank" rel="noopener noreferrer">ESPN game log &#8599;</a>';
    const h2hMarkup = renderHeadToHead(data.headToHead, p);
    if (!rows.length) {
      box.innerHTML = h2hMarkup + '<div class="gp-recent-block"><div class="gp-recent-label">RECENT FORM</div><p class="gp-note">No completed regular-season or playoff game stats were returned for this player in the last three seasons. Preseason games are excluded.</p>' + external + '</div>';
      return;
    }
    const summaries = fs.slice(0,3).map(f => {
      const values = rows.map(r=>num(stat(r,f))).filter(v=>v!==null);
      const average = values.length ? (values.reduce((a,b)=>a+b,0)/values.length).toFixed(1) : '\u2014';
      return '<div><strong>'+esc(average)+'</strong><small>'+esc(f.label)+' / game</small><span>'+values.length+' game'+(values.length===1?'':'s')+'</span></div>';
    }).join('');
    const prior = rows.some(r=>r.year<data.year);
    const notes = (prior ? 'Includes previous-season games; each season is labeled. ' : '') + (data.failed.length ? 'Some seasons could not be loaded ('+data.failed.join(', ')+'). Showing available results. ' : '') + 'Actual completed games only. Preseason excluded. A dash means the source did not report that stat.';
    const table = '<div class="gp-table-scroll" role="region" aria-label="Recent game box scores; scroll for more stats" tabindex="0"><table class="gp-game-table"><caption>Last '+rows.length+' completed game'+(rows.length===1?'':'s')+' with stats</caption><thead><tr><th scope="col">Date / season</th><th scope="col">Opponent</th><th scope="col">Result</th>'+fs.map(f=>'<th scope="col">'+esc(f.label)+'</th>').join('')+'<th scope="col">Box score</th></tr></thead><tbody>'+rows.map(r=>'<tr><th scope="row">'+esc(new Date(r.date).toLocaleDateString(undefined,{month:'short',day:'numeric',year:'numeric'}))+'<small>'+esc(r.year+' '+r.phase)+(r.team?' \u00b7 '+esc(r.team):'')+'</small></th><td>'+esc(r.opponent)+'</td><td>'+esc(r.result)+'</td>'+fs.map(f=>'<td>'+esc(stat(r,f)==null?'\u2014':stat(r,f))+'</td>').join('')+'<td><a href="https://www.espn.com/nfl/boxscore/_/gameId/'+encodeURIComponent(r.id)+'" target="_blank" rel="noopener noreferrer" aria-label="Full box score for '+esc(r.opponent)+' on '+esc(r.date.slice(0,10))+'">View &#8599;</a></td></tr>').join('')+'</tbody></table></div>';
    box.innerHTML = h2hMarkup + '<div class="gp-recent-block"><div class="gp-recent-label">RECENT FORM</div><p class="gp-note">'+esc(notes)+'</p><div class="gp-averages">'+summaries+'</div>'+table+'<div class="gp-log-foot"><span>Source: ESPN \u00b7 Loaded '+esc(new Date().toLocaleTimeString(undefined,{hour:'numeric',minute:'2-digit'}))+'</span>'+external+'</div></div>';
  }
  function mount(p, parent, before) {
    const section = doc.createElement('section');
    section.className = 'gp-game-section'; section.dataset.gpGames = p.key;
    section.innerHTML = '<div class="gp-log-head"><div><p>PLAYER BREAKDOWN</p><h3 tabindex="-1">Matchup & recent form</h3></div><button type="button" class="gp-retry">Refresh stats</button></div><div class="gp-log-content" aria-live="polite"><p class="gp-note">Loading matchup history and recent games...</p></div>';
    parent.insertBefore(section,before || null);
    const content = section.querySelector('.gp-log-content'), refresh = section.querySelector('.gp-retry');
    let revision=0;
    async function load(force) {
      const version=++revision; refresh.disabled=true; content.setAttribute('aria-busy','true');
      if (force) { requests.clear(); directoryPromise=null; }
      content.innerHTML='<p class="gp-note">Loading matchup history and recent games...</p>';
      try {
        const data = await recent(p);
        if (offensivePositions.has(pos(data.player.position))) {
          try {
            data.headToHead = await headToHead(data.player);
          } catch (headError) {
            data.headToHead = { error: 'Opponent history is temporarily unavailable. Please try again.' };
          }
        }
        if (version===revision && content.isConnected) renderGames(content,data);
      } catch(e) {
        if (version===revision && content.isConnected) content.innerHTML='<p class="gp-note">'+esc(e.message || 'Recent game stats could not be loaded.')+'</p>';
      } finally { if(version===revision){refresh.disabled=false; content.setAttribute('aria-busy','false');} }
    }
    refresh.onclick=()=>load(true); load(false);
    section.querySelector('h3').focus({preventScroll:true});
    return section;
  }
  function open(raw, key) {
    const p = raw && raw.key && registry.has(raw.key) ? registry.get(raw.key) : register(raw);
    if (!p) return;
    lastTrigger = doc.activeElement;
    if (originalProfile && typeof window.findPlayer==='function') {
      let potential = key || p.id;
      let known = window.findPlayer(potential);
      if (!known && typeof window.allPlayers === 'function') {
        const matches = arr(window.allPlayers()).filter(x => norm(nameOf(x)) === norm(p.name) && (!p.team || team(x.team) === p.team) && (!p.position || pos(x.position || x.positionGroup) === p.position));
        if (matches.length === 1 || (matches.length > 1 && new Set(matches.map(athleteId).filter(Boolean)).size === 1)) {
          known = matches[0]; potential = window.playerKey(known);
        }
      }
      if (known && norm(nameOf(known))===norm(p.name)) {
        originalProfile('player',potential);
        const body=doc.getElementById('detail-body');
        if (body) {
          body.querySelectorAll('[data-gp-games]').forEach(n=>n.remove());
          mount(p,body,body.querySelector('.modal-section'));
          const modal=body.closest('.modal'); if(modal) modal.scrollTop=0;
          return;
        }
      }
    }
    if (!standalone) {
      standalone=doc.createElement('dialog'); standalone.className='gp-player-dialog'; standalone.setAttribute('aria-labelledby','gp-player-title');
      doc.body.append(standalone);
      standalone.addEventListener('click',e=>{if(e.target===standalone){const r=standalone.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)standalone.close();}});
      standalone.addEventListener('close',()=>{if(lastTrigger && lastTrigger.isConnected)lastTrigger.focus({preventScroll:true});});
      standalone.addEventListener('keydown',e=>{if(e.key==='Escape')e.stopPropagation();});
    }
    standalone.innerHTML='<header><div><p>'+esc([p.team,p.position].filter(Boolean).join(' \u00b7 '))+'</p><h2 id="gp-player-title">'+esc(p.name)+'</h2></div><button type="button" class="gp-dialog-close" aria-label="Close player stats">&#215;</button></header>';
    standalone.querySelector('.gp-dialog-close').onclick=()=>standalone.close();
    if(!standalone.open)standalone.showModal();
    mount(p,standalone); standalone.scrollTop=0;
  }
  if(originalProfile) window.openProfile=function(kind,key){
    if(kind!=='player')return originalProfile(kind,key);
    const raw=typeof window.findPlayer==='function' && window.findPlayer(key);
    if(raw)return open(raw,key);
    const p=Array.from(registry.values()).find(p=>p.key===key||p.id===str(key));
    if(p)return open(p,key);
    return originalProfile(kind,key);
  };
  doc.addEventListener('click',e=>{
    const b=e.target.closest('[data-gp-player]');
    if(!b)return;
    e.preventDefault(); e.stopPropagation();
    open(registry.get(b.dataset.gpPlayer));
  },true);
  // Keep keyboard users inside the existing profile overlay while recent stats are visible.
  doc.addEventListener('keydown',e=>{
    if(standalone && standalone.open)return;
    const overlay=doc.querySelector('#detail-overlay.open');
    if(!overlay || !overlay.querySelector('[data-gp-games]') || e.key!=='Tab')return;
    const items=Array.from(overlay.querySelectorAll('button:not([disabled]),a[href],input,[tabindex="0"]')).filter(n=>n.getClientRects().length);
    const first=items[0],last=items[items.length-1];
    if(e.shiftKey && (doc.activeElement===first || !items.includes(doc.activeElement))){e.preventDefault();last && last.focus();}
    else if(!e.shiftKey && doc.activeElement===last){e.preventDefault();first && first.focus();}
  },true);
  const style=doc.createElement('style'); style.id='gp-game-log-styles';
  style.textContent=`
.gp-player-link{display:inline;border:0;padding:0;background:transparent;color:inherit;font:inherit;font-weight:inherit;text-align:inherit;text-decoration:underline;text-decoration-color:currentColor;text-decoration-thickness:1px;text-underline-offset:3px;cursor:pointer;white-space:normal}.gp-player-link:hover{opacity:.78}.gp-player-link:focus-visible{outline:2px solid #61e6a8;outline-offset:4px;border-radius:2px}.gp-game-section{padding:22px;margin:24px 0;border:1px solid #2e483b;border-radius:14px;background:#0b1b13;color:#f5faf7;font:400 14px/1.5 Inter,system-ui,sans-serif}.gp-log-head{display:flex;align-items:center;justify-content:space-between;gap:12px}.gp-log-head p{margin:0 0 4px;color:#b7ff3c;font-size:10px;font-weight:800;letter-spacing:.12em}.gp-log-head h3{margin:0;color:#fff;font-size:23px;line-height:1.2}.gp-log-head h3:focus{outline:0}.gp-retry{min-height:42px;padding:8px 12px;border:1px solid #42614f;border-radius:9px;background:transparent;color:#e9f4ed;font:700 12px system-ui;cursor:pointer}.gp-retry:disabled{opacity:.45;cursor:wait}.gp-note{margin:14px 0!important;color:#b8cbbf!important;font-size:12px!important;line-height:1.7!important}.gp-averages{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:9px;margin:16px 0}.gp-averages>div{padding:12px;border:1px solid #294132;background:#12271b;border-radius:9px}.gp-averages strong{display:block;color:#b7ff3c;font:800 25px/1.1 Consolas,monospace}.gp-averages small,.gp-averages span{display:block;margin-top:5px;color:#d2e0d7;font-size:11px}.gp-averages span{color:#9bb3a3;font-size:10px}.gp-table-scroll{max-width:100%;overflow-x:auto;border:1px solid #2e483b;border-radius:9px}.gp-game-table{border-collapse:collapse;width:100%;min-width:640px;background:#0b1b13;color:#ecf5ef;font:500 13px/1.4 system-ui;white-space:nowrap}.gp-game-table caption{padding:12px;text-align:left;color:#c2d3c8;font-weight:700;font-size:12px}.gp-game-table th,.gp-game-table td{padding:13px 12px;border-top:1px solid #2e483b;text-align:right}.gp-game-table th:first-child,.gp-game-table td:nth-child(2),.gp-game-table td:nth-child(3){text-align:left}.gp-game-table thead{background:#182f21;color:#bdd1c5;font-size:11px}.gp-game-table tbody tr:nth-child(even){background:#102217}.gp-game-table th small{display:block;color:#a0b9aa;font-size:10px;font-weight:500;margin-top:4px}.gp-game-table a,.gp-source{color:#b7ff3c;text-underline-offset:3px}.gp-log-foot{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:12px;margin-top:14px;color:#9db6a7;font-size:11px}.gp-h2h{position:relative;margin:18px 0 26px;padding:20px;border:2px solid #b7ff3c;border-radius:14px;background:linear-gradient(145deg,rgba(183,255,60,.13),rgba(17,45,30,.96));box-shadow:0 0 0 1px rgba(183,255,60,.08),0 18px 46px rgba(0,0,0,.28),0 0 28px rgba(183,255,60,.08)}.gp-h2h:before{content:'MATCHUP HISTORY';display:inline-flex;margin-bottom:10px;padding:6px 9px;border-radius:999px;background:#b7ff3c;color:#07110d;font:900 9px/1 Consolas,monospace;letter-spacing:.11em}.gp-h2h-head{display:flex;align-items:flex-end;justify-content:space-between;gap:12px;flex-wrap:wrap}.gp-h2h-head p{margin:0;color:#61e6a8;font-size:12px;font-weight:950;letter-spacing:.14em}.gp-h2h-head h4{margin:3px 0 0;color:#fff;font-size:clamp(25px,4vw,34px);line-height:1.05}.gp-h2h-summary{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:9px;margin:18px 0}.gp-h2h-summary>div{padding:14px 12px;border:1px solid rgba(183,255,60,.32);border-radius:10px;background:rgba(4,17,10,.72)}.gp-h2h-summary strong{display:block;color:#b7ff3c;font:900 30px/1 Consolas,monospace}.gp-h2h-summary small{display:block;margin-top:7px;color:#d8e7dd;font-size:10px;font-weight:800;text-transform:uppercase;letter-spacing:.06em}.gp-h2h .gp-note{color:#d5e5da!important}.gp-h2h .gp-table-scroll{border-color:rgba(183,255,60,.28)}.gp-h2h .gp-game-table caption{color:#b7ff3c}.gp-h2h .gp-game-table thead{background:#1b3524}.gp-h2h-table td:nth-child(2){text-align:left}.gp-recent-block{margin-top:28px;padding-top:22px;border-top:1px solid #31503d}.gp-recent-label{display:inline-flex;margin-bottom:2px;padding:5px 8px;border:1px solid #42614f;border-radius:999px;color:#a9c0b2;font:850 9px/1 Consolas,monospace;letter-spacing:.1em}.gp-player-dialog{width:min(960px,calc(100% - 24px));max-height:90dvh;padding:24px;border:1px solid #385842;border-radius:18px;background:#07110d;color:#fff;box-sizing:border-box;overflow:auto;font-family:Inter,system-ui,sans-serif}.gp-player-dialog::backdrop{background:rgba(0,0,0,.78);backdrop-filter:blur(5px)}.gp-player-dialog>header{display:flex;align-items:center;justify-content:space-between;gap:12px}.gp-player-dialog h2{font-size:clamp(24px,5vw,36px);margin:0}.gp-player-dialog header p{font-size:12px;color:#b7ff3c;margin:0 0 5px}.gp-dialog-close{flex:0 0 auto;width:44px;height:44px;border:1px solid #42614f;border-radius:50%;background:transparent;color:#fff;font-size:25px;cursor:pointer}.gp-player-dialog .gp-game-section{margin-bottom:0}.gp-game-section button:focus-visible,.gp-player-dialog button:focus-visible,.gp-table-scroll:focus-visible{outline:2px solid #b7ff3c;outline-offset:3px}@media(max-width:600px){.gp-h2h{padding:15px;margin:14px 0 22px}.gp-h2h-head h4{font-size:25px}.gp-h2h-summary{grid-template-columns:repeat(2,minmax(0,1fr))}.gp-h2h-summary strong{font-size:27px}.gp-game-section{padding:14px;margin:18px 0}.gp-player-dialog{padding:16px}.gp-log-head h3{font-size:20px}.gp-averages{gap:6px}.gp-averages>div{padding:9px}.gp-averages strong{font-size:22px}.gp-averages small{font-size:10px}.gp-log-head{align-items:flex-start}.gp-retry{font-size:11px}}
`;
  doc.head.append(style);
  observer=new MutationObserver(changes=>{
    if(changes.every(change=>change.target.nodeType===1 && change.target.closest('[data-gp-games],.gp-player-dialog')))return;
    clearTimeout(scanTimer); scanTimer=setTimeout(scan,100);
  });
  window.GPGameLogs=Object.assign({},core,{open,register:items=>arr(items).forEach(register),refresh:scan});
  scan();
})();
