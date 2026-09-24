#!/usr/bin/env python3
"""Idempotent trial integration and one-time pre-publication safety migration."""
from pathlib import Path
import hashlib
import re
import subprocess
import tempfile

model_path = Path('scripts/projection_trial.py')
model = model_path.read_text(encoding='utf-8')
marker = '# EXACT_TRACKER_CAPTURE_GUARDS_V1'
if marker not in model:
    def change(old, new):
        global model
        if model.count(old) != 1:
            raise RuntimeError('Trial migration anchor is missing or ambiguous: '+old[:90])
        model = model.replace(old, new, 1)

    change("if key in idx and idx[key]['position']!=val['position']:",
           "if key in idx and (idx[key].get('conflict') or idx[key]['position']!=val['position'] or idx[key]['id']!=val['id']):")
    change("if not candidates:raise ValueError('No verified upcoming offensive players')",
           "if not candidates:warnings.append('No eligible upcoming players; existing forecasts will still be graded.')")
    change("fs={n:features(combined,n) for n in {x['window'] for x in calibration['parameters'].values()}}",
           "fs={n:features(combined,n) for n in {x['window'] for x in calibration['parameters'].values()}} if candidates else {}")
    model = model.replace('new_records+=freeze(ledger,rec,now)', 'new_records+=freeze(ledger,rec,utc())')
    change("ledger=old['forecasts'];outcomes=old['outcomes'];initial_hashes={k:v['forecastHash'] for k,v in ledger.items()}",
           "ledger=old['forecasts'];outcomes=old['outcomes'];verify_ledger(ledger);initial_hashes={k:v['forecastHash'] for k,v in ledger.items()}")
    change("assert all(ledger[k]['forecastHash']==v for k,v in initial_hashes.items()), 'Frozen forecasts changed'",
           "verify_ledger(ledger)\n    assert all(ledger[k]['forecastHash']==v for k,v in initial_hashes.items()), 'Frozen forecasts changed'")
    change("if not fresh(s.get('generatedAt'),now,2):raise ValueError('Current agent snapshot stale; no forecasts frozen')\n    year=s['season']['year'];week=s['season']['week']",
           """capture_allowed=fresh(s.get('generatedAt'),now,2)
    if not args.offline:
        current_board=get(ESPN+'/scoreboard').json()
        current_season=current_board.get('season') or {}
        current_week=(current_board.get('week') or {}).get('number')
        expected={str(e['id']) for e in current_board.get('events',[])}
        supplied={str(g['id']) for g in s.get('games',[])}
        capture_allowed=capture_allowed and bool(expected) and expected.issubset(supplied) and all(str(s['season'].get(k))==str(current_season.get(k)) for k in ['year','type']) and str(s['season'].get('week'))==str(current_week)
    if not capture_allowed:
        warnings.append('Current analysis failed freshness/slate validation. No new forecasts captured; existing records still evaluated.')
        s={**s,'playerEdge':[]}
    year=s['season']['year'];week=s['season']['week']""")
    change("needed={r['gameId'] for r in ledger.values() if dt(r['kickoff'])<=now and r['gameId'] not in finals}",
           "needed={r['gameId'] for r in ledger.values() if dt(r['kickoff'])<=now}")
    change("result=grade(rec,actual,True,now,digest(summary))",
           """actual_start=dt(comp.get('date'))
        if actual_start and dt(rec['recordedAt'])>=min(actual_start,dt(rec['kickoff'])):
            result={'status':'INVALID_CAPTURE','reason':'Capture was not before verified game start','actualSourceHash':digest(summary)}
        else:
            result=grade(rec,actual,True,now,digest(summary))""")
    change("def main():", """def verify_ledger(ledger):
    for key, record in ledger.items():
        computed=digest({k:v for k,v in record.items() if k!='forecastHash'})
        if record.get('id')!=key or computed!=record.get('forecastHash'):
            raise ValueError('Frozen forecast integrity failed: '+str(key))


# EXACT_TRACKER_CAPTURE_GUARDS_V1
def main():""")
    compile(model, str(model_path), 'exec')
    model_path.write_text(model,encoding='utf-8')

page_path=Path('index.html')
page=page_path.read_text(encoding='utf-8')
# Inline app logic must remain byte-identical; the new adapter is separate.
scripts_before=re.findall(r'<script\b[^>]*>(.*?)</script>',page,flags=re.S|re.I)
css='<link rel="stylesheet" href="./assets/projection-trial.css?v=20260924-trial1">'
js='<script src="./assets/projection-trial.js?v=20260924-trial1" defer></script>'
if css not in page:page=page.replace('</head>',css+'\n</head>',1)
if js not in page:page=page.replace('</body>',js+'\n</body>',1)
if 'id="gp-trial-home-link"' not in page:
    anchor='<div class="hero-actions">'
    if page.count(anchor)!=1:raise RuntimeError('Homepage action hook is ambiguous')
    page=page.replace(anchor,anchor+'\n              <a id="gp-trial-home-link" class="secondary gp-exact-link" href="projection-trial.html">Projection Lab / Exact Results</a>',1)
if 'id="gp-exact-legacy-note"' not in page:
    anchor='<div id="model-feed-status"></div>'
    if page.count(anchor)!=1:raise RuntimeError('Model record hook is ambiguous')
    note='<p class="gp-exact-legacy-note" id="gp-exact-legacy-note"><b>Legacy performance thresholds.</b> These HIT/MISS results do not measure numerical projection accuracy. The original record is unchanged. <a href="projection-trial.html">See exact-stat errors and the workload trial</a>.</p>'
    page=page.replace(anchor,note+'\n'+anchor,1)
scripts_after=re.findall(r'<script\b[^>]*>(.*?)</script>',page,flags=re.S|re.I)
assert [s for s in scripts_before if s.strip()]==[s for s in scripts_after if s.strip()], 'Existing application code changed'
for code in scripts_after:
    if code.strip():
        with tempfile.NamedTemporaryFile(suffix='.js',mode='w',encoding='utf-8') as f:
            f.write(code);f.flush();subprocess.run(['node','--check',f.name],check=True)
for item in [css,js,'id="gp-trial-home-link"','id="gp-exact-legacy-note"']:
    assert page.count(item)==1,item
page_path.write_text(page,encoding='utf-8')
print('Exact-stat adapter installed; existing inline app and legacy result files unchanged.')
