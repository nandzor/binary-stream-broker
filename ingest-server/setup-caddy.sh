#!/bin/bash
# Setup script for Caddy reverse proxy with HTTPS/HTTP/2

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CADDY_DIR="$SCRIPT_DIR/caddy"
CADDYFILE="$SCRIPT_DIR/Caddyfile"

echo "=========================================="
echo "Caddy Setup for HTTPS/HTTP/2"
echo "=========================================="
echo ""

# Check if Caddy is installed
if ! command -v caddy &> /dev/null; then
    echo "Caddy is not installed. Installing..."
    
    # Try to install Caddy
    if command -v apt-get &> /dev/null; then
        sudo apt-get update
        sudo apt-get install -y debian-keyring debian-archive-keyring apt-transport-https
        curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
        curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
        sudo apt-get update
        sudo apt-get install -y caddy
    elif command -v yum &> /dev/null; then
        sudo yum install -y yum-plugin-copr
        sudo yum copr enable -y @caddy/caddy
        sudo yum install -y caddy
    else
        echo "Error: Cannot auto-install Caddy. Please install manually:"
        echo "  Visit: https://caddyserver.com/docs/install"
        exit 1
    fi
fi

echo "✓ Caddy is installed"
echo ""

# Create Caddy data directory
mkdir -p "$CADDY_DIR/data"
mkdir -p "$CADDY_DIR/config"

echo "✓ Caddy directories created"
echo ""

# Check if Caddyfile exists
if [ ! -f "$CADDYFILE" ]; then
    echo "Error: Caddyfile not found at $CADDYFILE"
    exit 1
fi

echo "✓ Caddyfile found"
echo ""
echo "Caddy configuration:"
echo "  - HTTP/2: Enabled"
echo "  - HTTPS: Enabled (self-signed for localhost)"
echo "  - Reverse proxy: localhost:3090 -> 127.0.0.1:3091"
echo ""
echo "To start Caddy:"
echo "  cd $SCRIPT_DIR"
echo "  caddy run --config Caddyfile"
echo ""
echo "Or use run.sh which will start both Caddy and Axum server"
echo ""

