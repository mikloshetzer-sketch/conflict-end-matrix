#!/usr/bin/env python3
"""
Import the latest IranStrike military-event layer from:
mikloshetzer-sketch/me-security-monitor/data/iranstrike.json

Safety rules:
- Never overwrite docs/kinetic_events.json with stale/invalid source data.
- Require a same-UTC-day source update when --require-today is used.
- Keep only the configured recent window (default: 90 days).
- Keep only military / kinetic categories.
- Prefer raw_source.origin for attacker when available because it is the
  source-system actor field and can be more reliable than derived labels.
"""

from __future__ import annotations

import argparse
import json
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

# Strict military/kinetic layer for the first integration.
# We intentionally exclude "political", "alert", "defense", "movement",
# and generic "infrastructure" here. Those can later become a separate
# military-posture layer if desired.
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
}


class SourceNotReady(RuntimeError):
    """Raised when source data exists but is not fresh enough to import."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-url", default=DEFAULT_SOURCE_URL)
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--max-age-hours", type=float, default=8.0)
    parser.add_argument(
        "--require-today",
        action="store_true",
        help="Require source generated_at to be on the current UTC date.",
    )
    parser.add_argument(
        "--output",
        default="docs/kinetic_events.json",
    )
    return parser.parse_args()


def parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None

    text = str(value).strip()

    # ISO 8601.
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        pass

    # RFC-style date fallback.
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
        raise RuntimeError(f"Source is not valid UTF-8 JSON: {exc}") from exc

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

    # Future timestamps beyond a small clock-skew allowance are suspicious.
    if age < timedelta(minutes=-10):
        raise SourceNotReady(
            f"Source generated_at is unexpectedly in the future: {generated_at.isoformat()}"
        )

    if age > timedelta(hours=max_age_hours):
        raise SourceNotReady(
            f"Source is stale: generated_at={generated_at.isoformat()}, "
            f"age={age.total_seconds()/3600:.2f}h, "
            f"limit={max_age_hours:.2f}h"
        )

    if require_today and generated_at.date() != now.date():
        raise SourceNotReady(
            f"Source is not from today UTC: "
            f"generated_at={generated_at.date()}, today={now.date()}"
        )

    return generated_at


def get_actor(event: dict[str, Any]) -> tuple[str, str, str]:
    """
    Returns actor_code, actor_label, actor_method.

    Prefer raw_source.origin. The normalized source can sometimes contain
    an inferred attacker that conflicts with the source-system origin.
    """
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

    return ("unknown", "Unknown", "unknown")


def normalize_event(event: dict[str, Any]) -> dict[str, Any] | None:
    category = str(event.get("category", "")).strip().lower()

    if category not in KINETIC_CATEGORIES:
        return None

    timestamp = parse_datetime(event.get("date"))
    if timestamp is None:
        raw_source = event.get("raw_source")
        if isinstance(raw_source, dict):
            timestamp = parse_datetime(raw_source.get("timestamp"))

    if timestamp is None:
        return None

    actor, actor_label, actor_method = get_actor(event)

    raw_source = event.get("raw_source")
    raw_source = raw_source if isinstance(raw_source, dict) else {}

    source_name = (
        str(event.get("source_name", "")).strip()
        or str(raw_source.get("source", "")).strip()
    )
    source_url = (
        str(event.get("source_url", "")).strip()
        or str(raw_source.get("sourceUrl", "")).strip()
    )

    lat = event.get("latitude")
    lon = event.get("longitude")

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
        "latitude": lat,
        "longitude": lon,
        "map_visualizable": bool(event.get("map_visualizable")),
        "description": str(event.get("description", "")).strip(),
        "source_name": source_name,
        "source_url": source_url,
        "source_repository": "mikloshetzer-sketch/me-security-monitor",
        "source_collection": str(event.get("source_collection", "")).strip(),
    }


def dedupe_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []

    for event in events:
        event_id = event.get("event_id")
        key = str(event_id).strip()

        if not key:
            key = "|".join(
                [
                    str(event.get("timestamp", "")),
                    str(event.get("category", "")),
                    str(event.get("actor", "")),
                    str(event.get("location", "")),
                    str(event.get("description", "")),
                ]
            )

        if key in seen:
            continue

        seen.add(key)
        result.append(event)

    return result


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
        max_age_hours=args.max_age_hours,
        require_today=args.require_today,
    )

    source_events = source.get("events")
    if not isinstance(source_events, list) or not source_events:
        raise SourceNotReady("Source events array is missing or empty.")

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=args.days)

    normalized: list[dict[str, Any]] = []

    for source_event in source_events:
        if not isinstance(source_event, dict):
            continue

        event = normalize_event(source_event)
        if event is None:
            continue

        timestamp = parse_datetime(event["timestamp"])
        if timestamp is None or timestamp < cutoff:
            continue

        normalized.append(event)

    normalized = dedupe_events(normalized)
    normalized.sort(
        key=lambda item: parse_datetime(item["timestamp"])
        or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )

    if not normalized:
        raise SourceNotReady(
            "No kinetic events remained after validation/filtering. "
            "Previous output will not be overwritten."
        )

    category_counts: dict[str, int] = {}
    severity_counts: dict[str, int] = {}
    actor_counts: dict[str, int] = {}

    for event in normalized:
        category = event["category"] or "unknown"
        severity = event["severity"] or "unknown"
        actor = event["actor_label"] or "Unknown"

        category_counts[category] = category_counts.get(category, 0) + 1
        severity_counts[severity] = severity_counts.get(severity, 0) + 1
        actor_counts[actor] = actor_counts.get(actor, 0) + 1

    output = {
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "source_generated_at": source_generated_at.isoformat().replace(
            "+00:00", "Z"
        ),
        "source_url": args.source_url,
        "source_repository": "mikloshetzer-sketch/me-security-monitor",
        "source_dataset": "data/iranstrike.json",
        "window_days": args.days,
        "freshness": {
            "required_today_utc": bool(args.require_today),
            "max_age_hours": args.max_age_hours,
        },
        "event_count": len(normalized),
        "category_counts": dict(
            sorted(category_counts.items(), key=lambda x: (-x[1], x[0]))
        ),
        "severity_counts": dict(
            sorted(severity_counts.items(), key=lambda x: (-x[1], x[0]))
        ),
        "actor_counts": dict(
            sorted(actor_counts.items(), key=lambda x: (-x[1], x[0]))
        ),
        "events": normalized,
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Atomic write: previous known-good file survives a crash or validation
    # failure before this point.
    temp_path = output_path.with_suffix(output_path.suffix + ".tmp")

    with temp_path.open("w", encoding="utf-8") as file:
        json.dump(output, file, ensure_ascii=False, indent=2)

    temp_path.replace(output_path)

    print("Kinetic event layer updated successfully.")
    print(f"Source generated_at: {output['source_generated_at']}")
    print(f"Window: last {args.days} days")
    print(f"Events imported: {len(normalized)}")
    print(f"Categories: {output['category_counts']}")
    print(f"Actors: {output['actor_counts']}")
    print(f"Output: {output_path}")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SourceNotReady as exc:
        # Dedicated retryable exit code for GitHub Actions.
        print(f"SOURCE_NOT_READY: {exc}", file=sys.stderr)
        raise SystemExit(3)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
