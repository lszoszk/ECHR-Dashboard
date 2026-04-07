#!/usr/bin/env python3
"""
build_db.py -- Import ECHR case data from JSONL into SQLite with FTS5 search.

Usage:
    python build_db.py --input cases.jsonl --output echr_search.db --batch-size 5000
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Iterator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA_SQL = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA foreign_keys = ON;
PRAGMA cache_size = -64000;  -- 64 MB page cache

CREATE TABLE IF NOT EXISTS cases (
    case_id          TEXT PRIMARY KEY,
    case_no          TEXT,
    title            TEXT,
    hudoc_url        TEXT,
    judgment_date    TEXT,
    ecli             TEXT,
    respondent_state TEXT,
    importance       TEXT,
    conclusion       TEXT,   -- JSON array stored as text
    violation        TEXT,   -- JSON array stored as text
    non_violation    TEXT,   -- JSON array stored as text
    keywords         TEXT,   -- JSON array stored as text
    originating_body TEXT    -- JSON array stored as text
);

CREATE TABLE IF NOT EXISTS paragraphs (
    rowid    INTEGER PRIMARY KEY,
    case_id  TEXT NOT NULL REFERENCES cases(case_id),
    section  TEXT,
    para_idx INTEGER,
    text     TEXT
);

CREATE VIRTUAL TABLE IF NOT EXISTS paragraphs_fts USING fts5(
    text,
    content   = 'paragraphs',
    content_rowid = 'rowid',
    tokenize  = 'porter unicode61'
);

-- Triggers to keep the FTS index in sync with the content table.
CREATE TRIGGER IF NOT EXISTS paragraphs_ai AFTER INSERT ON paragraphs BEGIN
    INSERT INTO paragraphs_fts(rowid, text) VALUES (new.rowid, new.text);
END;

CREATE TRIGGER IF NOT EXISTS paragraphs_ad AFTER DELETE ON paragraphs BEGIN
    INSERT INTO paragraphs_fts(paragraphs_fts, rowid, text)
        VALUES ('delete', old.rowid, old.text);
END;

CREATE TRIGGER IF NOT EXISTS paragraphs_au AFTER UPDATE ON paragraphs BEGIN
    INSERT INTO paragraphs_fts(paragraphs_fts, rowid, text)
        VALUES ('delete', old.rowid, old.text);
    INSERT INTO paragraphs_fts(rowid, text) VALUES (new.rowid, new.text);
END;

CREATE TABLE IF NOT EXISTS case_articles (
    case_id TEXT NOT NULL REFERENCES cases(case_id),
    article TEXT NOT NULL
);
"""

_INDEXES_SQL = """
CREATE INDEX IF NOT EXISTS idx_paragraphs_case_id      ON paragraphs(case_id);
CREATE INDEX IF NOT EXISTS idx_case_articles_article    ON case_articles(article);
CREATE INDEX IF NOT EXISTS idx_cases_respondent_state   ON cases(respondent_state);
CREATE INDEX IF NOT EXISTS idx_cases_judgment_date      ON cases(judgment_date);
"""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _json_field(value) -> str:
    """Serialize a value to a JSON text column.

    Handles:
    - None -> '[]'
    - list -> JSON array
    - str -> stored as-is (plain text)
    - other -> JSON-encoded
    """
    if value is None:
        return "[]"
    if isinstance(value, str):
        return value  # store strings as plain text, not JSON-encoded
    return json.dumps(value, ensure_ascii=False)


def _iter_jsonl(path: Path) -> Iterator[dict]:
    """Yield parsed JSON objects from a JSONL file, one per line."""
    with open(path, "r", encoding="utf-8") as fh:
        for line_no, raw_line in enumerate(fh, start=1):
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                yield json.loads(raw_line)
            except json.JSONDecodeError as exc:
                log.warning("Skipping malformed JSON at line %d: %s", line_no, exc)


