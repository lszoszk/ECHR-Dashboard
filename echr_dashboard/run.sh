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

# Resolve data file
DATA_FILE=""
if [ -n "${ECHR_DATA_FILE:-}" ] && [ -f "$ECHR_DATA_FILE" ]; then
    DATA_FILE="$ECHR_DATA_FILE"
elif [ -f "../data/echr_decisions_sample.jsonl" ]; then
    DATA_FILE="../data/echr_decisions_sample.jsonl"
elif [ -f "../echr_cases_optionB.jsonl" ]; then
    DATA_FILE="../echr_cases_optionB.jsonl"
elif [ -f "../echr_cases_20260207_121847.jsonl" ]; then
    DATA_FILE="../echr_cases_20260207_121847.jsonl"
else
    echo "❌ No data file found."
    echo "   Expected one of:"
    echo "   - ECHR_DATA_FILE (environment variable)"
    echo "   - ../data/echr_decisions_sample.jsonl"
    echo "   - ../echr_cases_optionB.jsonl"
    echo "   - ../echr_cases_20260207_121847.jsonl"
    exit 1
fi

echo "🚀 Starting dashboard at http://127.0.0.1:5001"
echo "📚 Using dataset: $DATA_FILE"
echo "   Press Ctrl+C to stop"
echo ""

python3 app.py
