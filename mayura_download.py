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
    pip install requests aiohttp Pillow pypdf
"""

import argparse
import site
import sys
from pathlib import Path
from datetime import datetime

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
    "prajavani": {
        "api_base": "https://api-epaper-prod.deccanherald.com",
        "publisher": "PV",
        "output_prefix": "prajavani",
        "default_date_mode": "today",
        "default_edition": 4,
    },
}


# ── Helpers ──────────────────────────────────────────────────────────────────

def get_latest_edition(api_url: str, date: str) -> dict:
    """Fetch edition list for a date and return the freshest entry."""
    params = {"date": date}
    resp = requests.get(api_url, params=params, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    editions = resp.json()
    if not editions:
        raise RuntimeError(f"API returned no editions for {date}.")
    return next((e for e in editions if e.get("Fresh") == 1), editions[0])


def get_default_date(base_url: str) -> str:
    """Mirror website behavior: fetch server-provided fallback edition date."""
    url = f"{base_url.rstrip('/')}/api/Login/GetDefaultDate"
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    value = resp.json()
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"Unexpected default date response: {value!r}")
    return value.strip()


def get_latest_edition_via_site_flow(api_url: str, base_url: str, requested_date: str) -> tuple[dict, str]:
    """
    Website-equivalent flow:
    1) GetAllEditions(requested_date)
    2) if empty -> GetDefaultDate() then GetAllEditions(default_date)
    """
    try:
        return get_latest_edition(api_url, requested_date), requested_date
    except RuntimeError:
        default_date = get_default_date(base_url)
        if default_date == requested_date:
            raise
        edition = get_latest_edition(api_url, default_date)
        print(f"      Requested date had no editions. Using site default date: {default_date}")
        return edition, default_date


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


def default_quality_for(publication: str) -> int:
    if publication == "prajavani":
        return 70
    return 95


def default_standardize_pages_for(publication: str) -> bool:
    return False


def date_ddmmyyyy_to_yyyymmdd(date_str: str) -> str:
    return datetime.strptime(date_str, "%d/%m/%Y").strftime("%Y%m%d")


def get_prajavani_editions(api_base: str, publisher: str) -> list[dict]:
    url = f"{api_base.rstrip('/')}/epaper/editions"
    resp = requests.get(url, params={"publisher": publisher}, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    groups = resp.json()
    if not isinstance(groups, list):
        raise RuntimeError(f"Unexpected editions response shape: {type(groups).__name__}")

    editions: list[dict] = []
    for group in groups:
        editions.extend(group.get("editions", []))
    return editions


def get_prajavani_available_dates(
    api_base: str, publisher: str, edition: int, month: int, year: int
) -> list[str]:
    url = f"{api_base.rstrip('/')}/epaper/available-dates"
    params = {
        "month": str(month),
        "year": str(year),
        "publisher": publisher,
        "edition": str(edition),
    }
    resp = requests.get(url, params=params, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    payload = resp.json()
    dates = payload.get("dates", [])
    return [
        str(item.get("date"))
        for item in dates
        if item.get("hasData") is True and item.get("date")
    ]


def get_prajavani_latest_available_date(
    api_base: str,
    publisher: str,
    edition: int,
    requested_yyyymmdd: str,
    lookback_months: int = 12,
) -> str:
    target = datetime.strptime(requested_yyyymmdd, "%Y%m%d")
    probe = datetime(target.year, target.month, 1)
    candidates: list[str] = []

    for _ in range(lookback_months + 1):
        month_dates = get_prajavani_available_dates(
            api_base, publisher, edition, probe.month, probe.year
        )
        candidates.extend([d for d in month_dates if d <= requested_yyyymmdd])

        if candidates:
            return max(candidates)

        # previous month
        if probe.month == 1:
            probe = datetime(probe.year - 1, 12, 1)
        else:
            probe = datetime(probe.year, probe.month - 1, 1)

    raise RuntimeError(
        f"No Prajavani dates found for edition={edition} on/before {requested_yyyymmdd}."
    )


def get_prajavani_data(api_base: str, publisher: str, edition: int, yyyymmdd: str) -> dict:
    url = f"{api_base.rstrip('/')}/epaper/data"
    params = {
        "date": yyyymmdd,
        "edition": str(edition),
        "publisher": publisher,
    }
    resp = requests.get(url, params=params, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.json()


def get_prajavani_index_payload(data_payload: dict) -> dict:
    html_url_suffix = data_payload.get("html_url_suffix")
    if not html_url_suffix:
        raise RuntimeError("Prajavani payload does not include html_url_suffix.")

    url = f"{html_url_suffix.rstrip('/')}/index.json"
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.json()


def get_prajavani_image_urls(data_payload: dict, index_payload: dict | None = None) -> list[str]:
    data_url_suffix = data_payload.get("data_url_suffix")
    data = (index_payload or data_payload).get("data", index_payload or data_payload)
    sections = data.get("sections", [])

    if not data_url_suffix or not sections:
        raise RuntimeError("Unexpected Prajavani data payload shape.")

    image_urls = []
    for section in sections:
        for page in section.get("pages", []):
            img_file = page.get("imgFile")
            if img_file:
                image_urls.append(f"{data_url_suffix}{img_file}")
    return image_urls


def get_prajavani_pdf_urls(data_payload: dict, index_payload: dict | None = None) -> list[str]:
    data_url_suffix = data_payload.get("data_url_suffix")
    data = (index_payload or data_payload).get("data", index_payload or data_payload)
    sections = data.get("sections", [])

    if not data_url_suffix or not sections:
        raise RuntimeError("Unexpected Prajavani data payload shape.")

    pdf_urls = []
    for section in sections:
        for page in section.get("pages", []):
            pdf_file = page.get("pdfFile")
            if pdf_file:
                pdf_urls.append(f"{data_url_suffix}{pdf_file}")
    return pdf_urls


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
        last_err = None
        for attempt in range(1, 4):
            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=45)) as r:
                    r.raise_for_status()
                    dest.write_bytes(await r.read())
                    print(f"  ↓ page {page:3d}/{total}  {url}")
                    return dest
            except Exception as e:
                last_err = e
                if attempt < 3:
                    await asyncio.sleep(0.5 * attempt)
                    continue
        print(f"  ✗ page {page:3d} failed after retries: {last_err}")
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

    image_paths = [p for p in results if p is not None]
    failed = total_pages - len(image_paths)
    if failed:
        raise RuntimeError(f"{failed} page(s) failed to download out of {total_pages}.")
    return image_paths


async def download_images_from_urls_async(
    image_urls: list[str], tmp_dir: Path, concurrency: int = 4
) -> list[Path]:
    headers = {"User-Agent": "Mozilla/5.0 (compatible; MayuraDownloader/1.0)"}
    semaphore = asyncio.Semaphore(concurrency)
    total_pages = len(image_urls)

    async with aiohttp.ClientSession(headers=headers) as session:
        tasks = [
            download_page(
                session,
                url,
                tmp_dir / f"page_{idx:04d}.img",
                idx,
                total_pages,
                semaphore,
            )
            for idx, url in enumerate(image_urls, start=1)
        ]
        results = await asyncio.gather(*tasks)

    image_paths = [p for p in results if p is not None]
    failed = total_pages - len(image_paths)
    if failed:
        raise RuntimeError(f"{failed} page(s) failed to download out of {total_pages}.")
    return image_paths


async def download_files_from_urls_async(
    urls: list[str], tmp_dir: Path, suffix: str, concurrency: int = 4
) -> list[Path]:
    headers = {"User-Agent": "Mozilla/5.0 (compatible; MayuraDownloader/1.0)"}
    semaphore = asyncio.Semaphore(concurrency)
    total_files = len(urls)

    async with aiohttp.ClientSession(headers=headers) as session:
        tasks = [
            download_page(
                session,
                url,
                tmp_dir / f"page_{idx:04d}.{suffix}",
                idx,
                total_files,
                semaphore,
            )
            for idx, url in enumerate(urls, start=1)
        ]
        results = await asyncio.gather(*tasks)

    file_paths = [p for p in results if p is not None]
    failed = total_files - len(file_paths)
    if failed:
        raise RuntimeError(f"{failed} file(s) failed to download out of {total_files}.")
    return file_paths


def download_images(dir_prefix: str, stem: str, suffix: str,
                    total_pages: int, tmp_dir: Path) -> list[Path]:
    """Sync wrapper around the async downloader."""
    return asyncio.run(download_images_async(dir_prefix, stem, suffix, total_pages, tmp_dir))


def download_images_from_urls(image_urls: list[str], tmp_dir: Path, concurrency: int = 4) -> list[Path]:
    return asyncio.run(download_images_from_urls_async(image_urls, tmp_dir, concurrency=concurrency))


def download_files_from_urls(urls: list[str], tmp_dir: Path, suffix: str, concurrency: int = 4) -> list[Path]:
    return asyncio.run(download_files_from_urls_async(urls, tmp_dir, suffix=suffix, concurrency=concurrency))


def merge_pdfs(pdf_paths: list[Path], output_pdf: Path) -> None:
    PdfReader = PdfWriter = None

    def try_import():
        nonlocal PdfReader, PdfWriter
        try:
            from pypdf import PdfReader as Reader, PdfWriter as Writer
            PdfReader, PdfWriter = Reader, Writer
            return True
        except ModuleNotFoundError:
            pass

        try:
            from PyPDF2 import PdfReader as Reader, PdfWriter as Writer
            PdfReader, PdfWriter = Reader, Writer
            return True
        except ModuleNotFoundError:
            return False

    if not try_import():
        user_site = site.getusersitepackages()
        if user_site and user_site not in sys.path:
            sys.path.append(user_site)
        if not try_import():
            raise RuntimeError(
                f"PDF merge dependency missing for interpreter {sys.executable}. "
                f"Install with: {sys.executable} -m pip install pypdf"
            )

    if not pdf_paths:
        raise RuntimeError("No PDFs to merge.")

    print(f"\nBuilding merged PDF from {len(pdf_paths)} page PDFs …")
    writer = PdfWriter()
    total_pages = 0
    for pdf_path in pdf_paths:
        reader = PdfReader(str(pdf_path))
        page_count = len(reader.pages)
        total_pages += page_count
        for page in reader.pages:
            writer.add_page(page)
        print(f"  {pdf_path.name}  {page_count} page(s)")

    with output_pdf.open("wb") as fh:
        writer.write(fh)

    size_mb = output_pdf.stat().st_size / 1_048_576
    print(f"\n✅  PDF saved → {output_pdf}  ({size_mb:.1f} MB, {total_pages} merged page(s))")


def images_to_pdf(image_paths: list[Path], output_pdf: Path,
                  quality: int = 75, scale: float = 1.0,
                  standardize_pages: bool = False) -> None:
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

    prepared_images = []
    for p in image_paths:
        try:
            img = Image.open(p).convert("RGB")
            if scale != 1.0:
                new_w = max(1, int(img.width  * scale))
                new_h = max(1, int(img.height * scale))
                img = img.resize((new_w, new_h), Image.LANCZOS)
            prepared_images.append((p, img))
        except Exception as e:
            print(f"  ✗ skipping {p.name}: {e}")

    if not prepared_images:
        raise RuntimeError("All images failed to process.")

    canvas_w = max(img.width for _, img in prepared_images)
    canvas_h = max(img.height for _, img in prepared_images)

    jpeg_pages = []
    for p, img in prepared_images:
        page_img = img
        if standardize_pages and (img.width != canvas_w or img.height != canvas_h):
            canvas = Image.new("RGB", (canvas_w, canvas_h), "white")
            offset = ((canvas_w - img.width) // 2, (canvas_h - img.height) // 2)
            canvas.paste(img, offset)
            page_img = canvas

        buf = io.BytesIO()
        page_img.save(buf, format="JPEG", quality=quality, optimize=True)
        data = buf.getvalue()
        print(f"  {p.name}  {p.stat().st_size // 1024}KB → {len(data) // 1024}KB")
        jpeg_pages.append((data, page_img.width, page_img.height))

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
    parser.add_argument("--edition", type=int, default=None,
                        help="Numeric edition id for Prajavani (default: 4)")
    parser.add_argument("--pages",   type=int, default=None,
                        help="Override page count (skip auto-detection)")
    parser.add_argument("--output",  default=None,
                        help="Output PDF filename (auto-named if omitted)")
    parser.add_argument("--tmp",     default="./mayura_tmp",
                        help="Temp directory for downloaded images")
    parser.add_argument("--quality", type=int, default=None,
                        help="JPEG quality after scaling. "
                             "Defaults: mayura/sudha=95, prajavani=70.")
    parser.add_argument("--scale",   type=float, default=1.0,
                        help="Downscale factor before encoding (default 1.0). "
                             "1.0 = original size, no quality downgrade.")
    parser.add_argument("--standardize-pages", action="store_true",
                        help="Render all pages onto a common canvas size before PDF generation.")
    args = parser.parse_args()

    cfg = PUBLICATIONS[args.publication]
    edition_date = args.date or default_date_for(args.publication)
    quality = args.quality if args.quality is not None else default_quality_for(args.publication)
    standardize_pages = args.standardize_pages or default_standardize_pages_for(args.publication)

    if args.publication == "prajavani":
        requested_yyyymmdd = date_ddmmyyyy_to_yyyymmdd(edition_date)
        edition_number = args.edition or cfg["default_edition"]

        print(
            f"\n[1/4] Fetching Prajavani editions and available dates "
            f"for requested date={edition_date} (edition={edition_number}) …"
        )
        editions = get_prajavani_editions(cfg["api_base"], cfg["publisher"])
        edition_numbers = {int(e["edition_number"]) for e in editions if e.get("edition_number") is not None}
        if edition_number not in edition_numbers:
            sample = ", ".join(str(x) for x in sorted(edition_numbers)[:15])
            raise RuntimeError(
                f"Edition {edition_number} is not available for Prajavani. "
                f"Known edition numbers include: {sample}"
            )

        resolved_yyyymmdd = get_prajavani_latest_available_date(
            cfg["api_base"], cfg["publisher"], edition_number, requested_yyyymmdd
        )
        if resolved_yyyymmdd != requested_yyyymmdd:
            print(
                f"      Requested date had no issue. Using latest available date: "
                f"{resolved_yyyymmdd}"
            )
        else:
            print(f"      Using requested date: {resolved_yyyymmdd}")

        print("\n[2/4] Fetching Prajavani page metadata …")
        payload = get_prajavani_data(
            cfg["api_base"], cfg["publisher"], edition_number, resolved_yyyymmdd
        )
        index_payload = get_prajavani_index_payload(payload)
        pdf_urls = get_prajavani_pdf_urls(payload, index_payload=index_payload)
        total_discovered = len(pdf_urls)
        if args.pages:
            pdf_urls = pdf_urls[:args.pages]
            print(f"      Limiting pages due to --pages={args.pages} (from {total_discovered})")
        if not pdf_urls:
            raise RuntimeError("No page PDFs found in Prajavani payload.")
        print(f"      Pages discovered: {len(pdf_urls)}")

        tmp_dir = Path(args.tmp)
        tmp_dir.mkdir(parents=True, exist_ok=True)

        print(f"\n[3/4] Downloading {len(pdf_urls)} page PDFs to {tmp_dir}/ …\n")
        pdf_paths = download_files_from_urls(pdf_urls, tmp_dir, suffix="pdf", concurrency=4)

        if args.output:
            out_pdf = Path(args.output)
        else:
            out_pdf = Path(f"prajavani_{resolved_yyyymmdd}_e{edition_number}.pdf")

        print("\n[4/4] Merging page PDFs …")
        merge_pdfs(pdf_paths, out_pdf)
        return

    # 1. Fetch edition metadata
    print(f"\n[1/4] Fetching {args.publication} edition list for date={edition_date} …")
    edition, resolved_date = get_latest_edition_via_site_flow(
        cfg["api_url"], cfg["base_url"], edition_date
    )
    print(f"      Effective date used: {resolved_date}")
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

    images_to_pdf(
        image_paths,
        out_pdf,
        quality=quality,
        scale=args.scale,
        standardize_pages=standardize_pages,
    )


if __name__ == "__main__":
    main()
