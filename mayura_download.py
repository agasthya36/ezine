#!/usr/bin/env python3
"""
E-Zine Downloader
=================
Downloads all pages of a supported e-zine edition and compiles them into a single PDF.

Usage:
    python mayura_download.py --publication mayura
    python mayura_download.py --publication sudha --date 26/03/2026
    python mayura_download.py --publication sudha --date 26/03/2026 --pages 64 --output sudha_w13.pdf

Dependencies:
    pip install requests aiohttp Pillow
"""

import argparse
from pathlib import Path
from datetime import datetime, timedelta

import asyncio
import aiohttp
import requests
from PIL import Image

# ── Config ──────────────────────────────────────────────────────────────────

HEADERS   = {"User-Agent": "Mozilla/5.0 (compatible; MayuraDownloader/1.0)"}
DELAY_SEC = 0.3   # polite delay between image requests

PUBLICATIONS = {
    "mayura": {
        "api_url": "http://mayuraezine.com/api/Login/GetAllEditions",
        "base_url": "http://mayuraezine.com",
        "output_prefix": "mayura",
        "default_date_mode": "month_start",
    },
    "sudha": {
        "api_url": "http://sudhaezine.com/api/Login/GetAllEditions",
        "base_url": "http://sudhaezine.com",
        "output_prefix": "sudha",
        "default_date_mode": "today",
    },
}


# ── Helpers ──────────────────────────────────────────────────────────────────

