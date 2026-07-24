#!/usr/bin/env python3
"""
Conflict End Matrix - short-term forecast + walk-forward backtest V1

Input:
  docs/conflict_analysis.json

Output:
  docs/conflict_forecast.json

Goal:
  Estimate the likely direction of military activity over the next
  24h / 48h / 72h as:
      increase / stable / decrease

Method:
  - transparent nearest-historical-analogue model
  - walk-forward backtest
  - NO future information is used when producing historical predictions
  - confidence is based on neighbour agreement and similarity
  - forecast is directional, not a prediction of a specific attack

Important:
  The model estimates short-term military activity direction only.
  It does not predict exact targets, locations or individual attacks.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, pstdev
from typing import Any


INPUT = Path("docs/conflict_analysis.json")
OUTPUT = Path("docs/conflict_forecast.json")

HORIZONS = {
    "24h": 1,
    "48h": 2,
    "72h": 3,
}

# Change in weighted military activity needed to classify a move.
# A neutral band avoids treating small day-to-day noise as a forecast hit/miss.
STABLE_THRESHOLD_PCT = 15.0

# Historical analogues used for each prediction.
K_NEIGHBORS = 7

# Minimum historical training observations needed before a backtest prediction.
MIN_TRAINING_ROWS = 18

FEATURES = [
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
]


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Missing required input: {path}")
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("Input JSON must contain an object.")
    return data


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        n = float(value)
        return n if math.isfinite(n) else default
    except (TypeError, ValueError):
        return default


def pct_change(current: float, baseline: float) -> float:
    if baseline == 0:
        return 0.0
    return ((current - baseline) / baseline) * 100.0


def rolling_mean(values: list[float], end_index: int, window: int) -> float:
    start = max(0, end_index - window + 1)
    slice_ = values[start:end_index + 1]
    return mean(slice_) if slice_ else 0.0


def classify_change(change_pct: float) -> str:
    if change_pct > STABLE_THRESHOLD_PCT:
        return "increase"
    if change_pct < -STABLE_THRESHOLD_PCT:
        return "decrease"
    return "stable"


def hu_label(label: str) -> str:
    return {
        "increase": "növekedés",
        "stable": "lényegében változatlan",
        "decrease": "csökkenés",
    }.get(label, label)


def extract_feature_rows(daily: list[dict[str, Any]]) -> list[dict[str, Any]]:
    weighted = [
        safe_float(row.get("military", {}).get("weighted_score"))
        for row in daily
    ]
    mai = [
        safe_float(row.get("military", {}).get("activity_index"))
        for row in daily
    ]
    ddi = [
        safe_float(row.get("diplomatic", {}).get("direction_index"))
        for row in daily
    ]
    gap = [
        safe_float(row.get("gap", {}).get("divergence_score"))
        for row in daily
    ]

    rows: list[dict[str, Any]] = []

    for i, row in enumerate(daily):
        military = row.get("military", {})
        diplomatic = row.get("diplomatic", {})

        feature_values = {
            "mai": mai[i],
            "mai_change_1d": mai[i] - mai[i - 1] if i >= 1 else 0.0,
            "mai_change_3d": mai[i] - rolling_mean(mai, i - 1, 3) if i >= 1 else 0.0,
            "mai_change_7d": mai[i] - rolling_mean(mai, i - 1, 7) if i >= 1 else 0.0,
            "weighted_change_1d": (
                pct_change(weighted[i], weighted[i - 1]) if i >= 1 else 0.0
            ),
            "ddi": ddi[i],
            "ddi_change_1d": ddi[i] - ddi[i - 1] if i >= 1 else 0.0,
            "ddi_change_3d": ddi[i] - rolling_mean(ddi, i - 1, 3) if i >= 1 else 0.0,
            "gap": gap[i],
            "gap_change_1d": gap[i] - gap[i - 1] if i >= 1 else 0.0,
            "military_pressure": safe_float(military.get("pressure_score")),
            "military_event_count": safe_float(military.get("event_count")),
            "diplomatic_event_count": safe_float(diplomatic.get("event_count")),
            "escalation_count": safe_float(diplomatic.get("escalation_count")),
            "deescalation_count": safe_float(diplomatic.get("deescalation_count")),
            "mixed_count": safe_float(diplomatic.get("mixed_count")),
        }

        rows.append({
            "date": row.get("date"),
            "weighted_activity": weighted[i],
            "features": feature_values,
        })

    return rows


def add_targets(rows: list[dict[str, Any]]) -> None:
    for i, row in enumerate(rows):
        row["targets"] = {}
        current = safe_float(row.get("weighted_activity"))

        for horizon, days in HORIZONS.items():
            target_i = i + days
            if target_i >= len(rows):
                row["targets"][horizon] = None
                continue

            future = safe_float(rows[target_i].get("weighted_activity"))
            change = pct_change(future, current)
            row["targets"][horizon] = {
                "future_date": rows[target_i].get("date"),
                "future_weighted_activity": round(future, 2),
                "change_pct": round(change, 1),
                "direction": classify_change(change),
            }


def feature_stats(training_rows: list[dict[str, Any]]) -> dict[str, tuple[float, float]]:
    stats: dict[str, tuple[float, float]] = {}

    for feature in FEATURES:
        values = [
            safe_float(r.get("features", {}).get(feature))
            for r in training_rows
        ]
        mu = mean(values) if values else 0.0
        sd = pstdev(values) if len(values) > 1 else 1.0
        if sd < 1e-9:
            sd = 1.0
        stats[feature] = (mu, sd)

    return stats


def distance(
    a: dict[str, Any],
    b: dict[str, Any],
    stats: dict[str, tuple[float, float]],
) -> float:
    total = 0.0

    for feature in FEATURES:
        _, sd = stats[feature]
        av = safe_float(a.get("features", {}).get(feature))
        bv = safe_float(b.get("features", {}).get(feature))
        z = (av - bv) / sd
        total += z * z

    return math.sqrt(total / len(FEATURES))


def confidence_label(score: float) -> str:
    if score >= 0.72:
        return "magas"
    if score >= 0.56:
        return "közepes"
    return "alacsony"


def predict_from_analogues(
    current_row: dict[str, Any],
    training_rows: list[dict[str, Any]],
    horizon: str,
) -> dict[str, Any] | None:
    eligible = [
        row for row in training_rows
        if row.get("targets", {}).get(horizon) is not None
    ]

    if len(eligible) < MIN_TRAINING_ROWS:
        return None

    stats = feature_stats(eligible)

    ranked = sorted(
        (
            (distance(current_row, row, stats), row)
            for row in eligible
        ),
        key=lambda item: item[0],
    )

    neighbours = ranked[:min(K_NEIGHBORS, len(ranked))]
    if not neighbours:
        return None

    # Similarity-weighted vote.
    votes = {"increase": 0.0, "stable": 0.0, "decrease": 0.0}
    weighted_changes: list[tuple[float, float]] = []
    neighbour_output: list[dict[str, Any]] = []

    for dist, row in neighbours:
        target = row["targets"][horizon]
        weight = 1.0 / (0.35 + dist)
        direction = target["direction"]

        votes[direction] += weight
        weighted_changes.append((target["change_pct"], weight))

        neighbour_output.append({
            "date": row["date"],
            "distance": round(dist, 3),
            "similarity_weight": round(weight, 3),
            "observed_direction": direction,
            "observed_direction_hu": hu_label(direction),
            "observed_change_pct": target["change_pct"],
            "future_date": target["future_date"],
        })

    total_vote = sum(votes.values())
    probabilities = {
        label: (votes[label] / total_vote if total_vote else 0.0)
        for label in votes
    }

    predicted = max(probabilities, key=probabilities.get)
    predicted_change = (
        sum(change * weight for change, weight in weighted_changes)
        / sum(weight for _, weight in weighted_changes)
    )

    sorted_probs = sorted(probabilities.values(), reverse=True)
    vote_margin = (
        sorted_probs[0] - sorted_probs[1]
        if len(sorted_probs) > 1
        else sorted_probs[0]
    )

    avg_distance = mean(dist for dist, _ in neighbours)
    similarity_factor = 1.0 / (1.0 + avg_distance)

    # Blend class agreement and analogue similarity.
    confidence_score = max(
        0.0,
        min(
            1.0,
            (probabilities[predicted] * 0.65)
            + (vote_margin * 0.20)
            + (similarity_factor * 0.15),
        ),
    )

    return {
        "direction": predicted,
        "direction_hu": hu_label(predicted),
        "estimated_change_pct": round(predicted_change, 1),
        "confidence_score": round(confidence_score, 3),
        "confidence": confidence_label(confidence_score),
        "probabilities": {
            k: round(v, 3) for k, v in probabilities.items()
        },
        "analogue_count": len(neighbours),
        "nearest_analogues": neighbour_output,
    }


def walk_forward_backtest(
    rows: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    predictions: list[dict[str, Any]] = []

    for i, current in enumerate(rows):
        # Training observations must be strictly prior to forecast date.
        # Additionally, their future target must already be known by that date.
        for horizon, days in HORIZONS.items():
            cutoff = i - days
            if cutoff <= 0:
                continue

            training = rows[:cutoff + 1]

            prediction = predict_from_analogues(
                current,
                training,
                horizon,
            )

            actual = current.get("targets", {}).get(horizon)

            if prediction is None or actual is None:
                continue

            predictions.append({
                "forecast_date": current["date"],
                "horizon": horizon,
                "predicted_direction": prediction["direction"],
                "predicted_direction_hu": prediction["direction_hu"],
                "confidence": prediction["confidence"],
                "confidence_score": prediction["confidence_score"],
                "estimated_change_pct": prediction["estimated_change_pct"],
                "actual_direction": actual["direction"],
                "actual_direction_hu": hu_label(actual["direction"]),
                "actual_change_pct": actual["change_pct"],
                "correct": prediction["direction"] == actual["direction"],
            })

    metrics: dict[str, Any] = {}

    for horizon in HORIZONS:
        subset = [p for p in predictions if p["horizon"] == horizon]

        if not subset:
            metrics[horizon] = {
                "sample_size": 0,
                "accuracy": None,
            }
            continue

        correct = sum(1 for p in subset if p["correct"])
        accuracy = correct / len(subset)

        by_class: dict[str, Any] = {}

        for label in ("increase", "stable", "decrease"):
            actual_label = [
                p for p in subset
                if p["actual_direction"] == label
            ]
            predicted_label = [
                p for p in subset
                if p["predicted_direction"] == label
            ]
            true_positive = sum(
                1 for p in subset
                if p["actual_direction"] == label
                and p["predicted_direction"] == label
            )

            recall = (
                true_positive / len(actual_label)
                if actual_label else None
            )
            precision = (
                true_positive / len(predicted_label)
                if predicted_label else None
            )

            by_class[label] = {
                "support": len(actual_label),
                "precision": round(precision, 3) if precision is not None else None,
                "recall": round(recall, 3) if recall is not None else None,
            }

        high_conf = [
            p for p in subset
            if p["confidence"] == "magas"
        ]
        medium_plus = [
            p for p in subset
            if p["confidence"] in {"magas", "közepes"}
        ]

        metrics[horizon] = {
            "sample_size": len(subset),
            "accuracy": round(accuracy, 3),
            "accuracy_pct": round(accuracy * 100, 1),
            "class_metrics": by_class,
            "high_confidence_sample": len(high_conf),
            "high_confidence_accuracy_pct": (
                round(
                    sum(1 for p in high_conf if p["correct"])
                    / len(high_conf) * 100,
                    1,
                )
                if high_conf else None
            ),
            "medium_or_high_confidence_sample": len(medium_plus),
            "medium_or_high_confidence_accuracy_pct": (
                round(
                    sum(1 for p in medium_plus if p["correct"])
                    / len(medium_plus) * 100,
                    1,
                )
                if medium_plus else None
            ),
        }

    return metrics, predictions


def persistence_baseline(
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Simple benchmark:
    assume the most recent 1-day direction persists.
    """
    results: dict[str, Any] = {}

    for horizon, days in HORIZONS.items():
        total = 0
        correct = 0

        for i in range(1, len(rows) - days):
            yesterday = safe_float(rows[i - 1]["weighted_activity"])
            today = safe_float(rows[i]["weighted_activity"])
            recent_change = pct_change(today, yesterday)
            predicted = classify_change(recent_change)

            actual = rows[i]["targets"][horizon]
            if actual is None:
                continue

            total += 1
            if predicted == actual["direction"]:
                correct += 1

        results[horizon] = {
            "sample_size": total,
            "accuracy_pct": round(correct / total * 100, 1) if total else None,
        }

    return results


