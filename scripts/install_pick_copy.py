#!/usr/bin/env python3
"""Apply presentation-only copy changes. Forecasts and identities stay untouched."""
from pathlib import Path
import re

MARKER = 'PLAIN_PICK_COPY_20261030'

def change(path, fn):
    p=Path(path);before=p.read_text(encoding='utf-8')
    if MARKER in before:return
    after=fn(before)
    p.write_text(after+'\n// '+MARKER+'\n',encoding='utf-8')

def once(text, old, new):
    if text.count(old)!=1:raise RuntimeError('Missing/ambiguous copy anchor: '+old[:100])
    return text.replace(old,new,1)

def saved(text):
    text=once(text,"    var label=r.model==='workload-trial-1'?'WORKLOAD TRIAL':'TRACKED v2.1';", "    var reason=root.GPPickReasons?root.GPPickReasons.markup(r):'';\n    var details=root.GPPickReasons?root.GPPickReasons.details(r):'<p>Pregame estimate. Saved '+esc(when(r.recordedAt))+'</p>';" )
    text=once(text,"+'</h3><div class=\"ds-values\">'", "+'</h3>'+reason+'<div class=\"ds-values\">'")
    text=once(text,"+'</div><p>'+esc(label+(r.modelFallback?' - selected model unavailable for this matchup':''))+'<br>Saved '+esc(when(r.recordedAt))+'</p></article>';", "+'</div>'+details+'</article>';")
    text=text.replace('SPOTLIGHT / SAVED PICKS','SPOTLIGHT PICKS').replace('SAVED UPCOMING PICKS','PLAYERS TO WATCH')
    text=text.replace('Verified pregame captures for this exact matchup. These remain available between live-analysis refreshes.', 'Players to watch in this matchup. See their recent production, opponent context and projected stats below.')
    text=once(text,"<p class=\"ds-foot\">Schedule checked '+esc(when(schedule.fetchedAt))+'. Conditional on playing; injury and lineup changes may not yet be reflected. TD estimates are expected counts, not scoring probabilities.</p>", '<p class="ds-foot">Pregame estimates, not guarantees. Check player availability before kickoff.</p>')
    text=once(text,"'+esc(model()==='workload-trial-1'?'Workload trial selected.':'Tracked v2.1 selected.')+' Each card identifies its model and original save time. An available alternative is labeled, never relabeled as the selected model.", "See the recent usage, production and opponent context behind each featured name. Tap a player for recent games and head-to-head history.")
    return text

def projection(text):
    old="    return '<div class=\"gp-exact\" data-record-id=\"'+esc(r.id)+'\"><small>'+esc(r.model==='workload-trial-1'?'WORKLOAD TRIAL':'TRACKED v2.1')+' \\u00b7 Saved '+esc(date(r.recordedAt))+'</small><div class=\"gp-exact-strip\">'"
    new="    return '<div class=\"gp-exact\" data-record-id=\"'+esc(r.id)+'\"><small>Projected stats</small><div class=\"gp-exact-strip\">'"
    text=once(text,old,new)
    text=once(text,"+'</div><small>Frozen pregame estimate; TD values are expected counts, not scoring probabilities.</small></div>';", "+'</div>'+(root.GPPickReasons?root.GPPickReasons.details(r):'<small>'+esc(r.model==='workload-trial-1'?'Recent-usage estimate':'Standard estimate')+' - Saved '+esc(date(r.recordedAt))+'</small>')+'</div>';")
    text=once(text,"root.playerProjectionMarkup=function(p){return strip(find(p));};", "root.playerProjectionMarkup=function(p){var r=find(p);return (root.GPPickReasons?root.GPPickReasons.markup(r,p):'')+strip(r);};")
    text=once(text,"+'</b>'+strip(r)+'</article>'", "+'</b>'+(root.GPPickReasons?root.GPPickReasons.markup(r,p):'')+strip(r)+'</article>'")
    text=text.replace('Saved player projections','Players to watch').replace('Show workload trial on cards','Use recent-usage estimates')
    text=text.replace("'Workload trial':'v2.1'", "'Recent-usage estimate':'Standard estimate'")
    text=text.replace("'<p>'+esc(x.model)+': captured '","'<p>'+esc(x.model==='workload-trial-1'?'Recent-usage estimate':'Standard estimate')+': saved '")
    text=text.replace('<th>v2.1</th><th>Trial</th>', '<th>Standard</th><th>Recent usage</th>')
    text=text.replace('<th>v2.1 error</th><th>Trial error</th>', '<th>Standard error</th><th>Recent-usage error</th>')
    text=text.replace('a direct comparison with v2.1.', 'a direct comparison with the standard estimate.')
    return text

change('assets/saved-picks.js',saved)
change('assets/projection-trial.js',projection)

# Use the same asset URL in the installers and pages to avoid duplicate scripts.
for name in ['index.html','projection-trial.html','scripts/install_projection_trial.py','scripts/install_durable_picks.py']:
    p=Path(name);s=p.read_text(encoding='utf-8')
    s=re.sub(r'(projection-trial\.js\?v=)[^\"\'\s<>]+',r'\g<1>20261030-copy1',s)
    s=re.sub(r'(saved-picks\.js\?v=)[^\"\'\s<>]+',r'\g<1>20261030-copy1',s)
    if name=='index.html':
        css='<link rel="stylesheet" href="./assets/pick-reasons.css?v=20261030-copy1">'
        js='<script src="./assets/pick-reasons.js?v=20261030-copy1" defer></script>'
        if css not in s:s=s.replace('</head>',css+'\n</head>',1)
        if js not in s:s=s.replace('<script src="./assets/projection-trial.js?',js+'\n<script src="./assets/projection-trial.js?',1)
    if name=='projection-trial.html':
        s=s.replace('Compare the current v2.1 model with an opportunity-based workload trial without changing the season projections.', 'Compare the standard estimate with a recent-usage estimate, alongside the actual result.')
    p.write_text(s,encoding='utf-8')
print('Plain-language pick explanations installed; saved forecasts, selection and grading unchanged.')
