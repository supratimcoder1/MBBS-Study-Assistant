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
logger = logging.getLogger("ocr_resume")

def count_page_markers(text: str) -> int:
    """Counts the number of PAGE markers in the text chunk."""
    pattern = r'(?:^|\n)(?:---\s*)?[Pp][Aa][Gg][Ee]\s*(\d+)'
    return len(re.findall(pattern, text))

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
                logger.warning("Rate limit/Quota hit. Retrying in %.1f seconds...", wait_time)
                time.sleep(wait_time)
            elif "demand" in str(e).lower() or "overloaded" in str(e).lower() or "503" in str(e):
                wait_time = base_wait * (2 ** attempt)
                logger.warning("Model in high demand / service overloaded. Retrying in %.1f seconds...", wait_time)
                time.sleep(wait_time)
            else:
                logger.error("API Error: %s", e)
                raise e
        except Exception as e:
            logger.error("Unexpected error during Gemini call: %s", e)
            wait_time = base_wait * (2 ** attempt)
            time.sleep(wait_time)
            
    raise RuntimeError(f"Failed to get OCR result from Gemini after {max_retries} attempts.")

def split_pdf_into_temp_chunk(input_path: str, start_page: int, end_page: int, temp_dir: str) -> str:
    """Splits a single chunk from the PDF and returns its path."""
    doc = fitz.open(input_path)
    chunk_name = os.path.join(temp_dir, f"chunk_{start_page+1}_to_{end_page}.pdf")
    
    chunk_doc = fitz.open()
    chunk_doc.insert_pdf(doc, from_page=start_page, to_page=end_page - 1)
    chunk_doc.save(chunk_name)
    chunk_doc.close()
    doc.close()
    return chunk_name

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

def main():
    parser = argparse.ArgumentParser(description="Automate & Resume Gemini OCR Chunks with Auto-Retry")
    parser.add_argument("-i", "--input", required=True, help="Path to the scanned input PDF")
    parser.add_argument("-op", "--output-pdf", help="Path for output searchable PDF")
    parser.add_argument("-ot", "--output-txt", help="Path for output text report")
    parser.add_argument("--model", default="gemini-2.5-flash-lite", help="Gemini model to use (default: gemini-2.5-flash-lite)")
    parser.add_argument("--chunk-size", type=int, default=50, help="Number of pages per PDF chunk (default: 50)")
    
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
    
    if not os.environ.get("GEMINI_API_KEY"):
        logger.error("GEMINI_API_KEY is not set in environment.")
        sys.exit(1)
        
    client = genai.Client()
    
    # Load cache
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
    doc.close()
    
    logger.info("Total pages in PDF: %d", total_pages)
    
    # Generate all expected chunks
    expected_chunks = []
    for i in range(0, total_pages, args.chunk_size):
        chunk_end = min(i + args.chunk_size, total_pages)
        expected_chunks.append((i, chunk_end))
        
    logger.info("Total expected chunks: %d", len(expected_chunks))
    
    # Identify missing or incomplete chunks
    # Incomplete if parsed page markers are less than 80% of pages in that chunk
    chunks_to_process = []
    for c_start, c_end in expected_chunks:
        chunk_key = f"chunk_{c_start}_{c_end}"
        expected_pages_in_chunk = c_end - c_start
        
        if chunk_key not in cache:
            logger.info("Chunk %s is MISSING.", chunk_key)
            chunks_to_process.append((c_start, c_end, "missing"))
        else:
            text = cache[chunk_key]
            markers = count_page_markers(text)
            # Threshold: 80% of expected pages
            threshold = int(expected_pages_in_chunk * 0.8)
            if markers < threshold:
                logger.warning("Chunk %s is INCOMPLETE (has %d page markers, expected ~%d). Will re-process.", chunk_key, markers, expected_pages_in_chunk)
                chunks_to_process.append((c_start, c_end, "incomplete"))
            else:
                logger.info("Chunk %s is complete (%d page markers).", chunk_key, markers)
                
    if not chunks_to_process:
        logger.info("All chunks are already present and complete in cache!")
    else:
        logger.info("Starting automation loop for %d chunks...", len(chunks_to_process))
        import tempfile
        temp_dir = tempfile.mkdtemp()
        
        prompt = (
            "Perform optical character recognition (OCR) on this entire document. "
            "Extract all text precisely as it reads page-by-page. Mark each page starting boundary clearly "
            "with '--- PAGE X ---' where X is the absolute page number of the textbook page. "
            "Do not leave out any text blocks. Do not append conversational introductions or summaries."
        )
        
        for c_start, c_end, status in chunks_to_process:
            chunk_key = f"chunk_{c_start}_{c_end}"
            logger.info("Processing %s chunk %s (%d to %d)...", status, chunk_key, c_start + 1, c_end)
            
            # Create chunk file
            chunk_path = split_pdf_into_temp_chunk(input_pdf, c_start, c_end, temp_dir)
            
            success = False
            retry_count = 0
            wait_time = 30.0
            
            while not success:
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
                    success = True
                    
                    # Wait between successful requests to stay under RPM
                    time.sleep(15.0)
                    
                except Exception as e:
                    retry_count += 1
                    logger.error("Error processing chunk %s: %s", chunk_key, e)
                    logger.info("Sleeping %d seconds before retry #%d...", wait_time, retry_count)
                    time.sleep(wait_time)
                    # Increase wait time for next retry (cap at 5 mins)
                    wait_time = min(wait_time * 1.5, 300.0)
                    
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
            
    # Step 6: Compilation of the Final Searchable PDF using parsed page texts
    logger.info("Compiling final searchable PDF by injecting text layer...")
    
    # Parse all pages from the cached chunk texts
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
                
    logger.info("Saving final searchable PDF to %s...", output_pdf)
    doc.save(output_pdf, garbage=3, deflate=True)
    doc.close()
    
    # Compile text report
    logger.info("Saving text report to %s...", output_txt)
    with open(output_txt, "w", encoding="utf-8") as f:
        f.write("========================================================================\n")
        f.write(f"GEMINI AUTOMATED RESUME OCR & SEARCHABLE PDF REPORT\n")
        f.write("========================================================================\n")
        f.write(f"Source PDF:       {input_pdf}\n")
        f.write(f"Searchable PDF:   {output_pdf}\n")
        f.write(f"Model Used:       {args.model}\n")
        f.write("========================================================================\n\n")
        
        # Sort and write all extracted page texts sequentially
        for p_num in sorted(page_text_map.keys()):
            f.write(f"--- PAGE {p_num} ---\n")
            f.write(page_text_map[p_num])
            f.write("\n\n")
            
    logger.info("OCR Automation & Compilation Finished Successfully!")

if __name__ == "__main__":
    main()
