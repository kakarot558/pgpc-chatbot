"""Reading what the student typed, the way a person would.

Students type fast, on phones, and mix English with Filipino:

    "wat is the haircutt polcy"          typos
    "whats d penalty 4 cheating"         texting slang
    "pwede ba magdala ng cellphone"      Taglish
    "who is the presedent of pgpc???"    typo + punctuation

The rest of the system (intent model, TF-IDF search, handbook lookup) works with clean English words, so one
mistyped word used to mean "I couldn't find that". This module repairs the question BEFORE anything else reads it:

    1. squeeze letter floods and spacing        "pleaseeee"  -> "pleaseee" -> "please"
    2. texting slang                            "wat", "wer", "abt", "u", "d", "4"  -> normal words
    3. Filipino phrases and words               "pwede ba", "kapag", "bawal"        -> English meaning
    4. spelling repair                          "haircutt" -> "haircut", "registrer" -> "registrar"

Spelling repair is deliberately careful. A word is only changed when ALL of these hold:
  * it is not a known word (not in the 30,000-word English list, not in the PGPC handbook/records, not a Filipino
    word, not a name of an employee/office), so correct words and names are never touched;
  * a known word is only 1 edit away (2 edits for words of 9+ letters) and starts with the same letter;
  * the PGPC knowledge base wins ties, so "registrer" becomes "registrar" and not some other English word.

Pure functions (no database) except `build_vocabulary`, which only reads the already-built search index.
"""
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from app.utils.text_cleaner import clean_user_input, normalize_text, strip_accents

LEXICON_FILE = Path(__file__).resolve().parents[2] / "data" / "lexicon" / "english_common.txt"

# --------------------------------------------------------------------------- 2. texting slang
SLANG: dict[str, str] = {
    "wat": "what", "wut": "what", "whut": "what", "wht": "what", "wats": "whats", "watz": "whats", "wer": "where",
    "whr": "where", "wher": "where", "were": "were", "wen": "when", "whn": "when", "hw": "how", "hu": "who",
    "wy": "why", "abt": "about", "abut": "about", "bout": "about", "ur": "your", "dis": "this", "dat": "that",
    "da": "the", "dont": "dont", "pls": "please", "plz": "please", "plss": "please", "pleaz": "please",
    "pleas": "please", "thx": "thanks", "tnx": "thanks", "tks": "thanks", "thnx": "thanks", "thanx": "thanks",
    "cn": "can", "cud": "could", "shud": "should", "wud": "would", "wanna": "want to", "gonna": "going to",
    "gotta": "got to", "lemme": "let me", "idk": "i dont know", "rn": "right now", "bcoz": "because",
    "bc": "because", "cuz": "because", "coz": "because", "sched": "schedule", "req": "requirement",
    "reqs": "requirements", "reqt": "requirement", "reqts": "requirements", "hrs": "hours", "gebuc": "sebuc", "manguray": "mangurali", "haziel": "hazel", "nery": "nedy",
    "dept": "department", "prof": "professor", "profs": "professors", "nid": "need",
    "gud": "good", "tym": "time", "skul": "school", "cp": "cellphone", "celfone": "cellphone",
    "cellfone": "cellphone", "selpon": "cellphone", "cellphones": "cellphone", "info": "information",
    "infos": "information", "sino": "who", "tuition": "tuition", "b4": "before", "w": "with", "wo": "without",
    "msg": "message", "num": "number", "nbr": "number", "tel": "telephone",
    "adm": "admission", "enrol": "enroll", "enrolment": "enrollment", "libary": "library", "libray": "library",
    "regstrar": "registrar", "reg": "registration", "grad": "graduation", "fac": "faculty", "acad": "academic",
    "ojt": "ojt", "nstp": "nstp", "csg": "csg", "cr": "cr", "comfort": "comfort",
}
# Slang that only means something between other words ("d" = the, "4" = for), so it is left alone elsewhere.
CONTEXT_SLANG = {"d": "the", "u": "you", "r": "are", "4": "for", "2": "to", "y": "why", "n": "and", "k": "okay"}
# Slang whose spelling is itself a normal word, so it is not applied blindly.
_SLANG_SKIP = {"were", "dont", "tuition", "ojt", "nstp", "csg", "cr", "comfort", "sino", "w", "wo"}


