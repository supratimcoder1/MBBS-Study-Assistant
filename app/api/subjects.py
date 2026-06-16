"""
Subjects API Routes
CRUD for subjects and PDF upload / processing pipeline.
"""

import os
import uuid
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Form, BackgroundTasks
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.database import get_db
from app.models.database import Subject, DocumentUpload, HierarchyNode
from app.services.pdf_processor import process_pdf

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/subjects", tags=["subjects"])

# Directory where uploaded PDFs are stored
UPLOADS_DIR = Path("/tmp/uploads") if (os.environ.get("VERCEL") == "1" or os.path.exists("/var/task")) else Path("uploads")


# ── GET / — List subjects ──────────────────────────────────────────────────
@router.get("/")
async def list_subjects(
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all subjects belonging to the authenticated user."""
    user_id = user["sub"]
    subjects = (
        db.query(Subject)
        .filter(Subject.user_id == user_id)
        .order_by(Subject.created_at.desc())
        .all()
    )
    return [
        {
            "id": str(s.id),
            "name": s.name,
            "book_title": s.book_title,
            "processing_status": s.processing_status,
            "created_at": str(s.created_at),
        }
        for s in subjects
    ]


# ── POST / — Create subject + upload PDF ───────────────────────────────────
@router.post("/")
async def create_subject(
    background_tasks: BackgroundTasks,
    name: str = Form(...),
    book_title: str = Form(""),
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Create a new subject, persist the uploaded PDF, and kick off
    background processing (TOC extraction → hierarchy → chunking → indexing).
    """
    user_id = uuid.UUID(user["sub"]) if isinstance(user["sub"], str) else user["sub"]

    # Validate file type
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")

    # Save uploaded file
    UPLOADS_DIR.mkdir(exist_ok=True)
    file_id = str(uuid.uuid4())
    safe_filename = f"{file_id}_{file.filename}"
    file_path = UPLOADS_DIR / safe_filename

    contents = await file.read()
    with open(file_path, "wb") as f:
        f.write(contents)

    # Create subject record
    subject = Subject(
        id=uuid.uuid4(),
        user_id=user_id,
        name=name,
        book_title=book_title or file.filename,
        file_path=str(file_path),
        processing_status="processing",
    )
    db.add(subject)
    db.flush()

    # Create document_upload record
    upload = DocumentUpload(
        id=uuid.uuid4(),
        subject_id=subject.id,
        filename=file.filename,
        status="uploaded",
        progress=0,
    )
    db.add(upload)
    db.commit()

    # Launch background processing
    background_tasks.add_task(
        _run_pdf_pipeline,
        file_path=str(file_path),
        subject_id=str(subject.id),
        upload_id=str(upload.id),
    )

    return {
        "id": str(subject.id),
        "name": subject.name,
        "processing_status": subject.processing_status,
        "upload_id": str(upload.id),
        "message": "Subject created – processing started",
    }


def _run_pdf_pipeline(file_path: str, subject_id: str, upload_id: str):
    """
    Wrapper that opens a fresh DB session for the background task.
    The main request session will have been closed by the time this runs.
    """
    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        process_pdf(file_path, subject_id, db, upload_id)
    finally:
        db.close()


# ── GET /{subject_id} — Subject details + hierarchy tree ───────────────────
@router.get("/{subject_id}")
async def get_subject(
    subject_id: str,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return subject details including its full hierarchy tree."""
    user_id = user["sub"]
    subject = (
        db.query(Subject)
        .filter(Subject.id == subject_id, Subject.user_id == user_id)
        .first()
    )
    if not subject:
        raise HTTPException(status_code=404, detail="Subject not found")

    # Build hierarchy tree
    nodes = (
        db.query(HierarchyNode)
        .filter(HierarchyNode.subject_id == subject_id)
        .order_by(HierarchyNode.level, HierarchyNode.page_start)
        .all()
    )

    hierarchy = [
        {
            "id": str(n.id),
            "parent_id": str(n.parent_id) if n.parent_id else None,
            "title": n.title,
            "node_type": n.node_type,
            "page_start": n.page_start,
            "page_end": n.page_end,
            "level": n.level,
            "path": n.path,
        }
        for n in nodes
    ]

    return {
        "id": str(subject.id),
        "name": subject.name,
        "book_title": subject.book_title,
        "processing_status": subject.processing_status,
        "created_at": str(subject.created_at),
        "hierarchy": hierarchy,
    }


# ── DELETE /{subject_id} — Delete subject and cascade ──────────────────────
@router.delete("/{subject_id}")
async def delete_subject(
    subject_id: str,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a subject and all related data (cascaded by FK)."""
    user_id = user["sub"]
    subject = (
        db.query(Subject)
        .filter(Subject.id == subject_id, Subject.user_id == user_id)
        .first()
    )
    if not subject:
        raise HTTPException(status_code=404, detail="Subject not found")

    # Clean up file from disk
    if subject.file_path and os.path.exists(subject.file_path):
        try:
            os.remove(subject.file_path)
        except OSError:
            logger.warning("Could not delete file %s", subject.file_path)

    db.delete(subject)
    db.commit()
    return {"message": "Subject deleted"}


# ── GET /{subject_id}/upload-status — Poll processing progress ─────────────
@router.get("/{subject_id}/upload-status")
async def get_upload_status(
    subject_id: str,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Return the latest document_upload status for a subject.
    The frontend polls this endpoint to display processing progress.
    """
    user_id = user["sub"]

    # Verify ownership
    subject = (
        db.query(Subject)
        .filter(Subject.id == subject_id, Subject.user_id == user_id)
        .first()
    )
    if not subject:
        raise HTTPException(status_code=404, detail="Subject not found")

    upload = (
        db.query(DocumentUpload)
        .filter(DocumentUpload.subject_id == subject_id)
        .order_by(DocumentUpload.uploaded_at.desc())
        .first()
    )

    if not upload:
        return {"status": "unknown", "progress": 0}

    return {
        "upload_id": str(upload.id),
        "status": upload.status,
        "progress": upload.progress,
        "error_message": upload.error_message,
        "processing_status": subject.processing_status,
        "document_type": upload.document_type,
    }


# ── GET /{subject_id}/focus-areas — Level-1 hierarchy nodes for context filtering
@router.get("/{subject_id}/focus-areas")
async def get_focus_areas(
    subject_id: str,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return Level-1 hierarchy nodes for a subject (used as Focus Area filters)."""
    user_id = user["sub"]

    # Verify ownership
    subject = (
        db.query(Subject)
        .filter(Subject.id == subject_id, Subject.user_id == user_id)
        .first()
    )
    if not subject:
        raise HTTPException(status_code=404, detail="Subject not found")

    nodes = (
        db.query(HierarchyNode)
        .filter(
            HierarchyNode.subject_id == subject_id,
            HierarchyNode.level == 1,
        )
        .order_by(HierarchyNode.page_start)
        .all()
    )

    return [
        {
            "id": str(n.id),
            "title": n.title,
            "subject_id": str(n.subject_id),
        }
        for n in nodes
    ]

