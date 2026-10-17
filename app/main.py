"""PGPC SmartGuide - application entry point."""
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api import admin, answer, auth, chat, documents, employees, facilities, faqs, handbook, health, history, library, offices, positions, quick_links, rooms, search
from app.core.config import get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

settings = get_settings()

# Refuse to run in production mode with a missing or weak signing key.
if not settings.debug and (settings.secret_key == "change-me" or len(settings.secret_key) < 32):
    raise RuntimeError("Set SECRET_KEY in .env to a random string of at least 32 characters (or DEBUG=true for local dev).")

app = FastAPI(
    title=settings.app_name,
    description="PGPC-specific institutional chatbot API (Padre Garcia Polytechnic College).",
    version="0.13.0",
)

@app.on_event("startup")
def update_old_database() -> None:
    """A database made by an earlier version gets the new tables/columns automatically (additive only)."""
    try:
        from app.database.database import engine
        from app.database.ensure_schema import ensure_schema
        ensure_schema(engine)
    except Exception:                                    # never stop the server because of this
        logging.getLogger("pgpc.schema").exception("could not update the database; run: alembic upgrade head")


app.include_router(health.router)
app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(search.router)
app.include_router(answer.router)
app.include_router(chat.router)
app.include_router(chat.admin_router)
app.include_router(documents.router)

# Each data module gives a public (read-only) router and an admin (write) router.
for module in (employees, positions, offices, rooms, facilities, handbook, history, faqs, library, quick_links):
    app.include_router(module.router)
    app.include_router(module.admin_router)

# Serve the frontend last so it never shadows /api, /docs or /redoc.
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
