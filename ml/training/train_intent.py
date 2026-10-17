"""Train and evaluate the intent classifier.

    python -m ml.training.train_intent

Two evaluations are reported:
  1. HELD-OUT TEST SET (data/training/intents_test.csv): different wording from the training file.
  2. 5-FOLD CROSS-VALIDATION on the training file.
Outputs go to ml/models/:  intent_model.joblib, intent_metrics.json,
                           intent_confusion_matrix.csv, intent_confusion_matrix.png, intent_errors.csv
"""
import json
import sys

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, precision_recall_fscore_support
from sklearn.model_selection import StratifiedKFold, cross_val_predict

from app.services.intent_classifier import (MODEL_FILE, TEST_FILE, TRAIN_FILE, IntentClassifier,
                                            build_pipeline, load_dataset)
from app.utils.text_cleaner import normalize_text

OUT = MODEL_FILE.parent


def summarize(y_true, y_pred, labels) -> dict:
    p, r, f1, _ = precision_recall_fscore_support(y_true, y_pred, average="weighted", zero_division=0)
    mp, mr, mf1, _ = precision_recall_fscore_support(y_true, y_pred, average="macro", zero_division=0)
    return {"accuracy": round(accuracy_score(y_true, y_pred), 4),
            "precision_weighted": round(p, 4), "recall_weighted": round(r, 4), "f1_weighted": round(f1, 4),
            "precision_macro": round(mp, 4), "recall_macro": round(mr, 4), "f1_macro": round(mf1, 4)}


def save_confusion(y_true, y_pred, labels) -> None:
    cm = confusion_matrix(y_true, y_pred, labels=labels)
    pd.DataFrame(cm, index=[f"true:{l}" for l in labels], columns=[f"pred:{l}" for l in labels]).to_csv(
        OUT / "intent_confusion_matrix.csv")
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(10, 8))
        im = ax.imshow(cm, cmap="Blues")
        ax.set_xticks(range(len(labels)), labels, rotation=60, ha="right", fontsize=8)
        ax.set_yticks(range(len(labels)), labels, fontsize=8)
        ax.set_xlabel("Predicted intent")
        ax.set_ylabel("True intent")
        ax.set_title("Intent classifier - confusion matrix (held-out test set)")
        for i in range(len(labels)):
            for j in range(len(labels)):
                if cm[i, j]:
                    ax.text(j, i, cm[i, j], ha="center", va="center", fontsize=8,
                            color="white" if cm[i, j] > cm.max() / 2 else "black")
        fig.colorbar(im)
        fig.tight_layout()
        fig.savefig(OUT / "intent_confusion_matrix.png", dpi=150)
        plt.close(fig)
    except ImportError:
        print("(matplotlib not installed: skipped the PNG; the CSV was saved)")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    X, y = load_dataset(TRAIN_FILE)
    test = pd.read_csv(TEST_FILE).dropna()
    Xt, yt = [normalize_text(t) for t in test["text"]], test["intent"].tolist()
    labels = sorted(set(y))

    print(f"Training questions : {len(X)}   Test questions : {len(Xt)}   Intents : {len(labels)}")

    # 1) cross-validation on the training file
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    y_cv = cross_val_predict(build_pipeline(), X, y, cv=cv)
    cv_metrics = summarize(y, y_cv, labels)

    # 2) train on everything in the training file, test on the held-out file
    clf = IntentClassifier().train(X, y)
    y_pred = clf.pipeline.predict(Xt)
    test_metrics = summarize(yt, y_pred, labels)

    print("\n=== Held-out test set ===")
    print(classification_report(yt, y_pred, labels=labels, zero_division=0, digits=3))
    print("=== Summary ===")
    print(f"{'':28}{'accuracy':>9}{'precision':>10}{'recall':>8}{'F1':>8}")
    print(f"{'Held-out test (weighted)':28}{test_metrics['accuracy']:>9.3f}{test_metrics['precision_weighted']:>10.3f}"
          f"{test_metrics['recall_weighted']:>8.3f}{test_metrics['f1_weighted']:>8.3f}")
    print(f"{'5-fold CV (weighted)':28}{cv_metrics['accuracy']:>9.3f}{cv_metrics['precision_weighted']:>10.3f}"
          f"{cv_metrics['recall_weighted']:>8.3f}{cv_metrics['f1_weighted']:>8.3f}")

    errors = [{"question": q, "true": t, "predicted": p} for q, t, p in zip(test["text"], yt, y_pred) if t != p]
    pd.DataFrame(errors, columns=["question", "true", "predicted"]).to_csv(OUT / "intent_errors.csv", index=False)
    if errors:
        print(f"\nMistakes on the test set ({len(errors)}):")
        for e in errors:
            print(f"  '{e['question']}'  true={e['true']}  predicted={e['predicted']}")

    save_confusion(yt, list(y_pred), labels)
    report = classification_report(yt, y_pred, labels=labels, zero_division=0, output_dict=True)
    (OUT / "intent_metrics.json").write_text(json.dumps(
        {"train_size": len(X), "test_size": len(Xt), "intents": labels,
         "held_out_test": test_metrics, "cross_validation_5fold": cv_metrics,
         "per_intent_test": {k: {m: round(v, 4) for m, v in report[k].items()} for k in labels}}, indent=2))

    # Final model for the chatbot: trained on training + test questions (more data = better model).
    final = IntentClassifier().train(X + Xt, y + yt)
    path = final.save()
    print(f"\nSaved model -> {path}")
    print("Saved metrics, confusion matrix and error list in", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
