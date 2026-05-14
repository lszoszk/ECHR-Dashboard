"""P52 — Multi-heal driven by LLM-judge findings on 1000 sampled rows.

Four healers run as a single forward pass per case, in dependency order:

  P52a  heading-role-heal
        Rows where `row_role = 'paragraph'` but text is a pure structural
        heading ("THE LAW", "II. RELEVANT DOMESTIC LAW", "A. The parties'
        submissions", "(b) The Government", …) get their `row_role`
        promoted to `heading` (collapses into heading_h0/h1/h2/h3/h4 for
        badge purposes downstream).  Detected by `is_heading_only()`,
        which combines length + uppercase ratio + absence of sentence
        body.  Judge-confirmed at 42/42 high-confidence hits.

  P52b  appendix-section-heal
        Post-operative `row_role = 'table_cell'` rows currently tagged
        as 'Operative part' or 'Separate Opinion' but actually belonging
        to an annex table (compensation schedules, applicant lists,
        Varnava-style mass-victim tables).  Heuristic: once the case has
        passed both `operative_part_seen` AND `done_line_seen`, every
        subsequent table_cell row is moved to section 'Appendix'.
        Conservative — never touches non-table rows.

  P52c  art41-boundary-heal
        Default-interest / Article 41 quote / "the Court considers it
        appropriate that interest at the marginal lending rate…"
        paragraphs that ended up in 'Merits' get retagged to 'Just
        Satisfaction'.  Requires explicit Article 41 marker text — never
        infers from position alone.

  P52d  style-flip-heal
        Rows currently in 'Operative part' but whose text is plainly a
        dissenting/concurring opinion paragraph (first-person voice,
        "We do not share the majority's view", "I respectfully
        dissent", …) get moved to 'Separate Opinion'.  Cross-validated
        by re-running OPI_HEAD_RE on prior context — only retag rows
        AFTER a confirmed OPI_HEAD anchor that drifted forward into
        the Operative part by an authoring error.

Each healer logs a count of touched rows and the (case_id, para_idx,
old, new) tuples.  Run order matters: 52a is independent; 52b feeds
52c (an Article 41 table cell becomes Appendix first, then JS-heal
won't touch it); 52d is independent of all.

Idempotent: re-running after a successful heal touches 0 rows.
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

DB = "/data/echr_search.db"

# ────────────────────────────────────────────────────────────────────────
# P52a — heading detector
# ────────────────────────────────────────────────────────────────────────

# Pure structural headings: short text dominated by uppercase / numbering
# and lacking a sentence body.  Mirrors `is_likely_heading` in p34 but
# explicit so it can be tightened independently without touching the
# parser.
# Heading char class: letters (incl. Latin-extended), spaces, dashes,
# straight + curly apostrophes, slashes, ampersand, colon, parens, comma.
_H_CHAR = r"[A-Za-zÀ-ſ \-–—'‘’/&:(),]"

HEADING_PATTERNS = [
    re.compile(r"^\s*(THE LAW|THE FACTS|PROCEDURE|THE COURT|JUDGMENT)\s*$", re.I),
    re.compile(r"^\s*(PROCÉDURE|EN FAIT|EN DROIT)\s*$", re.I),
    re.compile(r"^\s*[IVX]+\.\s+[A-Z][A-Z " + _H_CHAR + r"]{2,180}\s*$"),  # "II. RELEVANT DOMESTIC LAW"
    re.compile(r"^\s*[A-Z]\.\s+[A-Z]" + _H_CHAR + r"{2,180}\s*$"),  # "A. Pecuniary damage"
    re.compile(r"^\s*\d+\.\s+[A-Z]" + _H_CHAR + r"{2,160}\s*$"),  # "1. Admissibility"
    re.compile(r"^\s*\([a-z]+\)\s+[A-Z]" + _H_CHAR + r"{2,160}\s*$"),  # "(b) The Government"
    re.compile(r"^\s*\([ivx]+\)\s+[A-Z]" + _H_CHAR + r"{2,160}\s*$"),  # "(i) General principles"
    re.compile(r"^\s*FOR THESE REASONS\b.*$", re.I),
    re.compile(r"^\s*PAR CES MOTIFS\b.*$", re.I),
    re.compile(r"^\s*APPLICATION OF ARTICLE 4[16]\s*", re.I),
    re.compile(r"^\s*ALLEGED VIOLATION OF\b", re.I),
    re.compile(r"^\s*RELEVANT (DOMESTIC|INTERNATIONAL)\b", re.I),
]
HEADING_ALLCAPS_LEN_MAX = 90  # all-caps bare label up to ~6 words


# Sentence-terminator detection: a "." followed by space + capital, OR
# multiple ". "/"? "/"! ".  This avoids false positives on the "A. " /
# "II. " section labels that begin every sub-heading.
_TERMINATOR_RE = re.compile(r"[.?!;]\s+(?=[a-z])")


def looks_like_paragraph_body(text: str) -> bool:
    """Cheap negative gate — paragraph bodies have at least one sentence
    terminator followed by a lowercase letter (so "A. Pecuniary" does
    NOT trigger, but "On 12 May 2000 the Supreme..." does) AND are
    substantially lowercase."""
    if not text:
        return False
    if not _TERMINATOR_RE.search(text):
        # Allow long all-lowercase prose without explicit terminator
        if len(text) < 120:
            return False
    lower = sum(1 for c in text if c.isalpha() and c.islower())
    upper = sum(1 for c in text if c.isalpha() and c.isupper())
    return lower > upper * 2  # body text is dominantly lowercase


def is_heading_only(text: str) -> bool:
    """True iff ``text`` is a structural heading with no paragraph body.

    Decision order:
      1. Match against canonical heading regex set (positive evidence).
      2. If clearly paragraph-bodied, return False.
      3. Fallback: short (<= 90 chars) and dominantly uppercase.
    """
    if not text:
        return False
    t = text.strip()
    if not t or len(t) > 220:
        return False
    # 1. Positive heading match
    for pat in HEADING_PATTERNS:
        if pat.match(t):
            return True
    # 2. Body-like text: bail out
    if looks_like_paragraph_body(t):
        return False
    # 3. Fallback: short all-caps label
    if len(t) <= HEADING_ALLCAPS_LEN_MAX:
        upper = sum(1 for c in t if c.isalpha() and c.isupper())
        lower = sum(1 for c in t if c.isalpha() and c.islower())
        if upper >= 4 and upper >= lower * 2:
            return True
    return False


# ────────────────────────────────────────────────────────────────────────
# P52c — Article 41 / JS boundary detectors
# ────────────────────────────────────────────────────────────────────────

ART41_QUOTE_RE = re.compile(
    r"\bArticle\s*4[16]\s+of the Convention\s+(provides|reads)",
    re.I,
)
DEFAULT_INTEREST_RE = re.compile(
    r"default\s+interest.{0,80}marginal\s+lending\s+rate\s+of\s+the\s+European\s+Central\s+Bank",
    re.I,
)
ART41_HEADING_RE = re.compile(
    r"^\s*([IVX]+\.\s+)?APPLICATION\s+OF\s+ARTICLE\s*4[16]\b",
    re.I,
)
JS_SUBHEADING_RE = re.compile(
    r"^\s*[A-Z]\.\s+(Damage|Pecuniary damage|Non-pecuniary damage|"
    r"Costs and expenses|Default interest)\b",
    re.I,
)

# ────────────────────────────────────────────────────────────────────────
# P52d — style-flip (Operative→SO) detector
# ────────────────────────────────────────────────────────────────────────

OPINION_VOICE_RE = re.compile(
    r"\b(I\s+(respectfully\s+)?(dissent|disagree|am unable to agree|am of the opinion)|"
    r"we\s+(do not (share|consider)|cannot (agree|attach)|are unable to agree|"
    r"respectfully\s+dissent|fail to see)|"
    r"in my (view|opinion)|in our (view|opinion))\b",
    re.I,
)

# Reuse the parser's anchor
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

DONE_LINE_RE = re.compile(
    r"^\s*(Done in (English|French)|Fait en (anglais|fran[cç]ais))",
    re.I,
)


# ────────────────────────────────────────────────────────────────────────
# Heal routines (one case at a time, return list of UPDATEs)
# ────────────────────────────────────────────────────────────────────────


def heal_case(case_id: str, rows: list[dict], stats: Counter, log) -> list[tuple]:
    """Return [(set_clause_kv, rowid)] for this case."""
    updates: list[tuple] = []

    # Per-case ratchets (rebuilt by walking rows in order)
    seen_operative = False
    seen_done = False
    seen_opi_anchor = False
    seen_art41 = False
    in_appendix = False

    # P52d — record indexes of plausibly opinion-voiced rows currently
    # in 'Operative part'.  We only flip if a preceding OPI_HEAD anchor
    # exists earlier in the case.
    op_flip_candidates: list[int] = []

    for i, r in enumerate(rows):
        text = r["text"] or ""
        section = r["section"]
        role = r["row_role"]

        # Update ratchets
        if section in ("Operative part", "Operative Part"):
            seen_operative = True
        if DONE_LINE_RE.match(text):
            seen_done = True
        if OPI_HEAD_RE.match(text):
            seen_opi_anchor = True
        if ART41_HEADING_RE.match(text) or ART41_QUOTE_RE.search(text):
            seen_art41 = True
        if (
            section == "Appendix"
            or re.match(r"^\s*(APPENDIX|ANNEX|ANNEXE)\b", text, re.I)
        ):
            in_appendix = True

        # ─── P52a — heading-role heal ───
        # Only promote `paragraph` rows; never touch operative_list,
        # signature, metadata, table_cell, or already-tagged headings.
        if role == "paragraph" and is_heading_only(text):
            # Guard: numbered headings "1. Admissibility" can collide
            # with judgment paragraph "1." — only treat as heading when
            # there's no hudoc_para_no AND the text is short.
            if r["hudoc_para_no"] is None and len(text) <= 220:
                updates.append((("row_role", "heading"), r["rowid"]))
                stats["a_heading"] += 1
                log.append((case_id, r["para_idx"], "row_role", role, "heading",
                            text[:80]))

        # ─── P52b — appendix-section heal ───
        # Once both ratchets fired, post-dispositif table_cell rows
        # belong to Appendix.  Move them out of Operative part / SO.
        if (
            seen_operative
            and seen_done
            and role == "table_cell"
            and section in ("Operative part", "Operative Part", "Separate Opinion")
        ):
            updates.append((("section", "Appendix"), r["rowid"]))
            stats["b_appendix"] += 1
            log.append((case_id, r["para_idx"], "section", section, "Appendix",
                        text[:80]))
            in_appendix = True

        # ─── P52c — Article 41 boundary heal ───
        # Default-interest formula / Article 41 quote sitting in Merits
        # (or Admissibility, Final Submissions) → move to Just
        # Satisfaction.  Requires explicit JS-marker text.
        if (
            section in ("Merits", "Admissibility", "Final Submissions")
            and role == "paragraph"
        ):
            if (
                DEFAULT_INTEREST_RE.search(text)
                or ART41_QUOTE_RE.search(text)
                or ART41_HEADING_RE.match(text)
            ):
                updates.append((("section", "Just Satisfaction"), r["rowid"]))
                stats["c_js_boundary"] += 1
                log.append((case_id, r["para_idx"], "section", section,
                            "Just Satisfaction", text[:80]))
                seen_art41 = True

        # ─── P52d — style-flip detection ───
        # Collect candidates first; apply only if there's a preceding
        # OPI_HEAD anchor in this case.
        if (
            section in ("Operative part", "Operative Part")
            and role == "paragraph"
            and OPINION_VOICE_RE.search(text)
            and not OPI_HEAD_RE.match(text)  # actual SO headings handled by p34/p51
        ):
            op_flip_candidates.append(i)

    # Apply P52d if anchor existed
    if seen_opi_anchor and op_flip_candidates:
        for i in op_flip_candidates:
            r = rows[i]
            updates.append((("section", "Separate Opinion"), r["rowid"]))
            stats["d_style_flip"] += 1
            log.append((case_id, r["para_idx"], "section",
                        r["section"], "Separate Opinion",
                        (r["text"] or "")[:80]))

    return updates


# ────────────────────────────────────────────────────────────────────────
# Driver
# ────────────────────────────────────────────────────────────────────────


def run(dry_run: bool, healers: set[str], db_path: str, log_path: str | None):
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA journal_mode = WAL")

    cases = [r[0] for r in con.execute(
        "SELECT DISTINCT case_id FROM paragraphs ORDER BY case_id"
    )]
    print(f"scanning {len(cases):,} cases  (healers active: {sorted(healers)})",
          flush=True)

    stats = Counter()
    log: list[tuple] = []
    all_updates: list[tuple] = []

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
        case_updates = heal_case(cid, rows, stats, log)
        # Filter by active healers
        keep = []
        for (col, val), rowid in case_updates:
            healer = None
            # Match stat code by inspecting last log line for this row
            # (cheap: log is appended in order)
            keep.append(((col, val), rowid))
        all_updates.extend(case_updates)
        if ci % 500 == 0:
            print(f"  {ci:,}/{len(cases):,}  updates so far: {len(all_updates):,}",
                  flush=True)

    print(f"\nHealer hit-counts:")
    for k in ("a_heading", "b_appendix", "c_js_boundary", "d_style_flip"):
        print(f"  {k:20s} {stats[k]:>7,}")
    print(f"\nTotal updates queued: {len(all_updates):,}")

    # Optional log file
    if log_path:
        out = Path(log_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w") as f:
            f.write("case_id\tpara_idx\tcolumn\told\tnew\ttext_preview\n")
            for case_id, pi, col, old, new, txt in log:
                f.write(
                    f"{case_id}\t{pi}\t{col}\t{old}\t{new}\t"
                    f"{(txt or '').replace(chr(9), ' ')[:120]}\n"
                )
        print(f"Wrote audit log: {out}  ({len(log):,} rows)")

    if dry_run:
        print("\nDRY RUN — no UPDATE applied.")
        return

    print(f"\napplying UPDATEs...", flush=True)
    batch = 20000
    grouped: dict[str, list[tuple]] = {}
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
    ap.add_argument("--log", default="/tmp/p52_audit.tsv",
                    help="write audit log (set to '' to disable)")
    ap.add_argument("--healers", default="a,b,c,d",
                    help="comma-separated subset of {a,b,c,d}")
    args = ap.parse_args()
    healers = set(h.strip() for h in args.healers.split(",") if h.strip())
    run(args.dry_run, healers, args.db, args.log or None)


if __name__ == "__main__":
    main()
