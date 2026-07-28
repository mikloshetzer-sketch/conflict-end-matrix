#!/usr/bin/env python3
"""
Generate Strategic Interest Achievement scores for the US-Iran conflict.

Inputs:
    docs/strategic_pressure.json
    data/strategic/strategic_interests.json
    data/strategic/interest_impact_map.json

Output:
    docs/interest_achievement.json

Data flow:
    Strategic Pressure contributor
        ↓
    Strategic indicator
        ↓
    Indicator-to-interest impact mapping
        ↓
    Weighted strategic-interest contribution
        ↓
    Interest Achievement Index
        ↓
    Actor-level Strategic Achievement Index

The script reads all complete daily contributor sets from:

    days[].usa.contributors
    days[].iran.contributors

and uses current as a backwards-compatible fallback.

Suppressed duplicate evidence and bilateral duplicate mappings are preserved
in diagnostics but do not affect the achievement calculation.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


DEFAULT_PRESSURE_PATH = Path("docs/strategic_pressure.json")
DEFAULT_INTERESTS_PATH = Path(
    "data/strategic/strategic_interests.json"
)
DEFAULT_IMPACT_MAP_PATH = Path(
    "data/strategic/interest_impact_map.json"
)
DEFAULT_OUTPUT_PATH = Path("docs/interest_achievement.json")

MODEL_VERSION = "strategic_interest_achievement_v2"

ACTORS = ("usa", "iran")
PRESSURE_DIRECTIONS = (
    "increase_pressure",
    "decrease_pressure",
)

NEUTRAL_SCORE = 50.0
MIN_SCORE = 0.0
MAX_SCORE = 100.0

NORMALISATION_DIVISOR = 20.0
MAX_INDICATOR_STRENGTH = 20.0

LEVELS = (
    (80.0, "very_strong"),
    (65.0, "strong"),
    (55.0, "moderately_positive"),
    (45.0, "balanced"),
    (35.0, "moderately_negative"),
    (20.0, "weak"),
    (0.0, "very_weak"),
)


class InputDataError(ValueError):
    """Raised when an input file has an invalid structure."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate Strategic Interest Achievement scores "
            "from Strategic Pressure contributors."
        )
    )

    parser.add_argument(
        "--pressure",
        type=Path,
        default=DEFAULT_PRESSURE_PATH,
        help=(
            "Strategic Pressure JSON. "
            f"Default: {DEFAULT_PRESSURE_PATH}"
        ),
    )

    parser.add_argument(
        "--interests",
        type=Path,
        default=DEFAULT_INTERESTS_PATH,
        help=(
            "Strategic interests JSON. "
            f"Default: {DEFAULT_INTERESTS_PATH}"
        ),
    )

    parser.add_argument(
        "--impact-map",
        type=Path,
        default=DEFAULT_IMPACT_MAP_PATH,
        help=(
            "Indicator-to-interest impact map. "
            f"Default: {DEFAULT_IMPACT_MAP_PATH}"
        ),
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help=(
            "Generated output JSON. "
            f"Default: {DEFAULT_OUTPUT_PATH}"
        ),
    )

    parser.add_argument(
        "--normalisation-divisor",
        type=float,
        default=NORMALISATION_DIVISOR,
        help=(
            "Divisor controlling score sensitivity. "
            f"Default: {NORMALISATION_DIVISOR}"
        ),
    )

    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise InputDataError(
            f"Input file does not exist: {path}"
        )

    try:
        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)

    except json.JSONDecodeError as exc:
        raise InputDataError(
            f"Invalid JSON in {path}: "
            f"line {exc.lineno}, column {exc.colno}"
        ) from exc

    except OSError as exc:
        raise InputDataError(
            f"Unable to read {path}: {exc}"
        ) from exc

    if not isinstance(data, dict):
        raise InputDataError(
            f"Top-level JSON value must be an object: {path}"
        )

    return data


