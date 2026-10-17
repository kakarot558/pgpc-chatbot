from app.schemas.common import REQUIRED, Stamped, make_create_update, opt, req

FAQCreate, FAQUpdate = make_create_update("FAQ", {
    "question": (req(2000), REQUIRED),
    "answer": (req(10000), REQUIRED),
    "category": (opt(100), None),
    "keywords": (opt(2000), None),
    "source": (opt(200), None),
    "is_active": (bool, True),
})


class FAQOut(Stamped):
    question: str
    answer: str
    category: str | None
    keywords: str | None
    source: str | None
    is_active: bool
