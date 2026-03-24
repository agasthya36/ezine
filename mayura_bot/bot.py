#!/usr/bin/env python3
"""
Mayura Telegram Bot
===================
- /start   — subscribe to monthly delivery
- /stop    — unsubscribe
- /latest  — fetch and send the latest edition right now

Runs as a webhook server (Flask). Deploy on Render/Railway free tier.

Environment variables:
  TELEGRAM_BOT_TOKEN   — from @BotFather
  SECRET_PATH          — random string to secure your webhook URL (any UUID)

Deploy steps (Render.com):
  1. Push this folder to GitHub
  2. New Web Service → connect repo → set env vars
  3. Set webhook: https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://<your-app>.onrender.com/<SECRET_PATH>
"""

import json
import logging
import os
import sys
import threading
import urllib.request
from pathlib import Path

from flask import Flask, request, abort

# ── Import downloader from parent dir or same dir ────────────────────────────
sys.path.insert(0, str(Path(__file__).parent.parent))
from mayura_download import (
    get_latest_edition, parse_url_template,
    probe_page_count, download_images, images_to_pdf, build_page_url
)

# ── Config ───────────────────────────────────────────────────────────────────
BOT_TOKEN   = os.environ["TELEGRAM_BOT_TOKEN"]
SECRET_PATH = os.environ.get("SECRET_PATH", "mayura-webhook")
SCALE       = float(os.environ.get("PDF_SCALE", "1.0"))
QUALITY     = int(os.environ.get("PDF_QUALITY", "75"))
SUBS_FILE   = Path("subscribers.json")   # persists chat IDs

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

app = Flask(__name__)

# ── Subscriber store ─────────────────────────────────────────────────────────

def load_subs() -> set:
    if SUBS_FILE.exists():
        return set(json.loads(SUBS_FILE.read_text()))
    return set()

def save_subs(subs: set):
    SUBS_FILE.write_text(json.dumps(list(subs)))

def add_sub(chat_id: int):
    subs = load_subs()
    subs.add(chat_id)
    save_subs(subs)

def remove_sub(chat_id: int):
    subs = load_subs()
    subs.discard(chat_id)
    save_subs(subs)

# ── Telegram API helpers ──────────────────────────────────────────────────────

def tg(method: str, **kwargs):
    """Call a Telegram Bot API method."""
    url  = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    data = json.dumps(kwargs).encode()
    req  = urllib.request.Request(url, data=data,
                                  headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())

def send_message(chat_id: int, text: str):
    tg("sendMessage", chat_id=chat_id, text=text)

def send_pdf(chat_id: int, pdf_path: Path, caption: str):
    """Send a PDF file to a chat."""
    import uuid
    boundary = uuid.uuid4().hex.encode()
    pdf_bytes = pdf_path.read_bytes()

    body  = b"--" + boundary + b"\r\n"
    body += b'Content-Disposition: form-data; name="chat_id"\r\n\r\n'
    body += str(chat_id).encode() + b"\r\n"

    body += b"--" + boundary + b"\r\n"
    body += b'Content-Disposition: form-data; name="caption"\r\n\r\n'
    body += caption.encode("utf-8") + b"\r\n"

    body += b"--" + boundary + b"\r\n"
    body += (
        f'Content-Disposition: form-data; name="document"; filename="{pdf_path.name}"\r\n'
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
        return json.loads(r.read())

# ── PDF builder ───────────────────────────────────────────────────────────────

def fetch_and_build_pdf(date: str = None) -> Path:
    """Download the latest edition and return path to the built PDF."""
    edition      = get_latest_edition(date or "01/03/2026")
    dir_prefix, stem, suffix = parse_url_template(edition["FullPageUrl"])
    tmp_dir      = Path("mayura_tmp")
    tmp_dir.mkdir(exist_ok=True)
    total_pages  = probe_page_count(dir_prefix, stem, suffix)
    image_paths  = download_images(dir_prefix, stem, suffix, total_pages, tmp_dir)
    out_pdf      = Path(f"mayura_{stem}.pdf")
    images_to_pdf(image_paths, out_pdf, quality=QUALITY, scale=SCALE)
    return out_pdf

# ── Command handlers ──────────────────────────────────────────────────────────

def handle_start(chat_id: int, first_name: str):
    add_sub(chat_id)
    send_message(chat_id,
        f"ನಮಸ್ಕಾರ {first_name}! 👋\n\n"
        "You're now subscribed to Mayura e-zine.\n\n"
        "Commands:\n"
        "  /latest — get the latest edition now\n"
        "  /stop   — unsubscribe\n\n"
        "You'll automatically receive each new edition on the 2nd of every month."
    )
    log.info(f"New subscriber: {chat_id} ({first_name})")

def handle_stop(chat_id: int):
    remove_sub(chat_id)
    send_message(chat_id, "You've been unsubscribed. Send /start to resubscribe anytime.")
    log.info(f"Unsubscribed: {chat_id}")

def handle_latest(chat_id: int):
    """Fetch latest edition and send — runs in background thread."""
    def _run():
        try:
            send_message(chat_id, "⏳ Fetching the latest Mayura edition, please wait...")
            pdf = fetch_and_build_pdf()
            send_pdf(chat_id, pdf, "ಮಯೂರ | Mayura — Latest Edition")
            log.info(f"Sent latest to {chat_id}")
        except Exception as e:
            log.error(f"Failed to send to {chat_id}: {e}")
            send_message(chat_id, f"❌ Something went wrong: {e}")
    threading.Thread(target=_run, daemon=True).start()

# ── Broadcast (called by GitHub Actions cron) ─────────────────────────────────

def broadcast(pdf_path: Path, caption: str):
    subs = load_subs()
    log.info(f"Broadcasting to {len(subs)} subscribers...")
    for chat_id in subs:
        try:
            send_pdf(chat_id, pdf_path, caption)
            log.info(f"  ✅ Sent to {chat_id}")
        except Exception as e:
            log.error(f"  ❌ Failed for {chat_id}: {e}")

# ── Webhook endpoint ──────────────────────────────────────────────────────────

@app.route(f"/{SECRET_PATH}", methods=["POST"])
def webhook():
    update = request.get_json(silent=True)
    if not update:
        abort(400)

    msg = update.get("message") or update.get("channel_post")
    if not msg:
        return "ok"

    chat_id    = msg["chat"]["id"]
    first_name = msg.get("from", {}).get("first_name", "there")
    text       = msg.get("text", "").strip()

    if text.startswith("/start"):
        handle_start(chat_id, first_name)
    elif text.startswith("/stop"):
        handle_stop(chat_id)
    elif text.startswith("/latest"):
        handle_latest(chat_id)
    else:
        send_message(chat_id,
            "Commands:\n  /latest — get latest edition\n  /stop — unsubscribe")

    return "ok"

@app.route("/health")
def health():
    return {"status": "ok", "subscribers": len(load_subs())}

# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    log.info(f"Starting bot on port {port}, webhook path=/{SECRET_PATH}")
    app.run(host="0.0.0.0", port=port)