#!/usr/bin/env python3
"""P38 batch enrichment — run the triangulation scorer across every case
in the corpus and emit a TSV that can be applied to the VM database as
extra columns on the `paragraphs` table.

Pipeline shape:
    (local) DOCX cache + HTML cache  ──►  this script  ──►  TSV
    TSV  ──►  scp to VM  ──►  apply UPDATE per row  ──►  augmented DB

Output TSV (tab-separated, no header by default — sqlite `.import` friendly):

    case_id  block_idx  text_hash  text_first_60  role_top  role_score  confidence_band

Where:
  - block_idx       = 0-based visible-paragraph index in DOCX iteration
                      (same order P37 emits, so para_idx aligns when stable)
  - text_hash       = sha1(normalize(text))[:16]  — 16 hex chars; primary
                      join key on VM side, immune to para_idx drift
  - text_first_60   = first 60 chars of original text — debugging only,
                      never used as join key
  - role_top        = highest-scoring role from p38_triangulation_scorer
  - role_score      = float, top score from scorer
  - confidence_band = "high" / "medium" / "low" (or "unknown" when role itself
                       is unknown)

Resume-capable: re-running with the same --out skips cases whose case_id
already appears in the output.

Parallelism: ThreadPoolExecutor — DOCX parse + HTML parse are I/O-heavy
(reading + BeautifulSoup); the scorer itself is pure-Python and benefits
modestly from threads.  Default 4 workers.

Usage:
    python3 scripts/p38_batch_enrich.py \\
        --jsonl /tmp/echr_cases.v37.jsonl \\
        --out   /tmp/p38_enrichment.tsv

    # Or restrict to a custom case list (one cid per line):
    python3 scripts/p38_batch_enrich.py \\
        --case-list /tmp/panel10.txt \\
        --out /tmp/p38_panel10.tsv \\
        --verbose
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

# Re-use the scorer machinery directly — no duplication of feature logic.
from p38_triangulation_scorer import (  # type: ignore
    DOCX_DIR,
    HTML_DIR,
    extract_docx_features,
    merge_html_features,
    populate_sequence,
    classify_block,
)


HEADER = "case_id\tblock_idx\ttext_hash\ttext_first_60\trole_top\trole_score\tconfidence_band\n"
WHITESPACE_RE = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    """Whitespace-collapsed, lowercased text — same normalization used to
    compute the join hash on both sides (this script + VM apply step)."""
    return WHITESPACE_RE.sub(" ", (text or "").strip()).lower()


def hash_text(text: str) -> str:
    """16-hex-char sha1 of normalized text.  Stable across runs and
    architectures.  Collisions: 2^64 space → astronomically safe for 3.5M
    rows, even per-case."""
    norm = normalize_text(text)
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()[:16]


def enrich_case(cid: str) -> tuple[str, list[tuple], str]:
    """Score every visible block in case `cid` and return a list of
    output rows.  Status string explains skips/errors.

    Returns (cid, rows, status).  Rows are tuples ready for tab-join.
    """
    docx_path = DOCX_DIR / f"{cid}.docx"
    html_path = HTML_DIR / f"{cid}.html"

    if not docx_path.exists():
        return cid, [], "no_docx"

    try:
        blocks = extract_docx_features(docx_path)
    except Exception as e:
        return cid, [], f"docx_parse_error:{type(e).__name__}"

    if not blocks:
        return cid, [], "empty_docx"

    if html_path.exists():
        try:
            merge_html_features(blocks, html_path)
        except Exception:
            # HTML merge failure is non-fatal — scorer still works with
            # DOCX-only signal, just at lower confidence for some rows.
            pass

    populate_sequence(blocks)

    rows: list[tuple] = []
    for idx, b in enumerate(blocks):
        if not b.text or not b.text.strip():
            continue
        c = classify_block(b)
        rows.append((
            cid,
            idx,
            hash_text(b.text),
            (b.text or "")[:60].replace("\t", " ").replace("\n", " "),
            c.role,
            f"{c.score:.2f}",
            c.confidence,
        ))
    return cid, rows, "ok"


def load_case_ids(jsonl: Path | None, case_list: Path | None) -> list[str]:
    if case_list:
        return [
            line.strip()
            for line in case_list.open(encoding="utf-8")
            if line.strip() and not line.startswith("#")
        ]
    if not jsonl:
        raise SystemExit("must supply --jsonl or --case-list")
    cids = []
    with jsonl.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            cid = obj.get("case_id") or obj.get("cid")
            if cid:
                cids.append(cid)
    return cids


def already_processed(out_path: Path) -> set[str]:
    """One-pass scan of an existing output file for case_id column;
    so we can skip them on resume."""
    if not out_path.exists():
        return set()
    seen: set[str] = set()
    with out_path.open(encoding="utf-8") as f:
        for line in f:
            if not line or line.startswith("#") or line.startswith("case_id"):
                continue
            cid = line.split("\t", 1)[0].strip()
            if cid:
                seen.add(cid)
    return seen


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--jsonl", type=Path,
                    help="JSONL of cases (e.g. echr_cases.v37.jsonl)")
    ap.add_argument("--case-list", type=Path,
                    help="Plain-text list of case_ids, one per line")
    ap.add_argument("--out", type=Path, required=True,
                    help="Output TSV path")
    ap.add_argument("--workers", type=int, default=4,
                    help="ThreadPoolExecutor size (default: 4)")
    ap.add_argument("--no-header", action="store_true",
                    help="Skip writing the column-header line (handy for "
                         "direct sqlite `.import`)")
    ap.add_argument("--resume", action="store_true",
                    help="Skip case_ids already present in --out")
    ap.add_argument("--limit", type=int, default=0,
                    help="Process at most N cases (0 = all). For smoke tests.")
    ap.add_argument("--verbose", action="store_true",
                    help="Per-case progress detail to stderr")
    args = ap.parse_args()

    if not args.jsonl and not args.case_list:
        ap.error("supply --jsonl or --case-list")

    cids = load_case_ids(args.jsonl, args.case_list)
    if args.limit:
        cids = cids[:args.limit]

    skip: set[str] = set()
    if args.resume:
        skip = already_processed(args.out)
        if skip:
            print(f"resume: skipping {len(skip):,} already-processed cases",
                  file=sys.stderr)

    pending = [c for c in cids if c not in skip]
    print(f"to enrich: {len(pending):,}  workers={args.workers}", file=sys.stderr)

    # Append mode if resuming, else truncate.
    mode = "a" if (args.resume and args.out.exists()) else "w"
    args.out.parent.mkdir(parents=True, exist_ok=True)
    f = args.out.open(mode, encoding="utf-8", newline="")
    if mode == "w" and not args.no_header:
        f.write(HEADER)

    lock = Lock()
    start = time.time()
    n_ok = n_skip = n_err = 0
    total_rows = 0
    status_counts: dict[str, int] = {}
    by_role: dict[str, int] = {}
    by_band: dict[str, int] = {}

    def write_rows(cid: str, rows: list[tuple], status: str):
        nonlocal n_ok, n_skip, n_err, total_rows
        with lock:
            status_counts[status] = status_counts.get(status, 0) + 1
            if status != "ok":
                if status.startswith("docx_parse_error") or status == "no_docx":
                    n_err += 1
                else:
                    n_skip += 1
                if args.verbose:
                    print(f"  [{status}] {cid}", file=sys.stderr)
                return
            n_ok += 1
            for row in rows:
                f.write("\t".join(str(x) for x in row) + "\n")
                by_role[row[4]] = by_role.get(row[4], 0) + 1
                by_band[row[6]] = by_band.get(row[6], 0) + 1
            total_rows += len(rows)
            if args.verbose:
                print(f"  ok  {cid}  rows={len(rows)}", file=sys.stderr)

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(enrich_case, c): c for c in pending}
        done = 0
        for fut in as_completed(futs):
            cid, rows, status = fut.result()
            write_rows(cid, rows, status)
            done += 1
            if done % 100 == 0 or done == len(pending):
                elapsed = time.time() - start
                rate = done / elapsed if elapsed else 0
                eta = (len(pending) - done) / rate / 60 if rate else 0
                print(
                    f"  {done:,}/{len(pending):,}  ok={n_ok:,} skip={n_skip:,} "
                    f"err={n_err:,}  rows={total_rows:,}  rate={rate:.1f}/s  "
                    f"eta={eta:.1f}m",
                    file=sys.stderr,
                )
                f.flush()

    f.close()

    elapsed = time.time() - start
    print(f"\ndone in {elapsed/60:.1f} min", file=sys.stderr)
    print(f"  cases  ok={n_ok:,} skip={n_skip:,} err={n_err:,}", file=sys.stderr)
    print(f"  rows   total={total_rows:,}", file=sys.stderr)
    print(f"  output {args.out}", file=sys.stderr)
    if status_counts:
        print(f"  statuses: {dict(sorted(status_counts.items()))}", file=sys.stderr)
    if by_role:
        print(f"  by_role:  {dict(sorted(by_role.items(), key=lambda kv: -kv[1]))}",
              file=sys.stderr)
    if by_band:
        print(f"  by_band:  {dict(sorted(by_band.items(), key=lambda kv: -kv[1]))}",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
