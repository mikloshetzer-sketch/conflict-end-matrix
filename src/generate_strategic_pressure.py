import json
import math
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


# =====================================================================
# Conflict End Matrix -> Strategic Pressure Engine V1
#
# Purpose:
# - Reuse the repository's existing historical and daily events.
# - Add a separate strategic interpretation layer.
# - Preserve the existing Forecast Engine unchanged.
# - Produce explainable event-level contributions.
# - Support historical backfill and continuing live collection.
#
# Inputs:
# - docs/event_timeline.json
# - optional kinetic event file
# - data/strategic/strategic_interests.json
# - data/strategic/strategic_indicators.json
#
# Outputs:
# - docs/strategic_pressure.json
# - docs/strategic_pressure_history.json
#
# V1 scoring:
#
# strategic event score
# =
# existing operational event component
# +
# configured strategic modifier
#
# The current UTC day is excluded because it may be incomplete.
# =====================================================================


NON_KINETIC_INPUT = "docs/event_timeline.json"

KINETIC_INPUT_CANDIDATES = [
    "docs/kinetic_events.json",
    "docs/event_timeline_kinetic.json",
    "docs/kinetic_event_timeline.json",
    "data/processed/kinetic_events.json",
]

INTERESTS_INPUT = "data/strategic/strategic_interests.json"
INDICATORS_INPUT = "data/strategic/strategic_indicators.json"

CURRENT_OUTPUT = "docs/strategic_pressure.json"
HISTORY_OUTPUT = "docs/strategic_pressure_history.json"

MODEL_VERSION = "strategic_pressure_v1"

ROLLING_WINDOW_DAYS = 7
INDEX_BASELINE = 50.0
INDEX_POINTS_PER_SCORE = 2.0
MAX_INDICATORS_PER_ACTOR_EVENT = 3


# Newest day receives the highest weight.
ROLLING_WEIGHTS = [
    1.00,
    0.85,
    0.70,
    0.55,
    0.40,
    0.25,
    0.15,
]


# =====================================================================
# STRATEGIC INDICATOR RECOGNITION RULES
#
# Scores are not stored here. Scores are read from:
# data/strategic/strategic_indicators.json
#
# These rules only determine which configured indicator is present.
# =====================================================================

