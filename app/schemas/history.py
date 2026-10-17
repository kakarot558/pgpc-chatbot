from app.schemas.common import REQUIRED, Stamped, make_create_update, opt, req

HistoryCreate, HistoryUpdate = make_create_update("History", {
    "title": (req(300), REQUIRED),
    "year": (opt(20), None),
    "content": (req(100000, min_len=10), REQUIRED),
    "source": (opt(200), None),
})


class HistoryOut(Stamped):
    title: str
    year: str | None
    content: str
    source: str | None
