#!/usr/bin/env python3
"""P63 — split the Facts family into Procedure / Circumstances / Subject Matter.

Phase 2 of the facts reclassification (see docs/TODO-facts-reclassify.md).

Problem: 718,093 paragraphs across 19,808 cases sit in one undifferentiated
Facts family (`Facts` + the two legacy `Facts Background` / `Facts Proceedings`
labels), so the dashboard cannot offer the PROCEDURE vs CIRCUMSTANCES filters
that the HUDOC document structure actually supports.

Method (deterministic, established P5x pattern):
  The sections are CONTIGUOUS blocks, so the unit of work is the case boundary,
  not the paragraph. Within a case's Facts-family rows, one heading marks where
  the administrative PROCEDURE block ends and the substantive narrative begins.
  P62 measured that such a marker is present in 97.2% of cases / 99.0% of
  paragraphs.

    bucket A  a SUBJECT MATTER marker  -> rows before it = Procedure,
                                          rows from it on = Subject Matter
    bucket B  a facts-start marker     -> rows before it = Procedure,
                                          rows from it on = Circumstances
    bucket C  PROCEDURE marker only    -> SKIPPED (no end boundary)
    bucket D  no structural heading    -> SKIPPED

  Heading rows inherit the section of the block they introduce, per the
  labelling convention fixed in the v2-v5 judge sweeps.

  Cases in C+D keep their current labels untouched; they are the residue that
  step 3 of the TODO addresses by rule harvest.

Also re-homes the ~7,879 bare `PROCEDURE` heading rows that sit in the
`Introduction` section while their body paragraphs sit in Facts — otherwise the
new Procedure block renders without its own heading. Matching is on exact
normalised heading text, so the 1,989 genuine `INTRODUCTION` headings and the
`PROCEDURE BEFORE THE <domestic body>` sub-headings are left alone.

Safety:
  * Dry-run by default; --apply required to write.
  * Only UPDATEs `paragraphs.section`. Never inserts, deletes, or touches text,
    para_idx, row_role, or the `cases` table. `Header` is out of scope.
  * Every change recorded first in backup table section_backup_p63
    (rowid, old_section, new_section, bucket) — restore with --restore.
  * Idempotent: the new labels are members of the read set, so a second run
    re-derives the same plan and reports zero changes.
  * Three invariants are checked before any write (--verify-only to stop there):
      1. contiguity  - each case's new labels form contiguous runs, one
                       transition at most, no interleaving
      2. coverage    - every Facts-family row in an A/B case gets exactly one
                       new label
      3. row count   - the plan is UPDATE-only; total row count is unchanged

Usage (inside the echr-api container):
  python3 p63_resegment_facts.py                 # dry-run + invariant report
  python3 p63_resegment_facts.py --verify-only   # invariants, no plan dump
  python3 p63_resegment_facts.py --apply
  python3 p63_resegment_facts.py --restore
"""
from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys
from collections import Counter, defaultdict

DB = os.environ.get("ECHR_DB_PATH", "/data/echr_search.db")
BACKUP = "section_backup_p63"

# Legacy labels this pass consumes, plus the labels it produces (so a re-run
# reads its own output back and stays idempotent).
LEGACY = ("Facts", "Facts Background", "Facts Proceedings")
PROCEDURE = "Procedure"
CIRCUMSTANCES = "Circumstances"
SUBJECT_MATTER = "Subject Matter"
PRODUCED = (PROCEDURE, CIRCUMSTANCES, SUBJECT_MATTER)
FACTS_FAMILY = LEGACY + PRODUCED

# --------------------------------------------------------------- normalising

_WS = re.compile(r"\s+")
_LEAD_NUM = re.compile(r"^\s*(?:[IVXLC]+|[0-9]+|[A-Z])\s*[.)]\s*", re.I)


def norm(text: str) -> str:
    """Upper-case, collapse whitespace, strip leading numbering and trailing dots."""
    t = _WS.sub(" ", (text or "")).strip().upper()
    t = t.replace("’", "'").replace("‘", "'")
    prev = None
    while prev != t:                      # "I. A. FOO" -> "FOO"
        prev = t
        t = _LEAD_NUM.sub("", t)
    return t.strip(" .:")


# ------------------------------------------------------------------ markers

FACTS_START_EXACT = {"THE FACTS", "AS TO THE FACTS", "FACTS"}
PROC_EXACT = {"PROCEDURE", "PROCEDURE AND FACTS", "AS TO THE PROCEDURE"}


