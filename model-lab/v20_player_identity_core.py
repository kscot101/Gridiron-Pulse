#!/usr/bin/env python3
"""GRIDIRON PULSE v2.0 Player Identity Baseline research lab.

Builds player-specific preseason rate and availability baselines for QB/RB/WR/TE
from each player's own prior NFL seasons, then compares them with the generic
role-line model currently used by the Season Worker.

Research only. This script never writes to the production Worker, site, KV, or
v1.9 shadow router.
"""
from __future__ import annotations

import argparse
import io
import json
import math
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
import requests

BASE = "https://github.com/nflverse/nflverse-data/releases/download"
POSITIONS = ("QB", "RB", "WR", "TE")
MODELS = (
    "generic_role",
    "identity_raw",
    "identity_shrunk",
    "identity_state",
    "identity_guardrail",
    "identity_contract",
)

TEAM_ALIASES = {
    "JAC": "JAX",
    "LAR": "LAR",
    "LA": "LAR",
    "STL": "LAR",
    "OAK": "LV",
    "SD": "LAC",
    "WSH": "WAS",
}

PEAK_AGES = {
    "QB": (27, 34),
    "RB": (23, 26),
    "WR": (24, 29),
    "TE": (25, 30),
}
DECLINE_AGE = {"QB": 36, "RB": 28, "WR": 31, "TE": 32}
YOUNG_AGE = {"QB": 25, "RB": 24, "WR": 25, "TE": 26}
SHORT_SEASON_GAMES = {"QB": 13, "RB": 12, "WR": 13, "TE": 13}

# Exact generic top-role rates from the current Season Worker.
GENERIC_ROLE_RATES = {
    "QB": [245.0, 22.3, 4.5],
    "RB": [88.0, 48.4, 37.4, 10.9],
    "WR": [67.0, 53.0, 40.0, 17.2, 6.0],
    "TE": [43.0, 14.7, 4.2],
}

MODEL_LABELS = {
    "generic_role": "Current generic role model",
    "identity_raw": "Own-history rate",
    "identity_shrunk": "Own history + cohort shrinkage",
    "identity_state": "Career-state adjusted identity",
    "identity_guardrail": "Identity + established-star evidence floor",
    "identity_contract": "Identity + conditional contract context",
}


@dataclass(frozen=True)
class ContractRecord:
    season: int
    player_id: str
    player_name: str
    team: str
    status: str
    decision_type: str
    source_as_of: str
    note: str
    activate_research_adjustment: bool


def safe_float(value: object, default: float = np.nan) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def clamp(value: float, low: float, high: float) -> float:
    value = safe_float(value, low)
    return max(low, min(high, value))


def safe_div(numerator: float, denominator: float, default: float = 0.0) -> float:
    numerator = safe_float(numerator, 0.0)
    denominator = safe_float(denominator, 0.0)
    return numerator / denominator if abs(denominator) > 1e-12 else default


def weighted_mean(values: Sequence[float], weights: Sequence[float], default: float = 0.0) -> float:
    pairs = [
        (safe_float(value, np.nan), safe_float(weight, 0.0))
        for value, weight in zip(values, weights)
    ]
    pairs = [(value, weight) for value, weight in pairs if math.isfinite(value) and weight > 0]
    if not pairs:
        return default
    total_weight = sum(weight for _, weight in pairs)
    return sum(value * weight for value, weight in pairs) / total_weight


def normalize_name(value: object) -> str:
    text = str(value or "").lower()
    text = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", text)
    return re.sub(r"[^a-z0-9]", "", text)


def normalize_team(value: object) -> str:
    text = str(value or "").strip().upper()
    return TEAM_ALIASES.get(text, text)


def normalize_position(value: object) -> str:
    text = str(value or "").strip().upper()
    if text == "QB":
        return "QB"
    if text in {"RB", "FB", "HB", "TB"}:
        return "RB"
    if text in {"WR", "LWR", "RWR", "SWR", "FL", "SE"}:
        return "WR"
    if text in {"TE", "LTE", "RTE"}:
        return "TE"
    return text


def clean_id(value: object) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    text = str(value).strip()
    return "" if text.lower() in {"", "nan", "none", "null", "na"} else text


def first_column(frame: pd.DataFrame, candidates: Sequence[str]) -> Optional[str]:
    lookup = {str(column).lower(): column for column in frame.columns}
    for candidate in candidates:
        if candidate.lower() in lookup:
            return str(lookup[candidate.lower()])
    return None


