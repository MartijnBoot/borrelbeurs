@echo off
setlocal EnableExtensions
rem BorrelBeurs venue: one database dump now (Phase 8 SD11). Double-click; needs Docker Desktop running.
set "HERE=%~dp0"
set "COMPOSE=docker compose -f "%HERE%compose.yml" --env-file "%HERE%.env""
%COMPOSE% exec backup sh /scripts/backup.sh once
if errorlevel 1 (echo Back-up mislukt. & pause & exit /b 1)
echo Back-up gemaakt.
pause
