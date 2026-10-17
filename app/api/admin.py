"""Admin-only routes. Every route here depends on require_admin.
The CRUD routers added in Phase 4 will follow the same pattern."""
from fastapi import APIRouter, Depends

from app.core.dependencies import require_admin
from app.models import User
from app.schemas.auth import UserOut

router = APIRouter(prefix="/api/v1/admin", tags=["Admin"], dependencies=[Depends(require_admin)])


@router.get("/ping", summary="Admin access check",
            description="Succeeds only for an active administrator. Used to verify role-based access.")
def admin_ping():
    return {"success": True, "message": "Admin access confirmed."}
