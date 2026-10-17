"""Questions that PGPC answers with an official link.

"How do I enroll?" is not something the handbook answers well (it has a few numbered steps of the old paper
procedure). PGPC enrolls online, so the answer is the official link. The link is a setting (ENROLLMENT_URL in .env),
so it can change without touching the code; an empty value turns this feature off.

Pure functions, no database.
"""
import re

from app.utils.text_cleaner import normalize_text

ENROLL_RE = re.compile(r"\b(?:enrol\w*|pre\s?enrol\w*|inrol\w*|enrool\w*)\b")
# Questions about money, rules or penalties are NOT "how do I enroll": the normal handbook answer is better.
OTHER_TOPIC_WORDS = {"policy", "policies", "penalty", "penalties", "sanction", "sanctions", "fee", "fees", "tuition",
                     "cost", "price", "much", "magkano", "payment", "pay", "refund", "discount", "late", "deadline",
                     "schedule", "date", "dates", "when", "kailan", "kelan", "who", "dean", "list", "total", "many",
                     "number", "statistics", "cancel", "cancellation", "unenroll"}
REQUIREMENT_WORDS = {"requirement", "requirements", "document", "documents", "needed", "need", "needs", "bring",
                     "papers", "paper", "credentials", "checklist"}


def enrollment_mode(question: str) -> str | None:
    """'how'          - how / where / steps / online / link / just "enroll": the answer is the link.
    'requirements' - what to bring: the handbook answer stays, the link is added to it.
    None           - not an enrollment how-to (fees, policy, schedule ...)."""
    text = normalize_text(question)
    if not ENROLL_RE.search(text):
        return None
    words = set(text.split())
    if words & OTHER_TOPIC_WORDS:
        return None
    if words & REQUIREMENT_WORDS:
        return "requirements"
    return "how"


def enrollment_link_answer(url: str) -> str:
    return (f"You can enroll online through the official PGPC enrollment link:\n{url}\n\n"
            "Open the link to start your enrollment. For the requirements listed in the Student Handbook, "
            'you can ask me: "What are the requirements for enrollment?"\n\n'
            "Source: PGPC online enrollment")


def add_link_to_answer(text: str, url: str) -> str:
    """Adds 'To enroll online: <url>' before the answer's Source line (the chat shows the Source line last)."""
    line = f"To enroll online, use the official PGPC enrollment link:\n{url}"
    cut = text.rfind("\n\nSource: ")
    if cut == -1:
        return f"{text}\n\n{line}"
    return f"{text[:cut]}\n\n{line}{text[cut:]}"


# --------------------------------------------------------------------------- links the admin manages (database)
URL_OK = re.compile(r"^https?://[^\s<>\"']+$", re.I)


def valid_url(url: str) -> bool:
    return bool(URL_OK.match((url or "").strip()))


def _stem(w: str) -> str:
    return w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w


def clean_keywords(text: str) -> list[list[str]]:
    """'scholarship application, apply scholarship' -> [['scholarship','application'], ['apply','scholarship']]."""
    phrases = []
    for chunk in re.split(r"[,;\n]+", text or ""):
        words = [_stem(w) for w in normalize_text(chunk).split() if w]
        if words:
            phrases.append(words)
    return phrases


def match_link(question: str, links):
    """The active link whose keyword phrase has ALL its words in the question; the longest phrase wins."""
    words = {_stem(w) for w in normalize_text(question).split()}
    best, best_len = None, 0
    for link in links:
        if not getattr(link, "is_active", True):
            continue
        for phrase in clean_keywords(link.keywords):
            if set(phrase) <= words and len(phrase) > best_len:
                best, best_len = link, len(phrase)
    return best


def link_answer_text(link) -> str:
    lead = (link.message or "").strip() or f"Here is the official link for {link.title}:"
    return f"{lead}\n{link.url.strip()}\n\nSource: PGPC quick links"


def find_link(db, question: str):
    from sqlalchemy import select
    from app.models import QuickLink
    links = list(db.scalars(select(QuickLink).where(QuickLink.is_active.is_(True))))
    return match_link(question, links) if links else None
