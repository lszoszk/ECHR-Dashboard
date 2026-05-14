"""Detect and re-tag inline-numbered quote blocks ("13. ...", "14. ...").

Pre-1998 ECHR judgments routinely embed extensive verbatim extracts
from the European Commission of Human Rights report.  The author opens
the block with an inline ``"<N>.<space>text"`` quotation, lists
paragraphs N, N+1, … (sometimes spanning ten or more), then closes
with a matching ``"``.  Our parser saw "14. Suspicions concerning…"
as a fresh main-judgment ¶ 14, even though the digits belong to the
Commission's own numbering, NOT the Court's.

In VIEZZER v. ITALY (001-57663) this gives the Court a fake "¶ 14"
through "¶ 21" that duplicate the Commission text but should instead
render as a single indented blockquote.  Visible cost is twofold:
(a) the modal labels Court ¶ 14 with the wrong content, and (b) the
real Court ¶ 14 in "AS TO THE LAW" sits beside a phantom paragraph
also numbered 14 in "AS TO THE FACTS".

Detection
---------
For each case, walk paragraphs in para_idx order.  When a row's text
contains ``["“]\s*(\d+)\.\s`` somewhere PAST the first 50 chars (i.e.
the opening of an inline numbered quote, not the row's own leading
number), enter quote mode and remember the first quoted number N.
While in quote mode, every subsequent row whose ``hudoc_para_no`` is
exactly N+offset is re-tagged ``row_role='quote'`` with
``hudoc_para_no=NULL``.  We stop when:

  * a row's text ends with a closing ``"`` / ``"`` mark, or
  * the next expected number is skipped (e.g. ¶ 22 doesn't appear),
  * a heading row is encountered.

Conservative: only re-tags rows whose body content matches the
sequential quote pattern.  A heading or unrelated body row breaks
the streak immediately.
"""
import re
import sqlite3

DB = "/data/echr_search.db"
# Opening of an inline numbered quote: " then digits + period + space.
QUOTE_OPEN_RE = re.compile(r'[“"]\s*(\d+)\.\s')
# Closing quote mark — straight or curly closing.
CLOSING_QUOTE_RE = re.compile(r'[”"]\s*[.;,]?\s*$')


def main():
    con = sqlite3.connect(DB)
    con.execute("PRAGMA journal_mode = WAL")

    # Pull all paragraphs grouped by case.
    rows_by_case = {}
    for case_id, rowid, pi, role, hp, text, section in con.execute(
        "SELECT case_id, rowid, para_idx, row_role, hudoc_para_no, text, section "
        "FROM paragraphs "
        "ORDER BY case_id, para_idx IS NULL, para_idx, rowid"
    ):
        rows_by_case.setdefault(case_id, []).append({
            "rowid": rowid, "pi": pi, "role": role, "hp": hp,
            "text": text or "", "section": section,
        })

    n_cases_touched = 0
    n_rows_retagged = 0
    updates = []

    for case_id, rows in rows_by_case.items():
        in_quote = False
        next_expected = None
        touched_in_this_case = False

        for r in rows:
            text = r["text"]
            role = r["role"] or ""

            if in_quote:
                # Are we still in the quoted block?  Stop on heading or
                # if the next row's hpno breaks the expected sequence.
                if role.startswith("heading"):
                    in_quote = False
                    next_expected = None
                elif r["hp"] is not None and r["hp"] == next_expected:
                    # In-sequence quoted paragraph — re-tag.
                    updates.append((r["rowid"],))
                    n_rows_retagged += 1
                    touched_in_this_case = True
                    next_expected += 1
                    # Close if this row ends with a closing quote.
                    if CLOSING_QUOTE_RE.search(text.rstrip()):
                        in_quote = False
                        next_expected = None
                elif r["hp"] is not None and r["hp"] != next_expected:
                    # Out-of-sequence number → quote already ended.
                    in_quote = False
                    next_expected = None
                # Continuation rows without hpno are merged into prev
                # by reflow; they should not appear here, but if they
                # do, just stay in quote mode silently.
                continue

            # Not in quote — look for opening quote mark.
            m = QUOTE_OPEN_RE.search(text[50:])  # past row's own "N. "
            if m:
                start_n = int(m.group(1))
                # Next expected quoted paragraph is start_n + 1
                in_quote = True
                next_expected = start_n + 1
                # Note: the opener row itself stays as-is (it contains
                # the host paragraph text PLUS the start of the quote).
                # Splitting it would require text surgery that's deeper
                # than this single-pass recovery.

        if touched_in_this_case:
            n_cases_touched += 1

    print(f"Found {n_rows_retagged:,} rows in {n_cases_touched:,} cases "
          f"matching inline-quote-block pattern")
    batch = 20000
    for i in range(0, len(updates), batch):
        con.executemany(
            "UPDATE paragraphs SET row_role='quote', hudoc_para_no=NULL "
            "WHERE rowid=?",
            updates[i:i + batch],
        )
        con.commit()
    print(f"Re-tagged {len(updates):,} rows → row_role='quote', hpno=NULL")


if __name__ == "__main__":
    main()
