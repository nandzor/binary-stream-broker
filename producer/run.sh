#!/bin/bash
# Helper script to run producer with virtual environment

cd "$(dirname "$0")"

# Activate virtual environment if it exists
if [ -d "venv" ]; then
    source venv/bin/activate
fi

# Run producer
python main.py

