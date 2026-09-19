from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass
class TrainingRow:
    source_text: str
    optimized_text: str
    score: float


def load_rows(csv_path: Path) -> list[TrainingRow]:
    rows: list[TrainingRow] = []
    with csv_path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for item in reader:
            rows.append(
                TrainingRow(
                    source_text=item.get("source_text", ""),
                    optimized_text=item.get("optimized_text", ""),
                    score=float(item.get("score", 0.0)),
                )
            )
    return rows


def main() -> None:
    data_path = Path("data/training_pairs.csv")
    if not data_path.exists():
        print("Training data not found. Expected: data/training_pairs.csv")
        return

    rows = load_rows(data_path)
    if not rows:
        print("No rows loaded from training data.")
        return

    # Placeholder for ranking model training logic.
    avg_score = sum(r.score for r in rows) / len(rows)
    print(f"Loaded {len(rows)} rows. Average score={avg_score:.4f}")


if __name__ == "__main__":
    main()