# Contractions as they look once the apostrophe is gone ("what's" -> "whats"). Real words: never "corrected".
CONTRACTIONS = {"whos", "whats", "wheres", "whens", "hows", "whys", "thats", "theres", "heres", "lets", "its", "dont",
                "doesnt", "didnt", "cant", "couldnt", "wont", "wouldnt", "shouldnt", "isnt", "arent", "wasnt", "werent",
                "hasnt", "havent", "hadnt", "ive", "im", "youre", "youve", "theyre", "weve", "ill", "id"}


def squeeze_floods(text: str) -> str:
    """'pleaseeee' -> 'pleasee', 'haircutttt' -> 'haircutt' (3+ repeats become 2; spelling repair does the rest)
    and '???' / '!!!' collapse, so punctuation floods never reach the matcher."""
    text = re.sub(r"([a-zA-Z])\1{2,}", r"\1\1", text)
    return re.sub(r"([?!.,])\1+", r"\1", text)


def expand_slang(words: list[str]) -> tuple[list[str], list[tuple[str, str]]]:
    out, changes = [], []
    n = len(words)
    for i, w in enumerate(words):
        rep = None
        if w in SLANG and w not in _SLANG_SKIP and SLANG[w] != w:
            rep = SLANG[w]
        elif w in CONTEXT_SLANG and n > 2:
            before, after = i > 0, i < n - 1
            if w == "y":
                rep = CONTEXT_SLANG[w] if i == 0 and after else None           # "y is the clinic closed"
            elif w in {"4", "2"}:
                rep = CONTEXT_SLANG[w] if before and after else None           # "penalty 4 cheating"
            elif w == "k":
                rep = None
            elif after or w in {"u"}:
                rep = CONTEXT_SLANG[w]                                            # "d penalty", "u know", "r the faculty"
        if rep:
            changes.append((w, rep))
            out.extend(rep.split())
        else:
            out.append(w)
    return out, changes


# --------------------------------------------------------------------------- 3. Filipino phrases (before word-by-word translation)
# Longest first. Left side is matched on normalized text (lowercase, no punctuation).
PHRASES: list[tuple[str, str]] = [
    ("ano ang mangyayari kapag", "what happens if"), ("ano ang mangyayari pag", "what happens if"),
    ("anong mangyayari kapag", "what happens if"), ("ano mangyayari kapag", "what happens if"),
    ("ano ang mangyayari kung", "what happens if"), ("ano ang parusa sa", "what is the penalty for"),
    ("ano ang parusa", "what is the penalty"), ("anong parusa sa", "what is the penalty for"),
    ("ano ang patakaran sa", "what is the policy on"), ("ano ang patakaran", "what is the policy"),
    ("ano ang polisiya sa", "what is the policy on"), ("ano ang rules sa", "what are the rules on"),
    ("ano ang policy sa", "what is the policy on"), ("anong policy sa", "what is the policy on"),
    ("ano ang requirements", "what are the requirements"), ("ano ang mga requirements", "what are the requirements"),
    ("pwede ba akong", "can i"), ("puwede ba akong", "can i"), ("pwede ba ako", "can i"), ("pwede ba", "can i"),
    ("puwede ba", "can i"), ("pwede bang", "can i"), ("pwede po bang", "can i"), ("bawal ba ang", "is not allowed"),
    ("bawal ba", "is not allowed"), ("bawal ang", "not allowed"), ("bawal po ba", "is not allowed"),
    ("allowed ba", "is allowed"), ("may bayad ba", "is there a fee"), ("meron bang", "is there"),
    ("mayroon bang", "is there"), ("may bayad", "there is a fee"), ("libre ba", "is it free"),
    ("magkano ang", "how much is the"), ("magkano po ang", "how much is the"), ("ilan ang", "how many"),
    ("ilang araw", "how many days"), ("ilang beses", "how many times"), ("kailan ang", "when is the"),
    ("kelan ang", "when is the"), ("kailan po ang", "when is the"), ("saan po ang", "where is the"),
    ("saan ang", "where is the"), ("nasaan ang", "where is the"), ("nasaan po ang", "where is the"),
    ("saan makikita", "where can i find"), ("saan pwede", "where can i"), ("saan puwede", "where can i"),
    ("paano mag", "how to"), ("paano po mag", "how to"), ("paano magpa", "how to"), ("paano po", "how"),
    ("anong oras", "what time"), ("ano oras", "what time"), ("anong oras bukas", "what time open"),
    ("sino ang", "who is the"), ("sino po ang", "who is the"), ("sino si", "who is"), ("sino po si", "who is"),
    ("sino ang mga", "who are the"), ("kapag late", "if late"), ("kapag absent", "if absent"),
    ("kapag nag", "if"), ("kapag", "if"), ("pag nag", "if"), ("kung nag", "if"),
    ("nag cheat", "cheat"), ("nagcheat", "cheat"), ("nangopya", "cheat"), ("nangongopya", "cheat"),
    ("mangopya", "cheat"), ("mangongopya", "cheat"), ("nag absent", "absent"), ("nag-absent", "absent"),
    ("mag long hair", "long hair"), ("magpahaba ng buhok", "long hair"), ("magpakulay ng buhok", "colored hair"),
    ("magpa tattoo", "tattoo"), ("magpatattoo", "tattoo"), ("magpa-tattoo", "tattoo"),
    ("magdala ng", "bring"), ("magdala", "bring"), ("dalhin", "bring"), ("gamitin", "use"), ("gumamit ng", "use"),
    ("magsuot ng", "wear"), ("magsuot", "wear"), ("isuot", "wear"), ("suot", "wear"),
    ("sa klase", "in class"), ("sa loob ng klase", "in class"), ("sa school", "in school"),
    ("sa campus", "in campus"), ("sa loob ng campus", "in campus"), ("silid aralan", "classroom"),
]
_PHRASE_PATTERNS = [(re.compile(rf"\b{re.escape(k)}\b"), v) for k, v in sorted(PHRASES, key=lambda kv: -len(kv[0]))]

