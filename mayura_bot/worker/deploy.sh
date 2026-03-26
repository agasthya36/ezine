#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEV_VARS="$SCRIPT_DIR/.dev.vars"

# ── 1. Validate .dev.vars exists ─────────────────────────────────────────────
if [[ ! -f "$DEV_VARS" ]]; then
  echo "❌  .dev.vars not found at $DEV_VARS"
  echo "    Create it with all required secrets before deploying."
  exit 1
fi

echo "🚀  Deploying worker..."
npx wrangler deploy

echo ""
echo "🔐  Syncing secrets from .dev.vars..."

# ── 2. Read each KEY=VALUE line and push to Cloudflare ───────────────────────
while IFS='=' read -r key value || [[ -n "$key" ]]; do
  # Skip blank lines and comments
  [[ -z "$key" || "$key" == \#* ]] && continue

  # Strip surrounding quotes from value if present
  value="${value%\"}"
  value="${value#\"}"
  value="${value%\'}"
  value="${value#\'}"

  echo "   ↳ Setting secret: $key"
  printf '%s' "$value" | npx wrangler secret put "$key" 2>&1 | grep -E "(✨|❌|Error)" || true
done < "$DEV_VARS"

echo ""
echo "✅  Deploy complete. All secrets synced."
