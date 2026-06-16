"""
Standalone PDF OCR and Hierarchy Extraction Script.

This script takes a scanned PDF, binarizes its pages, runs OCR using OCRmyPDF,
extracts the Table of Contents (TOC) using PyMuPDF's get_toc(), and saves
both the extracted hierarchy and the full text of the OCR'd PDF into a text file.

Requirements:
- fitz (PyMuPDF)
- Pillow (PIL)
- ocrmypdf
- Tesseract OCR installed at C:\\Program Files\\Tesseract-OCR
- Ghostscript installed at C:\\Program Files\\gs\\gs10.04.0\\bin

Usage:
  python ocr_standalone.py --input path/to/scanned.pdf [--output-pdf path/to/output.pdf] [--output-txt path/to/output.txt]
"""

import os
import sys
import argparse
import logging
import json
import subprocess
from tempfile import TemporaryDirectory
import fitz  # PyMuPDF
from PIL import Image

# Setup logging to console
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("pdf_ocr_standalone")

def binarize_pdf(input_path: str, output_path: str):
    """
    Renders each page of the input PDF to a 300 DPI image,
    binarizes the image (converts to black and white),
    and saves them compiled into a new binarized PDF.
    """
    logger.info("Starting binarization of %s...", input_path)
    doc = fitz.open(input_path)
    new_doc = fitz.open()
    
    with TemporaryDirectory() as tempdir:
        for page_num in range(len(doc)):
            logger.info("Binarizing page %d/%d...", page_num + 1, len(doc))
            page = doc[page_num]
            
            # Render page to 300 DPI image
            zoom = 300 / 72
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat)
            
            # Save raw rendered page to temp dir
            img_path_raw = os.path.join(tempdir, f"raw_{page_num}.png")
            img_path_pdf = os.path.join(tempdir, f"bin_{page_num}.pdf")
            
            pix.save(img_path_raw)
            
            # Open image, convert to grayscale, and binarize
            img = Image.open(img_path_raw).convert('L')
            # Simple thresholding: values > 128 become white (255), rest become black (0)
            img_binary = img.point(lambda p: p > 128 and 255)
            img_binary.save(img_path_pdf, format="PDF")
            
            # Insert binarized page into new PDF
            img_doc = fitz.open(img_path_pdf)
            new_doc.insert_pdf(img_doc)
            img_doc.close()
            
        new_doc.save(output_path)
        new_doc.close()
        doc.close()
    
    logger.info("Binarization complete. Saved to %s", output_path)

def run_ocr(binarized_path: str, searchable_path: str):
    """
    Runs OCRmyPDF on the binarized PDF.
    Sets up system path for Ghostscript and Tesseract OCR.
    """
    logger.info("Running OCRmyPDF on %s...", binarized_path)
    
    # Configure PATH to include Ghostscript and Tesseract on Windows
    env = os.environ.copy()
    gs_path = r"C:\Program Files\gs\gs10.04.0\bin"
    tesseract_path = r"C:\Program Files\Tesseract-OCR"
    
    paths = []
    if os.path.exists(gs_path):
        paths.append(gs_path)
    else:
        logger.warning("Ghostscript not found at default location: %s", gs_path)
        
    if os.path.exists(tesseract_path):
        paths.append(tesseract_path)
    else:
        logger.warning("Tesseract OCR not found at default location: %s", tesseract_path)
        
    if paths:
        env["PATH"] = os.pathsep.join(paths) + os.pathsep + env.get("PATH", "")
        
    # Execute ocrmypdf command
    ocrmypdf_cmd = [
        sys.executable, "-m", "ocrmypdf",
        "--force-ocr",
        binarized_path,
        searchable_path
    ]
    
    logger.info("Executing command: %s", " ".join(ocrmypdf_cmd))
    result = subprocess.run(ocrmypdf_cmd, capture_output=True, text=True, env=env)
    
    if result.returncode == 0 and os.path.exists(searchable_path):
        logger.info("OCR completed successfully. Saved searchable PDF to %s", searchable_path)
    else:
        logger.error("OCR failed with code %d", result.returncode)
        logger.error("Stdout:\n%s", result.stdout)
        logger.error("Stderr:\n%s", result.stderr)
        raise RuntimeError(f"OCRmyPDF failed with code {result.returncode}")

