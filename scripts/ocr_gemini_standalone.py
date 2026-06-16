import os
import sys
import argparse
import logging
import json
import time
import re
from typing import Optional

# Force UTF-8 I/O on Windows
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = open(sys.stdout.fileno(), mode='w', encoding='utf-8', buffering=1)
if sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
    sys.stderr = open(sys.stderr.fileno(), mode='w', encoding='utf-8', buffering=1)

import fitz  # PyMuPDF
from PIL import Image, ImageDraw
from dotenv import load_dotenv

# We use the modern standard google-genai SDK
from google import genai
from google.genai.errors import APIError

load_dotenv()

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("ocr_gemini")

def count_page_markers(text: str) -> int:
    """Counts the number of PAGE markers in the text chunk."""
    pattern = r'(?:^|\n)(?:---\s*)?[Pp][Aa][Gg][Ee]\s*(\d+)'
    return len(re.findall(pattern, text))

def get_page_image(page: fitz.Page, dpi: int = 150) -> Image.Image:
    """Renders a PyMuPDF page to a PIL Image at the specified DPI."""
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat)
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    return img

def mask_camscanner_watermark(img: Image.Image) -> Image.Image:
    """
    Masks the bottom 5% of the page with a white rectangle to hide
    the 'Scanned by CamScanner' footer before sending to Gemini.
    """
    draw = ImageDraw.Draw(img)
    width, height = img.size
    crop_height = int(height * 0.05)
    bottom_rect = [0, height - crop_height, width, height]
    draw.rectangle(bottom_rect, fill="white")
    return img

def call_gemini_ocr_with_retry(client: genai.Client, model_id: str, content_items: list, max_retries: int = 5) -> str:
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

def split_pdf_into_temp_chunks(input_path: str, chunk_size: int, start_page: int, end_page: int, temp_dir: str) -> list[tuple[str, int, int]]:
    """
    Splits the PDF into smaller chunks and saves them in temp_dir.
    Returns list of (chunk_path, start_page_num, end_page_num).
    """
    logger.info("Splitting PDF into chunks of %d pages...", chunk_size)
    doc = fitz.open(input_path)
    chunks = []
    
    for i in range(start_page, end_page, chunk_size):
        chunk_end = min(i + chunk_size, end_page)
        chunk_name = os.path.join(temp_dir, f"chunk_{i+1}_to_{chunk_end}.pdf")
        
        chunk_doc = fitz.open()
        chunk_doc.insert_pdf(doc, from_page=i, to_page=chunk_end - 1)
        chunk_doc.save(chunk_name)
        chunk_doc.close()
        
        logger.info("  Created chunk: %s (Pages %d to %d)", os.path.basename(chunk_name), i + 1, chunk_end)
        chunks.append((chunk_name, i, chunk_end))
        
    doc.close()
    return chunks

def process_chunk_with_files_api(client: genai.Client, model_id: str, chunk_path: str, prompt: str) -> str:
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
    text = call_gemini_ocr_with_retry(client, model_id, [uploaded_file, prompt])
    
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
            # Check if this is a single page key from 'page' mode
            if chunk_key.isdigit():
                page_map[int(chunk_key) + 1] = text.strip()
            continue
            
        c_start = int(match_key.group(1))
        c_end = int(match_key.group(2))
        
        matches = re.findall(pattern, text, re.DOTALL)
        if not matches:
            continue
            
        # Determine the best offset for this chunk using majority vote
        offset_votes = {}
        possible_offsets = [0, 14, c_start]
        
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

def parse_page_range(s: str) -> Optional[tuple[int, int]]:
    """Parse '10-50' into (10, 50). Returns None if empty."""
    if not s:
        return None
    parts = s.split("-")
    if len(parts) == 1:
        p = int(parts[0])
        return (p, p)
    return (int(parts[0]), int(parts[1]))

