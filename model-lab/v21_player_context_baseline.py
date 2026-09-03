#!/usr/bin/env python3
"""GRIDIRON PULSE v2.1 last-season player context baseline.

The model deliberately removes career-state labels from projection logic.
A player's prior regular-season rate is the starting point. Target-season role,
new team/QB/coaching context, destination scheme and schedule matchups are then
applied as bounded, auditable adjustments. Availability remains separate.

Research only. This file never changes the live Worker, site, KV or v1.9 router.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from v19_player_feature_builder import parse_history_coach_continuity
from v20_player_identity_core import (
    POSITIONS,
    first_column,
    load_csv_url,
    normalize_name,
    normalize_position,
    normalize_team,
    numeric,
    roster_url,
    safe_float,
    stats_url,
    weighted_mean,
)
from v20_player_identity_integration_replay import (
    GAMES_URL,
    current_stat_total,
    current_worker_generic_rate,
    load_depth_chart,
    load_worker_snapshot,
    preseason_depth,
    projection_value,
    season_game_limit,
    target_role_rows,
    worker_player_name,
)

MODELS = ("role_generic", "last_season", "last_season_context")
MODEL_LABELS = {
    "role_generic": "Current generic role line",
    "last_season": "Last-season player baseline",
    "last_season_context": "Last season + QB/team/coach/scheme/matchup context",
}
STARTER_ROLES = {"STARTER", "CO_STARTER"}
SEASON_WORKER_URL = "https://gridiron-pulse-season.kadescott97.workers.dev/season-outlook"


def finite(value: object, default: float = np.nan) -> float:
    return safe_float(value, default)


def clamp(value: float, low: float, high: float) -> float:
    value = finite(value, low)
    return max(low, min(high, value))


def safe_ratio(value: float, reference: float, default: float = 1.0) -> float:
    value = finite(value, np.nan)
    reference = finite(reference, np.nan)
    if not math.isfinite(value) or not math.isfinite(reference) or abs(reference) < 1e-9:
        return default
    return value / reference


def normalize_role(value: object) -> str:
    text = str(value or "").strip().upper().replace("-", "_")
    if "CO" in text and ("START" in text or "COMMITTEE" in text):
        return "CO_STARTER"
    if "START" in text or text in {"QB1", "RB1", "WR1", "TE1"}:
        return "STARTER"
    if "ROTATION" in text:
        return "ROTATIONAL"
    if "DEVELOP" in text:
        return "DEVELOPMENTAL"
    if "BACKUP" in text or text in {"QB2", "QB3"}:
        return "BACKUP"
    return "UNCERTAIN"


def load_config(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("version") != "v2.1-last-season-context-1":
        raise RuntimeError("Unexpected v2.1 configuration version")
    if payload.get("productionChanged") is not False:
        raise RuntimeError("v2.1 configuration must remain shadow-only")
    return payload


def team_contexts(seasons: pd.DataFrame) -> Dict[Tuple[int, str], dict]:
    output: Dict[Tuple[int, str], dict] = {}
    for (season, team), group in seasons.groupby(["season", "team"], sort=False):
        season = int(season)
        team = normalize_team(team)
        games = max(1.0, finite(group["games"].max(), 1.0))
        qbs = group[group["position"] == "QB"].sort_values("attempts", ascending=False)
        qb = qbs.iloc[0] if not qbs.empty else None
        skill = group[group["position"].isin(["RB", "WR", "TE"])]
        total_targets = float(pd.to_numeric(skill["targets"], errors="coerce").fillna(0.0).sum())
        shares = {}
        for position in ("RB", "WR", "TE"):
            position_targets = float(
                pd.to_numeric(group[group["position"] == position]["targets"], errors="coerce")
                .fillna(0.0)
                .sum()
            )
            shares[position] = position_targets / total_targets if total_targets > 0 else 0.0
        output[(season, team)] = {
            "teamGames": games,
            "passAttemptsPg": float(pd.to_numeric(qbs["attempts"], errors="coerce").fillna(0.0).sum()) / games,
            "qbId": str(qb["player_id"]) if qb is not None else "",
            "qbName": str(qb["player_name"]) if qb is not None else "",
            "qbRate": finite(qb["primary_pg"], np.nan) if qb is not None else np.nan,
            "qbEfficiency": finite(qb["efficiency"], np.nan) if qb is not None else np.nan,
            "positionTargetShare": shares,
        }
    return output


def player_histories(seasons: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    return {
        str(player_id): group.sort_values("season", ascending=False).copy()
        for player_id, group in seasons.groupby("player_id", sort=False)
    }


def depth_qb_map(
    depth: pd.DataFrame,
    histories: Mapping[str, pd.DataFrame],
    target_season: int,
) -> Dict[str, dict]:
    output: Dict[str, dict] = {}
    if depth.empty:
        return output
    qbs = depth[depth["depth_position"] == "QB"].sort_values(["depth_team", "depth_rank"])
    for team, group in qbs.groupby("depth_team", sort=False):
        row = group.iloc[0]
        player_id = str(row.get("player_id") or "")
        history = histories.get(player_id, pd.DataFrame())
        history = history[pd.to_numeric(history.get("season"), errors="coerce") < target_season] if not history.empty else history
        latest = history.iloc[0] if not history.empty else None
        output[normalize_team(team)] = {
            "playerId": player_id,
            "playerName": str(row.get("depth_name") or (latest["player_name"] if latest is not None else "")),
            "rate": finite(latest["primary_pg"], np.nan) if latest is not None else np.nan,
            "efficiency": finite(latest["efficiency"], np.nan) if latest is not None else np.nan,
            "source": str(row.get("depth_source") or "preseason-depth"),
        }
    return output


def weekly_defense_allowance(stats: pd.DataFrame) -> Tuple[Dict[Tuple[str, str], float], Dict[str, float]]:
    if stats.empty:
        return {}, {}
    work = stats.copy()
    season_type = first_column(work, ["season_type", "game_type"])
    if season_type:
        values = work[season_type].fillna("").astype(str).str.upper()
        work = work[values.isin(["REG", "REGULAR", "2"]) | values.eq("")].copy()
    opponent_col = first_column(work, ["opponent_team", "opponent", "opp_team", "opponent_abbr"])
    position_col = first_column(work, ["position", "position_group", "pos"])
    game_col = first_column(work, ["game_id", "gameid"])
    week_col = first_column(work, ["week", "game_week"])
    if not opponent_col or not position_col or (not game_col and not week_col):
        return {}, {}
    work["_opponent"] = work[opponent_col].map(normalize_team)
    work["_position"] = work[position_col].map(normalize_position)
    work = work[work["_opponent"].ne("") & work["_position"].isin(POSITIONS)].copy()
    work["_primary"] = 0.0
    qb = work["_position"] == "QB"
    rb = work["_position"] == "RB"
    receiver = work["_position"].isin(["WR", "TE"])
    work.loc[qb, "_primary"] = numeric(work.loc[qb], "passing_yards")
    work.loc[rb, "_primary"] = numeric(work.loc[rb], "rushing_yards") + numeric(work.loc[rb], "receiving_yards")
    work.loc[receiver, "_primary"] = numeric(work.loc[receiver], "receiving_yards")
    work["_game"] = work[game_col].astype(str) if game_col else work[week_col].astype(str)
    game_totals = work.groupby(["_opponent", "_position", "_game"], as_index=False)["_primary"].sum()
    allowance = game_totals.groupby(["_opponent", "_position"])["_primary"].mean()
    league = game_totals.groupby("_position")["_primary"].mean()
    return allowance.to_dict(), league.to_dict()


def schedule_matchups(
    games: pd.DataFrame,
    target_season: int,
    defense: Mapping[Tuple[str, str], float],
    league: Mapping[str, float],
) -> Tuple[Dict[Tuple[str, str], float], Dict[Tuple[str, str, int], dict]]:
    season_col = first_column(games, ["season"])
    week_col = first_column(games, ["week"])
    home_col = first_column(games, ["home_team", "home"])
    away_col = first_column(games, ["away_team", "away"])
    type_col = first_column(games, ["game_type", "season_type"])
    if not season_col or not week_col or not home_col or not away_col:
        return {}, {}
    work = games[pd.to_numeric(games[season_col], errors="coerce") == target_season].copy()
    if type_col:
        values = work[type_col].fillna("").astype(str).str.upper()
        work = work[values.isin(["REG", "REGULAR", "2"]) | values.eq("")].copy()
    values: Dict[Tuple[str, str], List[float]] = {}
    weekly: Dict[Tuple[str, str, int], dict] = {}
    for row in work.to_dict("records"):
        week = int(finite(row.get(week_col), 0))
        home = normalize_team(row.get(home_col))
        away = normalize_team(row.get(away_col))
        if not home or not away or week <= 0:
            continue
        for team, opponent in ((home, away), (away, home)):
            for position in POSITIONS:
                baseline = finite(league.get(position), np.nan)
                allowed = finite(defense.get((opponent, position)), baseline)
                index = safe_ratio(allowed, baseline, 1.0)
                values.setdefault((team, position), []).append(index)
                weekly[(team, position, week)] = {
                    "opponent": opponent,
                    "index": index,
                    "allowed": allowed if math.isfinite(allowed) else None,
                    "league": baseline if math.isfinite(baseline) else None,
                }
    season_index = {key: float(np.mean(items)) for key, items in values.items() if items}
    return season_index, weekly


def role_sample_weight(games: float, config: Mapping[str, object]) -> float:
    baseline = config["baseline"]
    games = finite(games, 0.0)
    if games >= finite(baseline.get("fullSampleGames"), 12.0):
        return finite(baseline.get("lastSeasonWeightFull"), 0.9)
    if games >= 8:
        return finite(baseline.get("lastSeasonWeightMedium"), 0.78)
    if games >= 4:
        return finite(baseline.get("lastSeasonWeightShort"), 0.6)
    return finite(baseline.get("lastSeasonWeightTiny"), 0.35)


def prior_season_baseline(row: Mapping[str, object], generic_rate: float, config: Mapping[str, object]) -> dict:
    latest_rate = finite(row.get("latest_rate"), generic_rate)
    latest_games = finite(row.get("latest_games"), 0.0)
    older_rate = finite(row.get("older_rate"), np.nan)
    fallback = older_rate if math.isfinite(older_rate) else generic_rate
    latest_weight = role_sample_weight(latest_games, config)
    rate = latest_weight * latest_rate + (1.0 - latest_weight) * fallback
    return {
        "rate": max(0.0, rate),
        "latestRate": latest_rate,
        "latestGames": latest_games,
        "olderFallbackRate": fallback,
        "latestWeight": latest_weight,
    }


def projected_games(
    history: pd.DataFrame,
    target_season: int,
    position: str,
    role: str,
    past: pd.DataFrame,
) -> float:
    limit = float(season_game_limit(target_season))
    if history.empty:
        return limit
    recent = history[pd.to_numeric(history["season"], errors="coerce") < target_season].sort_values("season", ascending=False).head(3)
    if recent.empty:
        return limit
    latest_games = finite(recent.iloc[0]["games"], limit)
    older = pd.to_numeric(recent.iloc[1:]["games"], errors="coerce").dropna().tolist()
    older_games = weighted_mean(older, [0.65, 0.35][: len(older)], limit) if older else limit
    cohort = past[
        (past["position"] == position)
        & (past["role_bucket"] == role)
        & (past["games"] >= 4)
    ]["games"]
    cohort_games = float(pd.to_numeric(cohort, errors="coerce").median()) if len(cohort) else limit
    if latest_games >= 15:
        result = 0.72 * latest_games + 0.18 * older_games + 0.10 * cohort_games
    elif latest_games >= 10:
        result = 0.52 * latest_games + 0.38 * older_games + 0.10 * cohort_games
    else:
        result = 0.35 * latest_games + 0.50 * older_games + 0.15 * cohort_games
    return clamp(result, 1.0, limit)


def position_scheme_value(context: Mapping[str, object], position: str) -> float:
    if position == "QB":
        return finite(context.get("passAttemptsPg"), np.nan)
    shares = context.get("positionTargetShare") if isinstance(context.get("positionTargetShare"), Mapping) else {}
    return finite(shares.get(position), np.nan)


def build_context(
    row: Mapping[str, object],
    target_season: int,
    context_map: Mapping[Tuple[int, str], Mapping[str, object]],
    target_qbs: Mapping[str, Mapping[str, object]],
    coach_map: Mapping[Tuple[int, str], float],
    season_matchup: Mapping[Tuple[str, str], float],
    weekly_matchup: Mapping[Tuple[str, str, int], Mapping[str, object]],
    config: Mapping[str, object],
    current_week: Optional[int] = None,
) -> dict:
    prior_team = normalize_team(row.get("prior_team"))
    target_team = normalize_team(row.get("target_team") or row.get("forecast_team") or prior_team)
    position = normalize_position(row.get("target_position") or row.get("position"))
    previous_context = context_map.get((target_season - 1, prior_team), {})
    destination_context = context_map.get((target_season - 1, target_team), {})
    new_team = bool(prior_team and target_team and prior_team != target_team)

    prior_qb_id = str(previous_context.get("qbId") or "")
    prior_qb_rate = finite(previous_context.get("qbRate"), np.nan)
    target_qb = target_qbs.get(target_team) or destination_context
    target_qb_id = str(target_qb.get("playerId") or target_qb.get("qbId") or "")
    target_qb_name = str(target_qb.get("playerName") or target_qb.get("qbName") or "")
    target_qb_rate = finite(target_qb.get("rate") if "rate" in target_qb else target_qb.get("qbRate"), np.nan)
    new_qb = bool(position in {"RB", "WR", "TE"} and prior_qb_id and target_qb_id and prior_qb_id != target_qb_id)
    qb_delta = safe_ratio(target_qb_rate, prior_qb_rate, 1.0) - 1.0

    prior_scheme = position_scheme_value(previous_context, position)
    destination_scheme = position_scheme_value(destination_context, position)
    scheme_delta = safe_ratio(destination_scheme, prior_scheme, 1.0) - 1.0

    manual = config.get("teamContext2026", {}).get(target_team, {}) if target_season == 2026 else {}
    continuity = finite(coach_map.get((target_season, target_team)), np.nan)
    new_head_coach = bool(manual.get("newHeadCoach")) if manual else bool(math.isfinite(continuity) and continuity < 50.0)
    new_offensive_coordinator = bool(manual.get("newOffensiveCoordinator")) if manual else new_head_coach
    offensive_continuity = str(manual.get("offensiveContinuity") or ("LOW" if new_head_coach else "UNKNOWN"))

    caps = config["contextCaps"]
    qb_coefficient = 0.18 if position in {"WR", "TE"} else 0.08 if position == "RB" else 0.0
    qb_cap = finite(caps.get("quarterbackQualityPct"), 0.06)
    qb_factor = 1.0 + clamp(qb_delta * qb_coefficient, -qb_cap, qb_cap)

    scheme_coefficient = 0.22 if position in {"WR", "TE"} else 0.14
    scheme_cap = finite(caps.get("destinationSchemePct"), 0.06)
    scheme_factor = 1.0 + clamp(scheme_delta * scheme_coefficient, -scheme_cap, scheme_cap)

    season_index = finite(season_matchup.get((target_team, position)), 1.0)
    season_cap = finite(caps.get("seasonMatchupPct"), 0.05)
    season_matchup_factor = 1.0 + clamp((season_index - 1.0) * 0.25, -season_cap, season_cap)

    next_info = weekly_matchup.get((target_team, position, int(current_week or 0)), {}) if current_week else {}
    next_index = finite(next_info.get("index"), 1.0)
    next_cap = finite(caps.get("nextMatchupPct"), 0.04)
    next_matchup_factor = 1.0 + clamp((next_index - 1.0) * 0.25, -next_cap, next_cap)

    return {
        "priorTeam": prior_team,
        "targetTeam": target_team,
        "newTeam": new_team,
        "priorQuarterbackId": prior_qb_id or None,
        "targetQuarterbackId": target_qb_id or None,
        "targetQuarterback": target_qb_name or None,
        "newQuarterback": new_qb,
        "quarterbackRateDeltaPct": qb_delta * 100.0 if math.isfinite(qb_delta) else None,
        "quarterbackFactor": qb_factor,
        "priorSchemeValue": prior_scheme if math.isfinite(prior_scheme) else None,
        "destinationSchemeValue": destination_scheme if math.isfinite(destination_scheme) else None,
        "schemeDeltaPct": scheme_delta * 100.0 if math.isfinite(scheme_delta) else None,
        "schemeFactor": scheme_factor,
        "newHeadCoach": new_head_coach,
        "newOffensiveCoordinator": new_offensive_coordinator,
        "offensiveContinuity": offensive_continuity,
        "coachContinuityScore": continuity if math.isfinite(continuity) else None,
        "coachingNote": manual.get("note") if manual else None,
        "seasonMatchupIndex": season_index,
        "seasonMatchupFactor": season_matchup_factor,
        "nextOpponent": next_info.get("opponent"),
        "nextMatchupIndex": next_index if next_info else None,
        "nextMatchupFactor": next_matchup_factor if next_info else None,
        "combinedFactor": qb_factor * scheme_factor * season_matchup_factor,
    }


def apply_row(
    row: Mapping[str, object],
    history: pd.DataFrame,
    target_season: int,
    past: pd.DataFrame,
    context: Mapping[str, object],
    config: Mapping[str, object],
) -> dict:
    position = normalize_position(row.get("target_position") or row.get("position"))
    target_role = normalize_role(row.get("target_role") or row.get("role"))
    prior_role = normalize_role(row.get("role_bucket") or row.get("prior_role"))
    ordinal = int(max(1, finite(row.get("target_room_ordinal"), row.get("role_rank") or 1)))
    generic = current_worker_generic_rate(position, target_role, ordinal)
    baseline = prior_season_baseline(row, generic, config)
    eligible = bool(
        target_role in STARTER_ROLES
        and prior_role in STARTER_ROLES
        and baseline["latestGames"] >= finite(config["baseline"].get("minimumHistoryGames"), 4.0)
    )
    weight = baseline["latestWeight"] if eligible else 0.0
    if bool(row.get("depth_verified")):
        weight = min(0.95, weight + 0.04)
    if context.get("newTeam"):
        weight = max(0.45, weight - 0.04)
    if context.get("newHeadCoach") or context.get("newOffensiveCoordinator"):
        weight = max(
            0.40,
            weight - finite(config["contextCaps"].get("coachingUncertaintyBlendPenalty"), 0.05),
        )
    role_floor = finite(config["baseline"].get("roleGenericFloorWeight"), 0.10)
    weight = min(1.0 - role_floor, weight)

    last_season_rate = weight * baseline["rate"] + (1.0 - weight) * generic if eligible else generic
    context_rate = last_season_rate * finite(context.get("combinedFactor"), 1.0) if eligible else generic
    games = projected_games(history, target_season, position, prior_role, past) if eligible else float(season_game_limit(target_season))

    output = dict(row)
    output.update(context)
    output.update(
        {
            "target_position": position,
            "target_role": target_role,
            "prior_role": prior_role,
            "role_generic_rate": generic,
            "last_year_raw_rate": baseline["rate"],
            "last_year_rate": last_season_rate,
            "last_year_context_rate": context_rate,
            "last_year_games": baseline["latestGames"],
            "last_year_reported_rate": baseline["latestRate"],
            "older_fallback_rate": baseline["olderFallbackRate"],
            "last_year_sample_weight": baseline["latestWeight"],
            "projection_blend_weight": weight,
            "context_eligible": eligible,
            "projected_games_v21": games,
            "role_generic_total": generic * season_game_limit(target_season),
            "last_season_total": last_season_rate * games,
            "last_season_context_total": context_rate * games,
            "productionChanged": False,
        }
    )
    if "actual_rate" in output:
        for model in MODELS:
            output[f"{model}_rate_error"] = finite(output[f"{model}_rate"], 0.0) - finite(output["actual_rate"], 0.0)
            output[f"{model}_total_error"] = finite(output[f"{model}_total"], 0.0) - finite(output["actual_total"], 0.0)
    return output


def summary_rows(frame: pd.DataFrame, group: Mapping[str, object]) -> List[dict]:
    if frame.empty:
        return []
    generic_rate_mae = float(np.mean(np.abs(pd.to_numeric(frame["role_generic_rate_error"], errors="coerce"))))
    generic_total_mae = float(np.mean(np.abs(pd.to_numeric(frame["role_generic_total_error"], errors="coerce"))))
    rows: List[dict] = []
    for model in MODELS:
        rate_errors = pd.to_numeric(frame[f"{model}_rate_error"], errors="coerce").dropna()
        total_errors = pd.to_numeric(frame[f"{model}_total_error"], errors="coerce").dropna()
        if rate_errors.empty or total_errors.empty:
            continue
        rate_mae = float(np.mean(np.abs(rate_errors)))
        total_mae = float(np.mean(np.abs(total_errors)))
        rows.append(
            {
                **group,
                "model": model,
                "modelLabel": MODEL_LABELS[model],
                "rows": int(len(frame)),
                "contextEligibleRows": int(frame["context_eligible"].sum()),
                "rateMae": rate_mae,
                "rateRmse": float(math.sqrt(np.mean(np.square(rate_errors)))),
                "rateBias": float(np.mean(rate_errors)),
                "rateMaeImprovementPct": 0.0 if generic_rate_mae <= 0 else (generic_rate_mae - rate_mae) / generic_rate_mae * 100.0,
                "totalMae": total_mae,
                "totalRmse": float(math.sqrt(np.mean(np.square(total_errors)))),
                "totalBias": float(np.mean(total_errors)),
                "totalMaeImprovementPct": 0.0 if generic_total_mae <= 0 else (generic_total_mae - total_mae) / generic_total_mae * 100.0,
            }
        )
    return rows


def summarize(frame: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    overall = pd.DataFrame(summary_rows(frame, {"group": "ALL"}))
    position_rows: List[dict] = []
    for position, group in frame.groupby("target_position"):
        position_rows.extend(summary_rows(group, {"position": position}))
    subset_rows: List[dict] = []
    subsets = {
        "STABLE_STARTERS": frame[frame["context_eligible"] == True],  # noqa: E712
        "CHANGED_TEAM": frame[frame["newTeam"] == True],  # noqa: E712
        "CHANGED_QUARTERBACK": frame[frame["newQuarterback"] == True],  # noqa: E712
        "CHANGED_COACH_OR_OC": frame[(frame["newHeadCoach"] == True) | (frame["newOffensiveCoordinator"] == True)],  # noqa: E712
        "SHORT_PRIOR_SEASON": frame[pd.to_numeric(frame["last_year_games"], errors="coerce") < 13],
        "DEPTH_VERIFIED": frame[frame["depth_verified"] == True],  # noqa: E712
    }
    for label, subset in subsets.items():
        subset_rows.extend(summary_rows(subset, {"subset": label}))
    return {
        "overall": overall,
        "position": pd.DataFrame(position_rows),
        "subset": pd.DataFrame(subset_rows),
    }


def gate(summaries: Mapping[str, pd.DataFrame], frame: pd.DataFrame) -> dict:
    model = "last_season_context"
    overall = summaries["overall"]
    position = summaries["position"]
    subset = summaries["subset"]

    def value(source: pd.DataFrame, mask: pd.Series, column: str, fallback: float = -999.0) -> float:
        rows = source[mask]
        return finite(rows[column].iloc[0], fallback) if not rows.empty else fallback

    overall_rate = value(overall, overall["model"] == model, "rateMaeImprovementPct")
    positions = position[position["model"] == model]
    worst_position = finite(positions["rateMaeImprovementPct"].min(), -999.0) if not positions.empty else -999.0
    starters_rate = value(
        subset,
        (subset["model"] == model) & (subset["subset"] == "STABLE_STARTERS"),
        "rateMaeImprovementPct",
    )
    starters_total = value(
        subset,
        (subset["model"] == model) & (subset["subset"] == "STABLE_STARTERS"),
        "totalMaeImprovementPct",
    )
    passed = bool(overall_rate > 0 and worst_position >= -2.0 and starters_rate >= 5.0 and starters_total > 0)
    return {
        "version": "v2.1-last-season-context-policy-1",
        "researchOnly": True,
        "productionChanged": False,
        "candidateModel": model,
        "historicalReplayPassed": passed,
        "recommendedForProductionIntegration": False,
        "requirements": {
            "overallRateMaeImprovementPctGreaterThan": 0,
            "noPositionRateRegressionWorseThanPct": -2,
            "stableStarterRateImprovementPctAtLeast": 5,
            "stableStarterTotalImprovementPctGreaterThan": 0,
        },
        "observed": {
            "overallRateMaeImprovementPct": overall_rate,
            "worstPositionRateMaeImprovementPct": worst_position,
            "stableStarterRateMaeImprovementPct": starters_rate,
            "stableStarterTotalMaeImprovementPct": starters_total,
            "contextEligibleRows": int(frame["context_eligible"].sum()),
        },
        "note": "Career-state labels are not used. News is collected separately and remains display-only until it has its own validation gate.",
    }


def historical_replay(
    source: pd.DataFrame,
    backtest: pd.DataFrame,
    games: pd.DataFrame,
    histories: Mapping[str, pd.DataFrame],
    context_map: Mapping[Tuple[int, str], Mapping[str, object]],
    coach_map: Mapping[Tuple[int, str], float],
    start: int,
    end: int,
    cache: Path,
    config: Mapping[str, object],
) -> pd.DataFrame:
    outputs: List[dict] = []
    for target_season in range(start, end + 1):
        print(f"[v2.1 context] Historical target season {target_season}")
        roster = load_csv_url(roster_url(target_season), cache / f"roster_{target_season}.csv", optional=True)
        depth = preseason_depth(load_depth_chart(target_season, cache), games, target_season)
        roles = target_role_rows(backtest, target_season, roster, depth)
        prior_stats = load_csv_url(stats_url(target_season - 1), cache / f"stats_player_week_{target_season - 1}.csv")
        defense, league = weekly_defense_allowance(prior_stats)
        season_matchup, weekly_matchup = schedule_matchups(games, target_season, defense, league)
        target_qbs = depth_qb_map(depth, histories, target_season)
        past = source[pd.to_numeric(source["season"], errors="coerce") < target_season]
        for row in roles.to_dict("records"):
            player_id = str(row.get("player_id") or "")
            history = histories.get(player_id, pd.DataFrame())
            context = build_context(
                row,
                target_season,
                context_map,
                target_qbs,
                coach_map,
                season_matchup,
                weekly_matchup,
                config,
            )
            outputs.append(apply_row(row, history, target_season, past, context, config))
    return pd.DataFrame(outputs)


def worker_room_ordinals(players: Sequence[Mapping[str, object]]) -> Dict[Tuple[str, str, str], int]:
    output: Dict[Tuple[str, str, str], int] = {}
    groups: Dict[Tuple[str, str], List[Mapping[str, object]]] = {}
    for player in players:
        team = normalize_team(player.get("team"))
        position = normalize_position(player.get("positionGroup") or player.get("position"))
        if team and position in POSITIONS:
            groups.setdefault((team, position), []).append(player)
    for (team, position), room in groups.items():
        ordered = sorted(
            room,
            key=lambda player: (
                {"STARTER": 0, "CO_STARTER": 1, "ROTATIONAL": 2, "UNCERTAIN": 3, "BACKUP": 4, "DEVELOPMENTAL": 5}.get(normalize_role(player.get("role")), 9),
                int(max(1, finite(player.get("roleRank") or player.get("depthRank"), 99))),
                worker_player_name(player),
            ),
        )
        for ordinal, player in enumerate(ordered, start=1):
            output[(normalize_name(worker_player_name(player)), team, position)] = ordinal
    return output


def current_qb_map(
    players: Sequence[Mapping[str, object]],
    forecast_by_name_position: Mapping[Tuple[str, str], Mapping[str, object]],
) -> Dict[str, dict]:
    output: Dict[str, dict] = {}
    for player in players:
        position = normalize_position(player.get("positionGroup") or player.get("position"))
        role = normalize_role(player.get("role"))
        if position != "QB" or role != "STARTER":
            continue
        name = worker_player_name(player)
        team = normalize_team(player.get("team"))
        history = forecast_by_name_position.get((normalize_name(name), "QB"), {})
        output[team] = {
            "playerId": str(player.get("athleteId") or player.get("playerKey") or player.get("id") or ""),
            "playerName": name,
            "rate": finite(history.get("latest_rate"), np.nan),
            "source": str(player.get("roleSource") or "current-worker-role"),
        }
    return output


def build_current_preview(
    forecast: pd.DataFrame,
    source: pd.DataFrame,
    games: pd.DataFrame,
    histories: Mapping[str, pd.DataFrame],
    context_map: Mapping[Tuple[int, str], Mapping[str, object]],
    coach_map: Mapping[Tuple[int, str], float],
    forecast_season: int,
    cache: Path,
    config: Mapping[str, object],
    worker_url: str,
) -> Tuple[pd.DataFrame, dict]:
    snapshot, worker_error = load_worker_snapshot(worker_url)
    players = snapshot.get("players") if isinstance(snapshot.get("players"), list) else []
    if not players:
        return pd.DataFrame(), {"workerError": worker_error or "no-worker-players", "workerPlayers": 0}

    by_identity: Dict[Tuple[str, str, str], dict] = {}
    by_name_position: Dict[Tuple[str, str], dict] = {}
    for row in forecast.to_dict("records"):
        name = normalize_name(row.get("player_name"))
        position = normalize_position(row.get("forecast_position") or row.get("position"))
        team = normalize_team(row.get("forecast_team") or row.get("prior_team"))
        if name and position:
            by_identity[(name, position, team)] = row
            by_name_position[(name, position)] = row

    prior_stats = load_csv_url(stats_url(forecast_season - 1), cache / f"stats_player_week_{forecast_season - 1}.csv")
    defense, league = weekly_defense_allowance(prior_stats)
    season_matchup, weekly_matchup = schedule_matchups(games, forecast_season, defense, league)
    current_week = int(max(1, finite(snapshot.get("seasonWeek"), 1)))
    target_qbs = current_qb_map(players, by_name_position)
    ordinals = worker_room_ordinals(players)
    past = source[pd.to_numeric(source["season"], errors="coerce") < forecast_season]

    outputs: List[dict] = []
    matches = 0
    active = 0
    for player in players:
        name = worker_player_name(player)
        position = normalize_position(player.get("positionGroup") or player.get("position"))
        team = normalize_team(player.get("team"))
        if position not in POSITIONS:
            continue
        identity = by_identity.get((normalize_name(name), position, team)) or by_name_position.get((normalize_name(name), position))
        if identity:
            matches += 1
        row = dict(identity or {})
        row.update(
            {
                "player_id": row.get("player_id") or str(player.get("athleteId") or player.get("id") or ""),
                "player_name": name,
                "position": position,
                "target_position": position,
                "target_team": team,
                "forecast_team": team,
                "target_role": normalize_role(player.get("role")),
                "prior_role": row.get("role_bucket"),
                "target_room_ordinal": ordinals.get((normalize_name(name), team, position), 1),
                "depth_verified": bool(finite((player.get("depthChart") or {}).get("sourceCount") if isinstance(player.get("depthChart"), Mapping) else 0, 0.0) > 0),
                "target_role_source": player.get("roleSource"),
            }
        )
        context = build_context(
            row,
            forecast_season,
            context_map,
            target_qbs,
            coach_map,
            season_matchup,
            weekly_matchup,
            config,
            current_week=current_week,
        )
        history = histories.get(str(row.get("player_id") or ""), pd.DataFrame())
        applied = apply_row(row, history, forecast_season, past, context, config)
        official = projection_value(player)
        metric = str(player.get("primaryMetric") or ("passingYards" if position == "QB" else "scrimmageYards" if position == "RB" else "receivingYards"))
        actual_games = finite(player.get("actualGames"), 0.0)
        current_total = current_stat_total(player, metric)
        worker_remaining = finite(player.get("teamRemainingGames"), max(0.0, 17.0 - actual_games))
        candidate_remaining = min(worker_remaining, max(0.0, finite(applied.get("projected_games_v21"), 17.0) - actual_games))
        candidate_projection = current_total + finite(applied.get("last_season_context_rate"), 0.0) * candidate_remaining
        next_rate = finite(applied.get("last_season_context_rate"), 0.0) * finite(context.get("nextMatchupFactor"), 1.0)
        applied.update(
            {
                "playerName": name,
                "team": team,
                "position": position,
                "primaryMetric": metric,
                "role": normalize_role(player.get("role")),
                "roleSource": player.get("roleSource"),
                "officialProjection": official,
                "candidateProjection": candidate_projection if applied.get("context_eligible") else official,
                "delta": candidate_projection - official if applied.get("context_eligible") and official is not None else None,
                "actualGames": actual_games,
                "candidateRemainingGames": candidate_remaining,
                "nextGameRate": next_rate if applied.get("context_eligible") else None,
                "newsSignal": None,
                "newsModifier": 1.0,
                "newsApplied": False,
                "productionChanged": False,
            }
        )
        if applied.get("context_eligible"):
            active += 1
        outputs.append(applied)

    frame = pd.DataFrame(outputs)
    if not frame.empty:
        frame = frame.sort_values(["context_eligible", "delta"], ascending=[False, False], na_position="last")
    return frame, {
        "workerError": worker_error,
        "workerPlayers": len(players),
        "lastSeasonMatches": matches,
        "contextEligiblePlayers": active,
        "seasonWeek": current_week,
        "workerVersion": snapshot.get("version"),
        "productionChanged": False,
    }


def write_frame(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, float_format="%.6f")


def write_json(payload: object, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, allow_nan=False), encoding="utf-8")


def records(frame: pd.DataFrame) -> List[dict]:
    return json.loads(frame.replace({np.nan: None}).to_json(orient="records")) if not frame.empty else []


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--backtest", type=Path, required=True)
    parser.add_argument("--forecast", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--start", type=int, default=2015)
    parser.add_argument("--end", type=int, default=2025)
    parser.add_argument("--forecast-season", type=int, default=2026)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--worker-url", default=SEASON_WORKER_URL)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    source = pd.read_csv(args.source, low_memory=False)
    backtest = pd.read_csv(args.backtest, low_memory=False)
    forecast = pd.read_csv(args.forecast, low_memory=False)
    games = load_csv_url(GAMES_URL, args.cache / "games.csv")
    histories = player_histories(source)
    context_map = team_contexts(source)
    coach_map = parse_history_coach_continuity(args.history)

    replay = historical_replay(
        source,
        backtest,
        games,
        histories,
        context_map,
        coach_map,
        args.start,
        args.end,
        args.cache,
        config,
    )
    if replay.empty:
        raise RuntimeError("v2.1 historical replay produced no rows")
    summaries = summarize(replay)
    policy = gate(summaries, replay)

    preview, preview_meta = build_current_preview(
        forecast,
        source,
        games,
        histories,
        context_map,
        coach_map,
        args.forecast_season,
        args.cache,
        config,
        args.worker_url,
    )

    args.out.mkdir(parents=True, exist_ok=True)
    write_frame(replay, args.out / "historical_replay.csv")
    write_frame(summaries["overall"], args.out / "overall_summary.csv")
    write_frame(summaries["position"], args.out / "position_summary.csv")
    write_frame(summaries["subset"], args.out / "subset_summary.csv")
    write_frame(preview, args.out / f"preview_{args.forecast_season}.csv")
    write_json(
        {
            "ok": True,
            "ready": not preview.empty,
            "version": "v2.1-last-season-context-preview-1",
            "researchOnly": True,
            "productionChanged": False,
            "model": "last-year-first",
            "careerStateUsed": False,
            "generatedAt": pd.Timestamp.utcnow().isoformat(),
            "meta": preview_meta,
            "policy": policy,
            "players": records(preview),
        },
        args.out / f"preview_{args.forecast_season}.json",
    )
    write_json(policy, args.out / "policy.json")
    write_json(
        {
            "version": "v2.1-last-season-context-run-1",
            "researchOnly": True,
            "productionChanged": False,
            "careerStateUsed": False,
            "historicalRows": int(len(replay)),
            "contextEligibleHistoricalRows": int(replay["context_eligible"].sum()),
            "forecastRows": int(len(preview)),
            "forecastEligiblePlayers": int(preview_meta.get("contextEligiblePlayers") or 0),
            "newsStatus": "collected by a separate display-only step",
            "policy": policy,
        },
        args.out / "run_summary.json",
    )

    print(json.dumps({"policy": policy, "preview": preview_meta}, indent=2))


if __name__ == "__main__":
    main()
