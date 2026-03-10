import json
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


def generate_commentary(index: float, article_count: int, total_score: int) -> str:

    direction = classify_index(index)

    text = []

    text.append("Daily conflict signal assessment:")

    if direction == "strong escalation":
        text.append(
            "The current news flow indicates strong escalation dynamics. "
            "Media reporting is dominated by military actions such as strikes, "
            "missile activity or retaliatory operations."
        )

    elif direction == "moderate escalation":
        text.append(
            "The information environment suggests moderate escalation. "
            "Military developments appear frequently in headlines, "
            "but the situation does not yet indicate a large-scale expansion."
        )

    elif direction == "mild escalation":
        text.append(
            "The news environment shows mild escalation signals. "
            "Some conflict-related developments appear, but they are not dominant."
        )

    elif direction == "neutral":
        text.append(
            "The information flow appears relatively balanced. "
            "Escalatory and diplomatic signals are roughly balanced."
        )

    else:
        text.append(
            "News signals suggest possible de-escalation dynamics. "
            "Diplomatic engagement or negotiation signals appear in reporting."
        )

    text.append(
        f"The system analysed {article_count} news headlines "
        f"with a combined escalation score of {total_score}."
    )

    text.append(
        "The normalized conflict index allows comparison between days "
        "independently of the number of analysed articles."
    )

    return " ".join(text)


def main():

    base_dir = Path(__file__).resolve().parent.parent

    input_file = base_dir / "data" / "processed" / "latest_scored.json"
    output_dir = base_dir / "docs"
    output_dir.mkdir(parents=True, exist_ok=True)

    output_file = output_dir / "latest_summary.json"

    with open(input_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    article_count = data.get("article_count", 0)
    total_score = data.get("total_score", 0)

    if article_count == 0:
        conflict_index = 0
    else:
        conflict_index = round(total_score / article_count, 2)

    commentary = generate_commentary(conflict_index, article_count, total_score)

    summary = {
        "report_date": data.get("created_at", "")[:10],
        "created_at": data.get("created_at", ""),
        "article_count": article_count,
        "total_score": total_score,
        "conflict_index": conflict_index,
        "assessment": classify_index(conflict_index),
        "commentary": commentary
    }

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print("Dashboard summary updated.")


if __name__ == "__main__":
    main()
