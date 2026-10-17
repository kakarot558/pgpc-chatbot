"""Phase 11: document upload and management (admin only). Uploaded text becomes searchable knowledge chunks."""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.dependencies import require_admin
from app.database.database import get_db
from app.models import Document, KnowledgeChunk, User
from app.services import document_service as svc

logger = logging.getLogger("pgpc.documents")
router = APIRouter(prefix="/api/v1/admin/documents", tags=["Admin - Documents"],
                   dependencies=[Depends(require_admin)])


class DocumentUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=300)
    description: str | None = Field(None, max_length=5000)
    source: str | None = Field(None, max_length=200)


def _blank(v: str | None) -> str | None:
    return (v or "").strip() or None


def _iso(value: datetime | None) -> str | None:
    """SQLite returns naive datetimes; they are stored in UTC, so label them as such for the browser."""
    if value is None:
        return None
    return (value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value).isoformat()


def _out(doc: Document, chunks: int) -> dict:
    return {"id": doc.id, "title": doc.title, "file_name": doc.file_name, "file_type": doc.file_type,
            "description": doc.description, "source": doc.source, "status": doc.status, "chunks": chunks,
            "uploaded_by": doc.uploaded_by,
            "uploaded_at": _iso(doc.uploaded_at), "updated_at": _iso(doc.updated_at)}


def _chunk_count(db: Session, doc_id: int) -> int:
    return db.scalar(select(func.count(KnowledgeChunk.id)).where(KnowledgeChunk.document_id == doc_id)) or 0


def _get(db: Session, doc_id: int) -> Document:
    doc = db.get(Document, doc_id)
    if doc is None:
        raise HTTPException(404, "Document not found.")
    return doc


def _fail(e: svc.DocumentError):
    raise HTTPException(e.status, e.message)


@router.post("", status_code=201, summary="Upload a document",
             description="PDF, DOCX or TXT up to MAX_UPLOAD_SIZE_MB. The text is cut into passages and becomes "
                         "searchable at once. Set replaces_id to upload a new version: the old one is archived, "
                         "not deleted.")
async def upload_document(file: UploadFile = File(...), title: str | None = Form(None, max_length=300),
                          description: str | None = Form(None, max_length=5000),
                          source: str | None = Form(None, max_length=200),
                          category: str | None = Form(None, max_length=100),
                          replaces_id: int | None = Form(None, ge=1),
                          db: Session = Depends(get_db), admin_user: User = Depends(require_admin)):
    limit = get_settings().max_upload_size_mb * 1024 * 1024
    data = await file.read(limit + 1)          # never read more than the limit + 1 byte
    try:
        doc = svc.create_document(db, data=data, original_name=file.filename or "", title=_blank(title),
                                  description=_blank(description), source=_blank(source),
                                  category=_blank(category), user_id=admin_user.id, replaces_id=replaces_id)
    except svc.DocumentError as e:
        _fail(e)
    return _out(doc, _chunk_count(db, doc.id))


@router.get("", summary="List documents")
def list_documents(status: str | None = Query(None, pattern="^(active|archived)$"),
                   q: str | None = Query(None, max_length=100), skip: int = Query(0, ge=0),
                   limit: int = Query(50, ge=1, le=100), db: Session = Depends(get_db)):
    stmt = select(Document)
    if status:
        stmt = stmt.where(Document.status == status)
    if q and q.strip():
        stmt = stmt.where(Document.title.icontains(q.strip(), autoescape=True))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    docs = db.scalars(stmt.order_by(Document.id.desc()).offset(skip).limit(limit)).all()
    return {"items": [_out(d, _chunk_count(db, d.id)) for d in docs], "total": total, "skip": skip, "limit": limit}


@router.get("/{doc_id}", summary="Get one document")
def get_document(doc_id: int, db: Session = Depends(get_db)):
    doc = _get(db, doc_id)
    return _out(doc, _chunk_count(db, doc.id))


