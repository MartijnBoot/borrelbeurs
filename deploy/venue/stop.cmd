@echo off
setlocal EnableExtensions
rem BorrelBeurs venue: stop (Phase 8 SD11). Double-click; needs Docker Desktop running.
set "HERE=%~dp0"
set "COMPOSE=docker compose -f "%HERE%compose.yml" --env-file "%HERE%.env""
%COMPOSE% stop
echo BorrelBeurs is gestopt. De gegevens blijven bewaard.
pause
