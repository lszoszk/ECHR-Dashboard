"""P58 — Logical-paragraph backfill.

ECHR judgments store one `paragraphs` row per *physical* line: the
numbered body paragraph, but also every bullet / dash item, every nested
quote, and every continuation fragment the segmenter detached.  Only the
numbered body row carries a `hudoc_para_no`; the fragments have NULL.

Full-text search returns ONLY the rows that matched the query.  When a
query matches a lone bullet ("- biometric data uniquely identifying a
person;") the result card shows that fragment by itself, labelled
`¶ —`, with no parent context — it looks broken.

P58 reconstructs, once, the *logical paragraph* each physical row
belongs to and writes two columns:

  logical_para_idx  — the `para_idx` of the body ¶ this row belongs to.
                      A body ¶ points to itself; a bullet / quote /
                      continuation points to its parent body ¶.  This is
                      a per-case index (para_idx is unique within a
                      case), so the parent row is found with
                      `JOIN paragraphs parent
                         ON parent.case_id = p.case_id
                        AND parent.para_idx = p.logical_para_idx`.

  display_para_no   — the HUDOC ¶ number to show in the UI: the row's
                      own `hudoc_para_no`, or the parent's when the row
                      is a fragment.  NULL only for headings and for
                      orphan fragments with no numbered antecedent.

`compute_logical_para()` is the single source of truth — it is a port
of `enrichContinuationParaNos()` in docs/assets/search-app.js and is
also imported by p34_rebuild_from_hudoc.py so rebuilds stay consistent.

The script adds the two columns if missing, then backfills the whole
corpus.  Idempotent.
"""
from __future__ import annotations

import argparse
import re
import sqlite3
from pathlib import Path

DB = "/data/echr_search.db"

# Row roles that break the continuation chain — a heading / signature /
# table cell is its own logical unit and cannot be a continuation of the
# paragraph above it.
_HEADING_ROLES = {"metadata", "signature", "footer", "table_cell"}


def _is_heading_row(role: str, text: str) -> bool:
    """A row that breaks the continuation chain."""
    if role:
        if role == "heading" or role.startswith("heading"):
            return True
        if role in _HEADING_ROLES:
            return True
    # Backstop: a paragraph-role row whose text is a short all-caps
    # structural heading the role-heal (P52a) didn't promote
    # ("THE LAW", "PROCEDURE", "II. RELEVANT DOMESTIC LAW").  Quote rows
    # are exempt — their elision markers ("...") look all-caps.
    if role != "quote" and text:
        t = text.strip()
        if 0 < len(t) <= 60 and t == t.upper() and any(c.isalpha() for c in t):
            return True
    return False


def compute_logical_para(rows: list[dict]) -> list[dict]:
    """Set `logical_para_idx` and `display_para_no` on each row.

    `rows` is one case, ordered by document position.  Each dict needs
    `para_idx`, `hudoc_para_no`, `row_role`, `section`, `text`.  Mutated
    in place; returns the same list.  Idempotent.
    """
    last_num_idx = None        # para_idx of the most-recent numbered ¶
    last_num_no = None         # its hudoc_para_no
    last_section = object()    # sentinel — differs from any real section
    pending: list[dict] = []   # orphans parked before the first numbered ¶

    def flush(parent_no: int) -> None:
        for pr in pending:
            pr["display_para_no"] = parent_no
            pr["logical_para_idx"] = pr.get("para_idx")
        pending.clear()

    for r in rows:
        pidx = r.get("para_idx")
        r["logical_para_idx"] = pidx
        r["display_para_no"] = None

        sec = r.get("section")
        if sec != last_section:
            # Section boundary — abandon unplaceable orphans, reset chain.
            pending.clear()
            last_section = sec
            last_num_idx = None
            last_num_no = None

        role = r.get("row_role") or ""
        text = r.get("text") or ""

        if _is_heading_row(role, text):
            last_num_idx = None
            last_num_no = None
            pending.clear()
            continue  # heading is its own unit; display_para_no stays NULL

        hp = r.get("hudoc_para_no")
        if hp is not None:
            # Out-of-order guard: a numbered ¶ N appearing far from the
            # most-recent ¶ M in the same section is almost always a
            # fragment of M's running text where "N." was mis-tokenised
            # as a paragraph start ("§ 2 of the Convention", "(see
            # paragraph N above)").
            stripped = re.sub(r"^\d+\.\s+", "", text)[:12]
            looks_mid = bool(re.match(r"^[§(),·]", stripped)) or bool(
                re.match(r"^[a-z]", stripped))
            back_jump = last_num_no is not None and hp + 5 <= last_num_no
            fwd_jump = (last_num_no is not None
                        and hp >= last_num_no + 4 and looks_mid)
            if back_jump or fwd_jump:
                r["logical_para_idx"] = last_num_idx
                r["display_para_no"] = last_num_no
                continue
            # First numbered ¶ after a run of orphans → orphans are the
            # detached tail of (N − 1).
            if pending and last_num_idx is None:
                flush(max(1, hp - 1))
            last_num_idx = pidx
            last_num_no = hp
            r["logical_para_idx"] = pidx
            r["display_para_no"] = hp
        elif last_num_idx is not None:
            # Continuation / bullet / quote of the current numbered ¶.
            r["logical_para_idx"] = last_num_idx
            r["display_para_no"] = last_num_no
        else:
            # Orphan with no numbered antecedent yet — park it; flush()
            # fills both fields when the first numbered ¶ appears.
            pending.append(r)
    return rows


