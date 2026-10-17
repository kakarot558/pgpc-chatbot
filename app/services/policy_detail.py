"""Full-detail policy answers (an upgrade of the Phase 8 answer step).

Problem this fixes
------------------
A question such as "what is the haircut policy?" used to return ONE line of the handbook:

    30. Not in proper hair cut as prescribed by the college.

That line is useless on its own, because the handbook PDF was flattened into text:
  * the offense tables lost their columns, so a rule is separated from "Minor / Major" and from its sanctions;
  * the same topic is mentioned in several places (blonde hair, long hair, earrings, haircut ...);
  * the answer generator only showed the single best sentence.

What this module does (no language model, only stored handbook text, so nothing can be invented):
  1. Rebuilds the structure of the Student Conduct chapter:  rule -> Minor/Major -> offense category -> sanctions.
  2. Collects EVERY place the handbook mentions the topic and writes one complete answer:
        - the rules that mention it, with their number, offense class and category
        - the sanctions the handbook lists for that class/category
        - the policy text itself (e.g. the dress code section) shown in full, not one sentence of it
        - honest notes: what the handbook does not say, and where it contradicts itself
  3. Only runs when the student asks for a policy / rule / detail / penalty (or names a topic on its own),
     so "where is the clinic?" is not affected.

Pure functions first (parse_offenses, find_offense_items, ...) so they are testable without a database;
`build_detail_answer(db, question)` is the only function that touches the database.
"""
import re
from dataclasses import dataclass, field
from typing import Callable, Iterable

# --------------------------------------------------------------------------- when to use the detailed answer
# Words that mean "give me everything about it". They are NOT part of the topic itself.
DETAIL_WORDS = {
    "detail", "details", "detailed", "full", "complete", "completely", "everything", "explain", "explanation",
    "elaborate", "policy", "policies", "rule", "rules", "regulation", "regulations", "guideline", "guidelines",
    "violation", "violations", "violate", "offense", "offenses", "offence", "sanction", "sanctions", "penalty",
    "penalties", "punishment", "punishments", "consequence", "consequences", "prohibited", "allowed", "allow",
    "required", "requirement", "requirements", "restriction", "restrictions", "mean", "means", "meaning",
}
# Words that never describe the topic.
QUESTION_FILLER = {
    "what", "whats", "is", "are", "the", "a", "an", "of", "in", "on", "at", "to", "for", "about", "tell", "me", "give",
    "show", "can", "you", "please", "pls", "do", "does", "did", "i", "my", "we", "our", "us", "there", "any", "all",
    "some", "more", "info", "information", "know", "want", "need", "like", "regarding", "concerning", "with", "and",
    "or", "if", "when", "where", "whose", "whom", "how", "why", "who", "which", "will", "would", "should", "happen", "happens", "get", "gets",
    "pgpc", "college", "school", "campus", "handbook", "student", "students", "boy", "boys", "girl", "girls", "male",
    "female", "say", "says", "said", "its", "their", "this", "that", "these", "those", "be", "been", "being", "have",
    "has", "had", "it", "so", "than", "then", "also", "ever", "much", "many", "other", "kind", "kinds", "type",
    "types", "stated", "state", "states", "cover", "covers", "under", "within", "inside", "outside", "here",
    "use", "using", "used", "uses", "please", "pls", "plz", "po", "ho", "kindly", "hello", "hi", "hey", "ok", "okay",
    "thanks", "thank", "wanna", "let", "lets", "going", "whats", "whos", "if", "you", "d", "u", "r",
    "from", "another", "into", "by", "after", "before", "during", "apply", "applying", "getting", "got", "make",
    "making", "take", "taking", "needs", "needed", "documents", "document", "papers", "paper",
}
# Two words that mean one thing in the handbook.
PHRASES = {("latin", "honors"): "laude", ("latin", "honor"): "laude", ("cum", "laude"): "laude", ("dress", "code"): "dress", ("hair", "cut"): "haircut", ("id", "card"): "id",
           ("cell", "phone"): "cellphone", ("mobile", "phone"): "cellphone"}

TERM_ALIASES = {"phone": "cellphone", "phones": "cellphone", "cp": "cellphone", "gadgets": "gadget"}

# Words in the handbook that are about the same appearance rules (shown as "related", not as the answer itself).
RELATED = {"hair": ("earring", "tattoo"), "haircut": ("earring", "tattoo"), "grooming": ("earring", "tattoo", "hair")}
# Spelling variants that really occur in the handbook text.
VARIANTS = {"phone": ["cellphone", "gadget"], "phones": ["cellphone", "gadget"], "cellphone": ["gadget", "phone"], "earring": ["earing", "earrings"], "tattoo": ["tattoos"], "haircut": ["hair"], "hair": ["haircut"],
            "grooming": ["hair", "haircut"]}

MAX_ITEMS_PER_GROUP = 12          # offense items shown for one class/category
MAX_POLICY_CHARS = 2600           # policy text shown in full for one topic
MAX_BLOCKS = 6


# What the student must say to get the complete answer. ("allowed", "required"... only help name the topic.)
TRIGGER_WORDS = {
    "detail", "details", "detailed", "full", "complete", "everything", "explain", "explanation", "elaborate",
    "policy", "policies", "rule", "rules", "regulation", "regulations", "guideline", "guidelines", "violation",
    "violations", "offense", "offenses", "sanction", "sanctions", "penalty", "penalties", "punishment",
    "consequence", "consequences",
}
# A narrow question wants one fact ("how many absences are allowed?"), which the focused answer already gives.
NARROW_WORDS = {"many", "much", "long", "often", "old", "far", "when", "where", "who", "whom", "whose", "time", "date"}
EXPLICIT_DETAIL = {"detail", "details", "detailed", "full", "complete", "everything", "explain", "elaborate"}
EXPLICIT_FULL = EXPLICIT_DETAIL | {"policy", "policies"}


