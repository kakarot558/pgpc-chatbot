"""Public search endpoint: shows what the retrieval step finds for a question (the answer endpoint writes the reply)."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.database.database import get_db
from app.services.intent_classifier import get_intent_classifier
from app.services.retrieval import retrieve
from app.utils.text_cleaner import clean_user_input

router = APIRouter(prefix="/api/v1", tags=["Search"])


@router.get("/search", summary="Classify a question and retrieve matching PGPC records",
            description="Runs the intent classifier and the retrieval step. Inactive FAQs and archived "
                        "documents are never searched.")
def search(q: str = Query(..., min_length=1, max_length=2000, description="The question"),
           top_k: int = Query(5, ge=1, le=10), db: Session = Depends(get_db)):
    question = clean_user_input(q)[: get_settings().max_question_chars]
    intent = get_intent_classifier().predict(question)
    result = retrieve(db, question, intent.intent if intent.intent != "unknown" else None, top_k=top_k)
    return {"success": True, "question": question,
            "intent": {"name": intent.intent, "confidence": intent.confidence},
            "keywords": result.keywords, "found": result.found, "confidence": result.confidence,
            "total_matches": result.total_matches, "searched_sources": result.preferred_sources,
            "results": [h.as_dict() for h in result.hits]}
