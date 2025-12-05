#!/bin/bash
# Script to clean up old Docker containers and ensure only one instance runs

echo "Cleaning up old domo-mcp-server containers..."

# Stop and remove all containers for this service
docker-compose down --remove-orphans 2>/dev/null || true

# Also remove any stopped containers with the same name
docker ps -a --filter "name=domo-mcp-server" --format "{{.ID}}" | xargs -r docker rm -f 2>/dev/null || true

# Remove any dangling containers
docker container prune -f

echo "Cleanup complete. You can now start a fresh instance with: docker-compose run --rm domo-mcp-server"

