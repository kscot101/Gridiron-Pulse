from pathlib import Path

path = Path('assets/player-game-logs.js')
text = path.read_text(encoding='utf-8')

old_empty = "box.innerHTML = '<p class=\"gp-note\">No completed regular-season or playoff game stats were returned for this player in the last three seasons. Preseason games are excluded.</p>' + external + h2hMarkup;"
new_empty = "box.innerHTML = h2hMarkup + '<div class=\"gp-recent-block\"><div class=\"gp-recent-label\">RECENT FORM</div><p class=\"gp-note\">No completed regular-season or playoff game stats were returned for this player in the last three seasons. Preseason games are excluded.</p>' + external + '</div>';"
if old_empty in text:
    text = text.replace(old_empty, new_empty, 1)
elif new_empty not in text:
    raise SystemExit('Could not find empty recent-game render target')

old_render = "box.innerHTML = '<p class=\"gp-note\">'+esc(notes)+'</p><div class=\"gp-averages\">'+summaries+'</div>'+table+'<div class=\"gp-log-foot\"><span>Source: ESPN \\u00b7 Loaded '+esc(new Date().toLocaleTimeString(undefined,{hour:'numeric',minute:'2-digit'}))+'</span>'+external+'</div>'+h2hMarkup;"
new_render = "box.innerHTML = h2hMarkup + '<div class=\"gp-recent-block\"><div class=\"gp-recent-label\">RECENT FORM</div><p class=\"gp-note\">'+esc(notes)+'</p><div class=\"gp-averages\">'+summaries+'</div>'+table+'<div class=\"gp-log-foot\"><span>Source: ESPN \\u00b7 Loaded '+esc(new Date().toLocaleTimeString(undefined,{hour:'numeric',minute:'2-digit'}))+'</span>'+external+'</div></div>';"
if old_render in text:
    text = text.replace(old_render, new_render, 1)
elif new_render not in text:
    raise SystemExit('Could not find populated recent-game render target')

old_mount = "section.innerHTML = '<div class=\"gp-log-head\"><div><p>PLAYER BOX SCORES</p><h3 tabindex=\"-1\">Recent game stats</h3></div><button type=\"button\" class=\"gp-retry\">Refresh stats</button></div><div class=\"gp-log-content\" aria-live=\"polite\"><p class=\"gp-note\">Loading completed games...</p></div>';"
new_mount = "section.innerHTML = '<div class=\"gp-log-head\"><div><p>PLAYER BREAKDOWN</p><h3 tabindex=\"-1\">Matchup & recent form</h3></div><button type=\"button\" class=\"gp-retry\">Refresh stats</button></div><div class=\"gp-log-content\" aria-live=\"polite\"><p class=\"gp-note\">Loading matchup history and recent games...</p></div>';"
if old_mount in text:
    text = text.replace(old_mount, new_mount, 1)
elif new_mount not in text:
    raise SystemExit('Could not find player popup heading target')

old_loading = "content.innerHTML='<p class=\"gp-note\">Loading completed games...</p>';"
new_loading = "content.innerHTML='<p class=\"gp-note\">Loading matchup history and recent games...</p>';"
if old_loading in text:
    text = text.replace(old_loading, new_loading, 1)

old_css = ".gp-h2h{margin-top:24px;padding-top:22px;border-top:1px solid #31503d}.gp-h2h-head p{margin:0 0 5px;color:#61e6a8;font-size:10px;font-weight:900;letter-spacing:.12em}.gp-h2h-head h4{margin:0;color:#fff;font-size:21px}.gp-h2h-summary{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin:15px 0}.gp-h2h-summary>div{padding:11px;border:1px solid #31503d;border-radius:9px;background:#102218}.gp-h2h-summary strong{display:block;color:#61e6a8;font:800 22px/1.1 Consolas,monospace}.gp-h2h-summary small{display:block;margin-top:5px;color:#a9c0b2;font-size:10px;text-transform:uppercase;letter-spacing:.05em}.gp-h2h-table td:nth-child(2){text-align:left}"
new_css = ".gp-h2h{position:relative;margin:18px 0 26px;padding:20px;border:2px solid #b7ff3c;border-radius:14px;background:linear-gradient(145deg,rgba(183,255,60,.13),rgba(17,45,30,.96));box-shadow:0 0 0 1px rgba(183,255,60,.08),0 18px 46px rgba(0,0,0,.28),0 0 28px rgba(183,255,60,.08)}.gp-h2h:before{content:'MATCHUP HISTORY';display:inline-flex;margin-bottom:10px;padding:6px 9px;border-radius:999px;background:#b7ff3c;color:#07110d;font:900 9px/1 Consolas,monospace;letter-spacing:.11em}.gp-h2h-head{display:flex;align-items:flex-end;justify-content:space-between;gap:12px;flex-wrap:wrap}.gp-h2h-head p{margin:0;color:#61e6a8;font-size:12px;font-weight:950;letter-spacing:.14em}.gp-h2h-head h4{margin:3px 0 0;color:#fff;font-size:clamp(25px,4vw,34px);line-height:1.05}.gp-h2h-summary{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:9px;margin:18px 0}.gp-h2h-summary>div{padding:14px 12px;border:1px solid rgba(183,255,60,.32);border-radius:10px;background:rgba(4,17,10,.72)}.gp-h2h-summary strong{display:block;color:#b7ff3c;font:900 30px/1 Consolas,monospace}.gp-h2h-summary small{display:block;margin-top:7px;color:#d8e7dd;font-size:10px;font-weight:800;text-transform:uppercase;letter-spacing:.06em}.gp-h2h .gp-note{color:#d5e5da!important}.gp-h2h .gp-table-scroll{border-color:rgba(183,255,60,.28)}.gp-h2h .gp-game-table caption{color:#b7ff3c}.gp-h2h .gp-game-table thead{background:#1b3524}.gp-h2h-table td:nth-child(2){text-align:left}.gp-recent-block{margin-top:28px;padding-top:22px;border-top:1px solid #31503d}.gp-recent-label{display:inline-flex;margin-bottom:2px;padding:5px 8px;border:1px solid #42614f;border-radius:999px;color:#a9c0b2;font:850 9px/1 Consolas,monospace;letter-spacing:.1em}"
if old_css in text:
    text = text.replace(old_css, new_css, 1)
elif new_css not in text:
    raise SystemExit('Could not find H2H style target')

old_mobile = "@media(max-width:600px){.gp-h2h-summary{grid-template-columns:repeat(2,minmax(0,1fr))}"
new_mobile = "@media(max-width:600px){.gp-h2h{padding:15px;margin:14px 0 22px}.gp-h2h-head h4{font-size:25px}.gp-h2h-summary{grid-template-columns:repeat(2,minmax(0,1fr))}.gp-h2h-summary strong{font-size:27px}"
if old_mobile in text:
    text = text.replace(old_mobile, new_mobile, 1)
elif new_mobile not in text:
    raise SystemExit('Could not find H2H mobile style target')

required = [
    'MATCHUP HISTORY',
    'Matchup & recent form',
    'gp-recent-block',
    'gp-recent-label',
    "box.innerHTML = h2hMarkup",
]
missing = [token for token in required if token not in text]
if missing:
    raise SystemExit('Missing expected H2H emphasis tokens: ' + ', '.join(missing))

path.write_text(text, encoding='utf-8')
print('H2H moved above recent games and visually emphasized.')
