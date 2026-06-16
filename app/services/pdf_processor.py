"""
PDF Processing Service
Extracts table of contents, builds hierarchy nodes, splits text into
searchable chunks, and persists everything to the database.
"""

import os
import uuid
import logging
import time
import json
import subprocess
import sys
from datetime import datetime, timezone
from tempfile import TemporaryDirectory

import re
import fitz  # PyMuPDF
from sqlalchemy.orm import Session
from PIL import Image

from app.models.database import HierarchyNode, ContentChunk, DocumentUpload, Subject
from app.services.gemini_service import client as gemini_client
from app.services.gemini_ocr import process_scanned_pdf

logger = logging.getLogger(__name__)

# ── Chunk sizing ────────────────────────────────────────────────────────────
CHUNK_SIZE = 1000       # target characters per chunk
CHUNK_OVERLAP = 150     # overlap between consecutive chunks


# ── 1. Extract TOC ─────────────────────────────────────────────────────────
def extract_toc(file_path: str) -> tuple[list[dict], str]:
    """
    Open the PDF and read its embedded table of contents.
    Returns a tuple of (entries, toc_method_used).
    """
    doc = fitz.open(file_path)
    total_pages = len(doc)
    logger.info("PDF opened: %s, total pages: %d", file_path, total_pages)
    if total_pages > 0:
        first_page_text = doc[0].get_text("text")
        logger.info("First 1000 chars of page 1:\n%s", first_page_text[:1000])

    toc_method = "embedded_toc"
    toc = doc.get_toc(simple=True)  # [[level, title, page], ...]
    
    if not toc:
        logger.info("No embedded TOC found, attempting rule-based fallback TOC extraction...")
        toc_method = "rule_based_fallback"
        toc = _parse_local_rule_based_toc(doc)
        
        if not toc:
            logger.info("Regex fallback failed. Using Gemini ultimate fallback...")
            toc_method = "gemini_fallback"
            toc = _parse_gemini_fallback_toc(doc)

    doc.close()

    entries = []
    for item in toc:
        if len(item) == 3:
            level, title, page = item
        else:
            continue
        entries.append({
            "level": level,
            "title": str(title).strip(),
            "page": int(page),      # 1-indexed
        })

    logger.info("Extracted %d TOC entries from %s using %s.", len(entries), file_path, toc_method)
    return entries, toc_method


def _smooth_page_numbers(entries: list[dict]) -> list[dict]:
    pages = [e["page"] for e in entries]
    n = len(pages)
    
    for i in range(1, n - 1):
        p_prev = pages[i-1]
        p_curr = pages[i]
        p_next = pages[i+1]
        
        if p_prev is not None and p_curr is not None and p_next is not None:
            if p_curr > p_next and p_curr > p_prev:
                s_page = str(p_curr)
                if s_page.startswith('7') and len(s_page) > 1:
                    fixed_val = int('1' + s_page[1:])
                    if p_prev <= fixed_val <= p_next:
                        pages[i] = fixed_val
                        entries[i]["page"] = fixed_val
                        continue
                if s_page.endswith('7'):
                    fixed_val = int(s_page[:-1] + '1')
                    if p_prev <= fixed_val <= p_next:
                        pages[i] = fixed_val
                        entries[i]["page"] = fixed_val
                        continue
                if p_prev <= p_next:
                    pages[i] = p_prev
                    entries[i]["page"] = p_prev
                    
    current_max = 1
    for i in range(n):
        if pages[i] is not None:
            if pages[i] < current_max:
                pages[i] = current_max
                entries[i]["page"] = current_max
            else:
                current_max = pages[i]
                
    return entries


