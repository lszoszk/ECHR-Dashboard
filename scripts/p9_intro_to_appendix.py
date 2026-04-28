"""
P9 RELABEL: move applicant-table paragraphs from Introduction → Appendix.

Targets only Population C "mass cases" (Pop C + ≥10 paragraphs in
Introduction = ~3,290 cases). Within those, applies a conservative
deterministic rule with 95.3% audited precision (Sonnet 4.6 audit
on 500 stratified samples).

Rules (combined with OR; any match → relabel):
  R1 — exact column header match (e.g. "Applicant's name", "Year of birth")
  R2 — footnote marker (^\[\d+\]$)
  R3 — application-number pattern (\d{4,5}/\d{2}) AND length < 150

Recall: ~31.9% of true applicant_table paragraphs (the easy ones).
Precision: ~95.3% on audited sample.
Estimated scope: ~32,000 paragraphs moved (out of 132,544 in mass cases).

Usage:
  python p9_intro_to_appendix.py            # dry-run
  python p9_intro_to_appendix.py --apply    # commit
"""
import sqlite3
import sys
import re

DRY_RUN = "--apply" not in sys.argv
DB = "/data/echr_search.db"

COL_HEADERS = {
    "Applicant", "Applicant's name", "Applicant name",
    "Year of birth", "Date of birth", "Place of residence",
    "Representative", "Representative's name",
    "Facility", "Start and end date", "Duration",
    "Sq. m per inmate", "Specific grievances",
    "Amount awarded", "(in euros)", "Annex",
    "Total length", "Levels of jurisdiction",
    "Start of proceedings", "End of proceedings",
    "Other complaints under well-established case-law",
}

COL_HEADER_PREFIXES = (
    "Applicant's name", "Applicant name",
    "Applicant 1", "Applicant 2", "Applicant 3", "Applicant 4",
    "Applicant 5", "Applicant 6", "Applicant 7", "Applicant 8",
    "Applicant 9", "Applicant 10",
)

FOOTNOTE_RE = re.compile(r"^\s*\[\d+\]\s*$")
APP_NUM_RE = re.compile(r"\d{4,5}/\d{2}\b")

# Citation markers — when present, the app-number is from a case citation,
# not a table row. Spot check showed paragraphs like:
#   "46. The Government referred to the arguments... in the case of Figas v.
#    Poland (no. 7883/07, §§ 41-44, 23 June 2009)."
# These should NOT be moved.
CITATION_MARKERS = re.compile(
    r"(see |the case of |\(dec\.\)|ECHR \d{4}|§+\s*\d|cited above|"
    r"Court reiterates|, no\. \d|, no\.\s|§ \d|judgment of \d)",
    re.IGNORECASE,
)
# Also exclude paragraphs that look like citation continuations
# (start with comma, no., bracket etc — typical of citation fragments)
CITATION_START_RE = re.compile(r"^\s*[,)]\s*(no\.|\()", re.IGNORECASE)

def is_table_paragraph(text):
    """Return (matches, rule_name)."""
    if not text:
        return False, ""
    t = text.strip()
    # R1a: exact column-header match
    if t in COL_HEADERS:
        return True, "col_header_exact"
    # R1b: column header prefix
    for h in COL_HEADER_PREFIXES:
        if t == h or t.startswith(h + " ") or t.startswith(h + ":") or t.startswith(h + ".") or t.startswith(h + "\n"):
            return True, "col_header_prefix"
    # R2: footnote marker
    if FOOTNOTE_RE.match(t):
        return True, "footnote"
    # R3: application-number pattern + tight length + no citation markers
    if (len(t) < 100
        and APP_NUM_RE.search(t)
        and not CITATION_MARKERS.search(t)
        and not CITATION_START_RE.match(t)):
        return True, "app_number"
    return False, ""

if DRY_RUN:
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
else:
    conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# Identify mass cases
cur.execute("""
    SELECT case_id FROM paragraphs
    WHERE para_idx IS NULL AND section = 'Introduction'
    GROUP BY case_id HAVING COUNT(*) >= 10
""")
mass_case_ids = {r[0] for r in cur.fetchall()}
print(f"Mass cases (Pop C, ≥10 Intro paras): {len(mass_case_ids):,}")

# Pull all candidate paragraphs
ph = ",".join("?" * len(mass_case_ids))
cur.execute(f"""
    SELECT rowid, text FROM paragraphs
    WHERE para_idx IS NULL AND section = 'Introduction'
      AND case_id IN ({ph})
""", list(mass_case_ids))

relabels = []  # (rowid, rule_name)
rule_counts = {}
for r in cur.fetchall():
    matched, rule = is_table_paragraph(r["text"])
    if matched:
        relabels.append((r["rowid"], rule))
        rule_counts[rule] = rule_counts.get(rule, 0) + 1

print(f"\nTotal paragraphs flagged: {len(relabels):,}")
print("Per-rule breakdown:")
for rule, n in sorted(rule_counts.items(), key=lambda x: -x[1]):
    print(f"  {rule}: {n:,}")

# Spot check — show 3 examples per rule
print("\n── Spot check: 2 examples per rule ──")
seen_per_rule = {r: 0 for r in rule_counts}
for rid, rule in relabels:
    if seen_per_rule[rule] >= 2:
        continue
    cur.execute("SELECT case_id, substr(text, 1, 140) FROM paragraphs WHERE rowid = ?", (rid,))
    case_id, txt = cur.fetchone()
    print(f"  [{rule}] case={case_id} rowid={rid}")
    print(f"    text: {txt}")
    seen_per_rule[rule] += 1

# Current Appendix count for context
cur.execute("SELECT COUNT(*) FROM paragraphs WHERE section = 'Appendix'")
old_app = cur.fetchone()[0]
cur.execute("SELECT COUNT(*) FROM paragraphs WHERE section = 'Introduction'")
old_intro = cur.fetchone()[0]
print(f"\nCurrent: Introduction={old_intro:,}, Appendix={old_app:,}")
print(f"After P9: Introduction={old_intro - len(relabels):,}, Appendix={old_app + len(relabels):,}")

if DRY_RUN:
    print("\nDRY-RUN — no changes written.")
    conn.close()
    sys.exit(0)

# APPLY
print("\nAPPLYING...")
cur.execute("DROP TABLE IF EXISTS _p9_backup")
rowid_list = [r[0] for r in relabels]
cur.execute(f"""
    CREATE TABLE _p9_backup AS
    SELECT rowid, section FROM paragraphs
    WHERE rowid IN ({','.join(str(r) for r in rowid_list)})
""")
print(f"Backup _p9_backup: {cur.execute('SELECT COUNT(*) FROM _p9_backup').fetchone()[0]:,} rows")

BATCH = 9000
conn.execute("BEGIN")
total = 0
for start in range(0, len(rowid_list), BATCH):
    batch = rowid_list[start:start+BATCH]
    conn.execute(
        f"UPDATE paragraphs SET section = 'Appendix' WHERE rowid IN ({','.join(str(r) for r in batch)})"
    )
    total += len(batch)
conn.commit()
print(f"COMMITTED. {total:,} paragraphs relabeled to Appendix.")

cur.execute("SELECT COUNT(*) FROM paragraphs WHERE section = 'Appendix'")
print(f"Appendix total now: {cur.fetchone()[0]:,}")
conn.close()
print("DONE.")
