#!/usr/bin/env bash

# Run the docker container for tuochat
set -e

# Support passing arguments to the CLI tool
# Use a volume mount if you want to persist config:
# docker run --rm -v ~/.config/tuochat:/root/.config/tuochat tuochat:latest "$@"
echo "Running tuochat docker container..."
docker run --rm tuochat:latest "$@"
