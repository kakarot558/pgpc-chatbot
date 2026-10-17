"""Phase 7: knowledge retrieval.

Finds the PGPC records that best match a question. It does NOT write the answer (app/services/answer_generator.py, Phase 8, does).

    question -> text mining (Phase 5) -> TF-IDF similarity against every searchable record
             -> intent-aware weighting (Phase 6) -> ranked hits with a confidence level

Searched sources: employees, positions, offices, rooms, facilities, handbook sections, school history,
ACTIVE faqs, library books and chunks of ACTIVE uploaded documents. Inactive FAQs and archived
documents are never searched.

Honesty rules built in:
  * "[ADMIN: ...]" placeholders are removed from the searchable text and from the content, and the hit
    is flagged `incomplete=True`, so Phase 8 can say "that detail has not been added yet" instead of guessing.
  * Scores below SIMILARITY_THRESHOLD give `found=False`: the chatbot must say it has no information.

Try it:  python -m app.services.retrieval "Where is the registrar office?"
"""
import logging
import re
import sys
import threading
from dataclasses import dataclass, field

import numpy as np
from scipy import sparse
from sklearn.feature_extraction.text import TfidfVectorizer
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (FAQ, Document, Employee, Facility, HandbookSection, KnowledgeChunk, LibraryBook, Office,
                        Position, Room, SchoolHistory)
from app.services.synonyms import SYNONYMS
from app.services.text_mining import ProcessedText, SpellingCorrector, TextMiner, get_text_miner

logger = logging.getLogger("pgpc.retrieval")

PLACEHOLDER_RE = re.compile(r"\[ADMIN:[^\]]*\]")

# Which sources answer which intent. Sources listed here get full weight, all others are down-weighted
# (not removed) because the classifier can be wrong.
INTENT_SOURCES: dict[str, set[str]] = {
    "employee_info": {"employee", "position"},
    "office_location": {"office", "employee", "facility", "document"},
    "room_location": {"room", "facility", "office", "document"},
    "facility_info": {"facility", "room", "document"},
    "handbook_policy": {"handbook", "document", "faq"},
    "school_history": {"history", "handbook", "faq", "document"},
    "enrollment_info": {"faq", "handbook", "document"},
    "library_info": {"library", "handbook", "faq", "document"},
    "faq_general": {"faq", "handbook", "document"},
    "contact_info": {"office", "employee", "faq", "history", "document"},
}
OFF_INTENT_WEIGHT = 0.75
# "Where is X / who is X" must be answered by the matching record, not by a handbook paragraph that merely
# mentions the word. For these intents other sources are down-weighted much harder.
ENTITY_INTENTS = {"employee_info", "office_location", "room_location", "facility_info", "library_info", "contact_info"}
ENTITY_OFF_INTENT_WEIGHT = 0.5
# Records that name a single thing (a person, an office, a room...). A question must match something more
# specific than these generic words, otherwise "where is the guidance office" would return the registrar's
# office just because both contain the word "office".
ENTITY_TYPES = {"employee", "position", "office", "room", "facility", "library"}
GENERIC_TERMS = {"office", "room", "building", "floor", "facility", "department", "pgpc",
                 "college", "campus", "school", "located", "location", "list", "name", "number", "many",
                 "available", "information", "info", "detail", "type", "kind"}
GENERIC_PENALTY = 0.4
NO_SEARCH_INTENTS = {"greeting", "thanks", "goodbye", "bot_info", "out_of_scope"}


@dataclass
class Record:
    source_type: str
    source_id: int
    title: str
    content: str                 # clean text the answer will be built from
    tokens: list[str]            # lemmas used for TF-IDF
    source: str                  # human-readable origin, shown to the user
    fields: dict = field(default_factory=dict)
    incomplete: bool = False     # True when an [ADMIN: ...] placeholder was stripped out


@dataclass
class Hit:
    source_type: str
    source_id: int
    title: str
    content: str
    source: str
    score: float                 # final score 0..1 (after intent weighting)
    cosine: float
    coverage: float
    matched_terms: list[str]
    incomplete: bool
    fields: dict

    def as_dict(self, snippet_chars: int = 300) -> dict:
        d = {k: getattr(self, k) for k in ("source_type", "source_id", "title", "source", "score", "cosine",
                                           "coverage", "matched_terms", "incomplete", "fields")}
        d["snippet"] = self.content if len(self.content) <= snippet_chars else self.content[:snippet_chars].rstrip() + "..."
        return d


