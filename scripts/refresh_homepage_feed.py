#!/usr/bin/env python3
"""Refresh the existing homepage agent; never fabricate or regrade predictions.

The current season/week comes from ESPN, not a hardcoded WEEK environment
variable. A failed regeneration leaves the last validated mirror untouched.
An optional GRIDIRON_AGENT_RUN_KEY GitHub secret is used only in a header.
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

AGENT = 'https://grid-pulse-agent.kadescott97.workers.dev'
SCOREBOARD = 'https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard'
DATA = Path('data')


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def age_seconds(stamp):
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(str(stamp).replace('Z', '+00:00'))).total_seconds()
    except (ValueError, TypeError):
        return float('inf')


def request_json(url, method='GET', token=''):
    headers = {'Accept': 'application/json', 'User-Agent': 'GridironPulse-HomepageRefresh/1', 'Cache-Control': 'no-cache'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    request = Request(url, data=b'' if method == 'POST' else None, headers=headers, method=method)
    try:
        with urlopen(request, timeout=100) as response:
            payload = json.load(response)
    except HTTPError as error:
        # No request headers, credentials, or arbitrary error pages in public logs.
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
    age = age_seconds(snapshot.get('generatedAt'))
    if not -300 <= age <= 5400:
        return False
    games = snapshot.get('games')
    if not isinstance(games, list):
        return False
    returned = {str(g.get('id')) for g in games if isinstance(g, dict)}
    return bool(ids) and ids.issubset(returned)


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
    report = {'checkedAt': now_iso(), 'workflowRun': os.getenv('GITHUB_RUN_ID'), 'ok': False, 'refreshed': False}
    try:
        board = request_json(SCOREBOARD)
        season = board.get('season') or {}
        week = (board.get('week') or {}).get('number')
        ids = {str(e.get('id')) for e in board.get('events', []) if e.get('id')}
        if not all(season.get(k) for k in ('year', 'type')) or not week or not ids:
            raise RuntimeError('Current NFL slate unavailable; no guessed week was used')
        report.update(expectedSeason=season['year'], expectedSeasonType=season['type'], expectedWeek=week)
        health = request_json(AGENT + '/health')
        if not health.get('ok') or not (health.get('bindings') or {}).get('kv'):
            raise RuntimeError('Homepage agent is unavailable or its storage binding is missing')
        latest = request_json(AGENT + '/latest').get('snapshot') or {}
        report.update(previousGeneratedAt=latest.get('generatedAt'), previousSeason=latest.get('season'), previousResultCount=len(latest.get('results', [])))
        archive_results(latest)
        if not check(latest, season, week, ids) or age_seconds(latest.get('generatedAt')) > 1200:
            token = os.getenv('GRIDIRON_AGENT_RUN_KEY', '').strip()
            if (health.get('bindings') or {}).get('runKey') and not token:
                raise RuntimeError('Agent refresh requires RUN_KEY. Add the existing Worker RUN_KEY as GitHub Actions secret GRIDIRON_AGENT_RUN_KEY. No authentication was bypassed.')
            if '/run-now' not in health.get('routes', []):
                raise RuntimeError('The deployed agent does not advertise the expected refresh route')
            query = urlencode({'year': season['year'], 'type': season['type'], 'week': week})
            payload = request_json(AGENT + '/run-now?' + query, method='POST', token=token)
            if payload.get('ok') is not True:
                raise RuntimeError('Homepage agent rejected regeneration; the previous mirror was retained')
            latest = payload.get('snapshot') or {}
            report['refreshed'] = True
        if not check(latest, season, week, ids):
            raise RuntimeError('Regenerated homepage failed timestamp, season/week, or current-game checks')
        archive_results(latest)
        save_json('homepage-snapshot.json', {'ok': True, 'snapshot': latest})
        report.update(ok=True, generatedAt=latest['generatedAt'], season=latest['season'], gameCount=len(latest['games']), resultCount=len(latest.get('results', [])))
    except Exception as error:
        report['error'] = str(error)
    save_json('homepage-feed-status.json', report)
    print(json.dumps(report, indent=2), flush=True)
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
