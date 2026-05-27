@echo off
REM Build the docker image for tuochat
setlocal

REM Go to the project root directory
cd /d "%~dp0\.."

echo Building tuochat docker image...
docker build -t tuochat:latest .
echo Build complete.
pause
