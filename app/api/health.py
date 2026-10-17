from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.database.database import get_db

router = APIRouter(prefix="/api/v1", tags=["Health"])


@router.get("/health", summary="Health check",
            description="Reports whether the PGPC SmartGuide API and its database are reachable.")
def health_check(db: Session = Depends(get_db)):
    settings = get_settings()
    try:
        db.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception:
        # Never leak connection strings or driver errors to the client.
        db_status = "unavailable"
    return {
        "success": db_status == "connected",
        "app": settings.app_name,
        "api": "running",
        "database": db_status,
    }
