"""Published box scores -> descriptive defense comparisons. Never modifies predictions."""
import argparse
import csv
import hashlib
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ALIASES = {'LA': 'LAR', 'STL': 'LAR', 'WSH': 'WAS', 'JAC': 'JAX', 'SD': 'LAC', 'OAK': 'LV'}
NAMES = dict(x.split('=', 1) for x in (
    'ARI=Arizona Cardinals|ATL=Atlanta Falcons|BAL=Baltimore Ravens|BUF=Buffalo Bills|'
    'CAR=Carolina Panthers|CHI=Chicago Bears|CIN=Cincinnati Bengals|CLE=Cleveland Browns|'
    'DAL=Dallas Cowboys|DEN=Denver Broncos|DET=Detroit Lions|GB=Green Bay Packers|'
    'HOU=Houston Texans|IND=Indianapolis Colts|JAX=Jacksonville Jaguars|KC=Kansas City Chiefs|'
    'LAC=Los Angeles Chargers|LAR=Los Angeles Rams|LV=Las Vegas Raiders|MIA=Miami Dolphins|'
    'MIN=Minnesota Vikings|NE=New England Patriots|NO=New Orleans Saints|NYG=New York Giants|'
    'NYJ=New York Jets|PHI=Philadelphia Eagles|PIT=Pittsburgh Steelers|SEA=Seattle Seahawks|'
    'SF=San Francisco 49ers|TB=Tampa Bay Buccaneers|TEN=Tennessee Titans|WAS=Washington Commanders'
).split('|'))
POSITIONS = ('QB', 'RB', 'WR', 'TE')
METRICS = {}

def metric(key, label, unit='per game', higher=False):
    METRICS[key] = {'label': label, 'unit': unit, 'higherBetter': higher}

for k, label in [
    ('passYards', 'Passing yards allowed (gross)'), ('netPassYards', 'Net passing yards allowed'),
    ('rushYards', 'Rushing yards allowed'), ('totalYards', 'Total net yards allowed'),
    ('passTD', 'Passing TDs allowed'), ('rushTD', 'Rushing TDs allowed'),
    ('completions', 'Completions allowed'), ('attempts', 'Opponent pass attempts'),
    ('carries', 'Opponent rush attempts'), ('explosivePass', '20+ yard passes allowed'),
    ('explosiveRun', '10+ yard runs allowed'), ('points', 'Scoreboard points against')]: metric(k, label)
metric('completionPct', 'Completion percentage allowed', '%')
metric('yardsPerAttempt', 'Gross yards per pass attempt allowed', 'yds / attempt')
metric('yardsPerCarry', 'Yards per carry allowed', 'yds / carry')
for k, label in [('sacks', 'Sacks made'), ('interceptions', 'Interceptions made'),
                 ('takeaways', 'Takeaways'), ('qbHits', 'Quarterback hits')]: metric(k, label, higher=True)
for p in POSITIONS:
    metric(p + '_fantasy', p + ' fantasy points allowed (PPR)', 'pts / game')
    for k, label in [('receivingYards', 'receiving yards'), ('receptions', 'catches'),
                     ('receivingTD', 'receiving TDs'), ('rushingYards', 'rushing yards'),
                     ('rushingTD', 'rushing TDs'), ('passingYards', 'passing yards'),
                     ('passingTD', 'passing TDs'), ('scrimmageYards', 'scrimmage yards')]:
        metric(p + '_' + k, p + ' group ' + label + ' allowed')
RATIOS = {'completionPct': ('completions', 'attempts', 100),
          'yardsPerAttempt': ('passYards', 'attempts', 1),
          'yardsPerCarry': ('rushYards', 'carries', 1)}
PLAYER_FIELDS = {'passingYards': 'passing_yards', 'passingTD': 'passing_tds',
                 'interceptions': 'passing_interceptions', 'rushingYards': 'rushing_yards',
                 'rushingTD': 'rushing_tds', 'receivingYards': 'receiving_yards',
                 'receivingTD': 'receiving_tds', 'receptions': 'receptions',
                 'targets': 'targets', 'carries': 'carries'}