@dataclass
class RetrievalResult:
    question: str
    keywords: list[str]
    intent: str | None
    hits: list[Hit]
    found: bool                  # best hit reached SIMILARITY_THRESHOLD
    confidence: str              # "high" | "medium" | "low" | "none"
    total_matches: int           # how many records reached the threshold (e.g. "list of faculty")
    preferred_sources: list[str]

    @property
    def best(self) -> Hit | None:
        return self.hits[0] if self.hits else None


PASSAGE_MIN, PASSAGE_MAX = 350, 900
# The PDF text sometimes runs several handbook sections together ("4. Section B - Pre-Enrollment Requirements and
# Procedure" sits inside Section A's text). A heading line inside a passage becomes that passage's real title.
HEADING_RE = re.compile(r"^\s*(?:\d+\.\s*)?(Section\s+[A-Z][\w]*\s*[-\u2013:.]\s*\S.{3,110})$", re.MULTILINE)


def find_heading(text: str) -> str | None:
    m = HEADING_RE.search(text or "")
    return " ".join(m.group(1).split()).rstrip(" .") if m else None


def split_passages(text: str) -> list[str]:
    """Cut long text into passages of about PASSAGE_MIN..PASSAGE_MAX characters along paragraph/line breaks."""
    text = (text or "").strip()
    if len(text) <= PASSAGE_MAX:
        return [text] if text else []
    units = []
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        if len(para) <= PASSAGE_MAX:
            units.append(para)
        else:  # one huge paragraph: cut at line ends, then at spaces
            buf = ""
            for line in para.split("\n"):
                if buf and len(buf) + len(line) > PASSAGE_MAX:
                    units.append(buf.strip())
                    buf = ""
                while len(line) > PASSAGE_MAX:
                    cut = line.rfind(" ", 0, PASSAGE_MAX) or PASSAGE_MAX
                    units.append((buf + " " + line[:cut]).strip())
                    buf, line = "", line[cut:].strip()
                buf += line + "\n"
            if buf.strip():
                units.append(buf.strip())
    passages, cur = [], ""
    for u in units:
        if cur and (len(cur) >= PASSAGE_MIN or len(cur) + len(u) > PASSAGE_MAX):
            passages.append(cur.strip())
            cur = ""
        cur += u + "\n\n"
    if cur.strip():
        passages.append(cur.strip())
    return passages


# ----------------------------------------------------------------------------- record builders
def clean_value(value) -> tuple[str, bool]:
    """Returns (text without placeholders, whether a placeholder was present)."""
    if value is None:
        return "", False
    text = str(value)
    had = bool(PLACEHOLDER_RE.search(text))
    text = PLACEHOLDER_RE.sub("", text)
    return re.sub(r"\s+", " ", text).strip(" .:-"), had


def _join(*parts) -> str:
    return " ".join(p for p in parts if p)


def _labelled(pairs) -> str:
    return ". ".join(f"{k}: {v}" for k, v in pairs if v)


def finish_sentence(passage: str, following: str, limit: int = 260) -> str:
    """A passage can end in the middle of a sentence ('... the school shall' | 'automatically DROP the student').
    The text SHOWN to the student borrows the rest of that sentence from the next passage; the words used for
    searching stay exactly as they were."""
    text = (passage or "").rstrip()
    if not text or not following or text.endswith((".", "!", "?", ":", ";", '"')):
        return passage
    nxt = " ".join(following.split())
    m = re.search(r"[.!?](?:\s|$)", nxt[:limit])
    if not m:
        return passage                                      # no sentence end close by: do not guess
    return text + " " + nxt[: m.end()].strip()


