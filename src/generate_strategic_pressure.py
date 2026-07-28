import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


# =====================================================================
# Conflict End Matrix -> Strategic Pressure Engine V1.1
#
# Main corrections:
# - Bilateral diplomacy can affect both the USA and Iran.
# - Stronger USA actor recognition.
# - Stricter Iranian and Supreme Leader recognition.
# - No uncontrolled stacking of overlapping indicators.
# - One strongest increase and one strongest decrease indicator
#   are allowed per actor and event.
# - Pressure index 50 is classified as balanced.
#
# Inputs:
# - docs/event_timeline.json
# - docs/kinetic_events.json, if available
# - data/strategic/strategic_interests.json
# - data/strategic/strategic_indicators.json
#
# Outputs:
# - docs/strategic_pressure.json
# - docs/strategic_pressure_history.json
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

MODEL_VERSION = "strategic_pressure_v1_1"

ROLLING_WINDOW_DAYS = 7
INDEX_BASELINE = 50.0
INDEX_POINTS_PER_SCORE = 2.0

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
# ACTOR RECOGNITION
# =====================================================================

ACTOR_PATTERNS: dict[str, list[str]] = {
    "usa": [
        r"\bunited states\b",
        r"\bu\.s\.\b",
        r"\bu\.s\b",
        r"\bus military\b",
        r"\bus forces\b",
        r"\bus navy\b",
        r"\bus air force\b",
        r"\bamerican military\b",
        r"\bamerican forces\b",
        r"\bamerican troops\b",
        r"\bwashington\b",
        r"\bwhite house\b",
        r"\bpentagon\b",
        r"\bcentcom\b",
        r"\bus treasury\b",
        r"\bu\.s\. treasury\b",
        r"\btrump\b",
        r"\bpresident trump\b",
        r"\buss\s+[a-z0-9\-]+\b",
    ],
    "iran": [
        r"\biran\b",
        r"\biranian\b",
        r"\biranians\b",
        r"\btehran\b",
        r"\birgc\b",
        r"\bislamic revolutionary guard corps\b",
        r"\brevolutionary guards?\b",
        r"\bkhamenei\b",
        r"\bayatollah khamenei\b",
        r"\bsupreme leader\b",
    ],
}


# =====================================================================
# BILATERAL EVENTS
#
# These events can legitimately contribute to both actors.
# =====================================================================

BILATERAL_INDICATORS = {
    "negotiation",
    "ceasefire_support",
}

BILATERAL_PATTERNS = [
    r"\bus[- ]iran\b.*\b(?:talks?|negotiations?|dialogue|deal)\b",
    r"\b(?:talks?|negotiations?|dialogue|deal)\b.*\bus[- ]iran\b",
    r"\bunited states\b.*\biran\b.*\b(?:talks?|negotiations?|dialogue)\b",
    r"\biran\b.*\bunited states\b.*\b(?:talks?|negotiations?|dialogue)\b",
    r"\bu\.s\.\b.*\biran\b.*\b(?:talks?|negotiations?|dialogue)\b",
    r"\biran\b.*\bu\.s\.\b.*\b(?:talks?|negotiations?|dialogue)\b",
    r"\biran war talks\b",
    r"\bpeace talks\b.*\b(?:iran|u\.s\.|us|united states)\b",
    r"\b(?:iran|u\.s\.|us|united states)\b.*\bpeace talks\b",
]


# =====================================================================
# INDICATOR RECOGNITION
#
# The points are loaded from strategic_indicators.json.
# These patterns only identify the indicator.
# =====================================================================

