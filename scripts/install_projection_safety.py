#!/usr/bin/env python3
"""Idempotent, guarded UI migration; preserves favorites, profiles and layout."""
import re
from pathlib import Path

TAG = '<script src="./assets/projection-safety.js?v=20260911r1"></script>'
STATUS = '<p id="projection-feed-status" role="status" style="font-size:12px;line-height:1.5;margin:12px 0">Checking projection freshness...</p>'


def once(text, old, new):
    if old not in text:
        raise RuntimeError('Expected source anchor missing: '+old[:100])
    return text.replace(old,new,1)


def main():
    path = Path('index.html')
    page = path.read_text()
    if '/* PROJECTION RELIABILITY V1 */' not in page:
        page = once(page,'</head>',TAG+'\n</head>')
        page = once(page,'<div class="hero-meta">',STATUS+'\n        <div class="hero-meta">')
        page, n = re.subn(r'    function finiteProjection\(value\) \{.*?\n    \}', '    function finiteProjection(value) {\n      return GPProjectionSafety.number(value);\n    }',page,count=1,flags=re.S)
        if n!=1:
            raise RuntimeError('Missing homepage projection number parser')
        page = once(page,'function findProjectionForPick(pick) {','function findProjectionForPickUnchecked(pick) {')
        wrapper = '''/* PROJECTION RELIABILITY V1 */
    function findProjectionForPick(pick) {
      if (!GPProjectionSafety.fresh(state.playerContext)) return null;
      var row = findProjectionForPickUnchecked(pick);
      return GPProjectionSafety.forGame(row, pick, allGames(), allBoards()) ? row : null;
    }

    '''
        page = once(page,'function projectionMetricLabel(row, pick) {',wrapper+'function projectionMetricLabel(row, pick) {')
        page = once(page,'if (metric.includes("passing")) return "Proj pass yds";','if (metric.includes("scrimmage")) return "Proj rush + rec yds";\n      if (metric.includes("passing")) return "Proj pass yds";')
        page = once(page,'state.playerContext = payload;','state.playerContext = payload;\n        GPProjectionSafety.paint(payload);')
        page = once(page,'state.playerContextError = text(','state.playerContext = null;\n        GPProjectionSafety.paint(null);\n        state.playerContextError = text(')
        page = once(page,'</body>','''<script>
setInterval(function () {
  if (document.hidden) return;
  if (typeof loadPlayerContext === 'function') loadPlayerContext(true);
}, 300000);
setInterval(function () {
  if (typeof state !== 'undefined') {
    GPProjectionSafety.paint(state.playerContext);
    if (!GPProjectionSafety.fresh(state.playerContext)) {
      if (typeof renderSpotlight === 'function') renderSpotlight();
      if (typeof renderEdges === 'function') renderEdges();
    }
  }
}, 60000);
</script>
</body>''')
        path.write_text(page)

    path = Path('projections-2026.html')
    page = path.read_text()
    if '/* PROJECTION RELIABILITY V1 */' not in page:
        page = once(page,'</head>',TAG+'\n</head>')
        page = once(page,'<div class="tools">',STATUS+'<div class="tools">')
        old = "function N(v){if(v===null||v===undefined||v==='')return null;v=Number(v);return Number.isFinite(v)?v:null}"
        page = once(page,old,'/* PROJECTION RELIABILITY V1 */\nfunction N(v){return GPProjectionSafety.number(v)}')
        page = once(page,"if(!r.ok)throw Error(r.status);return r.json()}","if(!r.ok)throw Error(r.status);let d=await r.json();if(u===CX)GPProjectionSafety.paint(d);if([CX,SH,SW].includes(u)&&!GPProjectionSafety.fresh(d))throw Error('Projection source is stale or missing a timestamp');return d;}")
        page = once(page,'function stats(){',"function stats(){let label=document.querySelector('.live');if(label)label.textContent=S.meta.ready?'LAST-SEASON CONTEXT v2.1 ACTIVE':'FALLBACK MODEL - v2.1 UNAVAILABLE';")
        # Re-enter the normal loader periodically; failed refreshes remove displayed
        # estimates rather than presenting an aged number as a current forecast.
        page = once(page,'refresh.onclick=load;load()})();',"refresh.onclick=load;setInterval(()=>{if(!document.hidden)load()},300000);document.addEventListener('visibilitychange',()=>{if(!document.hidden)load()});load()})();")
        path.write_text(page)
    print('Projection safety is installed on homepage and 2026 projections.')


if __name__=='__main__':
    main()
