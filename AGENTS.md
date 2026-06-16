# Agents

This file will track the different agents and subagents used in this project, or contain notes about autonomous workflows.

## Agents Used

### Main Orchestrator
- **Role**: Project architect and coordinator
- **Tasks completed**:
  - Created project foundation: `requirements.txt`, `.env.example`, `.gitignore`, `vercel.json`
  - Set up core modules: `app/core/config.py`, `app/core/database.py`, `app/core/auth.py`
  - Created SQLAlchemy ORM models: `app/models/database.py`
  - Wrote full SQL schema with RLS policies: `schema.sql`
  - Configured Alembic migrations: `alembic.ini`, `alembic/env.py`
  - Migrated codebase to the new Supabase API key system (`SUPABASE_PUBLISHABLE_KEY` and `SUPABASE_SECRET_KEY`) and updated the token verification flow to use the Supabase Auth API.
  - Delegated and coordinated parallel subagent work
  - Redesigned ingestion pipeline to support scanned PDFs using OCRmyPDF and Ghostscript.
  - Implemented universal PDF ingestion pipeline: auto-detect scanned vs digital, PyMuPDF binarization, local TOC extraction with Gemini ultimate fallback, and detailed database tracking.
  - Fixed page range calculation bug during hierarchy generation.
  - Prepared Render deployment files (Dockerfile and render.yaml) and updated database schemas.
  - Resolved the infinite authentication redirect loop by implementing cookie clearing on the backend and frontend when auth checks fail.
  - Fixed the administrative user deletion error (SQLAlchemy ObjectDeletedError caused by database-level cascade deletes).
  - Implemented real-time dynamic upload/preprocessing step rendering on the frontend based on document type (digital vs. scanned).
  - Added UI locking mechanisms to disable the upload button and prevent closing the upload modal during processing.
  - Resolved database sentinel value mismatch errors by ensuring all primary/foreign keys passed to SQLAlchemy ORM models (in `pdf_processor.py`, `chat.py`, `subjects.py`, and `starred.py`) are proper python `uuid.UUID` objects.
  - Guaranteed hierarchy availability for context retrieval features by performing explicit database session commits immediately after hierarchy nodes are inserted.
  - Replaced the offline `OCRmyPDF` binarization pipeline with a custom cloud-based Gemini OCR engine (`app/services/gemini_ocr.py`) that uses the Files API and majority-vote offset detection.
  - Integrated the new Gemini OCR process into the backend document upload pipeline (`app/services/pdf_processor.py`).
  - Transitioned the RAG response generation model (`app/services/gemini_service.py`) to the latest `gemini-3.1-flash-lite` for improved cost efficiency and low-latency responses.
  - Implemented Level-1 Hierarchy Context Filtering to allow users to optionally narrow chat retrieval to specific textbook chapters (e.g., Hematology within Physiology) with an intuitive dynamic dropdown UI.
  - Created and applied Alembic database migration to synchronize the new `chat_focus_areas` table with RLS policy and index configurations, resolving the UndefinedTable error.
  - Fixed the Identical Timestamp Ordering Bug in `app/api/chat.py` by adding `role` as secondary order criteria, ensuring user messages load before their corresponding assistant replies.
  - Resolved the frontend message duplication race condition in `app/static/js/app.js` by checking active session IDs upon callback resolution.
  - Fixed the PDF binarization/OCR text layer truncation bug in `app/services/gemini_ocr.py` by implementing dynamic font size scaling for textbox insertion.
  - Recompiled the searchable PDF and reprocessed the `Physiology` subject database records, successfully expanding text chunks index coverage from 1,485 to 4,752 chunks and restoring missing section contents.
  - Added text-based flowchart generation instructions to the RAG chatbot's system instruction prompt for process descriptions and explicit user requests.
  - Implemented natural language query preprocessing (stripping conversational fillers) and `OR`-search fallback logic in `app/services/rag_service.py` to make search robust.
  - Updated RAG model system instructions to allow fallback supplementation from Gemini's internal knowledge base when textbook context is limited, with clear labeling.
  - Implemented automatic logout upon tab close by syncing authentication state validation checks with browser `sessionStorage` in `app/static/js/app.js`.
  - Fixed the new chat creation double-message rendering race condition by awaiting `switchChat` sequentially inside `createNewChat` in `app/static/js/app.js`.
  - Added query reformulation via `"gemini-2.5-flash"` in `app/services/gemini_service.py` to translate conversational follow-up turns into standalone search terms, isolating FTS preprocessing rate limits from the main chat model.
  - Project Reorganization: Moved standalone scripts, database schemas, and scratch files into `scripts/`, `db/`, and `scratch/`.
  - Git & GitHub Integration: Initialized local Git repository, created `.gitignore`, established MIT LICENSE, pushed initial codebase and deployment optimizations to `https://github.com/supratimcoder1/MBBS-Study-Assistant.git`.
  - Cloud Deployment Optimization: Simplified `Dockerfile` (removed Tesseract/Ghostscript), updated `requirements.txt` (added `psycopg2-binary`, removed `ocrmypdf`), and updated `README.md` to reflect cloud-native hosting setup.
  - Implemented stronger password creation logic for new users (client and server-side complexity validation).

### Backend Builder (Subagent)
- **Role**: Backend API Developer
- **Tasks completed**:
  - PDF processing service using PyMuPDF (fitz): `app/services/pdf_processor.py`
  - Gemini API service: `app/services/gemini_service.py`
  - RAG retrieval service with PostgreSQL FTS: `app/services/rag_service.py`
  - Auth API routes (signup, login, logout, profile): `app/api/auth.py`
  - Subject CRUD & upload routes: `app/api/subjects.py`
  - Chat session & message routes with RAG pipeline: `app/api/chat.py`
  - Starred responses routes: `app/api/starred.py`
  - FastAPI entry point: `app/main.py`

### Frontend Builder (Subagent)
- **Role**: Frontend UI Developer
- **Tasks completed**:
  - Premium dark theme CSS with glassmorphism: `app/static/css/style.css`
  - Base template with collapsible sidebar: `app/templates/base.html`
  - Login page (standalone): `app/templates/login.html`
  - Signup page (standalone): `app/templates/signup.html`
  - Dashboard with chat interface: `app/templates/dashboard.html`
  - Subjects page with upload modal & progress UI: `app/templates/subjects.html`
  - Profile settings with starred messages: `app/templates/profile.html`
  - WIP placeholder page: `app/templates/wip.html`
  - Full client-side JavaScript: `app/static/js/app.js`
