#!/usr/bin/env python3
"""Create verified full-history yardage inputs and a time-held-out uncertainty report.

Sources are official nflverse weekly statistical records from 1999 onward.
No game from the forecasted week, future game, postseason game, or incomplete
current-season fixture is allowed into an input. Missing values stay missing.
"""
from __future__ import annotations
import argparse
import csv
import json
import math
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

CURRENT_METRICS = {
    "QB": ("passingYards", "rushingYards"),
    "RB": ("scrimmageYards", "rushingYards", "receivingYards"),
    "WR": ("receivingYards", "rushingYards"),
    "TE": ("receivingYards",),
}
COLUMNS = {
    "passingYards": ("passing_yards",),
    "rushingYards": ("rushing_yards",),
    "receivingYards": ("receiving_yards",),
    "scrimmageYards": ("rushing_yards", "receiving_yards"),
}
ALIASES = {"LA": "LAR", "STL": "LAR", "WSH": "WAS", "JAC": "JAX", "SD": "LAC", "OAK": "LV"}
MIN_PAST = 5
Z_80 = 1.2815515655446004


def team(value):
    value = str(value or "").strip().upper()
    return ALIASES.get(value, value)


def position(value):
    value = str(value or "").strip().upper()
    return "RB" if value in ("FB", "HB", "TB") else value


def value(raw):
    if raw is None or isinstance(raw, bool) or str(raw).strip() == "":
        return None
    try:
        v = float(raw)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def number_or_none(nums):
    nums = list(nums)
    return round(statistics.mean(nums), 4) if nums else None


def quantile(vals, p):
    if not vals:
        return None
    sorted_vals = sorted(vals)
    k = (len(sorted_vals) - 1) * p
    a, b = int(math.floor(k)), int(math.ceil(k))
    return sorted_vals[a] * (1 - (k - a)) + sorted_vals[b] * (k - a)


def summarize(values):
    vals = [x for x in values if x is not None]
    return {"value": number_or_none(vals), "n": len(vals)}


def get_stat(game, metric):
    vals = (game.get("values") or {})
    return vals.get(metric)


def signal(history, metric, opponent, year):
    """All rows in history have already been played (chronological pregame)."""
    relevant = [(g, get_stat(g, metric)) for g in history if get_stat(g, metric) is not None]
    if len(relevant) < MIN_PAST:
        return None
    prior = [v for g, v in relevant if g["season"] < year]
    season = [v for g, v in relevant if g["season"] == year]
    all_values = [v for _, v in relevant]
    last5 = all_values[-5:]
    career_mean = statistics.mean(all_values)
    prior_mean = statistics.mean(prior) if prior else career_mean
    season_mean = statistics.mean(season) if season else None
    baseline = ((len(season) * season_mean + 6 * prior_mean) /
                (len(season) + 6)) if season_mean is not None else prior_mean
    reference = season_mean if season_mean is not None else baseline
    # A five-game streak is useful, but never replaces full history.
    recent_adjust = 0.45 * len(last5) / (len(last5) + 5) * (statistics.mean(last5) - reference)
    opponents = [(g, v) for g, v in relevant if g["opponent"] == team(opponent)]
    weighted_avg, effective_n = None, 0.0
    if opponents:
        weights = [0.5 ** (max(0, year - g["season"]) / 3.0) for g, _ in opponents]
        effective_n = sum(weights)
        weighted_avg = sum(w * v for (_, v), w in zip(opponents, weights)) / effective_n
    h2h_adjust = (0.35 * effective_n / (effective_n + 3) *
                  (weighted_avg - baseline)) if weighted_avg is not None else 0.0
    forecast = max(0.0, baseline + recent_adjust + h2h_adjust)
    return {
        "forecast": round(forecast, 4),
        "career": summarize(all_values),
        "priorCareer": summarize(prior),
        "season": summarize(season),
        "last5": summarize(last5),
        "h2h": {
            "value": round(weighted_avg, 4) if weighted_avg is not None else None,
            "raw": summarize([v for _, v in opponents]),
            "effectiveN": round(effective_n, 4),
            "latestSeason": max((g["season"] for g, _ in opponents), default=None),
        },
        "historyN": len(relevant),
    }


