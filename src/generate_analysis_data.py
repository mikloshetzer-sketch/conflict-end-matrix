import json
from collections import defaultdict
from pathlib import Path


# ---------------------------------------------------------------------
# Conflict index classification
# Kept identical to the logic used by generate_dashboard_data.py
# ---------------------------------------------------------------------
def classify_index(index: float) -> str:
    if index <= -2:
        return "strong escalation"
    if index <= -1:
        return "moderate escalation"
    if index < 0:
        return "mild escalation"
    if index < 1:
        return "neutral"
    return "de-escalation"


# ---------------------------------------------------------------------
# Analytical categories
#
# IMPORTANT:
# This file does NOT change the scoring model.
# It only groups the matched keywords already produced by score_news.py.
# ---------------------------------------------------------------------
KEYWORD_CATEGORIES = {
    # Military escalation
    "strike": "Military escalation",
    "strikes": "Military escalation",
    "attack": "Military escalation",
    "attacks": "Military escalation",
    "missile": "Military escalation",
    "missiles": "Military escalation",
    "drone": "Military escalation",
    "drones": "Military escalation",
    "bombing": "Military escalation",
    "offensive": "Military escalation",
    "war": "Military escalation",
    "clash": "Military escalation",
    "clashes": "Military escalation",

    # Retaliation / threats
    "retaliation": "Threats / retaliation",
    "escalation": "Threats / retaliation",
    "threat": "Threats / retaliation",
    "threatens": "Threats / retaliation",

    # Casualties
    "killed": "Casualties",
    "dead": "Casualties",
    "injured": "Casualties",

    # Diplomacy / negotiation
    "talks": "Diplomacy / negotiation",
    "negotiation": "Diplomacy / negotiation",
    "negotiations": "Diplomacy / negotiation",
    "diplomacy": "Diplomacy / negotiation",
    "diplomatic": "Diplomacy / negotiation",
    "mediator": "Diplomacy / negotiation",
    "mediation": "Diplomacy / negotiation",
    "peace": "Diplomacy / negotiation",
    "dialogue": "Diplomacy / negotiation",

    # Ceasefire / settlement
    "ceasefire": "Ceasefire / settlement",
    "truce": "Ceasefire / settlement",
    "de-escalation": "Ceasefire / settlement",
    "deescalation": "Ceasefire / settlement",
    "agreement": "Ceasefire / settlement",
    "deal": "Ceasefire / settlement",
    "pause": "Ceasefire / settlement",
    "settlement": "Ceasefire / settlement",
}


def load_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Required input file not found: {path}")

    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def calculate_driver_data(articles: list[dict]) -> list[dict]:
    """
    Aggregate the matched keywords already written into latest_scored.json.

    For every keyword:
      count  = number of matched appearances recorded by score_news.py
      weight = original keyword score
      impact = count * weight

    No rescoring is performed here.
    """
    stats: dict[str, dict] = {}

    for article in articles:
        for match in article.get("matched_keywords", []) or []:
            keyword = str(match.get("keyword", "")).strip()
            if not keyword:
                continue

            try:
                weight = int(match.get("value", 0))
            except (TypeError, ValueError):
                weight = 0

            if keyword not in stats:
                stats[keyword] = {
                    "driver": keyword,
                    "category": KEYWORD_CATEGORIES.get(keyword, "Other"),
                    "count": 0,
                    "weight": weight,
                    "impact": 0,
                }

            stats[keyword]["count"] += 1
            stats[keyword]["impact"] += weight

    drivers = list(stats.values())

    # Largest absolute contribution first.
    drivers.sort(
        key=lambda item: (
            abs(item["impact"]),
            item["count"],
            item["driver"],
        ),
        reverse=True,
    )

    return drivers


def calculate_categories(drivers: list[dict]) -> list[dict]:
    grouped: dict[str, dict] = defaultdict(
        lambda: {
            "category": "",
            "score": 0,
            "count": 0,
            "keywords": [],
        }
    )

    for driver in drivers:
        category = driver.get("category", "Other")
        grouped[category]["category"] = category
        grouped[category]["score"] += int(driver.get("impact", 0))
        grouped[category]["count"] += int(driver.get("count", 0))
        grouped[category]["keywords"].append(driver.get("driver", ""))

    categories = []

    for item in grouped.values():
        item["keywords"] = sorted(
            {keyword for keyword in item["keywords"] if keyword}
        )
        categories.append(item)

    categories.sort(
        key=lambda item: abs(item["score"]),
        reverse=True,
    )

    return categories


