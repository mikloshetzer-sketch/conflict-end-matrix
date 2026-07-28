#!/usr/bin/env python3
"""
Generate Strategic Success from Interest Achievement.

Input:
    docs/interest_achievement.json

Output:
    docs/strategic_success.json

Strategic Success combines:

    Achievement     50%
    Momentum        20%
    Stability       15%
    Consistency     15%

Data maturity:

    1–6 observations     insufficient
    7–29 observations    partial
    30+ observations     full

For incomplete rolling windows, momentum, stability and consistency are
shrunk toward the neutral score of 50. This prevents early historical
records from receiving artificially high Strategic Success values merely
because only one or a few observations are available.
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

MODEL_VERSION = "strategic_success_v1_1"

ACTOR_IDS = ("usa", "iran")

ACHIEVEMENT_WEIGHT = 0.50
MOMENTUM_WEIGHT = 0.20
STABILITY_WEIGHT = 0.15
CONSISTENCY_WEIGHT = 0.15

MOMENTUM_SHORT_WINDOW = 7
MOMENTUM_LONG_WINDOW = 30
STABILITY_WINDOW = 30
CONSISTENCY_WINDOW = 30

MINIMUM_ANALYTICAL_OBSERVATIONS = 7
FULL_MATURITY_OBSERVATIONS = 30

MOMENTUM_DELTA_CAP = 10.0
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
        raise StrategicSuccessError(
            f"Input file does not exist: {path}"
        )

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


def write_json(
    path: Path,
    data: dict[str, Any],
) -> None:
    try:
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        temporary_path = path.with_suffix(
            path.suffix + ".tmp"
        )

        with temporary_path.open(
            "w",
            encoding="utf-8",
        ) as file:
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


def clamp(
    value: float,
    minimum: float,
    maximum: float,
) -> float:
    return max(
        minimum,
        min(maximum, value),
    )


def round_value(
    value: float,
    digits: int = 2,
) -> float:
    return round(
        float(value),
        digits,
    )


def safe_number(
    value: Any,
) -> float | None:
    if isinstance(value, bool):
        return None

    if isinstance(value, (int, float)):
        numeric_value = float(value)

        if math.isfinite(numeric_value):
            return numeric_value

    return None


def validate_date(
    value: Any,
) -> str | None:
    if not isinstance(value, str):
        return None

    date_value = value.strip()

    if not date_value:
        return None

    try:
        datetime.strptime(
            date_value,
            "%Y-%m-%d",
        )

    except ValueError:
        return None

    return date_value


def mean(
    values: list[float],
) -> float:
    if not values:
        return NEUTRAL_INDEX

    return statistics.fmean(values)


def median(
    values: list[float],
) -> float:
    if not values:
        return NEUTRAL_INDEX

    return statistics.median(values)


def population_standard_deviation(
    values: list[float],
) -> float:
    if len(values) <= 1:
        return 0.0

    return statistics.pstdev(values)


def calculate_data_maturity(
    observation_count: int,
) -> dict[str, Any]:
    if observation_count < MINIMUM_ANALYTICAL_OBSERVATIONS:
        status = "insufficient"
        confidence = 0.0
        is_provisional = True

    elif observation_count < FULL_MATURITY_OBSERVATIONS:
        status = "partial"

        confidence = (
            observation_count
            - MINIMUM_ANALYTICAL_OBSERVATIONS
        ) / (
            FULL_MATURITY_OBSERVATIONS
            - MINIMUM_ANALYTICAL_OBSERVATIONS
        )

        confidence = clamp(
            confidence,
            0.0,
            1.0,
        )

        is_provisional = True

    else:
        status = "full"
        confidence = 1.0
        is_provisional = False

    return {
        "status": status,
        "observations": observation_count,
        "minimum_observations": (
            MINIMUM_ANALYTICAL_OBSERVATIONS
        ),
        "full_maturity_observations": (
            FULL_MATURITY_OBSERVATIONS
        ),
        "confidence": round_value(confidence),
        "confidence_percent": round_value(
            confidence * 100.0
        ),
        "is_provisional": is_provisional,
    }


def shrink_toward_neutral(
    raw_score: float,
    confidence: float,
) -> float:
    adjusted_score = (
        NEUTRAL_INDEX
        + (
            raw_score - NEUTRAL_INDEX
        )
        * confidence
    )

    return clamp(
        adjusted_score,
        0.0,
        100.0,
    )


def get_actor_achievement(
    record: dict[str, Any],
    actor_id: str,
) -> float | None:
    actors = record.get("actors")

    if isinstance(actors, dict):
        actor_data = actors.get(actor_id)

        if isinstance(actor_data, dict):
            achievement_index = safe_number(
                actor_data.get(
                    "achievement_index"
                )
            )

            if achievement_index is not None:
                return clamp(
                    achievement_index,
                    0.0,
                    100.0,
                )

    summary = record.get("summary")

    if isinstance(summary, dict):
        summary_key = (
            f"{actor_id}_achievement_index"
        )

        achievement_index = safe_number(
            summary.get(summary_key)
        )

        if achievement_index is not None:
            return clamp(
                achievement_index,
                0.0,
                100.0,
            )

    return None


def extract_history(
    input_data: dict[str, Any],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    raw_history = input_data.get("history")

    if not isinstance(raw_history, list):
        raise StrategicSuccessError(
            "Interest Achievement does not contain "
            "a valid history[] array."
        )

    invalid_records: list[dict[str, Any]] = []
    records_by_date: dict[
        str,
        dict[str, Any],
    ] = {}

    for position, record in enumerate(raw_history):
        if not isinstance(record, dict):
            invalid_records.append(
                {
                    "position": position,
                    "reason": (
                        "History record is not "
                        "a JSON object."
                    ),
                    "record": record,
                }
            )
            continue

        date = validate_date(
            record.get("date")
        )

        if date is None:
            invalid_records.append(
                {
                    "position": position,
                    "reason": (
                        "History record has no valid "
                        "YYYY-MM-DD date."
                    ),
                    "record": record,
                }
            )
            continue

        missing_actors = [
            actor_id
            for actor_id in ACTOR_IDS
            if get_actor_achievement(
                record,
                actor_id,
            ) is None
        ]

        if missing_actors:
            invalid_records.append(
                {
                    "position": position,
                    "date": date,
                    "reason": (
                        "Missing valid achievement "
                        "index for: "
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
                        "Duplicate history date. "
                        "The later valid record "
                        "replaced the earlier record."
                    ),
                    "record": records_by_date[date],
                }
            )

        records_by_date[date] = record

    valid_records = [
        records_by_date[date]
        for date in sorted(records_by_date)
    ]

    if not valid_records:
        raise StrategicSuccessError(
            "Interest Achievement history "
            "contains no valid records."
        )

    return (
        valid_records,
        invalid_records,
    )


def extract_current(
    input_data: dict[str, Any],
) -> dict[str, Any]:
    current = input_data.get("current")

    if not isinstance(current, dict):
        raise StrategicSuccessError(
            "Interest Achievement does not contain "
            "a valid current block."
        )

    date = validate_date(
        current.get("date")
    )

    if date is None:
        raise StrategicSuccessError(
            "Interest Achievement current block "
            "has no valid date."
        )

    missing_actors = [
        actor_id
        for actor_id in ACTOR_IDS
        if get_actor_achievement(
            current,
            actor_id,
        ) is None
    ]

    if missing_actors:
        raise StrategicSuccessError(
            "Interest Achievement current block "
            "is missing valid indexes for: "
            + ", ".join(missing_actors)
        )

    return current


def calculate_momentum(
    achievement_series: list[float],
) -> dict[str, Any]:
    observation_count = len(
        achievement_series
    )

    maturity = calculate_data_maturity(
        observation_count
    )

    short_values = achievement_series[
        -MOMENTUM_SHORT_WINDOW:
    ]

    long_values = achievement_series[
        -MOMENTUM_LONG_WINDOW:
    ]

    short_average = mean(short_values)
    long_average = mean(long_values)

    raw_delta = (
        short_average
        - long_average
    )

    if (
        observation_count
        < MINIMUM_ANALYTICAL_OBSERVATIONS
    ):
        raw_score = NEUTRAL_INDEX
        adjusted_score = NEUTRAL_INDEX
        direction = "insufficient_data"

    else:
        capped_delta = clamp(
            raw_delta,
            -MOMENTUM_DELTA_CAP,
            MOMENTUM_DELTA_CAP,
        )

        raw_score = clamp(
            NEUTRAL_INDEX
            + (
                capped_delta
                / MOMENTUM_DELTA_CAP
                * NEUTRAL_INDEX
            ),
            0.0,
            100.0,
        )

        adjusted_score = shrink_toward_neutral(
            raw_score=raw_score,
            confidence=float(
                maturity["confidence"]
            ),
        )

        if raw_delta > 0.25:
            direction = "improving"

        elif raw_delta < -0.25:
            direction = "deteriorating"

        else:
            direction = "stable"

    return {
        "score": round_value(
            adjusted_score
        ),
        "raw_score": round_value(
            raw_score
        ),
        "direction": direction,
        "delta_7_vs_30": round_value(
            raw_delta
        ),
        "average_7_day": round_value(
            short_average
        ),
        "average_30_day": round_value(
            long_average
        ),
        "observations_7_day": len(
            short_values
        ),
        "observations_30_day": len(
            long_values
        ),
        "maturity_adjusted": (
            maturity["status"] != "full"
        ),
    }


def calculate_stability(
    achievement_series: list[float],
) -> dict[str, Any]:
    observation_count = len(
        achievement_series
    )

    maturity = calculate_data_maturity(
        observation_count
    )

    window_values = achievement_series[
        -STABILITY_WINDOW:
    ]

    standard_deviation = (
        population_standard_deviation(
            window_values
        )
    )

    raw_score = clamp(
        100.0
        - (
            standard_deviation
            / STABILITY_STANDARD_DEVIATION_CAP
            * 100.0
        ),
        0.0,
        100.0,
    )

    adjusted_score = shrink_toward_neutral(
        raw_score=raw_score,
        confidence=float(
            maturity["confidence"]
        ),
    )

    if adjusted_score >= 80.0:
        level = "high"

    elif adjusted_score >= 60.0:
        level = "moderate"

    elif adjusted_score >= 40.0:
        level = "low"

    else:
        level = "very_low"

    return {
        "score": round_value(
            adjusted_score
        ),
        "raw_score": round_value(
            raw_score
        ),
        "level": level,
        "standard_deviation": round_value(
            standard_deviation
        ),
        "window": STABILITY_WINDOW,
        "observations": len(
            window_values
        ),
        "maturity_adjusted": (
            maturity["status"] != "full"
        ),
    }


def calculate_consistency(
    achievement_series: list[float],
) -> dict[str, Any]:
    observation_count = len(
        achievement_series
    )

    maturity = calculate_data_maturity(
        observation_count
    )

    window_values = achievement_series[
        -CONSISTENCY_WINDOW:
    ]

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

    window_observations = len(
        window_values
    )

    if window_observations:
        raw_score = (
            positive_days
            / window_observations
            * 100.0
        )

    else:
        raw_score = NEUTRAL_INDEX

    adjusted_score = shrink_toward_neutral(
        raw_score=raw_score,
        confidence=float(
            maturity["confidence"]
        ),
    )

    if adjusted_score >= 75.0:
        level = "high"

    elif adjusted_score >= 50.0:
        level = "moderate"

    elif adjusted_score >= 25.0:
        level = "low"

    else:
        level = "very_low"

    return {
        "score": round_value(
            adjusted_score
        ),
        "raw_score": round_value(
            raw_score
        ),
        "level": level,
        "positive_days": positive_days,
        "neutral_days": neutral_days,
        "negative_days": negative_days,
        "window": CONSISTENCY_WINDOW,
        "observations": window_observations,
        "maturity_adjusted": (
            maturity["status"] != "full"
        ),
    }


def classify_success_level(
    success_index: float,
) -> str:
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
            "No achievement series available "
            f"for actor: {actor_id}"
        )

    observation_count = len(
        achievement_series
    )

    maturity = calculate_data_maturity(
        observation_count
    )

    achievement = achievement_series[-1]

    momentum = calculate_momentum(
        achievement_series
    )

    stability = calculate_stability(
        achievement_series
    )

    consistency = calculate_consistency(
        achievement_series
    )

    weighted_achievement = (
        achievement
        * ACHIEVEMENT_WEIGHT
    )

    weighted_momentum = (
        momentum["score"]
        * MOMENTUM_WEIGHT
    )

    weighted_stability = (
        stability["score"]
        * STABILITY_WEIGHT
    )

    weighted_consistency = (
        consistency["score"]
        * CONSISTENCY_WEIGHT
    )

    success_index = clamp(
        weighted_achievement
        + weighted_momentum
        + weighted_stability
        + weighted_consistency,
        0.0,
        100.0,
    )

    if maturity["status"] == "insufficient":
        publication_status = (
            "insufficient_data"
        )

    elif maturity["status"] == "partial":
        publication_status = "provisional"

    else:
        publication_status = "final"

    return {
        "success_index": round_value(
            success_index
        ),
        "level": classify_success_level(
            success_index
        ),
        "change_from_neutral": round_value(
            success_index
            - NEUTRAL_INDEX
        ),
        "publication_status": (
            publication_status
        ),
        "data_maturity": maturity,
        "components": {
            "achievement": {
                "value": round_value(
                    achievement
                ),
                "weight": (
                    ACHIEVEMENT_WEIGHT
                ),
                "weighted_contribution": (
                    round_value(
                        weighted_achievement
                    )
                ),
                "maturity_adjusted": False,
            },
            "momentum": {
                **momentum,
                "weight": MOMENTUM_WEIGHT,
                "weighted_contribution": (
                    round_value(
                        weighted_momentum
                    )
                ),
            },
            "stability": {
                **stability,
                "weight": STABILITY_WEIGHT,
                "weighted_contribution": (
                    round_value(
                        weighted_stability
                    )
                ),
            },
            "consistency": {
                **consistency,
                "weight": CONSISTENCY_WEIGHT,
                "weighted_contribution": (
                    round_value(
                        weighted_consistency
                    )
                ),
            },
        },
    }


def classify_advantage(
    success_gap: float,
) -> str:
    if success_gap >= 5.0:
        return "usa"

    if success_gap <= -5.0:
        return "iran"

    return "balanced"


def calculate_day(
    date: str,
    achievement_series_by_actor: dict[
        str,
        list[float],
    ],
) -> dict[str, Any]:
    actors = {
        actor_id: calculate_actor_success(
            actor_id,
            achievement_series_by_actor[
                actor_id
            ],
        )
        for actor_id in ACTOR_IDS
    }

    usa_success = actors[
        "usa"
    ]["success_index"]

    iran_success = actors[
        "iran"
    ]["success_index"]

    success_gap = round_value(
        usa_success
        - iran_success
    )

    strategic_advantage = (
        classify_advantage(
            success_gap
        )
    )

    observation_count = min(
        len(
            achievement_series_by_actor[
                actor_id
            ]
        )
        for actor_id in ACTOR_IDS
    )

    day_maturity = calculate_data_maturity(
        observation_count
    )

    if day_maturity["status"] == "insufficient":
        interpretation_status = (
            "insufficient_data"
        )

    elif day_maturity["status"] == "partial":
        interpretation_status = (
            "provisional"
        )

    else:
        interpretation_status = "full"

    return {
        "date": date,
        "summary": {
            "usa_success_index": (
                usa_success
            ),
            "iran_success_index": (
                iran_success
            ),
            "success_gap": (
                success_gap
            ),
            "strategic_balance": (
                round_value(
                    NEUTRAL_INDEX
                    + success_gap / 2.0
                )
            ),
            "strategic_advantage": (
                strategic_advantage
            ),
            "interpretation_status": (
                interpretation_status
            ),
            "is_provisional": (
                day_maturity[
                    "is_provisional"
                ]
            ),
            "interpretation": (
                "Strategic Success combines "
                "Interest Achievement, momentum, "
                "stability and consistency. "
                "Values with fewer than 30 "
                "observations are maturity-adjusted "
                "and should be treated as "
                "provisional."
            ),
        },
        "data_maturity": day_maturity,
        "actors": actors,
    }


def build_history(
    history_records: list[
        dict[str, Any]
    ],
) -> list[dict[str, Any]]:
    achievement_series_by_actor: dict[
        str,
        list[float],
    ] = {
        actor_id: []
        for actor_id in ACTOR_IDS
    }

    generated_history: list[
        dict[str, Any]
    ] = []

    for record in history_records:
        date = str(
            record["date"]
        )

        for actor_id in ACTOR_IDS:
            achievement = (
                get_actor_achievement(
                    record,
                    actor_id,
                )
            )

            if achievement is None:
                raise StrategicSuccessError(
                    "Missing achievement value "
                    f"for {actor_id} on {date}."
                )

            achievement_series_by_actor[
                actor_id
            ].append(achievement)

        generated_history.append(
            calculate_day(
                date=date,
                achievement_series_by_actor=(
                    achievement_series_by_actor
                ),
            )
        )

    return generated_history


def build_current(
    current_record: dict[str, Any],
    history_records: list[
        dict[str, Any]
    ],
) -> dict[str, Any]:
    current_date = str(
        current_record["date"]
    )

    achievement_series_by_actor: dict[
        str,
        list[float],
    ] = {
        actor_id: []
        for actor_id in ACTOR_IDS
    }

    current_date_found = False

    for record in history_records:
        record_date = str(
            record["date"]
        )

        if record_date > current_date:
            continue

        for actor_id in ACTOR_IDS:
            achievement = (
                get_actor_achievement(
                    record,
                    actor_id,
                )
            )

            if achievement is None:
                raise StrategicSuccessError(
                    "Missing achievement value "
                    f"for {actor_id} on "
                    f"{record_date}."
                )

            achievement_series_by_actor[
                actor_id
            ].append(achievement)

        if record_date == current_date:
            current_date_found = True

    for actor_id in ACTOR_IDS:
        current_achievement = (
            get_actor_achievement(
                current_record,
                actor_id,
            )
        )

        if current_achievement is None:
            raise StrategicSuccessError(
                "Missing current achievement "
                f"value for {actor_id}."
            )

        if current_date_found:
            achievement_series_by_actor[
                actor_id
            ][-1] = current_achievement

        else:
            achievement_series_by_actor[
                actor_id
            ].append(
                current_achievement
            )

    return calculate_day(
        date=current_date,
        achievement_series_by_actor=(
            achievement_series_by_actor
        ),
    )


def calculate_rolling_average(
    history: list[dict[str, Any]],
    actor_id: str,
    window: int,
) -> list[dict[str, Any]]:
    values: list[float] = []
    result: list[dict[str, Any]] = []

    for record in history:
        success_index = float(
            record[
                "actors"
            ][actor_id][
                "success_index"
            ]
        )

        values.append(
            success_index
        )

        window_values = values[
            -window:
        ]

        result.append(
            {
                "date": record["date"],
                "value": round_value(
                    mean(window_values)
                ),
                "window": window,
                "observations": len(
                    window_values
                ),
                "is_full_window": (
                    len(window_values)
                    >= window
                ),
            }
        )

    return result


def build_distribution(
    values: list[float],
) -> dict[str, Any]:
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

    if total_days == 0:
        return {
            "positive_days": 0,
            "neutral_days": 0,
            "negative_days": 0,
            "positive_share": 0.0,
            "neutral_share": 0.0,
            "negative_share": 0.0,
        }

    return {
        "positive_days": positive_days,
        "neutral_days": neutral_days,
        "negative_days": negative_days,
        "positive_share": round_value(
            positive_days
            / total_days
            * 100.0
        ),
        "neutral_share": round_value(
            neutral_days
            / total_days
            * 100.0
        ),
        "negative_share": round_value(
            negative_days
            / total_days
            * 100.0
        ),
    }


def build_period_statistics(
    dated_values: list[
        dict[str, Any]
    ],
) -> dict[str, Any] | None:
    if not dated_values:
        return None

    values = [
        float(item["value"])
        for item in dated_values
    ]

    best_day = max(
        dated_values,
        key=lambda item: item["value"],
    )

    worst_day = min(
        dated_values,
        key=lambda item: item["value"],
    )

    return {
        "day_count": len(
            dated_values
        ),
        "start_date": (
            dated_values[0]["date"]
        ),
        "end_date": (
            dated_values[-1]["date"]
        ),
        "average": round_value(
            mean(values)
        ),
        "median": round_value(
            median(values)
        ),
        "latest": round_value(
            values[-1]
        ),
        "change_first_to_latest": (
            round_value(
                values[-1]
                - values[0]
            )
        ),
        "best_day": {
            "date": best_day["date"],
            "value": round_value(
                best_day["value"]
            ),
        },
        "worst_day": {
            "date": worst_day["date"],
            "value": round_value(
                worst_day["value"]
            ),
        },
        "volatility": {
            "standard_deviation": (
                round_value(
                    population_standard_deviation(
                        values
                    )
                )
            )
        },
        "day_distribution": (
            build_distribution(values)
        ),
    }


def build_actor_summary(
    history: list[dict[str, Any]],
    actor_id: str,
) -> dict[str, Any]:
    all_dated_values = [
        {
            "date": record["date"],
            "value": float(
                record[
                    "actors"
                ][actor_id][
                    "success_index"
                ]
            ),
            "maturity_status": (
                record[
                    "actors"
                ][actor_id][
                    "data_maturity"
                ]["status"]
            ),
        }
        for record in history
    ]

    full_maturity_values = [
        item
        for item in all_dated_values
        if item["maturity_status"]
        == "full"
    ]

    partial_values = [
        item
        for item in all_dated_values
        if item["maturity_status"]
        == "partial"
    ]

    insufficient_values = [
        item
        for item in all_dated_values
        if item["maturity_status"]
        == "insufficient"
    ]

    all_period = build_period_statistics(
        all_dated_values
    )

    full_period = build_period_statistics(
        full_maturity_values
    )

    if all_period is None:
        raise StrategicSuccessError(
            "Could not build actor history "
            f"summary for {actor_id}."
        )

    return {
        **all_period,
        "maturity_distribution": {
            "insufficient_days": len(
                insufficient_values
            ),
            "partial_days": len(
                partial_values
            ),
            "full_days": len(
                full_maturity_values
            ),
        },
        "full_maturity_period": (
            full_period
        ),
        "rolling_averages": {
            "7_day": (
                calculate_rolling_average(
                    history,
                    actor_id,
                    7,
                )
            ),
            "30_day": (
                calculate_rolling_average(
                    history,
                    actor_id,
                    30,
                )
            ),
        },
    }


def build_history_summary(
    history: list[dict[str, Any]],
) -> dict[str, Any]:
    success_gaps = [
        float(
            record[
                "summary"
            ]["success_gap"]
        )
        for record in history
    ]

    usa_advantage_days = sum(
        1
        for record in history
        if record[
            "summary"
        ][
            "strategic_advantage"
        ] == "usa"
    )

    iran_advantage_days = sum(
        1
        for record in history
        if record[
            "summary"
        ][
            "strategic_advantage"
        ] == "iran"
    )

    balanced_days = sum(
        1
        for record in history
        if record[
            "summary"
        ][
            "strategic_advantage"
        ] == "balanced"
    )

    insufficient_days = sum(
        1
        for record in history
        if record[
            "data_maturity"
        ]["status"] == "insufficient"
    )

    partial_days = sum(
        1
        for record in history
        if record[
            "data_maturity"
        ]["status"] == "partial"
    )

    full_days = sum(
        1
        for record in history
        if record[
            "data_maturity"
        ]["status"] == "full"
    )

    full_records = [
        record
        for record in history
        if record[
            "data_maturity"
        ]["status"] == "full"
    ]

    full_success_gaps = [
        float(
            record[
                "summary"
            ]["success_gap"]
        )
        for record in full_records
    ]

    strategic_balance: dict[str, Any] = {
        "average_success_gap": (
            round_value(
                mean(success_gaps)
            )
        ),
        "latest_success_gap": (
            round_value(
                success_gaps[-1]
            )
        ),
        "usa_advantage_days": (
            usa_advantage_days
        ),
        "iran_advantage_days": (
            iran_advantage_days
        ),
        "balanced_days": (
            balanced_days
        ),
    }

    if full_success_gaps:
        strategic_balance[
            "full_maturity_average_success_gap"
        ] = round_value(
            mean(full_success_gaps)
        )

        strategic_balance[
            "full_maturity_day_count"
        ] = len(
            full_success_gaps
        )

    else:
        strategic_balance[
            "full_maturity_average_success_gap"
        ] = None

        strategic_balance[
            "full_maturity_day_count"
        ] = 0

    return {
        "day_count": len(history),
        "start_date": history[0]["date"],
        "end_date": history[-1]["date"],
        "maturity_distribution": {
            "insufficient_days": (
                insufficient_days
            ),
            "partial_days": (
                partial_days
            ),
            "full_days": full_days,
        },
        "actors": {
            actor_id: build_actor_summary(
                history,
                actor_id,
            )
            for actor_id in ACTOR_IDS
        },
        "strategic_balance": (
            strategic_balance
        ),
    }


def build_output(
    input_data: dict[str, Any],
    input_path: Path,
) -> dict[str, Any]:
    (
        history_records,
        invalid_history_records,
    ) = extract_history(
        input_data
    )

    current_record = extract_current(
        input_data
    )

    history = build_history(
        history_records
    )

    current = build_current(
        current_record=current_record,
        history_records=history_records,
    )

    history_summary = (
        build_history_summary(
            history
        )
    )

    input_metadata = input_data.get(
        "metadata"
    )

    if not isinstance(
        input_metadata,
        dict,
    ):
        input_metadata = {}

    warnings: list[str] = []

    current_date = current["date"]
    history_end_date = history[-1]["date"]

    if current_date != history_end_date:
        warnings.append(
            "The Interest Achievement current "
            "date does not match the last valid "
            "history date. Current was calculated "
            "separately using the current block "
            "and the available historical context."
        )

    if invalid_history_records:
        warnings.append(
            f"{len(invalid_history_records)} "
            "invalid or duplicate history "
            "record(s) were excluded from "
            "Strategic Success calculations."
        )

    current_maturity = current[
        "data_maturity"
    ]

    if current_maturity[
        "status"
    ] != "full":
        warnings.append(
            "Current Strategic Success is based "
            "on an incomplete historical window "
            "and must be treated as provisional."
        )

    input_model_version = (
        input_metadata.get(
            "model_version"
        )
        or input_metadata.get(
            "version"
        )
        or input_metadata.get(
            "methodology_version"
        )
        or "unknown"
    )

    return {
        "metadata": {
            "dataset": (
                "Strategic Success"
            ),
            "model_version": (
                MODEL_VERSION
            ),
            "generated_at": (
                datetime.now(
                    timezone.utc
                ).isoformat()
            ),
            "source_dataset": (
                "Interest Achievement"
            ),
            "input_file": str(
                input_path
            ),
            "input_model_version": (
                input_model_version
            ),
            "current_date": (
                current_date
            ),
            "history_start_date": (
                history[0]["date"]
            ),
            "history_end_date": (
                history_end_date
            ),
            "history_day_count": (
                len(history)
            ),
            "actors": list(
                ACTOR_IDS
            ),
            "current_data_maturity": (
                current_maturity["status"]
            ),
            "current_is_provisional": (
                current_maturity[
                    "is_provisional"
                ]
            ),
            "warning_count": (
                len(warnings)
            ),
        },
        "current": current,
        "history": history,
        "history_summary": (
            history_summary
        ),
        "diagnostics": {
            "excluded_history_records": (
                invalid_history_records
            ),
            "warnings": warnings,
            "counts": {
                "processed_history_days": (
                    len(history)
                ),
                "excluded_history_records": (
                    len(
                        invalid_history_records
                    )
                ),
                "warnings": (
                    len(warnings)
                ),
                "insufficient_maturity_days": (
                    history_summary[
                        "maturity_distribution"
                    ][
                        "insufficient_days"
                    ]
                ),
                "partial_maturity_days": (
                    history_summary[
                        "maturity_distribution"
                    ][
                        "partial_days"
                    ]
                ),
                "full_maturity_days": (
                    history_summary[
                        "maturity_distribution"
                    ][
                        "full_days"
                    ]
                ),
            },
        },
        "methodology": {
            "source_scope": (
                "Strategic Success is calculated "
                "exclusively from "
                "docs/interest_achievement.json. "
                "No Strategic Pressure or raw-event "
                "input is read directly."
            ),
            "formula": (
                "success_index = achievement × 0.50 "
                "+ maturity_adjusted_momentum × 0.20 "
                "+ maturity_adjusted_stability × 0.15 "
                "+ maturity_adjusted_consistency × 0.15"
            ),
            "weights": {
                "achievement": (
                    ACHIEVEMENT_WEIGHT
                ),
                "momentum": (
                    MOMENTUM_WEIGHT
                ),
                "stability": (
                    STABILITY_WEIGHT
                ),
                "consistency": (
                    CONSISTENCY_WEIGHT
                ),
            },
            "data_maturity": {
                "insufficient": {
                    "observation_range": (
                        "1–6"
                    ),
                    "confidence": 0.0,
                    "publication_status": (
                        "insufficient_data"
                    ),
                },
                "partial": {
                    "observation_range": (
                        "7–29"
                    ),
                    "confidence_formula": (
                        "(observations - 7) "
                        "/ (30 - 7)"
                    ),
                    "publication_status": (
                        "provisional"
                    ),
                },
                "full": {
                    "observation_range": (
                        "30 or more"
                    ),
                    "confidence": 1.0,
                    "publication_status": (
                        "final"
                    ),
                },
                "adjustment_formula": (
                    "adjusted_component_score = "
                    "50 + "
                    "(raw_component_score - 50) "
                    "× maturity_confidence"
                ),
                "purpose": (
                    "The adjustment prevents early "
                    "records from appearing highly "
                    "stable or consistent solely "
                    "because only a small number "
                    "of observations exists."
                ),
            },
            "achievement": (
                "The actor's Interest Achievement "
                "index for the given day. "
                "Achievement is not maturity-adjusted."
            ),
            "momentum": {
                "description": (
                    "Momentum compares the trailing "
                    "7-day Interest Achievement "
                    "average with the trailing "
                    "30-day average."
                ),
                "formula": (
                    "raw_momentum_score = clamp("
                    "50 + capped_delta / 10 × 50, "
                    "0, 100)"
                ),
                "short_window": (
                    MOMENTUM_SHORT_WINDOW
                ),
                "long_window": (
                    MOMENTUM_LONG_WINDOW
                ),
                "delta_cap": (
                    MOMENTUM_DELTA_CAP
                ),
                "neutral_score": (
                    NEUTRAL_INDEX
                ),
            },
            "stability": {
                "description": (
                    "Stability measures the trailing "
                    "30-day population standard "
                    "deviation of Interest "
                    "Achievement."
                ),
                "formula": (
                    "raw_stability_score = clamp("
                    "100 - standard_deviation "
                    "/ 10 × 100, 0, 100)"
                ),
                "window": (
                    STABILITY_WINDOW
                ),
                "standard_deviation_cap": (
                    STABILITY_STANDARD_DEVIATION_CAP
                ),
            },
            "consistency": {
                "description": (
                    "Consistency is the percentage "
                    "of days in the trailing 30-day "
                    "window on which Interest "
                    "Achievement was strictly above "
                    "the neutral value of 50."
                ),
                "formula": (
                    "raw_consistency_score = "
                    "positive_days / observations "
                    "× 100"
                ),
                "window": (
                    CONSISTENCY_WINDOW
                ),
                "neutral_value": (
                    NEUTRAL_INDEX
                ),
            },
            "strategic_balance": {
                "description": (
                    "The success gap is USA "
                    "Strategic Success minus Iran "
                    "Strategic Success."
                ),
                "advantage_threshold": 5.0,
            },
            "limitations": [
                (
                    "Strategic Success inherits "
                    "the assumptions and data "
                    "limitations of Interest "
                    "Achievement."
                ),
                (
                    "Records with fewer than "
                    "30 observations are maturity-"
                    "adjusted and provisional."
                ),
                (
                    "Stability measures regularity, "
                    "not whether the underlying "
                    "strategic result is positive."
                ),
                (
                    "The index is an analytical "
                    "indicator and does not directly "
                    "measure military victory, "
                    "political legitimacy or final "
                    "conflict outcome."
                ),
            ],
        },
    }


def main() -> int:
    args = parse_args()

    try:
        input_data = load_json(
            args.input
        )

        output_data = build_output(
            input_data=input_data,
            input_path=args.input,
        )

        write_json(
            args.output,
            output_data,
        )

    except StrategicSuccessError as exc:
        print(
            f"ERROR: {exc}",
            file=sys.stderr,
        )
        return 1

    current = output_data[
        "current"
    ]

    summary = current[
        "summary"
    ]

    maturity = current[
        "data_maturity"
    ]

    diagnostics = output_data[
        "diagnostics"
    ]["counts"]

    print(
        "Strategic Success generation completed."
    )

    print(
        f"Output: {args.output}"
    )

    print(
        f"Current date: {current['date']}"
    )

    print(
        "Current maturity: "
        f"{maturity['status']}"
    )

    print(
        "Current maturity confidence: "
        f"{maturity['confidence_percent']}%"
    )

    print(
        "History range: "
        f"{output_data['metadata']['history_start_date']} "
        "to "
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

    print(
        f"Success gap: {summary['success_gap']}"
    )

    print(
        "Strategic advantage: "
        f"{summary['strategic_advantage']}"
    )

    print(
        "Insufficient maturity days: "
        f"{diagnostics['insufficient_maturity_days']}"
    )

    print(
        "Partial maturity days: "
        f"{diagnostics['partial_maturity_days']}"
    )

    print(
        "Full maturity days: "
        f"{diagnostics['full_maturity_days']}"
    )

    print(
        "Excluded history records: "
        f"{diagnostics['excluded_history_records']}"
    )

    print(
        f"Warnings: {diagnostics['warnings']}"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
