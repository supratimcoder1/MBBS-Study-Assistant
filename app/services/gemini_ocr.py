"""
Gemini OCR Service
Replaces local offline OCRmyPDF with Gemini API-based OCR.
Splits the PDF into chunks, extracts text using Gemini Files API, and rebuilds
a searchable PDF by injecting an invisible text layer.
"""

import os
import sys
import logging
import json
import time
import re
import tempfile
from typing import Optional

import fitz  # PyMuPDF
from google import genai
from google.genai.errors import APIError

from app.core.config import GEMINI_API_KEY

logger = logging.getLogger(__name__)

# Initialize the Gemini client once
client = genai.Client(api_key=GEMINI_API_KEY)


def count_page_markers(text: str) -> int:
    """Counts the number of PAGE markers in the text chunk."""
    pattern = r'(?:^|\n)(?:---\s*)?[Pp][Aa][Gg][Ee]\s*(\d+)'
    return len(re.findall(pattern, text))


def call_gemini_ocr_with_retry(model_id: str, content_items: list, max_retries: int = 5) -> str:
    """Calls Gemini API with exponential backoff on rate limits/errors."""
    base_wait = 10.0
    
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model=model_id,
                contents=content_items,
                config=genai.types.GenerateContentConfig(
                    temperature=0.0,
                )
            )
            return response.text or ""
        except APIError as e:
            if "429" in str(e) or "quota" in str(e).lower() or "limit" in str(e).lower():
                wait_time = base_wait * (2 ** attempt)
                logger.warning("Rate limit hit (429). Retrying in %.1f seconds...", wait_time)
                time.sleep(wait_time)
            elif "demand" in str(e).lower() or "overloaded" in str(e).lower() or "503" in str(e):
                wait_time = base_wait * (2 ** attempt)
                logger.warning("Model in high demand. Retrying in %.1f seconds...", wait_time)
                time.sleep(wait_time)
            else:
                logger.error("API Error: %s", e)
                raise e
        except Exception as e:
            logger.error("Unexpected error during Gemini call: %s", e)
            wait_time = base_wait * (2 ** attempt)
            time.sleep(wait_time)
            
    raise RuntimeError(f"Failed to get OCR result from Gemini after {max_retries} attempts.")


def split_pdf_into_temp_chunks(input_path: str, chunk_size: int, temp_dir: str) -> list[tuple[str, int, int]]:
    """
    Splits the PDF into smaller chunks and saves them in temp_dir.
    Returns list of (chunk_path, start_page_num, end_page_num).
    """
    logger.info("Splitting PDF into chunks of %d pages...", chunk_size)
    doc = fitz.open(input_path)
    total_pages = len(doc)
    chunks = []
    
    for i in range(0, total_pages, chunk_size):
        chunk_end = min(i + chunk_size, total_pages)
        chunk_name = os.path.join(temp_dir, f"chunk_{i+1}_to_{chunk_end}.pdf")
        
        chunk_doc = fitz.open()
        chunk_doc.insert_pdf(doc, from_page=i, to_page=chunk_end - 1)
        chunk_doc.save(chunk_name)
        chunk_doc.close()
        
        logger.info("  Created chunk: %s (Pages %d to %d)", os.path.basename(chunk_name), i + 1, chunk_end)
        chunks.append((chunk_name, i, chunk_end))
        
    doc.close()
    return chunks


def process_chunk_with_files_api(model_id: str, chunk_path: str, prompt: str) -> str:
    """Uploads a PDF chunk via Files API, waits for processing, runs OCR, and cleans up."""
    logger.info("Uploading %s to Gemini Files API...", os.path.basename(chunk_path))
    uploaded_file = client.files.upload(file=chunk_path)
    logger.info("Uploaded successfully. Remote Name: %s", uploaded_file.name)
    
    logger.info("Waiting for file processing to complete...")
    while uploaded_file.state.name == "PROCESSING":
        time.sleep(5)
        uploaded_file = client.files.get(name=uploaded_file.name)
        
    if uploaded_file.state.name == "FAILED":
        raise RuntimeError(f"File processing failed on Gemini servers for {chunk_path}")
        
    logger.info("Processing complete. Requesting structural OCR...")
    text = call_gemini_ocr_with_retry(model_id, [uploaded_file, prompt])
    
    logger.info("Cleaning up remote file: %s", uploaded_file.name)
    client.files.delete(name=uploaded_file.name)
    
    return text


def parse_all_pages_from_cache(cache: dict) -> dict[int, str]:
    """Parses page numbers and text blocks from all cached chunks with majority-vote offset detection."""
    pattern = r'(?:^|\n)(?:---\s*)?[Pp][Aa][Gg][Ee]\s*(\d+)\s*(?:---)?\s*\n(.*?)(?=(?:\n(?:---\s*)?[Pp][Aa][Gg][Ee]\s*\d+\s*(?:---)?\s*\n)|$)'
    page_map = {}
    
    for chunk_key, text in cache.items():
        match_key = re.match(r'chunk_(\d+)_(\d+)', chunk_key)
        if not match_key:
            continue
            
        c_start = int(match_key.group(1))
        c_end = int(match_key.group(2))
        
        matches = re.findall(pattern, text, re.DOTALL)
        if not matches:
            continue
            
        # Determine the best offset for this chunk using majority vote
        offset_votes = {}
        possible_offsets = [0, 14, c_start]  # Try exact, common offset, or relative to chunk start
        
        for page_str, _ in matches:
            num = int(page_str)
            for offset in possible_offsets:
                abs_page = num + offset
                if c_start < abs_page <= c_end:
                    offset_votes[offset] = offset_votes.get(offset, 0) + 1
                    
        if not offset_votes:
            best_offset = c_start
        else:
            best_offset = max(offset_votes, key=offset_votes.get)
            
        logger.info("Chunk %s: majority-vote detected page offset %d (votes: %s)", chunk_key, best_offset, offset_votes)
        
        # Apply the detected offset to map pages
        for page_str, page_text in matches:
            num = int(page_str)
            abs_page = num + best_offset
            if c_start < abs_page <= c_end:
                page_map[abs_page] = page_text.strip()
                
    return page_map


