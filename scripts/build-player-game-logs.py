#!/usr/bin/env python3
"""Build recent recorded NFL game logs; never substitute projections for results.

Sources: nflverse weekly player stats and nflverse/nfldata schedules.
Only published, completed regular-season/postseason games are retained.
Missing numeric fields remain null. Run using Python 3.11+ (stdlib only).
"""
from __future__ import annotations
import argparse
import csv
import io
import json
import math
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

STATS = "https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_{year}.csv"
SCHEDULE = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"
ALIASES = {"LA": "LAR", "STL": "LAR", "JAC": "JAX", "OAK": "LV", "SD": "LAC", "WSH": "WAS"}
FIELDS = {
    "completions": ("completions",), "attempts": ("attempts",),
    "passingYards": ("passing_yards",), "passingTouchdowns": ("passing_tds",),
    "interceptions": ("passing_interceptions", "interceptions"),
    "sacksTaken": ("sacks_suffered", "sacks"),
    "carries": ("carries",), "rushingYards": ("rushing_yards",),
    "rushingTouchdowns": ("rushing_tds",), "targets": ("targets",),
    "receptions": ("receptions",), "receivingYards": ("receiving_yards",),
    "receivingTouchdowns": ("receiving_tds",),
    "soloTackles": ("def_tackles_solo",), "assistedTackles": ("def_tackle_assists",),
    "sacks": ("def_sacks",), "defensiveInterceptions": ("def_interceptions",),
    "passesDefended": ("def_pass_defended", "def_passes_defended"),
    "forcedFumbles": ("def_fumbles_forced",),
    "fieldGoalsMade": ("fg_made",), "fieldGoalsAttempted": ("fg_att",),
    "extraPointsMade": ("pat_made",), "extraPointsAttempted": ("pat_att",),
    "punts": ("punts",), "puntYards": ("punt_yards",),
    "puntInside20": ("punt_inside_20",),
}


def num(value):
    try:
        number = float(value)
        if not math.isfinite(number):
            return None
        return int(number) if number.is_integer() else round(number, 3)
    except (ValueError, TypeError):
        return None


def team(value):
    value = str(value or "").strip().upper()
    return ALIASES.get(value, value)


def download(url, optional=False):
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "GridironPulse-RecentGames/1.0"})
            with urllib.request.urlopen(req, timeout=90) as response:
                raw = response.read().decode("utf-8-sig")
                return raw, response.headers.get("Last-Modified")
        except urllib.error.HTTPError as exc:
            if exc.code == 404 and optional:
                return None, None
            if attempt == 2 or exc.code in (401, 403, 404):
                raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == 2:
                raise
        time.sleep(2 ** attempt)
    raise RuntimeError("Download did not finish")


