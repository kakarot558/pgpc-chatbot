"""Phase 9: simple follow-up questions.

    "Where is the registrar office?"   -> topic = Office of the Registrar
    "What about its hours?"            -> rewritten to "what are the hours of Office of the Registrar"

No language model: a follow-up is spotted by simple cues, then the question is rewritten with the name of the
record the previous answer was about. The rewritten question goes through the normal pipeline, so the answer
still comes only from stored PGPC records.

Two kinds of cue:
  pronoun - the question points back with "it / its / they / their / he / she / his / her" (or "there" after
            "at / in / to ...").  Always about the previous topic.
  weak    - "what about ...", "how about ...", "and ...", or a very short detail request ("contact number?").
            The question may also name a NEW record ("what about the library?"). The caller checks that first.

This module has no database or web imports, so it is easy to test.
"""
import re
from dataclasses import dataclass

from app.utils.text_cleaner import normalize_text

PRONOUNS = {"it", "its", "they", "their", "theirs", "them", "he", "she", "his", "her", "hers"}
THERE_AFTER = {"at", "in", "to", "from", "near", "inside"}   # "close there"; NOT "is there a clinic"
WEAK_LEADS = ("what about", "how about", "and what about", "and how about", "what else about", "and", "also")

LOCATION_WORDS = {"where", "located", "location", "directions", "building", "floor", "room"}
CONTACT_WORDS = {"contact", "phone", "telephone", "number", "email", "mail", "call", "reach", "hotline"}
HOURS_WORDS = {"hours", "hour", "open", "opens", "close", "closes", "schedule", "time", "when"}
EXTRA_DETAIL_WORDS = {"details", "detail", "info", "information", "services", "service", "head", "position"}
# Short follow-ups about a POLICY topic: "what are the sanctions?", "and the penalty?", "any exceptions?"
POLICY_DETAIL_WORDS = {"sanction", "sanctions", "penalty", "penalties", "punishment", "punishments", "rule", "rules",
                       "policy", "policies", "requirement", "requirements", "procedure", "procedures", "exception",
                       "exceptions", "consequence", "consequences", "offense", "offenses", "violation", "violations"}
DETAIL_WORDS = LOCATION_WORDS | CONTACT_WORDS | HOURS_WORDS | EXTRA_DETAIL_WORDS
FILLER = {"the", "a", "an", "of", "is", "are", "what", "whats", "and", "also", "about", "how", "then", "please",
          "do", "does", "can", "i", "you", "me", "tell", "give", "show", "its", "it"}

# Intents that never use the previous topic (small talk, off-topic).
NO_FOLLOWUP_INTENTS = {"greeting", "thanks", "goodbye", "bot_info", "out_of_scope"}
# What a "topic" can be. FAQs, history and library notes are skipped: their titles are whole sentences.
TOPIC_TYPES = {"employee", "position", "office", "room", "facility", "library", "handbook"}
ENTITY_TYPES = TOPIC_TYPES - {"handbook"}
MAX_TOPIC_TITLE = 120

MISS_TEXT = ("I couldn't find that detail about {title}. It may not have been added yet, so please check with the "
             "concerned PGPC office. You can also ask me a new question.")


@dataclass
class Topic:
    type: str
    id: int | None
    title: str


# --------------------------------------------------------------------------- cue detection
def _has_pronoun(tokens: list[str]) -> bool:
    for i, w in enumerate(tokens):
        if w in PRONOUNS:
            return True
        if w == "there" and i > 0 and tokens[i - 1] in THERE_AFTER:
            return True
    return False


def detect_cue(question: str, topic_type: str | None = None) -> str:
    """Returns "pronoun", "weak" or "none". For a handbook topic, "what are the sanctions?" is also a follow-up."""
    text = normalize_text(question)
    tokens = text.split()
    if not tokens:
        return "none"
    if _has_pronoun(tokens):
        return "pronoun"
    if any(text == lead or text.startswith(lead + " ") for lead in WEAK_LEADS):
        return "weak"
    content = [w for w in tokens if w not in FILLER]
    allowed = DETAIL_WORDS | (POLICY_DETAIL_WORDS if topic_type == "handbook" else set())
    if len(tokens) <= 5 and content and all(w in allowed for w in content):
        return "weak"
    return "none"


def new_subject(question: str) -> str | None:
    """'what about the dress code' -> 'the dress code'. None when nothing new is named ('what about its hours',
    'and the sanctions'), so the question leans on the previous topic."""
    text = re.sub(r"\s+", " ", question).strip().rstrip("?!. ")
    low = text.lower()
    for lead in sorted(WEAK_LEADS, key=len, reverse=True):
        if low == lead or low.startswith(lead + " "):
            text = text[len(lead):].strip()
            break
    words = [w for w in normalize_text(text).split() if w not in FILLER and w not in {"for", "on", "in", "to"}]
    if not words or any(w in DETAIL_WORDS or w in POLICY_DETAIL_WORDS or w in PRONOUNS for w in words):
        return None
    return text or None


