#!/usr/bin/env bash

# Build the docker image for tuochat
set -e

# Go to the project root directory
cd "$(dirname "$0")/.."

echo "Building tuochat docker image..."
docker build -t tuochat:latest .
echo "Build complete."
