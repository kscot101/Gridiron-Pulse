# Gridiron Pulse v2.1 — Last-Season Player Context

## Purpose

Replace career-state projection logic with a simpler and more auditable player model:

1. Start from the player's own previous regular-season per-game production.
2. Use older history only as a sample-size fallback when the previous season was very short.
3. Keep target-season role and projected games separate from production rate.
4. Adjust the rate with bounded, visible context:
   - new team,
   - new starting quarterback,
   - new head coach or offensive coordinator,
   - destination pass volume / positional target environment,
   - full-season schedule matchup,
   - next-opponent matchup.
5. Collect recent attributed player news, but keep it display-only until it has its own validation gate.

## Explicit removals

- Career-state labels are not used to calculate the v2.1 projection.
- Users do not set or change career state.
- Contract status is not part of the v2.1 projection.
- No player receives a manual star boost.
- News sentiment cannot change production by default.

## Baseline

The previous season is the primary evidence. Last-season weight is determined only by games in that season:

- 12+ games: 90%
- 8–11 games: 78%
- 4–7 games: 60%
- fewer than 4 games: 35%

The remaining weight goes to the nearest older-season or role baseline as a small-sample fallback. This prevents a 12-game season from being treated like a low-output full season while avoiding overconfidence in a one- or two-game sample.

## Context

### New team

A team change is a flag and confidence adjustment. It is not automatically positive or negative. The destination quarterback, passing volume, positional share and schedule determine the direction.

### New quarterback

For RB/WR/TE, the target starting quarterback's prior rate is compared with the prior team's primary quarterback. The adjustment is capped.

### New coach / offensive coordinator

A coaching change reduces confidence in the prior team environment. It does not create a blanket production change. Current-season usage replaces preseason uncertainty as games are played.

### Scheme

The target team's prior pass attempts and positional target share are compared with the player's former environment. Adjustments are position-specific and capped.

### Matchups

The full-season schedule uses prior-year yards allowed by position. The next-game view uses the upcoming opponent separately so one matchup does not distort the season total.

## News Pulse

The scheduled collector reads recent headlines from official club RSS feeds and selected national NFL feeds. It stores:

- source,
- date,
- headline,
- matched player,
- explicit role/form/availability phrases,
- source trust,
- recency weight.

The collector does not infer from vague hype. The default configuration sets `applyToProjection` to `false`. News can be displayed as context while the numeric model remains unchanged.

## Safety

All outputs must include:

```json
{
  "researchOnly": true,
  "productionChanged": false,
  "careerStateUsed": false
}
```

The live Season Worker, website, KV and v1.9 routes are not changed by this branch.
