"""
Starred Responses API Routes
Star / unstar assistant messages for quick reference.
"""

import uuid

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.database import get_db
from app.models.database import StarredResponse, ChatMessage

router = APIRouter(prefix="/api/starred", tags=["starred"])


# ── Request schema ──────────────────────────────────────────────────────────
class StarRequest(BaseModel):
    message_id: str


# ── GET / — List starred messages ──────────────────────────────────────────
@router.get("/")
async def list_starred(
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Return all starred messages for the authenticated user,
    joined with chat_messages to include the message content.
    """
    user_id = user["sub"]

    rows = (
        db.query(StarredResponse, ChatMessage)
        .join(ChatMessage, StarredResponse.message_id == ChatMessage.id)
        .filter(StarredResponse.user_id == user_id)
        .order_by(StarredResponse.created_at.desc())
        .all()
    )

    return [
        {
            "id": str(star.id),
            "message_id": str(star.message_id),
            "content": msg.content,
            "role": msg.role,
            "metadata": msg.metadata_,
            "starred_at": str(star.created_at),
            "message_created_at": str(msg.created_at),
        }
        for star, msg in rows
    ]


# ── POST / — Star a message ───────────────────────────────────────────────
@router.post("/")
async def star_message(
    body: StarRequest,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Star a chat message. Duplicates are rejected by the DB unique constraint."""
    user_uuid = uuid.UUID(user["sub"]) if isinstance(user["sub"], str) else user["sub"]
    message_uuid = uuid.UUID(body.message_id) if isinstance(body.message_id, str) else body.message_id

    # Verify message exists
    message = db.query(ChatMessage).filter(ChatMessage.id == message_uuid).first()
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")

    # Check for existing star
    existing = (
        db.query(StarredResponse)
        .filter(
            StarredResponse.user_id == user_uuid,
            StarredResponse.message_id == message_uuid,
        )
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="Message already starred")

    star = StarredResponse(
        id=uuid.uuid4(),
        user_id=user_uuid,
        message_id=message_uuid,
    )
    db.add(star)
    db.commit()

    return {
        "id": str(star.id),
        "message_id": str(star.message_id),
        "message": "Message starred",
    }


# ── DELETE /{star_id} — Unstar a message ──────────────────────────────────
@router.delete("/{star_id}")
async def unstar_message(
    star_id: str,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Remove a star by its ID. Only the owner can unstar."""
    user_uuid = uuid.UUID(user["sub"]) if isinstance(user["sub"], str) else user["sub"]
    star_uuid = uuid.UUID(star_id) if isinstance(star_id, str) else star_id

    star = (
        db.query(StarredResponse)
        .filter(StarredResponse.id == star_uuid, StarredResponse.user_id == user_uuid)
        .first()
    )
    if not star:
        raise HTTPException(status_code=404, detail="Starred entry not found")

    db.delete(star)
    db.commit()
    return {"message": "Star removed"}
