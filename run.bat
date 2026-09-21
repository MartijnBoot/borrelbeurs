@echo off
setlocal

rem --- resolve project root to the script's own folder ---
set "ROOT=%~dp0"
pushd "%ROOT%"

rem --- settings ---
set PORT=8000
set URL=http://127.0.0.1:%PORT%/
set IMAGE=bierbeurs:latest
set TARBALL=bierbeurs-image.tar

rem --- ensure Docker is running ---
docker info >NUL 2>&1 || (echo [error] Docker Desktop lijkt niet te draaien.& popd & exit /b 1)

rem --- ensure host dirs/files exist (under ROOT) ---
if not exist "%ROOT%static" mkdir "%ROOT%static"
if not exist "%ROOT%static\earnings" mkdir "%ROOT%static\earnings"
if not exist "%ROOT%config" mkdir "%ROOT%config"

rem -- require new SPA files
for %%F in (home.html koers.html bar.html settings.html manipulation.html) do (
  if not exist "%ROOT%static\%%F" (
    echo [error] %ROOT%static\%%F ontbreekt. Zet hier je nieuwe %%F.
    popd & exit /b 1
  )
)

rem --- prefer loading tar (if present); else build current folder ---
if exist "%ROOT%%TARBALL%" (
  echo [load] Loading %TARBALL%...
  docker load -i "%ROOT%%TARBALL%"
) else (
  docker image inspect %IMAGE% >NUL 2>&1 || (
    echo [build] Building %IMAGE% from "%ROOT%"...
    docker build -t %IMAGE% "%ROOT%" || (echo [error] Build faalde.& popd & exit /b 1)
  )
)

rem --- replace old container ---
docker stop bierbeurs 1>NUL 2>NUL
docker rm   bierbeurs 1>NUL 2>NUL

rem --- ensure live config file exists (app falls back to baked-in template if empty) ---
if not exist "%ROOT%config\exchange_config.json" echo {}> "%ROOT%config\exchange_config.json"

rem --- persistent JWT secret: without it every restart logs everyone out ---
if not exist "%ROOT%config\.jwt_secret" (
  echo [init] Generating config\.jwt_secret ...
  powershell -NoProfile -Command "$b=New-Object byte[] 32; [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b); [IO.File]::WriteAllText('%ROOT%config\.jwt_secret', (-join ($b | ForEach-Object { $_.ToString('x2') })))"
)
set /p JWT_SECRET=<"%ROOT%config\.jwt_secret"

rem --- run: MOUNT DIRS from ROOT (host-bestanden overschrijven image) ---
echo [run] Starting container...
docker run -d -p %PORT%:8000 ^
  -e CONFIG_PATH=/app/config/exchange_config.json ^
  -e STATIC_DIR=/app/static ^
  -e ADMIN_TOKEN=TestTest ^
  -e JWT_SECRET=%JWT_SECRET% ^
  -v "%ROOT%config:/app/config" ^
  -v "%ROOT%static:/app/static" ^
  --name bierbeurs %IMAGE% || (echo [error] Failed to start container.& popd & exit /b 1)

rem --- wait for healthz ---
powershell -NoProfile -Command ^
  "$u='%URL%healthz'; for($i=0;$i -lt 60;$i++){ try{ $r=Invoke-WebRequest -Uri $u -UseBasicParsing -TimeoutSec 2; if($r.StatusCode -eq 200){ exit 0 } }catch{}; Start-Sleep -Milliseconds 500 }; exit 1"
if %ERRORLEVEL% NEQ 0 (
  echo [warn] Server not ready; recent logs:
  docker logs --tail=200 bierbeurs
  popd
  exit /b 1
)

rem --- sanity check: toon eerste regels van de gemounte frontend-bestanden ---
docker exec bierbeurs sh -lc ^
  "ls -l /app/static/home.html /app/static/koers.html /app/static/bar.html /app/static/settings.html /app/static/manipulation.html; ^
   echo ----- home.html (head) -----; sed -n '1,8p' /app/static/home.html"


rem --- open de home-pagina met cache-buster ---
set CB=%RANDOM%%TIME%
echo [ok] Opening %URL%?v=%CB%
start "" "%URL%?v=%CB%"


popd
endlocal
