"""Runs the fixed question set (data/eval/answer_questions.csv) through the real answer pipeline and prints accuracy.
Use it after every change, and for the thesis: it gives a number, not just examples.
    python -m ml.evaluation.run_answer_eval
"""
import csv
import sys
from pathlib import Path

from app.database.database import SessionLocal
from app.services.answer_generator import generate_answer

FILE = Path(__file__).resolve().parents[2] / "data" / "eval" / "answer_questions.csv"


def run() -> tuple[int, int, list[str]]:
    rows = list(csv.DictReader(FILE.open(encoding="utf-8")))
    wrong = []
    with SessionLocal() as db:
        for r in rows:
            text = generate_answer(db, r["question"]).text
            if r["expected"].lower() not in text.lower():
                wrong.append(f'{r["question"]!r}: expected "{r["expected"]}"')
    return len(rows) - len(wrong), len(rows), wrong


if __name__ == "__main__":
    ok, total, wrong = run()
    print(f"Answer check: {ok}/{total} correct ({100 * ok / total:.1f}%)")
    for w in wrong:
        print("  MISS", w)
    sys.exit(0 if not wrong else 1)
