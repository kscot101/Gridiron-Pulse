#!/usr/bin/env python3
"""Career-state and player-specific baseline calculations for v2.0."""
from __future__ import annotations

import math
from typing import List, Mapping, Optional, Tuple

import numpy as np
import pandas as pd

from v20_player_identity_core import *


def history_weights(state: str, count: int) -> List[float]:
    base = {
        "ASCENDING": [0.65, 0.25, 0.10],
        "DEVELOPING": [0.65, 0.25, 0.10],
        "ESTABLISHED": [0.55, 0.30, 0.15],
        "PEAK": [0.50, 0.30, 0.20],
        "DECLINING": [0.65, 0.25, 0.10],
        "ROLE_CHANGED": [0.65, 0.25, 0.10],
        "RETURNING_FROM_INJURY_OR_SHORTENED": [0.40, 0.40, 0.20],
        "LOW_SAMPLE": [0.70, 0.20, 0.10],
    }.get(state, [0.55, 0.30, 0.15])
    return base[:count]


def availability_weights(state: str, count: int) -> List[float]:
    base = [0.35, 0.40, 0.25] if state == "RETURNING_FROM_INJURY_OR_SHORTENED" else [0.55, 0.30, 0.15]
    return base[:count]


def role_score(role: str) -> int:
    return {"STARTER": 4, "CO_STARTER": 3, "ROTATIONAL": 2, "BACKUP": 1}.get(role, 0)


def estimate_target_age(history: pd.DataFrame, target_season: int) -> float:
    ages = history[pd.to_numeric(history["age"], errors="coerce").notna()]
    if ages.empty:
        return np.nan
    latest = ages.sort_values("season", ascending=False).iloc[0]
    return safe_float(latest["age"], np.nan) + max(0, target_season - int(latest["season"]))


def empirical_percentile(past: pd.DataFrame, position: str, rate: float) -> float:
    cohort = past[
        (past["position"] == position)
        & (past["games"] >= 6)
        & (past["role_bucket"].isin(["STARTER", "CO_STARTER"]))
    ]["primary_pg"]
    values = pd.to_numeric(cohort, errors="coerce").dropna().to_numpy()
    if not len(values):
        return 0.5
    return float(np.mean(values <= rate))


def classify_career_state(history: pd.DataFrame, target_season: int, past: pd.DataFrame) -> dict:
    recent = history.sort_values("season", ascending=False).head(3).copy()
    latest = recent.iloc[0]
    position = str(latest["position"])
    target_age = estimate_target_age(recent, target_season)
    older = recent.iloc[1:]
    older_rate = weighted_mean(older["primary_pg"].tolist(), [0.65, 0.35][: len(older)], np.nan)
    older_opp = weighted_mean(older["opportunity_pg"].tolist(), [0.65, 0.35][: len(older)], np.nan)
    latest_rate = safe_float(latest["primary_pg"], 0.0)
    latest_opp = safe_float(latest["opportunity_pg"], 0.0)
    rate_trend = safe_div(latest_rate, older_rate, 1.0) - 1.0 if math.isfinite(older_rate) and older_rate > 0 else 0.0
    opportunity_trend = safe_div(latest_opp, older_opp, 1.0) - 1.0 if math.isfinite(older_opp) and older_opp > 0 else 0.0
    full_seasons = int((recent["games"] >= 8).sum())
    total_games = int(recent["games"].sum())
    latest_percentile = empirical_percentile(past, position, latest_rate)
    previous_role = str(older.iloc[0]["role_bucket"]) if not older.empty else ""
    current_role = str(latest["role_bucket"])
    role_drop = bool(previous_role and role_score(current_role) < role_score(previous_role))
    shortened = int(latest["games"]) <= SHORT_SEASON_GAMES[position]
    preserved_rate = math.isfinite(older_rate) and latest_rate >= older_rate * 0.75

    if role_drop and opportunity_trend <= -0.22 and not shortened:
        state = "ROLE_CHANGED"
    elif shortened and not older.empty and preserved_rate:
        state = "RETURNING_FROM_INJURY_OR_SHORTENED"
    elif len(recent) < 2 or total_games < 12:
        state = "LOW_SAMPLE"
    elif (math.isfinite(target_age) and target_age <= YOUNG_AGE[position]) or safe_float(latest.get("experience"), 99) <= 2:
        state = "ASCENDING" if rate_trend >= 0.08 or opportunity_trend >= 0.10 else "DEVELOPING"
    elif math.isfinite(target_age) and target_age >= DECLINE_AGE[position] and rate_trend <= -0.08:
        state = "DECLINING"
    elif full_seasons >= 2 and latest_percentile >= 0.75 and math.isfinite(target_age) and PEAK_AGES[position][0] <= target_age <= PEAK_AGES[position][1]:
        state = "PEAK"
    elif full_seasons >= 2:
        state = "ESTABLISHED"
    elif rate_trend >= 0.10:
        state = "ASCENDING"
    else:
        state = "DEVELOPING"

    if len(recent) < 2:
        stability = "LOW"
    elif role_drop or opportunity_trend <= -0.25:
        stability = "LOW"
    elif current_role in {"STARTER", "CO_STARTER"} and previous_role in {"STARTER", "CO_STARTER"} and opportunity_trend >= -0.18:
        stability = "HIGH"
    else:
        stability = "MEDIUM"

    star_flag = bool(
        total_games >= 18
        and latest_percentile >= 0.80
        and current_role in {"STARTER", "CO_STARTER"}
        and stability != "LOW"
    )

    flags: List[str] = []
    if math.isfinite(target_age) and target_age >= DECLINE_AGE[position]:
        flags.append("LATE_CAREER")
    if shortened:
        flags.append("SHORTENED_PRIOR_SEASON")
    if role_drop:
        flags.append("ROLE_DROP")
    if star_flag:
        flags.append("ESTABLISHED_STAR_EVIDENCE")
    if len(recent) >= 2 and str(latest["team"]) != str(older.iloc[0]["team"]):
        flags.append("RECENT_TEAM_CHANGE")

    return {
        "career_state": state,
        "career_flags": flags,
        "target_age": target_age,
        "rate_trend": rate_trend,
        "opportunity_trend": opportunity_trend,
        "older_rate": older_rate,
        "older_opportunity": older_opp,
        "latest_percentile": latest_percentile,
        "role_stability": stability,
        "star_flag": star_flag,
        "shortened_prior": shortened,
        "full_prior_seasons": full_seasons,
        "prior_games": total_games,
    }


