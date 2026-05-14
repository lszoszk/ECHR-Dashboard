"""Second-pass line-wrap reflow after the P42 heal_hpno backfilled
``hudoc_para_no`` from text prefixes.

The original reflow in P34 (``_reflow_line_wrapped``) only merges
continuation lines into a parent paragraph that already has
``hudoc_para_no``.  Pre-1995 line-wrapped DOCX where the parser's
running-max guard rejected a number (e.g. VIEZZER ¶ 10 with text
"10. According to information…" arrived after a Commission-quote
block that bumped max_para_seen to 21) leaves the parent with
``hp=None`` and the continuation lines stranded as separate rows.

P42 then backfills the parent's ``hp`` from its text prefix — but by
then the reflow phase has long since finished, so the continuation
lines stay orphaned in the DB:

    pi=180  paragraph hp=10  "10.  According to information supplied to the Court by the"
    pi=181  paragraph hp=None  "Government and the applicant's lawyer the investigation is still"
    pi=182  paragraph hp=None  "pending."

P45 walks the DB after P42 has run, finds parent rows with ``hp``
that are *immediately* followed by orphan continuation rows (same
case, same section, no ``hp``, no leading number, not a heading or
quote), and merges the orphans' text into the parent row.  Each
merge deletes the orphan row.

Conservative — stops on:
  * row in a different section,
  * row whose role is not "paragraph",
  * row whose text starts with "<digits>. " (a new numbered paragraph),
  * row whose text starts with a heading-like prefix.
"""
import re
import sqlite3

DB = "/data/echr_search.db"
NUM_RE = re.compile(r"^\s*\d+\.\s")
HEAD_RE = re.compile(
    r"^\s*(?:\([a-z]\)|\([ivx]+\)|\([α-ω]\)|[IVX]+\.|[A-Z]\.)\s"
)


def main():
    con = sqlite3.connect(DB)
    con.execute("PRAGMA journal_mode = WAL")

    rows_by_case = {}
    for case_id, rowid, pi, role, hp, text, section in con.execute(
        "SELECT case_id, rowid, para_idx, row_role, hudoc_para_no, text, section "
        "FROM paragraphs "
        "ORDER BY case_id, para_idx IS NULL, para_idx, rowid"
    ):
        rows_by_case.setdefault(case_id, []).append({
            "rowid": rowid, "pi": pi, "role": role or "",
            "hp": hp, "text": text or "", "section": section,
        })

    text_updates = []   # (new_text, rowid)
    deletes = []        # rowids
    n_merges = 0

    for case_id, rows in rows_by_case.items():
        i = 0
        while i < len(rows):
            r = rows[i]
            if r["role"] != "paragraph" or r["hp"] is None:
                i += 1
                continue
            # Found a numbered parent — sweep forward for continuations.
            merged_text = r["text"]
            j = i + 1
            consumed = []
            while j < len(rows):
                nxt = rows[j]
                if nxt["role"] != "paragraph":
                    break
                if nxt["section"] != r["section"]:
                    break
                if nxt["hp"] is not None:
                    break
                if NUM_RE.match(nxt["text"]):
                    break
                if HEAD_RE.match(nxt["text"]):
                    break
                # Looks like a continuation — merge it.
                merged_text = merged_text.rstrip() + " " + nxt["text"].lstrip()
                consumed.append(nxt["rowid"])
                j += 1
            if consumed:
                text_updates.append((merged_text, r["rowid"]))
                deletes.extend(consumed)
                n_merges += len(consumed)
            i = j if consumed else i + 1

    print(f"merging {n_merges:,} continuation rows into "
          f"{len(text_updates):,} parents")
    batch = 20000
    for i in range(0, len(text_updates), batch):
        con.executemany(
            "UPDATE paragraphs SET text = ? WHERE rowid = ?",
            text_updates[i:i + batch],
        )
        con.commit()
    for i in range(0, len(deletes), batch):
        con.executemany(
            "DELETE FROM paragraphs WHERE rowid = ?",
            [(rid,) for rid in deletes[i:i + batch]],
        )
        con.commit()
    print(f"done: {len(text_updates):,} updates, {len(deletes):,} deletes")


if __name__ == "__main__":
    main()
