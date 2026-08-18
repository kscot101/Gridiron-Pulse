#!/usr/bin/env python3
"""Fast exact-integration replay for GRIDIRON PULSE v1.8.

This preserves the same integration math as v18_exact_integration_replay.py,
but vectorizes historical comparable distance calculations and prints progress
for every season/checkpoint so GitHub Actions no longer appears frozen.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Sequence, Tuple

import numpy as np
import pandas as pd

from v18_turnover_features import build_turnover_checkpoints, load_history
from v18_exact_integration_replay import (
    COMPS,
    CHECKPOINTS,
    RECENT_START,
    SIMULATIONS,
    SeasonGameStore,
    season_worker_base,
    projection_strength,
    build_target_features,
    team_season_index,
    coach_season_rows,
    historical_coach_impact,
    historical_opponent_quality_without_own_result,
    historical_schedule_strength,
    integration_weights,
    integrated_prediction,
    build_turnover_indexes,
    summarize,
    canon,
    r1,
    clamp,
    weighted_quantile,
    SCHEDULE_MARGIN_SCALE,
)


def finite_float(value: object, default: float = float("nan")) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


class FastComparableBucket:
    def __init__(self, rows: Sequence[dict]):
        self.rows = list(rows)
        self.outcomes = np.asarray(
            [finite_float(row.get("finalWinsEq17")) for row in self.rows],
            dtype=float,
        )
        self._matrix_cache: Dict[Tuple[str, ...], Tuple[np.ndarray, np.ndarray]] = {}

    def _matrix(self, features: Sequence[str]) -> Tuple[np.ndarray, np.ndarray]:
        key = tuple(features)
        cached = self._matrix_cache.get(key)
        if cached is not None:
            return cached

        matrix = np.full((len(self.rows), len(features)), np.nan, dtype=float)
        for column, feature in enumerate(features):
            matrix[:, column] = np.fromiter(
                (finite_float(row.get(feature)) for row in self.rows),
                dtype=float,
                count=len(self.rows),
            )

        scales = np.ones(len(features), dtype=float)
        for column in range(len(features)):
            values = matrix[:, column]
            finite = values[np.isfinite(values)]
            if len(finite) >= 2:
                scale = float(np.std(finite, ddof=0))
                scales[column] = scale if math.isfinite(scale) and scale > 0 else 1.0
            else:
                scales[column] = 1.0

        self._matrix_cache[key] = (matrix, scales)
        return matrix, scales

    def summary(self, target: Mapping[str, float], weights: Mapping[str, float]) -> dict:
        features = [
            feature
            for feature, weight in weights.items()
            if weight > 0 and feature in target and any(feature in row for row in self.rows)
        ]
        if not features or not self.rows:
            return {
                "count": 0,
                "meanWins": 8.5,
                "targetWins": 8.5,
                "similarity": 50.0,
                "outcomeSpreadWins": 6.5,
            }

        matrix, scales = self._matrix(features)
        target_vector = np.asarray([finite_float(target.get(feature)) for feature in features], dtype=float)
        feature_weights = np.asarray([float(weights[feature]) for feature in features], dtype=float)

        differences = matrix - target_vector[None, :]
        valid = np.isfinite(differences) & np.isfinite(target_vector[None, :])
        z = np.zeros_like(differences)
        np.divide(differences, scales[None, :], out=z, where=valid)
        distance = np.sqrt(np.sum((z * z) * feature_weights[None, :], axis=1))

        n = min(COMPS, len(distance))
        if n <= 0:
            return {
                "count": 0,
                "meanWins": 8.5,
                "targetWins": 8.5,
                "similarity": 50.0,
                "outcomeSpreadWins": 6.5,
            }

        idx = np.argpartition(distance, n - 1)[:n]
        idx = idx[np.argsort(distance[idx])]
        nearest_distance = distance[idx]
        minimum = float(nearest_distance[0])
        comp_weights = np.exp(-(nearest_distance - minimum) / 2.0)
        outcomes = self.outcomes[idx]
        ok = np.isfinite(outcomes) & np.isfinite(comp_weights)
        if not ok.any() or comp_weights[ok].sum() <= 0:
            mean_wins = float(np.nanmean(outcomes))
            similarity = 50.0
            spread = 6.5
        else:
            usable_outcomes = outcomes[ok]
            usable_weights = comp_weights[ok]
            total_weight = float(usable_weights.sum())
            mean_wins = float(np.dot(usable_outcomes, usable_weights) / total_weight)
            weighted_distance = float(np.dot(nearest_distance[ok], usable_weights) / total_weight)
            similarity = clamp(100.0 - weighted_distance * 11.0, 25.0, 98.0)
            weighted_values = list(zip(usable_outcomes.tolist(), usable_weights.tolist()))
            low = weighted_quantile(weighted_values, 0.20)
            high = weighted_quantile(weighted_values, 0.80)
            spread = max(0.0, high - low)

        return {
            "count": int(n),
            "meanWins": r1(mean_wins),
            "targetWins": r1(mean_wins),
            "similarity": r1(similarity),
            "outcomeSpreadWins": r1(spread),
        }


def enrich_history_rows(
    history: pd.DataFrame,
    history_raw: dict,
    team_index: Mapping[Tuple[int, str], dict],
    coach_rows: Sequence[dict],
    turnover_by_row: Mapping[Tuple[int, int, int, str], dict],
) -> pd.DataFrame:
    print("[fast replay] Precomputing historical coach/schedule/turnover features...", flush=True)

    coach_cache: Dict[Tuple[int, str], float] = {}
    records: List[dict] = []

    for raw in history.to_dict("records"):
        row = dict(raw)
        season = int(row["season"])
        week = int(row["week"])
        games = int(row["games"])
        team = canon(row["team"])
        row["team"] = team

        coach_key = (season, team)
        if coach_key not in coach_cache:
            coach_cache[coach_key] = historical_coach_impact(
                history_raw,
                team_index,
                coach_rows,
                season,
                team,
            )
        row["coachImpact"] = coach_cache[coach_key]

        row["rawOpponentQuality"] = finite_float(row.get("oppQuality"), 0.5)
        row["oppQuality"] = historical_opponent_quality_without_own_result(row)
        row["scheduleStrength"] = historical_schedule_strength(row)
        row["scheduleAdjustedMargin"] = finite_float(row.get("margin"), 0.0) + (
            finite_float(row.get("scheduleStrength"), 0.5) - 0.5
        ) * SCHEDULE_MARGIN_SCALE

        turnover = turnover_by_row.get((season, week, games, team), {})
        net = finite_float(turnover.get("netTurnoverPointsPerGame"), 0.0)
        row["netTurnoverPointsPerGame"] = net
        row["turnoverNeutralMargin"] = finite_float(row.get("margin"), 0.0) - net
        row["turnoverNeutralScheduleAdjustedMargin"] = finite_float(row.get("scheduleAdjustedMargin"), 0.0) - net
        records.append(row)

    output = pd.DataFrame(records)
    print(f"[fast replay] Historical feature rows ready: {len(output):,}", flush=True)
    return output


def bucket_rows(
    enriched_history: pd.DataFrame,
    current_season: int,
    games_played: int,
) -> List[dict]:
    wanted = {
        max(1, games_played - 1),
        max(1, games_played),
        min(17, games_played + 1),
    }
    subset = enriched_history[
        (enriched_history["season"] < current_season)
        & (enriched_history["games"].isin(wanted))
    ]
    return subset.to_dict("records")


def run_fast_replay(
    history_path: Path,
    sequences_path: Path,
    pbp_cache: Path,
    test_start: int,
    test_end: int,
) -> pd.DataFrame:
    history = load_history(history_path)
    history_raw = json.loads(history_path.read_text(encoding="utf-8"))
    sequences = pd.read_csv(sequences_path, low_memory=False)
    turnover = build_turnover_checkpoints(history, sequences)
    turnover_by_week, turnover_by_row = build_turnover_indexes(turnover)

    game_store = SeasonGameStore(pbp_cache)
    team_index = team_season_index(history)
    coach_rows = coach_season_rows(history_raw, team_index)
    enriched_history = enrich_history_rows(
        history,
        history_raw,
        team_index,
        coach_rows,
        turnover_by_row,
    )

    base_cache: Dict[Tuple[int, int], Dict[str, float]] = {}
    prior_cache: Dict[int, Dict[str, float]] = {}
    bucket_cache: Dict[Tuple[int, int], FastComparableBucket] = {}
    records: List[dict] = []

    total_checkpoints = (test_end - test_start + 1) * len(CHECKPOINTS)
    checkpoint_number = 0

    for season in range(test_start, test_end + 1):
        print(f"[fast replay] Season {season}: building frozen preseason Season Worker prior...", flush=True)
        preseason_base = base_cache.setdefault(
            (season, 0),
            season_worker_base(season, 0, game_store),
        )
        preseason_priors = prior_cache.setdefault(
            season,
            {team: projection_strength(wins) for team, wins in preseason_base.items()},
        )

        for checkpoint_week in CHECKPOINTS:
            checkpoint_number += 1
            print(
                f"[fast replay] {checkpoint_number}/{total_checkpoints} | Season {season} | Week {checkpoint_week}: "
                "Season Worker simulation...",
                flush=True,
            )

            base = base_cache.setdefault(
                (season, checkpoint_week),
                season_worker_base(season, checkpoint_week, game_store),
            )

            print(
                f"[fast replay] {checkpoint_number}/{total_checkpoints} | Season {season} | Week {checkpoint_week}: "
                "building checkpoint features...",
                flush=True,
            )
            features = build_target_features(
                season,
                checkpoint_week,
                game_store,
                history,
                history_raw,
                team_index,
                coach_rows,
                preseason_priors,
                turnover_by_week,
            )

            target_rows = history[
                (history["season"] == season)
                & (history["week"] == checkpoint_week)
            ]
            actual_by_team = {
                canon(row.team): float(row.finalWinsEq17)
                for row in target_rows.itertuples(index=False)
            }

            completed = 0
            for team, feature in features.items():
                if team not in actual_by_team or team not in base:
                    continue

                games_played = int(feature["games"])
                cache_key = (season, games_played)
                if cache_key not in bucket_cache:
                    bucket_cache[cache_key] = FastComparableBucket(
                        bucket_rows(enriched_history, season, games_played)
                    )
                bucket = bucket_cache[cache_key]
                if len(bucket.rows) < COMPS:
                    continue

                actual = actual_by_team[team]
                base_mean = float(base[team])

                comp17 = bucket.summary(
                    feature,
                    integration_weights("v1.7.0", checkpoint_week),
                )
                pred17, delta17, blend17 = integrated_prediction(
                    base_mean,
                    feature,
                    comp17,
                )

                comp18 = bucket.summary(
                    feature,
                    integration_weights("v1.8.0-candidate", checkpoint_week),
                )
                pred18, delta18, blend18 = integrated_prediction(
                    base_mean,
                    feature,
                    comp18,
                )

                records.append(
                    {
                        "season": season,
                        "week": checkpoint_week,
                        "games": games_played,
                        "team": team,
                        "actualFinalWinsEq17": actual,
                        "seasonWorkerBase": base_mean,
                        "v17Prediction": pred17,
                        "v18Prediction": pred18,
                        "baseAbsError": abs(base_mean - actual),
                        "v17AbsError": abs(pred17 - actual),
                        "v18AbsError": abs(pred18 - actual),
                        "v17DeltaWins": delta17,
                        "v18DeltaWins": delta18,
                        "v17Blend": blend17,
                        "v18Blend": blend18,
                        "v17ComparableMean": comp17["meanWins"],
                        "v18ComparableMean": comp18["meanWins"],
                        "v17Similarity": comp17["similarity"],
                        "v18Similarity": comp18["similarity"],
                        "netTurnoverPointsPerGame": finite_float(feature.get("netTurnoverPointsPerGame"), 0.0),
                        "rawMargin": finite_float(feature.get("margin"), 0.0),
                        "turnoverNeutralMargin": finite_float(feature.get("turnoverNeutralMargin"), 0.0),
                        "scheduleAdjustedMargin": finite_float(feature.get("scheduleAdjustedMargin"), 0.0),
                        "turnoverNeutralScheduleAdjustedMargin": finite_float(
                            feature.get("turnoverNeutralScheduleAdjustedMargin"),
                            0.0,
                        ),
                    }
                )
                completed += 1

            print(
                f"[fast replay] {checkpoint_number}/{total_checkpoints} | Season {season} | Week {checkpoint_week}: "
                f"complete ({completed} teams).",
                flush=True,
            )

    return pd.DataFrame(records)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--sequences", type=Path, required=True)
    parser.add_argument("--pbp-cache", type=Path, required=True)
    parser.add_argument("--test-start", type=int, default=2014)
    parser.add_argument("--test-end", type=int, default=2025)
    parser.add_argument("--out", type=Path, default=Path("model-lab/output"))
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    results = run_fast_replay(
        args.history,
        args.sequences,
        args.pbp_cache,
        args.test_start,
        args.test_end,
    )
    report = summarize(results)
    report["summary"]["engine"] = "optimized-vectorized-equivalent"
    report["summary"]["progressLogging"] = True

    results.to_csv(
        args.out / "turnover_exact_integration_predictions.csv",
        index=False,
    )
    pd.DataFrame(report["ranking"]).to_csv(
        args.out / "turnover_exact_integration_ranking.csv",
        index=False,
    )
    pd.DataFrame(report["weekly"]).to_csv(
        args.out / "turnover_exact_integration_weekly.csv",
        index=False,
    )
    pd.DataFrame(report["bySeason"]).to_csv(
        args.out / "turnover_exact_integration_by_season.csv",
        index=False,
    )
    (args.out / "turnover_exact_integration_summary.json").write_text(
        json.dumps(report, indent=2),
        encoding="utf-8",
    )

    print("\nGRIDIRON PULSE v1.8 FAST EXACT INTEGRATION REPLAY", flush=True)
    print(
        pd.DataFrame(report["ranking"]).to_string(
            index=False,
            float_format=lambda value: f"{value:.6f}",
        ),
        flush=True,
    )
    print("\nWEEKLY MAE", flush=True)
    print(
        pd.DataFrame(report["weekly"])
        .pivot(index="model", columns="week", values="mae")
        .to_string(float_format=lambda value: f"{value:.6f}"),
        flush=True,
    )
    print("\nSUMMARY", flush=True)
    print(json.dumps(report["summary"], indent=2), flush=True)


if __name__ == "__main__":
    main()
