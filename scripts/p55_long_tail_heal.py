"""P55 — Long-tail heal driven by v3 per-template judge findings.

Four narrow patterns surfaced by the per-stratum LLM-judge sweep (v3),
each producing only a handful of false labels but concentrated in
template families the earlier P52/P54 healers didn't reach.

  P55a  art50-boundary-heal (pre-1998 cases)
        Pre-Protocol-11 judgments use **Article 50** for just
        satisfaction where modern judgments use Article 41.  P52c's
        art41 ratchet missed these, so default-interest / Article 50
        compensation paragraphs ended up in 'Merits'.

  P55b  art41-body-quote-heal (modern committee judgments)
        Committee judgments (especially Russia/Chechen-disappearance
        cluster 001-214668..670) open their just satisfaction section
        by quoting Article 41 directly — `"If the Court finds that
        there has been a violation of the Convention..."` — WITHOUT a
        preceding "Article 41 of the Convention provides" header.
        P52c's art41 trigger missed those because it required the
        introducing phrase.

  P55c  initials-signature-heal (pre-1995 templates)
        Old templates close the operative part with judge/registrar
        initials only ("G.W.", "M.-A.E.").  P54's
        looks_like_signature_block required both "Registrar" and
        "President" words — initials slip through.

  P55d  pre-1998-annex-notice-heal
        Pre-Protocol-11 annex announcements use Rule 50 § 2 + Article
        51 § 2 instead of Article 45 § 2 + Rule 74 § 2.  P54's
        ANNEX_NOTICE_RE missed the older phrasing.

Idempotent.  Apply once.
"""
from __future__ import annotations

import argparse
import re
import sqlite3
from collections import Counter
from pathlib import Path

DB = "/data/echr_search.db"

# ────────────────────────────────────────────────────────────────────────
# Patterns
# ────────────────────────────────────────────────────────────────────────

# P55a — Article 50 (pre-Protocol 11) just satisfaction triggers
ART50_QUOTE_RE = re.compile(
    r"\bArticle\s*50\s+of the Convention\s+(provides|reads)",
    re.I,
)
ART50_HEADING_RE = re.compile(
    r"^\s*([IVX]+\.\s+)?APPLICATION\s+OF\s+ARTICLE\s*50\b",
    re.I,
)
# Article 50 body text (when quoted without preface) — pre-1998 text
ART50_BODY_RE = re.compile(
    r"^\s*[\"“]?\s*If the Court finds that a decision or a measure taken by a legal authority",
    re.I,
)

# P55b — Article 41 body text (modern committee opening)
ART41_BODY_RE = re.compile(
    r"^\s*[\"“]?\s*If the Court finds that there has been a violation of the Convention",
    re.I,
)
# Committee-judgment JS indicators (text-anchored, no surrounding heading)
JS_AMOUNTS_TABLE_RE = re.compile(
    r"\bamounts\s+claimed\s+by\s+the\s+applicants?\s+under\s+the\s+head\s+of",
    re.I,
)
JS_APPENDED_TABLE_RE = re.compile(
    r"\b(amounts?\s+(detailed|indicated|listed)\s+in\s+the\s+appended\s+table"
    r"|appended\s+table\s+(detailing|listing|setting\s+out))",
    re.I,
)
JS_GOV_ART41_RE = re.compile(
    r"\bArticle\s*4[16]\s+of\s+the\s+Convention\s+should\s+be\s+applied\b",
    re.I,
)

# P55c — Initials-only signatures (pre-1995 operative tail)
# "G.W.", "M.-A.E.", "J.-P.C.", "C.L.R. S.N." etc.
# Two or more capital letters separated by dots, possibly with hyphens.
INITIALS_SIG_RE = re.compile(
    r"^\s*[A-Z]\.(?:[\-\s][A-Z]?\.?)*\s*(?:[A-Z]\.(?:[\-\s][A-Z]?\.?)*)?\s*$"
)

# Looser, more reliable variant: short text dominated by uppercase letter+period
# pattern.  Accept rows up to 30 chars where >= 70% of non-space chars match
# `[A-Z.]`.
def looks_like_initials_signature(text: str) -> bool:
    if not text:
        return False
    t = text.strip()
    if not t or len(t) > 30:
        return False
    # Need at least two periods (initials have multiple)
    if t.count(".") < 2:
        return False
    non_space = [c for c in t if not c.isspace()]
    if len(non_space) < 3:
        return False
    initialy = sum(1 for c in non_space if c.isupper() or c in ".-")
    return initialy / len(non_space) >= 0.85


# P55d — Pre-1998 annex notice
PRE98_ANNEX_NOTICE_RE = re.compile(
    r"(The following separate opinions are annexed to the present judgment"
    r"|Article\s*51\s*(?:par|para|§)\.?\s*2.*Rule\s*50\s*(?:par|para|§)\.?\s*2"
    r"|Rule\s*50\s*(?:par|para|§)\.?\s*2.*Article\s*51\s*(?:par|para|§)\.?\s*2)",
    re.I,
)
# Bullet items listing the annexed opinions: "- dissenting opinion of Mr. X;"
OPINION_BULLET_RE = re.compile(
    r"^\s*[\-–—•]\s*(joint\s+)?(partly\s+)?"
    r"(concurring|dissenting|separate)(?:\s*,\s*partly\s+(?:concurring|dissenting))?"
    r"\s+opinion\s+of\s+",
    re.I,
)

# P54 patterns reused
DONE_LINE_RE = re.compile(
    r"^\s*(Done in (English|French)|Fait en (anglais|fran[cç]ais))",
    re.I,
)


