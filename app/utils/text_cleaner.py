"""Steps 1-3 of the text-mining pipeline: lowercase, remove punctuation, normalize whitespace.

The SAME function is used on user questions and on knowledge-base text, so both sides always
look alike (that is what makes TF-IDF matching work).
"""
import re
import unicodedata

# Different ways people write the school name all become one token: "pgpc".
_ALIASES = [
    (re.compile(r"\bpadre garcia polytechnic college\b"), "pgpc"),
    (re.compile(r"\bp g p c\b"), "pgpc"),          # "P.G.P.C." after punctuation is removed
]


def clean_user_input(text) -> str:
    """Safe cleanup of raw user input: drops control characters and collapses whitespace.
    Does NOT lowercase or cut the text, so the original wording can still be shown or logged."""
    if not isinstance(text, str):
        return ""
    kept = [" " if unicodedata.category(ch) in ("Cc", "Cf") else ch for ch in text]
    return re.sub(r"\s+", " ", "".join(kept)).strip()


def strip_accents(text: str) -> str:
    """'Viñas' -> 'Vinas', so a name typed without accents still matches."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def normalize_text(text) -> str:
    """lowercase -> strip accents -> drop possessives/apostrophes -> punctuation to spaces
    -> collapse whitespace -> unify school-name aliases.

    Example: "Hi, where can I find the Registrar's office in P.G.P.C.?"
          -> "hi where can i find the registrar office in pgpc"
    """
    text = clean_user_input(text).lower()
    text = strip_accents(text)
    text = re.sub(r"['’`]s\b", "", text)      # registrar's -> registrar
    text = re.sub(r"['’`]", "", text)         # don't -> dont
    text = re.sub(r"[^a-z0-9]+", " ", text)   # every other symbol (. , ? - / ( ) ...) becomes a space
    text = re.sub(r"\s+", " ", text).strip()
    for pattern, replacement in _ALIASES:
        text = pattern.sub(replacement, text)
    return text
