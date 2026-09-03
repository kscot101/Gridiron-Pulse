#!/usr/bin/env python3
"""GRIDIRON PULSE v2.0 Player Identity role-integration replay.

Replays the player-specific identity RATE inside a preseason role layer built
from target-season rosters and point-in-time depth charts. Low-confidence,
backup, developmental, and role-changed players remain on the generic role
baseline. Production is never modified by this research script.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Tuple

import numpy as np
import pandas as pd
import requests

try:
    import pyreadr
except ImportError:  # pragma: no cover
    pyreadr = None

from v20_player_identity_core import (
    BASE,
    clean_id,
    fetch_bytes,
    first_column,
    load_csv_url,
    normalize_name,
    normalize_position,
    normalize_team,
    roster_metadata,
    roster_url,
    safe_float,
)

DEPTH_URL = lambda season: f"{BASE}/depth_charts/depth_charts_{season}.rds"
GAMES_URL = "https://raw.githubusercontent.com/nflverse/nfldata/refs/heads/master/data/games.csv"
SEASON_WORKER_URL = "https://gridiron-pulse-season.kadescott97.workers.dev/season-outlook"

INTEGRATION_MODELS = (
    "role_generic",
    "identity_integrated",
    "identity_full_stable",
)

ROLE_PRIORITY = {
    "STARTER": 0,
    "CO_STARTER": 1,
    "ROTATIONAL": 2,
    "UNCERTAIN": 3,
    "BACKUP": 4,
    "DEVELOPMENTAL": 5,
}

IDENTITY_WEIGHTS = {
    "ASCENDING": 0.90,
    "DEVELOPING": 0.78,
    "ESTABLISHED": 0.90,
    "PEAK": 0.92,
    "DECLINING": 0.76,
    "RETURNING_FROM_INJURY_OR_SHORTENED": 0.90,
}


def season_game_limit(season: int) -> int:
    return 17 if season >= 2021 else 16


def load_depth_chart(season: int, cache_dir: Path) -> pd.DataFrame:
    if pyreadr is None:
        raise RuntimeError("pyreadr is required for depth-chart replay")
    path = cache_dir / f"depth_charts_{season}.rds"
    if not path.exists() or path.stat().st_size < 100:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(fetch_bytes(DEPTH_URL(season)))
    result = pyreadr.read_r(str(path))
    for value in result.values():
        if isinstance(value, pd.DataFrame):
            return value
    return pd.DataFrame()


def regular_games(frame: pd.DataFrame, season: int) -> pd.DataFrame:
    if frame.empty:
        return frame
    work = frame.copy()
    if "season" not in work.columns:
        return pd.DataFrame()
    work = work[pd.to_numeric(work["season"], errors="coerce") == season].copy()
    type_col = first_column(work, ["game_type", "season_type"])
    if type_col:
        values = work[type_col].fillna("").astype(str).str.upper()
        work = work[values.isin(["REG", "REGULAR", "2"]) | values.eq("")].copy()
    return work


def first_regular_kickoff(games: pd.DataFrame, season: int) -> Optional[pd.Timestamp]:
    work = regular_games(games, season)
    date_col = first_column(work, ["gameday", "game_date", "date"])
    if work.empty or not date_col:
        return None
    dates = pd.to_datetime(work[date_col], errors="coerce", utc=True).dropna()
    return dates.min() if not dates.empty else None


def preseason_depth(depth: pd.DataFrame, games: pd.DataFrame, season: int) -> pd.DataFrame:
    columns = ["player_id", "depth_name", "depth_team", "depth_position", "depth_rank", "depth_source"]
    if depth.empty:
        return pd.DataFrame(columns=columns)

    work = depth.copy()
    id_col = first_column(work, ["gsis_id", "player_id", "player_gsis_id", "nfl_id"])
    name_col = first_column(work, ["full_name", "player_name", "display_name", "player_display_name", "name"])
    team_col = first_column(work, ["team", "club_code", "recent_team", "team_abbr", "team_abbreviation"])
    pos_col = first_column(work, ["position", "position_group", "pos", "depth_position", "pos_grp", "pos_name", "pos_abb"])
    rank_col = first_column(work, ["pos_rank", "depth_team", "rank", "depth_rank"])
    date_col = first_column(work, ["dt", "date", "game_date"])
    week_col = first_column(work, ["week", "game_week"])

    if not id_col or not pos_col or not rank_col:
        return pd.DataFrame(columns=columns)

    source = "missing-time"
    if date_col:
        work["_date"] = pd.to_datetime(work[date_col], errors="coerce", utc=True)
        cutoff = first_regular_kickoff(games, season)
        if cutoff is None:
            return pd.DataFrame(columns=columns)
        work = work[work["_date"].notna() & (work["_date"] <= cutoff)].copy()
        work["_order"] = work["_date"].map(lambda value: value.value if pd.notna(value) else -1)
        source = "preseason-depth-date"
    elif week_col:
        work["_week"] = pd.to_numeric(work[week_col], errors="coerce")
        work = work[work["_week"].notna() & (work["_week"] <= 1)].copy()
        work["_order"] = work["_week"]
        source = "week-1-depth"
    else:
        return pd.DataFrame(columns=columns)

    if work.empty:
        return pd.DataFrame(columns=columns)

    work["player_id"] = work[id_col].map(clean_id)
    work["depth_name"] = work[name_col].fillna("").astype(str) if name_col else ""
    work["depth_team"] = work[team_col].map(normalize_team) if team_col else ""
    work["depth_position"] = work[pos_col].map(normalize_position)
    work["depth_rank"] = pd.to_numeric(work[rank_col], errors="coerce")
    work = work[
        work["player_id"].ne("")
        & work["depth_position"].isin(["QB", "RB", "WR", "TE"])
        & work["depth_rank"].notna()
        & (work["depth_rank"] > 0)
    ].copy()
    if work.empty:
        return pd.DataFrame(columns=columns)

    work = work.sort_values(
        ["player_id", "_order", "depth_rank"],
        ascending=[True, False, True],
        kind="stable",
    )
    work = work.groupby("player_id", as_index=False).first()
    work["depth_source"] = source
    return work[columns]


def depth_role(position: str, rank: float) -> str:
    rank = int(max(1, safe_float(rank, 99)))
    if rank == 1:
        return "STARTER"
    if position == "QB":
        return "BACKUP" if rank == 2 else "DEVELOPMENTAL"
    if position == "RB":
        return "ROTATIONAL" if rank == 2 else "BACKUP" if rank == 3 else "DEVELOPMENTAL"
    if position == "WR":
        return "ROTATIONAL" if rank == 2 else "BACKUP" if rank <= 4 else "DEVELOPMENTAL"
    if position == "TE":
        return "ROTATIONAL" if rank == 2 else "BACKUP" if rank == 3 else "DEVELOPMENTAL"
    return "UNCERTAIN"


def target_role_rows(
    predictions: pd.DataFrame,
    season: int,
    roster: pd.DataFrame,
    depth: pd.DataFrame,
) -> pd.DataFrame:
    target = predictions[predictions["target_season"] == season].copy()
    if target.empty:
        return target

    roster_meta = roster_metadata(roster, season)
    roster_by_id = {
        str(row["player_id"]): row
        for row in roster_meta.to_dict("records")
        if str(row.get("player_id") or "")
    }
    depth_by_id = {
        str(row["player_id"]): row
        for row in depth.to_dict("records")
        if str(row.get("player_id") or "")
    }
    depth_by_name = {
        normalize_name(row.get("depth_name")): row
        for row in depth.to_dict("records")
        if normalize_name(row.get("depth_name"))
    }

    rows: List[dict] = []
    for row in target.to_dict("records"):
        player_id = str(row.get("player_id") or "")
        name = str(row.get("player_name") or "")
        roster_row = roster_by_id.get(player_id)
        depth_row = depth_by_id.get(player_id) or depth_by_name.get(normalize_name(name))

        roster_position = normalize_position(roster_row.get("roster_position")) if roster_row else ""
        target_position = normalize_position(depth_row.get("depth_position")) if depth_row else roster_position
        if target_position not in {"QB", "RB", "WR", "TE"}:
            continue
        target_team = normalize_team(depth_row.get("depth_team")) if depth_row else normalize_team(roster_row.get("roster_team")) if roster_row else ""
        if not target_team:
            continue

        if depth_row:
            rank = int(max(1, safe_float(depth_row.get("depth_rank"), 99)))
            role = depth_role(target_position, rank)
            role_source = str(depth_row.get("depth_source") or "preseason-depth")
            depth_verified = True
        else:
            prior_role = str(row.get("role_bucket") or "UNCERTAIN")
            role = prior_role if prior_role in ROLE_PRIORITY else "UNCERTAIN"
            rank = int(max(1, safe_float(row.get("role_rank"), 99)))
            role_source = "target-roster-plus-prior-role-continuity"
            depth_verified = False

        output = dict(row)
        output.update(
            {
                "target_team": target_team,
                "target_position": target_position,
                "target_role": role,
                "target_depth_rank": rank,
                "target_role_source": role_source,
                "depth_verified": depth_verified,
            }
        )
        rows.append(output)

    result = pd.DataFrame(rows)
    if result.empty:
        return result

    result["target_room_ordinal"] = 99
    for (_, _), group in result.groupby(["target_team", "target_position"], sort=False):
        ordered = group.assign(
            _role_priority=group["target_role"].map(ROLE_PRIORITY).fillna(99),
            _star=group["star_flag"].astype(bool).astype(int),
        ).sort_values(
            ["_role_priority", "target_depth_rank", "_star", "latest_rate", "player_name"],
            ascending=[True, True, False, False, True],
            kind="stable",
        )
        for ordinal, index in enumerate(ordered.index, start=1):
            result.loc[index, "target_room_ordinal"] = ordinal

    result["target_generic_rate"] = result.apply(
        lambda row: current_worker_generic_rate(
            str(row["target_position"]),
            str(row["target_role"]),
            int(row["target_room_ordinal"]),
        ),
        axis=1,
    )
    return result


def current_worker_generic_rate(position: str, role: str, ordinal: int) -> float:
    if position == "QB":
        return {
            "STARTER": 245.0,
            "CO_STARTER": 131.88,
            "UNCERTAIN": 91.35,
            "ROTATIONAL": 37.24,
            "BACKUP": 22.33,
            "DEVELOPMENTAL": 5.81,
        }.get(role, 91.35)

    if position == "RB":
        return {
            "STARTER": 88.0,
            "CO_STARTER": 48.4,
            "UNCERTAIN": 31.9,
            "ROTATIONAL": 37.4,
            "BACKUP": 10.92,
            "DEVELOPMENTAL": 5.72,
        }.get(role, 31.9)

    if position == "WR":
        starter_lines = [67.0, 53.0, 40.0]
        if role == "STARTER":
            return starter_lines[min(max(ordinal - 1, 0), 2)]
        if role == "CO_STARTER":
            return 53.0 if ordinal <= 2 else 35.2
        if role == "ROTATIONAL":
            return 26.4 if ordinal <= 4 else 17.16
        if role == "UNCERTAIN":
            return 22.4 if ordinal <= 4 else 14.56
        if role == "BACKUP":
            return 10.4 if ordinal <= 4 else 6.0
        return 3.0

    if position == "TE":
        return {
            "STARTER": 43.0,
            "CO_STARTER": 19.78,
            "UNCERTAIN": 12.65,
            "ROTATIONAL": 14.72,
            "BACKUP": 4.18,
            "DEVELOPMENTAL": 2.2,
        }.get(role, 12.65)

    return 0.0


def identity_eligible(row: Mapping[str, object]) -> bool:
    return bool(
        str(row.get("target_role")) in {"STARTER", "CO_STARTER"}
        and str(row.get("role_bucket")) in {"STARTER", "CO_STARTER"}
        and str(row.get("role_stability")) in {"HIGH", "MEDIUM"}
        and str(row.get("career_state")) not in {"LOW_SAMPLE", "ROLE_CHANGED"}
        and safe_float(row.get("prior_games"), 0.0) >= 12
    )


def identity_weight(row: Mapping[str, object]) -> float:
    if not identity_eligible(row):
        return 0.0
    weight = IDENTITY_WEIGHTS.get(str(row.get("career_state")), 0.80)
    if bool(row.get("star_flag")):
        weight = max(weight, 0.95)
    if not bool(row.get("depth_verified")):
        weight -= 0.05
    return max(0.65, min(0.97, weight))


def apply_integration(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    result = frame.copy()
    result["identity_eligible"] = result.apply(identity_eligible, axis=1)
    result["identity_weight"] = result.apply(identity_weight, axis=1)
    result["role_generic_rate"] = pd.to_numeric(result["target_generic_rate"], errors="coerce").fillna(0.0)
    result["identity_integrated_rate"] = (
        result["identity_weight"] * pd.to_numeric(result["identity_guardrail_rate"], errors="coerce").fillna(result["role_generic_rate"])
        + (1.0 - result["identity_weight"]) * result["role_generic_rate"]
    )
    result["identity_full_stable_rate"] = np.where(
        result["identity_eligible"],
        pd.to_numeric(result["identity_guardrail_rate"], errors="coerce").fillna(result["role_generic_rate"]),
        result["role_generic_rate"],
    )

    limits = result["target_season"].map(lambda value: season_game_limit(int(value))).astype(float)
    availability_games = np.minimum(pd.to_numeric(result["predicted_games"], errors="coerce").fillna(limits), limits)
    result["integration_projected_games"] = np.where(result["identity_eligible"], availability_games, limits)

    result["role_generic_total"] = result["role_generic_rate"] * limits
    result["identity_integrated_total"] = result["identity_integrated_rate"] * result["integration_projected_games"]
    result["identity_full_stable_total"] = result["identity_full_stable_rate"] * result["integration_projected_games"]

    for model in INTEGRATION_MODELS:
        result[f"{model}_rate_error"] = result[f"{model}_rate"] - result["actual_rate"]
        result[f"{model}_total_error"] = result[f"{model}_total"] - result["actual_total"]
    return result


def summary_rows(frame: pd.DataFrame, group: Mapping[str, object]) -> List[dict]:
    if frame.empty:
        return []
    generic_rate_mae = float(np.mean(np.abs(frame["role_generic_rate_error"])))
    generic_total_mae = float(np.mean(np.abs(frame["role_generic_total_error"])))
    rows: List[dict] = []
    for model in INTEGRATION_MODELS:
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
                "rows": int(len(frame)),
                "identity_active_rows": int(frame["identity_eligible"].sum()),
                "rate_mae": rate_mae,
                "rate_rmse": float(math.sqrt(np.mean(np.square(rate_errors)))),
                "rate_bias": float(np.mean(rate_errors)),
                "rate_mae_improvement_vs_role_generic_pct": 0.0 if generic_rate_mae <= 0 else (generic_rate_mae - rate_mae) / generic_rate_mae * 100.0,
                "total_mae": total_mae,
                "total_rmse": float(math.sqrt(np.mean(np.square(total_errors)))),
                "total_bias": float(np.mean(total_errors)),
                "total_mae_improvement_vs_role_generic_pct": 0.0 if generic_total_mae <= 0 else (generic_total_mae - total_mae) / generic_total_mae * 100.0,
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
        "STABLE_STARTERS": frame[frame["identity_eligible"]],
        "ESTABLISHED_STARS": frame[frame["star_flag"] == True],
        "STABLE_ESTABLISHED_STARS": frame[(frame["star_flag"] == True) & (frame["identity_eligible"] == True)],
        "SHORTENED_PRIOR_SEASON": frame[frame["shortened_prior"] == True],
        "DEPTH_VERIFIED": frame[frame["depth_verified"] == True],
    }
    for label, subset in subsets.items():
        subset_rows.extend(summary_rows(subset, {"subset": label}))
    role_rows: List[dict] = []
    for (season, source), group in frame.groupby(["target_season", "target_role_source"]):
        role_rows.append(
            {
                "season": int(season),
                "role_source": source,
                "rows": int(len(group)),
                "depth_verified_rows": int(group["depth_verified"].sum()),
                "identity_active_rows": int(group["identity_eligible"].sum()),
            }
        )
    return {
        "overall": overall,
        "position": pd.DataFrame(position_rows),
        "subset": pd.DataFrame(subset_rows),
        "coverage": pd.DataFrame(role_rows),
    }


def promotion_gate(frame: pd.DataFrame, summaries: Mapping[str, pd.DataFrame]) -> dict:
    model = "identity_integrated"
    overall = summaries["overall"]
    position = summaries["position"]
    subset = summaries["subset"]

    def value(source: pd.DataFrame, mask: pd.Series, column: str, fallback: float = -999.0) -> float:
        rows = source[mask]
        return safe_float(rows[column].iloc[0], fallback) if not rows.empty else fallback

    overall_rate = value(overall, overall["model"] == model, "rate_mae_improvement_vs_role_generic_pct")
    positions = position[position["model"] == model]
    worst_position = safe_float(positions["rate_mae_improvement_vs_role_generic_pct"].min(), -999.0) if not positions.empty else -999.0
    stable_rate = value(
        subset,
        (subset["model"] == model) & (subset["subset"] == "STABLE_STARTERS"),
        "rate_mae_improvement_vs_role_generic_pct",
    )
    stable_total = value(
        subset,
        (subset["model"] == model) & (subset["subset"] == "STABLE_STARTERS"),
        "total_mae_improvement_vs_role_generic_pct",
    )
    star_rate = value(
        subset,
        (subset["model"] == model) & (subset["subset"] == "STABLE_ESTABLISHED_STARS"),
        "rate_mae_improvement_vs_role_generic_pct",
    )
    role_coverage = float(frame["target_role_source"].notna().mean() * 100.0)
    depth_coverage = float(frame["depth_verified"].mean() * 100.0)

    passed = bool(
        overall_rate > 0
        and worst_position >= -2
        and stable_rate >= 5
        and stable_total > 0
        and star_rate >= 5
        and role_coverage >= 90
    )
    return {
        "version": "v2.0-player-identity-role-integration-1",
        "researchOnly": True,
        "productionChanged": False,
        "candidateModel": model,
        "roleIntegrationReplayPassed": passed,
        "recommendedForProductionIntegration": False,
        "requirements": {
            "overallRateMaeImprovementPctGreaterThan": 0,
            "noPositionRateMaeRegressionWorseThanPct": -2,
            "stableStarterRateMaeImprovementPctAtLeast": 5,
            "stableStarterTotalMaeImprovementPctGreaterThan": 0,
            "stableStarRateMaeImprovementPctAtLeast": 5,
            "roleCoveragePctAtLeast": 90,
        },
        "observed": {
            "overallRateMaeImprovementPct": overall_rate,
            "worstPositionRateMaeImprovementPct": worst_position,
            "stableStarterRateMaeImprovementPct": stable_rate,
            "stableStarterTotalMaeImprovementPct": stable_total,
            "stableStarRateMaeImprovementPct": star_rate,
            "roleCoveragePct": role_coverage,
            "depthVerifiedCoveragePct": depth_coverage,
        },
        "note": "Passing this replay allows a separate shadow implementation. It does not authorize a live Season Worker replacement.",
    }


def projection_value(player: Mapping[str, object]) -> Optional[float]:
    metric = str(player.get("primaryMetric") or "")
    projections = player.get("projections")
    raw = projections.get(metric) if isinstance(projections, Mapping) and metric else None
    if isinstance(raw, Mapping):
        for key in ("mean", "projection", "projected", "value", "total"):
            value = safe_float(raw.get(key), np.nan)
            if math.isfinite(value):
                return value
    for key in ("primaryProjection", "projection", "projectedTotal", "seasonProjection", "seasonTotal"):
        value = safe_float(player.get(key), np.nan)
        if math.isfinite(value):
            return value
    return None


def worker_player_name(player: Mapping[str, object]) -> str:
    return str(player.get("name") or player.get("playerName") or player.get("displayName") or player.get("fullName") or "")


def load_worker_snapshot(url: str) -> Tuple[dict, Optional[str]]:
    try:
        response = requests.get(url, timeout=30, headers={"Accept": "application/json", "User-Agent": "GridironPulse-v2.0-identity-replay/1.0"})
        response.raise_for_status()
        payload = response.json()
        snapshot = payload.get("seasonOutlook") if isinstance(payload, Mapping) else None
        if not isinstance(snapshot, Mapping):
            return {}, "seasonOutlook-missing"
        return dict(snapshot), None
    except Exception as exc:
        return {}, str(exc)


def current_stat_total(player: Mapping[str, object], primary_metric: str) -> float:
    stats = player.get("currentStats") if isinstance(player.get("currentStats"), Mapping) else {}
    if primary_metric == "scrimmageYards":
        return safe_float(stats.get("rushingYards"), 0.0) + safe_float(stats.get("receivingYards"), 0.0)
    return safe_float(stats.get(primary_metric), 0.0)


def build_2026_preview(identity_forecast: pd.DataFrame, worker_url: str) -> Tuple[pd.DataFrame, dict]:
    snapshot, error = load_worker_snapshot(worker_url)
    players = snapshot.get("players") if isinstance(snapshot.get("players"), list) else []
    if not players:
        return pd.DataFrame(), {"workerError": error or "no-players", "workerPlayers": 0, "identityMatches": 0}

    by_identity: Dict[Tuple[str, str, str], dict] = {}
    by_name_position: Dict[Tuple[str, str], dict] = {}
    for row in identity_forecast.to_dict("records"):
        name = normalize_name(row.get("player_name"))
        position = normalize_position(row.get("forecast_position") or row.get("position"))
        team = normalize_team(row.get("forecast_team") or row.get("prior_team"))
        if name and position:
            by_identity[(name, position, team)] = row
            by_name_position[(name, position)] = row

    outputs: List[dict] = []
    matched = 0
    active = 0
    for player in players:
        name = worker_player_name(player)
        position = normalize_position(player.get("positionGroup") or player.get("position"))
        team = normalize_team(player.get("team"))
        identity = by_identity.get((normalize_name(name), position, team)) or by_name_position.get((normalize_name(name), position))
        if identity:
            matched += 1

        role = str(player.get("role") or "UNCERTAIN").upper()
        prior_role = str(identity.get("role_bucket") or "") if identity else ""
        eligible = bool(
            identity
            and role in {"STARTER", "CO-STARTER / COMMITTEE", "CO_STARTER"}
            and prior_role in {"STARTER", "CO_STARTER"}
            and str(identity.get("role_stability")) in {"HIGH", "MEDIUM"}
            and str(identity.get("career_state")) not in {"LOW_SAMPLE", "ROLE_CHANGED"}
        )
        weight = 0.0
        if eligible:
            pseudo = dict(identity)
            pseudo["target_role"] = "CO_STARTER" if "CO" in role else "STARTER"
            pseudo["depth_verified"] = bool(safe_float(player.get("depthChart", {}).get("sourceCount") if isinstance(player.get("depthChart"), Mapping) else 0, 0.0) > 0)
            weight = identity_weight(pseudo)
            active += 1

        official = projection_value(player)
        metric = str(player.get("primaryMetric") or "")
        official_per_game = safe_float((player.get("perGameProjection") or {}).get(metric) if isinstance(player.get("perGameProjection"), Mapping) else np.nan, np.nan)
        identity_rate = safe_float(identity.get("identity_guardrail_rate") if identity else np.nan, np.nan)
        blended_rate = (
            weight * identity_rate + (1.0 - weight) * official_per_game
            if eligible and math.isfinite(identity_rate) and math.isfinite(official_per_game)
            else identity_rate if eligible and math.isfinite(identity_rate)
            else official_per_game
        )

        actual_games = safe_float(player.get("actualGames"), 0.0)
        current_total = current_stat_total(player, metric)
        historical_games = safe_float(identity.get("predicted_games") if identity else np.nan, np.nan)
        worker_remaining = safe_float(player.get("teamRemainingGames"), max(0.0, 17.0 - actual_games))
        identity_remaining = max(0.0, historical_games - actual_games) if math.isfinite(historical_games) else worker_remaining
        remaining_games = min(worker_remaining, identity_remaining) if eligible else worker_remaining
        candidate_total = current_total + blended_rate * remaining_games if eligible and math.isfinite(blended_rate) else official

        outputs.append(
            {
                "playerName": name,
                "team": team,
                "position": position,
                "primaryMetric": metric,
                "role": role,
                "roleSource": player.get("roleSource"),
                "identityMatched": bool(identity),
                "identityEligible": eligible,
                "identityWeight": weight,
                "careerState": identity.get("career_state") if identity else None,
                "careerFlags": identity.get("career_flags") if identity else None,
                "contractStatus": identity.get("contract_status") if identity else None,
                "officialPerGame": official_per_game if math.isfinite(official_per_game) else None,
                "identityPerGame": identity_rate if math.isfinite(identity_rate) else None,
                "candidatePerGame": blended_rate if math.isfinite(blended_rate) else None,
                "officialProjection": official,
                "candidateProjection": candidate_total,
                "delta": candidate_total - official if candidate_total is not None and official is not None else None,
                "actualGames": actual_games,
                "identityProjectedGames": historical_games if math.isfinite(historical_games) else None,
                "candidateRemainingGames": remaining_games,
                "productionChanged": False,
            }
        )

    result = pd.DataFrame(outputs)
    if not result.empty:
        result = result.sort_values(["identityEligible", "delta"], ascending=[False, False], na_position="last")
    return result, {
        "workerError": error,
        "workerPlayers": len(players),
        "identityMatches": matched,
        "identityEligiblePlayers": active,
        "seasonWeek": snapshot.get("seasonWeek"),
        "workerVersion": snapshot.get("version"),
        "productionChanged": False,
    }


def sanity_rows(preview: pd.DataFrame) -> pd.DataFrame:
    if preview.empty:
        return preview
    names = {"matthewstafford", "brockbowers"}
    direct = preview[preview["playerName"].map(normalize_name).isin(names)]
    largest = preview[preview["identityEligible"] == True].sort_values("delta", ascending=False).head(18)
    return pd.concat([direct, largest], ignore_index=True).drop_duplicates(["playerName", "team", "position"])


def write_frame(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, float_format="%.6f")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--backtest", type=Path, required=True)
    parser.add_argument("--forecast", type=Path, required=True)
    parser.add_argument("--start", type=int, default=2015)
    parser.add_argument("--end", type=int, default=2025)
    parser.add_argument("--out", type=Path, default=Path("model-lab/output/v20-player-identity-integration"))
    parser.add_argument("--cache", type=Path, default=Path("model-lab/output/v20-player-identity-cache"))
    parser.add_argument("--worker-url", default=SEASON_WORKER_URL)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    pd.read_csv(args.source, low_memory=False)
    backtest = pd.read_csv(args.backtest, low_memory=False)
    forecast = pd.read_csv(args.forecast, low_memory=False)
    games = load_csv_url(GAMES_URL, args.cache / "games.csv")

    replay_frames: List[pd.DataFrame] = []
    coverage: List[dict] = []
    for season in range(args.start, args.end + 1):
        print(f"[v2.0 integration] Target season {season}")
        roster = load_csv_url(roster_url(season), args.cache / f"roster_{season}.csv", optional=True)
        depth_raw = load_depth_chart(season, args.cache)
        depth = preseason_depth(depth_raw, games, season)
        roles = target_role_rows(backtest, season, roster, depth)
        if roles.empty:
            print(f"  - no role rows for {season}")
            continue
        integrated = apply_integration(roles)
        replay_frames.append(integrated)
        coverage.append(
            {
                "season": season,
                "backtest_rows": int((backtest["target_season"] == season).sum()),
                "role_rows": int(len(integrated)),
                "depth_rows": int(len(depth)),
                "depth_verified_rows": int(integrated["depth_verified"].sum()),
                "identity_active_rows": int(integrated["identity_eligible"].sum()),
            }
        )

    if not replay_frames:
        raise RuntimeError("Role integration replay produced no rows")
    replay = pd.concat(replay_frames, ignore_index=True)
    write_frame(replay, args.out / "integration_replay_predictions.csv")
    write_frame(pd.DataFrame(coverage), args.out / "integration_role_coverage.csv")

    summaries = summarize(replay)
    write_frame(summaries["overall"], args.out / "integration_overall_summary.csv")
    write_frame(summaries["position"], args.out / "integration_position_summary.csv")
    write_frame(summaries["subset"], args.out / "integration_subset_summary.csv")
    write_frame(summaries["coverage"], args.out / "integration_source_coverage.csv")

    gate = promotion_gate(replay, summaries)
    (args.out / "integration_policy.json").write_text(json.dumps(gate, indent=2, allow_nan=False), encoding="utf-8")

    preview, preview_meta = build_2026_preview(forecast, args.worker_url)
    write_frame(preview, args.out / "integration_2026_preview.csv")
    sanity = sanity_rows(preview)
    write_frame(sanity, args.out / "integration_2026_sanity_checks.csv")
    preview_payload = {
        "version": "v2.0-player-identity-2026-preview-1",
        "researchOnly": True,
        "productionChanged": False,
        **preview_meta,
        "players": preview.replace({np.nan: None}).to_dict("records"),
    }
    (args.out / "integration_2026_preview.json").write_text(json.dumps(preview_payload, indent=2, allow_nan=False), encoding="utf-8")

    summary = {
        "version": "v2.0-player-identity-role-integration-1",
        "researchOnly": True,
        "productionChanged": False,
        "seasons": [args.start, args.end],
        "replayRows": int(len(replay)),
        "depthVerifiedRows": int(replay["depth_verified"].sum()),
        "identityActiveRows": int(replay["identity_eligible"].sum()),
        "preview": preview_meta,
        "gate": gate,
        "method": {
            "role": "Target-season preseason depth chart when available; otherwise target roster plus prior-role continuity. Low-confidence roles remain generic.",
            "rate": "Player Identity rate is blended only for stable starter/co-starter continuities. Backups, developmental players, low samples, and role changes remain on the generic role baseline.",
            "availability": "Historical game availability remains separate from rate and is applied only to identity-eligible stable starters.",
            "contract": "Contract context remains an optional flag from the baseline layer and never creates a blanket boost.",
        },
    }
    (args.out / "integration_summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False), encoding="utf-8")

    print("\n[v2.0 integration] Overall")
    print(summaries["overall"].to_string(index=False))
    print("\n[v2.0 integration] Stable/star subsets")
    print(summaries["subset"].to_string(index=False))
    print("\n[v2.0 integration] 2026 Stafford/Bowers and largest eligible changes")
    print(sanity.to_string(index=False) if not sanity.empty else "No 2026 sanity rows")
    print("\n[v2.0 integration] Gate")
    print(json.dumps(gate, indent=2))


if __name__ == "__main__":
    main()
