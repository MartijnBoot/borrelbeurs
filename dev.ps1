# Local dev stack: Postgres, migrations, API (:8000) and Vite (:5173).
# Assumes ./scripts/setup.sh has been run once (deps, .env.local).
#
# Usage:
#   ./dev.ps1 up [-NoWeb]   start everything in the background
#   ./dev.ps1 down          stop the servers and the Postgres container
#
# Server logs and PIDs live in .dev/ (gitignored): api.log, web.log, pids.json.

param(
    [Parameter(Mandatory, Position = 0)][ValidateSet('up', 'down')][string]$Command,
    [switch]$NoWeb
)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$stateDir = Join-Path $PSScriptRoot '.dev'
$pidFile = Join-Path $stateDir 'pids.json'

function Stop-Tree([int]$ProcessId) {
    # /T takes uvicorn's reload child and vite's node process down with the wrapper.
    taskkill /PID $ProcessId /T /F 2>&1 | Out-Null
}

function Get-RunningPids {
    if (-not (Test-Path $pidFile)) { return @() }
    $saved = Get-Content $pidFile -Raw | ConvertFrom-Json
    @($saved.PSObject.Properties.Value | Where-Object { Get-Process -Id $_ -ErrorAction SilentlyContinue })
}

function Start-Hidden([string]$Name, [string]$File, [string[]]$Arguments) {
    (Start-Process $File -ArgumentList $Arguments -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $stateDir "$Name.log") `
        -RedirectStandardError (Join-Path $stateDir "$Name.err.log")).Id
}

if ($Command -eq 'down') {
    if (Test-Path $pidFile) {
        $saved = Get-Content $pidFile -Raw | ConvertFrom-Json
        foreach ($p in $saved.PSObject.Properties) {
            if (Get-Process -Id $p.Value -ErrorAction SilentlyContinue) {
                Stop-Tree $p.Value
                Write-Host "stopped $($p.Name) (pid $($p.Value))"
            }
        }
        Remove-Item $pidFile
    }
    else {
        Write-Host 'no servers recorded as running'
    }
    docker compose stop db
    return
}

# --- up ---------------------------------------------------------------------
foreach ($tool in 'docker', 'uv', 'pnpm') {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
        throw "'$tool' is required but not installed. See scripts/setup.sh for install links."
    }
}
if (-not (Test-Path .env.local)) {
    throw '.env.local is missing. Run ./scripts/setup.sh once first.'
}
if (Get-RunningPids) {
    throw 'Dev servers are already running. Run ./dev.ps1 down first.'
}

# app/core/config.py reads only the process environment, so export .env.local here.
foreach ($line in Get-Content .env.local) {
    if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)=(.*)$') {
        [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2].Trim('"', "'"), 'Process')
    }
}
# "localhost" resolves via IPv6 first on Windows and makes DB connections crawl.
$env:DATABASE_URL = $env:DATABASE_URL -replace '@localhost:', '@127.0.0.1:'

docker compose up -d --wait --wait-timeout 60 db
if ($LASTEXITCODE -ne 0) { throw 'Postgres failed to become healthy.' }

uv run alembic -c db/alembic.ini upgrade head
if ($LASTEXITCODE -ne 0) { throw 'Migrations failed.' }

New-Item -ItemType Directory -Force $stateDir | Out-Null
$pids = [ordered]@{ api = Start-Hidden 'api' 'uv' @('run', 'uvicorn', 'app.main:app', '--reload', '--port', '8000') }
if (-not $NoWeb) {
    # pnpm is a .cmd shim, which Start-Process cannot launch directly.
    $pids.web = Start-Hidden 'web' 'cmd.exe' @('/c', 'pnpm --dir web dev')
}
$pids | ConvertTo-Json | Set-Content $pidFile

Write-Host 'API: http://127.0.0.1:8000'
if (-not $NoWeb) { Write-Host 'Web: http://localhost:5173' }
Write-Host 'Logs in .dev/ - stop with ./dev.ps1 down'
