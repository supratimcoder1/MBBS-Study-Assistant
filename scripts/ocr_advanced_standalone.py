"""
Advanced OCR Standalone Script — Adaptive Preprocessing Pipeline
================================================================

Tests the enhanced adaptive preprocessing strategy for scanned PDFs before
integrating into the main system. Implements 4 progressive stages:

  Stage 1 — Render at 400 DPI (better upscaling base vs native ~120 DPI source)
  Stage 2 — Adaptive preprocessing per-page:
               • Median denoising   (removes salt-and-pepper / CamScanner noise)
               • CLAHE-like autocontrast  (normalises uneven scan brightness)
               • Unsharp masking         (recovers edge definition lost to low DPI)
               • Adaptive local thresholding  (handles two-column & shadow regions)
  Stage 3 — OCRmyPDF with deskew + Sauvola thresholding (no manual binarisation)
  Stage 4 — Post-OCR text cleanup:
               • Strips CamScanner watermark strings
               • Saves cleaned text report alongside the searchable PDF

Usage:
  .venv\\Scripts\\python.exe ocr_advanced_standalone.py --input "path/to/scanned.pdf"
  .venv\\Scripts\\python.exe ocr_advanced_standalone.py --input "path/to/scanned.pdf" --dpi 400 --pages 1-20 --strategy adaptive

Requirements:
  pip install pymupdf Pillow numpy ocrmypdf
  Tesseract OCR  → C:\\Program Files\\Tesseract-OCR
  Ghostscript    → C:\\Program Files\\gs\\gs10.04.0\\bin
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from tempfile import TemporaryDirectory
from typing import Optional

# Force UTF-8 I/O on Windows so Unicode characters in logs/help don't crash
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import fitz                         # PyMuPDF
import numpy as np
from PIL import Image, ImageFilter, ImageOps

# Logging (configured after stdout is UTF-8 safe)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("ocr_advanced")


# ── Paths for Windows ────────────────────────────────────────────────────────
GS_PATH = r"C:\Program Files\gs\gs10.04.0\bin"
TESS_PATH = r"C:\Program Files\Tesseract-OCR"

# CamScanner watermark patterns to remove from extracted text
WATERMARK_PATTERNS = [
    r"[Ss]canned\s+(by|with)\s+[Cc]am[Ss]can(?:ner)?",
    r"[Ss]canned\s+with\s+\([a-zA-Z,\.]+\)[Ss]can(?:ner|aer|aner)?",
    r"\(?rm,?[Ss]can(?:ner|aer|aner)?\)?",
    r"[Gg]am[Ss]can(?:ner|cer)?",
    r"[Ss]am[Ss]ean(?:iner)?",
    r"[Cc]rm[Ss]cana(?:er|ner)?",
]
WATERMARK_RE = re.compile("|".join(WATERMARK_PATTERNS), re.IGNORECASE)


# ─────────────────────────────────────────────────────────────────────────────
# Data class to hold per-page statistics for the quality report
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class PageStats:
    page_num: int
    render_dpi: int
    mean_pixel: float
    std_pixel: float
    otsu_threshold: int
    adaptive_threshold_used: bool
    word_count_raw: int       # words before watermark stripping
    word_count_clean: int     # words after
    watermarks_removed: int
    processing_ms: int


# ─────────────────────────────────────────────────────────────────────────────
# 1. Otsu's threshold calculation (pure NumPy, no OpenCV dependency)
# ─────────────────────────────────────────────────────────────────────────────
def otsu_threshold(gray_arr: np.ndarray) -> int:
    """Compute Otsu's optimal binarisation threshold from a grayscale array."""
    hist, _ = np.histogram(gray_arr.ravel(), bins=256, range=(0, 256))
    total = gray_arr.size
    sum_total = float(np.sum(np.arange(256) * hist))
    sum_bg, w_bg, best_var, threshold = 0.0, 0, 0.0, 128

    for t in range(256):
        w_bg += hist[t]
        if w_bg == 0:
            continue
        w_fg = total - w_bg
        if w_fg == 0:
            break
        sum_bg += t * hist[t]
        mean_bg = sum_bg / w_bg
        mean_fg = (sum_total - sum_bg) / w_fg
        var = w_bg * w_fg * (mean_bg - mean_fg) ** 2
        if var > best_var:
            best_var = var
            threshold = t

    return threshold