def read_rows(file, year, completed=None):
    with file.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        required = {"player_id", "player_display_name", "position", "season",
                    "week", "season_type", "opponent_team", "game_id"}
        if not required.issubset(set(reader.fieldnames or [])):
            raise ValueError(f"Missing mandatory columns in {file}: {required - set(reader.fieldnames or [])}")
        for row in reader:
            if row.get("season_type") != "REG" or int(row["season"]) != year:
                continue
            pos = position(row.get("position"))
            if pos not in CURRENT_METRICS:
                continue
            pid = row.get("player_id", "")
            if not pid.startswith("00-"):
                continue
            game_id = row.get("game_id", "")
            if year == CURRENT_SEASON and completed is not None and game_id not in completed:
                continue
            stat = {}
            for key in CURRENT_METRICS[pos]:
                parts = [value(row.get(k)) for k in COLUMNS[key]]
                stat[key] = sum(parts) if all(v is not None for v in parts) else None
            yield {
                "id": pid, "name": row["player_display_name"],
                "position": pos, "season": year, "week": int(row["week"]),
                "gameId": game_id, "team": team(row.get("team") or row.get("recent_team")),
                "opponent": team(row.get("opponent_team")), "values": stat,
            }


def completed_schedule(file, year):
    ids = set()
    today = datetime.now(timezone.utc).date().isoformat()
    with file.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            if str(row.get("season")) != str(year) or row.get("game_type") != "REG":
                continue
            if (row.get("gameday") or "9999") >= today:
                continue
            if value(row.get("home_score")) is None or value(row.get("away_score")) is None:
                continue
            ids.add(row.get("game_id"))
    return ids


def active_roster(file):
    players = {}
    with file.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            pos = position(row.get("position"))
            pid = row.get("gsis_id") or row.get("player_id") or ""
            if pos not in CURRENT_METRICS or not pid.startswith("00-"):
                continue
            name = row.get("full_name") or row.get("player_name") or ""
            if not name:
                continue
            players[pid] = {
                "id": pid, "name": name, "position": pos,
                "team": team(row.get("team")), "espnId": str(row.get("espn_id") or ""),
            }
    return players


def normal_cdf(z):
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def calibration(rows, min_history=MIN_PAST):
    by_player = defaultdict(list)
    errors = defaultdict(list)
    holdouts = defaultdict(list)
    for row in rows:
        history = by_player[row["id"]]
        for metric in CURRENT_METRICS[row["position"]]:
            actual = get_stat(row, metric)
            if actual is None or len(history) < min_history or row["season"] not in (2024, 2025):
                continue
            proposed = signal(history, metric, row["opponent"], row["season"])
            if proposed:
                sample = (actual - proposed["forecast"], actual,
                          proposed["forecast"], proposed["season"]["value"],
                          proposed["career"]["value"])
                (errors if row["season"] == 2024 else holdouts)[(row["position"], metric)].append(sample)
        history.append(row)
    params, reports = {}, {}
    for pos, metrics in CURRENT_METRICS.items():
        for metric in metrics:
            key = pos + "_" + metric
            train = errors[(pos, metric)]
            test = holdouts[(pos, metric)]
            if len(train) < 60:
                continue
            residual = [x[0] for x in train]
            bias = statistics.mean(residual)
            centered = [v - bias for v in residual]
            sigma = max(2.0, quantile([abs(v) for v in centered], .8) / Z_80)
            params[key] = {"bias": round(bias, 4), "sigma": round(sigma, 4),
                           "calibrationN": len(train), "year": 2024}
            coverage = [abs(actual - (prediction + bias)) <= Z_80 * sigma
                        for _, actual, prediction, _, _ in test]
            bins = []
            for name, i in (("season", 3), ("career", 4)):
                pred = [(normal_cdf((row[2] + bias - row[i]) / sigma),
                         1 if row[1] > row[i] else 0)
                        for row in test if row[i] is not None]
                brier = sum((p - y)**2 for p, y in pred) / len(pred) if pred else None
                bins.append((name, round(brier, 4) if brier is not None else None))
            reports[key] = {
                "validationN": len(train), "holdoutN": len(test),
                "holdout2025Coverage80": round(sum(coverage) / len(coverage), 4) if coverage else None,
                "brierAboveAverage": dict(bins),
            }
    return params, reports