def asked_for_everything(words: Iterable[str]) -> bool:
    """The student literally asked for the details / the full text."""
    return bool(set(words) & EXPLICIT_DETAIL)


PERMISSION_STARTERS = {"can", "may", "could", "am", "is", "are", "do", "does", "should"}
PERMISSION_WORDS = {"allowed", "allow", "permitted", "permit", "prohibited", "forbidden", "banned", "ok", "okay"}
# Verbs that only say what the student wants to do; the topic is the thing ("wear SANDALS", "bring CELLPHONE").
ACTION_WORDS = {"wear", "wearing", "bring", "bringing", "carry", "take", "enter", "join", "go", "going", "have", "having",
                "keep", "put", "bawal", "not", "no", "class", "classes", "inside", "outside", "campus", "school", "ok",
                "okay", "fine", "permitted", "permit", "forbidden", "banned", "may", "could", "am", "should"}


def is_permission_question(words: Iterable[str]) -> bool:
    """'can i wear sandals', 'is blonde hair allowed', 'not allowed tattoo' (bawal ba ang tattoo)."""
    w = list(words)
    if not w or set(w) & NARROW_WORDS:
        return False
    if set(w) & PERMISSION_WORDS or ("not" in w and "allowed" in w):
        return True
    return w[0] in PERMISSION_STARTERS and len(topic_terms(w)) >= 1 and w[0] != "are" and "who" not in w


def asks_consequence(words: Iterable[str]) -> bool:
    """'what happens if i cheat', 'what will happen if late'."""
    w = set(words)
    return bool(w & {"happen", "happens", "happened"}) and "if" in w


def wants_full_detail(words: Iterable[str]) -> bool:
    w = set(words)
    if asks_consequence(w) or is_permission_question(words):
        return True
    if not (w & TRIGGER_WORDS):
        return False
    return not (w & NARROW_WORDS) or bool(w & EXPLICIT_FULL)


def is_topic_only(words: Iterable[str]) -> bool:
    """'haircut', 'dress code', 'what about uniforms' - a bare topic with no narrow question word."""
    w = list(words)
    if set(w) & NARROW_WORDS:
        return False
    return 0 < len(topic_terms(w)) <= 3


def topic_terms(question_words: list[str]) -> list[str]:
    """The words that name the topic: 'what is the haircut policy' -> ['haircut']."""
    words = list(question_words)
    out, i = [], 0
    while i < len(words):
        pair = tuple(words[i:i + 2])
        if len(pair) == 2 and pair in PHRASES:
            out.append(PHRASES[pair])
            i += 2
            continue
        w = TERM_ALIASES.get(words[i], words[i])
        if w not in DETAIL_WORDS and w not in QUESTION_FILLER and len(w) > 1 and w not in ACTION_WORDS:
            out.append(w)
        i += 1
    if not out:
        out = [w for w in words if w in {"class", "classes", "campus"}][:1] or out
    seen, uniq = set(), []
    for w in out:
        if w not in seen:
            seen.add(w)
            uniq.append(w)
    return uniq


def _norm(text: str) -> str:
    text = (text or "").lower().replace("hair cut", "haircut")
    text = re.sub(r"\b(cell|mobile)\s*phones?\b", "cellphone", text)
    return re.sub(r"[^a-z0-9\s]", " ", text)


def _stem(w: str) -> str:
    """Cheap singular form, enough to match 'earrings'/'earring' without loading NLTK."""
    for suf, rep in (("ies", "y"), ("sses", "ss"), ("s", "")):
        if w.endswith(suf) and len(w) > len(suf) + 2 and not w.endswith("ss"):
            return w[: -len(suf)] + rep
    return w


def word_set(text: str) -> set[str]:
    return {_stem(w) for w in _norm(text).split() if w}


def term_groups(terms: Iterable[str], synonyms: dict[str, list[str]] | None = None) -> list[set[str]]:
    """One group per topic word: the word, its spelling variants and its synonyms ('cut' alone is too vague)."""
    synonyms = synonyms or {}
    groups = []
    for t in terms:
        g = {_stem(t)}
        for extra in list(synonyms.get(t) or synonyms.get(_stem(t)) or []) + VARIANTS.get(t, []):
            g.add(_stem(extra))
        g.discard("cut")
        groups.append(g)
    return groups


def matches_all(words: set[str], groups: list[set[str]]) -> bool:
    return bool(groups) and all(words & g for g in groups)


