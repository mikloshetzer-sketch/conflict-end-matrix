import json
from pathlib import Path


def main():
    base_dir = Path(__file__).resolve().parent.parent
    input_file = base_dir / "data" / "processed" / "latest_scored.json"
    output_dir = base_dir / "docs"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / "latest_summary.json"

    with open(input_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    summary = {
        "report_date": data.get("created_at", "")[:10],
        "created_at": data.get("created_at", ""),
        "article_count": data.get("article_count", 0),
        "total_score": data.get("total_score", 0),
        "assessment": data.get("assessment", "unknown")
    }

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print(f"Dashboard summary created: {output_file}")


if __name__ == "__main__":
    main()
