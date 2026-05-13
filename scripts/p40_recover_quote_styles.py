"""Recover ``row_role='quote'`` for paragraphs styled ECHR_Para_Quote
(old template) or Ju_Quot (new template) but mis-tagged ``paragraph``
in the DB.

Background
----------
Before commit 4d41772 the parser did NOT know about the old
``ECHR_Para_Quote`` style — every quoted blockquote dropped into
``classify_style`` → ``"normal"`` and ended up rendered as a body
paragraph (no italic, no left border).  The fix landed in
``p34_rebuild_from_hudoc.py`` but P34 was not re-run over the full
corpus afterwards, only the headings TSV refresh + apply (which only
touches ``row_role`` for headings).

So in production the DB still carries ~tens of thousands of quotes
mis-tagged as ``paragraph`` — visible e.g. in GAUGHRAN's ¶ 51
recital of Council of Europe Recommendation R(87) 15, where every
"Principle N – …" line renders as a numbered body paragraph instead
of an indented italic quote.

Strategy
--------
1.  Walk ``~/Desktop/HUDOC-Docx`` (local cache, 19.7k DOCX files).
2.  For every visible paragraph whose style is ``ECHR_Para_Quote`` or
    ``Ju_Quot``, emit ``(case_id, text_hash)`` to TSV.
3.  On the VM, JOIN against ``paragraphs`` on
    ``(case_id, text_hash)`` and update rows currently marked
    ``row_role='paragraph'`` and ``numbering_block IN ('main_judgment',
    NULL)`` to ``row_role='quote'``.

Hash recipe matches ``apply_extract.py`` exactly: sha1 of normalised
text (whitespace collapsed, lower-cased), first 16 hex chars.  This
keeps the join stable even when the text was rewritten by earlier
recovery passes (since the same recipe is used everywhere).

Output TSV columns: ``case_id\tquote_hash\ttext_first_60``.

Usage
-----
::

    # Local: generate the TSV (uses ProcessPool, ~5 min for full corpus)
    python3 scripts/p40_recover_quote_styles.py \\
        --out /tmp/quote_recovery.tsv --workers 8

    # VM: apply the updates
    scp /tmp/quote_recovery.tsv amuvmuser@150.254.115.204:/tmp/
    ssh amuvmuser@150.254.115.204 \\
        'docker exec echr-api python3 -c "..."'   # or via apply helper
"""
from __future__ import annotations

import argparse
import hashlib
import io
import re
import sys
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed

_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS))

from docx import Document  # type: ignore  # noqa: E402
from p34_rebuild_from_hudoc import (  # noqa: E402
    iter_visible_paragraphs,
    para_text_full,
    is_legacy_word_doc,
    convert_legacy_word_to_docx,
    is_docx_zip,
)

DOCX_DIR = Path.home() / "Desktop" / "HUDOC-Docx"
WHITESPACE_RE = re.compile(r"\s+")

# Styles that map to "quote" in the parser.  Stay in sync with
# ``p34_rebuild_from_hudoc.classify_style``.
QUOTE_STYLES = frozenset({"ECHR_Para_Quote", "Ju_Quot"})


def hash_text(text: str) -> str:
    """Stable text identifier — matches ``apply_extract.hash_text``."""
    norm = WHITESPACE_RE.sub(" ", (text or "").strip()).lower()
    if not norm:
        return ""
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()[:16]


def extract_quote_rows(cid: str) -> list[tuple[str, str, str]]:
    """Return [(case_id, hash, first_60), …] for every ECHR_Para_Quote /
    Ju_Quot paragraph in the case's DOCX.  Empty list if file missing."""
    path = DOCX_DIR / f"{cid}.docx"
    if not path.exists():
        return []
    blob = path.read_bytes()
    if is_legacy_word_doc(blob):
        try:
            blob = convert_legacy_word_to_docx(blob)
        except Exception:
            return []
    if not is_docx_zip(blob):
        return []
    try:
        doc = Document(io.BytesIO(blob))
    except Exception:
        return []

    out: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for p, _in_table in iter_visible_paragraphs(doc):
        style = p.style.name if p.style else ""
        if style not in QUOTE_STYLES:
            continue
        text = (para_text_full(p) or "").strip()
        if not text:
            continue
        h = hash_text(text)
        if not h or h in seen:
            continue
        seen.add(h)
        out.append((cid, h, text[:60]))
    return out


def _worker(cid: str) -> tuple[str, list[tuple[str, str, str]], str | None]:
    try:
        return cid, extract_quote_rows(cid), None
    except Exception as e:
        return cid, [], str(e)[:80]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--out",
        type=Path,
        default=Path("/tmp/quote_recovery.tsv"),
    )
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument(
        "--list",
        type=Path,
        default=None,
        help="Optional list of case_ids (one per line); default = all "
        "files in DOCX cache.",
    )
    args = ap.parse_args()

    if args.list is not None:
        cids = [line.strip() for line in args.list.open() if line.strip()]
    else:
        cids = sorted(p.stem for p in DOCX_DIR.glob("*.docx"))

    print(
        f"# scanning {len(cids):,} cases for ECHR_Para_Quote / Ju_Quot "
        f"with {args.workers} workers",
        file=sys.stderr,
    )

    n_ok = n_err = 0
    n_quote_rows = 0
    with args.out.open("w") as f:
        f.write("case_id\tquote_hash\ttext_first_60\n")
        with ProcessPoolExecutor(max_workers=args.workers) as ex:
            futures = [ex.submit(_worker, c) for c in cids]
            for i, fut in enumerate(as_completed(futures), 1):
                cid, rows, err = fut.result()
                if err:
                    n_err += 1
                else:
                    n_ok += 1
                    for cid_, h, t in rows:
                        # Replace tabs/newlines in preview so the TSV
                        # stays single-line per row.
                        preview = t.replace("\t", " ").replace("\n", " ")
                        f.write(f"{cid_}\t{h}\t{preview}\n")
                        n_quote_rows += 1
                if i % 1000 == 0:
                    print(
                        f"  {i}/{len(cids):,}  cases ok={n_ok} err={n_err}  "
                        f"quote rows so far={n_quote_rows:,}",
                        file=sys.stderr,
                        flush=True,
                    )
    print(
        f"\nwrote {args.out}  cases ok={n_ok} err={n_err}  "
        f"total quote rows={n_quote_rows:,}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
