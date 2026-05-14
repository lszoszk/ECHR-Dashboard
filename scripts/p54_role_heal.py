"""P54 — Role-tightening heal for the residual operative-bleed cases
surfaced by the v2 judge sweep on the post-P52 DB.

The v2 sweep found 6 high-confidence FALSE classifications categorised
as `operative-bleed`: text that lives in `section = 'Operative part'`
but whose row_role makes it indistinguishable from a dispositif
paragraph.  Two patterns dominate:

  1. ANNEX_NOTICE_RE — boilerplate sentence appended to the operative
     part right before the appended separate opinions, e.g.
     "In accordance with Article 45 § 2 of the Convention and Rule 74
     § 2 of the Rules of Court, the dissenting opinion of Judge X is
     annexed to this judgment."  These pass through p34 as
     `row_role = 'paragraph'` because the source DOCX styles them as
     a plain Ju_Para.  Re-tag them as `metadata`.

  2. SIGNATURE_LINE_RE — tab-separated registrar/president signature
     block ("Stephen Phillips\\tRenate Jaeger\\nDeputy
     Registrar\\tPresident"). p34 tags these as `paragraph` when the
     source DOCX uses Normal-style instead of `Ju_Signed`.  Re-tag as
     `signature`.

Out-of-scope (judge-convention disagreement, not bug):
  - Rows tagged `heading_h0`/`heading_h1` whose db_section is
    Facts/Merits.  The judge's HEADING bucket is a separate
    classification axis; our schema treats heading as a row_role
    nested under the parent section.  The UI already excludes
    heading_* rows from search results by default, so these rows
    behave correctly even though the calibration TSV calls them N.

Idempotent.  Re-running after a successful heal touches 0 rows.
"""
from __future__ import annotations

import argparse
import re
import sqlite3
from collections import Counter
from pathlib import Path

DB = "/data/echr_search.db"

# ────────────────────────────────────────────────────────────────────────
# Detection patterns
# ────────────────────────────────────────────────────────────────────────

# "In accordance with Article 45 § 2 of the Convention and Rule 74 § 2 of
# the Rules of Court, the {separate|dissenting|concurring|partly} opinion
# of Judge X (joined by Y) is annexed to this judgment."
# Also French variant.
ANNEX_NOTICE_RE = re.compile(
    r"(In accordance with\s+Article\s*45\s*§\s*2\b"
    r"|Conform[ée]ment\s+(?:à\s+)?l['’]article\s*45\s*§\s*2\b)",
    re.I,
)

# Registrar / President signature line.  Heuristic:
#   - short (<= 220 chars) AND
#   - contains BOTH a Registrar word ("Registrar"/"Greffier") AND a
#     President word ("President"/"Président") AND
#   - typically tab or whitespace separated.
SIG_REGISTRAR_RE = re.compile(
    r"\b(Deputy\s+)?(Section\s+|Grand\s+Chamber\s+)?(Registrar|Greffier)(?:\s+adjoint)?\b",
    re.I,
)
SIG_PRESIDENT_RE = re.compile(
    r"\b(Vice-?\s*)?(President|Pr[ée]sident)\b",
    re.I,
)

# Done-line — already tagged 'footer' by p34 when matched.  Some old
# templates land it in role='paragraph'.  Detect and tag as 'metadata'.
DONE_LINE_RE = re.compile(
    r"^\s*(Done in (English|French)|Fait en (anglais|fran[cç]ais))",
    re.I,
)


def is_annex_notice(text: str) -> bool:
    if not text or len(text) > 400:
        return False
    return bool(ANNEX_NOTICE_RE.search(text))


def is_signature_line(text: str) -> bool:
    if not text:
        return False
    t = text.strip()
    if len(t) > 220:
        return False
    if not SIG_REGISTRAR_RE.search(t):
        return False
    if not SIG_PRESIDENT_RE.search(t):
        return False
    # Guard against substantive sentences mentioning the president —
    # signature lines have no sentence terminator + lots of whitespace.
    if re.search(r"[.?!]\s+[A-Z]", t):
        return False
    return True


def is_done_line(text: str) -> bool:
    if not text:
        return False
    return bool(DONE_LINE_RE.match(text))


# ────────────────────────────────────────────────────────────────────────
# Driver
# ────────────────────────────────────────────────────────────────────────


def run(dry_run: bool, db_path: str, log_path: str | None):
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA journal_mode = WAL")

    # Scope: only paragraph / footer rows currently in Operative part.
    rows = list(con.execute(
        "SELECT rowid, case_id, para_idx, row_role, section, text "
        "FROM paragraphs "
        "WHERE section IN ('Operative part','Operative Part') "
        "  AND row_role IN ('paragraph','footer')"
    ))
    print(f"candidates (operative-part paragraph/footer rows): {len(rows):,}",
          flush=True)

    stats = Counter()
    log: list[tuple] = []
    updates: list[tuple] = []  # (new_role, rowid)

    for rowid, cid, pi, role, section, text in rows:
        t = text or ""
        new_role = None
        rule = None
        if is_annex_notice(t):
            new_role = "metadata"
            rule = "annex_notice"
        elif is_signature_line(t):
            new_role = "signature"
            rule = "signature_line"
        elif is_done_line(t) and role == "paragraph":
            # already 'footer' rows are fine; only re-tag stragglers
            new_role = "metadata"
            rule = "done_line"
        if new_role and new_role != role:
            updates.append((new_role, rowid))
            stats[rule] += 1
            log.append((cid, pi, role, new_role, rule, t[:100]))

    print(f"\nRule hit-counts:")
    for k in ("annex_notice", "signature_line", "done_line"):
        print(f"  {k:18s} {stats[k]:>6,}")
    print(f"\nTotal updates queued: {len(updates):,}")

    if log_path:
        out = Path(log_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w") as f:
            f.write("case_id\tpara_idx\told_role\tnew_role\trule\ttext_preview\n")
            for cid, pi, old, new, rule, txt in log:
                f.write(
                    f"{cid}\t{pi}\t{old}\t{new}\t{rule}\t"
                    f"{(txt or '').replace(chr(9), ' ')[:120]}\n"
                )
        print(f"Wrote audit log: {out}  ({len(log):,} rows)")

    if dry_run:
        print("\nDRY RUN — no UPDATE applied.")
        return

    print(f"\napplying UPDATEs...", flush=True)
    batch = 20000
    for i in range(0, len(updates), batch):
        con.executemany(
            "UPDATE paragraphs SET row_role = ? WHERE rowid = ?",
            updates[i:i + batch],
        )
        con.commit()
    print("done.")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=DB)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--log", default="/tmp/p54_audit.tsv")
    args = ap.parse_args()
    run(args.dry_run, args.db, args.log or None)


if __name__ == "__main__":
    main()
