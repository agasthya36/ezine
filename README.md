# Mayura, Sudha, Prajavani, and Deccan Herald E-Zine Telegram Bot

Automated delivery of:
- Mayura (monthly)
- Sudha (weekly)
- Prajavani (daily)
- Deccan Herald (daily)

to Telegram subscribers.

This repository uses a hybrid architecture:
- Cloudflare Worker: webhook, subscriber management, and Telegram delivery from cached PDFs.
- GitHub Actions: scheduled PDF generation and upload to Cloudflare R2.

## Architecture

1. Users interact with Telegram bot commands.
2. Telegram webhook calls Cloudflare Worker.
3. Worker stores subscribers and metadata in Cloudflare KV.
4. GitHub workflows download editions and upload PDFs to R2.
5. Workflows trigger Worker admin endpoints to broadcast cached PDFs based on user subscription preferences.

## Supported Features

- Delivery of multiple periodic publications (Mayura, Sudha, Prajavani, Deccan Herald).
- Subscriber tracking, caching, and custom preference toggles via Cloudflare KV.
- Fast PDF delivery through Cloudflare R2 and Telegram Webhook.
- GitHub Actions daily, weekly, and monthly cron execution.
- Automated API fetching and compilation of image pages into unified PDFs.

## Bot Commands

- `/start` - Subscribe to updates
- `/prefs` - Manage subscriptions via inline keyboard
- `/stop` - Unsubscribe
- `/latest_mayura` - Fetch the latest Mayura edition
- `/latest_sudha` - Fetch the latest Sudha edition
- `/latest_prajavani` - Fetch the latest Prajavani edition
- `/latest_deccanherald` - Fetch the latest Deccan Herald edition

## Repository Layout

- `.github/workflows/mayura_monthly.yml` - Mayura monthly automation
- `.github/workflows/sudha_weekly.yml` - Sudha weekly automation
- `.github/workflows/prajavani_daily.yml` - Prajavani daily automation
- `.github/workflows/deccanherald_daily.yml` - Deccan Herald daily automation
- `mayura_download.py` - Downloader script
- `mayura_bot/worker/src/index.js` - Worker code

## Cache Key Convention

Mayura monthly:
- `pdfs/YYYY-MM/mayura_YYYY-MM.pdf`

Sudha weekly (ISO week):
- `pdfs/sudha/YYYY-Www/sudha_YYYY-Www.pdf`

Prajavani daily:
- `pdfs/prajavani/YYYY-MM-DD/prajavani_YYYY-MM-DD_e4.pdf`

Deccan Herald daily:
- `pdfs/deccanherald/YYYY-MM-DD/deccanherald_YYYY-MM-DD_e2.pdf`

## Worker Endpoints

Public:
- `POST /<SECRET_PATH>`
- `GET /health`

Admin (requires token):
- `POST /admin/import-subs?token=<ADMIN_TOKEN>`
- `POST /admin/run-monthly?token=<ADMIN_TOKEN>`
- `POST /admin/run-weekly-sudha?token=<ADMIN_TOKEN>`
- `POST /admin/run-daily-prajavani?token=<ADMIN_TOKEN>`
- `GET /subscribers?token=<ADMIN_TOKEN>`

Token can also be sent via header:
- `x-admin-token: <ADMIN_TOKEN>`

## Notes

- Worker serves/sends cached PDFs only.
- PDF generation/upload is done in GitHub Actions.
- Sudha API shape is compatible with Mayura API (`GetAllEditions` with `FullPageUrl`).
