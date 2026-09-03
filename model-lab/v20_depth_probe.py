#!/usr/bin/env python3
"""Temporary schema probe for v2.0 historical preseason depth charts."""
from pathlib import Path

import pandas as pd

from v20_player_identity_core import first_column, load_csv_url
from v20_player_identity_integration_replay import (
    GAMES_URL,
    first_regular_kickoff,
    load_depth_chart,
    preseason_depth,
)

CACHE = Path("model-lab/output/v20-player-identity-cache")

games = load_csv_url(GAMES_URL, CACHE / "games.csv")

for season in (2015, 2020, 2024, 2025):
    frame = load_depth_chart(season, CACHE)
    print("\n===", season, "===")
    print("shape:", frame.shape)
    print("columns:", list(frame.columns))
    print("first kickoff:", first_regular_kickoff(games, season))

    week_col = first_column(frame, ["week", "game_week"])
    date_col = first_column(frame, ["dt", "date", "game_date"])
    rank_col = first_column(frame, ["pos_rank", "depth_team", "rank", "depth_rank"])
    id_col = first_column(frame, ["gsis_id", "player_id", "player_gsis_id", "nfl_id"])
    pos_col = first_column(frame, ["position", "position_group", "pos", "depth_position", "pos_grp", "pos_name", "pos_abb"])

    print("detected:", {"week": week_col, "date": date_col, "rank": rank_col, "id": id_col, "position": pos_col})
    if week_col:
        weeks = pd.to_numeric(frame[week_col], errors="coerce")
        print("week range:", weeks.min(), weeks.max(), "week<=1 rows:", int((weeks <= 1).sum()))
    if date_col:
        dates = pd.to_datetime(frame[date_col], errors="coerce", utc=True)
        print("date range:", dates.min(), dates.max())
        cutoff = first_regular_kickoff(games, season)
        print("date<=cutoff rows:", int((dates <= cutoff).sum()) if cutoff is not None else 0)
    if rank_col:
        ranks = pd.to_numeric(frame[rank_col], errors="coerce")
        print("rank non-null:", int(ranks.notna().sum()), "rank samples:", ranks.dropna().head(10).tolist())
    if id_col:
        ids = frame[id_col].fillna("").astype(str)
        print("id non-empty:", int(ids.ne("").sum()), "id samples:", ids[ids.ne("")].head(5).tolist())
    if pos_col:
        print("position samples:", frame[pos_col].fillna("").astype(str).value_counts().head(20).to_dict())

    selected = preseason_depth(frame, games, season)
    print("selected shape:", selected.shape)
    print("selected sample:", selected.head(10).to_dict("records"))
