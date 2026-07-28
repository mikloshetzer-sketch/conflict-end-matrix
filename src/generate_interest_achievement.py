#!/usr/bin/env python3
"""
Generate the Strategic Interest Achievement assessment for the US-Iran conflict.

Default inputs:
    docs/strategic_pressure.json
    data/strategic/strategic_interests.json
    data/strategic/interest_impact_map.json

Default output:
    docs/interest_achievement.json

The engine connects detected Strategic Pressure indicators to long-term
US and Iranian strategic interests.

Calculation concept:

    indicator contribution
        = detected indicator strength
        × mapped interest effect
        × strategic interest weight

The raw interest result is normalised around a neutral baseline of 50.

Important:
- Strategic Pressure and Strategic Interest Achievement are separate concepts.
- A pressure-increasing event may support some interests while damaging others.
- Missing mappings are reported as warnings instead of terminating execution.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


DEFAULT_PRESSURE_PATH = Path("docs/strategic_pressure.json")
DEFAULT_INTERESTS_PATH = Path("data/strategic/strategic_interests.json")
DEFAULT_IMPACT_MAP_PATH = Path("data/strategic/interest_impact_map.json")
DEFAULT_OUTPUT_PATH = Path("docs/interest_achievement.json")

MODEL_VERSION = "strategic_interest_achievement_v1"

ACTORS = ("usa", "iran")

NEUTRAL_SCORE = 50.0
MIN_SCORE = 0.0
MAX_SCORE = 100.0

# Controls how quickly weighted raw contributions move the 0-100 index.
# A larger number produces smaller daily movements.
NORMALISATION_DIVISOR = 20.0

# Prevents one duplicated or extremely large indicator from dominating the day.
MAX_ABSOLUTE_INDICATOR_STRENGTH = 20.0

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
    """Raised when an input file is missing required structural data."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate Strategic Interest Achievement scores from Strategic "
            "Pressure evidence and the static interest-impact model."
        )
    )

    parser.add_argument(
        "--pressure",
        type=Path,
        default=DEFAULT_PRESSURE_PATH,
        help=f"Strategic Pressure JSON. Default: {DEFAULT_PRESSURE_PATH}",
    )

    parser.add_argument(
        "--interests",
        type=Path,
        default=DEFAULT_INTERESTS_PATH,
        help=f"Static strategic interests JSON. Default: {DEFAULT_INTERESTS_PATH}",
    )

    parser.add_argument(
        "--impact-map",
        type=Path,
        default=DEFAULT_IMPACT_MAP_PATH,
        help=f"Interest impact map JSON. Default: {DEFAULT_IMPACT_MAP_PATH}",
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help=f"Output JSON. Default: {DEFAULT_OUTPUT_PATH}",
    )

    parser.add_argument(
        "--normalisation-divisor",
        type=float,
        default=NORMALISATION_DIVISOR,
        help=(
            "Divisor used to normalise weighted contributions around the "
            f"neutral score. Default: {NORMALISATION_DIVISOR}"
        ),
    )

    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise InputDataError(f"Input file does not exist: {path}")

    try:
        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except json.JSONDecodeError as exc:
        raise InputDataError(
            f"Invalid JSON in {path}: line {exc.lineno}, column {exc.colno}"
        ) from exc
    except OSError as exc:
        raise InputDataError(f"Unable to read {path}: {exc}") from exc

    if not isinstance(data, dict):
        raise InputDataError(f"Top-level JSON value must be an object: {path}")

    return data


