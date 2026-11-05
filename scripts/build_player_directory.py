#!/usr/bin/env python3
"""Published roster + statistical identities. No forecasts or participation guesses."""
import argparse, copy, csv, importlib.util, json, re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('game_logs', ROOT/'scripts/build-player-game-logs.py')
logs = importlib.util.module_from_spec(spec); spec.loader.exec_module(logs)


def text(v):
    return '' if v is None or str(v).strip().lower() in ('nan','none','null') else str(v).strip()


def eid(v):
    v = text(v)
    return str(int(float(v))) if re.fullmatch(r'\d+(?:\.0+)?', v) else ''


def unique(values):
    return list(dict.fromkeys(v for v in values if v))


def rows(path):
    with path.open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def build(rosters, statistics, schedules, previous, season, now=None):
    now = now or datetime.now(timezone.utc)
    if previous.get('schemaVersion') != 1 or not isinstance(previous.get('players'),list):
        raise ValueError('Previous game-log schema missing; refusing to overwrite history')
    players = {p['id']:copy.deepcopy(p) for p in previous['players']}
    by_game = {g['game_id']:g for g in schedules}
    by_week = {}
    for g in schedules:
        st = 'REG' if g.get('game_type')=='REG' else 'POST' if g.get('game_type') in ('WC','DIV','CON','SB') else ''
        for club in [g.get('home_team'),g.get('away_team')]:
            by_week[(str(g.get('season')),str(g.get('week')),logs.team(club),st)] = g
    valid_ids = set()
    for r in statistics:
        pid,name,club = text(r.get('player_id')),text(r.get('player_display_name')),logs.team(r.get('team') or r.get('recent_team'))
        if not pid or not name or r.get('season_type') not in ('REG','POST') or str(r.get('season'))!=str(season):continue
        g = by_game.get(r.get('game_id')) or by_week.get((str(season),r['week'],club,r['season_type']))
        if not g or str(g.get('season'))!=str(season) or not g.get('gameday') or g['gameday']>=now.date().isoformat():continue
        home,away = logs.team(g.get('home_team')),logs.team(g.get('away_team'))
        if club not in (home,away):continue
        if (g.get('game_type')=='REG') != (r['season_type']=='REG'):continue
        hs,as_ = logs.num(g.get('home_score')),logs.num(g.get('away_score'))
        if hs is None or as_ is None:continue
        valid_ids.add(pid)
        p=players.setdefault(pid,dict(id=pid,name=name,position=r.get('position',''),team=club,teams=[],espnId=None,headshot=r.get('headshot_url',''),games=[]))
        p['aliases']=unique(p.get('aliases',[])+[p['name'],name])
        if not p['games'] or g['gameday']>=max(x.get('date','') for x in p['games']):
            p.update(name=name,position=r.get('position') or p['position'],team=club,headshot=r.get('headshot_url') or p.get('headshot',''))
        p['teams']=unique(p.get('teams',[])+[club])
        scored,allowed=(hs,as_) if club==home else (as_,hs)
        values={key:next((logs.num(r[k]) for k in names if k in r and logs.num(r[k]) is not None),None) for key,names in logs.FIELDS.items()}
        item=dict(gameId=g['game_id'],date=g['gameday'],season=season,week=int(r['week']),seasonType=r['season_type'],team=club,opponent=away if club==home else home,homeAway='home' if club==home else 'away',result='W' if scored>allowed else 'L' if scored<allowed else 'T',score=f'{scored}-{allowed}',stats=values)
        p['games']=[x for x in p['games'] if x['gameId']!=item['gameId']]+[item]
    roster_map={}
    for r in rosters:
        if str(r.get('season'))!=str(season):continue
        pid=text(r.get('gsis_id'));espn=eid(r.get('espn_id'))
        if not pid and not espn:continue
        key=pid or 'espn:'+espn
        roster_map.setdefault(key,[]).append(r)
    directory={}
    enriched=0
    for pid,p in players.items():
        rr=roster_map.get(pid,[])
        espns=unique([eid(r.get('espn_id')) for r in rr])
        if len(espns)>1:raise ValueError('Conflicting roster identity for '+pid)
        if espns:
            if p.get('espnId') and eid(p['espnId'])!=espns[0]:raise ValueError('Conflicting game-log identity for '+pid)
            enriched+=not bool(p.get('espnId'))
            p['espnId']=espns[0]
        names=[p['name']]+p.get('aliases',[])
        for r in rr:
            names += [text(r.get('full_name'))]
            for field in ['football_name','first_name']:
                if text(r.get(field)) and text(r.get('last_name')):names.append(text(r[field])+' '+text(r['last_name']))
        p['aliases']=unique(names)
        p['games']=sorted({g['gameId']:g for g in p['games']}.values(),key=lambda g:(g['date'],g['season'],g['week']),reverse=True)[:10]
        directory[pid]=dict(id=pid,player_id=pid,athleteId=eid(p.get('espnId')),name=p['name'],position=p.get('position',''),team=p.get('team',''),teams=p.get('teams',[]),aliases=p['aliases'],headshot=p.get('headshot',''),currentRoster=bool(rr),hasRecordedGames=bool(p['games']))
    for pid,rr in roster_map.items():
        rr.sort(key=lambda r:(logs.num(r.get('week')) or 0,r.get('status')=='ACT'))
        r=rr[-1];names=[]
        for x in rr:
            names.append(text(x.get('full_name')))
            for k in ['football_name','first_name']:
                if text(x.get(k)) and text(x.get('last_name')):names.append(text(x[k])+' '+text(x['last_name']))
        d=directory.setdefault(pid,dict(id=pid,player_id=text(r.get('gsis_id')),athleteId=eid(r.get('espn_id')),name=text(r.get('full_name')),position=r.get('position',''),team=logs.team(r.get('team')),teams=[],aliases=[],headshot=r.get('headshot_url',''),hasRecordedGames=False))
        d.update(currentRoster=True,team=logs.team(r.get('team')),rosterWeek=logs.num(r.get('week')),rosterStatus=text(r.get('status')))
        d['aliases']=unique(d['aliases']+names)
        d['teams']=unique(d['teams']+[logs.team(x.get('team')) for x in rr])
    seen={}
    for d in directory.values():
        if not d['athleteId']:continue
        if d['athleteId'] in seen and seen[d['athleteId']]!=d['id']:raise ValueError('Duplicate ESPN identity')
        seen[d['athleteId']]=d['id']
    result=copy.deepcopy(previous)
    result.update(season=season,generatedAt=now.isoformat(),players=sorted(players.values(),key=lambda p:p['id']))
    result['latestGameDate']=max(g['date'] for p in players.values() for g in p['games'])
    result['identitySource']='nflverse season roster: gsis_id + espn_id; aliases from published names'
    source=f'https://github.com/nflverse/nflverse-data/releases/download/rosters/roster_{season}.csv'
    result['sources']=[s for s in result.get('sources',[]) if s.get('name')!='nflverse roster identities']+[{'name':'nflverse roster identities','url':source}]
    report=dict(ok=True,schemaVersion=1,season=season,generatedAt=now.isoformat(),through=result['latestGameDate'],players=sorted(directory.values(),key=lambda p:(not p['currentRoster'],p['name'])),sources=[{'name':'nflverse roster identities','url':source}],coverage=dict(directoryPlayers=len(directory),playersWithLogs=len(players),currentSeasonStatPlayers=len(valid_ids),espnIdsAdded=int(enriched)))
    return report,result


