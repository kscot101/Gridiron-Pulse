#!/usr/bin/env python3
"""GRIDIRON PULSE v1.9f environment incremental value audit.

Compares the v1.9c nested validated model against an otherwise identical
history gate with all environment groups removed. This isolates whether the
v1.9c gain came from environment context or from the history on/off gate.

All history-gate decisions use only seasons before the held-out season.
Research only. No Season Worker production weights are set here.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import List, Mapping, Sequence

import numpy as np
import pandas as pd

from v19_player_comparable_backtest import metrics, safe_float
from v19_player_isolated_environment_backtest import (
    PRODUCTION_FEATURES,
    evaluate_stage,
    improvement_pct,
    make_prediction_frame,
)
from v19_player_validated_combination_backtest import (
    BASE_MIN_IMPROVEMENT_PCT,
    BASE_MIN_RECENT_PCT,
    BASE_MIN_WIN_PCT,
    MIN_BASE_BLOCKS,
    clears_gate,
    validation_summary,
)

MIN_TEST_ROWS = 5
MIN_TRAIN_ROWS = 25
ENV_MIN_IMPROVEMENT_PCT = 0.50
ENV_MIN_BLOCK_WIN_PCT = 55.0
ENV_MIN_RECENT_IMPROVEMENT_PCT = 0.0


def hard_gate_choice(block: pd.DataFrame, test_season: int, max_neighbors: int) -> dict:
    summary = validation_summary(
        block,
        test_season,
        PRODUCTION_FEATURES,
        None,
        max_neighbors,
    )
    enabled = clears_gate(
        summary,
        MIN_BASE_BLOCKS,
        BASE_MIN_IMPROVEMENT_PCT,
        BASE_MIN_WIN_PCT,
        BASE_MIN_RECENT_PCT,
    )
    return {"enabled": bool(enabled), **summary}


def build_hard_gate_predictions(data: pd.DataFrame, test_start: int, max_neighbors: int):
    predictions: List[pd.DataFrame] = []
    selections: List[dict] = []
    seasons = sorted(int(value) for value in data["season"].dropna().unique() if int(value) >= test_start)

    for position in sorted(data["position"].dropna().unique()):
        position_data = data[data["position"] == position]
        for checkpoint in sorted(int(value) for value in position_data["checkpoint"].dropna().unique()):
            block = position_data[position_data["checkpoint"] == checkpoint].copy()
            for test_season in seasons:
                test = block[block["season"] == test_season].copy()
                train = block[block["season"] < test_season].copy()
                if len(test) < MIN_TEST_ROWS or len(train) < MIN_TRAIN_ROWS:
                    continue

                full_adjustment, feature_count = evaluate_stage(
                    train,
                    test,
                    PRODUCTION_FEATURES,
                    max_neighbors,
                )
                pace = make_prediction_frame(
                    test,
                    "00_pace_baseline",
                    np.zeros(len(test), dtype=float),
                    0,
                )
                full = make_prediction_frame(
                    test,
                    "01_full_history_reference",
                    full_adjustment,
                    feature_count,
                )
                choice = hard_gate_choice(block, test_season, max_neighbors)
                gate_adjustment = full_adjustment if choice["enabled"] else np.zeros(len(test), dtype=float)
                gate = make_prediction_frame(
                    test,
                    "11_history_gate_no_environment",
                    gate_adjustment,
                    feature_count if choice["enabled"] else 0,
                )
                predictions.extend([pace, full, gate])
                selections.append(
                    {
                        "season": test_season,
                        "position": position,
                        "checkpoint": checkpoint,
                        "historyEnabled": bool(choice["enabled"]),
                        "validationBlocks": int(safe_float(choice.get("blocks"), 0.0)),
                        "validationImprovementPctVsPace": safe_float(choice.get("improvementPct"), np.nan),
                        "validationWinPct": safe_float(choice.get("winPct"), np.nan),
                        "validationRecentImprovementPct": safe_float(choice.get("recentImprovementPct"), np.nan),
                    }
                )

    prediction_df = pd.concat(predictions, ignore_index=True) if predictions else pd.DataFrame()
    return prediction_df, pd.DataFrame(selections)


def season_metrics(frame: pd.DataFrame, stage: str) -> pd.DataFrame:
    work = frame[frame["stage"] == stage].copy()
    rows = []
    if work.empty:
        return pd.DataFrame(columns=["season", "position", "checkpoint", "mae"])
    for keys, block in work.groupby(["season", "position", "checkpoint"], dropna=False):
        season, position, checkpoint = keys
        value = metrics(block, "prediction")
        rows.append(
            {
                "season": int(season),
                "position": position,
                "checkpoint": int(checkpoint),
                "mae": value["mae"],
            }
        )
    return pd.DataFrame(rows)


def comparison_stats(
    hard_season: pd.DataFrame,
    env_season: pd.DataFrame,
    filters: Mapping[str, object],
) -> dict:
    left = hard_season.copy()
    right = env_season.copy()
    for column, value in filters.items():
        left = left[left[column] == value]
        right = right[right[column] == value]
    merged = left.merge(
        right,
        on=["season", "position", "checkpoint"],
        how="inner",
        suffixes=("Hard", "Env"),
    )
    if merged.empty:
        return {
            "seasonBlocks": 0,
            "environmentBlockWinPctVsHardGate": np.nan,
            "environmentRecent4ImprovementPctVsHardGate": np.nan,
        }
    win_pct = float((merged["maeEnv"] <= merged["maeHard"]).mean() * 100.0)
    recent_seasons = sorted(int(value) for value in merged["season"].unique())[-4:]
    recent = merged[merged["season"].isin(recent_seasons)]
    recent_improvement = np.nan
    if not recent.empty and recent["maeHard"].mean() > 0:
        recent_improvement = improvement_pct(recent["maeHard"].mean(), recent["maeEnv"].mean())
    return {
        "seasonBlocks": int(len(merged)),
        "environmentBlockWinPctVsHardGate": win_pct,
        "environmentRecent4ImprovementPctVsHardGate": recent_improvement,
    }


def aggregate(
    hard_predictions: pd.DataFrame,
    validated_predictions: pd.DataFrame,
    group_columns: Sequence[str],
) -> pd.DataFrame:
    env_predictions = validated_predictions[validated_predictions["stage"] == "09_nested_selected"].copy()
    hard_season = season_metrics(hard_predictions, "11_history_gate_no_environment")
    env_season = season_metrics(validated_predictions, "09_nested_selected")

    groups = hard_predictions[list(group_columns)].drop_duplicates().to_dict("records") if group_columns else [{}]
    rows: List[dict] = []
    for group in groups:
        hard_block = hard_predictions.copy()
        env_block = env_predictions.copy()
        for column, value in group.items():
            hard_block = hard_block[hard_block[column] == value]
            env_block = env_block[env_block[column] == value]

        pace_metric = metrics(hard_block[hard_block["stage"] == "00_pace_baseline"], "prediction")
        full_metric = metrics(hard_block[hard_block["stage"] == "01_full_history_reference"], "prediction")
        gate_metric = metrics(hard_block[hard_block["stage"] == "11_history_gate_no_environment"], "prediction")
        env_metric = metrics(env_block, "prediction")
        compare = comparison_stats(hard_season, env_season, group)

        row = {
            **group,
            "rows": gate_metric["rows"],
            "paceMae": pace_metric["mae"],
            "fullHistoryMae": full_metric["mae"],
            "hardGateMae": gate_metric["mae"],
            "validatedEnvironmentMae": env_metric["mae"],
            "hardGateImprovementPctVsPace": improvement_pct(pace_metric["mae"], gate_metric["mae"]),
            "environmentIncrementalPctVsHardGate": improvement_pct(gate_metric["mae"], env_metric["mae"]),
            "validatedEnvironmentImprovementPctVsPace": improvement_pct(pace_metric["mae"], env_metric["mae"]),
            "fullHistoryImprovementPctVsPace": improvement_pct(pace_metric["mae"], full_metric["mae"]),
            **compare,
        }
        rows.append(row)
    return pd.DataFrame(rows)


def policy_table(position_checkpoint: pd.DataFrame) -> pd.DataFrame:
    rows: List[dict] = []
    for row in position_checkpoint.to_dict("records"):
        improvement = safe_float(row.get("environmentIncrementalPctVsHardGate"), np.nan)
        wins = safe_float(row.get("environmentBlockWinPctVsHardGate"), np.nan)
        recent = safe_float(row.get("environmentRecent4ImprovementPctVsHardGate"), np.nan)
        promoted = bool(
            math.isfinite(improvement)
            and improvement >= ENV_MIN_IMPROVEMENT_PCT
            and math.isfinite(wins)
            and wins >= ENV_MIN_BLOCK_WIN_PCT
            and math.isfinite(recent)
            and recent >= ENV_MIN_RECENT_IMPROVEMENT_PCT
        )
        recommendation = "core-environment" if promoted else "secondary-only"
        rows.append(
            {
                "position": row.get("position"),
                "checkpoint": row.get("checkpoint"),
                "environmentIncrementalPctVsHardGate": improvement,
                "environmentBlockWinPctVsHardGate": wins,
                "environmentRecent4ImprovementPctVsHardGate": recent,
                "environmentRecommendation": recommendation,
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--features", type=Path, default=Path("model-lab/output/v19-player-features/player_features.csv"))
    parser.add_argument("--validated-predictions", type=Path, default=Path("model-lab/output/v19-player-validated/validated_predictions.csv"))
    parser.add_argument("--out", type=Path, default=Path("model-lab/output/v19-player-environment-value"))
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

    validated = pd.read_csv(args.validated_predictions, low_memory=False)
    validated["season"] = pd.to_numeric(validated["season"], errors="coerce").astype("Int64")
    validated["checkpoint"] = pd.to_numeric(validated["checkpoint"], errors="coerce").astype("Int64")
    if "09_nested_selected" not in set(validated["stage"].dropna().astype(str)):
        raise RuntimeError("validated predictions do not contain stage 09_nested_selected")

    hard_predictions, selections = build_hard_gate_predictions(data, args.test_start, args.max_neighbors)
    if hard_predictions.empty:
        raise RuntimeError("No v1.9f hard-gate predictions were produced")

    overall = aggregate(hard_predictions, validated, [])
    position = aggregate(hard_predictions, validated, ["position"])
    position_checkpoint = aggregate(hard_predictions, validated, ["position", "checkpoint"])
    policy = policy_table(position_checkpoint)

    hard_predictions.to_csv(args.out / "environment_value_hard_gate_predictions.csv", index=False)
    selections.to_csv(args.out / "environment_value_history_gate_selection.csv", index=False)
    overall.to_csv(args.out / "environment_value_overall_summary.csv", index=False)
    position.to_csv(args.out / "environment_value_position_summary.csv", index=False)
    position_checkpoint.to_csv(args.out / "environment_value_position_checkpoint_summary.csv", index=False)
    policy.to_csv(args.out / "environment_value_policy.csv", index=False)

    report = {
        "lab": "GRIDIRON PULSE v1.9f environment incremental value audit",
        "researchOnly": True,
        "productionWeightsSelected": False,
        "testStart": args.test_start,
        "testEnd": int(data["season"].max()),
        "comparison": "v1.9c nested validated environment model versus the identical prior-only history gate with all environment groups removed",
        "promotionGate": {
            "minImprovementPctVsHardGate": ENV_MIN_IMPROVEMENT_PCT,
            "minSeasonBlockWinPct": ENV_MIN_BLOCK_WIN_PCT,
            "minRecent4ImprovementPct": ENV_MIN_RECENT_IMPROVEMENT_PCT,
        },
        "overall": overall.to_dict("records"),
        "positionCheckpoint": position_checkpoint.to_dict("records"),
        "policy": policy.to_dict("records"),
    }
    (args.out / "environment_value_summary.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    main()
