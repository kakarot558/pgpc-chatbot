"""Public answer endpoint (Phase 8): a question in, a written answer out. Chat sessions come in the next phase."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.services.answer_generator import generate_answer

router = APIRouter(prefix="/api/v1", tags=["Answer"])


@router.get("/answer", summary="Ask PGPC SmartGuide a question",
            description="Classifies the question, retrieves matching PGPC records and writes the answer. "
                        "Answers come only from stored PGPC records; when nothing matches, the reply says so. "
                        "Inactive FAQs and archived documents are never used.")
def answer(q: str = Query(..., min_length=1, max_length=2000, description="The question"),
           db: Session = Depends(get_db)):
    result = generate_answer(db, q)
    return {"success": True, "question": q.strip(), **result.as_dict()}
