from app.api.crud_factory import build_crud_routers
from app.models import SchoolHistory
from app.schemas.history import HistoryCreate, HistoryOut, HistoryUpdate
from app.utils.validators import conflict, is_duplicate


def check(db, v, exclude_id):
    if is_duplicate(db, SchoolHistory, {"title": v["title"], "year": v.get("year")}, exclude_id):
        conflict("A history entry with this title and year already exists.")


router, admin_router = build_crud_routers(
    path="history", singular="history entry", plural="history entries", model=SchoolHistory,
    create_schema=HistoryCreate, update_schema=HistoryUpdate, out_schema=HistoryOut,
    search_fields=("title", "content", "year"), check=check, tag="History")