def process_scanned_pdf(input_pdf: str, model_id: str = "gemini-2.5-flash-lite", chunk_size: int = 50) -> str:
    """
    Main pipeline to process a scanned PDF.
    Returns the path to the newly generated searchable PDF.
    """
    logger.info("Starting Gemini OCR pipeline for %s", input_pdf)
    base_dir = os.path.dirname(input_pdf)
    filename, _ = os.path.splitext(os.path.basename(input_pdf))
    output_pdf = os.path.join(base_dir, f"{filename}_searchable.pdf")
    cache_file = os.path.join(base_dir, f"{filename}_ocr_cache.json")
    
    # Load cache if exists
    cache = {}
    if os.path.exists(cache_file):
        with open(cache_file, "r", encoding="utf-8") as f:
            try:
                cache = json.load(f)
                logger.info("Loaded OCR cache with %d entries.", len(cache))
            except json.JSONDecodeError:
                logger.warning("Cache file is corrupted. Starting fresh.")
    
    # Create temp directory
    temp_dir = tempfile.mkdtemp()
    
    prompt = (
        "Perform optical character recognition (OCR) on this entire document. "
        "Extract all text precisely as it reads page-by-page. Mark each page starting boundary clearly "
        "with '--- PAGE X ---' where X is the absolute page number of the textbook page. "
        "Do not leave out any text blocks. Do not append conversational introductions or summaries."
    )
    
    chunks = split_pdf_into_temp_chunks(input_pdf, chunk_size, temp_dir)
    
    for chunk_path, c_start, c_end in chunks:
        chunk_key = f"chunk_{c_start}_{c_end}"
        
        if chunk_key in cache:
            logger.info("Chunk [%d to %d] Loaded from cache", c_start + 1, c_end)
        else:
            try:
                extracted_text = process_chunk_with_files_api(model_id, chunk_path, prompt)
                
                # Verify output is not truncated before saving
                markers = count_page_markers(extracted_text)
                expected_pages_in_chunk = c_end - c_start
                threshold = int(expected_pages_in_chunk * 0.8)
                
                if markers < threshold:
                    logger.warning("Gemini returned truncated output for %s (%d markers). Retrying...", chunk_key, markers)
                    time.sleep(15.0)
                    # Retry once inside the loop
                    extracted_text = process_chunk_with_files_api(model_id, chunk_path, prompt)
                    
                cache[chunk_key] = extracted_text
                with open(cache_file, "w", encoding="utf-8") as f:
                    json.dump(cache, f, indent=2, ensure_ascii=False)
                    
                logger.info("Successfully saved chunk %s to cache.", chunk_key)
                
                # Stay safely under 5 RPM limit
                time.sleep(15.0)
            except Exception as e:
                logger.error("Failed to process chunk [%d to %d]: %s", c_start + 1, c_end, e)
                # Ensure cleanup
                try:
                    os.remove(chunk_path)
                except:
                    pass
                raise
        
        # Clean up local temp file
        try:
            os.remove(chunk_path)
        except:
            pass
            
    # Clean up temp directory
    try:
        os.rmdir(temp_dir)
    except:
        pass
        
    # Compilation step
    logger.info("Compiling final searchable PDF by injecting text layer...")
    page_text_map = parse_all_pages_from_cache(cache)
    logger.info("Successfully parsed %d pages of text from cache.", len(page_text_map))
    
    doc = fitz.open(input_pdf)
    
    for page_num in range(len(doc)):
        pdf_page_num = page_num + 1
        if pdf_page_num in page_text_map:
            page = doc[page_num]
            extracted_text = page_text_map[pdf_page_num]
            
            rect = fitz.Rect(30, 30, page.rect.width - 30, page.rect.height - 30)
            safe_text = extracted_text.replace("\u2018", "'").replace("\u2019", "'").replace("\u201c", '"').replace("\u201d", '"')
            
            # Dynamically scale font size based on text length to prevent textbox overflow
            fontsize = max(2, min(8, int(8 * 1500 / len(safe_text))))
            
            try:
                page.insert_textbox(
                    rect,
                    safe_text,
                    fontsize=fontsize,
                    render_mode=3,
                    overlay=True
                )
            except Exception as e:
                logger.warning("Failed to insert text layer on page %d: %s", pdf_page_num, e)
                
    logger.info("Saving searchable PDF to %s...", output_pdf)
    doc.save(output_pdf, garbage=3, deflate=True)
    doc.close()
    
    return output_pdf
