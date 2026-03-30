#!/usr/bin/env python3
"""
mayura_broadcast.py
===================
Reads subscriber list directly from Cloudflare KV and broadcasts a PDF
to each subscriber via Telegram Bot API.

Called by GitHub Actions after a PDF is uploaded to R2 — eliminates the
round-trip curl callback to the Cloudflare Worker.

Usage:
    python mayura_broadcast.py \\
        --publication prajavani \\
        --date-key 2026-03-30 \\
        --pdf-file prajavani_latest.pdf \\
        --kv-namespace-id 16f852aca70c4596a93845091d054e10

Required environment variables:
    CLOUDFLARE_API_TOKEN
    CLOUDFLARE_ACCOUNT_ID
    TELEGRAM_BOT_TOKEN

Dependencies:
    pip install requests   (already installed by the GH workflow)
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import quote as url_quote

import requests

# ── Series config ─────────────────────────────────────────────────────────────

SERIES_LABELS = {
    "mayura":       "ಮಯೂರ | Mayura",
    "sudha":        "ಸುಧಾ | Sudha",
    "prajavani":    "ಪ್ರಜಾವಾಣಿ | Prajavani",
    "deccanherald": "Deccan Herald",
}

SERIES_FILENAME = {
    "mayura":       lambda k: f"mayura_{k}.pdf",
    "sudha":        lambda k: f"sudha_{k}.pdf",
    "prajavani":    lambda k: f"prajavani_{k}_e4.pdf",
    "deccanherald": lambda k: f"deccanherald_{k}_e2.pdf",
}

CF_API_BASE = "https://api.cloudflare.com/client/v4"

# Delay between Telegram sends to respect rate limits (30 msg/sec burst)
SEND_DELAY_S = 0.05

# ── Cloudflare KV client ──────────────────────────────────────────────────────


class KVClient:
    def __init__(self, account_id: str, namespace_id: str, api_token: str):
        self._base = (
            f"{CF_API_BASE}/accounts/{account_id}"
            f"/storage/kv/namespaces/{namespace_id}"
        )
        self._headers = {"Authorization": f"Bearer {api_token}"}

    def list_keys(self, prefix: str = "", limit: int = 1000) -> list[dict]:
        """List all KV keys (with metadata), paginated."""
        keys: list[dict] = []
        cursor: str | None = None
        while True:
            params: dict = {"limit": limit}
            if prefix:
                params["prefix"] = prefix
            if cursor:
                params["cursor"] = cursor
            r = requests.get(
                f"{self._base}/keys",
                headers=self._headers,
                params=params,
                timeout=30,
            )
            r.raise_for_status()
            data = r.json()
            keys.extend(data.get("result", []))
            cursor = data.get("result_info", {}).get("cursor") or None
            if not cursor:
                break
        return keys

    def get_value(self, key: str) -> str | None:
        """Get a KV value as plain text. Returns None if not found."""
        r = requests.get(
            f"{self._base}/values/{url_quote(key, safe='')}",
            headers=self._headers,
            timeout=15,
        )
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.text

    def put_value(self, key: str, value: str) -> None:
        """Write a KV value (plain text, no metadata)."""
        r = requests.put(
            f"{self._base}/values/{url_quote(key, safe='')}",
            headers={**self._headers, "Content-Type": "text/plain"},
            data=value.encode(),
            timeout=15,
        )
        r.raise_for_status()


# ── Telegram client ───────────────────────────────────────────────────────────


class TelegramClient:
    def __init__(self, bot_token: str):
        self._base = f"https://api.telegram.org/bot{bot_token}"

    def send_document_upload(
        self, chat_id: str, pdf_bytes: bytes, filename: str, caption: str
    ) -> str:
        """Upload a PDF file to a chat. Returns the Telegram file_id."""
        r = requests.post(
            f"{self._base}/sendDocument",
            data={"chat_id": chat_id, "caption": caption},
            files={"document": (filename, pdf_bytes, "application/pdf")},
            timeout=120,
        )
        r.raise_for_status()
        result = r.json()
        if not result.get("ok"):
            raise RuntimeError(f"Telegram upload failed: {result}")
        file_id: str = result["result"]["document"]["file_id"]
        print(f"  📤 Uploaded to {chat_id} — file_id acquired ({file_id[:20]}…)")
        return file_id

    def send_document_by_file_id(
        self, chat_id: str, file_id: str, caption: str
    ) -> bool:
        """Send a previously-uploaded document by file_id. Returns True on success."""
        r = requests.post(
            f"{self._base}/sendDocument",
            json={"chat_id": chat_id, "document": file_id, "caption": caption},
            timeout=30,
        )
        if not r.ok:
            print(f"  ✗ HTTP {r.status_code} for {chat_id}: {r.text[:120]}")
            return False
        result = r.json()
        if not result.get("ok"):
            print(f"  ✗ Telegram error for {chat_id}: {result}")
            return False
        return True


# ── KV helpers ────────────────────────────────────────────────────────────────


def get_subscribers_for_series(kv: KVClient, series: str) -> list[str]:
    """Return chat IDs of all KV subscribers opted-in to `series`."""
    keys = kv.list_keys(prefix="sub:")
    chat_ids: list[str] = []
    for key_obj in keys:
        name: str = key_obj.get("name", "")
        if not name.startswith("sub:"):
            continue
        chat_id = name[4:]
        metadata = key_obj.get("metadata")
        # No metadata → legacy subscriber, default to all series
        if metadata is None or metadata.get(series, True) is True:
            chat_ids.append(chat_id)
    return chat_ids


def get_meta(kv: KVClient, series: str) -> dict | None:
    raw = kv.get_value(f"meta:{series}:latest")
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def save_meta(kv: KVClient, series: str, meta: dict) -> None:
    kv.put_value(f"meta:{series}:latest", json.dumps(meta))


# ── Main ──────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Broadcast a PDF to Telegram subscribers via Cloudflare KV"
    )
    parser.add_argument(
        "--publication",
        required=True,
        choices=list(SERIES_LABELS.keys()),
        help="Publication series name",
    )
    parser.add_argument(
        "--date-key",
        required=True,
        help="Period key (YYYY-MM-DD for daily, YYYY-MM for monthly, YYYY-Www for weekly)",
    )
    parser.add_argument(
        "--pdf-file",
        required=True,
        help="Path to the PDF file to broadcast",
    )
    parser.add_argument(
        "--kv-namespace-id",
        required=True,
        help="Cloudflare KV namespace ID (SUBSCRIBERS namespace)",
    )
    args = parser.parse_args()

    # ── Validate env vars ──
    api_token  = os.environ.get("CLOUDFLARE_API_TOKEN",  "").strip()
    account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "").strip()
    bot_token  = os.environ.get("TELEGRAM_BOT_TOKEN",    "").strip()
    missing = [
        name for name, val in [
            ("CLOUDFLARE_API_TOKEN",  api_token),
            ("CLOUDFLARE_ACCOUNT_ID", account_id),
            ("TELEGRAM_BOT_TOKEN",    bot_token),
        ]
        if not val
    ]
    if missing:
        sys.exit(f"❌ Missing required environment variables: {', '.join(missing)}")

    pdf_path = Path(args.pdf_file)
    if not pdf_path.exists():
        sys.exit(f"❌ PDF file not found: {pdf_path}")

    series     = args.publication
    period_key = args.date_key
    label      = SERIES_LABELS[series]
    filename   = SERIES_FILENAME[series](period_key)
    caption    = f"{label} — {period_key} Edition"

    kv = KVClient(account_id, args.kv_namespace_id, api_token)
    tg = TelegramClient(bot_token)

    # ── Fetch subscribers ──
    print(f"\n🔍 Fetching subscribers for '{series}' from Cloudflare KV …")
    subscribers = get_subscribers_for_series(kv, series)
    total = len(subscribers)
    print(f"   Found {total} subscriber(s).")

    if not total:
        print("   No subscribers — nothing to do.")
        return

    # ── Check for cached Telegram file_id ──
    meta = get_meta(kv, series)
    file_id: str | None = None
    if meta and meta.get("period_key") == period_key and meta.get("telegram_file_id"):
        file_id = meta["telegram_file_id"]
        print(f"   ♻️  Reusing cached Telegram file_id for {period_key}.")
    else:
        print(f"   No cached file_id — will upload PDF on first send.")

    pdf_bytes = pdf_path.read_bytes()
    sent = 0
    failed = 0

    print(f"\n📡 Broadcasting '{filename}' to {total} subscriber(s) …\n")

    for i, chat_id in enumerate(subscribers, start=1):
        if file_id is None:
            # First send: multipart upload → captures file_id
            try:
                file_id = tg.send_document_upload(chat_id, pdf_bytes, filename, caption)
                new_meta = {
                    **(meta or {}),
                    "series":           series,
                    "period_key":       period_key,
                    "telegram_file_id": file_id,
                    "broadcast_at":     time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                }
                save_meta(kv, series, new_meta)
                print(f"   💾 Saved file_id to KV meta.")
                sent += 1
            except Exception as exc:
                print(f"  ✗ Upload to {chat_id} failed: {exc}")
                failed += 1
        else:
            # Subsequent sends: fast file_id reference
            ok = tg.send_document_by_file_id(chat_id, file_id, caption)
            if ok:
                print(f"  ✅ Sent to {chat_id} ({i}/{total})")
                sent += 1
            else:
                failed += 1

        if i < total:
            time.sleep(SEND_DELAY_S)

    print(
        f"\n{'✅' if not failed else '⚠️ '} Broadcast complete: "
        f"{sent} sent, {failed} failed / {total} subscribers."
    )
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
