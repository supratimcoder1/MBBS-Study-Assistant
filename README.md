# MBBS Study Assistant

An AI-powered Retrieval-Augmented Generation (RAG) web application designed specifically for MBBS (medical) students to chat with, query, and study complex medical textbooks. The app supports digital PDFs, scanned PDFs (via a high-quality cloud-based Gemini OCR engine), dynamic level-1 focus area (chapter-level) context filtering, and rich interactive chat elements (including text-based flowcharts).

---

## 🚀 Key Features

*   **Universal PDF Ingestion Pipeline:**
    *   Automatically detects whether an uploaded textbook is a digitally-born or scanned PDF.
    *   For scanned PDFs, it routes through a cloud-based **Gemini OCR engine** utilizing the Google GenAI Files API with majority-vote page offset correction.
    *   Compiles a searchable PDF by injecting an invisible text layer back into the original document.
*   **Hierarchical Document Parsing & Processing:**
    *   Extracts Table of Contents (TOC) using embedded data, local rule-based parsing, or Gemini 2.5 Flash as an ultimate fallback.
    *   Builds a structured database hierarchy (Parts ➔ Chapters ➔ Sections) mapped to absolute textbook pages.
    *   Splits text sections into overlapping semantic chunks with robust Full-Text Search (FTS) indexing in PostgreSQL.
*   **Context-Aware Medical RAG Chatbot:**
    *   Translates conversational follow-up turns into standalone queries using **Gemini 2.5 Flash** for reformulations.
    *   Retrieves context using high-performance PostgreSQL Full-Text Search.
    *   Uses **Gemini 3.1 Flash Lite** for generating replies, striking a balance between latency, accuracy, and cost efficiency.
    *   Generates interactive text-based flowcharts for complex process descriptions.
    *   *Self-Supplementation:* If textbook context is insufficient, the model falls back to Gemini's internal knowledge base, explicitly labeling the supplemental info.
*   **Focus Area Filtering:**
    *   Allows narrowing down chat retrieval to specific textbook chapters (e.g., studying *Hematology* within *Physiology*) to eliminate cross-topic noise.
*   **Saved Responses:** Save and star key generated answers for offline review in your profile.
*   **Secure Authentication:** User signup, login, and secure sessions synced with Supabase Auth.
*   **Premium UI/UX:** Responsive dark-theme design featuring modern glassmorphism, responsive sidebar layout, and live upload preprocessing progress steps.

---

## 📂 Project Structure

The codebase has been reorganized into a modular, clean, and production-ready layout:

```text
├── alembic/                # Database migration scripts and configuration
├── app/                    # Web application source code
│   ├── api/                # FastAPI routers (auth, chat, subjects, starred, admin)
│   ├── core/               # App configuration, security, auth, and database sessions
│   ├── models/             # SQLAlchemy ORM database models
│   ├── services/           # Backend services (Gemini OCR, Gemini LLM, RAG retrieval, PDF processor)
│   ├── static/             # Frontend static assets (premium CSS, client-side JS)
│   ├── templates/          # HTML templates (dashboard, login, signup, settings)
│   └── main.py             # FastAPI entrypoint
├── db/                     # Raw database schemas
│   └── schema.sql          # Postgres bootstrap schema (RLS, Triggers, Indexes)
├── scratch/                # Local development temp files, test PDFs, quality reports (git-ignored)
├── scripts/                # Administrative & standalone utility scripts
│   ├── seed_admin.py       # Seeds system administrators and elevates database privileges
│   ├── test_pipeline.py    # Offline diagnostic script for the parsing and ingestion pipeline
│   ├── ocr_standalone.py   # Standalone offline OCRmyPDF binarization & OCR
│   ├── ocr_gemini_standalone.py # Standalone Gemini-based OCR utility
│   ├── ocr_gemini_resume.py     # Resumes interrupted standalone Gemini OCR jobs
│   └── ocr_advanced_standalone.py # Standalone adaptive preprocessing + Sauvola thresholding pipeline
├── alembic.ini             # Alembic configuration
├── Dockerfile              # Deployment Dockerfile (used for Render)
├── render.yaml             # Render infrastructure blueprint
├── vercel.json             # Vercel serverless functions configuration
├── requirements.txt        # Python dependency manifest
└── LICENSE                 # MIT License details
```

---

## 🛠️ Local Development Setup

### Prerequisites
*   Python 3.11+
*   PostgreSQL database (configured with Full Text Search)
*   Supabase Account (for Auth and hosting the Database)
*   Gemini API Key (Google AI Studio)

### Installation

1.  **Clone the Repository:**
    ```bash
    git clone <your-repo-url>
    cd mbbs-study-assistant
    ```

2.  **Set Up Virtual Environment:**
    ```bash
    python -m venv .venv
    # On Windows:
    .venv\Scripts\activate
    # On Unix/macOS:
    source .venv/bin/activate
    ```

3.  **Install Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Configure Environment Variables:**
    Create a `.env` file in the root directory (use `.env.example` as a template):
    ```env
    SUPABASE_URL=https://your-supabase-project.supabase.co
    SUPABASE_PUBLISHABLE_KEY=your_supabase_anon_key
    SUPABASE_SECRET_KEY=your_supabase_service_role_key
    DATABASE_URL=postgresql://postgres:password@db-host:5432/postgres
    GEMINI_API_KEY=your_gemini_api_key
    ```

5.  **Bootstrap the Database:**
    *   Execute the SQL script in [db/schema.sql](db/schema.sql) using your database client or Supabase SQL Editor.
    *   Run migrations to bring the database schema up to date:
        ```bash
        alembic upgrade head
        ```

6.  **Run the Server:**
    ```bash
    uvicorn app.main:app --reload
    ```
    Open `http://127.0.0.1:8000` in your web browser.

---

## 🧪 Testing and Standalone Scripts

### Ingestion Pipeline Test
To run an offline run of the PDF parser, TOC extractor, hierarchy builder, and text chunker on a local PDF file:
1. Place a searchable PDF in the `scratch/` folder.
2. Edit path targets or run:
   ```bash
   python scripts/test_pipeline.py
   ```

---

## 🌐 Deployment

### 1. Backend (FastAPI & Background Tasks) on Render
The application is pre-configured for Docker-based deployment on **Render**:
*   The system-level requirements (`ghostscript`, `tesseract-ocr`, `ocrmypdf`) are built via the [Dockerfile](Dockerfile).
*   Use [render.yaml](render.yaml) to deploy the service in one click. Link the environment variables: `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, `SUPABASE_SECRET_KEY`, `DATABASE_URL`, and `GEMINI_API_KEY`.

### 2. Frontend / Serverless on Vercel
The app can also be deployed to **Vercel** serverless using the `@vercel/python` builder. The routing, static redirection, and API rules are defined in [vercel.json](vercel.json).

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
