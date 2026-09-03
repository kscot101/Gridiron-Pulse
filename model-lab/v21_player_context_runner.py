#!/usr/bin/env python3
"""Compatibility runner for the v2.1 last-season context lab.

The first v2.1 draft used descriptive output fields named ``last_year_*`` while
the comparison table expected model keys named ``last_season_*``. This runner
adds the aliases and removes inherited v2.0 career-state fields so the v2.1
feed contains only last-season, role, availability and current-context inputs.
"""
from __future__ import annotations

import math

import v21_player_context_baseline as lab


_ORIGINAL_APPLY_ROW = lab.apply_row

# These columns belong to the retired v2.0 identity/career-state experiment.
# They are removed from both historical and current v2.1 outputs so they cannot
# silently influence, label or confuse the last-season-first model.
_RETIRED_FIELDS = {
    "career_state",
    "career_flags",
    "state_adjustment",
    "star_flag",
    "evidence_floor",
    "role_stability",
    "rate_trend_pct",
    "opportunity_trend_pct",
    "latest_percentile",
    "cohort_rate",
    "cohort_rows",
    "history_weight",
    "shortened_prior",
    "contract_status",
    "contract_decision_type",
    "contract_rebound",
    "generic_role_rate",
    "generic_role_total",
    "identity_raw_rate",
    "identity_raw_total",
    "identity_shrunk_rate",
    "identity_shrunk_total",
    "identity_state_rate",
    "identity_state_total",
    "identity_guardrail_rate",
    "identity_guardrail_total",
    "identity_contract_rate",
    "identity_contract_total",
    "predicted_games",
    "latest_rate",
    "older_rate",
}


def _finite(value, default=0.0):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def apply_row_with_model_aliases(*args, **kwargs):
    """Run the original row builder, add canonical aliases and sanitize it."""
    models = lab.MODELS
    try:
        # The original function computes errors at the end. Limit that first
        # pass to the field that already has an exact name, then add the two
        # canonical aliases and their errors below.
        lab.MODELS = ("role_generic",)
        output = _ORIGINAL_APPLY_ROW(*args, **kwargs)
    finally:
        lab.MODELS = models

    output["last_season_rate"] = output.get("last_year_rate")
    output["last_season_context_rate"] = output.get("last_year_context_rate")

    if "actual_rate" in output:
        actual_rate = _finite(output.get("actual_rate"), 0.0)
        actual_total = _finite(output.get("actual_total"), 0.0)
        for model in ("last_season", "last_season_context"):
            output[f"{model}_rate_error"] = _finite(
                output.get(f"{model}_rate"), 0.0
            ) - actual_rate
            output[f"{model}_total_error"] = _finite(
                output.get(f"{model}_total"), 0.0
            ) - actual_total

    for field in _RETIRED_FIELDS:
        output.pop(field, None)

    output["careerStateUsed"] = False
    output["contractContextUsed"] = False
    return output


lab.apply_row = apply_row_with_model_aliases


if __name__ == "__main__":
    lab.main()
