#!/usr/bin/env python3
"""
Sends mayura_latest.pdf to a Telegram chat via a bot.
Telegram supports files up to 50 MB — no compression needed.

GitHub Secrets required:
  TELEGRAM_BOT_TOKEN  — get from @BotFather on Telegram
  TELEGRAM_CHAT_ID    — your chat/channel ID (see setup notes below)

Setup:
  1. Open Telegram, search for @BotFather
  2. Send /newbot, follow prompts, copy the token
  3. Start a chat with your new bot (search its username, press Start)
  4. Visit https://api.telegram.org/bot<TOKEN>/getUpdates
     Look for "chat":{"id": <YOUR_CHAT_ID>} in the response
  5. Add TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID as GitHub Secrets
"""

import os
import sys
from pathlib import Path
import urllib.request
import urllib.parse
import json

PDF_PATH  = Path("mayura_latest.pdf")
BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID   = os.environ["TELEGRAM_CHAT_ID"]
MONTH     = os.environ.get("MONTH_LABEL", "this month")

if not PDF_PATH.exists():
    print(f"ERROR: {PDF_PATH} not found.")
    sys.exit(1)

size_mb = PDF_PATH.stat().st_size / 1_048_576
print(f"Sending {PDF_PATH} ({size_mb:.1f} MB) to Telegram ...")

if size_mb > 50:
    print(f"ERROR: PDF is {size_mb:.1f} MB — exceeds Telegram's 50 MB bot limit.")
    sys.exit(1)

# ── Send document via multipart upload ───────────────────────────────────────
# Using urllib only (no extra dependencies)

import io
import uuid

url      = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
boundary = uuid.uuid4().hex.encode()
caption  = f"ಮಯೂರ | Mayura — {MONTH} Edition"

pdf_bytes = PDF_PATH.read_bytes()

body  = b"--" + boundary + b"\r\n"
body += b'Content-Disposition: form-data; name="chat_id"\r\n\r\n'
body += CHAT_ID.encode() + b"\r\n"

body += b"--" + boundary + b"\r\n"
body += b'Content-Disposition: form-data; name="caption"\r\n\r\n'
body += caption.encode("utf-8") + b"\r\n"

body += b"--" + boundary + b"\r\n"
body += (
    f'Content-Disposition: form-data; name="document"; filename="{PDF_PATH.name}"\r\n'
    f'Content-Type: application/pdf\r\n\r\n'
).encode()
body += pdf_bytes + b"\r\n"
body += b"--" + boundary + b"--\r\n"

req = urllib.request.Request(
    url,
    data=body,
    headers={"Content-Type": f"multipart/form-data; boundary={boundary.decode()}"},
    method="POST"
)

try:
    with urllib.request.urlopen(req, timeout=120) as resp:
        result = json.loads(resp.read())
        if result.get("ok"):
            print("✅ PDF sent to Telegram successfully.")
        else:
            print(f"ERROR: Telegram API error: {result}")
            sys.exit(1)
except urllib.error.HTTPError as e:
    print(f"ERROR: HTTP {e.code}: {e.read().decode()}")
    sys.exit(1)