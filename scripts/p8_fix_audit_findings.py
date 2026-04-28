"""
P8 RELABEL: fix systematic errors identified by Sonnet 4.6 precision audit.

Three error patterns from docs/methodology/precision-audit.md:

R1 — Just Satisfaction over-capture of dispositif clauses (P1 origin)
  Paragraphs like "8. Dismisses the remainder of the applicants' claim
  for just satisfaction;" are dispositif (Operative Part), not reasoning.

R2 — Operative Part sub-clauses stranded in Merits (P4 origin)
  In Pop C cases, payment items "(a) that the respondent State is to
  pay...", "(b) that from the expiry of the above-mentioned three months
  until settlement..." are operative dispositif, but P4 grabbed them as
  Merits because no separating heading.

R3 — Article 41 sub-headings still in Merits (P5 pipeline ordering)
  When P5 ran before P1 had relabeled an entire Article 41 block,
  paragraphs like "A. Damage 70. The applicant claimed..." propagated
  the residual Merits label rather than Just Satisfaction.

Usage:
  python p8_fix_audit_findings.py            # dry-run
  python p8_fix_audit_findings.py --apply    # commit
"""
import sqlite3
import sys
import re

DRY_RUN = "--apply" not in sys.argv
DB = "/data/echr_search.db"

# ── R1: Just Satisfaction → Operative Part for dispositif clauses ─────────
# Match short paragraphs starting with numbered dispositif verbs that ended
# up in Just Satisfaction.  Order matters: must start at paragraph beginning.
R1_RE = re.compile(
    r"^\s*\d+\.\s*(Dismisses|Decides|Declares|Holds)\b",
    re.IGNORECASE,
)
R1_MAX_LEN = 400  # dispositif clauses are usually short

# ── R2: Merits → Operative Part for operative sub-clauses (Pop C only) ────
# Sub-clause format: starts with "(a) that...", "(b) that...", "(i) in respect..."
# combined with operative keywords (respondent State, to pay, EUR, default
# interest).  Length cap because dispositif sub-clauses are short.
R2_PREFIX_RE = re.compile(
    r"^\s*\([a-z]\)\s+(that|in respect|from the expiry)\b",
    re.IGNORECASE,
)
R2_KEYWORDS_RE = re.compile(
    r"\b(respondent State|to pay|default interest|EUR\s*\d|euros?)\b",
    re.IGNORECASE,
)
R2_MAX_LEN = 600

# Roman-numeral payment sub-clauses too: "(i) in respect of pecuniary..."
R2_ROMAN_RE = re.compile(
    r"^\s*\((i+|iv|v|vi+|ix|x)\)\s+",
    re.IGNORECASE,
)

# ── R3: Merits → Just Satisfaction for Article 41 sub-heading paragraphs ──
# Sub-headings inside an Article 41 block.  These often appear glued with
# the first content paragraph (e.g. "A. Damage 70. The applicant claimed...")
R3_SUBHEADING_RE = re.compile(
    r"^\s*[A-D]\.\s+(Damage|Costs and expenses|Default interest|Pecuniary"
    r"|Non-pecuniary|Pecuniary damage|Non-pecuniary damage)\b",
    re.IGNORECASE,
)
# Also: paragraph containing canonical Article 41 quote that ended up in Merits
R3_ART41_QUOTE_RE = re.compile(
    r"Article\s+41\s+of\s+the\s+Convention\s+provides",
    re.IGNORECASE,
)

# Block-end patterns (same as P5)
END_RE = re.compile(
    r"(\b(FOR THESE REASONS|OPERATIVE PROVISIONS)\b)"
    r"|(^\s*\d+\.\s*(Decides|Declares|Holds|Dismisses)\b)",
    re.IGNORECASE,
)
HARD_ENDERS = frozenset({
    "Operative Part", "Operative part",
    "Separate Opinion", "Appendix", "Article 46",
})

if DRY_RUN:
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
else:
    conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

relabels = {}  # rowid -> new section
counts = {"R1": 0, "R2": 0, "R3_direct": 0, "R3_continuation": 0}

# ─────────────────────────────────────────────────────────────────────
# R1: Just Satisfaction → Operative Part for dispositif clauses
# ─────────────────────────────────────────────────────────────────────
print("── R1: Just Satisfaction → Operative Part (dispositif) ──")
cur.execute("""
    SELECT rowid, text FROM paragraphs
    WHERE section = 'Just Satisfaction'
      AND length(text) < ?
""", (R1_MAX_LEN,))
for r in cur.fetchall():
    text = r["text"] or ""
    if R1_RE.match(text):
        # Extra safety: must contain dispositif verb at very start
        relabels[r["rowid"]] = "Operative Part"
        counts["R1"] += 1
print(f"  Detected: {counts['R1']:,}")

# ─────────────────────────────────────────────────────────────────────
# R2: Merits → Operative Part for operative sub-clauses (Pop C only)
# ─────────────────────────────────────────────────────────────────────
print("\n── R2: Merits → Operative Part (Pop C operative sub-clauses) ──")
cur.execute("""
    SELECT rowid, text FROM paragraphs
    WHERE section = 'Merits'
      AND para_idx IS NULL
      AND length(text) < ?
""", (R2_MAX_LEN,))
for r in cur.fetchall():
    text = r["text"] or ""
    has_prefix = R2_PREFIX_RE.match(text) or R2_ROMAN_RE.match(text)
    if has_prefix and R2_KEYWORDS_RE.search(text):
        relabels[r["rowid"]] = "Operative Part"
        counts["R2"] += 1
print(f"  Detected: {counts['R2']:,}")

