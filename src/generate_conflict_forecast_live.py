#!/usr/bin/env python3
"""
Conflict Forecast Production Engine V2

Production 48h / 72h directional forecast with:
- expanding historical analogue learning,
- immutable daily forecast archive,
- automatic outcome scoring after the horizon matures,
- live out-of-sample performance tracking,
- adaptive NO SIGNAL calibration after enough live observations,
- protection against using a partial UTC day as a full-day forecast anchor.

Input:
  docs/conflict_analysis.json

Outputs:
  docs/conflict_forecast_live.json
  docs/conflict_forecast_history.json

"Self-learning" means:
1. every newly completed day automatically joins the historical analogue library;
2. issued forecasts are archived and later scored against realized outcomes;
3. after enough genuinely live outcomes exist, the NO SIGNAL gate can
   recalibrate from those out-of-sample results.

The core model families remain fixed to reduce overfitting.
"""

from __future__ import annotations

import json
import math
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import mean, pstdev
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
ANALYSIS_PATH = ROOT / "docs" / "conflict_analysis.json"
LIVE_PATH = ROOT / "docs" / "conflict_forecast_live.json"
HISTORY_PATH = ROOT / "docs" / "conflict_forecast_history.json"

MODEL_VERSION = "conflict_forecast_live_v2"
MIN_TRAINING_ROWS = 18
MIN_LIVE_EVALUATED_FOR_ADAPTATION = 20
MIN_SIGNAL_SAMPLE_FOR_ADAPTATION = 12
MIN_ADAPTIVE_COVERAGE = 0.25
TARGET_SIGNAL_ACCURACY = 0.75
LABELS = ("increase", "stable", "decrease")

CONFIGS = {
    "48h": {
        "days": 2,
        "stable_threshold_pct": 25.0,
        "k_neighbors": 10,
        "feature_set": "full",
        "features": [
            "mai","mai_change_1d","mai_change_3d","mai_change_7d",
            "weighted_change_1d","ddi","ddi_change_1d","ddi_change_3d",
            "gap","gap_change_1d","military_pressure","military_event_count",
            "diplomatic_event_count","escalation_count",
            "deescalation_count","mixed_count",
        ],
        "initial_gate": {
            "confidence_threshold": 0.45,
            "probability_threshold": 0.50,
            "validated_signal_accuracy_pct": 75.0,
            "validated_coverage_pct": 73.3,
        },
    },
    "72h": {
        "days": 3,
        "stable_threshold_pct": 10.0,
        "k_neighbors": 5,
        "feature_set": "mai_ddi",
        "features": [
            "mai","mai_change_1d","mai_change_3d","mai_change_7d",
            "weighted_change_1d","ddi","ddi_change_1d","ddi_change_3d",
        ],
        "initial_gate": {
            "confidence_threshold": 0.45,
            "probability_threshold": 0.79,
            "validated_signal_accuracy_pct": 75.0,
            "validated_coverage_pct": 48.3,
        },
    },
}


def sf(v: Any, default: float = 0.0) -> float:
    try:
        x = float(v)
        return x if math.isfinite(x) else default
    except (TypeError, ValueError):
        return default


def pct(current: float, baseline: float) -> float:
    return ((current - baseline) / baseline * 100.0) if baseline else 0.0


def rmean(values: list[float], end: int, window: int) -> float:
    if end < 0:
        return 0.0
    x = values[max(0, end-window+1):end+1]
    return mean(x) if x else 0.0


def classify(change: float, threshold: float) -> str:
    if change > threshold:
        return "increase"
    if change < -threshold:
        return "decrease"
    return "stable"


def hu(direction: str) -> str:
    return {
        "increase": "növekvő katonai aktivitás",
        "stable": "lényegében változatlan katonai aktivitás",
        "decrease": "csökkenő katonai aktivitás",
        "no_signal": "nincs egyértelmű jelzés",
    }.get(direction, direction)


def load_json(path: Path, default=None):
    if not path.exists():
        return deepcopy(default)
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def parse_utc(value: str | None):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def completed_daily_rows(source):
    daily = source.get("daily", [])
    if not isinstance(daily, list) or not daily:
        raise ValueError("conflict_analysis.json has no daily rows")

    end_dt = parse_utc(source.get("analysis_period", {}).get("end"))
    if end_dt is None:
        return daily, {
            "partial_day_excluded": False,
            "reason": "analysis end timestamp unavailable",
            "forecast_anchor_date": daily[-1].get("date"),
        }

    current_utc_date = end_dt.date().isoformat()
    complete = [r for r in daily if str(r.get("date")) < current_utc_date]

    if not complete:
        raise ValueError("No completed UTC daily rows available")

    excluded = str(daily[-1].get("date")) >= current_utc_date
    return complete, {
        "partial_day_excluded": excluded,
        "excluded_date": daily[-1].get("date") if excluded else None,
        "analysis_end_utc": end_dt.isoformat(),
        "forecast_anchor_date": complete[-1].get("date"),
    }


