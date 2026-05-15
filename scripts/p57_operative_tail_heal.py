"""P57 — Operative-tail heal: move the post-dispositif tail of the
Operative part section into Appendix.

The v4 per-template judge sweep left a residual cluster of
operative-bleed / annex-confusion false labels — rows that sit AFTER
the dispositif but are still labelled `section = 'Operative part'`:
registrar/president signature blocks, "Done in English …" footers,
"APPENDIX" / "ANNEX I/II" headings, annex notices, applicant-list
entries, annex table cells.

The dispositif itself is a contiguous run of `row_role =
'operative_list'` rows.  P57 walks the rows AFTER the last
operative_list row and retags the *unambiguous* tail material to
section = 'Appendix' (bucket META in the researcher view).

CRITICAL — selectivity.  A naive "everything after the last
operative_list → Appendix" rule is wrong: separate-opinion content
that never received an OPI_HEAD anchor sits in 'Operative part' after
the dispositif, and a blanket sweep mis-files it as Appendix.  P57
therefore only moves rows that are unambiguously tail material:

  MOVE:
    - row_role in (signature, footer, metadata, table_cell)
    - row_role heading* whose text is APPENDIX / ANNEX / judge-initials
    - row_role paragraph matching an annex-notice / opinion-bullet /
      done-line pattern, OR (once an ANNEX/APPENDIX heading has been
      seen) short non-sentence rows that are clearly table titles

  LEAVE (never touch):
    - operative_list rows (the genuine dispositif)
    - rows carrying a hudoc_para_no (numbered judgment/opinion ¶)
    - opinion-voiced paragraphs ("we share", "in my view", …)
    - quote rows
    - plain prose paragraphs with sentence structure

Stops at the first 'Separate Opinion' row.  Skips cases with no
dispositif.  Idempotent.
"""
from __future__ import annotations

import argparse
import re
import sqlite3
from collections import Counter
from pathlib import Path

DB = "/data/echr_search.db"
OPERATIVE_SECTIONS = ("Operative part", "Operative Part")

# Annex / appendix heading
ANNEX_HEAD_RE = re.compile(r"^\s*(APPENDIX|ANNEX(\s+[IVX]+)?|ANNEXE)\b", re.I)

# Annex-notice paragraphs (modern + pre-1998 variants)
ANNEX_NOTICE_RE = re.compile(
    r"(In accordance with\s+Article\s*(45|51)\s*§?\s*2"
    r"|Conform[ée]ment\s+(?:à\s+)?l['’]article\s*(45|51)\s*§?\s*2"
    r"|The following separate opinions are annexed)",
    re.I,
)

# Opinion-bullet list items: "(b) dissenting opinion of Judge X;"
OPINION_BULLET_RE = re.compile(
    r"^\s*(\([a-z]\)\s*)?[\-–—•]?\s*(joint\s+)?(partly\s+)?"
    r"(concurring|dissenting|separate)(?:\s*,\s*partly\s+(?:concurring|dissenting))?"
    r"\s+opinion\s+of\s+",
    re.I,
)

DONE_LINE_RE = re.compile(
    r"^\s*(Done in (English|French)|Fait en (anglais|fran[cç]ais))", re.I,
)

# Applicant-list entry: "Ms Aza Vakhayevna Tseltsayeva, born in 1976;"
APPLICANT_ENTRY_RE = re.compile(r"\bborn\s+in\s+\d{4}\b", re.I)

# Opinion voice — paragraphs we must NOT sweep into Appendix
OPINION_VOICE_RE = re.compile(
    r"\b(I\s+(respectfully\s+)?(dissent|disagree|am unable to agree|"
    r"am of the opinion|share|voted)|we\s+(share|do not|cannot|are unable|"
    r"voted|had no)|in my (view|opinion)|in our (view|opinion)|"
    r"my (general remarks|view|opinion))\b",
    re.I,
)


def looks_like_initials(text: str) -> bool:
    """Judge initials like 'G. W.' or 'J.-P.C. M.O'B.'"""
    if not text:
        return False
    t = text.strip()
    if not t or len(t) > 30:
        return False
    if t.count(".") < 2:
        return False
    non_space = [c for c in t if not c.isspace()]
    if len(non_space) < 3:
        return False
    initialy = sum(1 for c in non_space if c.isupper() or c in ".-'")
    return initialy / len(non_space) >= 0.85


def is_short_titleish(text: str) -> bool:
    """Short row with no sentence terminator — likely an annex table
    title ('The Court's awards in respect of pecuniary damage')."""
    if not text:
        return False
    t = text.strip()
    if not t or len(t) > 90:
        return False
    return not re.search(r"[.?!]\s", t)


def heal_case(case_id: str, rows: list[dict], stats: Counter, log: list):
    updates = []
    last_op = None
    for i, r in enumerate(rows):
        if (
            r["row_role"] == "operative_list"
            and r["section"] in OPERATIVE_SECTIONS
        ):
            last_op = i
    if last_op is None:
        return updates

    annex_sticky = False
    for i in range(last_op + 1, len(rows)):
        r = rows[i]
        sec = r["section"]
        if sec == "Separate Opinion":
            break
        if sec not in OPERATIVE_SECTIONS:
            continue
        role = r["row_role"] or ""
        text = r["text"] or ""
        rule = None

        if role in ("signature", "footer", "metadata", "table_cell"):
            rule = f"role_{role}"
        elif role.startswith("heading"):
            if ANNEX_HEAD_RE.match(text):
                rule = "annex_heading"
                annex_sticky = True
            elif looks_like_initials(text):
                rule = "initials_heading"
        elif role == "operative_list":
            continue  # genuine dispositif — leave
        elif role == "paragraph":
            if r["hudoc_para_no"] is not None:
                continue  # numbered judgment ¶ — never appendix
            if OPINION_VOICE_RE.search(text):
                continue  # stray separate-opinion content — leave
            if (
                ANNEX_NOTICE_RE.search(text)
                or OPINION_BULLET_RE.match(text)
                or DONE_LINE_RE.match(text)
                or APPLICANT_ENTRY_RE.search(text)
            ):
                rule = "annex_paragraph"
            elif annex_sticky and is_short_titleish(text):
                rule = "annex_table_title"
        # quote rows and everything else: leave

        if rule:
            updates.append((("section", "Appendix"), r["rowid"]))
            stats[rule] += 1
            log.append((case_id, r["para_idx"], sec, "Appendix",
                        role, rule, text[:80]))
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
        all_updates.extend(heal_case(cid, rows, stats, log))
        if ci % 2000 == 0:
            print(f"  {ci:,}/{len(cases):,}  updates: {len(all_updates):,}",
                  flush=True)

    print(f"\nHealer hit-counts by rule:")
    for k, n in stats.most_common():
        print(f"  {k:20s} {n:>7,}")
    print(f"\nTotal updates queued: {len(all_updates):,}")

    if log_path:
        out = Path(log_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w") as f:
            f.write("case_id\tpara_idx\told\tnew\trow_role\trule\ttext_preview\n")
            for cid, pi, old, new, role, rule, txt in log:
                f.write(
                    f"{cid}\t{pi}\t{old}\t{new}\t{role}\t{rule}\t"
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
    ap.add_argument("--log", default="/tmp/p57_audit.tsv")
    args = ap.parse_args()
    run(args.dry_run, args.db, args.log or None)


if __name__ == "__main__":
    main()
