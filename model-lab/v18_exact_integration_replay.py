#!/usr/bin/env python3
"""GRIDIRON PULSE v1.8 exact-integration replay.

This is a no-lookahead replay of the deployed integration logic:

1. Reconstruct the core Season Worker team projection from historical play-by-play
   using the same standing rating, Power Pulse heat formula, current-season weight,
   home-field win probability, and 2,000 deterministic remaining-game simulations.
2. Run the v1.7.0 History Worker comparable engine with the same schedule correction,
   comparable weights, similarity/dispersion blend, organizational context guardrail,
   and per-games-played adjustment cap.
3. Run the winning v1.8-B turnover rules through that same integration path:
      Week 4: net turnover sequence value weight 0.45
      Week 8: net turnover value weight 0.12 + turnover-neutralized margin features
      Week 12: turnover predictive influence off (identical to v1.7)

Historical injury/availability, exact preseason transaction adjustments, and exact
snap-weighted current-roster continuity snapshots do not exist for every held-out
checkpoint. They are held neutral in BOTH versions, so the replay isolates the
incremental turnover integration without leaking future information.
"""
from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from v18_turnover_features import build_turnover_checkpoints, load_history

COMPS = 40
SEASON_GAMES = 17
SIMULATIONS = 2000
CHECKPOINTS = (4, 8, 12)
RECENT_START = 2022
FORM_HISTORY_GAMES = 3

SCHEDULE_PRIOR_GAMES = 3.5
SCHEDULE_MARGIN_SCALE = 18.0
SCHEDULE_PRIOR_SHRINK = 0.82
SCHEDULE_STRONG_THRESHOLD = 0.58
SCHEDULE_ELITE_THRESHOLD = 0.65
SCHEDULE_WEAK_THRESHOLD = 0.42
SCHEDULE_HOME_WIN_EDGE = 0.04

HISTORY_INFLUENCE_CURVE = {
    1: 0.22, 2: 0.40, 3: 0.56, 4: 0.66, 5: 0.58, 6: 0.48,
    7: 0.39, 8: 0.30, 9: 0.25, 10: 0.20, 11: 0.16, 12: 0.13,
    13: 0.10, 14: 0.07, 15: 0.05, 16: 0.03, 17: 0.0,
}
HISTORY_ADJUSTMENT_CAP = {
    1: 0.45, 2: 0.75, 3: 1.10, 4: 1.50, 5: 1.40, 6: 1.25,
    7: 1.10, 8: 0.95, 9: 0.80, 10: 0.70, 11: 0.60, 12: 0.50,
    13: 0.40, 14: 0.30, 15: 0.22, 16: 0.15, 17: 0.0,
}

V17_WEIGHTS: Dict[str, float] = {
    "winPct": 1.30,
    "margin": 1.25,
    "ppg": 0.80,
    "papg": 0.80,
    "pythWinPct": 1.20,
    "winLuck": 1.00,
    "closeGamePct": 0.50,
    "closeWinPct": 0.60,
    "blowoutWinPct": 0.50,
    "last3Margin": 0.90,
    "momentum": 0.40,
    "offConsistency": 0.30,
    "defConsistency": 0.30,
    "offensePulse": 0.80,
    "defensePulse": 0.80,
    "tandemPulse": 1.10,
    "oppQuality": 0.35,
    "scheduleStrength": 0.25,
    "scheduleAdjustedMargin": 0.35,
    "qbContinuity": 0.50,
    "coachContinuity": 0.15,
    "coachImpact": 0.35,
}

ALIASES = {
    "JAC": "JAX",
    "LAR": "LA",
    "STL": "LA",
    "OAK": "LV",
    "SD": "LAC",
    "WSH": "WAS",
}

ESPN_IDS = {
    "ATL": "1", "BUF": "2", "CHI": "3", "CIN": "4", "CLE": "5", "DAL": "6",
    "DEN": "7", "DET": "8", "GB": "9", "TEN": "10", "IND": "11", "KC": "12",
    "LV": "13", "LA": "14", "MIA": "15", "MIN": "16", "NE": "17", "NO": "18",
    "NYG": "19", "NYJ": "20", "PHI": "21", "ARI": "22", "PIT": "23", "LAC": "24",
    "SF": "25", "SEA": "26", "TB": "27", "WAS": "28", "CAR": "29", "JAX": "30",
    "BAL": "33", "HOU": "34",
}

PBP_COLUMNS = [
    "game_id", "season", "season_type", "week", "play_id",
    "home_team", "away_team", "total_home_score", "total_away_score",
]


def canon(value: object) -> str:
    if value is None:
        return ""
    try:
        if isinstance(value, float) and math.isnan(value):
            return ""
    except TypeError:
        pass
    text = str(value).strip().upper()
    return ALIASES.get(text, text)


def cname(value: object) -> str:
    text = str(value or "").lower()
    for suffix in ("jr", "sr", "ii", "iii", "iv"):
        text = text.replace(f" {suffix} ", " ")
        if text.endswith(f" {suffix}"):
            text = text[: -(len(suffix) + 1)]
    return "".join(ch for ch in text if ch.isalnum())