@router.get("/{doc_id}/chunks", summary="Preview the searchable passages of a document")
def document_chunks(doc_id: int, skip: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100),
                    db: Session = Depends(get_db)):
    _get(db, doc_id)
    rows = db.scalars(select(KnowledgeChunk).where(KnowledgeChunk.document_id == doc_id)
                      .order_by(KnowledgeChunk.chunk_index).offset(skip).limit(limit)).all()
    return {"total": _chunk_count(db, doc_id), "skip": skip, "limit": limit,
            "items": [{"id": c.id, "index": c.chunk_index, "page": c.source_page, "keywords": c.keywords,
                       "category": c.category, "content": c.content} for c in rows]}


@router.get("/{doc_id}/file", summary="Download the original file")
def download_document(doc_id: int, db: Session = Depends(get_db)):
    doc = _get(db, doc_id)
    path = svc.stored_path(doc.id, doc.file_type)
    if not path.exists():
        raise HTTPException(404, "The stored file is missing.")
    return FileResponse(path, filename=doc.file_name)


@router.put("/{doc_id}", summary="Edit title, description or source")
def update_document(doc_id: int, data: DocumentUpdate, db: Session = Depends(get_db)):
    doc = _get(db, doc_id)
    changes = data.model_dump(exclude_unset=True)
    if "title" in changes:
        title = (changes["title"] or "").strip()
        if not title:
            raise HTTPException(422, "The title cannot be empty.")
        if doc.status == "active" and svc.title_in_use(db, title, exclude_id=doc.id):
            raise HTTPException(409, "An active document with that title already exists.")
        doc.title = title
    for key in ("description", "source"):
        if key in changes:
            setattr(doc, key, _blank(changes[key]))
    # Passages show the document's title and source, so keep them in step.
    for c in db.scalars(select(KnowledgeChunk).where(KnowledgeChunk.document_id == doc.id)):
        c.title, c.source = doc.title[:300], svc.chunk_source(doc)
    db.commit()
    db.refresh(doc)
    return _out(doc, _chunk_count(db, doc.id))


@router.post("/{doc_id}/archive", summary="Archive (stop using) a document",
             description="Archived documents are kept but never used to answer questions.")
def archive_document(doc_id: int, db: Session = Depends(get_db)):
    doc = _get(db, doc_id)
    doc.status = "archived"
    db.commit()
    db.refresh(doc)
    return _out(doc, _chunk_count(db, doc.id))


@router.post("/{doc_id}/restore", summary="Make an archived document active again")
def restore_document(doc_id: int, db: Session = Depends(get_db)):
    doc = _get(db, doc_id)
    if svc.title_in_use(db, doc.title, exclude_id=doc.id):
        raise HTTPException(409, "Another active document has the same title. Archive it or rename this one first.")
    doc.status = "active"
    db.commit()
    db.refresh(doc)
    return _out(doc, _chunk_count(db, doc.id))


@router.post("/{doc_id}/reprocess", summary="Rebuild the searchable passages from the stored file")
def reprocess_document(doc_id: int, db: Session = Depends(get_db)):
    doc = _get(db, doc_id)
    try:
        n = svc.reprocess(db, doc)
    except svc.DocumentError as e:
        _fail(e)
    return {"success": True, "chunks": n}


@router.delete("/{doc_id}", summary="Permanently delete an archived document",
               description="Only archived documents can be deleted. Archive first, so nothing in use disappears.")
def delete_document(doc_id: int, db: Session = Depends(get_db), admin_user: User = Depends(require_admin)):
    doc = _get(db, doc_id)
    if doc.status != "archived":
        raise HTTPException(409, "Archive the document first. Only archived documents can be deleted.")
    db.query(KnowledgeChunk).filter(KnowledgeChunk.document_id == doc.id).delete()
    ftype = doc.file_type
    db.delete(doc)
    db.commit()
    svc.remove_file(doc_id, ftype)
    logger.info("document deleted id=%s by user_id=%s", doc_id, admin_user.id)
    return {"success": True, "message": "Document deleted."}