def tm(v): return ALIASES.get(str(v).upper(), str(v).upper())
def pos(v): return 'RB' if v in ('FB', 'HB', 'TB') else v

def num(v):
    if v is None or isinstance(v, bool) or str(v).strip() == '': return None
    try:
        n = float(v)
        return n if math.isfinite(n) else None
    except (TypeError, ValueError): return None

def strict_sum(values):
    values = list(values)
    return sum(values) if all(v is not None for v in values) else None

def fantasy(r):
    """Offensive PPR only: no returns/bonuses. Never fill an absent stat with zero."""
    weights = {'passing_yards': .04, 'passing_tds': 4, 'passing_interceptions': -2,
               'rushing_yards': .1, 'rushing_tds': 6, 'receiving_yards': .1,
               'receiving_tds': 6, 'receptions': 1, 'sack_fumbles_lost': -2,
               'rushing_fumbles_lost': -2, 'receiving_fumbles_lost': -2,
               'passing_2pt_conversions': 2, 'rushing_2pt_conversions': 2,
               'receiving_2pt_conversions': 2}
    vals = {k: num(r.get(k)) for k in weights}
    return sum(vals[k] * w for k, w in weights.items()) if all(v is not None for v in vals.values()) else None

def player_values(r):
    v = {k: num(r.get(field)) for k, field in PLAYER_FIELDS.items()}
    v['scrimmageYards'] = strict_sum([v['rushingYards'], v['receivingYards']])
    v['scrimmageTD'] = strict_sum([v['rushingTD'], v['receivingTD']])
    v['fantasy'] = fantasy(r)
    return v

def aggregate(games, keys):
    out = {}
    for key in keys:
        if key in RATIOS:
            a, b, multiplier = RATIOS[key]
            valid = [g['values'] for g in games if num(g['values'].get(a)) is not None and num(g['values'].get(b)) is not None]
            den = sum(v[b] for v in valid)
            value = multiplier * sum(v[a] for v in valid) / den if den > 0 else None
        else:
            valid = [g['values'][key] for g in games if num(g['values'].get(key)) is not None]
            value = sum(valid) / len(valid) if valid else None
        out[key] = {'value': round(value, 4) if value is not None else None,
                    'n': len(valid), 'expected': len(games)}
    return out

def windows(games, keys):
    ordered = sorted(games, key=lambda g: (g['date'], g['id']))
    return {label: aggregate(rows, keys) for label, rows in
            [('season', ordered), ('last3', ordered[-3:]), ('last5', ordered[-5:])]}

def kickoff(row):
    dt = datetime.fromisoformat(row['gameday'] + 'T' + (row.get('gametime') or '13:00'))
    return dt.replace(tzinfo=ZoneInfo('America/New_York')).astimezone(timezone.utc)

