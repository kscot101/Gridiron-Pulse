# GRIDIRON PULSE v1.9 — Player Environment Shift Research Plan

## Goal

Build a no-lookahead historical player comparable layer for QB, RB, WR and TE that adjusts the existing Season Worker player projection only when historical testing shows that the player's changing environment adds predictive value.

## Production architecture

Existing Season Worker player projection
+
Historical player comparable signal
+
Validated Player Environment Shift signal
=
small capped season-long player projection adjustment

The v1.9 lab does **not** replace the existing player model. Every added signal must beat the existing baseline in rolling held-out seasons before promotion.

## Checkpoints

- Week 4
- Week 8
- Week 12

Historical comparison rows may use only information available through that checkpoint. Outcomes after the checkpoint are targets only.

## Positions

- QB
- RB
- WR
- TE

Each position receives its own feature weights and promotion test. There is no universal player-history weight.

## Core comparable features

### Production
- passing / rushing / receiving yards per game
- touchdowns and touchdown rate
- completion / yards-per-attempt style efficiency for QB
- yards per carry for RB
- yards per target / catch for WR and TE
- recent 3-game form
- consistency / volatility

### Usage
- offensive snap share
- pass attempts
- carries
- targets
- receptions
- opportunity per snap
- team opportunity share where reconstructable

### Role
- weekly depth-chart position
- starter / backup / rotational role
- role movement since prior season
- returning role versus newly acquired role

### Health / availability
- injury report status
- missed games
- games active
- role reduction around injury where observable

### Career context
- experience / age where available
- prior-year production
- prior-year usage
- returning starter versus promoted / acquired player

## Player Environment Shift

### 1. QB Quality Change

For WR/RB/TE, estimate the difference between the player's prior passing environment and current passing environment.

Candidate inputs:
- prior/current QB historical production level
- passing efficiency
- passing volume
- sack / pressure handling where reconstructable
- deep passing tendency / efficiency where PBP supports it
- QB rushing tendency where it materially changes target distribution
- team passing efficiency

The effect is interaction-based. A proven high-volume WR should be allowed to capture more of a QB upgrade than an unproven depth receiver.

Candidate interaction terms:
- `qb_quality_delta × prior_target_share`
- `qb_quality_delta × prior_receiving_yards_per_game`
- `qb_quality_delta × established_player_score`
- `qb_quality_delta × deep_target_archetype`

### 2. Coach / Scheme Utilization

Build a point-in-time coach offensive usage fingerprint from seasons before the season being predicted.

Candidate coach fingerprints:
- WR1 target concentration
- WR2 target concentration
- slot / secondary WR opportunity where reconstructable
- TE target share
- RB target share
- RB1 carry share
- committee frequency
- team pass rate
- early-down pass rate where PBP supports it
- red-zone opportunity distribution
- tendency to feature one player versus spread volume

Candidate player-fit signals:
- new coach expected role versus player's prior role
- coach historical usage of player's position/archetype
- returning player under same coach
- prior player-coach connection if reconstructable without future leakage
- first-year coach/player integration risk

### 3. Trade / Team Change Impact

For a player changing teams, create a before/after environment comparison.

Candidate dimensions:
- QB quality delta
- team offensive quality delta
- projected team scoring delta
- target/carry competition delta
- vacated opportunity
- depth-chart role delta
- coach usage-fit delta
- offensive line environment for QB/RB where reconstructable
- expected integration / ramp-up penalty

A trade is not automatically positive or negative. It is evaluated as the net change in role and surrounding environment.

### 4. Established Player Score

Estimate how much evidence exists that the player can command opportunity when the environment improves.

Candidate inputs:
- prior-year production
- multi-year production where available
- prior target/carry share
- prior starting role
- prior snap share
- experience

This is specifically used as an interaction modifier for environmental changes, not as a blanket reputation boost.

### 5. Opportunity / Competition Change

Candidate inputs:
- vacated targets
- vacated carries
- vacated snaps
- incoming target/carry competition
- teammate injuries known by the checkpoint
- depth-chart promotion/demotion
- new WR/RB/TE additions

## Proposed summary metric

`Player Environment Delta` is a diagnostic summary of the validated components, not automatically a percent projection change.

Example components:
- QB upgrade/downgrade
- coach/scheme fit
- opportunity change
- competition change
- team offense change
- integration risk

Historical backtesting determines how much, if any, each component changes projection for each position and checkpoint.

## No-lookahead rules

For a held-out season Y:

- player current-season stats stop at the checkpoint
- snap counts stop at the checkpoint
- depth charts stop at the checkpoint
- injury information stops at the checkpoint
- team performance stops at the checkpoint
- coach fingerprints use seasons strictly before Y
- QB quality priors use seasons strictly before Y plus performance available through the checkpoint
- prior-year player resume uses Y-1 and earlier only
- roster / team-change status must be knowable by the checkpoint
- future player/team results are outcomes only

## Promotion sequence

Test separately before combination:

1. production + usage historical comparables
2. add snap/depth role
3. add health/availability
4. add QB Environment Shift
5. add Coach/Scheme Utilization
6. add Trade/Team Change Impact
7. add Opportunity/Competition Change
8. test compact combination of only individually useful features
9. exact integration replay against the existing Season Worker player projection

## Promotion rules

A feature cannot enter production merely because it is football-logical.

Prefer a signal when it:
- improves overall held-out error
- does not materially worsen recent seasons
- behaves sensibly by checkpoint
- improves or holds in a majority of held-out seasons
- remains useful after being integrated with the existing Season Worker projection

If a signal helps one position but hurts another, keep it position-specific.
