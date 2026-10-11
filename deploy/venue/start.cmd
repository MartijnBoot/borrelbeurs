@echo off
setlocal EnableExtensions
rem BorrelBeurs venue: start (Phase 8 SD11). Double-click; needs Docker Desktop running.
set "HERE=%~dp0"
set "COMPOSE=docker compose -f "%HERE%compose.yml" --env-file "%HERE%.env""
setlocal EnableDelayedExpansion
if not exist "%HERE%.env" copy /y "%HERE%.env.example" "%HERE%.env" >nul
for /f "usebackq tokens=1,* delims==" %%A in ("%HERE%.env") do (
  set "LINE=%%A"
  if not "!LINE:~0,1!"=="#" if not "%%A"=="" set "%%A=%%B"
)

if "%BB_IMAGE_SHA%"=="" (
  echo BB_IMAGE_SHA ontbreekt in .env. Gebruik de .env uit de bundel.
  pause & exit /b 1
)

docker info >nul 2>&1
if errorlevel 1 (
  echo Docker Desktop draait niet. Start Docker Desktop, wacht tot het klaar is,
  echo en start dit bestand opnieuw.
  pause & exit /b 1
)

rem docker load keeps the pinned Postgres digest only on the containerd image store;
rem on the classic store compose could not find it offline (pull_policy: never).
docker info --format "{{json .DriverStatus}}" 2>nul | findstr /c:"io.containerd.snapshotter" >nul
if errorlevel 1 (
  echo Docker Desktop gebruikt de oude opslag voor images. Zet in Docker Desktop
  echo Settings - General: "Use containerd for pulling and storing images" aan,
  echo kies Apply, en start dit bestand opnieuw. Zie LEESMIJ.md.
  pause & exit /b 1
)

rem The images ship in the bundle; load them only when Docker does not have them.
docker image inspect "ghcr.io/martijnboot/borrelbeurs:%BB_IMAGE_SHA%" >nul 2>&1
if errorlevel 1 (
  echo Images laden uit images.tar ...
  docker load -i "%HERE%images.tar" || (echo Laden mislukt. & pause & exit /b 1)
)

rem First run: a session signing key, generated here and kept in .env (v1 run.bat:49-53).
if "%JWT_SECRET%"=="" (
  for /f %%S in ('powershell -NoProfile -Command "$b=New-Object byte[] 32;[Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b);($b|ForEach-Object{$_.ToString('x2')})-join''"') do set "JWT_SECRET=%%S"
  powershell -NoProfile -Command "(Get-Content -Raw '%HERE%.env') -replace '(?m)^JWT_SECRET=.*$','JWT_SECRET=!JWT_SECRET!' | Set-Content -NoNewline '%HERE%.env'"
)

if not exist "%BB_DATA_DIR%\backups" mkdir "%BB_DATA_DIR%\backups"
if not exist "%BB_DATA_DIR%\exports" mkdir "%BB_DATA_DIR%\exports"

%COMPOSE% up -d || (echo Starten mislukt. Zie logs.cmd. & pause & exit /b 1)

echo Wachten tot BorrelBeurs klaar is ...
set /a WAITED=0
:wait
powershell -NoProfile -Command "try{$r=Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 'http://127.0.0.1:%BB_HTTP_PORT%/readyz';exit [int]($r.StatusCode -ne 200)}catch{exit 1}" >nul 2>&1
if not errorlevel 1 goto ready
set /a WAITED+=2
if %WAITED% geq 120 (echo Niet klaar na 120 s. Zie logs.cmd. & pause & exit /b 1)
timeout /t 2 /nobreak >nul
goto wait

:ready
echo.
echo BorrelBeurs draait. Telefoons: %BB_PUBLIC_URL%
echo.
pause