def build(input_dir, output, season, today=None):
    global CURRENT_SEASON
    CURRENT_SEASON = season
    expected = range(1999, season + 1)
    missing = [yr for yr in expected if not (input_dir / f"stats_{yr}.csv").exists()]
    if missing:
        raise ValueError(f"Career history would be incomplete; refusing to label career averages: {missing}")
    roster = active_roster(input_dir / f"roster_{season}.csv")
    complete = completed_schedule(input_dir / "games.csv", season)
    all_rows, existing = [], set()
    for year in expected:
        for row in read_rows(input_dir / f"stats_{year}.csv", year, complete if year == season else None):
            identity = (row["id"], row["gameId"])
            if identity in existing:
                raise ValueError(f"Duplicate player-game {identity}")
            existing.add(identity)
            all_rows.append(row)
    all_rows.sort(key=lambda r: (r["season"], r["week"], r["gameId"], r["id"]))
    params, reports = calibration(all_rows)
    by_player = defaultdict(list)
    for row in all_rows:
        by_player[row["id"]].append(row)
    # A player with a verified current-season appearance must be represented
    # even when the seasonal roster source has an incomplete status record.
    for row in all_rows:
        if row["season"] == season and row["id"] not in roster:
            roster[row["id"]] = {k: row[k] for k in ("id", "name", "team", "position")}
    for pid, item in roster.items():
        games = by_player.get(pid, [])
        if games:
            last = games[-1]
            # Roster position is authoritative; old historic rows may differ.
            item["historyFrom"] = games[0]["season"]
            item["historyThrough"] = last["season"]
        item["metrics"] = {}
        for metric in CURRENT_METRICS[item["position"]]:
            series = [g for g in games if metric in g["values"]]
            # Before the next game, include all verified appearances so far.
            observed = [get_stat(g, metric) for g in series if get_stat(g, metric) is not None]
            if not observed:
                item["metrics"][metric] = {"career": {"n": 0, "value": None},
                    "season": {"n": 0, "value": None}, "last5": {"n": 0, "value": None},
                    "opponents": {}}
                continue
            lastseason = [v for g in series if g["season"] == season
                          for v in [get_stat(g, metric)] if v is not None]
            prior = [v for g in series if g["season"] < season
                     for v in [get_stat(g, metric)] if v is not None]
            h2h = {}
            for code in set(g["opponent"] for g in series if g["opponent"]):
                signal_stat = signal(series, metric, code, season)
                if signal_stat and signal_stat["h2h"]["raw"]["n"]:
                    h2h[code] = signal_stat["h2h"]
            item["metrics"][metric] = {
                "career": summarize(observed), "priorCareer": summarize(prior),
                "season": summarize(lastseason), "last5": summarize(observed[-5:]),
                "opponents": h2h, "calibrationKey": item["position"] + "_" + metric,
            }
    output_data = {
        "ok": True, "schemaVersion": 1, "season": season,
        "generatedAt": (today or datetime.now(timezone.utc)).isoformat(),
        "through": max((r["season"] * 100 + r["week"] for r in all_rows if r["season"] == season), default=None),
        "careerFrom": 1999, "careerThrough": season,
        "scope": "Verified regular-season published player appearances only. Not a count of games played or starts.",
        "model": {"version": "yardage-opponent-form-v1", "status": "experimental",
                  "baselineSeasonPriorGames": 6, "recentWeight": .45,
                  "recentPriorGames": 5, "opponentWeight": .35,
                  "opponentPriorGames": 3, "h2hHalfLifeSeasons": 3,
                  "interval": .8, "calibrationYear": 2024, "holdoutYear": 2025,
                  "calibration": params, "holdout": reports},
        "players": roster,
        "sources": ["nflverse stats_player_week_1999 through stats_player_week_" + str(season),
                    "nflverse rosters roster_" + str(season),
                    "nflverse completed game schedule"],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(output_data, separators=(",", ":"), allow_nan=False), encoding="utf-8")
    print(json.dumps({"players": len(roster), "playersWithHistory": sum(bool(by_player.get(p)) for p in roster),
        "verifiedCurrentGames": len(complete), "metricsValidated": len(params),
        "outputBytes": output.stat().st_size, "holdout": reports}, indent=2))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input-dir", type=Path, default=Path(".yardage-inputs"))
    p.add_argument("--out", type=Path, default=Path("data/player-yardage-outlook.json"))
    p.add_argument("--season", required=True, type=int)
    args = p.parse_args()
    build(args.input_dir, args.out, args.season)


if __name__ == "__main__":
    main()
