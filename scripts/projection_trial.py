#!/usr/bin/env python3
"""Exact-stat prospective tracker and a separately evaluated workload experiment.

Historical test: league efficiencies from 2022-23; window/shrinkage selected on
2024; 2025 held out. All rolling inputs exclude the row being predicted.
This does not change the legacy Worker, season model, picks or old HIT grades.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import requests

VERSION = 'workload-trial-1'
BASE = 'https://github.com/nflverse/nflverse-data/releases/download/'
ESPN = 'https://site.api.espn.com/apis/site/v2/sports/football/nfl'
AGENT = 'https://grid-pulse-agent.kadescott97.workers.dev/latest'
STATS = ['attempts', 'passing_yards', 'passing_tds', 'carries', 'rushing_yards',
         'rushing_tds', 'targets', 'receptions', 'receiving_yards', 'receiving_tds']
RATES = {'passing_yards': 'attempts', 'passing_tds': 'attempts',
         'rushing_yards': 'carries', 'rushing_tds': 'carries',
         'receiving_yards': 'targets', 'receiving_tds': 'targets', 'receptions': 'targets'}
PRIMARY = {'QB': 'passing_yards', 'RB': 'scrimmage_yards', 'WR': 'receiving_yards', 'TE': 'receiving_yards'}
METRICS = {'QB': ['passing_yards', 'passing_tds', 'rushing_yards'],
           'RB': ['carries', 'rushing_yards', 'receptions', 'receiving_yards', 'scrimmage_yards', 'scrimmage_tds'],
           'WR': ['targets', 'receptions', 'receiving_yards', 'receiving_tds'],
           'TE': ['targets', 'receptions', 'receiving_yards', 'receiving_tds']}
ALIASES = {'LA':'LAR', 'JAC':'JAX', 'WSH':'WAS', 'SD':'LAC', 'OAK':'LV'}


def number(v):
    if isinstance(v, bool) or v is None or not isinstance(v, (str, int, float, np.number)):
        return None
    try:
        n = float(str(v).replace(',', '').strip())
        return n if math.isfinite(n) else None
    except ValueError:
        return None


def identity(v):
    n = number(v)
    return str(int(n)) if n is not None else str(v or '').strip()


def team(v):
    return ALIASES.get(str(v).upper(), str(v).upper())


def pos(v):
    return {'FB': 'RB', 'HB': 'RB'}.get(str(v).upper(), str(v).upper())


def norm(v):
    return re.sub('[^a-z0-9]', '', re.sub(r'\b(jr|sr|ii|iii|iv|v)\b', '', str(v or '').lower()))


def utc():
    return datetime.now(timezone.utc)


def dt(v):
    try:
        x = datetime.fromisoformat(str(v).replace('Z', '+00:00'))
        return x if x.tzinfo else None
    except (ValueError, TypeError):
        return None


def fresh(v, now, hours=3):
    t = dt(v)
    return t is not None and -300 <= (now-t).total_seconds() <= hours*3600


def digest(v):
    return hashlib.sha256(json.dumps(v, sort_keys=True, allow_nan=False).encode()).hexdigest()


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(data, indent=2, allow_nan=False), encoding='utf-8')
    temp.replace(path)


def get(url):
    r = requests.get(url, timeout=65, headers={'Accept':'application/json', 'User-Agent':'GridironPulse-ExactTrial/1', 'Cache-Control':'no-cache'})
    r.raise_for_status()
    return r


def csv_input(cache, name, url):
    path = cache/name
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(get(url).content)
    return pd.read_csv(path, low_memory=False)


def prepare(frames):
    d = pd.concat(frames, ignore_index=True).copy()
    d = d[d.season_type.eq('REG')].rename(columns={'recent_team':'team'})
    for col in STATS:
        if col not in d:
            raise ValueError('Required source column missing: '+col)
        d[col] = pd.to_numeric(d[col], errors='coerce')
    d['team'] = d.team.map(team)
    d['position'] = d.position.map(pos)
    totals = d.groupby(['season','week','team'])[['attempts','carries']].sum(min_count=1).rename(columns={'attempts':'team_attempts','carries':'team_carries'}).reset_index()
    d = d.merge(totals, on=['season','week','team'], validate='many_to_one')
    d = d[d.position.isin(PRIMARY)].copy()
    d['scrimmage_yards'] = d.rushing_yards + d.receiving_yards
    d['scrimmage_tds'] = d.rushing_tds + d.receiving_tds
    if d.duplicated(['player_id','season','week','team']).any():
        raise ValueError('Duplicate historical player-game identities')
    return d


def features(data, window):
    d = data.sort_values(['season','week','team','player_id']).reset_index(drop=True).copy()
    cols = STATS + ['team_attempts','team_carries']
    g = d.groupby(['player_id','team'], sort=False)
    for col in cols:
        d['s_'+col] = g[col].transform(lambda s: s.shift(1).rolling(window, min_periods=2).sum())
    d['sample'] = g.cumcount().clip(upper=window)
    t = d[['season','week','team','team_attempts','team_carries']].drop_duplicates()
    if t.duplicated(['season','week','team']).any():
        raise ValueError('Conflicting team-volume observations')
    for col in ['team_attempts','team_carries']:
        t['expected_'+col] = t.groupby('team', sort=False)[col].transform(lambda s:s.shift(1).rolling(window,min_periods=2).mean())
    d = d.merge(t[['season','week','team','expected_team_attempts','expected_team_carries']], on=['season','week','team'], validate='many_to_one')
    for col, den in [('attempts','team_attempts'),('carries','team_carries'),('targets','team_attempts')]:
        d['expected_'+col] = d['expected_'+den]*(d['s_'+col]/d['s_'+den].where(d['s_'+den]>0)).clip(0,1)
    return d


def rates(training):
    out = {}
    for p in PRIMARY:
        d = training[training.position.eq(p)]
        out[p] = {}
        for metric, denom in RATES.items():
            valid = d[metric].notna() & d[denom].notna()
            a, b = d.loc[valid,metric].sum(), d.loc[valid,denom].sum()
            out[p][metric] = float(a/b) if b>0 else 0.0
    return out


def predict(f, prior, k):
    out = {c:f['expected_'+c] for c in ['attempts','carries','targets']}
    for metric, denom in RATES.items():
        r = (f['s_'+metric] + k*prior[metric])/(f['s_'+denom]+k).where(f['s_'+denom]+k>0)
        out[metric] = (out[denom]*r).clip(lower=0)
    out['scrimmage_yards'] = out['rushing_yards']+out['receiving_yards']
    out['scrimmage_tds'] = out['rushing_tds']+out['receiving_tds']
    return out


def error_report(actual, prediction):
    mask = actual.notna() & prediction.notna()
    e = prediction[mask]-actual[mask]
    return {'n':int(mask.sum()), 'mae':float(e.abs().mean()) if mask.any() else None,
            'bias':float(e.mean()) if mask.any() else None}


def train(data):
    prior = rates(data[data.season.isin([2022,2023])])
    windows = [3,5,8]
    fs = {n:features(data,n) for n in windows}
    parameters, reports = {}, []
    for p, metric in PRIMARY.items():
        choices = []
        for n in windows:
            f = fs[n]; f = f[f.position.eq(p)&f.season.eq(2024)]
            for k in [0,20,60]:
                pred = predict(f,prior[p],k)[metric]
                score = error_report(f[metric], pred)
                if score['n']:
                    choices.append((score['mae'],n,k))
        if not choices:
            raise ValueError('No validation cases for '+p)
        _,n,k = min(choices)
        parameters[p] = {'window':n,'efficiencyPriorOpportunities':k}
        f = fs[n]; v = f[f.position.eq(p)&f.season.eq(2024)]
        td = 'passing_tds' if p=='QB' else 'scrimmage_tds' if p=='RB' else 'receiving_tds'
        td_choices = []
        for tk in [20,60,120]:
            e = predict(v,prior[p],tk)[td]-v[td]
            td_choices.append((float((e.dropna()**2).mean()),tk))
        parameters[p]['tdPriorOpportunities'] = min(td_choices)[1]
        test = f[f.position.eq(p)&f.season.eq(2025)].copy()
        pred = predict(test,prior[p],k)[metric]
        original = data.sort_values(['season','week','player_id']).copy()
        original['last5'] = original.groupby('player_id')[metric].transform(lambda x:x.shift(1).rolling(5,min_periods=2).mean())
        last5 = original.set_index(['player_id','season','week','team'])['last5']
        keys = pd.MultiIndex.from_frame(test[['player_id','season','week','team']])
        recent = pd.Series(last5.reindex(keys).to_numpy(),index=test.index)
        past = data[data.season.eq(2024)].groupby('player_id')[metric].mean()
        prev = test.player_id.map(past)
        mask = pred.notna()&recent.notna()&prev.notna()&test[metric].notna()
        reports.append({'position':p,'metric':metric,'eligibleHoldoutRows':int(len(test)),
                        'pairedRows':int(mask.sum()),
                        'trial':error_report(test.loc[mask,metric],pred[mask]),
                        'last5':error_report(test.loc[mask,metric],recent[mask]),
                        'lastSeason':error_report(test.loc[mask,metric],prev[mask]),
                        'tdExpectedCountMSE':float(((predict(test,prior[p],parameters[p]['tdPriorOpportunities'])[td]-test[td]).dropna()**2).mean())})
    return {'version':VERSION,'parameters':parameters,'leagueRates':prior,'holdout':reports,
            'trainingSeasons':[2022,2023],'validationSeason':2024,'holdoutSeason':2025,
            'automaticallyPromoted':False,
            'limitations':['Retrospective test uses corrected historical box scores, not archived pregame forecasts.',
                           'Cohort includes players with an observed game row and at least two earlier same-team appearances; not an injury/participation forecast.',
                           '2025 comparison is against last-five and prior-season means, not against v2.1 archived next-game forecasts.',
                           'No routes, snap forecasts, red-zone opportunities, or opponent adjustments are claimed in trial v1.']}


def roster_index(rosters):
    idx = {}
    for row in rosters.to_dict('records'):
        eid, gsis = identity(row.get('espn_id')), row.get('gsis_id')
        if eid in ('', 'nan', 'None') or not isinstance(gsis,str) or not gsis:
            continue
        key = (eid,team(row.get('team')))
        val = {'id':gsis,'position':pos(row.get('position')),'name':row.get('full_name')}
        if key in idx and (idx[key].get('conflict') or idx[key]['position']!=val['position'] or idx[key]['id']!=val['id']):
            idx[key]['conflict']=True
        else:
            idx[key]=val
    return idx


def parse_summary(summary, roster):
    """Resolve position by athlete ID + team, never by receiving category.

