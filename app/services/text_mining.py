"""Text-mining pipeline (steps 1-7 of the project spec).

    raw text -> normalize -> tokenize -> remove stop words -> lemmatize -> keywords

Run a demo from the terminal:   python -m app.services.text_mining "Where is the registrar office?"
"""
import difflib
import logging
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache

from app.core.config import get_settings
from app.utils.text_cleaner import normalize_text

logger = logging.getLogger("pgpc.textmining")

# Used only when the NLTK stop-word data has not been downloaded.
FALLBACK_STOPWORDS = set("""
a about above after again all am an and any are as at be because been before being below between both but by
can could did do does doing down during each few for from further had has have having he her here hers him his
how i if in into is it its itself just me more most my myself of off on once only or other our out over own
same she should so some such than that the their theirs them then there these they this those through to too
under until up very was we were what when where which while who whom why will with would you your yours
""".split())

# Chat filler that carries no meaning for searching the PGPC knowledge base.
# Question words (where, who, ...) are removed here, but the intent classifier (Phase 6)
# reads the normalized text BEFORE stop-word removal, so it still sees them.
CHAT_FILLER = set("""
hi hello hey please pls thanks thank tell show give find know want need let lets may might might
looking look ask asking question about like get got also okay ok yes say says said
""".split())

# Negations change meaning, so they are kept even though NLTK lists them as stop words.
KEEP_WORDS = {"no", "not", "nor"}


def _load_stopwords() -> tuple[set[str], bool]:
    try:
        from nltk.corpus import stopwords
        return set(stopwords.words("english")), True
    except (LookupError, ImportError):
        return set(FALLBACK_STOPWORDS), False


def _load_lemmatizer():
    try:
        from nltk.stem import WordNetLemmatizer
        lemmatizer = WordNetLemmatizer()
        lemmatizer.lemmatize("tests")  # raises LookupError if WordNet is missing
        return lemmatizer.lemmatize
    except (LookupError, ImportError):
        return None


def _light_lemma(word: str) -> str:
    """Tiny rule-based fallback: facilities -> facility, rules -> rule, but status/address stay."""
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


@dataclass
class ProcessedText:
    """Every intermediate result is kept, so the pipeline can be shown step by step in a demo."""
    original: str
    normalized: str
    tokens: list[str] = field(default_factory=list)            # after tokenizing
    filtered_tokens: list[str] = field(default_factory=list)   # after stop-word removal
    lemmas: list[str] = field(default_factory=list)            # after lemmatizing
    keywords: list[str] = field(default_factory=list)          # unique, in order of appearance

    @property
    def search_text(self) -> str:
        """The string that goes into TF-IDF (Phase 7)."""
        return " ".join(self.lemmas)


