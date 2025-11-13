#!/bin/bash
# Helper script to run ingest server with optional Caddy (HTTPS/HTTP/2)

set -e

cd "$(dirname "$0")"

# Configuration
USE_CADDY="${USE_CADDY:-false}"
AXUM_PORT="${AXUM_PORT:-3091}"  # Internal port (behind Caddy)
CADDY_PORT="${CADDY_PORT:-3090}"  # External port (HTTPS)

# Function to check if port is in use
check_port() {
    local port=$1
    if lsof -Pi :$port -sTCP:LISTEN -t >/dev/null 2>&1 ; then
        return 0  # Port is in use
    else
        return 1  # Port is free
    fi
}

# Function to wait for server to be ready
wait_for_server() {
    local port=$1
    local max_attempts=30
    local attempt=0
    
    echo "Waiting for server on port $port..."
    while [ $attempt -lt $max_attempts ]; do
        if check_port $port; then
            echo "✓ Server is ready on port $port"
            return 0
        fi
        sleep 1
        attempt=$((attempt + 1))
    done
    
    echo "✗ Server failed to start on port $port"
    return 1
}

# Function to cleanup on exit
cleanup() {
    echo ""
    echo "Shutting down..."
    if [ ! -z "$AXUM_PID" ]; then
        kill $AXUM_PID 2>/dev/null || true
    fi
    if [ ! -z "$CADDY_PID" ]; then
        kill $CADDY_PID 2>/dev/null || true
    fi
    exit 0
}

trap cleanup SIGINT SIGTERM

# Check if release build exists
if [ ! -f "target/release/ingest-server" ]; then
    echo "Building release version..."
    cargo build --release
fi

if [ "$USE_CADDY" = "true" ]; then
    echo "=========================================="
    echo "Starting with Caddy (HTTPS/HTTP/2)"
    echo "=========================================="
    echo ""
    
    # Check if Caddy is installed
    if ! command -v caddy &> /dev/null; then
        echo "Caddy is not installed. Running setup..."
        bash setup-caddy.sh
        if ! command -v caddy &> /dev/null; then
            echo "Error: Caddy installation failed. Falling back to HTTP mode."
            USE_CADDY="false"
        fi
    fi
    
    if [ "$USE_CADDY" = "true" ]; then
        # Update Caddyfile with correct ports (create backup first)
        if [ -f "Caddyfile" ]; then
            cp Caddyfile Caddyfile.bak 2>/dev/null || true
            sed -i.tmp "s/:3090/:$CADDY_PORT/g; s/127.0.0.1:3091/127.0.0.1:$AXUM_PORT/g" Caddyfile 2>/dev/null || true
            rm -f Caddyfile.tmp 2>/dev/null || true
        fi
        
        # Set Axum to run on internal port
        export PORT=$AXUM_PORT
        
        # Start Axum server in background
        echo "Starting Axum server on port $AXUM_PORT (internal)..."
        ./target/release/ingest-server &
        AXUM_PID=$!
        
        # Wait for Axum to be ready
        if wait_for_server $AXUM_PORT; then
            # Start Caddy
            echo ""
            echo "Starting Caddy on port $CADDY_PORT (HTTPS/HTTP/2)..."
            caddy run --config Caddyfile &
            CADDY_PID=$!
            
            # Wait for Caddy to be ready
            sleep 2
            
            echo ""
            echo "=========================================="
            echo "✅ Server is running with HTTPS/HTTP/2!"
            echo "=========================================="
            echo "  🌐 HTTPS endpoint: https://localhost:$CADDY_PORT"
            echo "  🚀 HTTP/2: Enabled"
            echo "  🔒 TLS: Self-signed certificate (accept warning in browser)"
            echo "  📡 Internal Axum: http://localhost:$AXUM_PORT"
            echo ""
            echo "  📝 Producer config:"
            echo "     USE_HTTPS=true BROKER_PORT=$CADDY_PORT"
            echo ""
            echo "  🌍 Web Client:"
            echo "     wss://localhost:$CADDY_PORT/ws/stream1"
            echo ""
            echo "Press Ctrl+C to stop"
            echo "=========================================="
            
            # Wait for processes
            wait $AXUM_PID $CADDY_PID
        else
            echo "Failed to start Axum server"
            exit 1
        fi
    fi
fi

# Fallback to HTTP mode
if [ "$USE_CADDY" != "true" ]; then
    echo "Starting ingest server (HTTP mode)..."
    echo "  To enable HTTPS/HTTP/2, set USE_CADDY=true"
    echo "  Example: USE_CADDY=true ./run.sh"
    echo ""
    ./target/release/ingest-server
fi
