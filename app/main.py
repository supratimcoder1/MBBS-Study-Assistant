"""
MBBS Study Assistant — FastAPI Application Entry Point
Mounts static files, registers API routers, and serves Jinja2 template pages.
"""

import os
import logging
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app.core.auth import login_required, get_current_user

# API routers
from app.api.auth import router as auth_router
from app.api.subjects import router as subjects_router
from app.api.chat import router as chat_router
from app.api.starred import router as starred_router
from app.api.admin import router as admin_router

# ── Logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger(__name__)

# ── Paths ───────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent          # app/
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"
UPLOADS_DIR = Path("/tmp/uploads") if (os.environ.get("VERCEL") == "1" or os.path.exists("/var/task")) else Path("uploads")


# ── Lifespan (startup / shutdown) ──────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: ensure the uploads directory exists
    UPLOADS_DIR.mkdir(exist_ok=True)
    logger.info("Uploads directory ready at %s", UPLOADS_DIR.resolve())
    yield
    # Shutdown: nothing special needed
    logger.info("Application shutting down")


# ── Create the FastAPI app ─────────────────────────────────────────────────
app = FastAPI(
    title="MBBS Study Assistant",
    description="AI-powered study companion for medical students",
    version="1.0.0",
    lifespan=lifespan,
)

# Mount static files (CSS, JS, images)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Jinja2 templates
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


# ── Register API routers ───────────────────────────────────────────────────
app.include_router(auth_router)
app.include_router(subjects_router)
app.include_router(chat_router)
app.include_router(starred_router)
app.include_router(admin_router)


# ═══════════════════════════════════════════════════════════════════════════
# PAGE ROUTES  (render Jinja2 templates — NOT API endpoints)
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/", include_in_schema=False)
async def root(request: Request):
    """Render the landing page, or redirect to dashboard if logged in."""
    try:
        await get_current_user(request)
        return RedirectResponse(url="/dashboard", status_code=302)
    except HTTPException:
        return templates.TemplateResponse("landing.html", {"request": request})


@app.get("/login", include_in_schema=False)
async def login_page(request: Request):
    """Render the login page. Redirect to dashboard if already logged in."""
    from app.core.auth import check_login_rate_limit
    check_login_rate_limit(request)
    try:
        await get_current_user(request)
        return RedirectResponse(url="/dashboard", status_code=302)
    except HTTPException:
        response = templates.TemplateResponse("login.html", {"request": request})
        response.delete_cookie("access_token")
        response.delete_cookie("mbbs_access_token")
        return response


@app.get("/signup", include_in_schema=False)
async def signup_page(request: Request):
    """Render the signup page. Redirect to dashboard if already logged in."""
    try:
        await get_current_user(request)
        return RedirectResponse(url="/dashboard", status_code=302)
    except HTTPException:
        response = templates.TemplateResponse("signup.html", {"request": request})
        response.delete_cookie("access_token")
        response.delete_cookie("mbbs_access_token")
        return response


@app.get("/dashboard", include_in_schema=False)
@login_required
async def dashboard_page(request: Request):
    """Render the main dashboard (requires authentication)."""
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "user": request.state.user,
    })


@app.get("/subjects", include_in_schema=False)
@login_required
async def subjects_page(request: Request):
    """Render the subjects management page (requires authentication)."""
    return templates.TemplateResponse("subjects.html", {
        "request": request,
        "user": request.state.user,
    })


@app.get("/profile", include_in_schema=False)
@login_required
async def profile_page(request: Request):
    """Render the user profile page (requires authentication)."""
    return templates.TemplateResponse("profile.html", {
        "request": request,
        "user": request.state.user,
    })


@app.get("/wip", include_in_schema=False)
@login_required
async def wip_page(request: Request):
    """Render a 'work in progress' placeholder page (requires authentication)."""
    return templates.TemplateResponse("wip.html", {
        "request": request,
        "user": request.state.user,
    })


@app.get("/admin", include_in_schema=False)
@login_required
async def admin_page(request: Request):
    """Render the admin hacker dashboard (requires admin privileges)."""
    if not request.state.user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Access denied: Admin privileges required")
    return templates.TemplateResponse("admin.html", {
        "request": request,
        "user": request.state.user,
    })
