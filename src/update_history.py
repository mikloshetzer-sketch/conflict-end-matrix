import json
import csv
from pathlib import Path
from datetime import datetime


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

    row = [date, total_score, assessment, article_count]

    file_exists = history_file.exists()

    with open(history_file, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)

        if not file_exists:
            writer.writerow(["date", "total_score", "assessment", "article_count"])

        writer.writerow(row)

    print("History updated:", row)


if __name__ == "__main__":
    main()
