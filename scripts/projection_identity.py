"""Identity-only guardrails for the production v2.1 refresh."""
import math
import re
from numbers import Real
from datetime import datetime, timezone


def number(value):
    if value is None or isinstance(value, bool) or not isinstance(value, (str, Real)):
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        n = float(value)
    except (ValueError, TypeError):
        return None
    return n if math.isfinite(n) else None


def norm(value):
    text = re.sub(r'\b(jr|sr|ii|iii|iv|v)\b', '', str(value or '').lower())
    return re.sub('[^a-z0-9]', '', text)


def team(value):
    if isinstance(value, dict):
        value = value.get('abbreviation') or value.get('code') or value.get('team')
    t = str(value or '').upper()
    return {'LA':'LAR','STL':'LAR','JAC':'JAX','OAK':'LV','SD':'LAC','WSH':'WAS'}.get(t,t)


def player_name(p):
    return str(p.get('name') or p.get('playerName') or p.get('displayName') or p.get('fullName') or p.get('player_name') or '')


def espn_id(p):
    for key in ('athleteId', 'espnId', 'espn_id', 'id', 'playerKey'):
        v = str(p.get(key) or '')
        if v.isdigit():
            return v
    return ''


def canonical_id(value):
    value = str(value or '').strip()
    if re.fullmatch(r'00-\d+', value):
        return 'gsis:' + value
    if value.isdigit():
        return 'espn:' + value
    if value.startswith(('gsis:', 'espn:')):
        return value
    return ''


def changed(prior_id, prior_name, current_id, current_name, resolved=True):
    if not resolved:
        return None
    a, b = canonical_id(prior_id), canonical_id(current_id)
    if a and b and a.split(':')[0] == b.split(':')[0]:
        return a != b
    if norm(prior_name) and norm(current_name):
        return norm(prior_name) != norm(current_name)
    return None


def depth_starter(payload):
    """Read rank-one wrappers OR the site's ordered flat depth-list schema.

    Flat athlete lists are explicitly in depth order in the team depth endpoint,
    unlike the unordered Worker player collection. All formations must agree.
    """
    candidates = []
    stamp = payload.get('timestamp')
    if stamp:
        try:
            dt = datetime.fromisoformat(stamp.replace('Z','+00:00'))
            age = (datetime.now(timezone.utc)-dt).total_seconds()
            if age > 10800 or age < -300:
                return None
        except (ValueError, TypeError):
            return None
    for chart in payload.get('depthchart', payload.get('depthChart', [])):
        positions = chart.get('positions') or {}
        for key, entry in positions.items():
            label = str((entry.get('position') or {}).get('abbreviation') or key).upper()
            if label != 'QB':
                continue
            athletes = entry.get('athletes') or []
            if not athletes:
                continue
            flat_ordered = all(isinstance(item,dict) and item.get('id') and 'athlete' not in item and 'rank' not in item for item in athletes)
            if flat_ordered:
                # Ordered depth lists must carry source time, not just fetch time.
                if not stamp:
                    continue
                selected = [athletes[0]]
            else:
                selected = [item.get('athlete') or item for item in athletes if number(item.get('rank'))==1]
            for athlete in selected:
                if espn_id(athlete) and player_name(athlete):
                    candidates.append({'id':espn_id(athlete),'name':player_name(athlete),'sourceGeneratedAt':stamp})
    unique = {(x['id'], norm(x['name'])): x for x in candidates}
    return next(iter(unique.values())) if len(unique) == 1 else None


def select_qbs(players, forecasts, verified=None):
    verified = verified or {}
    history = {}
    for p in forecasts:
        if str(p.get('forecast_position') or p.get('position') or '').upper() == 'QB':
            history.setdefault(norm(player_name(p)), []).append(p)
    groups = {}
    for p in players:
        if str(p.get('positionGroup') or p.get('position') or '').upper() == 'QB':
            groups.setdefault(team(p.get('team')), []).append(p)
    result = {}
    for tm, room in groups.items():
        room = list({(espn_id(p), norm(player_name(p))):p for p in room}.values())
        chosen, source = None, 'unresolved-conflict'
        v = verified.get(tm)
        if v:
            matches = [p for p in room if (v.get('id') and espn_id(p)==v['id']) or (norm(v.get('name')) and norm(player_name(p))==norm(v['name']))]
            if len(matches)==1:
                chosen, source = matches[0], 'current-espn-depth-rank-1'
        if chosen is None and not v:
            ranked = []
            for p in room:
                dc = p.get('depthChart') or {}
                if (number(dc.get('sourceCount')) or 0) <= 0:
                    continue
                ranks = [number(p.get('depthRank')), number(dc.get('rank')), number(dc.get('depthRank'))]
                if 1 in ranks:
                    ranked.append(p)
            if len(ranked)==1:
                chosen, source = ranked[0], 'verified-worker-depth-rank-1'
            elif not ranked:
                starters = [p for p in room if str(p.get('role') or '').upper()=='STARTER']
                if len(starters)==1:
                    chosen, source = starters[0], 'unique-worker-starter'
        if chosen is None:
            result[tm] = {'playerId':'', 'playerName':'', 'rate':None, 'resolved':False, 'source':source, 'candidates':[player_name(p) for p in room]}
            continue
        matched = history.get(norm(player_name(chosen)), [])
        ids = {str(p.get('player_id') or '') for p in matched}
        h = matched[0] if len(ids)==1 and matched else {}
        cid = canonical_id(h.get('player_id')) or canonical_id(espn_id(chosen))
        result[tm] = {'playerId':cid, 'espnId':espn_id(chosen), 'playerName':player_name(chosen), 'rate':number(h.get('latest_rate')), 'resolved':True, 'source':source, 'sourceGeneratedAt':(v or {}).get('sourceGeneratedAt'), 'candidates':[player_name(p) for p in room]}
    return result
