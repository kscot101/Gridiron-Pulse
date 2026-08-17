#!/usr/bin/env python3
"""GRIDIRON PULSE v1.8 turnover-impact lab (data layer only).

This file does not change production projections. It builds a historical
sequence dataset from nflverse play-by-play so the next step can backtest
turnover creation, conversion, giveaway damage, and defensive bailout value.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import requests

PBP_URL = "https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_{season}.parquet"
ALIASES = {"JAC":"JAX","LAR":"LA","STL":"LA","OAK":"LV","SD":"LAC","WSH":"WAS"}
SPECIAL_TYPES = {"kickoff","punt","field_goal","extra_point"}
COLUMNS = [
    "game_id","season","season_type","week","play_id","drive","fixed_drive",
    "home_team","away_team","posteam","defteam","play_type","desc","special_teams_play",
    "interception","fumble_lost","touchdown","return_touchdown","td_team","yardline_100",
    "down","first_down","first_down_rush","first_down_pass","first_down_penalty","punt_attempt",
    "posteam_score","posteam_score_post","total_home_score","total_away_score","ep","epa","wp","wpa",
    "game_seconds_remaining"
]


def canon(v: object) -> str:
    if v is None or (isinstance(v,float) and math.isnan(v)): return ""
    t=str(v).strip().upper(); return ALIASES.get(t,t)

def num(v: object, default: float=0.0) -> float:
    try:
        n=float(v)
        return n if math.isfinite(n) else default
    except (TypeError,ValueError): return default

def flag(v: object) -> bool: return num(v,0)==1

def first_num(s: pd.Series, default=np.nan) -> float:
    x=pd.to_numeric(s,errors="coerce").dropna(); return float(x.iloc[0]) if len(x) else default

def max_num(s: pd.Series, default=np.nan) -> float:
    x=pd.to_numeric(s,errors="coerce").dropna(); return float(x.max()) if len(x) else default

def sum_num(s: pd.Series) -> float:
    x=pd.to_numeric(s,errors="coerce").dropna(); return float(x.sum()) if len(x) else 0.0


def download(season:int, cache:Path)->Path:
    cache.mkdir(parents=True,exist_ok=True)
    path=cache/f"play_by_play_{season}.parquet"
    if path.exists() and path.stat().st_size>1024: return path
    url=PBP_URL.format(season=season)
    print(f"download {season}: {url}")
    with requests.get(url,stream=True,timeout=180) as r:
        r.raise_for_status()
        with path.open("wb") as f:
            for chunk in r.iter_content(1024*1024):
                if chunk: f.write(chunk)
    return path


def load_pbp(season:int, cache:Path)->pd.DataFrame:
    import pyarrow.parquet as pq
    path=download(season,cache)
    pf=pq.ParquetFile(path); available=set(pf.schema.names)
    df=pf.read(columns=[c for c in COLUMNS if c in available]).to_pandas()
    for c in COLUMNS:
        if c not in df: df[c]=np.nan
    if "season" not in available: df["season"]=season
    df=df[df["season_type"].fillna("REG").astype(str).str.upper().eq("REG")].copy()
    df["season"]=pd.to_numeric(df["season"],errors="coerce").fillna(season).astype(int)
    df["week"]=pd.to_numeric(df["week"],errors="coerce").fillna(0).astype(int)
    df["play_id"]=pd.to_numeric(df["play_id"],errors="coerce").fillna(-1)
    for c in ["posteam","defteam","home_team","away_team","td_team"]: df[c]=df[c].map(canon)
    return df.sort_values(["game_id","play_id"]).reset_index(drop=True)


def is_takeaway(row:pd.Series)->bool:
    offense,defense=canon(row.get("posteam")),canon(row.get("defteam"))
    if not offense or not defense or offense==defense: return False
    # INT + lost fumble on the same play can represent a return fumble; skip it
    # instead of assigning the sequence to the wrong team.
    if flag(row.get("interception")) and flag(row.get("fumble_lost")): return False
    if not (flag(row.get("interception")) or flag(row.get("fumble_lost"))): return False
    p=str(row.get("play_type") or "").lower()
    if flag(row.get("special_teams_play")) or p in SPECIAL_TYPES: return False
    return True


def direct_def_td(row:pd.Series,beneficiary:str)->bool:
    return canon(row.get("td_team"))==beneficiary and (flag(row.get("touchdown")) or flag(row.get("return_touchdown")))


def next_drive(game:pd.DataFrame,pos:int,team:str)->pd.DataFrame:
    start=None
    for i in range(pos+1,len(game)):
        if canon(game.iloc[i].get("posteam"))==team:
            start=i; break
    if start is None: return game.iloc[0:0].copy()
    for drive_col in ("fixed_drive","drive"):
        dv=game.iloc[start].get(drive_col)
        if pd.notna(dv):
            out=game[(game[drive_col]==dv)&(game["posteam"].map(canon)==team)].copy()
            if len(out): return out
    rows=[]; begun=False
    for i in range(start,len(game)):
        r=game.iloc[i]; p=canon(r.get("posteam"))
        if p==team: rows.append(r); begun=True
        elif begun and p: break
        elif begun: rows.append(r)
    return pd.DataFrame(rows) if rows else game.iloc[0:0].copy()


def points_on_drive(drive:pd.DataFrame)->float:
    if drive.empty: return 0.0
    before=first_num(drive["posteam_score"]); after=max_num(drive["posteam_score_post"])
    if math.isfinite(before) and math.isfinite(after): return max(0.0,after-before)
    first=drive.iloc[0]; home=canon(first.get("home_team")); team=canon(first.get("posteam"))
    col="total_home_score" if team==home else "total_away_score"
    before=first_num(drive[col],0.0); after=max_num(drive[col],before); return max(0.0,after-before)


def first_downs(drive:pd.DataFrame)->int:
    cols=[]
    for c in ("first_down","first_down_rush","first_down_pass","first_down_penalty"):
        if c in drive: cols.append(pd.to_numeric(drive[c],errors="coerce").fillna(0))
    if not cols: return 0
    return int((pd.concat(cols,axis=1).max(axis=1)>0).sum())


def sequence(game:pd.DataFrame,pos:int)->Dict[str,object]:
    row=game.iloc[pos]; offense=canon(row.get("posteam")); defense=canon(row.get("defteam"))
    dtype="INT" if flag(row.get("interception")) else "FUMBLE"
    dtd=direct_def_td(row,defense); drive=game.iloc[0:0].copy() if dtd else next_drive(game,pos,defense)
    pts=points_on_drive(drive); start_ep=first_num(drive["ep"]) if len(drive) else np.nan
    off_rows=drive[drive["posteam"].map(canon).eq(defense)] if len(drive) else drive
    epa=sum_num(off_rows["epa"]) if len(off_rows) else 0.0
    drive_wpa=sum_num(off_rows["wpa"]) if len(off_rows) else 0.0
    turnover_wpa=num(row.get("wpa"),np.nan); takeaway_wpa=-turnover_wpa if math.isfinite(turnover_wpa) else np.nan
    td=bool(len(drive) and ((pd.to_numeric(drive["touchdown"],errors="coerce").fillna(0)==1)&drive["td_team"].map(canon).eq(defense)).any())
    fd=first_downs(drive); scrim=int(drive["play_type"].fillna("").astype(str).str.lower().isin(["run","pass"]).sum()) if len(drive) else 0
    punt=bool(len(drive) and (pd.to_numeric(drive["punt_attempt"],errors="coerce").fillna(0)>=1).any())
    three=bool(len(drive) and fd==0 and scrim<=3 and punt)
    direct_pts=6.0 if dtd else 0.0
    seq_wpa=(takeaway_wpa if math.isfinite(takeaway_wpa) else 0.0)+drive_wpa
    return {
        "season":int(row["season"]),"week":int(row["week"]),"gameId":str(row["game_id"]),"playId":num(row["play_id"],-1),
        "offenseGivingAway":offense,"defenseCreatingTakeaway":defense,"turnoverType":dtype,
        "directDefensiveTd":dtd,"defensiveTdPoints":direct_pts,"hasPostTakeawayPossession":bool(len(drive)),
        "postTakeawayPoints":pts,"postTakeawayScored":pts>0,"postTakeawayTd":td,"postTakeawayThreeAndOut":three,
        "postTakeawayFirstDowns":fd,"postTakeawayScrimmagePlays":scrim,
        "postTakeawayStartYardline100":first_num(drive["yardline_100"]) if len(drive) else np.nan,
        "postTakeawayStartEp":start_ep,"postTakeawayPointsAboveExpected":pts-start_ep if math.isfinite(start_ep) else np.nan,
        "postTakeawayEpa":epa,"takeawayPlayWpa":takeaway_wpa,"postTakeawayDriveWpa":drive_wpa,
        "turnoverSequenceWpa":seq_wpa,"turnoverSequencePoints":direct_pts+pts,"turnoverDesc":str(row.get("desc") or "")
    }


def extract(df:pd.DataFrame)->Tuple[pd.DataFrame,Dict[str,int]]:
    rows=[]; d={"games":0,"turnoverCandidates":0,"complexSkipped":0,"specialTeamsSkipped":0,"scrimmageTakeaways":0}
    for _,game in df.groupby("game_id",sort=False):
        game=game.sort_values("play_id").reset_index(drop=True); d["games"]+=1
        for pos in range(len(game)):
            r=game.iloc[pos]; any_to=flag(r.get("interception")) or flag(r.get("fumble_lost"))
            if not any_to: continue
            d["turnoverCandidates"]+=1
            if flag(r.get("interception")) and flag(r.get("fumble_lost")): d["complexSkipped"]+=1; continue
            p=str(r.get("play_type") or "").lower()
            if flag(r.get("special_teams_play")) or p in SPECIAL_TYPES: d["specialTeamsSkipped"]+=1; continue
            if not is_takeaway(r): continue
            d["scrimmageTakeaways"]+=1; rows.append(sequence(game,pos))
    return pd.DataFrame(rows),d


def load_history(path:Path)->pd.DataFrame:
    data=json.loads(path.read_text(encoding="utf-8")); fields=data["fields"]; rows=[]
    for bucket in data["rowsByGames"].values():
        rows.extend(dict(zip(fields,r)) for r in bucket if len(r)==len(fields))
    out=pd.DataFrame(rows); out["team"]=out["team"].map(canon)
    for c in ("season","week","games"): out[c]=pd.to_numeric(out[c],errors="coerce")
    return out


def weekly_sides(seq:pd.DataFrame)->pd.DataFrame:
    if seq.empty: return pd.DataFrame()
    t=seq.copy(); t["team"]=t["defenseCreatingTakeaway"].map(canon); t["takeaways"]=1; t["giveaways"]=0
    t["takeawayPoints"]=t["turnoverSequencePoints"]; t["postPoints"]=t["postTakeawayPoints"]
    t["postScore"]=t["postTakeawayScored"].astype(int); t["postTd"]=t["postTakeawayTd"].astype(int); t["postThree"]=t["postTakeawayThreeAndOut"].astype(int)
    t["postEpa"]=t["postTakeawayEpa"]; t["postAoe"]=pd.to_numeric(t["postTakeawayPointsAboveExpected"],errors="coerce").fillna(0)
    t["takeWpa"]=t["turnoverSequenceWpa"]; t["damagePoints"]=0.0; t["damageScore"]=0; t["giveWpa"]=0.0
    g=seq.copy(); g["team"]=g["offenseGivingAway"].map(canon); g["takeaways"]=0; g["giveaways"]=1
    for c in ("takeawayPoints","postPoints","postScore","postTd","postThree","postEpa","postAoe","takeWpa"): g[c]=0.0
    g["damagePoints"]=g["turnoverSequencePoints"]; g["damageScore"]=(g["turnoverSequencePoints"]>0).astype(int); g["giveWpa"]=g["turnoverSequenceWpa"]
    cols=["season","week","team","takeaways","giveaways","takeawayPoints","postPoints","postScore","postTd","postThree","postEpa","postAoe","takeWpa","damagePoints","damageScore","giveWpa"]
    return pd.concat([t[cols],g[cols]],ignore_index=True).groupby(["season","week","team"],as_index=False).sum(numeric_only=True)


def checkpoints(seq:pd.DataFrame,hist:pd.DataFrame)->pd.DataFrame:
    weekly=weekly_sides(seq); index={}
    if len(weekly):
        for (season,team),grp in weekly.groupby(["season","team"]): index[(int(season),canon(team))]=grp.sort_values("week")
    out=[]
    for _,h in hist.iterrows():
        season=int(num(h.get("season"),0)); week=int(num(h.get("week"),0)); games=max(1.0,num(h.get("games"),1)); team=canon(h.get("team"))
        grp=index.get((season,team)); cur=grp[grp["week"]<=week] if grp is not None else pd.DataFrame()
        def s(c): return sum_num(cur[c]) if len(cur) and c in cur else 0.0
        ta,ga=s("takeaways"),s("giveaways"); tp=s("takeawayPoints"); pp=s("postPoints"); ds=s("damageScore"); dmg=s("damagePoints"); nw=s("takeWpa")-s("giveWpa")
        out.append({
            "season":season,"week":week,"games":int(games),"team":team,"takeaways":ta,"giveaways":ga,"turnoverMargin":ta-ga,"turnoverMarginPerGame":(ta-ga)/games,
            "takeawayPoints":tp,"takeawayPointsPerTakeaway":tp/max(1,ta),"postTakeawayOffensePoints":pp,"postTakeawayScoreRate":s("postScore")/max(1,ta),
            "postTakeawayTdRate":s("postTd")/max(1,ta),"postTakeawayThreeAndOutRate":s("postThree")/max(1,ta),"postTakeawayEpaPerDrive":s("postEpa")/max(1,ta),
            "postTakeawayPointsAboveExpected":s("postAoe")/max(1,ta),"giveawayDamagePoints":dmg,"giveawayDamagePointsPerGiveaway":dmg/max(1,ga),
            "defenseBailoutRate":1-ds/max(1,ga),"netTurnoverPoints":tp-dmg,"netTurnoverPointsPerGame":(tp-dmg)/games,"turnoverSequenceWpa":nw,"turnoverSequenceWpaPerGame":nw/games
        })
    return pd.DataFrame(out)


def main()->None:
    ap=argparse.ArgumentParser(); ap.add_argument("--start-season",type=int,default=2014); ap.add_argument("--end-season",type=int,default=2025)
    ap.add_argument("--history",type=Path,default=Path("data/gridiron-history-data.json")); ap.add_argument("--cache",type=Path,default=Path("model-lab/cache/pbp")); ap.add_argument("--out",type=Path,default=Path("model-lab/output")); args=ap.parse_args()
    args.out.mkdir(parents=True,exist_ok=True); all_seq=[]; diagnostics={}
    for season in range(args.start_season,args.end_season+1):
        pbp=load_pbp(season,args.cache); seq,d=extract(pbp); diagnostics[str(season)]=d
        if len(seq): all_seq.append(seq)
        print(f"{season}: {d['scrimmageTakeaways']} defensive scrimmage takeaways")
    seq=pd.concat(all_seq,ignore_index=True) if all_seq else pd.DataFrame(); seq.to_csv(args.out/"turnover_sequences.csv",index=False)
    hist=load_history(args.history); hist=hist[(hist["season"]>=args.start_season)&(hist["season"]<=args.end_season)].copy(); cp=checkpoints(seq,hist); cp.to_csv(args.out/"turnover_checkpoints.csv",index=False)
    summary={
        "model":"GRIDIRON PULSE v1.8 turnover impact/conversion lab","productionChanged":False,"seasons":[args.start_season,args.end_season],"sequenceCount":int(len(seq)),"checkpointRows":int(len(cp)),
        "directDefensiveTouchdowns":int(seq["directDefensiveTd"].sum()) if len(seq) else 0,"postTakeawayPossessions":int(seq["hasPostTakeawayPossession"].sum()) if len(seq) else 0,
        "meanPostTakeawayPoints":round(float(seq["postTakeawayPoints"].mean()),4) if len(seq) else 0,"postTakeawayScoreRate":round(float(seq["postTakeawayScored"].mean()),4) if len(seq) else 0,
        "postTakeawayTdRate":round(float(seq["postTakeawayTd"].mean()),4) if len(seq) else 0,"meanPostTakeawayEpa":round(float(seq["postTakeawayEpa"].mean()),4) if len(seq) else 0,
        "diagnostics":diagnostics,"nextStep":"Merge turnover_checkpoints.csv into the rolling no-lookahead historical comparable backtest. Do not promote to production before that test."
    }
    (args.out/"turnover_lab_summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8"); print(json.dumps(summary,indent=2))

if __name__=="__main__": main()
