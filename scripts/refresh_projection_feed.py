#!/usr/bin/env python3
"""Refresh the existing v2.1 formula without rerunning historical backtests.

The research checkout is pinned by the workflow. Completed-season inputs may
be cached; current Worker, roster, schedule and QB depth inputs are not.
A failed refresh never overwrites the last successful public feed.
"""
import argparse
import copy
import io
import json
import math
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

from projection_identity import changed, depth_starter, norm, number, player_name, select_qbs, team

MAX_SOURCE_AGE = 3 * 3600
WORKER = 'https://gridiron-pulse-season.kadescott97.workers.dev/season-outlook'


def utc():
    return datetime.now(timezone.utc)


def request_json(url):
    r = requests.get(url, params={'reliabilityRefresh': int(utc().timestamp())}, timeout=40,
                     headers={'Accept':'application/json','Cache-Control':'no-cache','User-Agent':'GridironPulse-Reliability/1'})
    r.raise_for_status()
    return r.json()


def require_fresh(timestamp, label):
    if not timestamp:
        raise ValueError(label + ' timestamp is missing')
    dt = pd.Timestamp(timestamp)
    if dt.tzinfo is None:
        raise ValueError(label + ' timestamp has no timezone')
    age = (pd.Timestamp.now(tz='UTC') - dt).total_seconds()
    if not math.isfinite(age) or age > MAX_SOURCE_AGE or age < -300:
        raise ValueError(label + ' is stale or future-dated; keeping the last successful feed')


def stat_total(p, keys):
    stats = p.get('currentStats') or {}
    values = [number(stats.get(key)) for key in keys]
    if all(v is not None for v in values):
        return sum(values)
    # A verified zero games played is the only safe zero-stat fallback.
    return 0.0 if number(p.get('actualGames')) == 0 else None


