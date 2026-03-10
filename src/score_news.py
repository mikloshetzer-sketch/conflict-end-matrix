import json
from pathlib import Path
from datetime import datetime

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


def score_title(title: str) -> dict:
    title_lower = title.lower()
    score = 0
    matched_keywords = []

    for keyword, value in ESCALATION_KEYWORDS.items():
        if keyword in title_lower:
            score += value
            matched_keywords.append({"keyword": keyword, "value": value})

    for keyword, value in DEESCALATION_KEYWORDS.items():
        if keyword in title_lower:
            score += value
            matched_keywords.append({"keyword": keyword, "value": value})

    return {
        "title": title,
        "score": score,
        "matched_keywords": matched_keywords
    }


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


def main():
    base_dir = Path(__file__).resolve().parent.parent
    input_file = base_dir / "data" / "raw" / "latest_news.json"
    output_dir = base_dir / "data" / "processed"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / "latest_scored.json"

    with open(input_file, "r", encoding="utf-8") as f:
        raw_data = json.load(f)

    articles = raw_data.get("articles", [])
    scored_articles = []
    total_score = 0

    for article in articles:
        title = article.get("title", "")
        result = score_title(title)
        total_score += result["score"]

        scored_articles.append({
            "title": title,
            "link": article.get("link", ""),
            "published": article.get("published", ""),
            "source": article.get("source", ""),
            "score": result["score"],
            "matched_keywords": result["matched_keywords"]
        })

    output = {
        "created_at": datetime.utcnow().isoformat(),
        "article_count": len(scored_articles),
        "total_score": total_score,
        "assessment": classify_total_score(total_score),
        "articles": scored_articles
    }

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"Scored {len(scored_articles)} articles")
    print(f"Total score: {total_score}")
    print(f"Assessment: {output['assessment']}")


if __name__ == "__main__":
    main()
