#!/bin/bash
# Helper script to run web client server

cd "$(dirname "$0")"

# Check if Python 3 is available
if ! command -v python3 &> /dev/null; then
    echo "Error: python3 is not installed"
    exit 1
fi

# Run the server
echo "Starting web client server..."
python3 server.py

