from app.api.crud_factory import build_crud_routers
from app.models import HandbookSection
from app.schemas.handbook import HandbookCreate, HandbookOut, HandbookUpdate
from app.utils.validators import conflict, is_duplicate


def check(db, v, exclude_id):
    same = {"title": v["title"], "section_number": v.get("section_number"), "category": v.get("category")}
    if is_duplicate(db, HandbookSection, same, exclude_id):
        conflict("A handbook section with the same title, number and category already exists.")


router, admin_router = build_crud_routers(
    path="handbook", singular="handbook section", plural="handbook sections", model=HandbookSection,
    create_schema=HandbookCreate, update_schema=HandbookUpdate, out_schema=HandbookOut,
    search_fields=("title", "content", "category"), check=check, tag="Handbook")
