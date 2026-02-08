#!/bin/bash
# ECHR Case Law Dashboard — Local Launcher
# Usage: bash run.sh

cd "$(dirname "$0")"

echo "╔══════════════════════════════════════════════════════╗"
echo "║  ECHR Case Law Dashboard — Paragraph-Level Search   ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is required. Install it from https://python.org"
    exit 1
fi

# Check/install Flask
if ! python3 -c "import flask" 2>/dev/null; then
    echo "📦 Installing Flask..."
    pip3 install flask --quiet
fi

# Check data file
if [ ! -f "../echr_cases_20260207_121847.jsonl" ]; then
    echo "❌ Data file not found: ../echr_cases_20260207_121847.jsonl"
    echo "   Place the JSONL file in the parent directory."
    exit 1
fi

echo "🚀 Starting dashboard at http://127.0.0.1:5001"
echo "   Press Ctrl+C to stop"
echo ""

python3 app.py
