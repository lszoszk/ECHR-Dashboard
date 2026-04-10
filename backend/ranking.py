"""
Ranking & re-ranking helpers for the ECHR search API.

This module centralises every tunable parameter that influences the
ordering of search results, so that ranking behaviour can be reviewed,
unit-tested, and adjusted without touching the SQL layer in ``main.py``.

Two layers of ranking are used in ``/api/search``:

1. **SQL layer (BM25F → MAX-dominated aggregate)** — ``paragraphs_fts``
   is a multi-column FTS5 index over ``(title, keywords_text, text)``
   with column weights persisted via ``INSERT INTO paragraphs_fts
   (paragraphs_fts, rank) VALUES ('rank', 'bm25(5.0, 3.0, 1.0)')``
   inside ``build_db.py``.  The constants ``BM25_WEIGHT_TITLE``,
   ``BM25_WEIGHT_KEYWORDS``, ``BM25_WEIGHT_BODY`` defined here are the
   single source of truth and must stay in sync with that rank config.

   Because the weights are stored on the FTS5 table, the hidden
   ``pf.rank`` column exposes the pre-weighted BM25F score for each
   matching row and is aggregatable without materialisation (avoids
   the "unable to use function bm25 in the requested context" error).

   The per-case aggregate is a **max-dominated** formula:

       relevance_score = max(-pf.rank) * (1 + 0.3 * ln(1 + hit_count))

   * ``max(-pf.rank)`` is the strongest single-paragraph hit — the
     most distinctive match (typically the metadata row when the
     query appears in the case title).
   * ``(1 + 0.3 * ln(1 + hit_count))`` is a gentle density bonus so
     a case with several matches slightly outranks one lucky hit.

   Why not raw ``sum(-pf.rank)``?  Pilot A/B on golden queries showed
   severe long-judgment bias — e.g. "torture" placed an 1800-paragraph
   mega inter-state case above Ireland v. UK, and "Hirst" placed HORA
   (which cites Hirst 59x) above HIRST v. UK itself (which only
   mentions its own name 3x).  max*ln damps the "long-document wins"
   pathology while still rewarding topical density.

2. **Python layer (metadata boosts)** — on page 1 of a relevance sort,
   the endpoint fetches a slightly larger candidate pool and passes it
   through :func:`rerank_candidates`, which applies multiplicative
   boosts based on case importance, the originating body (Grand Chamber
   carries more precedential weight than a Committee), and document
   type (press releases are demoted relative to judgments).  The input
   score to this layer is ``relevance_score`` (the SQL max*ln value),
   passed via the ``sum_bm25`` candidate key for historical reasons.

Why multiplicative metadata boosts, not additive?  The raw score
magnitude varies by an order of magnitude across queries (one rare
token vs several common tokens), so additive boosts would need
per-query normalisation.  Multiplicative boosts are scale-invariant
and compose cleanly.

All constants in this module are intentionally conservative first
guesses.  Expect one round of tuning after the golden-query A/B.
"""

from __future__ import annotations

import json
from typing import Any, Iterable


# ---------------------------------------------------------------------------
# BM25F column weights — the single source of truth.
# ---------------------------------------------------------------------------
# Referenced from main.py via the literal numbers in the SQL strings
# (SQLite doesn't allow parameterised bm25 weights).  If you change any
# of these, update the corresponding literals in main.py::search().
# ---------------------------------------------------------------------------

BM25_WEIGHT_TITLE: float = 5.0
BM25_WEIGHT_KEYWORDS: float = 3.0
BM25_WEIGHT_BODY: float = 1.0


# ---------------------------------------------------------------------------
# Metadata multiplicative boosts.
# ---------------------------------------------------------------------------

#: HUDOC ``importance`` field → multiplicative boost.
#: 1 / "Key cases" = highest precedential value in HUDOC taxonomy.
#: Two label conventions coexist in the underlying HUDOC metadata: the
#: numeric codes ("1"–"4") and the human-readable "Key cases" tag which
#: HUDOC applies to the highest-importance subset.  Both surface in our
#: ``cases.importance`` column, so we map them equivalently here.
#: Lookup is case-insensitive; unknown / missing values fall through to
#: ``IMPORTANCE_DEFAULT_BOOST``.
IMPORTANCE_BOOST: dict[str, float] = {
    "1": 1.40,
    "key cases": 1.40,
    "2": 1.15,
    "3": 1.00,
    "4": 0.90,
}
IMPORTANCE_DEFAULT_BOOST: float = 1.00

#: Substring → multiplicative boost for ``originating_body``.
#: Matched case-insensitively via substring test, so
#: ``"Court (Grand Chamber)"`` matches the ``"Grand Chamber"`` key.
#: Order matters only for overlap edge cases — we iterate the dict
#: and pick the first matching key, so put more-specific keys first.
BODY_BOOST: dict[str, float] = {
    "Grand Chamber": 1.25,
    "Committee":     0.85,
    "Chamber":       1.00,
}
BODY_DEFAULT_BOOST: float = 1.00

#: Document-type boost.  Press releases remain searchable and are still
#: returned, but they're demoted so that substantive-law searches don't
#: get drowned in press coverage.  Apply detection via substring match
#: (mirrors the pattern used elsewhere in ``main.py``).
DOC_TYPE_BOOST_PRESS_RELEASE: float = 0.75
DOC_TYPE_BOOST_JUDGMENT: float = 1.00


