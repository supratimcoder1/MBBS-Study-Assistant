"""
Auth API Routes
Handles signup, login, logout, and profile management via Supabase Auth.
"""

from fastapi import APIRouter, HTTPException, Response, Request, Depends
from pydantic import BaseModel, EmailStr
from app.core.config import supabase, supabase_admin
from app.core.auth import get_current_user
import re

router = APIRouter(prefix="/api/auth", tags=["auth"])


# ── Request / Response schemas ──────────────────────────────────────────────
class SignupRequest(BaseModel):
    email: EmailStr
    password: str
    name: str = ""
    year: str | int = ""
    course: str = ""


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class ProfileUpdate(BaseModel):
    name: str | None = None
    year: str | int | None = None
    course: str | None = None


# ── POST /signup ────────────────────────────────────────────────────────────
@router.post("/signup")
async def signup(body: SignupRequest):
    """
    Register a new user via Supabase Auth.
    The DB trigger auto-creates a profile row; we then patch it with
    year/course using the admin client.
    """
    # Password complexity validation
    if len(body.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters long.")
    if not re.search(r"[A-Z]", body.password):
        raise HTTPException(status_code=400, detail="Password must contain at least one uppercase letter.")
    if not re.search(r"[a-z]", body.password):
        raise HTTPException(status_code=400, detail="Password must contain at least one lowercase letter.")
    if not re.search(r"\d", body.password):
        raise HTTPException(status_code=400, detail="Password must contain at least one number.")
    if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", body.password):
        raise HTTPException(status_code=400, detail="Password must contain at least one special character.")

    try:
        result = supabase.auth.sign_up({
            "email": body.email,
            "password": body.password,
            "options": {
                "data": {"name": body.name},
            },
        })
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if not result.user:
        raise HTTPException(status_code=400, detail="Signup failed – no user returned")

    user_id = result.user.id

    # Update profile with year / course via admin client (bypasses RLS)
    if body.year or body.course:
        try:
            supabase_admin.table("profiles").update({
                "year": body.year,
                "course": body.course,
            }).eq("id", str(user_id)).execute()
        except Exception:
            pass  # non-critical – user can update later

    access_token = result.session.access_token if result.session else None

    return {
        "message": "Signup successful",
        "access_token": access_token,
        "user_id": str(user_id),
    }


# ── POST /login ─────────────────────────────────────────────────────────────
@router.post("/login")
async def login(body: LoginRequest, response: Response, request: Request):
    """
    Authenticate with email + password. Returns an access_token and sets
    it as a cookie (httponly=False so the JS frontend can read it).
    """
    from app.core.auth import check_login_rate_limit
    check_login_rate_limit(request)

    try:
        result = supabase.auth.sign_in_with_password({
            "email": body.email,
            "password": body.password,
        })
    except Exception as exc:
        raise HTTPException(status_code=401, detail=str(exc))

    if not result.session:
        raise HTTPException(status_code=401, detail="Login failed – invalid credentials")

    token = result.session.access_token

    response.set_cookie(
        key="access_token",
        value=token,
        httponly=False,      # JS needs to read it for API calls
        samesite="lax",
        secure=False,        # set True in production behind HTTPS
        max_age=60 * 60 * 24 * 7,  # 7 days
    )

    return {
        "message": "Login successful",
        "access_token": token,
        "user_id": str(result.user.id),
    }


# ── POST /logout ────────────────────────────────────────────────────────────
@router.post("/logout")
async def logout(response: Response):
    """Clear access token cookies."""
    response.delete_cookie("access_token")
    response.delete_cookie("mbbs_access_token")
    return {"message": "Logged out"}


# ── GET /profile ────────────────────────────────────────────────────────────
@router.get("/profile")
async def get_profile(user: dict = Depends(get_current_user)):
    """Return the authenticated user's profile from Supabase."""
    user_id = user["sub"]
    try:
        result = (
            supabase_admin.table("profiles")
            .select("*")
            .eq("id", user_id)
            .single()
            .execute()
        )
        return result.data
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"Profile not found: {exc}")


# ── PUT /profile ────────────────────────────────────────────────────────────
@router.put("/profile")
async def update_profile(
    body: ProfileUpdate,
    user: dict = Depends(get_current_user),
):
    """Update the authenticated user's name, year, and/or course."""
    user_id = user["sub"]

    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if "year" in updates:
        updates["year"] = str(updates["year"])
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    try:
        result = (
            supabase_admin.table("profiles")
            .update(updates)
            .eq("id", user_id)
            .execute()
        )
        return result.data[0] if result.data else {"message": "Updated"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Update failed: {exc}")
