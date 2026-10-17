from fastapi import HTTPException

from app.api.crud_factory import build_crud_routers
from app.models import QuickLink
from app.schemas.quick_link import QuickLinkCreate, QuickLinkOut, QuickLinkUpdate
from app.services.quick_links import clean_keywords, valid_url
from app.utils.validators import conflict, is_duplicate


def check(db, v, exclude_id):
    if not valid_url(v["url"]):
        raise HTTPException(422, "The link must start with http:// or https:// and have no spaces.")
    if not clean_keywords(v["keywords"]):
        raise HTTPException(422, "Add at least one keyword (words a student might type).")
    if is_duplicate(db, QuickLink, {"title": v["title"]}, exclude_id):
        conflict("A quick link with this title already exists.")


router, admin_router = build_crud_routers(
    path="quick-links", singular="quick link", plural="quick links", model=QuickLink,
    create_schema=QuickLinkCreate, update_schema=QuickLinkUpdate, out_schema=QuickLinkOut,
    search_fields=("title", "keywords", "url"), check=check,
    public_filter=QuickLink.is_active.is_(True), tag="Quick links")