class Indexer:
    def __init__(self, miner: TextMiner):
        self.miner = miner

    def toks(self, text: str, weight: int = 1) -> list[str]:
        return self.miner.process(text).lemmas * weight

    def employees(self, db: Session) -> list[Record]:
        out = []
        for e in db.scalars(select(Employee)):
            first, f_bad = clean_value(e.first_name)
            last, _ = clean_value(e.last_name)
            middle, _ = clean_value(e.middle_name)
            name = _join(first, middle, last)
            position, _ = clean_value(e.position.name if e.position else None)
            office, _ = clean_value(e.office.name if e.office else None)
            note_m = re.search(r"Roster note:\s*\(([^)]*)\)", e.description or "", re.I)
            note = note_m.group(1).strip().title() if note_m else ""
            desc, d_bad = clean_value(e.description)
            if d_bad:
                desc = ""    # seeded roster boilerplate; not real information
            incomplete = f_bad or d_bad or not (e.office_id and e.position_id)
            content = _labelled([("Name", name), ("Group / position", position), ("Office", office),
                                 ("Roster note", note), ("Email", e.email), ("Contact number", e.contact_number)])
            if desc:
                content += f". {desc}"
            tokens = self.toks(name, 2) + self.toks(_join(position, office, desc, note))
            out.append(Record("employee", e.id, name, content, tokens, "PGPC employee records",
                              {"name": name, "position": position or None, "office": office or None,
                               "email": e.email, "contact_number": e.contact_number, "note": note or None},
                              incomplete))
        return out

    def positions(self, db: Session) -> list[Record]:
        out = []
        for p in db.scalars(select(Position)):
            desc, bad = clean_value(p.description)
            if bad:
                continue   # a roster group heading with no real description is not a searchable fact
            out.append(Record("position", p.id, p.name, _labelled([("Position", p.name), ("Description", desc)]),
                              self.toks(p.name, 2) + self.toks(desc), "PGPC position records",
                              {"name": p.name, "description": desc or None}))
        return out

    def offices(self, db: Session) -> list[Record]:
        out = []
        for o in db.scalars(select(Office)):
            desc, bad = clean_value(o.description)
            where = _join(f"Building {o.building}" if o.building else "", f"Floor {o.floor}" if o.floor else "",
                          f"Room {o.room_number}" if o.room_number else "")
            content = _labelled([("Office", o.name), ("Location", where.replace(" Floor", ", Floor").replace(" Room", ", Room")),
                                 ("Contact number", o.contact_number), ("Email", o.email), ("About", desc)])
            out.append(Record("office", o.id, o.name, content,
                              self.toks(o.name, 3) + self.toks(_join(desc, where)), "PGPC office records",
                              {"name": o.name, "building": o.building, "floor": o.floor, "room_number": o.room_number,
                               "contact_number": o.contact_number, "email": o.email, "about": desc or None},
                              bad or not (o.building or o.floor or o.room_number)))
        return out

    def rooms(self, db: Session) -> list[Record]:
        out = []
        for r in db.scalars(select(Room)):
            desc, bad = clean_value(r.description)
            facility = r.facility.name if r.facility else ""
            title = _join(f"Room {r.room_number}", f"({r.room_name})" if r.room_name else "")
            content = _labelled([("Room", title.replace("Room ", "", 1)), ("Building", r.building), ("Floor", r.floor),
                                 ("Type", r.room_type), ("Facility", facility), ("About", desc)])
            out.append(Record("room", r.id, title, content,
                              self.toks(_join("room", r.room_number, r.room_name), 2) +
                              self.toks(_join(r.building, f"floor {r.floor}" if r.floor else "", r.room_type, facility, desc)),
                              "PGPC room records",
                              {"room_number": r.room_number, "room_name": r.room_name, "building": r.building,
                               "floor": r.floor, "room_type": r.room_type, "facility": facility or None}, bad))
        return out

    def facilities(self, db: Session) -> list[Record]:
        out = []
        for f in db.scalars(select(Facility)):
            desc, bad1 = clean_value(f.description)
            equip, bad2 = clean_value(f.available_equipment)
            content = _labelled([("Facility", f.name), ("Building", f.building), ("Location", f.location),
                                 ("Equipment", equip), ("Operating hours", f.operating_hours), ("About", desc)])
            out.append(Record("facility", f.id, f.name, content,
                              self.toks(f.name, 3) + self.toks(_join(desc, equip, f.building, f.location)) +
                              # the field is called operating_hours, so a question about "hours" must match it
                              (self.toks(_join("operating hours", f.operating_hours)) if f.operating_hours else []),
                              "PGPC facility records",
                              {"name": f.name, "building": f.building, "location": f.location,
                               "equipment": equip or None, "operating_hours": f.operating_hours,
                               "about": desc or None}, bad1 or bad2 or not (f.building or f.location)))
        return out

    def handbook(self, db: Session) -> list[Record]:
        """A handbook section can be 3000 characters long, which makes TF-IDF scores for short questions
        tiny. So every section is cut into passages of roughly one paragraph group, and the best
        passage of a section is what gets returned."""
        out = []
        for h in db.scalars(select(HandbookSection)):
            content, bad = clean_value(h.content)
            page = f", page {h.source_page}" if h.source_page else ""
            src = f"{h.source_document or 'PGPC Student Handbook'}{page}"
            head = self.toks(h.title, 2) + self.toks(_join(h.category, h.section_number))
            heading = None
            passages = split_passages(h.content if not bad else content)
            for n, passage in enumerate(passages, start=1):
                heading = find_heading(passage) or heading        # later passages inherit the latest heading
                extra = self.toks(heading, 3) if heading else []
                shown = finish_sentence(passage, passages[n] if n < len(passages) else "")
                out.append(Record("handbook", h.id, h.title, shown, head + extra + self.toks(passage), src,
                                  {"category": h.category, "section_number": h.section_number,
                                   "page": h.source_page, "passage": n, "heading": heading}, bad))
        return out

    def history(self, db: Session) -> list[Record]:
        out = []
        for s in db.scalars(select(SchoolHistory)):
            content, bad = clean_value(s.content)
            out.append(Record("history", s.id, s.title, content,
                              self.toks(s.title, 2) + self.toks(_join(s.year, content)),
                              s.source or "PGPC school history", {"year": s.year}, bad))
        return out

    def faqs(self, db: Session) -> list[Record]:
        out = []
        for f in db.scalars(select(FAQ).where(FAQ.is_active.is_(True))):
            answer, bad = clean_value(f.answer)
            out.append(Record("faq", f.id, f.question, answer,
                              self.toks(f.question, 2) + self.toks(_join(f.keywords, f.category, answer)),
                              f.source or "PGPC FAQ", {"category": f.category, "question": f.question}, bad))
        return out

    def library(self, db: Session) -> list[Record]:
        out = []
        for b in db.scalars(select(LibraryBook)):
            content = _labelled([("Title", b.title), ("Author", b.author), ("ISBN", b.isbn), ("Category", b.category),
                                 ("Publisher", b.publisher), ("Year", b.year), ("Availability", b.availability),
                                 ("Location", b.location)])
            out.append(Record("library", b.id, b.title, content,
                              self.toks(b.title, 2) + self.toks(_join(b.author, b.isbn, b.category, b.publisher, b.year)),
                              "PGPC library records",
                              {"title": b.title, "author": b.author, "isbn": b.isbn, "availability": b.availability,
                               "location": b.location}))
        return out

    def chunks(self, db: Session) -> list[Record]:
        out = []
        q = (select(KnowledgeChunk, Document).outerjoin(Document, KnowledgeChunk.document_id == Document.id)
             .where((Document.id.is_(None)) | (Document.status == "active")))
        for c, d in db.execute(q):
            content, bad = clean_value(c.content)
            title = c.title or (d.title if d else "Uploaded document")
            page = f", page {c.source_page}" if c.source_page else ""
            out.append(Record("document", c.id, title, content,
                              self.toks(title, 2) + self.toks(_join(c.keywords, c.category, content)),
                              f"{c.source or (d.title if d else 'Uploaded document')}{page}",
                              {"document_id": c.document_id, "page": c.source_page}, bad))
        return out

    def build_all(self, db: Session) -> list[Record]:
        recs: list[Record] = []
        for fn in (self.employees, self.positions, self.offices, self.rooms, self.facilities, self.handbook,
                   self.history, self.faqs, self.library, self.chunks):
            recs.extend(fn(db))
        return [r for r in recs if r.tokens]


