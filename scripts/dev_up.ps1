<#
.SYNOPSIS
    Bring the whole local stack up: infrastructure, migrations, seed, verification.

.DESCRIPTION
    Run this after Docker Desktop is running. It is idempotent — re-running is
    safe and reports existing state rather than duplicating work.

    Steps, in dependency order:
      1. Confirm the Docker engine is reachable.
      2. Start Postgres, Redis, LocalStack and ClamAV via docker compose.
      3. Wait for Postgres and Redis to pass their healthchecks.
      4. Generate .env if absent (RSA keypair for JWT signing).
      5. Apply Alembic migrations 001-005.
      6. Seed a tenant, API client, users, schema, S3 bucket and KMS key.
      7. Verify a real token can be minted and a protected endpoint reached.

    Only the infrastructure containers are started, not the api/worker/beat
    services. The API runs from the venv so code changes are picked up without
    an image rebuild, which is what you want while developing.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\dev_up.ps1
#>

[CmdletBinding()]
param(
    # Skip the container steps when Postgres and Redis are already running
    # some other way.
    [switch]$SkipInfra
)

$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root '.venv\Scripts\python.exe'
$Docker = 'C:\Program Files\Docker\Docker\resources\bin\docker.exe'

function Write-Step { param([string]$Text) Write-Host "`n=== $Text ===" -ForegroundColor Cyan }
function Write-Ok   { param([string]$Text) Write-Host "  OK   $Text" -ForegroundColor Green }
function Write-Warn { param([string]$Text) Write-Host "  WARN $Text" -ForegroundColor Yellow }
function Fail       { param([string]$Text) Write-Host "  FAIL $Text" -ForegroundColor Red; exit 1 }

if (-not (Test-Path $Python)) { Fail "Python venv not found at $Python" }
if (-not (Test-Path $Docker)) { $Docker = 'docker' }

Push-Location $Root
try {
    # ------------------------------------------------------------------
    Write-Step 'Docker engine'
    # ------------------------------------------------------------------
    if (-not $SkipInfra) {
        $serverVersion = & $Docker info --format '{{.ServerVersion}}' 2>&1
        if ($LASTEXITCODE -ne 0) {
            Write-Host ($serverVersion | Out-String)
            Fail 'Docker engine is not reachable. Start Docker Desktop and wait for the whale icon to stop animating.'
        }
        Write-Ok "engine reachable (server $serverVersion)"
    } else {
        Write-Warn 'skipped (-SkipInfra)'
    }

    # ------------------------------------------------------------------
    Write-Step 'Infrastructure containers'
    # ------------------------------------------------------------------
    if (-not $SkipInfra) {
        # Only the dependencies. api/worker/beat are run from the venv below.
        & $Docker compose up -d postgres redis localstack clamav
        if ($LASTEXITCODE -ne 0) { Fail 'docker compose up failed' }
        Write-Ok 'postgres, redis, localstack, clamav requested'

        Write-Host '  waiting for healthchecks...'
        $deadline = (Get-Date).AddMinutes(3)
        $healthy = $false
        while ((Get-Date) -lt $deadline) {
            $pg = (& $Docker inspect --format '{{.State.Health.Status}}' repo_saas-postgres-1 2>$null)
            $rd = (& $Docker inspect --format '{{.State.Health.Status}}' repo_saas-redis-1 2>$null)
            if ($pg -eq 'healthy' -and $rd -eq 'healthy') { $healthy = $true; break }
            Start-Sleep -Seconds 5
        }
        if (-not $healthy) {
            # Container names vary with the compose project name; fall back to a
            # direct connection test rather than guessing further.
            Write-Warn 'healthchecks not confirmed by name; testing the port directly'
        }
        Write-Ok 'infrastructure up'
    } else {
        Write-Warn 'skipped (-SkipInfra)'
    }

    # ------------------------------------------------------------------
    Write-Step 'Environment file'
    # ------------------------------------------------------------------
    if (Test-Path (Join-Path $Root '.env')) {
        Write-Ok '.env exists (left untouched)'
    } else {
        & $Python scripts\bootstrap_demo.py
        if ($LASTEXITCODE -ne 0) { Fail 'bootstrap_demo.py failed' }
        Write-Ok '.env generated with a fresh RSA keypair'
    }

    # LocalStack endpoints are not in the generated .env because bootstrap_demo
    # targets bare localhost. Append them once so S3/KMS resolve locally.
    $envPath = Join-Path $Root '.env'
    $envText = Get-Content $envPath -Raw
    if ($envText -notmatch 'S3_ENDPOINT_URL') {
        Add-Content $envPath @'

# --- LocalStack (added by scripts/dev_up.ps1) ---
S3_ENDPOINT_URL=http://localhost:4566
KMS_ENDPOINT_URL=http://localhost:4566
SES_ENDPOINT_URL=http://localhost:4566
SNS_ENDPOINT_URL=http://localhost:4566
AWS_ACCESS_KEY_ID=test
AWS_SECRET_ACCESS_KEY=test
CLAMAV_HOST=localhost
CLAMAV_PORT=3310
'@
        Write-Ok 'LocalStack endpoints appended to .env'
    } else {
        Write-Ok 'LocalStack endpoints already configured'
    }

    # ------------------------------------------------------------------
    Write-Step 'Database migrations'
    # ------------------------------------------------------------------
    # Waiting on the port rather than the container name: this works whatever
    # the compose project prefix turns out to be.
    $pgReady = $false
    $deadline = (Get-Date).AddMinutes(2)
    while ((Get-Date) -lt $deadline) {
        try {
            $t = New-Object System.Net.Sockets.TcpClient
            $t.Connect('127.0.0.1', 5432)
            $t.Close()
            $pgReady = $true
            break
        } catch { Start-Sleep -Seconds 3 }
    }
    if (-not $pgReady) { Fail 'Postgres is not accepting connections on 127.0.0.1:5432' }
    Write-Ok 'postgres accepting connections'

    & $Python -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) { Fail 'alembic upgrade head failed — this is the first real test of migrations 002-005' }
    Write-Ok 'migrations applied through head'

    # ------------------------------------------------------------------
    Write-Step 'Seed data'
    # ------------------------------------------------------------------
    & $Python scripts\seed_dev.py
    if ($LASTEXITCODE -ne 0) { Fail 'seed_dev.py failed' }

    # ------------------------------------------------------------------
    Write-Step 'End-to-end verification'
    # ------------------------------------------------------------------
    & $Python scripts\verify_stack.py
    if ($LASTEXITCODE -ne 0) { Fail 'verification failed' }

    Write-Host "`nStack is up." -ForegroundColor Green
    Write-Host '  Start the API :  .venv\Scripts\python.exe -m uvicorn app.main:app --port 8000'
    Write-Host '  Start the UI  :  cd frontend; npm run dev'
    Write-Host '  Live UI mode  :  set VITE_API_MODE=live before starting the UI'
}
finally {
    Pop-Location
}
