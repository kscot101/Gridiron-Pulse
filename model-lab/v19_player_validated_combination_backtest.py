#!/usr/bin/env python3
"""GRIDIRON PULSE v1.9c nested validated player-environment combination backtest.

This lab combines only environment groups that have already shown useful
prior-season evidence inside each outer held-out season. Signal selection is
strictly nested: the season being predicted is never used to decide which
signals enter that season's model.

Research only. This script does not set Season Worker production weights.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from v19_player_comparable_backtest import metrics, safe_float
from v19_player_isolated_environment_backtest import (
    ENVIRONMENT_GROUPS,
    PRODUCTION_FEATURES,
    evaluate_stage,
    improvement_pct,
    make_prediction_frame,
    unique_columns,
)

MIN_TEST_ROWS = 5
MIN_TRAIN_ROWS = 25
MIN_BASE_BLOCKS = 1
MIN_SIGNAL_BLOCKS = 2
BASE_MIN_IMPROVEMENT_PCT = 0.0
BASE_MIN_WIN_PCT = 50.0
BASE_MIN_RECENT_PCT = -0.5
SIGNAL_MIN_IMPROVEMENT_PCT = 0.50
SIGNAL_MIN_WIN_PCT = 55.0
SIGNAL_MIN_RECENT_PCT = 0.0
RESCUE_MIN_IMPROVEMENT_PCT = 1.0
RESCUE_MIN_WIN_PCT = 60.0
RESCUE_MIN_RECENT_PCT = 0.0
MAX_ENV_GROUPS = 2


def eligible_environment_groups(position: str) -> List[Tuple[str, List[str]]]:
    rows: List[Tuple[str, List[str]]] = []
    for stage, features, eligible, positions, _note in ENVIRONMENT_GROUPS:
        if eligible and position in positions:
            rows.append((stage, list(features)))
    return rows


def prediction_for_features(
    train: pd.DataFrame,
    test: pd.DataFrame,
    features: Optional[Sequence[str]],
    stage: str,
    max_neighbors: int,
) -> pd.DataFrame:
    if not features:
        return make_prediction_frame(test, stage, np.zeros(len(test), dtype=float), 0)
    adjustment, count = evaluate_stage(train, test, features, max_neighbors)
    return make_prediction_frame(test, stage, adjustment, count)


def validation_summary(
    block: pd.DataFrame,
    before_season: int,
    candidate_features: Optional[Sequence[str]],
    reference_features: Optional[Sequence[str]],
    max_neighbors: int,
) -> dict:
    candidate_frames: List[pd.DataFrame] = []
    reference_frames: List[pd.DataFrame] = []
    season_rows: List[dict] = []
    seasons = sorted(
        int(value)
        for value in block["season"].dropna().unique()
        if int(value) < before_season
    )
    for validation_season in seasons:
        validation = block[block["season"] == validation_season].copy()
        train = block[block["season"] < validation_season].copy()
        if len(validation) < MIN_TEST_ROWS or len(train) < MIN_TRAIN_ROWS:
            continue
        candidate = prediction_for_features(
            train,
            validation,
            candidate_features,
            "candidate",
            max_neighbors,
        )
        reference = prediction_for_features(
            train,
            validation,
            reference_features,
            "reference",
            max_neighbors,
        )
        candidate_frames.append(candidate)
        reference_frames.append(reference)
        cm = metrics(candidate, "prediction")
        rm = metrics(reference, "prediction")
        season_rows.append(
            {
                "season": validation_season,
                "candidateMae": cm["mae"],
                "referenceMae": rm["mae"],
                "improvementPct": improvement_pct(rm["mae"], cm["mae"]),
            }
        )
    if not season_rows:
        return {
            "blocks": 0,
            "improvementPct": np.nan,
            "winPct": np.nan,
            "recentImprovementPct": np.nan,
        }
    candidate_all = pd.concat(candidate_frames, ignore_index=True)
    reference_all = pd.concat(reference_frames, ignore_index=True)
    cm = metrics(candidate_all, "prediction")
    rm = metrics(reference_all, "prediction")
    season_df = pd.DataFrame(season_rows)
    recent_seasons = sorted(season_df["season"].unique())[-4:]
    recent = season_df[season_df["season"].isin(recent_seasons)]
    recent_candidate = recent["candidateMae"].mean()
    recent_reference = recent["referenceMae"].mean()
    return {
        "blocks": int(len(season_df)),
        "improvementPct": improvement_pct(rm["mae"], cm["mae"]),
        "winPct": float((season_df["candidateMae"] <= season_df["referenceMae"]).mean() * 100.0),
        "recentImprovementPct": improvement_pct(recent_reference, recent_candidate),
    }


def clears_gate(
    summary: Mapping[str, object],
    min_blocks: int,
    min_improvement: float,
    min_wins: float,
    min_recent: float,
) -> bool:
    blocks = int(safe_float(summary.get("blocks"), 0.0))
    improvement = safe_float(summary.get("improvementPct"), np.nan)
    wins = safe_float(summary.get("winPct"), np.nan)
    recent = safe_float(summary.get("recentImprovementPct"), np.nan)
    return bool(
        blocks >= min_blocks
        and math.isfinite(improvement)
        and improvement >= min_improvement
        and math.isfinite(wins)
        and wins >= min_wins
        and math.isfinite(recent)
        and recent >= min_recent
    )


def choose_nested_model(
    block: pd.DataFrame,
    position: str,
    test_season: int,
    max_neighbors: int,
) -> dict:
    base_validation = validation_summary(
        block,
        test_season,
        PRODUCTION_FEATURES,
        None,
        max_neighbors,
    )
    production_enabled = clears_gate(
        base_validation,
        MIN_BASE_BLOCKS,
        BASE_MIN_IMPROVEMENT_PCT,
        BASE_MIN_WIN_PCT,
        BASE_MIN_RECENT_PCT,
    )
    groups = eligible_environment_groups(position)
    selection_trace: List[dict] = []

    if production_enabled:
        selected_groups: List[str] = []
        current_features = list(PRODUCTION_FEATURES)
        remaining = list(groups)
        while remaining and len(selected_groups) < MAX_ENV_GROUPS:
            passing: List[Tuple[float, str, List[str], dict]] = []
            for stage, incremental in remaining:
                candidate_features = unique_columns(current_features + incremental)
                summary = validation_summary(
                    block,
                    test_season,
                    candidate_features,
                    current_features,
                    max_neighbors,
                )
                passed = clears_gate(
                    summary,
                    MIN_SIGNAL_BLOCKS,
                    SIGNAL_MIN_IMPROVEMENT_PCT,
                    SIGNAL_MIN_WIN_PCT,
                    SIGNAL_MIN_RECENT_PCT,
                )
                selection_trace.append(
                    {
                        "candidate": stage,
                        "reference": "+".join(selected_groups) if selected_groups else "production_usage",
                        "passed": passed,
                        **summary,
                    }
                )
                if passed:
                    passing.append(
                        (
                            safe_float(summary.get("improvementPct"), -999.0),
                            stage,
                            incremental,
                            summary,
                        )
                    )
            if not passing:
                break
            passing.sort(key=lambda item: item[0], reverse=True)
            _score, best_stage, best_incremental, _summary = passing[0]
            selected_groups.append(best_stage)
            current_features = unique_columns(current_features + best_incremental)
            remaining = [row for row in remaining if row[0] != best_stage]
        return {
            "baseMode": "production",
            "features": current_features,
            "selectedGroups": selected_groups,
            "baseValidation": base_validation,
            "selectionTrace": selection_trace,
        }

    rescue_candidates: List[Tuple[float, str, List[str], dict]] = []
    for stage, incremental in groups:
        candidate_features = unique_columns(PRODUCTION_FEATURES + incremental)
        summary = validation_summary(
            block,
            test_season,
            candidate_features,
            None,
            max_neighbors,
        )
        passed = clears_gate(
            summary,
            MIN_SIGNAL_BLOCKS,
            RESCUE_MIN_IMPROVEMENT_PCT,
            RESCUE_MIN_WIN_PCT,
            RESCUE_MIN_RECENT_PCT,
        )
        selection_trace.append(
            {
                "candidate": stage,
                "reference": "pace",
                "passed": passed,
                **summary,
            }
        )
        if passed:
            rescue_candidates.append(
                (
                    safe_float(summary.get("improvementPct"), -999.0),
                    stage,
                    candidate_features,
                    summary,
                )
            )
    if rescue_candidates:
        rescue_candidates.sort(key=lambda item: item[0], reverse=True)
        _score, best_stage, best_features, _summary = rescue_candidates[0]
        return {
            "baseMode": "environment_rescue",
            "features": best_features,
            "selectedGroups": [best_stage],
            "baseValidation": base_validation,
            "selectionTrace": selection_trace,
        }
    return {
        "baseMode": "pace",
        "features": [],
        "selectedGroups": [],
        "baseValidation": base_validation,
        "selectionTrace": selection_trace,
    }


def aggregate_comparison(predictions: pd.DataFrame, group_columns: Sequence[str]) -> pd.DataFrame:
    rows: List[dict] = []
    groups = predictions[list(group_columns)].drop_duplicates().to_dict("records") if group_columns else [{}]
    for group in groups:
        block = predictions.copy()
        for column, value in group.items():
            block = block[block[column] == value]
        pace = metrics(block[block["stage"] == "00_pace_baseline"], "prediction")
        production = metrics(block[block["stage"] == "01_production_reference"], "prediction")
        nested = metrics(block[block["stage"] == "09_nested_selected"], "prediction")
        rows.append(
            {
                **group,
                "rows": nested["rows"],
                "paceMae": pace["mae"],
                "productionMae": production["mae"],
                "nestedMae": nested["mae"],
                "nestedImprovementPctVsPace": improvement_pct(pace["mae"], nested["mae"]),
                "nestedImprovementPctVsProduction": improvement_pct(production["mae"], nested["mae"]),
                "productionImprovementPctVsPace": improvement_pct(pace["mae"], production["mae"]),
            }
        )
    return pd.DataFrame(rows)


def history_policy(position_checkpoint: pd.DataFrame) -> pd.DataFrame:
    if position_checkpoint.empty:
        return pd.DataFrame()
    rows: List[dict] = []
    for row in position_checkpoint.to_dict("records"):
        vs_pace = safe_float(row.get("nestedImprovementPctVsPace"), np.nan)
        vs_prod = safe_float(row.get("nestedImprovementPctVsProduction"), np.nan)
        if math.isfinite(vs_pace) and vs_pace >= 2.0 and math.isfinite(vs_prod) and vs_prod >= -0.25:
            recommendation = "validated-history"
        elif math.isfinite(vs_pace) and vs_pace > 0.0:
            recommendation = "light-history"
        else:
            recommendation = "current-season-dominant"
        rows.append(
            {
                "position": row.get("position"),
                "checkpoint": row.get("checkpoint"),
                "nestedImprovementPctVsPace": vs_pace,
                "nestedImprovementPctVsProduction": vs_prod,
                "historyRecommendation": recommendation,
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--features", type=Path, default=Path("model-lab/output/v19-player-features/player_features.csv"))
    parser.add_argument("--out", type=Path, default=Path("model-lab/output/v19-player-validated"))
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
    season_metrics: List[dict] = []
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

                pace = prediction_for_features(train, test, None, "00_pace_baseline", args.max_neighbors)
                production = prediction_for_features(train, test, PRODUCTION_FEATURES, "01_production_reference", args.max_neighbors)
                choice = choose_nested_model(block, position, test_season, args.max_neighbors)
                nested = prediction_for_features(
                    train,
                    test,
                    choice["features"],
                    "09_nested_selected",
                    args.max_neighbors,
                )
                nested["baseMode"] = choice["baseMode"]
                nested["selectedGroups"] = ";".join(choice["selectedGroups"])
                predictions.extend([pace, production, nested])

                for frame, stage in (
                    (pace, "00_pace_baseline"),
                    (production, "01_production_reference"),
                    (nested, "09_nested_selected"),
                ):
                    metric = metrics(frame, "prediction")
                    season_metrics.append(
                        {
                            "season": test_season,
                            "checkpoint": checkpoint,
                            "position": position,
                            "stage": stage,
                            **metric,
                        }
                    )

                base_validation = choice["baseValidation"]
                selection_rows.append(
                    {
                        "season": test_season,
                        "checkpoint": checkpoint,
                        "position": position,
                        "baseMode": choice["baseMode"],
                        "selectedGroups": ";".join(choice["selectedGroups"]),
                        "selectedGroupCount": len(choice["selectedGroups"]),
                        "baseValidationBlocks": base_validation.get("blocks"),
                        "baseValidationImprovementPctVsPace": base_validation.get("improvementPct"),
                        "baseValidationWinPctVsPace": base_validation.get("winPct"),
                        "baseValidationRecentImprovementPctVsPace": base_validation.get("recentImprovementPct"),
                    }
                )
                for trace in choice["selectionTrace"]:
                    trace_rows.append(
                        {
                            "season": test_season,
                            "checkpoint": checkpoint,
                            "position": position,
                            **trace,
                        }
                    )

    if not predictions:
        raise RuntimeError("No v1.9c predictions were produced")

    prediction_df = pd.concat(predictions, ignore_index=True)
    season_df = pd.DataFrame(season_metrics)
    selection_df = pd.DataFrame(selection_rows)
    trace_df = pd.DataFrame(trace_rows)
    overall = aggregate_comparison(prediction_df, [])
    position_summary = aggregate_comparison(prediction_df, ["position"])
    position_checkpoint = aggregate_comparison(prediction_df, ["position", "checkpoint"])
    policy = history_policy(position_checkpoint)

    if not selection_df.empty:
        signal_frequency = (
            selection_df.assign(selectedGroups=selection_df["selectedGroups"].fillna(""))
            .groupby(["position", "checkpoint", "baseMode", "selectedGroups"], dropna=False)
            .size()
            .reset_index(name="outerSeasons")
        )
    else:
        signal_frequency = pd.DataFrame()

    prediction_df.to_csv(args.out / "validated_predictions.csv", index=False)
    season_df.to_csv(args.out / "validated_season_metrics.csv", index=False)
    selection_df.to_csv(args.out / "validated_selection_history.csv", index=False)
    trace_df.to_csv(args.out / "validated_selection_trace.csv", index=False)
    overall.to_csv(args.out / "validated_overall_summary.csv", index=False)
    position_summary.to_csv(args.out / "validated_position_summary.csv", index=False)
    position_checkpoint.to_csv(args.out / "validated_position_checkpoint_summary.csv", index=False)
    signal_frequency.to_csv(args.out / "validated_signal_selection_frequency.csv", index=False)
    policy.to_csv(args.out / "validated_history_policy.csv", index=False)

    result = {
        "lab": "GRIDIRON PULSE v1.9c nested validated environment combination",
        "researchOnly": True,
        "productionWeightsSelected": False,
        "selectionLeakageGuard": "Each outer season selects history/environment signals using only earlier seasons.",
        "testStart": args.test_start,
        "testEnd": int(data["season"].max()),
        "maxEnvironmentGroups": MAX_ENV_GROUPS,
        "baseGate": {
            "minBlocks": MIN_BASE_BLOCKS,
            "minImprovementPct": BASE_MIN_IMPROVEMENT_PCT,
            "minWinPct": BASE_MIN_WIN_PCT,
            "minRecentImprovementPct": BASE_MIN_RECENT_PCT,
        },
        "environmentGate": {
            "minBlocks": MIN_SIGNAL_BLOCKS,
            "minImprovementPct": SIGNAL_MIN_IMPROVEMENT_PCT,
            "minWinPct": SIGNAL_MIN_WIN_PCT,
            "minRecentImprovementPct": SIGNAL_MIN_RECENT_PCT,
        },
        "environmentRescueGate": {
            "minBlocks": MIN_SIGNAL_BLOCKS,
            "minImprovementPct": RESCUE_MIN_IMPROVEMENT_PCT,
            "minWinPct": RESCUE_MIN_WIN_PCT,
            "minRecentImprovementPct": RESCUE_MIN_RECENT_PCT,
        },
        "overall": overall.to_dict("records"),
        "positionSummary": position_summary.to_dict("records"),
        "historyPolicy": policy.to_dict("records"),
    }
    (args.out / "validated_backtest_summary.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    main()