def build(team_rows, player_rows, schedule, season, identities=None, now=None):
    now = now or datetime.now(timezone.utc)
    games = {g['game_id']: g for g in schedule if str(g.get('season')) == str(season) and g.get('game_type') == 'REG'}
    completed = {gid: g for gid, g in games.items() if num(g.get('away_score')) is not None and num(g.get('home_score')) is not None and kickoff(g) <= now}
    tmap = {}
    for r in team_rows:
        if r.get('season_type') != 'REG' or str(r.get('season')) != str(season) or r.get('game_id') not in completed: continue
        key = (r['game_id'], tm(r['team']))
        if key in tmap and tmap[key] != r: raise ValueError('Conflicting duplicate team row: ' + str(key))
        tmap[key] = r
    pmap = {}
    for r in player_rows:
        if r.get('season_type') != 'REG' or str(r.get('season')) != str(season) or r.get('game_id') not in completed: continue
        key = (r['game_id'], r['player_id'], tm(r['team']))
        if key in pmap and pmap[key] != r: raise ValueError('Conflicting duplicate player row: ' + str(key))
        pmap[key] = r
    by_offense = defaultdict(list)
    for r in pmap.values(): by_offense[(r['game_id'], tm(r['team']))].append(r)
    teams = {k: {'abbreviation': k, 'name': v, 'games': [], 'schedule': []} for k, v in NAMES.items()}
    warnings = []
    for gid, g in games.items():
        for side, other in [('home', 'away'), ('away', 'home')]:
            code, opponent = tm(g[side + '_team']), tm(g[other + '_team'])
            teams[code]['schedule'].append({'id': gid, 'espnId': str(g.get('espn') or ''), 'date': kickoff(g).isoformat(),
                                            'opponent': opponent, 'home': side == 'home', 'completed': gid in completed})
            if gid not in completed: continue
            own, opp = tmap.get((gid, code)), tmap.get((gid, opponent))
            def take(field): return num(opp.get(field)) if opp else None
            def made(field): return num(own.get(field)) if own else None
            vals = {k: take(f) for k, f in {'passYards': 'passing_yards', 'rushYards': 'rushing_yards',
                     'passTD': 'passing_tds', 'rushTD': 'rushing_tds', 'completions': 'completions',
                     'attempts': 'attempts', 'carries': 'carries', 'explosivePass': 'passing_20',
                     'explosiveRun': 'rushing_10'}.items()}
            sy = take('sack_yards_lost')
            vals['netPassYards'] = vals['passYards'] - abs(sy) if sy is not None and vals['passYards'] is not None else None
            vals['totalYards'] = strict_sum([vals['netPassYards'], vals['rushYards']])
            vals['points'] = num(g[other + '_score'])
            vals.update(sacks=made('def_sacks'), interceptions=made('def_interceptions'), qbHits=made('def_qb_hits'))
            vals['takeaways'] = strict_sum([take('passing_interceptions'), take('fumbles_lost_total')])
            prows = by_offense[(gid, opponent)]
            complete = bool(opp and prows)
            for field in ['passing_yards', 'rushing_yards', 'receiving_yards', 'attempts', 'receptions']:
                pv = strict_sum(num(r.get(field)) for r in prows)
                tv = take(field)
                complete = complete and pv is not None and tv is not None and abs(pv - tv) < .01
            unknown = any(not r.get('position') and any((num(r.get(f)) or 0) != 0 for f in ['attempts', 'carries', 'targets']) for r in prows)
            complete = complete and not unknown
            if not complete: warnings.append(gid + ' / ' + opponent + ': position totals incomplete; withheld')
            for p in POSITIONS:
                group = [player_values(r) for r in prows if pos(r.get('position')) == p]
                for key in ['fantasy', 'receivingYards', 'receptions', 'receivingTD', 'rushingYards', 'rushingTD', 'passingYards', 'passingTD', 'scrimmageYards']:
                    vals[p + '_' + key] = strict_sum(v[key] for v in group) if complete else None
            teams[code]['games'].append({'id': gid, 'espnId': str(g.get('espn') or ''), 'date': g['gameday'],
                                        'week': int(g['week']), 'opponent': opponent, 'home': side == 'home',
                                        'for': num(g[side + '_score']), 'against': num(g[other + '_score']), 'values': vals})
    all_games = []
    for t in teams.values():
        t['games'].sort(key=lambda r: (r['date'], r['id']))
        t['schedule'].sort(key=lambda r: r['date'])
        t['averages'] = windows(t['games'], METRICS)
        t['completedGames'] = len(t['games'])
        t['record'] = '-'.join(str(sum(1 for g in t['games'] if fn(g['for'], g['against']))) for fn in
                               [lambda a,b:a>b, lambda a,b:a<b, lambda a,b:a==b])
        all_games.extend(t['games'])
    league = aggregate(all_games, METRICS)
    for key in METRICS:
        eligible = [(code, t['averages']['season'][key]['value']) for code,t in teams.items()
                    if t['completedGames'] and t['averages']['season'][key]['n'] == t['completedGames']
                    and t['averages']['season'][key]['value'] is not None]
        for code, value in eligible:
            rank = 1 + sum(v > value if METRICS[key]['higherBetter'] else v < value for _,v in eligible)
            teams[code].setdefault('ranks', {})[key] = {'rank': rank, 'of': len(eligible)}
    players = {}
    for r in pmap.values():
        p = pos(r.get('position'))
        if p not in POSITIONS: continue
        pid = r['player_id']; g = completed[r['game_id']]
        identity = (identities or {}).get(pid, {})
        item = players.setdefault(pid, {'id': pid, 'espnId': identity.get('espnId'), 'name': r['player_display_name'],
                                      'position': p, 'team': tm(r['team']), 'games': []})
        item['games'].append({'id': g['game_id'], 'date': g['gameday'], 'week': int(g['week']),
                              'team': tm(r['team']), 'opponent': tm(r['opponent_team']), 'values': player_values(r)})
    for p in players.values():
        p['games'].sort(key=lambda r:(r['date'], r['id']))
        p['team'] = p['games'][-1]['team']
        p['averages'] = windows(p['games'], list(PLAYER_FIELDS) + ['scrimmageYards','scrimmageTD','fantasy'])
    stamp = now.isoformat()
    shared = {'schemaVersion': 1, 'season': season, 'seasonType': 'REG', 'generatedAt': stamp,
              'through': max((g['gameday'] for gid,g in completed.items() if any(k[0] == gid for k in tmap)), default=None),
              'sources': [{'name': 'nflverse weekly team stats', 'url': f'https://github.com/nflverse/nflverse-data/releases/download/stats_team/stats_team_week_{season}.csv'},
                          {'name': 'nflverse weekly player stats', 'url': f'https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_{season}.csv'},
                          {'name': 'nflverse game schedule', 'url': 'https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv'}]}
    defense = dict(shared, ok=True, metrics=METRICS, league=league, teams=teams, warnings=sorted(set(warnings)),
        definitions={'scope': 'Completed regular-season games only. Averages use available verified games; each bar shows its sample. Missing data is never zero.',
                     'pass': 'Gross passing yards exclude sack losses. Net passing yards subtract the magnitude of sack yards lost.',
                     'explosive': 'Explosive = a pass of 20+ yards or a rush of 10+ yards. Definitions chosen for this dashboard.',
                     'position': 'QB/RB/WR/TE allowance is the entire opposing position group per team-game, not an individual projection. RB includes FB.',
                     'fantasy': 'Offensive PPR: 1/catch, 1/10 rushing or receiving yards, 1/25 passing yards, 6/rush or receiving TD, 4/pass TD, -2/INT or offensive lost fumble, 2/two-point conversion. No return TDs, bonuses or defensive scoring.',
                     'league': 'League bar is a team-game weighted mean; percentages and yards per attempt use pooled attempts. Rank 1 is fewest allowed, or most sacks/takeaways.',
                     'points': 'Points against come from the final scoreboard and can include scores conceded by offense or special teams.',
                     'takeaways': 'Opponent interceptions thrown plus total fumbles lost, including special teams. QB hits are not a pressure rate.'})
    return defense, dict(shared, ok=True, players=players, scope='Published statistical appearances; not a count of starts or all active games.')

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--input-dir', default='.defense-inputs'); ap.add_argument('--out',default='data'); ap.add_argument('--season',type=int,required=True)
    a = ap.parse_args(); root=Path(a.input_dir)
    def read(name):
        with (root / (name + '.csv')).open(encoding='utf-8-sig',newline='') as f: return list(csv.DictReader(f))
    recent=Path('data/player-recent-games.json'); identities={}
    if recent.exists(): identities={str(p['id']):p for p in json.loads(recent.read_text()).get('players',[])}
    d,p=build(read('teams'),read('players'),read('games'),a.season,identities)
    if not any(t['games'] for t in d['teams'].values()): raise ValueError('No finalized current-season statistics; previous feed not overwritten')
    hashes={n:hashlib.sha256((root/(n+'.csv')).read_bytes()).hexdigest() for n in ['teams','players','games']}
    d['sourceHashes']=p['sourceHashes']=hashes
    out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
    for name,data in [('team-defense.json',d),('defense-players.json',p)]:
        temp=out/(name+'.tmp');temp.write_text(json.dumps(data,separators=(',',':'),allow_nan=False));temp.replace(out/name)
    print(json.dumps({'teams':len(d['teams']),'teamGames':sum(t['completedGames'] for t in d['teams'].values()),'players':len(p['players']),'through':d['through'],'warnings':len(d['warnings'])}))
if __name__=='__main__': main()
