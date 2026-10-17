from app.schemas.common import REQUIRED, Stamped, make_create_update, opt, req

HandbookCreate, HandbookUpdate = make_create_update("Handbook", {
    "title": (req(300), REQUIRED),
    "section_number": (opt(100), None),
    "content": (req(100000, min_len=10), REQUIRED),   # empty sections are rejected
    "category": (opt(300), None),
    "source_document": (opt(200), None),
    "source_page": (opt(50), None),
})


class HandbookOut(Stamped):
    title: str
    section_number: str | None
    content: str
    category: str | None
    source_document: str | None
    source_page: str | None
