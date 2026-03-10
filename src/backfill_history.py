import csv
import json
from pathlib import Path
from email.utils import parsedate_to_datetime


ESCALATION_KEYWORDS = {
    "strike": -2,
    "strikes": -2,
    "attack": -2,
    "attacks": -2,
    "missile": -2,
    "missiles": -2,
    "drone": -1,
    "drones": -1,
    "bombing": -2,
    "offensive": -2,
    "retaliation": -1,
    "escalation": -2,
    "war": -1,
    "clash": -1,
    "clashes": -1,
    "killed": -2,
    "dead": -2,
    "injured": -1,
    "threat": -1,
    "threatens": -1
}

DEESCALATION_KEYWORDS = {
    "ceasefire": 3,
    "truce": 3,
    "talks": 2,
    "negotiation": 2,
    "negotiations": 2,
    "diplomacy": 2,
    "diplomatic": 2,
    "mediator": 2,
    "mediation": 2,
    "peace": 2,
    "de-escalation": 3,
    "deescalation": 3,
    "agreement": 2,
    "deal": 1,
    "dialogue": 2,
    "pause": 1,
    "settlement": 2
}


def score_title(title: str) -> int:
    title_lower = title.lower()
    score = 0

    for keyword, value in ESCALATION_KEYWORDS.items():
        if keyword in title_lower:
            score += value

    for keyword, value in DEESCALATION_KEYWORDS.items():
        if keyword in title_lower:
            score += value

    return score


def classify_total_score(total_score: int) -> str:
    if total_score <= -15:
        return "strong escalation"
    if total_score <= -5:
        return "moderate escalation"
    if total_score < 5:
        return "mixed / unstable"
    if total_score < 15:
        return "moderate de-escalation"
    return "strong de-escalation"


def normalize_date(date_str: str) -> str | None:
    if not date_str:
        return None

    try:
        dt = parsedate_to_datetime(date_str)
        return dt.date().isoformat()
    except Exception:
        return None


def main():
    base_dir = Path(__file__).resolve().parent.parent
    input_file = base_dir / "data" / "raw" / "latest_news.json"
    history_file = base_dir / "data" / "conflict_history.csv"

    with open(input_file, "r", encoding="utf-8") as f:
        raw_data = json.load(f)

    articles = raw_data.get("articles", [])

    grouped = {}

    for article in articles:
        title = article.get("title", "")
        published = article.get("published", "")
        day = normalize_date(published)

        if not day:
            continue

        if day not in grouped:
            grouped[day] = {
                "total_score": 0,
                "article_count": 0
            }

        grouped[day]["total_score"] += score_title(title)
        grouped[day]["article_count"] += 1

    existing = {}

    if history_file.exists():
        with open(history_file, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                row_date = row.get("date", "").strip()
                if row_date:
                    existing[row_date] = {
                        "date": row_date,
                        "total_score": row.get("total_score", "").strip(),
                        "assessment": row.get("assessment", "").strip(),
                        "article_count": row.get("article_count", "").strip()
                    }

    for day, values in grouped.items():
        total_score = values["total_score"]
        article_count = values["article_count"]
        existing[day] = {
            "date": day,
            "total_score": str(total_score),
            "assessment": classify_total_score(total_score),
            "article_count": str(article_count)
        }

    rows = [existing[d] for d in sorted(existing.keys())]

    with open(history_file, "w", newline="", encoding="utf-8") as f:
        fieldnames = ["date", "total_score", "assessment", "article_count"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Backfill complete. Updated {len(grouped)} historical day(s).")


if __name__ == "__main__":
    main()
