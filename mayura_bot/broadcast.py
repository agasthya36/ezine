#!/usr/bin/env python3
"""
Called by GitHub Actions on the 2nd of every month.
Builds the PDF and broadcasts to all subscribers via the bot's /health endpoint
to get the subscriber list, then sends directly.

Environment variables:
  TELEGRAM_BOT_TOKEN
  MONTH_LABEL
  BOT_SUBSCRIBERS      — comma-separated chat IDs (set as GitHub Secret,
                         copy from bot's /health endpoint)
"""

import json
import os
import sys
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from mayura_download import (
    get_latest_edition, parse_url_template,
    probe_page_count, download_images, images_to_pdf
)

BOT_TOKEN   = os.environ["TELEGRAM_BOT_TOKEN"]
MONTH       = os.environ.get("MONTH_LABEL", "this month")
SUBSCRIBERS = os.environ.get("BOT_SUBSCRIBERS", "").split(",")
SUBSCRIBERS = [s.strip() for s in SUBSCRIBERS if s.strip()]
SCALE       = float(os.environ.get("PDF_SCALE", "1.0"))
EDITION_DATE = os.environ.get("EDITION_DATE", "01/03/2026")

if not SUBSCRIBERS:
    print("ERROR: BOT_SUBSCRIBERS secret is empty. "
          "Add comma-separated chat IDs from your bot's /health endpoint.")
    sys.exit(1)

# ── Build PDF ────────────────────────────────────────────────────────────────
print(f"Fetching edition for {EDITION_DATE} ...")
edition = get_latest_edition(EDITION_DATE)
dir_prefix, stem, suffix = parse_url_template(edition["FullPageUrl"])
tmp_dir = Path("mayura_tmp")
tmp_dir.mkdir(exist_ok=True)
total_pages = probe_page_count(dir_prefix, stem, suffix)
image_paths = download_images(dir_prefix, stem, suffix, total_pages, tmp_dir)
out_pdf     = Path("mayura_latest.pdf")
images_to_pdf(image_paths, out_pdf, quality=75, scale=SCALE)

# ── Send to all subscribers ───────────────────────────────────────────────────
caption   = f"ಮಯೂರ | Mayura — {MONTH} Edition"
pdf_bytes = out_pdf.read_bytes()

def send_pdf(chat_id: str):
    boundary = uuid.uuid4().hex.encode()
    body  = b"--" + boundary + b"\r\n"
    body += b'Content-Disposition: form-data; name="chat_id"\r\n\r\n'
    body += chat_id.encode() + b"\r\n"
    body += b"--" + boundary + b"\r\n"
    body += b'Content-Disposition: form-data; name="caption"\r\n\r\n'
    body += caption.encode("utf-8") + b"\r\n"
    body += b"--" + boundary + b"\r\n"
    body += (
        f'Content-Disposition: form-data; name="document"; filename="{out_pdf.name}"\r\n'
        f'Content-Type: application/pdf\r\n\r\n'
    ).encode()
    body += pdf_bytes + b"\r\n"
    body += b"--" + boundary + b"--\r\n"

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary.decode()}"}
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        result = json.loads(r.read())
        if not result.get("ok"):
            raise RuntimeError(result)

print(f"\nBroadcasting to {len(SUBSCRIBERS)} subscribers ...")
failed = []
for chat_id in SUBSCRIBERS:
    try:
        send_pdf(chat_id)
        print(f"  ✅ {chat_id}")
    except Exception as e:
        print(f"  ❌ {chat_id}: {e}")
        failed.append(chat_id)

if failed:
    print(f"\n{len(failed)} failed: {failed}")
    sys.exit(1)
print("\n✅ Broadcast complete.")