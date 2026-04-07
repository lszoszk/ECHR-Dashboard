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

# CORS — allow GitHub Pages production domain and local dev servers.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^(https://lszoszk\.github\.io|http://(localhost|127\.0\.0\.1)(:\d+)?)$",
    allow_methods=["GET"],
    allow_headers=["*"],
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


def _build_fts_query(raw: str) -> str:
    """
    Convert a user query string into an FTS5 MATCH expression.

    Strategy: split on whitespace, wrap each token in double-quotes for exact
    matching, join with AND.  If the user explicitly writes ``OR`` between
    tokens, honour that operator instead.
    """
    raw = raw.strip()
    if not raw:
        return ""

    # Split but keep OR as an operator.
    tokens = raw.split()
    parts: list[str] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok.upper() == "OR":
            # Replace last AND (implicit) with OR.
            if parts and parts[-1] == "AND":
                parts[-1] = "OR"
            i += 1
            continue
        # Strip characters that are special in FTS5 query syntax.
        clean = re.sub(r'["\'^*(){}:]+', "", tok).strip()
        if clean:
            parts.append(f'"{clean}"')
            parts.append("AND")
        i += 1

    # Remove trailing operator.
    if parts and parts[-1] in ("AND", "OR"):
        parts.pop()

    return " ".join(parts)


def _validate_page_size(page_size: int) -> int:
    return max(1, min(page_size, 100))


def _parse_comma_param(value: Optional[str]) -> list[str]:
    """Split a comma-separated query param into a trimmed list."""
    if not value:
        return []
    return [v.strip() for v in value.split(",") if v.strip()]


