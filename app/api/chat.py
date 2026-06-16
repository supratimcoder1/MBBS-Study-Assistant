"""
Chat API Routes
Session management, message send (RAG + Gemini pipeline), and context control.
"""

import uuid
import logging

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.database import get_db
from app.models.database import (
    ChatSession,
    ChatMessage,
    chat_subject_contexts,
    chat_focus_areas,
    Subject,
    HierarchyNode,
)
from app.services import rag_service, gemini_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/chat", tags=["chat"])


# ── Request schemas ─────────────────────────────────────────────────────────
class CreateSessionRequest(BaseModel):
    title: str = "New Chat"
    subject_ids: list[str] = []
    focus_area_ids: list[str] = []


class SendMessageRequest(BaseModel):
    content: str
    subject_ids: list[str] = []
    focus_area_ids: list[str] = []


class UpdateContextRequest(BaseModel):
    subject_ids: list[str]
    focus_area_ids: list[str] = []


# ── GET /sessions — List chat sessions ─────────────────────────────────────
@router.get("/sessions")
async def list_sessions(
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all chat sessions for the authenticated user, newest first."""
    user_id = user["sub"]
    sessions = (
        db.query(ChatSession)
        .filter(ChatSession.user_id == user_id)
        .order_by(ChatSession.created_at.desc())
        .all()
    )
    results = []
    for s in sessions:
        # Fetch linked subject IDs and focus area IDs
        subject_ids = [str(subj.id) for subj in s.subjects]
        focus_area_ids = [str(n.id) for n in s.focus_areas]
        results.append({
            "id": str(s.id),
            "title": s.title,
            "subject_ids": subject_ids,
            "focus_area_ids": focus_area_ids,
            "created_at": str(s.created_at),
        })
    return results


# ── POST /sessions — Create a new chat session ────────────────────────────
@router.post("/sessions")
async def create_session(
    body: CreateSessionRequest,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a chat session and optionally link it to one or more subjects."""
    user_uuid = uuid.UUID(user["sub"]) if isinstance(user["sub"], str) else user["sub"]

    session = ChatSession(
        id=uuid.uuid4(),
        user_id=user_uuid,
        title=body.title,
    )
    db.add(session)
    db.flush()

    # Create context mappings
    for sid in body.subject_ids:
        db.execute(
            chat_subject_contexts.insert().values(
                chat_session_id=session.id,
                subject_id=uuid.UUID(sid) if isinstance(sid, str) else sid,
            )
        )

    # Create focus area mappings
    for fid in body.focus_area_ids:
        db.execute(
            chat_focus_areas.insert().values(
                chat_session_id=session.id,
                node_id=uuid.UUID(fid) if isinstance(fid, str) else fid,
            )
        )
    db.commit()

    return {
        "id": str(session.id),
        "title": session.title,
        "subject_ids": body.subject_ids,
        "focus_area_ids": body.focus_area_ids,
        "created_at": str(session.created_at),
    }


# ── GET /sessions/{session_id}/messages — Message history ─────────────────
@router.get("/sessions/{session_id}/messages")
async def get_messages(
    session_id: str,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return all messages in a session ordered chronologically."""
    session_uuid = uuid.UUID(session_id) if isinstance(session_id, str) else session_id
    user_uuid = uuid.UUID(user["sub"]) if isinstance(user["sub"], str) else user["sub"]
    _verify_session_ownership(db, session_uuid, user_uuid)

    messages = (
        db.query(ChatMessage)
        .filter(ChatMessage.chat_session_id == session_uuid)
        .order_by(ChatMessage.created_at.asc(), ChatMessage.role.desc())
        .all()
    )
    return [
        {
            "id": str(m.id),
            "role": m.role,
            "content": m.content,
            "metadata": m.metadata_,
            "created_at": str(m.created_at),
        }
        for m in messages
    ]


# ── POST /sessions/{session_id}/messages — Send a message ─────────────────
@router.post("/sessions/{session_id}/messages")
async def send_message(
    session_id: str,
    body: SendMessageRequest,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    RAG-augmented message pipeline:
    1. Save user message
    2. Retrieve context via FTS
    3. Build chat history
    4. Generate response via Gemini
    5. Save assistant message with citation metadata
    """
    session_uuid = uuid.UUID(session_id) if isinstance(session_id, str) else session_id
    user_uuid = uuid.UUID(user["sub"]) if isinstance(user["sub"], str) else user["sub"]
    session = _verify_session_ownership(db, session_uuid, user_uuid)

    if not body.content.strip():
        raise HTTPException(status_code=400, detail="Message content cannot be empty")

    # 1. Save user message
    user_msg = ChatMessage(
        id=uuid.uuid4(),
        chat_session_id=session_uuid,
        role="user",
        content=body.content,
    )
    db.add(user_msg)
    db.flush()

    # 2. Determine subject IDs from request or session context
    subject_ids = body.subject_ids
    if not subject_ids:
        subject_ids = [str(s.id) for s in session.subjects]

    # Determine focus area IDs from request or session context
    focus_area_ids = body.focus_area_ids
    if not focus_area_ids:
        focus_area_ids = [str(n.id) for n in session.focus_areas]

    # 3. Build recent chat history (last 10 messages for conversational context)
    recent_messages = (
        db.query(ChatMessage)
        .filter(ChatMessage.chat_session_id == session_uuid)
        .order_by(ChatMessage.created_at.desc(), ChatMessage.role.asc())
        .limit(10)
        .all()
    )
    # Reverse so they are in chronological order, exclude the message we just added
    chat_history = [
        {"role": m.role, "content": m.content}
        for m in reversed(recent_messages)
        if str(m.id) != str(user_msg.id)
    ]

    # 4. Reformulate query to standalone search terms if it's a follow-up, and search FTS
    search_query = gemini_service.reformulate_query(body.content, chat_history)
    retrieved_chunks = rag_service.search_chunks(
        db=db,
        query=search_query,
        subject_ids=subject_ids,
        focus_area_ids=focus_area_ids,
        limit=10,
    )

    # 5. Generate response via Gemini (using original user question)
    answer = gemini_service.generate_response(
        query=body.content,
        context_chunks=retrieved_chunks,
        chat_history=chat_history,
    )

    # 6. Build citation metadata
    citation_meta = rag_service.build_citation_metadata(retrieved_chunks)

    # 7. Save assistant message
    assistant_msg = ChatMessage(
        id=uuid.uuid4(),
        chat_session_id=session_uuid,
        role="assistant",
        content=answer,
        metadata_=citation_meta,
    )
    db.add(assistant_msg)
    db.commit()

    return {
        "user_message": {
            "id": str(user_msg.id),
            "role": user_msg.role,
            "content": user_msg.content,
            "created_at": str(user_msg.created_at),
        },
        "assistant_message": {
            "id": str(assistant_msg.id),
            "role": assistant_msg.role,
            "content": assistant_msg.content,
            "metadata": assistant_msg.metadata_,
            "created_at": str(assistant_msg.created_at),
        },
    }


# ── PUT /sessions/{session_id}/context — Update subject context ───────────
@router.put("/sessions/{session_id}/context")
async def update_context(
    session_id: str,
    body: UpdateContextRequest,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Replace the subject context for a chat session."""
    session_uuid = uuid.UUID(session_id) if isinstance(session_id, str) else session_id
    user_uuid = uuid.UUID(user["sub"]) if isinstance(user["sub"], str) else user["sub"]
    _verify_session_ownership(db, session_uuid, user_uuid)

    # Clear existing context
    db.execute(
        chat_subject_contexts.delete().where(
            chat_subject_contexts.c.chat_session_id == session_uuid
        )
    )

    # Insert new context mappings
    for sid in body.subject_ids:
        db.execute(
            chat_subject_contexts.insert().values(
                chat_session_id=session_uuid,
                subject_id=uuid.UUID(sid) if isinstance(sid, str) else sid,
            )
        )

    # Clear existing focus areas
    db.execute(
        chat_focus_areas.delete().where(
            chat_focus_areas.c.chat_session_id == session_uuid
        )
    )

    # Insert new focus area mappings
    for fid in body.focus_area_ids:
        db.execute(
            chat_focus_areas.insert().values(
                chat_session_id=session_uuid,
                node_id=uuid.UUID(fid) if isinstance(fid, str) else fid,
            )
        )
    db.commit()

    return {"message": "Context updated", "subject_ids": body.subject_ids, "focus_area_ids": body.focus_area_ids}


# ── DELETE /sessions/{session_id} — Delete a chat session ─────────────────
@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: str,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a chat session and all its messages (cascaded)."""
    session_uuid = uuid.UUID(session_id) if isinstance(session_id, str) else session_id
    user_uuid = uuid.UUID(user["sub"]) if isinstance(user["sub"], str) else user["sub"]
    session = _verify_session_ownership(db, session_uuid, user_uuid)
    db.delete(session)
    db.commit()
    return {"message": "Chat session deleted"}


# ── Helpers ─────────────────────────────────────────────────────────────────
def _verify_session_ownership(db: Session, session_id: str, user_id: str) -> ChatSession:
    """Fetch a chat session and verify it belongs to the user, or 404."""
    s_uuid = uuid.UUID(session_id) if isinstance(session_id, str) else session_id
    u_uuid = uuid.UUID(user_id) if isinstance(user_id, str) else user_id
    session = (
        db.query(ChatSession)
        .filter(ChatSession.id == s_uuid, ChatSession.user_id == u_uuid)
        .first()
    )
    if not session:
        raise HTTPException(status_code=404, detail="Chat session not found")
    return session
