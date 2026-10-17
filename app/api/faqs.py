from app.api.crud_factory import build_crud_routers
from app.models import FAQ
from app.schemas.faq import FAQCreate, FAQOut, FAQUpdate
from app.utils.validators import conflict, is_duplicate


def check(db, v, exclude_id):
    if is_duplicate(db, FAQ, {"question": v["question"]}, exclude_id):
        conflict("This FAQ question already exists.")


# Inactive FAQs are unpublished drafts: the public API (and later the chatbot) never sees them.
router, admin_router = build_crud_routers(
    path="faqs", singular="FAQ", plural="FAQs", model=FAQ,
    create_schema=FAQCreate, update_schema=FAQUpdate, out_schema=FAQOut,
    search_fields=("question", "answer", "keywords", "category"), check=check,
    public_filter=FAQ.is_active.is_(True), tag="FAQs")
