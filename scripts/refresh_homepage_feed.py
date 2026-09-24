#!/usr/bin/env python3
"""Refresh current games and progressively warm the existing agent's history.

No model coefficients, historical locked picks, or grades are modified here.
A timestamp proves freshness, not input coverage; both are reported separately.
The refresh key is used only in an authorization header and is never printed.
"""
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

AGENT = 'https://grid-pulse-agent.kadescott97.workers.dev'
SCOREBOARD = 'https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard'
DATA = Path('data')
MAX_REFRESH_PASSES = 3
KV_SETTLE_SECONDS = 65


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def age_seconds(stamp):
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(str(stamp).replace('Z', '+00:00'))).total_seconds()
    except (ValueError, TypeError):
        return float('inf')


def request_json(url, method='GET', token=''):
    headers = {'Accept': 'application/json', 'User-Agent': 'GridironPulse-HomepageRefresh/2', 'Cache-Control': 'no-cache'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    request = Request(url, data=b'' if method == 'POST' else None, headers=headers, method=method)
    try:
        with urlopen(request, timeout=100) as response:
            payload = json.load(response)
    except HTTPError as error:
        raise RuntimeError('Homepage source returned HTTP ' + str(error.code)) from None
    if not isinstance(payload, dict):
        raise RuntimeError('Homepage source did not return a JSON object')
    return payload


def check(snapshot, season, week, ids):
    if not isinstance(snapshot, dict):
        return False
    actual = snapshot.get('season') or {}
    if any(str(actual.get(k)) != str(season[k]) for k in ('year', 'type')):
        return False
    if str(actual.get('week')) != str(week):
        return False
    if not -300 <= age_seconds(snapshot.get('generatedAt')) <= 5400:
        return False
    games = snapshot.get('games')
    if not isinstance(games, list):
        return False
    returned = {str(g.get('id')) for g in games if isinstance(g, dict)}
    return bool(ids) and ids.issubset(returned)


def signal_coverage(snapshot, target_samples):
    """Read actual evidence counts; do not infer history from a nonzero score."""
    games = {str(g.get('id')): g for g in snapshot.get('games', []) if isinstance(g, dict)}
    boards = {str(b.get('gameId')): b for b in snapshot.get('playerEdge', []) if isinstance(b, dict)}
    teams = {}
    picks = []
    for game_id, game in games.items():
        if (game.get('status') or {}).get('state') != 'pre':
            continue
        board = boards.get(game_id, {})
        samples = (board.get('evidence') or {}).get('formSamples') or {}
        for side in ('away', 'home'):
            team = (game.get('teams') or {}).get(side) or {}
            value = samples.get(side)
            count = int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0
            name = str(team.get('abbreviation') or team.get('id') or game_id + ':' + side)
            teams[name] = max(0, count)
        picks.extend(p for p in board.get('picks', []) if isinstance(p, dict))
    signals = [s for p in picks for s in p.get('signals', []) if isinstance(s, dict)]
    fallback_count = sum('still being established' in str(s.get('detail', '')).lower() for s in signals)
    sample_seasons = sorted({str(g.get('seasonYear')) for p in picks for g in p.get('recentGames', []) if isinstance(g, dict) and g.get('seasonYear') is not None})
    no_player_history = [p.get('name') for p in picks if not p.get('baselineAvailable') or not p.get('recentGames')]
    ready = bool(games) and all(n >= target_samples for n in teams.values())
    return {
        'historyReady': ready,
        'targetRecentGamesPerTeam': target_samples,
        'pregameTeams': len(teams),
        'teamsWithHistory': sum(n > 0 for n in teams.values()),
        'teamsMeetingSampleTarget': sum(n >= target_samples for n in teams.values()),
        'teamSamples': teams,
        'playerPicks': len(picks),
        'picksWithGameHistory': len(picks) - len(no_player_history),
        'playersWithoutGameHistory': no_player_history,
        'signalCount': len(signals),
        'fallbackSignalCount': fallback_count,
        'sampleSeasons': sample_seasons,
        'note': 'Small samples remain small samples. A missing player history is not evidence of zero production. Sample counts can include prior-season games under the existing agent policy.',
    }


def sample_signals(snapshot):
    wanted = {'Patrick Mahomes', 'Travis Kelce', "De'Von Achane"}
    found = {}
    for board in snapshot.get('playerEdge', []):
        pool = board.get('candidatePool') or {}
        players = list(board.get('picks', [])) + list(pool.get('away', [])) + list(pool.get('home', []))
        for p in players:
            if p.get('name') not in wanted or p['name'] in found:
                continue
            found[p['name']] = {k: p.get(k) for k in ['name', 'team', 'position', 'score', 'baselineAvailable', 'recentGames', 'signals']}
    return list(found.values())


def save_json(name, value):
    DATA.mkdir(exist_ok=True)
    path = DATA / name
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, indent=2, allow_nan=False), encoding='utf-8')
    temp.replace(path)


