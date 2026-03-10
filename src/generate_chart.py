from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt


def main():
    base_dir = Path(__file__).resolve().parent.parent
    input_file = base_dir / "data" / "conflict_history.csv"
    output_dir = base_dir / "docs"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / "conflict_trend.png"

    df = pd.read_csv(input_file)

    if df.empty:
        print("No history data available.")
        return

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"])
    df = df.sort_values("date")

    plt.figure(figsize=(10, 5))
    plt.plot(df["date"], df["total_score"], marker="o")
    plt.title("Conflict Escalation / De-escalation Trend")
    plt.xlabel("Date")
    plt.ylabel("Total Score")
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.savefig(output_file, dpi=150)
    plt.close()

    print(f"Chart created: {output_file}")


if __name__ == "__main__":
    main()