def build_latest_forecast(
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    if not rows:
        return {}

    latest = rows[-1]
    forecasts: dict[str, Any] = {}

    for horizon, days in HORIZONS.items():
        # For current forecast, any historical row whose target is already
        # observed by the latest date can be training data.
        training = rows[:-days] if len(rows) > days else []

        prediction = predict_from_analogues(
            latest,
            training,
            horizon,
        )

        forecasts[horizon] = prediction

    return {
        "forecast_date": latest["date"],
        "target": "weighted military activity direction",
        "forecasts": forecasts,
    }


def build_hungarian_summary(
    latest_forecast: dict[str, Any],
    metrics: dict[str, Any],
    baseline: dict[str, Any],
) -> dict[str, str]:
    forecasts = latest_forecast.get("forecasts", {})

    parts: list[str] = []

    for horizon in ("24h", "48h", "72h"):
        forecast = forecasts.get(horizon)
        if not forecast:
            continue
        parts.append(
            f"{horizon}: {forecast['direction_hu']} "
            f"({forecast['confidence']} bizonyosság, "
            f"becsült változás {forecast['estimated_change_pct']:+.1f}%)."
        )

    headline = " ".join(parts) if parts else "Nincs elegendő adat az előrejelzéshez."

    valid_horizons = [
        h for h, m in metrics.items()
        if m.get("accuracy_pct") is not None
    ]

    if valid_horizons:
        best = max(valid_horizons, key=lambda h: metrics[h]["accuracy_pct"])
        accuracy_text = (
            f"A történeti walk-forward backtest alapján a legerősebb "
            f"időtáv jelenleg {best}, {metrics[best]['accuracy_pct']:.1f}% "
            f"irányhelyességgel."
        )
    else:
        accuracy_text = "A backtesthez még nincs elegendő értékelhető minta."

    baseline_notes: list[str] = []
    for horizon in ("24h", "48h", "72h"):
        model_acc = metrics.get(horizon, {}).get("accuracy_pct")
        base_acc = baseline.get(horizon, {}).get("accuracy_pct")
        if model_acc is None or base_acc is None:
            continue
        diff = model_acc - base_acc
        baseline_notes.append(
            f"{horizon}: {diff:+.1f} százalékpont a trendfolytatásos baseline-hoz képest"
        )

    comparison = "; ".join(baseline_notes)

    return {
        "headline": headline,
        "backtest": accuracy_text,
        "baseline_comparison": comparison,
        "caution": (
            "Az előrejelzés a katonai aktivitás várható irányát becsüli, "
            "nem konkrét támadást. A modell történeti mintázatokból dolgozik; "
            "a geopolitikai döntések, váratlan műveletek és adatforrás-változások "
            "gyorsan felülírhatják a becslést."
        ),
    }


def main() -> int:
    data = load_json(INPUT)

    daily = data.get("daily", [])
    if not isinstance(daily, list) or len(daily) < 25:
        raise ValueError(
            "At least 25 complete daily observations are required."
        )

    rows = extract_feature_rows(daily)
    add_targets(rows)

    metrics, backtest_predictions = walk_forward_backtest(rows)
    baseline = persistence_baseline(rows)
    latest_forecast = build_latest_forecast(rows)

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "forecast_model": "historical_analogue_walkforward_v1",
        "source_analysis_model": data.get("analysis_model"),
        "source_analysis_period": data.get("analysis_period"),
        "methodology": {
            "forecast_target": (
                "Direction of weighted military activity over the next "
                "24h / 48h / 72h."
            ),
            "classes": {
                "increase": f"change > +{STABLE_THRESHOLD_PCT:.0f}%",
                "stable": (
                    f"change between -{STABLE_THRESHOLD_PCT:.0f}% "
                    f"and +{STABLE_THRESHOLD_PCT:.0f}%"
                ),
                "decrease": f"change < -{STABLE_THRESHOLD_PCT:.0f}%",
            },
            "model": (
                "Similarity-weighted nearest historical analogues. "
                "Features are standardized using training data only."
            ),
            "k_neighbors": K_NEIGHBORS,
            "minimum_training_rows": MIN_TRAINING_ROWS,
            "features": FEATURES,
            "backtest": (
                "Strict walk-forward evaluation. For each historical forecast "
                "date, only observations whose forecast outcomes were already "
                "known at that date are allowed into training."
            ),
            "causality": (
                "No causal inference. Forecasts are pattern-based short-term "
                "direction estimates."
            ),
        },
        "backtest": {
            "model_metrics": metrics,
            "persistence_baseline": baseline,
            "predictions": backtest_predictions,
        },
        "latest_forecast": latest_forecast,
    }

    output["hungarian_summary"] = build_hungarian_summary(
        latest_forecast,
        metrics,
        baseline,
    )

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temp = OUTPUT.with_suffix(".json.tmp")

    with temp.open("w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    temp.replace(OUTPUT)

    print("Conflict forecast V1 generated.")
    print("Source model:", data.get("analysis_model"))
    print("Complete daily rows:", len(daily))

    for horizon in ("24h", "48h", "72h"):
        m = metrics.get(horizon, {})
        b = baseline.get(horizon, {})
        print(
            horizon,
            "model accuracy:",
            m.get("accuracy_pct"),
            "| baseline:",
            b.get("accuracy_pct"),
        )

        f = latest_forecast.get("forecasts", {}).get(horizon)
        if f:
            print(
                " latest:",
                f["direction_hu"],
                "| confidence:",
                f["confidence"],
                "| estimated:",
                f["estimated_change_pct"],
            )

    print("Output:", OUTPUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
