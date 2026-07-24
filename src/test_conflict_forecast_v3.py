#!/usr/bin/env python3
"""
TEST - Conflict Forecast V3: NO SIGNAL threshold optimizer

Uses the V2-selected model families/configurations as the base:
  48h: full, K=10, stable threshold ±25%
  72h: mai_ddi, K=5, stable threshold ±10%

Purpose:
  Find a defensible abstention / NO SIGNAL threshold from historical
  walk-forward predictions instead of forcing a forecast every day.

Input:
  docs/conflict_analysis.json

Output:
  docs/conflict_forecast_v3_test.json

Important:
  This is an exploratory test. Threshold selection uses the historical
  backtest sample, so live out-of-sample tracking is still required.
"""

from __future__ import annotations
import json, math
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, pstdev
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
INPUT = REPO_ROOT / "docs" / "conflict_analysis.json"
OUTPUT = REPO_ROOT / "docs" / "conflict_forecast_v3_test.json"

MIN_TRAINING_ROWS = 18

CONFIGS = {
    "48h": {
        "days": 2,
        "stable_threshold_pct": 25.0,
        "k_neighbors": 10,
        "features": [
            "mai","mai_change_1d","mai_change_3d","mai_change_7d",
            "weighted_change_1d","ddi","ddi_change_1d","ddi_change_3d",
            "gap","gap_change_1d","military_pressure","military_event_count",
            "diplomatic_event_count","escalation_count",
            "deescalation_count","mixed_count",
        ],
    },
    "72h": {
        "days": 3,
        "stable_threshold_pct": 10.0,
        "k_neighbors": 5,
        "features": [
            "mai","mai_change_1d","mai_change_3d","mai_change_7d",
            "weighted_change_1d","ddi","ddi_change_1d","ddi_change_3d",
        ],
    },
}

CONFIDENCE_THRESHOLDS = [round(x / 100, 2) for x in range(50, 81, 2)]
PROBABILITY_THRESHOLDS = [round(x / 100, 2) for x in range(50, 81, 2)]
MIN_COVERAGE = 0.25
MIN_SIGNAL_SAMPLE = 12

LABELS = ("increase", "stable", "decrease")


def sf(v: Any, default=0.0):
    try:
        x=float(v)
        return x if math.isfinite(x) else default
    except (TypeError, ValueError):
        return default


def pct(a,b):
    return ((a-b)/b*100.0) if b else 0.0


def rmean(vals,end,w):
    if end < 0: return 0.0
    x=vals[max(0,end-w+1):end+1]
    return mean(x) if x else 0.0


def classify(change, threshold):
    if change > threshold: return "increase"
    if change < -threshold: return "decrease"
    return "stable"


def rows_from_daily(daily):
    weighted=[sf(r.get("military",{}).get("weighted_score")) for r in daily]
    mai=[sf(r.get("military",{}).get("activity_index")) for r in daily]
    ddi=[sf(r.get("diplomatic",{}).get("direction_index")) for r in daily]
    gap=[sf(r.get("gap",{}).get("divergence_score")) for r in daily]
    out=[]
    for i,r in enumerate(daily):
        m=r.get("military",{}); d=r.get("diplomatic",{})
        f={
            "mai":mai[i],
            "mai_change_1d":mai[i]-mai[i-1] if i else 0,
            "mai_change_3d":mai[i]-rmean(mai,i-1,3) if i else 0,
            "mai_change_7d":mai[i]-rmean(mai,i-1,7) if i else 0,
            "weighted_change_1d":pct(weighted[i],weighted[i-1]) if i else 0,
            "ddi":ddi[i],
            "ddi_change_1d":ddi[i]-ddi[i-1] if i else 0,
            "ddi_change_3d":ddi[i]-rmean(ddi,i-1,3) if i else 0,
            "gap":gap[i],
            "gap_change_1d":gap[i]-gap[i-1] if i else 0,
            "military_pressure":sf(m.get("pressure_score")),
            "military_event_count":sf(m.get("event_count")),
            "diplomatic_event_count":sf(d.get("event_count")),
            "escalation_count":sf(d.get("escalation_count")),
            "deescalation_count":sf(d.get("deescalation_count")),
            "mixed_count":sf(d.get("mixed_count")),
        }
        out.append({"date":r.get("date"),"weighted_activity":weighted[i],"features":f})
    return out


def add_targets(rows, days, threshold):
    for i,r in enumerate(rows):
        j=i+days
        if j>=len(rows):
            r["target"]=None
        else:
            ch=pct(sf(rows[j]["weighted_activity"]),sf(r["weighted_activity"]))
            r["target"]={"direction":classify(ch,threshold),"change_pct":round(ch,1),"future_date":rows[j]["date"]}


def feature_stats(training, features):
    s={}
    for f in features:
        vals=[sf(r["features"].get(f)) for r in training]
        mu=mean(vals) if vals else 0
        sd=pstdev(vals) if len(vals)>1 else 1
        s[f]=(mu,sd if sd>1e-9 else 1)
    return s


def dist(a,b,s,features):
    return math.sqrt(sum(((sf(a["features"].get(f))-sf(b["features"].get(f)))/s[f][1])**2 for f in features)/len(features))


