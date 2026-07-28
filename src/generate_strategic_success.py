#!/usr/bin/env python3
"""
Generate Strategic Success from Interest Achievement.

Input:
    docs/interest_achievement.json

Output:
    docs/strategic_success.json

The Strategic Success index combines:

    Achievement     50%
    Momentum        20%
    Stability       15%
    Consistency     15%

The script:

- processes the complete Interest Achievement history;
- recalculates the entire Strategic Success history on every run;
- creates current, history and history_summary blocks;
- calculates Strategic Balance between the actors;
- preserves warnings and excluded/invalid records in diagnostics;
- depends exclusively on Interest Achievement data.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_INPUT_PATH = Path("docs/interest_achievement.json")
DEFAULT_OUTPUT_PATH = Path("docs/strategic_success.json")

MODEL_VERSION = "strategic_success_v1"

ACTOR_IDS = ("usa", "iran")

ACHIEVEMENT_WEIGHT = 0.50
MOMENTUM_WEIGHT = 0.20
STABILITY_WEIGHT = 0.15
CONSISTENCY_WEIGHT = 0.15

MOMENTUM_SHORT_WINDOW = 7
MOMENTUM_LONG_WINDOW = 30
STABILITY_WINDOW = 30
CONSISTENCY_WINDOW = 30

# A 10-point difference between the 7-day and 30-day averages
# corresponds to the maximum positive or negative momentum score.
MOMENTUM_DELTA_CAP = 10.0

# Standard deviation is converted into a 0–100 stability score.
# A standard deviation of 10 points results in a stability score of 0.
STABILITY_STANDARD_DEVIATION_CAP = 10.0

NEUTRAL_INDEX = 50.0


class StrategicSuccessError(Exception):
    """Raised when Strategic Success generation cannot continue."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate docs/strategic_success.json exclusively from "
            "docs/interest_achievement.json."
        )
    )

    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT_PATH,
        help=(
            "Path to Interest Achievement JSON. "
            f"Default: {DEFAULT_INPUT_PATH}"
        ),
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help=(
            "Path for generated Strategic Success JSON. "
            f"Default: {DEFAULT_OUTPUT_PATH}"
        ),
    )

    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise StrategicSuccessError(f"Input file does not exist: {path}")

    try:
        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except json.JSONDecodeError as exc:
        raise StrategicSuccessError(
            f"Invalid JSON in {path}: {exc}"
        ) from exc
    except OSError as exc:
        raise StrategicSuccessError(
            f"Could not read {path}: {exc}"
        ) from exc

    if not isinstance(data, dict):
        raise StrategicSuccessError(
            f"The root element of {path} must be a JSON object."
        )

    return data


def write_json(path: Path, data: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)

        temporary_path = path.with_suffix(path.suffix + ".tmp")

        with temporary_path.open("w", encoding="utf-8") as file:
            json.dump(
                data,
                file,
                ensure_ascii=False,
                indent=2,
                allow_nan=False,
            )
            file.write("\n")

        temporary_path.replace(path)

    except OSError as exc:
        raise StrategicSuccessError(
            f"Could not write output file {path}: {exc}"
        ) from exc


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def round_value(value: float, digits: int = 2) -> float:
    return round(float(value), digits)


def safe_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None

    if isinstance(value, (int, float)):
        numeric_value = float(value)

        if math.isfinite(numeric_value):
            return numeric_value

    return None


def validate_date(value: Any) -> str | None:
    if not isinstance(value, str):
        return None

    date_value = value.strip()

    if not date_value:
        return None

    try:
        datetime.strptime(date_value, "%Y-%m-%d")
    except ValueError:
        return None

    return date_value


def mean(values: list[float]) -> float:
    if not values:
        return NEUTRAL_INDEX

    return statistics.fmean(values)


def median(values: list[float]) -> float:
    if not values:
        return NEUTRAL_INDEX

    return statistics.median(values)


def population_standard_deviation(values: list[float]) -> float:
    if len(values) <= 1:
        return 0.0

    return statistics.pstdev(values)


