#!/usr/bin/env python3
"""GRIDIRON PULSE v1.9g player availability / games-played backtest.

Uses the v1.9f no-environment history gate as the rate-model reference, then
learns whether an availability strategy improves actual season-total forecasts.
Every held-out season and every strategy choice uses only prior seasons.

Research only. No Season Worker production weights are set here.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

import numpy as np
import pandas as pd

from v19_player_comparable_backtest import robust_scale, safe_float
from v19_player_isolated_environment_backtest import (
    PRODUCTION_FEATURES,
    evaluate_stage,
    improvement_pct,
)
from v19_player_environment_value_audit import hard_gate_choice

MIN_TEST_ROWS = 5
MIN_TRAIN_ROWS = 25
MIN_VALIDATION_BLOCKS = 2
TIE_TOLERANCE_PCT = 0.10
MAX_NEIGHBORS = 35

AVAILABILITY_FEATURES: Tuple[str, ...] = (
    "availability_rate",
    "prior_availability_rate",
    "injury_burden",
    "out_report_rate",
    "injury_context_delta",
    "games_missed_to_date",
    "years_experience",
    "established_player_score",
    "snap_share",
    "starter_flag",
    "depth_rank",
    "prior_data_available",
    "changed_teams",
)

STRATEGIES: Tuple[str, ...] = (
    "full_available",
    "current_availability",
    "prior_availability",
    "health_knn",
)

STRATEGY_COMPLEXITY = {
    "full_available": 0,
    "current_availability": 1,
    "prior_availability": 1,
    "health_knn": 2,
}


def schedule_games(season: int) -> int:
    return 17 if int(season) >= 2021 else 16


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def enrich_availability_columns(data: pd.DataFrame) -> pd.DataFrame:
    work = data.copy()
    work["seasonScheduleGames"] = work["season"].map(lambda value: schedule_games(int(value)))
    availability = pd.to_numeric(work.get("availability_rate"), errors="coerce").fillna(1.0)
    games = pd.to_numeric(work.get("games"), errors="coerce").fillna(0.0)
    final_games = pd.to_numeric(work.get("finalGames"), errors="coerce").fillna(games)
    injury_delta = pd.to_numeric(work.get("injury_context_delta"), errors="coerce").fillna(0.0)

    estimated_team_games = np.where(
        availability > 1e-6,
        np.rint(games / availability),
        games,
    )
    estimated_team_games = np.maximum(estimated_team_games, games)
    estimated_team_games = np.minimum(estimated_team_games, work["seasonScheduleGames"].to_numpy(dtype=float))

    work["currentTeamGames"] = estimated_team_games
    work["remainingTeamGames"] = np.maximum(
        0.0,
        work["seasonScheduleGames"].to_numpy(dtype=float) - estimated_team_games,
    )
    work["games_missed_to_date"] = np.maximum(0.0, estimated_team_games - games)
    work["prior_availability_rate"] = np.clip(availability - injury_delta / 100.0, 0.0, 1.0)

    remaining_actual = np.maximum(0.0, final_games - games)
    denominator = np.maximum(work["remainingTeamGames"].to_numpy(dtype=float), 1.0)
    work["targetRemainingAvailabilityRate"] = np.clip(remaining_actual / denominator, 0.0, 1.0)
    work["targetRemainingGames"] = remaining_actual
    return work


def inverse_distance_target(
    train_x: np.ndarray,
    test_x: np.ndarray,
    train_y: np.ndarray,
    max_neighbors: int,
) -> np.ndarray:
    if len(train_x) == 0 or len(test_x) == 0:
        return np.zeros(len(test_x), dtype=float)
    k = min(max_neighbors, max(10, int(round(math.sqrt(len(train_x))))), len(train_x))
    preds: List[float] = []
    for row in test_x:
        distances = np.sqrt(np.mean((train_x - row) ** 2, axis=1))
        nearest = np.argpartition(distances, k - 1)[:k]
        d = distances[nearest]
        weights = 1.0 / np.maximum(d, 0.05)
        y = train_y[nearest]
        pred = float(np.sum(weights * y) / np.sum(weights)) if np.sum(weights) > 0 else float(np.mean(y))
        preds.append(clamp(pred, 0.0, 1.0))
    return np.asarray(preds, dtype=float)


def health_knn_availability(
    train: pd.DataFrame,
    test: pd.DataFrame,
    max_neighbors: int,
) -> Tuple[np.ndarray, int]:
    train_x, test_x, used = robust_scale(train, test, AVAILABILITY_FEATURES)
    if not used:
        fallback = pd.to_numeric(test["availability_rate"], errors="coerce").fillna(1.0).clip(0.0, 1.0)
        return fallback.to_numpy(dtype=float), 0
    train_y = pd.to_numeric(train["targetRemainingAvailabilityRate"], errors="coerce").fillna(1.0).clip(0.0, 1.0)
    return inverse_distance_target(train_x, test_x, train_y.to_numpy(dtype=float), max_neighbors), len(used)


def rate_prediction_eq17(
    block: pd.DataFrame,
    train: pd.DataFrame,
    test: pd.DataFrame,
    test_season: int,
    max_neighbors: int,
) -> Tuple[np.ndarray, bool, int]:
    adjustment, feature_count = evaluate_stage(train, test, PRODUCTION_FEATURES, max_neighbors)
    choice = hard_gate_choice(block, test_season, max_neighbors)
    enabled = bool(choice.get("enabled", False))
    base = pd.to_numeric(test["pacePrimaryEq17"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
    return base + (adjustment if enabled else 0.0), enabled, feature_count if enabled else 0


def availability_rate_for_strategy(
    strategy: str,
    train: pd.DataFrame,
    test: pd.DataFrame,
    max_neighbors: int,
) -> Tuple[np.ndarray, int]:
    if strategy == "full_available":
        return np.ones(len(test), dtype=float), 0
    if strategy == "current_availability":
        values = pd.to_numeric(test["availability_rate"], errors="coerce").fillna(1.0).clip(0.0, 1.0)
        return values.to_numpy(dtype=float), 1
    if strategy == "prior_availability":
        values = pd.to_numeric(test["prior_availability_rate"], errors="coerce").fillna(1.0).clip(0.0, 1.0)
        return values.to_numpy(dtype=float), 1
    if strategy == "health_knn":
        return health_knn_availability(train, test, max_neighbors)
    raise ValueError(f"Unknown availability strategy: {strategy}")


def total_prediction_frame(
    test: pd.DataFrame,
    rate_eq17: np.ndarray,
    availability_rate: np.ndarray,
    stage: str,
    strategy: str,
) -> pd.DataFrame:
    current_primary = pd.to_numeric(test["currentPrimary"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
    current_games = pd.to_numeric(test["games"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
    remaining_team = pd.to_numeric(test["remainingTeamGames"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
    predicted_remaining_games = np.clip(availability_rate, 0.0, 1.0) * remaining_team
    predicted_total = current_primary + (rate_eq17 / 17.0) * predicted_remaining_games
    frame = test[
        [
            "season",
            "checkpoint",
            "position",
            "playerKey",
            "playerName",
            "team",
            "finalPrimary",
            "finalGames",
            "currentPrimary",
            "games",
            "remainingTeamGames",
        ]
    ].copy()
    frame["stage"] = stage
    frame["availabilityStrategy"] = strategy
    frame["prediction"] = predicted_total
    frame["predictedRemainingGames"] = predicted_remaining_games
    frame["predictedFinalGames"] = current_games + predicted_remaining_games
    return frame


def strategy_validation(
    block: pd.DataFrame,
    before_season: int,
    strategy: str,
    max_neighbors: int,
) -> dict:
    frames: List[pd.DataFrame] = []
    season_rows: List[dict] = []
    seasons = sorted(int(value) for value in block["season"].dropna().unique() if int(value) < before_season)
    for validation_season in seasons:
        validation = block[block["season"] == validation_season].copy()
        train = block[block["season"] < validation_season].copy()
        if len(validation) < MIN_TEST_ROWS or len(train) < MIN_TRAIN_ROWS:
            continue
        rate_eq17, _history_enabled, _count = rate_prediction_eq17(
            block, train, validation, validation_season, max_neighbors
        )
        availability_rate, _feature_count = availability_rate_for_strategy(
            strategy, train, validation, max_neighbors
        )
        frame = total_prediction_frame(
            validation, rate_eq17, availability_rate, "validation", strategy
        )
        frames.append(frame)
        error = np.abs(
            pd.to_numeric(frame["finalPrimary"], errors="coerce").to_numpy(dtype=float)
            - pd.to_numeric(frame["prediction"], errors="coerce").to_numpy(dtype=float)
        )
        game_error = np.abs(
            pd.to_numeric(frame["finalGames"], errors="coerce").to_numpy(dtype=float)
            - pd.to_numeric(frame["predictedFinalGames"], errors="coerce").to_numpy(dtype=float)
        )
        season_rows.append(
            {
                "season": validation_season,
                "mae": float(np.nanmean(error)),
                "gamesMae": float(np.nanmean(game_error)),
            }
        )
    if not frames:
        return {"blocks": 0, "mae": np.nan, "gamesMae": np.nan, "recentMae": np.nan}
    merged = pd.concat(frames, ignore_index=True)
    errors = np.abs(
        pd.to_numeric(merged["finalPrimary"], errors="coerce").to_numpy(dtype=float)
        - pd.to_numeric(merged["prediction"], errors="coerce").to_numpy(dtype=float)
    )
    game_errors = np.abs(
        pd.to_numeric(merged["finalGames"], errors="coerce").to_numpy(dtype=float)
        - pd.to_numeric(merged["predictedFinalGames"], errors="coerce").to_numpy(dtype=float)
    )
    season_df = pd.DataFrame(season_rows)
    recent_seasons = sorted(season_df["season"].unique())[-4:]
    recent_mae = float(season_df[season_df["season"].isin(recent_seasons)]["mae"].mean())
    return {
        "blocks": int(len(season_df)),
        "mae": float(np.nanmean(errors)),
        "gamesMae": float(np.nanmean(game_errors)),
        "recentMae": recent_mae,
    }


def choose_strategy(block: pd.DataFrame, before_season: int, max_neighbors: int) -> dict:
    rows: List[dict] = []
    for strategy in STRATEGIES:
        summary = strategy_validation(block, before_season, strategy, max_neighbors)
        rows.append({"strategy": strategy, **summary})
    valid = [
        row for row in rows
        if int(row["blocks"]) >= MIN_VALIDATION_BLOCKS and math.isfinite(safe_float(row["mae"], np.nan))
    ]
    if not valid:
        chosen = next(row for row in rows if row["strategy"] == "full_available")
    else:
        best_mae = min(float(row["mae"]) for row in valid)
        tolerance = best_mae * TIE_TOLERANCE_PCT / 100.0
        near_best = [row for row in valid if float(row["mae"]) <= best_mae + tolerance]
        chosen = sorted(
            near_best,
            key=lambda row: (STRATEGY_COMPLEXITY[row["strategy"]], float(row["mae"]), row["strategy"]),
        )[0]
    return {"strategy": chosen["strategy"], "validation": chosen, "table": rows}


def aggregate(predictions: pd.DataFrame, group_columns: Sequence[str]) -> pd.DataFrame:
    groups = predictions[list(group_columns)].drop_duplicates().to_dict("records") if group_columns else [{}]
    rows: List[dict] = []
    for group in groups:
        block = predictions.copy()
        for column, value in group.items():
            block = block[block[column] == value]
        stage_metrics: Dict[str, dict] = {}
        for stage in ["00_pace_full_availability", "11_rate_gate_full_availability", "12_rate_gate_selected_availability"]:
            frame = block[block["stage"] == stage]
            if frame.empty:
                stage_metrics[stage] = {"mae": np.nan, "gamesMae": np.nan, "rows": 0}
                continue
            error = np.abs(
                pd.to_numeric(frame["finalPrimary"], errors="coerce").to_numpy(dtype=float)
                - pd.to_numeric(frame["prediction"], errors="coerce").to_numpy(dtype=float)
            )
            game_error = np.abs(
                pd.to_numeric(frame["finalGames"], errors="coerce").to_numpy(dtype=float)
                - pd.to_numeric(frame["predictedFinalGames"], errors="coerce").to_numpy(dtype=float)
            )
            stage_metrics[stage] = {
                "mae": float(np.nanmean(error)),
                "gamesMae": float(np.nanmean(game_error)),
                "rows": int(len(frame)),
            }
        pace = stage_metrics["00_pace_full_availability"]
        rate = stage_metrics["11_rate_gate_full_availability"]
        selected = stage_metrics["12_rate_gate_selected_availability"]
        rows.append(
            {
                **group,
                "rows": selected["rows"],
                "paceFullAvailMae": pace["mae"],
                "rateGateFullAvailMae": rate["mae"],
                "availabilityMae": selected["mae"],
                "rateGateImprovementPctVsPace": improvement_pct(pace["mae"], rate["mae"]),
                "availabilityIncrementalPctVsRateGate": improvement_pct(rate["mae"], selected["mae"]),
                "availabilityImprovementPctVsPace": improvement_pct(pace["mae"], selected["mae"]),
                "fullAvailGamesMae": rate["gamesMae"],
                "selectedGamesMae": selected["gamesMae"],
                "gamesMaeImprovementPct": improvement_pct(rate["gamesMae"], selected["gamesMae"]),
            }
        )
    return pd.DataFrame(rows)


def policy_table(position_checkpoint: pd.DataFrame, selections: pd.DataFrame) -> pd.DataFrame:
    rows: List[dict] = []
    for metric in position_checkpoint.to_dict("records"):
        position = str(metric.get("position") or "")
        checkpoint = int(metric.get("checkpoint") or 0)
        block = selections[(selections["position"] == position) & (selections["checkpoint"] == checkpoint)]
        counts = block["selectedAvailabilityStrategy"].value_counts().to_dict() if not block.empty else {}
        total = int(sum(counts.values()))
        top_strategy = "full_available"
        top_pct = 0.0
        if counts:
            top_strategy, top_count = sorted(counts.items(), key=lambda item: (-item[1], STRATEGY_COMPLEXITY.get(item[0], 9), item[0]))[0]
            top_pct = 100.0 * float(top_count) / total
        incremental = safe_float(metric.get("availabilityIncrementalPctVsRateGate"), np.nan)
        games_improvement = safe_float(metric.get("gamesMaeImprovementPct"), np.nan)
        recommendation = "availability-layer" if math.isfinite(incremental) and incremental > 0.0 else "full-availability-baseline"
        rows.append(
            {
                "position": position,
                "checkpoint": checkpoint,
                "topAvailabilityStrategy": top_strategy,
                "topStrategyPct": top_pct,
                "availabilityIncrementalPctVsRateGate": incremental,
                "gamesMaeImprovementPct": games_improvement,
                "availabilityRecommendation": recommendation,
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--features", type=Path, default=Path("model-lab/output/v19-player-features/player_features.csv"))
    parser.add_argument("--out", type=Path, default=Path("model-lab/output/v19-player-availability"))
    parser.add_argument("--test-start", type=int, default=2014)
    parser.add_argument("--max-neighbors", type=int, default=MAX_NEIGHBORS)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    data = pd.read_csv(args.features, low_memory=False)
    required = {
        "season", "checkpoint", "position", "playerKey", "targetPrimaryEq17", "pacePrimaryEq17",
        "games", "finalGames", "currentPrimary", "finalPrimary", "availability_rate", "injury_context_delta",
    }
    missing = sorted(required - set(data.columns))
    if missing:
        raise RuntimeError(f"Missing required feature columns: {missing}")
    data["season"] = pd.to_numeric(data["season"], errors="coerce").astype("Int64")
    data["checkpoint"] = pd.to_numeric(data["checkpoint"], errors="coerce").astype("Int64")
    for column in ["targetPrimaryEq17", "pacePrimaryEq17", "games", "finalGames", "currentPrimary", "finalPrimary", "availability_rate", "injury_context_delta"]:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    data = data[
        data["targetPrimaryEq17"].notna()
        & data["pacePrimaryEq17"].notna()
        & data["finalPrimary"].notna()
        & data["finalGames"].notna()
    ].copy()
    data["paceResidual"] = data["targetPrimaryEq17"] - data["pacePrimaryEq17"]
    data = enrich_availability_columns(data)

    predictions: List[pd.DataFrame] = []
    selection_rows: List[dict] = []
    trace_rows: List[dict] = []
    seasons = sorted(int(value) for value in data["season"].dropna().unique() if int(value) >= args.test_start)

    for position in sorted(data["position"].dropna().unique()):
        position_data = data[data["position"] == position]
        for checkpoint in sorted(int(value) for value in position_data["checkpoint"].dropna().unique()):
            block = position_data[position_data["checkpoint"] == checkpoint].copy()
            for test_season in seasons:
                test = block[block["season"] == test_season].copy()
                train = block[block["season"] < test_season].copy()
                if len(test) < MIN_TEST_ROWS or len(train) < MIN_TRAIN_ROWS:
                    continue

                rate_eq17, history_enabled, rate_feature_count = rate_prediction_eq17(
                    block, train, test, test_season, args.max_neighbors
                )
                pace_eq17 = pd.to_numeric(test["pacePrimaryEq17"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
                full_availability = np.ones(len(test), dtype=float)

                pace_frame = total_prediction_frame(
                    test, pace_eq17, full_availability, "00_pace_full_availability", "full_available"
                )
                rate_frame = total_prediction_frame(
                    test, rate_eq17, full_availability, "11_rate_gate_full_availability", "full_available"
                )

                choice = choose_strategy(block, test_season, args.max_neighbors)
                strategy = str(choice["strategy"])
                selected_rate, availability_feature_count = availability_rate_for_strategy(
                    strategy, train, test, args.max_neighbors
                )
                selected_frame = total_prediction_frame(
                    test, rate_eq17, selected_rate, "12_rate_gate_selected_availability", strategy
                )
                predictions.extend([pace_frame, rate_frame, selected_frame])

                selection_rows.append(
                    {
                        "season": test_season,
                        "position": position,
                        "checkpoint": checkpoint,
                        "historyEnabled": history_enabled,
                        "rateFeatureCount": rate_feature_count,
                        "selectedAvailabilityStrategy": strategy,
                        "availabilityFeatureCount": availability_feature_count,
                        "validationBlocks": int(choice["validation"].get("blocks", 0)),
                        "validationMae": safe_float(choice["validation"].get("mae"), np.nan),
                        "validationGamesMae": safe_float(choice["validation"].get("gamesMae"), np.nan),
                    }
                )
                for item in choice["table"]:
                    trace_rows.append(
                        {
                            "outerSeason": test_season,
                            "position": position,
                            "checkpoint": checkpoint,
                            "candidateStrategy": item["strategy"],
                            "validationBlocks": item["blocks"],
                            "validationMae": item["mae"],
                            "validationGamesMae": item["gamesMae"],
                            "validationRecentMae": item["recentMae"],
                            "selected": item["strategy"] == strategy,
                        }
                    )

    prediction_df = pd.concat(predictions, ignore_index=True) if predictions else pd.DataFrame()
    if prediction_df.empty:
        raise RuntimeError("No v1.9g availability predictions were produced")
    selection_df = pd.DataFrame(selection_rows)
    trace_df = pd.DataFrame(trace_rows)

    overall = aggregate(prediction_df, [])
    position = aggregate(prediction_df, ["position"])
    position_checkpoint = aggregate(prediction_df, ["position", "checkpoint"])
    policy = policy_table(position_checkpoint, selection_df)

    prediction_df.to_csv(args.out / "availability_predictions.csv", index=False)
    selection_df.to_csv(args.out / "availability_selection_history.csv", index=False)
    trace_df.to_csv(args.out / "availability_selection_trace.csv", index=False)
    overall.to_csv(args.out / "availability_overall_summary.csv", index=False)
    position.to_csv(args.out / "availability_position_summary.csv", index=False)
    position_checkpoint.to_csv(args.out / "availability_position_checkpoint_summary.csv", index=False)
    policy.to_csv(args.out / "availability_policy.csv", index=False)

    report = {
        "lab": "GRIDIRON PULSE v1.9g availability / games-played layer",
        "researchOnly": True,
        "productionWeightsSelected": False,
        "rateModel": "v1.9f prior-only production/usage history gate with environment removed",
        "availabilityStrategies": list(STRATEGIES),
        "availabilityTarget": "remaining player games through the regular-season schedule; actual season-total production is the scoring target",
        "scheduleAssumption": "16 regular-season games through 2020; 17 from 2021 onward",
        "selection": "Each held-out season chooses availability strategy using only nested validation seasons before that season, minimizing finalPrimary MAE.",
        "overall": overall.to_dict("records"),
        "positionCheckpoint": position_checkpoint.to_dict("records"),
        "policy": policy.to_dict("records"),
    }
    (args.out / "availability_summary.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    main()
