#!/bin/bash

echo ""
echo "========================================"
echo "    TeleCloud - Telegram Storage"
echo "========================================"
echo ""

cd "$(dirname "$0")"

# Check if venv exists
if [ ! -d "venv" ]; then
    echo "[!] Virtual environment not found."
    echo "[*] Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
source venv/bin/activate

# Install/update dependencies
echo "[*] Checking dependencies..."
pip install -q -r requirements.txt

echo ""
echo "[*] Starting TeleCloud server..."
echo "[*] Open your browser to: http://127.0.0.1:5000"
echo "[*] Press Ctrl+C to stop the server"
echo ""

python -m app.main
