#!/usr/bin/env python3
"""
Import and CLEAN the latest IranStrike military-event layer from:
mikloshetzer-sketch/me-security-monitor/data/iranstrike.json

Goals
-----
- Keep only recent kinetic events (default: 90 days).
- Reject records that are military-themed but are not actual kinetic events.
- Preserve the previous known-good output if the source is stale/invalid.
- Keep the existing Conflict End Matrix scoring pipeline untouched.

Examples of records rejected by this cleaner:
- "investigating whether Russia provided Iran ... drone technology"
- "air raid sirens activated in Bahrain"
- "reports 53 deaths ... from airstrikes over the past month"
- capability / stockpile / historical-summary / hypothetical reporting

Examples retained:
- missiles launched / impacted / intercepted
- drone attack / drone intercepted
- airstrike / strike carried out
- explosions reported at a place/time
- ground clashes
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


DEFAULT_SOURCE_URL = (
    "https://raw.githubusercontent.com/"
    "mikloshetzer-sketch/me-security-monitor/main/data/iranstrike.json"
)

KINETIC_CATEGORIES = {
    "missile",
    "drone",
    "strike",
    "airstrike",
    "explosion",
    "ground",
    "intercept",
}

ORIGIN_LABELS = {
    "USA": "United States",
    "US": "United States",
    "ISR": "Israel",
    "IRN": "Iran",
    "LBN": "Lebanon",
    "JOR": "Jordan",
    "IRQ": "Iraq",
    "SYR": "Syria",
    "YEM": "Yemen",
    "HOU": "Houthis",
    "SAU": "Saudi Arabia",
    "ARE": "United Arab Emirates",
    "KWT": "Kuwait",
    "BHR": "Bahrain",
    "QAT": "Qatar",
}

# ---------------------------------------------------------------------
# NON-EVENT / CONTEXT-ONLY FILTERS
# ---------------------------------------------------------------------

# These phrases usually indicate that the record is commentary,
# retrospective reporting, capability assessment or a hypothetical,
# rather than an event occurring at the record timestamp.
NON_EVENT_PATTERNS = [
    r"\binvestigat(?:e|es|ed|ing)\s+whether\b",
    r"\bexamining whether\b",
    r"\blooking into whether\b",
    r"\breports?\b.*\bover the past\b",
    r"\breports?\b.*\bin the past\b",
    r"\bover the past (?:day|week|month|year)s?\b",
    r"\bin recent (?:days|weeks|months)\b",
    r"\bsince (?:the start|the beginning|last|early)\b",
    r"\bcumulative\b",
    r"\btotal(?:s|led)?\b.*\bsince\b",
    r"\bstockpiles?\b",
    r"\bretains?\b.*\b(?:missile|drone|weapon|capabilit)",
    r"\bcapabilit(?:y|ies)\b",
    r"\bcould\b.*\b(?:attack|strike|launch|target)\b",
    r"\bmay\b.*\b(?:attack|strike|launch|target)\b",
    r"\bmight\b.*\b(?:attack|strike|launch|target)\b",
    r"\bplans?\s+to\b.*\b(?:attack|strike|launch)\b",
    r"\bexpected\s+to\b.*\b(?:attack|strike|launch)\b",
    r"\bprepar(?:e|es|ed|ing)\s+to\b.*\b(?:attack|strike|launch)\b",
    r"\bthreatens?\s+to\b.*\b(?:attack|strike|launch)\b",
    r"\bvows?\s+to\b.*\b(?:attack|strike|launch)\b",
    r"\bwarns?\s+of\b.*\b(?:attack|strike)\b",
    r"\bclaims?\s+(?:it|they|he|she)?\s*(?:has|have)\b.*\bcapabilit",
    r"\bassessment\b",
    r"\banalysis\b",
    r"\breview\b",
]

# Sirens/alerts alone are not a kinetic event unless the same record also
# explicitly says a missile/drone was launched, intercepted, hit, etc.
ALERT_ONLY_PATTERNS = [
    r"\bair raid sirens?\b",
    r"\bsirens? activated\b",
    r"\balert issued\b",
    r"\bwarning sirens?\b",
]

# ---------------------------------------------------------------------
# POSITIVE ACTION PATTERNS
# ---------------------------------------------------------------------

GENERAL_ACTION_PATTERNS = [
    r"\b(?:launch(?:ed|es|ing)?|fire(?:d|s|ing)?|strike(?:s|d|ing)?|attack(?:s|ed|ing)?|bomb(?:s|ed|ing)?|hit(?:s|ting)?|impact(?:s|ed|ing)?|intercept(?:s|ed|ing)?|destroy(?:s|ed|ing)?|engag(?:e|es|ed|ing)?)\b",
    r"\b(?:explosion|explosions|blast|blasts)\s+(?:reported|heard|confirmed)\b",
    r"\b(?:clash|clashes|fighting|combat)\b",
]

CATEGORY_ACTION_PATTERNS = {
    "missile": [
        r"\bmissiles?\b.*\b(?:launch(?:ed|es)?|fire(?:d|s)?|impact(?:ed|s)?|hit(?:s)?|intercept(?:ed|s)?|strike(?:s|d)?)\b",
        r"\b(?:launch(?:ed|es)?|fire(?:d|s)?|intercept(?:ed|s)?|hit(?:s)?|impact(?:ed|s)?)\b.*\bmissiles?\b",
        r"\bballistic missiles?\b",
        r"\bcruise missiles?\b",
    ],
    "drone": [
        r"\bdrones?\b.*\b(?:attack(?:ed|s)?|strike(?:s|d)?|hit(?:s)?|intercept(?:ed|s)?|launch(?:ed|es)?|engag(?:ed|es)?)\b",
        r"\b(?:attack(?:ed|s)?|strike(?:s|d)?|hit(?:s)?|intercept(?:ed|s)?|launch(?:ed|es)?)\b.*\bdrones?\b",
    ],
    "strike": [
        r"\bstrikes?\b",
        r"\bstruck\b",
        r"\battack(?:s|ed|ing)?\b",
    ],
    "airstrike": [
        r"\bairstrikes?\b",
        r"\bair strikes?\b",
        r"\baerial strikes?\b",
        r"\bbombing\b",
    ],
    "explosion": [
        r"\b(?:explosion|explosions|blast|blasts)\b.*\b(?:reported|heard|confirmed|rocked)\b",
        r"\b(?:reported|heard|confirmed)\b.*\b(?:explosion|explosions|blast|blasts)\b",
    ],
    "ground": [
        r"\bground clashes?\b",
        r"\bheavy clashes?\b",
        r"\bfighting\b",
        r"\bcombat\b",
    ],
    "intercept": [
        r"\bintercept(?:ed|s|ing)?\b",
        r"\bshot down\b",
        r"\bdowned\b",
    ],
}

# Historical-summary / aftermath patterns. These can mention attacks but
# do not represent the attack timestamp itself.
RETROSPECTIVE_PATTERNS = [
    r"\bsatellite imagery confirms\b.*\bdamage\b",
    r"\bsatellite imagery shows\b.*\bdamage\b",
    r"\bsatellite imagery confirms\b.*\bdestroy(?:ed|uction)\b",
    r"\b(?:health ministry|officials?|authorities)\s+reports?\b.*\b(?:deaths?|killed|injured)\b.*\bfrom\b.*\b(?:strikes?|airstrikes?|attacks?)\b",
    r"\bresulting from\b.*\b(?:strikes?|airstrikes?|attacks?)\b",
    r"\bcasualties from\b.*\b(?:strikes?|airstrikes?|attacks?)\b",
]

# But if these words are present, it is more likely the event itself.
LIVE_EVENT_CUES = [
    r"\bunderway\b",
    r"\bongoing\b",
    r"\bcurrently\b",
    r"\bjust\b",
    r"\btonight\b",
    r"\bovernight\b",
    r"\bthis morning\b",
    r"\bthis evening\b",
    r"\btoday\b",
    r"\bminutes ago\b",
    r"\bhours ago\b",
]


class SourceNotReady(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-url", default=DEFAULT_SOURCE_URL)
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--max-age-hours", type=float, default=8.0)
    parser.add_argument("--require-today", action="store_true")
    parser.add_argument("--output", default="docs/kinetic_events.json")
    return parser.parse_args()


def parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None

    text = str(value).strip()

    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        pass

    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(text)
        if dt is not None:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
    except Exception:
        pass

    return None


def regex_any(patterns: list[str], text: str) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def fetch_json(url: str, timeout: int = 45) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "conflict-end-matrix/kinetic-import",
            "Accept": "application/json",
            "Cache-Control": "no-cache",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                raise RuntimeError(f"HTTP status {response.status}")
            raw = response.read()
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not download source JSON: {exc}") from exc

    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Source is not valid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise RuntimeError("Source JSON top level must be an object.")

    return data


def validate_freshness(
    data: dict[str, Any],
    max_age_hours: float,
    require_today: bool,
) -> datetime:
    generated_at = parse_datetime(data.get("generated_at"))
    if generated_at is None:
        raise SourceNotReady("Source has no valid generated_at timestamp.")

    now = datetime.now(timezone.utc)
    age = now - generated_at

    if age < timedelta(minutes=-10):
        raise SourceNotReady("Source timestamp is unexpectedly in the future.")

    if age > timedelta(hours=max_age_hours):
        raise SourceNotReady(
            f"Source stale: {age.total_seconds()/3600:.2f}h old."
        )

    if require_today and generated_at.date() != now.date():
        raise SourceNotReady(
            f"Source is not today's UTC dataset: {generated_at.date()}."
        )

    return generated_at


def get_actor(event: dict[str, Any]) -> tuple[str, str, str]:
    raw_source = event.get("raw_source")

    if isinstance(raw_source, dict):
        origin = str(raw_source.get("origin", "")).strip().upper()
        if origin:
            return (
                origin.lower(),
                ORIGIN_LABELS.get(origin, origin),
                "raw_source.origin",
            )

    attacker = str(event.get("attacker", "")).strip()
    attacker_label = str(event.get("attacker_label", "")).strip()

    if attacker:
        return (
            attacker.lower(),
            attacker_label or attacker,
            "normalized.attacker",
        )

    return ("unknown", "Unknown actor", "unknown")


def is_actual_kinetic_event(
    category: str,
    description: str,
) -> tuple[bool, str]:
    """
    Returns (keep, reason).

    Conservative by design:
    better to lose a weak/ambiguous record than create a false
    Statement -> Action link later.
    """
    text = description.strip().lower()

    if not text:
        return False, "empty_description"

    # Clear commentary / capability / hypothetical record.
    if regex_any(NON_EVENT_PATTERNS, text):
        return False, "context_or_hypothetical"

    # Retrospective aftermath reporting is excluded unless the text also
    # contains a clear live-event cue.
    if regex_any(RETROSPECTIVE_PATTERNS, text) and not regex_any(
        LIVE_EVENT_CUES, text
    ):
        return False, "retrospective_or_aftermath"

    # Alerts/sirens alone are not military actions.
    if regex_any(ALERT_ONLY_PATTERNS, text):
        category_patterns = CATEGORY_ACTION_PATTERNS.get(category, [])
        has_action = regex_any(category_patterns, text)
        if not has_action:
            return False, "alert_only"

        # Special guard: "air raid sirens activated" wrongly labelled
        # as airstrike should not pass just because "air" is present.
        if category == "airstrike" and not regex_any(
            [
                r"\bairstrikes?\b",
                r"\bair strikes?\b",
                r"\bbombing\b",
                r"\baerial strikes?\b",
            ],
            text,
        ):
            return False, "alert_only"

    patterns = CATEGORY_ACTION_PATTERNS.get(category, [])

    if regex_any(patterns, text):
        return True, "category_action_match"

    if regex_any(GENERAL_ACTION_PATTERNS, text):
        return True, "general_action_match"

    return False, "no_confirmed_action_language"


def normalize_event(
    event: dict[str, Any],
) -> tuple[dict[str, Any] | None, str]:
    category = str(event.get("category", "")).strip().lower()

    if category not in KINETIC_CATEGORIES:
        return None, "category_not_kinetic"

    description = str(event.get("description", "")).strip()

    keep, validation_reason = is_actual_kinetic_event(
        category,
        description,
    )

    if not keep:
        return None, validation_reason

    timestamp = parse_datetime(event.get("date"))

    raw_source = event.get("raw_source")
    raw_source = raw_source if isinstance(raw_source, dict) else {}

    if timestamp is None:
        timestamp = parse_datetime(raw_source.get("timestamp"))

    if timestamp is None:
        return None, "invalid_timestamp"

    actor, actor_label, actor_method = get_actor(event)

    source_name = (
        str(event.get("source_name", "")).strip()
        or str(raw_source.get("source", "")).strip()
    )

    source_url = (
        str(event.get("source_url", "")).strip()
        or str(raw_source.get("sourceUrl", "")).strip()
    )

    return {
        "event_id": str(event.get("id", "")).strip(),
        "timestamp": timestamp.isoformat().replace("+00:00", "Z"),
        "event_type": "kinetic",
        "subtype": category,
        "category": category,
        "severity": str(event.get("severity", "")).strip().lower(),
        "actor": actor,
        "actor_label": actor_label,
        "actor_method": actor_method,
        "target_country": str(event.get("country", "")).strip(),
        "location": str(event.get("location", "")).strip(),
        "latitude": event.get("latitude"),
        "longitude": event.get("longitude"),
        "map_visualizable": bool(event.get("map_visualizable")),
        "description": description,
        "source_name": source_name,
        "source_url": source_url,
        "source_repository": "mikloshetzer-sketch/me-security-monitor",
        "source_collection": str(event.get("source_collection", "")).strip(),
        "validation": {
            "accepted": True,
            "reason": validation_reason,
            "mode": "strict_kinetic_v2",
        },
    }, "accepted"


def dedupe_events(
    events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    seen_ids: set[str] = set()
    seen_signature: set[str] = set()
    result: list[dict[str, Any]] = []

    for event in events:
        event_id = str(event.get("event_id", "")).strip()

        signature = "|".join(
            [
                str(event.get("timestamp", ""))[:16],
                str(event.get("category", "")).lower(),
                str(event.get("actor", "")).lower(),
                str(event.get("location", "")).lower(),
                re.sub(
                    r"\s+",
                    " ",
                    str(event.get("description", "")).lower(),
                )[:180],
            ]
        )

        if event_id and event_id in seen_ids:
            continue

        if signature in seen_signature:
            continue

        if event_id:
            seen_ids.add(event_id)

        seen_signature.add(signature)
        result.append(event)

    return result


def increment_counter(
    counter: dict[str, int],
    key: str,
) -> None:
    counter[key] = counter.get(key, 0) + 1


def main() -> int:
    args = parse_args()

    if args.days <= 0:
        raise SystemExit("--days must be greater than zero.")

    source = fetch_json(args.source_url)

    if str(source.get("status", "")).lower() not in {"", "ok"}:
        raise SourceNotReady(
            f"Source status is not OK: {source.get('status')!r}"
        )

    source_generated_at = validate_freshness(
        source,
        args.max_age_hours,
        args.require_today,
    )

    source_events = source.get("events")

    if not isinstance(source_events, list) or not source_events:
        raise SourceNotReady("Source events array is missing or empty.")

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=args.days)

    accepted: list[dict[str, Any]] = []
    rejection_counts: dict[str, int] = {}

    for source_event in source_events:
        if not isinstance(source_event, dict):
            increment_counter(rejection_counts, "invalid_record")
            continue

        event, reason = normalize_event(source_event)

        if event is None:
            increment_counter(rejection_counts, reason)
            continue

        timestamp = parse_datetime(event["timestamp"])

        if timestamp is None:
            increment_counter(rejection_counts, "invalid_timestamp")
            continue

        if timestamp < cutoff:
            increment_counter(rejection_counts, "outside_window")
            continue

        accepted.append(event)

    accepted = dedupe_events(accepted)

    accepted.sort(
        key=lambda item: parse_datetime(item["timestamp"])
        or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )

    if not accepted:
        raise SourceNotReady(
            "No validated kinetic events remained. "
            "Previous output was not overwritten."
        )

    category_counts: dict[str, int] = {}
    severity_counts: dict[str, int] = {}
    actor_counts: dict[str, int] = {}

    for event in accepted:
        increment_counter(
            category_counts,
            event["category"] or "unknown",
        )
        increment_counter(
            severity_counts,
            event["severity"] or "unknown",
        )
        increment_counter(
            actor_counts,
            event["actor_label"] or "Unknown actor",
        )

    output = {
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "source_generated_at": source_generated_at.isoformat().replace(
            "+00:00",
            "Z",
        ),
        "source_url": args.source_url,
        "source_repository": "mikloshetzer-sketch/me-security-monitor",
        "source_dataset": "data/iranstrike.json",
        "window_days": args.days,
        "cleaning_mode": "strict_kinetic_v2",
        "freshness": {
            "required_today_utc": bool(args.require_today),
            "max_age_hours": args.max_age_hours,
        },
        "source_event_count": len(source_events),
        "event_count": len(accepted),
        "rejected_count": sum(rejection_counts.values()),
        "rejection_counts": dict(
            sorted(
                rejection_counts.items(),
                key=lambda item: (-item[1], item[0]),
            )
        ),
        "category_counts": dict(
            sorted(
                category_counts.items(),
                key=lambda item: (-item[1], item[0]),
            )
        ),
        "severity_counts": dict(
            sorted(
                severity_counts.items(),
                key=lambda item: (-item[1], item[0]),
            )
        ),
        "actor_counts": dict(
            sorted(
                actor_counts.items(),
                key=lambda item: (-item[1], item[0]),
            )
        ),
        "events": accepted,
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    temp_path = output_path.with_suffix(
        output_path.suffix + ".tmp"
    )

    with temp_path.open("w", encoding="utf-8") as file:
        json.dump(
            output,
            file,
            ensure_ascii=False,
            indent=2,
        )

    temp_path.replace(output_path)

    print("Clean kinetic event layer updated.")
    print(f"Source events: {len(source_events)}")
    print(f"Accepted events: {len(accepted)}")
    print(f"Rejected: {output['rejected_count']}")
    print(f"Rejection reasons: {output['rejection_counts']}")
    print(f"Categories: {output['category_counts']}")
    print(f"Actors: {output['actor_counts']}")
    print(f"Output: {output_path}")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SourceNotReady as exc:
        print(f"SOURCE_NOT_READY: {exc}", file=sys.stderr)
        raise SystemExit(3)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