# ----------------------------------------------------------------------------- the index
def _identity(tokens):
    return tokens


TITLE_BOOST = 1.35        # score multiplier for a handbook section whose title contains a distinctive question word
TITLE_IDF_RATIO = 0.55    # "distinctive" = the word's weight is at least this share of the rarest word's weight


class KnowledgeIndex:
    def __init__(self, records: list[Record], miner: TextMiner):
        self.records = records
        self.miner = miner
        self.vectorizer = None
        self.matrix = None
        self.binary = None
        self.idf = None
        self.corrector: SpellingCorrector | None = None
        if records:
            self.vectorizer = TfidfVectorizer(analyzer=_identity, sublinear_tf=True)
            self.matrix = self.vectorizer.fit_transform([r.tokens for r in records])
            self.binary = (self.matrix > 0).astype(np.float32).tocsc()
            self.idf = self.vectorizer.idf_
            self.corrector = miner.make_corrector(self.vectorizer.vocabulary_.keys())
            # The words of each record's own title ("Absences and Tardiness"): a question about "absences" should
            # prefer that section over a long passage that only mentions the word.
            self.title_sets = [set(miner.process(r.title).lemmas) if r.source_type == "handbook" else set()
                               for r in records]

    def __len__(self) -> int:
        return len(self.records)

    def search(self, processed: ProcessedText, preferred: set[str] | None, top_k: int, threshold: float,
               off_weight: float = OFF_INTENT_WEIGHT):
        terms = list(dict.fromkeys(processed.lemmas))
        if not terms or self.matrix is None:
            return [], 0
        vocab = self.vectorizer.vocabulary_
        max_idf = float(self.idf.max())
        # Each question word becomes a group: the word itself plus its synonyms that exist in the knowledge base.
        groups = []   # (term, idf weight, [known words])
        for t in terms:
            members = [w for w in [t] + SYNONYMS.get(t, []) if w in vocab]
            weight = float(self.idf[vocab[t]]) if t in vocab else max_idf   # an unknown word lowers coverage
            groups.append((t, weight, members))
        if not any(g[2] for g in groups):
            return [], 0
        total_w = sum(g[1] for g in groups)

        query_words = list(dict.fromkeys(w for g in groups for w in g[2]))
        qvec = self.vectorizer.transform([query_words])                  # l2-normalised TF-IDF of the question
        cosine = (self.matrix @ qvec.T).toarray().ravel()
        coverage = np.zeros(len(self.records), dtype=np.float32)
        for _, weight, members in groups:
            if members:
                present = np.asarray(self.binary[:, [vocab[w] for w in members]].max(axis=1).todense()).ravel()
                coverage += weight * present
        coverage /= total_w
        base = np.sqrt(np.clip(cosine, 0, None) * np.clip(coverage, 0, None))   # both must be reasonably high

        weight = np.ones(len(self.records), dtype=np.float32)
        if preferred:
            weight = np.array([1.0 if r.source_type in preferred else off_weight for r in self.records],
                              dtype=np.float32)
        score = base * weight

        # Title boost: a distinctive question word that is part of a handbook section's title.
        distinctive = [g for g in groups if g[0] not in GENERIC_TERMS and g[1] >= TITLE_IDF_RATIO * max_idf and g[2]]
        if distinctive:
            title_hit = np.array([any(w in ts for g in distinctive for w in g[2]) for ts in self.title_sets])
            score = np.where(title_hit, score * TITLE_BOOST, score)

        # Entity records must match at least one non-generic word of the question (when it has any).
        specific = [g for g in groups if g[0] not in GENERIC_TERMS]   # words nobody uses count too
        if specific:
            distinct = np.zeros(len(self.records), dtype=bool)
            for _, _, members in specific:
                if members:
                    distinct |= np.asarray(self.binary[:, [vocab[w] for w in members]].max(axis=1).todense()).ravel() > 0
            is_entity = np.array([r.source_type in ENTITY_TYPES for r in self.records])
            score = np.where(is_entity & ~distinct, score * GENERIC_PENALTY, score)

        hits, seen, total_keys = [], set(), set()
        for i in np.argsort(-score, kind="stable"):
            if score[i] <= 0:
                break
            r = self.records[i]
            key = (r.source_type, r.source_id)
            if key in seen:               # several passages of one handbook section: keep only the best
                continue
            seen.add(key)
            if score[i] >= threshold:
                total_keys.add(key)
            if len(hits) < top_k:
                rec_terms = set(r.tokens)
                matched = [g[0] for g in groups if any(w in rec_terms for w in g[2])]
                hits.append(Hit(r.source_type, r.source_id, r.title, r.content, r.source, round(float(score[i]), 4),
                                round(float(cosine[i]), 4), round(float(coverage[i]), 4), matched, r.incomplete,
                                r.fields))
            elif score[i] < threshold:
                break
        return hits, len(total_keys)