def extract_hierarchy_and_text(pdf_path: str) -> tuple[list, str]:
    """
    Extracts the table of contents and full text content from the PDF.
    """
    logger.info("Extracting TOC and text from %s...", pdf_path)
    doc = fitz.open(pdf_path)
    
    # Extract TOC
    toc = doc.get_toc(simple=True)  # Returns list of [level, title, page]
    
    # Extract text
    text_content = []
    for page_num in range(len(doc)):
        text_content.append(f"--- PAGE {page_num + 1} ---")
        text_content.append(doc[page_num].get_text("text"))
        
    doc.close()
    
    return toc, "\n".join(text_content)

def format_toc_tree(toc_list: list) -> str:
    """
    Formats the list of TOC entries into a clean visual tree.
    """
    lines = []
    for entry in toc_list:
        if len(entry) >= 3:
            level, title, page = entry[:3]
            indent = "  " * (level - 1)
            prefix = "└─ " if level > 1 else "■ "
            lines.append(f"{indent}{prefix}{title} (Page {page})")
    return "\n".join(lines)

def main():
    parser = argparse.ArgumentParser(description="Scanned PDF OCR & Hierarchy Extractor")
    parser.add_argument("-i", "--input", required=True, help="Path to input scanned PDF file")
    parser.add_argument("-op", "--output-pdf", help="Path to save the searchable PDF (default: <input>_searchable.pdf)")
    parser.add_argument("-ot", "--output-txt", help="Path to save the text report (default: <input>_ocr_data.txt)")
    
    args = parser.parse_args()
    
    input_pdf = os.path.abspath(args.input)
    if not os.path.exists(input_pdf):
        logger.error("Input file not found: %s", input_pdf)
        sys.exit(1)
        
    base_dir = os.path.dirname(input_pdf)
    filename_w_ext = os.path.basename(input_pdf)
    filename, _ = os.path.splitext(filename_w_ext)
    
    # Set default output paths if not provided
    output_pdf = args.output_pdf or os.path.join(base_dir, f"{filename}_searchable.pdf")
    output_txt = args.output_txt or os.path.join(base_dir, f"{filename}_ocr_data.txt")
    
    binarized_temp_pdf = os.path.join(base_dir, f"{filename}_temp_binarized.pdf")
    
    try:
        # Step 1: Binarize PDF
        binarize_pdf(input_pdf, binarized_temp_pdf)
        
        # Step 2: Run OCR
        run_ocr(binarized_temp_pdf, output_pdf)
        
        # Step 3: Extract TOC and text
        toc, full_text = extract_hierarchy_and_text(output_pdf)
        
        # Step 4: Format TOC
        formatted_toc = format_toc_tree(toc)
        
        # Step 5: Save report to text file
        logger.info("Saving metadata and text content to %s...", output_txt)
        with open(output_txt, "w", encoding="utf-8") as f:
            f.write("========================================================================\n")
            f.write(f"PDF OCR & HIERARCHY REPORT\n")
            f.write("========================================================================\n")
            f.write(f"Source PDF:       {input_pdf}\n")
            f.write(f"Searchable PDF:   {output_pdf}\n")
            f.write(f"TOC Nodes Found:  {len(toc)}\n")
            f.write("========================================================================\n\n")
            
            f.write("--- TABLE OF CONTENTS ---\n")
            if toc:
                f.write(formatted_toc)
            else:
                f.write("[No embedded TOC structure found in PDF]\n")
            f.write("\n\n")
            
            f.write("--- RAW TOC DATA (JSON) ---\n")
            f.write(json.dumps(toc, indent=2))
            f.write("\n\n")
            
            f.write("========================================================================\n")
            f.write("--- EXTRACTED TEXT CONTENT ---\n")
            f.write("========================================================================\n")
            f.write(full_text)
            
        logger.info("Successfully finished processing!")
        logger.info("Searchable PDF: %s", output_pdf)
        logger.info("Text Report:     %s", output_txt)
        
    except Exception as e:
        logger.exception("An error occurred during standalone OCR processing: %s", e)
        sys.exit(1)
        
    finally:
        # Clean up temporary binarized PDF
        if os.path.exists(binarized_temp_pdf):
            try:
                os.remove(binarized_temp_pdf)
                logger.info("Cleaned up temporary binarized PDF file.")
            except Exception as e:
                logger.warning("Failed to remove temporary binarized PDF file: %s", e)

if __name__ == "__main__":
    main()
