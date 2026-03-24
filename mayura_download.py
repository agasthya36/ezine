#!/usr/bin/env python3
"""
Mayura E-Zine Downloader
========================
Downloads all pages of a Mayura edition and compiles them into a single PDF.

Usage:
    python mayura_download.py                        # downloads latest edition
    python mayura_download.py --date 01/03/2026      # specific edition date
    python mayura_download.py --date 01/03/2026 --pages 24 --output mayura_mar26.pdf

Dependencies:
    pip install requests Pillow
"""

import argparse
import sys
import time
from pathlib import Path

import requests
from PIL import Image

# ── Config ──────────────────────────────────────────────────────────────────

API_URL   = "http://mayuraezine.com/api/Login/GetAllEditions"
BASE_URL  = "http://mayuraezine.com"
HEADERS   = {"User-Agent": "Mozilla/5.0 (compatible; MayuraDownloader/1.0)"}
DELAY_SEC = 0.3   # polite delay between image requests


# ── Helpers ──────────────────────────────────────────────────────────────────

def get_latest_edition(date: str = "01/03/2026") -> dict:
    """Fetch edition list and return the freshest (or matching) entry."""
    params = {"date": date}
    resp = requests.get(API_URL, params=params, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    editions = resp.json()
    if not editions:
        raise RuntimeError("API returned no editions.")
    # Fresh==1 is the current edition; fallback to first entry
    fresh = next((e for e in editions if e.get("Fresh") == 1), editions[0])
    return fresh


def parse_url_template(full_page_url: str) -> tuple[str, str]:
    """
    Extract the base URL prefix and the filename stem from FullPageUrl.

    Example input:
        http://mayuraezine.com/Mayura_Fs\\030126\\page\\my03MAR01-164_1_mr.JPG

    Returns:
        base_prefix  = "http://mayuraezine.com/Mayura_Fs/030126/page/"
        stem         = "my03MAR01-164"      (everything before _1_mr.JPG)
        ext          = "mr.JPG"
    """
    # Normalise backslashes → forward slashes
    url = full_page_url.replace("\\", "/")
    # Make sure scheme is present
    if not url.startswith("http"):
        url = BASE_URL + "/" + url.lstrip("/")

    # Split into directory + filename
    dir_part  = url.rsplit("/", 1)[0] + "/"
    filename  = url.rsplit("/", 1)[1]            # e.g. my03MAR01-164_1_mr.JPG

    # Filename pattern: <stem>_<page>_mr.JPG
    # We want everything before the last two '_'-separated segments
    parts = filename.rsplit("_", 2)              # ['my03MAR01-164', '1', 'mr.JPG']
    if len(parts) != 3:
        raise ValueError(f"Unexpected filename format: {filename}")
    stem, _, suffix = parts                      # suffix = "mr.JPG"

    return dir_part, stem, suffix


def build_page_url(dir_prefix: str, stem: str, suffix: str, page: int) -> str:
    return f"{dir_prefix}{stem}_{page}_{suffix}"


def probe_page_count(dir_prefix: str, stem: str, suffix: str,
                     max_pages: int = 200) -> int:
    """
    Binary-search-style probe to find the last valid page number.
    Falls back to sequential scan if needed.
    """
    print("  Probing total page count …", end="", flush=True)

    # First confirm page 1 is reachable
    url1 = build_page_url(dir_prefix, stem, suffix, 1)
    r = requests.head(url1, headers=HEADERS, timeout=10)
    if r.status_code != 200:
        raise RuntimeError(f"Page 1 not reachable: {url1}  (HTTP {r.status_code})")

    # Binary search between 1 and max_pages
    lo, hi = 1, max_pages
    while lo < hi:
        mid = (lo + hi + 1) // 2
        url = build_page_url(dir_prefix, stem, suffix, mid)
        r = requests.head(url, headers=HEADERS, timeout=10)
        if r.status_code == 200:
            lo = mid
        else:
            hi = mid - 1

    print(f" {lo} pages found.")
    return lo


def download_images(dir_prefix: str, stem: str, suffix: str,
                    total_pages: int, tmp_dir: Path) -> list[Path]:
    """Download all page images into tmp_dir, return list of paths in order."""
    paths = []
    for page in range(1, total_pages + 1):
        url  = build_page_url(dir_prefix, stem, suffix, page)
        dest = tmp_dir / f"page_{page:04d}.jpg"

        if dest.exists():
            print(f"  [cache] page {page:3d}/{total_pages}")
            paths.append(dest)
            continue

        print(f"  ↓ page {page:3d}/{total_pages}  {url}")
        try:
            r = requests.get(url, headers=HEADERS, timeout=30, stream=True)
            r.raise_for_status()
            dest.write_bytes(r.content)
            paths.append(dest)
        except requests.HTTPError as e:
            print(f"    ✗ skipped (HTTP {e.response.status_code})")
        except Exception as e:
            print(f"    ✗ skipped ({e})")

        time.sleep(DELAY_SEC)

    return paths


def images_to_pdf(image_paths: list[Path], output_pdf: Path,
                  quality: int = 75) -> None:
    """
    Merge all downloaded images into a single PDF.

    quality: JPEG re-encoding quality (1-95).
             85  → near-lossless,  ~same size as original
             75  → good quality,   ~50-60% of original size  (default)
             60  → acceptable,     ~35-40% of original size
             40  → readable but visibly lossy
    """
    import io
    if not image_paths:
        raise RuntimeError("No images to merge.")

    print(f"\nBuilding PDF (JPEG quality={quality}) from {len(image_paths)} pages …")
    pil_images = []
    for p in image_paths:
        try:
            img = Image.open(p).convert("RGB")
            if quality < 85:
                # Re-encode in memory at target quality to reduce size
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=quality, optimize=True)
                buf.seek(0)
                img = Image.open(buf).convert("RGB")
                img.load()   # force decode before buf goes out of scope
            pil_images.append(img)
        except Exception as e:
            print(f"  ✗ skipping {p.name}: {e}")

    if not pil_images:
        raise RuntimeError("All images failed to open.")

    first, rest = pil_images[0], pil_images[1:]
    first.save(output_pdf, save_all=True, append_images=rest)
    size_mb = output_pdf.stat().st_size / 1_048_576
    print(f"✅  PDF saved → {output_pdf}  ({size_mb:.1f} MB)")
    if size_mb > 24:
        print("⚠️   Still over 24 MB — try a lower --quality value (e.g. 60).")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Download Mayura e-zine edition to PDF")
    parser.add_argument("--date",   default="01/03/2026",
                        help="Edition date in DD/MM/YYYY format (default: 01/03/2026)")
    parser.add_argument("--pages",  type=int, default=None,
                        help="Override page count (skip auto-detection)")
    parser.add_argument("--output", default=None,
                        help="Output PDF filename (auto-named if omitted)")
    parser.add_argument("--tmp",     default="./mayura_tmp",
                        help="Temp directory for downloaded images")
    parser.add_argument("--quality", type=int, default=75,
                        help="JPEG re-encoding quality 1-95 (default 75 ≈ half the size). "
                             "Use 85 for near-lossless, 60 for smallest file.")
    args = parser.parse_args()

    # 1. Fetch edition metadata
    print(f"\n[1/4] Fetching edition list for date={args.date} …")
    edition = get_latest_edition(args.date)
    print(f"      Edition: {edition.get('FileName', '?')}  |  "
          f"DateFolder={edition.get('DateFolder', '?')}  |  "
          f"Fresh={edition.get('Fresh')}")

    full_page_url = edition["FullPageUrl"]
    print(f"      FullPageUrl: {full_page_url}")

    # 2. Parse URL template
    dir_prefix, stem, suffix = parse_url_template(full_page_url)
    print(f"\n[2/4] URL template:\n"
          f"      Dir  : {dir_prefix}\n"
          f"      Stem : {stem}\n"
          f"      Suffix: {suffix}")

    # 3. Determine page count
    tmp_dir = Path(args.tmp)
    tmp_dir.mkdir(parents=True, exist_ok=True)

    print("\n[3/4] Determining page count …")
    total_pages = args.pages or probe_page_count(dir_prefix, stem, suffix)

    # 4. Download
    print(f"\n[4/4] Downloading {total_pages} pages to {tmp_dir}/ …\n")
    image_paths = download_images(dir_prefix, stem, suffix, total_pages, tmp_dir)

    # 5. Build PDF
    if args.output:
        out_pdf = Path(args.output)
    else:
        # Auto-name from stem: my03MAR01-164 → mayura_03MAR01-164.pdf
        out_pdf = Path(f"mayura_{stem.replace('my', '', 1)}.pdf")

    images_to_pdf(image_paths, out_pdf, quality=args.quality)


if __name__ == "__main__":
    main()