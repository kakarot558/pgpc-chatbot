"""Phase 6: intent classification  (TF-IDF + Logistic Regression).

The classifier reads the NORMALIZED question (lowercase, no punctuation) BEFORE stop-word
removal, because words like "where", "who" and "how many" are exactly what reveals the intent.

    "where is the registrar office"  ->  office_location  (0.9x)

Features = word 1-2 grams  +  character 3-5 grams (the character part keeps typos such as
"registrer" or "ofice" useful).

Train + evaluate:   python -m ml.training.train_intent
Try it:             python -m app.services.intent_classifier "Where is the registrar office?"
"""
import logging
import sys
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import joblib
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import FeatureUnion, Pipeline

from app.core.config import get_settings
from app.utils.text_cleaner import normalize_text

logger = logging.getLogger("pgpc.intent")

ROOT = Path(__file__).resolve().parents[2]
TRAIN_FILE = ROOT / "data" / "training" / "intents.csv"
TEST_FILE = ROOT / "data" / "training" / "intents_test.csv"
MODEL_FILE = ROOT / "ml" / "models" / "intent_model.joblib"

UNKNOWN = "unknown"

# What the later phases do with each intent. "small_talk" intents never search the knowledge base.
SMALL_TALK_INTENTS = {"greeting", "thanks", "goodbye", "bot_info"}
OUT_OF_SCOPE_INTENT = "out_of_scope"


@dataclass
class IntentResult:
    intent: str                      # predicted intent, or "unknown" when confidence is too low
    confidence: float                # probability of the best intent (0..1)
    raw_intent: str                  # best guess even when it was rejected as unknown
    alternatives: list[tuple[str, float]] = field(default_factory=list)   # top 3

    @property
    def is_small_talk(self) -> bool:
        return self.intent in SMALL_TALK_INTENTS

    @property
    def is_out_of_scope(self) -> bool:
        return self.intent == OUT_OF_SCOPE_INTENT

    @property
    def needs_knowledge_search(self) -> bool:
        """True when Phase 7 should look for an answer in the PGPC knowledge base."""
        return self.intent not in SMALL_TALK_INTENTS | {OUT_OF_SCOPE_INTENT, UNKNOWN}


def build_pipeline() -> Pipeline:
    features = FeatureUnion([
        ("word", TfidfVectorizer(analyzer="word", ngram_range=(1, 2), sublinear_tf=True, min_df=1)),
        ("char", TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True, min_df=2)),
    ])
    model = LogisticRegression(C=10.0, max_iter=2000, class_weight="balanced", random_state=42)
    return Pipeline([("features", features), ("model", model)])


def load_dataset(path: Path = TRAIN_FILE) -> tuple[list[str], list[str]]:
    df = pd.read_csv(path).dropna()
    texts = [normalize_text(t) for t in df["text"]]
    return texts, df["intent"].astype(str).tolist()


class IntentClassifier:
    def __init__(self, pipeline: Pipeline | None = None, min_confidence: float | None = None):
        self.pipeline = pipeline
        self.min_confidence = min_confidence if min_confidence is not None else get_settings().intent_min_confidence

    # ---------------------------------------------------------------- training
    def train(self, texts: list[str], labels: list[str]) -> "IntentClassifier":
        """`texts` must already be normalized (see load_dataset)."""
        self.pipeline = build_pipeline().fit(texts, labels)
        return self

    @classmethod
    def from_csv(cls, path: Path = TRAIN_FILE, **kw) -> "IntentClassifier":
        texts, labels = load_dataset(path)
        return cls(**kw).train(texts, labels)

    # ------------------------------------------------------------ persistence
    def save(self, path: Path | None = None) -> Path:
        path = path or MODEL_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self.pipeline, path)
        return path

    @classmethod
    def load(cls, path: Path | None = None, **kw) -> "IntentClassifier":
        path = path or MODEL_FILE
        return cls(joblib.load(path), **kw)

    @property
    def classes(self) -> list[str]:
        return list(self.pipeline.classes_)

    # ------------------------------------------------------------- prediction
    def predict(self, question) -> IntentResult:
        normalized = normalize_text(question)
        if not normalized:
            return IntentResult(intent=UNKNOWN, confidence=0.0, raw_intent=UNKNOWN)
        probs = self.pipeline.predict_proba([normalized])[0]
        order = probs.argsort()[::-1]
        classes = self.pipeline.classes_
        best, conf = str(classes[order[0]]), float(probs[order[0]])
        alts = [(str(classes[i]), round(float(probs[i]), 4)) for i in order[:3]]
        intent = best if conf >= self.min_confidence else UNKNOWN
        return IntentResult(intent=intent, confidence=round(conf, 4), raw_intent=best, alternatives=alts)

    def predict_many(self, questions: list[str]) -> list[str]:
        """Raw label for each question, without the confidence cut-off (used for evaluation)."""
        return [str(x) for x in self.pipeline.predict([normalize_text(q) for q in questions])]


@lru_cache
def get_intent_classifier() -> IntentClassifier:
    """Loads the saved model. If it does not exist yet, trains one from intents.csv (a few seconds)
    and saves it, so the chatbot works even before train_intent has been run."""
    if MODEL_FILE.exists():
        try:
            return IntentClassifier.load()
        except Exception:  # corrupted file or scikit-learn version change
            logger.warning("Saved intent model could not be loaded; retraining.")
    clf = IntentClassifier.from_csv()
    try:
        clf.save()
    except OSError:
        logger.warning("Could not save the intent model (read-only folder?).")
    return clf


def _demo(question: str) -> None:
    r = get_intent_classifier().predict(question)
    print(f"Question   : {question}")
    print(f"Normalized : {normalize_text(question)}")
    print(f"Intent     : {r.intent}  (confidence {r.confidence:.2f})")
    print("Top 3      : " + ", ".join(f"{i} {p:.2f}" for i, p in r.alternatives))


if __name__ == "__main__":
    _demo(" ".join(sys.argv[1:]) or "Where is the registrar office?")
