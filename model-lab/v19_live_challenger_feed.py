#!/usr/bin/env python3
"""GRIDIRON PULSE v1.9k live challenger feed.

Builds the 2026 v1.9 challenger projection only for routes frozen by v1.9j.
The current Season Worker remains the official source at all times. This feed is
research/shadow-only and fails closed when point-in-time inputs are missing.

The active challenger uses the validated v1.9f rate history gate plus the
v1.9g availability strategy selected from seasons strictly before 2026.
Historical features are supplied by the existing no-lookahead feature builder.
"""
from __future__ import annotations

import argparse
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
import requests

from v19_player_feature_builder import (
    aggregate_players,
    build_roster_crosswalk,
    checkpoint_cutoff_date,
    context_map,
    depth_context,
    feature_row,
    injury_context,
    load_games,
    period_stats,
    qb_quality,
    roster_at_checkpoint,
    roster_sets,
    season_source,
    snap_context,
    team_context,
)
from v19_player_availability_backtest import (
    MAX_NEIGHBORS,
    availability_rate_for_strategy,
    choose_strategy,
    enrich_availability_columns,
    rate_prediction_eq17,
)

MODEL_VERSION = "v1.9k"
SEASON = 2026
DEFAULT_WORKER_URL = "https://gridiron-pulse-season.kadescott97.workers.dev/season-outlook"
ACTIVE_CHECKPOINTS = (4, 8, 12)
VALID_POSITIONS = ("QB", "RB", "WR", "TE")


def safe_float(value: object, default: float = np.nan) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def checkpoint_for_week(week: int) -> Optional[int]:
    week = int(week)
    if week < 4:
        return None
    if week < 8:
        return 4
    if week < 12:
        return 8
    return 12


def normalize_name(value: object) -> str:
    text = str(value or "").lower()
    text = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", text)
    return re.sub(r"[^a-z0-9]", "", text)


def normalize_team(value: object) -> str:
    text = str(value or "").upper().strip()
    aliases = {"JAC": "JAX", "LAR": "LA", "STL": "LA", "OAK": "LV", "SD": "LAC", "WSH": "WAS"}
    return aliases.get(text, text)


