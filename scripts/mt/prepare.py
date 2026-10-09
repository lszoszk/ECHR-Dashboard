#!/usr/bin/env python3
"""
Cut French judgments into translation jobs (one JSON file per chunk of consecutive rows).

Sources of French text, one of:
  --codex-dir DIR     Codex's download folder (DIR/parsed/<english id>.json), the default for production;
  --hudoc             fetch and parse from HUDOC: ids are "<english id>:<french id>" (or a French id);
  --test N            the first N held-out judgments of the parallel corpus (French side), for evaluation;
                      the official English rows are written to <out>/<id>/reference.json.

Each job holds the rows to translate, the French paragraph before the chunk, the glossary terms that
occur in the chunk and up to 3 example paragraphs (French + official English) retrieved from the
translation memory (parallel corpus, held-out judgments excluded).

    python3 scripts/mt/prepare.py --codex-dir DIR --ids ids.json --parallel mt/parallel.sqlite \
            --glossary mt/glossary.json --out mt/jobs
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

MAX_ROWS, MAX_CHARS = 10, 5000
WORD = re.compile(r"[A-Za-zÀ-ÿ]{6,}")


def chunks(rows):
    cur, size = [], 0
    for r in rows:
        n = len(r["fr"])
        if cur and (len(cur) >= MAX_ROWS or size + n > MAX_CHARS):
            yield cur
            cur, size = [], 0
        cur.append(r)
        size += n
    if cur:
        yield cur


def examples(tm, text, exclude, k=3):
    words = sorted(set(w.lower() for w in WORD.findall(text)), key=len, reverse=True)[:14]
    if not words:
        return []
    q = " OR ".join(f'"{w}"' for w in words)
    rows = tm.execute(
        "SELECT p.fr, p.en FROM pairs_fts f JOIN pairs p ON p.rowid = f.rowid JOIN docs d ON d.en_id = p.en_id "
        "WHERE pairs_fts MATCH ? AND d.split = 'tm' AND p.en_id != ? AND length(p.fr) BETWEEN 120 AND 1500 "
        "ORDER BY bm25(pairs_fts) LIMIT ?", (q, exclude, k)).fetchall()
    return [{"fr": f, "en": e} for f, e in rows]


def write_jobs(out: Path, case: dict, rows: list[dict], tm, glossary: dict) -> int:
    d = out / case["id"]
    d.mkdir(parents=True, exist_ok=True)
    rows = [r for r in rows if (r.get("fr") or "").strip()]
    prev, n = "", 0
    for i, ch in enumerate(chunks(rows)):
        text = " ".join(r["fr"] for r in ch)
        low = text.lower().replace("’", "'")
        job = {
            "case": case, "chunk": i, "context_before": prev[-1200:],
            "rows": ch,
            "glossary": {fr: en for fr, en in glossary.items() if fr.lower() in low},
            "examples": examples(tm, text, case.get("en_id", case["id"])),
        }
        (d / f"chunk_{i:03d}.json").write_text(json.dumps(job, ensure_ascii=False, indent=1))
        prev = ch[-1]["fr"]
        n += 1
    return n


def rows_from(parsed_rows):
    out = []
    for k, r in enumerate(parsed_rows):
        out.append({"id": f"r{k:04d}", "section": r.get("section"), "role": r.get("row_role"),
                    "para_no": r.get("hudoc_para_no"), "fr": (r.get("text") or "").strip()})
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--codex-dir")
    src.add_argument("--hudoc", action="store_true")
    src.add_argument("--test", type=int)
    ap.add_argument("--ids", help="JSON list of ids (not needed with --test)")
    ap.add_argument("--parallel", required=True)
    ap.add_argument("--glossary", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    tm = sqlite3.connect(f"file:{args.parallel}?mode=ro", uri=True)
    glossary = json.loads(Path(args.glossary).read_text())["terms"]
    out = Path(args.out)
    total = 0
    if args.test:
        docs = tm.execute("SELECT en_id, fr_id, title FROM docs WHERE split = 'test' AND aligned > 20 "
                          "ORDER BY en_id LIMIT ?", (args.test,)).fetchall()
        for en_id, fr_id, title in docs:
            pairs = tm.execute("SELECT para_key, section, row_role, fr, en FROM pairs WHERE en_id = ? "
                               "ORDER BY CAST(substr(para_key, 2) AS INTEGER)", (en_id,)).fetchall()
            rows = [{"id": k, "section": s, "role": r, "para_no": None, "fr": f} for k, s, r, f, _ in pairs]
            case = {"id": en_id, "en_id": en_id, "source_id": fr_id, "title": title}
            total += write_jobs(out, case, rows, tm, glossary)
            (out / en_id / "reference.json").write_text(json.dumps({k: e for k, _, _, _, e in pairs}, ensure_ascii=False))
    else:
        ids = json.loads(Path(args.ids).read_text())
        if args.hudoc:
            os.environ.setdefault("P34_FETCH_DELAY", "0.4")
            import p60_monthly_update as p60
            p34 = p60._load_module(p60.P34_PATH, "p34_rebuild_from_hudoc")
        for item in ids:
            en_id, _, fr_id = item.partition(":")
            if args.codex_dir:
                data = json.loads((Path(args.codex_dir) / "parsed" / f"{en_id}.json").read_text())
                parsed, fr_id = data["paragraphs"], data.get("source_case_id") or en_id
                title = (data.get("official_metadata") or {}).get("docname", "")
            else:
                fr_id = fr_id or en_id
                parsed, _ = p34.parse_docx(p34.fetch_docx(fr_id))
                title = ""
            case = {"id": en_id, "en_id": en_id, "source_id": fr_id, "title": title}
            total += write_jobs(out, case, rows_from(parsed), tm, glossary)
    print(f"wrote {total} job files under {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