# ────────────────────────────────────────────────────────────────────────
# Heal logic
# ────────────────────────────────────────────────────────────────────────


def heal_case(case_id: str, rows: list[dict], stats: Counter, log: list):
    """Return list of (column, new_value, rowid) updates."""
    updates = []

    # P55a/b — JS boundary forward-only ratchet (extending P52c).
    # Trip the ratchet on:
    #   - Article 50 quote header / body text  (P55a)
    #   - Article 41 body text (committee opening, no preface)  (P55b)
    #   - JS-content phrases like "amounts claimed under the head of"
    art_seen = False
    operative_seen = False
    done_seen = False

    for r in rows:
        text = r["text"] or ""
        section = r["section"]
        role = r["row_role"]

        if section in ("Operative part", "Operative Part"):
            operative_seen = True
        if DONE_LINE_RE.match(text):
            done_seen = True

        # Check if this row trips the JS ratchet (idempotent — only trips
        # forward, never back to Merits).
        if not art_seen and not operative_seen:
            trips = (
                ART50_HEADING_RE.match(text)
                or ART50_QUOTE_RE.search(text)
                or ART50_BODY_RE.match(text)
                or ART41_BODY_RE.match(text)
                or JS_AMOUNTS_TABLE_RE.search(text)
                or JS_APPENDED_TABLE_RE.search(text)
                or JS_GOV_ART41_RE.search(text)
            )
            if trips and section in ("Merits", "Admissibility", "Final Submissions"):
                # Flip THIS row and all subsequent merits-section rows
                # to Just Satisfaction (until OPI_HEAD / operative).
                art_seen = True
                updates.append((("section", "Just Satisfaction"), r["rowid"]))
                stats["a_b_js_boundary"] += 1
                log.append((case_id, r["para_idx"], "section", section,
                            "Just Satisfaction", text[:80]))
                continue

        if art_seen and section in ("Merits", "Admissibility", "Final Submissions"):
            # Once tripped, drag forward until we hit operative/SO
            updates.append((("section", "Just Satisfaction"), r["rowid"]))
            stats["a_b_js_boundary"] += 1
            log.append((case_id, r["para_idx"], "section", section,
                        "Just Satisfaction", text[:80]))
            continue

        # Reset art_seen when we cross into operative — JS section is done
        if section in ("Operative part", "Operative Part"):
            art_seen = False

        # ─── P55c — initials signatures in Operative part ───
        if (
            section in ("Operative part", "Operative Part")
            and role in ("paragraph", "footer")
            and looks_like_initials_signature(text)
        ):
            updates.append((("row_role", "signature"), r["rowid"]))
            stats["c_initials_sig"] += 1
            log.append((case_id, r["para_idx"], "row_role", role,
                        "signature", text[:80]))
            continue

        # ─── P55d — Pre-1998 annex notice + opinion-bullet items ───
        if (
            section in ("Operative part", "Operative Part")
            and role in ("paragraph", "footer")
            and (
                PRE98_ANNEX_NOTICE_RE.search(text)
                or OPINION_BULLET_RE.match(text)
            )
        ):
            updates.append((("row_role", "metadata"), r["rowid"]))
            stats["d_pre98_annex"] += 1
            log.append((case_id, r["para_idx"], "row_role", role,
                        "metadata", text[:80]))
            continue

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
            {
                "rowid": r[0], "para_idx": r[1], "hudoc_para_no": r[2],
                "row_role": r[3], "section": r[4], "text": r[5],
            }
            for r in con.execute(
                "SELECT rowid, para_idx, hudoc_para_no, row_role, section, text "
                "FROM paragraphs WHERE case_id = ? "
                "ORDER BY para_idx IS NULL, para_idx, rowid",
                (cid,),
            )
        ]
        if not rows:
            continue
        all_updates.extend(heal_case(cid, rows, stats, log))
        if ci % 1000 == 0:
            print(f"  {ci:,}/{len(cases):,}  updates: {len(all_updates):,}",
                  flush=True)

    print(f"\nHealer hit-counts:")
    for k in ("a_b_js_boundary", "c_initials_sig", "d_pre98_annex"):
        print(f"  {k:20s} {stats[k]:>7,}")
    print(f"\nTotal updates queued: {len(all_updates):,}")

    if log_path:
        out = Path(log_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w") as f:
            f.write("case_id\tpara_idx\tcolumn\told\tnew\ttext_preview\n")
            for cid, pi, col, old, new, txt in log:
                f.write(
                    f"{cid}\t{pi}\t{col}\t{old}\t{new}\t"
                    f"{(txt or '').replace(chr(9), ' ')[:120]}\n"
                )
        print(f"Wrote audit log: {out}  ({len(log):,} rows)")

    if dry_run:
        print("\nDRY RUN — no UPDATE applied.")
        return

    print(f"\napplying UPDATEs...", flush=True)
    batch = 20000
    grouped: dict = {}
    for (col, val), rowid in all_updates:
        grouped.setdefault(col, []).append((val, rowid))
    for col, pairs in grouped.items():
        for i in range(0, len(pairs), batch):
            con.executemany(
                f"UPDATE paragraphs SET {col} = ? WHERE rowid = ?",
                pairs[i:i + batch],
            )
            con.commit()
        print(f"  {col:12s} applied {len(pairs):,}")
    print("done.")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=DB)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--log", default="/tmp/p55_audit.tsv")
    args = ap.parse_args()
    run(args.dry_run, args.db, args.log or None)


if __name__ == "__main__":
    main()
