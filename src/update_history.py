import json
import csv
from pathlib import Path


def main():
    base_dir = Path(__file__).resolve().parent.parent

    scored_file = base_dir / "data" / "processed" / "latest_scored.json"
    history_file = base_dir / "data" / "conflict_history.csv"

    with open(scored_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    date = data.get("created_at", "")[:10]
    total_score = data.get("total_score", 0)
    assessment = data.get("assessment", "")
    article_count = data.get("article_count", 0)

    new_row = {
        "date": date,
        "total_score": total_score,
        "assessment": assessment,
        "article_count": article_count
    }

    rows = []

    if history_file.exists():
        with open(history_file, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

    updated = False
    for row in rows:
        if row["date"] == date:
            row["total_score"] = str(total_score)
            row["assessment"] = assessment
            row["article_count"] = str(article_count)
            updated = True
            break

    if not updated:
        rows.append({
            "date": date,
            "total_score": str(total_score),
            "assessment": assessment,
            "article_count": str(article_count)
        })

    rows = sorted(rows, key=lambda x: x["date"])

    with open(history_file, "w", newline="", encoding="utf-8") as f:
        fieldnames = ["date", "total_score", "assessment", "article_count"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    if updated:
        print(f"Updated existing history row for {date}")
    else:
        print(f"Added new history row for {date}")


if __name__ == "__main__":
    main()
