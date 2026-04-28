"""
P4 VALIDATION (read-only): segment Population C cases (committee/joined).

Population C = paragraphs with para_idx IS NULL.
These cases have ALL content lumped into a few unordered buckets:
  - Introduction (often = applicant list in joined cases)
  - Facts (often contains ALLEGED VIOLATION = merits content)
  - Merits (sometimes legitimate)
  - Operative part

This script measures:
  1. How many cases are Population C
  2. Heading patterns visible inside their text (boundary signals)
  3. What fraction of paragraphs could be re-bucketed by heading detection
"""
import sqlite3
import re
from collections import Counter, defaultdict

DB = "/data/echr_search.db"
conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# Count Population C cases
cur.execute("""
    SELECT COUNT(DISTINCT case_id), COUNT(*)
    FROM paragraphs WHERE para_idx IS NULL
""")
pop_c_cases, pop_c_paras = cur.fetchone()
print(f"Population C: {pop_c_cases:,} cases, {pop_c_paras:,} paragraphs")

# Section distribution within Population C
print("\nSection distribution (Population C only):")
cur.execute("""
    SELECT section, COUNT(*) as n, COUNT(DISTINCT case_id) as cases
    FROM paragraphs WHERE para_idx IS NULL
    GROUP BY section ORDER BY n DESC
""")
for r in cur.fetchall():
    print(f"  {r['section']:<28} {r['n']:>7,} paras  ({r['cases']:,} cases)")

# Heading-pattern detection within each section
print("\n── Boundary-signal headings inside Population C paragraphs ──")
print("(short paragraphs <120 chars matching known section-header patterns)")

PATTERNS = [
    ("INTRODUCTION", "INTRODUCTION"),
    ("PROCEDURE", "PROCEDURE"),
    ("THE FACTS", "THE FACTS"),
    ("THE LAW", "THE LAW"),
    ("ALLEGED VIOLATION", "%ALLEGED VIOLATION%"),
    ("APPLICATION OF ARTICLE 41", "%APPLICATION OF ARTICLE 41%"),
    ("RELEVANT LEGAL FRAMEWORK", "%RELEVANT LEGAL FRAMEWORK%"),
    ("RELEVANT DOMESTIC LAW", "%RELEVANT DOMESTIC LAW%"),
    ("JOINDER OF THE APPLICATIONS", "%JOINDER OF THE APPLICATIONS%"),
    ("FOR THESE REASONS", "%FOR THESE REASONS%"),
    ("Decides", "Decides"),
    ("Declares", "Declares"),
    ("Holds", "Holds"),
    ("Applicant's name", "Applicant's name"),
    ("THE CIRCUMSTANCES", "%CIRCUMSTANCES%"),
]

for label, pattern in PATTERNS:
    cur.execute("""
        SELECT section, COUNT(*) as n
        FROM paragraphs
        WHERE para_idx IS NULL
          AND length(text) < 120
          AND UPPER(text) LIKE UPPER(?)
        GROUP BY section ORDER BY n DESC
    """, (pattern,))
    rows = cur.fetchall()
    if rows:
        total = sum(r["n"] for r in rows)
        breakdown = ", ".join(f"{r['section']}: {r['n']}" for r in rows)
        print(f"  '{label}' ({total} matches): {breakdown}")

# Per-case structure of Population C
print("\n── Sample Population C cases (5 random) ──")
cur.execute("""
    SELECT DISTINCT a.case_id, c.title
    FROM paragraphs a JOIN cases c ON c.case_id=a.case_id
    WHERE a.para_idx IS NULL
    ORDER BY RANDOM() LIMIT 5
""")
samples = cur.fetchall()
cur2 = conn.cursor()
for s in samples:
    print(f"\n  [{s['case_id']}] {(s['title'] or '')[:60]}")
    cur2.execute("""
        SELECT section, substr(text,1,80) as t, length(text) as L
        FROM paragraphs WHERE case_id=? AND para_idx IS NULL
        LIMIT 12
    """, (s["case_id"],))
    for p in cur2.fetchall():
        print(f"    [{p['section']:<24}] ({p['L']} chars) {p['t']}")

# Estimate boundary-detectable fraction
print("\n── Fraction of paragraphs that COULD be re-bucketed via heading detection ──")
# Build a single big SQL counting paragraphs that contain ANY known major heading
HEADING_KEYWORDS = [
    "INTRODUCTION", "PROCEDURE", "THE FACTS", "THE LAW",
    "ALLEGED VIOLATION", "APPLICATION OF ARTICLE",
    "RELEVANT LEGAL FRAMEWORK", "RELEVANT DOMESTIC LAW",
    "JOINDER OF THE APPLICATIONS", "FOR THESE REASONS",
    "DISSENTING OPINION", "CONCURRING OPINION",
]
where = " OR ".join(f"UPPER(text) LIKE '%{k}%'" for k in HEADING_KEYWORDS)
cur.execute(f"""
    SELECT COUNT(*) as headings,
           COUNT(DISTINCT case_id) as cases
    FROM paragraphs
    WHERE para_idx IS NULL
      AND length(text) < 120
      AND ({where})
""")
r = cur.fetchone()
print(f"  Heading paragraphs (signals):   {r['headings']:,}")
print(f"  Cases with ≥1 heading signal:   {r['cases']:,} / {pop_c_cases:,}")
print(f"  Avg signals per case:           {r['headings']/max(r['cases'],1):.1f}")

conn.close()
print("\nDONE.")
