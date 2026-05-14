"""P51 — Heal `section = "Separate Opinion"` false positives corpus-wide.

The DOCX-style-trust bug (cf. S. AND MARPER v. UK 001-90051) lets a
single misapplied `Opi_H_*` style poison every subsequent paragraph
until the next major section heading.  Corpus scan: ~31 % of cases
with any Separate Opinion paragraph have at least one Court-language
("The Court notes / considers / observes") paragraph wrongly tagged
SO.  63 cases have SO with no opinion-marker text anywhere — all
false positives.  Worst offenders: S. AND MARPER (80), BURMYCH
(51 032), SANDU (13 587).

P51 reconciles each case's `section` column with the authoritative
text signal.  For each case:

  1. Find the FIRST row whose text matches OPI_HEAD_RE (the
     opinion-heading anchor, e.g. "CONCURRING OPINION OF JUDGE X").
     This is the boundary.
  2. Rows BEFORE the anchor that carry section='Separate Opinion'
     are false positives — retag to the section of the most recent
     prior non-SO paragraph (forward-fill heuristic).
  3. Rows AT/AFTER the anchor stay 'Separate Opinion'.
  4. If NO anchor exists in the case, EVERY SO row is a false
     positive — retag wholesale.

Conservative — only touches rows currently in 'Separate Opinion';
never moves a paragraph INTO SO that wasn't already there (i.e.
false-negative rate stays exactly where it was, while false-positive
rate drops to ~0 % subject to the anchor regex coverage).
"""
import re
import sqlite3
from collections import Counter

DB = "/data/echr_search.db"

OPI_HEAD_RE = re.compile(
    r"^\s*("
    r"(JOINT\s+)?(PARTLY\s+)?(CONCURRING|DISSENTING)"
    r"(\s*,\s*PARTLY\s+(CONCURRING|DISSENTING))?\s+OPINION\s+(OF|BY)\s+JUDGES?\b"
    r"|SEPARATE\s+OPINION\s+OF\s+JUDGES?\b"
    r"|DECLARATION\s+OF\s+JUDGE\b"
    r"|OPINION\s+(CONCORDANTE|DISSIDENTE|S[EÉ]PAR[EÉ]E|COMMUNE|CONJOINTE)"
    r"|OPINION\s+(EN\s+PARTIE|PARTIELLEMENT)\s+(CONCORDANTE|DISSIDENTE)"
    r"|D[EÉ]CLARATION\s+(DU|DE\s+LA)\s+JUGE\b"
    r")",
    re.I,
)


def heal_case(con, case_id):
    """Return (n_retagged, dropped_so_count_change, anchor_pi)."""
    rows = list(con.execute(
        "SELECT rowid, para_idx, row_role, section, text "
        "FROM paragraphs WHERE case_id = ? "
        "ORDER BY para_idx IS NULL, para_idx, rowid",
        (case_id,),
    ))
    if not rows:
        return 0, 0, None

    # Step 1: Find the opinion anchor (first row where text matches
    # OPI_HEAD_RE).  Skip rows whose section is already 'Separate
    # Opinion' AND row_role is 'heading' that themselves look like
    # the heading (those ARE the opinion-start markers — we want the
    # earliest one).
    anchor_pi = None
    for rowid, pi, role, section, text in rows:
        if text and OPI_HEAD_RE.match(text):
            anchor_pi = pi
            break

    # Step 2: For each row currently in 'Separate Opinion' with
    # para_idx < anchor_pi (or all of them if no anchor), find the
    # nearest prior non-SO section and retag.
    # Build a quick lookup of "most recent non-SO section" walking
    # forward.
    prior_section = "Header"  # safe default
    updates = []  # (new_section, rowid)
    n_retagged = 0
    for rowid, pi, role, section, text in rows:
        if section != "Separate Opinion":
            prior_section = section
            continue
        # section == 'Separate Opinion'
        if anchor_pi is None or (pi is not None and pi < anchor_pi):
            # False positive — retag to last known non-SO section.
            new_sec = prior_section
            updates.append((new_sec, rowid))
            n_retagged += 1
    return n_retagged, anchor_pi, len(rows)


def main():
    con = sqlite3.connect(DB)
    con.execute("PRAGMA journal_mode = WAL")

    cases = [r[0] for r in con.execute(
        "SELECT DISTINCT case_id FROM paragraphs "
        "WHERE section = 'Separate Opinion'"
    )]
    print(f"scanning {len(cases):,} cases with any Separate Opinion paragraph",
          flush=True)

    total_retagged = 0
    cases_touched = 0
    cases_no_anchor = 0
    section_target_dist = Counter()

    all_updates = []
    for ci, cid in enumerate(cases, 1):
        rows = list(con.execute(
            "SELECT rowid, para_idx, row_role, section, text "
            "FROM paragraphs WHERE case_id = ? "
            "ORDER BY para_idx IS NULL, para_idx, rowid",
            (cid,),
        ))
        if not rows:
            continue

        # Find anchor
        anchor_pi = None
        for rowid, pi, role, section, text in rows:
            if text and OPI_HEAD_RE.match(text):
                anchor_pi = pi
                break

        prior_section = "Header"
        case_updates = []
        for rowid, pi, role, section, text in rows:
            if section != "Separate Opinion":
                prior_section = section
                continue
            if anchor_pi is None or (pi is not None and pi < anchor_pi):
                case_updates.append((prior_section, rowid))
                section_target_dist[prior_section] += 1

        if case_updates:
            all_updates.extend(case_updates)
            cases_touched += 1
            total_retagged += len(case_updates)
            if anchor_pi is None:
                cases_no_anchor += 1

        if ci % 200 == 0:
            print(
                f"  {ci:,}/{len(cases):,}  touched={cases_touched:,}  "
                f"retagged={total_retagged:,}  no-anchor={cases_no_anchor:,}",
                flush=True,
            )

    print(
        f"\ndone:\n"
        f"  cases scanned:               {len(cases):,}\n"
        f"  cases touched:               {cases_touched:,}\n"
        f"  cases with NO opinion anchor: {cases_no_anchor:,}  "
        f"(all SO rows in these cases were false positives)\n"
        f"  rows retagged out of SO:     {total_retagged:,}\n"
        f"\n  retag-target section distribution:"
    )
    for sec, n in section_target_dist.most_common():
        print(f"    {sec:30s} {n:>8,}")

    # Apply
    print(f"\napplying {len(all_updates):,} UPDATE statements...", flush=True)
    batch = 20000
    for i in range(0, len(all_updates), batch):
        con.executemany(
            "UPDATE paragraphs SET section = ? WHERE rowid = ?",
            all_updates[i:i + batch],
        )
        con.commit()
    print("done.")

    # Verify S. AND MARPER
    n = con.execute(
        "SELECT COUNT(*) FROM paragraphs "
        "WHERE case_id = '001-90051' AND section = 'Separate Opinion'"
    ).fetchone()[0]
    print(f"\nVerify: S. AND MARPER (001-90051) Separate Opinion rows: {n} "
          f"(expected 0)")


if __name__ == "__main__":
    main()
