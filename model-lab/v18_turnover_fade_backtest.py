#!/usr/bin/env python3
"""GRIDIRON PULSE v1.8-B targeted turnover fade backtest.

Research only. This tests the pre-registered hypothesis that net turnover
sequence value is most useful early, should fade by Week 8, and should be
nearly/off by Week 12. It also tests turnover-neutralized margin only at
Week 8, where the first signal screen showed its strongest result.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Dict, List, Mapping, Tuple

import numpy as np
import pandas as pd

from v18_turnover_features import (
    add_schedule_features,
    build_turnover_checkpoints,
    load_history,
)

COMPS = 40
CHECKPOINTS = (4, 8, 12)
RECENT_START = 2022

BASE_WEIGHTS = {
    "winPct": 1.30,
    "margin": 1.25,
    "ppg": 0.80,
    "papg": 0.80,
    "pythWinPct": 1.20,
    "winLuck": 1.00,
    "closeGamePct": 0.50,
    "closeWinPct": 0.60,
    "blowoutWinPct": 0.50,
    "last3Margin": 0.90,
    "momentum": 0.40,
    "offConsistency": 0.30,
    "defConsistency": 0.30,
    "offensePulse": 0.80,
    "defensePulse": 0.80,
    "tandemPulse": 1.10,
    "oppQuality": 0.35,
    "scheduleStrength": 0.25,
    "scheduleAdjustedMargin": 0.35,
    "qbContinuity": 0.50,
    "coachContinuity": 0.15,
}

VARIANTS = (
    "baseline",
    "net_fixed_045",
    "fade_conservative",
    "fade_balanced",
    "fade_strong_early",
    "fade_soft_tail",
    "neutralized_week8",
    "fade_plus_neutralized_week8",
)

# Pre-registered checkpoint weights. We are intentionally not searching a
# fine-grained grid; these are a small set of plausible fade schedules.
NET_WEIGHTS = {
    "net_fixed_045": {4: 0.45, 8: 0.45, 12: 0.45},
    "fade_conservative": {4: 0.35, 8: 0.15, 12: 0.00},
    "fade_balanced": {4: 0.45, 8: 0.20, 12: 0.00},
    "fade_strong_early": {4: 0.55, 8: 0.20, 12: 0.00},
    "fade_soft_tail": {4: 0.45, 8: 0.20, 12: 0.05},
    "fade_plus_neutralized_week8": {4: 0.45, 8: 0.12, 12: 0.00},
}


def variant_weights(name: str, week: int) -> Dict[str, float]:
    weights = dict(BASE_WEIGHTS)

    use_neutralized = name in {
        "neutralized_week8",
        "fade_plus_neutralized_week8",
    } and int(week) == 8

    if use_neutralized:
        weights.pop("margin", None)
        weights.pop("scheduleAdjustedMargin", None)
        weights["turnoverNeutralMargin"] = BASE_WEIGHTS["margin"]
        weights["turnoverNeutralScheduleAdjustedMargin"] = BASE_WEIGHTS["scheduleAdjustedMargin"]

    net_weight = NET_WEIGHTS.get(name, {}).get(int(week), 0.0)
    if net_weight > 0:
        weights["netTurnoverPointsPerGame"] = float(net_weight)

    return weights


def predict_one(
    target: pd.Series,
    train: pd.DataFrame,
    weights: Mapping[str, float],
) -> float:
    features = [
        feature
        for feature, weight in weights.items()
        if weight > 0 and feature in train.columns and feature in target.index
    ]
    if not features:
        return float(pd.to_numeric(train["finalWinsEq17"], errors="coerce").mean())

    x = train[features].apply(pd.to_numeric, errors="coerce").copy()
    target_values = pd.to_numeric(target[features], errors="coerce")

    means = x.mean(axis=0)
    scales = x.std(axis=0, ddof=0).replace(0, np.nan).fillna(1.0)
    x = x.fillna(means).fillna(0.0)
    target_values = target_values.fillna(means).fillna(0.0)

    dist2 = np.zeros(len(x), dtype=float)
    for feature in features:
        z = (
            x[feature].to_numpy(dtype=float) - float(target_values[feature])
        ) / max(1e-6, float(scales[feature]))
        dist2 += float(weights[feature]) * z * z

    distance = np.sqrt(dist2)
    n = min(COMPS, len(distance))
    if n <= 0:
        return float("nan")

    idx = np.argpartition(distance, n - 1)[:n]
    nearest_distance = distance[idx]
    nearest_min = float(nearest_distance.min())
    comp_weights = np.exp(-(nearest_distance - nearest_min) / 2.0)

    outcomes = pd.to_numeric(
        train.iloc[idx]["finalWinsEq17"], errors="coerce"
    ).to_numpy(dtype=float)
    valid = np.isfinite(outcomes) & np.isfinite(comp_weights)
    if not valid.any() or comp_weights[valid].sum() <= 0:
        return float(np.nanmean(outcomes))

    return float(
        np.dot(outcomes[valid], comp_weights[valid]) / comp_weights[valid].sum()
    )


def prepare_dataset(history_path: Path, sequence_path: Path) -> Tuple[pd.DataFrame, int]:
    history = load_history(history_path)
    sequences = pd.read_csv(sequence_path, low_memory=False)
    turnover = build_turnover_checkpoints(history, sequences)

    merged = history.merge(
        turnover,
        on=["season", "week", "games", "team"],
        how="left",
        validate="one_to_one",
    )
    merged = add_schedule_features(merged)

    data_start = int(pd.to_numeric(sequences["season"], errors="coerce").min())
    merged = merged[merged["season"] >= data_start].copy()
    return merged, data_start


def rolling_backtest(
    data: pd.DataFrame,
    test_start: int,
    test_end: int,
) -> pd.DataFrame:
    targets = data[
        data["season"].between(test_start, test_end)
        & data["week"].isin(CHECKPOINTS)
        & pd.to_numeric(data["finalWinsEq17"], errors="coerce").notna()
    ].copy()
    targets = (
        targets.sort_values(["season", "week", "team", "games"])
        .drop_duplicates(["season", "week", "team"], keep="last")
    )

    records: List[dict] = []

    for season in range(test_start, test_end + 1):
        season_targets = targets[targets["season"] == season]
        if season_targets.empty:
            continue

        # Strict no-lookahead: only prior seasons can be comparables.
        prior = data[data["season"] < season]

        for _, target in season_targets.iterrows():
            games = int(target["games"])
            week = int(target["week"])
            train = prior[
                (prior["games"] >= max(1, games - 1))
                & (prior["games"] <= min(17, games + 1))
            ].copy()
            if len(train) < 80:
                continue

            actual = float(target["finalWinsEq17"])

            for variant in VARIANTS:
                weights = variant_weights(variant, week)
                prediction = predict_one(target, train, weights)
                if not math.isfinite(prediction):
                    continue

                records.append(
                    {
                        "season": int(target["season"]),
                        "week": week,
                        "games": games,
                        "team": target["team"],
                        "variant": variant,
                        "netTurnoverWeight": float(
                            weights.get("netTurnoverPointsPerGame", 0.0)
                        ),
                        "usesNeutralizedMargin": bool(
                            "turnoverNeutralMargin" in weights
                        ),
                        "prediction": prediction,
                        "actualFinalWinsEq17": actual,
                        "absError": abs(prediction - actual),
                    }
                )

    return pd.DataFrame(records)


def safe_baseline_value(table: pd.DataFrame, column: str) -> float:
    values = table.loc[table["variant"].eq("baseline"), column].dropna()
    return float(values.iloc[0]) if len(values) else float("nan")


def summarize(results: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame, dict]:
    overall = (
        results.groupby("variant", as_index=False)
        .agg(mae=("absError", "mean"), n=("absError", "size"))
    )

    weekly = (
        results.groupby(["variant", "week"], as_index=False)
        .agg(mae=("absError", "mean"), n=("absError", "size"))
    )

    recent_results = results[results["season"] >= RECENT_START]
    recent = (
        recent_results.groupby("variant", as_index=False)
        .agg(recentMae=("absError", "mean"), recentN=("absError", "size"))
    )
    recent_weekly = (
        recent_results.groupby(["variant", "week"], as_index=False)
        .agg(recentMae=("absError", "mean"), recentN=("absError", "size"))
    )

    table = overall.merge(recent, on="variant", how="left")
    baseline_mae = safe_baseline_value(table, "mae")
    recent_baseline = safe_baseline_value(table, "recentMae")
    table["deltaVsBaseline"] = table["mae"] - baseline_mae
    table["recentDeltaVsBaseline"] = table["recentMae"] - recent_baseline

    by_season = (
        results.groupby(["variant", "season"], as_index=False)
        .agg(mae=("absError", "mean"), n=("absError", "size"))
    )
    baseline_by_season = (
        by_season[by_season["variant"].eq("baseline")][["season", "mae"]]
        .rename(columns={"mae": "baselineMae"})
    )
    by_season = by_season.merge(baseline_by_season, on="season", how="left")
    by_season["deltaVsBaseline"] = by_season["mae"] - by_season["baselineMae"]

    season_counts = (
        by_season[~by_season["variant"].eq("baseline")]
        .groupby("variant")
        .agg(
            seasonsBetter=("deltaVsBaseline", lambda s: int((s < -1e-12).sum())),
            seasonsTied=("deltaVsBaseline", lambda s: int((s.abs() <= 1e-12).sum())),
            seasonsWorse=("deltaVsBaseline", lambda s: int((s > 1e-12).sum())),
            medianSeasonDelta=("deltaVsBaseline", "median"),
        )
        .reset_index()
    )
    table = table.merge(season_counts, on="variant", how="left")

    baseline_week = weekly[weekly["variant"].eq("baseline")][["week", "mae"]].rename(
        columns={"mae": "baselineWeekMae"}
    )
    weekly_compare = weekly.merge(baseline_week, on="week", how="left")
    weekly_compare["deltaVsBaseline"] = (
        weekly_compare["mae"] - weekly_compare["baselineWeekMae"]
    )

    week_pivot = weekly_compare.pivot(
        index="variant", columns="week", values="deltaVsBaseline"
    )
    for week in CHECKPOINTS:
        table[f"week{week}Delta"] = table["variant"].map(
            week_pivot[week] if week in week_pivot.columns else {}
        )

    # Promotion screen: overall and recent cannot be worse; Week 4/8 must be
    # non-worse, Week 12 can only be neutral/better, and more held-out seasons
    # must improve than worsen. This is a research screen, not auto-deployment.
    def promotion_candidate(row: pd.Series) -> bool:
        if row["variant"] == "baseline":
            return False
        checks = [
            row.get("deltaVsBaseline", np.nan) <= 0,
            row.get("recentDeltaVsBaseline", np.nan) <= 0,
            row.get("week4Delta", np.nan) <= 0,
            row.get("week8Delta", np.nan) <= 0,
            row.get("week12Delta", np.nan) <= 1e-12,
            float(row.get("seasonsBetter", 0) or 0)
            >= float(row.get("seasonsWorse", 0) or 0),
        ]
        return bool(all(checks))

    table["passesPromotionScreen"] = table.apply(promotion_candidate, axis=1)
    table = table.sort_values(["mae", "variant"]).reset_index(drop=True)

    non_base = table[~table["variant"].eq("baseline")]
    best = non_base.iloc[0] if len(non_base) else table.iloc[0]
    passing = table[table["passesPromotionScreen"].eq(True)]

    summary = {
        "testName": "GRIDIRON PULSE v1.8-B targeted turnover fade screen",
        "testType": "rolling no-lookahead historical comparable backtest",
        "scope": (
            "Tests early-season/fading net turnover sequence value and a Week-8-only "
            "turnover-neutralized margin hypothesis. Production is unchanged."
        ),
        "noLookahead": (
            "Each held-out season uses only prior seasons; scaling and imputation "
            "are computed only from that prior-season training set."
        ),
        "checkpoints": list(CHECKPOINTS),
        "comparables": COMPS,
        "recentWindow": f"{RECENT_START}-2025",
        "baselineMae": round(baseline_mae, 6),
        "recentBaselineMae": round(recent_baseline, 6),
        "bestNonBaselineVariant": str(best["variant"]),
        "bestNonBaselineMae": round(float(best["mae"]), 6),
        "bestDeltaVsBaseline": round(float(best["deltaVsBaseline"]), 6),
        "promotionCandidates": passing["variant"].tolist(),
        "preRegisteredNetWeights": NET_WEIGHTS,
        "promotionScreen": (
            "Overall non-worse, 2022+ non-worse, Weeks 4/8 non-worse, Week 12 "
            "non-worse, and held-out seasons better >= worse. Passing is not automatic deployment."
        ),
    }

    detail = {
        "summary": summary,
        "weekly": weekly_compare.to_dict("records"),
        "recentWeekly": recent_weekly.to_dict("records"),
    }
    return table, by_season, detail


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--sequences", type=Path, required=True)
    parser.add_argument("--test-start", type=int, default=2014)
    parser.add_argument("--test-end", type=int, default=2025)
    parser.add_argument("--out", type=Path, default=Path("model-lab/output"))
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    data, data_start = prepare_dataset(args.history, args.sequences)
    results = rolling_backtest(data, args.test_start, args.test_end)
    if results.empty:
        raise RuntimeError("v1.8-B backtest generated no predictions")

    ranking, by_season, detail = summarize(results)

    results.to_csv(args.out / "turnover_fade_backtest_predictions.csv", index=False)
    ranking.to_csv(args.out / "turnover_fade_backtest_ranking.csv", index=False)
    by_season.to_csv(args.out / "turnover_fade_backtest_by_season.csv", index=False)

    payload = {
        **detail,
        "dataStartSeason": data_start,
        "testStartSeason": args.test_start,
        "testEndSeason": args.test_end,
        "predictionRows": int(len(results)),
        "ranking": json.loads(ranking.to_json(orient="records")),
    }
    (args.out / "turnover_fade_backtest_summary.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )

    print("\nGRIDIRON PULSE v1.8-B TARGETED TURNOVER FADE SCREEN")
    print(ranking.to_string(index=False, float_format=lambda x: f"{x:.6f}"))

    weekly = pd.DataFrame(detail["weekly"])
    print("\nWEEKLY MAE")
    print(
        weekly.pivot(index="variant", columns="week", values="mae")
        .sort_values(4)
        .to_string(float_format=lambda x: f"{x:.6f}")
    )

    recent_weekly = pd.DataFrame(detail["recentWeekly"])
    print("\nRECENT WEEKLY MAE")
    if len(recent_weekly):
        print(
            recent_weekly.pivot(index="variant", columns="week", values="recentMae")
            .sort_values(4)
            .to_string(float_format=lambda x: f"{x:.6f}")
        )
    else:
        print("No recent rows")

    print("\nSUMMARY")
    print(json.dumps(payload["summary"], indent=2))


if __name__ == "__main__":
    main()
