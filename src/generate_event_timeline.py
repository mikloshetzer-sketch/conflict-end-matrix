import json
from pathlib import Path

# ---------------------------------------------------------------------
# Conflict End Matrix -> non-kinetic event timeline
#
# Purpose:
# - Read the already scored daily news.
# - Extract ONLY non-kinetic / informational events such as:
#   diplomacy, negotiations, ceasefire, mediation, threats, warnings,
#   retaliation statements and political/military announcements.
# - Do NOT create military / kinetic events here.
# - Write docs/event_timeline.json for analysis.html.
#
# This script does not change score_news.py or the existing conflict index.
# ---------------------------------------------------------------------

NON_KINETIC_KEYWORDS = {
    # Diplomacy / negotiations
    "peace": ("diplomatic", "peace_signal", "de-escalation"),
    "talks": ("diplomatic", "talks", "de-escalation"),
    "negotiation": ("diplomatic", "negotiation", "de-escalation"),
    "negotiations": ("diplomatic", "negotiation", "de-escalation"),
    "diplomacy": ("diplomatic", "diplomacy", "de-escalation"),
    "diplomatic": ("diplomatic", "diplomacy", "de-escalation"),
    "mediator": ("diplomatic", "mediation", "de-escalation"),
    "mediation": ("diplomatic", "mediation", "de-escalation"),
    "dialogue": ("diplomatic", "dialogue", "de-escalation"),

    # Ceasefire / settlement
    "ceasefire": ("ceasefire", "ceasefire", "de-escalation"),
    "truce": ("ceasefire", "truce", "de-escalation"),
    "agreement": ("ceasefire", "agreement", "de-escalation"),
    "deal": ("ceasefire", "deal", "de-escalation"),
    "pause": ("ceasefire", "pause", "de-escalation"),
    "settlement": ("ceasefire", "settlement", "de-escalation"),
    "de-escalation": ("ceasefire", "de-escalation", "de-escalation"),
    "deescalation": ("ceasefire", "de-escalation", "de-escalation"),

    # Threats / warnings / retaliation language
    "threat": ("threat", "threat", "escalation"),
    "threatens": ("threat", "threat", "escalation"),
    "warning": ("threat", "warning", "escalation"),
    "warns": ("threat", "warning", "escalation"),
    "ultimatum": ("threat", "ultimatum", "escalation"),
    "retaliation": ("threat", "retaliation_statement", "escalation"),

    # Political / military statements
    "announcement": ("diplomatic", "announcement", "mixed"),
    "announces": ("diplomatic", "announcement", "mixed"),
    "statement": ("diplomatic", "statement", "mixed"),
    "calls for": ("diplomatic", "call_for_action", "mixed"),
}

# Any article containing one of these matched keywords is considered
# primarily kinetic and is excluded from this non-kinetic timeline.
KINETIC_KEYWORDS = {
    "strike",
    "strikes",
    "attack",
    "attacks",
    "missile",
    "missiles",
    "drone",
    "drones",
    "bombing",
    "offensive",
    "clash",
    "clashes",
    "killed",
    "dead",
    "injured",
    "war",
}


def load_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Required input file not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def unique_in_order(values):
    seen = set()
    result = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def choose_event_class(matches):
    """
    Pick the strongest non-kinetic event classification from matched keywords.

    Priority:
    ceasefire > diplomatic > threat
    This is only for display grouping, not for rescoring.
    """
    candidates = []

    for match in matches:
        keyword = str(match.get("keyword", "")).strip().lower()
        if keyword in NON_KINETIC_KEYWORDS:
            candidates.append((keyword, NON_KINETIC_KEYWORDS[keyword]))

    if not candidates:
        return None

    priority = {
        "ceasefire": 3,
        "diplomatic": 2,
        "threat": 1,
    }

    candidates.sort(
        key=lambda item: priority.get(item[1][0], 0),
        reverse=True,
    )

    keyword, (event_type, subtype, direction) = candidates[0]

    return {
        "primary_keyword": keyword,
        "event_type": event_type,
        "subtype": subtype,
        "direction": direction,
    }


def is_kinetic_article(matches):
    matched = {
        str(match.get("keyword", "")).strip().lower()
        for match in matches
    }
    return bool(matched & KINETIC_KEYWORDS)


def build_event(article: dict, index: int) -> dict | None:
    matches = article.get("matched_keywords", []) or []

    # Strict separation:
    # articles carrying kinetic keywords do not enter this non-kinetic layer.
    if is_kinetic_article(matches):
        return None

    classification = choose_event_class(matches)
    if classification is None:
        return None

    tags = unique_in_order(
        str(match.get("keyword", "")).strip()
        for match in matches
        if str(match.get("keyword", "")).strip()
    )

    published = article.get("published", "") or article.get("timestamp", "")
    title = article.get("title", "")

    # Keep event ids deterministic within the generated file.
    event_id = f"INFO-{index:04d}"

    return {
        "event_id": event_id,
        "timestamp": published,
        "event_type": classification["event_type"],
        "subtype": classification["subtype"],
        "title": title,
        "diplomatic_event": title,
        "military_event": "",
        "direction": classification["direction"],
        "actors": [],
        "target": "",
        "location": "",
        "keywords": tags,
        "source": article.get("source", ""),
        "link": article.get("link", ""),
        "score": int(article.get("score", 0) or 0),

        # Relationship fields are intentionally empty for now.
        # They will be filled later when the kinetic event layer is added.
        "linked_event_id": "",
        "linked_statement": "",
        "linked_military_event": "",
        "relation_type": "",
        "lag_minutes": None,
        "link_confidence": "",
    }


def main():
    base_dir = Path(__file__).resolve().parent.parent

    scored_file = base_dir / "data" / "processed" / "latest_scored.json"
    output_dir = base_dir / "docs"
    output_dir.mkdir(parents=True, exist_ok=True)

    output_file = output_dir / "event_timeline.json"

    scored_data = load_json(scored_file)
    articles = scored_data.get("articles", []) or []

    events = []
    counter = 1

    for article in articles:
        event = build_event(article, counter)
        if event is not None:
            events.append(event)
            counter += 1

    # Newest first when timestamps are parseable as strings in ISO/RFC form.
    # analysis.html also sorts client-side.
    events.sort(
        key=lambda item: item.get("timestamp", ""),
        reverse=True,
    )

    payload = {
        "generated_at": scored_data.get("created_at", ""),
        "source": "Conflict End Matrix non-kinetic signal layer",
        "scope": "diplomatic, political, ceasefire, threat and statement events only",
        "military_events_included": False,
        "events": events,
    }

    with output_file.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    print("Event timeline generated.")
    print(f"Input articles: {len(articles)}")
    print(f"Non-kinetic events: {len(events)}")
    print(f"Output: {output_file}")


if __name__ == "__main__":
    main()
