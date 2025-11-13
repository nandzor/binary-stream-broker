#!/bin/bash
# Docker run script for ingest-server with Caddy

set -e

cd "$(dirname "$0")"

echo "=========================================="
echo "Docker Setup for Binary Stream Broker"
echo "=========================================="
echo ""

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo "Error: Docker is not installed"
    echo "Please install Docker: https://docs.docker.com/get-docker/"
    exit 1
fi

# Check if Docker Compose is installed
if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
    echo "Error: Docker Compose is not installed"
    echo "Please install Docker Compose: https://docs.docker.com/compose/install/"
    exit 1
fi

# Use docker compose (v2) or docker-compose (v1)
COMPOSE_CMD="docker compose"
if ! docker compose version &> /dev/null; then
    COMPOSE_CMD="docker-compose"
fi

echo "Building and starting services..."
echo ""

# Build and start
$COMPOSE_CMD up -d --build

echo ""
echo "Waiting for services to be ready..."
sleep 5

# Check health
echo ""
echo "Checking service health..."
if curl -k -f https://localhost:3090/health &> /dev/null; then
    echo "✅ HTTPS endpoint is healthy"
elif curl -f http://localhost:3091/health &> /dev/null; then
    echo "✅ HTTP endpoint is healthy (HTTPS may still be starting)"
else
    echo "⚠️  Services may still be starting..."
fi

echo ""
echo "=========================================="
echo "✅ Services are running!"
echo "=========================================="
echo ""
echo "  🌐 HTTPS endpoint: https://localhost:3090"
echo "  🚀 HTTP/2: Enabled"
echo "  📡 Direct HTTP: http://localhost:3091"
echo ""
echo "  📝 Health check:"
echo "     curl -k https://localhost:3090/health"
echo ""
echo "  📊 View logs:"
echo "     $COMPOSE_CMD logs -f"
echo ""
echo "  🛑 Stop services:"
echo "     $COMPOSE_CMD down"
echo ""
echo "=========================================="

