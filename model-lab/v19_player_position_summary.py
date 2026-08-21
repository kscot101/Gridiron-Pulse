#!/usr/bin/env python3
"""Position-specific promotion summaries for GRIDIRON PULSE v1.9 research."""
from __future__ import annotations

import argparse
import math
from pathlib import Path

import numpy as np
import pandas as pd


def safe_float(value, default=np.nan):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def metrics(frame: pd.DataFrame) -> dict:
    target = pd.to_numeric(frame["targetPrimaryEq17"], errors="coerce").to_numpy(dtype=float)
    pred = pd.to_numeric(frame["prediction"], errors="coerce").to_numpy(dtype=float)
    error = pred - target
    return {
        "rows": int(len(frame)),
        "mae": float(np.mean(np.abs(error))),
        "rmse": float(np.sqrt(np.mean(np.square(error)))),
        "bias": float(np.mean(error)),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--season-metrics", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    predictions = pd.read_csv(args.predictions, low_memory=False)
    season = pd.read_csv(args.season_metrics, low_memory=False)
    stage_order = ["00_pace_baseline"] + [stage for stage in predictions["stage"].dropna().unique().tolist() if stage != "00_pace_baseline"]
    stage_order = sorted(stage_order, key=lambda value: (0 if value == "00_pace_baseline" else 1, value))
    position_rows = []
    checkpoint_rows = []
    promotion_rows = []
    max_season = int(pd.to_numeric(predictions["season"], errors="coerce").max())

    for position in sorted(predictions["position"].dropna().unique()):
        pos_pred = predictions[predictions["position"] == position]
        for stage in stage_order:
            stage_pred = pos_pred[pos_pred["stage"] == stage]
            if stage_pred.empty:
                continue
            metric = metrics(stage_pred)
            pace = metrics(pos_pred[pos_pred["stage"] == "00_pace_baseline"])
            prev_stage = stage_order[max(0, stage_order.index(stage) - 1)]
            prev_pred = pos_pred[pos_pred["stage"] == prev_stage]
            prev = metrics(prev_pred) if not prev_pred.empty else {"mae": np.nan}
            improvement_pace = 100.0 * (pace["mae"] - metric["mae"]) / pace["mae"] if stage != "00_pace_baseline" and pace["mae"] > 0 else 0.0
            improvement_prev = 100.0 * (prev["mae"] - metric["mae"]) / prev["mae"] if stage != "00_pace_baseline" and safe_float(prev["mae"], 0.0) > 0 else 0.0
            win_pct = np.nan
            recent_delta = np.nan
            if stage != "00_pace_baseline":
                current = season[(season["position"] == position) & (season["stage"] == stage)][["season", "checkpoint", "mae"]].rename(columns={"mae": "current_mae"})
                previous = season[(season["position"] == position) & (season["stage"] == prev_stage)][["season", "checkpoint", "mae"]].rename(columns={"mae": "previous_mae"})
                joined = current.merge(previous, on=["season", "checkpoint"], how="inner")
                if not joined.empty:
                    win_pct = float((joined["current_mae"] <= joined["previous_mae"]).mean() * 100.0)
                    recent = joined[joined["season"] >= max_season - 3]
                    if not recent.empty and recent["previous_mae"].mean() > 0:
                        recent_delta = 100.0 * (recent["previous_mae"].mean() - recent["current_mae"].mean()) / recent["previous_mae"].mean()
            candidate = bool(stage != "00_pace_baseline" and improvement_prev > 0 and (not math.isfinite(safe_float(win_pct)) or win_pct >= 55.0) and (not math.isfinite(safe_float(recent_delta)) or recent_delta >= -0.5))
            position_rows.append({
                "position": position,
                "stage": stage,
                **metric,
                "maeImprovementPctVsPace": improvement_pace,
                "maeImprovementPctVsPrevious": improvement_prev,
                "seasonCheckpointWinPctVsPrevious": win_pct,
                "recent4SeasonImprovementPctVsPrevious": recent_delta,
                "researchCandidate": candidate,
            })
            if stage != "00_pace_baseline":
                promotion_rows.append({
                    "position": position,
                    "stage": stage,
                    "researchCandidate": candidate,
                    "maeImprovementPctVsPrevious": improvement_prev,
                    "seasonCheckpointWinPctVsPrevious": win_pct,
                    "recent4SeasonImprovementPctVsPrevious": recent_delta,
                    "reason": "Position-specific held-out test clears research gate." if candidate else "Position-specific signal remains research-only.",
                })

        for checkpoint in sorted(pd.to_numeric(pos_pred["checkpoint"], errors="coerce").dropna().unique()):
            cp_pred = pos_pred[pd.to_numeric(pos_pred["checkpoint"], errors="coerce") == checkpoint]
            for stage in stage_order:
                stage_pred = cp_pred[cp_pred["stage"] == stage]
                if stage_pred.empty:
                    continue
                metric = metrics(stage_pred)
                pace = metrics(cp_pred[cp_pred["stage"] == "00_pace_baseline"])
                prev_stage = stage_order[max(0, stage_order.index(stage) - 1)]
                prev_pred = cp_pred[cp_pred["stage"] == prev_stage]
                prev = metrics(prev_pred) if not prev_pred.empty else {"mae": np.nan}
                checkpoint_rows.append({
                    "position": position,
                    "checkpoint": int(checkpoint),
                    "stage": stage,
                    **metric,
                    "maeImprovementPctVsPace": 100.0 * (pace["mae"] - metric["mae"]) / pace["mae"] if stage != "00_pace_baseline" and pace["mae"] > 0 else 0.0,
                    "maeImprovementPctVsPrevious": 100.0 * (prev["mae"] - metric["mae"]) / prev["mae"] if stage != "00_pace_baseline" and safe_float(prev["mae"], 0.0) > 0 else 0.0,
                })

    pd.DataFrame(position_rows).to_csv(args.out / "position_stage_summary.csv", index=False)
    pd.DataFrame(checkpoint_rows).to_csv(args.out / "position_checkpoint_summary.csv", index=False)
    pd.DataFrame(promotion_rows).to_csv(args.out / "position_promotion_candidates.csv", index=False)
    print(pd.DataFrame(position_rows).to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
