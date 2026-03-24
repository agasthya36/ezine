# Mayura Bot on Cloudflare + GitHub Actions

This setup is free-tier friendly:
- Cloudflare Worker handles webhook/subscribers and Telegram delivery from cached PDF.
- GitHub Actions generates monthly PDF and uploads it to Cloudflare R2.
- Worker monthly broadcast sends from cached R2 PDF (no heavy generation in Worker).

## Why this design
Cloudflare Workers Free has a per-invocation external subrequest limit. Building a full monthly PDF inside Worker exceeds that. This design avoids that limit.

## Worker endpoints
- `POST /<SECRET_PATH>` Telegram webhook
- `GET /health`
- `GET /subscribers?token=<ADMIN_TOKEN>`
- `POST /admin/import-subs?token=<ADMIN_TOKEN>`
- `POST /admin/run-monthly?token=<ADMIN_TOKEN>`

## R2 cache key format
Monthly PDF must be uploaded to:
`pdfs/YYYY-MM/mayura_YYYY-MM.pdf`

Example for March 2026:
`pdfs/2026-03/mayura_2026-03.pdf`

## One-time Worker setup
```bash
cd mayura_bot/worker
npm install
npx wrangler login
```

Create KV and R2 resources:
```bash
npx wrangler kv namespace create SUBSCRIBERS
npx wrangler r2 bucket create mayura-pdf-cache
```

Set secrets:
```bash
npx wrangler secret put TELEGRAM_BOT_TOKEN
npx wrangler secret put ADMIN_TOKEN
```

Edit `wrangler.toml`:
- `[[kv_namespaces]].id`
- `[[r2_buckets]].bucket_name = "mayura-pdf-cache"`
- `[vars].SECRET_PATH` random string

Deploy:
```bash
npm run deploy
```

Set Telegram webhook:
```text
https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/setWebhook?url=https://<worker-url>/<SECRET_PATH>
```

## GitHub Actions setup
Workflow file: `.github/workflows/mayura_montly.yml`

Add these GitHub repo secrets:
- `CLOUDFLARE_API_TOKEN` (R2 write permission for account)
- `CLOUDFLARE_ACCOUNT_ID`
- `WORKER_BASE_URL` (e.g. `https://mayura-bot.vishusince2001.workers.dev`)
- `WORKER_ADMIN_TOKEN` (same value as Worker `ADMIN_TOKEN`)

## Monthly flow
1. Workflow runs on 2nd day monthly (`0 6 2 * *`).
2. Generates `mayura_latest.pdf`.
3. Uploads PDF to R2 with monthly key.
4. Calls Worker `/admin/run-monthly`.
5. Worker sends cached PDF to all subscribers.

## Import existing subscribers
```bash
curl -X POST "https://<worker-url>/admin/import-subs?token=<ADMIN_TOKEN>" \
  -H "content-type: text/plain" \
  --data "123,456,789"
```