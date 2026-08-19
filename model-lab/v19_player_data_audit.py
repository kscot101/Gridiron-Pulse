#!/usr/bin/env python3
"""GRIDIRON PULSE v1.9 historical player comparable data audit.

The purpose of this first lab is to answer one question before we build any
predictive player layer: do we have enough point-in-time historical context to
run a real no-lookahead player comparable model?

Sources are official nflverse-data release assets:
- weekly player stats
- game-level snap counts
- weekly depth charts
- weekly injury reports
- season rosters / identifier crosswalks

The audit reports source coverage, schemas, identifier match rates, and the
number of QB/RB/WR/TE player-checkpoints available at Weeks 4/8/12.
"""
from __future__ import annotations

import argparse
import io
import json
import math
import re
import sys
import tempfile
import time
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
import requests

try:
    import pyreadr
except ImportError:  # pragma: no cover - workflow installs it
    pyreadr = None

BASE = "https://github.com/nflverse/nflverse-data/releases/download"
CHECKPOINTS = (4, 8, 12)
POSITIONS = ("QB", "RB", "WR", "TE")

ALIASES = {
    "JAC": "JAX",
    "LAR": "LA",
    "STL": "LA",
    "OAK": "LV",
    "SD": "LAC",
    "WSH": "WAS",
}

URLS = {
    "player_stats": lambda season: f"{BASE}/stats_player/stats_player_week_{season}.csv",
    "snap_counts": lambda season: f"{BASE}/snap_counts/snap_counts_{season}.csv",
    "injuries": lambda season: f"{BASE}/injuries/injuries_{season}.csv",
    "rosters": lambda season: f"{BASE}/rosters/roster_{season}.csv",
    "depth_charts": lambda season: f"{BASE}/depth_charts/depth_charts_{season}.rds",
}

ID_CANDIDATES = {
    "gsis": ["gsis_id", "player_id", "player_gsis_id", "nfl_id"],
    "pfr": ["pfr_id", "pfr_player_id", "playerid"],
}

NAME_CANDIDATES = [
    "player_display_name",
    "player_name",
    "full_name",
    "display_name",
    "player",
    "name",
]
TEAM_CANDIDATES = ["recent_team", "team", "club_code", "team_abbr", "team_abbreviation"]
POSITION_CANDIDATES = ["position", "position_group", "pos", "depth_position"]
WEEK_CANDIDATES = ["week", "game_week"]
SEASON_TYPE_CANDIDATES = ["season_type", "game_type"]


def canon_team(value: object) -> str:
    text = str(value or "").strip().upper()
    return ALIASES.get(text, text)


def clean_id(value: object) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    text = str(value).strip()
    if text.lower() in {"", "nan", "none", "null", "na"}:
        return ""
    return text


def clean_name(value: object) -> str:
    text = str(value or "").lower()
    text = re.sub(r"\b(jr|sr|ii|iii|iv)\b", "", text)
    return re.sub(r"[^a-z0-9]", "", text)


def first_column(frame: pd.DataFrame, candidates: Sequence[str]) -> Optional[str]:
    columns = {str(column).lower(): str(column) for column in frame.columns}
    for candidate in candidates:
        if candidate.lower() in columns:
            return columns[candidate.lower()]
    return None


def numeric_series(frame: pd.DataFrame, candidates: Sequence[str]) -> pd.Series:
    column = first_column(frame, candidates)
    if column is None:
        return pd.Series(np.zeros(len(frame)), index=frame.index, dtype=float)
    return pd.to_numeric(frame[column], errors="coerce").fillna(0.0)


def text_series(frame: pd.DataFrame, candidates: Sequence[str]) -> pd.Series:
    column = first_column(frame, candidates)
    if column is None:
        return pd.Series([""] * len(frame), index=frame.index, dtype=object)
    return frame[column].fillna("").astype(str)


def regular_season_only(frame: pd.DataFrame) -> pd.DataFrame:
    column = first_column(frame, SEASON_TYPE_CANDIDATES)
    if column is None:
        return frame
    values = frame[column].fillna("").astype(str).str.upper()
    mask = values.isin(["REG", "REGULAR", "2"]) | values.eq("")
    return frame.loc[mask].copy()


def normalize_position(value: object) -> str:
    position = str(value or "").upper().strip()
    position = re.sub(r"[^A-Z]", "", position)
    if position == "QB":
        return "QB"
    if position in {"RB", "HB", "FB", "TB"}:
        return "RB"
    if position in {"WR", "SE", "FL"}:
        return "WR"
    if position in {"TE"}:
        return "TE"
    return position