INDICATOR_PATTERNS: dict[str, dict[str, list[str]]] = {
    "usa": {
        "carrier_deployment": [
            r"\bcarrier strike group\b",
            r"\baircraft carrier\b.*\b(?:deploy|deployment|arrive|move|enter)\w*\b",
            r"\b(?:deploy|deployment|arrive|move|enter)\w*\b.*\baircraft carrier\b",
            r"\bcarrier\b.*\bcentcom\b",
            r"\buss\s+[a-z0-9\- ]+\b.*\bcarrier\b",
        ],
        "bomber_deployment": [
            r"\b(?:b-1|b-2|b-52)\b.*\b(?:deploy|deployment|arrive|move)\w*\b",
            r"\b(?:deploy|deployment|arrive|move)\w*\b.*\b(?:b-1|b-2|b-52)\b",
            r"\bstrategic bombers?\b.*\bdeploy\w*\b",
            r"\bbombers?\b.*\bcentcom\b",
        ],
        "additional_air_defense": [
            r"\bdeploy\w*\b.*\b(?:patriot|thaad|air defen[cs]e)\b",
            r"\badditional\b.*\b(?:patriot|thaad|air defen[cs]e)\b",
            r"\breinforc\w*\b.*\bair defen[cs]e\b",
        ],
        "new_sanctions": [
            r"\b(?:us|u\.s\.|united states|washington)\b.*\bnew sanctions\b",
            r"\b(?:us|u\.s\.|united states|washington)\b.*\bimpose\w*\b.*\bsanctions\b",
            r"\btreasury\b.*\b(?:sanctions|designates|designation)\b",
            r"\bnew sanctions\b.*\biran\b",
        ],
        "evacuation_warning": [
            r"\b(?:us|u\.s\.|american)\b.*\bembassy\b.*\b(?:evacuat|depart|leave)\w*\b",
            r"\b(?:ordered|authorized)\s+departure\b",
            r"\bevacuat\w*\b.*\b(?:americans|us citizens|u\.s\. citizens)\b",
            r"\b(?:us|u\.s\.)\b.*\btravel warning\b",
        ],
        "force_protection": [
            r"\bforce protection\b.*\b(?:raise|increase|heighten)\w*\b",
            r"\b(?:raise|increase|heighten)\w*\b.*\bforce protection\b",
            r"\b(?:us|u\.s\.|american)\b.*\b(?:forces|bases)\b.*\bhigh alert\b",
            r"\b(?:us|u\.s\.)\b.*\bmilitary readiness\b",
        ],
        "presidential_warning": [
            r"\b(?:trump|us president|u\.s\. president)\b.{0,100}\b(?:warns?|threatens?|ultimatum|military action|severe consequences)\b",
            r"\bwhite house\b.{0,100}\biran\b.{0,100}\b(?:warning|ultimatum|red line|military action)\b",
            r"\btrump\b.{0,100}\biran\b.{0,100}\b(?:strike|attack|retaliation|consequences)\b",
        ],
        "military_exercise": [
            r"\b(?:us|u\.s\.|american)\b.*\bmilitary exercise\b",
            r"\b(?:us|u\.s\.)\b.*\bjoint exercise\b",
            r"\bcentcom\b.*\bexercise\b",
            r"\bexercise\b.*\b(?:us navy|u\.s\. navy|us air force|u\.s\. air force)\b",
        ],
        "strike_preparation": [
            r"\b(?:us|u\.s\.|american)\b.*\bprepar\w*\b.*\bstrike\b",
            r"\bpentagon\b.*\b(?:strike options|attack options|target list)\b",
            r"\b(?:military|air)\s+strike\b.*\bimminent\b",
            r"\b(?:us|u\.s\.)\b.*\bposition\w*\b.*\bforces\b.*\bstrike\b",
            r"\bstrike package\b",
        ],
        "negotiation": [
            r"\b(?:us|u\.s\.|united states|washington|trump)\b.*\b(?:talks?|negotiations?|dialogue)\b",
            r"\b(?:talks?|negotiations?|dialogue)\b.*\b(?:us|u\.s\.|united states|washington|trump)\b",
            r"\bus[- ]iran\b.*\b(?:talks?|negotiations?|dialogue|deal)\b",
            r"\b(?:talks?|negotiations?|dialogue|deal)\b.*\bus[- ]iran\b",
            r"\bu\.s\.\b.*\bpauses?\b.*\bstrikes?\b.*\btalks?\b",
            r"\btrump\b.*\biran war talks\b",
        ],
        "ceasefire_support": [
            r"\b(?:us|u\.s\.|united states|white house|trump)\b.*\b(?:supports?|backs?|calls? for|urges?)\b.*\bcease[- ]?fire\b",
            r"\b(?:us|u\.s\.)\b.*\bcease[- ]?fire proposal\b",
            r"\b(?:us|u\.s\.)\b.*\bpauses?\b.*\bstrikes?\b",
            r"\bpauses?\b.*\b(?:us|u\.s\.)\b.*\bstrikes?\b",
        ],
        "sanction_relief": [
            r"\b(?:us|u\.s\.|united states|washington)\b.*\b(?:lifts?|eases?|waives?|suspends?)\b.*\bsanctions\b",
            r"\bsanctions relief\b",
            r"\bwaiver\b.*\biran\b.*\bsanctions\b",
        ],
        "troop_withdrawal": [
            r"\b(?:us|u\.s\.|american)\b.*\bwithdraw\w*\b.*\b(?:troops|forces|warships|aircraft)\b",
            r"\b(?:troops|forces|warships|aircraft)\b.*\bwithdraw\w*\b.*\b(?:us|u\.s\.)\b",
            r"\bstands? down\b.*\b(?:us|u\.s\.|american)\b.*\bforces\b",
        ],
    },

    "iran": {
        "missile_preparation": [
            r"\biran(?:ian)?\b.*\bmissiles?\b.*\b(?:prepar|ready|readiness|position|deploy)\w*\b",
            r"\b(?:prepar|ready|readiness|position|deploy)\w*\b.*\biran(?:ian)?\b.*\bmissiles?\b",
            r"\birgc\b.*\bmissile units?\b.*\balert\b",
            r"\biranian missile forces?\b.*\bhigh alert\b",
        ],
        "proxy_activation": [
            r"\biran\b.*\b(?:activates?|mobilizes?|mobilises?|orders?)\b.*\b(?:proxies|proxy forces|allied militias)\b",
            r"\biran-backed\b.*\b(?:militia|group|forces?)\b.*\b(?:mobiliz|activat|prepare|alert)\w*\b",
            r"\baxis of resistance\b.*\b(?:mobiliz|activat|prepare)\w*\b",
        ],
        "missile_test": [
            r"\biran(?:ian)?\b.*\b(?:tests?|tested|test-fires?|test-fired|launches?)\b.*\bmissiles?\b",
            r"\bmissile\b.*\btest\b.*\biran\b",
            r"\birgc\b.*\btest\w*\b.*\bmissiles?\b",
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
            r"\b(?:khamenei|supreme leader|ayatollah khamenei)\b.{0,80}\b(?:warns?|threatens?|vows?|orders?|promises?)\b.{0,80}\b(?:attack|strike|retaliate|revenge|punish|destroy|military response)\b",
            r"\b(?:khamenei|supreme leader|ayatollah khamenei)\b.{0,100}\b(?:crushing response|harsh response|severe consequences|military retaliation)\b",
            r"\b(?:attack|strike|retaliation|revenge)\b.{0,80}\b(?:khamenei|supreme leader|ayatollah khamenei)\b",
        ],
        "irgc_alert": [
            r"\birgc\b.*\b(?:high alert|raised alert|combat readiness|maximum readiness)\b",
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
            r"\biran(?:ian)?\b.*\bprepar\w*\b.*\b(?:strike|attack|retaliation)\b",
            r"\birgc\b.*\bprepar\w*\b.*\b(?:strike|attack|response)\b",
            r"\biran\b.*\bimminent\b.*\b(?:strike|attack|retaliation)\b",
            r"\biranian\b.*\btarget list\b",
        ],
        "negotiation": [
            r"\biran\b.*\b(?:talks?|negotiations?|dialogue)\b",
            r"\b(?:talks?|negotiations?|dialogue)\b.*\biran\b",
            r"\btehran\b.*\bresume\w*\b.*\bnegotiations\b",
            r"\bus[- ]iran\b.*\b(?:talks?|negotiations?|dialogue|deal)\b",
            r"\b(?:talks?|negotiations?|dialogue|deal)\b.*\bus[- ]iran\b",
            r"\biran war talks\b",
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


# =====================================================================
# GENERAL UTILITIES
# =====================================================================

def load_json(path: Path, required: bool = True) -> dict[str, Any]:
    if not path.exists():
        if required:
            raise FileNotFoundError(f"Required file not found: {path}")
        return {}

    with path.open("r", encoding="utf-8") as file:
        payload = json.load(file)

    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object: {path}")

    return payload


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    temporary_path = path.with_suffix(path.suffix + ".tmp")

    with temporary_path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2, ensure_ascii=False)

    temporary_path.replace(path)


def safe_number(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def round_score(value: float) -> float:
    return round(float(value), 2)


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


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


def regex_matches(patterns: list[str], text: str) -> list[str]:
    return [
        pattern
        for pattern in patterns
        if re.search(pattern, text, flags=re.IGNORECASE)
    ]


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
    for key in (
        "timestamp",
        "published",
        "date",
        "datetime",
        "created_at",
        "event_time",
    ):
        parsed = parse_datetime(event.get(key))

        if parsed is not None:
            return parsed

    return None


# =====================================================================
# INPUT PROCESSING
# =====================================================================

def extract_events(payload: dict[str, Any]) -> list[dict[str, Any]]:
    for key in (
        "events",
        "kinetic_events",
        "items",
        "articles",
        "data",
    ):
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

    event_id = normalise_text(
        event.get("event_id")
        or event.get("id")
    )

    if event_id:
        source_layer = normalise_text(
            event.get("_strategic_source_layer")
        )
        return f"{source_layer}:id:{event_id}"

    title = normalise_text(
        event.get("title")
        or event.get("description")
        or event.get("event")
    )

    timestamp = event_timestamp(event)

    return (
        f"title:{title}|"
        f"timestamp:{timestamp.isoformat() if timestamp else ''}"
    )


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

    events = list(unique.values())

    events.sort(
        key=lambda item: (
            event_timestamp(item)
            or datetime.min.replace(tzinfo=timezone.utc)
        )
    )

    return events


def event_text(event: dict[str, Any]) -> str:
    parts: list[str] = []

    for key in (
        "title",
        "description",
        "summary",
        "event",
        "diplomatic_event",
        "military_event",
        "event_type",
        "subtype",
        "primary_keyword",
        "target",
        "location",
        "source",
    ):
        value = event.get(key)

        if value:
            parts.append(str(value))

    for key in (
        "keywords",
        "actors",
        "matched_keywords",
        "tags",
    ):
        values = event.get(key)

        if not isinstance(values, list):
            continue

        for value in values:
            if isinstance(value, dict):
                parts.extend(
                    str(item)
                    for item in value.values()
                    if item not in (None, "")
                )
            elif value not in (None, ""):
                parts.append(str(value))

    return normalise_text(" ".join(parts))


# =====================================================================
# CONFIGURATION
# =====================================================================

def build_indicator_config(
    payload: dict[str, Any],
) -> dict[str, dict[str, dict[str, Any]]]:
    result: dict[str, dict[str, dict[str, Any]]] = {
        "usa": {},
        "iran": {},
    }

    for actor in ("usa", "iran"):
        actor_payload = payload.get(actor, {})

        if not isinstance(actor_payload, dict):
            continue

        for group in (
            "increase_pressure",
            "decrease_pressure",
        ):
            indicators = actor_payload.get(group, [])

            if not isinstance(indicators, list):
                continue

            for indicator in indicators:
                if not isinstance(indicator, dict):
                    continue

                indicator_id = str(
                    indicator.get("id", "")
                ).strip()

                if not indicator_id:
                    continue

                score = safe_number(indicator.get("score"))

                result[actor][indicator_id] = {
                    "id": indicator_id,
                    "name": str(
                        indicator.get("name", indicator_id)
                    ),
                    "configured_score": score,
                    "configured_direction": (
                        "increase"
                        if score > 0
                        else "decrease"
                        if score < 0
                        else "neutral"
                    ),
                }

    return result


def build_interest_config(
    payload: dict[str, Any],
) -> dict[str, dict[str, dict[str, Any]]]:
    result: dict[str, dict[str, dict[str, Any]]] = {
        "usa": {},
        "iran": {},
    }

    actors = payload.get("actors", {})

    if not isinstance(actors, dict):
        return result

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

            interest_id = str(
                interest.get("id", "")
            ).strip()

            if not interest_id:
                continue

            result[actor][interest_id] = {
                "id": interest_id,
                "name": str(
                    interest.get("name", interest_id)
                ),
                "weight": safe_number(
                    interest.get("weight")
                ),
            }

    return result


def validate_configuration(
    indicator_config: dict[str, dict[str, dict[str, Any]]],
) -> list[str]:
    warnings: list[str] = []

    for actor in ("usa", "iran"):
        configured = set(
            indicator_config.get(actor, {}).keys()
        )

        recognised = set(
            INDICATOR_PATTERNS.get(actor, {}).keys()
        )

        for indicator_id in sorted(recognised - configured):
            warnings.append(
                f"{actor}.{indicator_id} has patterns "
                "but is missing from strategic_indicators.json"
            )

        for indicator_id in sorted(configured - recognised):
            warnings.append(
                f"{actor}.{indicator_id} is configured "
                "but has no recognition pattern"
            )

    return warnings


# =====================================================================
# RECOGNITION GUARDS
# =====================================================================

def detect_actors(text: str) -> set[str]:
    actors: set[str] = set()

    for actor, patterns in ACTOR_PATTERNS.items():
        if regex_matches(patterns, text):
            actors.add(actor)

    return actors


def is_bilateral_event(text: str) -> bool:
    actor_set = detect_actors(text)

    if actor_set == {"usa", "iran"}:
        if regex_matches(BILATERAL_PATTERNS, text):
            return True

        if re.search(
            r"\b(?:talks?|negotiations?|dialogue|peace deal|cease[- ]?fire)\b",
            text,
            flags=re.IGNORECASE,
        ):
            return True

    return bool(regex_matches(BILATERAL_PATTERNS, text))


def has_explicit_threat_language(text: str) -> bool:
    threat_patterns = [
        r"\bthreatens?\b",
        r"\bvows?\b.*\b(?:attack|strike|retaliate|revenge)\b",
        r"\bwarns?\b.*\b(?:attack|strike|retaliation|military response|consequences)\b",
        r"\bcrushing response\b",
        r"\bharsh response\b",
        r"\bmilitary retaliation\b",
        r"\bsevere consequences\b",
        r"\bwill retaliate\b",
        r"\bwill strike\b",
        r"\bwill attack\b",
    ]

    return bool(regex_matches(threat_patterns, text))


def is_conditional_diplomacy(text: str) -> bool:
    patterns = [
        r"\bties?\b.*\b(?:peace deal|agreement|cease[- ]?fire|talks?)\b.*\bto\b",
        r"\b(?:peace deal|agreement|cease[- ]?fire|talks?)\b.*\bconditional\b",
        r"\bcondition(?:s|al)?\b.*\b(?:peace deal|agreement|cease[- ]?fire|talks?)\b",
        r"\bon condition that\b",
        r"\bonly if\b.*\b(?:peace|cease[- ]?fire|deal|talks?)\b",
    ]

    return bool(regex_matches(patterns, text))


def indicator_allowed(
    actor: str,
    indicator_id: str,
    text: str,
    bilateral: bool,
) -> bool:
    if indicator_id in BILATERAL_INDICATORS:
        if bilateral:
            return True

    if indicator_id == "supreme_leader_statement":
        if is_conditional_diplomacy(text):
            return False

        if not has_explicit_threat_language(text):
            return False

    if actor == "iran":
        if indicator_id not in BILATERAL_INDICATORS:
            iran_named = bool(
                regex_matches(ACTOR_PATTERNS["iran"], text)
            )

            if not iran_named:
                return False

    if actor == "usa":
        if indicator_id not in BILATERAL_INDICATORS:
            usa_named = bool(
                regex_matches(ACTOR_PATTERNS["usa"], text)
            )

            if not usa_named:
                return False

    return True


# =====================================================================
# INDICATOR SELECTION
# =====================================================================

def recognise_indicators(
    actor: str,
    text: str,
    indicator_config: dict[str, dict[str, dict[str, Any]]],
    bilateral: bool,
) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []

    for indicator_id, patterns in INDICATOR_PATTERNS[actor].items():
        configuration = indicator_config.get(
            actor,
            {},
        ).get(indicator_id)

        if configuration is None:
            continue

        matched_patterns = regex_matches(patterns, text)

        if not matched_patterns:
            continue

        if not indicator_allowed(
            actor=actor,
            indicator_id=indicator_id,
            text=text,
            bilateral=bilateral,
        ):
            continue

        result = dict(configuration)
        result["matched_patterns"] = matched_patterns

        matches.append(result)

    return select_non_overlapping_indicators(matches)


def select_non_overlapping_indicators(
    matches: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Prevent uncontrolled score stacking.

    Per actor and event:
    - keep the strongest pressure-increasing indicator;
    - keep the strongest pressure-decreasing indicator;
    - allow both only when both directions are genuinely present.
    """

    increasing = [
        match
        for match in matches
        if safe_number(match.get("configured_score")) > 0
    ]

    decreasing = [
        match
        for match in matches
        if safe_number(match.get("configured_score")) < 0
    ]

    selected: list[dict[str, Any]] = []

    if increasing:
        selected.append(
            max(
                increasing,
                key=lambda item: (
                    abs(
                        safe_number(
                            item.get("configured_score")
                        )
                    ),
                    len(item.get("matched_patterns", [])),
                ),
            )
        )

    if decreasing:
        selected.append(
            max(
                decreasing,
                key=lambda item: (
                    abs(
                        safe_number(
                            item.get("configured_score")
                        )
                    ),
                    len(item.get("matched_patterns", [])),
                ),
            )
        )

    return selected


# =====================================================================
# OPERATIONAL COMPONENT
# =====================================================================

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

    if direction in {
        "mixed",
        "neutral",
        "unclear",
    }:
        return "mixed"

    event_type = normalise_text(
        event.get("event_type")
    )

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
    values = [
        abs(safe_number(event.get("score"))),
        abs(safe_number(event.get("direction_score"))),
        abs(safe_number(event.get("severity_score"))),
        abs(safe_number(event.get("event_score"))),
        abs(safe_number(event.get("weight"))),
        abs(safe_number(event.get("severity"))),
    ]

    magnitude = max(values, default=0.0)

    return magnitude if magnitude > 0 else 1.0


def calculate_operational_component(
    event: dict[str, Any],
) -> tuple[float, str]:
    direction = infer_direction(event)
    magnitude = operational_magnitude(event)

    if direction == "escalation":
        return magnitude, direction

    if direction == "de-escalation":
        return -magnitude, direction

    return 0.0, direction


# =====================================================================
# CONTRIBUTION BUILDING
# =====================================================================

def interest_details(
    actor: str,
    indicator_id: str,
    interest_config: dict[str, dict[str, dict[str, Any]]],
) -> dict[str, Any] | None:
    interest_id = INDICATOR_INTEREST_MAP.get(
        actor,
        {},
    ).get(indicator_id)

    if not interest_id:
        return None

    interest = interest_config.get(
        actor,
        {},
    ).get(interest_id)

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


def build_reason(
    actor: str,
    title: str,
    operational_component: float,
    strategic_modifier: float,
    final_score: float,
    indicators: list[dict[str, Any]],
) -> str:
    actor_name = (
        "United States"
        if actor == "usa"
        else "Iran"
    )

    names = ", ".join(
        str(
            indicator.get(
                "name",
                indicator.get("id", ""),
            )
        )
        for indicator in indicators
    )

    return (
        f"{actor_name}: {names}. "
        f"Operational component: "
        f"{operational_component:+.2f}; "
        f"strategic modifier: "
        f"{strategic_modifier:+.2f}; "
        f"final contribution: "
        f"{final_score:+.2f}. "
        f"Event: {title}"
    )


def build_contribution(
    event: dict[str, Any],
    actor: str,
    indicators: list[dict[str, Any]],
    interest_config: dict[str, dict[str, dict[str, Any]]],
    bilateral: bool,
) -> dict[str, Any]:
    timestamp = event_timestamp(event)

    operational_component, event_direction = (
        calculate_operational_component(event)
    )

    strategic_modifier = sum(
        safe_number(
            indicator.get("configured_score")
        )
        for indicator in indicators
    )

    final_score = (
        operational_component
        + strategic_modifier
    )

    indicator_results: list[dict[str, Any]] = []

    for indicator in indicators:
        indicator_id = str(indicator.get("id", ""))

        indicator_results.append({
            "id": indicator_id,
            "name": indicator.get("name"),
            "score": round_score(
                safe_number(
                    indicator.get("configured_score")
                )
            ),
            "direction": indicator.get(
                "configured_direction"
            ),
            "interest": interest_details(
                actor,
                indicator_id,
                interest_config,
            ),
            "recognition_rule_count": len(
                indicator.get(
                    "matched_patterns",
                    [],
                )
            ),
        })

    title = str(
        event.get("title")
        or event.get("event")
        or event.get("description")
        or ""
    )

    event_id = str(
        event.get("event_id")
        or event.get("id")
        or event_identity(event)
    )

    return {
        "event_id": event_id,
        "timestamp": (
            timestamp.isoformat()
            if timestamp
            else ""
        ),
        "date": (
            timestamp.date().isoformat()
            if timestamp
            else ""
        ),
        "actor": actor,
        "bilateral_event": bilateral,
        "title": title,
        "source_layer": event.get(
            "_strategic_source_layer",
            "unknown",
        ),
        "event_type": event.get(
            "event_type",
            "",
        ),
        "event_direction": event_direction,
        "operational_component": round_score(
            operational_component
        ),
        "strategic_modifier": round_score(
            strategic_modifier
        ),
        "context_multiplier": 1.0,
        "final_score": round_score(
            final_score
        ),
        "indicators": indicator_results,
        "reason": build_reason(
            actor=actor,
            title=title,
            operational_component=operational_component,
            strategic_modifier=strategic_modifier,
            final_score=final_score,
            indicators=indicators,
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
            safe_number(
                event.get("direction_score")
            )
        ),
    }


def analyse_event(
    event: dict[str, Any],
    indicator_config: dict[str, dict[str, dict[str, Any]]],
    interest_config: dict[str, dict[str, dict[str, Any]]],
) -> list[dict[str, Any]]:
    timestamp = event_timestamp(event)

    if timestamp is None:
        return []

    current_utc_date = datetime.now(
        timezone.utc
    ).date()

    if timestamp.date() >= current_utc_date:
        return []

    text = event_text(event)
    detected_actors = detect_actors(text)
    bilateral = is_bilateral_event(text)

    actors_to_check: set[str] = set(detected_actors)

    if bilateral:
        actors_to_check.update({"usa", "iran"})

    contributions: list[dict[str, Any]] = []

    for actor in ("usa", "iran"):
        if actor not in actors_to_check:
            continue

        indicators = recognise_indicators(
            actor=actor,
            text=text,
            indicator_config=indicator_config,
            bilateral=bilateral,
        )

        if not indicators:
            continue

        contributions.append(
            build_contribution(
                event=event,
                actor=actor,
                indicators=indicators,
                interest_config=interest_config,
                bilateral=bilateral,
            )
        )

    return contributions


# =====================================================================
# DAILY AGGREGATION
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
        day = str(
            contribution.get("date", "")
        )

        actor = str(
            contribution.get("actor", "")
        )

        if not day or actor not in {
            "usa",
            "iran",
        }:
            continue

        if day not in grouped:
            grouped[day] = {
                "date": day,
                "usa": empty_actor_day(),
                "iran": empty_actor_day(),
            }

        actor_day = grouped[day][actor]
        score = safe_number(
            contribution.get("final_score")
        )

        actor_day["raw_score"] += score
        actor_day["event_count"] += 1
        actor_day["contributors"].append(
            contribution
        )

        if score > 0:
            actor_day["positive_score"] += score
            actor_day["increase_event_count"] += 1

        elif score < 0:
            actor_day["negative_score"] += score
            actor_day["decrease_event_count"] += 1

    for day_payload in grouped.values():
        for actor in ("usa", "iran"):
            actor_day = day_payload[actor]

            for field in (
                "raw_score",
                "positive_score",
                "negative_score",
            ):
                actor_day[field] = round_score(
                    actor_day[field]
                )

            actor_day["contributors"].sort(
                key=lambda item: (
                    abs(
                        safe_number(
                            item.get("final_score")
                        )
                    ),
                    str(item.get("timestamp", "")),
                ),
                reverse=True,
            )

    return grouped


def complete_date_range(
    grouped: dict[str, dict[str, Any]],
) -> list[str]:
    if not grouped:
        return []

    parsed_dates = sorted(
        date.fromisoformat(day)
        for day in grouped
    )

    current = parsed_dates[0]
    final = parsed_dates[-1]

    result: list[str] = []

    while current <= final:
        result.append(current.isoformat())
        current = date.fromordinal(
            current.toordinal() + 1
        )

    return result


def weighted_rolling_score(
    rows: list[dict[str, Any]],
    index: int,
    actor: str,
) -> float:
    total = 0.0

    for offset in range(ROLLING_WINDOW_DAYS):
        source_index = index - offset

        if source_index < 0:
            break

        weight = ROLLING_WEIGHTS[offset]

        raw_score = safe_number(
            rows[source_index]
            .get(actor, {})
            .get("raw_score")
        )

        total += raw_score * weight

    return total


def score_to_index(weighted_score: float) -> float:
    return round_score(
        clamp(
            INDEX_BASELINE
            + weighted_score
            * INDEX_POINTS_PER_SCORE,
            0.0,
            100.0,
        )
    )


def pressure_level(index_value: float) -> str:
    if index_value >= 80:
        return "critical"

    if index_value >= 65:
        return "high"

    if index_value >= 55:
        return "elevated"

    if index_value >= 45:
        return "balanced"

    if index_value >= 30:
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
    days = complete_date_range(grouped)

    if not days:
        return []

    existing_modes: dict[str, str] = {}

    for row in existing_history.get(
        "days",
        [],
    ) or []:
        if not isinstance(row, dict):
            continue

        row_date = str(row.get("date", ""))

        if row_date:
            existing_modes[row_date] = str(
                row.get(
                    "calculation_mode",
                    "",
                )
            )

    newest_day = days[-1]
    rows: list[dict[str, Any]] = []

    for day in days:
        source = grouped.get(
            day,
            {
                "date": day,
                "usa": empty_actor_day(),
                "iran": empty_actor_day(),
            },
        )

        previous_mode = existing_modes.get(day)

        if previous_mode == "live":
            calculation_mode = "live"

        elif day == newest_day:
            calculation_mode = "live"

        else:
            calculation_mode = "historical_backfill"

        rows.append({
            "date": day,
            "calculation_mode": calculation_mode,
            "usa": source["usa"],
            "iran": source["iran"],
        })

    for index, row in enumerate(rows):
        previous_row = (
            rows[index - 1]
            if index > 0
            else None
        )

        actor_indices: list[float] = []

        for actor in ("usa", "iran"):
            weighted_score = weighted_rolling_score(
                rows,
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
                    INDEX_BASELINE,
                )

            row[actor]["weighted_score_7d"] = (
                round_score(weighted_score)
            )

            row[actor]["pressure_index_7d"] = (
                current_index
            )

            row[actor]["pressure_level"] = (
                pressure_level(current_index)
            )

            row[actor]["trend"] = (
                pressure_trend(
                    current_index,
                    previous_index,
                )
            )

            actor_indices.append(current_index)

        overall_index = round_score(
            sum(actor_indices)
            / len(actor_indices)
        )

        previous_overall = None

        if previous_row is not None:
            previous_overall = safe_number(
                previous_row
                .get("overall", {})
                .get("pressure_index_7d"),
                INDEX_BASELINE,
            )

        row["overall"] = {
            "pressure_index_7d": overall_index,
            "pressure_level": pressure_level(
                overall_index
            ),
            "trend": pressure_trend(
                overall_index,
                previous_overall,
            ),
            "calculation": (
                "Arithmetic mean of USA and Iran "
                "seven-day pressure indices"
            ),
        }

    return rows


# =====================================================================
# STATISTICS
# =====================================================================

def contribution_count_by_actor(
    contributions: list[dict[str, Any]],
) -> dict[str, int]:
    counts = {
        "usa": 0,
        "iran": 0,
    }

    for contribution in contributions:
        actor = str(
            contribution.get("actor", "")
        )

        if actor in counts:
            counts[actor] += 1

    return counts


def contribution_count_by_layer(
    contributions: list[dict[str, Any]],
) -> dict[str, int]:
    counts: dict[str, int] = {}

    for contribution in contributions:
        layer = str(
            contribution.get(
                "source_layer",
                "unknown",
            )
        )

        counts[layer] = counts.get(layer, 0) + 1

    return counts


def indicator_count(
    contributions: list[dict[str, Any]],
) -> dict[str, int]:
    counts: dict[str, int] = {}

    for contribution in contributions:
        actor = str(
            contribution.get("actor", "")
        )

        for indicator in contribution.get(
            "indicators",
            [],
        ):
            if not isinstance(indicator, dict):
                continue

            indicator_id = str(
                indicator.get("id", "")
            )

            key = f"{actor}:{indicator_id}"

            counts[key] = counts.get(key, 0) + 1

    return dict(
        sorted(
            counts.items(),
            key=lambda item: (
                -item[1],
                item[0],
            ),
        )
    )


def strongest_contributors(
    contributors: list[dict[str, Any]],
    limit: int = 10,
) -> list[dict[str, Any]]:
    return sorted(
        contributors,
        key=lambda item: (
            abs(
                safe_number(
                    item.get("final_score")
                )
            ),
            str(item.get("timestamp", "")),
        ),
        reverse=True,
    )[:limit]


# =====================================================================
# MAIN
# =====================================================================

def main() -> None:
    repo_root = (
        Path(__file__).resolve().parent.parent
    )

    non_kinetic_path = (
        repo_root / NON_KINETIC_INPUT
    )

    indicators_path = (
        repo_root / INDICATORS_INPUT
    )

    interests_path = (
        repo_root / INTERESTS_INPUT
    )

    current_output_path = (
        repo_root / CURRENT_OUTPUT
    )

    history_output_path = (
        repo_root / HISTORY_OUTPUT
    )

    non_kinetic_payload = load_json(
        non_kinetic_path
    )

    indicators_payload = load_json(
        indicators_path
    )

    interests_payload = load_json(
        interests_path
    )

    existing_history = load_json(
        history_output_path,
        required=False,
    )

    kinetic_path = find_kinetic_input(
        repo_root
    )

    kinetic_payload = (
        load_json(
            kinetic_path,
            required=False,
        )
        if kinetic_path
        else {}
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

    configuration_warnings = (
        validate_configuration(
            indicator_config
        )
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

    statistics = {
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
            contribution_count_by_actor(
                contributions
            )
        ),
        "contributions_by_source_layer": (
            contribution_count_by_layer(
                contributions
            )
        ),
        "indicator_counts": indicator_count(
            contributions
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
    }

    metadata = {
        "generated_at": generated_at,
        "model": MODEL_VERSION,
        "description": (
            "Explainable strategic pressure layer "
            "for the United States-Iran conflict."
        ),
        "scoring_formula": (
            "final_event_score = "
            "existing_operational_component + "
            "strategic_modifier"
        ),
        "current_day_policy": (
            "The current UTC day is excluded."
        ),
        "rolling_window_days": (
            ROLLING_WINDOW_DAYS
        ),
        "index_formula": (
            f"pressure_index = clamp("
            f"{INDEX_BASELINE} + "
            f"weighted_7d_score * "
            f"{INDEX_POINTS_PER_SCORE}, "
            f"0, 100)"
        ),
        "context_multiplier": (
            "Fixed at 1.0 in V1.1."
        ),
        "overlap_policy": (
            "Per actor and event, only the strongest "
            "increasing and strongest decreasing "
            "indicator can contribute."
        ),
        "bilateral_policy": (
            "Recognised bilateral negotiation and "
            "ceasefire events may contribute to both "
            "the USA and Iran."
        ),
        "inputs": {
            "non_kinetic": NON_KINETIC_INPUT,
            "kinetic": (
                str(
                    kinetic_path.relative_to(
                        repo_root
                    )
                )
                if kinetic_path
                else None
            ),
            "strategic_interests": (
                INTERESTS_INPUT
            ),
            "strategic_indicators": (
                INDICATORS_INPUT
            ),
        },
        "statistics": statistics,
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

    if history_rows:
        latest = history_rows[-1]

        current_payload = {
            **metadata,
            "status": "ok",
            "latest_complete_utc_day": (
                latest["date"]
            ),
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

    else:
        current_payload = {
            **metadata,
            "status": "no_data",
            "latest_complete_utc_day": None,
            "current": None,
        }

    write_json(
        history_output_path,
        history_payload,
    )

    write_json(
        current_output_path,
        current_payload,
    )

    print(
        "Strategic Pressure Engine V1.1 completed."
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
        "Contributions by actor: "
        f"{statistics['contributions_by_actor']}"
    )

    if history_rows:
        latest = history_rows[-1]

        print(
            f"Latest complete UTC day: "
            f"{latest['date']}"
        )

        print(
            f"USA pressure: "
            f"{latest['usa']['pressure_index_7d']} "
            f"({latest['usa']['pressure_level']})"
        )

        print(
            f"Iran pressure: "
            f"{latest['iran']['pressure_index_7d']} "
            f"({latest['iran']['pressure_level']})"
        )

        print(
            f"Overall pressure: "
            f"{latest['overall']['pressure_index_7d']} "
            f"({latest['overall']['pressure_level']})"
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
