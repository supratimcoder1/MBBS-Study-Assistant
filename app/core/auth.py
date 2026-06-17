"""
Supabase JWT authentication middleware and dependency for FastAPI.
Verifies the JWT using Supabase's auth service.
"""

from fastapi import Request, HTTPException
from functools import wraps
from app.core.config import supabase


async def get_current_user(request: Request) -> dict:
    """
    FastAPI dependency – extracts and verifies the Supabase JWT from cookies
    or the Authorization header using Supabase's auth service.
    Returns decoded payload with at least 'sub' (user id).
    """
    token = request.cookies.get("access_token")

    if not token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]

    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        # Verify the token via Supabase Auth API
        response = supabase.auth.get_user(token)
        if not response or not response.user:
            raise HTTPException(status_code=401, detail="Invalid token")
        
        user = response.user

        # Fetch is_admin status from local database
        from app.core.database import SessionLocal
        from app.models.database import Profile

        db = SessionLocal()
        try:
            profile = db.query(Profile).filter(Profile.id == user.id).first()
            if profile and not profile.is_approved and not profile.is_admin:
                raise HTTPException(status_code=403, detail="Account pending approval")
            is_admin = profile.is_admin if profile else False
        finally:
            db.close()

        return {
            "sub": str(user.id),
            "email": user.email,
            "role": user.role,
            "user_metadata": user.user_metadata,
            "is_admin": is_admin,
        }
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"Authentication failed: {str(exc)}")


def login_required(func):
    """Decorator for Jinja2-rendered routes that redirects to /login on auth failure."""
    @wraps(func)
    async def wrapper(request: Request, *args, **kwargs):
        try:
            user = await get_current_user(request)
            request.state.user = user
        except HTTPException:
            from fastapi.responses import RedirectResponse
            response = RedirectResponse(url="/login", status_code=302)
            response.delete_cookie("access_token")
            response.delete_cookie("mbbs_access_token")
            return response
        return await func(request, *args, **kwargs)
    return wrapper


from collections import defaultdict
import time

_login_rate_limits = defaultdict(list)
LOGIN_LIMIT_WINDOW = 60  # 1 minute
LOGIN_LIMIT_MAX = 5     # Max 5 attempts/loads per minute

def check_login_rate_limit(request: Request):
    """Rate limit check for login page and login API to prevent brute-forcing/automated scanning."""
    client_ip = request.client.host if request.client else "unknown"
    now = time.time()
    
    # Clean up old timestamps
    _login_rate_limits[client_ip] = [t for t in _login_rate_limits[client_ip] if now - t < LOGIN_LIMIT_WINDOW]
    
    if len(_login_rate_limits[client_ip]) >= LOGIN_LIMIT_MAX:
        raise HTTPException(
            status_code=429,
            detail="Too many login attempts or page loads. Please try again in a minute."
        )
        
    _login_rate_limits[client_ip].append(now)