INDICATOR_PATTERNS: dict[str, dict[str, list[str]]] = {
    "usa": {
        "carrier_deployment": [
            r"\bcarrier strike group\b",
            r"\baircraft carrier\b.*\bdeploy",
            r"\bdeploy(?:s|ed|ing|ment)?\b.*\baircraft carrier\b",
            r"\bcarrier\b.*\bcentcom\b",
            r"\buss\s+[a-z0-9\- ]+\b.*\bcarrier\b",
        ],
        "bomber_deployment": [
            r"\b(?:b-1|b-2|b-52)\b.*\bdeploy",
            r"\bdeploy(?:s|ed|ing|ment)?\b.*\b(?:b-1|b-2|b-52)\b",
            r"\bstrategic bomber(?:s)?\b.*\bdeploy",
            r"\bbomber(?:s)?\b.*\bcentcom\b",
        ],
        "additional_air_defense": [
            r"\bdeploy(?:s|ed|ing|ment)?\b.*\b(?:patriot|thaad|air defen[cs]e)\b",
            r"\badditional\b.*\b(?:patriot|thaad|air defen[cs]e)\b",
            r"\breinforc(?:e|es|ed|ing)\b.*\bair defen[cs]e\b",
        ],
        "new_sanctions": [
            r"\b(?:us|u\.s\.|united states|washington)\b.*\bnew sanctions\b",
            r"\b(?:us|u\.s\.|united states|washington)\b.*\bimpose(?:s|d)?\b.*\bsanctions\b",
            r"\btreasury\b.*\b(?:sanctions|designates|designation)\b",
            r"\bnew sanctions\b.*\biran\b",
        ],
        "evacuation_warning": [
            r"\b(?:us|u\.s\.|american)\b.*\bembassy\b.*\b(?:evacuat|depart|leave)\b",
            r"\b(?:ordered|authorized)\s+departure\b",
            r"\bevacuat(?:e|es|ed|ing|ion)\b.*\b(?:americans|us citizens|u\.s\. citizens)\b",
            r"\b(?:us|u\.s\.)\b.*\btravel warning\b",
        ],
        "force_protection": [
            r"\bforce protection\b.*\b(?:raise|increase|heighten)\b",
            r"\b(?:raise|raises|raised|increase|increases|increased)\b.*\bforce protection\b",
            r"\b(?:us|u\.s\.|american)\b.*\b(?:forces|bases)\b.*\bhigh alert\b",
            r"\b(?:us|u\.s\.)\b.*\bmilitary readiness\b",
        ],
        "presidential_warning": [
            r"\b(?:us president|u\.s\. president|white house|president trump)\b.*\bwarn",
            r"\bpresident\b.*\biran\b.*\b(?:consequences|military action|strike|attack)\b",
            r"\bwhite house\b.*\biran\b.*\b(?:warning|ultimatum|red line)\b",
        ],
        "military_exercise": [
            r"\b(?:us|u\.s\.|american)\b.*\bmilitary exercise\b",
            r"\b(?:us|u\.s\.)\b.*\bjoint exercise\b",
            r"\bcentcom\b.*\bexercise\b",
            r"\bexercise\b.*\b(?:us navy|u\.s\. navy|us air force|u\.s\. air force)\b",
        ],
        "strike_preparation": [
            r"\b(?:us|u\.s\.|american)\b.*\bprepar(?:e|es|ed|ing|ation)\b.*\bstrike\b",
            r"\bpentagon\b.*\b(?:strike options|attack options|target list)\b",
            r"\b(?:military|air)\s+strike\b.*\bimminent\b",
            r"\b(?:us|u\.s\.)\b.*\bposition(?:s|ed|ing)?\b.*\bforces\b.*\bstrike\b",
            r"\bstrike package\b",
        ],
        "negotiation": [
            r"\b(?:us|u\.s\.|united states|washington)\b.*\b(?:talks|negotiations|dialogue)\b",
            r"\b(?:talks|negotiations|dialogue)\b.*\b(?:us|u\.s\.|united states|washington)\b",
            r"\b(?:us|u\.s\.)\b.*\bresume(?:s|d)?\b.*\bnegotiations\b",
        ],
        "ceasefire_support": [
            r"\b(?:us|u\.s\.|united states|white house)\b.*\b(?:supports?|backs?|calls for)\b.*\bceasefire\b",
            r"\b(?:us|u\.s\.)\b.*\bceasefire proposal\b",
            r"\bceasefire\b.*\b(?:supported|backed)\b.*\b(?:us|u\.s\.)\b",
        ],
        "sanction_relief": [
            r"\b(?:us|u\.s\.|united states|washington)\b.*\b(?:lifts?|eases?|waives?|suspends?)\b.*\bsanctions\b",
            r"\bsanctions relief\b",
            r"\bwaiver\b.*\biran\b.*\bsanctions\b",
        ],
        "troop_withdrawal": [
            r"\b(?:us|u\.s\.|american)\b.*\bwithdraw(?:s|al|ing)?\b.*\b(?:troops|forces|warships|aircraft)\b",
            r"\b(?:troops|forces|warships|aircraft)\b.*\bwithdraw(?:s|n|al|ing)?\b.*\b(?:us|u\.s\.)\b",
            r"\bstands? down\b.*\b(?:us|u\.s\.|american)\b.*\bforces\b",
        ],
    },

    "iran": {
        "missile_preparation": [
            r"\biran(?:ian)?\b.*\bmissile(?:s)?\b.*\b(?:prepar|ready|readiness|position|deploy)\b",
            r"\b(?:prepar|ready|readiness|position|deploy)\w*\b.*\biran(?:ian)?\b.*\bmissile",
            r"\birgc\b.*\bmissile units?\b.*\balert\b",
            r"\bmissile forces?\b.*\bhigh alert\b",
        ],
        "proxy_activation": [
            r"\biran\b.*\b(?:activates?|mobilizes?|mobilises?|orders?)\b.*\b(?:proxies|proxy forces|allied militias)\b",
            r"\biran-backed\b.*\b(?:militia|group|forces?)\b.*\b(?:mobiliz|activat|prepare|alert)\w*\b",
            r"\b(?:hezbollah|houthis?|iraqi militias?)\b.*\bcoordinat\w*\b.*\biran\b",
            r"\baxis of resistance\b.*\b(?:mobiliz|activat|prepare)\w*\b",
        ],
        "missile_test": [
            r"\biran(?:ian)?\b.*\b(?:tests?|tested|test-fires?|test-fired|launches?)\b.*\bmissile",
            r"\bmissile\b.*\btest\b.*\biran\b",
            r"\birgc\b.*\btest(?:s|ed)?\b.*\bmissile\b",
        ],
        "nuclear_activity": [
            r"\biran\b.*\b(?:enrich|enrichment)\w*\b.*\b(?:uranium|percent|%)\b",
            r"\biran\b.*\b(?:installs?|installed|activates?|activated)\b.*\bcentrifuges?\b",
            r"\biran\b.*\b(?:expands?|expanded|accelerates?|accelerated)\b.*\bnuclear\b",
            r"\b(?:fordow|natanz|arak)\b.*\b(?:expands?|enrichment|centrifuge|nuclear activity)\b",
            r"\biaea\b.*\biran\b.*\b(?:non-compliance|violation|stockpile increase)\b",
        ],
        "hormuz_threat": [
            r"\biran\b.*\b(?:close|closes|closed|block|blocks|blocked|shut)\b.*\bstrait of hormuz\b",
            r"\bstrait of hormuz\b.*\b(?:close|block|shut|disrupt|threat)\w*\b",
            r"\birgc\b.*\bhormuz\b.*\b(?:warning|threat|closure|blockade)\b",
        ],
        "supreme_leader_statement": [
            r"\b(?:supreme leader|ayatollah khamenei|khamenei)\b.*\b(?:warn|retaliat|revenge|punish|destroy|strike|attack)\w*\b",
            r"\b(?:supreme leader|khamenei)\b.*\b(?:severe consequences|crushing response|harsh response)\b",
        ],
        "irgc_alert": [
            r"\birgc\b.*\b(?:high alert|raised alert|readiness|combat readiness|maximum readiness)\b",
            r"\b(?:raises?|raised|increases?|increased)\b.*\birgc\b.*\breadiness\b",
            r"\birgc\b.*\b(?:mobilizes?|mobilises?|deploys?|deployment)\b",
        ],
        "military_exercise": [
            r"\biran(?:ian)?\b.*\bmilitary exercise\b",
            r"\birgc\b.*\bmilitary exercise\b",
            r"\biran(?:ian)?\b.*\bwar games?\b",
            r"\bexercise\b.*\b(?:iran|irgc)\b",
        ],
        "strike_preparation": [
            r"\biran(?:ian)?\b.*\bprepar(?:e|es|ed|ing|ation)\b.*\b(?:strike|attack|retaliation)\b",
            r"\birgc\b.*\bprepar(?:e|es|ed|ing|ation)\b.*\b(?:strike|attack|response)\b",
            r"\biran\b.*\bimminent\b.*\b(?:strike|attack|retaliation)\b",
            r"\biran(?:ian)?\b.*\btarget list\b",
        ],
        "negotiation": [
            r"\biran\b.*\b(?:talks|negotiations|dialogue)\b",
            r"\b(?:talks|negotiations|dialogue)\b.*\biran\b",
            r"\btehran\b.*\bresume(?:s|d)?\b.*\bnegotiations\b",
        ],
        "iaea_cooperation": [
            r"\biran\b.*\bcooperat\w*\b.*\biaea\b",
            r"\biaea\b.*\bcooperat\w*\b.*\biran\b",
            r"\biran\b.*\b(?:allows?|allowed|grants?|granted)\b.*\b(?:inspectors?|inspection|access)\b",
            r"\biran\b.*\breturns?\b.*\biaea compliance\b",
        ],
        "proxy_restraint": [
            r"\biran\b.*\b(?:restrains?|restrained|orders?)\b.*\b(?:proxies|proxy forces|militias)\b",
            r"\biran-backed\b.*\b(?:groups?|militias?)\b.*\bstand down\b",
            r"\btehran\b.*\b(?:urges?|orders?)\b.*\b(?:restraint|de-escalation)\b",
        ],
        "de_escalation_statement": [
            r"\biran\b.*\b(?:calls for|supports?|seeks?|wants?)\b.*\bde[- ]?escalation\b",
            r"\btehran\b.*\b(?:does not seek|not seeking|wants to avoid)\b.*\bwar\b",
            r"\biran\b.*\b(?:no intention|does not intend)\b.*\b(?:escalate|attack|war)\b",
            r"\biran\b.*\bready\b.*\b(?:reduce tensions|de-escalate)\b",
        ],
    },
}