def main():
    parser = argparse.ArgumentParser(description="Gemini API-based OCR Pipeline for Scanned PDFs")
    parser.add_argument("-i", "--input", required=True, help="Path to the scanned input PDF")
    parser.add_argument("-op", "--output-pdf", help="Path for output searchable PDF")
    parser.add_argument("-ot", "--output-txt", help="Path for output text report")
    parser.add_argument("--pages", help="Page range to process, e.g., '1-50'")
    parser.add_argument("--model", default="gemini-2.5-flash-lite", help="Gemini model to use (default: gemini-2.5-flash-lite)")
    parser.add_argument("--mode", choices=["page", "chunk"], default="chunk", 
                        help="OCR Mode: 'page' (renders pages to images, page-by-page) or 'chunk' (uses Gemini Files API on PDF chunks, default: chunk)")
    parser.add_argument("--chunk-size", type=int, default=50, help="Number of pages per PDF chunk in 'chunk' mode (default: 50)")
    parser.add_argument("--dpi", type=int, default=150, help="Render DPI for Gemini input in 'page' mode (default: 150)")
    
    args = parser.parse_args()
    
    input_pdf = os.path.abspath(args.input)
    if not os.path.exists(input_pdf):
        logger.error("Input file not found: %s", input_pdf)
        sys.exit(1)
        
    base_dir = os.path.dirname(input_pdf)
    filename, _ = os.path.splitext(os.path.basename(input_pdf))
    
    output_pdf = args.output_pdf or os.path.join(base_dir, f"{filename}_searchable.pdf")
    output_txt = args.output_txt or os.path.join(base_dir, f"{filename}_ocr_data.txt")
    cache_file = os.path.join(base_dir, f"{filename}_ocr_cache.json")
    
    page_range = parse_page_range(args.pages)
    
    if not os.environ.get("GEMINI_API_KEY"):
        logger.error("GEMINI_API_KEY is not set in environment.")
        sys.exit(1)
        
    client = genai.Client()
    
    # Load cache if exists
    cache = {}
    if os.path.exists(cache_file):
        with open(cache_file, "r", encoding="utf-8") as f:
            try:
                cache = json.load(f)
                logger.info("Loaded OCR cache with %d entries.", len(cache))
            except json.JSONDecodeError:
                logger.warning("Cache file is corrupted. Starting fresh.")
                
    doc = fitz.open(input_pdf)
    total_pages = len(doc)
    start_p = (page_range[0] - 1) if page_range else 0
    end_p = min(page_range[1], total_pages) if page_range else total_pages
    doc.close()
    
    logger.info("Running Gemini OCR in '%s' mode (pages %d to %d, total %d) using %s", 
                args.mode, start_p + 1, end_p, total_pages, args.model)
    
    if args.mode == "page":
        prompt = (
            "Perform optical character recognition (OCR) on this medical textbook page. "
            "Extract all text exactly as it reads. Preserve structure, headings, page numbers, and bullet points. "
            "Do not include any conversational introductions, summaries, or markdown block formatting. "
            "Just output the plain text of the page."
        )
        
        doc = fitz.open(input_pdf)
        # Iterate pages
        for page_num in range(start_p, end_p):
            page_key = str(page_num)
            page = doc[page_num]
            
            # OCR Extraction (or cache hit)
            if page_key in cache:
                extracted_text = cache[page_key]
                logger.info("[Page %d/%d] Loaded from cache (%d words)", page_num + 1, end_p, len(extracted_text.split()))
            else:
                logger.info("[Page %d/%d] Rendering and calling Gemini API...", page_num + 1, end_p)
                img = get_page_image(page, dpi=args.dpi)
                img = mask_camscanner_watermark(img)
                
                extracted_text = call_gemini_ocr_with_retry(client, args.model, [img, prompt])
                
                # Save to cache
                cache[page_key] = extracted_text
                with open(cache_file, "w", encoding="utf-8") as f:
                    json.dump(cache, f, indent=2, ensure_ascii=False)
                    
                logger.info("[Page %d/%d] OCR complete (%d words)", page_num + 1, end_p, len(extracted_text.split()))
                
                # Simple rate limiting pause
                time.sleep(12.0)
                
        doc.close()
                
    elif args.mode == "chunk":
        # Create a temp directory for chunk PDFs
        import tempfile
        temp_dir = tempfile.mkdtemp()
        
        prompt = (
            "Perform optical character recognition (OCR) on this entire document. "
            "Extract all text precisely as it reads page-by-page. Mark each page starting boundary clearly "
            "with '--- PAGE X ---' where X is the absolute page number of the textbook page. "
            "Do not leave out any text blocks. Do not append conversational introductions or summaries."
        )
        
        chunks = split_pdf_into_temp_chunks(input_pdf, args.chunk_size, start_p, end_p, temp_dir)
        
        for chunk_path, c_start, c_end in chunks:
            chunk_key = f"chunk_{c_start}_{c_end}"
            
            if chunk_key in cache:
                extracted_text = cache[chunk_key]
                logger.info("Chunk [%d to %d] Loaded from cache", c_start + 1, c_end)
            else:
                try:
                    extracted_text = process_chunk_with_files_api(client, args.model, chunk_path, prompt)
                    
                    # Verify output is not truncated before saving
                    markers = count_page_markers(extracted_text)
                    expected_pages_in_chunk = c_end - c_start
                    threshold = int(expected_pages_in_chunk * 0.8)
                    
                    if markers < threshold:
                        logger.warning("Gemini returned truncated output for %s (%d markers). Retrying...", chunk_key, markers)
                        time.sleep(15.0)
                        continue
                        
                    cache[chunk_key] = extracted_text
                    with open(cache_file, "w", encoding="utf-8") as f:
                        json.dump(cache, f, indent=2, ensure_ascii=False)
                        
                    logger.info("Successfully saved chunk %s to cache.", chunk_key)
                    
                    # Stay safely under 5 RPM limit
                    time.sleep(15.0)
                except Exception as e:
                    logger.error("Failed to process chunk [%d to %d]: %s", c_start + 1, c_end, e)
                    # Clean up local temp files on failure
                    try:
                        os.remove(chunk_path)
                    except:
                        pass
                    sys.exit(1)
            
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
            
            try:
                page.insert_textbox(
                    rect,
                    safe_text,
                    fontsize=8,
                    render_mode=3,
                    overlay=True
                )
            except Exception as e:
                logger.warning("Failed to insert text layer on page %d: %s", pdf_page_num, e)
                
    # Save the searchable PDF (incremental save or new file)
    logger.info("Saving searchable PDF to %s...", output_pdf)
    doc.save(output_pdf, garbage=3, deflate=True)
    doc.close()
    
    # Save text report
    logger.info("Saving text report to %s...", output_txt)
    with open(output_txt, "w", encoding="utf-8") as f:
        f.write("========================================================================\n")
        f.write(f"GEMINI OCR & SEARCHABLE PDF REPORT\n")
        f.write("========================================================================\n")
        f.write(f"Source PDF:       {input_pdf}\n")
        f.write(f"Searchable PDF:   {output_pdf}\n")
        f.write(f"Model Used:       {args.model}\n")
        f.write(f"OCR Mode:         {args.mode}\n")
        f.write("========================================================================\n\n")
        
        for p_num in sorted(page_text_map.keys()):
            f.write(f"--- PAGE {p_num} ---\n")
            f.write(page_text_map[p_num])
            f.write("\n\n")
            
    logger.info("Pipeline finished successfully!")

if __name__ == "__main__":
    main()
