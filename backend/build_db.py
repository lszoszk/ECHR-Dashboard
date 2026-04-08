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
# Section re-segmentation — fix misclassified paragraphs
# ---------------------------------------------------------------------------

import re

# Patterns that indicate a section boundary when found at the START of a
# short paragraph (< 150 chars).  Order matters: first match wins.
# Each tuple: (compiled regex, new_section_name)
_SECTION_BOUNDARY_PATTERNS = [
    # ── Separate opinions (must come before operative part checks) ──
    (re.compile(
        r"^(PARTLY\s+)?(JOINT\s+)?(DISSENTING|CONCURRING|SEPARATE)\s+OPINION",
        re.IGNORECASE,
    ), "Separate Opinion"),

    # ── Operative Part ──
    (re.compile(r"^FOR\s+THESE\s+REASONS", re.IGNORECASE), "Operative Part"),
    (re.compile(r"^OPERATIVE\s+PROVISIONS?", re.IGNORECASE), "Operative Part"),

    # ── Just Satisfaction (old-style Art. 50 and modern Art. 41) ──
    (re.compile(r"^APPLICATION\s+OF\s+ARTICLE\s+50\b", re.IGNORECASE), "Just Satisfaction"),
    # Note: "APPLICATION OF ARTICLE 41" also appears as sub-heading inside
    # Merits in modern judgments; only re-classify if it's a standalone heading.

    # ── Merits / Law ──
    (re.compile(r"^AS\s+TO\s+THE\s+LAW\b", re.IGNORECASE), "Merits"),
    (re.compile(r"^THE\s+LAW\s*$", re.IGNORECASE), "Merits"),
    # "THE LAW" followed by a section reference on the same line
    (re.compile(r"^THE\s+LAW\s+I\.\s", re.IGNORECASE), "Merits"),

    # ── Facts ──
    (re.compile(r"^AS\s+TO\s+THE\s+FACTS\b", re.IGNORECASE), "Facts Background"),
    (re.compile(r"^THE\s+FACTS\s*$", re.IGNORECASE), "Facts Background"),
    (re.compile(r"^THE\s+FACTS\s+I\.\s", re.IGNORECASE), "Facts Background"),

    # ── Circumstances of the case (Facts Proceedings sub-section) ──
    (re.compile(
        r"^I\.\s*(THE\s+)?CIRCUMSTANCES?\s+OF\s+THE\s+CASE",
        re.IGNORECASE,
    ), "Facts Proceedings"),

    # ── Proceedings before the Commission ──
    (re.compile(r"^PROCEEDINGS?\s+BEFORE\s+THE\s+COMMISSION", re.IGNORECASE), "Facts Proceedings"),

    # ── Legal Framework (modern) ──
    (re.compile(r"^RELEVANT\s+(DOMESTIC\s+|LEGAL\s+)?(LAW|FRAMEWORK|LEGISLATION)", re.IGNORECASE), "Legal Framework"),
    (re.compile(r"^RELEVANT\s+LEGAL\s+FRAMEWORK\s+AND\s+PRACTICE", re.IGNORECASE), "Legal Framework"),

    # ── Admissibility ──
    # Careful: "A. Admissibility" is often a sub-heading inside Merits.
    # Only trigger section change for standalone headings.
    (re.compile(r"^([A-Z]\.\s+)?ADMISSIBILITY\s*(OF\s+THE\s+COMPLAINT)?", re.IGNORECASE), "Admissibility"),
    (re.compile(r"^(I+\.\s*)?ADMISSIBILITY\b", re.IGNORECASE), "Admissibility"),

    # ── Introduction / Procedure ──
    (re.compile(r"^PROCEDURE\b", re.IGNORECASE), "Introduction"),
    (re.compile(r"^INTRODUCTION\s*$", re.IGNORECASE), "Introduction"),

    # ── Article 46 ──
    (re.compile(r"^(APPLICATION\s+OF\s+)?ARTICLE\s+46\b", re.IGNORECASE), "Article 46"),

    # ── Appendix ──
    (re.compile(r"^APPENDIX\b", re.IGNORECASE), "Appendix"),
]