EXTRA_FILIPINO: dict[str, str] = {
    "klase": "class", "klasrum": "classroom", "bawal": "not allowed", "parusa": "penalty", "patakaran": "policy",
    "polisiya": "policy", "mangyayari": "happens", "mangyari": "happen", "kung": "if", "kapag": "if", "pag": "if",
    "lalaki": "male", "babae": "female", "buhok": "hair", "gupit": "haircut", "kulay": "color", "hikaw": "earring",
    "tatu": "tattoo", "tsinelas": "slippers", "sandalyas": "sandals", "sapatos": "shoes", "damit": "clothes",
    "pantalon": "pants", "palda": "skirt", "pulis": "police", "guwardiya": "guard",
    "kapitbahay": "neighbor", "teknolohiya": "technology", "pagsusulit": "exam", "eksamen": "exam",
    "marka": "grade", "bagsak": "fail", "pasado": "pass", "tanggap": "accept", "kuha": "get", "papel": "document",
    "dokumento": "document", "talaan": "record", "pangalan": "name", "numero": "number", "telepono": "phone",
    "silid": "room", "gusali": "building", "palapag": "floor", "palikuran": "restroom", "banyo": "restroom",
    "kantina": "canteen", "kainan": "canteen", "pagkain": "food", "tubig": "water", "oras": "hours",
    "araw": "days", "buwan": "month", "taon": "year", "semestre": "semester", "sem": "semester",
    "magparehistro": "register", "pagpaparehistro": "registration", "pagpapatala": "enrollment",
    "pasok": "attendance", "liban": "absent", "huli": "late", "kopya": "copy", "mangopya": "cheat",
    "kopyahin": "copy", "magnakaw": "steal", "nakaw": "theft", "suntukan": "fight", "yosi": "cigarette",
    "sigarilyo": "cigarette", "bisyo": "vice", "alak": "alcohol", "inumin": "drink", "droga": "drugs",
    "ipinagbabawal": "prohibited", "ipinapatupad": "implemented", "kailangang": "need", "dapat": "should",
    "pwedeng": "can", "pwede": "can", "puwede": "can", "ba": "", "kasi": "", "yung": "", "yun": "",
    "dito": "here", "doon": "there", "doon po": "there", "mga": "", "nyo": "", "ninyo": "", "natin": "",
    "akin": "my", "iyong": "your", "ating": "our", "ikaw": "you", "ako": "i", "kami": "we", "sila": "they",
    "walang": "no", "wala": "no", "hindi": "not", "di": "not", "huwag": "dont", "wag": "dont",
    "tanong": "question", "sagot": "answer", "salamat": "thanks", "magandang": "good", "umaga": "morning",
    "hapon": "afternoon", "gabi": "evening", "paalam": "goodbye", "kumusta": "hello", "kamusta": "hello",
    "tulong": "help", "tulungan": "help", "gawin": "do", "gagawin": "do", "ginagawa": "doing",
    "lahat": "all", "isa": "one", "dalawa": "two", "tatlo": "three",
}