def build(output: Path, season: int):
    now = datetime.now(timezone.utc)
    raw, updated = download(SCHEDULE)
    schedules = list(csv.DictReader(io.StringIO(raw)))
    by_game = {row["game_id"]: row for row in schedules}
    by_team_week = {}
    for row in schedules:
        for club in (row.get("away_team"), row.get("home_team")):
            by_team_week[(str(row.get("season")), str(row.get("week")), team(club))] = row
    players = {}
    sources = [{"name": "nflverse schedules", "url": SCHEDULE, "lastModified": updated}]
    unavailable = []
    retained = 0
    for year in range(season - 2, season + 1):
        url = STATS.format(year=year)
        raw, updated = download(url, optional=(year == season))
        if raw is None:
            unavailable.append(year)
            continue
        reader = csv.DictReader(io.StringIO(raw))
        columns = set(reader.fieldnames or [])
        required = {"player_id", "player_display_name", "position", "season", "week", "season_type", "passing_yards", "receiving_yards"}
        if not required.issubset(columns):
            raise ValueError(f"Unexpected {year} stats schema: missing {required - columns}")
        print(f"{year}: columns={len(columns)}; defensive fields={sorted(c for c in columns if c.startswith('def_'))}")
        sources.append({"name": f"nflverse {year} weekly player stats", "url": url, "lastModified": updated})
        for row in reader:
            if row.get("season_type") not in ("REG", "POST"):
                continue
            pid = row.get("player_id", "").strip()
            name = row.get("player_display_name", "").strip()
            if not pid or not name:
                continue
            club = team(row.get("team") or row.get("recent_team"))
            schedule = by_game.get(row.get("game_id")) or by_team_week.get((row["season"], row["week"], club))
            # Do not turn future, live, cancelled, or unmapped rows into results.
            if not schedule or num(schedule.get("home_score")) is None or num(schedule.get("away_score")) is None:
                continue
            date = schedule.get("gameday", "")
            if not date or date >= now.date().isoformat():
                continue
            home = team(schedule.get("home_team"))
            away = team(schedule.get("away_team"))
            if club not in (home, away):
                continue
            is_home = club == home
            scored = num(schedule["home_score"] if is_home else schedule["away_score"])
            allowed = num(schedule["away_score"] if is_home else schedule["home_score"])
            stats = {}
            for label, keys in FIELDS.items():
                stats[label] = next((num(row[k]) for k in keys if k in row and num(row[k]) is not None), None)
            headshot = row.get("headshot_url") or ""
            espn = re.search(r"/full/(\d+)\.png", headshot)
            player = players.setdefault(pid, {"id": pid, "name": name, "position": row.get("position", ""), "team": club, "teams": [], "espnId": espn.group(1) if espn else None, "headshot": headshot, "games": []})
            if club not in player["teams"]:
                player["teams"].append(club)
            game = {"gameId": schedule["game_id"], "date": date, "season": int(row["season"]), "week": int(row["week"]), "seasonType": row["season_type"], "team": club, "opponent": away if is_home else home, "homeAway": "home" if is_home else "away", "result": "W" if scored > allowed else "L" if scored < allowed else "T", "score": f"{scored}-{allowed}", "stats": stats}
            player["games"].append(game)
            retained += 1
    if len(players) < 500:
        raise RuntimeError(f"Refusing to publish an unexpectedly empty feed ({len(players)} players)")
    for player in players.values():
        games = {game["gameId"]: game for game in player["games"]}
        player["games"] = sorted(games.values(), key=lambda g: (g["date"], g["season"], g["week"]), reverse=True)[:10]
        player["team"] = player["games"][0]["team"]
    latest_game = max(g["date"] for p in players.values() for g in p["games"])
    payload = {"ok": True, "schemaVersion": 1, "season": season, "generatedAt": now.isoformat(), "latestGameDate": latest_game, "source": "nflverse", "sources": sources, "unavailableSeasons": unavailable, "scope": "Published regular-season and postseason player game records; preseason excluded.", "players": sorted(players.values(), key=lambda p: p["id"])}
    output.parent.mkdir(parents=True, exist_ok=True)
    # Preserve the previous good file when content and source versions are unchanged.
    if output.exists():
        old = json.loads(output.read_text(encoding="utf-8"))
        if all(old.get(k) == v for k, v in payload.items() if k != "generatedAt"):
            print("Recent game stats unchanged")
            return
    temp = output.with_suffix(".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n", encoding="utf-8")
    temp.replace(output)
    print(f"Published {len(players)} players from {retained} recorded games. Latest game: {latest_game}.")
    for name in ("Josh Allen", "Jared Goff", "Saquon Barkley", "Justin Jefferson", "T.J. Watt"):
        sample = next((p for p in players.values() if p["name"] == name), None)
        if sample:
            print(json.dumps({"name": name, "latest": sample["games"][0]}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("data/player-recent-games.json"))
    today = datetime.now(timezone.utc)
    parser.add_argument("--season", type=int, default=today.year if today.month >= 3 else today.year - 1)
    args = parser.parse_args()
    build(args.output, args.season)