# Maximum text length for a paragraph to be treated as a potential section
# heading.  Real headings are short; we don't want to re-classify body text.
_HEADING_MAX_LEN = 200



# Sections that are known to be "monolithic catch-alls" in older HUDOC data.
# Only paragraphs originally tagged with these sections will be re-classified
# by the flowing current_section.  Paragraphs with specific sections
# (Admissibility, Just Satisfaction, Legal Framework, etc.) are preserved.
_SUSPECT_SECTIONS = frozenset({
    "Header",         # only for paras after a detected heading
    "Introduction",   # the biggest catch-all in old judgments
    "Operative Part", # often contains separate opinions
})


def _resegment_paragraphs(paragraphs: list[dict]) -> list[dict]:
    """Re-classify paragraph sections based on textual heading patterns.

    The HUDOC parser often dumps everything into "Introduction" or
    "Facts Proceedings" for older judgments.  This function scans for
    known section-heading patterns and re-assigns the ``section`` field.

    Strategy:
    1. Scan paragraphs in order for heading patterns.
    2. When a heading is detected, update ``current_section``.
    3. A paragraph is only re-classified if:
       a) Its text matches a heading pattern (always applied), OR
       b) Its original section is in _SUSPECT_SECTIONS (catch-all
          sections that are known to be unreliable in old data).
    4. Paragraphs originally tagged with specific sections like
       Admissibility, Just Satisfaction, Legal Framework, Merits,
       Separate Opinion, Article 46, Appendix are PRESERVED —
       they act as authoritative and also reset current_section.
    5. Header paragraphs before the first heading stay as Header
       naturally (since current_section starts as "Header").
    """
    if not paragraphs:
        return paragraphs

    # Sort by para_idx to ensure correct order
    paragraphs = sorted(paragraphs, key=lambda p: p.get("para_idx", 0))

    current_section = paragraphs[0].get("section", "Introduction")
    changed = 0

    for para in paragraphs:
        orig_section = para.get("section", "")
        text = (para.get("text") or "").strip()

        # Check if this paragraph looks like a section heading.
        # All patterns use ^ anchors, so we only need to check the
        # beginning of the text — safe even for long paragraphs.
        heading_match = None
        check_text = text[:_HEADING_MAX_LEN] if text else ""
        if check_text:
            for pattern, new_section in _SECTION_BOUNDARY_PATTERNS:
                if pattern.search(check_text):
                    heading_match = new_section
                    break

        if heading_match:
            # Heading detected — always update current section
            current_section = heading_match
            para["section"] = current_section
        elif orig_section in _SUSPECT_SECTIONS:
            # No heading, but original section is unreliable — apply flow
            if para["section"] != current_section:
                para["section"] = current_section
        else:
            # Original section is specific/authoritative — trust it
            # and let it set the current section for subsequent paragraphs
            current_section = orig_section

    return paragraphs


# Global counter for logging
_resegment_stats = {"cases_changed": 0, "paras_changed": 0}


def _resegment_case(paragraphs: list[dict]) -> list[dict]:
    """Wrapper that tracks statistics."""
    orig_sections = [p.get("section") for p in paragraphs]
    result = _resegment_paragraphs(paragraphs)
    new_sections = [p.get("section") for p in result]

    changes = sum(1 for a, b in zip(orig_sections, new_sections) if a != b)
    if changes:
        _resegment_stats["cases_changed"] += 1
        _resegment_stats["paras_changed"] += changes

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

            # Paragraphs — with section re-segmentation
            raw_paragraphs = record.get("paragraphs") or []
            paragraphs = _resegment_case(raw_paragraphs)
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
        log.info("  Re-segmented:     %d cases, %d paragraphs changed",
                 _resegment_stats["cases_changed"],
                 _resegment_stats["paras_changed"])
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
