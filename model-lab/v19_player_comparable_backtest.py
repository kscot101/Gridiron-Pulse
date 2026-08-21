#!/usr/bin/env python3
"""Rolling no-lookahead backtest for GRIDIRON PULSE v1.9 player comparables.

The model predicts a residual adjustment to a simple checkpoint pace baseline.
Feature stages are added in the promotion order from the v1.9 research plan.
All feature scaling and comparable selection use only seasons before the held-out
season. This script is research-only and does not choose production weights.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import List, Sequence, Tuple

import numpy as np
import pandas as pd

STAGES: List[Tuple[str, List[str]]] = [
    ("01_production_usage", ["current_primary_pg", "recent3_primary_pg", "primary_volatility", "opportunity_pg", "opportunity_share", "efficiency_1", "efficiency_2", "td_rate", "epa_per_opportunity", "prior_primary_pg", "prior_opportunity_share", "years_experience", "established_player_score"]),
    ("02_role", ["snap_share", "depth_rank", "starter_flag", "role_delta"]),
    ("03_health", ["availability_rate", "injury_burden", "out_report_rate", "injury_context_delta"]),
    ("04_qb_environment", ["qb_quality_delta", "qb_delta_x_prior_share", "qb_delta_x_established"]),
    ("05_coach_scheme", ["coach_continuity_score", "scheme_position_usage_delta", "scheme_concentration_delta", "team_pass_rate_delta"]),
    ("06_trade_team_change", ["changed_teams", "team_offense_delta", "team_change_x_established"]),
    ("07_opportunity_competition", ["vacated_opportunity_pct", "incoming_competition_pct", "competition_delta", "opportunity_delta"]),
]


def safe_float(value: object, default: float = np.nan) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def robust_scale(train: pd.DataFrame, test: pd.DataFrame, columns: Sequence[str]):
    train_parts = []
    test_parts = []
    used = []
    for column in columns:
        if column not in train.columns or column not in test.columns:
            continue
        tr = pd.to_numeric(train[column], errors="coerce")
        te = pd.to_numeric(test[column], errors="coerce")
        median = tr.median()
        if not math.isfinite(safe_float(median, np.nan)):
            median = 0.0
        scale = safe_float(tr.quantile(0.75) - tr.quantile(0.25), 0.0)
        if scale < 1e-9:
            sd = safe_float(tr.std(ddof=0), 0.0)
            scale = sd if sd >= 1e-9 else 1.0
        train_parts.append(((tr.fillna(median) - median) / scale).to_numpy(dtype=float))
        test_parts.append(((te.fillna(median) - median) / scale).to_numpy(dtype=float))
        used.append(column)
    if not train_parts:
        return np.zeros((len(train), 0)), np.zeros((len(test), 0)), []
    return np.column_stack(train_parts), np.column_stack(test_parts), used


def nearest_residuals(train_x: np.ndarray, test_x: np.ndarray, train_residual: np.ndarray, train_meta: pd.DataFrame, test_meta: pd.DataFrame, max_neighbors: int):
    predictions = np.zeros(len(test_x), dtype=float)
    samples = []
    if len(train_x) == 0 or train_x.shape[1] == 0:
        return predictions, samples
    k = min(max_neighbors, max(10, int(round(math.sqrt(len(train_x))))), len(train_x))
    for i, vector in enumerate(test_x):
        distances = np.sqrt(np.mean(np.square(train_x - vector), axis=1))
        order = np.argsort(distances)[:k]
        chosen_dist = distances[order]
        weights = 1.0 / np.maximum(chosen_dist + 0.15, 0.15)
        weights = weights / weights.sum()
        predictions[i] = float(np.sum(train_residual[order] * weights))
        if len(samples) < 250:
            test_row = test_meta.iloc[i]
            for rank, idx in enumerate(order[:5], start=1):
                comp = train_meta.iloc[int(idx)]
                samples.append({
                    "testSeason": int(test_row["season"]),
                    "checkpoint": int(test_row["checkpoint"]),
                    "position": test_row["position"],
                    "playerKey": test_row["playerKey"],
                    "playerName": test_row.get("playerName", test_row["playerKey"]),
                    "comparableRank": rank,
                    "comparableSeason": int(comp["season"]),
                    "comparablePlayerKey": comp["playerKey"],
                    "comparablePlayerName": comp.get("playerName", comp["playerKey"]),
                    "distance": float(chosen_dist[rank - 1]),
                    "comparableResidual": float(train_residual[int(idx)]),
                })
    return predictions, samples


def metrics(frame: pd.DataFrame, prediction_column: str) -> dict:
    if frame.empty:
        return {"rows": 0, "mae": np.nan, "rmse": np.nan, "bias": np.nan}
    target = pd.to_numeric(frame["targetPrimaryEq17"], errors="coerce").to_numpy(dtype=float)
    pred = pd.to_numeric(frame[prediction_column], errors="coerce").to_numpy(dtype=float)
    error = pred - target
    return {"rows": int(len(frame)), "mae": float(np.mean(np.abs(error))), "rmse": float(np.sqrt(np.mean(np.square(error)))), "bias": float(np.mean(error))}


def cumulative_stage_features():
    output = []
    cumulative = []
    for stage, features in STAGES:
        cumulative.extend(features)
        output.append((stage, list(dict.fromkeys(cumulative))))
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--features", type=Path, default=Path("model-lab/output/v19-player-features/player_features.csv"))
    parser.add_argument("--out", type=Path, default=Path("model-lab/output/v19-player-backtest"))
    parser.add_argument("--test-start", type=int, default=2014)
    parser.add_argument("--max-neighbors", type=int, default=35)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    data = pd.read_csv(args.features, low_memory=False)
    required = {"season", "checkpoint", "position", "playerKey", "targetPrimaryEq17", "pacePrimaryEq17"}
    missing = sorted(required - set(data.columns))
    if missing:
        raise RuntimeError(f"Missing required feature columns: {missing}")
    data["season"] = pd.to_numeric(data["season"], errors="coerce").astype("Int64")
    data["checkpoint"] = pd.to_numeric(data["checkpoint"], errors="coerce").astype("Int64")
    data["targetPrimaryEq17"] = pd.to_numeric(data["targetPrimaryEq17"], errors="coerce")
    data["pacePrimaryEq17"] = pd.to_numeric(data["pacePrimaryEq17"], errors="coerce")
    data = data[data["targetPrimaryEq17"].notna() & data["pacePrimaryEq17"].notna()].copy()
    data["paceResidual"] = data["targetPrimaryEq17"] - data["pacePrimaryEq17"]
    stage_predictions = []
    season_metrics = []
    comparable_samples = []
    stage_definitions = cumulative_stage_features()
    seasons = sorted(int(value) for value in data["season"].dropna().unique() if int(value) >= args.test_start)
    for position in sorted(data["position"].dropna().unique()):
        for checkpoint in sorted(int(value) for value in data[data["position"] == position]["checkpoint"].dropna().unique()):
            block = data[(data["position"] == position) & (data["checkpoint"] == checkpoint)].copy()
            for test_season in seasons:
                test = block[block["season"] == test_season].copy()
                train = block[block["season"] < test_season].copy()
                if len(test) < 5 or len(train) < 25:
                    continue
                base = test[["season", "checkpoint", "position", "playerKey", "playerName", "team", "targetPrimaryEq17", "pacePrimaryEq17"]].copy()
                base["stage"] = "00_pace_baseline"
                base["prediction"] = base["pacePrimaryEq17"]
                stage_predictions.append(base)
                season_metrics.append({"season": test_season, "checkpoint": checkpoint, "position": position, "stage": "00_pace_baseline", **metrics(base, "prediction")})
                for stage, feature_columns in stage_definitions:
                    train_x, test_x, used = robust_scale(train, test, feature_columns)
                    if not used:
                        continue
                    residual_pred, samples = nearest_residuals(train_x, test_x, train["paceResidual"].to_numpy(dtype=float), train[["season", "checkpoint", "position", "playerKey", "playerName"]].reset_index(drop=True), test[["season", "checkpoint", "position", "playerKey", "playerName"]].reset_index(drop=True), args.max_neighbors)
                    result = test[["season", "checkpoint", "position", "playerKey", "playerName", "team", "targetPrimaryEq17", "pacePrimaryEq17"]].copy()
                    result["stage"] = stage
                    result["prediction"] = test["pacePrimaryEq17"].to_numpy(dtype=float) + residual_pred
                    result["rawComparableAdjustment"] = residual_pred
                    result["featureCount"] = len(used)
                    stage_predictions.append(result)
                    season_metrics.append({"season": test_season, "checkpoint": checkpoint, "position": position, "stage": stage, "featureCount": len(used), **metrics(result, "prediction")})
                    if test_season == max(seasons) and stage == stage_definitions[-1][0]:
                        for sample in samples:
                            sample["stage"] = stage
                        comparable_samples.extend(samples)
    predictions = pd.concat(stage_predictions, ignore_index=True) if stage_predictions else pd.DataFrame()
    season_df = pd.DataFrame(season_metrics)
    sample_df = pd.DataFrame(comparable_samples)
    summary_rows = []
    promotion_rows = []
    stage_order = ["00_pace_baseline"] + [name for name, _ in stage_definitions]
    for stage in stage_order:
        stage_pred = predictions[predictions["stage"] == stage]
        metric = metrics(stage_pred, "prediction") if not stage_pred.empty else {"rows": 0, "mae": np.nan, "rmse": np.nan, "bias": np.nan}
        pace_pred = predictions[predictions["stage"] == "00_pace_baseline"]
        pace = metrics(pace_pred, "prediction") if not pace_pred.empty else {"mae": np.nan}
        prev_stage = stage_order[max(0, stage_order.index(stage) - 1)]
        prev_pred = predictions[predictions["stage"] == prev_stage]
        prev = metrics(prev_pred, "prediction") if not prev_pred.empty else {"mae": np.nan}
        improvement_pace = 100.0 * (pace["mae"] - metric["mae"]) / pace["mae"] if stage != "00_pace_baseline" and safe_float(pace["mae"], 0.0) > 0 else 0.0
        improvement_prev = 100.0 * (prev["mae"] - metric["mae"]) / prev["mae"] if stage != "00_pace_baseline" and safe_float(prev["mae"], 0.0) > 0 else 0.0
        season_win_pct = np.nan
        recent_delta_pct = np.nan
        if stage != "00_pace_baseline" and not season_df.empty:
            current_season = season_df[season_df["stage"] == stage][["season", "checkpoint", "position", "mae"]].rename(columns={"mae": "current_mae"})
            previous_season = season_df[season_df["stage"] == prev_stage][["season", "checkpoint", "position", "mae"]].rename(columns={"mae": "previous_mae"})
            merged = current_season.merge(previous_season, on=["season", "checkpoint", "position"], how="inner")
            if not merged.empty:
                season_win_pct = float((merged["current_mae"] <= merged["previous_mae"]).mean() * 100.0)
                recent = merged[merged["season"] >= max(args.test_start, int(data["season"].max()) - 3)]
                if not recent.empty and recent["previous_mae"].mean() > 0:
                    recent_delta_pct = 100.0 * (recent["previous_mae"].mean() - recent["current_mae"].mean()) / recent["previous_mae"].mean()
        summary_rows.append({"stage": stage, **metric, "maeImprovementPctVsPace": improvement_pace, "maeImprovementPctVsPrevious": improvement_prev, "seasonBlockWinPctVsPrevious": season_win_pct, "recent4SeasonImprovementPctVsPrevious": recent_delta_pct})
        if stage != "00_pace_baseline":
            research_candidate = bool(improvement_prev > 0.0 and (not math.isfinite(safe_float(season_win_pct, np.nan)) or season_win_pct >= 55.0) and (not math.isfinite(safe_float(recent_delta_pct, np.nan)) or recent_delta_pct >= -0.5))
            promotion_rows.append({"stage": stage, "researchCandidate": research_candidate, "reason": "Improves prior stage with majority held-out block wins and no material recent regression." if research_candidate else "Keep research-only until held-out improvement is more consistent.", "maeImprovementPctVsPrevious": improvement_prev, "seasonBlockWinPctVsPrevious": season_win_pct, "recent4SeasonImprovementPctVsPrevious": recent_delta_pct})
    summary_df = pd.DataFrame(summary_rows)
    promotion_df = pd.DataFrame(promotion_rows)
    predictions.to_csv(args.out / "backtest_predictions.csv", index=False)
    season_df.to_csv(args.out / "season_metrics.csv", index=False)
    summary_df.to_csv(args.out / "stage_summary.csv", index=False)
    promotion_df.to_csv(args.out / "promotion_candidates.csv", index=False)
    sample_df.to_csv(args.out / "sample_comparables.csv", index=False)
    result = {
        "lab": "GRIDIRON PULSE v1.9 rolling player comparable backtest",
        "researchOnly": True,
        "productionWeightsSelected": False,
        "testStart": args.test_start,
        "testEnd": int(data["season"].max()),
        "positions": sorted(data["position"].dropna().unique().tolist()),
        "checkpoints": sorted(int(value) for value in data["checkpoint"].dropna().unique()),
        "stageSummary": summary_df.to_dict("records"),
        "promotionCandidates": promotion_df.to_dict("records"),
        "method": {
            "baseline": "17-game-equivalent checkpoint pace",
            "comparableTarget": "held-out residual from pace baseline",
            "distance": "equal-weight robust-scaled Euclidean distance within position/checkpoint",
            "training": "strictly seasons before the held-out season",
            "neighbors": "sqrt(training rows), minimum 10, capped by max-neighbors",
            "productionIntegration": "not performed in this lab",
        },
    }
    (args.out / "backtest_summary.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    main()
