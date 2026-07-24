#!/usr/bin/env python3
"""
Conflict Forecast Model Optimizer V2

Purpose
-------
Searches for a more robust short-term directional forecast model using
strict walk-forward backtesting.

Input
-----
docs/conflict_analysis.json

Output
------
docs/conflict_forecast_optimization.json

The optimizer tests:
- stable thresholds: 10 / 15 / 20 / 25 percent
- historical analogue counts K: 5 / 7 / 10 / 15
- several feature sets
- 24h / 48h / 72h horizons separately

Selection is NOT based on raw accuracy alone. It prioritizes:
1. balanced accuracy
2. improvement over a persistence baseline
3. ordinary accuracy
4. minimum sample/class coverage

No future information is allowed into historical training sets.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, pstdev
from typing import Any

INPUT = Path("docs/conflict_analysis.json")
OUTPUT = Path("docs/conflict_forecast_optimization.json")

HORIZONS = {"24h": 1, "48h": 2, "72h": 3}
STABLE_THRESHOLDS = [10.0, 15.0, 20.0, 25.0]
K_VALUES = [5, 7, 10, 15]
MIN_TRAINING_ROWS = 18

FEATURE_SETS = {
    "mai_only": [
        "mai",
        "mai_change_1d",
        "mai_change_3d",
        "mai_change_7d",
    ],
    "military_trend": [
        "mai",
        "mai_change_1d",
        "mai_change_3d",
        "mai_change_7d",
        "weighted_change_1d",
        "military_pressure",
        "military_event_count",
    ],
    "mai_ddi": [
        "mai",
        "mai_change_1d",
        "mai_change_3d",
        "mai_change_7d",
        "weighted_change_1d",
        "ddi",
        "ddi_change_1d",
        "ddi_change_3d",
    ],
    "mai_ddi_gap": [
        "mai",
        "mai_change_1d",
        "mai_change_3d",
        "mai_change_7d",
        "weighted_change_1d",
        "ddi",
        "ddi_change_1d",
        "ddi_change_3d",
        "gap",
        "gap_change_1d",
    ],
    "full": [
        "mai",
        "mai_change_1d",
        "mai_change_3d",
        "mai_change_7d",
        "weighted_change_1d",
        "ddi",
        "ddi_change_1d",
        "ddi_change_3d",
        "gap",
        "gap_change_1d",
        "military_pressure",
        "military_event_count",
        "diplomatic_event_count",
        "escalation_count",
        "deescalation_count",
        "mixed_count",
    ],
}

LABELS = ("increase", "stable", "decrease")


def safe_float(v: Any, default: float = 0.0) -> float:
    try:
        n = float(v)
        return n if math.isfinite(n) else default
    except (TypeError, ValueError):
        return default


def pct_change(current: float, baseline: float) -> float:
    if baseline == 0:
        return 0.0
    return ((current - baseline) / baseline) * 100.0


def rolling_mean(values: list[float], end: int, window: int) -> float:
    if end < 0:
        return 0.0
    start = max(0, end - window + 1)
    vals = values[start:end + 1]
    return mean(vals) if vals else 0.0


def classify(change_pct: float, threshold: float) -> str:
    if change_pct > threshold:
        return "increase"
    if change_pct < -threshold:
        return "decrease"
    return "stable"


def extract_rows(daily: list[dict[str, Any]]) -> list[dict[str, Any]]:
    weighted = [
        safe_float(r.get("military", {}).get("weighted_score")) for r in daily
    ]
    mai = [
        safe_float(r.get("military", {}).get("activity_index")) for r in daily
    ]
    ddi = [
        safe_float(r.get("diplomatic", {}).get("direction_index")) for r in daily
    ]
    gap = [
        safe_float(r.get("gap", {}).get("divergence_score")) for r in daily
    ]

    rows = []
    for i, r in enumerate(daily):
        m = r.get("military", {})
        d = r.get("diplomatic", {})

        features = {
            "mai": mai[i],
            "mai_change_1d": mai[i] - mai[i - 1] if i else 0.0,
            "mai_change_3d": mai[i] - rolling_mean(mai, i - 1, 3) if i else 0.0,
            "mai_change_7d": mai[i] - rolling_mean(mai, i - 1, 7) if i else 0.0,
            "weighted_change_1d": pct_change(weighted[i], weighted[i - 1]) if i else 0.0,
            "ddi": ddi[i],
            "ddi_change_1d": ddi[i] - ddi[i - 1] if i else 0.0,
            "ddi_change_3d": ddi[i] - rolling_mean(ddi, i - 1, 3) if i else 0.0,
            "gap": gap[i],
            "gap_change_1d": gap[i] - gap[i - 1] if i else 0.0,
            "military_pressure": safe_float(m.get("pressure_score")),
            "military_event_count": safe_float(m.get("event_count")),
            "diplomatic_event_count": safe_float(d.get("event_count")),
            "escalation_count": safe_float(d.get("escalation_count")),
            "deescalation_count": safe_float(d.get("deescalation_count")),
            "mixed_count": safe_float(d.get("mixed_count")),
        }

        rows.append({
            "date": r.get("date"),
            "weighted_activity": weighted[i],
            "features": features,
        })
    return rows


def add_targets(rows: list[dict[str, Any]], threshold: float) -> None:
    for i, row in enumerate(rows):
        row["targets"] = {}
        now = safe_float(row["weighted_activity"])
        for horizon, days in HORIZONS.items():
            j = i + days
            if j >= len(rows):
                row["targets"][horizon] = None
                continue
            future = safe_float(rows[j]["weighted_activity"])
            change = pct_change(future, now)
            row["targets"][horizon] = {
                "direction": classify(change, threshold),
                "change_pct": change,
                "future_date": rows[j]["date"],
            }


def stats(training: list[dict[str, Any]], features: list[str]):
    result = {}
    for f in features:
        vals = [safe_float(r["features"].get(f)) for r in training]
        mu = mean(vals) if vals else 0.0
        sd = pstdev(vals) if len(vals) > 1 else 1.0
        result[f] = (mu, sd if sd > 1e-9 else 1.0)
    return result


def distance(a, b, feature_stats, features):
    total = 0.0
    for f in features:
        _, sd = feature_stats[f]
        z = (
            safe_float(a["features"].get(f))
            - safe_float(b["features"].get(f))
        ) / sd
        total += z * z
    return math.sqrt(total / max(1, len(features)))


def predict(current, training, horizon, features, k):
    eligible = [
        r for r in training
        if r.get("targets", {}).get(horizon) is not None
    ]
    if len(eligible) < MIN_TRAINING_ROWS:
        return None

    fs = stats(eligible, features)
    ranked = sorted(
        [(distance(current, r, fs, features), r) for r in eligible],
        key=lambda x: x[0],
    )[:min(k, len(eligible))]

    votes = {label: 0.0 for label in LABELS}
    weighted_changes = []
    neighbours = []

    for dist, row in ranked:
        target = row["targets"][horizon]
        weight = 1.0 / (0.35 + dist)
        votes[target["direction"]] += weight
        weighted_changes.append((target["change_pct"], weight))
        neighbours.append({
            "date": row["date"],
            "distance": round(dist, 3),
            "direction": target["direction"],
            "change_pct": round(target["change_pct"], 1),
        })

    total = sum(votes.values())
    probs = {k_: votes[k_] / total for k_ in votes}
    pred = max(probs, key=probs.get)

    sorted_probs = sorted(probs.values(), reverse=True)
    margin = sorted_probs[0] - sorted_probs[1]
    avg_dist = mean(d for d, _ in ranked)
    similarity = 1.0 / (1.0 + avg_dist)

    confidence = max(
        0.0,
        min(1.0, probs[pred] * 0.65 + margin * 0.20 + similarity * 0.15),
    )

    est = (
        sum(c * w for c, w in weighted_changes)
        / sum(w for _, w in weighted_changes)
    )

    return {
        "direction": pred,
        "probabilities": {x: round(y, 3) for x, y in probs.items()},
        "confidence_score": round(confidence, 3),
        "estimated_change_pct": round(est, 1),
        "neighbours": neighbours,
    }


def confusion_metrics(predictions):
    total = len(predictions)
    correct = sum(p["predicted"] == p["actual"] for p in predictions)
    accuracy = correct / total if total else None

    recalls = []
    class_metrics = {}

    for label in LABELS:
        actuals = [p for p in predictions if p["actual"] == label]
        preds = [p for p in predictions if p["predicted"] == label]
        tp = sum(
            p["actual"] == label and p["predicted"] == label
            for p in predictions
        )
        recall = tp / len(actuals) if actuals else None
        precision = tp / len(preds) if preds else None

        if recall is not None:
            recalls.append(recall)

        class_metrics[label] = {
            "support": len(actuals),
            "precision": round(precision, 3) if precision is not None else None,
            "recall": round(recall, 3) if recall is not None else None,
        }

    balanced = mean(recalls) if recalls else None

    return {
        "sample_size": total,
        "accuracy_pct": round(accuracy * 100, 1) if accuracy is not None else None,
        "balanced_accuracy_pct": (
            round(balanced * 100, 1) if balanced is not None else None
        ),
        "class_metrics": class_metrics,
    }


def walk_forward(rows, horizon, features, k):
    days = HORIZONS[horizon]
    predictions = []

    for i, current in enumerate(rows):
        cutoff = i - days
        if cutoff <= 0:
            continue

        # Critical anti-leakage rule:
        # target outcome for every training row must already be observable.
        training = rows[:cutoff + 1]
        actual = current["targets"].get(horizon)

        if actual is None:
            continue

        result = predict(current, training, horizon, features, k)
        if result is None:
            continue

        predictions.append({
            "date": current["date"],
            "predicted": result["direction"],
            "actual": actual["direction"],
            "confidence_score": result["confidence_score"],
        })

    return predictions


def persistence_baseline(rows, horizon, threshold):
    days = HORIZONS[horizon]
    predictions = []

    for i in range(1, len(rows) - days):
        today = safe_float(rows[i]["weighted_activity"])
        prev = safe_float(rows[i - 1]["weighted_activity"])
        predicted = classify(pct_change(today, prev), threshold)
        actual = rows[i]["targets"][horizon]
        if actual is None:
            continue
        predictions.append({
            "predicted": predicted,
            "actual": actual["direction"],
        })

    return confusion_metrics(predictions)


def score_candidate(metrics, baseline):
    """
    Robust selection score:
    balanced accuracy matters most, then baseline improvement,
    then raw accuracy. A small penalty is applied if any class is absent.
    """
    bal = metrics.get("balanced_accuracy_pct") or 0.0
    acc = metrics.get("accuracy_pct") or 0.0
    base = baseline.get("accuracy_pct") or 0.0
    improvement = acc - base

    supports = [
        metrics["class_metrics"][label]["support"] for label in LABELS
    ]
    class_penalty = 8.0 if min(supports) == 0 else 0.0

    return round(
        bal * 0.55
        + max(-25.0, improvement) * 0.30
        + acc * 0.15
        - class_penalty,
        3,
    )


def confidence_metrics(predictions):
    result = {}
    for threshold, name in [(0.56, "medium_plus"), (0.72, "high")]:
        subset = [
            p for p in predictions
            if p["confidence_score"] >= threshold
        ]
        if not subset:
            result[name] = {
                "sample_size": 0,
                "accuracy_pct": None,
            }
            continue
        acc = sum(p["predicted"] == p["actual"] for p in subset) / len(subset)
        result[name] = {
            "sample_size": len(subset),
            "accuracy_pct": round(acc * 100, 1),
        }
    return result


def main():
    with INPUT.open("r", encoding="utf-8") as f:
        source = json.load(f)

    daily = source.get("daily", [])
    if len(daily) < 25:
        raise ValueError("At least 25 complete daily rows are required.")

    base_rows = extract_rows(daily)

    candidates = []
    winners = {}

    for threshold in STABLE_THRESHOLDS:
        # targets depend on threshold, so use a clean copy
        rows = json.loads(json.dumps(base_rows))
        add_targets(rows, threshold)

        baselines = {
            horizon: persistence_baseline(rows, horizon, threshold)
            for horizon in HORIZONS
        }

        for feature_name, features in FEATURE_SETS.items():
            for k in K_VALUES:
                for horizon in HORIZONS:
                    preds = walk_forward(rows, horizon, features, k)
                    metrics = confusion_metrics(preds)
                    conf = confidence_metrics(preds)
                    baseline = baselines[horizon]
                    selection_score = score_candidate(metrics, baseline)

                    candidate = {
                        "horizon": horizon,
                        "stable_threshold_pct": threshold,
                        "k_neighbors": k,
                        "feature_set": feature_name,
                        "features": features,
                        "selection_score": selection_score,
                        "metrics": metrics,
                        "confidence_metrics": conf,
                        "baseline": baseline,
                        "baseline_improvement_pp": (
                            round(
                                (metrics["accuracy_pct"] or 0)
                                - (baseline["accuracy_pct"] or 0),
                                1,
                            )
                        ),
                    }
                    candidates.append(candidate)

    for horizon in HORIZONS:
        horizon_candidates = [
            c for c in candidates
            if c["horizon"] == horizon
            and c["metrics"]["sample_size"] >= 30
        ]

        horizon_candidates.sort(
            key=lambda c: (
                c["selection_score"],
                c["metrics"]["balanced_accuracy_pct"] or 0,
                c["baseline_improvement_pp"],
                c["metrics"]["accuracy_pct"] or 0,
            ),
            reverse=True,
        )

        winners[horizon] = horizon_candidates[0] if horizon_candidates else None

    # Feature-ablation summary: best result for each feature family/horizon.
    ablation = {}
    for horizon in HORIZONS:
        ablation[horizon] = {}
        for feature_name in FEATURE_SETS:
            subset = [
                c for c in candidates
                if c["horizon"] == horizon
                and c["feature_set"] == feature_name
                and c["metrics"]["sample_size"] >= 30
            ]
            subset.sort(key=lambda c: c["selection_score"], reverse=True)
            if subset:
                best = subset[0]
                ablation[horizon][feature_name] = {
                    "stable_threshold_pct": best["stable_threshold_pct"],
                    "k_neighbors": best["k_neighbors"],
                    "accuracy_pct": best["metrics"]["accuracy_pct"],
                    "balanced_accuracy_pct": best["metrics"]["balanced_accuracy_pct"],
                    "baseline_improvement_pp": best["baseline_improvement_pp"],
                    "selection_score": best["selection_score"],
                }

    # Generate latest forecasts with each horizon's winning configuration.
    latest = {}
    for horizon, winner in winners.items():
        if not winner:
            latest[horizon] = None
            continue

        threshold = winner["stable_threshold_pct"]
        rows = json.loads(json.dumps(base_rows))
        add_targets(rows, threshold)

        days = HORIZONS[horizon]
        training = rows[:-days]
        current = rows[-1]

        forecast = predict(
            current,
            training,
            horizon,
            winner["features"],
            winner["k_neighbors"],
        )

        latest[horizon] = {
            "forecast_date": current["date"],
            "direction": forecast["direction"] if forecast else None,
            "confidence_score": forecast["confidence_score"] if forecast else None,
            "probabilities": forecast["probabilities"] if forecast else None,
            # Kept for diagnostics only; do not present as a precise public forecast.
            "diagnostic_estimated_change_pct": (
                forecast["estimated_change_pct"] if forecast else None
            ),
            "nearest_analogues": forecast["neighbours"] if forecast else [],
            "model_configuration": {
                "stable_threshold_pct": threshold,
                "k_neighbors": winner["k_neighbors"],
                "feature_set": winner["feature_set"],
            },
            "validated_accuracy_pct": winner["metrics"]["accuracy_pct"],
            "validated_balanced_accuracy_pct": (
                winner["metrics"]["balanced_accuracy_pct"]
            ),
            "baseline_improvement_pp": winner["baseline_improvement_pp"],
        }

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "optimizer_version": "conflict_forecast_optimizer_v2",
        "source_analysis_period": source.get("analysis_period"),
        "tested_grid": {
            "stable_thresholds_pct": STABLE_THRESHOLDS,
            "k_neighbors": K_VALUES,
            "feature_sets": list(FEATURE_SETS.keys()),
            "horizons": list(HORIZONS.keys()),
            "candidate_count": len(candidates),
        },
        "selection_method": {
            "primary_metric": "balanced accuracy",
            "secondary_metric": "improvement over persistence baseline",
            "note": (
                "Configuration selection is performed on the same historical "
                "walk-forward sample and therefore remains exploratory. "
                "Live out-of-sample tracking is still required."
            ),
        },
        "winning_models": winners,
        "feature_ablation": ablation,
        "latest_forecast": latest,
        "all_candidates": sorted(
            candidates,
            key=lambda c: (
                c["horizon"],
                -c["selection_score"],
            ),
        ),
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUTPUT.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    tmp.replace(OUTPUT)

    print("Conflict Forecast Optimizer V2 complete")
    print("Daily rows:", len(daily))
    print("Candidates:", len(candidates))

    for horizon, winner in winners.items():
        if not winner:
            print(horizon, "NO WINNER")
            continue
        print(
            horizon,
            "| feature:", winner["feature_set"],
            "| threshold:", winner["stable_threshold_pct"],
            "| K:", winner["k_neighbors"],
            "| accuracy:", winner["metrics"]["accuracy_pct"],
            "| balanced:", winner["metrics"]["balanced_accuracy_pct"],
            "| baseline:", winner["baseline"]["accuracy_pct"],
            "| improvement:", winner["baseline_improvement_pp"],
        )

    print("Output:", OUTPUT)


if __name__ == "__main__":
    main()
