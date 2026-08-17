#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, math
from pathlib import Path
from typing import Dict, List, Mapping, Tuple
import numpy as np
import pandas as pd
from v18_turnover_features import load_history, build_turnover_checkpoints, add_schedule_features

COMPS=40
CHECKPOINTS=(4,8,12)
BASE_WEIGHTS={
    "winPct":1.30,"margin":1.25,"ppg":0.80,"papg":0.80,"pythWinPct":1.20,"winLuck":1.00,
    "closeGamePct":0.50,"closeWinPct":0.60,"blowoutWinPct":0.50,"last3Margin":0.90,"momentum":0.40,
    "offConsistency":0.30,"defConsistency":0.30,"offensePulse":0.80,"defensePulse":0.80,"tandemPulse":1.10,
    "oppQuality":0.35,"scheduleStrength":0.25,"scheduleAdjustedMargin":0.35,"qbContinuity":0.50,"coachContinuity":0.15,
}
VARIANTS={
    "baseline":{},
    "turnover_margin":{"turnoverMarginPerGame":0.40},
    "conversion":{"postTakeawayScoreRate":0.16,"postTakeawayTdRate":0.16,"postTakeawayEpaPerDrive":0.22,"postTakeawayPointsAboveExpected":0.18},
    "giveaway_damage":{"giveawayDamagePointsPerGiveaway":0.26,"defenseBailoutRate":0.20},
    "net_turnover_value":{"netTurnoverPointsPerGame":0.45},
    "turnover_wpa":{"turnoverSequenceWpaPerGame":0.35},
    "compact_turnover":{"netTurnoverPointsPerGame":0.30,"postTakeawayEpaPerDrive":0.16,"defenseBailoutRate":0.12},
    "full_turnover":{"turnoverMarginPerGame":0.18,"postTakeawayScoreRate":0.10,"postTakeawayTdRate":0.10,"postTakeawayEpaPerDrive":0.14,"postTakeawayPointsAboveExpected":0.10,"giveawayDamagePointsPerGiveaway":0.12,"defenseBailoutRate":0.10,"netTurnoverPointsPerGame":0.22,"turnoverSequenceWpaPerGame":0.16},
}
NEUTRALIZED={"turnover_neutralized_margin","neutralized_plus_compact"}

def variant_weights(name:str)->Dict[str,float]:
    w=dict(BASE_WEIGHTS)
    if name in NEUTRALIZED:
        w.pop("margin",None); w.pop("scheduleAdjustedMargin",None)
        w["turnoverNeutralMargin"]=BASE_WEIGHTS["margin"]
        w["turnoverNeutralScheduleAdjustedMargin"]=BASE_WEIGHTS["scheduleAdjustedMargin"]
        if name=="neutralized_plus_compact": w.update(VARIANTS["compact_turnover"])
    else:
        w.update(VARIANTS[name])
    return w

def predict_one(target:pd.Series, train:pd.DataFrame, weights:Mapping[str,float])->float:
    features=[f for f in weights if f in train.columns and f in target.index]
    if not features: return float(train["finalWinsEq17"].mean())
    x=train[features].apply(pd.to_numeric,errors="coerce").copy()
    tv=pd.to_numeric(target[features],errors="coerce")
    means=x.mean(axis=0); scales=x.std(axis=0,ddof=0).replace(0,np.nan).fillna(1.0)
    x=x.fillna(means).fillna(0.0); tv=tv.fillna(means).fillna(0.0)
    dist2=np.zeros(len(x),dtype=float)
    for f in features:
        z=(x[f].to_numpy(dtype=float)-float(tv[f]))/max(1e-6,float(scales[f]))
        dist2+=float(weights[f])*z*z
    distance=np.sqrt(dist2); n=min(COMPS,len(distance))
    if n<=0: return np.nan
    idx=np.argpartition(distance,n-1)[:n]; d=distance[idx]; dmin=float(d.min())
    ww=np.exp(-(d-dmin)/2.0)
    y=pd.to_numeric(train.iloc[idx]["finalWinsEq17"],errors="coerce").to_numpy(dtype=float)
    ok=np.isfinite(y)&np.isfinite(ww)
    if not ok.any() or ww[ok].sum()<=0: return float(np.nanmean(y))
    return float(np.dot(y[ok],ww[ok])/ww[ok].sum())

def rolling_backtest(df:pd.DataFrame,test_start:int,test_end:int)->pd.DataFrame:
    variants=list(VARIANTS)+sorted(NEUTRALIZED)
    targets=df[df["season"].between(test_start,test_end)&df["week"].isin(CHECKPOINTS)&pd.to_numeric(df["finalWinsEq17"],errors="coerce").notna()].copy()
    targets=targets.sort_values(["season","week","team","games"]).drop_duplicates(["season","week","team"],keep="last")
    rec=[]
    for season in range(test_start,test_end+1):
        st=targets[targets["season"]==season]
        if st.empty: continue
        prior=df[df["season"]<season]
        for _,t in st.iterrows():
            g=int(t["games"])
            train=prior[(prior["games"]>=max(1,g-1))&(prior["games"]<=min(17,g+1))].copy()
            if len(train)<80: continue
            actual=float(t["finalWinsEq17"])
            for v in variants:
                pred=predict_one(t,train,variant_weights(v))
                if math.isfinite(pred):
                    rec.append({"season":int(t["season"]),"week":int(t["week"]),"games":g,"team":t["team"],"variant":v,"prediction":pred,"actualFinalWinsEq17":actual,"absError":abs(pred-actual)})
    return pd.DataFrame(rec)