# What students call things -> what the handbook calls them. Applied to every question (English too).
DOMAIN_PHRASES: list[tuple[str, str]] = [
    ("excuse letter", "excuse slip"), ("absent letter", "excuse slip"), ("excuse note", "excuse slip"),
    ("absence letter", "excuse slip"), ("letter of excuse", "excuse slip"),
    ("change course", "shifting course"), ("change my course", "shifting course"), ("change program", "shifting course"),
    ("change my program", "shifting course"), ("shift course", "shifting course"), ("shift my course", "shifting course"),
    ("shift to another course", "shifting course"), ("transfer course", "shifting course"),
    ("drop out", "withdraw"), ("dropping out", "withdraw"), ("quit school", "withdraw"),
    ("cut classes", "absences"), ("cutting classes", "absences"), ("skip class", "absences"), ("skipping class", "absences"),
    ("tuition fee", "tuition fees"), ("school fees", "tuition fees"), ("miscellaneous fee", "tuition fees"),
    ("cell phone", "cellphone"), ("mobile phone", "cellphone"), ("hair cut", "haircut"), ("id card", "id"),
    ("school id", "id"), ("student id", "id"), ("report card", "grades"), ("transcript of records", "transcript"),
    ("tor", "transcript"), ("good moral", "good moral character"), ("dean s list", "deans list"),
    ("comfort room", "cr"), ("restroom", "cr"), ("bathroom", "cr"), ("toilet", "cr"), ("c r", "cr"),
]
_DOMAIN_PATTERNS = [(re.compile(rf"\b{re.escape(k)}\b"), v) for k, v in sorted(DOMAIN_PHRASES, key=lambda kv: -len(kv[0]))]
_QUIET_DOMAIN = {"cell phone", "mobile phone", "hair cut", "id card", "tuition fee", "comfort room", "restroom",
                 "bathroom", "toilet", "c r", "school id", "student id"}      # spelling variants: no "understood as"


def apply_domain_phrases(text: str) -> tuple[str, bool]:
    """Returns (text, loud). loud=True when the wording was really changed (shown as 'Understood as')."""
    out, loud = text, False
    for pat, rep in _DOMAIN_PATTERNS:
        new = pat.sub(rep, out)
        if new != out:
            key = pat.pattern.replace("\\b", "").replace("\\ ", " ")
            loud = loud or key not in _QUIET_DOMAIN
            out = new
    return out, loud


def apply_phrases(text: str) -> tuple[str, bool]:
    """Filipino phrases -> English (on normalized text). Returns (text, changed)."""
    out = text
    for pat, rep in _PHRASE_PATTERNS:
        out = pat.sub(rep, out)
    return re.sub(r"\s+", " ", out).strip(), out != text


