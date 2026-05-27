# Build the docker image for tuochat
$ErrorActionPreference = "Stop"

# Go to the project root directory
Set-Location "$PSScriptRoot\.."

Write-Host "Building tuochat docker image..."
docker build -t tuochat:latest .
Write-Host "Build complete."
