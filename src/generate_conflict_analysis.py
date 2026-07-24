#!/usr/bin/env python3
"""
Conflict End Matrix - analytical metrics layer

Inputs:
  docs/event_timeline.json
  docs/kinetic_events.json

Output:
  docs/conflict_analysis.json

Purpose:
- Build daily Military Activity Index (MAI)
- Build daily Diplomatic Direction Index (DDI)
- Build Diplomacy-Military Gap (DMG)
- Build lag-window summaries for 6h / 12h / 24h / 48h / 72h
- Do NOT claim causation. Lag outputs are temporal associations only.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean, median
from typing import Any


EVENT_TIMELINE = Path("docs/event_timeline.json")
KINETIC_EVENTS = Path("docs/kinetic_events.json")
OUTPUT = Path("docs/conflict_analysis.json")

# ---------------------------------------------------------------------
# Military weighting
# ---------------------------------------------------------------------

SEVERITY_WEIGHT = {
    "low": 1.0,
    "medium": 2.0,
    "high": 3.5,
    "critical": 5.0,
    "": 1.5,
    "unknown": 1.5,
}

CATEGORY_WEIGHT = {
    "intercept": 0.8,
    "ground": 1.0,
    "explosion": 1.1,
    "drone": 1.2,
    "missile": 1.5,
    "strike": 1.5,
    "airstrike": 1.7,
}

LAG_WINDOWS_HOURS = [6, 12, 24, 48, 72]


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Missing required input: {path}")

    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object.")

    return data


def parse_dt(value: Any) -> datetime | None:
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


def day_key(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).date().isoformat()


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def pct_change(current: float, baseline: float) -> float | None:
    if baseline == 0:
        return None
    return ((current - baseline) / baseline) * 100.0


def moving_average(values: list[float], index: int, window: int = 7) -> float:
    start = max(0, index - window)
    previous = values[start:index]

    if not previous:
        return values[index]

    return mean(previous)


def percentile_rank(values: list[float], value: float) -> float:
    if not values:
        return 0.0

    less_equal = sum(1 for item in values if item <= value)
    return (less_equal / len(values)) * 100.0


def military_event_weight(event: dict[str, Any]) -> float:
    severity = str(event.get("severity", "")).lower().strip()
    category = str(
        event.get("category")
        or event.get("subtype")
        or ""
    ).lower().strip()

    sw = SEVERITY_WEIGHT.get(severity, SEVERITY_WEIGHT["unknown"])
    cw = CATEGORY_WEIGHT.get(category, 1.0)

    return sw * cw


def get_analysis_window(
    diplomatic_events: list[dict[str, Any]],
    military_events: list[dict[str, Any]],
) -> tuple[datetime, datetime] | None:
    """
    The joint analysis period starts at the first valid military event.

    Diplomatic history may begin earlier, but MAI / DDI / Gap / lag analysis
    must only use the period in which both analytical layers can coexist.
    """
    military_dates = [
        dt
        for event in military_events
        if (dt := parse_dt(event.get("timestamp") or event.get("date"))) is not None
    ]

    diplomatic_dates = [
        dt
        for event in diplomatic_events
        if (dt := parse_dt(event.get("timestamp") or event.get("date"))) is not None
    ]

    if not military_dates:
        return None

    start = min(military_dates)

    all_end_dates = military_dates + diplomatic_dates
    end = max(all_end_dates) if all_end_dates else max(military_dates)

    return start, end


def filter_events_to_analysis_window(
    events: list[dict[str, Any]],
    start: datetime,
    end: datetime,
) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []

    for event in events:
        dt = parse_dt(event.get("timestamp") or event.get("date"))
        if dt is not None and start <= dt <= end:
            filtered.append(event)

    return filtered


def first_full_utc_day_after(start: datetime) -> datetime:
    """
    Return the first complete UTC calendar day available after the raw
    common-data start timestamp.

    Example:
      raw start = 2026-05-04 17:29 UTC
      daily start = 2026-05-05 00:00 UTC

    The partial first day remains available to lag analysis, but is excluded
    from MAI / DDI / Gap daily-baseline calculations.
    """
    start_utc = start.astimezone(timezone.utc)

    # If data happen to start exactly at 00:00:00 UTC, that day is complete
    # and may be used directly.
    if (
        start_utc.hour == 0
        and start_utc.minute == 0
        and start_utc.second == 0
        and start_utc.microsecond == 0
    ):
        return start_utc

    next_day = start_utc.date() + timedelta(days=1)

    return datetime(
        next_day.year,
        next_day.month,
        next_day.day,
        tzinfo=timezone.utc,
    )


def build_day_range(
    start: datetime,
    end: datetime,
) -> list[str]:
    start_day = start.astimezone(timezone.utc).date()
    end_day = end.astimezone(timezone.utc).date()

    days: list[str] = []
    cursor = start_day

    while cursor <= end_day:
        days.append(cursor.isoformat())
        cursor += timedelta(days=1)

    return days


def build_daily_metrics(
    diplomatic_events: list[dict[str, Any]],
    military_events: list[dict[str, Any]],
    analysis_start: datetime,
    analysis_end: datetime,
) -> list[dict[str, Any]]:
    dip_by_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
    mil_by_day: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for event in diplomatic_events:
        dt = parse_dt(event.get("timestamp") or event.get("date"))
        if dt:
            dip_by_day[day_key(dt)].append(event)

    for event in military_events:
        dt = parse_dt(event.get("timestamp") or event.get("date"))
        if dt:
            mil_by_day[day_key(dt)].append(event)

    all_days = build_day_range(analysis_start, analysis_end)

    raw_military_scores: list[float] = []

    for day in all_days:
        score = sum(military_event_weight(e) for e in mil_by_day.get(day, []))
        raw_military_scores.append(score)

    rows: list[dict[str, Any]] = []

    for idx, day in enumerate(all_days):
        dip_events = dip_by_day.get(day, [])
        mil_events = mil_by_day.get(day, [])

        # -----------------------------
        # Military Activity Index
        # -----------------------------
        raw_military = raw_military_scores[idx]
        military_percentile = percentile_rank(
            raw_military_scores,
            raw_military,
        )

        # 0-100 index, relative to observed historical distribution.
        mai = round(military_percentile, 1)

        previous_7d_avg = moving_average(raw_military_scores, idx, window=7)
        mil_vs_7d = pct_change(raw_military, previous_7d_avg)

        # -----------------------------
        # Diplomatic Direction Index
        # -----------------------------
        direction_scores = [
            float(e.get("direction_score", 0) or 0)
            for e in dip_events
        ]

        positive_total = sum(
            float(e.get("positive_signal_score", 0) or 0)
            for e in dip_events
        )
        negative_total = sum(
            float(e.get("negative_signal_score", 0) or 0)
            for e in dip_events
        )

        if direction_scores:
            # Average score mapped conservatively onto -100..+100.
            avg_direction = mean(direction_scores)
            ddi = round(clamp(avg_direction / 6.0 * 100.0, -100, 100), 1)
        else:
            avg_direction = 0.0
            ddi = 0.0

        escalation_count = sum(
            1 for e in dip_events
            if str(e.get("direction", "")).lower() == "escalation"
        )
        deescalation_count = sum(
            1 for e in dip_events
            if str(e.get("direction", "")).lower() == "de-escalation"
        )
        mixed_count = sum(
            1 for e in dip_events
            if str(e.get("direction", "")).lower() == "mixed"
        )

        # -----------------------------
        # Diplomacy-Military Gap
        #
        # Military pressure:
        #   +100 = very high / above-baseline activity
        #   -100 = very low / below-baseline activity
        #
        # DDI:
        #   +100 = de-escalatory
        #   -100 = escalatory
        #
        # High positive gap means:
        #   diplomacy is de-escalatory while military pressure remains high.
        #
        # High negative gap means:
        #   rhetoric is escalatory while kinetic activity is comparatively low.
        # -----------------------------
        if mil_vs_7d is None:
            military_pressure = 0.0
        else:
            military_pressure = clamp(mil_vs_7d, -100, 100)

        divergence_score = round(ddi + military_pressure, 1)
        gap_strength = abs(divergence_score)

        if gap_strength < 25:
            gap_level = "LOW"
        elif gap_strength < 50:
            gap_level = "MODERATE"
        elif gap_strength < 75:
            gap_level = "HIGH"
        else:
            gap_level = "VERY HIGH"

        if ddi >= 20 and military_pressure >= 20:
            gap_pattern = "DE-ESCALATORY SIGNALS / HIGH MILITARY ACTIVITY"
        elif ddi <= -20 and military_pressure <= -20:
            gap_pattern = "ESCALATORY SIGNALS / LOW MILITARY ACTIVITY"
        elif ddi >= 20 and military_pressure <= -20:
            gap_pattern = "CONVERGENCE - EASING"
        elif ddi <= -20 and military_pressure >= 20:
            gap_pattern = "CONVERGENCE - ESCALATION"
        else:
            gap_pattern = "MIXED / LIMITED DIVERGENCE"

        rows.append({
            "date": day,

            "diplomatic": {
                "event_count": len(dip_events),
                "direction_index": ddi,
                "mean_direction_score": round(avg_direction, 2),
                "positive_signal_score": round(positive_total, 2),
                "negative_signal_score": round(negative_total, 2),
                "escalation_count": escalation_count,
                "deescalation_count": deescalation_count,
                "mixed_count": mixed_count,
            },

            "military": {
                "event_count": len(mil_events),
                "weighted_score": round(raw_military, 2),
                "activity_index": mai,
                "previous_7d_average_weighted_score": round(
                    previous_7d_avg,
                    2,
                ),
                "change_vs_previous_7d_pct": (
                    round(mil_vs_7d, 1)
                    if mil_vs_7d is not None
                    else None
                ),
                "pressure_score": round(military_pressure, 1),
            },

            "gap": {
                "divergence_score": divergence_score,
                "strength": round(gap_strength, 1),
                "level": gap_level,
                "pattern": gap_pattern,
            },
        })

    return rows


def weighted_activity_between(
    military_events: list[dict[str, Any]],
    start: datetime,
    end: datetime,
) -> tuple[int, float]:
    selected: list[dict[str, Any]] = []

    for event in military_events:
        dt = parse_dt(event.get("timestamp") or event.get("date"))
        if dt is not None and start < dt <= end:
            selected.append(event)

    weighted = sum(military_event_weight(e) for e in selected)
    return len(selected), weighted


def build_lag_analysis(
    diplomatic_events: list[dict[str, Any]],
    military_events: list[dict[str, Any]],
    analysis_start: datetime,
    analysis_end: datetime,
) -> dict[str, Any]:
    """
    Event-study style temporal analysis.

    For every non-mixed diplomatic signal:
      compare military activity BEFORE and AFTER the event
      for 6h / 12h / 24h / 48h / 72h windows.

    This is association only. No causal inference is made.
    """
    signal_rows: list[dict[str, Any]] = []

    for event in diplomatic_events:
        direction = str(event.get("direction", "")).lower()

        if direction not in {"escalation", "de-escalation"}:
            continue

        event_dt = parse_dt(event.get("timestamp") or event.get("date"))
        if event_dt is None:
            continue

        # Only analyse diplomatic signals inside the common data period.
        if not (analysis_start <= event_dt <= analysis_end):
            continue

        windows: dict[str, Any] = {}

        for hours in LAG_WINDOWS_HOURS:
            before_start = event_dt - timedelta(hours=hours)
            after_end = event_dt + timedelta(hours=hours)

            # Require a complete symmetric window. Otherwise the first/last
            # observations would be structurally biased by missing coverage.
            if before_start < analysis_start or after_end > analysis_end:
                windows[f"{hours}h"] = {
                    "available": False,
                    "before_event_count": None,
                    "after_event_count": None,
                    "delta_event_count": None,
                    "before_weighted_activity": None,
                    "after_weighted_activity": None,
                    "delta_weighted_activity": None,
                    "weighted_activity_change_pct": None,
                }
                continue

            before_count, before_weight = weighted_activity_between(
                military_events,
                before_start,
                event_dt,
            )
            after_count, after_weight = weighted_activity_between(
                military_events,
                event_dt,
                after_end,
            )

            delta_count = after_count - before_count
            delta_weight = after_weight - before_weight

            windows[f"{hours}h"] = {
                "available": True,
                "before_event_count": before_count,
                "after_event_count": after_count,
                "delta_event_count": delta_count,
                "before_weighted_activity": round(before_weight, 2),
                "after_weighted_activity": round(after_weight, 2),
                "delta_weighted_activity": round(delta_weight, 2),
                "weighted_activity_change_pct": (
                    round(
                        ((after_weight - before_weight) / before_weight) * 100,
                        1,
                    )
                    if before_weight > 0
                    else None
                ),
            }

        signal_rows.append({
            "event_id": event.get("event_id"),
            "timestamp": event_dt.isoformat().replace("+00:00", "Z"),
            "title": event.get("title") or event.get("diplomatic_event"),
            "direction": direction,
            "direction_score": event.get("direction_score"),
            "positive_signal_score": event.get("positive_signal_score"),
            "negative_signal_score": event.get("negative_signal_score"),
            "event_type": event.get("event_type"),
            "subtype": event.get("subtype"),
            "source": event.get("source"),
            "link": event.get("link"),
            "windows": windows,
        })

    aggregate: dict[str, Any] = {}

    for direction in ("escalation", "de-escalation"):
        group = [r for r in signal_rows if r["direction"] == direction]
        aggregate[direction] = {}

        for hours in LAG_WINDOWS_HOURS:
            key = f"{hours}h"
            available_group = [
                r for r in group
                if r["windows"].get(key, {}).get("available") is True
            ]

            deltas = [
                float(r["windows"][key]["delta_weighted_activity"])
                for r in available_group
            ]

            pct_values = [
                float(r["windows"][key]["weighted_activity_change_pct"])
                for r in available_group
                if r["windows"][key]["weighted_activity_change_pct"] is not None
            ]

            aggregate[direction][key] = {
                "signal_count": len(available_group),
                "excluded_edge_signals": len(group) - len(available_group),
                "median_delta_weighted_activity": (
                    round(median(deltas), 2)
                    if deltas else None
                ),
                "mean_delta_weighted_activity": (
                    round(mean(deltas), 2)
                    if deltas else None
                ),
                "median_change_pct": (
                    round(median(pct_values), 1)
                    if pct_values else None
                ),
                "share_followed_by_activity_increase_pct": (
                    round(
                        sum(1 for x in deltas if x > 0) / len(deltas) * 100,
                        1,
                    )
                    if deltas else None
                ),
                "share_followed_by_activity_decrease_pct": (
                    round(
                        sum(1 for x in deltas if x < 0) / len(deltas) * 100,
                        1,
                    )
                    if deltas else None
                ),
            }

    return {
        "method": (
            "For each classified escalation/de-escalation signal inside the "
            "common diplomatic-military analysis period, weighted military activity "
            "in an equal pre-event and post-event window is compared. Only complete "
            "symmetric windows are included. Temporal association only; no causation inferred."
        ),
        "windows_hours": LAG_WINDOWS_HOURS,
        "aggregate": aggregate,
        "signals": signal_rows,
    }


def build_latest_summary(
    daily: list[dict[str, Any]],
    lag: dict[str, Any],
) -> dict[str, Any]:
    if not daily:
        return {}

    latest = daily[-1]

    return {
        "date": latest["date"],
        "military_activity_index": latest["military"]["activity_index"],
        "military_change_vs_7d_pct": latest["military"][
            "change_vs_previous_7d_pct"
        ],
        "diplomatic_direction_index": latest["diplomatic"][
            "direction_index"
        ],
        "diplomacy_military_gap": latest["gap"],
        "interpretation": {
            "military": (
                "Military Activity Index is percentile-based against the "
                "full observed historical daily distribution."
            ),
            "diplomacy": (
                "Diplomatic Direction Index ranges from -100 "
                "(escalatory) to +100 (de-escalatory)."
            ),
            "gap": (
                "The Diplomacy-Military Gap compares diplomatic direction "
                "with military pressure relative to the previous 7-day average."
            ),
            "lag": (
                "Lag analysis compares equal military-activity windows before "
                "and after classified diplomatic signals. It does not prove causation."
            ),
        },
    }


def main() -> int:
    timeline_data = load_json(EVENT_TIMELINE)
    kinetic_data = load_json(KINETIC_EVENTS)

    diplomatic_events_all = timeline_data.get("events", [])
    military_events_all = kinetic_data.get("events", [])

    if not isinstance(diplomatic_events_all, list):
        raise ValueError("event_timeline.json events must be a list.")

    if not isinstance(military_events_all, list):
        raise ValueError("kinetic_events.json events must be a list.")

    analysis_window = get_analysis_window(
        diplomatic_events_all,
        military_events_all,
    )

    if analysis_window is None:
        raise ValueError("No valid military event timestamps found.")

    analysis_start, analysis_end = analysis_window
    daily_analysis_start = first_full_utc_day_after(analysis_start)

    if daily_analysis_start > analysis_end:
        raise ValueError(
            "No complete UTC day is available inside the common analysis period."
        )

    # Full common-period event sets:
    # used by lag analysis so the partial first day remains usable.
    diplomatic_events = filter_events_to_analysis_window(
        diplomatic_events_all,
        analysis_start,
        analysis_end,
    )

    military_events = filter_events_to_analysis_window(
        military_events_all,
        analysis_start,
        analysis_end,
    )

    # Daily MAI / DDI / Gap starts only on the first COMPLETE UTC day.
    daily_diplomatic_events = filter_events_to_analysis_window(
        diplomatic_events_all,
        daily_analysis_start,
        analysis_end,
    )

    daily_military_events = filter_events_to_analysis_window(
        military_events_all,
        daily_analysis_start,
        analysis_end,
    )

    daily = build_daily_metrics(
        daily_diplomatic_events,
        daily_military_events,
        daily_analysis_start,
        analysis_end,
    )

    # Lag analysis deliberately retains the raw common-data start.
    lag = build_lag_analysis(
        diplomatic_events,
        military_events,
        analysis_start,
        analysis_end,
    )

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "analysis_model": "conflict_analysis_v1_2",
        "analysis_period": {
            "raw_common_start": analysis_start.isoformat().replace("+00:00", "Z"),
            "daily_analysis_start": daily_analysis_start.isoformat().replace("+00:00", "Z"),
            "end": analysis_end.isoformat().replace("+00:00", "Z"),
            "raw_common_start_date": analysis_start.date().isoformat(),
            "daily_analysis_start_date": daily_analysis_start.date().isoformat(),
            "end_date": analysis_end.date().isoformat(),
            "basis": (
                "Lag analysis starts at the first valid kinetic event. "
                "Daily MAI/DDI/Gap starts at the first complete UTC day."
            ),
        },
        "inputs": {
            "event_timeline_generated_at": timeline_data.get("generated_at"),
            "event_timeline_direction_model": timeline_data.get(
                "direction_model"
            ),
            "kinetic_generated_at": kinetic_data.get("generated_at"),
            "kinetic_cleaning_mode": kinetic_data.get("cleaning_mode"),
            "diplomatic_events_total_history": len(diplomatic_events_all),
            "diplomatic_events_in_common_period": len(diplomatic_events),
            "diplomatic_events_in_daily_period": len(daily_diplomatic_events),
            "military_events_total_history": len(military_events_all),
            "military_events_in_common_period": len(military_events),
            "military_events_in_daily_period": len(daily_military_events),
        },
        "methodology": {
            "military_activity_index": {
                "range": "0-100",
                "method": (
                    "Each military event receives category_weight × "
                    "severity_weight. Daily weighted activity is converted "
                    "to a percentile rank across the observed history."
                ),
                "severity_weights": SEVERITY_WEIGHT,
                "category_weights": CATEGORY_WEIGHT,
            },
            "diplomatic_direction_index": {
                "range": "-100 to +100",
                "method": (
                    "Mean event direction_score for the UTC day is mapped "
                    "onto -100..+100 using ±6 as the strong-signal reference."
                ),
                "meaning": {
                    "-100": "strong escalation signal",
                    "0": "mixed / neutral / no directional signal",
                    "+100": "strong de-escalation signal",
                },
            },
            "diplomacy_military_gap": {
                "method": (
                    "Diplomatic Direction Index is compared with military "
                    "pressure relative to the previous 7-day weighted-activity average."
                ),
                "caution": (
                    "The gap is descriptive. It measures divergence or convergence "
                    "between signalling and observed kinetic activity."
                ),
            },
        },
        "latest": build_latest_summary(daily, lag),
        "daily": daily,
        "lag_analysis": lag,
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    temp = OUTPUT.with_suffix(".json.tmp")
    with temp.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    temp.replace(OUTPUT)

    print("Conflict analysis V1.2 generated.")
    print(
        "Raw common period:",
        analysis_start.isoformat(),
        "->",
        analysis_end.isoformat(),
    )
    print(
        "Daily MAI/DDI/Gap period:",
        daily_analysis_start.isoformat(),
        "->",
        analysis_end.isoformat(),
    )
    print(
        f"Diplomatic events in common period: "
        f"{len(diplomatic_events)} / {len(diplomatic_events_all)}"
    )
    print(
        f"Diplomatic events in daily period: "
        f"{len(daily_diplomatic_events)}"
    )
    print(
        f"Military events in common period: "
        f"{len(military_events)} / {len(military_events_all)}"
    )
    print(
        f"Military events in daily period: "
        f"{len(daily_military_events)}"
    )
    print(f"Daily rows: {len(daily)}")
    print(
        "Lag signals:",
        len(lag.get("signals", [])),
    )
    print(f"Output: {OUTPUT}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
