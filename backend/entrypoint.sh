#!/usr/bin/env bash
set -euo pipefail

DB_PATH="${ECHR_DB_PATH:-/data/echr_search.db}"
JSONL_PATH="/data/echr_cases.jsonl"

echo "=== ECHR Search API entrypoint ==="

if [ ! -f "$DB_PATH" ]; then
    echo "Database not found at $DB_PATH"

    if [ -f "$JSONL_PATH" ]; then
        echo "Found JSONL source at $JSONL_PATH -- building database..."
        python build_db.py --input "$JSONL_PATH" --output "$DB_PATH"
        echo "Database built successfully."
    else
        echo "ERROR: No database and no JSONL source found."
        echo "  Place echr_cases.jsonl in /data/ or provide a pre-built DB."
        exit 1
    fi
else
    echo "Database found at $DB_PATH"
fi

echo "Starting uvicorn on 0.0.0.0:8000 with 2 workers..."
exec uvicorn main:app --host 0.0.0.0 --port 8000 --workers 2
