#!/usr/bin/env python3
"""GRIDIRON PULSE v1.9d nested historical-comparable shrinkage backtest.

Learns how much of the historical comparable residual adjustment to trust at
Weeks 4/8/12 for QB/RB/WR/TE. Every outer held-out season chooses its history
weight using only earlier seasons, so the season being judged cannot influence
its own weight.

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

from v19_player_comparable_backtest import metrics, safe_float
from v19_player_isolated_environment_backtest import (
    PRODUCTION_FEATURES,
    evaluate_stage,
    improvement_pct,
    make_prediction_frame,
)

WEIGHTS: Tuple[float, ...] = (0.0, 0.25, 0.50, 0.75, 1.0)
MIN_TEST_ROWS = 5
MIN_TRAIN_ROWS = 25
MIN_VALIDATION_BLOCKS = 2
TIE_TOLERANCE_PCT = 0.10


def prediction_from_adjustment(test: pd.DataFrame, stage: str, adjustment: np.ndarray, weight: float, feature_count: int) -> pd.DataFrame:
    result = make_prediction_frame(test, stage, adjustment * float(weight), feature_count)
    result["historyWeight"] = float(weight)
    return result


def production_adjustment(train: pd.DataFrame, test: pd.DataFrame, max_neighbors: int) -> Tuple[np.ndarray, int]:
    return evaluate_stage(train, test, PRODUCTION_FEATURES, max_neighbors)


def validation_predictions(block: pd.DataFrame, before_season: int, max_neighbors: int) -> pd.DataFrame:
    rows: List[pd.DataFrame] = []
    seasons = sorted(int(value) for value in block["season"].dropna().unique() if int(value) < before_season)
    for validation_season in seasons:
        validation = block[block["season"] == validation_season].copy()
        train = block[block["season"] < validation_season].copy()
        if len(validation) < MIN_TEST_ROWS or len(train) < MIN_TRAIN_ROWS:
            continue
        adjustment, count = production_adjustment(train, validation, max_neighbors)
        for weight in WEIGHTS:
            frame = prediction_from_adjustment(validation, f"weight_{weight:.2f}", adjustment, weight, count)
            frame["validationSeason"] = validation_season
            rows.append(frame)
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def choose_weight(block: pd.DataFrame, before_season: int, max_neighbors: int) -> dict:
    validation = validation_predictions(block, before_season, max_neighbors)
    if validation.empty:
        return {
            "weight": 0.0,
            "validationBlocks": 0,
            "validationMae": np.nan,
            "paceMae": np.nan,
            "improvementPctVsPace": np.nan,
            "weightTable": [],
        }
    table: List[dict] = []
    for weight in WEIGHTS:
        stage = f"weight_{weight:.2f}"
        frame = validation[validation["stage"] == stage]
        metric = metrics(frame, "prediction")
        blocks = int(frame["validationSeason"].nunique()) if not frame.empty else 0
        table.append({"weight": weight, "mae": metric["mae"], "blocks": blocks})
    pace = next((row for row in table if abs(row["weight"]) < 1e-12), None)
    valid = [row for row in table if row["blocks"] >= MIN_VALIDATION_BLOCKS and math.isfinite(safe_float(row["mae"], np.nan))]
    if not valid:
        return {
            "weight": 0.0,
            "validationBlocks": max((row["blocks"] for row in table), default=0),
            "validationMae": pace["mae"] if pace else np.nan,
            "paceMae": pace["mae"] if pace else np.nan,
            "improvementPctVsPace": 0.0,
            "weightTable": table,
        }
    best_mae = min(row["mae"] for row in valid)
    tolerance = best_mae * TIE_TOLERANCE_PCT / 100.0
    near_best = [row for row in valid if row["mae"] <= best_mae + tolerance]
    chosen = sorted(near_best, key=lambda row: (row["weight"], row["mae"]))[0]
    pace_mae = safe_float(pace.get("mae") if pace else np.nan, np.nan)
    return {
        "weight": float(chosen["weight"]),
        "validationBlocks": int(chosen["blocks"]),
        "validationMae": float(chosen["mae"]),
        "paceMae": pace_mae,
        "improvementPctVsPace": improvement_pct(pace_mae, chosen["mae"]),
        "weightTable": table,
    }


def aggregate(predictions: pd.DataFrame, group_columns: Sequence[str]) -> pd.DataFrame:
    groups = predictions[list(group_columns)].drop_duplicates().to_dict("records") if group_columns else [{}]
    rows: List[dict] = []
    for group in groups:
        block = predictions.copy()
        for column, value in group.items():
            block = block[block[column] == value]
        pace = metrics(block[block["stage"] == "00_pace_baseline"], "prediction")
        full = metrics(block[block["stage"] == "01_full_history_reference"], "prediction")
        shrink = metrics(block[block["stage"] == "10_nested_history_shrinkage"], "prediction")
        rows.append({
            **group,
            "rows": shrink["rows"],
            "paceMae": pace["mae"],
            "fullHistoryMae": full["mae"],
            "shrinkageMae": shrink["mae"],
            "shrinkageImprovementPctVsPace": improvement_pct(pace["mae"], shrink["mae"]),
            "shrinkageImprovementPctVsFullHistory": improvement_pct(full["mae"], shrink["mae"]),
            "fullHistoryImprovementPctVsPace": improvement_pct(pace["mae"], full["mae"]),
        })
    return pd.DataFrame(rows)


def recommended_policy(position_checkpoint: pd.DataFrame, selection: pd.DataFrame) -> pd.DataFrame:
    rows: List[dict] = []
    for metric_row in position_checkpoint.to_dict("records"):
        position = str(metric_row.get("position") or "")
        checkpoint = int(metric_row.get("checkpoint") or 0)
        picked = selection[(selection["position"] == position) & (selection["checkpoint"] == checkpoint)]
        weight_counts: Dict[float, int] = {}
        if not picked.empty:
            for weight, count in picked["selectedHistoryWeight"].value_counts().items():
                weight_counts[float(weight)] = int(count)
        total = sum(weight_counts.values())
        mean_weight = float(picked["selectedHistoryWeight"].mean()) if not picked.empty else 0.0
        median_weight = float(picked["selectedHistoryWeight"].median()) if not picked.empty else 0.0
        mode_weight = 0.0
        if weight_counts:
            mode_weight = sorted(weight_counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
        vs_pace = safe_float(metric_row.get("shrinkageImprovementPctVsPace"), np.nan)
        if not math.isfinite(vs_pace) or vs_pace <= 0.0:
            label = "current-season-dominant"
        elif mean_weight >= 0.70:
            label = "strong-history"
        elif mean_weight >= 0.35:
            label = "blended-history"
        elif mean_weight > 0.0:
            label = "light-history"
        else:
            label = "current-season-dominant"
        rows.append({
            "position": position,
            "checkpoint": checkpoint,
            "outerSeasons": total,
            "meanSelectedHistoryWeight": mean_weight,
            "medianSelectedHistoryWeight": median_weight,
            "modeSelectedHistoryWeight": mode_weight,
            "weight0Pct": 100.0 * weight_counts.get(0.0, 0) / total if total else np.nan,
            "weight25Pct": 100.0 * weight_counts.get(0.25, 0) / total if total else np.nan,
            "weight50Pct": 100.0 * weight_counts.get(0.50, 0) / total if total else np.nan,
            "weight75Pct": 100.0 * weight_counts.get(0.75, 0) / total if total else np.nan,
            "weight100Pct": 100.0 * weight_counts.get(1.0, 0) / total if total else np.nan,
            "shrinkageImprovementPctVsPace": vs_pace,
            "shrinkageImprovementPctVsFullHistory": safe_float(metric_row.get("shrinkageImprovementPctVsFullHistory"), np.nan),
            "historyRecommendation": label,
        })
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--features", type=Path, default=Path("model-lab/output/v19-player-features/player_features.csv"))
    parser.add_argument("--out", type=Path, default=Path("model-lab/output/v19-player-history-blend"))
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

                adjustment, feature_count = production_adjustment(train, test, args.max_neighbors)
                pace = prediction_from_adjustment(test, "00_pace_baseline", adjustment, 0.0, feature_count)
                full = prediction_from_adjustment(test, "01_full_history_reference", adjustment, 1.0, feature_count)
                choice = choose_weight(block, test_season, args.max_neighbors)
                selected_weight = float(choice["weight"])
                shrink = prediction_from_adjustment(test, "10_nested_history_shrinkage", adjustment, selected_weight, feature_count)
                predictions.extend([pace, full, shrink])
                selection_rows.append({
                    "season": test_season,
                    "position": position,
                    "checkpoint": checkpoint,
                    "selectedHistoryWeight": selected_weight,
                    "validationBlocks": choice["validationBlocks"],
                    "validationMae": choice["validationMae"],
                    "validationPaceMae": choice["paceMae"],
                    "validationImprovementPctVsPace": choice["improvementPctVsPace"],
                })
                for item in choice["weightTable"]:
                    trace_rows.append({
                        "outerSeason": test_season,
                        "position": position,
                        "checkpoint": checkpoint,
                        "candidateWeight": item["weight"],
                        "validationMae": item["mae"],
                        "validationBlocks": item["blocks"],
                        "selected": abs(float(item["weight"]) - selected_weight) < 1e-12,
                    })

    prediction_df = pd.concat(predictions, ignore_index=True) if predictions else pd.DataFrame()
    if prediction_df.empty:
        raise RuntimeError("No v1.9d predictions were produced")
    selection_df = pd.DataFrame(selection_rows)
    trace_df = pd.DataFrame(trace_rows)
    overall = aggregate(prediction_df, [])
    position_summary = aggregate(prediction_df, ["position"])
    position_checkpoint = aggregate(prediction_df, ["position", "checkpoint"])
    policy = recommended_policy(position_checkpoint, selection_df)

    prediction_df.to_csv(args.out / "history_blend_predictions.csv", index=False)
    selection_df.to_csv(args.out / "history_blend_selection_history.csv", index=False)
    trace_df.to_csv(args.out / "history_blend_selection_trace.csv", index=False)
    overall.to_csv(args.out / "history_blend_overall_summary.csv", index=False)
    position_summary.to_csv(args.out / "history_blend_position_summary.csv", index=False)
    position_checkpoint.to_csv(args.out / "history_blend_position_checkpoint_summary.csv", index=False)
    policy.to_csv(args.out / "history_blend_policy.csv", index=False)

    report = {
        "lab": "GRIDIRON PULSE v1.9d nested historical-comparable shrinkage",
        "researchOnly": True,
        "productionWeightsSelected": False,
        "testStart": args.test_start,
        "testEnd": int(data["season"].max()),
        "candidateHistoryWeights": list(WEIGHTS),
        "selection": "Each outer season chooses its history weight using only rolling validation seasons before that outer season.",
        "tieBreak": "If candidate MAEs are within 0.10%, prefer the lighter historical weight.",
        "overall": overall.to_dict("records"),
        "positionCheckpoint": position_checkpoint.to_dict("records"),
        "policy": policy.to_dict("records"),
    }
    (args.out / "history_blend_summary.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    main()
