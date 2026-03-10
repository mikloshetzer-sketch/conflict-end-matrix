from pathlib import Path
import json


def main():
    base_dir = Path(__file__).resolve().parent.parent
    output_dir = base_dir / "data" / "raw"
    output_dir.mkdir(parents=True, exist_ok=True)

    sample_data = {
        "status": "ok",
        "message": "News fetch placeholder created successfully",
        "sources": [],
        "articles": []
    }

    output_file = output_dir / "latest_news.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(sample_data, f, ensure_ascii=False, indent=2)

    print(f"Saved placeholder news data to: {output_file}")


if __name__ == "__main__":
    main()
