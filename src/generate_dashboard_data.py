import json
import csv
from pathlib import Path


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


def calculate_trajectory(history_rows):
    if len(history_rows) < 3:
        return "insufficient data"

    last_three = history_rows[-3:]
    values = []

    for row in last_three:
        try:
            values.append(float(row["conflict_index"]))
        except Exception:
            return "insufficient data"

    if values[2] < values[1] < values[0]:
        return "escalating"
    if values[2] > values[1] > values[0]:
        return "stabilizing"
    return "uncertain"


def build_outlook(conflict_index: float, trajectory: str) -> str:
    if trajectory == "escalating":
        if conflict_index <= -1:
            return "High short-term escalation pressure."
        return "Rising tension, but not yet at peak intensity."

    if trajectory == "stabilizing":
        if conflict_index < 0:
            return "Tension remains present, but escalation pressure may be easing."
        return "The information environment is moving toward stabilization."

    if trajectory == "uncertain":
        return "Short-term direction remains uncertain."

    return "Not enough trend data for a short-term outlook."


def generate_commentary(index: float, article_count: int, total_score: int, trajectory: str, outlook: str):
    assessment = classify_index(index)

    intro = (
        "This automated assessment analyses international news headlines "
        "related to the monitored conflict environment."
    )

    if assessment == "strong escalation":
        situation = (
            "The current information environment indicates strong escalation dynamics. "
            "A high concentration of headlines refers to military activity such as strikes, "
            "missile launches, retaliatory actions or combat developments."
        )
    elif assessment == "moderate escalation":
        situation = (
            "The news environment suggests moderate escalation pressure. "
            "Military developments appear regularly in reporting, though the pattern does not yet "
            "indicate the highest observable intensity."
        )
    elif assessment == "mild escalation":
        situation = (
            "The conflict environment shows mild escalation signals. "
            "Some military-related reporting appears, but it does not dominate the information flow."
        )
    elif assessment == "neutral":
        situation = (
            "The news flow currently appears relatively balanced. "
            "Escalatory signals and diplomatic reporting appear in similar proportions."
        )
    else:
        situation = (
            "The current reporting environment suggests possible de-escalation dynamics. "
            "Diplomatic engagement, negotiations or stabilization signals are increasingly visible."
        )

    methodology = (
        f"The system analysed {article_count} headlines with a cumulative score of {total_score}. "
        "To make day-to-day comparison more reliable, a normalized conflict index is calculated "
        "by dividing the total score by the number of analysed articles."
    )

    trend = (
        f"The short-term trajectory is currently assessed as {trajectory}. "
        f"Current outlook: {outlook}"
    )

    interpretation = (
        "This index reflects the tone of the information environment rather than the exact number "
        "of real-world incidents. Large moves may partly reflect repeated reporting on the same event."
    )

    return " ".join([intro, situation, methodology, trend, interpretation])


def load_history_with_index(history_file: Path):
    rows = []

    if not history_file.exists():
        return rows

    with open(history_file, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                total_score = float(row.get("total_score", 0))
                article_count = float(row.get("article_count", 0))
                conflict_index = round(total_score / article_count, 2) if article_count > 0 else 0
            except Exception:
                conflict_index = 0

            rows.append({
                "date": row.get("date", ""),
                "total_score": row.get("total_score", ""),
                "assessment": row.get("assessment", ""),
                "article_count": row.get("article_count", ""),
                "conflict_index": conflict_index
            })

    rows = sorted(rows, key=lambda x: x["date"])
    return rows


def extract_signal_lists(scored_articles):
    escalation_articles = sorted(
        [a for a in scored_articles if a.get("score", 0) < 0],
        key=lambda x: x.get("score", 0)
    )[:5]

    diplomatic_articles = sorted(
        [a for a in scored_articles if a.get("score", 0) > 0],
        key=lambda x: x.get("score", 0),
        reverse=True
    )[:5]

    key_headlines = sorted(
        scored_articles,
        key=lambda x: abs(x.get("score", 0)),
        reverse=True
    )[:5]

    return escalation_articles, diplomatic_articles, key_headlines


def compact_article(article):
    return {
        "title": article.get("title", ""),
        "link": article.get("link", ""),
        "source": article.get("source", ""),
        "published": article.get("published", ""),
        "score": article.get("score", 0)
    }


def main():
    base_dir = Path(__file__).resolve().parent.parent

    input_file = base_dir / "data" / "processed" / "latest_scored.json"
    history_file = base_dir / "data" / "conflict_history.csv"
    output_dir = base_dir / "docs"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / "latest_summary.json"

    with open(input_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    article_count = data.get("article_count", 0)
    total_score = data.get("total_score", 0)
    scored_articles = data.get("articles", [])

    if article_count == 0:
        conflict_index = 0
    else:
        conflict_index = round(total_score / article_count, 2)

    assessment = classify_index(conflict_index)

    history_rows = load_history_with_index(history_file)
    trajectory = calculate_trajectory(history_rows)
    outlook = build_outlook(conflict_index, trajectory)

    commentary = generate_commentary(
        conflict_index,
        article_count,
        total_score,
        trajectory,
        outlook
    )

    escalation_articles, diplomatic_articles, key_headlines = extract_signal_lists(scored_articles)

    summary = {
        "report_date": data.get("created_at", "")[:10],
        "created_at": data.get("created_at", ""),
        "article_count": article_count,
        "total_score": total_score,
        "conflict_index": conflict_index,
        "assessment": assessment,
        "trajectory": trajectory,
        "outlook": outlook,
        "commentary": commentary,
        "top_escalation_signals": [compact_article(a) for a in escalation_articles],
        "top_diplomatic_signals": [compact_article(a) for a in diplomatic_articles],
        "key_headlines": [compact_article(a) for a in key_headlines]
    }

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print("Dashboard summary generated with signal lists.")


if __name__ == "__main__":
    main()
