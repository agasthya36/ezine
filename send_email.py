#!/usr/bin/env python3
"""
Uploads mayura_latest.pdf to Google Drive and emails a link.
No attachment — bypasses Gmail's 25 MB limit entirely.

GitHub Secrets required:
  GMAIL_USER               — your Gmail address
  GMAIL_APP_PASSWORD       — 16-char Gmail App Password
  TO_EMAIL                 — recipient address
  GDRIVE_CREDENTIALS_JSON  — full contents of service account key JSON
  GDRIVE_FOLDER_ID         — (optional) Drive folder ID to upload into
"""

import json
import os
import smtplib
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

PDF_PATH   = Path("mayura_latest.pdf")
GMAIL_USER = os.environ["GMAIL_USER"]
APP_PASS   = os.environ["GMAIL_APP_PASSWORD"]
TO_EMAIL   = os.environ["TO_EMAIL"]
MONTH      = os.environ.get("MONTH_LABEL", "this month")
FOLDER_ID  = os.environ.get("GDRIVE_FOLDER_ID", "")
CREDS_JSON = os.environ["GDRIVE_CREDENTIALS_JSON"]

if not PDF_PATH.exists():
    print(f"ERROR: {PDF_PATH} not found.")
    sys.exit(1)

size_mb = PDF_PATH.stat().st_size / 1_048_576
print(f"PDF size: {size_mb:.1f} MB")

# ── 1. Upload to Google Drive ────────────────────────────────────────────────

print("Authenticating with Google Drive ...")
creds = service_account.Credentials.from_service_account_info(
    json.loads(CREDS_JSON),
    scopes=["https://www.googleapis.com/auth/drive"]
)
drive = build("drive", "v3", credentials=creds)

filename = f"Mayura_{MONTH.replace(' ', '_')}.pdf"
file_metadata = {"name": filename}
if FOLDER_ID:
    file_metadata["parents"] = [FOLDER_ID]

print(f"Uploading {filename} to Google Drive ...")
media = MediaFileUpload(str(PDF_PATH), mimetype="application/pdf", resumable=True)
uploaded = drive.files().create(
    body=file_metadata,
    media_body=media,
    fields="id, webViewLink"
).execute()

file_id   = uploaded["id"]
view_link = uploaded.get("webViewLink", f"https://drive.google.com/file/d/{file_id}/view")
dl_link   = f"https://drive.google.com/uc?export=download&id={file_id}"
print(f"Uploaded: {view_link}")

# Make publicly readable (anyone with the link)
drive.permissions().create(
    fileId=file_id,
    body={"type": "anyone", "role": "reader"}
).execute()
print("Permissions set: anyone with the link can view.")

# ── 2. Send email with link ──────────────────────────────────────────────────

msg = MIMEMultipart("alternative")
msg["From"]    = GMAIL_USER
msg["To"]      = TO_EMAIL
msg["Subject"] = f"Mayura | {MONTH} Edition"

plain = f"""\
Namaskara,

The Mayura e-zine for {MONTH} is ready.

View online  : {view_link}
Download PDF : {dl_link}

— Automated by GitHub Actions
"""

html = f"""\
<html><body style="font-family:sans-serif;line-height:1.7;color:#222">
  <p>ನಮಸ್ಕಾರ,</p>
  <p>The <strong>Mayura e-zine for {MONTH}</strong> is ready.</p>
  <p style="margin:24px 0">
    <a href="{view_link}"
       style="background:#1a73e8;color:#fff;padding:11px 22px;
              border-radius:6px;text-decoration:none;font-weight:bold;margin-right:12px">
      📖 Open in Google Drive
    </a>
    <a href="{dl_link}"
       style="background:#34a853;color:#fff;padding:11px 22px;
              border-radius:6px;text-decoration:none;font-weight:bold">
      ⬇ Download PDF
    </a>
  </p>
  <p style="color:#888;font-size:12px">Automated by GitHub Actions</p>
</body></html>
"""

msg.attach(MIMEText(plain, "plain", "utf-8"))
msg.attach(MIMEText(html,  "html",  "utf-8"))

print(f"Sending email to {TO_EMAIL} ...")
with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
    server.login(GMAIL_USER, APP_PASS)
    server.sendmail(GMAIL_USER, TO_EMAIL, msg.as_string())

print("✅ Done — email sent with Google Drive link.")