"""
FastAPI backend for ECHR full-text search over SQLite FTS5.

Provides endpoints for searching ECHR case paragraphs, browsing cases,
retrieving individual cases, and obtaining facet/statistics data.

Database is built separately; this service opens it in read-only mode.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import ranking

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DB_PATH = os.environ.get("ECHR_DB_PATH", "/data/echr_search.db")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("echr-api")

# ---------------------------------------------------------------------------
# Connection pool — thread-local, read-only SQLite connections
# ---------------------------------------------------------------------------

_local = threading.local()


def _get_connection() -> sqlite3.Connection:
    """Return a thread-local read-only SQLite connection."""
    conn: sqlite3.Connection | None = getattr(_local, "conn", None)
    if conn is None:
        uri = f"file:{DB_PATH}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = wal")
        conn.execute("PRAGMA query_only = ON")
        conn.execute("PRAGMA cache_size = -64000")  # 64 MB page cache
        _local.conn = conn
    return conn


@contextmanager
def get_cursor():
    """Yield a cursor from the thread-local connection."""
    conn = _get_connection()
    cur = conn.cursor()
    try:
        yield cur
    finally:
        cur.close()


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="ECHR Case Search API",
    version="1.0",
    description="Full-text search over European Court of Human Rights case law.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://lszoszk.github.io"],
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["Content-Type"],
)


# ---------------------------------------------------------------------------
# Request logging middleware
# ---------------------------------------------------------------------------

@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - start) * 1000
    logger.info(
        "%s %s %s — %.1f ms",
        request.method,
        request.url.path,
        response.status_code,
        elapsed_ms,
    )
    return response


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_json_field(value: Optional[str]):
    """Safely parse a JSON-encoded or plain-text database field.

    Fields may be stored as:
    - JSON array: '["a","b"]' -> ["a","b"]
    - Plain text: 'Court (Chamber)' -> 'Court (Chamber)'
    - Semicolon-separated: 'No violation;Violation' -> kept as string
    """
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    # Only try JSON parse if it looks like JSON (starts with [ or {)
    if value.startswith("[") or value.startswith("{"):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return value
    return value


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    """Convert a sqlite3.Row to a plain dict."""
    return dict(row)


_OR_RE = re.compile(r"\bOR\b", re.IGNORECASE)

# Characters that are special in FTS5 query syntax and must be stripped
# from bare tokens to avoid MATCH parser errors.  Apostrophes are also
# stripped: the FTS5 query parser rejects bare-token apostrophes with a
# syntax error, and because the ``unicode61`` tokenizer splits on them at
# index time anyway, ``O'Halloran`` indexed as ``o`` + ``halloran`` still
# matches a query emitted as ``OHalloran`` (or equivalently ``O Halloran``
# via subsequent splitting by whitespace further upstream — but we emit
# it as a single cleaned token here).
# Double-quotes are handled separately as phrase delimiters.
_FTS5_DANGEROUS_CHARS = re.compile(r"[\^*(){}:+\-~.,;!?/\\|<>=&']+")

# Reserved FTS5 operator keywords (uppercase).  Users who accidentally
# type them as bare words would otherwise produce malformed MATCH expressions.
_FTS5_RESERVED_OPERATORS = {"AND", "OR", "NOT", "NEAR"}


def _extract_phrases(raw: str) -> tuple[list[str], str]:
    """
    Pull balanced ``"..."`` substrings out of ``raw`` and return them as
    sanitised phrase strings alongside the remaining (non-phrase) text.

    Unbalanced stray quotes are dropped.  Phrase contents are themselves
    sanitised of FTS5-dangerous characters but whitespace is preserved so
    the tokenizer can split them at MATCH time.
    """
    phrases: list[str] = []
    remainder_parts: list[str] = []
    i = 0
    n = len(raw)
    while i < n:
        ch = raw[i]
        if ch == '"':
            end = raw.find('"', i + 1)
            if end == -1:
                # Unbalanced — drop the stray quote and keep scanning.
                i += 1
                continue
            inner = raw[i + 1:end]
            inner = _FTS5_DANGEROUS_CHARS.sub(" ", inner).strip()
            if inner:
                phrases.append(inner)
            i = end + 1
            continue
        remainder_parts.append(ch)
        i += 1
    return phrases, "".join(remainder_parts)


def _build_fts_query(raw: str) -> str:
    """
    Convert a user query string into an FTS5 MATCH expression.

    Strategy:
        1. Extract balanced ``"phrases"`` verbatim so the user can force
           exact-order matching for multi-word terms.
        2. Split the remaining text on whitespace into bare tokens.
        3. Strip characters that would confuse the FTS5 parser, but keep
           apostrophes and digits so names like ``O'Halloran`` and article
           numbers like ``3`` survive.
        4. Emit each bare token **without** surrounding double-quotes — this
           is critical: quoted tokens are treated as phrase literals by
           FTS5 and bypass the Porter stemmer, so ``detention`` would not
           match ``detained``.  Bare tokens are stemmed normally.
        5. Join everything with ``AND`` by default; honour an explicit
           uppercase ``OR`` between tokens as a disjunction.
    """
    raw = (raw or "").strip()
    if not raw:
        return ""

    phrases, remainder = _extract_phrases(raw)

    parts: list[str] = []

    # Quoted phrases always come first and join with AND — they are
    # high-precision user intent.
    for phrase in phrases:
        parts.append(f'"{phrase}"')
        parts.append("AND")

    # Replace problematic characters with spaces BEFORE splitting, so
    # ``O'Halloran`` becomes two tokens (``O`` ``Halloran``) that align
    # with how unicode61 tokenized them at index time.  Then split on
    # whitespace to get clean bare tokens.
    normalised = _FTS5_DANGEROUS_CHARS.sub(" ", remainder).replace('"', " ")
    tokens = normalised.split()
    for tok in tokens:
        upper = tok.upper()
        if upper == "OR":
            if parts and parts[-1] == "AND":
                parts[-1] = "OR"
            continue
        if upper in _FTS5_RESERVED_OPERATORS:
            # Swallow stray AND/NOT/NEAR — they're implicit or unsupported.
            continue
        if not tok:
            continue
        parts.append(tok)
        parts.append("AND")

    # Remove trailing operator.
    if parts and parts[-1] in ("AND", "OR"):
        parts.pop()

    return " ".join(parts)


def _validate_page_size(page_size: int, *, allow_large: bool = False) -> int:
    upper = 5000 if allow_large else 100
    return max(1, min(page_size, upper))


def _parse_comma_param(value: Optional[str]) -> list[str]:
    """Split a comma-separated query param into a trimmed list."""
    if not value:
        return []
    return [v.strip() for v in value.split(",") if v.strip()]


def _enrich_case_row(row: dict[str, Any]) -> dict[str, Any]:
    """Parse JSON text fields in a case row into native Python objects."""
    for field in ("conclusion", "violation", "non_violation",
                   "violation_inferred", "non_violation_inferred",
                   "keywords", "originating_body"):
        if field in row:
            row[field] = _parse_json_field(row[field])
    return row


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    """Simple health check."""
    try:
        with get_cursor() as cur:
            cur.execute("SELECT count(*) FROM cases")
            count = cur.fetchone()[0]
        return {"status": "ok", "cases": count}
    except Exception as exc:
        logger.exception("Health check failed")
        raise HTTPException(status_code=503, detail=str(exc)) from exc


# ---- /api/stats ------------------------------------------------------------

@app.get("/api/stats")
def stats():
    """Return high-level database statistics."""
    try:
        with get_cursor() as cur:
            cur.execute("SELECT count(*) FROM cases")
            total_cases = cur.fetchone()[0]

            cur.execute("SELECT count(*) FROM paragraphs")
            total_paragraphs = cur.fetchone()[0]

            cur.execute("SELECT count(*) FROM cases WHERE document_type NOT LIKE '%Press Release%'")
            total_judgments = cur.fetchone()[0]

            cur.execute("SELECT count(*) FROM cases WHERE document_type LIKE '%Press Release%'")
            total_press_releases = cur.fetchone()[0]

            # respondent_state is stored as a single string; inter-state
            # cases collapse multiple countries into one cell
            # (e.g. "Republic of Moldova, Russia",
            # "Bulgaria, Romania", or the 1960s mega-inter-state cases
            # with 15+ co-respondents).  A naive COUNT(DISTINCT ...)
            # returns 79 for the ECHR corpus because every combination
            # is counted as its own "country".  Split on commas and
            # count distinct trimmed values instead — the ECHR has 46
            # member states historically so that is the expected result.
            cur.execute(
                "SELECT respondent_state FROM cases "
                "WHERE respondent_state IS NOT NULL AND respondent_state != ''"
            )
            unique_states: set[str] = set()
            for (raw,) in cur.fetchall():
                for part in raw.split(","):
                    name = part.strip()
                    if name:
                        unique_states.add(name)
            total_countries = len(unique_states)

            # judgment_date is stored as DD/MM/YYYY strings, so naive
            # MIN/MAX does lexicographic (DD-first) comparison and
            # returns nonsense like "01/02/2000" → "31/10/2023" instead
            # of the true corpus range.  Build a YYYYMMDD sort key from
            # substr() and pick the first / last actual date strings.
            iso_key = (
                "substr(judgment_date,7,4) || "
                "substr(judgment_date,4,2) || "
                "substr(judgment_date,1,2)"
            )
            cur.execute(
                f"SELECT judgment_date FROM cases "
                f"WHERE judgment_date IS NOT NULL AND length(judgment_date) = 10 "
                f"ORDER BY {iso_key} ASC LIMIT 1"
            )
            row = cur.fetchone()
            date_from = row[0] if row else None
            cur.execute(
                f"SELECT judgment_date FROM cases "
                f"WHERE judgment_date IS NOT NULL AND length(judgment_date) = 10 "
                f"ORDER BY {iso_key} DESC LIMIT 1"
            )
            row = cur.fetchone()
            date_to = row[0] if row else None

        db_size_mb = 0.0
        try:
            db_size_mb = round(Path(DB_PATH).stat().st_size / (1024 * 1024), 2)
        except OSError:
            pass

        return {
            "total_cases": total_cases,
            "total_judgments": total_judgments,
            "total_press_releases": total_press_releases,
            "total_paragraphs": total_paragraphs,
            "total_countries": total_countries,
            "date_from": date_from,
            "date_to": date_to,
            "db_size_mb": db_size_mb,
            "version": "1.0",
        }
    except Exception as exc:
        logger.exception("Stats query failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ---- /api/facets -----------------------------------------------------------

@app.get("/api/facets")
def facets():
    """Return available filter values with counts."""
    try:
        result: dict[str, Any] = {}
        with get_cursor() as cur:
            # Articles
            cur.execute(
                "SELECT article AS value, count(DISTINCT case_id) AS count "
                "FROM case_articles GROUP BY article ORDER BY count DESC"
            )
            result["articles"] = [_row_to_dict(r) for r in cur.fetchall()]

            # Respondent states — split compound entries ("Italy, San Marino")
            # into individual unique countries with aggregated counts
            cur.execute(
                "SELECT respondent_state, count(*) AS count "
                "FROM cases WHERE respondent_state IS NOT NULL AND respondent_state != '' "
                "GROUP BY respondent_state"
            )
            country_counts: dict[str, int] = {}
            for row in cur.fetchall():
                raw = row["respondent_state"]
                parts = [p.strip() for p in raw.split(",") if p.strip()]
                for part in parts:
                    country_counts[part] = country_counts.get(part, 0) + row["count"]
            result["states"] = sorted(
                [{"value": k, "count": v} for k, v in country_counts.items()],
                key=lambda x: -x["count"],
            )

            # Importance
            cur.execute(
                "SELECT importance AS value, count(*) AS count "
                "FROM cases WHERE importance IS NOT NULL "
                "GROUP BY importance ORDER BY count DESC"
            )
            result["importance"] = [_row_to_dict(r) for r in cur.fetchall()]

            # Sections (exclude Header — it's case metadata, not judgment content)
            cur.execute(
                "SELECT section AS value, count(DISTINCT case_id) AS count "
                "FROM paragraphs WHERE section IS NOT NULL AND section != 'Header' "
                "GROUP BY section ORDER BY count DESC"
            )
            result["sections"] = [_row_to_dict(r) for r in cur.fetchall()]

            # Originating bodies
            cur.execute(
                "SELECT originating_body AS value, count(*) AS count "
                "FROM cases WHERE originating_body IS NOT NULL AND originating_body != '' "
                "GROUP BY originating_body ORDER BY count DESC"
            )
            result["bodies"] = [_row_to_dict(r) for r in cur.fetchall()]

            # Document types
            cur.execute(
                "SELECT document_type AS value, count(*) AS count "
                "FROM cases WHERE document_type IS NOT NULL AND document_type != '' "
                "GROUP BY document_type ORDER BY count DESC"
            )
            result["doc_types"] = [_row_to_dict(r) for r in cur.fetchall()]

            # Date range — judgment_date is DD/MM/YYYY, so naive MIN/MAX
            # is lexicographic-by-DD, not chronological.  Sort by an
            # ISO-style YYYYMMDD key and pick the first / last rows.
            iso_key = (
                "substr(judgment_date,7,4) || "
                "substr(judgment_date,4,2) || "
                "substr(judgment_date,1,2)"
            )
            cur.execute(
                f"SELECT judgment_date FROM cases "
                f"WHERE judgment_date IS NOT NULL AND length(judgment_date) = 10 "
                f"ORDER BY {iso_key} ASC LIMIT 1"
            )
            _r = cur.fetchone()
            min_date = _r["judgment_date"] if _r else None
            cur.execute(
                f"SELECT judgment_date FROM cases "
                f"WHERE judgment_date IS NOT NULL AND length(judgment_date) = 10 "
                f"ORDER BY {iso_key} DESC LIMIT 1"
            )
            _r = cur.fetchone()
            max_date = _r["judgment_date"] if _r else None
            result["date_range"] = {"min": min_date, "max": max_date}

        return result
    except Exception as exc:
        logger.exception("Facets query failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ---- /api/analytics --------------------------------------------------------

def _build_case_filter_sql(
    *,
    fts_expr: str = "",
    sec_list: list[str] | None = None,
    art_list: list[str] | None = None,
    state_list: list[str] | None = None,
    imp_list: list[str] | None = None,
    body_list: list[str] | None = None,
    outcome_list: list[str] | None = None,
    doc_type_list: list[str] | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> tuple[str, str, list[Any]]:
    """Build shared WHERE/JOIN clauses for case queries.

    Returns (join_sql, where_sql, params).
    If fts_expr is given, includes FTS join and match condition.
    """
    where_clauses: list[str] = []
    joins: list[str] = []
    params: list[Any] = []

    if fts_expr:
        joins.append(
            "JOIN paragraphs p ON p.case_id = c.case_id "
            "JOIN paragraphs_fts pf ON pf.rowid = p.rowid"
        )
        where_clauses.append("pf.paragraphs_fts MATCH ?")
        params.append(fts_expr)

    if sec_list and fts_expr:
        placeholders = ",".join("?" for _ in sec_list)
        where_clauses.append(f"p.section IN ({placeholders})")
        params.extend(sec_list)

    if art_list:
        placeholders = ",".join("?" for _ in art_list)
        joins.append(
            f"JOIN case_articles ca ON ca.case_id = c.case_id AND ca.article IN ({placeholders})"
        )
        params.extend(art_list)

    if state_list:
        state_conditions = []
        for st in state_list:
            state_conditions.append(
                "(c.respondent_state = ? OR c.respondent_state LIKE ? "
                "OR c.respondent_state LIKE ? OR c.respondent_state LIKE ?)"
            )
            params.extend([st, f"{st}, %", f"%, {st}, %", f"%, {st}"])
        where_clauses.append(f"({' OR '.join(state_conditions)})")

    if imp_list:
        placeholders = ",".join("?" for _ in imp_list)
        where_clauses.append(f"c.importance IN ({placeholders})")
        params.extend(imp_list)

    if body_list:
        body_conditions = []
        for b in body_list:
            body_conditions.append("c.originating_body LIKE ?")
            params.append(f"%{b}%")
        where_clauses.append(f"({' OR '.join(body_conditions)})")

    if outcome_list:
        oc_conditions = []
        for oc in outcome_list:
            if oc == "violation_only":
                oc_conditions.append("(c.violation != '[]' AND c.violation != '' AND (c.non_violation = '[]' OR c.non_violation = '') AND c.document_type NOT LIKE '%Press Release%')")
            elif oc == "non_violation_only":
                oc_conditions.append("((c.violation = '[]' OR c.violation = '') AND c.non_violation != '[]' AND c.non_violation != '' AND c.document_type NOT LIKE '%Press Release%')")
            elif oc == "both":
                oc_conditions.append("(c.violation != '[]' AND c.violation != '' AND c.non_violation != '[]' AND c.non_violation != '' AND c.document_type NOT LIKE '%Press Release%')")
            elif oc == "neither":
                oc_conditions.append("((c.violation = '[]' OR c.violation = '' OR c.violation IS NULL) AND (c.non_violation = '[]' OR c.non_violation = '' OR c.non_violation IS NULL) AND c.document_type NOT LIKE '%Press Release%')")
            elif oc == "press_release":
                oc_conditions.append("(c.document_type LIKE '%Press Release%')")
        if oc_conditions:
            where_clauses.append(f"({' OR '.join(oc_conditions)})")

    if doc_type_list:
        dt_conditions = []
        for dt in doc_type_list:
            if dt == "press_release":
                dt_conditions.append("c.document_type LIKE '%Press Release%'")
            elif dt == "judgment":
                dt_conditions.append("c.document_type NOT LIKE '%Press Release%'")
            elif dt == "committee":
                dt_conditions.append("c.document_type LIKE '%Committee%'")
            elif dt == "grand_chamber":
                dt_conditions.append("c.originating_body LIKE '%Grand Chamber%'")
            elif dt == "chamber":
                dt_conditions.append(
                    "(c.document_type NOT LIKE '%Press Release%' "
                    "AND c.document_type NOT LIKE '%Committee%' "
                    "AND (c.originating_body IS NULL "
                    "OR c.originating_body NOT LIKE '%Grand Chamber%'))"
                )
        if dt_conditions:
            where_clauses.append(f"({' OR '.join(dt_conditions)})")

    if date_from:
        where_clauses.append("c.judgment_date >= ?")
        params.append(date_from)

    if date_to:
        where_clauses.append("c.judgment_date <= ?")
        params.append(date_to)

    join_sql = " ".join(joins)
    where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"
    return join_sql, where_sql, params


@app.get("/api/analytics")
def analytics(
    q: Optional[str] = Query(None, description="Full-text search query"),
    sections: Optional[str] = Query(None),
    articles: Optional[str] = Query(None),
    states: Optional[str] = Query(None),
    importance: Optional[str] = Query(None),
    bodies: Optional[str] = Query(None),
    outcomes: Optional[str] = Query(None),
    doc_types: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
):
    """Return aggregated analytics for the given query/filters over ALL matching cases."""
    t0 = time.perf_counter()

    fts_expr = ""
    if q and q.strip():
        fts_expr = _build_fts_query(q)

    join_sql, where_sql, params = _build_case_filter_sql(
        fts_expr=fts_expr,
        sec_list=_parse_comma_param(sections),
        art_list=_parse_comma_param(articles),
        state_list=_parse_comma_param(states),
        imp_list=_parse_comma_param(importance),
        body_list=_parse_comma_param(bodies),
        outcome_list=_parse_comma_param(outcomes),
        doc_type_list=_parse_comma_param(doc_types),
        date_from=date_from,
        date_to=date_to,
    )

    try:
        result: dict[str, Any] = {}
        with get_cursor() as cur:
            # Step 1: Collect matching case_ids into a Python set (one FTS pass).
            cur.execute(
                f"SELECT DISTINCT c.case_id "
                f"FROM cases c {join_sql} "
                f"WHERE {where_sql}",
                params,
            )
            matching_ids = [r["case_id"] for r in cur.fetchall()]
            result["total_cases"] = len(matching_ids)

            if not matching_ids:
                elapsed = (time.perf_counter() - t0) * 1000
                result.update(articles=[], countries=[], sections=[], bodies=[],
                              importance=[], outcomes=[], doc_types=[],
                              analytics_time_ms=round(elapsed, 1))
                return result

            # Build a json array param for efficient IN-filtering via json_each.
            ids_json = json.dumps(matching_ids)

            # Articles breakdown
            cur.execute(
                "SELECT ca.article AS value, count(DISTINCT ca.case_id) AS count "
                "FROM case_articles ca "
                "WHERE ca.case_id IN (SELECT value FROM json_each(?)) "
                "GROUP BY ca.article ORDER BY count DESC LIMIT 15",
                [ids_json],
            )
            result["articles"] = [_row_to_dict(r) for r in cur.fetchall()]

            # Countries breakdown (split compound entries)
            cur.execute(
                "SELECT c.respondent_state, count(*) AS count "
                "FROM cases c "
                "WHERE c.case_id IN (SELECT value FROM json_each(?)) "
                "AND c.respondent_state IS NOT NULL AND c.respondent_state != '' "
                "GROUP BY c.respondent_state",
                [ids_json],
            )
            country_counts: dict[str, int] = {}
            for row in cur.fetchall():
                raw = row["respondent_state"]
                parts = [p.strip() for p in raw.split(",") if p.strip()]
                for part in parts:
                    country_counts[part] = country_counts.get(part, 0) + row["count"]
            result["countries"] = sorted(
                [{"value": k, "count": v} for k, v in country_counts.items()],
                key=lambda x: -x["count"],
            )[:15]

            # Sections breakdown (case count per section)
            cur.execute(
                "SELECT p.section AS value, count(DISTINCT p.case_id) AS count "
                "FROM paragraphs p "
                "WHERE p.case_id IN (SELECT value FROM json_each(?)) "
                "AND p.section IS NOT NULL AND p.section != 'Header' "
                "GROUP BY p.section ORDER BY count DESC LIMIT 15",
                [ids_json],
            )
            result["sections"] = [_row_to_dict(r) for r in cur.fetchall()]

            # Originating bodies
            cur.execute(
                "SELECT c.originating_body AS value, count(*) AS count "
                "FROM cases c "
                "WHERE c.case_id IN (SELECT value FROM json_each(?)) "
                "AND c.originating_body IS NOT NULL AND c.originating_body != '' "
                "GROUP BY c.originating_body ORDER BY count DESC LIMIT 15",
                [ids_json],
            )
            result["bodies"] = [_row_to_dict(r) for r in cur.fetchall()]

            # Importance
            cur.execute(
                "SELECT c.importance AS value, count(*) AS count "
                "FROM cases c "
                "WHERE c.case_id IN (SELECT value FROM json_each(?)) "
                "AND c.importance IS NOT NULL "
                "GROUP BY c.importance ORDER BY count DESC",
                [ids_json],
            )
            result["importance"] = [_row_to_dict(r) for r in cur.fetchall()]

            # Outcomes (derived from violation / non_violation + doc type)
            cur.execute(
                "SELECT "
                "  CASE "
                "    WHEN c.document_type LIKE '%Press Release%' THEN 'press_release' "
                "    WHEN c.violation != '[]' AND c.violation != '' "
                "         AND c.non_violation != '[]' AND c.non_violation != '' THEN 'both' "
                "    WHEN c.violation != '[]' AND c.violation != '' THEN 'violation_only' "
                "    WHEN c.non_violation != '[]' AND c.non_violation != '' THEN 'non_violation_only' "
                "    ELSE 'neither' "
                "  END AS value, "
                "  count(*) AS count "
                "FROM cases c "
                "WHERE c.case_id IN (SELECT value FROM json_each(?)) "
                "GROUP BY value ORDER BY count DESC",
                [ids_json],
            )
            result["outcomes"] = [_row_to_dict(r) for r in cur.fetchall()]

            # Document types
            cur.execute(
                "SELECT c.document_type AS value, count(*) AS count "
                "FROM cases c "
                "WHERE c.case_id IN (SELECT value FROM json_each(?)) "
                "AND c.document_type IS NOT NULL AND c.document_type != '' "
                "GROUP BY c.document_type ORDER BY count DESC",
                [ids_json],
            )
            result["doc_types"] = [_row_to_dict(r) for r in cur.fetchall()]

        elapsed = (time.perf_counter() - t0) * 1000
        result["analytics_time_ms"] = round(elapsed, 1)
        return result
    except sqlite3.OperationalError as exc:
        logger.exception("Analytics query failed")
        raise HTTPException(status_code=400, detail=f"Analytics error: {exc}") from exc
    except Exception as exc:
        logger.exception("Unexpected analytics error")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ---- /api/search -----------------------------------------------------------

@app.get("/api/search")
def search(
    q: str = Query(..., min_length=1, description="Full-text search query"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=5000),
    sections: Optional[str] = Query(None, description="Comma-separated section filter"),
    articles: Optional[str] = Query(None, description="Comma-separated article filter"),
    states: Optional[str] = Query(None, description="Comma-separated respondent_state filter"),
    importance: Optional[str] = Query(None, description="Comma-separated importance filter"),
    bodies: Optional[str] = Query(None, description="Comma-separated originating_body filter"),
    outcomes: Optional[str] = Query(None, description="Comma-separated outcome filter (violation_only,non_violation_only,both,neither)"),
    doc_types: Optional[str] = Query(None, description="Comma-separated document type filter (judgment,press_release,committee,chamber,grand_chamber)"),
    date_from: Optional[str] = Query(None, description="Earliest judgment_date (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="Latest judgment_date (YYYY-MM-DD)"),
    sort: str = Query("relevance", pattern="^(relevance|date_desc|date_asc)$"),
    export: bool = Query(False, description="If true, allow large page_size for CSV export"),
):
    """Full-text search across case paragraphs using FTS5."""
    t0 = time.perf_counter()
    page_size = _validate_page_size(page_size, allow_large=export)
    fts_expr = _build_fts_query(q)
    if not fts_expr:
        raise HTTPException(status_code=400, detail="Empty search query after sanitisation.")

    sec_list = _parse_comma_param(sections)
    art_list = _parse_comma_param(articles)
    state_list = _parse_comma_param(states)
    imp_list = _parse_comma_param(importance)
    body_list = _parse_comma_param(bodies)
    outcome_list = _parse_comma_param(outcomes)
    doc_type_list = _parse_comma_param(doc_types)

    # ------------------------------------------------------------------
    # Build the core query.  We join paragraphs_fts -> paragraphs -> cases
    # and optionally case_articles for the article filter.
    # ------------------------------------------------------------------
    params: list[Any] = []

    where_clauses: list[str] = ["pf.paragraphs_fts MATCH ?"]
    params.append(fts_expr)

    joins: list[str] = []

    if sec_list:
        placeholders = ",".join("?" for _ in sec_list)
        where_clauses.append(f"p.section IN ({placeholders})")
        params.extend(sec_list)

    if art_list:
        placeholders = ",".join("?" for _ in art_list)
        joins.append(
            f"JOIN case_articles ca ON ca.case_id = c.case_id AND ca.article IN ({placeholders})"
        )
        params.extend(art_list)

    if state_list:
        state_conditions = []
        for st in state_list:
            # Match both exact ("Italy") and compound ("Italy, San Marino")
            state_conditions.append(
                "(c.respondent_state = ? OR c.respondent_state LIKE ? OR c.respondent_state LIKE ? OR c.respondent_state LIKE ?)"
            )
            params.extend([st, f"{st}, %", f"%, {st}, %", f"%, {st}"])
        where_clauses.append(f"({' OR '.join(state_conditions)})")

    if imp_list:
        placeholders = ",".join("?" for _ in imp_list)
        where_clauses.append(f"c.importance IN ({placeholders})")
        params.extend(imp_list)

    if body_list:
        body_conditions = []
        for b in body_list:
            body_conditions.append("c.originating_body LIKE ?")
            params.append(f"%{b}%")
        where_clauses.append(f"({' OR '.join(body_conditions)})")

    if outcome_list:
        oc_conditions = []
        for oc in outcome_list:
            if oc == "violation_only":
                oc_conditions.append("(c.violation != '[]' AND c.violation != '' AND (c.non_violation = '[]' OR c.non_violation = '') AND c.document_type NOT LIKE '%Press Release%')")
            elif oc == "non_violation_only":
                oc_conditions.append("((c.violation = '[]' OR c.violation = '') AND c.non_violation != '[]' AND c.non_violation != '' AND c.document_type NOT LIKE '%Press Release%')")
            elif oc == "both":
                oc_conditions.append("(c.violation != '[]' AND c.violation != '' AND c.non_violation != '[]' AND c.non_violation != '' AND c.document_type NOT LIKE '%Press Release%')")
            elif oc == "neither":
                oc_conditions.append("((c.violation = '[]' OR c.violation = '' OR c.violation IS NULL) AND (c.non_violation = '[]' OR c.non_violation = '' OR c.non_violation IS NULL) AND c.document_type NOT LIKE '%Press Release%')")
            elif oc == "press_release":
                oc_conditions.append("(c.document_type LIKE '%Press Release%')")
        if oc_conditions:
            where_clauses.append(f"({' OR '.join(oc_conditions)})")

    if doc_type_list:
        dt_conditions = []
        for dt in doc_type_list:
            if dt == "press_release":
                dt_conditions.append("c.document_type LIKE '%Press Release%'")
            elif dt == "judgment":
                dt_conditions.append("c.document_type NOT LIKE '%Press Release%'")
            elif dt == "committee":
                dt_conditions.append("c.document_type LIKE '%Committee%'")
            elif dt == "grand_chamber":
                dt_conditions.append("c.originating_body LIKE '%Grand Chamber%'")
            elif dt == "chamber":
                dt_conditions.append(
                    "(c.document_type NOT LIKE '%Press Release%' "
                    "AND c.document_type NOT LIKE '%Committee%' "
                    "AND (c.originating_body IS NULL "
                    "OR c.originating_body NOT LIKE '%Grand Chamber%'))"
                )
        if dt_conditions:
            where_clauses.append(f"({' OR '.join(dt_conditions)})")

    if date_from:
        where_clauses.append("c.judgment_date >= ?")
        params.append(date_from)

    if date_to:
        where_clauses.append("c.judgment_date <= ?")
        params.append(date_to)

    where_sql = " AND ".join(where_clauses)
    join_sql = " ".join(joins)

    # Determine sort clause at the case-group level.
    # For relevance sort we order by a MAX-DOMINATED score:
    #     max(-rank) * (1 + 0.3 * ln(1 + hit_count))
    # where `max(-rank)` is the strongest single-paragraph BM25F hit in
    # the case (the most distinctive match) and the `ln(1+hit_count)`
    # factor adds a mild density bonus so that a case which mentions the
    # query several times slightly outranks one with a single lucky hit.
    #
    # Why not raw sum(-rank)?  Pilot A/B on golden queries showed strong
    # long-judgment bias — e.g. "torture" placed 1800-paragraph mega
    # inter-state cases above Ireland v. UK, and "Hirst" placed HORA
    # (which cites Hirst 59×) above HIRST v. UK itself (which only
    # mentions its own name 3×).  max*ln damps the "long-document wins"
    # pathology while still rewarding topical density.  See ranking.py
    # for BM25F column weights (title=5, keywords=3, text=1).
    # judgment_date is stored as DD/MM/YYYY; a raw ORDER BY on that
    # column is lexicographic-by-DD, not chronological.  Sort by an
    # ISO-style YYYYMMDD key derived from substr() to get the true
    # chronological order.
    date_sort_key = (
        "(substr(c.judgment_date,7,4) || "
        "substr(c.judgment_date,4,2) || "
        "substr(c.judgment_date,1,2))"
    )
    if sort == "date_desc":
        order_sql = f"{date_sort_key} DESC"
    elif sort == "date_asc":
        order_sql = f"{date_sort_key} ASC"
    else:
        order_sql = "relevance_score DESC"

    # ------------------------------------------------------------------
    # Step 1: Count distinct cases + total hits.
    # ------------------------------------------------------------------
    try:
        with get_cursor() as cur:
            count_sql = (
                "SELECT count(DISTINCT c.case_id) AS total_cases, count(*) AS total_hits "
                "FROM paragraphs_fts pf "
                "JOIN paragraphs p ON p.rowid = pf.rowid "
                "JOIN cases c ON c.case_id = p.case_id "
                f"{join_sql} "
                f"WHERE {where_sql}"
            )
            cur.execute(count_sql, params)
            count_row = cur.fetchone()
            total_cases = count_row["total_cases"]
            total_hits = count_row["total_hits"]

            if total_cases == 0:
                elapsed = (time.perf_counter() - t0) * 1000
                return {
                    "total_cases": 0,
                    "total_hits": 0,
                    "page": page,
                    "page_size": page_size,
                    "search_time_ms": round(elapsed, 1),
                    "cases": [],
                }

            # ----------------------------------------------------------
            # Step 2: Get case IDs + per-case scores.
            # ----------------------------------------------------------
            # bm25() returns a NEGATIVE float — more-negative = better match.
            # We negate it so the per-case score is "higher = better", which
            # rewards both quality (big positive max from a strong match)
            # and quantity (the ln(1+hit_count) density factor).
            # Column weights: title=5.0, keywords=3.0, body=1.0 (BM25F-style).
            #
            # On relevance sort we fetch **every** matching case together
            # with the metadata needed for the boost pass, then rerank
            # the full set in Python, and only then slice the requested
            # page.  This makes pagination invariant under page_size
            # changes: the ranking function sees the entire corpus of
            # matches, not an arbitrary candidate pool whose size would
            # otherwise let high-boost cases fall off the edge.
            #
            # On date sorts we delegate ordering and pagination to SQL
            # and skip the metadata rerank entirely.
            rerank_active = ranking.should_rerank(sort)

            # NOTE on the `-pf.rank` trick:
            #
            # SQLite 3.51 refuses to evaluate `bm25(paragraphs_fts, ...)`
            # inside a `sum()` aggregate when the query contains a
            # GROUP BY + JOIN chain — the planner flattens the subquery
            # and loses the FTS5 cursor context, raising "unable to use
            # function bm25 in the requested context".  A MATERIALIZED
            # CTE workaround exists but forces the planner to build a
            # 300k+ row temp table on every search, which adds ~2–10s
            # of latency on broad queries ("torture", "detention", …).
            #
            # The fast path: FTS5 exposes a hidden `rank` column that
            # returns the raw bm25 score for the current row.  By
            # persisting BM25F weights via
            #   INSERT INTO paragraphs_fts(paragraphs_fts, rank)
            #   VALUES ('rank', 'bm25(5.0, 3.0, 1.0)');
            # in build_db.py, `pf.rank` becomes the pre-weighted BM25F
            # score and IS aggregatable without materialisation.  We
            # negate so higher = better.
            # MAX-dominated relevance_score is pre-computed in SQL so we
            # can ORDER BY it (and pull importance / body / doc_type in
            # the same pass for the Python-side rerank).
            if rerank_active:
                # Fetch ALL matching cases + the metadata needed for the
                # boost pass in a single query.  No LIMIT — reranking
                # must see every match.
                case_ids_sql = (
                    "SELECT c.case_id, "
                    "       c.importance, "
                    "       c.originating_body, "
                    "       c.document_type, "
                    "       sum(-pf.rank) AS sum_bm25, "
                    "       max(-pf.rank) AS best_bm25, "
                    "       count(*) AS hit_count, "
                    "       max(-pf.rank) * (1.0 + 0.3 * ln(1.0 + count(*))) AS relevance_score "
                    "FROM paragraphs_fts pf "
                    "JOIN paragraphs p ON p.rowid = pf.rowid "
                    "JOIN cases c ON c.case_id = p.case_id "
                    f"{join_sql} "
                    f"WHERE {where_sql} "
                    "GROUP BY c.case_id "
                    f"ORDER BY {order_sql}"
                )
                cur.execute(case_ids_sql, params)
                case_rows = cur.fetchall()
                case_meta = {
                    r["case_id"]: {
                        "sum_bm25": r["sum_bm25"],
                        "best_bm25": r["best_bm25"],
                        "relevance_score": r["relevance_score"],
                        "score": r["relevance_score"],  # overwritten below
                        "hit_count": r["hit_count"],
                    }
                    for r in case_rows
                }

                # Rerank the full match set, then slice the requested
                # page.  Step 3 / Step 4 only pay for the final
                # page_size cases.
                candidates = [
                    {
                        "case_id": r["case_id"],
                        # Feed the max*ln relevance score into ranking,
                        # not the raw sum_bm25.  sum_bm25 is kept only
                        # for diagnostics / downstream display.
                        "sum_bm25": r["relevance_score"],
                        "hit_count": r["hit_count"],
                        "importance": r["importance"],
                        "originating_body": r["originating_body"],
                        "document_type": r["document_type"],
                    }
                    for r in case_rows
                ]
                reranked = ranking.rerank_candidates(candidates)
                for c in reranked:
                    case_meta[c["case_id"]]["score"] = c["final_score"]
                ordered_case_ids = [c["case_id"] for c in reranked]

                page_start = max(0, (page - 1) * page_size)
                case_ids = ordered_case_ids[page_start : page_start + page_size]
            else:
                # Date sort: let SQL order and paginate.
                sql_limit = page_size
                sql_offset = (page - 1) * page_size
                case_ids_sql = (
                    "SELECT c.case_id, "
                    "       sum(-pf.rank) AS sum_bm25, "
                    "       max(-pf.rank) AS best_bm25, "
                    "       count(*) AS hit_count, "
                    "       max(-pf.rank) * (1.0 + 0.3 * ln(1.0 + count(*))) AS relevance_score "
                    "FROM paragraphs_fts pf "
                    "JOIN paragraphs p ON p.rowid = pf.rowid "
                    "JOIN cases c ON c.case_id = p.case_id "
                    f"{join_sql} "
                    f"WHERE {where_sql} "
                    "GROUP BY c.case_id "
                    f"ORDER BY {order_sql} "
                    "LIMIT ? OFFSET ?"
                )
                cur.execute(case_ids_sql, params + [sql_limit, sql_offset])
                case_rows = cur.fetchall()
                case_ids = [r["case_id"] for r in case_rows]
                case_meta = {
                    r["case_id"]: {
                        "sum_bm25": r["sum_bm25"],
                        "best_bm25": r["best_bm25"],
                        "relevance_score": r["relevance_score"],
                        "score": r["relevance_score"],
                        "hit_count": r["hit_count"],
                    }
                    for r in case_rows
                }

            if not case_ids:
                elapsed = (time.perf_counter() - t0) * 1000
                return {
                    "total_cases": total_cases,
                    "total_hits": total_hits,
                    "page": page,
                    "page_size": page_size,
                    "search_time_ms": round(elapsed, 1),
                    "cases": [],
                }

            # ----------------------------------------------------------
            # Step 3: Fetch case details.
            # ----------------------------------------------------------
            id_placeholders = ",".join("?" for _ in case_ids)
            cur.execute(
                "SELECT case_id, case_no, title, judgment_date, hudoc_url, "
                "respondent_state, importance, conclusion, violation, "
                "non_violation, violation_inferred, non_violation_inferred, keywords, originating_body, document_type "
                f"FROM cases WHERE case_id IN ({id_placeholders})",
                case_ids,
            )
            case_details = {r["case_id"]: _enrich_case_row(_row_to_dict(r)) for r in cur.fetchall()}

            # Fetch articles per case.
            cur.execute(
                f"SELECT case_id, article FROM case_articles WHERE case_id IN ({id_placeholders})",
                case_ids,
            )
            case_articles: dict[str, list[str]] = {}
            for r in cur.fetchall():
                case_articles.setdefault(r["case_id"], []).append(r["article"])

            # ----------------------------------------------------------
            # Step 4: Fetch matching paragraphs with snippets.
            # ----------------------------------------------------------
            snippet_params: list[Any] = [fts_expr]
            sec_where = ""
            if sec_list:
                sec_ph = ",".join("?" for _ in sec_list)
                sec_where = f"AND p.section IN ({sec_ph})"
                snippet_params.extend(sec_list)

            snippet_params.append(fts_expr)
            snippet_params.extend(case_ids)

            # snippet() column index: text is column 2 in the multi-column
            # paragraphs_fts (title=0, keywords_text=1, text=2).
            # Within-case paragraph ordering uses `pf.rank` (which is the
            # stored BM25F-weighted score, via the rank config set in
            # build_db.py) so it stays consistent with cross-case ranking.
            snippet_sql = (
                "SELECT p.case_id, p.section, p.para_idx, p.hudoc_para_no, "
                "snippet(paragraphs_fts, 2, '<b>', '</b>', '...', 80) AS snippet, "
                "pf.rank AS para_score "
                "FROM paragraphs_fts pf "
                "JOIN paragraphs p ON p.rowid = pf.rowid "
                f"WHERE pf.paragraphs_fts MATCH ? {sec_where} "
                f"AND p.case_id IN (SELECT value FROM json_each(?) ) "
                "ORDER BY pf.rank"
            )
            # Use json array to pass case_ids safely.
            snippet_params_final: list[Any] = [fts_expr]
            if sec_list:
                snippet_params_final.extend(sec_list)
            snippet_params_final.append(json.dumps(case_ids))

            cur.execute(snippet_sql, snippet_params_final)
            case_paragraphs: dict[str, list[dict]] = {}
            for r in cur.fetchall():
                case_paragraphs.setdefault(r["case_id"], []).append({
                    "section": r["section"],
                    "para_idx": r["para_idx"],
                    "hudoc_para_no": r["hudoc_para_no"],
                    "snippet": r["snippet"],
                })

            # ----------------------------------------------------------
            # Assemble response in page order.
            # ----------------------------------------------------------
            cases_out: list[dict[str, Any]] = []
            for cid in case_ids:
                detail = case_details.get(cid, {})
                meta = case_meta.get(cid, {})
                cases_out.append({
                    **detail,
                    "articles": sorted(case_articles.get(cid, [])),
                    "hit_count": meta.get("hit_count", 0),
                    "score": meta.get("score", 0),
                    "paragraphs": case_paragraphs.get(cid, []),
                })

            elapsed = (time.perf_counter() - t0) * 1000
            return {
                "total_cases": total_cases,
                "total_hits": total_hits,
                "page": page,
                "page_size": page_size,
                "search_time_ms": round(elapsed, 1),
                "cases": cases_out,
            }
    except sqlite3.OperationalError as exc:
        logger.exception("Search query failed")
        raise HTTPException(status_code=400, detail=f"Search error: {exc}") from exc
    except Exception as exc:
        logger.exception("Unexpected search error")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ---- /api/cases/{case_id} -------------------------------------------------

@app.get("/api/cases/{case_id}")
def get_case(case_id: str):
    """Return full case detail with all paragraphs."""
    try:
        with get_cursor() as cur:
            cur.execute(
                "SELECT case_id, case_no, title, judgment_date, hudoc_url, ecli, "
                "respondent_state, importance, conclusion, violation, "
                "non_violation, violation_inferred, non_violation_inferred, keywords, originating_body, document_type "
                "FROM cases WHERE case_id = ?",
                (case_id,),
            )
            row = cur.fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail=f"Case '{case_id}' not found.")

            case = _enrich_case_row(_row_to_dict(row))

            # Articles
            cur.execute(
                "SELECT article FROM case_articles WHERE case_id = ? ORDER BY article",
                (case_id,),
            )
            case["articles"] = [r["article"] for r in cur.fetchall()]

            # All paragraphs (includes hudoc_para_no — see P10 / data-cleaning-full.md §11)
            cur.execute(
                "SELECT section, para_idx, hudoc_para_no, text "
                "FROM paragraphs WHERE case_id = ? ORDER BY para_idx",
                (case_id,),
            )
            case["paragraphs"] = [_row_to_dict(r) for r in cur.fetchall()]

        return case
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Case retrieval failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ---- /api/browse -----------------------------------------------------------

@app.get("/api/browse")
def browse(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    articles: Optional[str] = Query(None),
    states: Optional[str] = Query(None),
    importance: Optional[str] = Query(None),
    bodies: Optional[str] = Query(None),
    outcomes: Optional[str] = Query(None),
    doc_types: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    sort: str = Query("date_desc", pattern="^(date_desc|date_asc)$"),
):
    """Browse / filter cases without full-text search."""
    t0 = time.perf_counter()
    page_size = _validate_page_size(page_size)

    art_list = _parse_comma_param(articles)
    state_list = _parse_comma_param(states)
    imp_list = _parse_comma_param(importance)
    body_list = _parse_comma_param(bodies)
    outcome_list = _parse_comma_param(outcomes)
    doc_type_list = _parse_comma_param(doc_types)

    where_clauses: list[str] = []
    joins: list[str] = []
    params: list[Any] = []

    if art_list:
        placeholders = ",".join("?" for _ in art_list)
        joins.append(
            f"JOIN case_articles ca ON ca.case_id = c.case_id AND ca.article IN ({placeholders})"
        )
        params.extend(art_list)

    if state_list:
        state_conditions = []
        for st in state_list:
            # Match both exact ("Italy") and compound ("Italy, San Marino")
            state_conditions.append(
                "(c.respondent_state = ? OR c.respondent_state LIKE ? OR c.respondent_state LIKE ? OR c.respondent_state LIKE ?)"
            )
            params.extend([st, f"{st}, %", f"%, {st}, %", f"%, {st}"])
        where_clauses.append(f"({' OR '.join(state_conditions)})")

    if imp_list:
        placeholders = ",".join("?" for _ in imp_list)
        where_clauses.append(f"c.importance IN ({placeholders})")
        params.extend(imp_list)

    if body_list:
        body_conditions = []
        for b in body_list:
            body_conditions.append("c.originating_body LIKE ?")
            params.append(f"%{b}%")
        where_clauses.append(f"({' OR '.join(body_conditions)})")

    if outcome_list:
        oc_conditions = []
        for oc in outcome_list:
            if oc == "violation_only":
                oc_conditions.append("(c.violation != '[]' AND c.violation != '' AND (c.non_violation = '[]' OR c.non_violation = '') AND c.document_type NOT LIKE '%Press Release%')")
            elif oc == "non_violation_only":
                oc_conditions.append("((c.violation = '[]' OR c.violation = '') AND c.non_violation != '[]' AND c.non_violation != '' AND c.document_type NOT LIKE '%Press Release%')")
            elif oc == "both":
                oc_conditions.append("(c.violation != '[]' AND c.violation != '' AND c.non_violation != '[]' AND c.non_violation != '' AND c.document_type NOT LIKE '%Press Release%')")
            elif oc == "neither":
                oc_conditions.append("((c.violation = '[]' OR c.violation = '' OR c.violation IS NULL) AND (c.non_violation = '[]' OR c.non_violation = '' OR c.non_violation IS NULL) AND c.document_type NOT LIKE '%Press Release%')")
            elif oc == "press_release":
                oc_conditions.append("(c.document_type LIKE '%Press Release%')")
        if oc_conditions:
            where_clauses.append(f"({' OR '.join(oc_conditions)})")

    if doc_type_list:
        dt_conditions = []
        for dt in doc_type_list:
            if dt == "press_release":
                dt_conditions.append("c.document_type LIKE '%Press Release%'")
            elif dt == "judgment":
                dt_conditions.append("c.document_type NOT LIKE '%Press Release%'")
            elif dt == "committee":
                dt_conditions.append("c.document_type LIKE '%Committee%'")
            elif dt == "grand_chamber":
                dt_conditions.append("c.originating_body LIKE '%Grand Chamber%'")
            elif dt == "chamber":
                dt_conditions.append(
                    "(c.document_type NOT LIKE '%Press Release%' "
                    "AND c.document_type NOT LIKE '%Committee%' "
                    "AND (c.originating_body IS NULL "
                    "OR c.originating_body NOT LIKE '%Grand Chamber%'))"
                )
        if dt_conditions:
            where_clauses.append(f"({' OR '.join(dt_conditions)})")

    if date_from:
        where_clauses.append("c.judgment_date >= ?")
        params.append(date_from)

    if date_to:
        where_clauses.append("c.judgment_date <= ?")
        params.append(date_to)

    where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
    join_sql = " ".join(joins)

    # judgment_date is DD/MM/YYYY; sort by an ISO YYYYMMDD key, not
    # by raw lex order (which would sort by DD first).
    date_sort_key = (
        "(substr(c.judgment_date,7,4) || "
        "substr(c.judgment_date,4,2) || "
        "substr(c.judgment_date,1,2))"
    )
    order_sql = f"{date_sort_key} DESC" if sort == "date_desc" else f"{date_sort_key} ASC"
    offset = (page - 1) * page_size

    try:
        with get_cursor() as cur:
            # Count.
            count_sql = (
                f"SELECT count(DISTINCT c.case_id) AS total "
                f"FROM cases c {join_sql}{where_sql}"
            )
            cur.execute(count_sql, params)
            total_cases = cur.fetchone()["total"]

            if total_cases == 0:
                elapsed = (time.perf_counter() - t0) * 1000
                return {
                    "total_cases": 0,
                    "total_hits": 0,
                    "page": page,
                    "page_size": page_size,
                    "search_time_ms": round(elapsed, 1),
                    "cases": [],
                }

            # Paginated case IDs.
            ids_sql = (
                f"SELECT DISTINCT c.case_id "
                f"FROM cases c {join_sql}{where_sql} "
                f"ORDER BY {order_sql} LIMIT ? OFFSET ?"
            )
            cur.execute(ids_sql, params + [page_size, offset])
            case_ids = [r["case_id"] for r in cur.fetchall()]

            if not case_ids:
                elapsed = (time.perf_counter() - t0) * 1000
                return {
                    "total_cases": total_cases,
                    "total_hits": 0,
                    "page": page,
                    "page_size": page_size,
                    "search_time_ms": round(elapsed, 1),
                    "cases": [],
                }

            # Case details.
            id_ph = ",".join("?" for _ in case_ids)
            cur.execute(
                "SELECT case_id, case_no, title, judgment_date, hudoc_url, "
                "respondent_state, importance, conclusion, violation, "
                "non_violation, violation_inferred, non_violation_inferred, keywords, originating_body, document_type "
                f"FROM cases WHERE case_id IN ({id_ph})",
                case_ids,
            )
            case_details = {r["case_id"]: _enrich_case_row(_row_to_dict(r)) for r in cur.fetchall()}

            # Articles per case.
            cur.execute(
                f"SELECT case_id, article FROM case_articles WHERE case_id IN ({id_ph})",
                case_ids,
            )
            case_articles_map: dict[str, list[str]] = {}
            for r in cur.fetchall():
                case_articles_map.setdefault(r["case_id"], []).append(r["article"])

            # Assemble — maintain ORDER.
            cases_out: list[dict[str, Any]] = []
            for cid in case_ids:
                detail = case_details.get(cid, {})
                cases_out.append({
                    **detail,
                    "articles": sorted(case_articles_map.get(cid, [])),
                    "hit_count": 0,
                    "score": 0,
                    "paragraphs": [],
                })

            elapsed = (time.perf_counter() - t0) * 1000
            return {
                "total_cases": total_cases,
                "total_hits": 0,
                "page": page,
                "page_size": page_size,
                "search_time_ms": round(elapsed, 1),
                "cases": cases_out,
            }
    except Exception as exc:
        logger.exception("Browse query failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Global exception handler
# ---------------------------------------------------------------------------

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


# ---------------------------------------------------------------------------
# Startup / shutdown
# ---------------------------------------------------------------------------

@app.on_event("startup")
async def startup():
    logger.info("Starting ECHR Search API — DB path: %s", DB_PATH)
    if not Path(DB_PATH).exists():
        logger.warning("Database file does not exist yet: %s", DB_PATH)
        return
    # Warm the connection pool for the main thread.
    try:
        with get_cursor() as cur:
            cur.execute("SELECT count(*) FROM cases")
            n = cur.fetchone()[0]
        logger.info("Database opened — %d cases loaded.", n)
    except Exception:
        logger.exception("Failed to open database on startup")


@app.on_event("shutdown")
async def shutdown():
    conn: sqlite3.Connection | None = getattr(_local, "conn", None)
    if conn is not None:
        conn.close()
        _local.conn = None
    logger.info("ECHR Search API shut down.")


# ---------------------------------------------------------------------------
# Dev entry-point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8000")),
        reload=True,
    )
