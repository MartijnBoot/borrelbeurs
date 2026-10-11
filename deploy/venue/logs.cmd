@echo off
setlocal EnableExtensions
rem BorrelBeurs venue: logs (Phase 8 SD11). Double-click; needs Docker Desktop running.
set "HERE=%~dp0"
set "COMPOSE=docker compose -f "%HERE%compose.yml" --env-file "%HERE%.env""
%COMPOSE% logs --tail 200 app backup
pause
