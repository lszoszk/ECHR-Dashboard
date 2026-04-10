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
    violation        TEXT,   -- JSON array stored as text (HUDOC + inferred)
    non_violation    TEXT,   -- JSON array stored as text (HUDOC + inferred)
    violation_inferred   TEXT,  -- JSON array: articles inferred from conclusion text (not in HUDOC)
    non_violation_inferred TEXT, -- JSON array: articles inferred from conclusion text (not in HUDOC)
    keywords         TEXT,   -- JSON array stored as text
    originating_body TEXT,   -- JSON array stored as text
    document_type    TEXT    -- e.g. "Judgment (Merits and Just Satisfaction)", "Press Release - Chamber Judgments"
);

CREATE TABLE IF NOT EXISTS paragraphs (
    rowid         INTEGER PRIMARY KEY,
    case_id       TEXT NOT NULL REFERENCES cases(case_id),
    section       TEXT,
    para_idx      INTEGER,
    title         TEXT,   -- denormalized from cases.title for BM25F title weight
    keywords_text TEXT,   -- denormalized, " ; "-joined from cases.keywords for BM25F keyword weight
    text          TEXT
);

-- Multi-column FTS5 index enabling BM25F-style field weighting.
-- Column order matters: bm25(paragraphs_fts, w0, w1, w2) and
-- snippet(paragraphs_fts, col_index, ...) both reference columns by
-- position, so DO NOT reorder without updating main.py accordingly.
CREATE VIRTUAL TABLE IF NOT EXISTS paragraphs_fts USING fts5(
    title,           -- col 0 — boosted heavily (case title signal)
    keywords_text,   -- col 1 — boosted moderately (HUDOC thesaurus signal)
    text,            -- col 2 — baseline (paragraph body)
    content       = 'paragraphs',
    content_rowid = 'rowid',
    tokenize      = 'porter unicode61'
);

-- Triggers to keep the FTS index in sync with the content table.
CREATE TRIGGER IF NOT EXISTS paragraphs_ai AFTER INSERT ON paragraphs BEGIN
    INSERT INTO paragraphs_fts(rowid, title, keywords_text, text)
        VALUES (new.rowid, new.title, new.keywords_text, new.text);
END;

CREATE TRIGGER IF NOT EXISTS paragraphs_ad AFTER DELETE ON paragraphs BEGIN
    INSERT INTO paragraphs_fts(paragraphs_fts, rowid, title, keywords_text, text)
        VALUES ('delete', old.rowid, old.title, old.keywords_text, old.text);
END;

CREATE TRIGGER IF NOT EXISTS paragraphs_au AFTER UPDATE ON paragraphs BEGIN
    INSERT INTO paragraphs_fts(paragraphs_fts, rowid, title, keywords_text, text)
        VALUES ('delete', old.rowid, old.title, old.keywords_text, old.text);
    INSERT INTO paragraphs_fts(rowid, title, keywords_text, text)
        VALUES (new.rowid, new.title, new.keywords_text, new.text);
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
# Infer violation / non-violation from conclusion text
# ---------------------------------------------------------------------------

import re

# Regex to extract an article reference after "Violation of" / "No violation of"
# Handles:
#   "Violation of Art. 6-1"
#   "Violation of Article 3 - Prohibition of torture ..."
#   "Violation of Article 1 of Protocol No. 1 - ..."
#   "Violation de l'art. 6-1" (French)
#   "Vilation of Art. 6-1" (HUDOC typo)
_RE_ARTICLE_REF = re.compile(
    r"(?:Article|Art\.?)\s+"
    r"(\d+(?:-\d+)?(?:-[a-z])?)"           # e.g. "6-1", "5-3", "6-1-c"
    r"(?:\s+of\s+Protocol\s+No\.?\s*(\d+))?"  # optional " of Protocol No. 1"
    , re.IGNORECASE,
)

_RE_PROTOCOL_SHORT = re.compile(
    r"(P\d+-\d+(?:-\d+)?(?:-[a-z])?)",      # e.g. "P1-1", "P4-2", "P7-4"
    re.IGNORECASE,
)


def _extract_article(part: str) -> str | None:
    """Extract a normalised article reference from a conclusion clause.

    Returns e.g. "6-1", "P1-1", "3", or None if no article found.
    """
    # Try short protocol form first: "P1-1", "P4-2"
    m = _RE_PROTOCOL_SHORT.search(part)
    if m:
        return m.group(1).upper()

    # Try long form: "Article 6-1" or "Article 1 of Protocol No. 1"
    m = _RE_ARTICLE_REF.search(part)
    if m:
        art_num = m.group(1)
        proto_num = m.group(2)
        if proto_num:
            return f"P{proto_num}-{art_num}"
        return art_num

    # Fallback: bare article ref like "Violation of 6-1" (no "Art." prefix)
    m = re.search(
        r"(?:Violation|Vilation|violation)\s+(?:of|de)\s+(\d+(?:-\d+)?(?:-[a-z])?)",
        part, re.IGNORECASE,
    )
    if m:
        return m.group(1)

    return None


