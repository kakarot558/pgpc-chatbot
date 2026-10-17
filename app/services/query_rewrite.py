"""Understanding more kinds of questions, before intent classification and retrieval.

  1. Taglish / Filipino:  "Saan po ang registrar office?"  ->  "where registrar office"
     The intent model and the knowledge base are English, so common Filipino question words and school words
     are turned into their English meaning first. An English question is returned unchanged.
  2. Several questions in one message:  "Where is the clinic? What are its hours?"  ->  two questions,
     each answered on its own.

Pure functions, no database and no NLTK, so they are easy to test. Add words to the dictionaries below as you
see real questions in the chat logs (admin page -> chat logs).
"""
import re

from app.utils.text_cleaner import normalize_text

# Filipino word -> English meaning. Only words that are NOT normal English words belong here.
FILIPINO_TO_ENGLISH: dict[str, str] = {
    "saan": "where", "nasaan": "where", "asaan": "where", "sino": "who", "ano": "what", "anong": "what",
    "alin": "which", "kailan": "when", "magkano": "how much", "ilan": "how many", "paano": "how", "pano": "how",
    "bakit": "why", "meron": "is there", "mayroon": "is there", "merong": "is there", "pwede": "can",
    "puwede": "can", "kailangan": "need", "bayad": "fee", "matrikula": "tuition", "multa": "fine",
    "oras": "hours", "bukas": "open", "sarado": "closed", "libro": "book", "aklatan": "library",
    "silid-aralan": "classroom", "guro": "teacher", "titser": "teacher", "estudyante": "student",
    "mag-aaral": "student", "paaralan": "school", "hiram": "borrow", "manghiram": "borrow", "humiram": "borrow", "hiramin": "borrow", "manghihiram": "borrow",
    "ibalik": "return", "uniporme": "uniform", "pasok": "attendance", "pumasok": "attend",
    "magpa-enroll": "enroll", "magenroll": "enroll", "enrol": "enroll", "klinika": "clinic",
    "dekano": "dean", "magbayad": "pay", "bayaran": "pay", "kopya": "copy", "sertipiko": "certificate",
    "grado": "grade", "iskolarship": "scholarship", "libre": "free", "kelan": "when", "san": "where",
    "nasan": "where", "sinong": "who", "gaano": "how", "ilang": "how many", "anu": "what", "pagtatapos": "graduation",
    "presidente": "president", "alkalde": "mayor", "guwardiya": "guard", "gwardya": "guard", "tagalinis": "janitor",
    "librarian": "librarian", "punong": "head", "gupit": "haircut", "buhok": "hair", "kuha": "get", "tanggapan": "office", "numero": "number", "telepono": "phone",
}
# Filipino filler words that carry no meaning for searching.
FILIPINO_FILLER = {"po", "ho", "ba", "naman", "lang", "nga", "daw", "raw", "kasi", "ang", "ng", "mga", "yung",
                   "yong", "ung", "sa", "na", "mag", "nag", "pag", "mang", "ko", "mo", "namin", "natin", "ninyo", "nyo"}

MAX_SUB_QUESTIONS = 3
MIN_WORDS_PER_SUB_QUESTION = 3


def to_english(question: str) -> str:
    """Returns the question with Filipino words translated. If the question has no Filipino marker word it is
    returned exactly as it came in (so English questions are never touched)."""
    words = normalize_text(question).replace("silid aralan", "silid-aralan").split()
    if not any(w in FILIPINO_TO_ENGLISH for w in words):
        return question
    out = []
    for w in words:
        if w in FILIPINO_FILLER:
            continue
        out.append(FILIPINO_TO_ENGLISH.get(w, w))
    return " ".join(out)


def split_questions(message: str) -> list[str]:
    """Splits "Q1? Q2?" into separate questions. It only splits when EVERY part is a real question of at
    least MIN_WORDS_PER_SUB_QUESTION words, so short follow-ups such as "contact number?" stay whole."""
    parts = [p.strip() for p in re.split(r"(?<=\?)\s+", (message or "").strip()) if p.strip()]
    if len(parts) < 2 or len(parts) > MAX_SUB_QUESTIONS:
        return _split_on_conjunction(message)
    if any(len(normalize_text(p).split()) < MIN_WORDS_PER_SUB_QUESTION for p in parts):
        return [message]
    return parts


QUESTION_STARTERS = {"who", "whos", "what", "whats", "where", "when", "how", "why", "which", "can", "may", "is", "are",
                     "do", "does", "did", "will", "should", "saan", "sino", "ano", "anong", "kailan", "paano",
                     "magkano", "ilan", "pwede", "meron", "nasaan", "tell", "show", "give"}
PRONOUNS = {"it", "its", "this", "that", "there", "their", "them", "these", "those", "he", "she", "his", "her"}
CONJUNCTIONS = r"\s*(?:;|,|\band\b|\bat\b|\btapos\b|\bsaka\b|\bthen\b|\balso\b|\bplus\b)\s+(?=(?:{starters})\b)"


def _split_on_conjunction(message: str) -> list[str]:
    """'who is the mayor and who is the president' -> two questions. Only when every part starts with a question
    word and is long enough, and no later part leans on the first with 'it/its/there' (that stays one question)."""
    text = (message or "").strip().rstrip("?.! ")
    pattern = re.compile(CONJUNCTIONS.format(starters="|".join(sorted(QUESTION_STARTERS))), re.I)
    parts = [p.strip(" ,;") for p in pattern.split(text) if p and p.strip(" ,;")]
    if len(parts) < 2 or len(parts) > MAX_SUB_QUESTIONS:
        return [message]
    for i, part in enumerate(parts):
        words = normalize_text(part).split()
        if len(words) < MIN_WORDS_PER_SUB_QUESTION or words[0] not in QUESTION_STARTERS:
            return [message]
        if i > 0 and set(words) & PRONOUNS:
            return [message]
    return [p + "?" for p in parts]


# --------------------------------------------------------------------------- broad "what are the policies?" questions
OVERVIEW_TRIGGERS = {"policy", "policies", "rule", "rules", "regulation", "regulations", "guideline", "guidelines",
                     "handbook", "topics", "topic", "cover", "covers", "covered", "contain", "contains", "overview",
                     "summary"}
OVERVIEW_FILLER = {"what", "are", "is", "the", "in", "of", "at", "a", "an", "all", "any", "some", "list", "show", "me",
                   "tell", "give", "about", "can", "you", "please", "pls", "there", "do", "does", "have", "has", "say",
                   "says", "college", "school", "pgpc", "student", "students", "general", "main", "key", "important",
                   "available", "and", "to", "know", "for", "which", "its", "their", "our", "my", "i", "need", "want",
                   "see", "view", "read", "explain", "include", "included", "many", "how", "with", "on", "ones"}


def is_overview(question: str) -> bool:
    """True for broad questions that name no specific topic: "what are the policies in PGPC", "what does the
    handbook cover". Such a question has no single best passage, so the answer is a list of what the handbook has."""
    words = normalize_text(question).split()
    return bool(words) and any(w in OVERVIEW_TRIGGERS for w in words) \
        and all(w in OVERVIEW_TRIGGERS or w in OVERVIEW_FILLER for w in words)