# ----------------------------------------------------------------------------- cache + public API
_TABLES = (Employee, Position, Office, Room, Facility, HandbookSection, SchoolHistory, FAQ, LibraryBook,
           KnowledgeChunk, Document)
_lock = threading.Lock()
_cache: dict = {"signature": None, "index": None}


def data_signature(db: Session) -> tuple:
    """Cheap fingerprint of the knowledge tables (row count + latest edit). When an admin adds, edits or
    deletes anything, it changes and the index is rebuilt on the next question."""
    sig = []
    for model in _TABLES:
        col = getattr(model, "updated_at", None)
        cols = [func.count()] + ([func.max(col)] if col is not None else [])
        sig.append(tuple(str(v) for v in db.execute(select(*cols).select_from(model)).one()))
    # FAQ visibility and document status change what is searchable without always touching updated_at
    sig.append((str(db.scalar(select(func.count()).select_from(FAQ).where(FAQ.is_active.is_(True)))),
                str(db.scalar(select(func.count()).select_from(Document).where(Document.status == "active")))))
    return tuple(sig)


def get_index(db: Session, force: bool = False) -> KnowledgeIndex:
    sig = data_signature(db)
    with _lock:
        if force or _cache["index"] is None or _cache["signature"] != sig:
            miner = get_text_miner()
            records = Indexer(miner).build_all(db)
            _cache["index"] = KnowledgeIndex(records, miner)
            _cache["signature"] = sig
            logger.info("Knowledge index rebuilt: %d records", len(records))
        return _cache["index"]