# Maps strategic indicators to the long-term interest they most directly affect.
# Interest weights are included in the output for explainability.
# V1 does not multiply the score by the interest weight.
INDICATOR_INTEREST_MAP: dict[str, dict[str, str]] = {
    "usa": {
        "carrier_deployment": "regional_deterrence",
        "bomber_deployment": "regional_deterrence",
        "additional_air_defense": "force_protection",
        "new_sanctions": "nuclear_nonproliferation",
        "evacuation_warning": "force_protection",
        "force_protection": "force_protection",
        "presidential_warning": "regional_deterrence",
        "military_exercise": "regional_deterrence",
        "strike_preparation": "regional_deterrence",
        "negotiation": "avoid_full_scale_war",
        "ceasefire_support": "avoid_full_scale_war",
        "sanction_relief": "avoid_full_scale_war",
        "troop_withdrawal": "avoid_full_scale_war",
    },
    "iran": {
        "missile_preparation": "strategic_deterrence",
        "proxy_activation": "proxy_network",
        "missile_test": "missile_capability",
        "nuclear_activity": "nuclear_programme",
        "hormuz_threat": "hormuz_leverage",
        "supreme_leader_statement": "strategic_deterrence",
        "irgc_alert": "strategic_deterrence",
        "military_exercise": "strategic_deterrence",
        "strike_preparation": "strategic_deterrence",
        "negotiation": "avoid_regime_destroying_war",
        "iaea_cooperation": "nuclear_programme",
        "proxy_restraint": "proxy_network",
        "de_escalation_statement": "avoid_regime_destroying_war",
    },
}


ACTOR_PATTERNS: dict[str, list[str]] = {
    "usa": [
        r"\bunited states\b",
        r"\bu\.s\.\b",
        r"\bu\.s\b",
        r"\bus military\b",
        r"\bus forces\b",
        r"\bamerican\b",
        r"\bwashington\b",
        r"\bwhite house\b",
        r"\bpentagon\b",
        r"\bcentcom\b",
        r"\btreasury\b",
        r"\bpresident trump\b",
        r"\buss\s+[a-z0-9\-]+\b",
    ],
    "iran": [
        r"\biran\b",
        r"\biranian\b",
        r"\btehran\b",
        r"\birgc\b",
        r"\bislamic revolutionary guard corps\b",
        r"\bkhamenei\b",
        r"\bayatollah\b",
        r"\bsupreme leader\b",
    ],
}


# =====================================================================
# GENERAL UTILITIES
# =====================================================================

def load_json(path: Path, required: bool = True) -> dict[str, Any]:
    if not path.exists():
        if required:
            raise FileNotFoundError(f"Required file not found: {path}")
        return {}

    with path.open("r", encoding="utf-8") as file:
        loaded = json.load(file)

    if not isinstance(loaded, dict):
        raise ValueError(f"Expected a JSON object in: {path}")

    return loaded


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    temporary_path = path.with_suffix(path.suffix + ".tmp")

    with temporary_path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2, ensure_ascii=False)

    temporary_path.replace(path)


def parse_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()

    if not text:
        return None

    try:
        from email.utils import parsedate_to_datetime

        parsed = parsedate_to_datetime(text)

        if parsed is not None:
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)

            return parsed.astimezone(timezone.utc)

    except (TypeError, ValueError, OverflowError):
        pass

    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)

        return parsed.astimezone(timezone.utc)

    except ValueError:
        return None


def event_timestamp(event: dict[str, Any]) -> datetime | None:
    candidates = [
        event.get("timestamp"),
        event.get("published"),
        event.get("date"),
        event.get("datetime"),
        event.get("created_at"),
        event.get("event_time"),
    ]

    for candidate in candidates:
        parsed = parse_datetime(candidate)

        if parsed is not None:
            return parsed

    return None


def normalise_text(value: Any) -> str:
    text = str(value or "").lower()

    text = (
        text.replace("’", "'")
        .replace("“", '"')
        .replace("”", '"')
        .replace("–", "-")
        .replace("—", "-")
    )

    return re.sub(r"\s+", " ", text).strip()


