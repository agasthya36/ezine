# Worker Module (Cloudflare)

This folder contains the Cloudflare Worker used by the Mayura Telegram bot.

For full project setup (including GitHub workflow), see root `README.md`.

## What This Worker Does

- Handles Telegram webhook updates (`/start`, `/stop`, `/latest`)
- Stores subscribers in KV (`SUBSCRIBERS`)
- Sends monthly cached PDF from R2 (`PDF_CACHE`)
- Exposes admin endpoints for import and manual broadcast

## Endpoints

Public:
- `POST /<SECRET_PATH>`
- `GET /health`

Admin:
- `GET /subscribers?token=<ADMIN_TOKEN>`
- `POST /admin/import-subs?token=<ADMIN_TOKEN>`
- `POST /admin/run-monthly?token=<ADMIN_TOKEN>`

Admin token can also be sent via header:
- `x-admin-token: <ADMIN_TOKEN>`

## Required Cloudflare Bindings

In `wrangler.toml`:
- KV binding: `SUBSCRIBERS`
- R2 binding: `PDF_CACHE`
- var: `SECRET_PATH`

## Required Worker Secrets

```bash
npx wrangler secret put TELEGRAM_BOT_TOKEN
npx wrangler secret put ADMIN_TOKEN
```

## Deploy

```bash
cd mayura_bot/worker
npm install
npm run deploy
```

## Cache Key Contract

Monthly PDF must exist in R2 at:

`pdfs/YYYY-MM/mayura_YYYY-MM.pdf`

Example:

`pdfs/2026-03/mayura_2026-03.pdf`

The GitHub workflow uploads exactly this key format before triggering broadcast.

## Quick Checks

```bash
curl "https://<worker-url>/health"
curl -X POST "https://<worker-url>/admin/run-monthly" -H "x-admin-token: <ADMIN_TOKEN>"
```

## Notes

- Worker does not generate PDFs; it only serves/sends cached files.
- PDF generation and R2 upload are done by `.github/workflows/mayura_montly.yml`.