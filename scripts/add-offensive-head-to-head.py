from pathlib import Path

path = Path("assets/player-game-logs.js")
text = path.read_text(encoding="utf-8")

if "HEAD-TO-HEAD VS CURRENT OPPONENT" in text:
    print("Offensive head-to-head is already installed.")
    raise SystemExit(0)

old_opponent = """            week: event.week, team: team(event.team) || team(season.displayTeam),
            opponent: (event.atVs === '@' ? '@ ' : 'vs ') + str((event.opponent || {}).abbreviation || (event.opponent || {}).displayName || 'Unknown'),
            result: str(event.gameResult) + (event.score ? ' ' + str(event.score) : ''),"""
new_opponent = """            week: event.week, team: team(event.team) || team(season.displayTeam),
            opponentTeam: team(event.opponent),
            opponentName: str((event.opponent || {}).displayName || (event.opponent || {}).abbreviation || 'Unknown'),
            opponent: (event.atVs === '@' ? '@ ' : 'vs ') + str((event.opponent || {}).abbreviation || (event.opponent || {}).displayName || 'Unknown'),
            result: str(event.gameResult) + (event.score ? ' ' + str(event.score) : ''),"""
if old_opponent not in text:
    raise RuntimeError("Could not find game-log opponent parser")
text = text.replace(old_opponent, new_opponent, 1)

old_season = """  function seasonYear() {
    const d = new Date();
    return d.getUTCFullYear() - (d.getUTCMonth() < 2 ? 1 : 0);
  }
  async function recent(p) {"""
new_season = r"""  function seasonYear() {
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

  async function recent(p) {"""
if old_season not in text:
    raise RuntimeError("Could not find seasonYear insertion point")
text = text.replace(old_season, new_season, 1)

old_render_start = """  function renderGames(box, data) {
    const p = data.player, rows = data.rows, fs = columns(p.position,rows);
    const external = '<a class=\"gp-source\" href=\"https://www.espn.com/nfl/player/gamelog/_/id/' + p.id + '\" target=\"_blank\" rel=\"noopener noreferrer\">ESPN game log &#8599;</a>';
    if (!rows.length) {
      box.innerHTML = '<p class=\"gp-note\">No completed regular-season or playoff game stats were returned for this player in the last three seasons. Preseason games are excluded.</p>' + external;
      return;
    }"""
new_render_start = """  function renderGames(box, data) {
    const p = data.player, rows = data.rows, fs = columns(p.position,rows);
    const external = '<a class=\"gp-source\" href=\"https://www.espn.com/nfl/player/gamelog/_/id/' + p.id + '\" target=\"_blank\" rel=\"noopener noreferrer\">ESPN game log &#8599;</a>';
    const h2hMarkup = renderHeadToHead(data.headToHead, p);
    if (!rows.length) {
      box.innerHTML = '<p class=\"gp-note\">No completed regular-season or playoff game stats were returned for this player in the last three seasons. Preseason games are excluded.</p>' + external + h2hMarkup;
      return;
    }"""
if old_render_start not in text:
    raise RuntimeError("Could not find renderGames start")
text = text.replace(old_render_start, new_render_start, 1)

old_render_end = """    box.innerHTML = '<p class=\"gp-note\">'+esc(notes)+'</p><div class=\"gp-averages\">'+summaries+'</div>'+table+'<div class=\"gp-log-foot\"><span>Source: ESPN \\u00b7 Loaded '+esc(new Date().toLocaleTimeString(undefined,{hour:'numeric',minute:'2-digit'}))+'</span>'+external+'</div>';
  }"""
new_render_end = """    box.innerHTML = '<p class=\"gp-note\">'+esc(notes)+'</p><div class=\"gp-averages\">'+summaries+'</div>'+table+'<div class=\"gp-log-foot\"><span>Source: ESPN \\u00b7 Loaded '+esc(new Date().toLocaleTimeString(undefined,{hour:'numeric',minute:'2-digit'}))+'</span>'+external+'</div>'+h2hMarkup;
  }"""
if old_render_end not in text:
    raise RuntimeError("Could not find renderGames output")
text = text.replace(old_render_end, new_render_end, 1)

old_load = """      try {
        const data = await recent(p);
        if (version===revision && content.isConnected) renderGames(content,data);
      } catch(e) {"""
new_load = """      try {
        const data = await recent(p);
        if (offensivePositions.has(pos(data.player.position))) {
          try {
            data.headToHead = await headToHead(data.player);
          } catch (headError) {
            data.headToHead = { error: 'Opponent history is temporarily unavailable. Please try again.' };
          }
        }
        if (version===revision && content.isConnected) renderGames(content,data);
      } catch(e) {"""
if old_load not in text:
    raise RuntimeError("Could not find popup loader")
text = text.replace(old_load, new_load, 1)

style_anchor = ".gp-log-foot{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:12px;margin-top:14px;color:#9db6a7;font-size:11px}"
style_add = style_anchor + ".gp-h2h{margin-top:24px;padding-top:22px;border-top:1px solid #31503d}.gp-h2h-head p{margin:0 0 5px;color:#61e6a8;font-size:10px;font-weight:900;letter-spacing:.12em}.gp-h2h-head h4{margin:0;color:#fff;font-size:21px}.gp-h2h-summary{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin:15px 0}.gp-h2h-summary>div{padding:11px;border:1px solid #31503d;border-radius:9px;background:#102218}.gp-h2h-summary strong{display:block;color:#61e6a8;font:800 22px/1.1 Consolas,monospace}.gp-h2h-summary small{display:block;margin-top:5px;color:#a9c0b2;font-size:10px;text-transform:uppercase;letter-spacing:.05em}.gp-h2h-table td:nth-child(2){text-align:left}"
if style_anchor not in text:
    raise RuntimeError("Could not find game-log style insertion point")
text = text.replace(style_anchor, style_add, 1)

mobile_anchor = "@media(max-width:600px){.gp-game-section{padding:14px;margin:18px 0}"
mobile_new = "@media(max-width:600px){.gp-h2h-summary{grid-template-columns:repeat(2,minmax(0,1fr))}.gp-game-section{padding:14px;margin:18px 0}"
if mobile_anchor not in text:
    raise RuntimeError("Could not find mobile style insertion point")
text = text.replace(mobile_anchor, mobile_new, 1)

path.write_text(text, encoding="utf-8")
print("Installed offensive head-to-head opponent history.")