def rows_from_daily(daily):
    weighted = [sf(r.get("military", {}).get("weighted_score")) for r in daily]
    mai = [sf(r.get("military", {}).get("activity_index")) for r in daily]
    ddi = [sf(r.get("diplomatic", {}).get("direction_index")) for r in daily]
    gap = [sf(r.get("gap", {}).get("divergence_score")) for r in daily]
    out = []

    for i, r in enumerate(daily):
        m = r.get("military", {})
        d = r.get("diplomatic", {})
        features = {
            "mai": mai[i],
            "mai_change_1d": mai[i]-mai[i-1] if i else 0.0,
            "mai_change_3d": mai[i]-rmean(mai, i-1, 3) if i else 0.0,
            "mai_change_7d": mai[i]-rmean(mai, i-1, 7) if i else 0.0,
            "weighted_change_1d": pct(weighted[i], weighted[i-1]) if i else 0.0,
            "ddi": ddi[i],
            "ddi_change_1d": ddi[i]-ddi[i-1] if i else 0.0,
            "ddi_change_3d": ddi[i]-rmean(ddi, i-1, 3) if i else 0.0,
            "gap": gap[i],
            "gap_change_1d": gap[i]-gap[i-1] if i else 0.0,
            "military_pressure": sf(m.get("pressure_score")),
            "military_event_count": sf(m.get("event_count")),
            "diplomatic_event_count": sf(d.get("event_count")),
            "escalation_count": sf(d.get("escalation_count")),
            "deescalation_count": sf(d.get("deescalation_count")),
            "mixed_count": sf(d.get("mixed_count")),
        }
        out.append({
            "date": r.get("date"),
            "weighted_activity": weighted[i],
            "features": features,
        })
    return out


def add_targets(rows, days, threshold):
    for i, row in enumerate(rows):
        j = i + days
        if j >= len(rows):
            row["target"] = None
            continue
        change = pct(sf(rows[j]["weighted_activity"]), sf(row["weighted_activity"]))
        row["target"] = {
            "direction": classify(change, threshold),
            "change_pct": round(change, 1),
            "future_date": rows[j]["date"],
        }


def feature_stats(training, features):
    result = {}
    for f in features:
        vals = [sf(r["features"].get(f)) for r in training]
        mu = mean(vals) if vals else 0.0
        sd = pstdev(vals) if len(vals) > 1 else 1.0
        result[f] = (mu, sd if sd > 1e-9 else 1.0)
    return result


def distance(a, b, stats, features):
    return math.sqrt(sum(
        ((sf(a["features"].get(f)) - sf(b["features"].get(f))) / stats[f][1]) ** 2
        for f in features
    ) / len(features))


def predict(current, training, features, k):
    eligible = [r for r in training if r.get("target") is not None]
    if len(eligible) < MIN_TRAINING_ROWS:
        return None

    stats = feature_stats(eligible, features)
    ranked = sorted(
        ((distance(current, r, stats, features), r) for r in eligible),
        key=lambda x: x[0],
    )[:min(k, len(eligible))]

    votes = {label: 0.0 for label in LABELS}
    for dist, row in ranked:
        votes[row["target"]["direction"]] += 1.0 / (0.35 + dist)

    total = sum(votes.values())
    probs = {label: votes[label] / total for label in votes}
    predicted = max(probs, key=probs.get)
    ordered = sorted(probs.values(), reverse=True)
    margin = ordered[0] - ordered[1]
    avg_dist = mean(dist for dist, _ in ranked)
    similarity = 1.0 / (1.0 + avg_dist)

    confidence = max(
        0.0,
        min(1.0, probs[predicted]*0.65 + margin*0.20 + similarity*0.15),
    )

    return {
        "direction": predicted,
        "direction_hu": hu(predicted),
        "top_probability": round(probs[predicted], 4),
        "confidence_score": round(confidence, 4),
        "probabilities": {x: round(y, 4) for x, y in probs.items()},
        "nearest_analogues": [
            {
                "date": row["date"],
                "distance": round(dist, 3),
                "observed_direction": row["target"]["direction"],
                "observed_direction_hu": hu(row["target"]["direction"]),
            }
            for dist, row in ranked
        ],
    }