def cohort_values(past: pd.DataFrame, position: str, role: str, age_group: str) -> dict:
    candidates = [
        past[(past["position"] == position) & (past["role_bucket"] == role) & (past["age_bucket"] == age_group) & (past["games"] >= 4)],
        past[(past["position"] == position) & (past["role_bucket"] == role) & (past["games"] >= 4)],
        past[(past["position"] == position) & (past["games"] >= 4)],
    ]
    cohort = next((frame for frame in candidates if len(frame) >= 12), candidates[-1])
    if cohort.empty:
        fallback_rate = GENERIC_ROLE_RATES[position][0]
        return {"rate": fallback_rate, "opportunity": 1.0, "efficiency": fallback_rate, "games": 15.0, "rows": 0}
    return {
        "rate": float(pd.to_numeric(cohort["primary_pg"], errors="coerce").median()),
        "opportunity": float(pd.to_numeric(cohort["opportunity_pg"], errors="coerce").median()),
        "efficiency": float(pd.to_numeric(cohort["efficiency"], errors="coerce").median()),
        "games": float(pd.to_numeric(cohort["games"], errors="coerce").median()),
        "rows": int(len(cohort)),
    }


def state_adjustment(state: str, rate_trend: float, opportunity_trend: float, target_age: float, position: str) -> float:
    if state == "ASCENDING":
        return 1.0 + clamp(max(rate_trend, opportunity_trend, 0.0) * 0.22, 0.0, 0.06)
    if state == "DEVELOPING":
        return 1.0 + clamp(max(rate_trend, opportunity_trend, 0.0) * 0.12, 0.0, 0.03)
    if state == "DECLINING":
        trend_penalty = clamp(min(rate_trend, opportunity_trend, 0.0) * 0.25, -0.08, 0.0)
        age_penalty = 0.0
        if math.isfinite(target_age):
            age_penalty = -clamp((target_age - DECLINE_AGE[position]) * 0.008, 0.0, 0.04)
        return 1.0 + trend_penalty + age_penalty
    if state == "ROLE_CHANGED":
        return 1.0 + clamp(opportunity_trend * 0.18, -0.08, 0.03)
    if state == "RETURNING_FROM_INJURY_OR_SHORTENED":
        return 1.0 + clamp(max(rate_trend, 0.0) * 0.08, 0.0, 0.02)
    return 1.0