# ─────────────────────────────────────────────────────────────────────────────
# 2. Adaptive local threshold (Sauvola-style via PIL BoxBlur)
# ─────────────────────────────────────────────────────────────────────────────
def adaptive_threshold(gray_arr: np.ndarray, block_size: int = 35, c: int = 8) -> np.ndarray:
    """
    Local adaptive threshold.  For each pixel, threshold = local_mean - C.
    block_size: neighbourhood radius (odd number recommended)
    c:          constant subtracted from local mean (tune for scan darkness)
    """
    gray_img = Image.fromarray(gray_arr)
    # Use PIL BoxBlur as local mean approximation
    blurred = gray_img.filter(ImageFilter.BoxBlur(block_size // 2))
    local_mean = np.array(blurred, dtype=np.float32)
    binary = ((gray_arr.astype(np.float32) > (local_mean - c)) * 255).astype(np.uint8)
    return binary


# ─────────────────────────────────────────────────────────────────────────────
# 3. Full adaptive preprocessing pipeline for one PIL image
# ─────────────────────────────────────────────────────────────────────────────
def preprocess_page(img: Image.Image, strategy: str = "adaptive") -> tuple[Image.Image, dict]:
    """
    Apply preprocessing to a rendered page image.

    Strategies
    ----------
    "simple"   — Current approach: grayscale + fixed threshold 128
    "otsu"     — Grayscale + Otsu global threshold
    "adaptive" — Full pipeline: denoise → autocontrast → sharpen → adaptive local threshold
    "passthrough" — No binarisation; pass grayscale directly (let OCRmyPDF handle it)

    Returns (processed_image, stats_dict)
    """
    gray = img.convert("L")
    gray_arr = np.array(gray, dtype=np.uint8)
    stats: dict = {
        "mean": float(gray_arr.mean()),
        "std": float(gray_arr.std()),
        "otsu_t": 0,
        "adaptive_used": False,
    }

    if strategy == "simple":
        binary = gray.point(lambda p: 255 if p > 128 else 0)
        return binary, stats

    if strategy == "otsu":
        t = otsu_threshold(gray_arr)
        stats["otsu_t"] = t
        binary = Image.fromarray(((gray_arr > t) * 255).astype(np.uint8))
        return binary, stats

    if strategy == "passthrough":
        stats["adaptive_used"] = False
        return gray, stats

    # ── "adaptive" strategy (the new recommended path) ─────────────────────
    stats["adaptive_used"] = True

    # Step 1: Median denoise — removes salt-and-pepper noise from phone scans
    denoised = gray.filter(ImageFilter.MedianFilter(size=3))

    # Step 2: Auto-contrast with small cutoff — normalises brightness
    # across pages that vary from very dark (mean ~168) to very light (mean ~245)
    contrasted = ImageOps.autocontrast(denoised, cutoff=1.5)

    # Step 3: Unsharp mask — recovers edge definition lost to the ~120 DPI source
    sharpened = contrasted.filter(ImageFilter.UnsharpMask(radius=1, percent=120, threshold=3))

    # Step 4: Adaptive local threshold
    # Handles uneven illumination from phone-camera scans and two-column layouts
    sharpened_arr = np.array(sharpened, dtype=np.uint8)
    t_otsu = otsu_threshold(sharpened_arr)
    stats["otsu_t"] = t_otsu

    # Choose block_size based on mean brightness to be gentler on light pages
    mean_px = float(sharpened_arr.mean())
    block_size = 35 if mean_px < 200 else 45
    c = 8 if mean_px < 200 else 5          # less aggressive for already-light pages

    binary_arr = adaptive_threshold(sharpened_arr, block_size=block_size, c=c)
    binary = Image.fromarray(binary_arr)

    return binary, stats


# ─────────────────────────────────────────────────────────────────────────────
# 4. Build a preprocessed PDF (one image per page) ready for OCRmyPDF
# ─────────────────────────────────────────────────────────────────────────────
def build_preprocessed_pdf(
    input_path: str,
    output_path: str,
    render_dpi: int,
    strategy: str,
    page_range: Optional[tuple[int, int]],
    page_stats_out: list[PageStats],
) -> None:
    """
    Render every page of input_path at render_dpi, apply preprocessing,
    and compile into a single PDF at output_path.
    """
    doc = fitz.open(input_path)
    total = len(doc)
    start_p = (page_range[0] - 1) if page_range else 0
    end_p   = min(page_range[1], total) if page_range else total

    logger.info(
        "Pre-processing pages %d–%d of %d at %d DPI using strategy '%s'",
        start_p + 1, end_p, total, render_dpi, strategy,
    )

    new_doc = fitz.open()

    with TemporaryDirectory() as tmpdir:
        zoom = render_dpi / 72.0
        mat = fitz.Matrix(zoom, zoom)

        for page_num in range(start_p, end_p):
            t0 = time.monotonic()
            page = doc[page_num]
            pix = page.get_pixmap(matrix=mat)

            # Render → PIL
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

            # Preprocess
            processed, stats = preprocess_page(img, strategy=strategy)

            # Save as single-page PDF (needed for fitz.insert_pdf)
            page_pdf_path = os.path.join(tmpdir, f"page_{page_num:05d}.pdf")
            processed.save(page_pdf_path, format="PDF", resolution=render_dpi)

            # Append to output doc
            with fitz.open(page_pdf_path) as page_doc:
                new_doc.insert_pdf(page_doc)

            elapsed_ms = int((time.monotonic() - t0) * 1000)
            page_stats_out.append(PageStats(
                page_num=page_num + 1,
                render_dpi=render_dpi,
                mean_pixel=stats["mean"],
                std_pixel=stats["std"],
                otsu_threshold=stats["otsu_t"],
                adaptive_threshold_used=stats["adaptive_used"],
                word_count_raw=0,
                word_count_clean=0,
                watermarks_removed=0,
                processing_ms=elapsed_ms,
            ))

            if (page_num - start_p + 1) % 10 == 0 or page_num == end_p - 1:
                logger.info(
                    "  Preprocessed %d / %d pages  (mean=%.1f, otsu_t=%d, %d ms)",
                    page_num - start_p + 1, end_p - start_p,
                    stats["mean"], stats["otsu_t"], elapsed_ms,
                )

        new_doc.save(output_path)
        new_doc.close()

    doc.close()
    logger.info("Pre-processed PDF saved → %s", output_path)


# ─────────────────────────────────────────────────────────────────────────────
# 5. OCRmyPDF runner — adaptive flags
# ─────────────────────────────────────────────────────────────────────────────
def run_ocrmypdf(
    input_pdf: str,
    output_pdf: str,
    render_dpi: int,
    skip_binarisation: bool = False,
) -> None:
    """
    Run OCRmyPDF with the enhanced flag set.

    skip_binarisation=True  → pass the already-preprocessed PDF directly;
                               tell OCRmyPDF not to re-binarise (--tesseract-thresholding=none
                               is not a real flag, so we omit --clean and skip thresholding flag)
    skip_binarisation=False → let OCRmyPDF handle binarisation with Sauvola (fallback to adaptive-otsu)
    """
    env = os.environ.copy()
    paths_to_add = [p for p in [GS_PATH, TESS_PATH] if os.path.exists(p)]
    if paths_to_add:
        env["PATH"] = os.pathsep.join(paths_to_add) + os.pathsep + env.get("PATH", "")

    # Base flags always applied
    cmd = [
        sys.executable, "-m", "ocrmypdf",
        "--force-ocr",
        "--deskew",                  # correct tilted pages
        "--rotate-pages",            # fix upside-down / sideways pages
        "--image-dpi", str(render_dpi),
        "--optimize", "1",           # compress output without quality loss
        "--jobs", "1",               # sequential for stability on Windows
    ]

    if not skip_binarisation:
        # Let OCRmyPDF do its own binarisation using Sauvola adaptive method
        # Try sauvola first; fall back to adaptive-otsu if unsupported
        cmd += ["--tesseract-thresholding", "sauvola"]
        cmd += ["--clean"]           # unpaper noise removal before Tesseract

    cmd += [input_pdf, output_pdf]

    logger.info("Running OCRmyPDF: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)

    if result.returncode == 0 and os.path.exists(output_pdf):
        logger.info("OCRmyPDF succeeded → %s", output_pdf)
        return

    # If sauvola failed (not supported), retry without thresholding flag
    if not skip_binarisation and result.returncode != 0:
        logger.warning(
            "OCRmyPDF with --tesseract-thresholding sauvola failed (code %d). "
            "Retrying with adaptive-otsu…",
            result.returncode,
        )
        cmd2 = [c for c in cmd if c not in ("sauvola", "--tesseract-thresholding")]
        cmd2.insert(-2, "--tesseract-thresholding")
        cmd2.insert(-2, "adaptive-otsu")
        result = subprocess.run(cmd2, capture_output=True, text=True, env=env)

        if result.returncode == 0 and os.path.exists(output_pdf):
            logger.info("OCRmyPDF with adaptive-otsu succeeded → %s", output_pdf)
            return

    # Both failed — log and raise
    logger.error("OCRmyPDF STDOUT:\n%s", result.stdout[-3000:])
    logger.error("OCRmyPDF STDERR:\n%s", result.stderr[-3000:])
    raise RuntimeError(f"OCRmyPDF failed with exit code {result.returncode}")


# ─────────────────────────────────────────────────────────────────────────────
# 6. Extract and clean text from the output PDF
# ─────────────────────────────────────────────────────────────────────────────
def extract_and_clean_text(
    pdf_path: str,
    page_stats: list[PageStats],
) -> tuple[list, str]:
    """Extract embedded TOC and full text from the searchable PDF.
    Strips CamScanner watermarks and updates word counts in page_stats."""
    doc = fitz.open(pdf_path)
    toc = doc.get_toc(simple=True)

    page_stat_map = {s.page_num: s for s in page_stats}
    text_parts: list[str] = []

    for page_num in range(len(doc)):
        raw_text = doc[page_num].get_text("text")

        # Strip CamScanner watermarks
        wm_count = len(WATERMARK_RE.findall(raw_text))
        clean_text = WATERMARK_RE.sub("", raw_text).strip()

        text_parts.append(f"\n--- PAGE {page_num + 1} ---\n{clean_text}")

        # Update stats if we have an entry for this page
        if (page_num + 1) in page_stat_map:
            s = page_stat_map[page_num + 1]
            s.word_count_raw = len(raw_text.split())
            s.word_count_clean = len(clean_text.split())
            s.watermarks_removed = wm_count

    doc.close()
    return toc, "\n".join(text_parts)


# ─────────────────────────────────────────────────────────────────────────────
# 7. Quality report
# ─────────────────────────────────────────────────────────────────────────────
def write_report(
    report_path: str,
    input_pdf: str,
    output_pdf: str,
    strategy: str,
    render_dpi: int,
    toc: list,
    full_text: str,
    page_stats: list[PageStats],
) -> None:
    """Write a comprehensive text report of the OCR run."""

    total_pages = len(page_stats)
    total_words = sum(s.word_count_clean for s in page_stats)
    total_wm = sum(s.watermarks_removed for s in page_stats)
    avg_ms = int(sum(s.processing_ms for s in page_stats) / max(total_pages, 1))
    dark_pages  = [s.page_num for s in page_stats if s.mean_pixel < 180]
    light_pages = [s.page_num for s in page_stats if s.mean_pixel > 230]

    sep = "=" * 72

    def fmt_toc(toc_list: list) -> str:
        lines = []
        for entry in toc_list:
            if len(entry) >= 3:
                lvl, title, pg = entry[:3]
                lines.append("  " * (lvl - 1) + f"{'└─ ' if lvl > 1 else '■ '}{title} (p.{pg})")
        return "\n".join(lines) if lines else "[No embedded TOC found]"

    with open(report_path, "w", encoding="utf-8") as f:
        f.write(f"{sep}\n")
        f.write(f" ADVANCED OCR REPORT — Adaptive Preprocessing Strategy\n")
        f.write(f"{sep}\n")
        f.write(f" Input PDF   : {input_pdf}\n")
        f.write(f" Output PDF  : {output_pdf}\n")
        f.write(f" Strategy    : {strategy}\n")
        f.write(f" Render DPI  : {render_dpi}\n")
        f.write(f" Pages proc. : {total_pages}\n")
        f.write(f" TOC nodes   : {len(toc)}\n")
        f.write(f" Total words : {total_words}\n")
        f.write(f" Watermarks  : {total_wm} occurrences removed\n")
        f.write(f" Avg preproc : {avg_ms} ms/page\n")
        f.write(f"{sep}\n\n")

        f.write("--- TABLE OF CONTENTS ---\n")
        f.write(fmt_toc(toc))
        f.write("\n\n--- RAW TOC (JSON) ---\n")
        f.write(json.dumps(toc, indent=2))
        f.write("\n\n")

        f.write(f"{sep}\n")
        f.write("--- PAGE STATISTICS ---\n")
        f.write(f"{'Page':>5}  {'Mean':>6}  {'Std':>5}  {'OtsuT':>6}  {'Words':>6}  {'WM':>3}  {'ms':>5}\n")
        f.write("-" * 50 + "\n")
        for s in page_stats:
            f.write(
                f"{s.page_num:>5}  {s.mean_pixel:>6.1f}  {s.std_pixel:>5.1f}  "
                f"{s.otsu_threshold:>6}  {s.word_count_clean:>6}  {s.watermarks_removed:>3}  {s.processing_ms:>5}\n"
            )

        if dark_pages:
            f.write(f"\nDark pages (mean<180): {dark_pages}\n")
        if light_pages:
            f.write(f"Light pages (mean>230): {light_pages}\n")

        f.write(f"\n{sep}\n")
        f.write("--- EXTRACTED TEXT CONTENT ---\n")
        f.write(f"{sep}\n")
        f.write(full_text)

    logger.info("Report written → %s", report_path)


# ─────────────────────────────────────────────────────────────────────────────
# 8. CLI entry point
# ─────────────────────────────────────────────────────────────────────────────
def parse_page_range(s: str) -> Optional[tuple[int, int]]:
    """Parse '10-50' into (10, 50). Returns None if s is empty."""
    if not s:
        return None
    parts = s.split("-")
    if len(parts) == 1:
        p = int(parts[0])
        return (p, p)
    return (int(parts[0]), int(parts[1]))


def main():
    parser = argparse.ArgumentParser(
        description="Advanced adaptive OCR pipeline — test before system integration",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Full book with adaptive strategy
  python ocr_advanced_standalone.py --input "Debashis Paramanik (6th ed).pdf"

  # First 30 pages only, for quick testing
  python ocr_advanced_standalone.py --input book.pdf --pages 1-30

  # Compare strategies: run once with each flag and compare the report
  python ocr_advanced_standalone.py --input book.pdf --pages 1-30 --strategy adaptive
  python ocr_advanced_standalone.py --input book.pdf --pages 1-30 --strategy simple
  python ocr_advanced_standalone.py --input book.pdf --pages 1-30 --strategy otsu

Strategies:
  adaptive    [RECOMMENDED] Full pipeline: denoise → autocontrast → sharpen → local adaptive threshold
  simple      Current system approach: fixed threshold at 128 (baseline for comparison)
  otsu        Global Otsu threshold (single optimal t per page)
  passthrough No binarisation; OCRmyPDF handles everything with Sauvola
        """,
    )
    parser.add_argument("-i", "--input", required=True, help="Path to input scanned PDF")
    parser.add_argument(
        "-op", "--output-pdf",
        help="Output searchable PDF path (default: <input>_advanced_ocr.pdf)",
    )
    parser.add_argument(
        "-ot", "--output-txt",
        help="Output text report path (default: <input>_advanced_ocr_report.txt)",
    )
    parser.add_argument(
        "--dpi", type=int, default=400,
        help="Render DPI for page rasterisation (default: 400, was 300 in old system)",
    )
    parser.add_argument(
        "--pages", default="",
        help="Page range to process, e.g. '1-50'. Omit for all pages.",
    )
    parser.add_argument(
        "--strategy",
        choices=["adaptive", "simple", "otsu", "passthrough"],
        default="adaptive",
        help="Preprocessing strategy (default: adaptive)",
    )
    parser.add_argument(
        "--keep-preprocessed", action="store_true",
        help="Keep the intermediate pre-processed PDF for inspection",
    )

    args = parser.parse_args()

    input_pdf = os.path.abspath(args.input)
    if not os.path.exists(input_pdf):
        logger.error("Input file not found: %s", input_pdf)
        sys.exit(1)

    base_dir = os.path.dirname(input_pdf)
    stem = os.path.splitext(os.path.basename(input_pdf))[0]

    output_pdf = args.output_pdf or os.path.join(base_dir, f"{stem}_advanced_ocr.pdf")
    output_txt = args.output_txt or os.path.join(base_dir, f"{stem}_advanced_ocr_report.txt")
    preprocessed_pdf = os.path.join(base_dir, f"{stem}_preprocessed_temp.pdf")

    page_range = parse_page_range(args.pages)

    logger.info("=" * 60)
    logger.info("Advanced OCR Pipeline Starting")
    logger.info("  Input    : %s", input_pdf)
    logger.info("  Strategy : %s", args.strategy)
    logger.info("  DPI      : %d", args.dpi)
    logger.info("  Pages    : %s", args.pages or "all")
    logger.info("=" * 60)

    page_stats: list[PageStats] = []
    run_start = time.monotonic()

    try:
        # ── Stage 1 & 2: Render + Preprocess ─────────────────────────────
        logger.info("\n[Stage 1/3] Rendering and preprocessing pages…")
        build_preprocessed_pdf(
            input_path=input_pdf,
            output_path=preprocessed_pdf,
            render_dpi=args.dpi,
            strategy=args.strategy,
            page_range=page_range,
            page_stats_out=page_stats,
        )

        # ── Stage 3: OCRmyPDF ─────────────────────────────────────────────
        logger.info("\n[Stage 2/3] Running OCRmyPDF on pre-processed PDF…")
        # For adaptive strategy: our preprocessing already binarised → tell OCRmyPDF
        # to skip its own binarisation step and just run Tesseract on the image.
        # For passthrough: let OCRmyPDF handle binarisation with Sauvola.
        skip_bin = args.strategy in ("adaptive", "simple", "otsu")
        run_ocrmypdf(
            input_pdf=preprocessed_pdf,
            output_pdf=output_pdf,
            render_dpi=args.dpi,
            skip_binarisation=skip_bin,
        )

        # ── Stage 4: Extract, clean, and report ───────────────────────────
        logger.info("\n[Stage 3/3] Extracting text and writing report…")
        toc, full_text = extract_and_clean_text(output_pdf, page_stats)
        write_report(
            report_path=output_txt,
            input_pdf=input_pdf,
            output_pdf=output_pdf,
            strategy=args.strategy,
            render_dpi=args.dpi,
            toc=toc,
            full_text=full_text,
            page_stats=page_stats,
        )

        elapsed = int(time.monotonic() - run_start)
        logger.info("\n%s", "=" * 60)
        logger.info("Pipeline complete in %dm %ds", elapsed // 60, elapsed % 60)
        logger.info("  Searchable PDF : %s", output_pdf)
        logger.info("  Text Report    : %s", output_txt)
        logger.info("  TOC nodes      : %d", len(toc))
        logger.info(
            "  Total words    : %d",
            sum(s.word_count_clean for s in page_stats),
        )
        logger.info(
            "  Watermarks rm  : %d",
            sum(s.watermarks_removed for s in page_stats),
        )
        logger.info("%s", "=" * 60)

    except Exception as exc:
        logger.exception("Pipeline failed: %s", exc)
        sys.exit(1)

    finally:
        if not args.keep_preprocessed and os.path.exists(preprocessed_pdf):
            try:
                os.remove(preprocessed_pdf)
                logger.info("Cleaned up temporary preprocessed PDF.")
            except OSError as e:
                logger.warning("Could not remove temp file: %s", e)


if __name__ == "__main__":
    main()