def summarize(results:pd.DataFrame)->Tuple[pd.DataFrame,pd.DataFrame,dict]:
    overall=results.groupby("variant",as_index=False).agg(mae=("absError","mean"),n=("absError","size"))
    weeks=results.groupby(["variant","week"],as_index=False).agg(mae=("absError","mean"),n=("absError","size"))
    recent_results=results[results["season"]>=2022]
    recent=recent_results.groupby("variant",as_index=False).agg(recentMae=("absError","mean"),recentN=("absError","size"))
    recent_weeks=recent_results.groupby(["variant","week"],as_index=False).agg(recentMae=("absError","mean"),recentN=("absError","size"))
    table=overall.merge(recent,on="variant",how="left")
    base=float(table.loc[table.variant.eq("baseline"),"mae"].iloc[0])
    rb=table.loc[table.variant.eq("baseline"),"recentMae"].dropna(); recent_base=float(rb.iloc[0]) if len(rb) else float("nan")
    table["deltaVsBaseline"]=table["mae"]-base
    table["recentDeltaVsBaseline"]=table["recentMae"]-recent_base if math.isfinite(recent_base) else np.nan
    ps=results.groupby(["variant","season"],as_index=False).agg(mae=("absError","mean"),n=("absError","size"))
    bb=ps[ps.variant.eq("baseline")][["season","mae"]].rename(columns={"mae":"baselineMae"})
    ps=ps.merge(bb,on="season",how="left"); ps["deltaVsBaseline"]=ps["mae"]-ps["baselineMae"]
    wc=ps[~ps.variant.eq("baseline")].groupby("variant").agg(seasonsBetter=("deltaVsBaseline",lambda s:int((s<0).sum())),seasonsWorse=("deltaVsBaseline",lambda s:int((s>0).sum())),medianSeasonDelta=("deltaVsBaseline","median")).reset_index()
    table=table.merge(wc,on="variant",how="left").sort_values(["mae","variant"]).reset_index(drop=True)
    best=table.iloc[0]
    summary={
        "testType":"rolling no-lookahead historical-comparable signal screen",
        "scope":"Screens incremental turnover signal in the historical-comparable layer; not the exact deployed Season Worker + History Worker blend.",
        "noLookahead":"Each held-out season uses only prior seasons; imputation and scaling come only from prior-season training rows.",
        "checkpoints":[4,8,12],"comparables":COMPS,
        "conversionDenominator":"Actual post-takeaway offensive possessions; direct defensive touchdowns are excluded from offensive conversion rates.",
        "baselineMae":round(base,6),"recentBaselineMae":round(recent_base,6) if math.isfinite(recent_base) else None,
        "bestVariant":str(best["variant"]),"bestMae":round(float(best["mae"]),6),"bestDeltaVsBaseline":round(float(best["deltaVsBaseline"]),6),
        "promotionRule":"Prefer lower overall MAE, non-worse recent MAE, and improvement across a majority of held-out seasons/checkpoints before production promotion."
    }
    return table,ps,{"summary":summary,"weeks":weeks.to_dict("records"),"recentWeeks":recent_weeks.to_dict("records")}

def main()->None:
    ap=argparse.ArgumentParser(); ap.add_argument("--history",type=Path,required=True); ap.add_argument("--sequences",type=Path,required=True)
    ap.add_argument("--test-start",type=int,default=2014); ap.add_argument("--test-end",type=int,default=2025); ap.add_argument("--out",type=Path,default=Path("model-lab/output")); a=ap.parse_args()
    a.out.mkdir(parents=True,exist_ok=True)
    history=load_history(a.history); seq=pd.read_csv(a.sequences,low_memory=False)
    turnover=build_turnover_checkpoints(history,seq)
    merged=history.merge(turnover,on=["season","week","games","team"],how="left",validate="one_to_one")
    merged=add_schedule_features(merged)
    pbp_start=int(pd.to_numeric(seq["season"],errors="coerce").min()); merged=merged[merged["season"]>=pbp_start].copy()
    results=rolling_backtest(merged,a.test_start,a.test_end)
    if results.empty: raise RuntimeError("backtest generated no predictions")
    ranking,per_season,detail=summarize(results)
    results.to_csv(a.out/"turnover_backtest_predictions.csv",index=False)
    ranking.to_csv(a.out/"turnover_backtest_ranking.csv",index=False)
    per_season.to_csv(a.out/"turnover_backtest_by_season.csv",index=False)
    payload={**detail,"dataStartSeason":pbp_start,"testStartSeason":a.test_start,"testEndSeason":a.test_end,"predictionRows":int(len(results)),"ranking":json.loads(ranking.to_json(orient="records"))}
    (a.out/"turnover_backtest_summary.json").write_text(json.dumps(payload,indent=2),encoding="utf-8")
    print("\nGRIDIRON PULSE v1.8 TURNOVER SIGNAL SCREEN")
    print(ranking.to_string(index=False,float_format=lambda x:f"{x:.6f}"))
    print("\nWEEKLY MAE")
    print(pd.DataFrame(detail["weeks"]).pivot(index="variant",columns="week",values="mae").sort_values(4).to_string(float_format=lambda x:f"{x:.6f}"))
    print("\nRECENT (2022-2025) WEEKLY MAE")
    rw=pd.DataFrame(detail["recentWeeks"])
    print(rw.pivot(index="variant",columns="week",values="recentMae").sort_values(4).to_string(float_format=lambda x:f"{x:.6f}")) if len(rw) else print("No 2022+ rows")
    print("\nSUMMARY")
    print(json.dumps(payload["summary"],indent=2))

if __name__=="__main__": main()
