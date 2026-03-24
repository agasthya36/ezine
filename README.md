# Mayura E-Zine Telegram Bot

Automated monthly delivery of the Mayura e-zine to Telegram subscribers.

This repository uses a hybrid architecture:
- Cloudflare Worker: webhook, subscriber management, and Telegram delivery from cached PDF.
- GitHub Actions: monthly PDF generation and upload to Cloudflare R2.

## Architecture

1. Users interact with the Telegram bot (`/start`, `/stop`, `/latest`).
2. Telegram webhook calls Cloudflare Worker.
3. Worker stores subscribers in Cloudflare KV.
4. Monthly GitHub workflow:
   - generates the monthly PDF,
   - uploads it to R2 cache,
   - calls Worker admin endpoint to broadcast to all subscribers.
5. Worker sends the cached PDF to all subscribers.

## Repository Layout

- `.github/workflows/mayura_montly.yml` - monthly automation workflow
- `mayura_download.py` - downloads Mayura edition and builds PDF
- `mayura_bot/worker/src/index.js` - Worker code (webhook + broadcast + admin endpoints)
- `mayura_bot/worker/wrangler.toml` - Worker config (KV, R2, vars)
- `mayura_bot/worker/package.json` - Wrangler scripts

## Prerequisites

- Cloudflare account
- Telegram bot token (from `@BotFather`)
- GitHub repository secrets configured
- Node.js 18+ (for local Worker deploy)
- Python 3.11+ (for local testing of downloader)

## 1) Cloudflare Setup (One-time)

From `mayura_bot/worker`:

```bash
npm install
npx wrangler login
```

Create KV namespace:

```bash
npx wrangler kv namespace create SUBSCRIBERS
```

Create R2 bucket:

```bash
npx wrangler r2 bucket create mayura-pdf-cache
```

Update `mayura_bot/worker/wrangler.toml`:
- set `[[kv_namespaces]].id`
- set `[[r2_buckets]].bucket_name`
- set `[vars].SECRET_PATH` to a long random string

Set Worker secrets:

```bash
npx wrangler secret put TELEGRAM_BOT_TOKEN
npx wrangler secret put ADMIN_TOKEN
```

Deploy Worker:

```bash
npm run deploy
```

## 2) Telegram Webhook Setup

Set webhook to your Worker:

```text
https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/setWebhook?url=https://<worker-url>/<SECRET_PATH>
```

Verify webhook:

```text
https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/getWebhookInfo
```

## 3) GitHub Actions Setup

Workflow file: `.github/workflows/mayura_montly.yml`

Add these repository secrets:
- `CLOUDFLARE_API_TOKEN`
- `CLOUDFLARE_ACCOUNT_ID`
- `WORKER_BASE_URL` (example: `https://mayura-bot.<subdomain>.workers.dev`)
- `WORKER_ADMIN_TOKEN` (must match Worker `ADMIN_TOKEN`)

Notes:
- Workflow uploads PDF to R2 using `wrangler r2 object put --remote`.
- Worker is triggered with `x-admin-token` header.

## 4) Monthly Cache Key Convention

Workflow uploads to:

`pdfs/YYYY-MM/mayura_YYYY-MM.pdf`

Example:

`pdfs/2026-03/mayura_2026-03.pdf`

Worker expects this exact path pattern.

## 5) Worker Endpoints

Public:
- `POST /<SECRET_PATH>` - Telegram webhook
- `GET /health` - service health

Admin (requires token):
- `POST /admin/import-subs?token=<ADMIN_TOKEN>`
- `POST /admin/run-monthly?token=<ADMIN_TOKEN>`
- `GET /subscribers?token=<ADMIN_TOKEN>`

Admin token can also be passed as header:

`x-admin-token: <ADMIN_TOKEN>`

## 6) Initial Subscriber Import (Optional)

```bash
curl -X POST "https://<worker-url>/admin/import-subs?token=<ADMIN_TOKEN>" \
  -H "content-type: text/plain" \
  --data "123456789,987654321"
```

## 7) Manual Test Run

1. Trigger GitHub workflow manually from Actions tab.
2. Confirm workflow succeeds (download, upload, broadcast).
3. Check Worker health:

```bash
curl "https://<worker-url>/health"
```

4. In Telegram, send `/latest` to confirm cached send path works.