def build_prediction(
    history: pd.DataFrame,
    target_season: int,
    past: pd.DataFrame,
    contract: Optional[ContractRecord],
) -> dict:
    recent = history.sort_values("season", ascending=False).head(3).copy()
    latest = recent.iloc[0]
    position = str(latest["position"])
    state_info = classify_career_state(recent, target_season, past)
    state = str(state_info["career_state"])
    weights = history_weights(state, len(recent))

    direct_rate = weighted_mean(recent["primary_pg"].tolist(), weights)
    opportunity = weighted_mean(recent["opportunity_pg"].tolist(), weights)
    efficiency = weighted_mean(recent["efficiency"].tolist(), weights)
    component_rate = opportunity * efficiency
    raw_rate = 0.75 * direct_rate + 0.25 * component_rate

    age_group = age_bucket(state_info["target_age"], position)
    cohort = cohort_values(past, position, str(latest["role_bucket"]), age_group)
    sample_games = float(recent["games"].sum())
    shrink_k = {
        "PEAK": 4.0,
        "ESTABLISHED": 5.0,
        "ASCENDING": 7.0,
        "RETURNING_FROM_INJURY_OR_SHORTENED": 6.0,
        "DECLINING": 8.0,
        "ROLE_CHANGED": 10.0,
        "DEVELOPING": 12.0,
        "LOW_SAMPLE": 20.0,
    }.get(state, 10.0)
    own_weight = sample_games / (sample_games + shrink_k)
    if state_info["star_flag"]:
        own_weight = max(own_weight, 0.88)
    shrunk_rate = own_weight * raw_rate + (1.0 - own_weight) * cohort["rate"]

    adjustment = state_adjustment(
        state,
        safe_float(state_info["rate_trend"], 0.0),
        safe_float(state_info["opportunity_trend"], 0.0),
        safe_float(state_info["target_age"], np.nan),
        position,
    )
    state_rate = max(0.0, shrunk_rate * adjustment)

    evidence_floor = raw_rate * (0.90 if state_info["star_flag"] else 0.0)
    guardrail_rate = max(state_rate, evidence_floor) if state_info["star_flag"] else state_rate

    contract_status = contract.status if contract else "UNKNOWN"
    contract_rebound = bool(
        contract
        and contract.status == "CONTRACT_YEAR"
        and contract.activate_research_adjustment
        and math.isfinite(safe_float(state_info["older_rate"], np.nan))
        and safe_float(latest["primary_pg"], 0.0) <= safe_float(state_info["older_rate"], 0.0) * 0.85
        and state_info["role_stability"] != "LOW"
    )
    contract_rate = guardrail_rate
    if contract_rebound:
        older_floor = safe_float(state_info["older_rate"], guardrail_rate) * 0.96
        contract_rate = max(guardrail_rate, min(older_floor, guardrail_rate * 1.04))

    game_weights = availability_weights(state, len(recent))
    own_games = weighted_mean(recent["games"].tolist(), game_weights, 15.0)
    games_weight = sample_games / (sample_games + 12.0)
    predicted_games = clamp(games_weight * own_games + (1.0 - games_weight) * cohort["games"], 1.0, 17.0)

    generic_rate = generic_role_rate(position, int(latest["team_position_rank"]), str(latest["role_bucket"]))
    flags = list(state_info["career_flags"])
    if contract_status and contract_status != "UNKNOWN":
        flags.append(contract_status)
    if contract_rebound:
        flags.append("CONTRACT_REBOUND_RESEARCH")

    return {
        "player_id": str(latest["player_id"]),
        "player_name": str(latest["player_name"]),
        "position": position,
        "prior_team": str(latest["team"]),
        "target_season": target_season,
        "career_state": state,
        "career_flags": "|".join(flags),
        "target_age": state_info["target_age"],
        "prior_seasons": int(len(recent)),
        "prior_games": int(state_info["prior_games"]),
        "full_prior_seasons": int(state_info["full_prior_seasons"]),
        "latest_games": int(latest["games"]),
        "latest_rate": float(latest["primary_pg"]),
        "older_rate": state_info["older_rate"],
        "rate_trend_pct": safe_float(state_info["rate_trend"], 0.0) * 100.0,
        "opportunity_trend_pct": safe_float(state_info["opportunity_trend"], 0.0) * 100.0,
        "latest_percentile": safe_float(state_info["latest_percentile"], 0.5) * 100.0,
        "role_bucket": str(latest["role_bucket"]),
        "role_rank": int(latest["team_position_rank"]),
        "role_stability": str(state_info["role_stability"]),
        "star_flag": bool(state_info["star_flag"]),
        "shortened_prior": bool(state_info["shortened_prior"]),
        "cohort_rows": int(cohort["rows"]),
        "cohort_rate": float(cohort["rate"]),
        "history_weight": float(own_weight),
        "state_adjustment": float(adjustment),
        "evidence_floor": float(evidence_floor),
        "predicted_games": float(predicted_games),
        "contract_status": contract_status,
        "contract_decision_type": contract.decision_type if contract else "",
        "contract_rebound_research": contract_rebound,
        "generic_role_rate": float(generic_rate),
        "identity_raw_rate": float(raw_rate),
        "identity_shrunk_rate": float(shrunk_rate),
        "identity_state_rate": float(state_rate),
        "identity_guardrail_rate": float(guardrail_rate),
        "identity_contract_rate": float(contract_rate),
        "generic_role_total": float(generic_rate * predicted_games),
        "identity_raw_total": float(raw_rate * predicted_games),
        "identity_shrunk_total": float(shrunk_rate * predicted_games),
        "identity_state_total": float(state_rate * predicted_games),
        "identity_guardrail_total": float(guardrail_rate * predicted_games),
        "identity_contract_total": float(contract_rate * predicted_games),
        "generic_role_eq17": float(generic_rate * 17.0),
        "identity_raw_eq17": float(raw_rate * 17.0),
        "identity_shrunk_eq17": float(shrunk_rate * 17.0),
        "identity_state_eq17": float(state_rate * 17.0),
        "identity_guardrail_eq17": float(guardrail_rate * 17.0),
        "identity_contract_eq17": float(contract_rate * 17.0),
    }

