#!/usr/bin/env python3
"""
Sends mayura_latest.pdf as a Gmail attachment.
Reads credentials from environment variables (set as GitHub Secrets).
"""

import os
import smtplib
import sys
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

PDF_PATH   = Path("mayura_latest.pdf")
GMAIL_USER = os.environ["GMAIL_USER"]
APP_PASS   = os.environ["GMAIL_APP_PASSWORD"]
TO_EMAIL   = os.environ["TO_EMAIL"]
MONTH      = os.environ.get("MONTH_LABEL", "this month")

if not PDF_PATH.exists():
    print(f"ERROR: {PDF_PATH} not found. Download may have failed.")
    sys.exit(1)

size_mb = PDF_PATH.stat().st_size / 1_048_576
print(f"Attaching {PDF_PATH} ({size_mb:.1f} MB) ...")

if size_mb > 24.5:
    print(f"ERROR: PDF is {size_mb:.1f} MB — exceeds Gmail's 25 MB limit. Try --scale 0.6.")
    sys.exit(1)

msg = MIMEMultipart()
msg["From"]    = GMAIL_USER
msg["To"]      = TO_EMAIL
msg["Subject"] = f"ಮಯೂರ | Mayura — {MONTH} Edition"

body = f"ನಮಸ್ಕಾರ,\n\nPlease find attached the Mayura e-zine for {MONTH}.\n\n— Automated by GitHub Actions"
msg.attach(MIMEText(body, "plain", "utf-8"))

with open(PDF_PATH, "rb") as f:
    part = MIMEApplication(f.read(), Name=PDF_PATH.name)
part["Content-Disposition"] = f'attachment; filename="{PDF_PATH.name}"'
msg.attach(part)

print(f"Sending to {TO_EMAIL} ...")
with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
    server.login(GMAIL_USER, APP_PASS)
    server.sendmail(GMAIL_USER, TO_EMAIL, msg.as_string())

print("✅ Email sent successfully.")