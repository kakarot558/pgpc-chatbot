from app.schemas.common import REQUIRED, Stamped, make_create_update, opt, req

QuickLinkCreate, QuickLinkUpdate = make_create_update("QuickLink", {
    "title": (req(200), REQUIRED),
    "keywords": (req(2000), REQUIRED),
    "url": (req(500), REQUIRED),
    "message": (opt(2000), None),
    "is_active": (bool, True),
})


class QuickLinkOut(Stamped):
    title: str
    keywords: str
    url: str
    message: str | None
    is_active: bool
