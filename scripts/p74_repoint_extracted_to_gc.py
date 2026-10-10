#!/usr/bin/env python3
"""p74 — move citations taken from HUDOC's bare extracted application numbers to the Grand Chamber
judgment, where one already existed when the citing judgment was delivered.

Until 10 October 2026, p29 resolved a number without context (extractedappno) to the principal,
earliest judgment under it, so a 2012 judgment "citing" no. 36022/97 was linked to the 2001 Chamber
judgment in Hatton and Others instead of the 2003 Grand Chamber judgment. p29 now applies the rule
in `pick_extracted`; this script applies it to the rows already in the database, in both
case_citations and french_only_citations (extraction_method 'hudoc_extracted' only), so no full
rebuild is needed. Where the citing judgment already cites the Grand Chamber judgment, the
Chamber row is deleted instead of moved.

    python3 p74_repoint_extracted_to_gc.py --db /data/echr_search.db            # dry run
    python3 p74_repoint_extracted_to_gc.py --db /data/echr_search.db --apply    # write, keep a log

Every change is logged in table p74_repoint_log, which is enough to undo it (--rollback).
Needs p29_extract_citations.py next to it.
"""
import argparse
import importlib.util
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

_spec = importlib.util.spec_from_file_location("p29", Path(__file__).with_name("p29_extract_citations.py"))
p29 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(p29)

TABLES = ("case_citations", "french_only_citations")


def plan(con: sqlite3.Connection, idx) -> list[tuple]:
    """(table, rowid, citing, old_cited, new_cited, action) for every row to change."""
    fo_dates = {}
    if con.execute("SELECT 1 FROM sqlite_master WHERE name = 'french_only_cases'").fetchone():
        fo_dates = {r[0]: p29.parse_date(r[1]) for r in con.execute("SELECT case_id, judgment_date FROM french_only_cases")}
    changes = []
    for table in TABLES:
        if not con.execute("SELECT 1 FROM sqlite_master WHERE name = ?", (table,)).fetchone():
            continue
        cited_by = {}
        for citing, cited in con.execute(f"SELECT citing_case_id, cited_case_id FROM {table}"):
            cited_by.setdefault(citing, set()).add(cited)
        rows = con.execute(f"SELECT rowid, citing_case_id, cited_case_id FROM {table} "
                           "WHERE extraction_method = 'hudoc_extracted'").fetchall()
        for rowid, citing_id, cited_id in rows:
            cited = idx.docs.get(cited_id)
            if cited is None or cited.is_gc or cited.is_decision:
                continue
            citing = idx.docs.get(citing_id)
            date = citing.date if citing else fo_dates.get(citing_id)
            if not date:
                continue
            cands = {d.case_id: d for a in cited.appnos for d in idx.by_appno.get(a, [])}
            probe = cited._replace(case_id=citing_id, date=date)
            new = p29.pick_extracted(list(cands.values()), probe)
            if new is None or not new.is_gc or new.case_id in (cited_id, citing_id):
                continue
            action = "delete" if new.case_id in cited_by.get(citing_id, ()) else "move"
            changes.append((table, rowid, citing_id, cited_id, new.case_id, action))
            cited_by.setdefault(citing_id, set()).add(new.case_id)
    return changes


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", required=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--rollback", action="store_true", help="undo the changes recorded in p74_repoint_log")
    args = ap.parse_args()
    con = sqlite3.connect(args.db, timeout=600)

    if args.rollback:
        with con:
            log = con.execute("SELECT tbl, citing, old_cited, new_cited, action, rowdata FROM p74_repoint_log").fetchall()
            for tbl, citing, old, new, action, rowdata in log:
                cols = [r[1] for r in con.execute(f"PRAGMA table_info({tbl})")]
                if action == "move":
                    con.execute(f"DELETE FROM {tbl} WHERE citing_case_id = ? AND cited_case_id = ? "
                                "AND extraction_method = 'hudoc_extracted'", (citing, new))
                values = json.loads(rowdata)
                con.execute(f"INSERT OR IGNORE INTO {tbl} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", values)
            con.execute("DROP TABLE p74_repoint_log")
        print(f"rolled back {len(log):,} changes")
        return 0

    con.row_factory = sqlite3.Row
    idx = p29.build_indexes(con.cursor())
    con.row_factory = None
    changes = plan(con, idx)
    print(dict(Counter((t, a) for t, *_, a in changes)))
    titles = {}
    for t, _, citing, old, new, a in changes[:8]:
        for cid in (citing, old, new):
            if cid not in titles:
                r = con.execute("SELECT title FROM cases WHERE case_id = ?", (cid,)).fetchone()
                titles[cid] = (r[0] if r else cid)[:40]
        print(f"  {t}: {titles[citing]} -> {titles[old]} ({old}) => {new} [{a}]")
    if not args.apply:
        print("dry run: nothing written (use --apply)")
        return 0
    with con:
        con.execute("CREATE TABLE IF NOT EXISTS p74_repoint_log (tbl TEXT, citing TEXT, old_cited TEXT, "
                    "new_cited TEXT, action TEXT, rowdata TEXT)")
        for t, rowid, citing, old, new, action in changes:
            row = con.execute(f"SELECT * FROM {t} WHERE rowid = ?", (rowid,)).fetchone()
            con.execute("INSERT INTO p74_repoint_log VALUES (?,?,?,?,?,?)", (t, citing, old, new, action, json.dumps(list(row))))
            if action == "delete":
                con.execute(f"DELETE FROM {t} WHERE rowid = ?", (rowid,))
            else:
                con.execute(f"UPDATE {t} SET cited_case_id = ? WHERE rowid = ?", (new, rowid))
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    print(f"applied {len(changes):,} changes (log: p74_repoint_log)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
