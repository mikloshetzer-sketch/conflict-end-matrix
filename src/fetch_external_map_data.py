import json
from pathlib import Path
import requests

FILES = {
    "brief_daily.json": "https://raw.githubusercontent.com/mikloshetzer-sketch/ukraine-war-map/main/data/brief_daily.json",
    "change_latest.json": "https://raw.githubusercontent.com/mikloshetzer-sketch/ukraine-war-map/main/data/change_latest.json",
    "deepstate_latest.geojson": "https://raw.githubusercontent.com/mikloshetzer-sketch/ukraine-war-map/main/data/deepstate_latest.geojson",
}

def main():
    base_dir = Path(__file__).resolve().parent.parent
    out_dir = base_dir / "data" / "external"
    out_dir.mkdir(parents=True, exist_ok=True)

    for filename, url in FILES.items():
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        (out_dir / filename).write_text(r.text, encoding="utf-8")
        print(f"Saved: {filename}")

if __name__ == "__main__":
    main()
