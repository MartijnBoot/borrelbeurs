@echo off
setlocal EnableExtensions
rem BorrelBeurs venue: restore the newest (or a named) dump (Phase 8 SD11). Double-click; needs Docker Desktop running.
set "HERE=%~dp0"
set "COMPOSE=docker compose -f "%HERE%compose.yml" --env-file "%HERE%.env""
echo Dit vervangt ALLE gegevens door de back-up %1 (leeg = de nieuwste).
set /p CONFIRM=Typ HERSTEL om door te gaan:
if not "%CONFIRM%"=="HERSTEL" (echo Afgebroken. & pause & exit /b 1)

%COMPOSE% stop app backup
%COMPOSE% exec -T db sh /scripts/restore.sh %1
if errorlevel 1 (
  echo.
  echo HERSTEL MISLUKT. De app is gestopt gelaten.
  echo Probeer de vorige back-up: restore.cmd ^<bestandsnaam^> ^(zie LEESMIJ.md^).
  pause
  exit /b 1
)
%COMPOSE% up -d
echo Hersteld. BorrelBeurs start opnieuw.
pause
