# Worker Module (Cloudflare)

Cloudflare Worker used by the Telegram bot for Mayura, Sudha, and Prajavani delivery.

## What This Worker Does

- Handles Telegram webhook updates (`/start`, `/stop`, `/latest_mayura`, `/latest_sudha`, `/latest_prajavani`)
- Manages and stores subscribers cleanly in KV (`SUBSCRIBERS`)
- Efficiently sends cached PDFs from R2 (`PDF_CACHE`) to Telegram chats
- Triggers GitHub workflow dispatches based on Cloudflare cron schedules (daily, weekly, monthly)
- Exposes admin endpoints for manual subscriber import and broadcast triggers.

## Environment Variables & Secrets

The application strictly requires the following secrets to be stored in the Cloudflare environment:
- `SECRET_PATH`
- `GITHUB_TOKEN`
- `TELEGRAM_BOT_TOKEN`
- `CLOUDFLARE_API`
- `ADMIN_TOKEN`

## Endpoints

Public:
- `POST /<SECRET_PATH>` - Webhook ingestion path
- `GET /health` - Healthcheck and cache validity status

Admin:
- `GET /subscribers?token=<ADMIN_TOKEN>`
- `POST /admin/import-subs?token=<ADMIN_TOKEN>`
- `POST /admin/run-monthly?token=<ADMIN_TOKEN>`
- `POST /admin/run-weekly-sudha?token=<ADMIN_TOKEN>`
- `POST /admin/run-daily-prajavani?token=<ADMIN_TOKEN>`
- `POST /admin/run-daily-deccanherald?token=<ADMIN_TOKEN>`
- `POST /admin/setup-menu?token=<ADMIN_TOKEN>`

Admin token can also be sent via header:
- `x-admin-token: <ADMIN_TOKEN>`

## Cache Key Contract

Mayura monthly:
- `pdfs/YYYY-MM/mayura_YYYY-MM.pdf`

Sudha weekly:
- `pdfs/sudha/YYYY-Www/sudha_YYYY-Www.pdf`

Prajavani daily:
- `pdfs/prajavani/YYYY-MM-DD/prajavani_YYYY-MM-DD_e4.pdf`

## Notes

- Worker does not generate PDFs; it only serves/sends cached files.
- PDF generation and R2 upload are done by GitHub workflows.
