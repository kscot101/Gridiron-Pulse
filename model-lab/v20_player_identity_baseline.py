#!/usr/bin/env python3
"""GRIDIRON PULSE v2.0 Player Identity Baseline research runner.

Research only. It compares player-specific identity baselines with the current
generic role model and never changes the live Worker or site.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Dict, List, Mapping, Tuple

import numpy as np
import pandas as pd

from v20_player_identity_core import *
from v20_player_identity_model import *


def build_backtest(
    seasons: pd.DataFrame,
    test_start: int,
    end_season: int,
    contract_by_id: Mapping[Tuple[int, str], ContractRecord],
    contract_by_name: Mapping[Tuple[int, str], ContractRecord],
) -> pd.DataFrame:
    outputs: List[dict] = []
    by_player = {player_id: frame.copy() for player_id, frame in seasons.groupby("player_id", sort=False)}
    for target_season in range(test_start, end_season + 1):
        actuals = seasons[(seasons["season"] == target_season) & (seasons["games"] >= 4)]
        past = seasons[seasons["season"] < target_season]
        print(f"[v2.0 identity] Backtest season {target_season}: {len(actuals):,} eligible actual players")
        for actual in actuals.to_dict("records"):
            history = by_player.get(str(actual["player_id"]), pd.DataFrame())
            history = history[(history["season"] < target_season) & (history["season"] >= target_season - 3)]
            if history.empty:
                continue
            contract = contract_for_player(
                target_season,
                str(actual["player_id"]),
                str(actual["player_name"]),
                contract_by_id,
                contract_by_name,
            )
            prediction = build_prediction(history, target_season, past, contract)
            prediction.update(
                {
                    "actual_games": int(actual["games"]),
                    "actual_rate": float(actual["primary_pg"]),
                    "actual_total": float(actual["primary"]),
                    "actual_team": str(actual["team"]),
                    "actual_role_bucket": str(actual["role_bucket"]),
                    "actual_role_rank": int(actual["team_position_rank"]),
                }
            )
            for model in MODELS:
                prediction[f"{model}_rate_error"] = prediction[f"{model}_rate"] - prediction["actual_rate"]
                prediction[f"{model}_total_error"] = prediction[f"{model}_total"] - prediction["actual_total"]
            outputs.append(prediction)
    return pd.DataFrame(outputs)


def metric_rows(frame: pd.DataFrame, group_values: Mapping[str, object]) -> List[dict]:
    rows: List[dict] = []
    if frame.empty:
        return rows
    generic_rate_mae = float(np.mean(np.abs(frame["generic_role_rate_error"])))
    generic_total_mae = float(np.mean(np.abs(frame["generic_role_total_error"])))
    for model in MODELS:
        rate_error = pd.to_numeric(frame[f"{model}_rate_error"], errors="coerce").dropna()
        total_error = pd.to_numeric(frame[f"{model}_total_error"], errors="coerce").dropna()
        if rate_error.empty or total_error.empty:
            continue
        rate_mae = float(np.mean(np.abs(rate_error)))
        total_mae = float(np.mean(np.abs(total_error)))
        rows.append(
            {
                **group_values,
                "model": model,
                "model_label": MODEL_LABELS[model],
                "rows": int(len(frame)),
                "rate_mae": rate_mae,
                "rate_rmse": float(math.sqrt(np.mean(np.square(rate_error)))),
                "rate_bias": float(np.mean(rate_error)),
                "rate_median_ae": float(np.median(np.abs(rate_error))),
                "rate_mae_improvement_vs_generic_pct": 0.0 if generic_rate_mae <= 0 else (generic_rate_mae - rate_mae) / generic_rate_mae * 100.0,
                "total_mae": total_mae,
                "total_rmse": float(math.sqrt(np.mean(np.square(total_error)))),
                "total_bias": float(np.mean(total_error)),
                "total_median_ae": float(np.median(np.abs(total_error))),
                "total_mae_improvement_vs_generic_pct": 0.0 if generic_total_mae <= 0 else (generic_total_mae - total_mae) / generic_total_mae * 100.0,
            }
        )
    return rows


def summarize(backtest: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    overall = pd.DataFrame(metric_rows(backtest, {"group": "ALL"}))
    position_rows: List[dict] = []
    for position, group in backtest.groupby("position"):
        position_rows.extend(metric_rows(group, {"position": position}))
    state_rows: List[dict] = []
    for state, group in backtest.groupby("career_state"):
        state_rows.extend(metric_rows(group, {"career_state": state}))
    star = backtest[backtest["star_flag"] == True]  # noqa: E712
    star_rows = metric_rows(star, {"subset": "ESTABLISHED_STAR_EVIDENCE"})
    shortened = backtest[backtest["shortened_prior"] == True]  # noqa: E712
    star_rows.extend(metric_rows(shortened, {"subset": "SHORTENED_PRIOR_SEASON"}))
    star_short = backtest[(backtest["star_flag"] == True) & (backtest["shortened_prior"] == True)]  # noqa: E712
    star_rows.extend(metric_rows(star_short, {"subset": "STAR_AND_SHORTENED"}))
    return {
        "overall": overall,
        "position": pd.DataFrame(position_rows),
        "state": pd.DataFrame(state_rows),
        "subsets": pd.DataFrame(star_rows),
    }


def current_forecast(
    seasons: pd.DataFrame,
    forecast_season: int,
    contract_by_id: Mapping[Tuple[int, str], ContractRecord],
    contract_by_name: Mapping[Tuple[int, str], ContractRecord],
    current_roster: pd.DataFrame,
) -> pd.DataFrame:
    past = seasons[seasons["season"] < forecast_season]
    latest_season = int(past["season"].max())
    candidates = past[past["season"] == latest_season].copy()
    roster_ids: set[str] = set()
    roster_map: Dict[str, dict] = {}
    if not current_roster.empty:
        meta = roster_metadata(current_roster, forecast_season)
        meta = meta[meta["roster_position"].isin(POSITIONS)]
        roster_ids = set(meta["player_id"].astype(str))
        roster_map = {str(row["player_id"]): row for row in meta.to_dict("records")}
        candidates = candidates[candidates["player_id"].astype(str).isin(roster_ids)]

    by_player = {player_id: frame.copy() for player_id, frame in past.groupby("player_id", sort=False)}
    outputs: List[dict] = []
    for latest in candidates.to_dict("records"):
        player_id = str(latest["player_id"])
        history = by_player[player_id]
        history = history[history["season"] >= forecast_season - 3]
        contract = contract_for_player(
            forecast_season,
            player_id,
            str(latest["player_name"]),
            contract_by_id,
            contract_by_name,
        )
        row = build_prediction(history, forecast_season, past, contract)
        if player_id in roster_map:
            current = roster_map[player_id]
            row["forecast_team"] = current.get("roster_team") or row["prior_team"]
            row["forecast_position"] = current.get("roster_position") or row["position"]
            row["current_roster_match"] = True
        else:
            row["forecast_team"] = row["prior_team"]
            row["forecast_position"] = row["position"]
            row["current_roster_match"] = False
        outputs.append(row)
    result = pd.DataFrame(outputs)
    if not result.empty:
        result = result.sort_values(["position", "identity_guardrail_total"], ascending=[True, False])
    return result


def build_sanity_checks(forecast: pd.DataFrame) -> pd.DataFrame:
    if forecast.empty:
        return forecast
    names = {"matthewstafford", "brockbowers"}
    direct = forecast[forecast["player_name"].map(normalize_name).isin(names)].copy()
    largest = forecast.assign(
        _gap=forecast["identity_guardrail_total"] - forecast["generic_role_total"]
    ).sort_values("_gap", ascending=False).head(20)
    combined = pd.concat([direct, largest], ignore_index=True).drop_duplicates("player_id")
    columns = [
        "player_id",
        "player_name",
        "position",
        "forecast_team",
        "career_state",
        "career_flags",
        "role_stability",
        "star_flag",
        "latest_games",
        "latest_rate",
        "older_rate",
        "predicted_games",
        "generic_role_rate",
        "identity_guardrail_rate",
        "generic_role_total",
        "identity_guardrail_total",
        "generic_role_eq17",
        "identity_guardrail_eq17",
        "contract_status",
    ]
    return combined[[column for column in columns if column in combined.columns]]


def promotion_gate(summaries: Mapping[str, pd.DataFrame]) -> dict:
    overall = summaries["overall"]
    position = summaries["position"]
    subsets = summaries["subsets"]
    model = "identity_guardrail"
    overall_row = overall[overall["model"] == model]
    star_row = subsets[(subsets["model"] == model) & (subsets["subset"] == "ESTABLISHED_STAR_EVIDENCE")]
    position_rows = position[position["model"] == model]
    overall_improvement = safe_float(overall_row["rate_mae_improvement_vs_generic_pct"].iloc[0], -999) if not overall_row.empty else -999
    star_improvement = safe_float(star_row["rate_mae_improvement_vs_generic_pct"].iloc[0], -999) if not star_row.empty else -999
    worst_position = safe_float(position_rows["rate_mae_improvement_vs_generic_pct"].min(), -999) if not position_rows.empty else -999
    recommended = bool(overall_improvement > 0 and star_improvement >= 5 and worst_position >= -2)
    return {
        "productionChanged": False,
        "candidateModel": model,
        "recommendedForProductionIntegration": recommended,
        "requirements": {
            "overallRateMaeImprovementPctGreaterThan": 0,
            "starRateMaeImprovementPctAtLeast": 5,
            "noPositionRateMaeRegressionWorseThanPct": -2,
        },
        "observed": {
            "overallRateMaeImprovementPct": overall_improvement,
            "starRateMaeImprovementPct": star_improvement,
            "worstPositionRateMaeImprovementPct": worst_position,
        },
        "note": "A green research gate still requires manual player sanity review before any Season Worker change.",
    }


def write_frame(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, float_format="%.6f")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=int, default=2012)
    parser.add_argument("--end", type=int, default=2025)
    parser.add_argument("--test-start", type=int, default=2015)
    parser.add_argument("--forecast-season", type=int, default=2026)
    parser.add_argument("--out", type=Path, default=Path("model-lab/output/v20-player-identity"))
    parser.add_argument("--cache", type=Path, default=Path("model-lab/output/v20-player-identity-cache"))
    parser.add_argument("--contract-context", type=Path, default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.start > args.end:
        raise SystemExit("--start must be <= --end")
    if args.test_start < args.start + 1:
        raise SystemExit("--test-start must leave at least one prior season")

    args.out.mkdir(parents=True, exist_ok=True)
    contract_by_id, contract_by_name, contract_coverage = load_contract_context(args.contract_context)

    season_frames: List[pd.DataFrame] = []
    source_rows: List[dict] = []
    for season in range(args.start, args.end + 1):
        print(f"[v2.0 identity] Loading season {season}")
        stats = load_csv_url(stats_url(season), args.cache / f"stats_player_week_{season}.csv")
        roster = load_csv_url(roster_url(season), args.cache / f"roster_{season}.csv", optional=True)
        aggregated = aggregate_player_season(stats, roster, season)
        if aggregated.empty:
            raise RuntimeError(f"No player-season rows were built for {season}")
        season_frames.append(aggregated)
        source_rows.append(
            {
                "season": season,
                "stats_rows": len(stats),
                "roster_rows": len(roster),
                "player_season_rows": len(aggregated),
                "qb": int((aggregated["position"] == "QB").sum()),
                "rb": int((aggregated["position"] == "RB").sum()),
                "wr": int((aggregated["position"] == "WR").sum()),
                "te": int((aggregated["position"] == "TE").sum()),
            }
        )

    seasons = pd.concat(season_frames, ignore_index=True)
    write_frame(seasons, args.out / "player_season_identity_source.csv")
    write_frame(pd.DataFrame(source_rows), args.out / "source_coverage.csv")

    backtest = build_backtest(
        seasons,
        args.test_start,
        args.end,
        contract_by_id,
        contract_by_name,
    )
    if backtest.empty:
        raise RuntimeError("Backtest produced no predictions")
    write_frame(backtest, args.out / "backtest_predictions.csv")

    summaries = summarize(backtest)
    write_frame(summaries["overall"], args.out / "overall_model_summary.csv")
    write_frame(summaries["position"], args.out / "position_model_summary.csv")
    write_frame(summaries["state"], args.out / "career_state_model_summary.csv")
    write_frame(summaries["subsets"], args.out / "star_and_shortened_summary.csv")

    current_roster = load_csv_url(
        roster_url(args.forecast_season),
        args.cache / f"roster_{args.forecast_season}.csv",
        optional=True,
    )
    forecast = current_forecast(
        seasons,
        args.forecast_season,
        contract_by_id,
        contract_by_name,
        current_roster,
    )
    write_frame(forecast, args.out / f"forecast_{args.forecast_season}_player_identity.csv")
    sanity = build_sanity_checks(forecast)
    write_frame(sanity, args.out / "sanity_checks.csv")

    gate = promotion_gate(summaries)
    summary = {
        "version": "v2.0-player-identity-baseline-1",
        "researchOnly": True,
        "productionChanged": False,
        "seasonRange": [args.start, args.end],
        "testStartSeason": args.test_start,
        "forecastSeason": args.forecast_season,
        "playerSeasonRows": int(len(seasons)),
        "backtestRows": int(len(backtest)),
        "forecastRows": int(len(forecast)),
        "contractContext": contract_coverage,
        "careerStates": sorted(backtest["career_state"].dropna().astype(str).unique().tolist()),
        "promotionGate": gate,
        "method": {
            "rate": "Each player's own prior one-to-three season per-game production and opportunity/efficiency identity, dynamically weighted by career state and shrunk toward a no-lookahead role/age cohort.",
            "availability": "Projected games are estimated separately from production rate so a shortened season is not counted twice.",
            "starGuardrail": "Strong multi-season, high-percentile starter evidence limits over-regression toward a generic role average; it does not create production above the player's own evidence.",
            "contractContext": "Contract year is a context flag. No blanket boost is allowed. The optional research adjustment only restores a small part of an older baseline when a verified contract-year player had a down prior season and retained a stable role.",
        },
    }
    (args.out / "run_summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False), encoding="utf-8")
    (args.out / "baseline_policy.json").write_text(json.dumps(gate, indent=2, allow_nan=False), encoding="utf-8")

    print("\n[v2.0 identity] Overall model summary")
    print(summaries["overall"].to_string(index=False))
    print("\n[v2.0 identity] Stafford/Bowers and largest generic gaps")
    print(sanity.to_string(index=False) if not sanity.empty else "No sanity-check rows found")
    print("\n[v2.0 identity] Promotion gate")
    print(json.dumps(gate, indent=2))


if __name__ == "__main__":
    main()