def _parse_local_rule_based_toc(doc: fitz.Document) -> list:
    """Fallback parser: Detect TOC pages and apply rule-based parsing."""
    toc_text_parts = []
    toc_started = False
    
    for p in range(min(50, len(doc))):
        text = doc[p].get_text("text")
        if not toc_started:
            if re.search(r'^\s*(table of contents|contents)\s*$', text, re.IGNORECASE | re.MULTILINE):
                toc_started = True
                toc_text_parts.append(text)
        else:
            toc_text_parts.append(text)
            
        if toc_started and len(toc_text_parts) > 15:
            break
            
    if not toc_text_parts:
        for p in range(min(15, len(doc))):
            toc_text_parts.append(doc[p].get_text("text"))
            
    full_text = "\n".join(toc_text_parts)
    lines = [line.strip() for line in full_text.split('\n') if line.strip()]
    
    toc_entries = []
    processed_lines = []
    
    for line in lines:
        joined_match = re.search(r'^(.*?)\s+(\d+)\s*([^\w\s\d]+)\s*(.*?)\s+(\d+)$', line)
        if not joined_match:
            joined_match = re.search(r'^(.*?)\s+(\d+)\s+([A-Z\(\[\{\'\u201c\u2018].*?)\s+(\d+)$', line)
            
        if joined_match:
            title1 = joined_match.group(1).strip()
            page1 = int(joined_match.group(2))
            if len(joined_match.groups()) == 5:
                bullet2 = joined_match.group(3)
                title2 = joined_match.group(4).strip()
                page2 = int(joined_match.group(5))
                sep = f"{bullet2} " if bullet2 else ""
            else:
                title2 = joined_match.group(3).strip()
                page2 = int(joined_match.group(4))
                sep = ""
            processed_lines.append(f"{title1} {page1}")
            processed_lines.append(f"{sep}{title2} {page2}")
        else:
            processed_lines.append(line)

    i = 0
    while i < len(processed_lines):
        line = processed_lines[i]
        
        section_match = re.search(r'^\s*(?:section|part)\s*(\d+)[:.]?\s*(.*)$', line, re.IGNORECASE)
        if section_match:
            sec_num = section_match.group(1)
            sec_title = section_match.group(2).strip()
            current_section = f"Section {sec_num}: {sec_title}" if sec_title else f"Section {sec_num}"
            toc_entries.append({"level": 1, "title": current_section, "page": None})
            i += 1
            continue
            
        chapter_num_match = re.match(r'^\d+[\.:]?$', line)
        if chapter_num_match and i + 1 < len(processed_lines):
            next_line = processed_lines[i+1]
            if not re.match(r'^\d+[\.:]?$', next_line) and not re.search(r'\d+$', next_line):
                title = next_line.strip()
                chap_num = chapter_num_match.group(0).strip('.')
                current_chapter = f"Chapter {chap_num}: {title}"
                toc_entries.append({"level": 2, "title": current_chapter, "page": None})
                i += 2
                continue
                
        chap_inline = re.search(r'^\s*(?:chapter|ch\.)?\s*(\d+)\.\s+(.*)$', line, re.IGNORECASE)
        if chap_inline:
            chap_num = chap_inline.group(1)
            chap_title = chap_inline.group(2).strip()
            page_match = re.search(r'\s+(\d+)$', chap_title)
            page = None
            if page_match:
                page = int(page_match.group(1))
                chap_title = chap_title[:page_match.start()].strip()
            
            current_chapter = f"Chapter {chap_num}: {chap_title}"
            toc_entries.append({"level": 2, "title": current_chapter, "page": page})
            i += 1
            continue

        subtopic_match = re.search(r'^(.*?)\s+(\d+)$', line)
        if subtopic_match:
            title = subtopic_match.group(1).strip()
            page = int(subtopic_match.group(2))
            title = re.sub(r'^[^\w\(\[\{\'\"]+', '', title)
            title = re.sub(r'[\s.\-=_~+*]+$', '', title)
            title = title.strip()
            if title and len(title) > 2:
                toc_entries.append({"level": 3, "title": title, "page": page})
            i += 1
            continue
            
        i += 1

    for idx, entry in enumerate(toc_entries):
        if entry["page"] is None:
            for future in toc_entries[idx+1:]:
                if future["page"] is not None:
                    entry["page"] = future["page"]
                    break
            if entry["page"] is None:
                entry["page"] = 1
                
    toc_entries = _smooth_page_numbers(toc_entries)
    return [[e["level"], e["title"], e["page"]] for e in toc_entries]


def _parse_gemini_fallback_toc(doc: fitz.Document) -> list:
    """Ultimate fallback: Send first 50 pages to Gemini to extract TOC."""
    text_parts = []
    for p in range(min(50, len(doc))):
        text_parts.append(doc[p].get_text("text"))
    full_text = "\n".join(text_parts)
    
    prompt = f"""
    Analyze the following text extracted from the first 50 pages of a book.
    Identify the Table of Contents and extract it as a structured JSON list.
    Each item must be a dictionary with "level" (int), "title" (str), and "page" (int).
    Return ONLY valid JSON, nothing else.
    
    Text:
    {full_text[:50000]}
    """
    try:
        response = gemini_client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
        )
        text = response.text.strip()
        if text.startswith("```json"):
            text = text[7:-3]
        elif text.startswith("```"):
            text = text[3:-3]
        parsed = json.loads(text.strip())
        
        toc = []
        for item in parsed:
            toc.append([item.get("level", 1), item.get("title", ""), item.get("page", 1)])
        return toc
    except Exception as e:
        logger.error(f"Gemini fallback TOC extraction failed: {e}")
        return []


