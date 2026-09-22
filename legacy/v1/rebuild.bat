@echo off
setlocal

set IMAGE=bierbeurs:latest
set TARBALL=bierbeurs-image.tar

echo [build] Bouwen van image %IMAGE% ...
docker build -t %IMAGE% . || exit /b 1

echo [export] Opslaan als %TARBALL% ...
docker save -o %TARBALL% %IMAGE% || exit /b 1

echo [run] Start run.bat ...
call run.bat

endlocal
