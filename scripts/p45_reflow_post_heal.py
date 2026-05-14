"""Streaming version of P45 — processes case-by-case to avoid loading
all 3.3M paragraphs into memory at once."""
import re
import sqlite3
import sys

DB = "/data/echr_search.db"
NUM_RE = re.compile(r"^\s*\d+\.\s")
HEAD_RE = re.compile(
    r"^\s*(?:\([a-z]\)|\([ivx]+\)|\([α-ω]\)|[IVX]+\.|[A-Z]\.)\s"
)


def main():
    con = sqlite3.connect(DB)
    con.execute("PRAGMA journal_mode = WAL")

    cases = [r[0] for r in con.execute(
        "SELECT DISTINCT case_id FROM paragraphs"
    )]
    print(f"processing {len(cases):,} cases", flush=True)

    total_merges = 0
    total_deletes = 0
    cases_touched = 0

    for ci, case_id in enumerate(cases, 1):
        rows = list(con.execute(
            "SELECT rowid, para_idx, row_role, hudoc_para_no, text, section "
            "FROM paragraphs WHERE case_id=? "
            "ORDER BY para_idx IS NULL, para_idx, rowid",
            (case_id,)
        ))
        if not rows:
            continue

        text_updates = []
        deletes = []
        i = 0
        while i < len(rows):
            rid, pi, role, hp, text, sec = rows[i]
            if (role or "") != "paragraph" or hp is None:
                i += 1
                continue
            merged = text or ""
            j = i + 1
            consumed = []
            while j < len(rows):
                nrid, npi, nrole, nhp, ntext, nsec = rows[j]
                if (nrole or "") != "paragraph": break
                if nsec != sec: break
                if nhp is not None: break
                if NUM_RE.match(ntext or ""): break
                if HEAD_RE.match(ntext or ""): break
                merged = merged.rstrip() + " " + (ntext or "").lstrip()
                consumed.append(nrid)
                j += 1
            if consumed:
                text_updates.append((merged, rid))
                deletes.extend(consumed)
            i = j if consumed else i + 1

        if text_updates:
            con.executemany(
                "UPDATE paragraphs SET text=? WHERE rowid=?",
                text_updates,
            )
        if deletes:
            con.executemany(
                "DELETE FROM paragraphs WHERE rowid=?",
                [(r,) for r in deletes],
            )
        if text_updates or deletes:
            con.commit()
            cases_touched += 1
            total_merges += len(text_updates)
            total_deletes += len(deletes)

        if ci % 1000 == 0:
            print(
                f"  {ci:,}/{len(cases):,}  "
                f"touched={cases_touched:,}  "
                f"merges={total_merges:,}  deletes={total_deletes:,}",
                flush=True,
            )

    print(
        f"\ndone: {total_merges:,} parents merged, "
        f"{total_deletes:,} orphan rows deleted, "
        f"{cases_touched:,} cases touched"
    )


if __name__ == "__main__":
    main()