def _enrich_case_row(row: dict[str, Any]) -> dict[str, Any]:
    """Parse JSON text fields in a case row into native Python objects."""
    for field in ("conclusion", "violation", "non_violation", "keywords", "originating_body"):
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

        db_size_mb = 0.0
        try:
            db_size_mb = round(Path(DB_PATH).stat().st_size / (1024 * 1024), 2)
        except OSError:
            pass

        return {
            "total_cases": total_cases,
            "total_paragraphs": total_paragraphs,
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

            # Respondent states
            cur.execute(
                "SELECT respondent_state AS value, count(*) AS count "
                "FROM cases WHERE respondent_state IS NOT NULL "
                "GROUP BY respondent_state ORDER BY count DESC"
            )
            result["states"] = [_row_to_dict(r) for r in cur.fetchall()]

            # Importance
            cur.execute(
                "SELECT importance AS value, count(*) AS count "
                "FROM cases WHERE importance IS NOT NULL "
                "GROUP BY importance ORDER BY count DESC"
            )
            result["importance"] = [_row_to_dict(r) for r in cur.fetchall()]

            # Sections
            cur.execute(
                "SELECT section AS value, count(DISTINCT case_id) AS count "
                "FROM paragraphs WHERE section IS NOT NULL "
                "GROUP BY section ORDER BY count DESC"
            )
            result["sections"] = [_row_to_dict(r) for r in cur.fetchall()]

            # Date range
            cur.execute(
                "SELECT min(judgment_date) AS min, max(judgment_date) AS max FROM cases"
            )
            date_row = cur.fetchone()
            result["date_range"] = {"min": date_row["min"], "max": date_row["max"]}

        return result
    except Exception as exc:
        logger.exception("Facets query failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ---- /api/search -----------------------------------------------------------

@app.get("/api/search")
def search(
    q: str = Query(..., min_length=1, description="Full-text search query"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    sections: Optional[str] = Query(None, description="Comma-separated section filter"),
    articles: Optional[str] = Query(None, description="Comma-separated article filter"),
    states: Optional[str] = Query(None, description="Comma-separated respondent_state filter"),
    importance: Optional[str] = Query(None, description="Comma-separated importance filter"),
    date_from: Optional[str] = Query(None, description="Earliest judgment_date (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="Latest judgment_date (YYYY-MM-DD)"),
    sort: str = Query("relevance", pattern="^(relevance|date_desc|date_asc)$"),
):
    """Full-text search across case paragraphs using FTS5."""
    t0 = time.perf_counter()
    page_size = _validate_page_size(page_size)
    fts_expr = _build_fts_query(q)
    if not fts_expr:
        raise HTTPException(status_code=400, detail="Empty search query after sanitisation.")

    sec_list = _parse_comma_param(sections)
    art_list = _parse_comma_param(articles)
    state_list = _parse_comma_param(states)
    imp_list = _parse_comma_param(importance)

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
        placeholders = ",".join("?" for _ in state_list)
        where_clauses.append(f"c.respondent_state IN ({placeholders})")
        params.extend(state_list)

    if imp_list:
        placeholders = ",".join("?" for _ in imp_list)
        where_clauses.append(f"c.importance IN ({placeholders})")
        params.extend(imp_list)

    if date_from:
        where_clauses.append("c.judgment_date >= ?")
        params.append(date_from)

    if date_to:
        where_clauses.append("c.judgment_date <= ?")
        params.append(date_to)

    where_sql = " AND ".join(where_clauses)
    join_sql = " ".join(joins)

    # Determine sort clause at the case-group level.
    if sort == "date_desc":
        order_sql = "c.judgment_date DESC"
    elif sort == "date_asc":
        order_sql = "c.judgment_date ASC"
    else:
        order_sql = "score ASC"  # lower bm25 = better in FTS5; using alias from SELECT

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
            # Step 2: Get paginated case IDs.
            # ----------------------------------------------------------
            offset = (page - 1) * page_size

            case_ids_sql = (
                "SELECT c.case_id, min(pf.rank) AS score, "
                "count(*) AS hit_count "
                "FROM paragraphs_fts pf "
                "JOIN paragraphs p ON p.rowid = pf.rowid "
                "JOIN cases c ON c.case_id = p.case_id "
                f"{join_sql} "
                f"WHERE {where_sql} "
                "GROUP BY c.case_id "
                f"ORDER BY {order_sql} "
                "LIMIT ? OFFSET ?"
            )
            cur.execute(case_ids_sql, params + [page_size, offset])
            case_rows = cur.fetchall()
            case_ids = [r["case_id"] for r in case_rows]
            case_meta = {r["case_id"]: {"score": r["score"], "hit_count": r["hit_count"]} for r in case_rows}

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
                "non_violation, keywords, originating_body "
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

            snippet_sql = (
                "SELECT p.case_id, p.section, p.para_idx, "
                "snippet(paragraphs_fts, 0, '<b>', '</b>', '...', 80) AS snippet, "
                "bm25(paragraphs_fts) AS para_score "
                "FROM paragraphs_fts pf "
                "JOIN paragraphs p ON p.rowid = pf.rowid "
                f"WHERE pf.paragraphs_fts MATCH ? {sec_where} "
                f"AND p.case_id IN (SELECT value FROM json_each(?) ) "
                f"ORDER BY bm25(paragraphs_fts)"
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
                "non_violation, keywords, originating_body "
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

            # All paragraphs
            cur.execute(
                "SELECT section, para_idx, text "
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
        placeholders = ",".join("?" for _ in state_list)
        where_clauses.append(f"c.respondent_state IN ({placeholders})")
        params.extend(state_list)

    if imp_list:
        placeholders = ",".join("?" for _ in imp_list)
        where_clauses.append(f"c.importance IN ({placeholders})")
        params.extend(imp_list)

    if date_from:
        where_clauses.append("c.judgment_date >= ?")
        params.append(date_from)

    if date_to:
        where_clauses.append("c.judgment_date <= ?")
        params.append(date_to)

    where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
    join_sql = " ".join(joins)

    order_sql = "c.judgment_date DESC" if sort == "date_desc" else "c.judgment_date ASC"
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
                "non_violation, keywords, originating_body "
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