def predict(current, training, features, k):
    eligible=[r for r in training if r.get("target") is not None]
    if len(eligible)<MIN_TRAINING_ROWS: return None
    s=feature_stats(eligible,features)
    ranked=sorted(((dist(current,r,s,features),r) for r in eligible),key=lambda x:x[0])[:min(k,len(eligible))]
    votes={x:0.0 for x in LABELS}
    for d,r in ranked:
        votes[r["target"]["direction"]]+=1/(0.35+d)
    total=sum(votes.values())
    probs={x:v/total for x,v in votes.items()}
    pred=max(probs,key=probs.get)
    sp=sorted(probs.values(),reverse=True)
    margin=sp[0]-sp[1]
    avgd=mean(d for d,_ in ranked)
    similarity=1/(1+avgd)
    conf=max(0,min(1,probs[pred]*0.65+margin*0.20+similarity*0.15))
    return {
        "direction":pred,
        "top_probability":round(probs[pred],4),
        "confidence_score":round(conf,4),
        "probabilities":{x:round(v,4) for x,v in probs.items()},
        "nearest_analogues":[
            {"date":r["date"],"distance":round(d,3),"observed_direction":r["target"]["direction"]}
            for d,r in ranked
        ],
    }


def walkforward(rows, cfg):
    preds=[]
    days=cfg["days"]
    for i,current in enumerate(rows):
        cutoff=i-days
        if cutoff<=0 or current.get("target") is None: continue
        training=rows[:cutoff+1]
        p=predict(current,training,cfg["features"],cfg["k_neighbors"])
        if p:
            preds.append({
                "date":current["date"],
                "predicted":p["direction"],
                "actual":current["target"]["direction"],
                "correct":p["direction"]==current["target"]["direction"],
                "confidence_score":p["confidence_score"],
                "top_probability":p["top_probability"],
            })
    return preds


def threshold_eval(preds, cthr, pthr):
    signaled=[p for p in preds if p["confidence_score"]>=cthr and p["top_probability"]>=pthr]
    n=len(preds); sn=len(signaled)
    correct=sum(p["correct"] for p in signaled)
    accuracy=correct/sn if sn else None
    coverage=sn/n if n else 0
    # utility rewards accuracy but prevents trivial tiny-coverage solutions
    utility=(accuracy or 0)*(coverage**0.35)
    return {
        "confidence_threshold":cthr,
        "probability_threshold":pthr,
        "signal_sample":sn,
        "total_sample":n,
        "coverage_pct":round(coverage*100,1),
        "signal_accuracy_pct":round(accuracy*100,1) if accuracy is not None else None,
        "no_signal_sample":n-sn,
        "utility_score":round(utility,4),
    }


def select_threshold(preds):
    tests=[]
    for c in CONFIDENCE_THRESHOLDS:
        for p in PROBABILITY_THRESHOLDS:
            e=threshold_eval(preds,c,p)
            tests.append(e)
    eligible=[
        e for e in tests
        if e["signal_sample"]>=MIN_SIGNAL_SAMPLE
        and e["coverage_pct"]>=MIN_COVERAGE*100
    ]
    if not eligible:
        eligible=[e for e in tests if e["signal_sample"]>=8]
    eligible.sort(key=lambda e:(e["utility_score"],e["signal_accuracy_pct"] or 0,e["coverage_pct"]),reverse=True)
    return eligible[0] if eligible else None, tests


def main():
    source=json.loads(INPUT.read_text(encoding="utf-8"))
    daily=source.get("daily",[])
    if len(daily)<25: raise SystemExit("Not enough daily observations.")
    base=rows_from_daily(daily)
    horizons={}

    for horizon,cfg in CONFIGS.items():
        rows=json.loads(json.dumps(base))
        add_targets(rows,cfg["days"],cfg["stable_threshold_pct"])
        preds=walkforward(rows,cfg)
        selected,tests=select_threshold(preds)

        training=rows[:-cfg["days"]]
        latest=predict(rows[-1],training,cfg["features"],cfg["k_neighbors"])
        if latest and selected:
            signal=(
                latest["confidence_score"]>=selected["confidence_threshold"]
                and latest["top_probability"]>=selected["probability_threshold"]
            )
            public_direction=latest["direction"] if signal else "no_signal"
        else:
            signal=False
            public_direction="no_signal"

        horizons[horizon]={
            "configuration":cfg,
            "backtest_sample":len(preds),
            "selected_no_signal_rule":selected,
            "latest_raw_prediction":latest,
            "latest_public_signal":{
                "direction":public_direction,
                "has_signal":signal,
                "label_hu":{
                    "increase":"növekvő katonai aktivitás",
                    "decrease":"csökkenő katonai aktivitás",
                    "stable":"lényegében változatlan katonai aktivitás",
                    "no_signal":"nincs egyértelmű jelzés",
                }[public_direction],
            },
            "threshold_tests":tests,
        }

    out={
        "generated_at":datetime.now(timezone.utc).isoformat(),
        "test_version":"conflict_forecast_v3_no_signal_test",
        "status":"TEST_ONLY",
        "source_analysis_period":source.get("analysis_period"),
        "method":{
            "focus":["48h","72h"],
            "24h":"excluded from main forecast because historical performance was insufficient",
            "threshold_selection":"confidence + top-class probability grid search",
            "minimum_signal_sample":MIN_SIGNAL_SAMPLE,
            "minimum_coverage_pct":MIN_COVERAGE*100,
            "warning":"Thresholds are selected on historical backtest data and require live out-of-sample validation.",
        },
        "horizons":horizons,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(out, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("TEST Conflict Forecast V3 complete")
    for h,x in horizons.items():
        rule=x["selected_no_signal_rule"]
        latest=x["latest_public_signal"]
        print(
            h,
            "| rule:",rule,
            "| latest:",latest["label_hu"],
            "| raw:",x["latest_raw_prediction"]["direction"] if x["latest_raw_prediction"] else None,
            "| confidence:",x["latest_raw_prediction"]["confidence_score"] if x["latest_raw_prediction"] else None,
        )
    print("Output:",OUTPUT)


if __name__=="__main__":
    main()
