"""
P12 EXTRACT: assign numbering_block to each paragraph.

Discovered during expert manual review M3/M4 (2026-04-28). HUDOC has
multiple independent numbering schemes within a single judgment:

  - Main judgment body:        paragraphs 1, 2, 3, ..., N
  - Operative Part dispositif: numbered ruling clauses 1, 2, 3, ...
  - Each Separate Opinion:     restarts numbering at 1, 2, 3, ...

Without context, "paragraph 1" is ambiguous. P12 adds a `numbering_block`
column to disambiguate:

  Value                        Meaning
  ─────────────────────────    ──────────────────────────────────────
  main_judgment                Paragraphs 1..N of the body (Intro through
                                Article 46, including Merits etc.)
  operative_dispositif         Numbered clauses in Operative Part /
                                Operative part section
  separate_opinion_N           Paragraph M within the Nth separate
                                opinion of the case (multiple opinions
                                per case are common — up to 10)
  NULL                         Header, Appendix, or other no-clear-
                                numbering paragraphs

Usage:
  python p12_extract.py            # dry-run with stats
  python p12_extract.py --apply    # add column + populate
"""
import sqlite3
import sys
import re

DRY_RUN = "--apply" not in sys.argv
DB = "/data/echr_search.db"

# Body sections — these are part of "main_judgment" numbering scheme
BODY_SECTIONS = frozenset([
    "Introduction", "Facts Background", "Facts Proceedings", "Facts",
    "Legal Framework", "Relevant legal framework", "Legal Context",
    "Commission Proceedings", "Final Submissions",
    "Admissibility", "Merits", "Just Satisfaction", "Article 46",
])
OPERATIVE_SECTIONS = frozenset(["Operative Part", "Operative part"])
SEPARATE_OPINION_SECTION = "Separate Opinion"
# Header and Appendix have no numbering scheme

# Opinion title at paragraph start — a NEW separate opinion begins.
# Allows an optional bracketed footnote marker between the keyword and OPINION
# (e.g., "DISSENTING [] OPINION OF JUDGE X" — PDF extraction artefact).
OPINION_TITLE_RE = re.compile(
    r"^\s*"
    r"(?:JOINT\s+)?"
    r"(?:PARTLY\s+|PARTIALLY\s+)?"
    r"(?:DISSENTING|CONCURRING|SEPARATE)\s*"
    r"(?:\[[^\]]{0,30}\]\s*)?"   # optional [] or [N] footnote marker
    r"(?:AND\s+(?:DISSENTING|CONCURRING|PARTLY\s+DISSENTING|PARTLY\s+CONCURRING)\s+)?"
    r"OPINION\s+OF\s+",
    re.IGNORECASE,
)

if DRY_RUN:
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
else:
    conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# Walk all cases, assign numbering_block to each paragraph
print("Walking all cases...")
cur.execute("SELECT DISTINCT case_id FROM paragraphs ORDER BY case_id")
case_ids = [r[0] for r in cur.fetchall()]
print(f"  {len(case_ids):,} cases to process")

assignments = {}  # rowid -> numbering_block string
stats = {
    "main_judgment": 0,
    "operative_dispositif": 0,
    "separate_opinion": 0,  # any sep_op_N
    "null": 0,
}
opinion_counter_dist = []

