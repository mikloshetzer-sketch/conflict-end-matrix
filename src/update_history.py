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

    latest_row = {
        "date": date,
        "total_score": str(total_score),
        "assessment": assessment,
        "article_count": str(article_count)
    }

    deduplicated = {}

    if history_file.exists():
        with open(history_file, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                row_date = row.get("date", "").strip()
                if row_date:
                    deduplicated[row_date] = {
                        "date": row_date,
                        "total_score": row.get("total_score", "").strip(),
                        "assessment": row.get("assessment", "").strip(),
                        "article_count": row.get("article_count", "").strip()
                    }

    deduplicated[date] = latest_row

    rows = [deduplicated[d] for d in sorted(deduplicated.keys())]

    with open(history_file, "w", newline="", encoding="utf-8") as f:
        fieldnames = ["date", "total_score", "assessment", "article_count"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"History cleaned and updated for {date}")
    print(f"Total unique days stored: {len(rows)}")


if __name__ == "__main__":
    main()
