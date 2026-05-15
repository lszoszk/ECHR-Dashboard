"""P56 — JS propagation heal: once a case has entered the Just
Satisfaction section, all subsequent `Merits` rows (until Operative)
also belong to Just Satisfaction.

Bug discovered via deep-dive LLM-judge on modern Ju_* committee
judgments (001-214668..670 cluster).  P52c/P55 reset section forward
on TEXT triggers, but missed cases where the parser ALREADY assigned
the JS heading + first JS row correctly — only to lose the section
when the Article 41 quote block reverted to its structural parent
(Merits) and subsequent body rows inherited that.

Rule: walk each case in para_idx order; once any row has
`section IN ('Just Satisfaction', 'Article 46')`, set `js_seen = True`;
every subsequent row with `section IN ('Merits', 'Admissibility',
'Final Submissions')` gets retagged to `Just Satisfaction` until a row
with `section = 'Operative part'` is seen (then reset js_seen).

Conservative: never touches rows that aren't currently in
Merits/Admissibility/Final Submissions.
"""
from __future__ import annotations

import argparse
import sqlite3
from collections import Counter
from pathlib import Path

DB = "/data/echr_search.db"


def heal_case(case_id: str, rows: list[dict], stats: Counter, log: list):
    updates = []
    js_seen = False
    for r in rows:
        section = r["section"]
        if section in ("Just Satisfaction", "Article 46"):
            js_seen = True
            continue
        if section in ("Operative part", "Operative Part"):
            js_seen = False
            continue
        if section == "Separate Opinion":
            # SO terminates everything; don't propagate JS into SO
            js_seen = False
            continue
        if js_seen and section in ("Merits", "Admissibility", "Final Submissions"):
            updates.append((("section", "Just Satisfaction"), r["rowid"]))
            stats["js_propagate"] += 1
            log.append((case_id, r["para_idx"], "section", section,
                        "Just Satisfaction", (r["text"] or "")[:80]))
    return updates


def run(dry_run: bool, db_path: str, log_path: str | None):
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA journal_mode = WAL")
    cases = [r[0] for r in con.execute(
        "SELECT DISTINCT case_id FROM paragraphs ORDER BY case_id"
    )]
    print(f"scanning {len(cases):,} cases", flush=True)

    stats = Counter()
    log: list = []
    all_updates: list = []

    for ci, cid in enumerate(cases, 1):
        rows = [
            {"rowid": r[0], "para_idx": r[1], "section": r[2],
             "row_role": r[3], "text": r[4]}
            for r in con.execute(
                "SELECT rowid, para_idx, section, row_role, text "
                "FROM paragraphs WHERE case_id = ? "
                "ORDER BY para_idx IS NULL, para_idx, rowid",
                (cid,),
            )
        ]
        if not rows:
            continue
        all_updates.extend(heal_case(cid, rows, stats, log))
        if ci % 2000 == 0:
            print(f"  {ci:,}/{len(cases):,}  updates: {len(all_updates):,}",
                  flush=True)

    print(f"\nHealer hit-counts:")
    print(f"  js_propagate         {stats['js_propagate']:>7,}")
    print(f"\nTotal updates queued: {len(all_updates):,}")

    if log_path:
        out = Path(log_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w") as f:
            f.write("case_id\tpara_idx\tcolumn\told\tnew\ttext_preview\n")
            for cid, pi, col, old, new, txt in log:
                f.write(
                    f"{cid}\t{pi}\t{col}\t{old}\t{new}\t"
                    f"{(txt or '').replace(chr(9), ' ')[:120]}\n"
                )
        print(f"Wrote audit log: {out}  ({len(log):,} rows)")

    if dry_run:
        print("\nDRY RUN — no UPDATE applied.")
        return

    print(f"\napplying UPDATEs...", flush=True)
    batch = 20000
    for i in range(0, len(all_updates), batch):
        chunk = all_updates[i:i + batch]
        con.executemany(
            "UPDATE paragraphs SET section = ? WHERE rowid = ?",
            [(v, rid) for (col, v), rid in chunk],
        )
        con.commit()
    print(f"  applied {len(all_updates):,}")
    print("done.")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=DB)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--log", default="/tmp/p56_audit.tsv")
    args = ap.parse_args()
    run(args.dry_run, args.db, args.log or None)


if __name__ == "__main__":
    main()