def numeric(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(np.zeros(len(frame)), index=frame.index, dtype=float)
    return pd.to_numeric(frame[column], errors="coerce").fillna(0.0)


def fetch_bytes(url: str, attempts: int = 4) -> bytes:
    session = requests.Session()
    session.headers.update({"User-Agent": "GridironPulse-PlayerIdentityLab/2.0"})
    last_error: Optional[Exception] = None
    for attempt in range(1, attempts + 1):
        try:
            response = session.get(url, timeout=90)
            response.raise_for_status()
            return response.content
        except Exception as exc:  # pragma: no cover - network behavior
            last_error = exc
            if attempt < attempts:
                time.sleep(min(10, attempt * 2))
    raise RuntimeError(f"Could not download {url}: {last_error}")


def load_csv_url(url: str, cache_path: Path, optional: bool = False) -> pd.DataFrame:
    try:
        if cache_path.exists() and cache_path.stat().st_size > 100:
            return pd.read_csv(cache_path, low_memory=False)
        data = fetch_bytes(url)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(data)
        return pd.read_csv(io.BytesIO(data), low_memory=False)
    except Exception:
        if optional:
            return pd.DataFrame()
        raise


def stats_url(season: int) -> str:
    return f"{BASE}/stats_player/stats_player_week_{season}.csv"


def roster_url(season: int) -> str:
    return f"{BASE}/rosters/roster_{season}.csv"


def roster_metadata(frame: pd.DataFrame, season: int) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["player_id", "roster_name", "roster_team", "roster_position", "age", "experience"])

    id_col = first_column(frame, ["gsis_id", "player_id", "player_gsis_id", "nfl_id"])
    name_col = first_column(frame, ["full_name", "player_name", "display_name", "player_display_name", "name"])
    team_col = first_column(frame, ["team", "recent_team", "team_abbr", "club_code"])
    pos_col = first_column(frame, ["position", "position_group", "pos"])
    age_col = first_column(frame, ["age"])
    birth_col = first_column(frame, ["birth_date", "birthdate", "date_of_birth"])
    rookie_col = first_column(frame, ["rookie_year", "entry_year", "draft_year"])
    exp_col = first_column(frame, ["years_exp", "experience", "years_experience"])

    if not id_col:
        return pd.DataFrame(columns=["player_id", "roster_name", "roster_team", "roster_position", "age", "experience"])

    work = frame.copy()
    work["player_id"] = work[id_col].map(clean_id)
    work = work[work["player_id"].ne("")].copy()
    work["roster_name"] = work[name_col].fillna("").astype(str) if name_col else ""
    work["roster_team"] = work[team_col].map(normalize_team) if team_col else ""
    work["roster_position"] = work[pos_col].map(normalize_position) if pos_col else ""

    age = pd.to_numeric(work[age_col], errors="coerce") if age_col else pd.Series(np.nan, index=work.index)
    if birth_col:
        birth = pd.to_datetime(work[birth_col], errors="coerce", utc=True)
        season_date = pd.Timestamp(year=season, month=9, day=1, tz="UTC")
        birth_age = (season_date - birth).dt.days / 365.2425
        age = age.fillna(birth_age)
    work["age"] = age

    experience = pd.to_numeric(work[exp_col], errors="coerce") if exp_col else pd.Series(np.nan, index=work.index)
    if rookie_col:
        rookie_year = pd.to_numeric(work[rookie_col], errors="coerce")
        experience = experience.fillna((season - rookie_year).clip(lower=0))
    work["experience"] = experience

    work["_meta_quality"] = (
        work["roster_name"].ne("").astype(int)
        + work["roster_team"].ne("").astype(int)
        + work["roster_position"].isin(POSITIONS).astype(int)
        + work["age"].notna().astype(int)
    )
    work = work.sort_values(["player_id", "_meta_quality"], ascending=[True, False])
    return work.groupby("player_id", as_index=False).first()[
        ["player_id", "roster_name", "roster_team", "roster_position", "age", "experience"]
    ]