def clamp(value: float, low: float, high: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = 0.0
    if not math.isfinite(number):
        number = 0.0
    return max(low, min(high, number))


def scale(value: float, low: float, high: float, out_low: float, out_high: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return out_low
    if not math.isfinite(number) or high == low:
        return out_low
    ratio = clamp((number - low) / (high - low), 0.0, 1.0)
    return out_low + ratio * (out_high - out_low)


def r1(value: float) -> float:
    return round(float(value) * 10.0) / 10.0


def avg(values: Iterable[float]) -> float:
    numbers = [float(v) for v in values if v is not None and math.isfinite(float(v))]
    return sum(numbers) / len(numbers) if numbers else 0.0


def sd(values: Iterable[float], fallback: float = 0.0) -> float:
    numbers = [float(v) for v in values if v is not None and math.isfinite(float(v))]
    if len(numbers) < 2:
        return fallback
    mean = avg(numbers)
    return math.sqrt(avg([(v - mean) ** 2 for v in numbers]))


def weighted_average(values: Sequence[float], weights: Sequence[float]) -> float:
    pairs = [
        (float(v), float(w))
        for v, w in zip(values, weights)
        if math.isfinite(float(v)) and math.isfinite(float(w)) and float(w) > 0
    ]
    total = sum(w for _, w in pairs)
    return sum(v * w for v, w in pairs) / total if total > 0 else 0.0


def weighted_quantile(items: Sequence[Tuple[float, float]], probability: float) -> float:
    rows = sorted(
        [(float(value), float(weight)) for value, weight in items if math.isfinite(value) and math.isfinite(weight)],
        key=lambda item: item[0],
    )
    total = sum(weight for _, weight in rows)
    if not rows or total <= 0:
        return 0.0
    target = clamp(probability, 0.0, 1.0) * total
    cumulative = 0.0
    for value, weight in rows:
        cumulative += weight
        if cumulative >= target:
            return value
    return rows[-1][0]


def js_imul_mod(a: int, b: int) -> int:
    return (int(a) * int(b)) & 0xFFFFFFFF


def seed_from_text(text: str) -> int:
    seed = 2166136261
    for ch in str(text):
        seed ^= ord(ch)
        seed = js_imul_mod(seed, 16777619)
    return seed & 0xFFFFFFFF or 1


def next_random(seed: int) -> Tuple[int, float]:
    value = seed & 0xFFFFFFFF
    value ^= (value << 13) & 0xFFFFFFFF
    value &= 0xFFFFFFFF
    value ^= (value >> 17) & 0xFFFFFFFF
    value &= 0xFFFFFFFF
    value ^= (value << 5) & 0xFFFFFFFF
    value &= 0xFFFFFFFF
    return (value or 1), value / 4294967296.0


@dataclass
class Standing:
    team: str
    wins: int = 0
    losses: int = 0
    ties: int = 0
    points_for: int = 0
    points_against: int = 0

    @property
    def games(self) -> int:
        return self.wins + self.losses + self.ties

    @property
    def win_pct(self) -> float:
        return (self.wins + 0.5 * self.ties) / self.games if self.games else 0.5


class SeasonGameStore:
    def __init__(self, cache_dir: Path):
        self.cache_dir = cache_dir
        self._cache: Dict[int, pd.DataFrame] = {}

    def load(self, season: int) -> pd.DataFrame:
        if season in self._cache:
            return self._cache[season]
        path = self.cache_dir / f"play_by_play_{season}.parquet"
        if not path.exists():
            raise FileNotFoundError(f"Missing cached PBP file: {path}")
        parquet = pq.ParquetFile(path)
        available = set(parquet.schema.names)
        columns = [column for column in PBP_COLUMNS if column in available]
        frame = parquet.read(columns=columns).to_pandas()
        for column in PBP_COLUMNS:
            if column not in frame.columns:
                frame[column] = np.nan
        if "season_type" in available:
            frame = frame[frame["season_type"].fillna("REG").astype(str).str.upper().eq("REG")]
        frame["week"] = pd.to_numeric(frame["week"], errors="coerce").fillna(0).astype(int)
        frame["play_id"] = pd.to_numeric(frame["play_id"], errors="coerce").fillna(-1)
        frame = frame.sort_values(["game_id", "play_id"])

        games: List[dict] = []
        for game_id, group in frame.groupby("game_id", sort=False):
            group = group.sort_values("play_id")
            home_values = group["home_team"].dropna().astype(str)
            away_values = group["away_team"].dropna().astype(str)
            if home_values.empty or away_values.empty:
                continue
            home = canon(home_values.iloc[0])
            away = canon(away_values.iloc[0])
            if not home or not away:
                continue
            week_values = pd.to_numeric(group["week"], errors="coerce").dropna()
            week = int(week_values.iloc[0]) if len(week_values) else 0
            home_scores = pd.to_numeric(group["total_home_score"], errors="coerce").dropna()
            away_scores = pd.to_numeric(group["total_away_score"], errors="coerce").dropna()
            if home_scores.empty or away_scores.empty:
                continue
            home_score = int(home_scores.iloc[-1])
            away_score = int(away_scores.iloc[-1])
            games.append(
                {
                    "gameId": str(game_id),
                    "season": int(season),
                    "week": week,
                    "home": home,
                    "away": away,
                    "homeScore": home_score,
                    "awayScore": away_score,
                }
            )
        output = pd.DataFrame(games).sort_values(["week", "gameId"]).reset_index(drop=True)
        self._cache[season] = output
        return output


def teams_in_season(games: pd.DataFrame) -> List[str]:
    return sorted(set(games["home"].map(canon)) | set(games["away"].map(canon)))


def standings_from_games(games: pd.DataFrame, max_week: Optional[int] = None) -> Dict[str, Standing]:
    subset = games if max_week is None else games[games["week"] <= int(max_week)]
    teams = teams_in_season(games)
    standings = {team: Standing(team=team) for team in teams}
    for game in subset.itertuples(index=False):
        home = canon(game.home)
        away = canon(game.away)
        hs = int(game.homeScore)
        aas = int(game.awayScore)
        standings.setdefault(home, Standing(team=home))
        standings.setdefault(away, Standing(team=away))
        standings[home].points_for += hs
        standings[home].points_against += aas
        standings[away].points_for += aas
        standings[away].points_against += hs
        if hs > aas:
            standings[home].wins += 1
            standings[away].losses += 1
        elif hs < aas:
            standings[away].wins += 1
            standings[home].losses += 1
        else:
            standings[home].ties += 1
            standings[away].ties += 1
    return standings


def standing_rating(standing: Standing) -> float:
    if not standing.games:
        return 50.0
    point_diff = (standing.points_for - standing.points_against) / standing.games
    raw = 50.0 + (standing.win_pct - 0.5) * 34.0 + clamp(point_diff, -13.0, 13.0) * 1.05
    return clamp(50.0 + (raw - 50.0) * 0.62, 32.0, 70.0)


def current_season_weight(games_played: int) -> float:
    games = float(games_played or 0)
    if games <= 0:
        return 0.0
    if games <= 4:
        return (games / 4.0) * 0.4
    if games <= 8:
        return 0.4 + ((games - 4.0) / 4.0) * 0.3
    return clamp(0.7 + ((games - 8.0) / 9.0) * 0.2, 0.7, 0.9)


def team_side_games(games: pd.DataFrame, team: str, max_week: int) -> List[dict]:
    team = canon(team)
    rows: List[dict] = []
    for game in games[games["week"] <= int(max_week)].itertuples(index=False):
        if canon(game.home) == team:
            pf, pa, opponent, home = int(game.homeScore), int(game.awayScore), canon(game.away), True
        elif canon(game.away) == team:
            pf, pa, opponent, home = int(game.awayScore), int(game.homeScore), canon(game.home), False
        else:
            continue
        margin = pf - pa
        rows.append(
            {
                "id": str(game.gameId),
                "week": int(game.week),
                "home": home,
                "opponent": opponent,
                "pointsFor": pf,
                "pointsAllowed": pa,
                "margin": margin,
                "result": 1.0 if margin > 0 else 0.0 if margin < 0 else 0.5,
            }
        )
    rows.sort(key=lambda row: (row["week"], row["id"]))
    return rows


def team_heat_score(
    team: str,
    season_games: pd.DataFrame,
    current_standings: Mapping[str, Standing],
    checkpoint_week: int,
) -> float:
    recent = list(reversed(team_side_games(season_games, team, checkpoint_week)))[:FORM_HISTORY_GAMES]
    if not recent:
        return 50.0
    weights = [max(1, FORM_HISTORY_GAMES - index) for index in range(len(recent))]
    results = [row["result"] for row in recent]
    margins = [float(row["margin"]) for row in recent]
    points_for = weighted_average([row["pointsFor"] for row in recent], weights)
    points_allowed = weighted_average([row["pointsAllowed"] for row in recent], weights)
    weighted_win_rate = weighted_average(results, weights)
    average_margin = weighted_average(margins, weights)
    older_margin = avg(margins[1:]) if len(margins) > 1 else (margins[0] if margins else 0.0)
    momentum = (margins[0] if margins else 0.0) - older_margin
    opponent_quality_values = [
        current_standings.get(row["opponent"], Standing(row["opponent"])).win_pct
        for row in recent
    ]
    opponent_quality = avg(opponent_quality_values) if opponent_quality_values else 0.5
    components = {
        "results": weighted_win_rate * 32.0,
        "margin": scale(average_margin, -21.0, 21.0, 0.0, 24.0),
        "offense": scale(points_for, 10.0, 38.0, 0.0, 16.0),
        "defense": scale(-points_allowed, -38.0, -10.0, 0.0, 16.0),
        "momentum": scale(momentum, -21.0, 21.0, 0.0, 7.0),
        "opponentQuality": scale(opponent_quality, 0.25, 0.75, 0.0, 5.0),
    }
    return float(round(clamp(sum(components.values()), 0.0, 100.0)))


def win_probability(team_rating: float, opponent_rating: float, home: bool) -> float:
    difference = float(team_rating) - float(opponent_rating) + (2.0 if home else 0.0)
    return clamp(1.0 / (1.0 + math.exp(-difference / 10.5)), 0.16, 0.84)


def standings_signature(standings: Mapping[str, Standing]) -> str:
    rows = []
    for team, standing in standings.items():
        team_id = ESPN_IDS.get(canon(team), canon(team))
        rows.append(
            (
                str(team_id),
                f"{team_id}:{standing.wins}-{standing.losses}-{standing.ties}:"
                f"{standing.points_for}-{standing.points_against}",
            )
        )
    rows.sort(key=lambda item: item[0])
    return "|".join(text for _, text in rows)


def simulate_mean_wins(
    ratings: Mapping[str, float],
    current: Mapping[str, Standing],
    remaining_games: pd.DataFrame,
    season: int,
    simulations: int = SIMULATIONS,
) -> Dict[str, float]:
    teams = sorted(ratings.keys(), key=lambda team: ESPN_IDS.get(team, team))
    wins_sum = {team: 0.0 for team in teams}
    seed = seed_from_text(f"{season}:{standings_signature(current)}")
    ordered_games = remaining_games.sort_values(["week", "gameId"])

    game_probs: List[Tuple[str, str, float]] = []
    for game in ordered_games.itertuples(index=False):
        home = canon(game.home)
        away = canon(game.away)
        if home not in ratings or away not in ratings:
            continue
        game_probs.append((home, away, win_probability(ratings[home], ratings[away], True)))

    for _ in range(int(simulations)):
        wins = {
            team: float(current.get(team, Standing(team)).wins)
            + 0.5 * float(current.get(team, Standing(team)).ties)
            for team in teams
        }
        for _team in teams:
            seed, _ = next_random(seed)
        for home, away, home_probability in game_probs:
            seed, value = next_random(seed)
            if value <= home_probability:
                wins[home] += 1.0
            else:
                wins[away] += 1.0
        for team in teams:
            wins_sum[team] += wins[team]

    return {team: wins_sum[team] / simulations for team in teams}


def season_worker_base(
    season: int,
    checkpoint_week: int,
    game_store: SeasonGameStore,
) -> Dict[str, float]:
    games = game_store.load(season)
    previous_games = game_store.load(season - 1)
    teams = teams_in_season(games)
    previous = standings_from_games(previous_games)
    current = standings_from_games(games, checkpoint_week)

    ratings: Dict[str, float] = {}
    for team in teams:
        previous_standing = previous.get(team, Standing(team))
        current_standing = current.get(team, Standing(team))
        prior_rating = standing_rating(previous_standing)
        current_rating = standing_rating(current_standing)
        heat = team_heat_score(team, games, current, checkpoint_week) if current_standing.games else 50.0
        form_rating = current_rating + (heat - 50.0) * 0.16 if current_standing.games else current_rating
        current_weight = current_season_weight(current_standing.games)
        rating = r1(clamp(prior_rating * (1.0 - current_weight) + form_rating * current_weight, 24.0, 82.0))
        ratings[team] = rating

    remaining = games[games["week"] > int(checkpoint_week)].copy()
    simulated = simulate_mean_wins(ratings, current, remaining, season, SIMULATIONS)
    team_game_counts = pd.concat([games["home"], games["away"]], ignore_index=True).value_counts() if len(games) else pd.Series(dtype=float)
    season_game_count = int(team_game_counts.max()) if len(team_game_counts) else SEASON_GAMES
    normalization = SEASON_GAMES / max(1.0, float(season_game_count))
    return {team: r1(simulated.get(team, 8.5) * normalization) for team in teams}


def projection_strength(projected_wins_eq17: float) -> float:
    wins = clamp(projected_wins_eq17, 0.0, SEASON_GAMES)
    raw = clamp(wins / SEASON_GAMES, 0.15, 0.85)
    return clamp(0.5 + (raw - 0.5) * SCHEDULE_PRIOR_SHRINK, 0.28, 0.72)


def pulses(points_for: Sequence[float], points_allowed: Sequence[float]) -> Tuple[float, float, float, float]:
    off = clamp((avg(points_for) - 14.0) / 20.0, 0.0, 1.0)
    defense_norm = clamp((34.0 - avg(points_allowed)) / 20.0, 0.0, 1.0)
    offense = 100.0 * (0.82 * off + 0.18 * clamp(1.0 - sd(points_for, 10.0) / 18.0, 0.0, 1.0))
    defense = 100.0 * (0.82 * defense_norm + 0.18 * clamp(1.0 - sd(points_allowed, 10.0) / 18.0, 0.0, 1.0))
    comp_pct = avg([1.0 if p >= 24 and float(points_allowed[i]) <= 20 else 0.0 for i, p in enumerate(points_for)])
    balance = 1.0 - abs(offense - defense) / 100.0
    tandem = clamp(0.45 * min(offense, defense) + 25.0 * balance + 30.0 * comp_pct, 0.0, 100.0)
    return offense, defense, tandem, comp_pct


def historical_opponent_quality_without_own_result(row: Mapping[str, float]) -> float:
    games = max(0.0, float(row.get("games", 0.0)))
    raw = float(row.get("rawOpponentQuality", row.get("oppQuality", 0.5)))
    if games <= 1:
        return 0.5
    direct_opponent_result = 1.0 - clamp(float(row.get("winPct", 0.5)), 0.0, 1.0)
    return clamp((games * raw - direct_opponent_result) / (games - 1.0), 0.1, 0.9)


def historical_schedule_strength(row: Mapping[str, float]) -> float:
    games = max(0.0, float(row.get("games", 0.0)))
    evidence = games / (games + SCHEDULE_PRIOR_GAMES)
    return clamp(0.5 + (float(row.get("oppQuality", 0.5)) - 0.5) * evidence, 0.2, 0.8)


def opponent_strength_profile(opponent_feature: Optional[dict], excluded_game_id: str, prior_strength: float) -> dict:
    other_games = [
        game for game in (opponent_feature or {}).get("recentGames", [])
        if str(game.get("id")) != str(excluded_game_id)
    ]
    games = len(other_games)
    prior = clamp(prior_strength, 0.2, 0.8)
    if not games:
        return {
            "games": 0, "evidence": 0.0, "observedStrength": 0.5,
            "comparableStrength": 0.5, "priorStrength": prior, "liveStrength": prior,
        }
    wins = sum(float(game["result"]) for game in other_games)
    total_for = sum(float(game["pointsFor"]) for game in other_games)
    total_allowed = sum(float(game["pointsAllowed"]) for game in other_games)
    win_pct = wins / games
    pyth = (
        total_for ** 2.37 / (total_for ** 2.37 + total_allowed ** 2.37)
        if total_for + total_allowed > 0 else 0.5
    )
    margin = avg([float(game["margin"]) for game in other_games])
    margin_strength = scale(margin, -14.0, 14.0, 0.18, 0.82)
    observed = clamp(0.42 * win_pct + 0.38 * pyth + 0.20 * margin_strength, 0.12, 0.88)
    evidence = games / (games + SCHEDULE_PRIOR_GAMES)
    comparable = clamp(0.5 + (observed - 0.5) * evidence, 0.2, 0.8)
    live = clamp(prior * (1.0 - evidence) + observed * evidence, 0.2, 0.8)
    return {
        "games": games,
        "evidence": evidence,
        "observedStrength": observed,
        "comparableStrength": comparable,
        "priorStrength": prior,
        "liveStrength": live,
    }


def schedule_expected_win_pct(team_prior: float, opponent_strength: float, home: bool) -> float:
    neutral = 1.0 / (1.0 + math.exp(-(float(team_prior) - float(opponent_strength)) * 6.0))
    return clamp(neutral + (SCHEDULE_HOME_WIN_EDGE if home else -SCHEDULE_HOME_WIN_EDGE), 0.08, 0.92)


def apply_schedule_context(features: Dict[str, dict], prior_strengths: Mapping[str, float]) -> None:
    profile_cache: Dict[Tuple[str, str], dict] = {}
    for target, feature in features.items():
        target_prior = float(prior_strengths.get(target, 0.5))
        game_profiles: List[dict] = []
        for game in feature.get("recentGames", []):
            opponent = canon(game.get("opponent"))
            cache_key = (opponent, str(game.get("id")))
            profile = profile_cache.get(cache_key)
            if profile is None:
                profile = opponent_strength_profile(
                    features.get(opponent),
                    str(game.get("id")),
                    float(prior_strengths.get(opponent, 0.5)),
                )
                profile_cache[cache_key] = profile
            comparable_adjusted_margin = float(game["margin"]) + (profile["comparableStrength"] - 0.5) * SCHEDULE_MARGIN_SCALE
            live_adjusted_margin = float(game["margin"]) + (profile["liveStrength"] - 0.5) * SCHEDULE_MARGIN_SCALE
            expected_win = schedule_expected_win_pct(target_prior, profile["liveStrength"], bool(game["home"]))
            game_profiles.append(
                {
                    "strength": profile["liveStrength"],
                    "comparableStrength": profile["comparableStrength"],
                    "observedStrength": profile["observedStrength"],
                    "priorStrength": profile["priorStrength"],
                    "evidence": profile["evidence"],
                    "result": float(game["result"]),
                    "scheduleAdjustedMargin": comparable_adjusted_margin,
                    "liveScheduleAdjustedMargin": live_adjusted_margin,
                    "resultOverExpectation": float(game["result"]) - expected_win,
                }
            )
        total = len(game_profiles)
        strong = [x for x in game_profiles if x["strength"] >= SCHEDULE_STRONG_THRESHOLD]
        weak = [x for x in game_profiles if x["strength"] <= SCHEDULE_WEAK_THRESHOLD]
        feature["oppQuality"] = avg([x["comparableStrength"] for x in game_profiles]) if total else 0.5
        feature["scheduleStrength"] = feature["oppQuality"]
        feature["liveScheduleStrength"] = avg([x["strength"] for x in game_profiles]) if total else 0.5
        feature["observedScheduleStrength"] = avg([x["observedStrength"] for x in game_profiles]) if total else 0.5
        feature["schedulePriorStrength"] = avg([x["priorStrength"] for x in game_profiles]) if total else 0.5
        feature["scheduleEvidence"] = avg([x["evidence"] for x in game_profiles]) if total else 0.0
        feature["scheduleAdjustedMargin"] = avg([x["scheduleAdjustedMargin"] for x in game_profiles]) if total else float(feature["margin"])
        feature["liveScheduleAdjustedMargin"] = avg([x["liveScheduleAdjustedMargin"] for x in game_profiles]) if total else float(feature["margin"])
        feature["qualityWinPct"] = sum(x["result"] for x in strong) / total if total else 0.0
        feature["badLossPct"] = sum(1 for x in weak if x["result"] == 0.0) / total if total else 0.0
        feature["scheduleOverExpectation"] = avg([x["resultOverExpectation"] for x in game_profiles]) if total else 0.0


def team_season_index(history: pd.DataFrame) -> Dict[Tuple[int, str], dict]:
    index: Dict[Tuple[int, str], dict] = {}
    for row in history.itertuples(index=False):
        season = int(row.season)
        team = canon(row.team)
        games = int(row.games)
        key = (season, team)
        old = index.get(key)
        if old is not None and int(old["games"]) >= games:
            continue
        index[key] = {
            "season": season,
            "team": team,
            "games": games,
            "finalWinsEq17": float(row.finalWinsEq17),
            "playoff": bool(float(row.playoff)),
            "divisionWinner": bool(float(row.divisionWinner)),
            "offensePulse": float(row.offensePulse),
            "defensePulse": float(row.defensePulse),
            "tandemPulse": float(row.tandemPulse),
        }
    return index


def coach_season_rows(history_raw: dict, team_index: Mapping[Tuple[int, str], dict]) -> List[dict]:
    rows: List[dict] = []
    for season_text, teams in (history_raw.get("primaries") or {}).items():
        season = int(season_text)
        for team_raw, primary in (teams or {}).items():
            team = canon(team_raw)
            coach = str((primary or {}).get("coach") or "")
            result = team_index.get((season, team))
            if coach and result:
                rows.append({**result, "coach": coach})
    return rows


def coach_profile_for_season(
    history_raw: dict,
    team_index: Mapping[Tuple[int, str], dict],
    coach_rows: Sequence[dict],
    coach: str,
    before_season: int,
    target_team: str,
    prior_coach: str,
) -> dict:
    coach_name = str(coach or "")
    continuity_value = 100.0 if coach_name and cname(coach_name) == cname(prior_coach) else 25.0
    if not coach_name:
        impact = 50.0
        return {"continuity": continuity_value, "impact": impact, "coachingScore": 0.25 * continuity_value + 0.75 * impact}

    seasons = sorted(
        [row for row in coach_rows if cname(row["coach"]) == cname(coach_name) and int(row["season"]) < int(before_season)],
        key=lambda row: int(row["season"]),
    )
    resume_seasons = len(seasons)
    career_wins = avg([row["finalWinsEq17"] for row in seasons]) if seasons else 8.5
    playoff_rate = avg([1.0 if row["playoff"] else 0.0 for row in seasons]) if seasons else 0.0
    division_rate = avg([1.0 if row["divisionWinner"] else 0.0 for row in seasons]) if seasons else 0.0
    win_score = scale(career_wins, 5.0, 12.5, 25.0, 95.0)
    playoff_score = scale(playoff_rate, 0.0, 0.75, 35.0, 95.0)
    division_score = scale(division_rate, 0.0, 0.55, 40.0, 95.0)
    experience_score = scale(resume_seasons, 0.0, 12.0, 40.0, 88.0)
    resume = 0.55 * win_score + 0.20 * playoff_score + 0.10 * division_score + 0.15 * experience_score if resume_seasons else 50.0

    recent = sorted(seasons, key=lambda row: int(row["season"]), reverse=True)[:3]
    recent_weights = [1.0, 0.65, 0.40]
    recent_weight = sum(recent_weights[: len(recent)])
    if recent_weight:
        recent_wins = sum(recent_weights[i] * float(row["finalWinsEq17"]) for i, row in enumerate(recent)) / recent_weight
        recent_playoffs = sum(recent_weights[i] * (1.0 if row["playoff"] else 0.0) for i, row in enumerate(recent)) / recent_weight
        recent_performance = 0.78 * scale(recent_wins, 5.0, 12.5, 25.0, 95.0) + 0.22 * scale(recent_playoffs, 0.0, 0.75, 35.0, 95.0)
    else:
        recent_performance = 50.0

    switches: List[float] = []
    for entry in seasons:
        previous_coach = str(((history_raw.get("primaries") or {}).get(str(int(entry["season"]) - 1), {}) or {}).get(entry["team"], {}).get("coach") or "")
        if cname(previous_coach) == cname(coach_name):
            continue
        previous_team = team_index.get((int(entry["season"]) - 1, canon(entry["team"])))
        if previous_team:
            switches.append(float(entry["finalWinsEq17"]) - float(previous_team["finalWinsEq17"]))
    switching_impact = scale(avg(switches), -3.0, 3.0, 25.0, 90.0) if switches else 50.0

    coach_off = avg([row["offensePulse"] for row in seasons]) if seasons else 50.0
    coach_def = avg([row["defensePulse"] for row in seasons]) if seasons else 50.0
    roster_balance = 0.0
    identity = coach_off - coach_def
    alignment = clamp(50.0 + (identity / 50.0) * (roster_balance / 50.0) * 22.0, 35.0, 72.0)
    prior_team = team_index.get((int(before_season) - 1, canon(target_team)))
    unit_similarity = (
        clamp(100.0 - (abs(coach_off - float(prior_team["offensePulse"])) + abs(coach_def - float(prior_team["defensePulse"]))) / 2.0, 35.0, 85.0)
        if prior_team else 50.0
    )
    scheme_fit = clamp(0.55 * alignment + 0.45 * unit_similarity + (10.0 if continuity_value == 100.0 else 0.0), 30.0, 90.0)
    impact = clamp(0.35 * resume + 0.30 * recent_performance + 0.20 * switching_impact + 0.15 * scheme_fit, 20.0, 100.0)
    coaching_score = clamp(0.25 * continuity_value + 0.75 * impact, 20.0, 100.0)
    return {"continuity": continuity_value, "impact": impact, "coachingScore": coaching_score}


def historical_coach_impact(
    history_raw: dict,
    team_index: Mapping[Tuple[int, str], dict],
    coach_rows: Sequence[dict],
    season: int,
    team: str,
) -> float:
    primaries = history_raw.get("primaries") or {}
    coach = str(((primaries.get(str(season), {}) or {}).get(canon(team), {}) or {}).get("coach") or "")
    prior = str(((primaries.get(str(season - 1), {}) or {}).get(canon(team), {}) or {}).get("coach") or "")
    return float(coach_profile_for_season(history_raw, team_index, coach_rows, coach, season, team, prior)["impact"])


def organizational_context_wins(coach_impact: float) -> float:
    roster = scale(62.5, 35.0, 90.0, -0.20, 0.20)
    coach = scale(coach_impact, 30.0, 85.0, -0.16, 0.16)
    unit_balance = scale(60.0, 35.0, 85.0, -0.08, 0.08)
    return clamp(roster + coach + unit_balance, -0.35, 0.35)


def build_target_features(
    season: int,
    checkpoint_week: int,
    game_store: SeasonGameStore,
    history: pd.DataFrame,
    history_raw: dict,
    team_index: Mapping[Tuple[int, str], dict],
    coach_rows: Sequence[dict],
    preseason_priors: Mapping[str, float],
    turnover_index: Mapping[Tuple[int, int, str], dict],
) -> Dict[str, dict]:
    games = game_store.load(season)
    targets = history[(history["season"] == season) & (history["week"] == checkpoint_week)]
    history_by_team = {canon(row.team): row for row in targets.itertuples(index=False)}
    features: Dict[str, dict] = {}

    for team in teams_in_season(games):
        rows = team_side_games(games, team, checkpoint_week)
        if not rows:
            continue
        pf = [float(row["pointsFor"]) for row in rows]
        pa = [float(row["pointsAllowed"]) for row in rows]
        margins = [float(row["margin"]) for row in rows]
        outcomes = [float(row["result"]) for row in rows]
        total_for, total_allowed = sum(pf), sum(pa)
        pyth = total_for ** 2.37 / (total_for ** 2.37 + total_allowed ** 2.37) if total_for + total_allowed > 0 else 0.5
        close = [row for row in rows if abs(float(row["margin"])) <= 7.0]
        recent = rows[-3:]
        margin = avg(margins)
        last3 = avg([float(row["margin"]) for row in recent])
        offense, defense, tandem, comp_pct = pulses(pf, pa)

        hrow = history_by_team.get(team)
        qb_cont = float(getattr(hrow, "qbContinuity", 50.0)) if hrow is not None else 50.0
        coach_cont = float(getattr(hrow, "coachContinuity", 50.0)) if hrow is not None else 50.0
        coach_impact = historical_coach_impact(history_raw, team_index, coach_rows, season, team)
        turnover = turnover_index.get((season, checkpoint_week, team), {})

        features[team] = {
            "team": team,
            "games": len(rows),
            "winPct": sum(outcomes) / len(rows),
            "ppg": avg(pf),
            "papg": avg(pa),
            "margin": margin,
            "pythWinPct": pyth,
            "winLuck": sum(outcomes) / len(rows) - pyth,
            "closeGamePct": len(close) / len(rows),
            "closeWinPct": sum(float(row["result"]) for row in close) / len(close) if close else 0.5,
            "blowoutWinPct": sum(1 for value in margins if value >= 10.0) / len(rows),
            "last3Margin": last3,
            "momentum": last3 - margin,
            "offConsistency": sd(pf, 10.0),
            "defConsistency": sd(pa, 10.0),
            "offensePulse": offense,
            "defensePulse": defense,
            "tandemPulse": tandem,
            "complementaryGamePct": comp_pct,
            "oppQuality": 0.5,
            "qbContinuity": qb_cont,
            "coachContinuity": coach_cont,
            "coachImpact": coach_impact,
            "recentGames": rows,
            "netTurnoverPointsPerGame": float(turnover.get("netTurnoverPointsPerGame", 0.0) or 0.0),
        }

    apply_schedule_context(features, preseason_priors)
    for feature in features.values():
        net = float(feature.get("netTurnoverPointsPerGame", 0.0))
        feature["turnoverNeutralMargin"] = float(feature["margin"]) - net
        feature["turnoverNeutralScheduleAdjustedMargin"] = float(feature["scheduleAdjustedMargin"]) - net
    return features


def prepare_history_rows(
    history: pd.DataFrame,
    history_raw: dict,
    team_index: Mapping[Tuple[int, str], dict],
    coach_rows: Sequence[dict],
    turnover_by_row: Mapping[Tuple[int, int, int, str], dict],
    games_played: int,
    current_season: int,
) -> List[dict]:
    wanted_games = sorted(set([max(1, games_played - 1), max(1, games_played), min(17, games_played + 1)]))
    subset = history[(history["games"].isin(wanted_games)) & (history["season"] < current_season)]
    rows: List[dict] = []
    for record in subset.to_dict("records"):
        record = dict(record)
        season = int(record["season"])
        week = int(record["week"])
        games = int(record["games"])
        team = canon(record["team"])
        record["team"] = team
        record["coachImpact"] = historical_coach_impact(history_raw, team_index, coach_rows, season, team)
        record["rawOpponentQuality"] = float(record.get("oppQuality", 0.5))
        record["oppQuality"] = historical_opponent_quality_without_own_result(record)
        record["scheduleStrength"] = historical_schedule_strength(record)
        record["scheduleAdjustedMargin"] = float(record["margin"]) + (float(record["scheduleStrength"]) - 0.5) * SCHEDULE_MARGIN_SCALE
        turnover = turnover_by_row.get((season, week, games, team), {})
        net = float(turnover.get("netTurnoverPointsPerGame", 0.0) or 0.0)
        record["netTurnoverPointsPerGame"] = net
        record["turnoverNeutralMargin"] = float(record["margin"]) - net
        record["turnoverNeutralScheduleAdjustedMargin"] = float(record["scheduleAdjustedMargin"]) - net
        rows.append(record)
    return rows


def integration_weights(model: str, checkpoint_week: int) -> Dict[str, float]:
    weights = dict(V17_WEIGHTS)
    if model == "v1.7.0":
        return weights
    if model != "v1.8.0-candidate":
        raise ValueError(model)
    if checkpoint_week == 4:
        weights["netTurnoverPointsPerGame"] = 0.45
    elif checkpoint_week == 8:
        weights.pop("margin", None)
        weights.pop("scheduleAdjustedMargin", None)
        weights["turnoverNeutralMargin"] = V17_WEIGHTS["margin"]
        weights["turnoverNeutralScheduleAdjustedMargin"] = V17_WEIGHTS["scheduleAdjustedMargin"]
        weights["netTurnoverPointsPerGame"] = 0.12
    return weights


def comparable_summary(target: Mapping[str, float], rows: Sequence[dict], weights: Mapping[str, float]) -> dict:
    features = [feature for feature in weights if feature in target and any(feature in row for row in rows)]
    scales: Dict[str, float] = {}
    for feature in features:
        values = []
        for row in rows:
            try:
                value = float(row.get(feature, float("nan")))
            except (TypeError, ValueError):
                value = float("nan")
            if math.isfinite(value):
                values.append(value)
        scales[feature] = sd(values, 1.0)

    nearest: List[Tuple[dict, float]] = []
    for row in rows:
        score = 0.0
        for feature in features:
            try:
                a = float(target.get(feature, float("nan")))
                b = float(row.get(feature, float("nan")))
            except (TypeError, ValueError):
                continue
            if not math.isfinite(a) or not math.isfinite(b):
                continue
            z = (a - b) / max(0.0001, float(scales.get(feature, 1.0)))
            score += float(weights[feature]) * z * z
        nearest.append((row, math.sqrt(score)))
    nearest.sort(key=lambda item: item[1])
    nearest = nearest[:COMPS]
    if not nearest:
        return {"count": 0, "meanWins": 8.5, "targetWins": 8.5, "similarity": 50.0, "outcomeSpreadWins": 6.5}
    min_distance = nearest[0][1]
    ranked = [(row, distance, math.exp(-(distance - min_distance) / 2.0)) for row, distance in nearest]
    total = sum(weight for _, _, weight in ranked) or 1.0
    weighted = lambda fn: sum(float(fn(row)) * weight for row, _, weight in ranked) / total
    wins = weighted(lambda row: row["finalWinsEq17"])
    similarity = clamp(100.0 - (sum(distance * weight for _, distance, weight in ranked) / total) * 11.0, 25.0, 98.0)
    values = [(float(row["finalWinsEq17"]), weight) for row, _, weight in ranked]
    low = weighted_quantile(values, 0.2)
    high = weighted_quantile(values, 0.8)
    spread = max(0.0, high - low)
    return {
        "count": len(ranked),
        "meanWins": r1(wins),
        "targetWins": r1(wins),
        "similarity": r1(similarity),
        "outcomeSpreadWins": r1(spread),
    }


def history_blend(games: int, comp: Mapping[str, float]) -> float:
    timing = float(HISTORY_INFLUENCE_CURVE.get(int(round(games)), 0.0))
    if not timing:
        return 0.0
    similarity_factor = scale(float(comp.get("similarity", 60.0)), 50.0, 92.0, 0.85, 1.03)
    dispersion_factor = scale(float(comp.get("outcomeSpreadWins", 6.5)), 6.5, 2.0, 0.78, 1.02)
    return clamp(timing * similarity_factor * dispersion_factor, 0.0, 0.65)


def integrated_prediction(base_mean: float, feature: Mapping[str, float], comp: Mapping[str, float]) -> Tuple[float, float, float]:
    org = organizational_context_wins(float(feature.get("coachImpact", 50.0)))
    historical_target = float(comp.get("targetWins", comp.get("meanWins", 8.5))) + org
    blend = history_blend(int(feature.get("games", 0)), comp)
    raw_delta = (historical_target - float(base_mean)) * blend
    cap = float(HISTORY_ADJUSTMENT_CAP.get(int(round(float(feature.get("games", 0)))), 0.0))
    delta = clamp(raw_delta, -cap, cap)
    mean = clamp(float(base_mean) + delta, 0.0, SEASON_GAMES)
    return mean, delta, blend


def build_turnover_indexes(turnover: pd.DataFrame) -> Tuple[Dict[Tuple[int, int, str], dict], Dict[Tuple[int, int, int, str], dict]]:
    by_week: Dict[Tuple[int, int, str], dict] = {}
    by_row: Dict[Tuple[int, int, int, str], dict] = {}
    for row in turnover.to_dict("records"):
        season = int(row["season"])
        week = int(row["week"])
        games = int(row["games"])
        team = canon(row["team"])
        by_week[(season, week, team)] = row
        by_row[(season, week, games, team)] = row
    return by_week, by_row


def run_replay(
    history_path: Path,
    sequences_path: Path,
    pbp_cache: Path,
    test_start: int,
    test_end: int,
) -> pd.DataFrame:
    history = load_history(history_path)
    history_raw = json.loads(history_path.read_text(encoding="utf-8"))
    sequences = pd.read_csv(sequences_path, low_memory=False)
    turnover = build_turnover_checkpoints(history, sequences)
    turnover_by_week, turnover_by_row = build_turnover_indexes(turnover)

    game_store = SeasonGameStore(pbp_cache)
    team_index = team_season_index(history)
    coach_rows = coach_season_rows(history_raw, team_index)

    base_cache: Dict[Tuple[int, int], Dict[str, float]] = {}
    prior_cache: Dict[int, Dict[str, float]] = {}
    history_bucket_cache: Dict[Tuple[int, int], List[dict]] = {}
    records: List[dict] = []

    for season in range(test_start, test_end + 1):
        preseason_base = base_cache.setdefault((season, 0), season_worker_base(season, 0, game_store))
        preseason_priors = prior_cache.setdefault(
            season,
            {team: projection_strength(wins) for team, wins in preseason_base.items()},
        )

        for checkpoint_week in CHECKPOINTS:
            base = base_cache.setdefault(
                (season, checkpoint_week),
                season_worker_base(season, checkpoint_week, game_store),
            )
            features = build_target_features(
                season,
                checkpoint_week,
                game_store,
                history,
                history_raw,
                team_index,
                coach_rows,
                preseason_priors,
                turnover_by_week,
            )
            target_rows = history[(history["season"] == season) & (history["week"] == checkpoint_week)]
            actual_by_team = {canon(row.team): float(row.finalWinsEq17) for row in target_rows.itertuples(index=False)}

            for team, feature in features.items():
                if team not in actual_by_team or team not in base:
                    continue
                games_played = int(feature["games"])
                bucket_key = (season, games_played)
                bucket = history_bucket_cache.setdefault(
                    bucket_key,
                    prepare_history_rows(
                        history,
                        history_raw,
                        team_index,
                        coach_rows,
                        turnover_by_row,
                        games_played,
                        season,
                    ),
                )
                if len(bucket) < COMPS:
                    continue

                actual = actual_by_team[team]
                base_mean = float(base[team])

                comp17 = comparable_summary(feature, bucket, integration_weights("v1.7.0", checkpoint_week))
                pred17, delta17, blend17 = integrated_prediction(base_mean, feature, comp17)

                comp18 = comparable_summary(feature, bucket, integration_weights("v1.8.0-candidate", checkpoint_week))
                pred18, delta18, blend18 = integrated_prediction(base_mean, feature, comp18)

                records.append(
                    {
                        "season": season,
                        "week": checkpoint_week,
                        "games": games_played,
                        "team": team,
                        "actualFinalWinsEq17": actual,
                        "seasonWorkerBase": base_mean,
                        "v17Prediction": pred17,
                        "v18Prediction": pred18,
                        "baseAbsError": abs(base_mean - actual),
                        "v17AbsError": abs(pred17 - actual),
                        "v18AbsError": abs(pred18 - actual),
                        "v17DeltaWins": delta17,
                        "v18DeltaWins": delta18,
                        "v17Blend": blend17,
                        "v18Blend": blend18,
                        "v17ComparableMean": comp17["meanWins"],
                        "v18ComparableMean": comp18["meanWins"],
                        "v17Similarity": comp17["similarity"],
                        "v18Similarity": comp18["similarity"],
                        "netTurnoverPointsPerGame": float(feature.get("netTurnoverPointsPerGame", 0.0)),
                        "rawMargin": float(feature["margin"]),
                        "turnoverNeutralMargin": float(feature["turnoverNeutralMargin"]),
                        "scheduleAdjustedMargin": float(feature["scheduleAdjustedMargin"]),
                        "turnoverNeutralScheduleAdjustedMargin": float(feature["turnoverNeutralScheduleAdjustedMargin"]),
                    }
                )
    return pd.DataFrame(records)


def summarize(results: pd.DataFrame) -> dict:
    if results.empty:
        raise RuntimeError("Exact integration replay generated no predictions")

    model_columns = {
        "season_worker_base": "baseAbsError",
        "v1.7.0_integrated": "v17AbsError",
        "v1.8.0_candidate": "v18AbsError",
    }
    ranking = []
    for model, error_column in model_columns.items():
        ranking.append(
            {
                "model": model,
                "mae": float(results[error_column].mean()),
                "recentMae": float(results.loc[results["season"] >= RECENT_START, error_column].mean()),
                "n": int(results[error_column].notna().sum()),
            }
        )
    ranking_df = pd.DataFrame(ranking).sort_values("mae").reset_index(drop=True)

    weekly_rows = []
    for week in CHECKPOINTS:
        subset = results[results["week"] == week]
        for model, error_column in model_columns.items():
            weekly_rows.append({"week": week, "model": model, "mae": float(subset[error_column].mean()), "n": int(len(subset))})
    weekly_df = pd.DataFrame(weekly_rows)

    by_season = (
        results.groupby("season", as_index=False)
        .agg(
            v17Mae=("v17AbsError", "mean"),
            v18Mae=("v18AbsError", "mean"),
            baseMae=("baseAbsError", "mean"),
            n=("team", "size"),
        )
    )
    by_season["v18DeltaVsV17"] = by_season["v18Mae"] - by_season["v17Mae"]

    overall17 = float(results["v17AbsError"].mean())
    overall18 = float(results["v18AbsError"].mean())
    recent = results[results["season"] >= RECENT_START]
    recent17 = float(recent["v17AbsError"].mean())
    recent18 = float(recent["v18AbsError"].mean())

    weekly_pivot = weekly_df.pivot(index="model", columns="week", values="mae")
    weekly_delta = {
        str(week): float(weekly_pivot.loc["v1.8.0_candidate", week] - weekly_pivot.loc["v1.7.0_integrated", week])
        for week in CHECKPOINTS
    }

    season_better = int((by_season["v18DeltaVsV17"] < -1e-12).sum())
    season_equal = int((by_season["v18DeltaVsV17"].abs() <= 1e-12).sum())
    season_worse = int((by_season["v18DeltaVsV17"] > 1e-12).sum())

    promotion = (
        overall18 <= overall17 + 1e-12
        and recent18 <= recent17 + 1e-12
        and weekly_delta["4"] <= 1e-12
        and weekly_delta["8"] <= 1e-12
        and weekly_delta["12"] <= 1e-12
        and season_better >= season_worse
    )

    return {
        "summary": {
            "testName": "GRIDIRON PULSE v1.8 exact integration replay",
            "testType": "rolling no-lookahead Season Worker core + v1.7 History Worker integration replay",
            "testSeasons": [int(results["season"].min()), int(results["season"].max())],
            "checkpoints": list(CHECKPOINTS),
            "predictionRows": int(len(results)),
            "simulationsPerCheckpoint": SIMULATIONS,
            "v17IntegratedMae": round(overall17, 6),
            "v18CandidateMae": round(overall18, 6),
            "v18DeltaVsV17": round(overall18 - overall17, 6),
            "recentV17Mae": round(recent17, 6),
            "recentV18Mae": round(recent18, 6),
            "recentDeltaVsV17": round(recent18 - recent17, 6),
            "weeklyDeltaVsV17": {week: round(value, 6) for week, value in weekly_delta.items()},
            "seasonsBetter": season_better,
            "seasonsEqual": season_equal,
            "seasonsWorse": season_worse,
            "passesPromotionScreen": bool(promotion),
            "winningTurnoverRule": {
                "week4": "netTurnoverPointsPerGame weight 0.45",
                "week8": "netTurnoverPointsPerGame weight 0.12 + turnover-neutral margin and schedule-adjusted margin",
                "week12": "turnover predictive influence off",
            },
            "noLookahead": (
                "Current standings, form, heat and turnover sequences stop at the checkpoint. "
                "Historical comparables use only prior seasons. Remaining opponents use schedule only, not future results."
            ),
            "heldNeutralInBothModels": [
                "historical point-in-time injury/availability adjustments",
                "historical point-in-time offseason transaction rating adjustments",
                "historical current-roster snap continuity contribution to organizationalContextWins",
            ],
            "interpretation": (
                "This is the exact deployed integration math for the Season Worker core and History Worker blend/caps. "
                "Unavailable historical context inputs are neutralized identically in v1.7 and v1.8 so the incremental turnover result remains no-lookahead."
            ),
        },
        "ranking": ranking_df.to_dict("records"),
        "weekly": weekly_df.to_dict("records"),
        "bySeason": by_season.to_dict("records"),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--sequences", type=Path, required=True)
    parser.add_argument("--pbp-cache", type=Path, required=True)
    parser.add_argument("--test-start", type=int, default=2014)
    parser.add_argument("--test-end", type=int, default=2025)
    parser.add_argument("--out", type=Path, default=Path("model-lab/output"))
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    results = run_replay(
        args.history,
        args.sequences,
        args.pbp_cache,
        args.test_start,
        args.test_end,
    )
    report = summarize(results)

    results.to_csv(args.out / "turnover_exact_integration_predictions.csv", index=False)
    pd.DataFrame(report["ranking"]).to_csv(args.out / "turnover_exact_integration_ranking.csv", index=False)
    pd.DataFrame(report["weekly"]).to_csv(args.out / "turnover_exact_integration_weekly.csv", index=False)
    pd.DataFrame(report["bySeason"]).to_csv(args.out / "turnover_exact_integration_by_season.csv", index=False)
    (args.out / "turnover_exact_integration_summary.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("\nGRIDIRON PULSE v1.8 EXACT INTEGRATION REPLAY")
    print(pd.DataFrame(report["ranking"]).to_string(index=False, float_format=lambda value: f"{value:.6f}"))
    print("\nWEEKLY MAE")
    print(pd.DataFrame(report["weekly"]).pivot(index="model", columns="week", values="mae").to_string(float_format=lambda value: f"{value:.6f}"))
    print("\nBY SEASON")
    print(pd.DataFrame(report["bySeason"]).to_string(index=False, float_format=lambda value: f"{value:.6f}"))
    print("\nSUMMARY")
    print(json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    main()