def write_json(
    path: Path,
    data: Mapping[str, Any],
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary_path = path.with_suffix(
        path.suffix + ".tmp"
    )

    try:
        with temporary_path.open(
            "w",
            encoding="utf-8",
        ) as file:
            json.dump(
                data,
                file,
                ensure_ascii=False,
                indent=2,
            )
            file.write("\n")

        temporary_path.replace(path)

    except OSError as exc:
        raise InputDataError(
            f"Unable to write {path}: {exc}"
        ) from exc


def clean_text(value: Any) -> str:
    if value is None:
        return ""

    return " ".join(
        str(value).strip().split()
    )


def as_float(
    value: Any,
    default: float = 0.0,
) -> float:
    if isinstance(value, bool):
        return default

    if isinstance(value, (int, float)):
        result = float(value)

        if math.isfinite(result):
            return result

        return default

    if isinstance(value, str):
        try:
            result = float(value.strip())

            if math.isfinite(result):
                return result

        except ValueError:
            pass

    return default


def clamp(
    value: float,
    minimum: float,
    maximum: float,
) -> float:
    return max(
        minimum,
        min(maximum, value),
    )


def utc_now_iso() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat(timespec="seconds")


def score_level(score: float) -> str:
    for threshold, level in LEVELS:
        if score >= threshold:
            return level

    return "very_weak"


def score_trend(
    score: float,
) -> str:
    difference = score - NEUTRAL_SCORE

    if difference >= 2.0:
        return "improving"

    if difference <= -2.0:
        return "deteriorating"

    return "stable"


def contribution_trend(
    contribution: float,
) -> str:
    if contribution > 0.5:
        return "improving"

    if contribution < -0.5:
        return "deteriorating"

    return "stable"


def unique_strings(
    values: Sequence[str],
) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()

    for value in values:
        text = clean_text(value)

        if not text:
            continue

        if text in seen:
            continue

        seen.add(text)
        output.append(text)

    return output


def extract_version(
    data: Mapping[str, Any],
) -> str:
    direct_candidates = (
        data.get("model"),
        data.get("version"),
        data.get("model_version"),
    )

    for candidate in direct_candidates:
        text = clean_text(candidate)

        if text:
            return text

    metadata = data.get("metadata")

    if isinstance(metadata, Mapping):
        metadata_candidates = (
            metadata.get("model"),
            metadata.get("version"),
            metadata.get("model_version"),
        )

        for candidate in metadata_candidates:
            text = clean_text(candidate)

            if text:
                return text

    return ""


def extract_reference_date(
    pressure_data: Mapping[str, Any],
) -> str:
    candidates: list[Any] = [
        pressure_data.get("latest_complete_utc_day"),
        pressure_data.get("reference_date"),
        pressure_data.get("date"),
    ]

    current = pressure_data.get("current")

    if isinstance(current, Mapping):
        candidates.extend(
            [
                current.get("date"),
                current.get("reference_date"),
            ]
        )

    for candidate in candidates:
        text = clean_text(candidate)

        if text:
            return text[:10]

    return ""


def build_interest_catalog(
    interests_data: Mapping[str, Any],
) -> dict[str, dict[str, dict[str, Any]]]:
    actors_data = interests_data.get("actors")

    if not isinstance(actors_data, Mapping):
        raise InputDataError(
            "Strategic interests JSON must contain "
            "an 'actors' object."
        )

    catalog: dict[
        str,
        dict[str, dict[str, Any]],
    ] = {}

    for actor in ACTORS:
        actor_data = actors_data.get(actor)

        if not isinstance(actor_data, Mapping):
            raise InputDataError(
                f"Strategic interests missing actor: {actor}"
            )

        interests = actor_data.get("interests")

        if not isinstance(interests, list):
            raise InputDataError(
                f"Actor '{actor}' must contain "
                "an interests array."
            )

        actor_catalog: dict[
            str,
            dict[str, Any],
        ] = {}

        for position, interest in enumerate(interests):
            if not isinstance(interest, Mapping):
                raise InputDataError(
                    f"Invalid interest entry for actor "
                    f"'{actor}' at index {position}."
                )

            interest_id = clean_text(
                interest.get("id")
            )

            if not interest_id:
                raise InputDataError(
                    f"Interest at '{actor}[{position}]' "
                    "does not contain an id."
                )

            if interest_id in actor_catalog:
                raise InputDataError(
                    f"Duplicate strategic interest: "
                    f"{actor}.{interest_id}"
                )

            weight = as_float(
                interest.get("weight")
            )

            if weight <= 0:
                raise InputDataError(
                    f"Interest '{actor}.{interest_id}' "
                    "must have a positive weight."
                )

            actor_catalog[interest_id] = {
                "id": interest_id,
                "name": clean_text(
                    interest.get("name")
                ) or interest_id,
                "description": clean_text(
                    interest.get("description")
                ),
                "weight": weight,
            }

        if not actor_catalog:
            raise InputDataError(
                f"No strategic interests found for {actor}."
            )

        catalog[actor] = actor_catalog

    return catalog


def build_impact_lookup(
    impact_map_data: Mapping[str, Any],
    interest_catalog: Mapping[
        str,
        Mapping[str, Mapping[str, Any]],
    ],
) -> tuple[
    dict[
        tuple[str, str, str],
        list[dict[str, Any]],
    ],
    list[str],
]:
    indicator_impacts = impact_map_data.get(
        "indicator_impacts"
    )

    if not isinstance(indicator_impacts, Mapping):
        raise InputDataError(
            "Interest impact map must contain "
            "'indicator_impacts'."
        )

    lookup: dict[
        tuple[str, str, str],
        list[dict[str, Any]],
    ] = {}

    warnings: list[str] = []

    for source_actor in ACTORS:
        actor_impacts = indicator_impacts.get(
            source_actor
        )

        if not isinstance(actor_impacts, Mapping):
            warnings.append(
                f"Missing impact map actor: {source_actor}"
            )
            continue

        for direction in PRESSURE_DIRECTIONS:
            direction_impacts = actor_impacts.get(
                direction
            )

            if not isinstance(
                direction_impacts,
                Mapping,
            ):
                warnings.append(
                    f"Missing impact group: "
                    f"{source_actor}.{direction}"
                )
                continue

            for indicator_id, definition in (
                direction_impacts.items()
            ):
                indicator_id = clean_text(
                    indicator_id
                )

                if not indicator_id:
                    continue

                if not isinstance(
                    definition,
                    Mapping,
                ):
                    warnings.append(
                        f"Invalid mapping definition: "
                        f"{source_actor}.{direction}."
                        f"{indicator_id}"
                    )
                    continue

                impacts = definition.get("impacts")

                if not isinstance(impacts, list):
                    warnings.append(
                        f"Missing impacts array: "
                        f"{source_actor}.{direction}."
                        f"{indicator_id}"
                    )
                    continue

                validated: list[
                    dict[str, Any]
                ] = []

                for impact in impacts:
                    if not isinstance(
                        impact,
                        Mapping,
                    ):
                        continue

                    target_actor = clean_text(
                        impact.get("actor")
                    ).lower()

                    interest_id = clean_text(
                        impact.get("interest_id")
                    )

                    effect = as_float(
                        impact.get("effect")
                    )

                    if target_actor not in ACTORS:
                        warnings.append(
                            f"Unknown target actor "
                            f"'{target_actor}' in "
                            f"{source_actor}.{direction}."
                            f"{indicator_id}"
                        )
                        continue

                    if interest_id not in (
                        interest_catalog[target_actor]
                    ):
                        warnings.append(
                            f"Unknown strategic interest "
                            f"'{target_actor}.{interest_id}' "
                            f"in mapping "
                            f"{source_actor}.{direction}."
                            f"{indicator_id}"
                        )
                        continue

                    if effect == 0:
                        continue

                    validated.append(
                        {
                            "actor": target_actor,
                            "interest_id": interest_id,
                            "effect": effect,
                            "rationale": clean_text(
                                impact.get("rationale")
                            ),
                        }
                    )

                lookup[
                    (
                        source_actor,
                        direction,
                        indicator_id,
                    )
                ] = validated

    return lookup, warnings


def extract_daily_contributors(
    daily_data: Mapping[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(daily_data, Mapping):
        raise InputDataError(
            "Strategic Pressure daily assessment must be an object."
        )

    output: dict[
        str,
        list[dict[str, Any]],
    ] = {}

    for actor in ACTORS:
        actor_data = daily_data.get(actor)

        if not isinstance(actor_data, Mapping):
            raise InputDataError(
                f"Strategic Pressure daily section "
                f"is missing actor '{actor}'."
            )

        contributors = actor_data.get(
            "contributors"
        )

        if contributors is None:
            contributors = []

        if not isinstance(contributors, list):
            raise InputDataError(
                f"daily.{actor}.contributors "
                "must be an array."
            )

        output[actor] = [
            dict(item)
            for item in contributors
            if isinstance(item, Mapping)
        ]

    return output


def build_indicator_lookup(
    contributor: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    indicators = contributor.get("indicators")

    if not isinstance(indicators, list):
        return {}

    lookup: dict[
        str,
        dict[str, Any],
    ] = {}

    for indicator in indicators:
        if not isinstance(indicator, Mapping):
            continue

        indicator_id = clean_text(
            indicator.get("id")
        )

        if not indicator_id:
            continue

        lookup[indicator_id] = dict(indicator)

    return lookup


def extract_selected_indicators(
    contributor: Mapping[str, Any],
) -> list[str]:
    winning = contributor.get(
        "winning_daily_indicators"
    )

    selected: list[str] = []

    if isinstance(winning, list):
        selected.extend(
            clean_text(item)
            for item in winning
            if clean_text(item)
        )

    primary = clean_text(
        contributor.get(
            "primary_daily_indicator"
        )
    )

    if primary:
        selected.append(primary)

    selected = unique_strings(selected)

    if selected:
        return selected

    indicator_lookup = build_indicator_lookup(
        contributor
    )

    return list(indicator_lookup.keys())


def resolve_indicator_direction(
    indicator_data: Mapping[str, Any],
    final_score: float,
) -> str:
    direction = clean_text(
        indicator_data.get("direction")
    ).lower()

    increase_aliases = {
        "increase",
        "increasing",
        "increase_pressure",
        "escalation",
        "escalatory",
        "positive",
    }

    decrease_aliases = {
        "decrease",
        "decreasing",
        "decrease_pressure",
        "de-escalation",
        "de_escalation",
        "deescalation",
        "negative",
    }

    if direction in increase_aliases:
        return "increase_pressure"

    if direction in decrease_aliases:
        return "decrease_pressure"

    if final_score < 0:
        return "decrease_pressure"

    return "increase_pressure"


def contributor_is_suppressed(
    contributor: Mapping[str, Any],
) -> bool:
    if contributor.get(
        "daily_score_suppressed"
    ) is True:
        return True

    final_score = as_float(
        contributor.get("final_score")
    )

    original_score = as_float(
        contributor.get("original_final_score")
    )

    if final_score == 0 and original_score != 0:
        return True

    return False


def calculate_assessment(
    daily_data: Mapping[str, Any],
    assessment_date: str,
    interest_catalog: Mapping[
        str,
        Mapping[str, Mapping[str, Any]],
    ],
    impact_lookup: Mapping[
        tuple[str, str, str],
        Sequence[Mapping[str, Any]],
    ],
    normalisation_divisor: float,
) -> tuple[dict[str, Any], list[str], dict[str, Any]]:
    if normalisation_divisor <= 0:
        raise InputDataError(
            "Normalisation divisor must be greater "
            "than zero."
        )

    contributors_by_actor = (
        extract_daily_contributors(
            daily_data
        )
    )

    warnings: list[str] = []

    interest_contributions: dict[
        str,
        dict[str, list[dict[str, Any]]],
    ] = {
        actor: {
            interest_id: []
            for interest_id in (
                interest_catalog[actor]
            )
        }
        for actor in ACTORS
    }

    processed_evidence: list[
        dict[str, Any]
    ] = []

    suppressed_evidence: list[
        dict[str, Any]
    ] = []

    unmapped_evidence: list[
        dict[str, Any]
    ] = []

    bilateral_duplicates: list[dict[str, Any]] = []
    used_interest_evidence: set[tuple[str, str, str, str]] = set()

    for source_actor in ACTORS:
        contributors = contributors_by_actor[
            source_actor
        ]

        for contributor in contributors:
            final_score = as_float(
                contributor.get("final_score")
            )

            original_score = as_float(
                contributor.get(
                    "original_final_score"
                )
            )

            suppressed = contributor_is_suppressed(
                contributor
            )

            base_record = {
                "event_id": clean_text(
                    contributor.get("event_id")
                ),
                "timestamp": clean_text(
                    contributor.get("timestamp")
                ),
                "date": clean_text(
                    contributor.get("date")
                ) or assessment_date,
                "source_actor": source_actor,
                "title": clean_text(
                    contributor.get("title")
                ),
                "event_type": clean_text(
                    contributor.get("event_type")
                ),
                "event_direction": clean_text(
                    contributor.get(
                        "event_direction"
                    )
                ),
                "source_layer": clean_text(
                    contributor.get("source_layer")
                ),
                "final_score": final_score,
                "original_final_score": (
                    original_score
                ),
                "operational_component": as_float(
                    contributor.get(
                        "operational_component"
                    )
                ),
                "strategic_modifier": as_float(
                    contributor.get(
                        "strategic_modifier"
                    )
                ),
                "reason": clean_text(
                    contributor.get("reason")
                ),
                "source": clean_text(
                    contributor.get("source")
                ),
                "link": clean_text(
                    contributor.get("link")
                ),
                "daily_score_suppressed": (
                    suppressed
                ),
                "suppression_reason": clean_text(
                    contributor.get(
                        "suppression_reason"
                    )
                ),
            }

            if suppressed:
                suppressed_evidence.append(
                    {
                        **base_record,
                        "indicators": (
                            extract_selected_indicators(
                                contributor
                            )
                        ),
                    }
                )
                continue

            if final_score == 0:
                warnings.append(
                    f"Contributor "
                    f"'{base_record['event_id']}' "
                    "has final_score 0 and was skipped."
                )
                continue

            indicator_lookup = (
                build_indicator_lookup(
                    contributor
                )
            )

            selected_indicators = (
                extract_selected_indicators(
                    contributor
                )
            )

            if not selected_indicators:
                warnings.append(
                    f"No strategic indicator found "
                    f"for contributor "
                    f"'{base_record['event_id']}'."
                )

                unmapped_evidence.append(
                    {
                        **base_record,
                        "warning": (
                            "No strategic indicator "
                            "found."
                        ),
                    }
                )
                continue

            evidence_record = {
                **base_record,
                "mapped_indicators": [],
            }

            contributor_has_mapping = False

            for indicator_id in selected_indicators:
                indicator_data = (
                    indicator_lookup.get(
                        indicator_id,
                        {},
                    )
                )

                direction = (
                    resolve_indicator_direction(
                        indicator_data,
                        final_score,
                    )
                )

                mapping_key = (
                    source_actor,
                    direction,
                    indicator_id,
                )

                impacts = impact_lookup.get(
                    mapping_key
                )

                indicator_score = as_float(
                    indicator_data.get("score"),
                    default=final_score,
                )

                if indicator_score == 0:
                    indicator_score = final_score

                indicator_strength = clamp(
                    abs(indicator_score),
                    0.0,
                    MAX_INDICATOR_STRENGTH,
                )

                indicator_record = {
                    "indicator": indicator_id,
                    "indicator_name": clean_text(
                        indicator_data.get("name")
                    ) or indicator_id,
                    "pressure_direction": direction,
                    "indicator_score": (
                        indicator_score
                    ),
                    "indicator_strength": (
                        indicator_strength
                    ),
                    "mapped_impacts": [],
                }

                if not impacts:
                    warning = (
                        "No interest impact mapping "
                        f"found for {source_actor}."
                        f"{direction}.{indicator_id}."
                    )

                    warnings.append(warning)

                    unmapped_evidence.append(
                        {
                            **base_record,
                            "indicator": indicator_id,
                            "pressure_direction": (
                                direction
                            ),
                            "warning": warning,
                        }
                    )

                    evidence_record[
                        "mapped_indicators"
                    ].append(indicator_record)

                    continue

                contributor_has_mapping = True

                for impact in impacts:
                    target_actor = clean_text(
                        impact.get("actor")
                    ).lower()

                    interest_id = clean_text(
                        impact.get("interest_id")
                    )

                    effect = as_float(
                        impact.get("effect")
                    )

                    interest = (
                        interest_catalog[
                            target_actor
                        ][interest_id]
                    )

                    interest_weight = as_float(
                        interest.get("weight")
                    )

                    raw_contribution = (
                        indicator_strength
                        * effect
                        * interest_weight
                    )

                    contribution_record = {
                        "event_id": (
                            base_record["event_id"]
                        ),
                        "date": base_record["date"],
                        "source_actor": source_actor,
                        "indicator": indicator_id,
                        "pressure_direction": (
                            direction
                        ),
                        "indicator_score": round(
                            indicator_score,
                            4,
                        ),
                        "indicator_strength": round(
                            indicator_strength,
                            4,
                        ),
                        "effect": round(
                            effect,
                            4,
                        ),
                        "interest_weight": round(
                            interest_weight,
                            4,
                        ),
                        "raw_contribution": round(
                            raw_contribution,
                            4,
                        ),
                        "rationale": clean_text(
                            impact.get("rationale")
                        ),
                        "title": (
                            base_record["title"]
                        ),
                        "reason": (
                            base_record["reason"]
                        ),
                        "source": (
                            base_record["source"]
                        ),
                        "link": base_record["link"],
                    }

                    dedup_key = (
                        base_record["date"],
                        base_record["event_id"],
                        target_actor,
                        interest_id,
                    )

                    if dedup_key in used_interest_evidence:
                        duplicate_record = {
                            **contribution_record,
                            "target_actor": target_actor,
                            "interest_id": interest_id,
                            "deduplication_key": {
                                "date": dedup_key[0],
                                "event_id": dedup_key[1],
                                "target_actor": dedup_key[2],
                                "interest_id": dedup_key[3],
                            },
                            "suppression_reason": (
                                "Duplicate event-to-interest evidence "
                                "within the same day."
                            ),
                        }
                        bilateral_duplicates.append(duplicate_record)
                        indicator_record["mapped_impacts"].append(
                            {
                                "target_actor": target_actor,
                                "interest_id": interest_id,
                                "effect": round(effect, 4),
                                "interest_weight": round(interest_weight, 4),
                                "raw_contribution": 0.0,
                                "original_raw_contribution": round(
                                    raw_contribution, 4
                                ),
                                "suppressed": True,
                                "rationale": clean_text(
                                    impact.get("rationale")
                                ),
                            }
                        )
                        continue

                    used_interest_evidence.add(dedup_key)
                    interest_contributions[
                        target_actor
                    ][interest_id].append(
                        contribution_record
                    )

                    indicator_record[
                        "mapped_impacts"
                    ].append(
                        {
                            "target_actor": (
                                target_actor
                            ),
                            "interest_id": (
                                interest_id
                            ),
                            "effect": round(
                                effect,
                                4,
                            ),
                            "interest_weight": round(
                                interest_weight,
                                4,
                            ),
                            "raw_contribution": round(
                                raw_contribution,
                                4,
                            ),
                            "rationale": clean_text(
                                impact.get(
                                    "rationale"
                                )
                            ),
                        }
                    )

                evidence_record[
                    "mapped_indicators"
                ].append(indicator_record)

            if contributor_has_mapping:
                processed_evidence.append(
                    evidence_record
                )

    actor_results: dict[str, Any] = {}

    for actor in ACTORS:
        interest_results: list[
            dict[str, Any]
        ] = []

        weighted_index_total = 0.0
        total_weight = 0.0
        actor_raw_contribution = 0.0

        for interest_id, interest in (
            interest_catalog[actor].items()
        ):
            contributions = (
                interest_contributions[
                    actor
                ][interest_id]
            )

            raw_contribution = sum(
                as_float(
                    item.get(
                        "raw_contribution"
                    )
                )
                for item in contributions
            )

            positive_contribution = sum(
                max(
                    0.0,
                    as_float(
                        item.get(
                            "raw_contribution"
                        )
                    ),
                )
                for item in contributions
            )

            negative_contribution = sum(
                min(
                    0.0,
                    as_float(
                        item.get(
                            "raw_contribution"
                        )
                    ),
                )
                for item in contributions
            )

            achievement_index = clamp(
                NEUTRAL_SCORE
                + (
                    raw_contribution
                    / normalisation_divisor
                ),
                MIN_SCORE,
                MAX_SCORE,
            )

            sorted_evidence = sorted(
                contributions,
                key=lambda item: abs(
                    as_float(
                        item.get(
                            "raw_contribution"
                        )
                    )
                ),
                reverse=True,
            )

            weight = as_float(
                interest.get("weight")
            )

            interest_result = {
                "id": interest_id,
                "name": interest["name"],
                "description": (
                    interest["description"]
                ),
                "weight": weight,
                "achievement_index": round(
                    achievement_index,
                    2,
                ),
                "change_from_neutral": round(
                    achievement_index
                    - NEUTRAL_SCORE,
                    2,
                ),
                "raw_contribution": round(
                    raw_contribution,
                    4,
                ),
                "positive_contribution": round(
                    positive_contribution,
                    4,
                ),
                "negative_contribution": round(
                    negative_contribution,
                    4,
                ),
                "trend": contribution_trend(
                    raw_contribution
                ),
                "level": score_level(
                    achievement_index
                ),
                "evidence_count": len(
                    contributions
                ),
                "top_evidence": (
                    sorted_evidence[:5]
                ),
                "evidence": sorted_evidence,
            }

            interest_results.append(
                interest_result
            )

            weighted_index_total += (
                achievement_index * weight
            )

            total_weight += weight

            actor_raw_contribution += (
                raw_contribution
            )

        actor_index = (
            weighted_index_total
            / total_weight
            if total_weight > 0
            else NEUTRAL_SCORE
        )

        strongest = sorted(
            interest_results,
            key=lambda item: as_float(
                item.get(
                    "change_from_neutral"
                )
            ),
            reverse=True,
        )[:3]

        weakest = sorted(
            interest_results,
            key=lambda item: as_float(
                item.get(
                    "change_from_neutral"
                )
            ),
        )[:3]

        actor_results[actor] = {
            "achievement_index": round(
                actor_index,
                2,
            ),
            "change_from_neutral": round(
                actor_index - NEUTRAL_SCORE,
                2,
            ),
            "trend": score_trend(
                actor_index
            ),
            "level": score_level(
                actor_index
            ),
            "raw_contribution": round(
                actor_raw_contribution,
                4,
            ),
            "interest_count": len(
                interest_results
            ),
            "interests_with_evidence": sum(
                1
                for item in interest_results
                if item["evidence_count"] > 0
            ),
            "strongest_interests": [
                {
                    "id": item["id"],
                    "name": item["name"],
                    "achievement_index": (
                        item[
                            "achievement_index"
                        ]
                    ),
                    "change_from_neutral": (
                        item[
                            "change_from_neutral"
                        ]
                    ),
                }
                for item in strongest
            ],
            "weakest_interests": [
                {
                    "id": item["id"],
                    "name": item["name"],
                    "achievement_index": (
                        item[
                            "achievement_index"
                        ]
                    ),
                    "change_from_neutral": (
                        item[
                            "change_from_neutral"
                        ]
                    ),
                }
                for item in weakest
            ],
            "interests": interest_results,
        }

    usa_index = as_float(
        actor_results["usa"].get(
            "achievement_index"
        ),
        NEUTRAL_SCORE,
    )

    iran_index = as_float(
        actor_results["iran"].get(
            "achievement_index"
        ),
        NEUTRAL_SCORE,
    )

    achievement_gap = (
        usa_index - iran_index
    )

    if achievement_gap >= 3.0:
        strategic_advantage = "usa"

    elif achievement_gap <= -3.0:
        strategic_advantage = "iran"

    else:
        strategic_advantage = "balanced"

    summary = {
        "usa_achievement_index": round(
            usa_index,
            2,
        ),
        "iran_achievement_index": round(
            iran_index,
            2,
        ),
        "achievement_gap": round(
            achievement_gap,
            2,
        ),
        "daily_strategic_advantage": (
            strategic_advantage
        ),
        "interpretation": (
            "The index measures whether the current "
            "day's detected developments support or "
            "weaken each actor's own weighted strategic "
            "interests. It does not directly measure "
            "military victory or conflict outcome."
        ),
    }

    calculation = {
        "neutral_score": NEUTRAL_SCORE,
        "minimum_score": MIN_SCORE,
        "maximum_score": MAX_SCORE,
        "normalisation_divisor": (
            normalisation_divisor
        ),
        "indicator_strength_cap": (
            MAX_INDICATOR_STRENGTH
        ),
        "formula": (
            "raw_contribution = "
            "absolute_indicator_score × "
            "mapped_interest_effect × "
            "interest_weight; "
            "interest_index = clamp("
            "50 + raw_contribution / "
            "normalisation_divisor, 0, 100); "
            "actor_index = interest-weighted mean "
            "of the actor's interest indices"
        ),
    }

    assessment = {
        "summary": summary,
        "actors": actor_results,
        "processed_evidence": (
            processed_evidence
        ),
        "suppressed_evidence": (
            suppressed_evidence
        ),
        "unmapped_evidence": (
            unmapped_evidence
        ),
        "calculation": calculation,
    }

    diagnostics = {
        "suppressed_evidence": suppressed_evidence,
        "bilateral_duplicates": bilateral_duplicates,
        "unmapped_indicators": unmapped_evidence,
        "warnings": unique_strings(warnings),
        "counts": {
            "processed_evidence": len(processed_evidence),
            "suppressed_evidence": len(suppressed_evidence),
            "bilateral_duplicates": len(bilateral_duplicates),
            "unmapped_indicators": len(unmapped_evidence),
            "warnings": len(unique_strings(warnings)),
        },
    }

    return assessment, warnings, diagnostics


def extract_history_days(
    pressure_data: Mapping[str, Any],
) -> list[dict[str, Any]]:
    days = pressure_data.get("days")
    output: list[dict[str, Any]] = []

    if isinstance(days, list):
        for position, day in enumerate(days):
            if not isinstance(day, Mapping):
                continue
            date = clean_text(day.get("date"))[:10]
            if not date:
                date = f"undated-{position:04d}"
            output.append({"date": date, "data": dict(day)})

    if output:
        output.sort(key=lambda item: item["date"])
        return output

    current = pressure_data.get("current")
    if isinstance(current, Mapping):
        date = clean_text(current.get("date"))[:10]
        if not date:
            date = extract_reference_date(pressure_data)
        return [{"date": date, "data": dict(current)}]

    raise InputDataError(
        "Strategic Pressure JSON contains neither a valid days[] "
        "history nor a valid current object."
    )


def linear_trend(values: Sequence[float]) -> dict[str, Any]:
    if len(values) < 2:
        return {"direction": "stable", "slope": 0.0}
    n = len(values)
    x_mean = (n - 1) / 2.0
    y_mean = sum(values) / n
    denominator = sum((i - x_mean) ** 2 for i in range(n))
    slope = (
        sum((i - x_mean) * (value - y_mean) for i, value in enumerate(values))
        / denominator
        if denominator
        else 0.0
    )
    if slope > 0.05:
        direction = "improving"
    elif slope < -0.05:
        direction = "deteriorating"
    else:
        direction = "stable"
    return {"direction": direction, "slope": round(slope, 4)}


def rolling_average(
    dated_values: Sequence[tuple[str, float]],
    window: int,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for index, (date, _) in enumerate(dated_values):
        start = max(0, index - window + 1)
        values = [value for _, value in dated_values[start:index + 1]]
        result.append({
            "date": date,
            "value": round(sum(values) / len(values), 2),
            "window": window,
            "observations": len(values),
        })
    return result


def build_history_summary(
    history: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    summary: dict[str, Any] = {"day_count": len(history), "actors": {}}
    for actor in ACTORS:
        dated_values = [
            (
                clean_text(day.get("date")),
                as_float(
                    day.get("actors", {}).get(actor, {}).get(
                        "achievement_index"
                    ),
                    NEUTRAL_SCORE,
                ),
            )
            for day in history
            if isinstance(day.get("actors"), Mapping)
        ]
        values = [value for _, value in dated_values]
        if not values:
            continue
        best_date, best_value = max(dated_values, key=lambda item: item[1])
        worst_date, worst_value = min(dated_values, key=lambda item: item[1])
        summary["actors"][actor] = {
            "average": round(sum(values) / len(values), 2),
            "median": round(statistics.median(values), 2),
            "best_day": {"date": best_date, "value": round(best_value, 2)},
            "worst_day": {"date": worst_date, "value": round(worst_value, 2)},
            "rolling_averages": {
                "7_day": rolling_average(dated_values, 7),
                "30_day": rolling_average(dated_values, 30),
            },
            "trend": linear_trend(values),
            "volatility": round(
                statistics.pstdev(values) if len(values) > 1 else 0.0,
                4,
            ),
            "latest": round(values[-1], 2),
            "change_first_to_latest": round(values[-1] - values[0], 2),
        }
    return summary


def merge_diagnostics(
    daily_diagnostics: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    merged = {
        "suppressed_evidence": [],
        "bilateral_duplicates": [],
        "unmapped_indicators": [],
        "warnings": [],
    }
    for item in daily_diagnostics:
        date = clean_text(item.get("date"))
        diagnostics = item.get("diagnostics")
        if not isinstance(diagnostics, Mapping):
            continue
        for key in (
            "suppressed_evidence",
            "bilateral_duplicates",
            "unmapped_indicators",
        ):
            values = diagnostics.get(key)
            if isinstance(values, list):
                merged[key].extend(
                    {"assessment_date": date, **dict(value)}
                    for value in values
                    if isinstance(value, Mapping)
                )
        warnings = diagnostics.get("warnings")
        if isinstance(warnings, list):
            merged["warnings"].extend(
                f"{date}: {clean_text(value)}"
                for value in warnings
                if clean_text(value)
            )
    merged["warnings"] = unique_strings(merged["warnings"])
    merged["counts"] = {
        "suppressed_evidence": len(merged["suppressed_evidence"]),
        "bilateral_duplicates": len(merged["bilateral_duplicates"]),
        "unmapped_indicators": len(merged["unmapped_indicators"]),
        "warnings": len(merged["warnings"]),
    }
    return merged


def main() -> int:
    args = parse_args()

    try:
        pressure_data = load_json(args.pressure)
        interests_data = load_json(args.interests)
        impact_map_data = load_json(args.impact_map)

        interest_catalog = build_interest_catalog(interests_data)
        impact_lookup, map_warnings = build_impact_lookup(
            impact_map_data,
            interest_catalog,
        )

        history_days = extract_history_days(pressure_data)
        history: list[dict[str, Any]] = []
        daily_diagnostics: list[dict[str, Any]] = []
        calculation_warnings: list[str] = []

        for day in history_days:
            date = clean_text(day.get("date"))
            day_data = day.get("data")
            if not isinstance(day_data, Mapping):
                continue

            assessment, day_warnings, diagnostics = calculate_assessment(
                daily_data=day_data,
                assessment_date=date,
                interest_catalog=interest_catalog,
                impact_lookup=impact_lookup,
                normalisation_divisor=args.normalisation_divisor,
            )
            history.append({"date": date, **assessment})
            daily_diagnostics.append(
                {"date": date, "diagnostics": diagnostics}
            )
            calculation_warnings.extend(
                f"{date}: {warning}" for warning in day_warnings
            )

        if not history:
            raise InputDataError(
                "No valid daily Strategic Pressure assessments were found."
            )

        current = history[-1]
        diagnostics = merge_diagnostics(daily_diagnostics)
        warnings = unique_strings(
            [*map_warnings, *calculation_warnings]
        )
        diagnostics["warnings"] = unique_strings(
            [*diagnostics["warnings"], *warnings]
        )
        diagnostics["counts"]["warnings"] = len(
            diagnostics["warnings"]
        )

        output = {
            "metadata": {
                "model": MODEL_VERSION,
                "generated_at": utc_now_iso(),
                "reference_date": current["date"],
                "history_start_date": history[0]["date"],
                "history_end_date": history[-1]["date"],
                "history_day_count": len(history),
                "conflict": "United States-Iran",
                "description": (
                    "Historical and current assessment of the degree to "
                    "which detected developments support or weaken the "
                    "weighted strategic interests of the United States "
                    "and Iran."
                ),
                "input_files": {
                    "strategic_pressure": str(args.pressure),
                    "strategic_interests": str(args.interests),
                    "interest_impact_map": str(args.impact_map),
                },
                "pressure_model_version": extract_version(pressure_data),
                "interests_model_version": extract_version(interests_data),
                "impact_map_version": extract_version(impact_map_data),
                "warning_count": len(diagnostics["warnings"]),
            },
            "current": current,
            "history": history,
            "history_summary": build_history_summary(history),
            "diagnostics": diagnostics,
            "methodology": {
                "source_scope": (
                    "Every valid day in Strategic Pressure days[] is "
                    "processed. The current block is used only as a "
                    "backwards-compatible fallback when days[] is absent."
                ),
                "duplicate_policy": (
                    "Evidence is counted once per date + event_id + "
                    "target_actor + interest_id. Further occurrences remain "
                    "visible in diagnostics.bilateral_duplicates but have "
                    "no effect on the calculated index."
                ),
                "baseline": (
                    "A score of 50 represents a neutral position with no "
                    "supporting or weakening mapped evidence."
                ),
                "positive_score": (
                    "A score above 50 indicates that developments support "
                    "the actor's weighted strategic interests overall."
                ),
                "negative_score": (
                    "A score below 50 indicates that developments weaken "
                    "the actor's weighted strategic interests overall."
                ),
                "limitations": [
                    "The result depends on the completeness of Strategic Pressure evidence.",
                    "Indicator-to-interest effects are analytical judgements.",
                    "The index measures strategic interest alignment, not military victory or legitimacy.",
                ],
            },
        }

        write_json(args.output, output)

    except InputDataError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    except Exception as exc:
        print(
            "UNEXPECTED ERROR: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1

    print(f"Strategic Interest Achievement generated: {args.output}")
    print("Reference date:", output["metadata"]["reference_date"])
    print("History days:", output["metadata"]["history_day_count"])
    print(
        "USA achievement index:",
        output["current"]["summary"]["usa_achievement_index"],
    )
    print(
        "Iran achievement index:",
        output["current"]["summary"]["iran_achievement_index"],
    )
    print(
        "Daily strategic advantage:",
        output["current"]["summary"]["daily_strategic_advantage"],
    )
    print(
        "Bilateral duplicates:",
        output["diagnostics"]["counts"]["bilateral_duplicates"],
    )
    print("Warnings:", output["diagnostics"]["counts"]["warnings"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
