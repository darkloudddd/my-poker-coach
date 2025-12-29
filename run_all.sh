#!/bin/bash

# Ensure script directory (similar to %~dp0 in Windows)
cd "$(dirname "$0")"

echo "=========================================="
echo "🃏 My Poker Coach - Launcher 🚀"
echo "=========================================="
echo ""

# Check Python
PYTHON_CMD="python"
if command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
elif command -v python &> /dev/null; then
    PYTHON_CMD="python"
else
    echo "❌ Error: Python not found. Please install Python."
    exit 1
fi

echo "ℹ️  Using System Python: $PYTHON_CMD"
echo ""

# 1. Setup Venv
echo "🔍 1. Checking virtual environment (.venv)..."
if [ ! -d ".venv" ]; then
    echo "   Creating .venv..."
    $PYTHON_CMD -m venv .venv
    if [ $? -ne 0 ]; then
        echo "❌ Error: Failed to create venv."
        exit 1
    fi
    echo "   Done."
fi

# Set venv python path
VENV_PYTHON="./.venv/bin/python"

# 2. Install Dependencies
echo "📦 2. Installing dependencies..."
"$VENV_PYTHON" -m pip install -r requirements.txt > /dev/null 2>&1
if [ $? -ne 0 ]; then
    echo "❌ Error: Installation failed."
    exit 1
fi
echo "✅ Dependencies ready!"
echo ""

# 3. Setup .env
echo "⚙️ 3. Checking configuration..."
if [ ! -f .env ]; then
    echo "⚠️  .env not found."
    echo ""
    read -p "Please enter your API Key (e.g. sk-...), then press Enter: " API_KEY
    
    cp .env.example .env
    echo "" >> .env
    echo "LLM_API_KEY=$API_KEY" >> .env
    
    echo "✅ .env created!"
else
    echo "✅ .env exists. Skipping setup."
fi
echo ""

# 4. Start Server
echo "🚀 4. Starting Server..."

# Find Port (Bash handles command substitution robustly)
SERVER_PORT=$("$VENV_PYTHON" find_port.py)

if [ "$SERVER_PORT" == "None" ] || [ -z "$SERVER_PORT" ]; then
    echo "❌ Error: No free port found (8000-8010)."
    echo "Please close other applications and try again."
    exit 1
fi

echo "   Server starting on Port: $SERVER_PORT"
echo "🌍 Opening browser..."

# Open browser based on OS
if [[ "$OSTYPE" == "darwin"* ]]; then
    open "http://localhost:$SERVER_PORT"
elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
    xdg-open "http://localhost:$SERVER_PORT" 2>/dev/null || echo "   Please open browser manually: http://localhost:$SERVER_PORT"
fi

# Start Server
# Note: In Bash, we don't need 'start' equivalent for background browser, open/xdg-open handles it.
"$VENV_PYTHON" -u -m uvicorn server:app --reload --port "$SERVER_PORT"
