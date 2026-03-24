# Mayura + Sudha E-Zine Telegram Bot

Automated delivery of:
- Mayura (monthly)
- Sudha (weekly)

to Telegram subscribers.

This repository uses a hybrid architecture:
- Cloudflare Worker: webhook, subscriber management, and Telegram delivery from cached PDFs.
- GitHub Actions: scheduled PDF generation and upload to Cloudflare R2.

## Architecture

1. Users interact with Telegram bot commands.
2. Telegram webhook calls Cloudflare Worker.
3. Worker stores subscribers in Cloudflare KV.
4. GitHub workflows download editions and upload PDFs to R2.
5. Workflows trigger Worker admin endpoints to broadcast cached PDFs.

## Bot Commands

- `/start`
- `/stop`
- `/latest_mayura`
- `/latest_sudha`

## Repository Layout

- `.github/workflows/mayura_montly.yml` - Mayura monthly automation
- `.github/workflows/sudha_weekly.yml` - Sudha weekly automation
- `mayura_download.py` - downloader for both publications (`--publication mayura|sudha`)
- `mayura_bot/worker/src/index.js` - Worker code

## Cache Key Convention

Mayura monthly:
- `pdfs/YYYY-MM/mayura_YYYY-MM.pdf`
- Example: `pdfs/2026-03/mayura_2026-03.pdf`

Sudha weekly (ISO week):
- `pdfs/sudha/YYYY-Www/sudha_YYYY-Www.pdf`
- Example: `pdfs/sudha/2026-W13/sudha_2026-W13.pdf`

## Worker Endpoints

Public:
- `POST /<SECRET_PATH>`
- `GET /health`

Admin (requires token):
- `POST /admin/import-subs?token=<ADMIN_TOKEN>`
- `POST /admin/run-monthly?token=<ADMIN_TOKEN>`
- `POST /admin/run-weekly-sudha?token=<ADMIN_TOKEN>`
- `GET /subscribers?token=<ADMIN_TOKEN>`

Token can also be sent via header:
- `x-admin-token: <ADMIN_TOKEN>`

## Notes

- Worker serves/sends cached PDFs only.
- PDF generation/upload is done in GitHub Actions.
- Sudha API shape is compatible with Mayura API (`GetAllEditions` with `FullPageUrl`).