def get_latest_edition(api_url: str, date: str, fallback_days: int = 0) -> dict:
    """Fetch edition list and return the freshest (or nearest-previous) entry."""
    base_date = datetime.strptime(date, "%d/%m/%Y")

    for delta in range(0, fallback_days + 1):
        probe_date = (base_date - timedelta(days=delta)).strftime("%d/%m/%Y")
        params = {"date": probe_date}
        resp = requests.get(api_url, params=params, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        editions = resp.json()
        if not editions:
            continue

        # Fresh==1 is the current edition; fallback to first entry
        fresh = next((e for e in editions if e.get("Fresh") == 1), editions[0])
        if delta > 0:
            print(f"      No edition on requested date. Using previous available date: {probe_date}")
        return fresh

    raise RuntimeError(
        f"API returned no editions for {date} or previous {fallback_days} day(s)."
    )


def parse_url_template(full_page_url: str, base_url: str) -> tuple[str, str]:
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
        url = base_url + "/" + url.lstrip("/")

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


def default_date_for(publication: str) -> str:
    cfg = PUBLICATIONS[publication]
    now = datetime.now()
    if cfg["default_date_mode"] == "month_start":
        return now.strftime("01/%m/%Y")
    return now.strftime("%d/%m/%Y")


def auto_output_name(publication: str, stem: str) -> str:
    prefix = PUBLICATIONS[publication]["output_prefix"]
    return f"{prefix}_{stem}.pdf"


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


async def download_page(session: "aiohttp.ClientSession", url: str,
                        dest: Path, page: int, total: int,
                        semaphore: "asyncio.Semaphore") -> Path | None:
    """Download a single page image, respecting the concurrency semaphore."""
    if dest.exists():
        print(f"  [cache] page {page:3d}/{total}")
        return dest
    async with semaphore:
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as r:
                r.raise_for_status()
                dest.write_bytes(await r.read())
                print(f"  ↓ page {page:3d}/{total}  {url}")
                return dest
        except Exception as e:
            print(f"  ✗ page {page:3d} failed: {e}")
            return None


async def download_images_async(dir_prefix: str, stem: str, suffix: str,
                                total_pages: int, tmp_dir: Path,
                                concurrency: int = 8) -> list[Path]:
    """Download all pages concurrently, return paths in page order."""
    headers = {"User-Agent": "Mozilla/5.0 (compatible; MayuraDownloader/1.0)"}
    semaphore = asyncio.Semaphore(concurrency)

    async with aiohttp.ClientSession(headers=headers) as session:
        tasks = [
            download_page(
                session,
                build_page_url(dir_prefix, stem, suffix, page),
                tmp_dir / f"page_{page:04d}.jpg",
                page, total_pages, semaphore
            )
            for page in range(1, total_pages + 1)
        ]
        results = await asyncio.gather(*tasks)

    # Filter out failures, preserve order
    return [p for p in results if p is not None]


def download_images(dir_prefix: str, stem: str, suffix: str,
                    total_pages: int, tmp_dir: Path) -> list[Path]:
    """Sync wrapper around the async downloader."""
    return asyncio.run(download_images_async(dir_prefix, stem, suffix, total_pages, tmp_dir))


def images_to_pdf(image_paths: list[Path], output_pdf: Path,
                  quality: int = 75, scale: float = 1.0) -> None:
    """
    Embeds pages as raw DCTDecode JPEG objects in a hand-built PDF.

    scale:   downscale factor before re-encoding (most effective lever).
             1.0 = original size  (~40 MB for Mayura)
             0.7 = 70% dimensions (~12-15 MB, sharp on screen)
             0.5 = 50% dimensions (~6-8 MB,  fine for reading)
    quality: JPEG quality after scaling (75 is fine; below 60 rarely helps
             further because JPEG re-encoding hits a quantisation floor).
    """
    import io

    if not image_paths:
        raise RuntimeError("No images to merge.")

    print(f"\nBuilding PDF (scale={scale}, quality={quality}) "
          f"from {len(image_paths)} pages …")

    jpeg_pages = []
    for p in image_paths:
        try:
            img = Image.open(p).convert("RGB")
            if scale != 1.0:
                new_w = max(1, int(img.width  * scale))
                new_h = max(1, int(img.height * scale))
                img = img.resize((new_w, new_h), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=quality, optimize=True)
            data = buf.getvalue()
            print(f"  {p.name}  {p.stat().st_size // 1024}KB → {len(data) // 1024}KB")
            jpeg_pages.append((data, img.width, img.height))
        except Exception as e:
            print(f"  ✗ skipping {p.name}: {e}")

    if not jpeg_pages:
        raise RuntimeError("All images failed to process.")

    # Hand-built PDF: embed raw JPEG bytes via /DCTDecode (no Pillow re-encode)
    parts = [b"%PDF-1.4\n"]
    xrefs = []

    def obj(content: bytes) -> int:
        n = len(xrefs) + 1
        xrefs.append(sum(len(p) for p in parts))
        parts.append(f"{n} 0 obj\n".encode() + content + b"\nendobj\n")
        return n

    page_info = []
    for jpeg_bytes, w, h in jpeg_pages:
        img_id = obj((
            f"<< /Type /XObject /Subtype /Image "
            f"/Width {w} /Height {h} "
            f"/ColorSpace /DeviceRGB /BitsPerComponent 8 "
            f"/Filter /DCTDecode /Length {len(jpeg_bytes)} >>\nstream\n"
        ).encode() + jpeg_bytes + b"\nendstream")

        cs = f"q {w} 0 0 {h} 0 0 cm /Im{img_id} Do Q".encode()
        content_id = obj(
            f"<< /Length {len(cs)} >>\nstream\n".encode() + cs + b"\nendstream"
        )
        page_info.append((content_id, img_id, w, h))

    pages_id = len(xrefs) + 1 + len(page_info)
    page_ids = []
    for content_id, img_id, w, h in page_info:
        page_ids.append(obj((
            f"<< /Type /Page /Parent {pages_id} 0 R "
            f"/MediaBox [0 0 {w} {h}] "
            f"/Contents {content_id} 0 R "
            f"/Resources << /XObject << /Im{img_id} {img_id} 0 R >> >> >>"
        ).encode()))

    kids = " ".join(f"{i} 0 R" for i in page_ids)
    actual_pages_id = obj(
        f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode()
    )
    assert actual_pages_id == pages_id

    catalog_id = obj(f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode())

    xref_offset = sum(len(p) for p in parts)
    xref  = b"xref\n"
    xref += f"0 {len(xrefs) + 1}\n".encode()
    xref += b"0000000000 65535 f \n"
    for offset in xrefs:
        xref += f"{offset:010d} 00000 n \n".encode()
    xref += (
        f"trailer\n<< /Size {len(xrefs)+1} /Root {catalog_id} 0 R >>\n"
        f"startxref\n{xref_offset}\n%%%%EOF\n"
    ).encode()
    parts.append(xref)

    output_pdf.write_bytes(b"".join(parts))
    size_mb = output_pdf.stat().st_size / 1_048_576
    print(f"\n✅  PDF saved → {output_pdf}  ({size_mb:.1f} MB)")
    if size_mb > 24.5:
        print("⚠️   Over 24.5 MB — try --scale 0.6 or lower.")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Download supported e-zine edition to PDF")
    parser.add_argument(
        "--publication",
        choices=sorted(PUBLICATIONS.keys()),
        default="mayura",
        help="Publication to download (default: mayura)",
    )
    parser.add_argument("--date", default=None,
                        help="Edition date in DD/MM/YYYY format (default depends on publication)")
    parser.add_argument("--pages",   type=int, default=None,
                        help="Override page count (skip auto-detection)")
    parser.add_argument("--output",  default=None,
                        help="Output PDF filename (auto-named if omitted)")
    parser.add_argument("--tmp",     default="./mayura_tmp",
                        help="Temp directory for downloaded images")
    parser.add_argument("--quality", type=int, default=95,
                        help="JPEG quality after scaling (default 95). "
                             "Use 100 for maximum quality (may increase file size).")
    parser.add_argument("--scale",   type=float, default=1.0,
                        help="Downscale factor before encoding (default 1.0). "
                             "1.0 = original size, no quality downgrade.")
    args = parser.parse_args()

    cfg = PUBLICATIONS[args.publication]
    edition_date = args.date or default_date_for(args.publication)

    # 1. Fetch edition metadata
    print(f"\n[1/4] Fetching {args.publication} edition list for date={edition_date} …")
    fallback_days = 7 if args.publication == "sudha" else 35
    edition = get_latest_edition(cfg["api_url"], edition_date, fallback_days=fallback_days)
    print(f"      Edition: {edition.get('FileName', '?')}  |  "
          f"Fresh={edition.get('Fresh')}")

    full_page_url = edition["FullPageUrl"]
    print(f"      FullPageUrl: {full_page_url}")

    # 2. Parse URL template
    dir_prefix, stem, suffix = parse_url_template(full_page_url, cfg["base_url"])
    print(f"\n[2/4] URL template:\n"
          f"      Dir   : {dir_prefix}\n"
          f"      Stem  : {stem}\n"
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
        out_pdf = Path(auto_output_name(args.publication, stem))

    images_to_pdf(image_paths, out_pdf, quality=args.quality, scale=args.scale)


if __name__ == "__main__":
    main()
