# Run the docker container for tuochat
$ErrorActionPreference = "Stop"

# Support passing arguments to the CLI tool
# Use a volume mount if you want to persist config:
# docker run --rm -v $HOME/.config/tuochat:/root/.config/tuochat tuochat:latest $args
Write-Host "Running tuochat docker container..."
docker run --rm tuochat:latest $args