def detail_kind(question: str) -> str | None:
    words = set(normalize_text(question).split())
    if words & LOCATION_WORDS:
        return "location"
    if words & CONTACT_WORDS:
        return "contact"
    if words & HOURS_WORDS:
        return "hours"
    return None


# --------------------------------------------------------------------------- rewriting
def rewrite(question: str, topic: Topic, cue: str | None = None) -> str:
    """Puts the topic's name into the question. Returns the rewritten question."""
    title = topic.title.strip()
    cue = cue or detect_cue(question)
    kind = detail_kind(question)
    # A plain request for one detail becomes a clean, complete question.
    if kind == "location":
        return f"where is {title}"
    if kind == "hours":
        return f"what are the hours of {title}"
    if kind == "contact":
        words = set(normalize_text(question).split())
        if topic.type == "employee" and words & {"email", "mail", "emails"} \
                and not words & {"number", "phone", "telephone", "call", "hotline"}:
            return f"what is the email of {title}"          # "what is his email" asks for the email, not the number
        return f"what is the contact number of {title}"

    text = re.sub(r"\s+", " ", question).strip().rstrip("?!. ")
    if cue == "pronoun":
        pattern = r"\b(" + "|".join(sorted(PRONOUNS, key=len, reverse=True)) + r")\b"
        text, n = re.subn(pattern, title, text, flags=re.IGNORECASE)
        if n == 0:   # "there" after a preposition
            text = re.sub(r"\bthere\b", title, text, flags=re.IGNORECASE)
        return text
    # weak cue: drop the lead-in words and attach the topic
    low = text.lower()
    for lead in sorted(WEAK_LEADS, key=len, reverse=True):
        if low == lead or low.startswith(lead + " "):
            text = text[len(lead):].strip()
            break
    if topic.type == "handbook":
        text = re.sub(r"^(?:(?:what|which)\s+(?:is|are)\s+)?(?:the\s+|a\s+|an\s+)?", "", text, flags=re.I)
        return f"{text} for {title}".strip()
    return f"{text} {title}".strip()


# --------------------------------------------------------------------------- the decision
def answer_with_context(question, topic, answer_fn, classify, miss_fn):
    """Answers `question`, using the previous `topic` when the question is a follow-up.

    answer_fn(q)   -> an Answer (see answer_generator).      classify(q) -> intent name.
    miss_fn(text)  -> an Answer that says "not found" with `text`.
    Returns (answer, interpreted_as). interpreted_as is the rewritten question, or None when the question
    was answered as it stands."""
    if topic is None or topic.type not in TOPIC_TYPES or not topic.title or len(topic.title) > MAX_TOPIC_TITLE:
        return answer_fn(question), None
    cue = detect_cue(question, topic.type)
    if cue == "none" or classify(question) in NO_FOLLOWUP_INTENTS:
        return answer_fn(question), None

    # "what about the dress code?" / "how about tattoo?" names a NEW subject: answer that, not the old topic
    if cue == "weak" and topic.type == "handbook":
        subject = new_subject(question)
        if subject:
            return answer_fn(subject), (subject if subject.lower() != question.strip().lower() else None)

    def about_topic(ans) -> bool:
        """A rewritten question must end up on the same record, otherwise it drifted to something else."""
        if not ans.found:
            return False
        if topic.type not in ENTITY_TYPES:
            return True
        return any(s.get("type") == topic.type and s.get("id") == topic.id for s in ans.sources)

    rewritten = rewrite(question, topic, cue)

    if cue == "weak":
        # "What about the library?" names its own record: keep it. Otherwise lean on the topic.
        own = answer_fn(question)
        if own.found and own.kind in ("answer", "list") and own.sources \
                and own.sources[0].get("type") in ENTITY_TYPES:
            return own, None
        follow = answer_fn(rewritten)
        return (follow, rewritten) if about_topic(follow) else (own, None)

    # pronoun: this is about the previous topic, never about another office, person or facility
    follow = answer_fn(rewritten)
    if about_topic(follow):
        return follow, rewritten
    # "Is it okay to be late?" has an "it" but is a handbook question. If the question on its own lands on
    # a handbook/FAQ-type record (not a person, office or room), answer it as it stands.
    own = answer_fn(question)
    if own.found and own.sources and own.sources[0].get("type") not in ENTITY_TYPES:
        return own, None
    return miss_fn(MISS_TEXT.format(title=topic.title)), rewritten
