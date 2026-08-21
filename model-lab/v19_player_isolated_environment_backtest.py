#!/usr/bin/env python3
"""GRIDIRON PULSE v1.9b isolated player-environment backtest.

Tests each environment family independently on top of the proven
production/usage comparable model. This avoids cumulative-stage contamination:
a later signal is never penalized simply because an earlier experimental signal
hurt the model.

Research only. No production weights are selected here.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Dict, List, Mapping, Sequence, Tuple

import numpy as np
import pandas as pd

from v19_player_comparable_backtest import (
    STAGES,
    metrics,
    nearest_residuals,
    robust_scale,
    safe_float,
)

PRODUCTION_FEATURES = list(STAGES[0][1])
ENVIRONMENT_GROUPS: List[Tuple[str, List[str], bool, Sequence[str], str]] = [
    (
        "02_role_isolated",
        list(STAGES[1][1]),
        True,
        ("QB", "RB", "WR", "TE"),
        "Snap share, depth role and role movement tested only against production/usage base.",
    ),
    (
        "03_health_rate_diagnostic",
        list(STAGES[2][1]),
        False,
        ("QB", "RB", "WR", "TE"),
        "Diagnostic only: the target is a 17-game-equivalent rate, so health belongs in a later availability/games-played layer.",
    ),
    (
        "04_qb_environment_isolated",
        list(STAGES[3][1]),
        True,
        ("RB", "WR", "TE"),
        "QB quality change and established-player interactions; not applicable to QB projections themselves.",
    ),
    (
        "05_coach_scheme_isolated",
        list(STAGES[4][1]),
        True,
        ("QB", "RB", "WR", "TE"),
        "Coach continuity plus point-in-time team usage/scheme fingerprints.",
    ),
    (
        "06_trade_team_change_isolated",
        list(STAGES[5][1]),
        True,
        ("QB", "RB", "WR", "TE"),
        "Team change, team offense delta and established-player interaction.",
    ),
    (
        "07_opportunity_competition_isolated",
        list(STAGES[6][1]),
        True,
        ("QB", "RB", "WR", "TE"),
        "Vacated opportunity, incoming competition and current opportunity-share change.",
    ),
]

MIN_IMPROVEMENT_PCT = 0.50
MIN_BLOCK_WIN_PCT = 55.0
MIN_RECENT_IMPROVEMENT_PCT = 0.0


def unique_columns(columns: Sequence[str]) -> List[str]:
    return list(dict.fromkeys(columns))


def stage_catalog() -> List[dict]:
    rows = [
        {
            "stage": "00_pace_baseline",
            "features": [],
            "promotionEligible": False,
            "applicablePositions": ["QB", "RB", "WR", "TE"],
            "note": "17-game-equivalent checkpoint pace reference.",
        },
        {
            "stage": "01_production_usage_base",
            "features": PRODUCTION_FEATURES,
            "promotionEligible": True,
            "applicablePositions": ["QB", "RB", "WR", "TE"],
            "note": "Proven historical-comparable base from v1.9 first pass.",
        },
    ]
    for stage, features, eligible, positions, note in ENVIRONMENT_GROUPS:
        rows.append(
            {
                "stage": stage,
                "features": unique_columns(PRODUCTION_FEATURES + features),
                "incrementalFeatures": features,
                "promotionEligible": eligible,
                "applicablePositions": list(positions),
                "note": note,
            }
        )
    return rows


def evaluate_stage(
    train: pd.DataFrame,
    test: pd.DataFrame,
    feature_columns: Sequence[str],
    max_neighbors: int,
) -> Tuple[np.ndarray, int]:
    train_x, test_x, used = robust_scale(train, test, feature_columns)
    if not used:
        return np.zeros(len(test), dtype=float), 0
    residual_pred, _ = nearest_residuals(
        train_x,
        test_x,
        train["paceResidual"].to_numpy(dtype=float),
        train[["season", "checkpoint", "position", "playerKey", "playerName"]].reset_index(drop=True),
        test[["season", "checkpoint", "position", "playerKey", "playerName"]].reset_index(drop=True),
        max_neighbors,
    )
    return residual_pred, len(used)


def make_prediction_frame(test: pd.DataFrame, stage: str, adjustment: np.ndarray, feature_count: int) -> pd.DataFrame:
    result = test[
        [
            "season",
            "checkpoint",
            "position",
            "playerKey",
            "playerName",
            "team",
            "targetPrimaryEq17",
            "pacePrimaryEq17",
        ]
    ].copy()
    result["stage"] = stage
    result["prediction"] = test["pacePrimaryEq17"].to_numpy(dtype=float) + adjustment
    result["rawComparableAdjustment"] = adjustment
    result["featureCount"] = feature_count
    return result


def improvement_pct(base_mae: float, candidate_mae: float) -> float:
    base = safe_float(base_mae, np.nan)
    candidate = safe_float(candidate_mae, np.nan)
    if not math.isfinite(base) or not math.isfinite(candidate) or base <= 0:
        return np.nan
    return 100.0 * (base - candidate) / base


def comparison_stats(
    season_df: pd.DataFrame,
    stage: str,
    base_stage: str,
    filters: Mapping[str, object],
    test_start: int,
    test_end: int,
) -> dict:
    current = season_df[season_df["stage"] == stage].copy()
    baseline = season_df[season_df["stage"] == base_stage].copy()
    for column, value in filters.items():
        current = current[current[column] == value]
        baseline = baseline[baseline[column] == value]
    keys = ["season", "checkpoint", "position"]
    current = current[keys + ["mae"]].rename(columns={"mae": "candidateMae"})
    baseline = baseline[keys + ["mae"]].rename(columns={"mae": "baseMae"})
    merged = current.merge(baseline, on=keys, how="inner")
    if merged.empty:
        return {
            "seasonBlocks": 0,
            "seasonBlockWinPctVsProductionBase": np.nan,
            "recent4SeasonImprovementPctVsProductionBase": np.nan,
        }
    win_pct = float((merged["candidateMae"] <= merged["baseMae"]).mean() * 100.0)
    recent_start = max(test_start, test_end - 3)
    recent = merged[merged["season"] >= recent_start]
    recent_improvement = np.nan
    if not recent.empty and recent["baseMae"].mean() > 0:
        recent_improvement = improvement_pct(recent["baseMae"].mean(), recent["candidateMae"].mean())
    return {
        "seasonBlocks": int(len(merged)),
        "seasonBlockWinPctVsProductionBase": win_pct,
        "recent4SeasonImprovementPctVsProductionBase": recent_improvement,
    }


def aggregate_rows(
    predictions: pd.DataFrame,
    season_df: pd.DataFrame,
    catalog: Sequence[dict],
    group_columns: Sequence[str],
    test_start: int,
    test_end: int,
) -> pd.DataFrame:
    rows: List[dict] = []
    groups = predictions[list(group_columns)].drop_duplicates().to_dict("records") if group_columns else [{}]
    for group in groups:
        block = predictions.copy()
        for column, value in group.items():
            block = block[block[column] == value]
        production_block = block[block["stage"] == "01_production_usage_base"]
        pace_block = block[block["stage"] == "00_pace_baseline"]
        production_metric = metrics(production_block, "prediction")
        pace_metric = metrics(pace_block, "prediction")
        for spec in catalog:
            stage = spec["stage"]
            stage_block = block[block["stage"] == stage]
            if stage_block.empty:
                continue
            metric = metrics(stage_block, "prediction")
            row = {**group, "stage": stage, **metric}
            row["maeImprovementPctVsPace"] = improvement_pct(pace_metric["mae"], metric["mae"]) if stage != "00_pace_baseline" else 0.0
            row["maeImprovementPctVsProductionBase"] = improvement_pct(production_metric["mae"], metric["mae"]) if stage not in {"00_pace_baseline", "01_production_usage_base"} else (0.0 if stage == "01_production_usage_base" else np.nan)
            row["promotionEligible"] = bool(spec["promotionEligible"])
            row["note"] = spec["note"]
            if stage not in {"00_pace_baseline", "01_production_usage_base"}:
                row.update(comparison_stats(season_df, stage, "01_production_usage_base", group, test_start, test_end))
            else:
                row.update(
                    {
                        "seasonBlocks": 0,
                        "seasonBlockWinPctVsProductionBase": np.nan,
                        "recent4SeasonImprovementPctVsProductionBase": np.nan,
                    }
                )
            rows.append(row)
    return pd.DataFrame(rows)


def candidate_table(position_checkpoint: pd.DataFrame) -> pd.DataFrame:
    rows: List[dict] = []
    for row in position_checkpoint.to_dict("records"):
        stage = str(row.get("stage") or "")
        if stage in {"00_pace_baseline", "01_production_usage_base"}:
            continue
        eligible = bool(row.get("promotionEligible", False))
        improvement = safe_float(row.get("maeImprovementPctVsProductionBase"), np.nan)
        wins = safe_float(row.get("seasonBlockWinPctVsProductionBase"), np.nan)
        recent = safe_float(row.get("recent4SeasonImprovementPctVsProductionBase"), np.nan)
        research_candidate = bool(
            eligible
            and math.isfinite(improvement)
            and improvement >= MIN_IMPROVEMENT_PCT
            and math.isfinite(wins)
            and wins >= MIN_BLOCK_WIN_PCT
            and math.isfinite(recent)
            and recent >= MIN_RECENT_IMPROVEMENT_PCT
        )
        reason = "Independent environment signal clears v1.9b held-out gate." if research_candidate else "Keep research-only; isolated held-out gate not cleared."
        if not eligible:
            reason = "Diagnostic only for rate target; move to availability/games-played research."
        rows.append(
            {
                "position": row.get("position"),
                "checkpoint": row.get("checkpoint"),
                "stage": stage,
                "researchCandidate": research_candidate,
                "promotionEligible": eligible,
                "maeImprovementPctVsProductionBase": improvement,
                "seasonBlockWinPctVsProductionBase": wins,
                "recent4SeasonImprovementPctVsProductionBase": recent,
                "reason": reason,
            }
        )
    return pd.DataFrame(rows)


def production_decay_table(position_checkpoint: pd.DataFrame) -> pd.DataFrame:
    base = position_checkpoint[position_checkpoint["stage"] == "01_production_usage_base"].copy()
    if base.empty:
        return pd.DataFrame()
    def label(value: float) -> str:
        value = safe_float(value, np.nan)
        if not math.isfinite(value):
            return "unknown"
        if value >= 5.0:
            return "strong-history"
        if value >= 1.0:
            return "reduced-history"
        if value > -1.0:
            return "near-neutral"
        return "current-season-dominant"
    base["historyUseRecommendation"] = base["maeImprovementPctVsPace"].map(label)
    return base[["position", "checkpoint", "rows", "mae", "maeImprovementPctVsPace", "historyUseRecommendation"]]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--features", type=Path, default=Path("model-lab/output/v19-player-features/player_features.csv"))
    parser.add_argument("--out", type=Path, default=Path("model-lab/output/v19-player-isolated"))
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

    catalog = stage_catalog()
    predictions: List[pd.DataFrame] = []
    season_metrics: List[dict] = []
    seasons = sorted(int(value) for value in data["season"].dropna().unique() if int(value) >= args.test_start)
    test_end = max(seasons) if seasons else args.test_start

    for position in sorted(data["position"].dropna().unique()):
        for checkpoint in sorted(int(value) for value in data[data["position"] == position]["checkpoint"].dropna().unique()):
            block = data[(data["position"] == position) & (data["checkpoint"] == checkpoint)].copy()
            for test_season in seasons:
                test = block[block["season"] == test_season].copy()
                train = block[block["season"] < test_season].copy()
                if len(test) < 5 or len(train) < 25:
                    continue

                pace = make_prediction_frame(test, "00_pace_baseline", np.zeros(len(test), dtype=float), 0)
                predictions.append(pace)
                season_metrics.append({"season": test_season, "checkpoint": checkpoint, "position": position, "stage": "00_pace_baseline", **metrics(pace, "prediction")})

                base_adjustment, base_count = evaluate_stage(train, test, PRODUCTION_FEATURES, args.max_neighbors)
                base = make_prediction_frame(test, "01_production_usage_base", base_adjustment, base_count)
                predictions.append(base)
                season_metrics.append({"season": test_season, "checkpoint": checkpoint, "position": position, "stage": "01_production_usage_base", "featureCount": base_count, **metrics(base, "prediction")})

                for stage, incremental, _eligible, applicable_positions, _note in ENVIRONMENT_GROUPS:
                    if position not in applicable_positions:
                        continue
                    columns = unique_columns(PRODUCTION_FEATURES + incremental)
                    adjustment, count = evaluate_stage(train, test, columns, args.max_neighbors)
                    result = make_prediction_frame(test, stage, adjustment, count)
                    predictions.append(result)
                    season_metrics.append({"season": test_season, "checkpoint": checkpoint, "position": position, "stage": stage, "featureCount": count, **metrics(result, "prediction")})

    prediction_df = pd.concat(predictions, ignore_index=True) if predictions else pd.DataFrame()
    season_df = pd.DataFrame(season_metrics)
    if prediction_df.empty:
        raise RuntimeError("No isolated backtest predictions were produced")

    overall = aggregate_rows(prediction_df, season_df, catalog, [], args.test_start, test_end)
    by_position = aggregate_rows(prediction_df, season_df, catalog, ["position"], args.test_start, test_end)
    by_position_checkpoint = aggregate_rows(prediction_df, season_df, catalog, ["position", "checkpoint"], args.test_start, test_end)
    candidates = candidate_table(by_position_checkpoint)
    decay = production_decay_table(by_position_checkpoint)

    prediction_df.to_csv(args.out / "isolated_predictions.csv", index=False)
    season_df.to_csv(args.out / "isolated_season_metrics.csv", index=False)
    overall.to_csv(args.out / "isolated_stage_summary.csv", index=False)
    by_position.to_csv(args.out / "isolated_position_summary.csv", index=False)
    by_position_checkpoint.to_csv(args.out / "isolated_position_checkpoint_summary.csv", index=False)
    candidates.to_csv(args.out / "isolated_promotion_candidates.csv", index=False)
    decay.to_csv(args.out / "production_history_decay.csv", index=False)

    result = {
        "lab": "GRIDIRON PULSE v1.9b isolated environment tests",
        "researchOnly": True,
        "productionWeightsSelected": False,
        "testStart": args.test_start,
        "testEnd": test_end,
        "baseline": "01_production_usage_base",
        "candidateGate": {
            "minimumMaeImprovementPctVsProductionBase": MIN_IMPROVEMENT_PCT,
            "minimumSeasonBlockWinPct": MIN_BLOCK_WIN_PCT,
            "minimumRecent4SeasonImprovementPct": MIN_RECENT_IMPROVEMENT_PCT,
        },
        "healthPolicy": "Health is diagnostic only for the 17-game-equivalent rate target; it is reserved for a separate availability/games-played layer.",
        "tests": catalog,
        "researchCandidates": candidates[candidates["researchCandidate"] == True].to_dict("records") if not candidates.empty else [],
        "productionHistoryDecay": decay.to_dict("records") if not decay.empty else [],
    }
    (args.out / "isolated_backtest_summary.json").write_text(json.dumps(result, indent=2), encoding="utf-8")

    print("\nGRIDIRON PULSE v1.9b ISOLATED ENVIRONMENT TESTS")
    print("\nPOSITION / CHECKPOINT RESULTS")
    print(by_position_checkpoint.to_string(index=False))
    print("\nPROMOTION CANDIDATES")
    print(candidates.to_string(index=False) if not candidates.empty else "none")
    print("\nHISTORY DECAY")
    print(decay.to_string(index=False) if not decay.empty else "none")
    print("\nSUMMARY")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
