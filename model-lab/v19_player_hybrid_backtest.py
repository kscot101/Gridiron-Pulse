#!/usr/bin/env python3
"""GRIDIRON PULSE v1.9e nested history-shrinkage + environment hybrid backtest.

For every held-out season, this lab first learns the best historical-comparable
weight using only earlier seasons. It then allows at most one environment family
to enter, and only when that environment-aware comparable model beats the
already-shrunk history baseline in prior-only validation.

Research only. No Season Worker production weights are set here.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

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
from v19_player_history_blend_backtest import WEIGHTS

MIN_TEST_ROWS = 5
MIN_TRAIN_ROWS = 25
MIN_VALIDATION_BLOCKS = 2
TIE_TOLERANCE_PCT = 0.10
ENV_MIN_IMPROVEMENT_PCT = 0.50
ENV_MIN_BLOCK_WIN_PCT = 55.0
ENV_MIN_RECENT_IMPROVEMENT_PCT = 0.0


def eligible_groups(position: str) -> List[Tuple[str, List[str]]]:
    rows: List[Tuple[str, List[str]]] = []
    for stage, features, eligible, positions, _note in ENVIRONMENT_GROUPS:
        if eligible and position in positions:
            rows.append((stage, list(features)))
    return rows


def model_specs(position: str) -> List[Tuple[str, Optional[str], List[str]]]:
    specs: List[Tuple[str, Optional[str], List[str]]] = [
        ("history", None, list(PRODUCTION_FEATURES)),
    ]
    for stage, incremental in eligible_groups(position):
        specs.append((stage, stage, unique_columns(PRODUCTION_FEATURES + incremental)))
    return specs


def prediction_from_adjustment(
    test: pd.DataFrame,
    stage: str,
    adjustment: np.ndarray,
    weight: float,
    feature_count: int,
) -> pd.DataFrame:
    result = make_prediction_frame(test, stage, adjustment * float(weight), feature_count)
    result["historyWeight"] = float(weight)
    return result


def validation_candidates(
    block: pd.DataFrame,
    position: str,
    before_season: int,
    max_neighbors: int,
) -> List[dict]:
    accum: Dict[Tuple[str, float], dict] = {}
    specs = model_specs(position)
    seasons = sorted(int(value) for value in block["season"].dropna().unique() if int(value) < before_season)

    for validation_season in seasons:
        validation = block[block["season"] == validation_season].copy()
        train = block[block["season"] < validation_season].copy()
        if len(validation) < MIN_TEST_ROWS or len(train) < MIN_TRAIN_ROWS:
            continue

        target = pd.to_numeric(validation["targetPrimaryEq17"], errors="coerce").to_numpy(dtype=float)
        pace = pd.to_numeric(validation["pacePrimaryEq17"], errors="coerce").to_numpy(dtype=float)

        for model_name, environment_group, features in specs:
            adjustment, feature_count = evaluate_stage(train, validation, features, max_neighbors)
            for weight in WEIGHTS:
                prediction = pace + adjustment * float(weight)
                mae = float(np.mean(np.abs(prediction - target)))
                key = (model_name, float(weight))
                row = accum.setdefault(
                    key,
                    {
                        "model": model_name,
                        "environmentGroup": environment_group,
                        "weight": float(weight),
                        "absErrorSum": 0.0,
                        "rows": 0,
                        "seasonMae": {},
                        "featureCount": int(feature_count),
                    },
                )
                row["absErrorSum"] += float(np.abs(prediction - target).sum())
                row["rows"] += int(len(validation))
                row["seasonMae"][int(validation_season)] = mae
                row["featureCount"] = int(feature_count)

    output: List[dict] = []
    for row in accum.values():
        rows = int(row["rows"])
        output.append(
            {
                **row,
                "mae": float(row["absErrorSum"] / rows) if rows else np.nan,
                "blocks": int(len(row["seasonMae"])),
            }
        )
    return output


def choose_near_best(rows: Sequence[dict]) -> Optional[dict]:
    valid = [
        row
        for row in rows
        if int(row.get("blocks", 0)) >= MIN_VALIDATION_BLOCKS
        and math.isfinite(safe_float(row.get("mae"), np.nan))
    ]
    if not valid:
        return None
    best_mae = min(float(row["mae"]) for row in valid)
    tolerance = best_mae * TIE_TOLERANCE_PCT / 100.0
    near = [row for row in valid if float(row["mae"]) <= best_mae + tolerance]
    return sorted(
        near,
        key=lambda row: (
            float(row.get("weight", 0.0)),
            0 if row.get("environmentGroup") is None else 1,
            float(row.get("mae", np.inf)),
        ),
    )[0]


def comparison_stats(candidate: Mapping[str, object], reference: Mapping[str, object]) -> dict:
    candidate_mae = safe_float(candidate.get("mae"), np.nan)
    reference_mae = safe_float(reference.get("mae"), np.nan)
    candidate_seasons = candidate.get("seasonMae") if isinstance(candidate.get("seasonMae"), dict) else {}
    reference_seasons = reference.get("seasonMae") if isinstance(reference.get("seasonMae"), dict) else {}
    common = sorted(set(candidate_seasons) & set(reference_seasons))
    if not common:
        return {
            "improvementPctVsShrinkage": np.nan,
            "blockWinPctVsShrinkage": np.nan,
            "recentImprovementPctVsShrinkage": np.nan,
        }
    wins = sum(float(candidate_seasons[season]) <= float(reference_seasons[season]) for season in common)
    recent = common[-4:]
    recent_candidate = float(np.mean([float(candidate_seasons[season]) for season in recent]))
    recent_reference = float(np.mean([float(reference_seasons[season]) for season in recent]))
    return {
        "improvementPctVsShrinkage": improvement_pct(reference_mae, candidate_mae),
        "blockWinPctVsShrinkage": 100.0 * wins / len(common),
        "recentImprovementPctVsShrinkage": improvement_pct(recent_reference, recent_candidate),
    }


def choose_model(
    block: pd.DataFrame,
    position: str,
    before_season: int,
    max_neighbors: int,
) -> dict:
    candidates = validation_candidates(block, position, before_season, max_neighbors)
    history_rows = [row for row in candidates if row.get("environmentGroup") is None]
    history_choice = choose_near_best(history_rows)

    if history_choice is None:
        return {
            "historyChoice": {
                "model": "history",
                "environmentGroup": None,
                "weight": 0.0,
                "mae": np.nan,
                "blocks": 0,
                "featureCount": len(PRODUCTION_FEATURES),
                "seasonMae": {},
            },
            "selectedChoice": {
                "model": "history",
                "environmentGroup": None,
                "weight": 0.0,
                "mae": np.nan,
                "blocks": 0,
                "featureCount": len(PRODUCTION_FEATURES),
                "seasonMae": {},
            },
            "trace": [],
        }

    trace: List[dict] = []
    passing: List[Tuple[float, dict, dict]] = []
    for row in candidates:
        if row.get("environmentGroup") is None:
            continue
        stats = comparison_stats(row, history_choice)
        improvement = safe_float(stats["improvementPctVsShrinkage"], np.nan)
        wins = safe_float(stats["blockWinPctVsShrinkage"], np.nan)
        recent = safe_float(stats["recentImprovementPctVsShrinkage"], np.nan)
        passed = bool(
            int(row.get("blocks", 0)) >= MIN_VALIDATION_BLOCKS
            and math.isfinite(improvement)
            and improvement >= ENV_MIN_IMPROVEMENT_PCT
            and math.isfinite(wins)
            and wins >= ENV_MIN_BLOCK_WIN_PCT
            and math.isfinite(recent)
            and recent >= ENV_MIN_RECENT_IMPROVEMENT_PCT
        )
        trace.append(
            {
                "candidateModel": row["model"],
                "environmentGroup": row["environmentGroup"],
                "candidateWeight": row["weight"],
                "validationMae": row["mae"],
                "validationBlocks": row["blocks"],
                "passedEnvironmentGate": passed,
                **stats,
            }
        )
        if passed:
            passing.append((improvement, row, stats))

    selected = history_choice
    if passing:
        passing.sort(
            key=lambda item: (
                -item[0],
                float(item[1].get("weight", 0.0)),
                str(item[1].get("environmentGroup") or ""),
            )
        )
        selected = passing[0][1]

    return {
        "historyChoice": history_choice,
        "selectedChoice": selected,
        "trace": trace,
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
        shrink = metrics(block[block["stage"] == "10_shrinkage_reference"], "prediction")
        hybrid = metrics(block[block["stage"] == "11_nested_hybrid"], "prediction")
        rows.append(
            {
                **group,
                "rows": hybrid["rows"],
                "paceMae": pace["mae"],
                "fullHistoryMae": full["mae"],
                "shrinkageMae": shrink["mae"],
                "hybridMae": hybrid["mae"],
                "hybridImprovementPctVsPace": improvement_pct(pace["mae"], hybrid["mae"]),
                "hybridImprovementPctVsFullHistory": improvement_pct(full["mae"], hybrid["mae"]),
                "hybridImprovementPctVsShrinkage": improvement_pct(shrink["mae"], hybrid["mae"]),
                "shrinkageImprovementPctVsPace": improvement_pct(pace["mae"], shrink["mae"]),
            }
        )
    return pd.DataFrame(rows)


def signal_frequency(selection: pd.DataFrame) -> pd.DataFrame:
    if selection.empty:
        return pd.DataFrame()
    rows: List[dict] = []
    groups = selection[["position", "checkpoint"]].drop_duplicates().to_dict("records")
    for group in groups:
        block = selection[
            (selection["position"] == group["position"])
            & (selection["checkpoint"] == group["checkpoint"])
        ]
        total = len(block)
        env = block[block["selectedEnvironmentGroup"].fillna("").ne("")]
        counts = env["selectedEnvironmentGroup"].value_counts()
        if counts.empty:
            rows.append(
                {
                    **group,
                    "environmentGroup": "none",
                    "selectedSeasons": 0,
                    "outerSeasons": total,
                    "selectionPct": 0.0,
                }
            )
        else:
            for environment_group, count in counts.items():
                rows.append(
                    {
                        **group,
                        "environmentGroup": environment_group,
                        "selectedSeasons": int(count),
                        "outerSeasons": total,
                        "selectionPct": 100.0 * int(count) / total if total else np.nan,
                    }
                )
    return pd.DataFrame(rows)


def policy_table(position_checkpoint: pd.DataFrame, selection: pd.DataFrame, frequency: pd.DataFrame) -> pd.DataFrame:
    rows: List[dict] = []
    for metric_row in position_checkpoint.to_dict("records"):
        position = str(metric_row.get("position") or "")
        checkpoint = int(metric_row.get("checkpoint") or 0)
        picked = selection[
            (selection["position"] == position)
            & (selection["checkpoint"] == checkpoint)
        ]
        mean_weight = float(picked["selectedHistoryWeight"].mean()) if not picked.empty else 0.0
        mode_weight = 0.0
        if not picked.empty:
            counts = picked["selectedHistoryWeight"].value_counts()
            if not counts.empty:
                max_count = int(counts.max())
                mode_weight = float(min(float(index) for index, value in counts.items() if int(value) == max_count))
        vs_pace = safe_float(metric_row.get("hybridImprovementPctVsPace"), np.nan)
        if not math.isfinite(vs_pace) or vs_pace <= 0.0 or mean_weight <= 0.05:
            history_label = "current-season-dominant"
        elif mean_weight >= 0.70:
            history_label = "strong-history"
        elif mean_weight >= 0.35:
            history_label = "blended-history"
        else:
            history_label = "light-history"

        freq = frequency[
            (frequency["position"] == position)
            & (frequency["checkpoint"] == checkpoint)
            & (frequency["environmentGroup"] != "none")
        ] if not frequency.empty else pd.DataFrame()
        environment_label = "none"
        top_environment_pct = 0.0
        if not freq.empty:
            top = freq.sort_values(["selectionPct", "environmentGroup"], ascending=[False, True]).iloc[0]
            top_environment_pct = safe_float(top["selectionPct"], 0.0)
            if top_environment_pct >= 25.0 and safe_float(metric_row.get("hybridImprovementPctVsShrinkage"), 0.0) > 0.0:
                environment_label = f"conditional:{top['environmentGroup']}"

        rows.append(
            {
                "position": position,
                "checkpoint": checkpoint,
                "meanSelectedHistoryWeight": mean_weight,
                "modeSelectedHistoryWeight": mode_weight,
                "historyRecommendation": history_label,
                "environmentRecommendation": environment_label,
                "topEnvironmentSelectionPct": top_environment_pct,
                "hybridImprovementPctVsPace": vs_pace,
                "hybridImprovementPctVsFullHistory": safe_float(metric_row.get("hybridImprovementPctVsFullHistory"), np.nan),
                "hybridImprovementPctVsShrinkage": safe_float(metric_row.get("hybridImprovementPctVsShrinkage"), np.nan),
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--features", type=Path, default=Path("model-lab/output/v19-player-features/player_features.csv"))
    parser.add_argument("--out", type=Path, default=Path("model-lab/output/v19-player-hybrid"))
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

                production_adjustment, production_count = evaluate_stage(train, test, PRODUCTION_FEATURES, args.max_neighbors)
                choice = choose_model(block, position, test_season, args.max_neighbors)
                history_choice = choice["historyChoice"]
                selected_choice = choice["selectedChoice"]

                pace = prediction_from_adjustment(test, "00_pace_baseline", production_adjustment, 0.0, production_count)
                full = prediction_from_adjustment(test, "01_full_history_reference", production_adjustment, 1.0, production_count)
                shrink = prediction_from_adjustment(
                    test,
                    "10_shrinkage_reference",
                    production_adjustment,
                    float(history_choice.get("weight", 0.0)),
                    production_count,
                )

                selected_environment = selected_choice.get("environmentGroup")
                selected_weight = float(selected_choice.get("weight", history_choice.get("weight", 0.0)))
                if selected_environment:
                    incremental = next(
                        features
                        for stage, features in eligible_groups(position)
                        if stage == selected_environment
                    )
                    hybrid_features = unique_columns(PRODUCTION_FEATURES + incremental)
                    hybrid_adjustment, hybrid_count = evaluate_stage(train, test, hybrid_features, args.max_neighbors)
                else:
                    hybrid_adjustment, hybrid_count = production_adjustment, production_count

                hybrid = prediction_from_adjustment(
                    test,
                    "11_nested_hybrid",
                    hybrid_adjustment,
                    selected_weight,
                    hybrid_count,
                )
                hybrid["selectedEnvironmentGroup"] = selected_environment or ""
                predictions.extend([pace, full, shrink, hybrid])

                selection_rows.append(
                    {
                        "season": test_season,
                        "position": position,
                        "checkpoint": checkpoint,
                        "historyOnlyWeight": float(history_choice.get("weight", 0.0)),
                        "selectedHistoryWeight": selected_weight,
                        "selectedEnvironmentGroup": selected_environment or "",
                        "historyValidationMae": safe_float(history_choice.get("mae"), np.nan),
                        "selectedValidationMae": safe_float(selected_choice.get("mae"), np.nan),
                        "validationBlocks": int(selected_choice.get("blocks", 0)),
                    }
                )
                for item in choice["trace"]:
                    trace_rows.append(
                        {
                            "outerSeason": test_season,
                            "position": position,
                            "checkpoint": checkpoint,
                            **item,
                            "selected": bool(
                                selected_environment
                                and item["environmentGroup"] == selected_environment
                                and abs(float(item["candidateWeight"]) - selected_weight) < 1e-12
                            ),
                        }
                    )

    prediction_df = pd.concat(predictions, ignore_index=True) if predictions else pd.DataFrame()
    if prediction_df.empty:
        raise RuntimeError("No v1.9e hybrid predictions were produced")
    selection_df = pd.DataFrame(selection_rows)
    trace_df = pd.DataFrame(trace_rows)

    overall = aggregate(prediction_df, [])
    position_summary = aggregate(prediction_df, ["position"])
    position_checkpoint = aggregate(prediction_df, ["position", "checkpoint"])
    frequency = signal_frequency(selection_df)
    policy = policy_table(position_checkpoint, selection_df, frequency)

    prediction_df.to_csv(args.out / "hybrid_predictions.csv", index=False)
    selection_df.to_csv(args.out / "hybrid_selection_history.csv", index=False)
    trace_df.to_csv(args.out / "hybrid_selection_trace.csv", index=False)
    overall.to_csv(args.out / "hybrid_overall_summary.csv", index=False)
    position_summary.to_csv(args.out / "hybrid_position_summary.csv", index=False)
    position_checkpoint.to_csv(args.out / "hybrid_position_checkpoint_summary.csv", index=False)
    frequency.to_csv(args.out / "hybrid_signal_frequency.csv", index=False)
    policy.to_csv(args.out / "hybrid_policy.csv", index=False)

    report = {
        "lab": "GRIDIRON PULSE v1.9e nested history shrinkage + environment hybrid",
        "researchOnly": True,
        "productionWeightsSelected": False,
        "testStart": args.test_start,
        "testEnd": int(data["season"].max()),
        "candidateHistoryWeights": list(WEIGHTS),
        "environmentRule": "At most one eligible environment family may enter, and only if it improves the prior-only shrinkage baseline by >=0.50%, wins >=55% of validation blocks, and does not regress the recent validation window.",
        "overall": overall.to_dict("records"),
        "positionCheckpoint": position_checkpoint.to_dict("records"),
        "policy": policy.to_dict("records"),
        "signalFrequency": frequency.to_dict("records"),
    }
    (args.out / "hybrid_summary.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    main()