def _count_lines(path: Path) -> int:
    """Fast line count for progress reporting."""
    count = 0
    with open(path, "rb") as fh:
        for _ in fh:
            count += 1
    return count


def _normalize_articles(article_no) -> list:
    """Explode combined article references into individual articles.

    Handles both:
    - String format: "17;5;5-1-b;14+P1-2" (semicolon-separated, '+' for combined)
    - List format: ["14+P1-1", "P1-1", "14"]

    Example: "14+P1-1;P1-1;14" -> ["14", "P1-1"]  (deduplicated)
    """
    if not article_no:
        return []
    # If it's a string, split on semicolons first
    if isinstance(article_no, str):
        entries = [e.strip() for e in article_no.split(";") if e.strip()]
    elif isinstance(article_no, list):
        entries = article_no
    else:
        entries = [str(article_no)]

    seen = set()
    result = []
    for entry in entries:
        # Split combined articles like "14+P1-1" on '+'
        parts = str(entry).split("+")
        for part in parts:
            part = part.strip()
            if part and part not in seen:
                seen.add(part)
                result.append(part)
    return result


# ---------------------------------------------------------------------------
# Progress wrapper (tqdm when available, fallback to plain logging)
# ---------------------------------------------------------------------------

try:
    from tqdm import tqdm as _tqdm  # type: ignore[import-untyped]

    def _progress(iterable, **kwargs):
        return _tqdm(iterable, **kwargs)

