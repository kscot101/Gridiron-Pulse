#!/usr/bin/env python3
"""GRIDIRON PULSE v1.9i nested champion/challenger shadow router.

Routes between the reproducible Season Worker bridge (champion) and the
validated v1.9f rate gate + v1.9g availability stack (challenger). For every
held-out season, the routing decision for each QB/RB/WR/TE checkpoint uses only
prior seasons from the v1.9h replay. This prevents the current held-out season
from deciding whether it receives the new model.

Research/shadow only. This script does not alter or deploy the Season Worker.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Dict, List, Mapping, Sequence

import numpy as np
import pandas as pd

from v19_player_comparable_backtest import safe_float
from v19_player_isolated_environment_backtest import improvement_pct

KEY_COLUMNS = ["season", "checkpoint", "position", "playerKey"]
MIN_VALIDATION_BLOCKS = 3
MIN_IMPROVEMENT_PCT = 1.0
MIN_BLOCK_WIN_PCT = 55.0
MIN_RECENT4_IMPROVEMENT_PCT = 0.0
TIE_TOLERANCE_PCT = 0.10


def mae(actual: pd.Series, predicted: pd.Series) -> float:
    a = pd.to_numeric(actual, errors="coerce").to_numpy(dtype=float)
    p = pd.to_numeric(predicted, errors="coerce").to_numpy(dtype=float)
    valid = np.isfinite(a) & np.isfinite(p)
    if not valid.any():
        return np.nan
    return float(np.mean(np.abs(a[valid] - p[valid])))


def season_score_table(block: pd.DataFrame, before_season: int) -> pd.DataFrame:
    rows: List[dict] = []
    prior = block[block["season"] < before_season].copy()
    for season, season_block in prior.groupby("season", dropna=False):
        worker_mae = mae(
            season_block["finalPrimary"],
            season_block["workerCurrentAvailabilityProxyPrediction"],
        )
        challenger_mae = mae(
            season_block["finalPrimary"],
            season_block["v19SelectedAvailabilityPrediction"],
        )
        if not (math.isfinite(worker_mae) and math.isfinite(challenger_mae)):
            continue
        rows.append(
            {
                "season": int(season),
                "workerMae": worker_mae,
                "challengerMae": challenger_mae,
                "challengerImprovementPct": improvement_pct(worker_mae, challenger_mae),
            }
        )
    return pd.DataFrame(rows)


def routing_decision(block: pd.DataFrame, before_season: int) -> dict:
    table = season_score_table(block, before_season)
    if len(table) < MIN_VALIDATION_BLOCKS:
        return {
            "route": "worker",
            "validationBlocks": int(len(table)),
            "validationWorkerMae": np.nan,
            "validationChallengerMae": np.nan,
            "validationImprovementPct": np.nan,
            "validationWinPct": np.nan,
            "validationRecent4ImprovementPct": np.nan,
            "reason": "insufficient-prior-blocks",
        }

    worker_mae = float(table["workerMae"].mean())
    challenger_mae = float(table["challengerMae"].mean())
    improvement = improvement_pct(worker_mae, challenger_mae)
    win_pct = float((table["challengerMae"] <= table["workerMae"]).mean() * 100.0)
    recent = table.sort_values("season").tail(4)
    recent_worker = float(recent["workerMae"].mean())
    recent_challenger = float(recent["challengerMae"].mean())
    recent_improvement = improvement_pct(recent_worker, recent_challenger)

    clears = bool(
        math.isfinite(improvement)
        and improvement >= MIN_IMPROVEMENT_PCT
        and math.isfinite(win_pct)
        and win_pct >= MIN_BLOCK_WIN_PCT
        and math.isfinite(recent_improvement)
        and recent_improvement >= MIN_RECENT4_IMPROVEMENT_PCT
    )

    if clears and abs(challenger_mae - worker_mae) <= worker_mae * TIE_TOLERANCE_PCT / 100.0:
        clears = False
        reason = "near-tie-keep-champion"
    else:
        reason = "prior-validation-pass" if clears else "prior-validation-hold"

    return {
        "route": "v19" if clears else "worker",
        "validationBlocks": int(len(table)),
        "validationWorkerMae": worker_mae,
        "validationChallengerMae": challenger_mae,
        "validationImprovementPct": improvement,
        "validationWinPct": win_pct,
        "validationRecent4ImprovementPct": recent_improvement,
        "reason": reason,
    }


def build_routed_predictions(replay: pd.DataFrame, test_start: int):
    predictions: List[pd.DataFrame] = []
    selections: List[dict] = []

    for position in sorted(replay["position"].dropna().astype(str).unique()):
        position_data = replay[replay["position"] == position]
        for checkpoint in sorted(int(value) for value in position_data["checkpoint"].dropna().unique()):
            block = position_data[position_data["checkpoint"] == checkpoint].copy()
            seasons = sorted(int(value) for value in block["season"].dropna().unique() if int(value) >= test_start)
            for season in seasons:
                test = block[block["season"] == season].copy()
                if test.empty:
                    continue
                choice = routing_decision(block, season)
                use_v19 = choice["route"] == "v19"
                test["shadowRoute"] = choice["route"]
                test["shadowPrediction"] = np.where(
                    use_v19,
                    pd.to_numeric(test["v19SelectedAvailabilityPrediction"], errors="coerce"),
                    pd.to_numeric(test["workerCurrentAvailabilityProxyPrediction"], errors="coerce"),
                )
                test["shadowPredictedFinalGames"] = np.where(
                    use_v19,
                    pd.to_numeric(test["v19SelectedAvailabilityFinalGames"], errors="coerce"),
                    pd.to_numeric(test["workerCurrentAvailabilityProxyFinalGames"], errors="coerce"),
                )
                predictions.append(test)
                selections.append(
                    {
                        "season": season,
                        "position": position,
                        "checkpoint": checkpoint,
                        "selectedRoute": choice["route"],
                        "validationBlocks": choice["validationBlocks"],
                        "validationWorkerMae": choice["validationWorkerMae"],
                        "validationChallengerMae": choice["validationChallengerMae"],
                        "validationImprovementPct": choice["validationImprovementPct"],
                        "validationWinPct": choice["validationWinPct"],
                        "validationRecent4ImprovementPct": choice["validationRecent4ImprovementPct"],
                        "reason": choice["reason"],
                    }
                )

    if not predictions:
        return pd.DataFrame(), pd.DataFrame()
    return pd.concat(predictions, ignore_index=True), pd.DataFrame(selections)


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
        challenger_mae = mae(
            block["finalPrimary"],
            block["v19SelectedAvailabilityPrediction"],
        )
        shadow_mae = mae(block["finalPrimary"], block["shadowPrediction"])
        if all(math.isfinite(value) for value in [worker_mae, challenger_mae, shadow_mae]):
            rows.append(
                {
                    "season": int(season),
                    "workerMae": worker_mae,
                    "challengerMae": challenger_mae,
                    "shadowMae": shadow_mae,
                }
            )
    if not rows:
        return {
            "seasonBlocks": 0,
            "shadowBlockWinPctVsWorker": np.nan,
            "shadowRecent4ImprovementPctVsWorker": np.nan,
        }
    season_df = pd.DataFrame(rows)
    win_pct = float((season_df["shadowMae"] <= season_df["workerMae"]).mean() * 100.0)
    recent = season_df.sort_values("season").tail(4)
    recent_improvement = improvement_pct(
        float(recent["workerMae"].mean()),
        float(recent["shadowMae"].mean()),
    )
    return {
        "seasonBlocks": int(len(season_df)),
        "shadowBlockWinPctVsWorker": win_pct,
        "shadowRecent4ImprovementPctVsWorker": recent_improvement,
    }


def aggregate(frame: pd.DataFrame, group_columns: Sequence[str]) -> pd.DataFrame:
    groups = frame[list(group_columns)].drop_duplicates().to_dict("records") if group_columns else [{}]
    rows: List[dict] = []
    for group in groups:
        block = frame.copy()
        for column, value in group.items():
            block = block[block[column] == value]
        worker_mae = mae(
            block["finalPrimary"],
            block["workerCurrentAvailabilityProxyPrediction"],
        )
        challenger_mae = mae(
            block["finalPrimary"],
            block["v19SelectedAvailabilityPrediction"],
        )
        shadow_mae = mae(block["finalPrimary"], block["shadowPrediction"])
        worker_games = mae(
            block["finalGames"],
            block["workerCurrentAvailabilityProxyFinalGames"],
        )
        challenger_games = mae(
            block["finalGames"],
            block["v19SelectedAvailabilityFinalGames"],
        )
        shadow_games = mae(block["finalGames"], block["shadowPredictedFinalGames"])
        block_stats = season_block_stats(frame, group)
        rows.append(
            {
                **group,
                "rows": int(len(block)),
                "workerMae": worker_mae,
                "alwaysV19Mae": challenger_mae,
                "shadowRouterMae": shadow_mae,
                "shadowImprovementPctVsWorker": improvement_pct(worker_mae, shadow_mae),
                "shadowImprovementPctVsAlwaysV19": improvement_pct(challenger_mae, shadow_mae),
                "workerGamesMae": worker_games,
                "alwaysV19GamesMae": challenger_games,
                "shadowRouterGamesMae": shadow_games,
                "shadowGamesImprovementPctVsWorker": improvement_pct(worker_games, shadow_games),
                **block_stats,
            }
        )
    return pd.DataFrame(rows)


def selection_frequency(selections: pd.DataFrame) -> pd.DataFrame:
    rows: List[dict] = []
    if selections.empty:
        return pd.DataFrame()
    for (position, checkpoint), block in selections.groupby(["position", "checkpoint"]):
        counts = block["selectedRoute"].value_counts().to_dict()
        total = int(len(block))
        rows.append(
            {
                "position": position,
                "checkpoint": int(checkpoint),
                "outerSeasons": total,
                "workerSelectedSeasons": int(counts.get("worker", 0)),
                "v19SelectedSeasons": int(counts.get("v19", 0)),
                "v19SelectionPct": 100.0 * counts.get("v19", 0) / total if total else np.nan,
            }
        )
    return pd.DataFrame(rows)


def policy_table(position_checkpoint: pd.DataFrame, frequency: pd.DataFrame) -> pd.DataFrame:
    merged = position_checkpoint.merge(frequency, on=["position", "checkpoint"], how="left")
    rows: List[dict] = []
    for row in merged.to_dict("records"):
        gain = safe_float(row.get("shadowImprovementPctVsWorker"), np.nan)
        wins = safe_float(row.get("shadowBlockWinPctVsWorker"), np.nan)
        recent = safe_float(row.get("shadowRecent4ImprovementPctVsWorker"), np.nan)
        candidate = bool(
            math.isfinite(gain)
            and gain >= 1.0
            and math.isfinite(wins)
            and wins >= 55.0
            and math.isfinite(recent)
            and recent >= 0.0
        )
        rows.append(
            {
                "position": row.get("position"),
                "checkpoint": row.get("checkpoint"),
                "shadowImprovementPctVsWorker": gain,
                "shadowBlockWinPctVsWorker": wins,
                "shadowRecent4ImprovementPctVsWorker": recent,
                "v19SelectionPct": safe_float(row.get("v19SelectionPct"), np.nan),
                "shadowRecommendation": "shadow-candidate" if candidate else "keep-champion",
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--replay",
        type=Path,
        default=Path("model-lab/output/v19-player-worker-replay/worker_replay_predictions.csv"),
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("model-lab/output/v19-player-shadow-router"),
    )
    parser.add_argument("--test-start", type=int, default=2014)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    replay = pd.read_csv(args.replay, low_memory=False)
    required = {
        "season",
        "checkpoint",
        "position",
        "playerKey",
        "finalPrimary",
        "finalGames",
        "workerCurrentAvailabilityProxyPrediction",
        "workerCurrentAvailabilityProxyFinalGames",
        "v19SelectedAvailabilityPrediction",
        "v19SelectedAvailabilityFinalGames",
    }
    missing = sorted(required - set(replay.columns))
    if missing:
        raise RuntimeError(f"Missing required replay columns: {missing}")

    replay["season"] = pd.to_numeric(replay["season"], errors="coerce").astype("Int64")
    replay["checkpoint"] = pd.to_numeric(replay["checkpoint"], errors="coerce").astype("Int64")
    replay = replay[replay["season"] >= args.test_start].copy()

    routed, selections = build_routed_predictions(replay, args.test_start)
    if routed.empty:
        raise RuntimeError("No v1.9i routed predictions were produced")

    overall = aggregate(routed, [])
    position = aggregate(routed, ["position"])
    position_checkpoint = aggregate(routed, ["position", "checkpoint"])
    frequency = selection_frequency(selections)
    policy = policy_table(position_checkpoint, frequency)

    routed.to_csv(args.out / "shadow_router_predictions.csv", index=False)
    selections.to_csv(args.out / "shadow_router_selection_history.csv", index=False)
    overall.to_csv(args.out / "shadow_router_overall_summary.csv", index=False)
    position.to_csv(args.out / "shadow_router_position_summary.csv", index=False)
    position_checkpoint.to_csv(args.out / "shadow_router_position_checkpoint_summary.csv", index=False)
    frequency.to_csv(args.out / "shadow_router_selection_frequency.csv", index=False)
    policy.to_csv(args.out / "shadow_router_policy.csv", index=False)

    report = {
        "lab": "GRIDIRON PULSE v1.9i nested champion/challenger shadow router",
        "researchOnly": True,
        "productionWorkerChanged": False,
        "champion": "v1.9h reproducible Season Worker current-availability bridge",
        "challenger": "v1.9f history-gated rate + v1.9g availability stack",
        "selection": "For every outer season and position/checkpoint, route to the challenger only when prior seasons clear the improvement, block-win, and recent-stability gates; otherwise keep the Worker champion.",
        "routingGate": {
            "minValidationBlocks": MIN_VALIDATION_BLOCKS,
            "minImprovementPct": MIN_IMPROVEMENT_PCT,
            "minBlockWinPct": MIN_BLOCK_WIN_PCT,
            "minRecent4ImprovementPct": MIN_RECENT4_IMPROVEMENT_PCT,
            "nearTieTolerancePct": TIE_TOLERANCE_PCT,
        },
        "overall": overall.to_dict("records"),
        "positionCheckpoint": position_checkpoint.to_dict("records"),
        "selectionFrequency": frequency.to_dict("records"),
        "policy": policy.to_dict("records"),
    }
    (args.out / "shadow_router_summary.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    main()