Only explicit player stat cells are grades. An absent category remains unknown.
Team-level totals are used only to forecast opportunities.
"""
    h = summary.get('header') or {}; comp=(h.get('competitions') or [{}])[0]
    if not (comp.get('status') or {}).get('type',{}).get('completed'):
        return []
    year=(h.get('season') or {}).get('year');week=h.get('week')
    if isinstance(week,dict):week=week.get('number')
    season_type=(h.get('season') or {}).get('type')
    if season_type!=2:return []
    totals={}
    for t in (summary.get('boxscore') or {}).get('teams',[]):
        st={x['name']:x.get('displayValue') for x in t.get('statistics',[])}
        ca=str(st.get('completionAttempts','')).split('/')
        totals[team(t['team']['abbreviation'])]={'team_attempts':number(ca[-1]) if len(ca)==2 else None,'team_carries':number(st.get('rushingAttempts'))}
    rows={}
    cat_cols={'passing':{'YDS':'passing_yards','TD':'passing_tds'},'rushing':{'CAR':'carries','YDS':'rushing_yards','TD':'rushing_tds'},'receiving':{'TGTS':'targets','REC':'receptions','YDS':'receiving_yards','TD':'receiving_tds'}}
    for t in (summary.get('boxscore') or {}).get('players',[]):
        tm=team(t['team']['abbreviation'])
        for cat in t.get('statistics',[]):
            name=cat.get('name')
            if name not in cat_cols:continue
            for a in cat.get('athletes',[]):
                athlete=a.get('athlete') or {};eid=identity(athlete.get('id'));known=roster.get((eid,tm))
                if not known or known.get('conflict') or known['position'] not in PRIMARY:continue
                row=rows.setdefault((eid,tm),{'player_id':known['id'],'athleteId':eid,'player_display_name':athlete.get('displayName'),'position':known['position'],'team':tm,'season':year,'week':week,'season_type':'REG','game_id':str(h.get('id') or comp.get('id')),'gameDate':comp.get('date'),**totals.get(tm,{}),**{k:None for k in STATS}})
                cells=dict(zip(cat.get('labels',[]),a.get('stats',[])))
                for label,key in cat_cols[name].items():row[key]=number(cells.get(label))
                if name=='passing':
                    ca=str(cells.get('C/ATT','')).split('/')
                    row['attempts']=number(ca[-1]) if len(ca)==2 else None
    for row in rows.values():
        for total,parts in [('scrimmage_yards',['rushing_yards','receiving_yards']),('scrimmage_tds',['rushing_tds','receiving_tds'])]:
            row[total]=sum(row[k] for k in parts) if all(row[k] is not None for k in parts) else None
    return list(rows.values())


def freeze(ledger, record, now):
    """First valid capture wins. No backfill or later forecast replacement."""
    kick=dt(record.get('kickoff'))
    if not kick or now>=kick-timedelta(minutes=5):return False
    key=record['id']
    if key in ledger:return False
    record={**record,'recordedAt':now.isoformat()}
    record['forecastHash']=digest(record)
    ledger[key]=record
    return True


def grade(record, actual, final, now, source_hash):
    if not final:return {'status':'PENDING'}
    kickoff=dt(record['kickoff']);recorded=dt(record.get('recordedAt'))
    if not recorded or recorded>=kickoff:return {'status':'INVALID_CAPTURE'}
    values={}
    for metric,pred in record['predictions'].items():
        value=number(actual.get(metric)) if actual else None
        values[metric]={'prediction':pred,'actual':value,'error':round(value-pred,4) if value is not None else None,'absoluteError':round(abs(value-pred),4) if value is not None else None,'status':'GRADED' if value is not None else 'NO_DATA'}
    return {'status':'FINAL','evaluatedAt':now.isoformat(),'actualSourceHash':source_hash,'metrics':values}


def verify_ledger(ledger):
    for key, record in ledger.items():
        computed=digest({k:v for k,v in record.items() if k!='forecastHash'})
        if record.get('id')!=key or computed!=record.get('forecastHash'):
            raise ValueError('Frozen forecast integrity failed: '+str(key))


# EXACT_TRACKER_CAPTURE_GUARDS_V1
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--cache',type=Path,default=Path('.cache/projection-trial'));ap.add_argument('--out',type=Path,default=Path('data'));ap.add_argument('--offline',action='store_true');args=ap.parse_args()
    cache=args.cache;cache.mkdir(parents=True,exist_ok=True);now=utc();warnings=[]
    frames=[csv_input(cache,f'stats_{y}.csv',BASE+f'stats_player/stats_player_week_{y}.csv') for y in range(2022,2026)]
    historical=prepare(frames)
    calibration_path=args.out/'projection-trial-calibration.json'
    if calibration_path.exists():
        calibration=json.loads(calibration_path.read_text())
        if calibration['version']!=VERSION:raise ValueError('Calibration version mismatch')
    else:
        calibration=train(historical)
        calibration['inputHashes']={str(y):hashlib.sha256((cache/f'stats_{y}.csv').read_bytes()).hexdigest() for y in range(2022,2026)}
        save(calibration_path,calibration)
    s=json.loads((cache/'agent.json').read_text())['snapshot'] if args.offline else get(AGENT).json()['snapshot']
    capture_allowed=fresh(s.get('generatedAt'),now,2)
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
    year=s['season']['year'];week=s['season']['week']
    rp=cache/f'roster_{year}.csv'
    if not args.offline:rp.unlink(missing_ok=True)
    rosters=csv_input(cache,rp.name,BASE+f'rosters/roster_{year}.csv');roster=roster_index(rosters)
    summaries=[]
    for w in range(1,week):
        board=json.loads((cache/f'week-{w}.json').read_text()) if args.offline else get(ESPN+f'/scoreboard?dates={year}&seasontype=2&week={w}').json()
        events=[e for e in board.get('events',[]) if e.get('status',{}).get('type',{}).get('completed')]
        def summary(e):
            path=cache/f'summary-{e["id"]}.json'
            if path.exists():return json.loads(path.read_text())
            data=get(ESPN+'/summary?event='+e['id']).json();save(path,data);return data
        with ThreadPoolExecutor(max_workers=4) as pool:summaries.extend(pool.map(summary,events))
    live_rows=[r for summary in summaries for r in parse_summary(summary,roster)]
    live=pd.DataFrame(live_rows)
    if live.empty:raise ValueError('No completed-game history parsed')
    candidates=[];skipped=[];games={str(g['id']):g for g in s['games']}
    for board in s['playerEdge']:
        game=games.get(str(board.get('gameId')))
        if not game or game['status']['state']!='pre' or not dt(game['date']) or dt(game['date'])<=now+timedelta(minutes=5):continue
        for pick in board.get('picks',[]):
            eid=identity(pick.get('athleteId'));tm=team(pick.get('team'));known=roster.get((eid,tm))
            if not known or known.get('conflict') or known['position'] not in PRIMARY:
                skipped.append({'name':pick.get('name'),'reason':'Unresolved athlete ID/position'});continue
            p=known['position']
            candidates.append({'player_id':known['id'],'athleteId':eid,'player_display_name':pick['name'],'position':p,'team':tm,'season':year,'week':week,'game_id':str(game['id']),'gameDate':game['date'],'opponent':team(game['teams']['home' if team(game['teams']['away']['abbreviation'])==tm else 'away']['abbreviation']),'future':True,**{k:np.nan for k in STATS+['team_attempts','team_carries','scrimmage_yards','scrimmage_tds']}})
    if not candidates:warnings.append('No eligible upcoming players; existing forecasts will still be graded.')
    historical['future']=False;live['future']=False
    combined=pd.concat([historical,live,pd.DataFrame(candidates)],ignore_index=True)
    fs={n:features(combined,n) for n in {x['window'] for x in calibration['parameters'].values()}} if candidates else {}
    history_path=args.out/'projection-trial-ledger.json'
    old=json.loads(history_path.read_text()) if history_path.exists() else {'forecasts':{},'outcomes':{}}
    ledger=old['forecasts'];outcomes=old['outcomes'];verify_ledger(ledger);initial_hashes={k:v['forecastHash'] for k,v in ledger.items()}
    context_path=args.out/'player-context-v21.json';context=json.loads(context_path.read_text()) if context_path.exists() else {}
    baseline_fresh=fresh(context.get('generatedAt'),now) and fresh(context.get('sourceGeneratedAt'),now)
    if not baseline_fresh:warnings.append('Existing v2.1 feed stale or missing; no new v2.1 comparisons captured this run.')
    context_rows=context.get('players',[]);new_records=0
    for c in candidates:
        p=c['position'];cfg=calibration['parameters'][p];f=fs[cfg['window']]
        f=f[f.future.eq(True)&f.player_id.eq(c['player_id'])&f.game_id.eq(c['game_id'])]
        if len(f)!=1:raise ValueError('Ambiguous future player-game row')
        yd=predict(f,calibration['leagueRates'][p],cfg['efficiencyPriorOpportunities']);td=predict(f,calibration['leagueRates'][p],cfg['tdPriorOpportunities'])
        values={k:number((td if 'tds' in k else yd)[k].iloc[0]) for k in METRICS[p]}
        values={k:round(v,2 if 'tds' in k else 1) for k,v in values.items() if v is not None}
        info={k:c[k] for k in ['athleteId','player_id','position','team','opponent']};info.update(playerName=c['player_display_name'],gameId=c['game_id'],kickoff=c['gameDate'],season=year,week=week)
        evidence=live[live.player_id.eq(c['player_id'])&live.team.eq(c['team'])]
        if values:
            rec={**info,'id':'|'.join([c['game_id'],c['athleteId'],VERSION]),'model':VERSION,'predictions':values,'sourceGeneratedAt':s['generatedAt'],'sourceHash':digest(s),'historyGames':int(f['sample'].iloc[0]),'currentSeasonGames':len(evidence),'conditionalOnPlaying':True}
            new_records+=freeze(ledger,rec,utc())
        else:skipped.append({'name':c['player_display_name'],'reason':'Fewer than two usable same-team observations'})
        if not baseline_fresh:continue
        matches=[r for r in context_rows if str(r.get('player_id'))==c['player_id'] and team(r.get('team'))==c['team'] and pos(r.get('position'))==p and str(r.get('nextGameId'))==c['game_id'] and team(r.get('nextOpponent'))==c['opponent']]
        if len(matches)!=1:continue
        r=matches[0]
        if not dt(r.get('nextGameKickoff')) or abs((dt(r['nextGameKickoff'])-dt(c['gameDate'])).total_seconds())>300:continue
        metric={'passingYards':'passing_yards','rushingYards':'rushing_yards','receivingYards':'receiving_yards','scrimmageYards':'scrimmage_yards'}.get(r.get('primaryMetric'))
        y=number(r.get('nextGameRate'));t=number(r.get('nextGameTouchdownRate'));preds={}
        if metric and y is not None:preds[metric]=float(round(y))
        if t is not None:preds['passing_tds' if p=='QB' else 'scrimmage_tds' if p=='RB' else 'receiving_tds']=round(t,1)
        if preds:
            rec={**info,'id':'|'.join([c['game_id'],c['athleteId'],'v2.1-tracked-1']),'model':'v2.1-tracked-1','predictions':preds,'sourceGeneratedAt':context['generatedAt'],'sourceHash':digest(context),'historyGames':None,'conditionalOnPlaying':True}
            new_records+=freeze(ledger,rec,utc())
    finals={str(x.get('header',{}).get('id')):x for x in summaries}
    needed={r['gameId'] for r in ledger.values() if dt(r['kickoff'])<=now}
    for gid in sorted(needed):
        try:finals[gid]=get(ESPN+'/summary?event='+gid).json()
        except requests.RequestException:warnings.append('Final box score unavailable: '+gid)
    for rec in ledger.values():
        summary=finals.get(rec['gameId'])
        if not summary:continue
        comp=(summary.get('header',{}).get('competitions') or [{}])[0]
        final=comp.get('status',{}).get('type',{}).get('completed') is True
        if not final:continue
        grade_roster={**roster,(rec['athleteId'],rec['team']):{'id':rec['player_id'],'position':rec['position']}}
        actual=next((r for r in parse_summary(summary,grade_roster) if r['athleteId']==rec['athleteId'] and r['team']==rec['team']),None)
        actual_start=dt(comp.get('date'))
        if actual_start and dt(rec['recordedAt'])>=min(actual_start,dt(rec['kickoff'])):
            result={'status':'INVALID_CAPTURE','reason':'Capture was not before verified game start','actualSourceHash':digest(summary)}
        else:
            result=grade(rec,actual,True,now,digest(summary))
        if outcomes.get(rec['id'],{}).get('actualSourceHash')!=result['actualSourceHash']:outcomes[rec['id']]=result
    verify_ledger(ledger)
    assert all(ledger[k]['forecastHash']==v for k,v in initial_hashes.items()), 'Frozen forecasts changed'
    save(history_path,{'version':1,'forecasts':ledger,'outcomes':outcomes})
    metrics=[]
    for model in sorted({r['model'] for r in ledger.values()}):
        for p in PRIMARY:
            for metric in METRICS[p]:
                entries=[outcomes.get(k,{}).get('metrics',{}).get(metric,{}) for k,r in ledger.items() if r['model']==model and r['position']==p and metric in r['predictions']]
                vals=[x for x in entries if x.get('status')=='GRADED']
                if entries:metrics.append({'model':model,'position':p,'metric':metric,'graded':len(vals),'mae':float(np.mean([x['absoluteError'] for x in vals])) if vals else None,'biasActualMinusPredicted':float(np.mean([x['error'] for x in vals])) if vals else None,'noData':sum(x.get('status')=='NO_DATA' for x in entries)})
    paired=[]
    for p in PRIMARY:
        for metric in METRICS[p]:
            pairs=[]
            for key,r in ledger.items():
                if r['model']!=VERSION or r['position']!=p:continue
                bid='|'.join([r['gameId'],r['athleteId'],'v2.1-tracked-1'])
                b=ledger.get(bid)
                if not b or abs((dt(r['recordedAt'])-dt(b['recordedAt'])).total_seconds())>300:continue
                a1=outcomes.get(key,{}).get('metrics',{}).get(metric,{})
                a2=outcomes.get(bid,{}).get('metrics',{}).get(metric,{})
                if a1.get('status')=='GRADED' and a2.get('status')=='GRADED' and a1['actual']==a2['actual']:
                    pairs.append((a1['absoluteError'],a2['absoluteError']))
            if pairs:paired.append({'position':p,'metric':metric,'n':len(pairs),'trialMAE':float(np.mean([a for a,b in pairs])),'baselineMAE':float(np.mean([b for a,b in pairs]))})
    output={'version':VERSION,'generatedAt':utc().isoformat(),'analysisSourceGeneratedAt':s['generatedAt'],'season':year,'week':week,'trialOnly':True,'autoPromoted':False,'newCaptures':int(new_records),'baselineFresh':baseline_fresh,'warnings':warnings,'skipped':skipped,'calibration':calibration,'forecasts':list(ledger.values()),'outcomes':outcomes,'metrics':metrics,'pairedComparisons':paired,'policy':'First eligible pregame capture, at least five minutes before kickoff, is frozen. Cards and grading use the same recorded number. Missing data is not a miss or zero; legacy outcomes remain unchanged.'}
    save(args.out/'projection-trial.json',output)
    print(json.dumps({k:output[k] for k in ['version','generatedAt','season','week','newCaptures','baselineFresh','warnings','skipped']},indent=2))
    print('HOLDOUT',json.dumps(calibration['holdout']))


if __name__=='__main__':main()