# --------------------------------------------------------------------------- 4. spelling repair
def osa_distance(a: str, b: str, limit: int) -> int:
    """Edit distance with swaps of neighbouring letters counted as ONE edit (so 'recieve' is 1 away from
    'receive'). Stops early and returns limit+1 when the words are further apart than `limit`."""
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    prev2, prev = None, list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        cur = [i] + [0] * len(b)
        best = cur[0]
        for j in range(1, len(b) + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                cur[j] = min(cur[j], prev2[j - 2] + 1)
            best = min(best, cur[j])
        if best > limit:
            return limit + 1
        prev2, prev = prev, cur
    return prev[-1]


@dataclass
class Vocabulary:
    english: dict[str, int] = field(default_factory=dict)       # word -> frequency rank (1 = most common)
    kb: Counter = field(default_factory=Counter)                 # words the PGPC handbook / records use
    protect: set[str] = field(default_factory=set)               # words that must never be changed
    _pool: dict[str, list[str]] = field(default_factory=dict, repr=False)

    def known(self, w: str) -> bool:
        return w in self.english or w in self.kb or w in self.protect

    def pool(self, first: str) -> list[str]:
        if not self._pool:
            for w in set(self.english) | set(self.kb):
                if len(w) >= 3:
                    self._pool.setdefault(w[0], []).append(w)
        return self._pool.get(first, [])


_WORD = re.compile(r"[a-z]{3,}")
_cached_lexicon: dict[str, int] | None = None


def load_english() -> dict[str, int]:
    global _cached_lexicon
    if _cached_lexicon is None:
        try:
            words = LEXICON_FILE.read_text(encoding="utf-8").split()
        except OSError:
            words = []
        _cached_lexicon = {w: i + 1 for i, w in enumerate(words)}
    return _cached_lexicon


def fixed_words() -> set[str]:
    """Words that are real but not in an English list: Filipino words, slang, school terms and acronyms."""
    from app.services.query_rewrite import FILIPINO_FILLER, FILIPINO_TO_ENGLISH
    # SLANG keys are NOT protected: they are rewritten before spelling repair, and a misspelling such as "libary"
    # sits among them only so that it is fixed even without a vocabulary.
    base = set(FILIPINO_TO_ENGLISH) | set(FILIPINO_FILLER) | set(EXTRA_FILIPINO) | set(CONTEXT_SLANG)
    base |= {w for v in SLANG.values() for w in v.split()}
    base |= CONTRACTIONS
    base |= {"pgpc", "osa", "saco", "nstp", "ojt", "csg", "gwa", "drp", "inc", "cosc", "bscs", "bpa", "bsma", "bscrim",
             "wifi", "cpe", "taga", "pgpcian", "garcia", "batangas", "sangguniang", "bayan", "padre", "vpaa",
             "kuya", "ate", "opac", "crim", "admin", "vpaf", "oic", "ccba", "mis", "deptac", "beced", "cr", "id", "ids", "it", "ict", "lpt", "hon", "atty", "engr", "dr", "mr", "ms", "mrs"}
    return base


def build_vocabulary(texts=(), names=()) -> Vocabulary:
    """`texts`: strings from the PGPC handbook/records. `names`: employee/office names (always protected)."""
    vocab = Vocabulary(english=load_english(), protect=fixed_words())
    for t in texts:
        for w in _WORD.findall(strip_accents(t or "").lower()):
            vocab.kb[w] += 1
    for n in names:
        for w in _WORD.findall(strip_accents(n or "").lower()):
            vocab.protect.add(w)
            vocab.kb[w] += TITLE_WEIGHT          # "registrar" (an office) must beat "register" (a common word)
    vocab._pool = {}
    return vocab


def _is_swap(a: str, b: str) -> bool:
    """True when b is a with two neighbouring letters swapped ('recieve' / 'receive')."""
    diff = [i for i in range(len(a)) if a[i] != b[i]]
    return len(diff) == 2 and diff[1] == diff[0] + 1 and a[diff[0]] == b[diff[1]] and a[diff[1]] == b[diff[0]]


TITLE_WEIGHT = 60


def max_distance(word: str) -> int:
    return 1 if len(word) < 9 else 2


def best_correction(word: str, vocab: Vocabulary) -> str | None:
    """The known word the student most likely meant, or None (leave the word alone)."""
    if len(word) < 4 or not word.isalpha() or vocab.known(word):
        return None
    limit = max_distance(word)
    best, best_key = None, None
    for cand in vocab.pool(word[0]):
        if cand == word or abs(len(cand) - len(word)) > limit:
            continue
        d = osa_distance(word, cand, limit)
        if d > limit:
            continue
        in_kb = vocab.kb.get(cand, 0)
        # "dres" is a dropped letter from "dress" (kind 0), but only a wrong letter from "does" (kind 1)
        kind = 1 if (d == 1 and len(cand) == len(word) and not _is_swap(word, cand)) else 0
        function_word = 1 if vocab.english.get(cand, 10**7) <= 300 else 0       # the, does, what ... rarely the target
        key = (d, function_word, 0 if in_kb else 1, -in_kb, kind, vocab.english.get(cand, 10**7), cand)
        if best_key is None or key < best_key:
            best, best_key = cand, key
    return best


def repair_spelling(words: list[str], vocab: Vocabulary) -> tuple[list[str], list[tuple[str, str]]]:
    out, changes = [], []
    for w in words:
        fixed = best_correction(w, vocab)
        if fixed:
            changes.append((w, fixed))
            out.append(fixed)
        else:
            out.append(w)
    return out, changes


# --------------------------------------------------------------------------- the whole reader
@dataclass
class ReadResult:
    original: str
    text: str                                  # what the rest of the system reads
    display: str | None = None                 # "I read your question as ..." (None when nothing was repaired)
    corrections: list[tuple[str, str]] = field(default_factory=list)
    filipino: bool = False
    reply_in_filipino: bool = False            # a Filipino phrase or content word, not only "po" / "ba"


def read_input(question: str, vocab: Vocabulary | None = None) -> ReadResult:
    """Repairs a question. Never raises; an unreadable question comes back unchanged."""
    original = clean_user_input(question)
    try:
        text = squeeze_floods(original)
        words = normalize_text(text).split()
        if not words:
            return ReadResult(original, original)
        words, slang_changes = expand_slang(words)
        joined = " ".join(words)
        joined, domain_loud = apply_domain_phrases(joined)
        joined, phrase_changed = apply_phrases(joined)
        from app.services.query_rewrite import FILIPINO_TO_ENGLISH, FILIPINO_FILLER
        words = joined.split()
        def _fil(w):                                           # a word that maps to itself ("librarian") is English
            return (w in FILIPINO_TO_ENGLISH and FILIPINO_TO_ENGLISH[w] != w) or (w in EXTRA_FILIPINO and EXTRA_FILIPINO[w] != w)
        filipino = phrase_changed or any(_fil(w) for w in words)
        if filipino:
            tr = []
            for w in words:
                if w in FILIPINO_FILLER and w not in FILIPINO_TO_ENGLISH and w not in EXTRA_FILIPINO:
                    continue
                rep = FILIPINO_TO_ENGLISH.get(w, EXTRA_FILIPINO.get(w, w))
                tr.extend(rep.split())
            words = tr
        spelled, spell_changes = (words, [])
        if vocab is not None:
            spelled, spell_changes = repair_spelling(words, vocab)
        result = " ".join(spelled).strip()
        corrections = slang_changes + spell_changes
        display = None
        if (corrections or domain_loud) and not filipino:
            display = result
        if not corrections and not filipino and result == " ".join(normalize_text(original).split()):
            return ReadResult(original, original)        # nothing to repair: the question is passed on untouched
        if not corrections and not filipino and not domain_loud:
            return ReadResult(original, result or original)    # quiet spelling variant ("cell phone" -> "cellphone")
        particles = {"po", "ho", "ba", "naman", "lang", "nga", "daw", "raw", "kasi", "ang", "ng", "mga", "yung", "yong",
                     "ung", "sa", "na", "mag", "nag", "pag", "mang", "ko", "mo", "namin", "natin", "ninyo", "nyo"}
        content_filipino = any(_fil(w) and w not in particles for w in normalize_text(original).split())
        return ReadResult(original, result or original, display, corrections, filipino,
                          reply_in_filipino=phrase_changed or content_filipino)
    except Exception:                                    # a reader must never break a question
        return ReadResult(original, original)


# --------------------------------------------------------------------------- knowledge-base vocabulary (database part)
_vocab_cache: dict = {"id": None, "vocab": None}


def get_vocabulary(db) -> Vocabulary:
    """Words of the PGPC knowledge base, rebuilt whenever the search index is rebuilt (admin edits, new uploads)."""
    from app.services.retrieval import get_index
    index = get_index(db)
    if _vocab_cache["id"] is not index:
        texts = [f"{r.title} {r.content}" for r in index.records]
        names = [r.title for r in index.records if r.source_type in ("employee", "office", "facility", "room")]
        _vocab_cache["vocab"] = build_vocabulary(texts, names)
        _vocab_cache["id"] = index
    return _vocab_cache["vocab"]