# ── 2. Build Hierarchy ─────────────────────────────────────────────────────
def build_hierarchy(toc_entries: list[dict], subject_id: str) -> list[dict]:
    """
    Convert flat TOC entries into a tree of HierarchyNode-like dicts.
    """
    if not toc_entries:
        return []

    # Ensure subject_id is a UUID object
    if isinstance(subject_id, str):
        subject_id = uuid.UUID(subject_id)

    nodes: list[dict] = []
    stack: list[tuple[int, dict]] = []

    for idx, entry in enumerate(toc_entries):
        node_id = uuid.uuid4()
        level = entry["level"]
        title = entry["title"]
        page_start = entry["page"]

        page_end = None
        for future in toc_entries[idx + 1:]:
            if future["level"] <= level:
                page_end = future["page"] - 1
                break

        if page_end is not None and page_end < page_start:
            page_end = page_start

        while stack and stack[-1][0] >= level:
            stack.pop()

        parent_id = stack[-1][1]["id"] if stack else None
        parent_path = stack[-1][1]["path"] if stack else ""

        type_map = {1: "part", 2: "chapter", 3: "section", 4: "subsection"}
        node_type = type_map.get(level, "subsection")
        path = f"{parent_path} / {title}" if parent_path else title

        node = {
            "id": node_id,
            "subject_id": subject_id,
            "parent_id": parent_id,
            "title": title,
            "node_type": node_type,
            "page_start": page_start,
            "page_end": page_end,
            "level": level,
            "path": path,
        }

        nodes.append(node)
        stack.append((level, node))

    logger.info("Built %d hierarchy nodes for subject %s", len(nodes), subject_id)
    return nodes


# ── 3. Extract & Chunk Text ───────────────────────────────────────────────
def extract_chunks(file_path: str, nodes: list[dict]) -> list[dict]:
    """
    For each node, extract raw text and split it into overlapping chunks.
    Only extracts the "direct" text of a node (before its first child starts).
    """
    doc = fitz.open(file_path)
    total_pages = len(doc)

    chunks: list[dict] = []

    for node in nodes:
        page_start = node.get("page_start")
        if page_start is None:
            continue

        # Determine the page where this node's exclusive text ends
        children = [n for n in nodes if n["parent_id"] == node["id"]]
        page_end_overall = node.get("page_end")
        
        child_starts = [c["page_start"] for c in children if c.get("page_start") is not None]
        if child_starts:
            first_child_start = min(child_starts)
            if page_end_overall is not None:
                exclusive_page_end = min(page_end_overall, first_child_start - 1)
            else:
                exclusive_page_end = first_child_start - 1
        else:
            exclusive_page_end = page_end_overall
            
        if exclusive_page_end is not None and exclusive_page_end < page_start:
            exclusive_page_end = page_start

        start_idx = max(page_start - 1, 0)
        if exclusive_page_end is None:
            end_idx = total_pages - 1
        else:
            end_idx = min(exclusive_page_end, total_pages) - 1

        text_parts: list[str] = []
        for p in range(start_idx, end_idx + 1):
            page_text = doc[p].get_text("text")
            if page_text:
                text_parts.append(page_text)
        full_text = "\n".join(text_parts).strip()

        if not full_text:
            continue

        node_chunks = _split_text(full_text, CHUNK_SIZE, CHUNK_OVERLAP)
        for ci, chunk_text in enumerate(node_chunks):
            chunks.append({
                "id": uuid.uuid4(),
                "node_id": node["id"],
                "chunk_index": ci,
                "text_content": chunk_text,
                "page_start": page_start,
                "page_end": exclusive_page_end,
            })

    doc.close()
    logger.info("Created %d content chunks from %s", len(chunks), file_path)
    return chunks


def _split_text(text: str, size: int, overlap: int) -> list[str]:
    if len(text) <= size:
        return [text]

    parts: list[str] = []
    start = 0
    while start < len(text):
        end = start + size
        chunk = text[start:end]
        parts.append(chunk.strip())
        start += size - overlap
    return parts


