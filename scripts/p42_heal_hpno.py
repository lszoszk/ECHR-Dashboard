"""Self-healing pass: re-extract hudoc_para_no from text and reconcile
with the stored value.

For each ``paragraphs`` row whose text starts with ``"<digits>.<space>"``,
take the digits as the truth.  If they differ from ``hudoc_para_no`` in
the row, overwrite.  This corrects the X6 anomaly where apply_extract's
robust_key fallback collided across paragraphs that differed only by
their leading number (e.g. 24 ECODEFENCE rows all stamped 641).
"""
import re
import sqlite3
import sys

DB = "/data/echr_search.db"
NUM_RE = re.compile(r"^\s*(\d+)\.\s")


def main():
    con = sqlite3.connect(DB)
    con.execute("PRAGMA journal_mode = WAL")

    cur = con.execute(
        "SELECT rowid, text, hudoc_para_no, row_role FROM paragraphs"
    )
    updates = []
    nulls = []
    n_seen = 0
    n_misalign = 0
    n_null_phantom = 0
    for rowid, text, hp, role in cur:
        n_seen += 1
        if not text:
            continue
        # Skip rows we know shouldn't have a leading-N prefix style.
        # ``quote`` rows are critical here — the leading digit of a
        # quoted "13. After an investigation…" belongs to the source
        # document being quoted (e.g. the Commission's Article 31
        # report), not to the Court's own paragraph counter.  Quote
        # rows must always render with hpno = NULL.
        if role in ("table_cell", "metadata", "footer", "signature",
                    "heading", "heading_h0", "heading_h1", "heading_h2",
                    "heading_h3", "heading_h4", "operative_list",
                    "quote"):
            # Heading / quote phantoms — null them if they're set.
            if hp is not None and (
                role.startswith("heading") or role == "quote"
            ):
                nulls.append((rowid,))
                n_null_phantom += 1
            continue
        m = NUM_RE.match(text)
        text_n = int(m.group(1)) if m else None
        if text_n is None:
            # Row text has no leading "N. " — if hpno is set, it's
            # plausibly correct from an earlier-extracted source
            # (e.g. <w:fldSimple> auto-numbered ¶s where the prefix
            # was never inlined).  Leave it alone.
            continue
        # Text has explicit "N. " — that's the truth.
        if hp != text_n:
            updates.append((text_n, rowid))
            n_misalign += 1
        if n_seen % 500000 == 0:
            print(
                f"  scanned {n_seen:,}  misaligned {n_misalign:,}  "
                f"heading-phantoms {n_null_phantom:,}",
                flush=True,
            )

    print(
        f"\nFound {n_misalign:,} hpno misalignments + "
        f"{n_null_phantom:,} residual heading phantoms",
        flush=True,
    )
    batch = 20000
    for i in range(0, len(updates), batch):
        con.executemany(
            "UPDATE paragraphs SET hudoc_para_no = ? WHERE rowid = ?",
            updates[i:i + batch],
        )
        con.commit()
    for i in range(0, len(nulls), batch):
        con.executemany(
            "UPDATE paragraphs SET hudoc_para_no = NULL WHERE rowid = ?",
            nulls[i:i + batch],
        )
        con.commit()
    print(f"applied {len(updates):,} corrections + {len(nulls):,} NULLs")


if __name__ == "__main__":
    main()