def ensure_columns(con: sqlite3.Connection) -> None:
    cols = {r[1] for r in con.execute("PRAGMA table_info(paragraphs)")}
    if "logical_para_idx" not in cols:
        con.execute("ALTER TABLE paragraphs ADD COLUMN logical_para_idx INTEGER")
    if "display_para_no" not in cols:
        con.execute("ALTER TABLE paragraphs ADD COLUMN display_para_no INTEGER")
    # Composite index backs the parent-row JOIN the search API issues
    # (parent.case_id = p.case_id AND parent.para_idx = p.logical_para_idx).
    con.execute(
        "CREATE INDEX IF NOT EXISTS idx_paragraphs_case_para "
        "ON paragraphs(case_id, para_idx)"
    )
    con.commit()


def run(dry_run: bool, db_path: str) -> None:
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA journal_mode = WAL")
    ensure_columns(con)

    cases = [r[0] for r in con.execute(
        "SELECT DISTINCT case_id FROM paragraphs ORDER BY case_id"
    )]
    print(f"scanning {len(cases):,} cases", flush=True)

    updates: list = []
    n_display = n_fragment = 0

    for ci, cid in enumerate(cases, 1):
        rows = [
            {"rowid": r[0], "para_idx": r[1], "hudoc_para_no": r[2],
             "section": r[3], "row_role": r[4], "text": r[5]}
            for r in con.execute(
                "SELECT rowid, para_idx, hudoc_para_no, section, row_role, text "
                "FROM paragraphs WHERE case_id = ? "
                "ORDER BY para_idx IS NULL, para_idx, rowid",
                (cid,),
            )
        ]
        if not rows:
            continue
        compute_logical_para(rows)
        for r in rows:
            updates.append((r["logical_para_idx"], r["display_para_no"],
                            r["rowid"]))
            if r["display_para_no"] is not None:
                n_display += 1
            if r["logical_para_idx"] != r["para_idx"]:
                n_fragment += 1
        if ci % 2000 == 0:
            print(f"  {ci:,}/{len(cases):,}  rows queued: {len(updates):,}",
                  flush=True)

    print(f"\nRows total:                 {len(updates):,}")
    print(f"Rows with display_para_no:  {n_display:,}")
    print(f"Fragment rows (re-parented):{n_fragment:,}")

    if dry_run:
        print("\nDRY RUN — no UPDATE applied.")
        return

    print("\napplying UPDATEs...", flush=True)
    batch = 20000
    for i in range(0, len(updates), batch):
        con.executemany(
            "UPDATE paragraphs SET logical_para_idx = ?, display_para_no = ? "
            "WHERE rowid = ?",
            updates[i:i + batch],
        )
        con.commit()
    print(f"  applied {len(updates):,}")
    print("done.")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=DB)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    run(args.dry_run, args.db)


if __name__ == "__main__":
    main()