def default_history():
    return {
        "history_version": "conflict_forecast_history_v2",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": None,
        "records": [],
    }


def plus_days(date_str, days):
    return (date.fromisoformat(date_str) + timedelta(days=days)).isoformat()


def evaluate_pending(history, rows):
    by_date = {str(r["date"]): sf(r["weighted_activity"]) for r in rows}
    updated = 0

    for record in history.get("records", []):
        if record.get("outcome") is not None:
            continue

        horizon = record.get("horizon")
        cfg = CONFIGS.get(horizon)
        forecast_date = record.get("forecast_reference_date")

        if not cfg or not forecast_date:
            continue

        target_date = plus_days(forecast_date, cfg["days"])
        if forecast_date not in by_date or target_date not in by_date:
            continue

        change = pct(by_date[target_date], by_date[forecast_date])
        actual = classify(change, cfg["stable_threshold_pct"])
        raw = record.get("raw_prediction", {}).get("direction")
        issued = record.get("public_signal", {}).get("direction")

        record["outcome"] = {
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
            "target_date": target_date,
            "actual_direction": actual,
            "actual_direction_hu": hu(actual),
            "actual_change_pct": round(change, 1),
            "raw_prediction_correct": raw == actual,
            "public_signal_was_issued": issued != "no_signal",
            "public_signal_correct": issued == actual if issued != "no_signal" else None,
        }
        enrich_dashboard_fields(record)
        updated += 1

    return updated



def enrich_dashboard_fields(record: dict[str, Any]) -> None:
    """
    Add a stable, flat audit schema for the dashboard while preserving the
    original nested production fields. Existing historical records are migrated
    automatically on every run.
    """
    raw = record.get("raw_prediction") or {}
    public = record.get("public_signal") or {}
    outcome = record.get("outcome")

    raw_direction = raw.get("direction")
    public_direction = public.get("direction", "no_signal")
    has_signal = bool(public.get("has_signal", public_direction != "no_signal"))

    record["forecast_direction"] = public_direction if has_signal else raw_direction
    record["forecast_direction_hu"] = hu(record["forecast_direction"]) if record.get("forecast_direction") else None
    record["raw_forecast_direction"] = raw_direction
    record["raw_forecast_direction_hu"] = hu(raw_direction) if raw_direction else None
    record["public_forecast_direction"] = public_direction
    record["public_forecast_direction_hu"] = hu(public_direction)
    record["has_public_signal"] = has_signal
    record["top_probability"] = raw.get("top_probability")
    record["confidence_score"] = raw.get("confidence_score")

    if outcome is None:
        record["evaluated"] = False
        record["realized_direction"] = None
        record["realized_direction_hu"] = None
        record["actual_direction"] = None
        record["actual_direction_hu"] = None
        record["actual_change_pct"] = None
        record["is_correct"] = None
        record["raw_is_correct"] = None
        record["evaluation"] = None
        return

    actual = outcome.get("actual_direction")
    public_correct = outcome.get("public_signal_correct")
    raw_correct = outcome.get("raw_prediction_correct")

    record["evaluated"] = True
    record["realized_direction"] = actual
    record["realized_direction_hu"] = outcome.get("actual_direction_hu") or hu(actual)
    record["actual_direction"] = actual
    record["actual_direction_hu"] = outcome.get("actual_direction_hu") or hu(actual)
    record["actual_change_pct"] = outcome.get("actual_change_pct")
    record["is_correct"] = public_correct if has_signal else None
    record["raw_is_correct"] = raw_correct
    record["evaluation"] = {
        "evaluated_at": outcome.get("evaluated_at"),
        "target_date": outcome.get("target_date") or record.get("target_date"),
        "observed_direction": actual,
        "observed_direction_hu": outcome.get("actual_direction_hu") or hu(actual),
        "realized_direction": actual,
        "realized_direction_hu": outcome.get("actual_direction_hu") or hu(actual),
        "actual_change_pct": outcome.get("actual_change_pct"),
        "raw_prediction_correct": raw_correct,
        "public_signal_was_issued": outcome.get("public_signal_was_issued"),
        "public_signal_correct": public_correct,
    }


def migrate_history_for_dashboard(history: dict[str, Any]) -> None:
    """Normalize every existing record to the dashboard audit schema."""
    for record in history.get("records", []):
        if isinstance(record, dict):
            enrich_dashboard_fields(record)