def write_json(path: Path, data: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    temporary_path = path.with_suffix(path.suffix + ".tmp")

    try:
        with temporary_path.open("w", encoding="utf-8") as file:
            json.dump(
                data,
                file,
                ensure_ascii=False,
                indent=2,
                sort_keys=False,
            )
            file.write("\n")

        temporary_path.replace(path)

    except OSError as exc:
        raise InputDataError(f"Unable to write output file {path}: {exc}") from exc


def as_float(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default

    if isinstance(value, (int, float)):
        result = float(value)
        return result if math.isfinite(result) else default

    if isinstance(value, str):
        try:
            result = float(value.strip())
            return result if math.isfinite(result) else default
        except ValueError:
            return default

    return default


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def clean_text(value: Any) -> str:
    if value is None:
        return ""

    return " ".join(str(value).strip().split())


def first_nonempty(*values: Any) -> str:
    for value in values:
        text = clean_text(value)
        if text:
            return text

    return ""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def extract_reference_date(pressure_data: Mapping[str, Any]) -> str:
    candidates: list[Any] = [
        pressure_data.get("reference_date"),
        pressure_data.get("date"),
        pressure_data.get("completed_day"),
        pressure_data.get("assessment_date"),
    ]

    metadata = pressure_data.get("metadata")
    if isinstance(metadata, Mapping):
        candidates.extend(
            [
                metadata.get("reference_date"),
                metadata.get("date"),
                metadata.get("completed_day"),
                metadata.get("assessment_date"),
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
    actors = interests_data.get("actors")

    if not isinstance(actors, Mapping):
        raise InputDataError(
            "Strategic interests JSON must contain an 'actors' object."
        )

    catalog: dict[str, dict[str, dict[str, Any]]] = {}

    for actor in ACTORS:
        actor_data = actors.get(actor)

        if not isinstance(actor_data, Mapping):
            raise InputDataError(
                f"Strategic interests JSON is missing actor: {actor}"
            )

        interests = actor_data.get("interests")

        if not isinstance(interests, list) or not interests:
            raise InputDataError(
                f"Actor '{actor}' must contain a non-empty interests array."
            )

        actor_catalog: dict[str, dict[str, Any]] = {}

        for position, interest in enumerate(interests):
            if not isinstance(interest, Mapping):
                raise InputDataError(
                    f"Invalid interest entry for actor '{actor}' at index {position}."
                )

            interest_id = clean_text(interest.get("id"))

            if not interest_id:
                raise InputDataError(
                    f"Interest entry for actor '{actor}' at index {position} "
                    "does not contain an id."
                )

            if interest_id in actor_catalog:
                raise InputDataError(
                    f"Duplicate interest id for actor '{actor}': {interest_id}"
                )

            weight = as_float(interest.get("weight"), default=0.0)

            if weight <= 0:
                raise InputDataError(
                    f"Interest '{actor}.{interest_id}' must have a positive weight."
                )

            actor_catalog[interest_id] = {
                "id": interest_id,
                "name": first_nonempty(interest.get("name"), interest_id),
                "description": clean_text(interest.get("description")),
                "weight": weight,
            }

        catalog[actor] = actor_catalog

    return catalog


def build_impact_lookup(
    impact_map_data: Mapping[str, Any],
    interest_catalog: Mapping[str, Mapping[str, Mapping[str, Any]]],
) -> tuple[
    dict[tuple[str, str, str], list[dict[str, Any]]],
    list[str],
]:
    indicator_impacts = impact_map_data.get("indicator_impacts")

    if not isinstance(indicator_impacts, Mapping):
        raise InputDataError(
            "Interest impact map must contain an 'indicator_impacts' object."
        )

    lookup: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    warnings: list[str] = []

    for source_actor in ACTORS:
        actor_map = indicator_impacts.get(source_actor)

        if not isinstance(actor_map, Mapping):
            warnings.append(
                f"Impact map does not contain mappings for source actor '{source_actor}'."
            )
            continue

        for pressure_direction in ("increase_pressure", "decrease_pressure"):
            direction_map = actor_map.get(pressure_direction)

            if not isinstance(direction_map, Mapping):
                warnings.append(
                    f"Impact map does not contain '{source_actor}."
                    f"{pressure_direction}'."
                )
                continue

            for indicator_id, indicator_definition in direction_map.items():
                indicator_key = clean_text(indicator_id)

                if not indicator_key:
                    continue

                if not isinstance(indicator_definition, Mapping):
                    warnings.append(
                        f"Invalid impact definition: {source_actor}."
                        f"{pressure_direction}.{indicator_key}"
                    )
                    continue

                impacts = indicator_definition.get("impacts")

                if not isinstance(impacts, list):
                    warnings.append(
                        f"No impacts array for {source_actor}."
                        f"{pressure_direction}.{indicator_key}"
                    )
                    continue

                validated_impacts: list[dict[str, Any]] = []

                for impact in impacts:
                    if not isinstance(impact, Mapping):
                        continue

                    target_actor = clean_text(impact.get("actor")).lower()
                    interest_id = clean_text(impact.get("interest_id"))
                    effect = as_float(impact.get("effect"), default=0.0)

                    if target_actor not in ACTORS:
                        warnings.append(
                            f"Unknown target actor '{target_actor}' in mapping "
                            f"{source_actor}.{pressure_direction}.{indicator_key}."
                        )
                        continue

                    if interest_id not in interest_catalog.get(target_actor, {}):
                        warnings.append(
                            f"Unknown interest '{target_actor}.{interest_id}' in mapping "
                            f"{source_actor}.{pressure_direction}.{indicator_key}."
                        )
                        continue

                    if effect == 0:
                        continue

                    validated_impacts.append(
                        {
                            "actor": target_actor,
                            "interest_id": interest_id,
                            "effect": effect,
                            "rationale": clean_text(impact.get("rationale")),
                        }
                    )

                lookup[
                    (
                        source_actor,
                        pressure_direction,
                        indicator_key,
                    )
                ] = validated_impacts

    return lookup, warnings


def iter_nested_objects(value: Any) -> Iterable[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        yield value

        for nested_value in value.values():
            yield from iter_nested_objects(nested_value)

    elif isinstance(value, list):
        for item in value:
            yield from iter_nested_objects(item)


def looks_like_evidence(item: Mapping[str, Any]) -> bool:
    indicator = first_nonempty(
        item.get("indicator"),
        item.get("indicator_id"),
        item.get("strategic_indicator"),
    )

    if not indicator:
        return False

    actor = clean_text(
        first_nonempty(
            item.get("actor"),
            item.get("source_actor"),
        )
    ).lower()

    if actor not in ACTORS:
        return False

    evidence_fields = (
        "final_score",
        "operational_component",
        "strategic_modifier",
        "score",
        "weighted_score",
        "contribution",
        "reason",
        "title",
        "source",
        "link",
    )

    return any(field in item for field in evidence_fields)


def evidence_signature(item: Mapping[str, Any]) -> tuple[str, ...]:
    return (
        clean_text(item.get("actor")).lower(),
        first_nonempty(
            item.get("indicator"),
            item.get("indicator_id"),
            item.get("strategic_indicator"),
        ),
        first_nonempty(
            item.get("event_id"),
            item.get("id"),
        ),
        first_nonempty(
            item.get("link"),
            item.get("source_url"),
            item.get("url"),
        ),
        first_nonempty(
            item.get("reason"),
            item.get("title"),
            item.get("description"),
        ),
        str(
            first_nonempty(
                item.get("final_score"),
                item.get("weighted_score"),
                item.get("score"),
            )
        ),
    )


def extract_pressure_evidence(
    pressure_data: Mapping[str, Any],
) -> list[dict[str, Any]]:
    preferred_containers: list[Any] = []

    for key in (
        "evidence",
        "latest_drivers",
        "drivers",
        "events",
        "contributions",
        "daily_evidence",
        "strategic_evidence",
    ):
        if key in pressure_data:
            preferred_containers.append(pressure_data[key])

    actors_data = pressure_data.get("actors")

    if isinstance(actors_data, Mapping):
        for actor in ACTORS:
            actor_data = actors_data.get(actor)

            if isinstance(actor_data, Mapping):
                for key in (
                    "evidence",
                    "drivers",
                    "events",
                    "contributions",
                    "latest_drivers",
                ):
                    if key in actor_data:
                        preferred_containers.append(actor_data[key])

    for actor in ACTORS:
        actor_data = pressure_data.get(actor)

        if isinstance(actor_data, Mapping):
            for key in (
                "evidence",
                "drivers",
                "events",
                "contributions",
                "latest_drivers",
            ):
                if key in actor_data:
                    preferred_containers.append(actor_data[key])

    search_roots: Sequence[Any]

    if preferred_containers:
        search_roots = preferred_containers
    else:
        search_roots = [pressure_data]

    evidence: list[dict[str, Any]] = []
    seen: set[tuple[str, ...]] = set()

    for root in search_roots:
        for item in iter_nested_objects(root):
            if not looks_like_evidence(item):
                continue

            signature = evidence_signature(item)

            if signature in seen:
                continue

            seen.add(signature)
            evidence.append(dict(item))

    return evidence


def infer_pressure_direction(
    evidence: Mapping[str, Any],
    source_actor: str,
    indicator_id: str,
    impact_lookup: Mapping[
        tuple[str, str, str],
        Sequence[Mapping[str, Any]],
    ],
) -> str:
    explicit = clean_text(
        first_nonempty(
            evidence.get("pressure_direction"),
            evidence.get("indicator_group"),
            evidence.get("direction_group"),
            evidence.get("pressure_type"),
        )
    ).lower()

    explicit_aliases = {
        "increase": "increase_pressure",
        "increasing": "increase_pressure",
        "increase_pressure": "increase_pressure",
        "pressure_increase": "increase_pressure",
        "escalation": "increase_pressure",
        "escalatory": "increase_pressure",
        "positive": "increase_pressure",
        "decrease": "decrease_pressure",
        "decreasing": "decrease_pressure",
        "decrease_pressure": "decrease_pressure",
        "pressure_decrease": "decrease_pressure",
        "de-escalation": "decrease_pressure",
        "de_escalation": "decrease_pressure",
        "deescalation": "decrease_pressure",
        "de-escalatory": "decrease_pressure",
        "negative": "decrease_pressure",
    }

    if explicit in explicit_aliases:
        return explicit_aliases[explicit]

    increase_key = (source_actor, "increase_pressure", indicator_id)
    decrease_key = (source_actor, "decrease_pressure", indicator_id)

    has_increase = increase_key in impact_lookup
    has_decrease = decrease_key in impact_lookup

    if has_increase and not has_decrease:
        return "increase_pressure"

    if has_decrease and not has_increase:
        return "decrease_pressure"

    raw_score = extract_indicator_strength(evidence)

    if raw_score < 0:
        return "decrease_pressure"

    return "increase_pressure"


def extract_indicator_strength(evidence: Mapping[str, Any]) -> float:
    candidates = (
        evidence.get("final_score"),
        evidence.get("weighted_score"),
        evidence.get("contribution"),
        evidence.get("score"),
        evidence.get("operational_component"),
    )

    for candidate in candidates:
        value = as_float(candidate, default=float("nan"))

        if math.isfinite(value):
            return clamp(
                value,
                -MAX_ABSOLUTE_INDICATOR_STRENGTH,
                MAX_ABSOLUTE_INDICATOR_STRENGTH,
            )

    operational_component = as_float(
        evidence.get("operational_component"),
        default=0.0,
    )
    strategic_modifier = as_float(
        evidence.get("strategic_modifier"),
        default=0.0,
    )

    combined = operational_component + strategic_modifier

    return clamp(
        combined,
        -MAX_ABSOLUTE_INDICATOR_STRENGTH,
        MAX_ABSOLUTE_INDICATOR_STRENGTH,
    )


def normalise_strength(
    strength: float,
    pressure_direction: str,
) -> float:
    magnitude = abs(strength)

    if magnitude == 0:
        return 0.0

    # The mapping already contains the strategic direction of each interest
    # effect. Therefore, a decrease-pressure indicator is not multiplied by -1.
    # Its absolute detected strength controls only the magnitude.
    if pressure_direction in ("increase_pressure", "decrease_pressure"):
        return magnitude

    return magnitude


def score_level(score: float) -> str:
    for threshold, level in LEVELS:
        if score >= threshold:
            return level

    return "very_weak"


def interest_trend(raw_contribution: float) -> str:
    if raw_contribution > 0.5:
        return "improving"

    if raw_contribution < -0.5:
        return "deteriorating"

    return "stable"


def actor_trend(index: float) -> str:
    difference = index - NEUTRAL_SCORE

    if difference >= 2.0:
        return "improving"

    if difference <= -2.0:
        return "deteriorating"

    return "stable"


def calculate_assessment(
    pressure_data: Mapping[str, Any],
    interest_catalog: Mapping[str, Mapping[str, Mapping[str, Any]]],
    impact_lookup: Mapping[
        tuple[str, str, str],
        Sequence[Mapping[str, Any]],
    ],
    normalisation_divisor: float,
) -> tuple[dict[str, Any], list[str]]:
    if normalisation_divisor <= 0:
        raise InputDataError("Normalisation divisor must be greater than zero.")

    warnings: list[str] = []
    pressure_evidence = extract_pressure_evidence(pressure_data)

    if not pressure_evidence:
        warnings.append(
            "No Strategic Pressure evidence objects were detected. "
            "All interest scores remain neutral."
        )

    interest_contributions: dict[
        str,
        dict[str, list[dict[str, Any]]],
    ] = {
        actor: {
            interest_id: []
            for interest_id in interest_catalog[actor]
        }
        for actor in ACTORS
    }

    processed_evidence: list[dict[str, Any]] = []
    unmapped_evidence: list[dict[str, Any]] = []

    for evidence_position, evidence in enumerate(pressure_evidence, start=1):
        source_actor = clean_text(
            first_nonempty(
                evidence.get("actor"),
                evidence.get("source_actor"),
            )
        ).lower()

        indicator_id = first_nonempty(
            evidence.get("indicator"),
            evidence.get("indicator_id"),
            evidence.get("strategic_indicator"),
        )

        if source_actor not in ACTORS or not indicator_id:
            continue

        pressure_direction = infer_pressure_direction(
            evidence=evidence,
            source_actor=source_actor,
            indicator_id=indicator_id,
            impact_lookup=impact_lookup,
        )

        mapping_key = (
            source_actor,
            pressure_direction,
            indicator_id,
        )

        impacts = impact_lookup.get(mapping_key)

        raw_strength = extract_indicator_strength(evidence)
        indicator_strength = normalise_strength(
            strength=raw_strength,
            pressure_direction=pressure_direction,
        )

        evidence_record = {
            "sequence": evidence_position,
            "source_actor": source_actor,
            "indicator": indicator_id,
            "pressure_direction": pressure_direction,
            "indicator_strength": round(indicator_strength, 4),
            "original_score": round(raw_strength, 4),
            "event_id": first_nonempty(
                evidence.get("event_id"),
                evidence.get("id"),
            ),
            "reason": first_nonempty(
                evidence.get("reason"),
                evidence.get("title"),
                evidence.get("description"),
            ),
            "source": first_nonempty(
                evidence.get("source"),
                evidence.get("source_name"),
            ),
            "link": first_nonempty(
                evidence.get("link"),
                evidence.get("source_url"),
                evidence.get("url"),
            ),
            "operational_component": as_float(
                evidence.get("operational_component"),
                default=0.0,
            ),
            "strategic_modifier": as_float(
                evidence.get("strategic_modifier"),
                default=0.0,
            ),
            "mapped_impacts": [],
        }

        if not impacts:
            warning = (
                f"No impact mapping found for "
                f"{source_actor}.{pressure_direction}.{indicator_id}."
            )

            warnings.append(warning)

            unmapped_evidence.append(
                {
                    **evidence_record,
                    "warning": warning,
                }
            )
            continue

        if indicator_strength == 0:
            warnings.append(
                f"Indicator '{source_actor}.{indicator_id}' has zero strength "
                "and produces no achievement contribution."
            )

        for impact in impacts:
            target_actor = clean_text(impact.get("actor")).lower()
            interest_id = clean_text(impact.get("interest_id"))
            effect = as_float(impact.get("effect"), default=0.0)

            interest = interest_catalog[target_actor][interest_id]
            interest_weight = as_float(interest.get("weight"), default=0.0)

            raw_contribution = (
                indicator_strength
                * effect
                * interest_weight
            )

            contribution_record = {
                "source_actor": source_actor,
                "indicator": indicator_id,
                "pressure_direction": pressure_direction,
                "indicator_strength": round(indicator_strength, 4),
                "effect": round(effect, 4),
                "interest_weight": round(interest_weight, 4),
                "raw_contribution": round(raw_contribution, 4),
                "rationale": clean_text(impact.get("rationale")),
                "event_id": evidence_record["event_id"],
                "reason": evidence_record["reason"],
                "source": evidence_record["source"],
                "link": evidence_record["link"],
            }

            interest_contributions[target_actor][interest_id].append(
                contribution_record
            )

            evidence_record["mapped_impacts"].append(
                {
                    "target_actor": target_actor,
                    "interest_id": interest_id,
                    "effect": round(effect, 4),
                    "interest_weight": round(interest_weight, 4),
                    "raw_contribution": round(raw_contribution, 4),
                    "rationale": clean_text(impact.get("rationale")),
                }
            )

        processed_evidence.append(evidence_record)

    actor_results: dict[str, Any] = {}

    for actor in ACTORS:
        interest_results: list[dict[str, Any]] = []

        weighted_index_numerator = 0.0
        total_interest_weight = 0.0
        actor_raw_contribution = 0.0

        for interest_id, interest in interest_catalog[actor].items():
            contributions = interest_contributions[actor][interest_id]

            raw_contribution = sum(
                as_float(item.get("raw_contribution"))
                for item in contributions
            )

            interest_weight = as_float(interest.get("weight"))
            normalised_change = raw_contribution / normalisation_divisor

            achievement_index = clamp(
                NEUTRAL_SCORE + normalised_change,
                MIN_SCORE,
                MAX_SCORE,
            )

            positive_contribution = sum(
                max(0.0, as_float(item.get("raw_contribution")))
                for item in contributions
            )

            negative_contribution = sum(
                min(0.0, as_float(item.get("raw_contribution")))
                for item in contributions
            )

            sorted_contributions = sorted(
                contributions,
                key=lambda item: abs(
                    as_float(item.get("raw_contribution"))
                ),
                reverse=True,
            )

            interest_result = {
                "id": interest_id,
                "name": interest["name"],
                "description": interest["description"],
                "weight": interest_weight,
                "achievement_index": round(achievement_index, 2),
                "change_from_neutral": round(
                    achievement_index - NEUTRAL_SCORE,
                    2,
                ),
                "raw_contribution": round(raw_contribution, 4),
                "positive_contribution": round(
                    positive_contribution,
                    4,
                ),
                "negative_contribution": round(
                    negative_contribution,
                    4,
                ),
                "trend": interest_trend(raw_contribution),
                "level": score_level(achievement_index),
                "evidence_count": len(contributions),
                "top_evidence": sorted_contributions[:5],
                "evidence": sorted_contributions,
            }

            interest_results.append(interest_result)

            weighted_index_numerator += (
                achievement_index * interest_weight
            )
            total_interest_weight += interest_weight
            actor_raw_contribution += raw_contribution

        if total_interest_weight > 0:
            actor_index = weighted_index_numerator / total_interest_weight
        else:
            actor_index = NEUTRAL_SCORE

        interest_results.sort(
            key=lambda item: (
                -as_float(item.get("weight")),
                clean_text(item.get("name")),
            )
        )

        strongest_interests = sorted(
            interest_results,
            key=lambda item: as_float(
                item.get("change_from_neutral")
            ),
            reverse=True,
        )[:3]

        weakest_interests = sorted(
            interest_results,
            key=lambda item: as_float(
                item.get("change_from_neutral")
            ),
        )[:3]

        actor_results[actor] = {
            "achievement_index": round(actor_index, 2),
            "change_from_neutral": round(
                actor_index - NEUTRAL_SCORE,
                2,
            ),
            "trend": actor_trend(actor_index),
            "level": score_level(actor_index),
            "raw_contribution": round(
                actor_raw_contribution,
                4,
            ),
            "interest_count": len(interest_results),
            "interests_with_evidence": sum(
                1
                for item in interest_results
                if item["evidence_count"] > 0
            ),
            "strongest_interests": [
                {
                    "id": item["id"],
                    "name": item["name"],
                    "achievement_index": item["achievement_index"],
                    "change_from_neutral": item["change_from_neutral"],
                }
                for item in strongest_interests
            ],
            "weakest_interests": [
                {
                    "id": item["id"],
                    "name": item["name"],
                    "achievement_index": item["achievement_index"],
                    "change_from_neutral": item["change_from_neutral"],
                }
                for item in weakest_interests
            ],
            "interests": interest_results,
        }

    usa_index = as_float(
        actor_results["usa"].get("achievement_index"),
        default=NEUTRAL_SCORE,
    )
    iran_index = as_float(
        actor_results["iran"].get("achievement_index"),
        default=NEUTRAL_SCORE,
    )

    advantage = usa_index - iran_index

    if advantage >= 3:
        daily_advantage = "usa"
    elif advantage <= -3:
        daily_advantage = "iran"
    else:
        daily_advantage = "balanced"

    summary = {
        "usa_achievement_index": round(usa_index, 2),
        "iran_achievement_index": round(iran_index, 2),
        "achievement_gap": round(advantage, 2),
        "daily_strategic_advantage": daily_advantage,
        "interpretation": (
            "The achievement index measures whether detected daily developments "
            "support or weaken each actor's own weighted long-term interests. "
            "It does not measure military victory, legitimacy or forecast probability."
        ),
    }

    calculation_details = {
        "neutral_score": NEUTRAL_SCORE,
        "minimum_score": MIN_SCORE,
        "maximum_score": MAX_SCORE,
        "normalisation_divisor": normalisation_divisor,
        "indicator_strength_cap": MAX_ABSOLUTE_INDICATOR_STRENGTH,
        "formula": (
            "raw_contribution = absolute_indicator_strength "
            "× mapped_interest_effect × interest_weight; "
            "interest_index = clamp(50 + raw_contribution / "
            "normalisation_divisor, 0, 100); "
            "actor_index = interest-weighted mean of interest indices"
        ),
    }

    assessment = {
        "summary": summary,
        "actors": actor_results,
        "processed_evidence": processed_evidence,
        "unmapped_evidence": unmapped_evidence,
        "calculation": calculation_details,
    }

    return assessment, warnings


def unique_warnings(warnings: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()

    for warning in warnings:
        cleaned = clean_text(warning)

        if not cleaned or cleaned in seen:
            continue

        seen.add(cleaned)
        result.append(cleaned)

    return result


def main() -> int:
    args = parse_args()

    try:
        pressure_data = load_json(args.pressure)
        interests_data = load_json(args.interests)
        impact_map_data = load_json(args.impact_map)

        interest_catalog = build_interest_catalog(interests_data)

        impact_lookup, mapping_warnings = build_impact_lookup(
            impact_map_data=impact_map_data,
            interest_catalog=interest_catalog,
        )

        assessment, calculation_warnings = calculate_assessment(
            pressure_data=pressure_data,
            interest_catalog=interest_catalog,
            impact_lookup=impact_lookup,
            normalisation_divisor=args.normalisation_divisor,
        )

        warnings = unique_warnings(
            [
                *mapping_warnings,
                *calculation_warnings,
            ]
        )

        reference_date = extract_reference_date(pressure_data)

        output = {
            "metadata": {
                "model": MODEL_VERSION,
                "generated_at": utc_now_iso(),
                "reference_date": reference_date,
                "conflict": "United States-Iran",
                "description": (
                    "Daily assessment of the degree to which current developments "
                    "support or weaken the weighted long-term strategic interests "
                    "of the United States and Iran."
                ),
                "input_files": {
                    "strategic_pressure": str(args.pressure),
                    "strategic_interests": str(args.interests),
                    "interest_impact_map": str(args.impact_map),
                },
                "pressure_model_version": clean_text(
                    (
                        pressure_data.get("metadata")
                        if isinstance(
                            pressure_data.get("metadata"),
                            Mapping,
                        )
                        else {}
                    ).get("version")
                ),
                "interests_model_version": clean_text(
                    (
                        interests_data.get("metadata")
                        if isinstance(
                            interests_data.get("metadata"),
                            Mapping,
                        )
                        else {}
                    ).get("version")
                ),
                "impact_map_version": clean_text(
                    (
                        impact_map_data.get("metadata")
                        if isinstance(
                            impact_map_data.get("metadata"),
                            Mapping,
                        )
                        else {}
                    ).get("version")
                ),
                "warning_count": len(warnings),
            },
            **assessment,
            "warnings": warnings,
            "methodology": {
                "scope": (
                    "The model evaluates daily changes against static, weighted "
                    "long-term national interests."
                ),
                "baseline": (
                    "A score of 50 represents a neutral daily position with no "
                    "detected supporting or weakening evidence."
                ),
                "positive_score": (
                    "A score above 50 means the day's detected developments "
                    "support the actor's weighted strategic interests overall."
                ),
                "negative_score": (
                    "A score below 50 means the day's detected developments "
                    "weaken the actor's weighted strategic interests overall."
                ),
                "limitations": [
                    (
                        "The result depends on the completeness and accuracy of "
                        "the Strategic Pressure evidence."
                    ),
                    (
                        "Impact mappings are analytical judgements and should be "
                        "reviewed when strategic conditions change."
                    ),
                    (
                        "The index measures interest alignment, not battlefield "
                        "victory or final conflict outcome."
                    ),
                    (
                        "The current version is a daily assessment and does not "
                        "yet calculate historical trend against previous output files."
                    ),
                ],
            },
        }

        write_json(args.output, output)

    except InputDataError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(
            f"UNEXPECTED ERROR: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1

    print(f"Strategic Interest Achievement generated: {args.output}")
    print(
        "USA index:",
        output["summary"]["usa_achievement_index"],
    )
    print(
        "Iran index:",
        output["summary"]["iran_achievement_index"],
    )
    print(
        "Daily strategic advantage:",
        output["summary"]["daily_strategic_advantage"],
    )
    print("Warnings:", len(output["warnings"]))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
