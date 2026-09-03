#!/usr/bin/env python3
"""Compatibility runner for the v2.1 last-season context lab.

The first v2.1 draft used descriptive output fields named ``last_year_*`` while
the comparison table expected model keys named ``last_season_*``.  This runner
adds the aliases in one isolated place so the original research module remains
readable and the workflow can continue without touching production code.
"""
from __future__ import annotations

import math

import v21_player_context_baseline as lab


_ORIGINAL_APPLY_ROW = lab.apply_row


def _finite(value, default=0.0):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def apply_row_with_model_aliases(*args, **kwargs):
    """Run the original row builder and add canonical comparison aliases."""
    models = lab.MODELS
    try:
        # The original function computes errors at the end.  Limit that first
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

    return output


lab.apply_row = apply_row_with_model_aliases


if __name__ == "__main__":
    lab.main()
