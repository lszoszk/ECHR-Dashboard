#!/usr/bin/env python3
"""
P69 — take HUDOC's own "Case details" metadata for every document in the corpus.

Why: the outcome lists in `cases.violation` / `non_violation` came from an old pipeline that read
the conclusion text, so "violation of Article 8 read in the light of Article 9" became a violation of
Article 9 (Abdi Ibrahim v. Norway). HUDOC's structured fields say `8;8-1`. On 2026-10-09 our lists
differed from HUDOC's in 60% of Grand Chamber judgments and 74% of a random sample. Several HUDOC
fields were never stored at all: the Strasbourg case-law list, domestic and international law, Rules
of Court, separate opinions, the application numbers HUDOC extracted from the text.

Two steps, so the network part and the database part can run on different machines:

  fetch  (needs internet)   python3 scripts/p69_sync_hudoc_metadata.py fetch --db DB --out meta.json [--ids more_ids.txt]
  apply  (needs the DB)     python3 scripts/p69_sync_hudoc_metadata.py apply --db DB --meta meta.json [--apply]

`apply` without --apply only reports. With --apply, in one transaction:
  * every HUDOC field is stored raw in `hudoc_metadata` (one row per case, replaced on re-run);
  * the original outcome columns go to `outcome_backup_p69` the FIRST time only (a re-run never
    overwrites the original backup);
  * `violation` / `non_violation` become HUDOC's lists (";"-separated tokens, including HUDOC's
    combined codes such as "13+8-1"); the *_inferred columns are emptied, because nothing is inferred.
    When HUDOC has neither field for a case, our existing values are kept and the case is counted;
  * `strasbourg_caselaw`, `domestic_law`, `international_law`, `rules_of_court` and `separate_opinion`
    ("true"/"false") are added to `cases` if missing and filled (the API serves them when present).

Rollback of the outcome columns:
  UPDATE cases SET violation=b.violation, non_violation=b.non_violation,
         violation_inferred=b.violation_inferred, non_violation_inferred=b.non_violation_inferred
  FROM outcome_backup_p69 b WHERE b.case_id = cases.case_id;
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

FIELDS = ("violation,nonviolation,article,conclusion,scl,extractedappno,separateopinion,"
          "externalsources,issue,rulesofcourt,representedby,importance,kpthesaurus,judgementdate,kpdate,ecli")
NEW_COLUMNS = {
    "strasbourg_caselaw": "scl",
    "domestic_law": "issue",
    "international_law": "externalsources",
    "rules_of_court": "rulesofcourt",
}
# Single values, stored as text ("true" / "false" / "").
SCALAR_COLUMNS = {"separate_opinion": "separateopinion"}


def split(value) -> list[str]:
    return [x.strip() for x in str(value or "").split(";") if x.strip()]


def cmd_fetch(args) -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import p60_monthly_update as p60
    con = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    ids = [r[0] for r in con.execute("SELECT case_id FROM cases ORDER BY case_id")]
    if args.ids:
        ids += [x.strip().split("\t")[0] for x in Path(args.ids).read_text().splitlines() if x.strip()]
    ids = sorted({i for i in ids if i.startswith("001-")})
    out: dict[str, dict] = {}
    if args.resume and Path(args.out).exists():
        out = json.loads(Path(args.out).read_text())
    todo = [i for i in ids if i not in out]
    print(f"{len(ids):,} documents, {len(todo):,} to fetch", flush=True)
    t0 = time.time()
    for k in range(0, len(todo), 25):
        chunk = todo[k:k + 25]
        q = "contentsitename:ECHR AND (" + " OR ".join(f'itemid:"{i}"' for i in chunk) + ")"
        data = p60.hudoc_get({"query": q, "select": "itemid," + FIELDS, "sort": "itemid Ascending",
                              "start": "0", "length": "50"})
        for r in data.get("results", []):
            c = r["columns"]
            out[c["itemid"]] = {f: c.get(f) for f in FIELDS.split(",")}
        if (k // 25) % 40 == 0:
            print(f"  {k + len(chunk):,}/{len(todo):,}  ({time.time() - t0:.0f} s)", flush=True)
            Path(args.out).write_text(json.dumps(out, ensure_ascii=False))
        time.sleep(0.2)
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False))
    missing = [i for i in ids if i not in out]
    print(f"fetched {len(out):,}; not returned by HUDOC: {len(missing):,}")
    return 0


def cmd_apply(args) -> int:
    meta = json.loads(Path(args.meta).read_text())
    con = sqlite3.connect(args.db, timeout=600, isolation_level=None)
    con.execute("PRAGMA busy_timeout = 600000")
    rows = con.execute("SELECT case_id, violation, non_violation FROM cases").fetchall()
    stats = {"cases": len(rows), "in_hudoc": 0, "outcome_changed": 0, "kept_hudoc_empty": 0,
             "with_strasbourg_caselaw": 0, "not_in_hudoc": 0}
    plan = []
    for case_id, v_old, nv_old in rows:
        m = meta.get(case_id)
        if not m:
            stats["not_in_hudoc"] += 1
            continue
        stats["in_hudoc"] += 1
        hv, hn = split(m.get("violation")), split(m.get("nonviolation"))
        if hv or hn:
            new_v, new_nv = json.dumps(hv), json.dumps(hn)
            if sorted(json.loads(v_old or "[]")) != sorted(hv) or sorted(json.loads(nv_old or "[]")) != sorted(hn):
                stats["outcome_changed"] += 1
        else:
            new_v = new_nv = None
            if json.loads(v_old or "[]") or json.loads(nv_old or "[]"):
                stats["kept_hudoc_empty"] += 1
        stats["with_strasbourg_caselaw"] += bool(split(m.get("scl")))
        plan.append((case_id, m, new_v, new_nv))
    print(json.dumps(stats, indent=1))
    if not args.apply:
        print("dry run: nothing changed (add --apply)")
        return 0

    have = {r[1] for r in con.execute("PRAGMA table_info(cases)")}
    con.execute("BEGIN")
    try:
        for col in list(NEW_COLUMNS) + list(SCALAR_COLUMNS):
            if col not in have:
                con.execute(f"ALTER TABLE cases ADD COLUMN {col} TEXT")
        con.execute("CREATE TABLE IF NOT EXISTS outcome_backup_p69 (case_id TEXT PRIMARY KEY, violation TEXT, "
                    "non_violation TEXT, violation_inferred TEXT, non_violation_inferred TEXT)")
        con.execute("INSERT OR IGNORE INTO outcome_backup_p69 SELECT case_id, violation, non_violation, "
                    "violation_inferred, non_violation_inferred FROM cases")
        cols = ["case_id", "fetched_at"] + FIELDS.split(",")
        con.execute(f"CREATE TABLE IF NOT EXISTS hudoc_metadata ({', '.join(c + ' TEXT' for c in cols)}, "
                    "PRIMARY KEY (case_id))")
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        for case_id, m, new_v, new_nv in plan:
            con.execute(f"INSERT OR REPLACE INTO hudoc_metadata ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                        [case_id, now] + [m.get(f) for f in FIELDS.split(",")])
            sets = {col: json.dumps(split(m.get(src))) for col, src in NEW_COLUMNS.items()}
            sets.update({col: str(m.get(src) or "").strip().lower() for col, src in SCALAR_COLUMNS.items()})
            if new_v is not None:
                sets.update(violation=new_v, non_violation=new_nv,
                            violation_inferred="[]", non_violation_inferred="[]")
            con.execute(f"UPDATE cases SET {', '.join(k + ' = ?' for k in sets)} WHERE case_id = ?",
                        list(sets.values()) + [case_id])
        con.execute("COMMIT")
    except Exception as exc:                                                  # noqa: BLE001
        con.execute("ROLLBACK")
        print(f"ROLLED BACK: {exc}", file=sys.stderr)
        return 1
    print("applied; checkpoint:", con.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone())
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("--db", required=True)
    f.add_argument("--out", required=True)
    f.add_argument("--ids", help="extra case ids (one per line, first column) to fetch as well")
    f.add_argument("--resume", action="store_true")
    a = sub.add_parser("apply")
    a.add_argument("--db", required=True)
    a.add_argument("--meta", required=True)
    a.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    return cmd_fetch(args) if args.cmd == "fetch" else cmd_apply(args)


if __name__ == "__main__":
    sys.exit(main())
