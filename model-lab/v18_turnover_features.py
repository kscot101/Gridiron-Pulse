#!/usr/bin/env python3
from __future__ import annotations
import json, math
from pathlib import Path
from typing import Dict, Iterable, List, Tuple
import numpy as np
import pandas as pd

SCHEDULE_PRIOR_GAMES=3.5
SCHEDULE_MARGIN_SCALE=18.0
ALIASES={"JAC":"JAX","LAR":"LA","STL":"LA","OAK":"LV","SD":"LAC","WSH":"WAS"}
BASE_NUMERIC={"winPct","margin","ppg","papg","pythWinPct","winLuck","closeGamePct","closeWinPct","blowoutWinPct","last3Margin","momentum","offConsistency","defConsistency","offensePulse","defensePulse","tandemPulse","oppQuality","qbContinuity","coachContinuity"}

def canon(v: object) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return ""
    t = str(v).strip().upper()
    return ALIASES.get(t, t)


def numeric(df: pd.DataFrame, cols: Iterable[str]) -> None:
    for c in cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")


def load_history(path: Path) -> pd.DataFrame:
    raw = json.loads(path.read_text(encoding="utf-8"))
    fields = raw["fields"]
    rows: List[dict] = []
    for bucket in raw["rowsByGames"].values():
        for r in bucket:
            if len(r) == len(fields):
                rows.append(dict(zip(fields, r)))
    df = pd.DataFrame(rows)
    if df.empty:
        raise RuntimeError("history dataset contained no in-season rows")
    df["team"] = df["team"].map(canon)
    numeric(df, BASE_NUMERIC | {"season","week","games","finalWinsEq17","finalWins","finalLosses","finalTies"})
    return df


def bool_series(s: pd.Series) -> pd.Series:
    if s.dtype == bool:
        return s.fillna(False)
    return s.fillna(False).astype(str).str.lower().isin({"true","1","1.0","yes"})


