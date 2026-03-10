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


def generate_commentary(index: float, article_count: int, total_score: int):

    assessment = classify_index(index)

    intro = (
        "This automated assessment analyses international news headlines "
        "related to the monitored conflict environment."
    )

    situation = ""

    if assessment == "strong escalation":
        situation = (
            "The current information environment indicates strong escalation dynamics. "
            "A high concentration of headlines refers to military activity such as strikes, "
            "missile launches, retaliatory actions or combat developments."
        )

    elif assessment == "moderate escalation":
        situation = (
            "The news environment suggests moderate escalation pressure. "
            "Military developments appear regularly in reporting, "
            "though the information pattern does not yet indicate a full-scale conflict surge."
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
        f"The system analysed {article_count} headlines with a cumulative "
        f"escalation score of {total_score}. "
        "To make comparisons between days more reliable, a normalized conflict index "
        "is calculated by dividing the total escalation score by the number of analysed articles."
    )

    interpretation = (
        "This index reflects the overall tone of the information environment rather than "
        "the exact number of real-world incidents. Peaks in the index may occur when multiple "
        "media outlets report the same event."
    )

    commentary = " ".join([intro, situation, methodology, interpretation])

    return commentary


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

    assessment = classify_index(conflict_index)

    commentary = generate_commentary(
        conflict_index,
        article_count,
        total_score
    )

    summary = {
        "report_date": data.get("created_at", "")[:10],
        "created_at": data.get("created_at", ""),
        "article_count": article_count,
        "total_score": total_score,
        "conflict_index": conflict_index,
        "assessment": assessment,
        "commentary": commentary
    }

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print("Dashboard summary generated.")


if __name__ == "__main__":
    main()