def aggregate_player_season(stats: pd.DataFrame, roster: pd.DataFrame, season: int) -> pd.DataFrame:
    if stats.empty:
        return pd.DataFrame()

    work = stats.copy()
    season_type_col = first_column(work, ["season_type", "game_type"])
    if season_type_col:
        values = work[season_type_col].fillna("").astype(str).str.upper()
        work = work[values.isin(["REG", "REGULAR", "2"]) | values.eq("")].copy()

    week_col = first_column(work, ["week", "game_week"])
    id_col = first_column(work, ["player_id", "gsis_id", "player_gsis_id", "nfl_id"])
    name_col = first_column(work, ["player_display_name", "player_name", "display_name", "full_name", "name"])
    pos_col = first_column(work, ["position", "position_group", "pos"])
    team_col = first_column(work, ["recent_team", "team", "team_abbr", "team_abbreviation", "club_code"])
    game_col = first_column(work, ["game_id", "gameid"])

    if not week_col or not id_col or not pos_col or not team_col:
        raise RuntimeError(f"Season {season} player stats are missing required columns")

    work["_week"] = pd.to_numeric(work[week_col], errors="coerce")
    work = work[work["_week"].between(1, 22, inclusive="both")].copy()
    work["player_id"] = work[id_col].map(clean_id)
    work["position"] = work[pos_col].map(normalize_position)
    work["team"] = work[team_col].map(normalize_team)
    work["player_name"] = work[name_col].fillna("").astype(str) if name_col else work["player_id"]
    work = work[
        work["player_id"].ne("")
        & work["team"].ne("")
        & work["position"].isin(POSITIONS)
    ].copy()

    rows: List[dict] = []
    for (player_id, position), group in work.groupby(["player_id", "position"], sort=False):
        group = group.sort_values("_week", kind="stable")
        games = int(group[game_col].nunique()) if game_col else int(group["_week"].nunique())
        if games <= 0:
            continue
        names = group["player_name"].replace("", np.nan).dropna()
        name = str(names.iloc[-1]) if len(names) else player_id
        team = str(group["team"].iloc[-1])

        attempts = float(numeric(group, "attempts").sum())
        pass_yards = float(numeric(group, "passing_yards").sum())
        pass_tds = float(numeric(group, "passing_tds").sum())
        carries = float(numeric(group, "carries").sum())
        rush_yards = float(numeric(group, "rushing_yards").sum())
        rush_tds = float(numeric(group, "rushing_tds").sum())
        targets = float(numeric(group, "targets").sum())
        receptions = float(numeric(group, "receptions").sum())
        rec_yards = float(numeric(group, "receiving_yards").sum())
        rec_tds = float(numeric(group, "receiving_tds").sum())

        if position == "QB":
            primary = pass_yards
            opportunity = attempts
            touchdowns = pass_tds
        elif position == "RB":
            primary = rush_yards + rec_yards
            opportunity = carries + targets
            touchdowns = rush_tds + rec_tds
        else:
            primary = rec_yards
            opportunity = targets
            touchdowns = rec_tds

        rows.append(
            {
                "season": season,
                "player_id": player_id,
                "player_name": name,
                "position": position,
                "team": team,
                "games": games,
                "primary": primary,
                "primary_pg": safe_div(primary, games),
                "opportunity": opportunity,
                "opportunity_pg": safe_div(opportunity, games),
                "efficiency": safe_div(primary, opportunity),
                "touchdowns": touchdowns,
                "touchdowns_pg": safe_div(touchdowns, games),
                "attempts": attempts,
                "carries": carries,
                "targets": targets,
                "receptions": receptions,
            }
        )

    result = pd.DataFrame(rows)
    if result.empty:
        return result

    meta = roster_metadata(roster, season)
    if not meta.empty:
        result = result.merge(meta, on="player_id", how="left")
        result["player_name"] = np.where(
            result["player_name"].eq("") | result["player_name"].isna(),
            result["roster_name"],
            result["player_name"],
        )
        result["team"] = np.where(result["team"].eq(""), result["roster_team"], result["team"])
    else:
        result["age"] = np.nan
        result["experience"] = np.nan

    result["age"] = pd.to_numeric(result.get("age"), errors="coerce")
    result["experience"] = pd.to_numeric(result.get("experience"), errors="coerce")

    result["team_position_rank"] = 99
    result["team_opportunity_share"] = 0.0
    for (_, _, _), group in result.groupby(["season", "team", "position"], sort=False):
        ordered = group.sort_values(["opportunity", "primary"], ascending=[False, False])
        total = float(ordered["opportunity"].sum())
        for rank, (index, row) in enumerate(ordered.iterrows(), start=1):
            result.loc[index, "team_position_rank"] = rank
            result.loc[index, "team_opportunity_share"] = safe_div(row["opportunity"], total)

    result["role_bucket"] = result.apply(role_bucket, axis=1)
    result["generic_role_rate"] = result.apply(
        lambda row: generic_role_rate(str(row["position"]), int(row["team_position_rank"]), str(row["role_bucket"])),
        axis=1,
    )
    result["age_bucket"] = result.apply(lambda row: age_bucket(row["age"], str(row["position"])), axis=1)
    return result


