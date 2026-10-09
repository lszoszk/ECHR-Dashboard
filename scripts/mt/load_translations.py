#!/usr/bin/env python3
"""
Load machine-translated judgments into the search database (cases + paragraphs), marked as such.

For every judgment folder under --jobs: the English rows are merged from the translation tags (first tag
that has a row wins, so repair tags go first), the structure of each row (section, paragraph number,
role, ...) comes from the French source rows downloaded by the reconciliation worker (--codex-dir), and
the case metadata from HUDOC's catalogue record of the judgment, mapped exactly as the monthly update maps
it (p60.map_metadata / emit_case). A row without a translation keeps its French text.

The cases get text_origin = 'machine_translation', source_case_id (the French HUDOC item, the authentic
text) and source_language 'FRE'. The API leaves them out unless a search asks for them (include_mt) or names
the document. Paragraphs still doubtful after the repair (Jev below --review-threshold, a deterministic
check, or no translation) are listed in mt_review for a person to check.

    python3 scripts/mt/load_translations.py --jobs mt/jobs_t1 --suffix fix_ab,fix_c,t1a,t1b,t1c \\
        --codex-dir output/hudoc-reconciliation/missing-judgments --cache mt/jev_t1.jsonl \\
        --sql-out mt/load_t1.sql [--apply local.db]
The SQL needs the three cases columns and the mt_review table: --apply adds them; SCHEMA below for others.
Rollback: <sql-out>.rollback deletes the loaded judgments.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import judge  # noqa: E402
from assemble import merged_translation  # noqa: E402

SCHEMA = [
    ("cases", "text_origin", "ALTER TABLE cases ADD COLUMN text_origin TEXT"),
    ("cases", "source_case_id", "ALTER TABLE cases ADD COLUMN source_case_id TEXT"),
    ("cases", "source_language", "ALTER TABLE cases ADD COLUMN source_language TEXT"),
]
REVIEW_TABLE = ("CREATE TABLE IF NOT EXISTS mt_review (case_id TEXT NOT NULL, para_idx INTEGER NOT NULL, "
                "reason TEXT, jev_p REAL, PRIMARY KEY (case_id, para_idx))")


def migrate(con: sqlite3.Connection) -> None:
    for table, col, sql in SCHEMA:
        if not any(r[1] == col for r in con.execute(f"PRAGMA table_info({table})")):
            con.execute(sql)
    con.execute(REVIEW_TABLE)
    con.commit()


def review_flags(job_rows: list[dict], tr: dict, cache: dict, rid: str, threshold: float) -> dict[str, tuple]:
    """row id -> (reason, jev probability) for rows a person should check."""
    out = {}
    for r in job_rows:
        en = tr.get(r["id"])
        if not en:
            out[r["id"]] = ("no translation", None)
            continue
        rules = judge.rule_flags(r["fr"], en)
        p = cache.get(f"{rid}__{r['id']}__{judge.sha(en)}")
        if rules:
            out[r["id"]] = ("checks: " + ", ".join(rules), p)
        elif p is not None and p < threshold:
            out[r["id"]] = ("Jev", p)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--jobs", required=True)
    ap.add_argument("--suffix", required=True)
    ap.add_argument("--codex-dir", required=True)
    ap.add_argument("--cache", required=True, help="Jev answers (judge.py)")
    ap.add_argument("--review-threshold", type=float, default=0.3)
    ap.add_argument("--sql-out", required=True)
    ap.add_argument("--apply", help="local database to migrate and load into")
    ap.add_argument("--only", help="case ids, comma-separated")
    args = ap.parse_args()

    import p60_monthly_update as p60
    build_db = p60._load_module(p60.BUILD_DB_PATH, "build_db")
    p34 = p60._load_module(p60.P34_PATH, "p34_rebuild_from_hudoc")
    kpthes = json.loads(p60.KPTHESAURUS_PATH.read_text())
    cache = judge.load_cache(args.cache)
    tags = args.suffix.split(",")
    v = p34.sql_value
    forward, case_ids, stats = ["BEGIN;"], [], Counter()
    only = set(args.only.split(",")) if args.only else None
    for case_dir in sorted(p for p in Path(args.jobs).iterdir() if p.is_dir()):
        cid = case_dir.name
        if only and cid not in only:
            continue
        data = json.loads((Path(args.codex_dir) / "parsed" / f"{cid}.json").read_text())
        en_rows: dict[str, str] = {}
        review: dict[str, tuple] = {}
        for jf in sorted(case_dir.glob("chunk_[0-9][0-9][0-9].json")):
            job, tr = json.loads(jf.read_text()), merged_translation(jf, tags)
            en_rows.update({k: v_ for k, v_ in tr.items() if v_})
            rid = f"{cid}__{jf.stem[6:]}"
            for row_id, flag in review_flags(job["rows"], tr, cache, rid, args.review_threshold).items():
                review[row_id] = flag
        paras = []
        for k, r in enumerate(data["paragraphs"]):
            if not (r.get("text") or "").strip():
                continue
            en = en_rows.get(f"r{k:04d}")
            stats["rows"] += 1
            stats["translated" if en else "kept in French"] += 1
            paras.append({**r, "text": en or r["text"]})
        meta = p60.map_metadata(data["official_metadata"], kpthes, build_db)
        forward += p60.emit_case(meta, paras, build_db, p34)
        forward.append(f"UPDATE cases SET text_origin = 'machine_translation', source_case_id = "
                       f"{v(data.get('source_case_id'))}, source_language = 'FRE' WHERE case_id = {v(cid)};")
        idx_of = {f"r{k:04d}": r["para_idx"] for k, r in enumerate(data["paragraphs"])}
        for row_id, (reason, p) in review.items():
            forward.append(f"INSERT OR REPLACE INTO mt_review VALUES ({v(cid)}, {v(idx_of.get(row_id))}, "
                           f"{v(reason)}, {v(round(p, 3) if p is not None else None)});")
            stats["for review"] += 1
        case_ids.append(cid)
    forward.append("COMMIT;")
    Path(args.sql_out).write_text("\n".join(forward) + "\n")
    rollback = [f"DELETE FROM mt_review WHERE case_id = {v(c)};" for c in case_ids] + p60.emit_rollback(case_ids, p34)
    Path(args.sql_out + ".rollback").write_text("\n".join(rollback) + "\n")
    print(json.dumps({"judgments": len(case_ids), **stats}))
    if args.apply:
        con = sqlite3.connect(args.apply, timeout=600)
        migrate(con)
        con.close()
        print(f"schema ready in {args.apply}; load with: python3 scripts/apply_sql_batched.py --db {args.apply} "
              f"--sql {args.sql_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
