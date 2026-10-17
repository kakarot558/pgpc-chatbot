"""Optional module: library catalogue."""
from app.api.crud_factory import build_crud_routers
from app.models import LibraryBook
from app.schemas.library import LibraryCreate, LibraryOut, LibraryUpdate
from app.utils.validators import conflict, is_duplicate


def check(db, v, exclude_id):
    if v.get("isbn") and is_duplicate(db, LibraryBook, {"isbn": v["isbn"]}, exclude_id):
        conflict("A book with this ISBN already exists.")


router, admin_router = build_crud_routers(
    path="library", singular="book", plural="library books", model=LibraryBook,
    create_schema=LibraryCreate, update_schema=LibraryUpdate, out_schema=LibraryOut,
    search_fields=("title", "author", "isbn", "category"), check=check, tag="Library")