def evaluated_records(history, horizon):
    return [
        r for r in history.get("records", [])
        if r.get("horizon") == horizon and r.get("outcome") is not None
    ]


def adaptive_gate(evaluated, initial_gate):
    if len(evaluated) < MIN_LIVE_EVALUATED_FOR_ADAPTATION:
        return deepcopy(initial_gate), {
            "mode": "initial_v31_gate",
            "adaptive": False,
            "evaluated_live_forecasts": len(evaluated),
            "required_for_adaptation": MIN_LIVE_EVALUATED_FOR_ADAPTATION,
        }

    tests = []
    for ci in range(40, 86):
        conf = ci / 100
        for pi in range(45, 91):
            prob = pi / 100
            q = [
                r for r in evaluated
                if sf(r.get("raw_prediction", {}).get("confidence_score")) >= conf
                and sf(r.get("raw_prediction", {}).get("top_probability")) >= prob
            ]
            if not q:
                continue

            correct = sum(
                1 for r in q
                if r.get("outcome", {}).get("raw_prediction_correct") is True
            )
            accuracy = correct / len(q)
            coverage = len(q) / len(evaluated)

            tests.append({
                "confidence_threshold": round(conf, 2),
                "probability_threshold": round(prob, 2),
                "signal_sample": len(q),
                "coverage_pct": round(coverage*100, 1),
                "signal_accuracy_pct": round(accuracy*100, 1),
            })

    eligible = [
        x for x in tests
        if x["signal_sample"] >= MIN_SIGNAL_SAMPLE_FOR_ADAPTATION
        and x["coverage_pct"] >= MIN_ADAPTIVE_COVERAGE*100
        and x["signal_accuracy_pct"] >= TARGET_SIGNAL_ACCURACY*100
    ]

    if not eligible:
        return deepcopy(initial_gate), {
            "mode": "initial_v31_gate_no_safe_live_recalibration",
            "adaptive": False,
            "evaluated_live_forecasts": len(evaluated),
        }

    eligible.sort(
        key=lambda x: (x["coverage_pct"], x["signal_accuracy_pct"], x["signal_sample"]),
        reverse=True,
    )
    chosen = eligible[0]

    return {
        "confidence_threshold": chosen["confidence_threshold"],
        "probability_threshold": chosen["probability_threshold"],
        "validated_signal_accuracy_pct": chosen["signal_accuracy_pct"],
        "validated_coverage_pct": chosen["coverage_pct"],
    }, {
        "mode": "adaptive_live_gate",
        "adaptive": True,
        "evaluated_live_forecasts": len(evaluated),
        "selected_from_live_results": chosen,
    }


def live_performance(evaluated):
    if not evaluated:
        return {
            "evaluated_forecasts": 0,
            "issued_signals": 0,
            "issued_signal_accuracy_pct": None,
            "raw_direction_accuracy_pct": None,
        }

    raw_correct = sum(
        1 for r in evaluated
        if r.get("outcome", {}).get("raw_prediction_correct") is True
    )
    issued = [
        r for r in evaluated
        if r.get("outcome", {}).get("public_signal_was_issued") is True
    ]
    issued_correct = sum(
        1 for r in issued
        if r.get("outcome", {}).get("public_signal_correct") is True
    )

    return {
        "evaluated_forecasts": len(evaluated),
        "issued_signals": len(issued),
        "issued_signal_accuracy_pct": (
            round(issued_correct / len(issued) * 100, 1) if issued else None
        ),
        "raw_direction_accuracy_pct": round(
            raw_correct / len(evaluated) * 100, 1
        ),
    }


def record_exists(history, forecast_date, horizon):
    return any(
        r.get("forecast_reference_date") == forecast_date
        and r.get("horizon") == horizon
        for r in history.get("records", [])
    )


