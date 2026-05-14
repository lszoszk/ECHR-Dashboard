"""Promote body paragraphs sandwiched between two quote rows to quote.

CATT v. UK (001-189424) and similar cases quote Convention 108
verbatim with a bulleted list of categories.  The bullet rows
("- genetic data;", "- biometric data uniquely identifying a person;",
etc.) sit between the opening quote row and the closing quote row,
all in the same section, but were authored with a list style rather
than ECHR_Para_Quote.  Our parser tagged them as role=paragraph,
fragmenting the visible blockquote.

P46 walks paragraphs per case in source order.  When a row's role
flips quote → paragraph, peek ahead: if the NEXT same-section
paragraph row is again quote (within a small lookahead window) AND
the intervening paragraph row(s) don't carry a hudoc_para_no AND
their text doesn't start with a paragraph number, treat them as
sandwich-continuation of the quote block — re-tag to role=quote.

Conservative — only re-tags row whose text is short-ish, contains no
numbered prefix, and sits within 3 rows of both a preceding and
following quote in the same section.
"""
import re
import sqlite3

DB = "/data/echr_search.db"
NUM_RE = re.compile(r"^\s*\d+\.\s")
HEAD_RE = re.compile(
    r"^\s*(?:\([a-z]\)|\([ivx]+\)|\([α-ω]\)|[IVX]+\.|[A-Z]\.)\s"
)

LOOKAHEAD = 5


def main():
    con = sqlite3.connect(DB)
    con.execute("PRAGMA journal_mode = WAL")

    cases = [r[0] for r in con.execute(
        "SELECT DISTINCT case_id FROM paragraphs"
    )]
    print(f"processing {len(cases):,} cases", flush=True)

    total_promotions = 0
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

        updates = []  # rowids to promote → quote

        for i, r in enumerate(rows):
            rid, pi, role, hp, text, sec = r
            if (role or "") != "paragraph":
                continue
            if hp is not None:
                continue  # numbered ¶ is a real body paragraph
            if NUM_RE.match(text or ""):
                continue  # starts with "N. " — body
            if HEAD_RE.match(text or "") and len(text or "") < 80:
                continue  # heading-like
            if len(text or "") > 400:
                continue  # too long for a sandwich continuation

            # Look back for quote in same section within LOOKAHEAD
            prev_quote = False
            for j in range(i - 1, max(-1, i - LOOKAHEAD - 1), -1):
                pj = rows[j]
                if pj[5] != sec:
                    break  # section change blocks the sandwich
                if (pj[2] or "") == "quote":
                    prev_quote = True
                    break
                if (pj[2] or "").startswith("heading"):
                    break
            if not prev_quote:
                continue

            # Look forward for quote in same section within LOOKAHEAD
            next_quote = False
            for j in range(i + 1, min(len(rows), i + LOOKAHEAD + 1)):
                pj = rows[j]
                if pj[5] != sec:
                    break
                if (pj[2] or "") == "quote":
                    next_quote = True
                    break
                if (pj[2] or "").startswith("heading"):
                    break
            if not next_quote:
                continue

            updates.append(rid)

        if updates:
            con.executemany(
                "UPDATE paragraphs SET row_role='quote', hudoc_para_no=NULL "
                "WHERE rowid = ?",
                [(r,) for r in updates],
            )
            con.commit()
            cases_touched += 1
            total_promotions += len(updates)

        if ci % 2000 == 0:
            print(
                f"  {ci:,}/{len(cases):,}  touched={cases_touched:,}  "
                f"promotions={total_promotions:,}",
                flush=True,
            )

    print(
        f"\ndone: {total_promotions:,} sandwiched paragraphs promoted to "
        f"quote in {cases_touched:,} cases"
    )


if __name__ == "__main__":
    main()
