# Worker Module (Cloudflare)

Cloudflare Worker used by the Telegram bot for Mayura and Sudha.

## What This Worker Does

- Handles Telegram webhook updates (`/start`, `/stop`, `/latest_mayura`, `/latest_sudha`)
- Stores subscribers in KV (`SUBSCRIBERS`)
- Sends cached PDFs from R2 (`PDF_CACHE`)
- Exposes admin endpoints for import and manual broadcasts

## Endpoints

Public:
- `POST /<SECRET_PATH>`
- `GET /health`

Admin:
- `GET /subscribers?token=<ADMIN_TOKEN>`
- `POST /admin/import-subs?token=<ADMIN_TOKEN>`
- `POST /admin/run-monthly?token=<ADMIN_TOKEN>`
- `POST /admin/run-weekly-sudha?token=<ADMIN_TOKEN>`

Admin token can also be sent via header:
- `x-admin-token: <ADMIN_TOKEN>`

## Cache Key Contract

Mayura monthly:
- `pdfs/YYYY-MM/mayura_YYYY-MM.pdf`

Sudha weekly:
- `pdfs/sudha/YYYY-Www/sudha_YYYY-Www.pdf`

## Notes

- Worker does not generate PDFs; it only serves/sends cached files.
- PDF generation and R2 upload are done by GitHub workflows.
