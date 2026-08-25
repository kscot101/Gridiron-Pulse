#!/usr/bin/env python3
"""GRIDIRON PULSE v1.9h reproducible Season Worker integration replay.

This lab bridges the validated v1.9 player stack back to the current Season
Worker architecture without pretending historical inputs exist when they do
not. It reproduces the Worker pieces that are reconstructible point-in-time:

- the exact v1.2.0 currentSeasonWeight(gamesPlayed) curve;
- realized current totals plus projected remaining production accounting;
- the same QB/RB/WR/TE primary-stat definitions used by the research dataset.

Historical live-only inputs that were not persisted (exact Heat Score/profile,
team rating, trade/scheme multiplier, and live role-assignment state) are
neutralized. For the Worker weighting bridge, prior-year player production per
game is used as the neutral prior rate; when no prior exists, current rate is
used so the replay does not invent a role baseline.

The comparison is therefore a reproducible-core integration replay, not a claim
that every historical Season Worker snapshot can be reconstructed exactly.
Research only. This script does not alter or select production Worker weights.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import List, Mapping, Sequence

import numpy as np
import pandas as pd

from v19_player_comparable_backtest import safe_float
from v19_player_isolated_environment_backtest import improvement_pct
from v19_player_availability_backtest import enrich_availability_columns

KEY_COLUMNS = ["season", "checkpoint", "position", "playerKey"]
RATE_STAGE = "11_rate_gate_full_availability"
STACK_STAGE = "12_rate_gate_selected_availability"
MIN_INTEGRATION_IMPROVEMENT_PCT = 2.0
MIN_BLOCK_WIN_PCT = 55.0
MIN_RECENT4_IMPROVEMENT_PCT = 0.0


def worker_current_season_weight(games_played: float) -> float:
    """Exact Python port of Season Worker v1.2.0 currentSeasonWeight()."""
    games = max(0.0, safe_float(games_played, 0.0))
    if games <= 0:
        return 0.0
    if games <= 4:
        return (games / 4.0) * 0.4
    if games <= 8:
        return 0.4 + ((games - 4.0) / 4.0) * 0.3
    return max(0.7, min(0.9, 0.7 + ((games - 8.0) / 9.0) * 0.2))


def mae(actual: pd.Series, predicted: pd.Series) -> float:
    a = pd.to_numeric(actual, errors="coerce").to_numpy(dtype=float)
    p = pd.to_numeric(predicted, errors="coerce").to_numpy(dtype=float)
    valid = np.isfinite(a) & np.isfinite(p)
    if not valid.any():
        return np.nan
    return float(np.mean(np.abs(a[valid] - p[valid])))


def worker_bridge_frame(features: pd.DataFrame) -> pd.DataFrame:
    work = enrich_availability_columns(features)
    for column in [
        "currentPrimary",
        "current_primary_pg",
        "prior_primary_pg",
        "prior_data_available",
        "availability_rate",
        "games",
        "finalGames",
        "finalPrimary",
        "remainingTeamGames",
    ]:
        work[column] = pd.to_numeric(work.get(column), errors="coerce")

    current_pg = work["current_primary_pg"].fillna(0.0).clip(lower=0.0)
    prior_pg_raw = work["prior_primary_pg"]
    prior_available = work["prior_data_available"].fillna(0.0) > 0.5
    usable_prior = prior_available & prior_pg_raw.notna() & np.isfinite(prior_pg_raw)
    prior_pg = current_pg.where(~usable_prior, prior_pg_raw.clip(lower=0.0))

    worker_weight = work["games"].fillna(0.0).map(worker_current_season_weight)
    blended_pg = prior_pg * (1.0 - worker_weight) + current_pg * worker_weight

    remaining_games = work["remainingTeamGames"].fillna(0.0).clip(lower=0.0)
    current_primary = work["currentPrimary"].fillna(0.0).clip(lower=0.0)
    current_availability = work["availability_rate"].fillna(1.0).clip(0.0, 1.0)

    result = work[
        KEY_COLUMNS
        + [
            "playerName",
            "team",
            "finalPrimary",
            "finalGames",
            "currentPrimary",
            "games",
            "remainingTeamGames",
        ]
    ].copy()
    result["workerCurrentSeasonWeight"] = worker_weight.to_numpy(dtype=float)
    result["workerPriorRatePg"] = prior_pg.to_numpy(dtype=float)
    result["workerCurrentRatePg"] = current_pg.to_numpy(dtype=float)
    result["workerBlendedRatePg"] = blended_pg.to_numpy(dtype=float)
    result["workerPriorSource"] = np.where(
        usable_prior,
        "prior-year-production",
        "current-rate-neutral-fallback",
    )

    result["workerFullAvailabilityPrediction"] = (
        current_primary + blended_pg * remaining_games
    ).to_numpy(dtype=float)
    result["workerCurrentAvailabilityProxyPrediction"] = (
        current_primary + blended_pg * remaining_games * current_availability
    ).to_numpy(dtype=float)
    result["workerFullAvailabilityFinalGames"] = (
        work["games"].fillna(0.0) + remaining_games
    ).to_numpy(dtype=float)
    result["workerCurrentAvailabilityProxyFinalGames"] = (
        work["games"].fillna(0.0) + remaining_games * current_availability
    ).to_numpy(dtype=float)
    return result


def attach_v19_predictions(
    worker: pd.DataFrame,
    availability_predictions: pd.DataFrame,
) -> pd.DataFrame:
    predictions = availability_predictions.copy()
    predictions["season"] = pd.to_numeric(
        predictions["season"], errors="coerce"
    ).astype("Int64")
    predictions["checkpoint"] = pd.to_numeric(
        predictions["checkpoint"], errors="coerce"
    ).astype("Int64")

    rate = predictions[predictions["stage"] == RATE_STAGE][
        KEY_COLUMNS + ["prediction", "predictedFinalGames"]
    ].rename(
        columns={
            "prediction": "v19RateGateFullAvailabilityPrediction",
            "predictedFinalGames": "v19RateGateFullAvailabilityFinalGames",
        }
    )
    stack = predictions[predictions["stage"] == STACK_STAGE][
        KEY_COLUMNS + ["prediction", "predictedFinalGames", "availabilityStrategy"]
    ].rename(
        columns={
            "prediction": "v19SelectedAvailabilityPrediction",
            "predictedFinalGames": "v19SelectedAvailabilityFinalGames",
            "availabilityStrategy": "v19AvailabilityStrategy",
        }
    )
    if rate.empty or stack.empty:
        raise RuntimeError(
            f"Availability predictions must contain stages {RATE_STAGE} and {STACK_STAGE}"
        )

    aligned = worker.merge(rate, on=KEY_COLUMNS, how="inner").merge(
        stack, on=KEY_COLUMNS, how="inner"
    )
    if aligned.empty:
        raise RuntimeError("No aligned rows between Worker replay and v1.9g predictions")
    return aligned


def season_block_stats(frame: pd.DataFrame, filters: Mapping[str, object]) -> dict:
    work = frame.copy()
    for column, value in filters.items():
        work = work[work[column] == value]
    rows: List[dict] = []
    for season, block in work.groupby("season", dropna=False):
        worker_mae = mae(
            block["finalPrimary"],
            block["workerCurrentAvailabilityProxyPrediction"],
        )
        stack_mae = mae(
            block["finalPrimary"],
            block["v19SelectedAvailabilityPrediction"],
        )
        if math.isfinite(worker_mae) and math.isfinite(stack_mae):
            rows.append(
                {
                    "season": int(season),
                    "workerMae": worker_mae,
                    "stackMae": stack_mae,
                    "improvementPct": improvement_pct(worker_mae, stack_mae),
                }
            )
    if not rows:
        return {
            "seasonBlocks": 0,
            "stackBlockWinPctVsWorkerProxy": np.nan,
            "stackRecent4ImprovementPctVsWorkerProxy": np.nan,
        }
    seasons = pd.DataFrame(rows)
    win_pct = float((seasons["stackMae"] <= seasons["workerMae"]).mean() * 100.0)
    recent_years = sorted(int(value) for value in seasons["season"].unique())[-4:]
    recent = work[work["season"].isin(recent_years)]
    recent_worker = mae(
        recent["finalPrimary"],
        recent["workerCurrentAvailabilityProxyPrediction"],
    )
    recent_stack = mae(
        recent["finalPrimary"],
        recent["v19SelectedAvailabilityPrediction"],
    )
    return {
        "seasonBlocks": int(len(seasons)),
        "stackBlockWinPctVsWorkerProxy": win_pct,
        "stackRecent4ImprovementPctVsWorkerProxy": improvement_pct(
            recent_worker, recent_stack
        ),
    }


def aggregate(frame: pd.DataFrame, group_columns: Sequence[str]) -> pd.DataFrame:
    groups = (
        frame[list(group_columns)].drop_duplicates().to_dict("records")
        if group_columns
        else [{}]
    )
    rows: List[dict] = []
    for group in groups:
        block = frame.copy()
        for column, value in group.items():
            block = block[block[column] == value]
        worker_full = mae(
            block["finalPrimary"], block["workerFullAvailabilityPrediction"]
        )
        worker_current = mae(
            block["finalPrimary"],
            block["workerCurrentAvailabilityProxyPrediction"],
        )
        rate_gate = mae(
            block["finalPrimary"],
            block["v19RateGateFullAvailabilityPrediction"],
        )
        stack = mae(
            block["finalPrimary"], block["v19SelectedAvailabilityPrediction"]
        )
        worker_games = mae(
            block["finalGames"],
            block["workerCurrentAvailabilityProxyFinalGames"],
        )
        stack_games = mae(
            block["finalGames"], block["v19SelectedAvailabilityFinalGames"]
        )
        block_stats = season_block_stats(frame, group)
        rows.append(
            {
                **group,
                "rows": int(len(block)),
                "workerFullAvailabilityMae": worker_full,
                "workerCurrentAvailabilityProxyMae": worker_current,
                "v19RateGateFullAvailabilityMae": rate_gate,
                "v19SelectedAvailabilityMae": stack,
                "v19RateGateImprovementPctVsWorkerFullAvailability": improvement_pct(
                    worker_full, rate_gate
                ),
                "v19StackImprovementPctVsWorkerCurrentAvailabilityProxy": improvement_pct(
                    worker_current, stack
                ),
                "v19StackImprovementPctVsWorkerFullAvailability": improvement_pct(
                    worker_full, stack
                ),
                "workerCurrentAvailabilityProxyGamesMae": worker_games,
                "v19SelectedAvailabilityGamesMae": stack_games,
                "v19GamesImprovementPctVsWorkerCurrentAvailabilityProxy": improvement_pct(
                    worker_games, stack_games
                ),
                **block_stats,
            }
        )
    return pd.DataFrame(rows)


def policy_table(position_checkpoint: pd.DataFrame) -> pd.DataFrame:
    rows: List[dict] = []
    for row in position_checkpoint.to_dict("records"):
        total_gain = safe_float(
            row.get("v19StackImprovementPctVsWorkerCurrentAvailabilityProxy"),
            np.nan,
        )
        rate_gain = safe_float(
            row.get("v19RateGateImprovementPctVsWorkerFullAvailability"), np.nan
        )
        wins = safe_float(row.get("stackBlockWinPctVsWorkerProxy"), np.nan)
        recent = safe_float(
            row.get("stackRecent4ImprovementPctVsWorkerProxy"), np.nan
        )
        candidate = bool(
            math.isfinite(total_gain)
            and total_gain >= MIN_INTEGRATION_IMPROVEMENT_PCT
            and math.isfinite(rate_gain)
            and rate_gain >= 0.0
            and math.isfinite(wins)
            and wins >= MIN_BLOCK_WIN_PCT
            and math.isfinite(recent)
            and recent >= MIN_RECENT4_IMPROVEMENT_PCT
        )
        rows.append(
            {
                "position": row.get("position"),
                "checkpoint": row.get("checkpoint"),
                "v19RateGateImprovementPctVsWorkerFullAvailability": rate_gain,
                "v19StackImprovementPctVsWorkerCurrentAvailabilityProxy": total_gain,
                "stackBlockWinPctVsWorkerProxy": wins,
                "stackRecent4ImprovementPctVsWorkerProxy": recent,
                "integrationRecommendation": (
                    "integration-candidate" if candidate else "research-hold"
                ),
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--features",
        type=Path,
        default=Path("model-lab/output/v19-player-features/player_features.csv"),
    )
    parser.add_argument(
        "--availability-predictions",
        type=Path,
        default=Path(
            "model-lab/output/v19-player-availability/availability_predictions.csv"
        ),
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("model-lab/output/v19-player-worker-replay"),
    )
    parser.add_argument("--test-start", type=int, default=2014)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    features = pd.read_csv(args.features, low_memory=False)
    required = {
        "season",
        "checkpoint",
        "position",
        "playerKey",
        "finalPrimary",
        "finalGames",
        "currentPrimary",
        "games",
        "current_primary_pg",
        "prior_primary_pg",
        "prior_data_available",
        "availability_rate",
    }
    missing = sorted(required - set(features.columns))
    if missing:
        raise RuntimeError(f"Missing required feature columns: {missing}")
    features["season"] = pd.to_numeric(
        features["season"], errors="coerce"
    ).astype("Int64")
    features["checkpoint"] = pd.to_numeric(
        features["checkpoint"], errors="coerce"
    ).astype("Int64")
    features = features[features["season"] >= args.test_start].copy()

    availability_predictions = pd.read_csv(
        args.availability_predictions, low_memory=False
    )
    worker = worker_bridge_frame(features)
    replay = attach_v19_predictions(worker, availability_predictions)

    overall = aggregate(replay, [])
    position = aggregate(replay, ["position"])
    position_checkpoint = aggregate(replay, ["position", "checkpoint"])
    policy = policy_table(position_checkpoint)

    replay.to_csv(args.out / "worker_replay_predictions.csv", index=False)
    overall.to_csv(args.out / "worker_replay_overall_summary.csv", index=False)
    position.to_csv(args.out / "worker_replay_position_summary.csv", index=False)
    position_checkpoint.to_csv(
        args.out / "worker_replay_position_checkpoint_summary.csv", index=False
    )
    policy.to_csv(args.out / "worker_replay_policy.csv", index=False)

    fidelity = {
        "replayFidelity": "reproducible-core",
        "exactlyReplayed": [
            "Season Worker v1.2.0 currentSeasonWeight(gamesPlayed) curve",
            "realized current totals plus projected remaining production accounting",
            "QB/RB/WR/TE primary-stat mapping used by the research dataset",
        ],
        "neutralizedOrProxied": {
            "priorRate": "prior-year player primary production per game; current-rate fallback when prior data is unavailable",
            "availability": "current availability rate is a proxy for the Worker's live status-driven expectedMissedGames logic",
            "liveRoleAssignment": "not reconstructed because exact historical Ourlads/ESPN role snapshots and role-conflict state were not persisted",
            "heatAndForm": "neutralized because historical live Heat Score/profile snapshots were not persisted",
            "teamRating": "neutralized because exact historical point-in-time Season Worker team rating snapshots were not persisted",
            "tradeAndScheme": "neutralized because exact live transaction classification and scheme snapshots were not persisted",
        },
        "interpretation": "Use this replay to test whether the validated v1.9 rate+availability stack improves on the reproducible Worker weighting bridge. Do not treat it as a byte-for-byte replay of historical Worker snapshots.",
    }
    (args.out / "worker_replay_fidelity.json").write_text(
        json.dumps(fidelity, indent=2), encoding="utf-8"
    )

    report = {
        "lab": "GRIDIRON PULSE v1.9h Season Worker reproducible-core integration replay",
        "researchOnly": True,
        "productionWorkerChanged": False,
        "testStart": args.test_start,
        "testEnd": int(replay["season"].max()),
        "integrationGate": {
            "minImprovementPctVsWorkerCurrentAvailabilityProxy": MIN_INTEGRATION_IMPROVEMENT_PCT,
            "minRateImprovementPctVsWorkerFullAvailability": 0.0,
            "minSeasonBlockWinPct": MIN_BLOCK_WIN_PCT,
            "minRecent4ImprovementPct": MIN_RECENT4_IMPROVEMENT_PCT,
        },
        "fidelity": fidelity,
        "overall": overall.to_dict("records"),
        "positionCheckpoint": position_checkpoint.to_dict("records"),
        "policy": policy.to_dict("records"),
    }
    (args.out / "worker_replay_summary.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    main()