def load_policy(path: Path) -> Tuple[dict, Dict[Tuple[str, int], str]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if int(data.get("season") or 0) != SEASON or data.get("mode") != "shadow-only":
        raise RuntimeError("v1.9k requires the frozen 2026 shadow-only policy")
    routes: Dict[Tuple[str, int], str] = {}
    for row in data.get("routes") or []:
        position = str(row.get("position") or "").upper()
        checkpoint = int(row.get("checkpoint") or 0)
        route = str(row.get("route") or "worker").lower()
        if position in VALID_POSITIONS and checkpoint in ACTIVE_CHECKPOINTS:
            routes[(position, checkpoint)] = route
    if len(routes) != 12:
        raise RuntimeError(f"Expected 12 frozen position/checkpoint routes, found {len(routes)}")
    return data, routes


def worker_projection_value(player: Mapping[str, object]) -> Optional[float]:
    metric = str(player.get("primaryMetric") or "")
    projections = player.get("projections")
    raw = projections.get(metric) if isinstance(projections, Mapping) and metric else None
    if isinstance(raw, (int, float)) and math.isfinite(float(raw)):
        return float(raw)
    if isinstance(raw, Mapping):
        for key in (
            "projection",
            "projected",
            "value",
            "total",
            "mean",
            "median",
            "expected",
            "projectedTotal",
            "seasonTotal",
        ):
            value = safe_float(raw.get(key), np.nan)
            if math.isfinite(value):
                return value
    for key in ("projection", "projectedTotal", "seasonProjection", "seasonTotal"):
        value = safe_float(player.get(key), np.nan)
        if math.isfinite(value):
            return value
    return None


def worker_player_key(player: Mapping[str, object]) -> str:
    for key in ("gsisId", "gsis_id", "playerKey", "athleteId", "id", "key"):
        value = str(player.get(key) or "").strip()
        if value:
            return value.upper()
    return ""


def worker_identity_key(player: Mapping[str, object]) -> Tuple[str, str, str]:
    name = normalize_name(
        player.get("playerName")
        or player.get("displayName")
        or player.get("fullName")
        or player.get("name")
    )
    position = str(player.get("positionGroup") or player.get("position") or "").upper().strip()
    team_value = player.get("team") or player.get("teamAbbr") or player.get("teamCode") or player.get("teamAbbreviation")
    if isinstance(team_value, Mapping):
        team_value = team_value.get("abbreviation") or team_value.get("abbr") or team_value.get("code")
    return name, position, normalize_team(team_value)


def fetch_worker_players(url: str, timeout: int = 30) -> Tuple[List[dict], Optional[str]]:
    if not url:
        return [], "worker-url-disabled"
    try:
        response = requests.get(
            url,
            timeout=timeout,
            headers={"Accept": "application/json", "User-Agent": "GridironPulse-v1.9k-shadow/1.0"},
        )
        response.raise_for_status()
        payload = response.json()
        players = payload.get("players") if isinstance(payload, Mapping) else None
        if not isinstance(players, list):
            return [], "worker-response-missing-players"
        return [row for row in players if isinstance(row, dict)], None
    except Exception as exc:
        return [], f"worker-fetch-failed: {exc}"


def build_worker_indexes(players: Sequence[Mapping[str, object]]):
    by_id: Dict[str, Mapping[str, object]] = {}
    by_identity: Dict[Tuple[str, str, str], Mapping[str, object]] = {}
    for player in players:
        key = worker_player_key(player)
        if key:
            by_id[key] = player
        identity = worker_identity_key(player)
        if identity[0] and identity[1]:
            by_identity[identity] = player
    return by_id, by_identity


def max_regular_week(stats_raw: pd.DataFrame) -> int:
    work = period_stats(stats_raw, None)
    if work.empty or "_week" not in work.columns:
        return 0
    weeks = pd.to_numeric(work["_week"], errors="coerce").dropna()
    return int(weeks.max()) if not weeks.empty else 0


def safe_depth_context(
    depth_raw: pd.DataFrame,
    checkpoint: Optional[int],
    cutoff: Optional[pd.Timestamp],
) -> Dict[str, dict]:
    if depth_raw.empty:
        return {}
    if "dt" in depth_raw.columns and cutoff is None:
        return {}
    return depth_context(depth_raw, checkpoint, cutoff)


def live_feature_frame(season: int, checkpoint: int) -> Tuple[pd.DataFrame, dict]:
    stats_raw = season_source("player_stats", season)
    prior_stats_raw = season_source("player_stats", season - 1)
    roster_raw = season_source("rosters", season)
    prior_roster_raw = season_source("rosters", season - 1)
    injuries_raw = season_source("injuries", season)
    snaps_raw = season_source("snap_counts", season)
    prior_snaps_raw = season_source("snap_counts", season - 1)
    depth_raw = season_source("depth_charts", season)
    prior_depth_raw = season_source("depth_charts", season - 1)

    if stats_raw.empty:
        return pd.DataFrame(), {"ready": False, "reason": "current-player-stats-unavailable"}
    latest_week = max_regular_week(stats_raw)
    if latest_week < checkpoint:
        return pd.DataFrame(), {
            "ready": False,
            "reason": "checkpoint-not-yet-complete",
            "latestRegularWeek": latest_week,
            "requiredCheckpoint": checkpoint,
        }
    if prior_stats_raw.empty or roster_raw.empty or prior_roster_raw.empty:
        return pd.DataFrame(), {"ready": False, "reason": "required-prior-or-roster-data-unavailable"}
    if injuries_raw.empty:
        return pd.DataFrame(), {"ready": False, "reason": "current-injury-data-unavailable"}

    rosters = {season - 1: prior_roster_raw, season: roster_raw}
    pfr_to_gsis, identity = build_roster_crosswalk(rosters)
    games = load_games()

    current_work = period_stats(stats_raw, checkpoint)
    current_players = aggregate_players(current_work)
    if current_players.empty:
        return pd.DataFrame(), {"ready": False, "reason": "no-current-player-rows"}
    current_players = current_players[current_players["eligible"]].copy()

    prior_work = period_stats(prior_stats_raw, None)
    prior_players_df = aggregate_players(prior_work)
    prior_players = prior_players_df.set_index("playerKey").to_dict("index") if not prior_players_df.empty else {}
    for key, info in prior_players.items():
        info["playerKey"] = key

    current_context = context_map(team_context(current_work))
    prior_context = context_map(team_context(prior_work))
    current_qb = qb_quality(current_work)
    prior_qb = qb_quality(prior_work)
    current_snap = snap_context(snaps_raw, pfr_to_gsis, checkpoint)
    prior_snap = snap_context(prior_snaps_raw, pfr_to_gsis, None)

    current_cutoff = checkpoint_cutoff_date(games, season, checkpoint)
    prior_cutoff = checkpoint_cutoff_date(games, season - 1, 22)
    current_depth = safe_depth_context(depth_raw, checkpoint, current_cutoff)
    prior_depth = safe_depth_context(prior_depth_raw, None, prior_cutoff)
    current_injury = injury_context(injuries_raw, checkpoint)
    current_roster = roster_at_checkpoint(roster_raw, checkpoint)
    current_sets = roster_sets(current_roster)

    rows: List[dict] = []
    for current in current_players.to_dict("records"):
        player = str(current.get("playerKey") or "")
        if not player:
            continue
        rows.append(
            feature_row(
                season,
                checkpoint,
                current,
                current,
                prior_players.get(player),
                current_context,
                prior_context,
                current_qb,
                prior_qb,
                current_snap,
                prior_snap,
                current_depth,
                prior_depth,
                current_injury,
                current_roster,
                current_sets,
                prior_players,
                {},
                identity,
            )
        )

    frame = pd.DataFrame(rows)
    return frame, {
        "ready": not frame.empty,
        "reason": "ready" if not frame.empty else "no-live-feature-rows",
        "latestRegularWeek": latest_week,
        "checkpoint": checkpoint,
        "rows": int(len(frame)),
        "snapPlayers": len(current_snap),
        "depthPlayers": len(current_depth),
        "injuryPlayers": len(current_injury),
    }


def prepare_history(path: Path) -> pd.DataFrame:
    history = pd.read_csv(path, low_memory=False)
    history["season"] = pd.to_numeric(history["season"], errors="coerce").astype("Int64")
    history["checkpoint"] = pd.to_numeric(history["checkpoint"], errors="coerce").astype("Int64")
    history["targetPrimaryEq17"] = pd.to_numeric(history["targetPrimaryEq17"], errors="coerce")
    history["pacePrimaryEq17"] = pd.to_numeric(history["pacePrimaryEq17"], errors="coerce")
    history = history[
        history["season"].notna()
        & (history["season"] < SEASON)
        & history["targetPrimaryEq17"].notna()
        & history["pacePrimaryEq17"].notna()
    ].copy()
    history["paceResidual"] = history["targetPrimaryEq17"] - history["pacePrimaryEq17"]
    return enrich_availability_columns(history)


def find_worker_player(
    row: Mapping[str, object],
    by_id: Mapping[str, Mapping[str, object]],
    by_identity: Mapping[Tuple[str, str, str], Mapping[str, object]],
) -> Optional[Mapping[str, object]]:
    player_key = str(row.get("playerKey") or "").upper().strip()
    if player_key and player_key in by_id:
        return by_id[player_key]
    identity = (
        normalize_name(row.get("playerName")),
        str(row.get("position") or "").upper().strip(),
        normalize_team(row.get("team")),
    )
    return by_identity.get(identity)


def challenger_rows(
    live: pd.DataFrame,
    history: pd.DataFrame,
    checkpoint: int,
    routes: Mapping[Tuple[str, int], str],
    worker_players: Sequence[Mapping[str, object]],
) -> Tuple[List[dict], List[dict]]:
    live = enrich_availability_columns(live)
    by_id, by_identity = build_worker_indexes(worker_players)
    outputs: List[dict] = []
    decisions: List[dict] = []

    for position in VALID_POSITIONS:
        route = routes.get((position, checkpoint), "worker")
        live_position = live[live["position"] == position].copy()
        if live_position.empty:
            decisions.append({"position": position, "checkpoint": checkpoint, "route": route, "rows": 0, "status": "no-live-rows"})
            continue
        if route != "v19":
            decisions.append({"position": position, "checkpoint": checkpoint, "route": route, "rows": int(len(live_position)), "status": "worker-route"})
            continue

        block = history[(history["position"] == position) & (history["checkpoint"] == checkpoint)].copy()
        train = block[block["season"] < SEASON].copy()
        if block.empty or train.empty:
            decisions.append({"position": position, "checkpoint": checkpoint, "route": route, "rows": int(len(live_position)), "status": "history-unavailable-fail-closed"})
            continue

        rate_eq17, history_enabled, rate_feature_count = rate_prediction_eq17(
            block,
            train,
            live_position,
            SEASON,
            MAX_NEIGHBORS,
        )
        strategy_choice = choose_strategy(block, SEASON, MAX_NEIGHBORS)
        strategy = str(strategy_choice.get("strategy") or "full_available")
        availability_rate, availability_feature_count = availability_rate_for_strategy(
            strategy,
            train,
            live_position,
            MAX_NEIGHBORS,
        )

        current_primary = pd.to_numeric(live_position["currentPrimary"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
        current_games = pd.to_numeric(live_position["games"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
        remaining_team = pd.to_numeric(live_position["remainingTeamGames"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
        predicted_remaining_games = np.clip(availability_rate, 0.0, 1.0) * remaining_team
        predicted_total = current_primary + (rate_eq17 / 17.0) * predicted_remaining_games
        predicted_final_games = current_games + predicted_remaining_games

        for idx, (_, row) in enumerate(live_position.iterrows()):
            record = row.to_dict()
            worker_player = find_worker_player(record, by_id, by_identity)
            worker_projection = worker_projection_value(worker_player) if worker_player else None
            outputs.append(
                {
                    "playerKey": str(record.get("playerKey") or ""),
                    "playerName": str(record.get("playerName") or ""),
                    "team": str(record.get("team") or ""),
                    "position": position,
                    "checkpoint": checkpoint,
                    "policyRoute": "v19",
                    "historyEnabled": bool(history_enabled),
                    "rateEq17": float(rate_eq17[idx]),
                    "rateFeatureCount": int(rate_feature_count),
                    "availabilityStrategy": strategy,
                    "availabilityRate": float(np.clip(availability_rate[idx], 0.0, 1.0)),
                    "availabilityFeatureCount": int(availability_feature_count),
                    "currentPrimary": float(current_primary[idx]),
                    "currentGames": float(current_games[idx]),
                    "predictedRemainingGames": float(predicted_remaining_games[idx]),
                    "challengerPrediction": float(predicted_total[idx]),
                    "challengerPredictedFinalGames": float(predicted_final_games[idx]),
                    "workerPlayerFound": bool(worker_player),
                    "workerPrimaryMetric": str(worker_player.get("primaryMetric") or "") if worker_player else None,
                    "workerPrediction": worker_projection,
                    "shadowDelta": float(predicted_total[idx] - worker_projection) if worker_projection is not None else None,
                    "officialSource": "worker",
                    "shadowSource": "v19",
                }
            )

        validation = strategy_choice.get("validation") or {}
        decisions.append(
            {
                "position": position,
                "checkpoint": checkpoint,
                "route": "v19",
                "rows": int(len(live_position)),
                "status": "challenger-generated",
                "historyEnabled": bool(history_enabled),
                "availabilityStrategy": strategy,
                "strategyValidationBlocks": int(safe_float(validation.get("blocks"), 0.0)),
                "strategyValidationMae": safe_float(validation.get("mae"), np.nan),
            }
        )
    return outputs, decisions


def write_outputs(out_dir: Path, payload: dict, rows: Sequence[Mapping[str, object]]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "live_shadow_feed.json").write_text(json.dumps(payload, indent=2, allow_nan=False), encoding="utf-8")
    pd.DataFrame(rows).to_csv(out_dir / "live_shadow_players.csv", index=False)


def self_test(policy_path: Path) -> None:
    _data, routes = load_policy(policy_path)
    expected = {("RB", 4), ("TE", 8), ("WR", 4), ("WR", 8)}
    actual = {key for key, value in routes.items() if value == "v19"}
    assert actual == expected, (actual, expected)
    assert checkpoint_for_week(3) is None
    assert checkpoint_for_week(4) == 4
    assert checkpoint_for_week(8) == 8
    assert checkpoint_for_week(12) == 12
    fixture = {
        "primaryMetric": "receivingYards",
        "projections": {"receivingYards": {"projection": 1111.5}},
    }
    assert worker_projection_value(fixture) == 1111.5
    assert worker_projection_value({"primaryMetric": "x", "projections": {"x": None}}) is None
    print("v1.9k live challenger feed self-test passed.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", type=int, default=SEASON)
    parser.add_argument("--week", type=int, default=0, help="0 = infer latest regular-season week from nflverse")
    parser.add_argument(
        "--historical-features",
        type=Path,
        default=Path("model-lab/output/v19-player-features/player_features.csv"),
    )
    parser.add_argument(
        "--policy",
        type=Path,
        default=Path("model-lab/v19_shadow_policy_2026.json"),
    )
    parser.add_argument("--worker-url", default=DEFAULT_WORKER_URL)
    parser.add_argument("--out", type=Path, default=Path("model-lab/output/v19-live-shadow"))
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test(args.policy)
        return
    if args.season != SEASON:
        raise RuntimeError("v1.9k live shadow feed is frozen for the 2026 season")

    policy_data, routes = load_policy(args.policy)
    requested_week = max(0, int(args.week))

    if requested_week <= 0:
        stats_raw = season_source("player_stats", SEASON)
        inferred_week = max_regular_week(stats_raw) if not stats_raw.empty else 0
        week = inferred_week
    else:
        week = requested_week

    checkpoint = checkpoint_for_week(week)
    worker_players, worker_error = fetch_worker_players(args.worker_url)
    base = {
        "model": "GRIDIRON PULSE v1.9k live challenger feed",
        "modelVersion": MODEL_VERSION,
        "season": SEASON,
        "week": week,
        "checkpoint": checkpoint,
        "mode": "shadow-only",
        "productionWorkerChanged": False,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "policySource": {
            "shadowRouterWorkflowRun": (policy_data.get("source") or {}).get("shadowRouterWorkflowRun"),
            "historicalEvidenceThrough": (policy_data.get("source") or {}).get("historicalEvidenceThrough"),
        },
        "workerUrl": args.worker_url,
        "workerPlayers": len(worker_players),
        "workerError": worker_error,
    }

    if checkpoint is None:
        payload = {
            **base,
            "status": "inactive-before-week4",
            "summary": {"challengerPlayers": 0, "officialSource": "worker"},
            "decisions": [],
            "players": [],
        }
        write_outputs(args.out, payload, [])
        print(json.dumps(payload, indent=2), flush=True)
        return

    live, live_status = live_feature_frame(SEASON, checkpoint)
    if live.empty or not live_status.get("ready"):
        payload = {
            **base,
            "status": "fail-closed-live-inputs-not-ready",
            "liveInputs": live_status,
            "summary": {"challengerPlayers": 0, "officialSource": "worker"},
            "decisions": [],
            "players": [],
        }
        write_outputs(args.out, payload, [])
        print(json.dumps(payload, indent=2), flush=True)
        return

    if not args.historical_features.exists():
        raise RuntimeError(f"Historical feature file not found: {args.historical_features}")
    history = prepare_history(args.historical_features)
    players, decisions = challenger_rows(live, history, checkpoint, routes, worker_players)
    worker_found = sum(1 for row in players if row.get("workerPlayerFound"))
    worker_numeric = sum(1 for row in players if row.get("workerPrediction") is not None)
    payload = {
        **base,
        "status": "active-shadow-feed",
        "liveInputs": live_status,
        "summary": {
            "liveEligiblePlayers": int(len(live)),
            "challengerPlayers": int(len(players)),
            "workerMatchedPlayers": int(worker_found),
            "workerNumericProjectionPlayers": int(worker_numeric),
            "officialSource": "worker",
        },
        "decisions": decisions,
        "players": players,
    }
    write_outputs(args.out, payload, players)
    print(json.dumps({key: payload[key] for key in ["modelVersion", "season", "week", "checkpoint", "status", "summary", "decisions"]}, indent=2), flush=True)


if __name__ == "__main__":
    main()
