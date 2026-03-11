import json
from datetime import datetime
from pathlib import Path

import requests


FILES = {
    "brief_daily.json": "https://raw.githubusercontent.com/mikloshetzer-sketch/ukraine-war-map/main/data/brief_daily.json",
    "change_latest.json": "https://raw.githubusercontent.com/mikloshetzer-sketch/ukraine-war-map/main/data/change_latest.json",
    "deepstate_latest.geojson": "https://raw.githubusercontent.com/mikloshetzer-sketch/ukraine-war-map/main/data/deepstate_latest.geojson",
}

TIMEOUT = 30


def fetch_file(url: str) -> tuple[bool, str]:
    try:
        response = requests.get(url, timeout=TIMEOUT)
        response.raise_for_status()
        return True, response.text
    except Exception as exc:
        return False, str(exc)


def main():
    base_dir = Path(__file__).resolve().parent.parent
    out_dir = base_dir / "data" / "external"
    out_dir.mkdir(parents=True, exist_ok=True)

    status = {
        "created_at": datetime.utcnow().isoformat(),
        "source_repo": "mikloshetzer-sketch/ukraine-war-map",
        "files": [],
    }

    success_count = 0

    for filename, url in FILES.items():
        ok, result = fetch_file(url)

        file_status = {
            "filename": filename,
            "url": url,
            "success": ok,
        }

        if ok:
            target_path = out_dir / filename
            target_path.write_text(result, encoding="utf-8")
            file_status["saved_to"] = str(target_path.relative_to(base_dir))
            file_status["size_bytes"] = len(result.encode("utf-8"))
            success_count += 1
            print(f"Saved: {filename}")
        else:
            file_status["error"] = result
            print(f"Failed: {filename} -> {result}")

        status["files"].append(file_status)

    status["success_count"] = success_count
    status["total_count"] = len(FILES)

    status_path = out_dir / "fetch_status.json"
    status_path.write_text(
        json.dumps(status, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    print(f"Saved status: {status_path}")

    if success_count == 0:
        raise RuntimeError("No external files could be downloaded.")


if __name__ == "__main__":
    main()
