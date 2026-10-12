#!/usr/bin/env python3
"""p78 — move judgments whose text is HUDOC's French item out of the English corpus into the French
originals (echr_fr.db).

Fifty judgments of 2026, loaded by monthly updates before p60 checked the item's language, sat in the
English corpus with their French text: an English search for "marge" found them, the French search did
not, and they counted as English judgments. They belong with the French originals.

    python3 p78_move_french_items.py --main /data/echr_search.db --fr /data/echr_fr.db --ids ids.json          # report
    python3 p78_move_french_items.py --main /data/echr_search.db --fr /data/echr_fr.db --ids ids.json --apply  # move

--apply, in one transaction per database:
  * main: copies the rows into p78_moved_cases / p78_moved_paragraphs / p78_moved_case_articles, then
    deletes them (the paragraph triggers keep the full-text index in step);
  * French: inserts the cases, paragraphs (new row ids) and articles, and adds the paragraphs to its
    full-text index (it has no triggers) — except a judgment already there under HUDOC's English record
    of it (same application number and date, as p75 keys them): that one is only removed from the
    English corpus. On 12 October 2026 that was 49 of the 50; the first run inserted them and they were
    deleted again from echr_fr.db, which this check now avoids.
Rollback: re-insert from the p78_moved_* tables into the main database, and delete the ids from
echr_fr.db (cases, case_articles, paragraphs and their paragraphs_fts rows).
Afterwards: rebuild the citations (deploy/rebuild_citations.sh --apply, then p76 for the French ones)
and the Semantic Search metadata (rag/pipeline/build_cases_meta.py).
"""
from __future__ import annotations

import argparse
import json
import sqlite3


def cols(con, table):
    return [r[1] for r in con.execute(f"PRAGMA table_info('{table}')")]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--main", required=True)
    ap.add_argument("--fr", required=True)
    ap.add_argument("--ids", required=True, help="JSON list of case ids")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    ids = json.load(open(args.ids))
    m = sqlite3.connect(args.main if args.apply else f"file:{args.main}?mode=ro", uri=not args.apply, timeout=600)
    f = sqlite3.connect(args.fr if args.apply else f"file:{args.fr}?mode=ro", uri=not args.apply, timeout=600)
    ph = ",".join("?" * len(ids))
    present = [r[0] for r in m.execute(f"SELECT case_id FROM cases WHERE case_id IN ({ph})", ids)]
    already = [r[0] for r in f.execute(f"SELECT case_id FROM cases WHERE case_id IN ({ph})", ids)]
    n_par = m.execute(f"SELECT count(*) FROM paragraphs WHERE case_id IN ({ph})", ids).fetchone()[0]
    n_art = m.execute(f"SELECT count(*) FROM case_articles WHERE case_id IN ({ph})", ids).fetchone()[0]
    print(f"ids {len(ids)}; in the main database {len(present)} ({n_par} paragraphs, {n_art} articles); "
          f"already in the French one {len(already)}")
    if already:
        raise SystemExit("some ids are already French originals; stopping")
    twins = {i for i in present if (lambda r: r and f.execute(
        "SELECT 1 FROM cases WHERE case_no = ? AND judgment_date = ?", r).fetchone())(
        m.execute("SELECT case_no, judgment_date FROM cases WHERE case_id = ?", (i,)).fetchone())}
    new = [i for i in present if i not in twins]
    print(f"already French originals under the English record's id: {len(twins)}; to add: {len(new)}")
    shared = {t: [c for c in cols(m, t) if c in cols(f, t) and c != "rowid"] for t in ("cases", "paragraphs", "case_articles")}
    print("columns copied:", {t: len(c) for t, c in shared.items()},
          "| French-only columns left empty:", {t: [c for c in cols(f, t) if c not in cols(m, t)] for t in shared})
    if not args.apply:
        print("dry run: nothing written (use --apply)")
        return 0

    nph = ",".join("?" * len(new))
    rows = {t: m.execute(f"SELECT {','.join(shared[t])} FROM {t} WHERE case_id IN ({nph})"
                         + (" ORDER BY case_id, para_idx" if t == "paragraphs" else ""), new).fetchall() for t in shared}
    with f:
        for t in ("cases", "paragraphs", "case_articles"):
            f.executemany(f"INSERT INTO {t} ({','.join(shared[t])}) VALUES ({','.join('?' * len(shared[t]))})", rows[t])
        f.execute(f"INSERT INTO paragraphs_fts (rowid, title, keywords_text, text) "
                  f"SELECT rowid, title, keywords_text, text FROM paragraphs WHERE case_id IN ({nph})", new)
    with m:
        for t, b in (("cases", "p78_moved_cases"), ("paragraphs", "p78_moved_paragraphs"), ("case_articles", "p78_moved_case_articles")):
            m.execute(f"DROP TABLE IF EXISTS {b}")
            m.execute(f"CREATE TABLE {b} AS SELECT * FROM {t} WHERE case_id IN ({ph})", ids)
        m.execute(f"DELETE FROM paragraphs WHERE case_id IN ({ph})", ids)
        m.execute(f"DELETE FROM case_articles WHERE case_id IN ({ph})", ids)
        m.execute(f"DELETE FROM cases WHERE case_id IN ({ph})", ids)
    for con in (m, f):
        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    print("moved:", f.execute(f"SELECT count(*) FROM cases WHERE case_id IN ({ph})", ids).fetchone()[0], "cases;",
          f.execute(f"SELECT count(*) FROM paragraphs WHERE case_id IN ({ph})", ids).fetchone()[0], "paragraphs in the French database;",
          m.execute(f"SELECT count(*) FROM cases WHERE case_id IN ({ph})", ids).fetchone()[0], "left in the main one")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
