$ErrorActionPreference = "Continue"
$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
$docker = "C:\Program Files\Docker\Docker\resources\bin\docker.exe"
$log = "c:\repo_as_saas\deploy_log.txt"

"=== Deploy Script Start: $(Get-Date) ===" | Out-File $log

# Wait for Docker daemon
$attempts = 0
while ($attempts -lt 12) {
    $info = & $docker info 2>&1
    if ($LASTEXITCODE -eq 0) {
        "Docker daemon is ready." | Out-File $log -Append
        break
    }
    $attempts++
    "Waiting for Docker daemon (attempt $attempts/12)..." | Out-File $log -Append
    Start-Sleep -Seconds 10
}

if ($attempts -ge 12) {
    "FATAL: Docker daemon not available after 2 minutes." | Out-File $log -Append
    exit 1
}

# Generate RSA keys if they don't exist
if (-not (Test-Path "c:\repo_as_saas\private.pem")) {
    "Generating RSA keys..." | Out-File $log -Append
    & $docker run --rm -v "c:/repo_as_saas:/keys" python:3.12-slim pip install cryptography -q 2>&1 | Out-File $log -Append
    & $docker run --rm -v "c:/repo_as_saas:/keys" python:3.12-slim bash -c "pip install cryptography -q && python /keys/gen_keys.py" 2>&1 | Out-File $log -Append
}

# Update .env with real keys if keys exist
if ((Test-Path "c:\repo_as_saas\private.pem") -and (Test-Path "c:\repo_as_saas\public.pem")) {
    $privKey = Get-Content "c:\repo_as_saas\private.pem" -Raw
    $pubKey = Get-Content "c:\repo_as_saas\public.pem" -Raw
    # Replace placeholder keys in .env
    $envContent = Get-Content "c:\repo_as_saas\.env" -Raw
    $envContent = $envContent -replace 'JWT_PRIVATE_KEY="[^"]*"', "JWT_PRIVATE_KEY=`"$($privKey.Replace("`n","\n").TrimEnd('\n'))`""
    $envContent = $envContent -replace 'JWT_PUBLIC_KEY="[^"]*"', "JWT_PUBLIC_KEY=`"$($pubKey.Replace("`n","\n").TrimEnd('\n'))`""
    $envContent | Out-File "c:\repo_as_saas\.env" -Encoding utf8 -NoNewline
    "Keys injected into .env" | Out-File $log -Append
}

# Build and start all services
Set-Location c:\repo_as_saas
"Starting docker compose build..." | Out-File $log -Append
& $docker compose build 2>&1 | Out-File $log -Append
"Build complete. Starting services..." | Out-File $log -Append
& $docker compose up -d 2>&1 | Out-File $log -Append

# Wait for PostgreSQL to be healthy
"Waiting for services to be healthy..." | Out-File $log -Append
Start-Sleep -Seconds 20

# Run migrations
"Running migrations..." | Out-File $log -Append
& $docker compose --profile migrate up migrate -d 2>&1 | Out-File $log -Append
Start-Sleep -Seconds 15

# Create S3 bucket in LocalStack
"Creating S3 bucket..." | Out-File $log -Append
& $docker compose exec localstack awslocal s3 mb s3://reposaaas-documents-dev 2>&1 | Out-File $log -Append

# Show status
"=== Final Status ===" | Out-File $log -Append
& $docker compose ps 2>&1 | Out-File $log -Append

"=== Deploy Complete: $(Get-Date) ===" | Out-File $log -Append
