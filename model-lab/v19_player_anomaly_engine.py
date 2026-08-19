#!/usr/bin/env python3
"""Secondary anomaly guardrail for GRIDIRON PULSE v1.9 player models.

This module is intentionally NOT a core predictive model. It sits beside the
historical-player comparable layer and is used to:

- flag unusual production/usage/environment/model-disagreement situations,
- distinguish explainable regime changes from unexplained noise,
- reduce trust in historical comps when the current situation is structurally new,
- widen projection ranges when uncertainty is unusually high,
- never create a large projection adjustment by itself.

All inputs must be point-in-time / no-lookahead values when used in backtests.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, asdict
from typing import Dict, Iterable, Mapping, Optional, Sequence


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = 0.0
    if not math.isfinite(number):
        number = 0.0
    return max(low, min(high, number))


def mean(values: Iterable[float], fallback: float = 0.0) -> float:
    cleaned = []
    for value in values:
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            cleaned.append(number)
    return sum(cleaned) / len(cleaned) if cleaned else fallback


def robust_zscore(current: float, peer_mean: float, peer_sd: float, cap: float = 4.0) -> float:
    sd = abs(float(peer_sd or 0.0))
    if sd < 1e-9:
        return 0.0
    z = (float(current) - float(peer_mean)) / sd
    return max(-cap, min(cap, z))


def z_to_anomaly(z: float) -> float:
    """Map absolute z distance to a 0-100 anomaly scale."""
    az = abs(float(z))
    if az <= 0.75:
        return 0.0
    if az <= 1.5:
        return (az - 0.75) / 0.75 * 30.0
    if az <= 2.5:
        return 30.0 + (az - 1.5) * 35.0
    return clamp(65.0 + (az - 2.5) / 1.5 * 35.0)


def model_disagreement_score(projections: Sequence[float]) -> float:
    vals = [float(v) for v in projections if v is not None and math.isfinite(float(v))]
    if len(vals) < 2:
        return 0.0
    center = mean(vals)
    if abs(center) < 1e-9:
        return 0.0
    spread = max(vals) - min(vals)
    return clamp((spread / max(abs(center), 1.0)) * 180.0)


def environment_shift_score(features: Mapping[str, float]) -> float:
    """0-100 magnitude of structural environment change.

    Expected feature inputs are already expressed on roughly 0-100 scales or
    percentage-point deltas. Missing inputs simply contribute zero.
    """
    qb = abs(float(features.get("qb_quality_delta", 0.0)))
    coach = abs(float(features.get("coach_usage_delta", 0.0)))
    role = abs(float(features.get("role_delta", 0.0)))
    opportunity = abs(float(features.get("opportunity_delta", 0.0)))
    competition = abs(float(features.get("competition_delta", 0.0)))
    team = abs(float(features.get("team_offense_delta", 0.0)))
    trade = 100.0 if bool(features.get("changed_teams", False)) else 0.0

    return clamp(
        0.25 * qb
        + 0.20 * coach
        + 0.20 * role
        + 0.12 * opportunity
        + 0.08 * competition
        + 0.08 * team
        + 0.07 * trade
    )


def explainability_score(features: Mapping[str, float]) -> float:
    """How much of the anomaly has a plausible football explanation."""
    evidence = [
        abs(float(features.get("qb_quality_delta", 0.0))),
        abs(float(features.get("coach_usage_delta", 0.0))),
        abs(float(features.get("role_delta", 0.0))),
        abs(float(features.get("opportunity_delta", 0.0))),
        abs(float(features.get("competition_delta", 0.0))),
        abs(float(features.get("team_offense_delta", 0.0))),
        abs(float(features.get("injury_context_delta", 0.0))),
    ]
    base = clamp(mean(evidence) * 1.35)
    if bool(features.get("changed_teams", False)):
        base = clamp(base + 8.0)
    if bool(features.get("new_starting_role", False)):
        base = clamp(base + 8.0)
    if bool(features.get("major_teammate_departure", False)):
        base = clamp(base + 6.0)
    return base


@dataclass
class AnomalyResult:
    anomaly_score: float
    explainability_score: float
    regime_change: bool
    label: str
    historical_weight_multiplier: float
    current_role_weight_multiplier: float
    projection_range_multiplier: float
    production_anomaly: float
    usage_anomaly: float
    environment_anomaly: float
    model_disagreement_anomaly: float
    data_anomaly: float
    note: str

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


def anomaly_label(score: float) -> str:
    score = float(score)
    if score >= 81:
        return "EXTREME"
    if score >= 61:
        return "HIGH"
    if score >= 41:
        return "UNUSUAL"
    if score >= 21:
        return "WATCH"
    return "NORMAL"


def evaluate_player_anomaly(
    *,
    production_zscores: Sequence[float] = (),
    usage_zscores: Sequence[float] = (),
    environment_features: Optional[Mapping[str, float]] = None,
    model_projections: Sequence[float] = (),
    data_quality_risk: float = 0.0,
) -> AnomalyResult:
    """Return a secondary anomaly/guardrail assessment.

    This function should be called after the main player models have produced
    their signals. It does not generate a fantasy/yardage projection itself.
    """
    environment_features = environment_features or {}

    production = clamp(mean(z_to_anomaly(z) for z in production_zscores))
    usage = clamp(mean(z_to_anomaly(z) for z in usage_zscores))
    environment = environment_shift_score(environment_features)
    disagreement = model_disagreement_score(model_projections)
    data = clamp(data_quality_risk)

    # Keep anomaly detection secondary. Production/usage lead, but environment,
    # model disagreement and data quality influence trust/uncertainty.
    anomaly = clamp(
        0.30 * production
        + 0.25 * usage
        + 0.20 * environment
        + 0.15 * disagreement
        + 0.10 * data
    )

    explainability = explainability_score(environment_features)
    regime_change = bool(
        environment >= 55.0
        or abs(float(environment_features.get("role_delta", 0.0))) >= 45.0
        or (
            bool(environment_features.get("changed_teams", False))
            and environment >= 40.0
        )
    )

    # Guardrail policy:
    # - explained regime change -> reduce stale-history dependence, increase
    #   current role/environment emphasis;
    # - unexplained anomaly -> reduce historical trust and widen uncertainty;
    # - normal situation -> leave the main model untouched.
    historical_multiplier = 1.0
    current_role_multiplier = 1.0
    range_multiplier = 1.0

    if regime_change and explainability >= 55.0:
        historical_multiplier = 0.72 if anomaly >= 60 else 0.82
        current_role_multiplier = 1.18 if anomaly >= 60 else 1.10
        range_multiplier = 1.10
    elif anomaly >= 81.0:
        historical_multiplier = 0.55
        range_multiplier = 1.35
    elif anomaly >= 61.0:
        historical_multiplier = 0.68
        range_multiplier = 1.25
    elif anomaly >= 41.0:
        historical_multiplier = 0.82
        range_multiplier = 1.12
    elif anomaly >= 21.0:
        historical_multiplier = 0.92
        range_multiplier = 1.05

    if data >= 60.0:
        historical_multiplier = min(historical_multiplier, 0.75)
        range_multiplier = max(range_multiplier, 1.20)

    if regime_change and explainability >= 55.0:
        note = (
            "Unusual situation is substantially explained by a structural role/environment change; "
            "reduce stale-history weight and lean slightly more on current role/environment evidence."
        )
    elif anomaly >= 61.0 and explainability < 40.0:
        note = (
            "High anomaly with weak football explanation; treat the current signal as regression/uncertainty risk "
            "and widen the projection interval."
        )
    elif anomaly >= 41.0:
        note = "Moderately unusual player state; reduce comparable-model trust slightly and widen uncertainty."
    else:
        note = "No material anomaly guardrail required."

    return AnomalyResult(
        anomaly_score=round(anomaly, 1),
        explainability_score=round(explainability, 1),
        regime_change=regime_change,
        label=anomaly_label(anomaly),
        historical_weight_multiplier=round(historical_multiplier, 3),
        current_role_weight_multiplier=round(current_role_multiplier, 3),
        projection_range_multiplier=round(range_multiplier, 3),
        production_anomaly=round(production, 1),
        usage_anomaly=round(usage, 1),
        environment_anomaly=round(environment, 1),
        model_disagreement_anomaly=round(disagreement, 1),
        data_anomaly=round(data, 1),
        note=note,
    )


if __name__ == "__main__":
    # Small smoke example; research workflow/backtests will provide real inputs.
    result = evaluate_player_anomaly(
        production_zscores=[2.4, 1.8],
        usage_zscores=[2.7],
        environment_features={
            "qb_quality_delta": 28,
            "coach_usage_delta": 18,
            "role_delta": 38,
            "opportunity_delta": 26,
            "competition_delta": -12,
            "team_offense_delta": 16,
            "changed_teams": True,
            "new_starting_role": False,
        },
        model_projections=[1180, 1260, 1325, 1240],
        data_quality_risk=5,
    )
    print(result.to_dict())