def _infer_violations_from_conclusion(conclusion_text: str) -> tuple[list[str], list[str]]:
    """Parse conclusion text to extract violation / no-violation article lists.

    Returns (violations, non_violations) — each a deduplicated list of article refs.
    """
    if not conclusion_text:
        return [], []

    violations: list[str] = []
    non_violations: list[str] = []
    seen_v: set[str] = set()
    seen_nv: set[str] = set()

    parts = [p.strip() for p in conclusion_text.split(";")]
    for part in parts:
        pu = part.upper()

        # Skip non-violation/non-resolution clauses
        skip_phrases = (
            "FINDING OF VIOLATION SUFFICIENT",
            "PECUNIARY DAMAGE",
            "NON-PECUNIARY DAMAGE",
            "COSTS AND EXPENSES",
            "JUST SATISFACTION RESERVED",
            "NOT NECESSARY TO EXAMINE",
            "NO SEPARATE ISSUE",
            "REMAINDER INADMISSIBLE",
            "PRELIMINARY OBJECTION",
            "STRUCK OUT",
            "FRIENDLY SETTLEMENT",
            "QUESTIONS OF PROCEDURE",
        )
        # If clause is purely about remedies / procedure, skip
        if any(pu.startswith(phrase) for phrase in skip_phrases):
            continue

        # Detect "No violation" / "Non-violation" (incl. French)
        is_no_viol = bool(re.match(
            r"(?:No violation|Non-violation|Non violation|non-violation)",
            part, re.IGNORECASE,
        ))

        # Detect positive "Violation" (but NOT "No violation")
        is_viol = False
        if not is_no_viol:
            is_viol = bool(re.match(
                r"(?:Violation|Vilation)",  # HUDOC typo "Vilation"
                part, re.IGNORECASE,
            ))

        if not is_viol and not is_no_viol:
            continue

        art = _extract_article(part)
        if not art:
            continue

        if is_no_viol:
            if art not in seen_nv:
                seen_nv.add(art)
                non_violations.append(art)
        else:
            if art not in seen_v:
                seen_v.add(art)
                violations.append(art)

    return violations, non_violations


# ---------------------------------------------------------------------------
# Section re-segmentation — fix misclassified paragraphs
# ---------------------------------------------------------------------------

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
                        violation_inferred, non_violation_inferred,
                        keywords, originating_body, document_type)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    case_rows,
                )
            if para_rows:
                conn.executemany(
                    """INSERT INTO paragraphs
                       (case_id, section, para_idx, title, keywords_text, text)
                       VALUES (?,?,?,?,?,?)""",
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

            # --- Violation / non-violation enrichment ---
            hudoc_violation = record.get("violation") or []
            hudoc_non_violation = record.get("non-violation") or record.get("non_violation") or []
            if isinstance(hudoc_violation, str):
                try: hudoc_violation = json.loads(hudoc_violation)
                except: hudoc_violation = []
            if isinstance(hudoc_non_violation, str):
                try: hudoc_non_violation = json.loads(hudoc_non_violation)
                except: hudoc_non_violation = []

            # Parse conclusion text to find articles missing from HUDOC fields
            conclusion_raw = record.get("conclusion")
            conclusion_text = ""
            if isinstance(conclusion_raw, list):
                conclusion_text = "; ".join(str(x) for x in conclusion_raw)
            elif isinstance(conclusion_raw, str):
                conclusion_text = conclusion_raw

            inferred_v, inferred_nv = _infer_violations_from_conclusion(conclusion_text)

            # Determine which inferred articles are truly new (not already in HUDOC)
            hudoc_v_set = set(hudoc_violation)
            hudoc_nv_set = set(hudoc_non_violation)
            new_v = [a for a in inferred_v if a not in hudoc_v_set]
            new_nv = [a for a in inferred_nv if a not in hudoc_nv_set]

            # Merge: final fields = HUDOC + inferred
            merged_violation = list(hudoc_violation) + new_v
            merged_non_violation = list(hudoc_non_violation) + new_nv

            case_rows.append((
                case_id,
                record.get("case_no"),
                record.get("title"),
                record.get("hudoc_url"),
                record.get("judgment_date"),
                record.get("ecli"),
                record.get("respondent_state"),
                str(record.get("importance", "")) if record.get("importance") is not None else None,
                _json_field(conclusion_raw),
                _json_field(merged_violation),
                _json_field(merged_non_violation),
                _json_field(new_v) if new_v else "[]",     # violation_inferred
                _json_field(new_nv) if new_nv else "[]",   # non_violation_inferred
                _json_field(record.get("keywords")),
                _json_field(record.get("originating_body")),
                record.get("document_type") or "",
            ))

            # Paragraphs — with section re-segmentation.
            # Denormalize the case-level title and keywords into every
            # paragraph row so the multi-column FTS5 index can apply
            # per-field BM25F weights.  The memory/storage cost of
            # redundancy is bounded and acceptable (~+200MB for 18k cases).
            case_title = record.get("title") or ""
            raw_keywords = record.get("keywords") or []
            if isinstance(raw_keywords, str):
                try:
                    raw_keywords = json.loads(raw_keywords)
                except Exception:
                    raw_keywords = [raw_keywords]
            if not isinstance(raw_keywords, list):
                raw_keywords = []
            case_keywords_text = " ; ".join(str(k) for k in raw_keywords if k)

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
                    case_title,
                    case_keywords_text,
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