def archive_results(snapshot):
    path = DATA / 'homepage-result-archive.json'
    previous = json.loads(path.read_text()) if path.exists() else {'results': []}
    rows = {}
    for row in previous.get('results', []):
        key = '|'.join(str(row.get(k, '')) for k in ('gameId', 'player', 'team'))
        rows[key] = row
    game_map = {str(g.get('id')): g for g in snapshot.get('games', [])}
    for result in snapshot.get('results', []):
        if not isinstance(result, dict):
            continue
        row = dict(result)
        game = game_map.get(str(row.get('gameId')), {})
        row['gameDate'] = row.get('gameDate') or game.get('date')
        row['sourceGeneratedAt'] = snapshot.get('generatedAt')
        key = '|'.join(str(row.get(k, '')) for k in ('gameId', 'player', 'team'))
        rows[key] = row
    save_json('homepage-result-archive.json', {'description': 'Actual stored agent results; no retroactive predictions created.', 'results': list(rows.values())})


def main():
    report = {'checkedAt': now_iso(), 'workflowRun': os.getenv('GITHUB_RUN_ID'), 'ok': False, 'refreshed': False, 'refreshPasses': []}
    try:
        board = request_json(SCOREBOARD)
        season = board.get('season') or {}
        week = (board.get('week') or {}).get('number')
        ids = {str(e.get('id')) for e in board.get('events', []) if e.get('id')}
        if not all(season.get(k) for k in ('year', 'type')) or not week or not ids:
            raise RuntimeError('Current NFL slate unavailable; no guessed week was used')
        target = min(3, max(1, int(week) - 1)) if season['type'] == 2 else 1
        report.update(expectedSeason=season['year'], expectedSeasonType=season['type'], expectedWeek=week)
        health = request_json(AGENT + '/health')
        if not health.get('ok') or not (health.get('bindings') or {}).get('kv'):
            raise RuntimeError('Homepage agent is unavailable or its storage binding is missing')
        latest = request_json(AGENT + '/latest').get('snapshot') or {}
        report.update(previousGeneratedAt=latest.get('generatedAt'), previousSeason=latest.get('season'), previousResultCount=len(latest.get('results', [])), previousAnalysisInputs=signal_coverage(latest, target))
        archive_results(latest)
        for pass_index in range(MAX_REFRESH_PASSES):
            coverage = signal_coverage(latest, target)
            fresh = check(latest, season, week, ids)
            if fresh and age_seconds(latest.get('generatedAt')) <= 1200 and coverage['historyReady']:
                break
            token = os.getenv('GRIDIRON_AGENT_RUN_KEY', '').strip()
            if (health.get('bindings') or {}).get('runKey') and not token:
                raise RuntimeError('Agent refresh requires RUN_KEY. Add the Worker RUN_KEY as GitHub Actions secret GRIDIRON_AGENT_RUN_KEY. No authentication was bypassed.')
            if '/run-now' not in health.get('routes', []):
                raise RuntimeError('The deployed agent does not advertise the expected refresh route')
            if pass_index:
                # Let KV writes become visible before asking the next pass to
                # advance the history cursor. Never run these passes in parallel.
                time.sleep(KV_SETTLE_SECONDS)
            query = urlencode({'year': season['year'], 'type': season['type'], 'week': week})
            payload = request_json(AGENT + '/run-now?' + query, method='POST', token=token)
            if payload.get('ok') is not True:
                raise RuntimeError('Homepage agent rejected regeneration; the previous mirror was retained')
            latest = payload.get('snapshot') or {}
            if not check(latest, season, week, ids):
                raise RuntimeError('Regenerated homepage failed timestamp, season/week, or current-game checks')
            report['refreshed'] = True
            after = signal_coverage(latest, target)
            report['refreshPasses'].append({'generatedAt': latest.get('generatedAt'), 'teamsWithHistory': after['teamsWithHistory'], 'teamsMeetingSampleTarget': after['teamsMeetingSampleTarget'], 'fallbackSignalCount': after['fallbackSignalCount'], 'warnings': latest.get('warnings', [])})
            print('History pass ' + str(pass_index + 1) + ': ' + json.dumps(report['refreshPasses'][-1]), flush=True)
        if not check(latest, season, week, ids):
            raise RuntimeError('Current homepage did not pass freshness and slate checks')
        coverage = signal_coverage(latest, target)
        latest['analysisInputStatus'] = coverage
        archive_results(latest)
        save_json('homepage-snapshot.json', {'ok': True, 'snapshot': latest})
        report.update(ok=True, generatedAt=latest['generatedAt'], season=latest['season'], gameCount=len(latest['games']), resultCount=len(latest.get('results', [])), analysisInputs=coverage, sampleSignals=sample_signals(latest), warnings=latest.get('warnings', []))
        if not coverage['historyReady']:
            report['analysisWarning'] = 'History warm-up is incomplete; a fresh timestamp alone does not mean complete analysis.'
    except Exception as error:
        report['error'] = str(error)
    save_json('homepage-feed-status.json', report)
    print(json.dumps(report, indent=2), flush=True)
    # Incomplete input coverage remains visibly unsuccessful in Actions even
    # though a timestamped partial mirror can still serve current game scores.
    return 0 if report['ok'] and (report.get('analysisInputs') or {}).get('historyReady') else 1


if __name__ == '__main__':
    sys.exit(main())
