param(
  [string]$SourceDir = (Get-Location).Path,
  [string]$Remote = "git@github.com:agasthya36/ezine.git",
  [string]$Branch = "main",
  [string]$GitName = "Agasthya Bot",
  [string]$GitEmail = "vishusince2001@gmail.com",
  [switch]$SanitizeWrangler,
  [switch]$Push
)

$ErrorActionPreference = "Stop"

function Info($msg) { Write-Host "[INFO] $msg" -ForegroundColor Cyan }
function Warn($msg) { Write-Host "[WARN] $msg" -ForegroundColor Yellow }
function Fail($msg) { Write-Host "[ERROR] $msg" -ForegroundColor Red; exit 1 }

if (-not (Test-Path $SourceDir)) {
  Fail "SourceDir not found: $SourceDir"
}

$SourceDir = (Resolve-Path $SourceDir).Path
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$ExportDir = Join-Path $env:TEMP "ezine_push_$timestamp"

Info "Source: $SourceDir"
Info "Export: $ExportDir"

New-Item -ItemType Directory -Path $ExportDir | Out-Null

# Robust exclude list for local artifacts and secret files.
$excludeDirs = @(
  ".git",
  "_pushrepo",
  "mayura_bot\\worker\\node_modules",
  ".wrangler",
  "venv",
  ".venv",
  "__pycache__"
)

$excludeFiles = @(
  "*.pdf",
  ".env",
  ".env.*",
  "*.dev.vars",
  ".dev.vars",
  "subscribers.json"
)

$robocopyArgs = @(
  $SourceDir,
  $ExportDir,
  "/E",
  "/R:1",
  "/W:1",
  "/XD"
) + $excludeDirs + @("/XF") + $excludeFiles

Info "Copying project to clean export directory..."
& robocopy @robocopyArgs | Out-Null
$rc = $LASTEXITCODE
if ($rc -gt 7) {
  Fail "robocopy failed with code $rc"
}

# Ensure .gitignore exists and is strict.
$gitignorePath = Join-Path $ExportDir ".gitignore"
$gitignoreContent = @"
# Python
__pycache__/
*.pyc

# Node
node_modules/
npm-debug.log*

# Cloudflare/Wrangler local
.wrangler/
*.dev.vars
.dev.vars

# Secrets / env
.env
.env.*

# Local artifacts
*.pdf
mayura_tmp/
subscribers.json
_pushrepo/
"@
$gitignoreContent | Set-Content -Path $gitignorePath -NoNewline

if ($SanitizeWrangler) {
  $wrangler = Join-Path $ExportDir "mayura_bot\\worker\\wrangler.toml"
  if (Test-Path $wrangler) {
    Info "Sanitizing wrangler.toml placeholders..."
    $txt = Get-Content -Raw -Path $wrangler
    $txt = $txt -replace 'id\s*=\s*"[a-f0-9]{32}"', 'id = "REPLACE_WITH_KV_NAMESPACE_ID"'
    $txt = $txt -replace 'bucket_name\s*=\s*"[^"]+"', 'bucket_name = "REPLACE_WITH_R2_BUCKET_NAME"'
    $txt = $txt -replace 'SECRET_PATH\s*=\s*"[^"]+"', 'SECRET_PATH = "REPLACE_WITH_RANDOM_SECRET_PATH"'
    Set-Content -Path $wrangler -Value $txt -NoNewline
  } else {
    Warn "wrangler.toml not found, skipping sanitization."
  }
}

# Quick secret-pattern scan (best-effort).
Info "Scanning export for obvious secret patterns..."
$patterns = @(
  "AKIA[0-9A-Z]{16}",
  "(?i)api[_-]?key\\s*[=:]\\s*['\"].+['\"]",
  "(?i)token\\s*[=:]\\s*['\"].+['\"]",
  "(?i)secret\\s*[=:]\\s*['\"].+['\"]",
  "(?i)password\\s*[=:]\\s*['\"].+['\"]"
)
$hits = @()
foreach ($p in $patterns) {
  $hits += Get-ChildItem -Recurse -File $ExportDir | Select-String -Pattern $p -ErrorAction SilentlyContinue
}
if ($hits.Count -gt 0) {
  Warn "Potential secret-like matches found. Review before pushing:"
  $hits | Select-Object -First 20 | ForEach-Object { Write-Host "  $($_.Path):$($_.LineNumber)" }
}

Push-Location $ExportDir
try {
  Info "Initializing git repository in export folder..."
  git init | Out-Null
  git branch -M $Branch | Out-Null
  git config user.name $GitName
  git config user.email $GitEmail
  git add .

  $status = git status --short
  if (-not $status) {
    Warn "No files to commit."
  } else {
    Info "Creating commit..."
    git commit -m "Migrate deploy flow to Cloudflare Worker + R2 cache" | Out-Null
    git remote add origin $Remote

    if ($Push) {
      Info "Pushing to $Remote ($Branch)..."
      git push -u origin $Branch
      Info "Push complete."
    } else {
      Info "Dry run complete."
      Write-Host "Export ready at: $ExportDir"
      Write-Host "To push manually:"
      Write-Host "  cd \"$ExportDir\""
      Write-Host "  git push -u origin $Branch"
      Write-Host "Or rerun script with -Push"
    }
  }
}
finally {
  Pop-Location
}