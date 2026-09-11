from pathlib import Path

path = Path("projections-2026.html")
page = path.read_text(encoding="utf-8")

if "data-proj-follow" in page and "gridironPulseFavoritesV1" in page:
    print("Projection favorites are already installed.")
    raise SystemExit(0)

css_anchor = "@media(max-width:1000px){"
css = ".card-actions{display:flex;align-items:center;justify-content:flex-end;gap:6px;flex-wrap:wrap}.follow{height:29px;padding:0 9px;border:1px solid rgba(183,255,60,.28);border-radius:999px;background:rgba(183,255,60,.05);color:var(--a);font-size:9px;font-weight:950;text-transform:uppercase;letter-spacing:.04em;cursor:pointer}.follow:hover{background:rgba(183,255,60,.12)}.follow.active{background:var(--a);border-color:var(--a);color:#07110d}.follow:focus-visible{outline:2px solid var(--m);outline-offset:2px}"
if css_anchor not in page:
    raise RuntimeError("Could not find CSS breakpoint anchor")
page = page.replace(css_anchor, css + css_anchor, 1)

var_old = "var SH='https://gridiron-shadow.kadescott97.workers.dev/projections',SW='https://gridiron-pulse-season.kadescott97.workers.dev/season-outlook',CX='./data/player-context-v21.json',NEWS='./data/player-context-v21-news.json',S={rows:[],pos:'ALL',team:'ALL',source:'ALL',q:'',meta:{}};"
var_new = "var SH='https://gridiron-shadow.kadescott97.workers.dev/projections',SW='https://gridiron-pulse-season.kadescott97.workers.dev/season-outlook',CX='./data/player-context-v21.json',NEWS='./data/player-context-v21-news.json',FAV='gridironPulseFavoritesV1',S={rows:[],pos:'ALL',team:'ALL',source:'ALL',q:'',meta:{}};"
if var_old not in page:
    raise RuntimeError("Could not find projection state declaration")
page = page.replace(var_old, var_new, 1)

js_anchor = "async function J(u){let r=await fetch(u+(u.includes('?')?'&':'?')+'t='+Date.now(),{cache:'no-store'});if(!r.ok)throw Error(r.status);return r.json()}"
js_extra = """
function favKey(r){return String((r&&r.id)||(((r&&r.team)||'NFL')+':'+((r&&r.name)||'PLAYER')).toLowerCase())}
function favState(){try{let x=JSON.parse(localStorage.getItem(FAV)||'{}');return{teams:L(x.teams),players:L(x.players)}}catch(e){return{teams:[],players:[]}}}
function isFav(r){let k=favKey(r);return favState().players.some(p=>String(p&&p.key)===k)}
function followButton(r){let on=isFav(r),k=favKey(r);return'<button type=\"button\" class=\"follow '+(on?'active':'')+'\" data-proj-follow=\"'+E(k)+'\" aria-pressed=\"'+on+'\" aria-label=\"'+(on?'Unfollow ':'Follow ')+E(r.name)+'\">'+(on?'★ Following':'☆ Follow')+'</button>'}
function toggleFollow(key){let r=S.rows.find(x=>favKey(x)===String(key));if(!r)return;let f=favState(),i=f.players.findIndex(p=>String(p&&p.key)===String(key));if(i>=0){f.players.splice(i,1)}else{f.players.push({key:favKey(r),id:r.id||'',athleteId:r.id||'',player_id:r.id||'',name:r.name,playerName:r.name,team:r.team,position:r.pos,positionGroup:r.pos})}localStorage.setItem(FAV,JSON.stringify(f));render()}
"""
if js_anchor not in page:
    raise RuntimeError("Could not find request helper anchor")
page = page.replace(js_anchor, js_anchor + js_extra, 1)

card_old = "</div></div><span class=\"src '+r.src+'\">'+cl+'</span></div><div class=\"metricrow\">"
card_new = "</div></div><div class=\"card-actions\">'+followButton(r)+'<span class=\"src '+r.src+'\">'+cl+'</span></div></div><div class=\"metricrow\">"
if card_old not in page:
    raise RuntimeError("Could not find projection card header")
page = page.replace(card_old, card_new, 1)

bottom_old = "refresh.onclick=load;load()})();"
bottom_new = "grid.addEventListener('click',e=>{let b=e.target.closest('[data-proj-follow]');if(!b)return;e.preventDefault();e.stopPropagation();toggleFollow(b.dataset.projFollow)});window.addEventListener('storage',e=>{if(e.key===FAV)render()});refresh.onclick=load;load()})();"
if bottom_old not in page:
    raise RuntimeError("Could not find projection init anchor")
page = page.replace(bottom_old, bottom_new, 1)

path.write_text(page, encoding="utf-8")
print("Added shared Follow/Favorite controls to the 2026 projections page.")