def matches(words: set[str], groups: list[set[str]]) -> bool:
    """A text matches the topic when it contains the topic word (or a synonym) of at least half of the groups,
    and at least one of them. 'dress code' -> only 'dress' is a group, so 'attire' matches."""
    if not groups:
        return False
    hit = sum(1 for g in groups if words & g)
    return hit >= max(1, (len(groups) + 1) // 2) and hit / len(groups) >= 0.5


# --------------------------------------------------------------------------- offense table parser
@dataclass
class OffenseItem:
    table: str                    # "Minor" | "Major"
    category: str                 # e.g. "Offenses Against Order"
    number: str                   # the number printed in the handbook
    text: str
    key: str = "general"          # category key used to look up sanctions
    subs: list[str] = field(default_factory=list)      # a) b) c) ... lines listed under one numbered rule


@dataclass
class OffenseIndex:
    items: list[OffenseItem] = field(default_factory=list)
    # (table, category key) -> sanctions listed for it.  Minor offenses have one shared list.
    sanctions: dict[tuple[str, str], list[str]] = field(default_factory=dict)
    category_names: dict[tuple[str, str], str] = field(default_factory=dict)


_NOISE = re.compile(r"^(table(\s+type)?(\s+continuation)?|continuation|nature of offense|-{3,}|_{3,}|=+)$", re.I)
_MARKER = re.compile(r"^(\d{1,2})\s*\.\s*(.*)$")
_OCR_MARKER = re.compile(r"^([IiPp])\.\s*(\S.*)$")             # the scan turned "1." / "2." into "I." / "P."
_SUBITEM = re.compile(r"^(\(?[a-eA-E]\)|\.)\s+")
_LETTER_SUB = re.compile(r"^\(?[a-eA-E]\)\s*(\S.*)$")
_ITEM_CAT = re.compile(r"^offenses\s+(against|involving)\s+(.{3,40})$", re.I)          # plural: heading of rules
_SANCTION_LABEL = re.compile(r"^offense\s+(against|involving)\s+(.{3,40})$", re.I)    # singular: heading of sanctions
_SANCTION_WORDS = re.compile(r"reprimand|apolog|formation session|community service|suspension|dismissal|expulsion|"
                             r"drug test|mandatory work|probation|warning", re.I)
_MINOR_SANCTION_START = re.compile(r"^(written|formation sessions)", re.I)


def _key(name: str) -> str:
    name = re.sub(r"\b(offenses?|against|involving)\b", " ", name.lower())
    return " ".join(name.split())


def _pretty_category(raw: str) -> str:
    return " ".join(raw.split()).title()


def _clean_item_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip(" .")
    return text[:1].upper() + text[1:] if text else text


def parse_offenses(text: str) -> OffenseIndex:
    """Rebuilds 'rule -> Minor/Major -> category -> sanctions' from the flattened Student Conduct text.

    How the PDF text looks (and what this reads from it):
      "Minor Offense" / "Major Offense"            switch the table
      "Offenses Against Order"                     heading of a group of numbered rules
      "OFFENSE AGAINST ORDER" (singular)           heading of the sanctions of that group
      "Sanctions" + numbered lines                 sanctions of the groups that have no own heading (Security, Persons)
      lines starting "Written/..." "Formation..."  the one shared sanction list of the minor table
    """
    idx = OffenseIndex()
    table = category = cat_label = None
    mode = "items"                       # "items" | "sanctions"
    sanction_target = None               # (table, key) of a labelled sanction block
    block_no = 0
    pending: list[str] = []              # Major categories (keys) still waiting for an unlabelled sanction block
    cur: OffenseItem | None = None
    last: OffenseItem | None = None      # last finished item: page breaks cut a rule in two
    cur_sanction: list[str] | None = None
    blank = False                        # a blank line was seen since the last sanction line

    def close_item():
        nonlocal cur, last
        if cur is not None and cur.text.strip():
            idx.items.append(cur)
            last = cur
        cur = None

    def new_sanction(target, first_line):
        entry = [first_line]
        idx.sanctions.setdefault(target, []).append(entry)       # type: ignore[arg-type]  (joined at the end)
        return entry

    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            blank = True
            continue
        low = line.lower()

        if re.match(r"^(table\s+)?minor offenses?$", low):
            close_item(); table, category, cat_label, mode, cur_sanction = "Minor", "general", "Minor offenses", "items", None
            continue
        if re.match(r"^(table\s+type\s+)?major offenses?$", low):
            close_item(); table, category, cat_label, mode, cur_sanction, pending = "Major", None, None, "items", None, []
            continue
        if table is None:
            continue
        if _NOISE.match(line):
            if low.endswith("continuation"):
                mode, cur_sanction = "items", None
            continue
        if low.startswith("the following are considered inimical"):
            close_item(); last = None; cur_sanction = None
            continue

        # ---- the shared sanction list of the minor table (unnumbered lines)
        if table == "Minor":
            if _MINOR_SANCTION_START.match(line):
                close_item(); last = None
                cur_sanction = new_sanction(("Minor", "general"), line)
                blank = False
                continue
            if cur_sanction is not None and not blank and not _MARKER.match(line):
                cur_sanction.append(line)
                continue
            cur_sanction = None

        # ---- headings
        if line == "Sanctions":
            close_item()
            mode, block_no, sanction_target, cur_sanction = "sanctions", 0, None, None
            pending = [k for k in pending if ("Major", k) not in idx.sanctions]
            blank = False
            continue
        if _SANCTION_LABEL.match(line) or (table == "Major" and line.isupper() and _key(line) == "plagiarism"):
            close_item()
            mode, sanction_target, block_no, cur_sanction = "sanctions", ("Major", _key(line)), 0, None
            blank = False
            continue
        if _ITEM_CAT.match(line):
            close_item(); last = None
            category, cat_label, mode = _key(line), _pretty_category(line), "items"
            idx.category_names[(table, category)] = cat_label
            if table == "Major":
                pending.append(category)
            continue
        if table == "Major" and line == "Plagiarism":
            close_item(); last = None
            category, cat_label, mode = "plagiarism", "Plagiarism", "items"
            idx.category_names[(table, category)] = cat_label
            continue

        # ---- numbered sanction lines after a "Sanctions" heading or a labelled sanction block
        mk = _MARKER.match(line)
        if mode == "sanctions":
            if mk and _SANCTION_WORDS.search(mk.group(2)):
                if mk.group(1) == "1":
                    block_no += 1
                if sanction_target is not None:
                    tgt = sanction_target
                else:
                    i = block_no - 1
                    tgt = ("Major", pending[i]) if 0 <= i < len(pending) else None
                cur_sanction = new_sanction(tgt, mk.group(2)) if tgt else None
                blank = False
                continue
            if cur_sanction is not None and not blank and not mk:
                cur_sanction.append(line)                  # wrapped line of the sanction above
                continue
            mode, cur_sanction = "items", None             # not a sanction: the rules go on

        # ---- rules
        ocr = _OCR_MARKER.match(line) if table == "Minor" else None
        if mk or ocr:
            close_item()
            number = mk.group(1) if mk else {"i": "1", "p": "2"}[ocr.group(1).lower()]
            body = mk.group(2) if mk else ocr.group(2)
            cur = OffenseItem(table, cat_label or "Offenses", number, body, category or "general")
            last = None
            continue
        if cur is not None:
            sub = _LETTER_SUB.match(line)
            if sub:
                cur.subs.append(sub.group(1))                    # "e) Using cell phone during classes"
            elif cur.subs:
                cur.subs[-1] += " " + line
            else:
                cur.text += " " + ("\u2022 " + line[1:].strip() if line.startswith(".") else line)
        elif last is not None and line[:1].islower():
            last.text += " " + line                        # the rest of a rule that a page break cut in two
    close_item()

    final: dict[tuple[str, str], list[str]] = {}
    for key, entries in idx.sanctions.items():
        for e in entries:
            sentence = " ".join(" ".join(e).split())
            if sentence and sentence not in final.setdefault(key, []):
                final[key].append(sentence)
    idx.sanctions = final
    for it in idx.items:
        it.text = _clean_item_text(it.text)
        it.subs = [_clean_item_text(x) for x in it.subs]
    return idx


def sanctions_for(index: OffenseIndex, item: OffenseItem) -> list[str]:
    return index.sanctions.get((item.table, item.key), [])


def find_offense_items(index: OffenseIndex, groups: list[set[str]], strict: bool = False) -> list[OffenseItem]:
    """Rules about the topic. When only one a)/b)/c) line of a numbered rule is about it, just that line is shown,
    with the rule it is listed under. strict=True needs EVERY topic word, not just half of them."""
    from dataclasses import replace
    test = matches_all if strict else matches
    found = []
    for it in index.items:
        if test(word_set(it.text) | word_set(it.category), groups):
            if it.subs:
                it = replace(it, text=f"{it.text.rstrip('.')}: " + "; ".join(it.subs))
            found.append(it)
            continue
        hit = [x for x in it.subs if test(word_set(x), groups)]
        if hit:
            found.append(replace(it, text="; ".join(hit) + f" (listed under: {it.text.rstrip('.')})", subs=[]))
    return found


# --------------------------------------------------------------------------- policy text (non-table passages)
_HEADING_LIKE = re.compile(r"^(\d+\.\s|[A-Za-z]\)\s|\.\s|[-•]\s)")


def split_blocks(text: str) -> list[str]:
    return [b.strip() for b in re.split(r"\n\s*\n", text or "") if b.strip()]


_SECTION_LINE = re.compile(r"^(?:Section|Article|Chapter|Bection|Beetion|Neotlon|Nection)\s+\w+\s*[-\u2013:.]", re.I)


def heading_line_index(block: str, exact: set[str] | None) -> int | None:
    """Index of a heading line INSIDE a block that names the topic: '4. Section B - Pre-Enrollment Requirements and
    Procedure' sits in the middle of the text of the previous section in the scanned handbook."""
    if not exact:
        return None
    for i, raw in enumerate(block.splitlines()):
        line = re.sub(r"^\d+\.\s*", "", raw.strip())
        if (len(line) <= 70 and (_SECTION_LINE.match(line) or looks_like_heading(line))) and word_set(line) & exact:
            return i
    return None


def pick_policy_blocks(blocks: list[str], groups: list[set[str]], exact: set[str] | None = None,
                       max_chars: int = MAX_POLICY_CHARS) -> list[str]:
    """The best matching block, then the blocks that follow it while they match or continue a numbered/bulleted
    list, so a whole policy (rule, prohibited items, sanctions, schedule) is shown, not one sentence of it."""
    if not groups or not blocks:
        return []
    scored = []
    for i, b in enumerate(blocks):
        head = b.splitlines()[0]
        ws = word_set(b)
        hit = sum(1 for g in groups if ws & g)
        head_hit = sum(1 for g in groups if word_set(head) & g)
        exact_hit = len(ws & exact) if exact else 0
        if heading_line_index(b, exact) is not None:
            head_hit += 2                                 # a heading about the topic inside the block
        # a block that only contains one synonym (e.g. "uniform" in a withdrawal rule) is not about the topic
        if exact is not None and not exact_hit and hit < 2:
            continue
        scored.append((hit * 2 + head_hit * 3 + exact_hit * 3, i))
    if not scored:
        return []
    best_score, best = max(scored, key=lambda t: (t[0], -t[1]))
    if best_score <= 0:
        return []
    start = best
    cut_at = heading_line_index(blocks[start], exact)
    if cut_at is None and (blocks[start].lstrip()[:2] in {". ", "- "} or re.match(r"^[2-9]\.\s", blocks[start])):
        start = max(0, start - 1)                        # we landed in the middle of a list: take its start
    if cut_at:                                           # start the answer at the heading, not above it
        blocks = list(blocks)
        blocks[start] = "\n".join(blocks[start].splitlines()[cut_at:])
    chosen, size = [], 0
    for j in range(start, len(blocks)):
        b = blocks[j]
        follows = j == start or matches(word_set(b), groups) or bool(_HEADING_LIKE.match(b))
        if not follows:
            break
        if size + len(b) > max_chars and chosen:
            break
        chosen.append(b)
        size += len(b) + 2
        if len(chosen) >= MAX_BLOCKS:
            break
    return chosen


_OCR_HEADING = re.compile(r"^([A-Za-z]{5,10})\s+([A-Za-z]|\d{1,2})\s*[-\u2013.]\s*(\S.*)$")


def fix_ocr_heading(line: str) -> str:
    """The scanned handbook has headings such as 'WEETLON A-LIBRARY RULES' or 'Bection M - ...' for 'SECTION ...'.
    A first word that is no real word, followed by a section letter and a dash, is the word SECTION."""
    m = _OCR_HEADING.match(line.strip())
    if not m:
        return line
    from app.services.input_reader import load_english
    first = m.group(1).lower()
    if first == "section" or first in load_english():
        return line
    return f"Section {m.group(2)} - {m.group(3)}" if not line.isupper() else f"SECTION {m.group(2)} - {m.group(3)}"


def looks_like_heading(line: str) -> bool:
    """'Dress Code Policy on Washdays' is a heading; 'Absences may either be:' is the start of a sentence."""
    line = (line or "").strip()
    if not 4 <= len(line) <= 80 or line[-1] in ".:,;" or not line[0].isupper() or line[0].isdigit():
        return False
    words = [w for w in line.split() if w[0].isalpha()]
    return bool(words) and sum(1 for w in words if w[0].isupper()) / len(words) >= 0.6


def tidy_block(block: str) -> str:
    """Join PDF-wrapped lines; keep numbered / bulleted lines on their own line."""
    out: list[str] = []
    for line in (l.strip() for l in block.splitlines()):
        if not line or re.fullmatch(r"-{3,}|page\s*\d+", line, re.I):
            continue
        line = fix_ocr_heading(re.sub(r"^(Bection|Beetion)\b", "Section", line))      # typos of the scanned handbook
        line = re.sub(r"^\.\s+", "- ", line)
        if out and not _HEADING_LIKE.match(line) and not out[-1].endswith(":") and len(out[-1]) > 60:
            out[-1] += " " + line
        else:
            out.append(line)
    return "\n".join(out)


# --------------------------------------------------------------------------- writing the answer
MINOR_NOTE = ("These sanctions are listed once for the whole table of minor offenses; the handbook text does not say "
              "which one applies to which rule.")
CATEGORY_NOTE = ("The handbook lists these sanctions once for the whole category; the text does not say which one "
                 "applies to which rule.")


def _label_topic(terms: list[str], words: list[str] | None = None) -> str:
    if words:
        shown = [w for w in words if w not in DETAIL_WORDS and w not in QUESTION_FILLER and w not in ACTION_WORDS
                 and not w.isdigit()]
        if shown:
            return " ".join(shown)
    return " ".join(terms) if terms else "this topic"


def write_offense_section(index: OffenseIndex, items: list[OffenseItem], related: list[OffenseItem]) -> list[str]:
    lines: list[str] = []
    for table in ("Minor", "Major"):
        mine = [i for i in items if i.table == table]
        if not mine:
            continue
        lines.append("")
        lines.append(f"{table.upper()} OFFENSES" + (" (lighter violations)" if table == "Minor" else " (serious violations)"))
        by_cat: dict[str, list[OffenseItem]] = {}
        for it in mine:
            by_cat.setdefault(it.category, []).append(it)
        for cat, group in by_cat.items():
            if table == "Major":
                lines.append(f"{cat}:")
            for it in group[:MAX_ITEMS_PER_GROUP]:
                lines.append(f"- No. {it.number}: {it.text}")
            sanc = sanctions_for(index, group[0])
            if sanc:
                lines.append(f"Sanctions the handbook lists for {'minor offenses' if table == 'Minor' else cat.lower()}:")
                for n, s in enumerate(sanc, 1):
                    lines.append(f"  {n}. {s}")
                lines.append(MINOR_NOTE if table == "Minor" else CATEGORY_NOTE)
            else:
                lines.append("The handbook text I have does not list a sanction for this part.")
    if related:
        lines.append("")
        lines.append("RELATED APPEARANCE RULES in the same handbook tables")
        for it in related[:6]:
            lines.append(f"- {it.table} offense, No. {it.number}: {it.text}")
    return lines


_CONFLICT_IGNORE = {"for", "and", "of", "the", "not", "in", "as", "by", "to", "boy", "a", "an", "with", "during"}


def classification_conflict(items: list[OffenseItem], groups: list[set[str]]) -> bool:
    """True when nearly the same rule is listed as both a minor and a major offense (e.g. 'blonde hair')."""
    def head(i: OffenseItem) -> set[str]:
        return word_set(i.text.split(" (listed under")[0]) - _CONFLICT_IGNORE
    minor = [head(i) for i in items if i.table == "Minor"]
    major = [head(i) for i in items if i.table == "Major"]
    for a in minor:
        for b in major:
            shared = a & b
            shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
            # the short rule is contained in the other short rule ("blonde hair" in "tattoo, blonde hair, earring")
            if len(shared) >= 2 and shorter <= longer and len(longer) <= 8 and any(shared & g for g in groups):
                return True
    return False


@dataclass
class DetailResult:
    text: str
    sources: list[dict]
    incomplete: bool = False


GENERIC_END = ("That is everything the handbook says about this topic. For details it does not give, please ask the "
               "concerned PGPC office, such as the Office of Student Affairs (OSA).")


def direct_hits(items: list[OffenseItem], terms: list[str]) -> list[OffenseItem]:
    """Items whose own words contain EVERY topic word ('cheat' matches 'cheating'). Only these may be called an
    offense in a short answer; a loose match (one shared word) never is."""
    stems = [_stem(t) for t in terms if len(t) >= 3]
    out = []
    for it in items:
        words = word_set(it.text.split(" (listed under")[0] + " " + " ".join(it.subs))
        if stems and all(any(w == st or (len(st) >= 4 and w.startswith(st)) for w in words) for st in stems):
            out.append(it)
    return out


def short_answer(hits: list[OffenseItem], consequence: bool = False) -> str | None:
    """A yes/no question gets a direct first line. The handbook lists these acts under its OFFENSES, which are the
    things students must not do, so a topic found there is 'not allowed'."""
    if not hits:
        return None
    classes = sorted({i.table.lower() for i in hits})
    where = " and ".join(f"its {c} offenses" for c in classes)
    if consequence:
        return (f"Short answer: the handbook lists this under {where}, so there are sanctions. "
                "The sanctions are below.")
    return (f"Short answer: no. The handbook lists this under {where}, so it is not allowed. "
            "The details and the sanctions are below.")


def compose_detail(topic: list[str], index: OffenseIndex, offense_items: list[OffenseItem],
                   related: list[OffenseItem], policy_blocks: list[tuple[str, list[str]]],
                   groups: list[set[str]], words: list[str] | None = None) -> DetailResult | None:
    """Pure: builds the complete answer text from already-found pieces. None when there is nothing to say."""
    if not offense_items and not policy_blocks:
        return None
    name = _label_topic(topic, words)
    out: list[str] = []
    if words and (is_permission_question(words) or asks_consequence(words)):
        lead = short_answer(direct_hits(offense_items, topic), consequence=asks_consequence(words))
        if lead:
            out += [lead, ""]
    out.append(f'Here is what the PGPC Student Handbook says about "{name}":')

    if policy_blocks:
        for label, blocks in policy_blocks:
            out.append("")
            out.append(label.upper())
            out.extend(tidy_block(b) for b in blocks)
    if offense_items:
        if not policy_blocks:
            out.append("")
            out.append('The handbook has no separate section for this topic. It appears in the rules on Student '
                       'Conduct and Discipline (Chapter XIII, Section 1: Offenses, Violation and Sanctions).')
        out.extend(write_offense_section(index, offense_items, related))
        if classification_conflict(offense_items, groups):
            out.append("")
            out.append("Note: the handbook lists related wording under both minor and major offenses, so the exact "
                       "classification of a case should be confirmed with the Office of Student Affairs (OSA).")
    out.append("")
    out.append(GENERIC_END)
    chapters = []
    if offense_items:
        chapters.append("Chapter XIII (Student Conduct and Discipline)")
    for label, _ in policy_blocks:
        m = re.search(r"\((Chapter [IVXL]+)\)\s*$", label)
        if m and not any(c.startswith(m.group(1)) for c in chapters):
            chapters.append(m.group(1))
    out.append("")
    out.append("Source: PGPC Student Handbook" + (" - " + ", ".join(chapters) if chapters else ""))
    sources = [{"type": "handbook", "id": None, "title": "Student Handbook, Chapter XIII: Student Conduct and "
                "Discipline", "source": "PGPC Student Handbook"}] if offense_items else []
    sources += [{"type": "handbook", "id": None, "title": label, "source": "PGPC Student Handbook"}
                for label, _ in policy_blocks]
    return DetailResult("\n".join(out).strip(), sources)


# --------------------------------------------------------------------------- database part
CONDUCT_MARKER = "offenses, violation and sanctions"
_PART = re.compile(r"\s*\(part \d+\)\s*$", re.I)


def _logical_sections(rows) -> dict[tuple, str]:
    """Handbook sections are split into '(part n)' rows. Join them back in order."""
    joined: dict[tuple, list[str]] = {}
    order: list[tuple] = []
    for r in sorted(rows, key=lambda r: r.id):
        key = (r.section_number or "", _PART.sub("", r.title or ""), r.category or "")
        if key not in joined:
            joined[key] = []
            order.append(key)
        joined[key].append(r.content or "")
    return {k: "\n\n".join(joined[k]) for k in order}

# --------------------------------------------------------------------------- the dress code family
# "uniform", "attire", "what to wear", "dress code" and "the uniform schedule" are ONE policy in the handbook
# (Dress Code Policy on Washdays + prohibited attire + exemptions + sanctions + the weekly schedule).
DRESS_WORDS = {"code", "uniform", "uniforms", "attire", "dress", "outfit", "outfits", "clothes", "clothing", "polo", "washday",
               "washdays", "wash", "wear", "wearing", "wore", "suit", "suits", "corporate", "shirt", "shirts", "wearin"}
SCHEDULE_WORDS = {"schedule", "schedules", "day", "days", "when", "week", "weekly", "today", "tomorrow", "monday",
                  "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "mon", "tue", "wed", "thu", "fri", "sat"}
_DRESS_FILLER = {"that", "be", "being", "i", "we", "students", "student", "should", "to", "on", "in", "a", "an", "the",
                 "pgpc", "at", "for", "do", "what", "is", "are", "my", "our", "school", "college", "campus", "every",
                 "each", "any", "kind", "type", "types", "allowed", "required", "prescribed", "official", "of", "and",
                 "me", "tell", "show", "give", "please", "ba", "ang", "sa", "ng", "which", "whats", "wat", "can", "will"}
DRESS_START = "dress code policy on washdays"
DRESS_SCHEDULE = "schedule for wearing school uniforms"


def is_dress_question(words: Iterable[str]) -> bool:
    """True for a bare uniform / attire / what-to-wear / schedule question, not for 'can I wear sandals'."""
    w = [x for x in words]
    if not set(w) & DRESS_WORDS:
        return False
    rest = [x for x in w if x not in DRESS_WORDS and x not in SCHEDULE_WORDS and x not in _DRESS_FILLER
            and x not in DETAIL_WORDS and x not in QUESTION_FILLER and x not in ACTION_WORDS and len(x) > 1]
    return not rest


def asks_dress_schedule(words: Iterable[str]) -> bool:
    return bool(set(words) & SCHEDULE_WORDS)


def _dress_lines(text: str) -> list[str] | None:
    lines = text.splitlines()
    low = [l.strip().lower() for l in lines]
    if DRESS_START not in low:
        return None
    start = low.index(DRESS_START)
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if re.match(r"^-{3,}$", low[j]) or low[j].startswith("page "):
            end = j
            break
    return [l.rstrip() for l in lines[start:end]]


def _nice(line: str) -> str:
    line = line.strip()
    return "- " + line[1:].strip() if line.startswith(". ") else line


def dress_code_answer(sections: dict, words: list[str]) -> "DetailResult | None":
    chunk = None
    for key, text in sections.items():
        chunk = _dress_lines(text)
        if chunk:
            break
    if not chunk:
        return None
    low = [l.strip().lower() for l in chunk]
    cut = low.index(DRESS_SCHEDULE) if DRESS_SCHEDULE in low else len(chunk)
    main, sched = chunk[:cut], chunk[cut + 1:]
    kept = []
    for l in sched:                                    # the schedule is the bullet lines right under its heading
        if not l.strip():
            if kept:
                break
            continue
        if not l.strip().startswith((". ", "- ")):
            break
        kept.append(l)
    sched_txt = "\n".join(_nice(l) for l in kept)
    sources = [{"type": "handbook", "id": None, "title": "Dress Code Policy (Chapter XVI)",
                "source": "PGPC Student Handbook"}]
    if asks_dress_schedule(words) and sched_txt:
        text = ("Here is the weekly schedule for what to wear, from the PGPC Student Handbook:\n\n"
                "Schedule for Wearing School Uniforms (Chapter XVI)\n" + sched_txt +
                "\n\nAsk \"what is the uniform\" or \"dress code\" to see what the uniform is and what is not allowed."
                "\n\nSource: PGPC Student Handbook - Chapter XVI")
        return DetailResult(text, sources)
    body: list[str] = []
    for l in main[1:]:
        if not l.strip():
            body.append("")
            continue
        line = _nice(l)
        starts_new = line.startswith("- ") or bool(re.match(r"^\d+\.\s", line)) or not body or not body[-1]
        if starts_new:
            body.append(line)
        else:
            body[-1] += " " + line                        # the scan broke one sentence over several lines: join it
    body_txt = re.sub(r"\n{3,}", "\n\n", "\n".join(body)).strip()
    text = ('Here is what the PGPC Student Handbook says about the uniform and dress code:\n\n'
            "DRESS CODE POLICY ON WASHDAYS (CHAPTER XVI)\n" + body_txt)
    if sched_txt:
        text += "\n\nSchedule for Wearing School Uniforms\n" + sched_txt
    text += "\n\nSource: PGPC Student Handbook - Chapter XVI"
    return DetailResult(text, sources)


# --------------------------------------------------------------------------- a topic that is a heading of its own
_HEAD_PREFIX = re.compile(r"^(?:[a-z]{5,8}\s+[a-z0-9]{1,2}\s*[-\u2013:.]\s*|[a-z]\)\s*|\d{1,2}[.)]\s*)", re.I)


def _heading_key(line: str) -> str:
    line = _HEAD_PREFIX.sub("", line.strip())
    words = re.sub(r"[^a-z0-9 ]", "", line.lower().replace("'", "").replace("\u2019", "")).split()
    return " ".join(_stem(w) for w in words if w not in {"of", "the", "and", "for", "a", "an"})


def heading_topic_answer(sections: dict, terms: list[str]) -> "DetailResult | None":
    """'what is the dean's list': the handbook has a heading called exactly that ('b) Dean's List'). Show the text under
    it, up to the next heading. Only for a short heading that equals the whole topic."""
    want = " ".join(_stem(t.lower()) for t in terms)
    if len(want) < 6 or len(terms) < 2:
        return None
    for key, text in sections.items():
        if _heading_key(key[1] or "") == want and text.strip():          # the section's own title is the topic
            title = _HEAD_PREFIX.sub("", (key[1] or "").strip()).strip()
            chapter = key[2].split(":")[0] if key[2] else "Handbook"
            body = tidy_block(text.strip()[:MAX_POLICY_CHARS])
            out = (f'Here is what the PGPC Student Handbook says about "{title}":\n\n{title.upper()} ({chapter.upper()})\n'
                   f"{body}\n\nSource: PGPC Student Handbook - {chapter}")
            return DetailResult(out, [{"type": "handbook", "id": None, "title": f"{title} ({chapter})",
                                       "source": "PGPC Student Handbook"}])
        lines = text.splitlines()
        for i, raw in enumerate(lines):
            if len(raw.strip()) > 60 or re.match(r"^\s*\d+\s*[.)]", raw) or _heading_key(raw) != want:
                continue                                      # a numbered line is a rule in a list, not a heading
            body: list[str] = []
            for nxt in lines[i + 1:]:
                t = nxt.strip()
                if body and (re.match(r"^[a-z]\)\s", t, re.I) or _SECTION_LINE.match(t) or re.match(r"^PAGE\s+\d+", t, re.I)):
                    break
                if t:
                    body.append(t)
                if len(body) > 40:
                    break
            if not body:
                continue
            title = _HEAD_PREFIX.sub("", raw.strip()).strip()
            chapter = key[2].split(":")[0] if key[2] else "Handbook"
            text_out = (f'Here is what the PGPC Student Handbook says about "{title}":\n\n{title.upper()} ({chapter.upper()})\n'
                        + "\n".join(body) + f"\n\nSource: PGPC Student Handbook - {chapter}")
            return DetailResult(text_out, [{"type": "handbook", "id": None, "title": f"{title} ({chapter})",
                                            "source": "PGPC Student Handbook"}])
    return None


def build_detail_answer(db, question_words: list[str], synonyms: dict[str, list[str]] | None = None,
                        require_titled: bool = False):
    """Returns a DetailResult, or None when the topic is not found in the handbook (the normal answer is used)."""
    from sqlalchemy import select
    from app.models import HandbookSection

    terms = topic_terms(question_words)
    rows = list(db.scalars(select(HandbookSection)))
    if not rows:
        return None
    sections = _logical_sections(rows)
    if not (is_permission_question(question_words) or asks_consequence(question_words)):
        exact_heading = heading_topic_answer(sections, terms)
        if exact_heading is not None:
            return exact_heading
    if is_dress_question(question_words):
        dress = dress_code_answer(sections, question_words)
        if dress is not None:
            return dress
    groups = term_groups(terms, synonyms)
    if not groups:
        return None
    exact = {_stem(t) for t in terms}

    index = OffenseIndex()
    conduct_keys = [k for k in sections if CONDUCT_MARKER in k[1].lower()]
    for k in conduct_keys:
        part = parse_offenses(sections[k])
        index.items += part.items
        for key, val in part.sanctions.items():
            index.sanctions.setdefault(key, []).extend(v for v in val if v not in index.sanctions.get(key, []))
        index.category_names.update(part.category_names)

    offense_items = find_offense_items(index, groups, strict=True)
    relaxed_items = find_offense_items(index, groups) if len(groups) > 1 and not offense_items else []
    related: list[OffenseItem] = []
    rel_words = {w for t in terms for w in RELATED.get(t, ())}
    if offense_items and rel_words:
        rel_groups = [{_stem(w), *[_stem(v) for v in VARIANTS.get(w, [])]} for w in rel_words]
        taken = {id(i) for i in offense_items}
        related = [i for i in index.items if id(i) not in taken and any(word_set(i.text) & g for g in rel_groups)]

    policy_blocks: list[tuple[str, list[str]]] = []
    scored = []
    for key, text in sections.items():
        if key in conduct_keys:
            continue
        blocks = pick_policy_blocks(split_blocks(text), groups, exact)
        if blocks:
            strength = sum(len(groups_hit(word_set(b), groups)) for b in blocks)
            scored.append((strength, key, blocks))
    scored.sort(key=lambda t: -t[0])
    # Prefer sections whose own title/heading is about the topic ("Absences and Tardiness" for "attendance") over
    # sections that merely mention the word in passing ("Attendance is a must" in the cleanliness rules).
    def tier(key, blocks) -> int:
        """0: the title/heading contains the topic word itself ('Pre-Enrollment Requirements' for 'enrollment');
        1: only a synonym ('Absences and Tardiness' for 'attendance'); 2: the word is just mentioned in passing."""
        head = re.sub(r"^\d+\.\s*", "", blocks[0].splitlines()[0].strip()) if blocks else ""
        head = head if (looks_like_heading(head) or (_SECTION_LINE.match(head) and len(head) <= 70)) else ""
        ws = word_set(key[1] + " " + head)
        if ws & exact:
            return 0
        return 1 if ws & set().union(*groups) else 2
    ranked = sorted(((tier(k, b), -st, k, b) for st, k, b in scored), key=lambda t: (t[0] == 2, t[1], t[0]))
    titled = [(k, b) for t, _, k, b in ranked if t < 2]
    chosen_sections = titled or [(k, b) for _, _, k, b in ranked]
    for key, blocks in chosen_sections[:2]:
        chapter = key[2].split(":")[0] if key[2] else "Handbook"
        first = re.sub(r"^\d+\.\s*", "", blocks[0].splitlines()[0].strip()) if blocks else ""
        first = fix_ocr_heading(first)
        title = re.sub(r"^(?:Section|Bection|Beetion)\s+\w+\s*[-\u2013:.]\s*", "", key[1] or "").strip()
        first = re.sub(r"^(?:Section|Bection|Beetion)\s+\w+\s*[-\u2013:.]\s*", "", first).strip()
        label = f"{first} ({chapter})" if looks_like_heading(first) else (f"{title} ({chapter})" if title else chapter)
        if looks_like_heading(first) and blocks:
            rest = "\n".join(blocks[0].splitlines()[1:]).strip()
            blocks = ([rest] if rest else []) + list(blocks[1:])        # the heading is the label already
        if blocks:
            policy_blocks.append((label, blocks))

    if require_titled and not (titled or direct_hits(offense_items, terms)):
        return None                                    # a rescue for an unsure intent: only when the handbook clearly has the topic
    if relaxed_items and not policy_blocks:
        offense_items = relaxed_items                  # only a loose match exists, and nothing else says more
    return compose_detail(terms, index, offense_items, related, policy_blocks, groups, question_words)


def groups_hit(words: set[str], groups: list[set[str]]) -> list[set[str]]:
    return [g for g in groups if words & g]


# --------------------------------------------------------------------------- an answer that misses part of the question
def missing_topic_words(text: str, terms: list[str], synonyms: dict[str, list[str]] | None = None) -> list[str]:
    """Topic words (with their variants and synonyms) that appear nowhere in the answer text. Two or more topic words
    are needed to judge: 'late return books' answered by a registration passage that has 'late' but neither 'return'
    nor 'books' is not an answer. One missing word out of one is judged by the normal match instead."""
    generic = {"available", "offered", "offer", "offers", "exist", "list", "types", "kinds", "there"}
    terms = [t for t in terms if t not in generic]
    if len(terms) < 2:
        return []
    have = word_set(text)

    def close(a: str, b: str) -> bool:                      # miss / missed, drop / dropping, absent / absence
        if a == b:
            return True
        n = min(len(a), len(b))
        return n >= 4 and (a.startswith(b) or b.startswith(a) or a[:5] == b[:5] and n >= 5)

    out = []
    for t, g in zip(terms, term_groups(terms, synonyms)):
        if not any(close(w, x) for x in g for w in have):
            out.append(t)
    return out


def closest_label(sources: list[dict]) -> str | None:
    for src in sources:
        title = re.sub(r"\s*\((?:Chapter|CHAPTER)[^)]*\)\s*$", "", src.get("title") or "").strip()
        if title and not title.lower().startswith("student handbook"):
            return title
    return None
