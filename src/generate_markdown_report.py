import json
from pathlib import Path
from datetime import datetime


def main():
    base_dir = Path(__file__).resolve().parent.parent
    input_file = base_dir / "data" / "processed" / "latest_scored.json"
    output_dir = base_dir / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / "latest_report.md"

    with open(input_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    created_at = data.get("created_at", "")
    article_count = data.get("article_count", 0)
    total_score = data.get("total_score", 0)
    assessment = data.get("assessment", "unknown")
    articles = data.get("articles", [])

    top_negative = sorted(articles, key=lambda x: x.get("score", 0))[:5]
    top_positive = sorted(articles, key=lambda x: x.get("score", 0), reverse=True)[:5]

    lines = []
    lines.append("# Daily Conflict Report")
    lines.append("")
    lines.append(f"**Generated:** {created_at}")
    lines.append(f"**Articles analyzed:** {article_count}")
    lines.append(f"**Total score:** {total_score}")
    lines.append(f"**Assessment:** {assessment}")
    lines.append("")

    lines.append("## Summary")
    lines.append("")
    if total_score <= -15:
        lines.append("The news flow indicates strong escalation dynamics.")
    elif total_score <= -5:
        lines.append("The news flow indicates moderate escalation dynamics.")
    elif total_score < 5:
        lines.append("The news flow is mixed, with no clear dominant direction.")
    elif total_score < 15:
        lines.append("The news flow indicates moderate de-escalation dynamics.")
    else:
        lines.append("The news flow indicates strong de-escalation dynamics.")
    lines.append("")

    lines.append("## Top escalation signals")
    lines.append("")
    for article in top_negative:
        title = article.get("title", "")
        score = article.get("score", 0)
        link = article.get("link", "")
        lines.append(f"- **{score}** — [{title}]({link})")
    lines.append("")

    lines.append("## Top de-escalation signals")
    lines.append("")
    for article in top_positive:
        title = article.get("title", "")
        score = article.get("score", 0)
        link = article.get("link", "")
        lines.append(f"- **{score}** — [{title}]({link})")
    lines.append("")

    lines.append("## All analyzed articles")
    lines.append("")
    for article in articles:
        title = article.get("title", "")
        score = article.get("score", 0)
        source = article.get("source", "")
        published = article.get("published", "")
        link = article.get("link", "")
        lines.append(f"- **{score}** | {source} | {published} | [{title}]({link})")

    content = "\n".join(lines)

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"Markdown report created: {output_file}")


if __name__ == "__main__":
    main()
