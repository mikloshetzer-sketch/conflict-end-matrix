from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np


def main():

    base_dir = Path(__file__).resolve().parent.parent
    input_file = base_dir / "data" / "conflict_history.csv"
    output_dir = base_dir / "docs"
    output_dir.mkdir(parents=True, exist_ok=True)

    output_file = output_dir / "conflict_trend.png"

    df = pd.read_csv(input_file)

    if df.empty:
        print("No history data available")
        return

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["total_score"] = pd.to_numeric(df["total_score"], errors="coerce")
    df["article_count"] = pd.to_numeric(df["article_count"], errors="coerce")

    df = df.dropna(subset=["date", "total_score", "article_count"])
    df = df.sort_values("date")

    df["conflict_index"] = df.apply(
        lambda row: row["total_score"] / row["article_count"] if row["article_count"] > 0 else 0,
        axis=1
    )

    df["moving_average_3"] = df["conflict_index"].rolling(window=3, min_periods=1).mean()

    # regression trend
    x = np.arange(len(df))
    y = df["conflict_index"].values

    if len(x) > 1:
        coeff = np.polyfit(x, y, 1)
        trend = np.poly1d(coeff)
        df["trend_line"] = trend(x)
    else:
        df["trend_line"] = y

    plt.figure(figsize=(11,5.5))

    plt.plot(
        df["date"],
        df["conflict_index"],
        marker="o",
        linewidth=2,
        label="Daily conflict index"
    )

    plt.plot(
        df["date"],
        df["moving_average_3"],
        linestyle="--",
        linewidth=2.5,
        label="3-day moving average"
    )

    plt.plot(
        df["date"],
        df["trend_line"],
        linestyle=":",
        linewidth=3,
        label="Trend line"
    )

    plt.title("Conflict Escalation / De-escalation Trend")
    plt.xlabel("Date")
    plt.ylabel("Conflict Index")

    plt.xticks(rotation=45)

    plt.legend()
    plt.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(output_file, dpi=150)
    plt.close()

    print("Chart generated with trend line")


if __name__ == "__main__":
    main()