cur2 = conn.cursor()
for i, case_id in enumerate(case_ids):
    if i % 5000 == 0 and i > 0:
        print(f"  ... {i:,} / {len(case_ids):,}")
    cur2.execute("""
        SELECT rowid, para_idx, section, text
        FROM paragraphs WHERE case_id = ?
        ORDER BY COALESCE(para_idx, rowid)
    """, (case_id,))
    paras = cur2.fetchall()

    # Within Separate Opinion section, count opinions
    opinion_n = 0  # 0 means we haven't seen the first opinion title yet

    for p in paras:
        sec = p["section"]
        text = p["text"] or ""
        rowid = p["rowid"]

        if sec in BODY_SECTIONS:
            assignments[rowid] = "main_judgment"
            stats["main_judgment"] += 1
            opinion_n = 0  # reset (we left Separate Opinion section if we were in it)
        elif sec in OPERATIVE_SECTIONS:
            assignments[rowid] = "operative_dispositif"
            stats["operative_dispositif"] += 1
            opinion_n = 0
        elif sec == SEPARATE_OPINION_SECTION:
            # Did this paragraph start a new opinion?
            if OPINION_TITLE_RE.match(text):
                opinion_n += 1
            if opinion_n == 0:
                # We're in Separate Opinion section but haven't seen a title yet.
                # Treat it as opinion 1 (graceful fallback for cases where the
                # title was glued or absent).
                opinion_n = 1
            assignments[rowid] = f"separate_opinion_{opinion_n}"
            stats["separate_opinion"] += 1
        else:
            # Header, Appendix, or unknown section → NULL
            stats["null"] += 1
            opinion_n = 0
            # Don't add to assignments — leave NULL

    if opinion_n > 0:
        opinion_counter_dist.append(opinion_n)

print(f"\n=== Assignment summary ===")
print(f"  main_judgment:        {stats['main_judgment']:>10,}")
print(f"  operative_dispositif: {stats['operative_dispositif']:>10,}")
print(f"  separate_opinion_N:   {stats['separate_opinion']:>10,}")
print(f"  NULL (Header/Appendix): {stats['null']:>10,}")
print(f"  TOTAL assigned:       {len(assignments):>10,}")

# Distribution of opinions per case
from collections import Counter
opinion_dist = Counter(opinion_counter_dist)
print(f"\n=== Separate-opinion count distribution ({len(opinion_counter_dist):,} cases with opinions) ===")
for n in sorted(opinion_dist.keys())[:12]:
    print(f"  {n} opinion(s) per case: {opinion_dist[n]:,} cases")

# Spot check: case with multiple opinions
print("\n=== SPOT CHECK: Matznetter v. Austria (multiple opinions) ===")
cur.execute("""
    SELECT rowid, para_idx, section, hudoc_para_no, substr(text, 1, 80) AS t
    FROM paragraphs WHERE case_id = '001-57537' AND para_idx BETWEEN 60 AND 90
    ORDER BY para_idx
""")
for p in cur.fetchall():
    h = p["hudoc_para_no"] if p["hudoc_para_no"] is not None else "—"
    block = assignments.get(p["rowid"], "NULL")
    print(f"  ¶{p['para_idx']:>4} hudoc={str(h):<5} block={block:<20} [{p['section']:<22}] {p['t']}")

if DRY_RUN:
    print("\nDRY-RUN — no changes written. Run with --apply to commit.")
    conn.close()
    sys.exit(0)

# === APPLY ===
print("\nAPPLYING...")
print("Adding numbering_block column...")
try:
    cur.execute("ALTER TABLE paragraphs ADD COLUMN numbering_block TEXT")
    conn.commit()
    print("  Column added.")
except sqlite3.OperationalError as e:
    if "duplicate column" in str(e).lower():
        print("  Column already exists, continuing.")
    else:
        raise

print(f"Populating {len(assignments):,} rows...")
BATCH = 5000
items = list(assignments.items())
done = 0
conn.execute("BEGIN")
for start in range(0, len(items), BATCH):
    batch = items[start:start+BATCH]
    conn.executemany(
        "UPDATE paragraphs SET numbering_block = ? WHERE rowid = ?",
        [(blk, rid) for rid, blk in batch]
    )
    done += len(batch)
    if done % 200000 == 0:
        print(f"  ... {done:,} / {len(items):,}")
conn.commit()
print(f"  done. {done:,} updates committed.")

# Verify
cur.execute("SELECT numbering_block, COUNT(*) FROM paragraphs GROUP BY numbering_block ORDER BY 2 DESC LIMIT 15")
print("\n  Final distribution:")
for r in cur.fetchall():
    print(f"    {r[0] or 'NULL':<25} {r[1]:>10,}")

conn.close()
print("\nDONE.")
