# Gridiron Pulse v2.0 — Player Identity Baseline

## Purpose

The current Season Worker begins each player from a generic role line (for example, a QB1, WR1, or TE1 average) and then makes relatively small context adjustments. That is useful for unknown players, but it over-regresses established players and can make stars look interchangeable.

v2.0 replaces that research assumption with a player-specific identity baseline while keeping production rate and availability separate.

## Core model

For each QB, RB, WR, and TE:

1. Build the player's own one-to-three season history.
2. Express production per game and per opportunity.
3. Classify the player's career state.
4. Dynamically weight recent seasons based on that state.
5. Shrink only as much as the player's sample requires toward a no-lookahead position/role/age cohort.
6. Apply an evidence floor for established high-percentile starters so a generic role average cannot erase strong multi-season evidence.
7. Estimate games played separately from production rate.
8. Add contract status as a context flag, never a blanket boost.

## Career states

- `LOW_SAMPLE`
- `DEVELOPING`
- `ASCENDING`
- `ESTABLISHED`
- `PEAK`
- `DECLINING`
- `ROLE_CHANGED`
- `RETURNING_FROM_INJURY_OR_SHORTENED`

Additional flags can coexist with the state:

- `LATE_CAREER`
- `SHORTENED_PRIOR_SEASON`
- `ROLE_DROP`
- `RECENT_TEAM_CHANGE`
- `ESTABLISHED_STAR_EVIDENCE`
- `CONTRACT_YEAR`
- `ROOKIE_DEAL`
- other verified contract context

## Contract context policy

Contract status is an overlay, not a free production increase.

The optional contract-rebound research path can activate only when all of these are true:

- verified contract year;
- previous season was materially below the player's older per-game baseline;
- role stability is not low;
- the contract record explicitly enables the research adjustment.

Even then, the adjustment is capped and can only restore a small portion of the player's older evidence. It cannot project a player above his own demonstrated baseline merely because he is seeking a contract.

## Models compared

- Current generic role model
- Own-history rate
- Own history plus cohort shrinkage
- Career-state adjusted identity
- Identity plus established-star evidence floor
- Identity plus conditional contract context

## Required outputs

- player-season source table
- rolling no-lookahead backtest predictions
- overall model comparison
- position comparison
- career-state comparison
- established-star and shortened-season comparison
- 2026 research baselines
- Matthew Stafford and Brock Bowers sanity checks
- promotion gate and run manifest

## Promotion gate

The research candidate is not eligible for Season Worker integration unless:

- overall per-game MAE improves over the generic role model;
- established-star per-game MAE improves by at least 5%;
- no position regresses by more than 2%;
- manual sanity checks show believable rates and availability assumptions;
- production remains unchanged until a separate integration step is approved.

## Separation from production

This branch and workflow are research only. They do not change:

- `main`;
- `gridiron-pulse-season`;
- `gridiron-shadow`;
- the live Gridiron Pulse site;
- Cloudflare KV.