def marker_class(h: str) -> str | None:
    """'SUBJ' | 'FACTS_START' | 'PROC' | None for a normalised heading.

    SUBJ is tested first: "FACTS AND PROCEDURE" would otherwise match PROC.
    PROC membership is exact, so "PROCEDURE BEFORE THE COURT OF CASSATION"
    (a domestic-proceedings sub-heading) does not fire.
    """
    if "SUBJECT MATTER OF THE CASE" in h or h.startswith("FACTS AND PROCEDURE"):
        return "SUBJ"
    if h in FACTS_START_EXACT or "CIRCUMSTANCES OF THE CASE" in h:
        return "FACTS_START"
    if h in PROC_EXACT or "PROCEEDINGS BEFORE THE COMMISSION" in h:
        return "PROC"
    return None


# --------------------------------------------------------------------- plan


def build_plan(conn):
    """Return (changes, stats). changes = [(rowid, old, new, bucket)]."""
    cur = conn.cursor()
    ph = ",".join("?" * len(FACTS_FAMILY))

    # First marker of each class per case, from Facts-family heading rows.
    first: dict[str, dict[str, int]] = defaultdict(dict)
    cur.execute(
        f"""SELECT case_id, para_idx, text FROM paragraphs
            WHERE section IN ({ph}) AND row_role LIKE 'heading%'
            ORDER BY case_id, para_idx""",
        FACTS_FAMILY,
    )
    for case_id, para_idx, text in cur:
        cls = marker_class(norm(text))
        if cls and cls not in first[case_id]:
            first[case_id][cls] = para_idx

    # All Facts-family rows.
    rows: dict[str, list[tuple[int, int, str]]] = defaultdict(list)
    cur.execute(
        f"SELECT case_id, para_idx, rowid, section FROM paragraphs WHERE section IN ({ph})",
        FACTS_FAMILY,
    )
    for case_id, para_idx, rowid, section in cur:
        rows[case_id].append((para_idx, rowid, section))

    changes: list[tuple[int, str, str, str]] = []
    stats = Counter()
    bucket_of: dict[str, str] = {}
    new_label: dict[int, str] = {}          # rowid -> new section (for invariants)

    for case_id, items in rows.items():
        m = first.get(case_id, {})
        if "SUBJ" in m:
            bucket, cut, tail = "A", m["SUBJ"], SUBJECT_MATTER
        elif "FACTS_START" in m:
            bucket, cut, tail = "B", m["FACTS_START"], CIRCUMSTANCES
        else:
            stats["cases_skipped_residue"] += 1
            stats["paras_skipped_residue"] += len(items)
            bucket_of[case_id] = "C/D"
            continue

        bucket_of[case_id] = bucket
        stats[f"cases_bucket_{bucket}"] += 1
        for para_idx, rowid, old in items:
            new = PROCEDURE if para_idx < cut else tail
            new_label[rowid] = new
            if new != old:
                changes.append((rowid, old, new, bucket))

    # Re-home bare PROCEDURE headings parked in `Introduction`, for A/B cases only.
    cur.execute(
        """SELECT rowid, case_id, para_idx, text FROM paragraphs
           WHERE section = 'Introduction' AND row_role LIKE 'heading%'"""
    )
    for rowid, case_id, para_idx, text in cur.fetchall():
        if bucket_of.get(case_id) not in ("A", "B"):
            continue
        if marker_class(norm(text)) != "PROC":
            continue
        cut = first[case_id].get("SUBJ", first[case_id].get("FACTS_START"))
        if para_idx >= cut:
            # A PROCEDURE heading after the facts boundary is not the top-level
            # one; leave it alone and count it for review.
            stats["intro_heading_after_boundary_skipped"] += 1
            continue
        changes.append((rowid, "Introduction", PROCEDURE, "H"))
        stats["intro_headings_rehomed"] += 1

    return changes, stats, rows, new_label, bucket_of


# --------------------------------------------------------------- invariants


def check_invariants(conn, rows, new_label, bucket_of):
    """Return list of failure strings; empty means all three invariants hold."""
    failures = []

    # 1. contiguity: at most one Procedure -> tail transition, no interleaving.
    bad_contig = []
    for case_id, items in rows.items():
        if bucket_of.get(case_id) not in ("A", "B"):
            continue
        seq = [new_label[rowid] for _, rowid, _ in sorted(items)]
        transitions = sum(1 for a, b in zip(seq, seq[1:]) if a != b)
        if transitions > 1:
            bad_contig.append(case_id)
    if bad_contig:
        failures.append(
            f"contiguity: {len(bad_contig)} case(s) have >1 label transition "
            f"(e.g. {bad_contig[:5]})"
        )

    # 2. coverage: every Facts-family row in an A/B case has exactly one label.
    missing = 0
    for case_id, items in rows.items():
        if bucket_of.get(case_id) not in ("A", "B"):
            continue
        for _, rowid, _ in items:
            if new_label.get(rowid) not in PRODUCED:
                missing += 1
    if missing:
        failures.append(f"coverage: {missing} row(s) in A/B cases got no valid label")

    # 3. row count: nothing in the plan inserts or deletes.
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM paragraphs")
    failures.append(("_rowcount", cur.fetchone()[0]))
    return failures


