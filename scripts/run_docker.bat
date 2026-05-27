@echo off
REM Run the docker container for tuochat
setlocal

REM Support passing arguments to the CLI tool
REM Use a volume mount if you want to persist config:
REM docker run --rm -v %USERPROFILE%\.config\tuochat:/root/.config/tuochat tuochat:latest %*
echo Running tuochat docker container...
docker run --rm tuochat:latest %*
pause