def request_bytes(url: str, attempts: int = 3, timeout: int = 60) -> bytes:
    error: Optional[Exception] = None
    headers = {
        "User-Agent": "GridironPulse-v1.9-player-lab/1.0",
        "Accept": "*/*",
    }
    for attempt in range(1, attempts + 1):
        try:
            response = requests.get(url, timeout=timeout, headers=headers, allow_redirects=True)
            response.raise_for_status()
            return response.content
        except Exception as exc:  # pragma: no cover - network dependent
            error = exc
            if attempt < attempts:
                time.sleep(attempt * 1.5)
    raise RuntimeError(f"Download failed for {url}: {error}")


def load_csv_url(url: str) -> pd.DataFrame:
    payload = request_bytes(url)
    return pd.read_csv(io.BytesIO(payload), low_memory=False)


def load_rds_url(url: str) -> pd.DataFrame:
    if pyreadr is None:
        raise RuntimeError("pyreadr is required to read nflverse depth-chart RDS files")
    payload = request_bytes(url)
    with tempfile.NamedTemporaryFile(suffix=".rds") as handle:
        handle.write(payload)
        handle.flush()
        result = pyreadr.read_r(handle.name)
    if not result:
        return pd.DataFrame()
    return next(iter(result.values()))


def load_source(source: str, season: int) -> pd.DataFrame:
    url = URLS[source](season)
    if source == "depth_charts":
        return load_rds_url(url)
    return load_csv_url(url)


def source_summary(source: str, season: int, frame: pd.DataFrame) -> dict:
    team_column = first_column(frame, TEAM_CANDIDATES)
    week_column = first_column(frame, WEEK_CANDIDATES)
    name_column = first_column(frame, NAME_CANDIDATES)
    position_column = first_column(frame, POSITION_CANDIDATES)
    gsis_column = first_column(frame, ID_CANDIDATES["gsis"])
    pfr_column = first_column(frame, ID_CANDIDATES["pfr"])

    summary = {
        "source": source,
        "season": season,
        "rows": int(len(frame)),
        "columns": int(len(frame.columns)),
        "columnNames": [str(column) for column in frame.columns],
        "teamColumn": team_column,
        "weekColumn": week_column,
        "nameColumn": name_column,
        "positionColumn": position_column,
        "gsisColumn": gsis_column,
        "pfrColumn": pfr_column,
        "uniqueTeams": 0,
        "uniqueWeeks": 0,
        "uniquePlayersByName": 0,
        "uniqueGsisIds": 0,
        "uniquePfrIds": 0,
    }

    if team_column:
        summary["uniqueTeams"] = int(frame[team_column].fillna("").astype(str).map(canon_team).replace("", np.nan).nunique())
    if week_column:
        summary["uniqueWeeks"] = int(pd.to_numeric(frame[week_column], errors="coerce").dropna().nunique())
    if name_column:
        summary["uniquePlayersByName"] = int(frame[name_column].fillna("").astype(str).map(clean_name).replace("", np.nan).nunique())
    if gsis_column:
        summary["uniqueGsisIds"] = int(frame[gsis_column].map(clean_id).replace("", np.nan).nunique())
    if pfr_column:
        summary["uniquePfrIds"] = int(frame[pfr_column].map(clean_id).replace("", np.nan).nunique())

    return summary


def build_roster_crosswalk(rosters: Mapping[int, pd.DataFrame]) -> Tuple[set[str], set[str]]:
    gsis: set[str] = set()
    pfr: set[str] = set()
    for frame in rosters.values():
        gsis_column = first_column(frame, ID_CANDIDATES["gsis"])
        pfr_column = first_column(frame, ID_CANDIDATES["pfr"])
        if gsis_column:
            gsis.update(value for value in frame[gsis_column].map(clean_id) if value)
        if pfr_column:
            pfr.update(value for value in frame[pfr_column].map(clean_id) if value)
    return gsis, pfr


def identifier_match_rate(frame: pd.DataFrame, source: str, roster_gsis: set[str], roster_pfr: set[str]) -> dict:
    gsis_column = first_column(frame, ID_CANDIDATES["gsis"])
    pfr_column = first_column(frame, ID_CANDIDATES["pfr"])

    if gsis_column:
        ids = {value for value in frame[gsis_column].map(clean_id) if value}
        matched = ids & roster_gsis
        return {
            "idType": "gsis",
            "idColumn": gsis_column,
            "uniqueIds": len(ids),
            "matchedIds": len(matched),
            "matchPct": round(100 * len(matched) / len(ids), 2) if ids else None,
        }
    if pfr_column:
        ids = {value for value in frame[pfr_column].map(clean_id) if value}
        matched = ids & roster_pfr
        return {
            "idType": "pfr",
            "idColumn": pfr_column,
            "uniqueIds": len(ids),
            "matchedIds": len(matched),
            "matchPct": round(100 * len(matched) / len(ids), 2) if ids else None,
        }
    return {
        "idType": None,
        "idColumn": None,
        "uniqueIds": 0,
        "matchedIds": 0,
        "matchPct": None,
    }


