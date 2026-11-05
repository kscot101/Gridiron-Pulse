#!/usr/bin/env python3
"""Publish original completed-game rankings independently of live-feed expiry.

A failed, empty, older or malformed refresh never replaces the last good file.
Rankings are copied, not recalculated. Their original generatedAt is retained.
"""
from __future__ import annotations
import argparse, json, math, urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
HISTORY='https://gridiron-pulse-history.kadescott97.workers.dev/historical-outlook'

def dt(value):
    try:
        t=datetime.fromisoformat(str(value).replace('Z','+00:00'))
        return t if t.tzinfo else None
    except (ValueError,TypeError):return None

def number(v):return isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v)

def validate(power,now):
    if not isinstance(power,dict) or power.get('available') is not True:return False
    source=dt(power.get('generatedAt'));season=now.year-(now.month<3)
    if not source or not -300<=(now-source).total_seconds()<=7*86400:return False
    if power.get('seasonYear')!=season or power.get('seasonType') not in (2,3) or not isinstance(power.get('seasonWeek'),int) or power['seasonWeek']<1:return False
    for kind in ('teams','players'):
        rows=power.get(kind);seen=set()
        if not isinstance(rows,list) or not rows:return False
        for row in rows:
            identity=str((row.get('teamId') or row.get('abbreviation') or '') if kind=='teams' else (row.get('athleteId') or row.get('key') or ''))
            score=row.get('heatScore');sample=row.get('sampleSize');games=row.get('recentGames')
            if not identity or identity in seen or not number(score) or not 0<=score<=100 or not number(sample) or sample<1 or not isinstance(games,list) or not games:return False
            seen.add(identity)
            for game in games:
                when=dt(game.get('date'))
                if not game.get('gameId') or not when or (when-source).total_seconds()>300:return False
    return True

def unit_data(payload,now):
    h=payload.get('historicalOutlook',payload)
    source=dt(h.get('generatedAt'))
    if not source or not -300<=(now-source).total_seconds()<=7*86400:return None
    rows=[]
    for t in h.get('teams',[]):
        m=t.get('metrics') or {}
        if not (t.get('historical') or {}).get('active'):continue
        vals={k:m[k] for k in ('offensePulse','defensePulse','tandemPulse') if number(m.get(k))}
        if not vals:continue
        rows.append({k:t[k] for k in ('teamId','id','abbreviation') if k in t}|{'metrics':vals,'historical':{'active':True}})
    return {'generatedAt':h['generatedAt'],'teams':rows} if rows else None

def build(root=ROOT,fetch_units=False):
    now=datetime.now(timezone.utc);dest=root/'data/power-pulse.json';old={}
    if dest.exists():old=json.loads(dest.read_text())
    path=root/'data/homepage-snapshot.json'
    raw=json.loads(path.read_text());snapshot=raw.get('snapshot') or {};power=snapshot.get('powerRankings')
    good=raw.get('ok') is True and validate(power,now)
    if not good:
        if validate(old.get('rankings'),now):
            print('Keeping last verified Power Pulse; new source is unavailable or invalid.');return old
        raise ValueError('No valid Power Pulse rankings available; previous file left untouched')
    if validate(old.get('rankings'),now) and dt(old['rankings']['generatedAt'])>dt(power['generatedAt']):power=old['rankings']
    units=unit_data(old.get('units') or {},now)
    if fetch_units:
        try:
            req=urllib.request.Request(HISTORY,headers={'Accept':'application/json','User-Agent':'GridironPulse-PowerMirror/1'})
            with urllib.request.urlopen(req,timeout=15) as res:latest=unit_data(json.load(res),now)
            if latest and (not units or dt(latest['generatedAt'])>=dt(units['generatedAt'])):units=latest
        except Exception as error:print('Team unit scores unavailable; no replacement scores invented:',type(error).__name__)
    output={'ok':True,'schemaVersion':1,'rankings':power,'units':units,'source':'Existing published Power Pulse scores; no model or forecast changes.'}
    if old!=output:
        dest.parent.mkdir(parents=True,exist_ok=True);tmp=dest.with_suffix('.tmp')
        tmp.write_text(json.dumps(output,separators=(',',':'),allow_nan=False)+'\n');tmp.replace(dest)
    print(json.dumps({'generatedAt':power['generatedAt'],'teams':len(power['teams']),'players':len(power['players']),'unitTeams':len((units or {}).get('teams',[]))}))
    return output

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--fetch-units',action='store_true');args=parser.parse_args();build(fetch_units=args.fetch_units)