def get_actor_achievement(
    record: dict[str, Any],
    actor_id: str,
) -> float | None:
    actors = record.get("actors")

    if isinstance(actors, dict):
        actor_data = actors.get(actor_id)

        if isinstance(actor_data, dict):
            achievement_index = safe_number(
                actor_data.get("achievement_index")
            )

            if achievement_index is not None:
                return clamp(achievement_index, 0.0, 100.0)

    summary = record.get("summary")

    if isinstance(summary, dict):
        summary_key = f"{actor_id}_achievement_index"
        achievement_index = safe_number(summary.get(summary_key))

        if achievement_index is not None:
            return clamp(achievement_index, 0.0, 100.0)

    return None


def extract_history(
    input_data: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    raw_history = input_data.get("history")

    if not isinstance(raw_history, list):
        raise StrategicSuccessError(
            "Interest Achievement does not contain a valid history[] array."
        )

    valid_records: list[dict[str, Any]] = []
    invalid_records: list[dict[str, Any]] = []

    records_by_date: dict[str, dict[str, Any]] = {}

    for position, record in enumerate(raw_history):
        if not isinstance(record, dict):
            invalid_records.append(
                {
                    "position": position,
                    "reason": "History record is not a JSON object.",
                    "record": record,
                }
            )
            continue

        date = validate_date(record.get("date"))

        if date is None:
            invalid_records.append(
                {
                    "position": position,
                    "reason": "History record has no valid YYYY-MM-DD date.",
                    "record": record,
                }
            )
            continue

        missing_actors = [
            actor_id
            for actor_id in ACTOR_IDS
            if get_actor_achievement(record, actor_id) is None
        ]

        if missing_actors:
            invalid_records.append(
                {
                    "position": position,
                    "date": date,
                    "reason": (
                        "Missing valid achievement index for: "
                        + ", ".join(missing_actors)
                    ),
                    "record": record,
                }
            )
            continue

        if date in records_by_date:
            invalid_records.append(
                {
                    "position": position,
                    "date": date,
                    "reason": (
                        "Duplicate history date. The later valid record "
                        "replaced the earlier record."
                    ),
                    "record": records_by_date[date],
                }
            )

        records_by_date[date] = record

    for date in sorted(records_by_date):
        valid_records.append(records_by_date[date])

    if not valid_records:
        raise StrategicSuccessError(
            "Interest Achievement history contains no valid records."
        )

    return valid_records, invalid_records


def extract_current(
    input_data: dict[str, Any],
) -> dict[str, Any]:
    current = input_data.get("current")

    if not isinstance(current, dict):
        raise StrategicSuccessError(
            "Interest Achievement does not contain a valid current block."
        )

    date = validate_date(current.get("date"))

    if date is None:
        raise StrategicSuccessError(
            "Interest Achievement current block has no valid date."
        )

    missing_actors = [
        actor_id
        for actor_id in ACTOR_IDS
        if get_actor_achievement(current, actor_id) is None
    ]

    if missing_actors:
        raise StrategicSuccessError(
            "Interest Achievement current block is missing valid indexes for: "
            + ", ".join(missing_actors)
        )

    return current


def calculate_momentum(
    achievement_series: list[float],
) -> dict[str, Any]:
    short_values = achievement_series[-MOMENTUM_SHORT_WINDOW:]
    long_values = achievement_series[-MOMENTUM_LONG_WINDOW:]

    short_average = mean(short_values)
    long_average = mean(long_values)

    raw_delta = short_average - long_average
    capped_delta = clamp(
        raw_delta,
        -MOMENTUM_DELTA_CAP,
        MOMENTUM_DELTA_CAP,
    )

    momentum_score = clamp(
        NEUTRAL_INDEX
        + (
            capped_delta
            / MOMENTUM_DELTA_CAP
            * NEUTRAL_INDEX
        ),
        0.0,
        100.0,
    )

    if raw_delta > 0.25:
        direction = "improving"
    elif raw_delta < -0.25:
        direction = "deteriorating"
    else:
        direction = "stable"

    return {
        "score": round_value(momentum_score),
        "direction": direction,
        "delta_7_vs_30": round_value(raw_delta),
        "average_7_day": round_value(short_average),
        "average_30_day": round_value(long_average),
        "observations_7_day": len(short_values),
        "observations_30_day": len(long_values),
    }


def calculate_stability(
    achievement_series: list[float],
) -> dict[str, Any]:
    window_values = achievement_series[-STABILITY_WINDOW:]

    standard_deviation = population_standard_deviation(window_values)

    stability_score = clamp(
        100.0
        - (
            standard_deviation
            / STABILITY_STANDARD_DEVIATION_CAP
            * 100.0
        ),
        0.0,
        100.0,
    )

    if stability_score >= 80.0:
        level = "high"
    elif stability_score >= 60.0:
        level = "moderate"
    elif stability_score >= 40.0:
        level = "low"
    else:
        level = "very_low"

    return {
        "score": round_value(stability_score),
        "level": level,
        "standard_deviation": round_value(standard_deviation),
        "window": STABILITY_WINDOW,
        "observations": len(window_values),
    }


def calculate_consistency(
    achievement_series: list[float],
) -> dict[str, Any]:
    window_values = achievement_series[-CONSISTENCY_WINDOW:]

    positive_days = sum(
        1
        for value in window_values
        if value > NEUTRAL_INDEX
    )

    neutral_days = sum(
        1
        for value in window_values
        if value == NEUTRAL_INDEX
    )

    negative_days = sum(
        1
        for value in window_values
        if value < NEUTRAL_INDEX
    )

    observation_count = len(window_values)

    if observation_count:
        consistency_score = (
            positive_days
            / observation_count
            * 100.0
        )
    else:
        consistency_score = 0.0

    if consistency_score >= 75.0:
        level = "high"
    elif consistency_score >= 50.0:
        level = "moderate"
    elif consistency_score >= 25.0:
        level = "low"
    else:
        level = "very_low"

    return {
        "score": round_value(consistency_score),
        "level": level,
        "positive_days": positive_days,
        "neutral_days": neutral_days,
        "negative_days": negative_days,
        "window": CONSISTENCY_WINDOW,
        "observations": observation_count,
    }


def classify_success_level(success_index: float) -> str:
    if success_index >= 70.0:
        return "strong_success"

    if success_index >= 55.0:
        return "moderate_success"

    if success_index > 45.0:
        return "balanced"

    if success_index > 30.0:
        return "moderate_failure"

    return "strong_failure"


def calculate_actor_success(
    actor_id: str,
    achievement_series: list[float],
) -> dict[str, Any]:
    if not achievement_series:
        raise StrategicSuccessError(
            f"No achievement series available for actor: {actor_id}"
        )

    achievement = achievement_series[-1]

    momentum = calculate_momentum(achievement_series)
    stability = calculate_stability(achievement_series)
    consistency = calculate_consistency(achievement_series)

    weighted_achievement = achievement * ACHIEVEMENT_WEIGHT
    weighted_momentum = momentum["score"] * MOMENTUM_WEIGHT
    weighted_stability = stability["score"] * STABILITY_WEIGHT
    weighted_consistency = consistency["score"] * CONSISTENCY_WEIGHT

    success_index = clamp(
        weighted_achievement
        + weighted_momentum
        + weighted_stability
        + weighted_consistency,
        0.0,
        100.0,
    )

    return {
        "success_index": round_value(success_index),
        "level": classify_success_level(success_index),
        "change_from_neutral": round_value(
            success_index - NEUTRAL_INDEX
        ),
        "components": {
            "achievement": {
                "value": round_value(achievement),
                "weight": ACHIEVEMENT_WEIGHT,
                "weighted_contribution": round_value(
                    weighted_achievement
                ),
            },
            "momentum": {
                **momentum,
                "weight": MOMENTUM_WEIGHT,
                "weighted_contribution": round_value(
                    weighted_momentum
                ),
            },
            "stability": {
                **stability,
                "weight": STABILITY_WEIGHT,
                "weighted_contribution": round_value(
                    weighted_stability
                ),
            },
            "consistency": {
                **consistency,
                "weight": CONSISTENCY_WEIGHT,
                "weighted_contribution": round_value(
                    weighted_consistency
                ),
            },
        },
    }


def classify_advantage(success_gap: float) -> str:
    if success_gap >= 5.0:
        return "usa"

    if success_gap <= -5.0:
        return "iran"

    return "balanced"


def calculate_day(
    date: str,
    achievement_series_by_actor: dict[str, list[float]],
) -> dict[str, Any]:
    actors = {
        actor_id: calculate_actor_success(
            actor_id,
            achievement_series_by_actor[actor_id],
        )
        for actor_id in ACTOR_IDS
    }

    usa_success = actors["usa"]["success_index"]
    iran_success = actors["iran"]["success_index"]

    success_gap = round_value(usa_success - iran_success)
    strategic_advantage = classify_advantage(success_gap)

    return {
        "date": date,
        "summary": {
            "usa_success_index": usa_success,
            "iran_success_index": iran_success,
            "success_gap": success_gap,
            "strategic_balance": round_value(
                NEUTRAL_INDEX + success_gap / 2.0
            ),
            "strategic_advantage": strategic_advantage,
            "interpretation": (
                "Strategic Success combines Interest Achievement, momentum, "
                "stability and consistency. It measures whether an actor's "
                "strategic-interest performance is positive and sustainable."
            ),
        },
        "actors": actors,
    }


def build_history(
    history_records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    achievement_series_by_actor: dict[str, list[float]] = {
        actor_id: []
        for actor_id in ACTOR_IDS
    }

    generated_history: list[dict[str, Any]] = []

    for record in history_records:
        date = str(record["date"])

        for actor_id in ACTOR_IDS:
            achievement = get_actor_achievement(record, actor_id)

            if achievement is None:
                raise StrategicSuccessError(
                    f"Missing achievement value for {actor_id} on {date}."
                )

            achievement_series_by_actor[actor_id].append(achievement)

        generated_history.append(
            calculate_day(
                date=date,
                achievement_series_by_actor=achievement_series_by_actor,
            )
        )

    return generated_history


def build_current(
    current_record: dict[str, Any],
    history_records: list[dict[str, Any]],
) -> dict[str, Any]:
    current_date = str(current_record["date"])

    achievement_series_by_actor: dict[str, list[float]] = {
        actor_id: []
        for actor_id in ACTOR_IDS
    }

    current_date_found = False

    for record in history_records:
        record_date = str(record["date"])

        if record_date > current_date:
            continue

        for actor_id in ACTOR_IDS:
            achievement = get_actor_achievement(record, actor_id)

            if achievement is None:
                raise StrategicSuccessError(
                    f"Missing achievement value for {actor_id} on "
                    f"{record_date}."
                )

            achievement_series_by_actor[actor_id].append(achievement)

        if record_date == current_date:
            current_date_found = True

    for actor_id in ACTOR_IDS:
        current_achievement = get_actor_achievement(
            current_record,
            actor_id,
        )

        if current_achievement is None:
            raise StrategicSuccessError(
                f"Missing current achievement value for {actor_id}."
            )

        if current_date_found:
            achievement_series_by_actor[actor_id][-1] = current_achievement
        else:
            achievement_series_by_actor[actor_id].append(
                current_achievement
            )

    return calculate_day(
        date=current_date,
        achievement_series_by_actor=achievement_series_by_actor,
    )


def calculate_rolling_average(
    history: list[dict[str, Any]],
    actor_id: str,
    window: int,
) -> list[dict[str, Any]]:
    values: list[float] = []
    result: list[dict[str, Any]] = []

    for record in history:
        actor_data = record["actors"][actor_id]
        success_index = float(actor_data["success_index"])

        values.append(success_index)
        window_values = values[-window:]

        result.append(
            {
                "date": record["date"],
                "value": round_value(mean(window_values)),
                "window": window,
                "observations": len(window_values),
            }
        )

    return result


def build_actor_summary(
    history: list[dict[str, Any]],
    actor_id: str,
) -> dict[str, Any]:
    values = [
        float(record["actors"][actor_id]["success_index"])
        for record in history
    ]

    dated_values = [
        {
            "date": record["date"],
            "value": float(
                record["actors"][actor_id]["success_index"]
            ),
        }
        for record in history
    ]

    best_day = max(
        dated_values,
        key=lambda item: item["value"],
    )

    worst_day = min(
        dated_values,
        key=lambda item: item["value"],
    )

    positive_days = sum(
        1
        for value in values
        if value > NEUTRAL_INDEX
    )

    neutral_days = sum(
        1
        for value in values
        if value == NEUTRAL_INDEX
    )

    negative_days = sum(
        1
        for value in values
        if value < NEUTRAL_INDEX
    )

    total_days = len(values)

    return {
        "average": round_value(mean(values)),
        "median": round_value(median(values)),
        "latest": round_value(values[-1]),
        "change_first_to_latest": round_value(
            values[-1] - values[0]
        ),
        "best_day": {
            "date": best_day["date"],
            "value": round_value(best_day["value"]),
        },
        "worst_day": {
            "date": worst_day["date"],
            "value": round_value(worst_day["value"]),
        },
        "volatility": {
            "standard_deviation": round_value(
                population_standard_deviation(values)
            )
        },
        "day_distribution": {
            "positive_days": positive_days,
            "neutral_days": neutral_days,
            "negative_days": negative_days,
            "positive_share": round_value(
                positive_days / total_days * 100.0
            ),
            "neutral_share": round_value(
                neutral_days / total_days * 100.0
            ),
            "negative_share": round_value(
                negative_days / total_days * 100.0
            ),
        },
        "rolling_averages": {
            "7_day": calculate_rolling_average(
                history,
                actor_id,
                7,
            ),
            "30_day": calculate_rolling_average(
                history,
                actor_id,
                30,
            ),
        },
    }


def build_history_summary(
    history: list[dict[str, Any]],
) -> dict[str, Any]:
    success_gaps = [
        float(record["summary"]["success_gap"])
        for record in history
    ]

    usa_advantage_days = sum(
        1
        for record in history
        if record["summary"]["strategic_advantage"] == "usa"
    )

    iran_advantage_days = sum(
        1
        for record in history
        if record["summary"]["strategic_advantage"] == "iran"
    )

    balanced_days = sum(
        1
        for record in history
        if record["summary"]["strategic_advantage"] == "balanced"
    )

    return {
        "day_count": len(history),
        "start_date": history[0]["date"],
        "end_date": history[-1]["date"],
        "actors": {
            actor_id: build_actor_summary(history, actor_id)
            for actor_id in ACTOR_IDS
        },
        "strategic_balance": {
            "average_success_gap": round_value(mean(success_gaps)),
            "latest_success_gap": round_value(success_gaps[-1]),
            "usa_advantage_days": usa_advantage_days,
            "iran_advantage_days": iran_advantage_days,
            "balanced_days": balanced_days,
        },
    }


def build_output(
    input_data: dict[str, Any],
    input_path: Path,
) -> dict[str, Any]:
    history_records, invalid_history_records = extract_history(
        input_data
    )

    current_record = extract_current(input_data)

    history = build_history(history_records)

    current = build_current(
        current_record=current_record,
        history_records=history_records,
    )

    history_summary = build_history_summary(history)

    input_metadata = input_data.get("metadata")

    if not isinstance(input_metadata, dict):
        input_metadata = {}

    warnings: list[str] = []

    current_date = current["date"]
    history_end_date = history[-1]["date"]

    if current_date != history_end_date:
        warnings.append(
            "The Interest Achievement current date does not match the "
            "last valid history date. Current was calculated separately "
            "using the current block and the available historical context."
        )

    if invalid_history_records:
        warnings.append(
            f"{len(invalid_history_records)} invalid or duplicate history "
            "record(s) were excluded from Strategic Success calculations."
        )

    return {
        "metadata": {
            "dataset": "Strategic Success",
            "model_version": MODEL_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source_dataset": "Interest Achievement",
            "input_file": str(input_path),
            "input_model_version": input_metadata.get(
                "model_version",
                input_metadata.get("version"),
            ),
            "current_date": current_date,
            "history_start_date": history[0]["date"],
            "history_end_date": history_end_date,
            "history_day_count": len(history),
            "actors": list(ACTOR_IDS),
            "warning_count": len(warnings),
        },
        "current": current,
        "history": history,
        "history_summary": history_summary,
        "diagnostics": {
            "excluded_history_records": invalid_history_records,
            "warnings": warnings,
            "counts": {
                "processed_history_days": len(history),
                "excluded_history_records": len(
                    invalid_history_records
                ),
                "warnings": len(warnings),
            },
        },
        "methodology": {
            "source_scope": (
                "Strategic Success is calculated exclusively from "
                "docs/interest_achievement.json. No Strategic Pressure "
                "or raw-event input is read directly."
            ),
            "formula": (
                "success_index = achievement × 0.50 "
                "+ momentum_score × 0.20 "
                "+ stability_score × 0.15 "
                "+ consistency_score × 0.15"
            ),
            "weights": {
                "achievement": ACHIEVEMENT_WEIGHT,
                "momentum": MOMENTUM_WEIGHT,
                "stability": STABILITY_WEIGHT,
                "consistency": CONSISTENCY_WEIGHT,
            },
            "achievement": (
                "The actor's Interest Achievement index for the given day."
            ),
            "momentum": {
                "description": (
                    "Momentum compares the trailing 7-day Interest "
                    "Achievement average with the trailing 30-day average."
                ),
                "formula": (
                    "momentum_score = clamp("
                    "50 + capped_delta / 10 × 50, 0, 100)"
                ),
                "short_window": MOMENTUM_SHORT_WINDOW,
                "long_window": MOMENTUM_LONG_WINDOW,
                "delta_cap": MOMENTUM_DELTA_CAP,
                "neutral_score": NEUTRAL_INDEX,
            },
            "stability": {
                "description": (
                    "Stability measures the trailing 30-day population "
                    "standard deviation of Interest Achievement."
                ),
                "formula": (
                    "stability_score = clamp("
                    "100 - standard_deviation / 10 × 100, 0, 100)"
                ),
                "window": STABILITY_WINDOW,
                "standard_deviation_cap": (
                    STABILITY_STANDARD_DEVIATION_CAP
                ),
            },
            "consistency": {
                "description": (
                    "Consistency is the percentage of days in the trailing "
                    "30-day window on which Interest Achievement was "
                    "strictly above the neutral value of 50."
                ),
                "formula": (
                    "consistency_score = positive_days / observations × 100"
                ),
                "window": CONSISTENCY_WINDOW,
                "neutral_value": NEUTRAL_INDEX,
            },
            "strategic_balance": {
                "description": (
                    "The success gap is USA Strategic Success minus "
                    "Iran Strategic Success."
                ),
                "advantage_threshold": 5.0,
            },
            "limitations": [
                (
                    "Strategic Success inherits the assumptions and data "
                    "limitations of Interest Achievement."
                ),
                (
                    "Early historical records use partial rolling windows "
                    "until 7 or 30 observations become available."
                ),
                (
                    "Stability measures regularity, not whether the "
                    "underlying strategic result is positive."
                ),
                (
                    "The index is an analytical indicator and does not "
                    "directly measure military victory, political legitimacy "
                    "or final conflict outcome."
                ),
            ],
        },
    }


def main() -> int:
    args = parse_args()

    try:
        input_data = load_json(args.input)

        output_data = build_output(
            input_data=input_data,
            input_path=args.input,
        )

        write_json(args.output, output_data)

    except StrategicSuccessError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    current = output_data["current"]
    summary = current["summary"]
    diagnostics = output_data["diagnostics"]["counts"]

    print("Strategic Success generation completed.")
    print(f"Output: {args.output}")
    print(f"Current date: {current['date']}")
    print(
        "History range: "
        f"{output_data['metadata']['history_start_date']} to "
        f"{output_data['metadata']['history_end_date']}"
    )
    print(
        "History days: "
        f"{output_data['metadata']['history_day_count']}"
    )
    print(
        "USA Strategic Success: "
        f"{summary['usa_success_index']}"
    )
    print(
        "Iran Strategic Success: "
        f"{summary['iran_success_index']}"
    )
    print(f"Success gap: {summary['success_gap']}")
    print(
        "Strategic advantage: "
        f"{summary['strategic_advantage']}"
    )
    print(
        "Excluded history records: "
        f"{diagnostics['excluded_history_records']}"
    )
    print(f"Warnings: {diagnostics['warnings']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