def save(path,data):
    path.parent.mkdir(exist_ok=True,parents=True)
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(data,ensure_ascii=False,separators=(',',':'),allow_nan=False)+'\n',encoding='utf-8');tmp.replace(path)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--input-dir',type=Path);parser.add_argument('--season',type=int,default=datetime.now(timezone.utc).year-(datetime.now(timezone.utc).month<3));args=parser.parse_args()
    folder=args.input_dir or ROOT/'.directory-inputs';folder.mkdir(exist_ok=True)
    if not args.input_dir:
        for name,url in [('roster.csv',f'https://github.com/nflverse/nflverse-data/releases/download/rosters/roster_{args.season}.csv'),('players.csv',logs.STATS.format(year=args.season)),('games.csv',logs.SCHEDULE)]:
            raw,_=logs.download(url);(folder/name).write_text(raw,encoding='utf-8')
    d,g=build(rows(folder/'roster.csv'),rows(folder/'players.csv'),rows(folder/'games.csv'),json.loads((ROOT/'data/player-recent-games.json').read_text()),args.season)
    if d['coverage']['directoryPlayers']<1000 or d['coverage']['currentSeasonStatPlayers']<100:raise ValueError('Unexpectedly incomplete directory; previous files retained')
    save(ROOT/'data/player-recent-games.json',g);save(ROOT/'data/player-directory.json',d);print(json.dumps(d['coverage']))
if __name__=='__main__':main()