class TextMiner:
    def __init__(self, lemmatize: bool = True, use_nltk: bool = True):
        self.lemmatize_enabled = lemmatize
        self._nltk_stopwords = False
        self._lemmatizer = None
        if use_nltk:
            stops, self._nltk_stopwords = _load_stopwords()
            self._lemmatizer = _load_lemmatizer() if lemmatize else None
            if not self._nltk_stopwords:
                logger.warning("NLTK data not found; using built-in lists. Run: python -m app.utils.nltk_setup")
        else:
            stops = set(FALLBACK_STOPWORDS)
        self.stopwords = (stops | CHAT_FILLER) - KEEP_WORDS

    # Step 4
    def tokenize(self, normalized: str) -> list[str]:
        try:
            from nltk.tokenize import RegexpTokenizer  # offline tokenizer, needs no downloads
            return RegexpTokenizer(r"[a-z0-9]+").tokenize(normalized)
        except ImportError:
            return re.findall(r"[a-z0-9]+", normalized)

    # Step 5
    def remove_stopwords(self, tokens: list[str]) -> list[str]:
        return [t for t in tokens if t not in self.stopwords]

    # Step 6
    def lemmatize(self, tokens: list[str]) -> list[str]:
        if not self.lemmatize_enabled:
            return list(tokens)
        if self._lemmatizer:
            return [t if t.isdigit() else self._lemmatizer(t) for t in tokens]
        return [t if t.isdigit() else _light_lemma(t) for t in tokens]

    # Step 7
    @staticmethod
    def extract_keywords(tokens: list[str], top_n: int | None = None, by_frequency: bool = False) -> list[str]:
        """Unique words. Default order = order of appearance (good for short questions).
        by_frequency=True ranks by how often a word occurs (good for long text such as handbook sections)."""
        if by_frequency:
            counts = Counter(tokens)
            first_seen = {t: i for i, t in reversed(list(enumerate(tokens)))}
            ranked = sorted(counts, key=lambda t: (-counts[t], first_seen[t]))
        else:
            ranked = list(dict.fromkeys(tokens))
        return ranked[:top_n] if top_n else ranked

    def make_corrector(self, vocabulary, cutoff: float | None = None) -> "SpellingCorrector":
        """A spelling corrector that also knows the stop words, so a typo like 'wher' becomes 'where'
        and is then removed instead of lingering as a meaningless keyword."""
        return SpellingCorrector(set(vocabulary) | self.stopwords, cutoff)

    def process(self, text, corrector: "SpellingCorrector | None" = None) -> ProcessedText:
        """Run the whole pipeline. Pass a corrector (built from the knowledge base words) to fix typos
        right after tokenizing."""
        normalized = normalize_text(text)
        tokens = self.tokenize(normalized)
        if corrector:
            tokens = corrector.correct(tokens)
        filtered = self.remove_stopwords(tokens)
        lemmas = self.lemmatize(filtered)
        return ProcessedText(original=text if isinstance(text, str) else "", normalized=normalized,
                             tokens=tokens, filtered_tokens=filtered, lemmas=lemmas,
                             keywords=self.extract_keywords(lemmas))

    def document_keywords(self, text: str, top_n: int = 10) -> list[str]:
        """Most frequent meaningful words of a longer text (used when saving knowledge chunks)."""
        return self.extract_keywords(self.process(text).lemmas, top_n=top_n, by_frequency=True)

    def tfidf_keywords(self, texts: list[str], top_n: int = 8) -> list[list[str]]:
        """For each text, the words that are most specific to it compared with the other texts (TF-IDF)."""
        from sklearn.feature_extraction.text import TfidfVectorizer
        if not texts:
            return []
        vectorizer = TfidfVectorizer(analyzer=lambda doc: self.process(doc).lemmas)
        try:
            matrix = vectorizer.fit_transform(texts)
        except ValueError:  # every text was empty after cleaning
            return [[] for _ in texts]
        terms = vectorizer.get_feature_names_out()
        result = []
        for row in range(matrix.shape[0]):
            scores = matrix.getrow(row)
            pairs = sorted(zip(scores.indices, scores.data), key=lambda p: (-p[1], terms[p[0]]))
            result.append([terms[i] for i, _ in pairs[:top_n]])
        return result


class SpellingCorrector:
    """Fixes small typos by matching unknown words to words that really occur in the knowledge base.
    'registrer' -> 'registrar'.  Words that are already known, very short, or numbers are left alone."""

    def __init__(self, vocabulary, cutoff: float | None = None):
        self.vocabulary = set(vocabulary)
        self._sorted = sorted(self.vocabulary)
        self.cutoff = cutoff if cutoff is not None else get_settings().spelling_cutoff

    def correct_token(self, token: str) -> str:
        if token in self.vocabulary or len(token) < 4 or token.isdigit():
            return token
        match = difflib.get_close_matches(token, self._sorted, n=1, cutoff=self.cutoff)
        return match[0] if match else token

    def correct(self, tokens: list[str]) -> list[str]:
        return [self.correct_token(t) for t in tokens]


@lru_cache
def get_text_miner() -> TextMiner:
    return TextMiner()


def _demo(question: str) -> None:
    r = get_text_miner().process(question)
    print(f"Input        : {r.original}")
    print(f"Normalized   : {r.normalized}")
    print(f"Tokens       : {r.tokens}")
    print(f"No stopwords : {r.filtered_tokens}")
    print(f"Lemmas       : {r.lemmas}")
    print(f"Keywords     : {r.keywords}")


if __name__ == "__main__":
    _demo(" ".join(sys.argv[1:]) or "Hi, where can I find the registrar office in PGPC?")