except ImportError:

    class _FallbackProgress:
        """Minimal progress printer when tqdm is not installed."""

        def __init__(self, iterable, total=None, desc="", **_kwargs):
            self._iter = iter(iterable)
            self._total = total
            self._desc = desc
            self._count = 0
            self._last_log = 0

        def __iter__(self):
            return self

        def __next__(self):
            value = next(self._iter)
            self._count += 1
            if self._total and (
                self._count - self._last_log >= max(1, self._total // 20)
                or self._count == self._total
            ):
                pct = self._count * 100 // self._total
                log.info("%s: %d / %d (%d%%)", self._desc, self._count, self._total, pct)
                self._last_log = self._count
            return value

    def _progress(iterable, **kwargs):
        return _FallbackProgress(iterable, **kwargs)


# ---------------------------------------------------------------------------
# Core import logic
# ---------------------------------------------------------------------------


def build_database(input_path: Path, output_path: Path, batch_size: int) -> None:
    """Read *input_path* (JSONL) and write a fully indexed SQLite database."""

    if not input_path.is_file():
        log.error("Input file not found: %s", input_path)
        sys.exit(1)

    log.info("Counting lines in %s ...", input_path)
    total_lines = _count_lines(input_path)
    log.info("Found %d lines (including possible blanks).", total_lines)

    # Remove stale DB so we start fresh (WAL files too).
    for suffix in ("", "-wal", "-shm"):
        target = Path(str(output_path) + suffix)
        if target.exists():
            target.unlink()

    conn = sqlite3.connect(str(output_path))
    try:
        conn.executescript(_SCHEMA_SQL)
        log.info("Schema created.")

        # ------------------------------------------------------------------
        # Batch accumulators
        # ------------------------------------------------------------------
        case_rows: list[tuple] = []
        para_rows: list[tuple] = []
        article_rows: list[tuple] = []
        total_cases = 0
        total_paragraphs = 0
        skipped = 0

        def _flush() -> None:
            nonlocal case_rows, para_rows, article_rows
            if case_rows:
                conn.executemany(
                    """INSERT OR REPLACE INTO cases
                       (case_id, case_no, title, hudoc_url, judgment_date,
                        ecli, respondent_state, importance,
                        conclusion, violation, non_violation,
                        keywords, originating_body)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    case_rows,
                )
            if para_rows:
                conn.executemany(
                    """INSERT INTO paragraphs (case_id, section, para_idx, text)
                       VALUES (?,?,?,?)""",
                    para_rows,
                )
            if article_rows:
                conn.executemany(
                    """INSERT OR REPLACE INTO case_articles (case_id, article)
                       VALUES (?,?)""",
                    article_rows,
                )
            conn.commit()
            case_rows = []
            para_rows = []
            article_rows = []

        # ------------------------------------------------------------------
        # Main loop
        # ------------------------------------------------------------------
        records = _iter_jsonl(input_path)
        for record in _progress(records, total=total_lines, desc="Importing"):
            case_id = record.get("case_id")
            if not case_id:
                skipped += 1
                continue

            case_rows.append((
                case_id,
                record.get("case_no"),
                record.get("title"),
                record.get("hudoc_url"),
                record.get("judgment_date"),
                record.get("ecli"),
                record.get("respondent_state"),
                str(record.get("importance", "")) if record.get("importance") is not None else None,
                _json_field(record.get("conclusion")),
                _json_field(record.get("violation")),
                _json_field(record.get("non_violation")),
                _json_field(record.get("keywords")),
                _json_field(record.get("originating_body")),
            ))

            # Paragraphs
            paragraphs = record.get("paragraphs") or []
            for para in paragraphs:
                text = para.get("text", "")
                if not text:
                    continue
                para_rows.append((
                    case_id,
                    para.get("section"),
                    para.get("para_idx"),
                    text,
                ))
                total_paragraphs += 1

            # Exploded articles
            articles = _normalize_articles(record.get("article_no"))
            for art in articles:
                article_rows.append((case_id, art))

            total_cases += 1

            if total_cases % batch_size == 0:
                _flush()
                log.info(
                    "Flushed batch — cases so far: %d, paragraphs: %d",
                    total_cases,
                    total_paragraphs,
                )

        # Final flush
        _flush()

        # ------------------------------------------------------------------
        # Post-import: indexes, FTS optimization, ANALYZE
        # ------------------------------------------------------------------
        log.info("Creating indexes ...")
        conn.executescript(_INDEXES_SQL)

        log.info("Optimizing FTS index ...")
        conn.execute("INSERT INTO paragraphs_fts(paragraphs_fts) VALUES ('optimize')")
        conn.commit()

        log.info("Running ANALYZE ...")
        conn.execute("ANALYZE")
        conn.commit()

        log.info("Running integrity check ...")
        result = conn.execute("PRAGMA integrity_check").fetchone()
        if result and result[0] == "ok":
            log.info("Integrity check passed.")
        else:
            log.warning("Integrity check returned: %s", result)

        # ------------------------------------------------------------------
        # Stats
        # ------------------------------------------------------------------
        db_size_bytes = os.path.getsize(output_path)
        if db_size_bytes >= 1_073_741_824:
            size_str = f"{db_size_bytes / 1_073_741_824:.2f} GB"
        else:
            size_str = f"{db_size_bytes / 1_048_576:.1f} MB"

        log.info("=" * 60)
        log.info("Import complete.")
        log.info("  Total cases:      %d", total_cases)
        log.info("  Total paragraphs: %d", total_paragraphs)
        log.info("  Skipped records:  %d", skipped)
        log.info("  Database size:    %s", size_str)
        log.info("  Output file:      %s", output_path.resolve())
        log.info("=" * 60)

    except Exception:
        log.exception("Fatal error during import.")
        conn.rollback()
        sys.exit(1)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import ECHR JSONL data into a SQLite database with FTS5 search.",
    )
    parser.add_argument(
        "--input",
        required=True,
        type=Path,
        help="Path to the input JSONL file.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("echr_search.db"),
        help="Path for the output SQLite database (default: echr_search.db).",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=5000,
        help="Number of cases per commit batch (default: 5000).",
    )
    args = parser.parse_args()

    if args.batch_size < 1:
        parser.error("--batch-size must be a positive integer.")

    t0 = time.monotonic()
    build_database(args.input, args.output, args.batch_size)
    elapsed = time.monotonic() - t0
    log.info("Wall time: %.1f seconds.", elapsed)


if __name__ == "__main__":
    main()
