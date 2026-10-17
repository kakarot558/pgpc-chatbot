from app.schemas.common import REQUIRED, Stamped, make_create_update, opt, req

LibraryCreate, LibraryUpdate = make_create_update("Library", {
    "title": (req(300), REQUIRED),
    "author": (opt(200), None),
    "isbn": (opt(30), None),
    "category": (opt(100), None),
    "publisher": (opt(200), None),
    "year": (opt(10), None),
    "availability": (opt(50), None),
    "location": (opt(150), None),
})


class LibraryOut(Stamped):
    title: str
    author: str | None
    isbn: str | None
    category: str | None
    publisher: str | None
    year: str | None
    availability: str | None
    location: str | None