def next_schedule(games, season, now):
    out = {}
    rows = games[(pd.to_numeric(games['season'],errors='coerce')==season) & games['game_type'].eq('REG')]
    for row in rows.to_dict('records'):
        day, clock = row.get('gameday'), row.get('gametime')
        if pd.isna(day) or pd.isna(clock):
            continue
        try:
            kickoff = pd.Timestamp(str(day)+' '+str(clock)).tz_localize('America/New_York').tz_convert('UTC')
        except (ValueError, TypeError):
            continue
        # Do not recycle a completed/in-progress game's estimate as next-game.
        if kickoff <= pd.Timestamp(now):
            continue
        eid = row.get('espn')
        if eid is None or pd.isna(eid):
            continue
        eid = str(int(float(eid))) if str(eid).replace('.','',1).isdigit() else str(eid)
        for tm, opp in ((row['away_team'],row['home_team']),(row['home_team'],row['away_team'])):
            tm = team(tm)
            info = {'week':int(row['week']), 'opponent':team(opp), 'id':eid, 'kickoff':kickoff.isoformat()}
            if tm not in out or info['kickoff'] < out[tm]['kickoff']:
                out[tm] = info
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--research', type=Path, default=Path('research'))
    ap.add_argument('--cache', type=Path, default=Path('.cache/projections-v21'))
    ap.add_argument('--out', type=Path, default=Path('data'))
    ap.add_argument('--season', type=int, default=2026)
    args = ap.parse_args()
    now = utc()
    sys.path.insert(0, str(args.research / 'model-lab'))
    import v20_player_identity_core as core
    import v20_player_identity_baseline as prior
    import v21_player_context_runner  # Installs the existing field aliases.
    import v21_player_context_baseline as lab

    raw = request_json(WORKER)
    snapshot = raw.get('seasonOutlook') or {}
    if not isinstance(snapshot.get('players'), list) or not snapshot['players']:
        raise ValueError('No current Worker players; refusing to publish')
    source_stamp = snapshot.get('generatedAt') or raw.get('generatedAt')
    require_fresh(source_stamp, 'Season Worker')
    stated_season = snapshot.get('season') or snapshot.get('seasonYear')
    if stated_season is not None and int(stated_season) != args.season:
        raise ValueError('Season Worker season does not match requested forecast')
    players = snapshot['players']
    print('Fresh Worker:', source_stamp, 'players:', len(players), flush=True)

    args.cache.mkdir(parents=True, exist_ok=True)
    source_path = args.cache / ('source_2012_'+str(args.season-1)+'.csv')
    if source_path.exists():
        source = pd.read_csv(source_path, low_memory=False)
    else:
        frames = []
        for year in range(2012,args.season):
            print('Building completed-season source:',year,flush=True)
            stats = core.load_csv_url(core.stats_url(year),args.cache / ('stats_player_week_'+str(year)+'.csv'))
            roster = core.load_csv_url(core.roster_url(year),args.cache / ('roster_'+str(year)+'.csv'),optional=True)
            frame = core.aggregate_player_season(stats,roster,year)
            if frame.empty:
                raise ValueError('Empty historical source for '+str(year))
            frames.append(frame)
        source = pd.concat(frames,ignore_index=True)
        source.to_csv(source_path,index=False)
    if int(source['season'].max()) != args.season-1:
        raise ValueError('Historical source does not include the last completed season')

    # Invalidate only changing inputs. Completed-season data remains reusable.
    roster_path = args.cache / ('roster_'+str(args.season)+'.csv')
    roster_path.unlink(missing_ok=True)
    roster = core.load_csv_url(core.roster_url(args.season),roster_path,optional=True)
    forecast = prior.current_forecast(source,args.season,{}, {},roster)
    games_path = args.cache / 'games.csv'
    games_path.unlink(missing_ok=True)
    games = core.load_csv_url(lab.GAMES_URL,games_path)
    schedule = next_schedule(games,args.season,now)
    if not schedule:
        raise ValueError('No verifiable upcoming regular-season schedule; refusing to publish')

    qb_teams = sorted({team(p.get('team')) for p in players if str(p.get('positionGroup') or p.get('position')).upper()=='QB'})
    def get_depth(tm):
        try:
            url = 'https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams/'+tm.lower()+'/depthcharts'
            payload = request_json(url)
            return tm, depth_starter(payload), None
        except Exception as exc:
            return tm, None, str(exc)
    with ThreadPoolExecutor(max_workers=6) as pool:
        depth_results = list(pool.map(get_depth,qb_teams))
    verified = {tm:value for tm,value,error in depth_results if value}
    qb_map = select_qbs(players,forecast.to_dict('records'),verified)
    print('QB resolution:',json.dumps(qb_map,default=str),flush=True)

    original_context = lab.build_context
    def build_context(row,target_season,context_map,target_qbs,coach_map,season_matchup,weekly_matchup,config,current_week=None):
        tm = team(row.get('target_team') or row.get('forecast_team') or row.get('prior_team'))
        match = schedule.get(tm)
        result = original_context(row,target_season,context_map,target_qbs,coach_map,season_matchup,weekly_matchup,config,current_week=match['week'] if match else None)
        qb = qb_map.get(tm) or {'resolved':False,'source':'unknown'}
        previous = context_map.get((target_season-1,team(row.get('prior_team'))),{})
        is_skill = str(row.get('target_position') or row.get('position')) in {'RB','WR','TE'}
        result['newQuarterback'] = changed(previous.get('qbId'),previous.get('qbName'),qb.get('playerId'),qb.get('playerName'),qb.get('resolved')) if is_skill else False
        result['quarterbackIdentityStatus'] = 'resolved' if qb.get('resolved') else 'unknown'
        result['quarterbackSelectionSource'] = qb.get('source')
        result['targetQuarterbackId'] = qb.get('playerId') or None
        result['targetQuarterback'] = qb.get('playerName') or None
        result['priorQuarterbackId'] = 'gsis:'+str(previous['qbId']) if str(previous.get('qbId') or '').startswith('00-') else previous.get('qbId')
        if not qb.get('resolved'):
            result['quarterbackFactor'] = 1.0
            result['quarterbackRateDeltaPct'] = None
            result['combinedFactor'] = result['schemeFactor'] * result['seasonMatchupFactor']
        result['nextGameId'] = match['id'] if match else None
        result['nextGameKickoff'] = match['kickoff'] if match else None
        result['nextGameWeek'] = match['week'] if match else None
        return result
    lab.build_context = build_context
    lab.current_qb_map = lambda *_: qb_map
    # All outputs in a run use the same validated live snapshot.
    lab.load_worker_snapshot = lambda _: (copy.deepcopy(snapshot),None)
    config = lab.load_config(args.research / 'model-lab/v21_context_config.json')
    histories = lab.player_histories(source)
    context_map = lab.team_contexts(source)
    coach_map = lab.parse_history_coach_continuity(args.research / 'data/gridiron-history-data.json')
    frame, meta = lab.build_current_preview(forecast,source,games,histories,context_map,coach_map,args.season,args.cache,config,WORKER)
    rows = lab.records(frame)
    if not rows:
        raise ValueError('No projections generated')
    worker = {(norm(player_name(p)),team(p.get('team')),str(p.get('positionGroup') or p.get('position'))):p for p in players}
    td_count = 0
    for row in rows:
        pos = row['position']
        p = worker.get((norm(row['playerName']),team(row['team']),pos),{})
        played = number(p.get('actualGames'))
        remaining = number(p.get('teamRemainingGames'))
        total = stat_total(p,['rushingYards','receivingYards'] if row['primaryMetric']=='scrimmageYards' else [row['primaryMetric']])
        if played is None or remaining is None:
            row['candidateRemainingGames'] = None
        if row.get('context_eligible') and (total is None or row['candidateRemainingGames'] is None):
            row['candidateProjection'] = None
            row['delta'] = None
            row['projectionDataStatus'] = 'current-stats-unavailable'
        else:
            row['projectionDataStatus'] = 'available' if number(row.get('candidateProjection')) is not None else 'unavailable'
        for key in ('candidateTouchdowns','projectedTouchdownsPerGame','nextGameTouchdownRate','actualTouchdowns','lastYearTouchdowns','lastYearTouchdownsPerGame'):
            row[key] = None
        history = histories.get(str(row.get('player_id')),pd.DataFrame())
        history = history[history['season']<args.season].sort_values('season',ascending=False) if not history.empty else history
        if not history.empty:
            last = history.iloc[0]
            td_total,td_pg = number(last.get('touchdowns')),number(last.get('touchdowns_pg'))
            reported = number(row.get('last_year_reported_rate'))
            context = number(row.get('last_year_context_rate'))
            adjustment = context/reported if context is not None and reported is not None and reported>1e-9 else 1.0
            adjustment = max(.5,min(1.5,adjustment))
            pg = max(0,td_pg*adjustment) if td_pg is not None else None
            keys = ['passingTouchdowns'] if pos=='QB' else ['rushingTouchdowns','receivingTouchdowns'] if pos=='RB' else ['receivingTouchdowns']
            aliases = {'passingTouchdowns':['passingTds','passingTDs','passing_tds'],'rushingTouchdowns':['rushingTds','rushingTDs','rushing_tds'],'receivingTouchdowns':['receivingTds','receivingTDs','receiving_tds']}
            p = copy.deepcopy(p)
            stats = p.setdefault('currentStats',{}) or {}
            p['currentStats'] = stats
            for key in keys:
                if number(stats.get(key)) is None:
                    for alias in aliases[key]:
                        if number(stats.get(alias)) is not None:
                            stats[key] = stats[alias]
                            break
            actual = stat_total(p,keys)
            rem = number(row.get('candidateRemainingGames'))
            row.update(lastYearTouchdowns=td_total,lastYearTouchdownsPerGame=td_pg,projectedTouchdownsPerGame=pg,actualTouchdowns=actual,touchdownProjectionAdjustment=adjustment)
            if actual is not None and pg is not None and rem is not None:
                row['candidateTouchdowns'] = round(actual+pg*rem,2)
                td_count += 1
            factor = number(row.get('nextMatchupFactor'))
            if pg is not None and factor is not None and row.get('nextGameId'):
                row['nextGameTouchdownRate'] = round(pg*factor,4)
        if not row.get('nextGameId') or not row.get('nextOpponent'):
            row['nextGameRate'] = None
            row['nextGameTouchdownRate'] = None
        for key in ('candidateProjection','candidateTouchdowns','nextGameRate','nextGameTouchdownRate'):
            value = number(row.get(key))
            if value is not None and value<0:
                raise ValueError('Negative projection: '+key)
            row[key] = value
    policy_path = args.research / 'model-lab/results/v21-player-context-latest/policy.json'
    policy = json.loads(policy_path.read_text())
    if policy.get('historicalReplayPassed') is not True:
        raise ValueError('Existing historical model gate is not passed')
    require_fresh(source_stamp,'Season Worker at publication')
    unresolved = sorted(tm for tm,qb in qb_map.items() if not qb.get('resolved'))
    meta.update(touchdownProjectionPlayers=td_count,quarterbackUnresolvedTeams=unresolved,quarterbackDepthVerifiedTeams=len(verified))
    generated = utc().isoformat()
    payload = {'ok':True,'ready':True,'version':'v2.1-reliability-1','reliabilityVersion':1,'season':args.season,'careerStateUsed':False,'productionChanged':False,'productionWorkerChanged':False,'generatedAt':generated,'sourceGeneratedAt':source_stamp,'sourceFetchedAt':now.isoformat(),'maxAgeHours':3,'meta':meta,'policy':policy,'players':rows}
    report = {'generatedAt':generated,'sourceGeneratedAt':source_stamp,'workflowRun':os.environ.get('GITHUB_RUN_ID'),'implementationCommit':os.environ.get('GITHUB_SHA'),'players':len(rows),'contextEligiblePlayers':sum(bool(p.get('context_eligible')) for p in rows),'unresolvedQuarterbackTeams':unresolved,'quarterbacks':qb_map,'missingYardageProjections':sum(p.get('candidateProjection') is None for p in rows),'missingTouchdownProjections':sum(p.get('candidateTouchdowns') is None for p in rows),'historicalBacktestRerun':False,'formulaCoefficientsChanged':False}
    args.out.mkdir(parents=True,exist_ok=True)
    temp = args.out / 'player-context-v21.json.tmp'
    temp.write_text(json.dumps(payload,indent=2,allow_nan=False))
    temp.replace(args.out / 'player-context-v21.json')
    (args.out/'projection-refresh-status.json').write_text(json.dumps(report,indent=2,allow_nan=False))
    print(json.dumps({k:v for k,v in report.items() if k!='quarterbacks'},indent=2),flush=True)


if __name__=='__main__':
    main()