def role_bucket(row: pd.Series) -> str:
    position = str(row["position"])
    rank = int(row["team_position_rank"])
    share = safe_float(row["team_opportunity_share"], 0.0)
    if position == "QB":
        return "STARTER" if rank == 1 else "BACKUP"
    if position == "RB":
        if rank == 1 and share >= 0.38:
            return "STARTER"
        if rank <= 2 and share >= 0.24:
            return "CO_STARTER"
        return "ROTATIONAL" if rank <= 3 else "BACKUP"
    if position == "WR":
        if rank <= 3:
            return "STARTER"
        return "ROTATIONAL" if rank == 4 else "BACKUP"
    if position == "TE":
        if rank == 1:
            return "STARTER"
        return "ROTATIONAL" if rank == 2 else "BACKUP"
    return "BACKUP"


def generic_role_rate(position: str, rank: int, role: str) -> float:
    rates = GENERIC_ROLE_RATES[position]
    if position == "QB":
        index = 0 if role == "STARTER" else 1 if rank == 2 else 2
    elif position == "RB":
        index = 0 if role == "STARTER" else 1 if role == "CO_STARTER" else 2 if role == "ROTATIONAL" else 3
    elif position == "WR":
        index = min(max(rank - 1, 0), len(rates) - 1)
    else:
        index = 0 if role == "STARTER" else 1 if role == "ROTATIONAL" else 2
    return float(rates[index])


def age_bucket(age: object, position: str) -> str:
    value = safe_float(age, np.nan)
    if not math.isfinite(value):
        return "UNKNOWN"
    low, high = PEAK_AGES[position]
    if value < low:
        return "YOUNG"
    if value <= high:
        return "PEAK"
    if value >= DECLINE_AGE[position]:
        return "LATE"
    return "VETERAN"


def load_contract_context(path: Optional[Path]) -> Tuple[Dict[Tuple[int, str], ContractRecord], Dict[Tuple[int, str], ContractRecord], dict]:
    by_id: Dict[Tuple[int, str], ContractRecord] = {}
    by_name: Dict[Tuple[int, str], ContractRecord] = {}
    if not path or not path.exists():
        return by_id, by_name, {"records": 0, "activeResearchAdjustments": 0, "status": "not-supplied"}

    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("players") if isinstance(payload, Mapping) else payload
    if not isinstance(rows, list):
        raise RuntimeError("Contract context must contain a players list")

    active = 0
    for item in rows:
        if not isinstance(item, Mapping):
            continue
        season = int(safe_float(item.get("season"), 0))
        player_id = clean_id(item.get("playerId") or item.get("player_id"))
        player_name = str(item.get("playerName") or item.get("player_name") or "").strip()
        if not season or (not player_id and not player_name):
            continue
        record = ContractRecord(
            season=season,
            player_id=player_id,
            player_name=player_name,
            team=normalize_team(item.get("team")),
            status=str(item.get("status") or "UNKNOWN").strip().upper(),
            decision_type=str(item.get("decisionType") or item.get("decision_type") or "").strip().upper(),
            source_as_of=str(item.get("sourceAsOf") or item.get("source_as_of") or "").strip(),
            note=str(item.get("note") or "").strip(),
            activate_research_adjustment=bool(item.get("activateResearchAdjustment", False)),
        )
        if record.activate_research_adjustment:
            active += 1
        if player_id:
            by_id[(season, player_id.upper())] = record
        if player_name:
            by_name[(season, normalize_name(player_name))] = record
    return by_id, by_name, {"records": len(set(by_id.values()) | set(by_name.values())), "activeResearchAdjustments": active, "status": "loaded"}


def contract_for_player(
    season: int,
    player_id: str,
    player_name: str,
    by_id: Mapping[Tuple[int, str], ContractRecord],
    by_name: Mapping[Tuple[int, str], ContractRecord],
) -> Optional[ContractRecord]:
    return by_id.get((season, player_id.upper())) or by_name.get((season, normalize_name(player_name)))

