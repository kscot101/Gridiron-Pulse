#!/usr/bin/env python3
"""GRIDIRON PULSE v1.9 historical player comparable feature builder.

Research-only, no-lookahead dataset for QB/RB/WR/TE checkpoints at Weeks 4/8/12.
This script does not set production projection weights. It creates raw feature
families that can be evaluated stage-by-stage in rolling held-out seasons.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from v19_player_data_audit import (
    URLS,
    ID_CANDIDATES,
    NAME_CANDIDATES,
    POSITION_CANDIDATES,
    TEAM_CANDIDATES,
    WEEK_CANDIDATES,
    canon_team,
    clean_id,
    first_column,
    load_csv_url,
    load_rds_url,
    normalize_position,
    regular_season_only,
)

CHECKPOINTS = (4, 8, 12)
POSITIONS = ("QB", "RB", "WR", "TE")
GAMES_URL = "https://raw.githubusercontent.com/nflverse/nfldata/refs/heads/master/data/games.csv"


def safe_float(value: object, default: float = np.nan) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def safe_div(num: float, den: float, default: float = 0.0) -> float:
    num = safe_float(num, 0.0)
    den = safe_float(den, 0.0)
    return num / den if abs(den) > 1e-12 else default


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, safe_float(value, low)))


def numeric(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(np.zeros(len(frame)), index=frame.index, dtype=float)
    return pd.to_numeric(frame[column], errors="coerce").fillna(0.0)


def zscores(series: pd.Series) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce")
    mean = values.mean()
    sd = values.std(ddof=0)
    if not math.isfinite(safe_float(sd, np.nan)) or sd < 1e-9:
        return pd.Series(np.zeros(len(values)), index=values.index)
    return (values - mean) / sd


def season_source(source: str, season: int) -> pd.DataFrame:
    url = URLS[source](season)
    try:
        return load_rds_url(url) if source == "depth_charts" else load_csv_url(url)
    except Exception:
        return pd.DataFrame()


def parse_history_coach_continuity(path: Path) -> Dict[Tuple[int, str], float]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    fields = payload.get("fields") or []
    if not isinstance(fields, list):
        return {}
    try:
        season_i = fields.index("season")
        team_i = fields.index("team")
        games_i = fields.index("games")
        coach_i = fields.index("coachContinuity")
    except ValueError:
        return {}
    best: Dict[Tuple[int, str], Tuple[float, float]] = {}
    rows_by_games = payload.get("rowsByGames") or {}
    if not isinstance(rows_by_games, dict):
        return {}
    for rows in rows_by_games.values():
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, list) or max(season_i, team_i, games_i, coach_i) >= len(row):
                continue
            season = int(safe_float(row[season_i], 0))
            team = canon_team(row[team_i])
            games = safe_float(row[games_i], 0.0)
            continuity = safe_float(row[coach_i], np.nan)
            if not season or not team or not math.isfinite(continuity):
                continue
            if 0.0 <= continuity <= 1.0:
                continuity *= 100.0
            key = (season, team)
            if key not in best or games > best[key][0]:
                best[key] = (games, clamp(continuity, 0.0, 100.0))
    return {key: value[1] for key, value in best.items()}


def load_games() -> pd.DataFrame:
    try:
        frame = load_csv_url(GAMES_URL)
    except Exception:
        return pd.DataFrame()
    if "season" not in frame.columns or "week" not in frame.columns:
        return pd.DataFrame()
    season_type = first_column(frame, ["game_type", "season_type"])
    if season_type:
        values = frame[season_type].fillna("").astype(str).str.upper()
        frame = frame[values.isin(["REG", "REGULAR", "2"]) | values.eq("")].copy()
    return frame


def checkpoint_cutoff_date(games: pd.DataFrame, season: int, checkpoint: int) -> Optional[pd.Timestamp]:
    if games.empty:
        return None
    date_col = first_column(games, ["gameday", "game_date", "date"])
    if not date_col:
        return None
    work = games[(pd.to_numeric(games["season"], errors="coerce") == season) & (pd.to_numeric(games["week"], errors="coerce") <= checkpoint)]
    if work.empty:
        return None
    dates = pd.to_datetime(work[date_col], errors="coerce", utc=True).dropna()
    return dates.max() if not dates.empty else None


def build_roster_crosswalk(rosters: Mapping[int, pd.DataFrame]) -> Tuple[Dict[str, str], Dict[str, dict]]:
    pfr_to_gsis: Dict[str, str] = {}
    identity: Dict[str, dict] = {}
    for frame in rosters.values():
        if frame.empty:
            continue
        gsis_col = first_column(frame, ID_CANDIDATES["gsis"])
        pfr_col = first_column(frame, ID_CANDIDATES["pfr"])
        name_col = first_column(frame, NAME_CANDIDATES)
        if not gsis_col:
            continue
        for row in frame.to_dict("records"):
            gsis = clean_id(row.get(gsis_col))
            if not gsis:
                continue
            pfr = clean_id(row.get(pfr_col)) if pfr_col else ""
            if pfr:
                pfr_to_gsis[pfr] = gsis
            info = identity.setdefault(gsis, {})
            info["name"] = str(row.get(name_col) or info.get("name") or "") if name_col else info.get("name", "")
            info["birth_date"] = row.get("birth_date") or info.get("birth_date")
            info["rookie_year"] = row.get("rookie_year") or info.get("rookie_year")
            info["entry_year"] = row.get("entry_year") or info.get("entry_year")
    return pfr_to_gsis, identity


def period_stats(frame: pd.DataFrame, max_week: Optional[int] = None) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    work = regular_season_only(frame.copy())
    week_col = first_column(work, WEEK_CANDIDATES)
    if not week_col:
        return pd.DataFrame()
    work["_week"] = pd.to_numeric(work[week_col], errors="coerce")
    work = work[work["_week"].between(1, 22, inclusive="both")]
    if max_week is not None:
        work = work[work["_week"] <= max_week]
    pos_col = first_column(work, POSITION_CANDIDATES)
    player_col = first_column(work, ID_CANDIDATES["gsis"])
    team_col = first_column(work, TEAM_CANDIDATES)
    name_col = first_column(work, NAME_CANDIDATES)
    if not pos_col or not player_col or not team_col:
        return pd.DataFrame()
    work["_position"] = work[pos_col].map(normalize_position)
    work = work[work["_position"].isin(POSITIONS)].copy()
    work["_player"] = work[player_col].map(clean_id)
    work["_team"] = work[team_col].map(canon_team)
    work["_name"] = work[name_col].fillna("").astype(str) if name_col else ""
    return work[work["_player"].ne("") & work["_team"].ne("")]


def aggregate_players(work: pd.DataFrame) -> pd.DataFrame:
    if work.empty:
        return pd.DataFrame()
    rows: List[dict] = []
    for (player, position), group in work.groupby(["_player", "_position"], sort=False):
        group = group.sort_values("_week", kind="stable")
        games = int(group["game_id"].nunique()) if "game_id" in group.columns else int(group["_week"].nunique())
        if games <= 0:
            continue
        team = str(group["_team"].iloc[-1])
        names = group["_name"].replace("", np.nan).dropna()
        name = str(names.iloc[-1]) if len(names) else player
        attempts = numeric(group, "attempts").sum()
        completions = numeric(group, "completions").sum()
        pass_yards = numeric(group, "passing_yards").sum()
        pass_tds = numeric(group, "passing_tds").sum()
        passing_epa = numeric(group, "passing_epa").sum()
        cpoe = safe_div((numeric(group, "passing_cpoe") * numeric(group, "attempts")).sum(), attempts)
        carries = numeric(group, "carries").sum()
        rush_yards = numeric(group, "rushing_yards").sum()
        rush_tds = numeric(group, "rushing_tds").sum()
        rush_epa = numeric(group, "rushing_epa").sum()
        targets = numeric(group, "targets").sum()
        receptions = numeric(group, "receptions").sum()
        rec_yards = numeric(group, "receiving_yards").sum()
        rec_tds = numeric(group, "receiving_tds").sum()
        rec_epa = numeric(group, "receiving_epa").sum()
        if position == "QB":
            primary = pass_yards
            opportunity = attempts
            efficiency_1 = safe_div(pass_yards, attempts)
            efficiency_2 = safe_div(completions, attempts)
            td_rate = safe_div(pass_tds, attempts)
            epa_per_opp = safe_div(passing_epa, attempts)
            eligible = attempts >= 20
            weekly_primary = numeric(group, "passing_yards")
        elif position == "RB":
            primary = rush_yards + rec_yards
            opportunity = carries + targets
            efficiency_1 = safe_div(rush_yards, carries)
            efficiency_2 = safe_div(primary, opportunity)
            td_rate = safe_div(rush_tds + rec_tds, opportunity)
            epa_per_opp = safe_div(rush_epa + rec_epa, opportunity)
            eligible = opportunity >= 12
            weekly_primary = numeric(group, "rushing_yards") + numeric(group, "receiving_yards")
        else:
            primary = rec_yards
            opportunity = targets
            efficiency_1 = safe_div(rec_yards, targets)
            efficiency_2 = safe_div(receptions, targets)
            td_rate = safe_div(rec_tds, targets)
            epa_per_opp = safe_div(rec_epa, targets)
            eligible = targets >= 6 or receptions >= 4
            weekly_primary = numeric(group, "receiving_yards")
        recent3 = weekly_primary.tail(3)
        rows.append({
            "playerKey": player,
            "playerName": name,
            "position": position,
            "team": team,
            "games": games,
            "primary": float(primary),
            "primary_pg": safe_div(primary, games),
            "recent3_primary_pg": float(recent3.mean()) if len(recent3) else 0.0,
            "primary_volatility": float(weekly_primary.std(ddof=0)) if len(weekly_primary) > 1 else 0.0,
            "opportunity": float(opportunity),
            "opportunity_pg": safe_div(opportunity, games),
            "efficiency_1": float(efficiency_1),
            "efficiency_2": float(efficiency_2),
            "td_rate": float(td_rate),
            "epa_per_opportunity": float(epa_per_opp),
            "cpoe": float(cpoe),
            "pass_attempts": float(attempts),
            "carries": float(carries),
            "targets": float(targets),
            "receptions": float(receptions),
            "eligible": bool(eligible and games >= 2),
        })
    result = pd.DataFrame(rows)
    if result.empty:
        return result
    result["opportunity_share"] = 0.0
    for (team, position), group in result.groupby(["team", "position"]):
        if position == "QB":
            denominator = group["pass_attempts"].sum()
            values = group["pass_attempts"]
        elif position == "RB":
            denominator = group["opportunity"].sum()
            values = group["opportunity"]
        else:
            denominator = result[(result["team"] == team) & (result["position"].isin(["RB", "WR", "TE"]))]["targets"].sum()
            values = group["targets"]
        result.loc[group.index, "opportunity_share"] = values / denominator if denominator > 0 else 0.0
    return result


def team_context(work: pd.DataFrame) -> pd.DataFrame:
    if work.empty:
        return pd.DataFrame()
    rows: List[dict] = []
    for team, group in work.groupby("_team", sort=False):
        games = int(group["game_id"].nunique()) if "game_id" in group.columns else int(group["_week"].nunique())
        games = max(games, 1)
        qb_rows = group[group["_position"] == "QB"]
        pass_attempts = numeric(qb_rows, "attempts").sum()
        pass_yards = numeric(qb_rows, "passing_yards").sum()
        pass_tds = numeric(qb_rows, "passing_tds").sum()
        carries = numeric(group, "carries").sum()
        rush_yards = numeric(group, "rushing_yards").sum()
        rush_tds = numeric(group, "rushing_tds").sum()
        total_targets = numeric(group, "targets").sum()
        pos_targets = {pos: numeric(group[group["_position"] == pos], "targets").sum() for pos in ("RB", "WR", "TE")}
        target_by_player = group.groupby("_player")["targets"].sum() if "targets" in group.columns else pd.Series(dtype=float)
        rb_group = group[group["_position"] == "RB"]
        rb_carry_by_player = rb_group.groupby("_player")["carries"].sum() if "carries" in rb_group.columns else pd.Series(dtype=float)
        rows.append({
            "team": team,
            "team_games": games,
            "pass_rate": safe_div(pass_attempts, pass_attempts + carries),
            "pass_attempts_pg": safe_div(pass_attempts, games),
            "offense_yards_pg": safe_div(pass_yards + rush_yards, games),
            "offense_tds_pg": safe_div(pass_tds + rush_tds, games),
            "rb_target_share": safe_div(pos_targets["RB"], total_targets),
            "wr_target_share": safe_div(pos_targets["WR"], total_targets),
            "te_target_share": safe_div(pos_targets["TE"], total_targets),
            "target_concentration": safe_div(target_by_player.max() if len(target_by_player) else 0.0, total_targets),
            "rb_carry_concentration": safe_div(rb_carry_by_player.max() if len(rb_carry_by_player) else 0.0, rb_carry_by_player.sum() if len(rb_carry_by_player) else 0.0),
        })
    context = pd.DataFrame(rows)
    if context.empty:
        return context
    offense_z = 0.70 * zscores(context["offense_yards_pg"]) + 0.30 * zscores(context["offense_tds_pg"])
    context["team_offense_score"] = (50.0 + 10.0 * offense_z).clip(0.0, 100.0)
    return context


def qb_quality(work: pd.DataFrame) -> Dict[str, float]:
    if work.empty:
        return {}
    qbs = work[work["_position"] == "QB"].copy()
    rows: List[dict] = []
    for (team, player), group in qbs.groupby(["_team", "_player"], sort=False):
        attempts = numeric(group, "attempts").sum()
        if attempts <= 0:
            continue
        sacks = numeric(group, "sacks_suffered").sum()
        rows.append({
            "team": team,
            "player": player,
            "attempts": attempts,
            "epa_att": safe_div(numeric(group, "passing_epa").sum(), attempts),
            "cpoe": safe_div((numeric(group, "passing_cpoe") * numeric(group, "attempts")).sum(), attempts),
            "ypa": safe_div(numeric(group, "passing_yards").sum(), attempts),
            "td_rate": safe_div(numeric(group, "passing_tds").sum(), attempts),
            "int_rate": safe_div(numeric(group, "passing_interceptions").sum(), attempts),
            "sack_rate": safe_div(sacks, attempts + sacks),
        })
    frame = pd.DataFrame(rows)
    if frame.empty:
        return {}
    frame = frame.sort_values(["team", "attempts"], ascending=[True, False]).groupby("team", as_index=False).first()
    composite = 0.35 * zscores(frame["epa_att"]) + 0.20 * zscores(frame["cpoe"]) + 0.20 * zscores(frame["ypa"]) + 0.15 * zscores(frame["td_rate"]) - 0.05 * zscores(frame["int_rate"]) - 0.05 * zscores(frame["sack_rate"])
    frame["quality"] = (50.0 + 10.0 * composite).clip(0.0, 100.0)
    return frame.set_index("team")["quality"].to_dict()


def roster_at_checkpoint(frame: pd.DataFrame, checkpoint: Optional[int]) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    work = frame.copy()
    gsis_col = first_column(work, ID_CANDIDATES["gsis"])
    team_col = first_column(work, TEAM_CANDIDATES)
    pos_col = first_column(work, POSITION_CANDIDATES)
    week_col = first_column(work, WEEK_CANDIDATES)
    if not gsis_col or not team_col or not pos_col:
        return pd.DataFrame()
    work["playerKey"] = work[gsis_col].map(clean_id)
    work["team"] = work[team_col].map(canon_team)
    work["position"] = work[pos_col].map(normalize_position)
    if week_col:
        work["_week"] = pd.to_numeric(work[week_col], errors="coerce")
        if checkpoint is not None:
            work = work[work["_week"] <= checkpoint]
        work = work.sort_values(["playerKey", "_week"], kind="stable").groupby("playerKey", as_index=False).last()
    else:
        work = work.groupby("playerKey", as_index=False).last()
    return work[work["playerKey"].ne("") & work["team"].ne("")]


def snap_context(frame: pd.DataFrame, pfr_to_gsis: Mapping[str, str], checkpoint: Optional[int]) -> Dict[str, dict]:
    if frame.empty:
        return {}
    work = frame.copy()
    week_col = first_column(work, WEEK_CANDIDATES)
    pfr_col = first_column(work, ID_CANDIDATES["pfr"])
    if not week_col or not pfr_col:
        return {}
    work["_week"] = pd.to_numeric(work[week_col], errors="coerce")
    if checkpoint is not None:
        work = work[work["_week"] <= checkpoint]
    work["playerKey"] = work[pfr_col].map(clean_id).map(lambda value: pfr_to_gsis.get(value, ""))
    work = work[work["playerKey"].ne("")]
    if work.empty:
        return {}
    offense_pct = pd.to_numeric(work["offense_pct"], errors="coerce").fillna(0.0) if "offense_pct" in work.columns else pd.Series(np.zeros(len(work)), index=work.index)
    if offense_pct.max() > 1.5:
        offense_pct = offense_pct / 100.0
    work["_snap_share"] = offense_pct.clip(0.0, 1.0)
    work["_offense_snaps"] = numeric(work, "offense_snaps")
    grouped = work.groupby("playerKey").agg(snap_games=("_week", "nunique"), snap_share=("_snap_share", "mean"), offense_snaps=("_offense_snaps", "sum"))
    return grouped.to_dict("index")


def depth_context(frame: pd.DataFrame, checkpoint: Optional[int], cutoff: Optional[pd.Timestamp]) -> Dict[str, dict]:
    if frame.empty:
        return {}
    work = frame.copy()
    gsis_col = first_column(work, ID_CANDIDATES["gsis"])
    if not gsis_col:
        return {}
    work["playerKey"] = work[gsis_col].map(clean_id)
    if "week" in work.columns:
        work["_order"] = pd.to_numeric(work["week"], errors="coerce")
        if checkpoint is not None:
            work = work[work["_order"] <= checkpoint]
        rank_col = "depth_team" if "depth_team" in work.columns else None
    elif "dt" in work.columns:
        work["_date"] = pd.to_datetime(work["dt"], errors="coerce", utc=True)
        if cutoff is not None:
            cutoff = pd.to_datetime(cutoff, errors="coerce", utc=True)
            if pd.notna(cutoff):
                work = work[work["_date"] <= cutoff]
        work["_order"] = work["_date"].map(lambda value: value.value if pd.notna(value) else -1)
        rank_col = "pos_rank" if "pos_rank" in work.columns else None
    else:
        return {}
    if not rank_col or work.empty:
        return {}
    work["_rank"] = pd.to_numeric(work[rank_col], errors="coerce")
    work = work[work["playerKey"].ne("")]
    if work.empty:
        return {}
    latest_order = work.groupby("playerKey")["_order"].transform("max")
    latest = work[work["_order"] == latest_order]
    grouped = latest.groupby("playerKey")["_rank"].min()
    return {key: {"depth_rank": safe_float(value, np.nan), "starter_flag": 1.0 if safe_float(value, 99.0) <= 1.0 else 0.0} for key, value in grouped.items()}


def injury_context(frame: pd.DataFrame, checkpoint: Optional[int]) -> Dict[str, dict]:
    if frame.empty:
        return {}
    work = frame.copy()
    gsis_col = first_column(work, ID_CANDIDATES["gsis"])
    week_col = first_column(work, WEEK_CANDIDATES)
    if not gsis_col or not week_col or "report_status" not in work.columns:
        return {}
    work["playerKey"] = work[gsis_col].map(clean_id)
    work["_week"] = pd.to_numeric(work[week_col], errors="coerce")
    if checkpoint is not None:
        work = work[work["_week"] <= checkpoint]
    status = work["report_status"].fillna("").astype(str).str.upper()
    work["_burden"] = status.map({"OUT": 1.0, "DOUBTFUL": 0.75, "QUESTIONABLE": 0.35}).fillna(0.0)
    work["_out"] = status.eq("OUT").astype(float)
    grouped = work.groupby("playerKey").agg(injury_reports=("_week", "nunique"), injury_burden=("_burden", "mean"), out_reports=("_out", "sum"))
    result = grouped.to_dict("index")
    for info in result.values():
        reports = max(safe_float(info.get("injury_reports"), 0.0), 1.0)
        info["out_report_rate"] = safe_div(info.get("out_reports", 0.0), reports)
        info["injury_burden"] = safe_float(info.get("injury_burden"), 0.0) * 100.0
    return result


def roster_sets(roster: pd.DataFrame) -> Dict[Tuple[str, str], set[str]]:
    output: Dict[Tuple[str, str], set[str]] = {}
    if roster.empty:
        return output
    for row in roster.to_dict("records"):
        team = str(row.get("team") or "")
        pos = str(row.get("position") or "")
        key = str(row.get("playerKey") or "")
        if team and pos in POSITIONS and key:
            output.setdefault((team, pos), set()).add(key)
    return output


def context_map(frame: pd.DataFrame) -> Dict[str, dict]:
    return frame.set_index("team").to_dict("index") if not frame.empty else {}


def position_scheme_value(context: Mapping[str, float], position: str) -> float:
    if position == "RB":
        return safe_float(context.get("rb_target_share"), 0.0)
    if position == "WR":
        return safe_float(context.get("wr_target_share"), 0.0)
    if position == "TE":
        return safe_float(context.get("te_target_share"), 0.0)
    return safe_float(context.get("pass_rate"), 0.0)


def concentration_value(context: Mapping[str, float], position: str) -> float:
    if position == "RB":
        return safe_float(context.get("rb_carry_concentration"), 0.0)
    if position in {"WR", "TE"}:
        return safe_float(context.get("target_concentration"), 0.0)
    return safe_float(context.get("pass_rate"), 0.0)


def established_score(prior: Optional[Mapping[str, object]], years_exp: float) -> float:
    if not prior:
        return 0.0
    exp_component = clamp(years_exp / 6.0, 0.0, 1.0)
    game_component = clamp(safe_float(prior.get("games"), 0.0) / 17.0, 0.0, 1.0)
    share_component = clamp(safe_float(prior.get("opportunity_share"), 0.0) / 0.30, 0.0, 1.0)
    production_component = clamp(safe_float(prior.get("primary_pg"), 0.0) / 90.0, 0.0, 1.0)
    return 100.0 * (0.25 * exp_component + 0.25 * game_component + 0.25 * share_component + 0.25 * production_component)


def years_experience(roster_row: Optional[Mapping[str, object]], season: int, identity: Mapping[str, object]) -> float:
    if roster_row:
        value = safe_float(roster_row.get("years_exp"), np.nan)
        if math.isfinite(value):
            return max(0.0, value)
    rookie_year = safe_float(identity.get("rookie_year") or identity.get("entry_year"), np.nan)
    return max(0.0, season - rookie_year) if math.isfinite(rookie_year) else 0.0


def feature_row(season: int, checkpoint: int, current: Mapping[str, object], final: Mapping[str, object], prior: Optional[Mapping[str, object]], current_context: Mapping[str, dict], prior_context: Mapping[str, dict], current_qb: Mapping[str, float], prior_qb: Mapping[str, float], current_snap: Mapping[str, dict], prior_snap: Mapping[str, dict], current_depth: Mapping[str, dict], prior_depth: Mapping[str, dict], current_injury: Mapping[str, dict], current_roster: pd.DataFrame, current_roster_sets: Mapping[Tuple[str, str], set[str]], prior_players: Mapping[str, dict], coach_continuity: Mapping[Tuple[int, str], float], identity: Mapping[str, dict]) -> dict:
    player = str(current["playerKey"])
    position = str(current["position"])
    team = str(current["team"])
    prior_team = str(prior.get("team") or "") if prior else ""
    prior_team_context = prior_context.get(prior_team, {}) if prior_team else {}
    current_team_context = current_context.get(team, {})
    changed_teams = 1.0 if prior_team and prior_team != team else 0.0
    roster_row = None
    if not current_roster.empty:
        match = current_roster[current_roster["playerKey"] == player]
        if not match.empty:
            roster_row = match.iloc[-1].to_dict()
    years_exp = years_experience(roster_row, season, identity.get(player, {}))
    established = established_score(prior, years_exp)
    snap = current_snap.get(player, {})
    prior_snap_info = prior_snap.get(player, {})
    depth = current_depth.get(player, {})
    prior_depth_info = prior_depth.get(player, {})
    injury = current_injury.get(player, {})
    snap_share = safe_float(snap.get("snap_share"), np.nan)
    prior_snap_share = safe_float(prior_snap_info.get("snap_share"), np.nan)
    depth_rank = safe_float(depth.get("depth_rank"), np.nan)
    prior_depth_rank = safe_float(prior_depth_info.get("depth_rank"), np.nan)
    starter = safe_float(depth.get("starter_flag"), np.nan)
    current_share = safe_float(current.get("opportunity_share"), 0.0)
    prior_share = safe_float(prior.get("opportunity_share"), 0.0) if prior else 0.0
    role_parts: List[float] = []
    if math.isfinite(snap_share) and math.isfinite(prior_snap_share):
        role_parts.append((snap_share - prior_snap_share) * 100.0)
    if prior:
        role_parts.append((current_share - prior_share) * 100.0)
    if math.isfinite(depth_rank) and math.isfinite(prior_depth_rank):
        role_parts.append((prior_depth_rank - depth_rank) * 20.0)
    role_delta = float(np.mean(role_parts)) if role_parts else 0.0
    current_qb_quality = safe_float(current_qb.get(team), 50.0)
    prior_qb_quality = safe_float(prior_qb.get(prior_team), 50.0) if prior_team else 50.0
    qb_delta = current_qb_quality - prior_qb_quality if position != "QB" and prior else 0.0
    team_offense_delta = safe_float(current_team_context.get("team_offense_score"), 50.0) - safe_float(prior_team_context.get("team_offense_score"), 50.0) if prior else 0.0
    scheme_usage_delta = (position_scheme_value(current_team_context, position) - position_scheme_value(prior_team_context, position)) * 100.0 if prior else 0.0
    scheme_concentration_delta = (concentration_value(current_team_context, position) - concentration_value(prior_team_context, position)) * 100.0 if prior else 0.0
    pass_rate_delta = (safe_float(current_team_context.get("pass_rate"), 0.0) - safe_float(prior_team_context.get("pass_rate"), 0.0)) * 100.0 if prior else 0.0
    coach_score = safe_float(coach_continuity.get((season, team)), 50.0)
    current_team_prior_pos = [row for row in prior_players.values() if str(row.get("team") or "") == team and str(row.get("position") or "") == position]
    prior_team_position_opp = sum(safe_float(row.get("opportunity"), 0.0) for row in current_team_prior_pos)
    current_ids = current_roster_sets.get((team, position), set())
    vacated_opp = sum(safe_float(row.get("opportunity"), 0.0) for row in current_team_prior_pos if str(row.get("playerKey") or "") not in current_ids)
    incoming_opp = 0.0
    for peer in current_ids:
        if peer == player:
            continue
        peer_prior = prior_players.get(peer)
        if peer_prior and str(peer_prior.get("team") or "") != team:
            incoming_opp += safe_float(peer_prior.get("opportunity"), 0.0)
    vacated_pct = 100.0 * safe_div(vacated_opp, prior_team_position_opp)
    incoming_pct = 100.0 * safe_div(incoming_opp, prior_team_position_opp)
    competition_delta = vacated_pct - incoming_pct
    opportunity_delta = (current_share - prior_share) * 100.0 if prior else 0.0
    availability_rate = safe_div(current.get("games", 0.0), current_team_context.get("team_games", checkpoint), 0.0)
    prior_availability = safe_div(prior.get("games", 0.0), prior_team_context.get("team_games", 17.0), 0.0) if prior else 0.0
    injury_context_delta = (availability_rate - prior_availability) * 100.0 if prior else 0.0
    final_games = safe_float(final.get("games"), 0.0)
    final_primary = safe_float(final.get("primary"), 0.0)
    target_eq17 = safe_div(final_primary, final_games) * 17.0 if final_games > 0 else np.nan
    pace_eq17 = safe_div(current.get("primary", 0.0), current.get("games", 0.0)) * 17.0
    return {
        "season": season, "checkpoint": checkpoint, "playerKey": player, "playerName": current.get("playerName", player), "position": position, "team": team, "priorTeam": prior_team,
        "games": int(safe_float(current.get("games"), 0.0)), "finalGames": int(final_games), "currentPrimary": safe_float(current.get("primary"), 0.0), "finalPrimary": final_primary, "targetPrimaryEq17": target_eq17, "pacePrimaryEq17": pace_eq17,
        "current_primary_pg": safe_float(current.get("primary_pg"), 0.0), "recent3_primary_pg": safe_float(current.get("recent3_primary_pg"), 0.0), "primary_volatility": safe_float(current.get("primary_volatility"), 0.0), "opportunity_pg": safe_float(current.get("opportunity_pg"), 0.0), "opportunity_share": current_share,
        "efficiency_1": safe_float(current.get("efficiency_1"), 0.0), "efficiency_2": safe_float(current.get("efficiency_2"), 0.0), "td_rate": safe_float(current.get("td_rate"), 0.0), "epa_per_opportunity": safe_float(current.get("epa_per_opportunity"), 0.0),
        "prior_primary_pg": safe_float(prior.get("primary_pg"), 0.0) if prior else 0.0, "prior_opportunity_share": prior_share, "years_experience": years_exp, "established_player_score": established,
        "snap_share": snap_share, "prior_snap_share": prior_snap_share, "depth_rank": depth_rank, "starter_flag": starter, "role_delta": role_delta,
        "availability_rate": availability_rate, "injury_burden": safe_float(injury.get("injury_burden"), 0.0), "out_report_rate": safe_float(injury.get("out_report_rate"), 0.0), "injury_context_delta": injury_context_delta,
        "qb_quality_current": current_qb_quality, "qb_quality_prior": prior_qb_quality, "qb_quality_delta": qb_delta, "qb_delta_x_prior_share": qb_delta * prior_share, "qb_delta_x_established": qb_delta * established / 100.0,
        "coach_continuity_score": coach_score, "scheme_position_usage_delta": scheme_usage_delta, "scheme_concentration_delta": scheme_concentration_delta, "team_pass_rate_delta": pass_rate_delta, "coach_usage_delta": scheme_usage_delta,
        "changed_teams": changed_teams, "team_offense_delta": team_offense_delta, "team_change_x_established": changed_teams * established,
        "vacated_opportunity_pct": vacated_pct, "incoming_competition_pct": incoming_pct, "competition_delta": competition_delta, "opportunity_delta": opportunity_delta,
        "snap_data_available": 1.0 if math.isfinite(snap_share) else 0.0, "depth_data_available": 1.0 if math.isfinite(depth_rank) else 0.0, "prior_data_available": 1.0 if prior else 0.0,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=int, default=2012)
    parser.add_argument("--end", type=int, default=2025)
    parser.add_argument("--out", type=Path, default=Path("model-lab/output/v19-player-features"))
    parser.add_argument("--history", type=Path, default=Path("data/gridiron-history-data.json"))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    seasons = list(range(args.start, args.end + 1))
    games = load_games()
    coach_continuity = parse_history_coach_continuity(args.history)
    print("[v1.9 features] Loading roster crosswalk", flush=True)
    rosters: Dict[int, pd.DataFrame] = {season: season_source("rosters", season) for season in seasons}
    pfr_to_gsis, identity = build_roster_crosswalk(rosters)
    full_players: Dict[int, Dict[str, dict]] = {}
    full_context: Dict[int, Dict[str, dict]] = {}
    full_qb: Dict[int, Dict[str, float]] = {}
    full_snap: Dict[int, Dict[str, dict]] = {}
    full_depth: Dict[int, Dict[str, dict]] = {}
    rows: List[dict] = []
    quality_rows: List[dict] = []
    for season in seasons:
        print(f"[v1.9 features] Season {season}", flush=True)
        stats_raw = season_source("player_stats", season)
        snap_raw = season_source("snap_counts", season)
        injury_raw = season_source("injuries", season)
        depth_raw = season_source("depth_charts", season)
        roster_raw = rosters.get(season, pd.DataFrame())
        if stats_raw.empty:
            quality_rows.append({"season": season, "status": "missing-player-stats"})
            continue
        full_work = period_stats(stats_raw, None)
        full_player_df = aggregate_players(full_work)
        full_player_map = full_player_df.set_index("playerKey").to_dict("index") if not full_player_df.empty else {}
        for key, info in full_player_map.items():
            info["playerKey"] = key
        full_players[season] = full_player_map
        full_context[season] = context_map(team_context(full_work))
        full_qb[season] = qb_quality(full_work)
        full_snap[season] = snap_context(snap_raw, pfr_to_gsis, None)
        full_depth[season] = depth_context(depth_raw, None, checkpoint_cutoff_date(games, season, 22))
        for checkpoint in CHECKPOINTS:
            current_work = period_stats(stats_raw, checkpoint)
            current_player_df = aggregate_players(current_work)
            if current_player_df.empty:
                continue
            current_player_df = current_player_df[current_player_df["eligible"]].copy()
            current_context = context_map(team_context(current_work))
            current_qb = qb_quality(current_work)
            current_snap = snap_context(snap_raw, pfr_to_gsis, checkpoint)
            current_depth = depth_context(depth_raw, checkpoint, checkpoint_cutoff_date(games, season, checkpoint))
            current_injury = injury_context(injury_raw, checkpoint)
            current_roster = roster_at_checkpoint(roster_raw, checkpoint)
            current_sets = roster_sets(current_roster)
            prior_players = full_players.get(season - 1, {})
            prior_context = full_context.get(season - 1, {})
            prior_qb = full_qb.get(season - 1, {})
            prior_snap = full_snap.get(season - 1, {})
            prior_depth = full_depth.get(season - 1, {})
            for current in current_player_df.to_dict("records"):
                player = str(current["playerKey"])
                final = full_player_map.get(player)
                if not final:
                    continue
                rows.append(feature_row(season, checkpoint, current, final, prior_players.get(player), current_context, prior_context, current_qb, prior_qb, current_snap, prior_snap, current_depth, prior_depth, current_injury, current_roster, current_sets, prior_players, coach_continuity, identity))
        quality_rows.append({"season": season, "playerRows": len(full_player_df), "snapMappedPlayers": len(full_snap[season]), "depthPlayers": len(full_depth[season]), "coachContinuityTeams": sum(1 for key in coach_continuity if key[0] == season)})
    features = pd.DataFrame(rows)
    quality = pd.DataFrame(quality_rows)
    features.to_csv(args.out / "player_features.csv", index=False)
    quality.to_csv(args.out / "feature_quality.csv", index=False)
    feature_groups = {
        "production_usage": ["current_primary_pg", "recent3_primary_pg", "primary_volatility", "opportunity_pg", "opportunity_share", "efficiency_1", "efficiency_2", "td_rate", "epa_per_opportunity", "prior_primary_pg", "prior_opportunity_share", "years_experience", "established_player_score"],
        "role": ["snap_share", "depth_rank", "starter_flag", "role_delta"],
        "health": ["availability_rate", "injury_burden", "out_report_rate", "injury_context_delta"],
        "qb_environment": ["qb_quality_delta", "qb_delta_x_prior_share", "qb_delta_x_established"],
        "coach_scheme": ["coach_continuity_score", "scheme_position_usage_delta", "scheme_concentration_delta", "team_pass_rate_delta"],
        "trade_team_change": ["changed_teams", "team_offense_delta", "team_change_x_established"],
        "opportunity_competition": ["vacated_opportunity_pct", "incoming_competition_pct", "competition_delta", "opportunity_delta"],
    }
    manifest = {
        "lab": "GRIDIRON PULSE v1.9 player comparable feature dataset",
        "researchOnly": True,
        "noProductionWeights": True,
        "seasons": [args.start, args.end],
        "checkpoints": list(CHECKPOINTS),
        "positions": list(POSITIONS),
        "rowCount": int(len(features)),
        "featureGroups": feature_groups,
        "notes": [
            "Current-season inputs stop at each checkpoint; full-season outcomes are targets only.",
            "Snap-dependent features are naturally missing for 2012 and are median-imputed inside held-out backtests.",
            "2025 depth charts use dated snapshots; the builder cuts them at the checkpoint schedule date.",
            "Coach/scheme stage uses historical coach-continuity plus observed point-in-time team usage fingerprints. It does not invent named-coach resume data.",
            "Historical comparables are evaluated as residual adjustments to the checkpoint pace baseline; production integration weights remain unset.",
        ],
    }
    (args.out / "feature_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({"rows": len(features), "features": len(features.columns), "groups": feature_groups}, indent=2), flush=True)


if __name__ == "__main__":
    main()