# ---------------------------------------------------------------------------
# Rerank scope
# ---------------------------------------------------------------------------
#
# As of the ranking-consistency fix (April 2026), the rerank pass applies
# to **every case that matches the FTS query**, not just an over-fetched
# candidate pool.  The previous candidate-pool approach broke whenever a
# high-boost case (e.g. imp=1 Grand Chamber, ×1.75) had a pre-boost score
# low enough to fall outside a small ``page_size × 3`` window — it would
# simply never get a chance to climb.  Reranking the full match set is
# the only way to make the page-1 (and indeed every-page) ordering
# invariant under ``page_size`` changes.
#
# Scaling note: even broad queries ("article", "torture") return at most
# a few thousand matching cases; the total corpus is ~18k cases, so the
# absolute worst case is an ~18k-row Python sort.  timsort on a list of
# ~20k small dicts runs in single-digit milliseconds — negligible next
# to SQLite FTS5 latency, and cheaper than the old over-fetch +
# metadata round-trip.
#
# Date sorts still skip rerank entirely — they are deterministic by
# definition and must never be touched by boosts.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def should_rerank(sort: str) -> bool:
    """Return True iff metadata re-ranking should run for this request.

    Only relevance sorts are reranked.  Date sorts are deterministic by
    definition and must never be touched by boosts.

    Unlike the previous implementation, this function no longer takes a
    ``page`` argument: reranking applies uniformly to every page of a
    relevance sort so that pagination is stable (page 2 of a reranked
    result set is still the rerank-ordered continuation of page 1).
    """
    return sort == "relevance"


def _resolve_body_boost(originating_body: Any) -> float:
    """Substring-match the (possibly JSON-encoded list) body field against
    ``BODY_BOOST`` and return the first matching value, or the default.
    """
    if not originating_body:
        return BODY_DEFAULT_BOOST

    # ``cases.originating_body`` is sometimes a plain string ("Court (Chamber)")
    # and sometimes a JSON-encoded list.  Be defensive.
    if isinstance(originating_body, list):
        items = originating_body
    elif isinstance(originating_body, str):
        stripped = originating_body.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            try:
                parsed = json.loads(stripped)
                items = parsed if isinstance(parsed, list) else [stripped]
            except json.JSONDecodeError:
                items = [stripped]
        else:
            items = [stripped]
    else:
        items = [str(originating_body)]

    haystack = " ".join(str(x) for x in items).lower()
    if not haystack:
        return BODY_DEFAULT_BOOST

    for key, boost in BODY_BOOST.items():
        if key.lower() in haystack:
            return boost
    return BODY_DEFAULT_BOOST


def _resolve_importance_boost(importance: Any) -> float:
    if importance is None:
        return IMPORTANCE_DEFAULT_BOOST
    # Case-insensitive: HUDOC ships both "1" and "Key cases" forms,
    # and we want operators to be able to write the boost keys in any
    # casing without silently dropping to the default.
    key = str(importance).strip().lower()
    if not key:
        return IMPORTANCE_DEFAULT_BOOST
    return IMPORTANCE_BOOST.get(key, IMPORTANCE_DEFAULT_BOOST)


def _resolve_doc_type_boost(document_type: Any) -> float:
    if not document_type:
        return DOC_TYPE_BOOST_JUDGMENT
    if "press release" in str(document_type).lower():
        return DOC_TYPE_BOOST_PRESS_RELEASE
    return DOC_TYPE_BOOST_JUDGMENT


def compute_final_score(
    sum_bm25: float | None,
    *,
    importance: Any = None,
    originating_body: Any = None,
    document_type: Any = None,
) -> float:
    """Apply multiplicative metadata boosts to ``sum_bm25``.

    Returns ``0.0`` for missing / non-positive base scores (defensive —
    a candidate without a base score has nothing to rank on).
    """
    if sum_bm25 is None:
        return 0.0
    try:
        base = float(sum_bm25)
    except (TypeError, ValueError):
        return 0.0
    if base <= 0:
        return 0.0

    imp_mult = _resolve_importance_boost(importance)
    body_mult = _resolve_body_boost(originating_body)
    doc_mult = _resolve_doc_type_boost(document_type)

    return base * imp_mult * body_mult * doc_mult


def rerank_candidates(candidates: Iterable[dict]) -> list[dict]:
    """Sort ``candidates`` by their computed final score.

    Each candidate dict is expected to carry at minimum::

        {
            "case_id": str,
            "sum_bm25": float,
            "importance": str | None,
            "originating_body": str | list | None,
            "document_type": str | None,
        }

    A ``final_score`` key is attached to each returned dict so the
    caller can inspect / log the post-boost score.  Returns a new list
    (does not mutate the input order) containing **every** candidate —
    callers are responsible for their own pagination/slicing.
    """
    scored: list[dict] = []
    for cand in candidates:
        final = compute_final_score(
            cand.get("sum_bm25"),
            importance=cand.get("importance"),
            originating_body=cand.get("originating_body"),
            document_type=cand.get("document_type"),
        )
        enriched = dict(cand)
        enriched["final_score"] = final
        scored.append(enriched)

    scored.sort(key=lambda c: c["final_score"], reverse=True)
    return scored