def safe_number(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default

        return float(value)

    except (TypeError, ValueError):
        return default


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def round_score(value: float) -> float:
    return round(float(value), 2)


def regex_matches(patterns: list[str], text: str) -> list[str]:
    matched: list[str] = []

    for pattern in patterns:
        if re.search(pattern, text, flags=re.IGNORECASE):
            matched.append(pattern)

    return matched


# =====================================================================
# INPUT NORMALISATION
# =====================================================================

def extract_events(payload: dict[str, Any]) -> list[dict[str, Any]]:
    possible_keys = [
        "events",
        "kinetic_events",
        "items",
        "articles",
        "data",
    ]

    for key in possible_keys:
        value = payload.get(key)

        if isinstance(value, list):
            return [
                item
                for item in value
                if isinstance(item, dict)
            ]

    return []


def find_kinetic_input(repo_root: Path) -> Path | None:
    for relative_path in KINETIC_INPUT_CANDIDATES:
        candidate = repo_root / relative_path

        if candidate.exists():
            return candidate

    return None


def event_identity(event: dict[str, Any]) -> str:
    link = normalise_text(
        event.get("link")
        or event.get("url")
        or event.get("source_url")
    )

    if link:
        return f"link:{link}"

    external_id = normalise_text(
        event.get("event_id")
        or event.get("id")
    )

    if external_id:
        return f"id:{external_id}"

    title = normalise_text(
        event.get("title")
        or event.get("event")
        or event.get("description")
    )

    timestamp = event_timestamp(event)
    timestamp_text = timestamp.isoformat() if timestamp else ""

    return f"title:{title}|timestamp:{timestamp_text}"


def merge_events(
    non_kinetic_events: list[dict[str, Any]],
    kinetic_events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    unique: dict[str, dict[str, Any]] = {}

    for event in non_kinetic_events:
        copied = dict(event)
        copied["_strategic_source_layer"] = "non_kinetic"
        unique[event_identity(copied)] = copied

    for event in kinetic_events:
        copied = dict(event)
        copied["_strategic_source_layer"] = "kinetic"

        identity = event_identity(copied)

        if identity not in unique:
            unique[identity] = copied

    merged = list(unique.values())

    merged.sort(
        key=lambda item: event_timestamp(item)
        or datetime.min.replace(tzinfo=timezone.utc)
    )

    return merged


# =====================================================================
# CONFIGURATION
# =====================================================================

def build_indicator_config(
    payload: dict[str, Any],
) -> dict[str, dict[str, dict[str, Any]]]:
    config: dict[str, dict[str, dict[str, Any]]] = {
        "usa": {},
        "iran": {},
    }

    for actor in ("usa", "iran"):
        actor_payload = payload.get(actor, {})

        if not isinstance(actor_payload, dict):
            continue

        for direction_key in ("increase_pressure", "decrease_pressure"):
            configured = actor_payload.get(direction_key, [])

            if not isinstance(configured, list):
                continue

            for item in configured:
                if not isinstance(item, dict):
                    continue

                indicator_id = str(item.get("id", "")).strip()

                if not indicator_id:
                    continue

                configured_score = safe_number(item.get("score"))

                config[actor][indicator_id] = {
                    "id": indicator_id,
                    "name": str(item.get("name", indicator_id)),
                    "configured_score": configured_score,
                    "configured_direction": (
                        "increase"
                        if configured_score > 0
                        else "decrease"
                        if configured_score < 0
                        else "neutral"
                    ),
                }

    return config


def build_interest_config(
    payload: dict[str, Any],
) -> dict[str, dict[str, dict[str, Any]]]:
    config: dict[str, dict[str, dict[str, Any]]] = {
        "usa": {},
        "iran": {},
    }

    actors = payload.get("actors", {})

    if not isinstance(actors, dict):
        return config

    for actor in ("usa", "iran"):
        actor_payload = actors.get(actor, {})

        if not isinstance(actor_payload, dict):
            continue

        interests = actor_payload.get("interests", [])

        if not isinstance(interests, list):
            continue

        for interest in interests:
            if not isinstance(interest, dict):
                continue

            interest_id = str(interest.get("id", "")).strip()

            if not interest_id:
                continue

            config[actor][interest_id] = {
                "id": interest_id,
                "name": str(interest.get("name", interest_id)),
                "description": str(interest.get("description", "")),
                "weight": safe_number(interest.get("weight")),
            }

    return config


def validate_configuration(
    indicator_config: dict[str, dict[str, dict[str, Any]]],
) -> list[str]:
    warnings: list[str] = []

    for actor, actor_patterns in INDICATOR_PATTERNS.items():
        configured_ids = set(indicator_config.get(actor, {}).keys())
        pattern_ids = set(actor_patterns.keys())

        missing_in_config = sorted(pattern_ids - configured_ids)
        missing_patterns = sorted(configured_ids - pattern_ids)

        for indicator_id in missing_in_config:
            warnings.append(
                f"{actor}.{indicator_id} has recognition patterns "
                "but is missing from strategic_indicators.json"
            )

        for indicator_id in missing_patterns:
            warnings.append(
                f"{actor}.{indicator_id} is configured "
                "but has no recognition patterns in the script"
            )

    return warnings


# =====================================================================
# EVENT INTERPRETATION
# =====================================================================

def event_text(event: dict[str, Any]) -> str:
    text_parts: list[str] = []

    scalar_fields = [
        "title",
        "description",
        "summary",
        "event",
        "diplomatic_event",
        "military_event",
        "subtype",
        "primary_keyword",
        "target",
        "location",
        "actor",
        "source",
    ]

    for field in scalar_fields:
        value = event.get(field)

        if value:
            text_parts.append(str(value))

    list_fields = [
        "keywords",
        "actors",
        "matched_keywords",
        "tags",
    ]

    for field in list_fields:
        value = event.get(field)

        if not isinstance(value, list):
            continue

        for item in value:
            if isinstance(item, dict):
                text_parts.extend(
                    str(entry)
                    for entry in item.values()
                    if entry not in (None, "")
                )
            elif item not in (None, ""):
                text_parts.append(str(item))

    return normalise_text(" ".join(text_parts))


def detect_actors(text: str) -> list[str]:
    actors: list[str] = []

    for actor, patterns in ACTOR_PATTERNS.items():
        if regex_matches(patterns, text):
            actors.append(actor)

    return actors


def detect_indicators_for_actor(
    actor: str,
    text: str,
    indicator_config: dict[str, dict[str, dict[str, Any]]],
) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []

    actor_patterns = INDICATOR_PATTERNS.get(actor, {})
    actor_config = indicator_config.get(actor, {})

    for indicator_id, patterns in actor_patterns.items():
        configuration = actor_config.get(indicator_id)

        if configuration is None:
            continue

        matched_patterns = regex_matches(patterns, text)

        if not matched_patterns:
            continue

        match = dict(configuration)
        match["matched_patterns"] = matched_patterns

        matches.append(match)

    matches.sort(
        key=lambda item: (
            abs(safe_number(item.get("configured_score"))),
            str(item.get("id", "")),
        ),
        reverse=True,
    )

    return matches[:MAX_INDICATORS_PER_ACTOR_EVENT]


def infer_direction(event: dict[str, Any]) -> str:
    direction = normalise_text(
        event.get("direction")
        or event.get("trend")
        or event.get("classification")
    )

    if direction in {
        "escalation",
        "escalatory",
        "increase",
        "increasing",
        "negative",
    }:
        return "escalation"

    if direction in {
        "de-escalation",
        "deescalation",
        "de-escalatory",
        "deescalatory",
        "decrease",
        "decreasing",
        "positive",
    }:
        return "de-escalation"

    if direction in {"mixed", "neutral", "unclear"}:
        return "mixed"

    event_type = normalise_text(event.get("event_type"))

    if event_type in {
        "kinetic",
        "attack",
        "strike",
        "airstrike",
        "missile",
        "drone",
        "military_attack",
    }:
        return "escalation"

    return "unknown"


def operational_magnitude(event: dict[str, Any]) -> float:
    candidates = [
        abs(safe_number(event.get("score"))),
        abs(safe_number(event.get("direction_score"))),
        abs(safe_number(event.get("severity_score"))),
        abs(safe_number(event.get("event_score"))),
        abs(safe_number(event.get("weight"))),
        abs(safe_number(event.get("severity"))),
    ]

    magnitude = max(candidates, default=0.0)

    if magnitude == 0:
        magnitude = 1.0

    return magnitude


def calculate_operational_component(
    event: dict[str, Any],
) -> tuple[float, str]:
    direction = infer_direction(event)
    magnitude = operational_magnitude(event)

    if direction == "escalation":
        return magnitude, direction

    if direction == "de-escalation":
        return -magnitude, direction

    if direction == "mixed":
        return 0.0, direction

    return 0.0, direction


def interest_details(
    actor: str,
    indicator_id: str,
    interest_config: dict[str, dict[str, dict[str, Any]]],
) -> dict[str, Any] | None:
    interest_id = INDICATOR_INTEREST_MAP.get(actor, {}).get(indicator_id)

    if not interest_id:
        return None

    interest = interest_config.get(actor, {}).get(interest_id)

    if interest is None:
        return {
            "id": interest_id,
            "name": interest_id,
            "weight": None,
        }

    return {
        "id": interest.get("id"),
        "name": interest.get("name"),
        "weight": interest.get("weight"),
    }


def build_actor_contribution(
    event: dict[str, Any],
    actor: str,
    matched_indicators: list[dict[str, Any]],
    interest_config: dict[str, dict[str, dict[str, Any]]],
) -> dict[str, Any]:
    timestamp = event_timestamp(event)

    operational_component, event_direction = (
        calculate_operational_component(event)
    )

    strategic_modifier = sum(
        safe_number(indicator.get("configured_score"))
        for indicator in matched_indicators
    )

    final_score = operational_component + strategic_modifier

    indicator_results: list[dict[str, Any]] = []

    for indicator in matched_indicators:
        indicator_id = str(indicator.get("id", ""))

        indicator_results.append({
            "id": indicator_id,
            "name": indicator.get("name"),
            "score": round_score(
                safe_number(indicator.get("configured_score"))
            ),
            "direction": indicator.get("configured_direction"),
            "interest": interest_details(
                actor,
                indicator_id,
                interest_config,
            ),
            "recognition_rule_count": len(
                indicator.get("matched_patterns", [])
            ),
        })

    title = (
        event.get("title")
        or event.get("event")
        or event.get("description")
        or ""
    )

    source_layer = event.get(
        "_strategic_source_layer",
        "unknown",
    )

    event_id = (
        event.get("event_id")
        or event.get("id")
        or event_identity(event)
    )

    return {
        "event_id": str(event_id),
        "timestamp": timestamp.isoformat() if timestamp else "",
        "date": timestamp.date().isoformat() if timestamp else "",
        "actor": actor,
        "title": str(title),
        "source_layer": source_layer,
        "event_type": event.get("event_type", ""),
        "event_direction": event_direction,
        "operational_component": round_score(
            operational_component
        ),
        "strategic_modifier": round_score(
            strategic_modifier
        ),
        "context_multiplier": 1.0,
        "final_score": round_score(final_score),
        "indicators": indicator_results,
        "reason": build_reason(
            actor=actor,
            title=str(title),
            operational_component=operational_component,
            strategic_modifier=strategic_modifier,
            final_score=final_score,
            matched_indicators=matched_indicators,
        ),
        "source": event.get("source", ""),
        "link": (
            event.get("link")
            or event.get("url")
            or event.get("source_url")
            or ""
        ),
        "existing_event_score": round_score(
            safe_number(event.get("score"))
        ),
        "existing_direction_score": round_score(
            safe_number(event.get("direction_score"))
        ),
    }


def build_reason(
    actor: str,
    title: str,
    operational_component: float,
    strategic_modifier: float,
    final_score: float,
    matched_indicators: list[dict[str, Any]],
) -> str:
    actor_name = "United States" if actor == "usa" else "Iran"

    indicator_names = ", ".join(
        str(indicator.get("name", indicator.get("id", "")))
        for indicator in matched_indicators
    )

    return (
        f"{actor_name}: {indicator_names}. "
        f"Existing operational component: "
        f"{round_score(operational_component):+.2f}; "
        f"strategic modifier: "
        f"{round_score(strategic_modifier):+.2f}; "
        f"final contribution: "
        f"{round_score(final_score):+.2f}. "
        f"Event: {title}"
    )


def analyse_event(
    event: dict[str, Any],
    indicator_config: dict[str, dict[str, dict[str, Any]]],
    interest_config: dict[str, dict[str, dict[str, Any]]],
) -> list[dict[str, Any]]:
    timestamp = event_timestamp(event)

    if timestamp is None:
        return []

    # The current UTC day is incomplete and must not be used.
    if timestamp.date() >= datetime.now(timezone.utc).date():
        return []

    text = event_text(event)
    detected_actors = detect_actors(text)

    contributions: list[dict[str, Any]] = []

    for actor in ("usa", "iran"):
        matched_indicators = detect_indicators_for_actor(
            actor,
            text,
            indicator_config,
        )

        if not matched_indicators:
            continue

        # Actor-specific indicator patterns are the primary control.
        # Actor detection provides an additional guard where possible.
        if detected_actors and actor not in detected_actors:
            actor_specific_pattern_match = any(
                actor in pattern.lower()
                for indicator in matched_indicators
                for pattern in indicator.get("matched_patterns", [])
            )

            if not actor_specific_pattern_match:
                continue

        contributions.append(
            build_actor_contribution(
                event=event,
                actor=actor,
                matched_indicators=matched_indicators,
                interest_config=interest_config,
            )
        )

    return contributions


# =====================================================================
# AGGREGATION
# =====================================================================

def empty_actor_day() -> dict[str, Any]:
    return {
        "raw_score": 0.0,
        "positive_score": 0.0,
        "negative_score": 0.0,
        "event_count": 0,
        "increase_event_count": 0,
        "decrease_event_count": 0,
        "contributors": [],
    }


def group_contributions_by_day(
    contributions: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}

    for contribution in contributions:
        day = str(contribution.get("date", ""))

        if not day:
            continue

        if day not in grouped:
            grouped[day] = {
                "date": day,
                "usa": empty_actor_day(),
                "iran": empty_actor_day(),
            }

        actor = str(contribution.get("actor", ""))

        if actor not in ("usa", "iran"):
            continue

        actor_day = grouped[day][actor]
        final_score = safe_number(
            contribution.get("final_score")
        )

        actor_day["raw_score"] += final_score
        actor_day["event_count"] += 1
        actor_day["contributors"].append(contribution)

        if final_score > 0:
            actor_day["positive_score"] += final_score
            actor_day["increase_event_count"] += 1

        elif final_score < 0:
            actor_day["negative_score"] += final_score
            actor_day["decrease_event_count"] += 1

    for day_payload in grouped.values():
        for actor in ("usa", "iran"):
            actor_day = day_payload[actor]

            actor_day["raw_score"] = round_score(
                actor_day["raw_score"]
            )
            actor_day["positive_score"] = round_score(
                actor_day["positive_score"]
            )
            actor_day["negative_score"] = round_score(
                actor_day["negative_score"]
            )

            actor_day["contributors"].sort(
                key=lambda item: (
                    abs(safe_number(item.get("final_score"))),
                    str(item.get("timestamp", "")),
                ),
                reverse=True,
            )

    return grouped


def date_range_from_days(
    grouped: dict[str, dict[str, Any]],
) -> list[str]:
    if not grouped:
        return []

    parsed_dates = sorted(
        date.fromisoformat(day)
        for day in grouped.keys()
    )

    start = parsed_dates[0]
    end = parsed_dates[-1]

    days: list[str] = []
    cursor = start

    while cursor <= end:
        days.append(cursor.isoformat())
        cursor = date.fromordinal(cursor.toordinal() + 1)

    return days


def weighted_rolling_score(
    history_rows: list[dict[str, Any]],
    row_index: int,
    actor: str,
) -> float:
    weighted_total = 0.0

    for offset in range(ROLLING_WINDOW_DAYS):
        source_index = row_index - offset

        if source_index < 0:
            break

        weight = (
            ROLLING_WEIGHTS[offset]
            if offset < len(ROLLING_WEIGHTS)
            else 0.0
        )

        raw_score = safe_number(
            history_rows[source_index]
            .get(actor, {})
            .get("raw_score")
        )

        weighted_total += raw_score * weight

    return weighted_total


def score_to_index(weighted_score: float) -> float:
    index_value = (
        INDEX_BASELINE
        + weighted_score * INDEX_POINTS_PER_SCORE
    )

    return round_score(
        clamp(index_value, 0.0, 100.0)
    )


def pressure_level(index_value: float) -> str:
    if index_value >= 80:
        return "critical"

    if index_value >= 65:
        return "high"

    if index_value >= 50:
        return "elevated"

    if index_value >= 35:
        return "reduced"

    return "low"


def pressure_trend(
    current_index: float,
    previous_index: float | None,
) -> str:
    if previous_index is None:
        return "insufficient_history"

    change = current_index - previous_index

    if change >= 5:
        return "strong_increase"

    if change >= 1:
        return "increase"

    if change <= -5:
        return "strong_decrease"

    if change <= -1:
        return "decrease"

    return "stable"


def build_history_rows(
    grouped: dict[str, dict[str, Any]],
    existing_history: dict[str, Any],
) -> list[dict[str, Any]]:
    all_days = date_range_from_days(grouped)

    if not all_days:
        return []

    existing_modes: dict[str, str] = {}

    for row in existing_history.get("days", []) or []:
        if not isinstance(row, dict):
            continue

        row_date = str(row.get("date", ""))

        if row_date:
            existing_modes[row_date] = str(
                row.get("calculation_mode", "")
            )

    newest_available_day = all_days[-1]
    history_rows: list[dict[str, Any]] = []

    for day in all_days:
        source = grouped.get(day, {
            "date": day,
            "usa": empty_actor_day(),
            "iran": empty_actor_day(),
        })

        existing_mode = existing_modes.get(day)

        if existing_mode in {
            "historical_backfill",
            "live",
        }:
            calculation_mode = existing_mode

        elif day == newest_available_day:
            calculation_mode = "live"

        else:
            calculation_mode = "historical_backfill"

        history_rows.append({
            "date": day,
            "calculation_mode": calculation_mode,
            "usa": source["usa"],
            "iran": source["iran"],
        })

    for index, row in enumerate(history_rows):
        previous_row = (
            history_rows[index - 1]
            if index > 0
            else None
        )

        actor_indices: list[float] = []

        for actor in ("usa", "iran"):
            weighted_score = weighted_rolling_score(
                history_rows,
                index,
                actor,
            )

            current_index = score_to_index(
                weighted_score
            )

            previous_index = None

            if previous_row is not None:
                previous_index = safe_number(
                    previous_row
                    .get(actor, {})
                    .get("pressure_index_7d"),
                    default=INDEX_BASELINE,
                )

            row[actor]["weighted_score_7d"] = round_score(
                weighted_score
            )
            row[actor]["pressure_index_7d"] = current_index
            row[actor]["pressure_level"] = pressure_level(
                current_index
            )
            row[actor]["trend"] = pressure_trend(
                current_index,
                previous_index,
            )

            actor_indices.append(current_index)

        overall_index = round_score(
            sum(actor_indices) / len(actor_indices)
        )

        previous_overall_index = None

        if previous_row is not None:
            previous_overall_index = safe_number(
                previous_row
                .get("overall", {})
                .get("pressure_index_7d"),
                default=INDEX_BASELINE,
            )

        row["overall"] = {
            "pressure_index_7d": overall_index,
            "pressure_level": pressure_level(
                overall_index
            ),
            "trend": pressure_trend(
                overall_index,
                previous_overall_index,
            ),
            "calculation": (
                "Arithmetic mean of USA and Iran "
                "seven-day pressure indices"
            ),
        }

    return history_rows


# =====================================================================
# VALIDATION AND SUMMARY
# =====================================================================

def source_count(
    contributions: list[dict[str, Any]],
) -> dict[str, int]:
    counts: dict[str, int] = {}

    for contribution in contributions:
        source_layer = str(
            contribution.get("source_layer", "unknown")
        )

        counts[source_layer] = (
            counts.get(source_layer, 0) + 1
        )

    return counts


def actor_contribution_count(
    contributions: list[dict[str, Any]],
) -> dict[str, int]:
    counts = {
        "usa": 0,
        "iran": 0,
    }

    for contribution in contributions:
        actor = str(contribution.get("actor", ""))

        if actor in counts:
            counts[actor] += 1

    return counts


def strongest_contributors(
    contributors: list[dict[str, Any]],
    limit: int = 10,
) -> list[dict[str, Any]]:
    sorted_contributors = sorted(
        contributors,
        key=lambda item: (
            abs(safe_number(item.get("final_score"))),
            str(item.get("timestamp", "")),
        ),
        reverse=True,
    )

    return sorted_contributors[:limit]


def current_payload(
    history_rows: list[dict[str, Any]],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    if not history_rows:
        return {
            **metadata,
            "status": "no_data",
            "message": (
                "No complete UTC day with recognised "
                "strategic indicators was available."
            ),
            "current": None,
        }

    latest = history_rows[-1]

    return {
        **metadata,
        "status": "ok",
        "latest_complete_utc_day": latest["date"],
        "current": {
            "date": latest["date"],
            "calculation_mode": latest[
                "calculation_mode"
            ],
            "usa": {
                **latest["usa"],
                "strongest_contributors": (
                    strongest_contributors(
                        latest["usa"].get(
                            "contributors",
                            [],
                        )
                    )
                ),
            },
            "iran": {
                **latest["iran"],
                "strongest_contributors": (
                    strongest_contributors(
                        latest["iran"].get(
                            "contributors",
                            [],
                        )
                    )
                ),
            },
            "overall": latest["overall"],
        },
    }


# =====================================================================
# MAIN
# =====================================================================

def main() -> None:
    repo_root = Path(__file__).resolve().parent.parent

    non_kinetic_path = repo_root / NON_KINETIC_INPUT
    interests_path = repo_root / INTERESTS_INPUT
    indicators_path = repo_root / INDICATORS_INPUT

    current_output_path = repo_root / CURRENT_OUTPUT
    history_output_path = repo_root / HISTORY_OUTPUT

    non_kinetic_payload = load_json(
        non_kinetic_path,
        required=True,
    )

    interests_payload = load_json(
        interests_path,
        required=True,
    )

    indicators_payload = load_json(
        indicators_path,
        required=True,
    )

    existing_history = load_json(
        history_output_path,
        required=False,
    )

    kinetic_path = find_kinetic_input(repo_root)
    kinetic_payload: dict[str, Any] = {}

    if kinetic_path is not None:
        kinetic_payload = load_json(
            kinetic_path,
            required=False,
        )

    non_kinetic_events = extract_events(
        non_kinetic_payload
    )

    kinetic_events = extract_events(
        kinetic_payload
    )

    all_events = merge_events(
        non_kinetic_events,
        kinetic_events,
    )

    indicator_config = build_indicator_config(
        indicators_payload
    )

    interest_config = build_interest_config(
        interests_payload
    )

    configuration_warnings = validate_configuration(
        indicator_config
    )

    contributions: list[dict[str, Any]] = []

    skipped_without_timestamp = 0
    skipped_current_utc_day = 0

    current_utc_date = datetime.now(
        timezone.utc
    ).date()

    for event in all_events:
        timestamp = event_timestamp(event)

        if timestamp is None:
            skipped_without_timestamp += 1
            continue

        if timestamp.date() >= current_utc_date:
            skipped_current_utc_day += 1
            continue

        contributions.extend(
            analyse_event(
                event=event,
                indicator_config=indicator_config,
                interest_config=interest_config,
            )
        )

    contributions.sort(
        key=lambda item: (
            str(item.get("timestamp", "")),
            str(item.get("actor", "")),
            str(item.get("event_id", "")),
        )
    )

    grouped = group_contributions_by_day(
        contributions
    )

    history_rows = build_history_rows(
        grouped=grouped,
        existing_history=existing_history,
    )

    generated_at = datetime.now(
        timezone.utc
    ).isoformat()

    metadata = {
        "generated_at": generated_at,
        "model": MODEL_VERSION,
        "description": (
            "Explainable strategic pressure layer for "
            "the United States-Iran conflict."
        ),
        "scoring_formula": (
            "final_event_score = "
            "existing_operational_component + "
            "strategic_modifier"
        ),
        "current_day_policy": (
            "The current UTC day is excluded."
        ),
        "rolling_window_days": ROLLING_WINDOW_DAYS,
        "index_formula": (
            f"pressure_index = clamp("
            f"{INDEX_BASELINE} + "
            f"weighted_7d_score * "
            f"{INDEX_POINTS_PER_SCORE}, 0, 100)"
        ),
        "context_multiplier": (
            "Fixed at 1.0 in V1."
        ),
        "interest_weight_policy": (
            "Strategic interest weights are stored "
            "for explainability but do not alter V1 scores."
        ),
        "inputs": {
            "non_kinetic": NON_KINETIC_INPUT,
            "kinetic": (
                str(
                    kinetic_path.relative_to(
                        repo_root
                    )
                )
                if kinetic_path is not None
                else None
            ),
            "strategic_interests": INTERESTS_INPUT,
            "strategic_indicators": INDICATORS_INPUT,
        },
        "statistics": {
            "non_kinetic_events_loaded": len(
                non_kinetic_events
            ),
            "kinetic_events_loaded": len(
                kinetic_events
            ),
            "unique_events_scanned": len(
                all_events
            ),
            "strategic_contributions": len(
                contributions
            ),
            "contributions_by_actor": (
                actor_contribution_count(
                    contributions
                )
            ),
            "contributions_by_source_layer": (
                source_count(contributions)
            ),
            "skipped_without_timestamp": (
                skipped_without_timestamp
            ),
            "skipped_current_utc_day": (
                skipped_current_utc_day
            ),
            "history_day_count": len(
                history_rows
            ),
        },
        "configuration_warnings": (
            configuration_warnings
        ),
    }

    history_payload = {
        **metadata,
        "status": (
            "ok"
            if history_rows
            else "no_data"
        ),
        "days": history_rows,
    }

    latest_payload = current_payload(
        history_rows=history_rows,
        metadata=metadata,
    )

    write_json(
        history_output_path,
        history_payload,
    )

    write_json(
        current_output_path,
        latest_payload,
    )

    print(
        "Strategic Pressure Engine V1 completed."
    )
    print(
        f"Non-kinetic events loaded: "
        f"{len(non_kinetic_events)}"
    )
    print(
        f"Kinetic events loaded: "
        f"{len(kinetic_events)}"
    )
    print(
        f"Unique events scanned: "
        f"{len(all_events)}"
    )
    print(
        f"Strategic contributions: "
        f"{len(contributions)}"
    )
    print(
        f"History days: "
        f"{len(history_rows)}"
    )

    if kinetic_path is None:
        print(
            "Kinetic input: not found. "
            "The engine used the non-kinetic "
            "event timeline only."
        )
    else:
        print(
            f"Kinetic input: {kinetic_path}"
        )

    if history_rows:
        latest = history_rows[-1]

        print(
            f"Latest complete UTC day: "
            f"{latest['date']}"
        )
        print(
            f"USA pressure: "
            f"{latest['usa']['pressure_index_7d']}"
        )
        print(
            f"Iran pressure: "
            f"{latest['iran']['pressure_index_7d']}"
        )
        print(
            f"Overall pressure: "
            f"{latest['overall']['pressure_index_7d']}"
        )

    if configuration_warnings:
        print("Configuration warnings:")

        for warning in configuration_warnings:
            print(f"- {warning}")

    print(
        f"Current output: "
        f"{current_output_path}"
    )
    print(
        f"History output: "
        f"{history_output_path}"
    )


if __name__ == "__main__":
    main()