def player_stats_checkpoint_rows(frame: pd.DataFrame, season: int) -> pd.DataFrame:
    frame = regular_season_only(frame)
    if frame.empty:
        return pd.DataFrame()

    week_column = first_column(frame, WEEK_CANDIDATES)
    position_column = first_column(frame, POSITION_CANDIDATES)
    team_column = first_column(frame, TEAM_CANDIDATES)
    name_column = first_column(frame, NAME_CANDIDATES)
    id_column = first_column(frame, ID_CANDIDATES["gsis"])

    if week_column is None or position_column is None:
        return pd.DataFrame()

    work = frame.copy()
    work["_week"] = pd.to_numeric(work[week_column], errors="coerce")
    work = work[work["_week"].between(1, 22, inclusive="both")]
    work["_position"] = work[position_column].map(normalize_position)
    work = work[work["_position"].isin(POSITIONS)]
    if work.empty:
        return pd.DataFrame()

    if id_column:
        work["_player_key"] = work[id_column].map(clean_id)
    else:
        work["_player_key"] = ""
    if name_column:
        fallback_name = work[name_column].map(clean_name)
    else:
        fallback_name = pd.Series([""] * len(work), index=work.index)
    if team_column:
        team = work[team_column].map(canon_team)
    else:
        team = pd.Series([""] * len(work), index=work.index)
    work.loc[work["_player_key"].eq(""), "_player_key"] = (
        team + ":" + fallback_name
    )[work["_player_key"].eq("")]
    work = work[work["_player_key"].ne(":") & work["_player_key"].ne("")]

    metric_candidates = {
        "attempts": ["attempts", "passing_attempts"],
        "passing_yards": ["passing_yards"],
        "carries": ["carries", "rushing_attempts"],
        "rushing_yards": ["rushing_yards"],
        "targets": ["targets"],
        "receptions": ["receptions"],
        "receiving_yards": ["receiving_yards"],
    }
    for metric, candidates in metric_candidates.items():
        work[f"_{metric}"] = numeric_series(work, candidates)

    records: List[dict] = []
    final_totals = work.groupby(["_player_key", "_position"], as_index=False).agg(
        finalGames=("_week", "nunique"),
        finalPassYards=("_passing_yards", "sum"),
        finalRushYards=("_rushing_yards", "sum"),
        finalRecYards=("_receiving_yards", "sum"),
    )
    final_map = {
        (row._player_key, row._position): row
        for row in final_totals.itertuples(index=False)
    }

    for checkpoint in CHECKPOINTS:
        current = work[work["_week"] <= checkpoint]
        grouped = current.groupby(["_player_key", "_position"], as_index=False).agg(
            games=("_week", "nunique"),
            passAttempts=("_attempts", "sum"),
            passYards=("_passing_yards", "sum"),
            carries=("_carries", "sum"),
            rushYards=("_rushing_yards", "sum"),
            targets=("_targets", "sum"),
            receptions=("_receptions", "sum"),
            recYards=("_receiving_yards", "sum"),
        )

        for row in grouped.itertuples(index=False):
            if row.games < 2:
                continue
            if row._position == "QB":
                eligible = row.passAttempts >= 20
                current_primary = row.passYards
            elif row._position == "RB":
                eligible = (row.carries + row.targets) >= 12
                current_primary = row.rushYards + row.recYards
            else:
                eligible = row.targets >= 6 or row.receptions >= 4
                current_primary = row.recYards
            if not eligible:
                continue
            final = final_map.get((row._player_key, row._position))
            if final is None:
                continue
            if row._position == "QB":
                final_primary = final.finalPassYards
            elif row._position == "RB":
                final_primary = final.finalRushYards + final.finalRecYards
            else:
                final_primary = final.finalRecYards
            records.append(
                {
                    "season": season,
                    "checkpoint": checkpoint,
                    "playerKey": row._player_key,
                    "position": row._position,
                    "games": int(row.games),
                    "currentPrimary": float(current_primary),
                    "finalGames": int(final.finalGames),
                    "finalPrimary": float(final_primary),
                }
            )

    return pd.DataFrame(records)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=int, default=2012)
    parser.add_argument("--end", type=int, default=2025)
    parser.add_argument("--out", type=Path, default=Path("model-lab/output/v19-player-audit"))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    frames: Dict[str, Dict[int, pd.DataFrame]] = {source: {} for source in URLS}
    source_rows: List[dict] = []
    failures: List[dict] = []

    seasons = list(range(args.start, args.end + 1))
    for season in seasons:
        print(f"\n[v1.9 audit] Season {season}", flush=True)
        for source in URLS:
            print(f"  - loading {source}...", end="", flush=True)
            try:
                frame = load_source(source, season)
                frames[source][season] = frame
                summary = source_summary(source, season, frame)
                source_rows.append(summary)
                print(f" {len(frame):,} rows / {len(frame.columns)} columns", flush=True)
            except Exception as exc:
                failures.append({"source": source, "season": season, "error": str(exc)})
                print(f" FAILED: {exc}", flush=True)

    roster_gsis, roster_pfr = build_roster_crosswalk(frames["rosters"])
    join_rows: List[dict] = []
    for source, by_season in frames.items():
        if source == "rosters":
            continue
        for season, frame in by_season.items():
            join_rows.append(
                {
                    "source": source,
                    "season": season,
                    **identifier_match_rate(frame, source, roster_gsis, roster_pfr),
                }
            )

    checkpoint_frames: List[pd.DataFrame] = []
    for season, frame in frames["player_stats"].items():
        checkpoint = player_stats_checkpoint_rows(frame, season)
        if not checkpoint.empty:
            checkpoint_frames.append(checkpoint)
    checkpoints = pd.concat(checkpoint_frames, ignore_index=True) if checkpoint_frames else pd.DataFrame()

    if not checkpoints.empty:
        checkpoint_summary = (
            checkpoints.groupby(["checkpoint", "position"], as_index=False)
            .agg(
                playerCheckpoints=("playerKey", "size"),
                seasons=("season", "nunique"),
                uniquePlayers=("playerKey", "nunique"),
                medianGames=("games", "median"),
                medianFinalGames=("finalGames", "median"),
            )
        )
    else:
        checkpoint_summary = pd.DataFrame()

    source_df = pd.DataFrame(source_rows)
    joins_df = pd.DataFrame(join_rows)
    failures_df = pd.DataFrame(failures)

    source_df.to_csv(args.out / "source_coverage.csv", index=False)
    joins_df.to_csv(args.out / "identifier_match_rates.csv", index=False)
    checkpoints.to_csv(args.out / "player_checkpoint_candidates.csv", index=False)
    checkpoint_summary.to_csv(args.out / "checkpoint_summary.csv", index=False)
    failures_df.to_csv(args.out / "failures.csv", index=False)

    required_sources = {
        "player_stats": args.start,
        "snap_counts": max(args.start, 2012),
        "depth_charts": max(args.start, 2001),
        "injuries": max(args.start, 2009),
        "rosters": args.start,
    }
    source_success = {
        source: len(frames[source])
        for source in URLS
    }

    report = {
        "lab": "GRIDIRON PULSE v1.9 historical player comparable data audit",
        "requestedSeasons": [args.start, args.end],
        "sourceSuccessSeasons": source_success,
        "sourceFailures": failures,
        "rosterCrosswalk": {
            "uniqueGsisIds": len(roster_gsis),
            "uniquePfrIds": len(roster_pfr),
        },
        "checkpointRows": int(len(checkpoints)),
        "checkpointSummary": checkpoint_summary.to_dict("records"),
        "recommendedCommonHistoryStart": 2012,
        "recommendedInitialBacktest": {
            "trainStart": 2012,
            "testStart": 2014,
            "testEnd": args.end,
            "checkpoints": list(CHECKPOINTS),
            "positions": list(POSITIONS),
        },
        "goNoGo": {
            "hasPlayerStats": len(frames["player_stats"]) >= max(1, len(seasons) - 1),
            "hasSnapCounts": len(frames["snap_counts"]) >= max(1, len(seasons) - 1),
            "hasDepthCharts": len(frames["depth_charts"]) >= max(1, len(seasons) - 1),
            "hasInjuries": len(frames["injuries"]) >= max(1, len(seasons) - 1),
            "hasRosters": len(frames["rosters"]) >= max(1, len(seasons) - 1),
            "hasCheckpointSample": len(checkpoints) >= 1000,
        },
    }
    report["goNoGo"]["allCoreDataAvailable"] = all(report["goNoGo"].values())

    (args.out / "audit_summary.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("\nGRIDIRON PULSE v1.9 PLAYER DATA AUDIT", flush=True)
    print(json.dumps(report, indent=2), flush=True)
    if not checkpoint_summary.empty:
        print("\nCHECKPOINT SAMPLE", flush=True)
        print(checkpoint_summary.to_string(index=False), flush=True)
    if failures:
        print("\nSOURCE FAILURES", flush=True)
        print(failures_df.to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
