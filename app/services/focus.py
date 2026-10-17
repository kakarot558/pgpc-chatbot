"""Answer focusing: from a long passage, pick the sentence(s) that actually answer the question.

Without this, a question like "how many books can a student borrow" returns the whole 700-character passage and
the student has to find the answer inside it. Here the passage is cut into sentences / list items, every unit is
scored against the question, and only the best unit(s) are returned (plus the lead-in line of a list).

No heavy imports on purpose: the lemmatizer is passed in, so this file can be tested without NLTK or a database.
"""
import math
import re
from typing import Callable, Iterable

MIN_CHARS_TO_FOCUS = 400      # short passages are shown in full
MAX_UNITS = 3                 # at most this many matching sentences are shown
RELATIVE_KEEP = 0.7           # a unit is also shown when it scores >= 70% of the best unit
MIN_SHARE = 0.4               # the best unit must carry >= 40% of everything the question matched in the passage
MAX_LIST_ITEMS = 4
MAX_PROCEDURE_ITEMS = 12      # a "how do I ..." question gets the whole numbered procedure, up to this many steps

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"“(])")
_ABBREVIATION = re.compile(r"\b(Dr|Mr|Mrs|Ms|Prof|Sr|Jr|No|Nos|Sec|Art|Inc|vs|etc|Engr|Atty)\.$")
_MARKER_ONLY = re.compile(r"^(\d+(\.\d+)*[.)]|[A-Za-z][.)])$")      # "1." or "a." left alone on a line
_LIST_START = re.compile(r"^(\d+(\.\d+)*[.)]\s|\(?[a-zA-Z0-9]{1,2}\)\s|[-•]\s)")

Lemmatizer = Callable[[str], Iterable[str]]


def split_units(text: str) -> list[str]:
    """Sentences and list items, in order. Expects text where wrapped lines are already joined."""
    units: list[str] = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        pieces = _SENTENCE_END.split(line)
        merged: list[str] = []
        for piece in pieces:
            if merged and (_ABBREVIATION.search(merged[-1]) or _MARKER_ONLY.match(merged[-1])):
                merged[-1] += " " + piece          # "Dr. Cruz" / "1. Item": not a sentence break
            else:
                merged.append(piece)
        units.extend(p.strip() for p in merged if p.strip())
    return units


def _groups(question_lemmas: Iterable[str], synonyms: dict[str, list[str]]) -> list[set[str]]:
    seen, groups = set(), []
    for term in question_lemmas:
        if term in seen:
            continue
        seen.add(term)
        groups.append({term, *synonyms.get(term, [])})
    return groups


def focus(text: str, question: str, lemmas: Lemmatizer, synonyms: dict[str, list[str]] | None = None,
          whole_list: bool = False) -> tuple[str, bool] | None:
    """Returns (focused_text, True) or None when the passage should be shown as it is
    (short passage, no clear best sentence, or nothing in the question matches)."""
    if len(text or "") < MIN_CHARS_TO_FOCUS:
        return None
    units = split_units(text)
    if len(units) < 3:
        return None
    groups = _groups(lemmas(question), synonyms or {})
    if not groups:
        return None

    unit_terms = [set(lemmas(u)) for u in units]
    n = len(units)
    weights = []                                   # (group, weight) for groups found somewhere in the passage
    for g in groups:
        df = sum(1 for terms in unit_terms if terms & g)
        if df:
            weights.append((g, math.log(1 + n / df)))
    if not weights:
        return None
    total = sum(w for _, w in weights)
    scores = [sum(w for g, w in weights if terms & g) for terms in unit_terms]
    best = max(range(n), key=lambda i: (scores[i], -i))      # ties: earliest sentence
    if scores[best] <= 0 or scores[best] < MIN_SHARE * total:
        return None

    chosen = {best}
    extra = sorted((i for i in range(n) if i != best and scores[i] >= RELATIVE_KEEP * scores[best] > 0),
                   key=lambda i: (-scores[i], i))
    for i in extra[:MAX_UNITS - 1]:
        chosen.add(i)
    if whole_list and _LIST_START.match(units[best]):
        # "How do I enroll?" needs every step, not just the step that mentions the word.
        a = best
        while a > 0 and _LIST_START.match(units[a - 1]):
            a -= 1
        b = best
        while b + 1 < n and _LIST_START.match(units[b + 1]) and b - a < MAX_PROCEDURE_ITEMS:
            b += 1
        chosen.update(range(a, b + 1))
        if a > 0 and len(units[a - 1]) < 70 and not units[a - 1].rstrip().endswith("."):
            chosen.add(a - 1)                       # a short heading such as "For Old Students:"
    # A list item needs its lead-in ("The penalties are:"), and a lead-in needs its items.
    for i in list(chosen):
        if _LIST_START.match(units[i]):
            j = i - 1
            while j >= 0 and _LIST_START.match(units[j]):
                j -= 1
            if j >= 0 and units[j].rstrip().endswith(":"):
                chosen.add(j)
        if units[i].rstrip().endswith(":"):
            for j in range(i + 1, min(n, i + 1 + MAX_LIST_ITEMS)):
                if not _LIST_START.match(units[j]):
                    break
                chosen.add(j)

    if len(chosen) >= n:
        return None
    out = ""
    for i in sorted(chosen):
        sep = "" if not out else ("\n" if _LIST_START.match(units[i]) or out.endswith(":") else " ")
        out += sep + units[i]
    return out, True