# ── 4. Full Pipeline ──────────────────────────────────────────────────────
def process_pdf(
    file_path: str,
    subject_id: str,
    db_session: Session,
    upload_id: str,
) -> None:
    """End-to-end PDF processing pipeline."""
    u_id = uuid.UUID(upload_id) if isinstance(upload_id, str) else upload_id
    s_id = uuid.UUID(subject_id) if isinstance(subject_id, str) else subject_id

    upload = db_session.query(DocumentUpload).filter_by(id=u_id).first()
    subject = db_session.query(Subject).filter_by(id=s_id).first()

    if not upload or not subject:
        logger.error("Upload %s or subject %s not found", upload_id, subject_id)
        return

    start_time = time.time()
    
    try:
        # ── Stage 1: Detect & OCR Scanned PDFs ───────────────────────────
        sample_doc = fitz.open(file_path)
        sample_text = ""
        for p in range(min(10, len(sample_doc))):
            sample_text += sample_doc[p].get_text("text")
        sample_doc.close()
        
        document_type = "digital"
        if len(sample_text.strip()) < 500:
            document_type = "scanned"
            
        # Immediately save the detected document type and status so frontend can build the steps
        upload.document_type = document_type
        _update_upload(db_session, upload, f"detected_{document_type}", 10)
        
        if document_type == "scanned":
            logger.info("PDF detected as SCANNED.")
            searchable_pdf = file_path.replace(".pdf", "_searchable.pdf")
            
            if os.path.exists(searchable_pdf):
                logger.info("Found existing searchable PDF: %s. Skipping OCR.", searchable_pdf)
                file_path = searchable_pdf
            else:
                logger.info("Starting Gemini API-based OCR...")
                _update_upload(db_session, upload, "extracting_ocr_gemini", 20)
                
                try:
                    file_path = process_scanned_pdf(file_path)
                    logger.info("Gemini OCR completed successfully. Output: %s", file_path)
                except Exception as e:
                    logger.error("Exception during Gemini OCR: %s", e)
                    raise e

        # ── Stage 2: Extracting TOC ──────────────────────────────────────
        _update_upload(db_session, upload, "extracting_toc", 40)
        toc_entries, toc_method_used = extract_toc(file_path)

        if not toc_entries:
            toc_entries = [{"level": 1, "title": subject.name, "page": 1}]
            toc_method_used = "single_root"

        # ── Stage 2: Building hierarchy ──────────────────────────────────
        _update_upload(db_session, upload, "building_hierarchy", 50)
        node_dicts = build_hierarchy(toc_entries, subject_id)

        for nd in node_dicts:
            db_node = HierarchyNode(
                id=nd["id"],
                subject_id=nd["subject_id"],
                parent_id=nd["parent_id"],
                title=nd["title"],
                node_type=nd["node_type"],
                page_start=nd["page_start"],
                page_end=nd["page_end"],
                level=nd["level"],
                path=nd["path"],
            )
            db_session.add(db_node)
        db_session.commit() # Explicitly commit hierarchy nodes so they are immediately available for the context feature

        # ── Stage 3: Chunking text ───────────────────────────────────────
        _update_upload(db_session, upload, "chunking", 70)
        chunk_dicts = extract_chunks(file_path, node_dicts)

        # ── Stage 4: Indexing ────────────────────────────────────────────
        _update_upload(db_session, upload, "indexing", 90)
        for cd in chunk_dicts:
            db_chunk = ContentChunk(
                id=cd["id"],
                node_id=cd["node_id"],
                chunk_index=cd["chunk_index"],
                text_content=cd["text_content"],
                page_start=cd["page_start"],
                page_end=cd["page_end"],
            )
            db_session.add(db_chunk)
        db_session.flush()

        # ── Stage 5: Complete ────────────────────────────────────────────
        processing_time = int(time.time() - start_time)
        upload.toc_method_used = toc_method_used
        upload.hierarchy_node_count = len(node_dicts)
        upload.chunk_count = len(chunk_dicts)
        upload.processing_time_seconds = processing_time
        upload.processed_at = datetime.now(timezone.utc)
        upload.status = "completed"
        upload.progress = 100
        
        subject.processing_status = "ready"
        db_session.commit()

        logger.info("PDF processing completed for subject %s in %d seconds.", subject_id, processing_time)

    except Exception as exc:
        db_session.rollback()
        logger.exception("PDF processing failed for subject %s: %s", subject_id, exc)
        try:
            upload.status = "failed"
            upload.error_message = str(exc)[:2000]
            subject.processing_status = "failed"
            db_session.commit()
        except Exception:
            db_session.rollback()
            logger.exception("Failed to persist error state for upload %s", upload_id)


def _update_upload(db: Session, upload: DocumentUpload, status: str, progress: int):
    """Helper to update upload status and progress, then flush."""
    upload.status = status
    upload.progress = progress
    db.commit()