def main():
    source = load_json(ANALYSIS_PATH)
    if not source:
        raise FileNotFoundError(f"Missing input: {ANALYSIS_PATH}")

    complete_daily, completeness = completed_daily_rows(source)
    if len(complete_daily) < 25:
        raise ValueError("At least 25 completed UTC days are required")

    base_rows = rows_from_daily(complete_daily)
    forecast_date = str(base_rows[-1]["date"])

    history = load_json(HISTORY_PATH, default_history())
    if not isinstance(history, dict):
        history = default_history()
    history.setdefault("records", [])
    history["history_version"] = "conflict_forecast_history_v2"
    migrate_history_for_dashboard(history)

    newly_evaluated = evaluate_pending(history, base_rows)

    live = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model_version": MODEL_VERSION,
        "forecast_reference_date": forecast_date,
        "source_analysis_period": source.get("analysis_period"),
        "day_completeness": completeness,
        "learning": {
            "analogue_library_days": len(base_rows),
            "newly_evaluated_forecasts_this_run": newly_evaluated,
            "mechanism": (
                "New completed days enter the analogue library automatically. "
                "Archived forecasts are scored after maturity. The NO SIGNAL "
                "gate can recalibrate only after sufficient live outcomes."
            ),
        },
        "horizons": {},
        "disclaimer_hu": (
            "Az előrejelzés az összesített katonai aktivitás várható irányát "
            "becsüli történeti mintázatok alapján. Nem konkrét támadás, célpont "
            "vagy katonai művelet előrejelzése."
        ),
    }

    for horizon, cfg in CONFIGS.items():
        rows = deepcopy(base_rows)
        add_targets(rows, cfg["days"], cfg["stable_threshold_pct"])

        training = rows[:-cfg["days"]]
        current = rows[-1]
        raw = predict(current, training, cfg["features"], cfg["k_neighbors"])

        evaluated = evaluated_records(history, horizon)
        gate, gate_meta = adaptive_gate(evaluated, cfg["initial_gate"])

        has_signal = bool(
            raw
            and raw["confidence_score"] >= gate["confidence_threshold"]
            and raw["top_probability"] >= gate["probability_threshold"]
        )
        public_direction = raw["direction"] if has_signal else "no_signal"

        public = {
            "direction": public_direction,
            "direction_hu": hu(public_direction),
            "has_signal": has_signal,
            "gate_used": {
                "confidence_threshold": gate["confidence_threshold"],
                "probability_threshold": gate["probability_threshold"],
            },
        }

        target_date = plus_days(forecast_date, cfg["days"])

        result = {
            "horizon": horizon,
            "target_date": target_date,
            "configuration": {
                "feature_set": cfg["feature_set"],
                "stable_threshold_pct": cfg["stable_threshold_pct"],
                "k_neighbors": cfg["k_neighbors"],
            },
            "raw_prediction": raw,
            "public_signal": public,
            "gate_calibration": gate_meta,
            "historical_v31_validation": {
                "signal_accuracy_pct": cfg["initial_gate"]["validated_signal_accuracy_pct"],
                "coverage_pct": cfg["initial_gate"]["validated_coverage_pct"],
            },
            "live_out_of_sample_performance": live_performance(evaluated),
        }

        live["horizons"][horizon] = result

        if not record_exists(history, forecast_date, horizon):
            new_record = {
                "issued_at": datetime.now(timezone.utc).isoformat(),
                "model_version": MODEL_VERSION,
                "forecast_reference_date": forecast_date,
                "target_date": target_date,
                "horizon": horizon,
                "configuration": result["configuration"],
                "gate_calibration_mode": gate_meta.get("mode"),
                "gate_used": public["gate_used"],
                "raw_prediction": raw,
                "public_signal": {
                    "direction": public_direction,
                    "direction_hu": hu(public_direction),
                    "has_signal": has_signal,
                },
                "outcome": None,
            }
            enrich_dashboard_fields(new_record)
            history["records"].append(new_record)

    migrate_history_for_dashboard(history)
    history["records"].sort(
        key=lambda r: (str(r.get("forecast_reference_date", "")), str(r.get("horizon", "")))
    )
    history["updated_at"] = datetime.now(timezone.utc).isoformat()
    history["record_count"] = len(history["records"])
    history["evaluated_record_count"] = sum(
        1 for r in history["records"] if r.get("evaluated") is True
    )

    atomic_write(HISTORY_PATH, history)
    atomic_write(LIVE_PATH, live)

    print("Conflict Forecast LIVE V1 complete")
    print("Forecast reference date:", forecast_date)
    print("Completed analogue days:", len(base_rows))
    print("New outcomes evaluated:", newly_evaluated)

    for horizon, result in live["horizons"].items():
        print(f"\n===== {horizon} =====")
        print("Public:", result["public_signal"]["direction_hu"])
        print("Gate:", result["public_signal"]["gate_used"])
        print("Gate mode:", result["gate_calibration"].get("mode"))
        print("Live performance:", result["live_out_of_sample_performance"])

    print("\nLive output:", LIVE_PATH)
    print("History:", HISTORY_PATH)


if __name__ == "__main__":
    main()