def build_key_signals(articles: list[dict], limit: int = 12) -> list[dict]:
    """
    Select the most influential scored headlines.

    Only headlines with a non-zero score are used.
    Ranking is based on absolute article score.
    """
    scored = [
        article
        for article in articles
        if int(article.get("score", 0) or 0) != 0
    ]

    scored.sort(
        key=lambda article: (
            abs(int(article.get("score", 0) or 0)),
            int(article.get("score", 0) or 0) < 0,
        ),
        reverse=True,
    )

    result = []

    for article in scored[:limit]:
        matches = article.get("matched_keywords", []) or []

        tags = []
        for match in matches:
            keyword = str(match.get("keyword", "")).strip()
            if keyword and keyword not in tags:
                tags.append(keyword)

        result.append(
            {
                "title": article.get("title", ""),
                "link": article.get("link", ""),
                "source": article.get("source", ""),
                "published": article.get("published", ""),
                "score": int(article.get("score", 0) or 0),
                "tags": tags,
            }
        )

    return result


def main() -> None:
    base_dir = Path(__file__).resolve().parent.parent

    scored_file = base_dir / "data" / "processed" / "latest_scored.json"
    summary_file = base_dir / "docs" / "latest_summary.json"

    output_dir = base_dir / "docs"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / "analysis.json"

    scored_data = load_json(scored_file)

    articles = scored_data.get("articles", []) or []
    article_count = int(scored_data.get("article_count", len(articles)) or 0)
    total_score = int(scored_data.get("total_score", 0) or 0)

    # Use the existing dashboard summary where available so the analysis
    # page displays exactly the same index/assessment as the Overview page.
    summary_data = {}
    if summary_file.exists():
        summary_data = load_json(summary_file)

    if article_count > 0:
        calculated_index = round(total_score / article_count, 2)
    else:
        calculated_index = 0.0

    conflict_index = float(
        summary_data.get("conflict_index", calculated_index)
    )
    assessment = str(
        summary_data.get("assessment", classify_index(conflict_index))
    )

    drivers = calculate_driver_data(articles)

    escalation_pressure = sum(
        int(driver["impact"])
        for driver in drivers
        if int(driver["impact"]) < 0
    )

    diplomatic_pressure = sum(
        int(driver["impact"])
        for driver in drivers
        if int(driver["impact"]) > 0
    )

    net_signal = escalation_pressure + diplomatic_pressure

    categories = calculate_categories(drivers)
    key_signals = build_key_signals(articles)

    analysis = {
        "report_date": scored_data.get("created_at", "")[:10],
        "created_at": scored_data.get("created_at", ""),
        "article_count": article_count,
        "total_score": total_score,
        "conflict_index": conflict_index,
        "assessment": assessment,

        # Current-day analytical pressure
        "escalation_pressure": escalation_pressure,
        "diplomatic_pressure": diplomatic_pressure,
        "net_signal": net_signal,

        # Driver detail
        "top_drivers": drivers,
        "categories": categories,
        "key_signals": key_signals,

        # Simple integrity check:
        # with the current scoring model this should normally be true.
        "integrity": {
            "driver_net_equals_total_score": net_signal == total_score,
            "driver_net": net_signal,
            "source_total_score": total_score,
        },
    }

    with open(output_file, "w", encoding="utf-8") as file:
        json.dump(
            analysis,
            file,
            indent=2,
            ensure_ascii=False,
        )

    print("Conflict Driver Analysis data generated.")
    print(f"Articles analysed: {article_count}")
    print(f"Conflict index: {conflict_index}")
    print(f"Assessment: {assessment}")
    print(f"Escalation pressure: {escalation_pressure}")
    print(f"Diplomatic pressure: {diplomatic_pressure}")
    print(f"Net signal: {net_signal}")
    print(f"Total score: {total_score}")
    print(f"Integrity check: {net_signal == total_score}")
    print(f"Output: {output_file}")


if __name__ == "__main__":
    main()
