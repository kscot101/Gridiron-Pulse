#!/usr/bin/env python3
"""Targeted UI/identity repair; never rewrites forecasts or their ledger."""
from pathlib import Path
import re
ROOT=Path(__file__).resolve().parents[1]
VERSION='20261105-players1'

def patch(path,old,new):
    p=ROOT/path;s=p.read_text()
    if new in s:return
    if old not in s:raise ValueError('Missing patch anchor: '+path+' '+old[:70])
    p.write_text(s.replace(old,new,1))

patch('index.html','''      return unique(
        seasonPlayers().concat(
          rankings,
          picks,
          gamePlayers,
          availability
        ),
        playerKey
      );''','''      var available = unique(
        seasonPlayers().concat(rankings, picks, gamePlayers, availability),
        playerKey
      );
      return window.GPPlayerDirectory ? GPPlayerDirectory.merge(available) : available;''')
patch('index.html','''              title: player.name,
              meta:''','''              title: player.name,
              aliases: player.aliases || [],
              meta:''')
patch('index.html','''          return (
            item.title +
            " " +
            item.meta
          )
            .toLowerCase()
            .includes(query);''','''          return window.GPPlayerDirectory
            ? GPPlayerDirectory.matches(item, query)
            : String(item.title + " " + item.meta).toLowerCase().includes(query);''')
patch('index.html','''      results = results.slice(0, 30);''','''      if (query && window.GPPlayerDirectory) results.sort(function(a,b) {
        return GPPlayerDirectory.rank(a,query) - GPPlayerDirectory.rank(b,query);
      });
      results = results.slice(0, 30);''')
patch('index.html',"'<div class=\"empty\">No teams, players or games match that search.</div>'", "'<div class=\"empty\">' + (window.GPPlayerDirectory && GPPlayerDirectory.status === 'loading' ? 'Loading the player directory...' : window.GPPlayerDirectory && GPPlayerDirectory.status === 'unavailable' ? 'Player directory could not load. Close and reopen Search to retry.' : 'No teams, players or games match that search.') + '</div>'")
patch('index.html','''    function openSearch() {''','''    function openSearch() {
      if (window.GPPlayerDirectory) GPPlayerDirectory.load().then(function(){renderSearch();});''')
patch('assets/player-game-log.js','''    p = p || {};
    return {name:''','''    p = p || {};
    if (window.GPPlayerDirectory) p = GPPlayerDirectory.enrich(p);
    return {name:''')
patch('assets/player-game-log.js',"      position:pos(p.position || p.positionGroup || p.pos || p.target_position),", "      position:pos((p.position && p.position.abbreviation) || p.position || p.positionGroup || p.pos || p.target_position),")
patch('assets/player-game-log.js','''          var key = norm(p.name), group = data.byName.get(key) || [];
          group.push(p); data.byName.set(key, group);''','''          Array.from(new Set([p.name].concat(arr(p.aliases)).map(norm))).forEach(function(key) {
            var group = data.byName.get(key) || [];
            group.push(p); data.byName.set(key, group);
          });''')
patch('assets/player-game-log.js','''    var exact = data.byId.get(d.id) || data.byEspn.get(d.espnId) || data.byEspn.get(d.id);
    if (exact) return exact;''','''    d = describe(d);
    var byId = data.byId.get(d.id), byEspn = data.byEspn.get(d.espnId) || data.byEspn.get(d.id);
    if (byId && byEspn && byId.id !== byEspn.id) return null;
    if (byId || byEspn) return byId || byEspn;
    if (d.espnId || /^00-\\d+$/.test(d.id)) return null;''')
patch('assets/player-game-log.js','''      var data = await load(force);
      if (!section.isConnected) return;
      render(section,d,resolve(d,data),data,5);''','''      var values = await Promise.all([load(force), window.GPPlayerDirectory ? GPPlayerDirectory.load() : Promise.resolve()]);
      var data = values[0]; d = describe(d);
      if (!section.isConnected) return;
      render(section,d,resolve(d,data),data,5);''')
patch('assets/player-game-log.js','''New players may not have an NFL game record yet. Missing stats are not shown as zero.''','''This does not mean the player did not play: some appearances have no published individual stat row, and new results may not be published yet. Missing stats are not shown as zero.''')
patch('assets/player-game-log.js',"'. Not live play-by-play.</p>';", "'. Published games through ' + esc(data.latestGameDate || 'the latest available source') + '. Not live play-by-play.</p>';")
patch('assets/player-game-log.js','''var players=mainPlayers().concat(arr(state.playerContext && state.playerContext.players));''','''var players=mainPlayers().filter(function(p){return !p.directoryOnly;}).concat(arr(state.playerContext && state.playerContext.players));''')
patch('assets/projection-trial.js', '''return '<div><strong data-metric="'+esc(k)+'">'+fmt(r.predictions[k])+'</strong><span>'+esc(labels[k]||k)+'</span></div>';''', '''return '<div><span class="gp-expected-label">Expected '+esc(labels[k]||k)+'</span><strong data-metric="'+esc(k)+'">'+fmt(r.predictions[k])+'</strong></div>';''')
patch('assets/saved-picks.js', '''return '<div><strong data-saved-metric="'+esc(k)+'">'+esc(r.predictions[k].toLocaleString(undefined,{maximumFractionDigits:2}))+'</strong><span>'+esc(metrics[k])+'</span></div>';''', '''return '<div><span class="gp-expected-label">Expected '+esc(metrics[k])+'</span><strong data-saved-metric="'+esc(k)+'">'+esc(r.predictions[k].toLocaleString(undefined,{maximumFractionDigits:2}))+'</strong></div>';''')
for file,variable in [('assets/projection-trial.js','labels'),('assets/saved-picks.js','metrics')]:
    p=ROOT/file;s=p.read_text()
    start=s.index('var '+variable+'=');end=s.index(';',start)
    block=s[start:end].replace("'Passing TD'","'passing touchdowns'").replace("'Rushing TD'","'rushing touchdowns'").replace("'Receiving TD'","'receiving touchdowns'").replace("'Rush + receiving TD'","'rush + receiving touchdowns'")
    for word in ['Passing yards','Rushing yards','Receiving yards','Rush + receiving yards','Receptions','Targets','Carries']:
        block=block.replace("'"+word+"'","'"+word.lower()+"'")
    p.write_text(s[:start]+block+s[end:])
for name in ['index.html','pick-tracker.html','projection-trial.html','projections-2026.html','team.html','scripts/install-player-game-logs.py','scripts/install_durable_picks.py','scripts/install_projection_trial.py']:
    p=ROOT/name;s=p.read_text()
    for asset in ['player-game-log.js','projection-trial.js','saved-picks.js']:
        s=re.sub(re.escape(asset)+r'(\?v=[^"\'&\s<>]+)(?:&directory=[^"\'\s<>]+)?',lambda m:asset+m[1]+'&directory='+VERSION,s)
    if name.endswith('.html'):
        tag='<script src="./assets/player-directory.js?v='+VERSION+'" defer></script>'
        css='<link rel="stylesheet" href="./assets/expected-stats.css?v='+VERSION+'">'
        if tag not in s:s=s.replace('</head>',tag+'\n</head>',1)
        if css not in s:s=s.replace('</head>',css+'\n</head>',1)
    p.write_text(s)
print('Search directory, stable identity matching and expected-stat labels installed.')