def clear_index_cache() -> None:
    with _lock:
        _cache["signature"] = None
        _cache["index"] = None


def confidence_level(score: float) -> str:
    s = get_settings()
    if score >= s.high_confidence_threshold:
        return "high"
    if score >= s.medium_confidence_threshold:
        return "medium"
    if score >= s.similarity_threshold:
        return "low"
    return "none"


def retrieve(db: Session, question: str, intent: str | None = None, top_k: int = 5) -> RetrievalResult:
    """Main entry point. `intent` comes from the Phase 6 classifier (None = search every source equally)."""
    settings = get_settings()
    if intent in NO_SEARCH_INTENTS:
        # Greetings, thanks and off-topic questions never search the knowledge base. A joke question would
        # otherwise "match" a handbook passage that merely contains the word "jokes".
        return RetrievalResult(question=question, keywords=[], intent=intent, hits=[], found=False,
                               confidence="none", total_matches=0, preferred_sources=[])
    index = get_index(db)
    processed = get_text_miner().process(question, corrector=index.corrector)
    preferred = INTENT_SOURCES.get(intent or "")
    off_weight = ENTITY_OFF_INTENT_WEIGHT if intent in ENTITY_INTENTS else OFF_INTENT_WEIGHT
    hits, total = index.search(processed, preferred, top_k, settings.similarity_threshold, off_weight)
    best = hits[0].score if hits else 0.0
    level = confidence_level(best)
    return RetrievalResult(question=question, keywords=processed.keywords, intent=intent, hits=hits,
                           found=level != "none", confidence=level, total_matches=total,
                           preferred_sources=sorted(preferred or []))


def _demo(question: str) -> None:
    from app.database.database import SessionLocal
    from app.services.intent_classifier import get_intent_classifier
    intent = get_intent_classifier().predict(question)
    with SessionLocal() as db:
        res = retrieve(db, question, intent.intent if intent.intent != "unknown" else None)
    print(f"Question  : {question}")
    print(f"Intent    : {intent.intent} ({intent.confidence:.2f})")
    print(f"Keywords  : {res.keywords}")
    print(f"Found     : {res.found}  confidence={res.confidence}  matches above threshold={res.total_matches}")
    for i, h in enumerate(res.hits, 1):
        flag = "  [incomplete]" if h.incomplete else ""
        print(f"  {i}. {h.score:.2f}  [{h.source_type}] {h.title}  ({h.source}){flag}")


if __name__ == "__main__":
    _demo(" ".join(sys.argv[1:]) or "Where is the registrar office?")