# ─────────────────────────────────────────────────────────────────────
# R3: Merits → Just Satisfaction (stranded Article 41 sub-headings)
# ─────────────────────────────────────────────────────────────────────
# Strategy: walk each Pop C case in rowid order. Find Merits paragraphs
# matching either (a) Article 41 sub-heading pattern OR (b) the canonical
# Article 41 quote. From there, propagate forward through subsequent
# Merits paragraphs (not yet operative dispositif via R2) until block ends.
print("\n── R3: Merits → Just Satisfaction (stranded Art.41 sub-blocks) ──")

cur.execute("SELECT DISTINCT case_id FROM paragraphs WHERE para_idx IS NULL")
case_ids = [r[0] for r in cur.fetchall()]

cur2 = conn.cursor()
for case_id in case_ids:
    cur2.execute("""
        SELECT rowid, section, text FROM paragraphs
        WHERE case_id=? AND para_idx IS NULL
        ORDER BY rowid
    """, (case_id,))
    paras = cur2.fetchall()

    active = False
    for p in paras:
        sec = p["section"]
        text = p["text"] or ""
        rowid = p["rowid"]

        # Hard ends
        if sec in HARD_ENDERS:
            active = False
            continue
        if len(text) < 200 and END_RE.search(text):
            active = False
            continue

        # Trigger detection on Merits paragraphs (this is where R3 fixes happen)
        if sec == "Merits":
            # Skip paragraphs already flagged for R2 (operative sub-clauses)
            if rowid in relabels:
                continue
            # Trigger A: Art.41 sub-heading at start
            # Trigger B: canonical Art.41 quote anywhere in text
            triggered = (R3_SUBHEADING_RE.match(text)
                       or R3_ART41_QUOTE_RE.search(text))
            if triggered:
                relabels[rowid] = "Just Satisfaction"
                active = True
                counts["R3_direct"] += 1
                continue
            # Already in propagation mode
            if active:
                relabels[rowid] = "Just Satisfaction"
                counts["R3_continuation"] += 1
                continue

        # Existing Just Satisfaction → enter mode (don't relabel)
        if sec == "Just Satisfaction":
            active = True
            continue

        # Anything else (including Admissibility) — end propagation
        if sec != "Merits":
            active = False

print(f"  R3 direct triggers:       {counts['R3_direct']:,}")
print(f"  R3 continuations:         {counts['R3_continuation']:,}")

# Summary
print(f"\nTotal relabels: {len(relabels):,}")
print(f"  R1 (JS → Op.Part):                 {counts['R1']:,}")
print(f"  R2 (Merits → Op.Part):             {counts['R2']:,}")
print(f"  R3 (Merits → JS, direct):          {counts['R3_direct']:,}")
print(f"  R3 (Merits → JS, propagation):     {counts['R3_continuation']:,}")

# Distribution check
if relabels:
    rowid_list = list(relabels.keys())
    by_target = {}
    BATCH = 9000
    for start in range(0, len(rowid_list), BATCH):
        batch = rowid_list[start:start+BATCH]
        cur.execute(
            "SELECT rowid, section FROM paragraphs WHERE rowid IN ({})".format(
                ",".join(str(r) for r in batch)
            )
        )
        for r in cur.fetchall():
            old = r["section"]
            new = relabels[r["rowid"]]
            key = f"{old} → {new}"
            by_target.setdefault(key, 0)
            by_target[key] += 1
    print("\nDistribution:")
    for k, v in sorted(by_target.items(), key=lambda x: -x[1]):
        print(f"  {v:>7,}  {k}")

# Spot checks: 2 examples per rule
print("\n── SPOT CHECKS ──")
for rule_name, predicate in [
    ("R1 (JS dispositif → Op.Part)",
     lambda rid: relabels.get(rid) == "Operative Part" and rid not in []),
    ("R3 (Merits Art.41 → JS)",
     lambda rid: relabels.get(rid) == "Just Satisfaction"),
]:
    print(f"\n  {rule_name}:")
    shown = 0
    for rid in relabels:
        if predicate(rid):
            cur.execute("SELECT case_id, section, substr(text,1,140) FROM paragraphs WHERE rowid=?", (rid,))
            r = cur.fetchone()
            print(f"    rowid={rid} [{r['section']}] → {relabels[rid]}")
            print(f"      text: {r[2]}")
            shown += 1
            if shown >= 2:
                break

if DRY_RUN:
    print("\nDRY-RUN — no changes written.")
    conn.close()
    sys.exit(0)

# APPLY
print("\nAPPLYING...")
cur.execute("DROP TABLE IF EXISTS _p8_backup")
cur.execute(f"""
    CREATE TABLE _p8_backup AS
    SELECT rowid, section FROM paragraphs
    WHERE rowid IN ({','.join(str(r) for r in relabels.keys())})
""")
print(f"Backup _p8_backup: {cur.execute('SELECT COUNT(*) FROM _p8_backup').fetchone()[0]:,} rows")

# Group by target
by_t = {}
for rid, tgt in relabels.items():
    by_t.setdefault(tgt, []).append(rid)

conn.execute("BEGIN")
total = 0
for tgt, rowids in by_t.items():
    BATCH = 9000
    for start in range(0, len(rowids), BATCH):
        batch = rowids[start:start+BATCH]
        conn.execute(
            f"UPDATE paragraphs SET section = ? WHERE rowid IN ({','.join(str(r) for r in batch)})",
            (tgt,)
        )
        total += len(batch)
conn.commit()
print(f"COMMITTED. {total:,} paragraphs relabeled.")
conn.close()
print("DONE.")