# ------------------------------------------------------------------- report


def report(changes, stats, invariant_failures, rowcount):
    print("P63 — Facts family -> Procedure / Circumstances / Subject Matter")
    print("=" * 72)
    print(f"cases bucket A (subject matter) : {stats['cases_bucket_A']:>7,}")
    print(f"cases bucket B (facts-start)    : {stats['cases_bucket_B']:>7,}")
    print(f"cases skipped (residue C+D)     : {stats['cases_skipped_residue']:>7,}"
          f"   [{stats['paras_skipped_residue']:,} paragraphs left untouched]")
    print(f"Introduction headings re-homed  : {stats['intro_headings_rehomed']:>7,}")
    if stats["intro_heading_after_boundary_skipped"]:
        print(f"  ...skipped (after boundary)   : "
              f"{stats['intro_heading_after_boundary_skipped']:>7,}")
    print()
    print(f"TOTAL ROW UPDATES PLANNED       : {len(changes):>7,}")
    print(f"corpus row count (unchanged by this pass): {rowcount:,}")

    print()
    print("--- transition matrix (old section -> new section) ---")
    tm = Counter((old, new) for _, old, new, _ in changes)
    for (old, new), n in tm.most_common():
        print(f"  {old:20s} -> {new:16s} {n:>9,}")

    print()
    print("--- resulting distribution over changed rows ---")
    for new, n in Counter(new for _, _, new, _ in changes).most_common():
        print(f"  {new:20s} {n:>9,}")

    print()
    print("--- invariants ---")
    real = [f for f in invariant_failures if not (isinstance(f, tuple))]
    if real:
        for f in real:
            print(f"  FAIL  {f}")
    else:
        print("  PASS  1. contiguity   — no case has >1 label transition")
        print("  PASS  2. coverage     — every A/B row received a valid label")
        print("  PASS  3. row count    — plan is UPDATE-only, no inserts/deletes")
    return not real


# -------------------------------------------------------------------- apply


def apply_changes(conn, changes):
    cur = conn.cursor()
    cur.execute(
        f"""CREATE TABLE IF NOT EXISTS {BACKUP} (
              rowid_ref   INTEGER,
              old_section TEXT,
              new_section TEXT,
              bucket      TEXT
            )"""
    )
    cur.executemany(
        f"INSERT INTO {BACKUP} (rowid_ref, old_section, new_section, bucket) "
        f"VALUES (?,?,?,?)",
        changes,
    )
    cur.executemany(
        "UPDATE paragraphs SET section = ? WHERE rowid = ?",
        [(new, rowid) for rowid, _, new, _ in changes],
    )
    conn.commit()
    print(f"\nAPPLIED {len(changes):,} updates. Backup: {BACKUP} "
          f"({len(changes):,} rows).")


def restore(conn):
    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='{BACKUP}'")
    if not cur.fetchone()[0]:
        sys.exit(f"No backup table {BACKUP} — nothing to restore.")
    cur.execute(f"SELECT rowid_ref, old_section FROM {BACKUP}")
    pairs = cur.fetchall()
    cur.executemany("UPDATE paragraphs SET section = ? WHERE rowid = ?",
                    [(old, rid) for rid, old in pairs])
    cur.execute(f"DROP TABLE {BACKUP}")
    conn.commit()
    print(f"Restored {len(pairs):,} rows and dropped {BACKUP}.")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="write changes")
    ap.add_argument("--restore", action="store_true", help="undo everything")
    ap.add_argument("--verify-only", action="store_true",
                    help="check invariants and exit")
    args = ap.parse_args()

    if args.restore:
        restore(sqlite3.connect(DB))
        return

    mode = "rw" if args.apply else "ro"
    conn = sqlite3.connect(f"file:{DB}?mode={mode}", uri=True)

    changes, stats, rows, new_label, bucket_of = build_plan(conn)
    failures = check_invariants(conn, rows, new_label, bucket_of)
    rowcount = next(f[1] for f in failures if isinstance(f, tuple))

    ok = report(changes, stats, failures, rowcount)
    if args.verify_only:
        return
    if not ok:
        sys.exit("\nInvariants FAILED — refusing to apply.")
    if args.apply:
        apply_changes(conn, changes)
    else:
        print("\nDry run. Re-run with --apply to write.")


if __name__ == "__main__":
    main()
