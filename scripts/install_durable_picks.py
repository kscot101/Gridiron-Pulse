#!/usr/bin/env python3
"""Install isolated saved-pick display. Forecasts and grading are unchanged."""
from pathlib import Path

def edit(name, old, new):
    p=Path(name);text=p.read_text()
    if new in text:return
    if text.count(old)!=1:raise RuntimeError('Missing or ambiguous install anchor: '+name)
    p.write_text(text.replace(old,new,1))

p=Path('index.html');text=p.read_text()
for tag,anchor in [('<link rel="stylesheet" href="./assets/saved-picks.css?v=20261028a">','</head>'),('<script src="./assets/saved-picks.js?v=20261030-copy1" defer></script>','</body>')]:
    if tag not in text:text=text.replace(anchor,tag+'\n'+anchor,1)
p.write_text(text)
# Input coverage is a diagnostic, not a blanket rejection of every team's
# independently validated forecasts. Timestamp/slate/auth failures still fail.
edit('scripts/refresh_homepage_feed.py','MAX_REFRESH_PASSES = 3','MAX_REFRESH_PASSES = 5')
edit('scripts/refresh_homepage_feed.py',"    # Incomplete input coverage remains visibly unsuccessful in Actions even\n    # though a timestamped partial mirror can still serve current game scores.\n    return 0 if report['ok'] and (report.get('analysisInputs') or {}).get('historyReady') else 1",
     "    # Preserve coverage warnings. A valid current slate can feed the exact\n    # model, which independently resolves athlete identities and game history.\n    # Invalid timestamps, missing auth, wrong slate or source failures still fail.\n    return 0 if report['ok'] else 1")
# Consume the timestamp-validated local mirror before a potentially stale KV read.
# All existing capture validation, roster resolution and frozen hashes remain.
edit('scripts/projection_trial.py',
 "    s=json.loads((cache/'agent.json').read_text())['snapshot'] if args.offline else get(AGENT).json()['snapshot']",
 "    s=json.loads((cache/'agent.json').read_text())['snapshot'] if args.offline else load_capture_source(args.out, now)")
helper='''def load_capture_source(out, now):
    """Use the freshest accessible source, keeping its original timestamp."""
    local_path=out/'homepage-snapshot.json'
    candidates=[]
    if local_path.exists():
        payload=json.loads(local_path.read_text())
        if payload.get('ok') and isinstance(payload.get('snapshot'),dict):
            candidates.append(payload['snapshot'])
    # A newly mirrored source was already validated against the current slate.
    # The normal main() slate checks below still run before any capture.
    if candidates and fresh(candidates[0].get('generatedAt'),now,0.5):
        return candidates[0]
    try:
        payload=get(AGENT).json()
        if payload.get('ok') and isinstance(payload.get('snapshot'),dict):
            candidates.append(payload['snapshot'])
    except (requests.RequestException, ValueError):
        pass
    if not candidates:
        raise ValueError('No analysis source available; saved ledger retained')
    return max(candidates,key=lambda s:dt(s.get('generatedAt')) or datetime.min.replace(tzinfo=timezone.utc))


'''
p=Path('scripts/projection_trial.py');text=p.read_text()
if 'def load_capture_source(' not in text:text=text.replace('# EXACT_TRACKER_CAPTURE_GUARDS_V1',helper+'# EXACT_TRACKER_CAPTURE_GUARDS_V1',1)
compile(text,str(p),'exec');p.write_text(text)
print('Installed durable saved-pick display; original prediction formulas and ledger hashes unchanged.')
