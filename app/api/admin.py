"""
Admin API Routes
Provides admin dashboard stats, user listing, and user account deletion.
Only users with is_admin = True can access these routes.
"""

import logging
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from app.core.auth import get_current_user
from app.core.database import get_db
from app.core.config import supabase_admin
from app.models.database import Profile, Subject, ChatSession, ChatMessage, StarredResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin", tags=["admin"])


def verify_admin(user: dict = Depends(get_current_user)):
    """Dependency helper to ensure user is an administrator."""
    if not user or not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Access denied: Admin privileges required")
    return user


# ── GET /stats ──────────────────────────────────────────────────────────────
@router.get("/stats")
async def get_admin_stats(
    admin_user: dict = Depends(verify_admin),
    db: Session = Depends(get_db),
):
    """Return platform-wide aggregated metrics for the hacker panel."""
    try:
        total_users = db.query(Profile).count()
        total_subjects = db.query(Subject).count()
        total_chats = db.query(ChatSession).count()
        total_messages = db.query(ChatMessage).count()
        total_stars = db.query(StarredResponse).count()

        # Custom stats for the hacker vibe
        active_uploads = db.query(Subject).filter(Subject.processing_status == "processing").count()
        ready_subjects = db.query(Subject).filter(Subject.processing_status == "ready").count()
        failed_subjects = db.query(Subject).filter(Subject.processing_status == "failed").count()

        success_rate = 100.0
        if (ready_subjects + failed_subjects) > 0:
            success_rate = round((ready_subjects / (ready_subjects + failed_subjects)) * 100, 1)

        return {
            "metrics": {
                "total_users": total_users,
                "total_subjects": total_subjects,
                "total_chats": total_chats,
                "total_messages": total_messages,
                "total_stars": total_stars,
            },
            "system": {
                "active_uploads": active_uploads,
                "success_rate": f"{success_rate}%",
                "pulse": "ONLINE",
            }
        }
    except Exception as exc:
        logger.error("Error fetching admin stats: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to load system metrics")


# ── GET /users ──────────────────────────────────────────────────────────────
@router.get("/users")
async def get_admin_users(
    admin_user: dict = Depends(verify_admin),
    db: Session = Depends(get_db),
):
    """Return a detailed list of all users and their usage metrics."""
    try:
        profiles = db.query(Profile).order_by(Profile.created_at.desc()).all()
        results = []

        for p in profiles:
            subject_count = db.query(Subject).filter(Subject.user_id == p.id).count()
            chat_count = db.query(ChatSession).filter(ChatSession.user_id == p.id).count()
            star_count = db.query(StarredResponse).filter(StarredResponse.user_id == p.id).count()

            results.append({
                "id": str(p.id),
                "name": p.name or "Unnamed User",
                "email": p.email,
                "year": p.year or "N/A",
                "course": p.course or "N/A",
                "is_admin": p.is_admin,
                "is_approved": p.is_approved,
                "created_at": str(p.created_at),
                "stats": {
                    "subjects": subject_count,
                    "chats": chat_count,
                    "stars": star_count,
                }
            })

        return results
    except Exception as exc:
        logger.error("Error listing users for admin: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to load user accounts")


# ── POST /users/{user_id}/approve — Approve a pending user account ──────────
@router.post("/users/{user_id}/approve")
async def approve_user_account(
    user_id: str,
    admin_user: dict = Depends(verify_admin),
    db: Session = Depends(get_db),
):
    """
    Approve a pending user account so they can log in and use the platform.
    Sets is_approved = True on the target profile.
    """
    target_profile = db.query(Profile).filter(Profile.id == user_id).first()
    if not target_profile:
        raise HTTPException(status_code=404, detail="User account not found")

    if target_profile.is_approved:
        return {"message": f"Account {target_profile.email} is already approved"}

    target_profile.is_approved = True
    db.commit()

    logger.info(
        "Admin %s approved user %s (%s)",
        admin_user["email"], user_id, target_profile.email,
    )
    return {"message": f"Account {target_profile.email} approved successfully"}


# ── DELETE /users/{user_id} ──────────────────────────────────────────────────
@router.delete("/users/{user_id}")
async def delete_user_account(
    user_id: str,
    admin_user: dict = Depends(verify_admin),
    db: Session = Depends(get_db),
):
    """
    Administratively terminate a user account.
    Deletes the auth.users record via Supabase Admin Client.
    Cascades down to profiles, subjects, uploads, chunks, chats, etc. in the DB.
    """
    # Prevent self-deletion via admin panel for safety
    if user_id == admin_user["sub"]:
        raise HTTPException(status_code=400, detail="Forbidden: You cannot terminate your own active session")

    # Verify target exists in DB
    target_profile = db.query(Profile).filter(Profile.id == user_id).first()
    if not target_profile:
        raise HTTPException(status_code=404, detail="User account not found")

    email = target_profile.email

    try:
        logger.info("Admin %s requested deletion of user %s (%s)", admin_user["email"], user_id, email)
        
        # Call Supabase Admin Client to hard delete the user from auth.users
        supabase_admin.auth.admin.delete_user(user_id)
        
        # Expunge target_profile from database session as database cascade deleted it
        db.expunge(target_profile)
        
        db.commit()
        return {"message": f"Account {email} terminated successfully"}
    except Exception as exc:
        logger.error("Error deleting user %s via admin: %s", user_id, exc)
        raise HTTPException(status_code=500, detail=f"Failed to terminate account: {exc}")