def build_turnover_checkpoints(history: pd.DataFrame, sequences: pd.DataFrame) -> pd.DataFrame:
    """Rebuild cumulative turnover metrics with correct possession denominators."""
    s = sequences.copy()
    numeric(s, [
        "season","week","turnoverSequencePoints","postTakeawayPoints","postTakeawayEpa",
        "postTakeawayPointsAboveExpected","turnoverSequenceWpa"
    ])
    for c in ["defenseCreatingTakeaway","offenseGivingAway"]:
        s[c] = s[c].map(canon)
    for c in ["directDefensiveTd","hasPostTakeawayPossession","postTakeawayScored","postTakeawayTd","postTakeawayThreeAndOut"]:
        s[c] = bool_series(s[c])

    take = pd.DataFrame({
        "season": s["season"], "week": s["week"], "team": s["defenseCreatingTakeaway"],
        "takeaways": 1.0, "giveaways": 0.0,
        "directDefensiveTouchdowns": s["directDefensiveTd"].astype(float),
        "postTakeawayPossessions": s["hasPostTakeawayPossession"].astype(float),
        "postTakeawayScores": s["postTakeawayScored"].astype(float),
        "postTakeawayTds": s["postTakeawayTd"].astype(float),
        "postTakeawayThreeAndOuts": s["postTakeawayThreeAndOut"].astype(float),
        "postTakeawayEpaTotal": s["postTakeawayEpa"].where(s["hasPostTakeawayPossession"], 0.0).fillna(0.0),
        "postTakeawayAoeTotal": s["postTakeawayPointsAboveExpected"].where(s["hasPostTakeawayPossession"], 0.0).fillna(0.0),
        "takeawayPoints": s["turnoverSequencePoints"].fillna(0.0),
        "takeawayWpa": s["turnoverSequenceWpa"].fillna(0.0),
        "giveawayDamagePoints": 0.0, "giveawayDamageScores": 0.0, "giveawayWpa": 0.0,
    })

    give = pd.DataFrame({
        "season": s["season"], "week": s["week"], "team": s["offenseGivingAway"],
        "takeaways": 0.0, "giveaways": 1.0,
        "directDefensiveTouchdowns": 0.0, "postTakeawayPossessions": 0.0,
        "postTakeawayScores": 0.0, "postTakeawayTds": 0.0, "postTakeawayThreeAndOuts": 0.0,
        "postTakeawayEpaTotal": 0.0, "postTakeawayAoeTotal": 0.0,
        "takeawayPoints": 0.0, "takeawayWpa": 0.0,
        "giveawayDamagePoints": s["turnoverSequencePoints"].fillna(0.0),
        "giveawayDamageScores": (s["turnoverSequencePoints"].fillna(0.0) > 0).astype(float),
        "giveawayWpa": s["turnoverSequenceWpa"].fillna(0.0),
    })
    weekly = pd.concat([take, give], ignore_index=True)
    weekly = weekly[weekly["team"].ne("")].groupby(["season","week","team"], as_index=False).sum(numeric_only=True)

    metric_cols = [c for c in weekly.columns if c not in {"season","week","team"}]
    cum_parts = []
    for (season, team), grp in weekly.groupby(["season","team"], sort=False):
        g = grp.sort_values("week").copy()
        g[metric_cols] = g[metric_cols].cumsum()
        cum_parts.append(g)
    cumulative = pd.concat(cum_parts, ignore_index=True) if cum_parts else weekly.copy()

    grouped: Dict[Tuple[int,str], pd.DataFrame] = {}
    for key, grp in cumulative.groupby(["season","team"], sort=False):
        grouped[(int(key[0]), canon(key[1]))] = grp.sort_values("week")

    out = []
    for h in history[["season","week","games","team"]].itertuples(index=False):
        season, week, games, team = int(h.season), int(h.week), max(1.0, float(h.games)), canon(h.team)
        grp = grouped.get((season, team))
        if grp is None:
            vals = {c: 0.0 for c in metric_cols}
        else:
            prior = grp[grp["week"] <= week]
            if prior.empty:
                vals = {c: 0.0 for c in metric_cols}
            else:
                last = prior.iloc[-1]
                vals = {c: float(last[c]) for c in metric_cols}

        ta, ga = vals["takeaways"], vals["giveaways"]
        poss = vals["postTakeawayPossessions"]
        dmg_scores = vals["giveawayDamageScores"]
        take_pts, dmg_pts = vals["takeawayPoints"], vals["giveawayDamagePoints"]
        post_rate = lambda numerator: (numerator / poss) if poss > 0 else np.nan
        out.append({
            "season": season, "week": week, "games": int(games), "team": team,
            "takeaways": ta, "giveaways": ga,
            "turnoverMargin": ta - ga, "turnoverMarginPerGame": (ta-ga)/games,
            "directDefensiveTouchdowns": vals["directDefensiveTouchdowns"],
            "postTakeawayPossessions": poss,
            "postTakeawayScoreRate": post_rate(vals["postTakeawayScores"]),
            "postTakeawayTdRate": post_rate(vals["postTakeawayTds"]),
            "postTakeawayThreeAndOutRate": post_rate(vals["postTakeawayThreeAndOuts"]),
            "postTakeawayEpaPerDrive": post_rate(vals["postTakeawayEpaTotal"]),
            "postTakeawayPointsAboveExpected": post_rate(vals["postTakeawayAoeTotal"]),
            "takeawayPoints": take_pts,
            "takeawayPointsPerTakeaway": take_pts/ta if ta > 0 else np.nan,
            "giveawayDamagePoints": dmg_pts,
            "giveawayDamagePointsPerGiveaway": dmg_pts/ga if ga > 0 else np.nan,
            "defenseBailoutRate": 1.0 - dmg_scores/ga if ga > 0 else np.nan,
            "netTurnoverPoints": take_pts-dmg_pts,
            "netTurnoverPointsPerGame": (take_pts-dmg_pts)/games,
            "turnoverSequenceWpa": vals["takeawayWpa"]-vals["giveawayWpa"],
            "turnoverSequenceWpaPerGame": (vals["takeawayWpa"]-vals["giveawayWpa"])/games,
        })
    return pd.DataFrame(out)


def add_schedule_features(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    games = pd.to_numeric(out["games"], errors="coerce").fillna(0.0)
    win = pd.to_numeric(out["winPct"], errors="coerce").fillna(0.5)
    raw = pd.to_numeric(out["oppQuality"], errors="coerce").fillna(0.5)
    corrected = np.where(
        games > 1,
        (games * raw - (1.0 - win)) / np.maximum(1.0, games - 1.0),
        0.5,
    )
    corrected = np.clip(corrected, 0.1, 0.9)
    evidence = games / (games + SCHEDULE_PRIOR_GAMES)
    out["oppQuality"] = corrected
    out["scheduleStrength"] = np.clip(0.5 + (corrected - 0.5) * evidence, 0.2, 0.8)
    out["scheduleAdjustedMargin"] = pd.to_numeric(out["margin"], errors="coerce") + (out["scheduleStrength"] - 0.5) * SCHEDULE_MARGIN_SCALE
    out["turnoverNeutralMargin"] = pd.to_numeric(out["margin"], errors="coerce") - pd.to_numeric(out["netTurnoverPointsPerGame"], errors="coerce").fillna(0.0)
    out["turnoverNeutralScheduleAdjustedMargin"] = out["scheduleAdjustedMargin"] - pd.to_numeric(out["netTurnoverPointsPerGame"], errors="coerce").fillna(0.0)
    return out
